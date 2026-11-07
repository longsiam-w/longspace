"""Tiny isolated business envelope checks; no production or screenshots."""
import os,tempfile,unittest
from datetime import datetime,timezone
TMP=tempfile.TemporaryDirectory();os.environ['HUB_DATA']=TMP.name;os.environ['HUB_ORIGIN']='http://testserver'
from fastapi.testclient import TestClient
import server as s
from integration.business_protocol import validate_business

def body(kind='data'):
    value={'protocol':'longs-app','version':1,'kind':kind,'name':'notes.import-image','operationId':'small-001','issuedAt':'2026-11-07T08:00:00Z','payload':{}}
    if kind=='command':value['expiresAt']='2026-11-07T08:05:00Z'
    if kind=='result':value['status']='succeeded'
    return value

class ProtocolTests(unittest.TestCase):
    def test_shapes(self):
        for kind in ['data','event','command','result']:self.assertEqual(validate_business(body(kind))['kind'],kind)
        for patch in [{'kind':'shell'},{'version':True},{'payload':[]},{'issuedAt':'bad'},{'name':'RUN SHELL'},{'extra':1}]:
            with self.assertRaises(ValueError):validate_business({**body(),**patch})
        with self.assertRaises(ValueError):validate_business({**body(),'kind':'command'})
        failure={**body('result'),'status':'failed','error':{'code':'FAILED','message':'local test','retryable':False}}
        validate_business(failure)
        with self.assertRaises(ValueError):validate_business(body('command'),check_expiry=True,now=datetime(2026,11,7,9,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):validate_business(body('command'),sender='untrusted',allowed_senders=['pc'])
    def test_api(self):
        with TestClient(s.app) as c:
            with s.DB:
                for cid in ['a','b']:s.DB.execute('INSERT INTO clients VALUES(?,?,?,?)',(cid,cid,s.digest('local-'+cid),0))
            headers={'Authorization':'Bearer local-a'}
            invalid=c.post('/api/messages',headers=headers,json={'recipient':'b','body':{**body(),'kind':'invalid'}});self.assertEqual(invalid.status_code,400)
            self.assertEqual(s.DB.execute('SELECT COUNT(*) FROM queue').fetchone()[0],0)
            for i,kind in enumerate(['data','event','command','result']):
                result=c.post('/api/messages',headers=headers,json={'recipient':'b','clientMessageId':'test-'+str(i),'body':body(kind)});self.assertEqual(result.status_code,200,result.text)
            old=c.post('/api/messages',headers=headers,json={'recipient':'b','body':{'legacy':True}});self.assertEqual(old.status_code,200)
            messages=c.get('/api/messages',headers={'Authorization':'Bearer local-b'}).json()['messages']
            self.assertEqual([m['body']['kind'] for m in messages[:4]],['data','event','command','result'])
            for path in ['/integration/business_protocol.py','/integration/business-protocol.mjs']:
                self.assertEqual(c.get(path).status_code,200)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:TMP.cleanup()
