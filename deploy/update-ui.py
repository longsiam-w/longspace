"""Run from the uploaded project: sudo python3 deploy/update-ui.py.
Replaces shipped web assets and application code; never resets data/config.
"""
import datetime, pathlib, shutil, subprocess, urllib.request
source = pathlib.Path(__file__).resolve().parent.parent
target = pathlib.Path('/opt/private-hub/app')
if not (target / 'server.py').is_file():
    raise SystemExit('Expected existing installation at /opt/private-hub/app')
assets = ['index.html', 'console.html', 'app.js', 'style.css', 'space.svg', 'guide.html', 'api-docs.html', 'api-docs.js', 'favicon.svg', 'favicon.png', 'favicon.ico']
integration_assets = ['SKILL.md', 'hub-sdk.mjs', 'README.md', 'reliable_receiver.py', 'business_protocol.py', 'business-protocol.mjs', 'attachment-client.mjs']
for name in integration_assets:
    if not (source / 'integration' / name).is_file(): raise SystemExit('Missing integration file: ' + name)
if not (source / 'relay_attachments.py').is_file(): raise SystemExit('Missing attachment module')
if not (source / 'check_relay.py').is_file(): raise SystemExit('Missing relay checker')
for name in assets:
    if not (source / 'web' / name).is_file(): raise SystemExit('Missing asset: ' + name)
server = (target / 'server.py').read_text()
old = "if name not in ('style.css', 'app.js'):"
new = "if name not in ('style.css', 'app.js', 'space.svg'):"
latest = "if name not in ('style.css', 'app.js', 'space.svg', 'api-docs.js'):"
favicon_allowlist = "if name not in ('style.css', 'app.js', 'space.svg', 'api-docs.js', 'favicon.svg', 'favicon.png', 'favicon.ico'):"
if not any(signature in server for signature in (old, new, latest, favicon_allowlist)):
    raise SystemExit('Unrecognized asset allowlist; stopped without changes.')
backup = pathlib.Path('/opt/private-hub/backups') / ('ui-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, mode=0o700)
shutil.copytree(target / 'web', backup / 'web')
shutil.copy2(target / 'server.py', backup / 'server.py')
if (target / 'relay_attachments.py').exists(): shutil.copy2(target / 'relay_attachments.py', backup / 'relay_attachments.py')
if (target / 'integration').exists(): shutil.copytree(target / 'integration', backup / 'integration')
if (target / 'check_relay.py').exists(): shutil.copy2(target / 'check_relay.py', backup / 'check_relay.py')
print('Backup:', backup, flush=True)
# Folder management requires the new API implementation, not just static assets.
replacement = (source / 'server.py').read_text()
if "@app.post('/api/files/move')" not in replacement or "@app.get('/api/folders/{fid}/download')" not in replacement:
    raise SystemExit('Missing folder API implementation in update package.')
changed = replacement != server or not (target / 'relay_attachments.py').exists() or (target / 'relay_attachments.py').read_bytes() != (source / 'relay_attachments.py').read_bytes()

def readable_application():
    # Only shipped code and public assets, never HUB_DATA, keys or backups.
    for directory in [target, target / 'web', target / 'integration']:
        directory.chmod(0o755)
    (target / 'server.py').chmod(0o644)
    if (target / 'relay_attachments.py').exists(): (target / 'relay_attachments.py').chmod(0o644)
    (target / 'check_relay.py').chmod(0o644)
    for directory, names in [(target / 'web', assets), (target / 'integration', integration_assets)]:
        for name in names:
            (directory / name).chmod(0o644)

def verify_pages():
    expected = [('/', 'web/index.html'), ('/drive', 'web/console.html'),
                ('/guide', 'web/guide.html'), ('/api/docs', 'web/api-docs.html'),
                ('/assets/style.css', 'web/style.css'), ('/assets/app.js', 'web/app.js'),
                ('/assets/api-docs.js', 'web/api-docs.js'),
                ('/assets/favicon.svg', 'web/favicon.svg'),
                ('/favicon.ico', 'web/favicon.ico'),
                ('/integration/SKILL.md', 'integration/SKILL.md')]
    for route, relative in expected:
        # Custom portal deliberately takes precedence; only require a nonempty page.
        with urllib.request.urlopen('http://127.0.0.1:8765' + route, timeout=10) as response:
            body = response.read()
            if response.status != 200 or not body: raise RuntimeError('Empty or failed response: ' + route)
            if route != '/' and body != (source / relative).read_bytes():
                raise RuntimeError('Incomplete or unexpected response: ' + route)
    print('Verified page and asset bodies, including /guide and /api/docs.', flush=True)

try:
    shutil.copyfile(source / 'relay_attachments.py', target / 'relay_attachments.py')
    for name in assets: shutil.copyfile(source / 'web' / name, target / 'web' / name)
    (target / 'integration').mkdir(exist_ok=True)
    for name in integration_assets: shutil.copyfile(source / 'integration' / name, target / 'integration' / name)
    shutil.copyfile(source / 'check_relay.py', target / 'check_relay.py')
    if changed:
        (target / 'server.py').write_text(replacement)
    readable_application()
    if changed:
        subprocess.run(['systemctl', 'restart', 'private-hub'], check=True)
    import time
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3) as r:
                if r.status == 200: break
        except Exception:
            if attempt == 29: raise
            time.sleep(1)
    verify_pages()
    print('UI updated. No password/data/origin/certificate changes.')
    print('If a custom portal exists at /var/lib/private-hub/portal/index.html, it still takes precedence.')
except BaseException:
    for name in assets:
        saved = backup / 'web' / name
        if saved.exists(): shutil.copyfile(saved, target / 'web' / name)
    for name in integration_assets:
        saved = backup / 'integration' / name
        dest = target / 'integration' / name
        if saved.exists(): shutil.copyfile(saved, dest)
        elif dest.exists(): dest.unlink()
    saved = backup / 'check_relay.py'
    if saved.exists(): shutil.copyfile(saved, target / 'check_relay.py')
    elif (target / 'check_relay.py').exists(): (target / 'check_relay.py').unlink()
    shutil.copyfile(backup / 'server.py', target / 'server.py')
    if (backup / 'relay_attachments.py').exists(): shutil.copyfile(backup / 'relay_attachments.py', target / 'relay_attachments.py')
    for directory in (target, target / 'web', target / 'integration'):
        if directory.exists(): directory.chmod(0o755)
    for directory, names in [(target / 'web', assets), (target / 'integration', integration_assets)]:
        for name in names:
            restored = directory / name
            if restored.exists(): restored.chmod(0o644)
    (target / 'server.py').chmod(0o644)
    if (target / 'relay_attachments.py').exists(): (target / 'relay_attachments.py').chmod(0o644)
    if changed: subprocess.run(['systemctl', 'restart', 'private-hub'], check=False)
    raise
