import getpass, os, secrets, sys

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('init', 'reset-password'):
        raise SystemExit('Usage: python manage.py init|reset-password')
    import server as s
    if sys.argv[1] == 'init' and s.setting('password'):
        raise SystemExit('Already initialized; use reset-password explicitly.')
    password = getpass.getpass('Admin password (non-empty): ')
    if not password: raise SystemExit('Password must not be empty')
    if password != getpass.getpass('Repeat password: '): raise SystemExit('Passwords differ')
    salt = secrets.token_hex(16)
    with s.DB:
        s.DB.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('salt',salt))
        s.DB.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('password',s.password_hash(password,salt)))
    print('Saved. Restart service to invalidate all existing sessions.')
if __name__ == '__main__': main()
