"""Portable packaging and verified extraction, Python standard library only."""
import hashlib, pathlib, sys, zipfile
P=pathlib.Path
REQUIRED=('server.py','relay_attachments.py','manage.py','check_relay.py','requirements.txt','README.md','web/app.js','web/console.html','web/index.html','web/style.css','integration/SKILL.md','integration/hub-sdk.mjs','integration/business_protocol.py','integration/business-protocol.mjs','integration/attachment-client.mjs','deploy/install-server.py','deploy/hub.service')

def main():
    action,source,target=sys.argv[1:]
    source=P(source); target=P(target)
    if action=='pack':
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for name in ('server.py','relay_attachments.py','manage.py','check_relay.py','requirements.txt','README.md','web','integration','deploy'):
                item=source/name
                paths=sorted(item.rglob('*')) if item.is_dir() else [item]
                for p in paths:
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.key','.pem'):
                        z.write(p,p.relative_to(source).as_posix())
        with zipfile.ZipFile(target) as z:
            missing=set(REQUIRED)-set(z.namelist())
            if missing: raise SystemExit('Archive missing files: '+str(missing))
            if z.testzip(): raise SystemExit('Archive integrity check failed')
        print('Archive verified:',target,'SHA256:',hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)
    elif action=='unpack':
        print('Remote archive:',source,'SHA256:',hashlib.sha256(source.read_bytes()).hexdigest(),flush=True)
        target.mkdir(parents=True,exist_ok=True,mode=0o700)
        with zipfile.ZipFile(source) as z:
            if z.testzip(): raise SystemExit('Archive integrity check failed')
            for item in z.infolist():
                # Tolerate legacy Windows ZIP paths without ever escaping destination.
                name=item.filename.replace('\\','/')
                parts=pathlib.PurePosixPath(name)
                if parts.is_absolute() or '..' in parts.parts or ':' in name: raise SystemExit('Unsafe archive path')
                dest=target.joinpath(*parts.parts)
                if item.is_dir() or name.endswith('/'):
                    dest.mkdir(parents=True,exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(z.read(item))
        missing=[name for name in REQUIRED if not (target/name).is_file()]
        if missing:
            print('Extracted files:',[str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()][:100])
            raise SystemExit('Extraction missing required files: '+str(missing))
        print('Remote extraction verified. Installer:',target/'deploy/install-server.py',flush=True)
    else: raise SystemExit('Expected pack or unpack')

if __name__=='__main__': main()
