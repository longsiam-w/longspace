"""Local read-only documentation acceptance; no production, messages or uploads."""
import os, sys, tempfile, subprocess, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent

def main():
    with tempfile.TemporaryDirectory(prefix='hub-docs-') as tmp:
        env=os.environ.copy();env['HUB_DATA']=tmp;env['HUB_ORIGIN']='http://127.0.0.1:18767'
        server=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','18767','--no-access-log'],cwd=ROOT,env=env)
        try:
            for _ in range(60):
                try: urllib.request.urlopen('http://127.0.0.1:18767/api/health',timeout=1);break
                except Exception:time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge');page=browser.new_page(viewport={'width':1280,'height':900});errors=[];external=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
                page.on('request',lambda req:external.append(req.url) if not req.url.startswith('http://127.0.0.1:18767/') else None)
                for resource in ['/guide','/assets/favicon.svg?v=20261107b','/assets/favicon.png?v=20261107b','/favicon.ico?v=20261107b','/assets/api-docs.js']:
                    check=page.request.get('http://127.0.0.1:18767'+resource);assert check.ok,resource;assert len(check.body())==int(check.headers['content-length']),resource
                page.goto('http://127.0.0.1:18767/guide');page.get_by_role('heading',name='连接你的工具与设备',exact=True).wait_for()
                response=page.goto('http://127.0.0.1:18767/api/docs');assert response.status==200
                assert "script-src 'self'" in response.headers['content-security-policy']
                page.locator('.api-endpoint').first.wait_for();assert page.locator('.api-endpoint').count()>10
                page.locator('#api-filter').fill('/api/messages');assert page.locator('.api-endpoint:visible').count()==3
                page.locator('.api-endpoint:visible').first.locator('summary').click();assert page.locator('.api-endpoint:visible').first.locator('pre').is_visible()
                page.locator('#api-filter').fill('');assert page.locator('body>header>nav').evaluate('(el)=>Math.abs((el.getBoundingClientRect().left+el.getBoundingClientRect().right)/2-innerWidth/2)<2');page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                screenshots=ROOT/'gui-验收截图';screenshots.mkdir(exist_ok=True);page.screenshot(path=str(screenshots/'api-docs-mobile.png'),full_page=True)
                assert not errors,errors;assert not external,external;browser.close()
                print('API docs PASS: strict CSP, no external requests/errors, schema rendering, filter, expand, mobile. Local only.')
        finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':main()
