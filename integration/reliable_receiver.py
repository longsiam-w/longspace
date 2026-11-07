"""Durable inbox example. Standard library only; HTTPS token stays in environment.
Business SQLite writes and processed ID commit together BEFORE server ACK.
External side effects are NOT transactional with SQLite: use an outbox/idempotency API.
"""
import json, os, sqlite3, time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError('Redirect refused')

class DurableInbox:
    def __init__(self, path):
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS processed(recipient TEXT NOT NULL,id TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(recipient,id));
        CREATE TABLE IF NOT EXISTS business_inbox(recipient TEXT NOT NULL,id TEXT NOT NULL,sender TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(recipient,id));
        ''')
    def process(self, message, apply=None):
        recipient=message['recipient'];mid=message['id']
        with self.db:
            if self.db.execute('SELECT 1 FROM processed WHERE recipient=? AND id=?',(recipient,mid)).fetchone():return False
            if apply is None:
                self.db.execute('INSERT INTO business_inbox VALUES(?,?,?,?)',(recipient,mid,message['sender'],json.dumps(message['body'],ensure_ascii=False)))
            else:
                # apply must only perform writes on this connection, without committing.
                apply(self.db,message)
            self.db.execute('INSERT INTO processed VALUES(?,?,?)',(recipient,mid,time.time()))
        return True
    def close(self):self.db.close()

def main():
    base=os.environ.get('HUB_URL','').rstrip('/');token=os.environ.get('HUB_TOKEN','');parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not token:
        raise ValueError('Set HUB_URL to a trusted HTTPS origin and HUB_TOKEN locally')
    inbox=DurableInbox(os.environ.get('HUB_INBOX_DB','relay-inbox.sqlite3'));opener=build_opener(NoRedirect)
    def request(path,ack=False):
        req=Request(base+'/api'+path,headers={'Authorization':'Bearer '+token},data=b'{}' if ack else None)
        with opener.open(req,timeout=15) as response:return json.load(response)
    try:
        while True:
            try:
                for message in request('/messages')['messages']:
                    inbox.process(message)
                    # If this request fails, replay will find the committed processed ID.
                    request('/messages/'+message['id']+'/ack',True)
                time.sleep(3)
            except HTTPError as error:
                if error.code in (401,403):raise ValueError('Credentials invalid/revoked; receiver stopped') from None
                print('Relay HTTP unavailable; retry in 5 seconds (no body/token logged)');time.sleep(5)
            except (URLError,TimeoutError,OSError):
                print('Relay connection unavailable; retry in 5 seconds');time.sleep(5)
    finally:inbox.close()
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
