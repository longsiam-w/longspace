"""Run as root through an interactive SSH TTY. Targets this BT-managed site only."""
import datetime, hashlib, json, os, pathlib, pwd, shutil, socket, ssl, subprocess, sys, time, urllib.request
P=pathlib.Path
SITE=P('/www/server/panel/vhost/nginx/html_8.163.121.238.conf')
WEB=P('/www/wwwroot/8.163.121.238')
CERT=P('/www/server/panel/vhost/cert/8.163.121.238/fullchain.pem')
PRIV=P('/www/server/panel/vhost/cert/8.163.121.238/privkey.pem')
NGINX='/www/server/nginx/sbin/nginx'
SOURCE=P(__file__).resolve().parent.parent
APP=P('/opt/private-hub/app'); VENV=P('/opt/private-hub/venv'); DATA=P('/var/lib/private-hub')
BACKUP=P('/root/private-hub-backups')/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

def run(args, **kw):
    print('+', ' '.join(map(str,args)),flush=True)
    return subprocess.run(list(map(str,args)),check=True,**kw)

def private_write(path, text, mode=0o600):
    path.write_text(text,encoding='utf-8'); path.chmod(mode)

def tls_check():
    print('\n=== Public certificate metadata (no private key output) ===',flush=True)
    run(['openssl','x509','-in',CERT,'-noout','-subject','-issuer','-dates','-ext','subjectAltName'])
    # Connection to local nginx with the actual public IP as certificate identity.
    context=ssl.create_default_context()
    with socket.create_connection(('127.0.0.1',443),timeout=15) as sock:
        with context.wrap_socket(sock,server_hostname='8.163.121.238') as tls:
            print('TLS identity verification PASS:',tls.version(),flush=True)

def main():
    global CERT, PRIV
    os.umask(0o077)
    if os.geteuid()!=0: raise SystemExit('Run as root')
    if not SITE.is_file() or not WEB.is_dir() or not P(NGINX).is_file(): raise SystemExit('Expected BT site layout missing; no changes made')
    old=SITE.read_text()
    if 'server_name 8.163.121.238;' not in old: raise SystemExit('Unexpected site configuration; stop for review')
    for path in (CERT,PRIV):
        if not path.is_file(): raise SystemExit('Certificate/key path missing; stop for review')
    BACKUP.mkdir(parents=True,mode=0o700)
    shutil.copy2(SITE,BACKUP/'site.conf')
    # Back up the old site, not the certificate private key.
    run(['tar','-czf',BACKUP/'old-webroot.tar.gz','-C',WEB.parent,WEB.name])
    (BACKUP/'old-webroot.tar.gz').chmod(0o600)
    prior_env=P('/etc/private-hub.env')
    if prior_env.exists(): shutil.copy2(prior_env,BACKUP/'private-hub.env')
    prior_service=P('/etc/systemd/system/private-hub.service')
    if prior_service.exists(): shutil.copy2(prior_service,BACKUP/'private-hub.service')
    print('BACKUP:',BACKUP,flush=True)
    # Never replace or install another nginx alongside BaoTa nginx.
    if not P('/usr/bin/python3').is_file(): raise SystemExit('System python3 missing')
    if not subprocess.run(['/usr/bin/python3','-c','import venv,ensurepip'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
        run(['apt-get','update'])
        run(['apt-get','install','-y','python3-venv'])
    try: account=pwd.getpwnam('private-hub')
    except KeyError:
        run(['useradd','--system','--home','/var/lib/private-hub','--shell','/usr/sbin/nologin','private-hub'])
        account=pwd.getpwnam('private-hub')
    DATA.mkdir(parents=True,exist_ok=True); DATA.chmod(0o700); os.chown(DATA,account.pw_uid,account.pw_gid)
    if APP.exists():
        run(['tar','-czf',BACKUP/'previous-app.tar.gz','-C',APP.parent,'app'])
    APP.mkdir(parents=True,exist_ok=True)
    # Files are root-owned and read-only to the service; no secrets in app tree.
    for name in ('server.py','relay_attachments.py','manage.py','requirements.txt','README.md'):
        shutil.copy2(SOURCE/name,APP/name); (APP/name).chmod(0o644)
    for name in ('web','integration','deploy'):
        shutil.copytree(SOURCE/name,APP/name,dirs_exist_ok=True)
    for root,dirs,files in os.walk(APP):
        P(root).chmod(0o755)
        for f in files: (P(root)/f).chmod(0o644)
    # Parent permissions must allow the unprivileged service to traverse.
    APP.parent.chmod(0o755)
    # Runtime libraries contain no secrets and must be readable by service user.
    os.umask(0o022)
    try:
        if not (VENV/'bin/python').exists(): run(['/usr/bin/python3','-m','venv',VENV])
        run([VENV/'bin/python','-m','pip','install','-r',APP/'requirements.txt'])
    finally:
        os.umask(0o077)
    # Backups are private; prepare rollback before any public cutover.
    rollback=f'''#!/bin/sh
set -eu
cp '{BACKUP}/site.conf' '{SITE}'
'{NGINX}' -t
'{NGINX}' -s reload
echo 'Previous website routing restored. Hub data retained; backend left running on loopback only.'
'''
    private_write(BACKUP/'rollback.sh',rollback,0o700)
    # Do not reset an existing admin password.
    env=os.environ.copy(); env['HUB_DATA']=str(DATA)
    check=subprocess.run(['runuser','-u','private-hub','--','env','HUB_DATA='+str(DATA),str(VENV/'bin/python'),'-c','import server; print(bool(server.setting("password")))'],cwd=APP,capture_output=True,text=True,check=True)
    if check.stdout.strip()!='True':
        print('\nEnter a NEW Hub admin password below (not your SSH password). Input is hidden.',flush=True)
        run(['runuser','-u','private-hub','--','env','HUB_DATA='+str(DATA),VENV/'bin/python',APP/'manage.py','init'],cwd=APP)
    private_write(prior_env,'HUB_DATA=/var/lib/private-hub\nHUB_ORIGIN=https://8.163.121.238\nHUB_MAX_FILE_BYTES=1073741824\nHUB_QUOTA_BYTES=21474836480\n')
    shutil.copy2(SOURCE/'deploy/hub.service',prior_service); prior_service.chmod(0o644)
    run(['systemctl','daemon-reload']);run(['systemctl','enable','private-hub']);run(['systemctl','restart','private-hub'])
    for _ in range(50):
        try:
            health=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=2))
            if health.get('configured'): break
        except Exception: time.sleep(.2)
    else: raise SystemExit('Backend health failed. Public site untouched. Check systemctl status private-hub')
    print('Backend health PASS; encrypted storage initialized.',flush=True)
    if '--setup-https' in sys.argv:
        from https_setup import setup
        CERT, PRIV = setup(BACKUP)
        time.sleep(1)
    try: tls_check()
    except Exception as exc:
        print('\nTLS CHECK FAILED:',str(exc),flush=True)
        print('Backend installed on loopback ONLY. Existing public website was NOT changed.',flush=True)
        print('Fix a trusted certificate for IP 8.163.121.238 in BaoTa, or ask to adapt to your domain, then rerun deployment.',flush=True)
        print('For private local preview: ssh -L 18765:127.0.0.1:8765 root@8.163.121.238 (portal only; HTTPS cookie login requires HTTPS).',flush=True)
        raise SystemExit(20)
    well_known='/www/server/panel/vhost/nginx/well-known/8.163.121.238.conf'
    include=f'    include {well_known};\n' if P(well_known).exists() else ''
    config='''# LONGS Private Hub. Managed deployment; use private backup for rollback.
server {
    listen 80;
    server_name 8.163.121.238;
    root /www/wwwroot/8.163.121.238;
    location ^~ /.well-known/acme-challenge/ { try_files $uri =404; }
    location / { return 308 https://8.163.121.238$request_uri; }
    access_log off;
}
server {
    listen 443 ssl;
    server_name 8.163.121.238;
    root /www/wwwroot/8.163.121.238;
    ssl_certificate /www/server/panel/vhost/cert/8.163.121.238/fullchain.pem;
    ssl_certificate_key /www/server/panel/vhost/cert/8.163.121.238/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    ssl_early_data off;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 1024m;
    client_body_timeout 300s;
    access_log off;
    error_log /www/wwwlogs/8.163.121.238.error.log warn;
INCLUDE
    location ^~ /.well-known/acme-challenge/ { try_files $uri =404; }
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Origin $http_origin;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache off;
        proxy_next_upstream off;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 120s;
        proxy_send_timeout 300s;
    }
}
'''.replace('INCLUDE',include.rstrip()).replace('/www/server/panel/vhost/cert/8.163.121.238/fullchain.pem',str(CERT)).replace('/www/server/panel/vhost/cert/8.163.121.238/privkey.pem',str(PRIV))
    print('TLS verified. Ready to replace the old test page and route the site to Private Hub.',flush=True)
    if input('Type DEPLOY to switch this site now: ').strip()!='DEPLOY':
        print('Cancelled public cutover. Backend stays on loopback.');return
    # Old root stays in private backup and behind the proxy, not deleted.
    # No extension include: BaoTa site_total captures cookies and must not apply here.
    candidate=BACKUP/'new-site.conf'; private_write(candidate,config)
    shutil.copy2(candidate,SITE); SITE.chmod(0o644)
    try:
        run([NGINX,'-t']);run([NGINX,'-s','reload'])
        time.sleep(1)
        # Check actual TLS virtual host locally, with full chain and IP verification.
        ctx=ssl.create_default_context()
        with socket.create_connection(('127.0.0.1',443),timeout=10) as raw:
            with ctx.wrap_socket(raw,server_hostname='8.163.121.238') as tls:
                tls.sendall(b'GET /api/health HTTP/1.1\r\nHost: 8.163.121.238\r\nConnection: close\r\n\r\n')
                result=b''
                while True:
                    block=tls.recv(65536)
                    if not block: break
                    result+=block
                if b'200 OK' not in result.split(b'\r\n')[0] or b'"configured":true' not in result: raise RuntimeError('TLS health check failed')
    except Exception:
        shutil.copy2(BACKUP/'site.conf',SITE);run([NGINX,'-t']);run([NGINX,'-s','reload']);raise
    if '--setup-https' in sys.argv:
        print('Testing automatic renewal against final HTTP challenge routing...',flush=True)
        renewal_test = subprocess.run(['/opt/private-hub-certbot/bin/certbot','renew','--cert-name','private-hub-ip','--dry-run','--run-deploy-hooks'])
        if renewal_test.returncode:
            print('WARNING: HTTPS cutover passed, but simulated renewal FAILED. Production certificate remains installed; renewal reliability requires follow-up before expiry.',flush=True)
    print('\nDEPLOYMENT COMPLETE: https://8.163.121.238',flush=True)
    print('Old test page is no longer served. Cookie-capturing statistics disabled for this site.',flush=True)
    print('Backup and rollback:',BACKUP,flush=True)
    print('Please send this output for external verification. Do not share passwords or private keys.',flush=True)

if __name__=='__main__':
    try: main()
    except subprocess.CalledProcessError as e: raise SystemExit('Command failed; review above output: '+str(e))
