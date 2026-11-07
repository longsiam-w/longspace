"""Small relay readiness check. Default: isolated local subprocess, never production.
Remote read-only: python check_relay.py --url https://your-host
Remote 2-message test: use dedicated idle test identities via environment; --send required.
No load tests, no password collection, no TLS bypass, no token output.
"""
import argparse, json, os, secrets, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parent

def local_worker(phase):
    data=Path(os.environ.get('HUB_DATA','')).resolve()
    if os.environ.get('HUB_RELAY_CHECK_ISOLATED')!='1' or not (data/'.relay-check-only').is_file():
        raise ValueError('Worker requires an isolated temporary check directory; run without --worker')
    from fastapi.testclient import TestClient
    import server as s
    if phase=='restart':
        with TestClient(s.app) as c:
            row=s.DB.execute("SELECT * FROM queue WHERE recipient='probe-b'").fetchone()
            assert row and json.loads(s.decrypt(row['payload'],row['id'].encode()))=={'probe':'restart'},'Restart persistence failed'
            retry=c.post('/api/messages',headers={'Authorization':'Bearer local-probe-token-a'},json={'recipient':'probe-b','body':{'probe':'restart'},'clientMessageId':'restart-key'}).json()
            assert retry['id']==row['id'] and retry['duplicate'],'Restart idempotency failed'
            with s.DB: s.DB.execute('DELETE FROM queue')
        print('PASS fresh process: encrypted unacknowledged message survives restart');return
    with TestClient(s.app) as c:
        a,b='local-probe-token-a','local-probe-token-b'
        with s.DB:
            for cid,token in [('probe-a',a),('probe-b',b)]:
                s.DB.execute('INSERT INTO clients VALUES(?,?,?,?)',(cid,cid,s.digest(token),time.time()))
        ha={'Authorization':'Bearer '+a};hb={'Authorization':'Bearer '+b}
        def send(value):
            r=c.post('/api/messages',headers=ha,json={'recipient':'probe-b','body':value,**({'clientMessageId':'restart-key'} if value=={'probe':'restart'} else {})});assert r.status_code==200,r.text;return r.json()['id']
        assert c.get('/api/messages').status_code==401
        mid=send({'probe':'offline'})
        for _ in range(2):
            batch=c.get('/api/messages',headers=hb).json()['messages'];assert [m['id'] for m in batch]==[mid]
        c.post('/api/messages/'+mid+'/ack',headers=ha)
        assert len(c.get('/api/messages',headers=hb).json()['messages'])==1
        with c.websocket_connect('/api/ws') as ws:
            ws.send_json({'type':'auth','token':b});assert ws.receive_json()['messages'][0]['id']==mid
            ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
        with c.websocket_connect('/api/ws') as ws:
            ws.send_json({'type':'auth','token':b});assert ws.receive_json()['messages'][0]['id']==mid
            ws.send_json({'type':'ack','id':mid});ws.send_json({'type':'ping'});assert ws.receive_json()['type']=='pong'
            assert c.get('/api/messages',headers=hb).json()['messages']==[]
            live=send({'probe':'online'});assert ws.receive_json()['messages'][0]['id']==live
            assert c.post('/api/messages/'+live+'/ack',headers=hb).status_code==200
            assert c.post('/api/messages/'+live+'/ack',headers=hb).status_code==200
        reverse=c.post('/api/messages',headers=hb,json={'recipient':'probe-a','body':{'probe':'reverse'}}).json()['id']
        assert c.get('/api/messages',headers=ha).json()['messages'][0]['id']==reverse
        c.post('/api/messages/'+reverse+'/ack',headers=ha)
        from starlette.websockets import WebSocketDisconnect
        with c.websocket_connect('/api/ws') as ws:
            ws.send_json({'token':'invalid'})
            try: ws.receive_json();raise AssertionError('Invalid token accepted')
            except WebSocketDisconnect as e: assert e.code==4003
        with c.websocket_connect('/api/ws') as ws:
            ws.send_json({'token':b});ws.receive_json();ws.send_json([])
            try: ws.receive_json();raise AssertionError('Malformed frame accepted')
            except WebSocketDisconnect as e: assert e.code==1008
        final=send({'probe':'restart'})
        stored=s.DB.execute('SELECT payload FROM queue WHERE id=?',(final,)).fetchone()[0]
        assert b'restart' not in stored
    print('PASS local: unauthorized rejection, offline/redelivery, reconnect, live WS, heartbeat, recipient-only/idempotent ACK, bidirectional, malformed frame, encrypted storage')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect refused: use the final trusted HTTPS origin directly')

def request(base,path,token=None,body=None):
    headers={'Accept':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    if body is not None: headers['Content-Type']='application/json'
    req=Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    with build_opener(NoRedirect).open(req,timeout=12) as response: return json.load(response)


def remote(args):
    parsed=urlsplit(args.url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('--url must be an HTTPS origin without credentials, path, query or fragment')
    base=args.url.rstrip('/');health=request(base,'/api/health');assert health.get('ok') is True
    mapping=request(base,'/api/software');assert isinstance(mapping.get('software'),list)
    print('PASS HTTPS health + software registry; this alone does NOT prove end-to-end relay availability')
    if not args.send:return
    a=os.environ.get('HUB_CHECK_A_TOKEN');b=os.environ.get('HUB_CHECK_B_TOKEN');aid=os.environ.get('HUB_CHECK_A_ID');bid=os.environ.get('HUB_CHECK_B_ID')
    if not all([a,b,aid,bid]) or aid==bid:raise ValueError('Set distinct dedicated HUB_CHECK_A_ID/A_TOKEN and HUB_CHECK_B_ID/B_TOKEN')
    for token in (a,b):
        if request(base,'/api/messages',token)['messages']:raise ValueError('Dedicated test queues must be empty; no messages have been sent')
    marker=secrets.token_hex(8);sent=[]
    try:
        for sender,recipient,token,receiver in [(aid,bid,a,b),(bid,aid,b,a)]:
            result=request(base,'/api/messages',token,{'recipient':recipient,'body':{'kind':'availability-check','nonce':marker}})
            if result.get('evicted'):raise RuntimeError('Queue eviction observed: stop using non-idle identities')
            mid=result['id'];sent.append((mid,receiver));messages=request(base,'/api/messages',receiver)['messages']
            item=next((m for m in messages if m['id']==mid),None)
            assert item and item['sender']==sender and item['recipient']==recipient and item['body'].get('nonce')==marker
            request(base,'/api/messages/'+mid+'/ack',receiver,{})
            request(base,'/api/messages/'+mid+'/ack',receiver,{})
            assert not any(m['id']==mid for m in request(base,'/api/messages',receiver)['messages'])
        print('PASS HTTP bidirectional relay + payload + idempotent ACK; exactly 2 small messages; remote WebSocket/restart NOT tested')
    finally:
        for mid,receiver in sent:
            try:request(base,'/api/messages/'+mid+'/ack',receiver,{})
            except Exception:print('WARN one test ACK failed; inspect the dedicated test queues')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',help='HTTPS origin; read-only unless --send')
    parser.add_argument('--send',action='store_true',help='Opt-in 2-message test, dedicated idle identities only')
    parser.add_argument('--worker',choices=['initial','restart'],help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:local_worker(args.worker);return
    if args.url:remote(args);return
    if args.send:raise ValueError('--send requires --url')
    with tempfile.TemporaryDirectory(prefix='hub-relay-check-') as tmp:
        (Path(tmp)/'.relay-check-only').write_text('isolated local relay check',encoding='utf-8')
        env=os.environ.copy();env['HUB_DATA']=tmp;env['HUB_ORIGIN']='http://testserver';env['HUB_RELAY_CHECK_ISOLATED']='1'
        for phase in ['initial','restart']:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',phase],cwd=ROOT,env=env,check=True,timeout=40)
    print('PASS local relay readiness (4 tiny messages total). No production requests, no load test.')

if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:
        # Do not expose HTTP headers, tokens or response bodies on failure.
        print('FAIL:',type(e).__name__,str(e) if isinstance(e,(ValueError,AssertionError)) else 'check did not complete; verify connectivity/dependencies/service logs',file=sys.stderr)
        sys.exit(1)
