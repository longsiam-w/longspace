import os, tempfile, unittest, json
TMP = tempfile.TemporaryDirectory(); os.environ['HUB_DATA']=TMP.name
os.environ['HUB_ORIGIN']='http://testserver'
from fastapi.testclient import TestClient
import server as s

class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        salt='ab'*16
        with s.DB:
            s.DB.execute('INSERT INTO settings VALUES(?,?)',('salt',salt))
            s.DB.execute('INSERT INTO settings VALUES(?,?)',('password',s.password_hash('test-private-password',salt)))
        cls.c=TestClient(s.app); cls.c.__enter__()
        assert cls.c.post('/api/login',json={'password':'test-private-password'}).status_code==200
    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None,None,None)
        TMP.cleanup()
    def register(self,name): return self.c.post('/api/admin/software',json={'name':name}).json()
    def hdr(self,a): return {'Authorization':'Bearer '+a['token']}
    def test_01_auth(self):
        c=TestClient(s.app)
        self.assertEqual(c.get('/api/files').status_code,401)
        self.assertEqual(c.post('/api/messages',json={}).status_code,401)
        self.assertEqual(self.c.post('/api/folders',json={'path':'x'},headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.c.post('/api/login',json={'password':'wrong'}).status_code,401)
    def test_02_drive(self):
        self.assertEqual(self.c.post('/api/folders',json={'path':'docs'}).status_code,200)
        payload=(b'super-secret-contents'*100000)+os.urandom(300)
        r=self.c.put('/api/files',params={'path':'docs/文件.bin'},content=payload)
        self.assertEqual(r.status_code,200,r.text); fid=r.json()['id']
        self.assertNotIn(b'super-secret-contents',(s.BLOBS/fid).read_bytes())
        self.assertEqual(self.c.get(f'/api/files/{fid}/download').content,payload)
        self.assertEqual(self.c.put('/api/files',params={'path':'docs/文件.bin'},content=b'x').status_code,409)
        self.assertEqual(self.c.put('/api/files',params={'path':'../bad'},content=b'x').status_code,400)
        self.assertEqual(self.c.put('/api/files',params={'path':'missing/file'},content=b'x').status_code,400)
        folder=next(f for f in self.c.get('/api/files').json()['files'] if f['path']=='docs')
        self.assertEqual(self.c.delete('/api/files/'+folder['id']).status_code,409)
        self.assertEqual(self.c.delete('/api/files/'+fid).status_code,200)
        self.assertEqual(self.c.delete('/api/files/'+folder['id']).status_code,200)
        empty=self.c.put('/api/files',params={'path':'empty'},content=b'').json()
        self.assertEqual(self.c.get('/api/files/'+empty['id']+'/download').content,b'')
    def test_02_folders_move_zip(self):
        import io, zipfile
        self.assertEqual(self.c.post('/api/folders/ensure',json={'paths':['pack/sub/empty','pack','pack/sub','target']}).status_code,200)
        f=self.c.put('/api/files',params={'path':'pack/sub/你好.html'},content=b'<h1>hello</h1>').json()
        listing=lambda: self.c.get('/api/files').json()['files']
        root=next(x for x in listing() if x['path']=='pack')
        self.assertEqual(self.c.post('/api/files/move',json={'ids':[root['id']], 'destination':'pack/sub'}).status_code,400)
        moved=self.c.post('/api/files/move',json={'ids':[root['id'],f['id']], 'destination':'target'})
        self.assertEqual(moved.status_code,200,moved.text)
        self.assertTrue(any(x['path']=='target/pack/sub/你好.html' for x in listing()))
        result=self.c.get('/api/folders/'+root['id']+'/download')
        self.assertEqual(result.status_code,200)
        with zipfile.ZipFile(io.BytesIO(result.content)) as z:
            self.assertEqual(z.read('pack/sub/你好.html'),b'<h1>hello</h1>')
            self.assertIn('pack/sub/empty/',z.namelist())
            self.assertIsNone(z.testzip())
        self.c.post('/api/folders',json={'path':'pack'})
        self.assertEqual(self.c.post('/api/files/move',json={'ids':[root['id']], 'destination':''}).status_code,409)
        self.assertTrue(any(x['path']=='target/pack/sub/你好.html' for x in listing()))
        self.assertEqual(self.c.post('/api/folders/ensure',json={'paths':['../escape']}).status_code,400)
        self.assertEqual(self.c.post('/api/files/move',json={'ids':[f['id']], 'destination':None}).status_code,400)
    def test_03_queue_and_ack(self):
        a=self.register('sender'); b=self.register('recipient'); ha=self.hdr(a); hb=self.hdr(b)
        ids=[]
        for i in range(10):
            r=self.c.post('/api/messages',json={'recipient':b['id'],'body':{'i':i,'secret':'NOT_ON_DISK'}},headers=ha)
            self.assertEqual(r.status_code,200,r.text); ids.append(r.json()['id'])
        rejected=self.c.post('/api/messages',json={'recipient':b['id'],'body':'overflow'},headers=ha)
        self.assertEqual(rejected.status_code,409)
        messages=self.c.get('/api/messages',headers=hb).json()['messages']
        self.assertEqual([m['body']['i'] for m in messages],list(range(10)))
        self.assertNotIn(b'NOT_ON_DISK',s.DB.execute('SELECT payload FROM queue WHERE id=?',(ids[-1],)).fetchone()[0])
        self.c.post('/api/messages/'+ids[-1]+'/ack',headers=ha)
        self.assertEqual(len(self.c.get('/api/messages',headers=hb).json()['messages']),10)
        self.c.post('/api/messages/'+ids[-1]+'/ack',headers=hb)
        self.assertEqual(len(self.c.get('/api/messages',headers=hb).json()['messages']),9)
        self.assertEqual(self.c.post('/api/messages',json={'sender':b['id'],'recipient':b['id'],'body':1},headers=ha).status_code,403)
        self.assertEqual(self.c.post('/api/messages',json={'recipient':a['id'],'body':'reverse'},headers=hb).status_code,200)
        self.assertEqual(len(self.c.get('/api/messages',headers=ha).json()['messages']),1)
    def test_03b_reliable_send(self):
        a=self.register('idempotent-a');b=self.register('idempotent-b');ha=self.hdr(a);hb=self.hdr(b)
        body={'recipient':b['id'],'body':{'operationId':'small-test','value':1},'clientMessageId':'request-one'}
        first=self.c.post('/api/messages',headers=ha,json=body).json()
        again=self.c.post('/api/messages',headers=ha,json=body).json()
        self.assertEqual(first['id'],again['id']);self.assertTrue(again['duplicate'])
        self.assertEqual(len(self.c.get('/api/messages',headers=hb).json()['messages']),1)
        conflict=self.c.post('/api/messages',headers=ha,json={**body,'body':2});self.assertEqual(conflict.status_code,409)
        self.c.post('/api/messages/'+first['id']+'/ack',headers=ha)
        self.assertEqual(self.c.post('/api/messages',headers=ha,json=body).json()['state'],'queued')
        self.c.post('/api/messages/'+first['id']+'/ack',headers=hb)
        acknowledged=self.c.post('/api/messages',headers=ha,json=body).json()
        self.assertEqual(acknowledged['state'],'acked');self.assertFalse(acknowledged['queued'])
        self.assertEqual(self.c.get('/api/messages',headers=hb).json()['messages'],[])
        # Local business write survives restart before ACK, and rollback permits safe replay.
        from integration.reliable_receiver import DurableInbox
        path=os.path.join(TMP.name,'consumer.sqlite3');msg={'id':first['id'],'recipient':b['id'],'sender':a['id'],'body':1}
        inbox=DurableInbox(path);self.assertTrue(inbox.process(msg));inbox.close()
        inbox=DurableInbox(path);self.assertFalse(inbox.process(msg))
        self.assertEqual(inbox.db.execute('SELECT COUNT(*) FROM business_inbox').fetchone()[0],1)
        def failure(db,message):
            db.execute('INSERT INTO business_inbox VALUES(?,?,?,?)',(message['recipient'],message['id'],message['sender'],'rollback'))
            raise ValueError('simulated business failure')
        bad={**msg,'id':'rollback-message'}
        with self.assertRaises(ValueError):inbox.process(bad,failure)
        self.assertTrue(inbox.process(bad));inbox.close()
        # Simulate an online push that remains blocked; HTTP send must already have returned.
        import asyncio, threading
        started=threading.Event();release=threading.Event();original=s.flush
        async def blocked(cid):
            started.set()
            while not release.is_set():await asyncio.sleep(.01)
        s.flush=blocked;s.SOCKETS[b['id']]=object()
        try:
            response=self.c.post('/api/messages',headers=ha,json={**body,'clientMessageId':'slow-push'})
            self.assertEqual(response.status_code,200);self.assertTrue(started.wait(2))
            self.assertEqual(len(self.c.get('/api/messages',headers=hb).json()['messages']),1)
        finally:
            release.set();s.SOCKETS.pop(b['id'],None);s.flush=original

    def test_04_websocket(self):
        a=self.register('ws-sender'); b=self.register('ws-recipient'); ha=self.hdr(a); hb=self.hdr(b)
        first=self.c.post('/api/messages',json={'recipient':b['id'],'body':'offline'},headers=ha).json()
        with self.c.websocket_connect('/api/ws') as ws:
            ws.send_json({'type':'auth','token':b['token']})
            batch=ws.receive_json()['messages']; self.assertEqual(batch[0]['body'],'offline')
            ws.send_json({'type':'ack','id':first['id']})
            ws.send_json({'type':'ping'}); self.assertEqual(ws.receive_json()['type'],'pong')
            self.assertEqual(self.c.get('/api/messages',headers=hb).json()['messages'],[])
            self.c.post('/api/messages',json={'recipient':b['id'],'body':'live'},headers=ha)
            self.assertEqual(ws.receive_json()['messages'][0]['body'],'live')
    def test_04b_token_rotation(self):
        a=self.register('rotation');b=self.register('rotation-sender');ha=self.hdr(a)
        self.c.post('/api/messages',headers=self.hdr(b),json={'recipient':a['id'],'body':'preserve pending'})
        dashboard=self.c.get('/api/admin/dashboard').json()
        entry=next(x for x in dashboard['software'] if x['id']==a['id'])
        self.assertEqual(entry['token_suffix'],a['token'][-3:]);self.assertNotIn(a['token'],json.dumps(dashboard))
        self.assertNotIn('token_suffix',json.dumps(self.c.get('/api/software').json()))
        anonymous=TestClient(s.app)
        self.assertEqual(anonymous.post('/api/admin/software/'+a['id']+'/token').status_code,401)
        with self.c.websocket_connect('/api/ws') as ws:
            ws.send_json({'token':a['token']});ws.receive_json()
            changed=self.c.post('/api/admin/software/'+a['id']+'/token').json()
            from starlette.websockets import WebSocketDisconnect
            with self.assertRaises(WebSocketDisconnect) as closed: ws.receive_json()
            self.assertEqual(closed.exception.code,4003)
        self.assertNotEqual(changed['token'],a['token']);self.assertEqual(changed['id'],a['id'])
        self.assertEqual(self.c.get('/api/messages',headers=ha).status_code,401)
        fresh={'Authorization':'Bearer '+changed['token']}
        self.assertEqual(len(self.c.get('/api/messages',headers=fresh).json()['messages']),1)
        entry=next(x for x in self.c.get('/api/admin/dashboard').json()['software'] if x['id']==a['id'])
        self.assertEqual(entry['token_suffix'],changed['token'][-3:])
        self.c.delete('/api/admin/software/'+a['id'])
        self.assertEqual(self.c.get('/api/messages',headers=fresh).status_code,401)
        self.assertIsNone(s.DB.execute('SELECT 1 FROM client_token_hints WHERE client_id=?',(a['id'],)).fetchone())

    def test_05_revocation_and_security(self):
        a=self.register('<script>alert(1)</script>')
        self.assertEqual(self.c.get('/api/software').status_code,200)
        self.assertEqual(self.c.delete('/api/admin/software/'+a['id']).status_code,200)
        self.assertEqual(self.c.get('/api/messages',headers=self.hdr(a)).status_code,401)
        self.assertEqual(self.c.get('/assets/server.py').status_code,404)
        self.assertIn('frame-ancestors',self.c.get('/').headers['content-security-policy'])
        self.assertEqual(self.c.post('/api/messages',content=b'x'*65537,headers=self.hdr(self.register('large'))).status_code,413)

if __name__=='__main__': unittest.main(verbosity=2)
