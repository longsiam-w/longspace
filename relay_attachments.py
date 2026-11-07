"""Private ephemeral attachments; no entries in drive files table, no public paths."""
import asyncio, hashlib, json, os, re, secrets, struct, time, uuid
from pathlib import Path
from urllib.parse import quote
from fastapi import Request
from fastapi.responses import StreamingResponse

def install(app, h):
    store=h.DATA/'.file';store.mkdir(exist_ok=True);store.chmod(0o700)
    maximum=int(os.environ.get('HUB_ATTACHMENT_MAX_BYTES',h.MAX_FILE))
    quota=int(os.environ.get('HUB_ATTACHMENT_QUOTA_BYTES',min(h.QUOTA,2*1024**3)))
    ttl=int(os.environ.get('HUB_ATTACHMENT_TTL_SECONDS',86400))
    if maximum<=0 or quota<=0 or not 60<=ttl<=7*86400:raise ValueError('Invalid attachment limits')
    h.DB.executescript('''CREATE TABLE IF NOT EXISTS attachments(
      id TEXT PRIMARY KEY,sender TEXT NOT NULL,recipient TEXT NOT NULL,upload_key TEXT NOT NULL,
      name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,
      created REAL NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL,UNIQUE(sender,upload_key));
      CREATE INDEX IF NOT EXISTS attachments_expiry ON attachments(expires);''');h.DB.commit()
    active=set();downloads={};reserved=0;active_keys=set()
    def clean_files(aid):
        for suffix in ('','.part'):
            try:(store/(aid+suffix)).unlink(missing_ok=True)
            except OSError:h.event('attachment_cleanup_error')
    def erase(aid):
        # Tombstone first: a failed unlink remains visible to maintenance for retry.
        with h.DB:h.DB.execute("UPDATE attachments SET state='deleted' WHERE id=?",(aid,))
        clean_files(aid)
    def cleanup():
        now=time.time()
        for row in h.DB.execute("SELECT * FROM attachments WHERE expires<? OR state='deleted'",(now,)).fetchall():
            if not downloads.get(row['id']) and row['id'] not in active:erase(row['id'])
        with h.DB:h.DB.execute("DELETE FROM attachments WHERE state='deleted' AND expires<?",(now-7*86400,))
        known={r['id'] for r in h.DB.execute('SELECT id FROM attachments')}
        for path in store.iterdir():
            aid=path.name.removesuffix('.part')
            if re.fullmatch('[0-9a-f]{32}',aid) and aid not in known and aid not in active:clean_files(aid)
    h.attachment_cleanup=cleanup
    def metadata(row):return {k:row[k] for k in ('id','sender','recipient','name','mime','size','sha256','created','expires','state')}
    def get(aid,who):
        row=h.DB.execute('SELECT * FROM attachments WHERE id=?',(aid,)).fetchone()
        if not row or who['id'] not in (row['sender'],row['recipient']):h.err(404,'附件不存在')
        return row
    def ready(row):
        if row['state']!='ready' or row['expires']<=time.time():h.err(410,'附件已删除或过期')

    @app.put('/api/attachments')
    async def upload(request: Request,recipient: str,name: str,uploadKey: str,sha256: str):
        nonlocal reserved
        who=h.client(request)
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',uploadKey):h.err(400,'非法uploadKey')
        if not re.fullmatch('[0-9a-f]{64}',sha256):h.err(400,'需要小写SHA256')
        if not name or len(name)>240 or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):h.err(400,'非法附件名称')
        if not h.DB.execute('SELECT 1 FROM clients WHERE id=?',(recipient,)).fetchone():h.err(404,'接收软件不存在')
        mime=request.headers.get('content-type','application/octet-stream').split(';')[0].strip()
        if not re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+',mime):h.err(400,'非法Content-Type')
        key=(who['id'],uploadKey)
        old=h.DB.execute('SELECT * FROM attachments WHERE sender=? AND upload_key=?',key).fetchone()
        if old:
            if (old['recipient'],old['name'],old['mime'],old['sha256'])!=(recipient,name,mime,sha256):h.err(409,'uploadKey已用于不同附件')
            if old['state']=='ready' and old['expires']<=time.time():
                erase(old['id']);old=h.DB.execute('SELECT * FROM attachments WHERE id=?',(old['id'],)).fetchone()
            return {**metadata(old),'duplicate':True}
        if key in active_keys:h.err(409,'该附件正在上传')
        if len(active)>=2:h.err(429,'附件上传忙，请稍后重试')
        cleanup();aid=uuid.uuid4().hex;active.add(aid);active_keys.add(key);total=0;index=0;hasher=hashlib.sha256()
        try:
            with (store/(aid+'.part')).open('xb') as f:
                f.write(b'HAT1')
                async for chunk in request.stream():
                    for offset in range(0,len(chunk),1024*1024):
                        part=chunk[offset:offset+1024*1024]
                        used=h.DB.execute("SELECT COALESCE(SUM(size),0) FROM attachments WHERE state='ready'").fetchone()[0]
                        if total+len(part)>maximum or used+reserved+len(part)>quota:h.err(413,'附件大小或临时空间配额超限')
                        total+=len(part);reserved+=len(part);hasher.update(part)
                        encrypted=h.encrypt(part,f'attachment:{aid}:{index}'.encode());index+=1
                        f.write(struct.pack('>I',len(encrypted)));f.write(encrypted)
                if hasher.hexdigest()!=sha256:h.err(400,'附件SHA256不匹配')
                footer=h.encrypt(struct.pack('>QQ',index,total),f'attachment:{aid}:end'.encode())
                f.write(struct.pack('>I',0));f.write(footer);f.flush();os.fsync(f.fileno())
            # Recheck rotation/revocation and recipient after awaiting request stream.
            h.client(request)
            if not h.DB.execute('SELECT 1 FROM clients WHERE id=?',(recipient,)).fetchone():h.err(404,'接收软件已删除')
            (store/(aid+'.part')).replace(store/aid)
            now=time.time()
            with h.DB:h.DB.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,who['id'],recipient,uploadKey,name,mime,total,sha256,now,now+ttl,'ready'))
            return {**metadata(h.DB.execute('SELECT * FROM attachments WHERE id=?',(aid,)).fetchone()),'duplicate':False}
        except BaseException:
            clean_files(aid);raise
        finally:reserved-=total;active.discard(aid);active_keys.discard(key)

    @app.get('/api/attachments/{aid}')
    async def info(aid: str,request: Request):return metadata(get(aid,h.client(request)))

    @app.get('/api/attachments/{aid}/download')
    async def download(aid: str,request: Request):
        who=h.client(request);row=dict(get(aid,who));ready(row)
        if row['recipient']!=who['id']:h.err(403,'仅指定接收方可下载')
        if downloads.get(aid):h.err(409,'附件已有下载进行中')
        downloads[aid]=1
        async def stream():
            try:
                with (store/aid).open('rb') as f:
                    if f.read(4)!=b'HAT1':raise ValueError('Invalid attachment header')
                    index=0;total=0;sha=hashlib.sha256()
                    while True:
                        raw=f.read(4)
                        if len(raw)!=4:raise ValueError('Truncated attachment')
                        size=struct.unpack('>I',raw)[0]
                        if size==0:
                            final=h.decrypt(f.read(44),f'attachment:{aid}:end'.encode())
                            if struct.unpack('>QQ',final)!=(index,total) or total!=row['size'] or sha.hexdigest()!=row['sha256'] or f.read(1):raise ValueError('Invalid attachment footer')
                            break
                        if not 28<=size<=1024*1024+28:raise ValueError('Invalid attachment chunk')
                        data=h.decrypt(f.read(size),f'attachment:{aid}:{index}'.encode());index+=1;total+=len(data);sha.update(data)
                        yield data
                        await asyncio.sleep(0)
            finally:downloads.pop(aid,None)
        return StreamingResponse(stream(),media_type='application/octet-stream',headers={'Content-Length':str(row['size']),'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['name'],safe=''),'X-Attachment-SHA256':row['sha256']})

    @app.post('/api/attachments/{aid}/complete')
    async def complete(aid: str,request: Request):
        who=h.client(request);row=get(aid,who)
        if row['recipient']!=who['id']:h.err(403,'仅接收方可确认')
        try:body=json.loads(await h.limited_body(request,1024))
        except (ValueError,TypeError):h.err(400,'非法确认')
        if not isinstance(body,dict) or body.get('sha256')!=row['sha256'] or type(body.get('size')) is not int or body['size']!=row['size']:h.err(400,'确认大小/哈希不匹配')
        if downloads.get(aid):h.err(409,'下载尚在进行，请稍后确认')
        erase(aid);return {'ok':True,'deleted':True}

    @app.delete('/api/attachments/{aid}')
    async def cancel(aid: str,request: Request):
        who=h.client(request);row=get(aid,who)
        if who['id']!=row['sender']:h.err(403,'仅发送方可取消')
        if downloads.get(aid):h.err(409,'接收方正在下载')
        erase(aid);return {'ok':True,'deleted':True}

    def revoke(cid):
        for row in h.DB.execute('SELECT id FROM attachments WHERE sender=? OR recipient=?',(cid,cid)).fetchall():erase(row['id'])
    h.revoke_attachments=revoke
    cleanup()
