"""Private Hub: encrypted drive + bounded, acknowledged relay."""
import asyncio, base64, hashlib, hmac, json, os, secrets, sqlite3, struct, time, uuid
from collections import Counter, deque
from contextlib import asynccontextmanager, suppress
from pathlib import Path, PurePosixPath
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from integration.business_protocol import validate_business

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('HUB_DATA', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
BLOBS = DATA / 'blobs'; BLOBS.mkdir(exist_ok=True)
KEYFILE = DATA / 'master.key'
if not KEYFILE.exists():
    with KEYFILE.open('xb') as f: f.write(secrets.token_bytes(32))
    KEYFILE.chmod(0o600)
KEY = KEYFILE.read_bytes()
CIPHER = AESGCM(KEY)
DB = sqlite3.connect(DATA / 'hub.sqlite3', check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.executescript('''
PRAGMA journal_mode=WAL;
PRAGMA secure_delete=ON;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS client_token_hints(client_id TEXT PRIMARY KEY,suffix TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,size INTEGER NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS queue(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,sender TEXT NOT NULL,recipient TEXT NOT NULL,payload BLOB NOT NULL,created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS queue_recipient ON queue(recipient,seq);
CREATE TABLE IF NOT EXISTS relay_receipts(sender TEXT NOT NULL,client_id TEXT NOT NULL,recipient TEXT NOT NULL,message_id TEXT NOT NULL,fingerprint TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(sender,client_id));
CREATE INDEX IF NOT EXISTS relay_receipts_message ON relay_receipts(message_id);
CREATE INDEX IF NOT EXISTS relay_receipts_created ON relay_receipts(created);
''')
DB.commit()
MAX_FILE = int(os.environ.get('HUB_MAX_FILE_BYTES', 1024**3))
QUOTA = int(os.environ.get('HUB_QUOTA_BYTES', 20 * 1024**3))
PUBLIC_ORIGIN = os.environ.get('HUB_ORIGIN', '')
SESSIONS = {}; SOCKETS = {}; LOCKS = {}; EVENTS = deque(maxlen=100); COUNTS = Counter()
START = time.time(); UPLOADING = set(); RESERVED = 0
RECEIPT_TTL = 7 * 86400
PUSH_PENDING = set(); PUSH_TASKS = set(); PUSH_WAKE = asyncio.Event()
PUSH_WORKERS = 2
ONLINE_TTL = 75
HTTP_ACTIVITY = {}; WS_ACTIVITY = {}; RELAY_MINUTES = {}

def online_ids():
    now = time.monotonic()
    registered = {r[0] for r in DB.execute("SELECT id FROM clients")}
    for cid, seen in list(HTTP_ACTIVITY.items()):
        if cid not in registered or now-seen >= ONLINE_TTL: HTTP_ACTIVITY.pop(cid, None)
    return sorted(cid for cid in registered if cid in HTTP_ACTIVITY or
                  (cid in SOCKETS and now-WS_ACTIVITY.get(cid, float("-inf")) < ONLINE_TTL))

def relay_throughput():
    minute = int(time.time()//60)
    for old in list(RELAY_MINUTES):
        if old < minute-119: RELAY_MINUTES.pop(old, None)
    return {"windowSeconds":7200,"bucketSeconds":60,"buckets":[
        {"start":m*60,"count":RELAY_MINUTES.get(m,0)} for m in range(minute-119,minute+1)]}

def notify_recipient(cid):
    # Coalesce per recipient; offline messages are read on the next connection.
    if cid in SOCKETS:
        PUSH_PENDING.add(cid); PUSH_WAKE.set()

async def push_worker():
    while True:
        await PUSH_WAKE.wait()
        if not PUSH_PENDING:
            PUSH_WAKE.clear(); continue
        cid = PUSH_PENDING.pop()
        if not PUSH_PENDING: PUSH_WAKE.clear()
        try: await asyncio.wait_for(flush(cid), 12)
        except Exception: event('push_error', recipient=cid)

def acknowledge(cid, mid):
    with DB:
        n = DB.execute('DELETE FROM queue WHERE id=? AND recipient=?', (mid,cid)).rowcount
        if n: DB.execute("UPDATE relay_receipts SET state='acked',created=? WHERE message_id=? AND recipient=?", (time.time(),mid,cid))
    if n: event('ack', id=mid, recipient=cid)
    return bool(n)

def setting(k):
    r = DB.execute('SELECT v FROM settings WHERE k=?', (k,)).fetchone()
    return r['v'] if r else None

def digest(token): return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password, salt): return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
def admin_password(password):
    salt = setting('salt'); expected = setting('password')
    return bool(salt and expected and hmac.compare_digest(password_hash(password, salt), expected))
def encrypt(data, aad):
    nonce = secrets.token_bytes(12)
    return nonce + CIPHER.encrypt(nonce, data, aad)
def decrypt(data, aad): return CIPHER.decrypt(data[:12], data[12:], aad)
def err(code, text): raise HTTPException(code, text)
async def limited_body(request, maximum):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum: err(413, '请求体过大')
        data.extend(chunk)
    return bytes(data)
def origin_ok(origin): return not origin or bool(PUBLIC_ORIGIN and origin == PUBLIC_ORIGIN)
def session(request):
    token = request.cookies.get('hub_session', '')
    expiry = SESSIONS.get(digest(token), 0)
    if expiry < time.time(): err(401, '请先登录')

def client_auth(token):
    row = DB.execute('SELECT id,name FROM clients WHERE token_hash=?', (digest(token),)).fetchone()
    if not row: err(401, '无效的软件凭据')
    return dict(row)
def client(request):
    who = client_auth(request.headers.get('authorization', '').removeprefix('Bearer '))
    HTTP_ACTIVITY[who['id']] = time.monotonic()
    return who
def clean_path(value):
    if not isinstance(value, str) or '\\' in value or '\x00' in value or len(value) > 1024: err(400, '非法路径')
    value = value.strip('/')
    if not value or any(x in ('', '.', '..') or len(x) > 240 or any(ord(c) < 32 for c in x) for x in value.split('/')): err(400, '非法路径')
    return value

def parent_exists(path):
    p = str(PurePosixPath(path).parent)
    if p != '.' and not DB.execute("SELECT 1 FROM files WHERE path=? AND kind='folder'", (p,)).fetchone(): err(400, '父文件夹不存在')
def event(kind, **kw):
    now = time.time()
    for field in ('sender', 'recipient'):
        if field in kw:
            row = DB.execute('SELECT name FROM clients WHERE id=?', (kw[field],)).fetchone()
            kw[field+'Name'] = row['name'] if row else '已注销软件'
    EVENTS.appendleft({'time': now, 'kind': kind, **kw}); COUNTS[kind] += 1
    if kind == 'relay':
        relay_throughput()
        minute = int(now//60)
        RELAY_MINUTES[minute] = RELAY_MINUTES.get(minute, 0)+1

def pending(cid):
    result = []
    for r in DB.execute('SELECT * FROM queue WHERE recipient=? ORDER BY seq', (cid,)).fetchall():
        result.append({'type': 'message', 'id': r['id'], 'sender': r['sender'], 'recipient': cid, 'body': json.loads(decrypt(r['payload'], r['id'].encode())), 'created': r['created']})
    return result

async def flush(cid):
    lock = LOCKS.setdefault(cid, asyncio.Lock())
    async with lock:
        ws = SOCKETS.get(cid)
        if ws:
            try:
                await asyncio.wait_for(ws.send_json({'type': 'sync', 'messages': pending(cid)}), 10)
            except Exception:
                event('push_error', recipient=cid)
                if SOCKETS.get(cid) is ws:
                    SOCKETS.pop(cid, None); WS_ACTIVITY.pop(cid, None)
                try: await asyncio.wait_for(ws.close(code=1011), 1)
                except Exception: pass

@asynccontextmanager
async def lifespan(app):
    async def maintenance():
        while True:
            await asyncio.sleep(60)
            try:
                with DB: DB.execute("DELETE FROM relay_receipts WHERE state='acked' AND created<?", (time.time()-RECEIPT_TTL,))
                attachment_cleanup()
                DB.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.Error: event('maintenance_error')
    task = asyncio.create_task(maintenance())
    PUSH_PENDING.clear(); PUSH_WAKE.clear()
    for _ in range(PUSH_WORKERS): PUSH_TASKS.add(asyncio.create_task(push_worker()))
    try:
        yield
    finally:
        task.cancel()
        for worker in PUSH_TASKS: worker.cancel()
        for worker in [task, *PUSH_TASKS]:
            with suppress(asyncio.CancelledError): await worker
        PUSH_TASKS.clear(); PUSH_PENDING.clear()
        DB.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        DB.close()

app = FastAPI(title='Private Hub API', version='1.0.0', lifespan=lifespan, docs_url=None, openapi_url='/api/openapi.json', redoc_url=None)

@app.middleware('http')
async def security(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not origin_ok(request.headers.get('origin')):
        return JSONResponse({'detail': '跨站请求已拒绝'}, status_code=403)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    return response

ATTEMPTS = {}
@app.post('/api/login')
async def login(request: Request):
    ip = request.client.host
    now = time.time(); recent = [t for t in ATTEMPTS.get(ip, []) if t > now - 300]
    if len(recent) >= 10: err(429, '尝试过多，请五分钟后重试')
    ATTEMPTS[ip] = recent + [now]
    if not setting('password'): err(503, '请在服务器执行 python manage.py init')
    raw = await limited_body(request, 4096)
    try: password = json.loads(raw).get('password', '')
    except Exception: err(400, '无效 JSON')
    if not isinstance(password, str) or len(password) > 1024 or not admin_password(password): err(401, '密码错误')
    for key, expiry in list(SESSIONS.items()):
        if expiry < now: SESSIONS.pop(key, None)
    if len(SESSIONS) > 100: SESSIONS.clear()
    token = secrets.token_urlsafe(32); SESSIONS[digest(token)] = now + 12 * 3600
    response = JSONResponse({'ok': True})
    response.set_cookie('hub_session', token, httponly=True, secure=PUBLIC_ORIGIN.startswith('https://'), samesite='strict', max_age=43200)
    return response

@app.post('/api/logout')
async def logout(request: Request):
    SESSIONS.pop(digest(request.cookies.get('hub_session', '')), None)
    r = JSONResponse({'ok': True}); r.delete_cookie('hub_session'); return r

@app.get('/api/me')
async def me(request: Request): session(request); return {'role': 'admin'}

@app.get('/api/health')
async def health(): return {'ok': True, 'configured': bool(setting('password'))}

def software_data():
    return {'software': [dict(r) for r in DB.execute('SELECT id,name FROM clients ORDER BY id')], 'version': setting('registry_version') or '0'}

@app.get('/api/software')
async def software(): return software_data()

@app.get('/api/software/me')
async def software_identity(request: Request):
    """Resolve this software's identity from its Bearer token, not an admin cookie."""
    return client(request)

@app.post('/api/admin/software')
async def register(request: Request):
    session(request)
    raw = await limited_body(request, 4096)
    try: body = json.loads(raw)
    except Exception: err(400, '无效 JSON')
    if not isinstance(body, dict): err(400, '无效 JSON 对象')
    name = body.get('name', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: err(400, '软件名称长度应为 1–80')
    cid = uuid.uuid4().hex[:12]; token = secrets.token_urlsafe(36)
    with DB:
        DB.execute('INSERT INTO clients VALUES(?,?,?,?)', (cid, name.strip(), digest(token), time.time()))
        DB.execute('INSERT INTO client_token_hints VALUES(?,?)', (cid,token[-3:]))
        DB.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('registry_version', str(time.time_ns())))
    return {'id': cid, 'name': name.strip(), 'token': token, 'warning': '凭据仅返回一次，请安全保存'}

@app.post('/api/admin/software/{cid}/token')
async def rotate_token(cid: str, request: Request):
    session(request)
    token = secrets.token_urlsafe(36)
    with DB:
        if not DB.execute('UPDATE clients SET token_hash=? WHERE id=?', (digest(token),cid)).rowcount:
            err(404, '软件不存在，请刷新列表')
        DB.execute('INSERT OR REPLACE INTO client_token_hints VALUES(?,?)', (cid,token[-3:]))
    # Detach before awaiting close: old sockets cannot continue ACKing or receiving.
    ws = SOCKETS.pop(cid, None)
    HTTP_ACTIVITY.pop(cid, None); WS_ACTIVITY.pop(cid, None)
    PUSH_PENDING.discard(cid)
    if ws:
        try: await asyncio.wait_for(ws.close(code=4003, reason='Token已重新分配'), 2)
        except Exception: pass
    return {'id':cid,'token':token,'warning':'旧token已失效，新token仅返回一次'}

@app.delete('/api/admin/software/{cid}')
async def revoke(cid: str, request: Request):
    session(request)
    with DB:
        DB.execute('DELETE FROM clients WHERE id=?', (cid,))
        DB.execute('DELETE FROM client_token_hints WHERE client_id=?', (cid,))
        SEND_RATES.pop(cid, None)
        PUSH_PENDING.discard(cid)
        DB.execute('DELETE FROM relay_receipts WHERE sender=? OR recipient=?', (cid,cid))
        DB.execute('DELETE FROM queue WHERE sender=? OR recipient=?', (cid,cid))
        DB.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('registry_version', str(time.time_ns())))
    revoke_attachments(cid)
    ws = SOCKETS.pop(cid, None)
    HTTP_ACTIVITY.pop(cid, None); WS_ACTIVITY.pop(cid, None)
    if ws:
        try: await asyncio.wait_for(ws.close(code=4003), 2)
        except Exception: pass
    return {'ok': True}

@app.get('/api/files')
async def files(request: Request):
    session(request)
    return {'files': [dict(r) for r in DB.execute('SELECT * FROM files ORDER BY kind DESC,path')], 'quota': QUOTA, 'maxFile': MAX_FILE, 'used': DB.execute('SELECT COALESCE(SUM(size),0) FROM files').fetchone()[0]}

@app.post('/api/folders')
async def folder(request: Request):
    session(request)
    raw = await limited_body(request, 4096)
    try: path = clean_path(json.loads(raw)['path'])
    except (ValueError, KeyError, TypeError): err(400, '无效请求')
    parent_exists(path)
    try:
        with DB: DB.execute('INSERT INTO files VALUES(?,?,?,?,?)', (uuid.uuid4().hex, path, 'folder', 0, time.time()))
    except sqlite3.IntegrityError: err(409, '同名条目已存在')
    return {'ok': True}

@app.put('/api/files')
async def upload(request: Request, path: str):
    global RESERVED
    session(request); path = clean_path(path); parent_exists(path)
    if path in UPLOADING or DB.execute('SELECT 1 FROM files WHERE path=?', (path,)).fetchone(): err(409, '同名条目已存在')
    UPLOADING.add(path)
    fid = uuid.uuid4().hex; blob = BLOBS / fid; total = 0
    try:
        with blob.open('xb') as f:
            f.write(b'HUB1')
            index = 0
            async for chunk in request.stream():
                for offset in range(0, len(chunk), 1024 * 1024):
                    part = chunk[offset:offset + 1024 * 1024]
                    if not part: continue
                    used = DB.execute('SELECT COALESCE(SUM(size),0) FROM files').fetchone()[0]
                    if total + len(part) > MAX_FILE or used + RESERVED + len(part) > QUOTA: err(413, '超出单文件大小或空间配额')
                    total += len(part); RESERVED += len(part)
                    encrypted = encrypt(part, f'{fid}:{index}'.encode())
                    f.write(struct.pack('>I', len(encrypted))); f.write(encrypted); index += 1
            # Authenticated footer detects truncation, including empty files.
            footer = encrypt(struct.pack('>QQ', index, total), f'{fid}:end'.encode())
            f.write(struct.pack('>I', 0)); f.write(footer)
            f.flush(); os.fsync(f.fileno())
        parent_exists(path)
        with DB: DB.execute('INSERT INTO files VALUES(?,?,?,?,?)', (fid, path, 'file', total, time.time()))
        event('upload', bytes=total)
    except BaseException:
        blob.unlink(missing_ok=True)
        raise
    finally:
        RESERVED -= total; UPLOADING.discard(path)
    return {'id': fid, 'path': path, 'size': total}

def decrypted_chunks(r):
    fid = r['id']
    with (BLOBS / fid).open('rb') as f:
        if f.read(4) != b'HUB1': raise ValueError('invalid header')
        index = 0; total = 0
        while True:
            length = struct.unpack('>I', f.read(4))[0]
            if length == 0:
                footer = decrypt(f.read(44), f'{fid}:end'.encode())
                if struct.unpack('>QQ', footer) != (index, total) or total != r['size'] or f.read(1): raise ValueError('invalid footer')
                break
            if not 28 <= length <= 1024 * 1024 + 28: raise ValueError('invalid chunk')
            data = decrypt(f.read(length), f'{fid}:{index}'.encode())
            index += 1; total += len(data)
            yield data

@app.post('/api/folders/ensure')
async def ensure_folders(request: Request):
    session(request)
    try:
        body = json.loads(await limited_body(request, 2 * 1024 * 1024))
        paths = body['paths']
        if not isinstance(paths, list) or not 1 <= len(paths) <= 1000: err(400, '每次最多创建 1000 个目录')
        paths = sorted(set(clean_path(p) for p in paths), key=lambda p: (p.count('/'), p))
    except (ValueError, TypeError, KeyError): err(400, '无效目录列表')
    with DB:
        for path in paths:
            existing = DB.execute('SELECT kind FROM files WHERE path=?', (path,)).fetchone()
            if existing:
                if existing['kind'] != 'folder': err(409, '同名文件阻止创建目录：' + path)
                continue
            parent_exists(path)
            DB.execute('INSERT INTO files VALUES(?,?,?,?,?)', (uuid.uuid4().hex, path, 'folder', 0, time.time()))
    return {'ok': True}

@app.post('/api/files/move')
async def move_files(request: Request):
    session(request)
    try:
        body = json.loads(await limited_body(request, 65536))
        ids = body['ids']; destination = body['destination']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or any(not isinstance(i, str) for i in ids): err(400, '请选择 1–1000 个条目')
        if destination != '': destination = clean_path(destination)
    except (ValueError, TypeError, KeyError): err(400, '无效移动请求')
    rows = [dict(r) for r in DB.execute('SELECT * FROM files')]
    by_id = {r['id']: r for r in rows}
    if any(i not in by_id for i in ids): err(404, '所选条目已不存在，请刷新')
    if destination and not any(r['path'] == destination and r['kind'] == 'folder' for r in rows): err(404, '目标文件夹不存在')
    roots = [by_id[i] for i in set(ids)]
    roots = [r for r in roots if not any(r['path'].startswith(p['path'] + '/') for p in roots if p['kind'] == 'folder' and p['id'] != r['id'])]
    changes = {}
    for root in roots:
        path = root['path']
        if destination == path or destination.startswith(path + '/'): err(400, '不能移动到自身或子文件夹')
        new = (destination + '/' if destination else '') + path.rsplit('/', 1)[-1]
        if new == path: continue
        for r in rows:
            if r['id'] == root['id'] or (root['kind'] == 'folder' and r['path'].startswith(path + '/')):
                changes[r['id']] = clean_path(new + r['path'][len(path):])
        if any(p == path or p.startswith(path + '/') or p.startswith(new + '/') or p == new for p in UPLOADING): err(409, '相关目录正在上传，请稍后移动')
    occupied = {r['path'] for r in rows if r['id'] not in changes}
    values = list(changes.values())
    if len(set(values)) != len(values) or any(p in occupied for p in values): err(409, '目标中存在同名条目，移动已取消，不会覆盖')
    with DB:
        for fid, path in changes.items(): DB.execute('UPDATE files SET path=? WHERE id=?', (path, fid))
    return {'ok': True, 'moved': len(changes)}

@app.get('/api/folders/{fid}/download')
async def download_folder(fid: str, request: Request):
    session(request)
    # Snapshot metadata on the main DB connection; sqlite operations are read-only here.
    root = DB.execute("SELECT * FROM files WHERE id=? AND kind='folder'", (fid,)).fetchone()
    if not root: err(404, '文件夹不存在')
    prefix = root['path'] + '/'
    rows = [dict(r) for r in DB.execute('SELECT * FROM files ORDER BY path') if r['path'] == root['path'] or r['path'].startswith(prefix)]
    base = root['path'].rsplit('/', 1)[-1]
    offset = len(root['path']) - len(base)
    def archive():
        import zipfile
        class Sink:
            def __init__(self): self.parts = []; self.position = 0
            def write(self, data): self.parts.append(data); self.position += len(data); return len(data)
            def tell(self): return self.position
            def flush(self): pass
            def drain(self):
                parts = self.parts; self.parts = []
                return parts
        sink = Sink()
        # ZIP_STORED avoids CPU-heavy compression; no plaintext temporary archive is created.
        with zipfile.ZipFile(sink, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for r in rows:
                name = r['path'][offset:]
                if r['kind'] == 'folder':
                    z.writestr(name + '/', b'')
                    yield from sink.drain()
                else:
                    with z.open(name, 'w', force_zip64=True) as entry:
                        for chunk in decrypted_chunks(r):
                            entry.write(chunk)
                            yield from sink.drain()
                    yield from sink.drain()
        yield from sink.drain()
    from urllib.parse import quote
    return StreamingResponse(archive(), media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(base + '.zip', safe='')})

@app.get('/api/files/{fid}/download')
async def download(fid: str, request: Request):
    session(request)
    r = DB.execute("SELECT * FROM files WHERE id=? AND kind='file'", (fid,)).fetchone()
    if not r: err(404, '文件不存在')
    from urllib.parse import quote
    event('download', bytes=r['size'])
    return StreamingResponse(decrypted_chunks(dict(r)), media_type='application/octet-stream', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(PurePosixPath(r['path']).name, safe=''), 'Content-Length': str(r['size'])})

@app.delete('/api/files/{fid}')
async def remove_file(fid: str, request: Request):
    session(request)
    row = DB.execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone()
    if not row: err(404, '不存在')
    if row['kind'] == 'folder' and any(r['path'].startswith(row['path'] + '/') for r in DB.execute('SELECT path FROM files')): err(409, '请先清空文件夹')
    with DB: DB.execute('DELETE FROM files WHERE id=?', (fid,))
    if row['kind'] == 'file': (BLOBS / fid).unlink(missing_ok=True)
    return {'ok': True}

SEND_RATES = {}
@app.post('/api/messages')
async def send(request: Request):
    who = client(request)
    now = time.time()
    rate = SEND_RATES.setdefault(who['id'], deque())
    while rate and rate[0] < now - 60: rate.popleft()
    if len(rate) >= 120: err(429, '每个软件每分钟最多发送 120 条')
    rate.append(now)
    raw = await limited_body(request, 65536)
    try: body = json.loads(raw)
    except Exception: err(400, '无效 JSON')
    if not isinstance(body, dict): err(400, '无效消息')
    recipient = body.get('recipient')
    if not isinstance(recipient, str) or not DB.execute('SELECT 1 FROM clients WHERE id=?', (recipient,)).fetchone(): err(404, '接收方不存在')
    if body.get('sender', who['id']) != who['id']: err(403, '不得伪造发送方')
    if 'body' not in body: err(400, '缺少 body')
    content = body['body']
    if isinstance(content, dict) and content.get('protocol') == 'longs-app':
        try: validate_business(content)
        except ValueError as error: err(400, '业务协议格式错误：' + str(error))
    # Authentication may have been revoked while awaiting the request body.
    who = client(request)
    client_id = body.get('clientMessageId')
    if client_id is not None and (not isinstance(client_id,str) or not 1 <= len(client_id) <= 128 or any(ord(c)<33 or ord(c)>126 for c in client_id)):
        err(400, 'clientMessageId 必须是 1–128 个可见 ASCII 字符')
    try:
        canonical = json.dumps({'recipient':recipient,'body':body['body']}, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError): err(400, '正文必须是有效 JSON')
    # Keyed digest avoids storing plaintext or readily guessable body fingerprints.
    fingerprint = hmac.new(KEY, canonical.encode(), hashlib.sha256).hexdigest()
    mid = uuid.uuid4().hex; now = time.time()
    with DB:
        DB.execute("DELETE FROM relay_receipts WHERE state='acked' AND created<?", (now-RECEIPT_TTL,))
        if client_id is not None:
            existing = DB.execute('SELECT * FROM relay_receipts WHERE sender=? AND client_id=?', (who['id'],client_id)).fetchone()
            if existing:
                if existing['fingerprint'] != fingerprint: err(409, '幂等标识已用于不同接收方或正文')
                notify_recipient(recipient)
                return {'id':existing['message_id'],'queued':existing['state']=='queued','state':existing['state'],'duplicate':True,'clientMessageId':client_id,'evicted':[]}
            if DB.execute('SELECT COUNT(*) FROM relay_receipts WHERE sender=?', (who['id'],)).fetchone()[0] >= 10000:
                err(429, '幂等记录已达上限，请等待保留期结束或联系管理员')
        if DB.execute('SELECT COUNT(*) FROM queue WHERE recipient=?', (recipient,)).fetchone()[0] >= 10:
            event('queue_full', recipient=recipient)
            err(409, '接收方队列已满（10条），未入队且不会淘汰旧消息；请保留待发消息，稍后使用相同标识重试')
        payload = encrypt(json.dumps(body['body'], ensure_ascii=False, allow_nan=False).encode(), mid.encode())
        DB.execute('INSERT INTO queue(id,sender,recipient,payload,created) VALUES(?,?,?,?,?)', (mid,who['id'],recipient,payload,now))
        if client_id is not None:
            DB.execute('INSERT INTO relay_receipts VALUES(?,?,?,?,?,?,?)', (who['id'],client_id,recipient,mid,fingerprint,'queued',now))
    event('relay', id=mid, sender=who['id'], recipient=recipient, bytes=len(raw))
    notify_recipient(recipient)
    return {'id':mid,'queued':True,'state':'queued','duplicate':False,'clientMessageId':client_id,'evicted':[]}

@app.get('/api/messages')
async def pull(request: Request): return {'messages': pending(client(request)['id'])}

@app.post('/api/messages/{mid}/ack')
async def ack(mid: str, request: Request):
    cid = client(request)['id']
    return {'ok': True, 'removed': acknowledge(cid, mid)}

@app.websocket('/api/ws')
async def websocket(ws: WebSocket):
    if not origin_ok(ws.headers.get('origin')): await ws.close(code=1008); return
    await ws.accept(); cid = None
    try:
        frame = await asyncio.wait_for(ws.receive_text(), 10)
        if len(frame) > 4096: await ws.close(code=1009); return
        auth = json.loads(frame)
        if not isinstance(auth, dict) or not isinstance(auth.get('token'), str):
            await ws.close(code=1008); return
        try: who = client_auth(auth['token'])
        except HTTPException:
            await ws.close(code=4003); return
        cid = who['id']
        old = SOCKETS.get(cid)
        SOCKETS[cid] = ws
        WS_ACTIVITY[cid] = time.monotonic()
        if old:
            try: await asyncio.wait_for(old.close(code=4001, reason='同软件新连接已替代旧连接'), 2)
            except Exception: pass
        notify_recipient(cid)
        while True:
            text = await asyncio.wait_for(ws.receive_text(), ONLINE_TTL)
            if len(text) > 4096: break
            packet = json.loads(text)
            if not isinstance(packet, dict):
                await ws.close(code=1008); return
            # A replaced or revoked connection cannot process queued ACK frames.
            if SOCKETS.get(cid) is not ws or not DB.execute('SELECT 1 FROM clients WHERE id=?', (cid,)).fetchone():
                await ws.close(code=4003); return
            if packet.get('type') in ('ack', 'ping'): WS_ACTIVITY[cid] = time.monotonic()
            if packet.get('type') == 'ack':
                mid = packet.get('id')
                if isinstance(mid, str):
                    acknowledge(cid, mid)
            elif packet.get('type') == 'ping':
                async with LOCKS.setdefault(cid, asyncio.Lock()): await asyncio.wait_for(ws.send_json({'type':'pong'}), 10)
    except (WebSocketDisconnect, asyncio.TimeoutError, HTTPException, ValueError, AttributeError, RuntimeError): pass
    finally:
        if cid and SOCKETS.get(cid) is ws:
            SOCKETS.pop(cid, None); WS_ACTIVITY.pop(cid, None)
        try: await ws.close()
        except Exception: pass

@app.get('/api/admin/dashboard')
async def dashboard(request: Request):
    session(request)
    return {'uptime': int(time.time()-START), 'counters': dict(COUNTS), 'online': online_ids(), 'onlineTimeoutSeconds': ONLINE_TTL, 'throughput': relay_throughput(), 'events': list(EVENTS), 'pending': [dict(r) for r in DB.execute('SELECT id,sender,recipient,created FROM queue ORDER BY seq')], 'software': [dict(r) for r in DB.execute('SELECT c.id,c.name,h.suffix AS token_suffix FROM clients c LEFT JOIN client_token_hints h ON h.client_id=c.id ORDER BY c.id')], 'queueLimit': 10}

def small_resource(path, media_type=None):
    # Avoid FileResponse/sendfile path for tiny UI resources: explicit bytes + length.
    # User uploads continue to use encrypted streaming endpoints, not this helper.
    import mimetypes
    media_type = media_type or mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    return Response(content=path.read_bytes(), media_type=media_type)

@app.get('/')
async def portal():
    custom = DATA / 'portal' / 'index.html'
    return small_resource(custom if custom.exists() else ROOT / 'web' / 'index.html', media_type='text/html')

@app.get('/api/docs', include_in_schema=False)
async def api_documentation(): return small_resource(ROOT / 'web' / 'api-docs.html', media_type='text/html')

@app.get('/guide')
async def developer_guide(): return small_resource(ROOT / 'web' / 'guide.html', media_type='text/html')

@app.get('/drive')
@app.get('/dashboard')
async def console(): return small_resource(ROOT / 'web' / 'console.html', media_type='text/html')

@app.get('/favicon.ico', include_in_schema=False)
async def favicon(): return small_resource(ROOT / 'web' / 'favicon.ico', media_type='image/vnd.microsoft.icon')

@app.get('/assets/{name}')
async def asset(name: str):
    if name not in ('style.css', 'app.js', 'space.svg', 'api-docs.js', 'favicon.svg', 'favicon.png', 'favicon.ico'): err(404, '不存在')
    return small_resource(ROOT / 'web' / name)

@app.get('/integration/{name}')
async def integration(name: str):
    if name not in ('SKILL.md','hub-sdk.mjs','README.md','reliable_receiver.py','business_protocol.py','business-protocol.mjs','attachment-client.mjs'): err(404, '不存在')
    return small_resource(ROOT / 'integration' / name, media_type='text/javascript' if name.endswith('.mjs') else 'text/plain')

# Isolated temporary attachment storage/API. Install after all relay helpers exist.
import sys as _sys
from relay_attachments import install as _install_attachments
_install_attachments(app, _sys.modules[__name__])
