"""Isolated tiny attachment checks, no production/load tests."""
import os,tempfile,hashlib,time,unittest
TMP=tempfile.TemporaryDirectory();os.environ['HUB_DATA']=TMP.name;os.environ['HUB_ORIGIN']='http://testserver';os.environ['HUB_ATTACHMENT_MAX_BYTES']='64';os.environ['HUB_ATTACHMENT_QUOTA_BYTES']='96'
from fastapi.testclient import TestClient
import server as s
class AttachmentTests(unittest.TestCase):
    def test_lifecycle(self):
        with TestClient(s.app) as c:
            with s.DB:
                for cid in ['a','b','c']:s.DB.execute('INSERT INTO clients VALUES(?,?,?,?)',(cid,cid,s.digest('test-'+cid),0))
                salt='aa'*16;s.DB.execute('INSERT INTO settings VALUES(?,?)',('salt',salt));s.DB.execute('INSERT INTO settings VALUES(?,?)',('password',s.password_hash('local-test',salt)))
            c.post('/api/login',json={'password':'local-test'})
            auth=lambda cid:{'Authorization':'Bearer test-'+cid}
            data=b'tiny-private-picture';sha=hashlib.sha256(data).hexdigest()
            def upload(key='one',content=data,digest=None):return c.put('/api/attachments',params={'recipient':'b','name':'截图.png','uploadKey':key,'sha256':digest or hashlib.sha256(content).hexdigest()},headers={**auth('a'),'Content-Type':'image/png'},content=content)
            self.assertEqual(c.put('/api/attachments',params={'recipient':'b','name':'x','uploadKey':'x','sha256':sha},content=data).status_code,401)
            first=upload();self.assertEqual(first.status_code,200,first.text);asset=first.json();aid=asset['id'];path=s.DATA/'.file'/aid
            self.assertTrue(path.exists());self.assertNotIn(data,path.read_bytes())
            self.assertEqual(c.get('/api/files').json()['files'],[])
            self.assertEqual(upload().json()['id'],aid)
            self.assertEqual(upload(content=b'other').status_code,409)
            self.assertEqual(c.get('/api/attachments/'+aid,headers=auth('c')).status_code,404)
            self.assertEqual(c.get('/api/attachments/'+aid+'/download',headers=auth('a')).status_code,403)
            result=c.get('/api/attachments/'+aid+'/download',headers=auth('b'));self.assertEqual(result.content,data)
            self.assertTrue(path.exists(),'GET must not delete before explicit integrity confirmation')
            self.assertEqual(c.post('/api/attachments/'+aid+'/complete',headers=auth('b'),json={'size':0,'sha256':sha}).status_code,400)
            self.assertEqual(c.post('/api/attachments/'+aid+'/complete',headers=auth('a'),json={'size':len(data),'sha256':sha}).status_code,403)
            for _ in range(2):self.assertEqual(c.post('/api/attachments/'+aid+'/complete',headers=auth('b'),json={'size':len(data),'sha256':sha}).status_code,200)
            self.assertFalse(path.exists());self.assertEqual(c.get('/api/attachments/'+aid+'/download',headers=auth('b')).status_code,410)
            self.assertEqual(upload().json()['state'],'deleted')
            self.assertEqual(upload('too-big',b'x'*65).status_code,413)
            self.assertEqual(upload('bad-hash',digest='0'*64).status_code,400)
            self.assertEqual(list((s.DATA/'.file').glob('*.part')),[])
            exp=upload('expire').json()
            with s.DB:s.DB.execute('UPDATE attachments SET expires=? WHERE id=?',(time.time()-1,exp['id']))
            s.attachment_cleanup();self.assertFalse((s.DATA/'.file'/exp['id']).exists())
            canceled=upload('cancel').json();self.assertEqual(c.delete('/api/attachments/'+canceled['id'],headers=auth('a')).status_code,200)
            revoked=upload('revoke').json();c.delete('/api/admin/software/b');self.assertFalse((s.DATA/'.file'/revoked['id']).exists())
            self.assertEqual(c.get('/assets/.file').status_code,404)
            self.assertEqual(list((s.DATA/'.file').iterdir()),[])
if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:TMP.cleanup()
