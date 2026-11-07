"""Let's Encrypt IP certificate for the inspected BaoTa site. No cloud credentials."""
import os, pathlib, re, secrets, shutil, subprocess, urllib.request
P=pathlib.Path
IP='8.163.121.238'
SITE=P('/www/server/panel/vhost/nginx/html_8.163.121.238.conf')
NGINX='/www/server/nginx/sbin/nginx'
WEB=P('/www/wwwroot/8.163.121.238')
BOT=P('/opt/private-hub-certbot/bin/certbot')
NAME='private-hub-ip'
LIVE=P('/etc/letsencrypt/live')/NAME

def run(args,**kw):
    print('+',' '.join(map(str,args)),flush=True)
    return subprocess.run(list(map(str,args)),check=True,**kw)

def write(path,text,mode=0o644):
    path=P(path);path.write_text(text,encoding='utf-8');path.chmod(mode)

def setup(backup):
    print('\nFree IP certificate: valid about 6 days; automatic renewal is required.',flush=True)
    print('CA: Lets Encrypt. Terms: https://letsencrypt.org/repository/',flush=True)
    print('Account email: wen.longs@qq.com. The IP certificate will be publicly logged in Certificate Transparency.',flush=True)
    if input('Agree to CA terms and request a certificate? Type YES: ').strip()!='YES':
        raise SystemExit('Certificate request cancelled. Public site unchanged.')
    # Independent venv avoids changing BaoTa Python and nginx.
    run(['/usr/bin/python3','-m','venv','/opt/private-hub-certbot'])
    run(['/opt/private-hub-certbot/bin/python','-m','pip','install','certbot>=5.4,<6'])
    run([BOT,'--version'])
    original=SITE.read_text()
    # Only this site's IPv4 HTTP listener is moved to a challenge-only server.
    # Keep its existing HTTPS listener intact until the trusted certificate is ready.
    if re.search(r'listen\s+[^;]*80[^;]*;',original) is None:
        raise SystemExit('HTTP listener not found; stop for manual review')
    stripped,count=re.subn(r'(?m)^\s*listen\s+80\s*;\s*$', '',original)
    if count!=1: raise SystemExit('Unexpected HTTP listener layout; stop for manual review')
    temporary='''
server {
    listen 80;
    server_name 8.163.121.238;
    root /www/wwwroot/8.163.121.238;
    access_log off;
    location ^~ /.well-known/acme-challenge/ { try_files $uri =404; }
    location / { return 503; }
}
'''
    # Backed up by parent before this function; restore on any issuance failure.
    try:
        write(SITE,stripped+temporary)
        run([NGINX,'-t']);run([NGINX,'-s','reload'])
        challenge=WEB/'.well-known/acme-challenge';challenge.mkdir(parents=True,exist_ok=True)
        for folder in (WEB/'.well-known',challenge): folder.chmod(0o755)
        token=secrets.token_hex(16);test=challenge/('hub-check-'+token);write(test,token)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://'+IP+'/.well-known/acme-challenge/'+test.name,timeout=20) as response:
                if response.read().decode()!=token: raise RuntimeError('HTTP challenge content mismatch')
        finally: test.unlink(missing_ok=True)
        args=[BOT,'certonly','--non-interactive','--agree-tos','--email','wen.longs@qq.com',
              '--preferred-profile','shortlived','--webroot','--webroot-path',WEB,
              '--ip-address',IP,'--cert-name',NAME]
        # Dry-run uses the staging CA and never installs its untrusted certificate.
        print('Checking issuance with staging CA (dry-run); no staging cert will be installed.',flush=True)
        run(args+['--dry-run'])
        run(args)
        if not (LIVE/'fullchain.pem').is_file() or not (LIVE/'privkey.pem').is_file():
            raise RuntimeError('Expected production certificate paths missing')
        hook=P('/etc/letsencrypt/renewal-hooks/deploy/private-hub-nginx')
        hook.parent.mkdir(parents=True,exist_ok=True)
        write(hook,'#!/bin/sh\nset -eu\n'+NGINX+' -t\n'+NGINX+' -s reload\n',0o700)
        write('/etc/systemd/system/private-hub-cert-renew.service','''[Unit]
Description=Renew LONGS IP certificate
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/private-hub-certbot/bin/certbot renew --cert-name private-hub-ip --quiet
''')
        write('/etc/systemd/system/private-hub-cert-renew.timer','''[Unit]
Description=Check LONGS IP certificate renewal every 6 hours
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
''')
        run(['systemctl','daemon-reload'])
        run(['systemctl','enable','--now','private-hub-cert-renew.timer'])
        run(['systemctl','list-timers','private-hub-cert-renew.timer','--no-pager'])
        # Restore the prior routing until parent validates and performs final cutover.
        # It will replace old certificate references with LIVE below.
        candidate=re.sub(r'(?m)^(\s*ssl_certificate\s+)[^;]+;',lambda m:m.group(1)+str(LIVE/'fullchain.pem')+';',original)
        candidate=re.sub(r'(?m)^(\s*ssl_certificate_key\s+)[^;]+;',lambda m:m.group(1)+str(LIVE/'privkey.pem')+';',candidate)
        if str(LIVE/'fullchain.pem') not in candidate: raise RuntimeError('Existing certificate directive differs; stop for review')
        write(SITE,candidate);run([NGINX,'-t']);run([NGINX,'-s','reload'])
        # Check renewal challenge against the SAME temporary config already proven.
        # Final parent config keeps an identical public challenge route on port 80.
        print('Production certificate issued; renewal timer enabled. Final site cutover follows.',flush=True)
        return LIVE/'fullchain.pem',LIVE/'privkey.pem'
    except BaseException:
        write(SITE,original)
        run([NGINX,'-t']);run([NGINX,'-s','reload'])
        print('HTTPS setup stopped. Previous site configuration restored.',flush=True)
        raise
