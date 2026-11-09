"""Ephemeral local browser smoke test; never uses production credentials/data."""
import os, tempfile, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy(); env['HUB_DATA']=tmp; env['HUB_ORIGIN']='http://127.0.0.1:18765'
        setup="import server as s; salt='cd'*16; s.DB.execute('INSERT INTO settings VALUES(?,?)',('salt',salt)); s.DB.execute('INSERT INTO settings VALUES(?,?)',('password',s.password_hash('browser-test-password',salt))); s.DB.commit(); s.DB.close()"
        subprocess.run([sys.executable,'-c',setup],env=env,check=True)
        process=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','18765','--no-access-log'],env=env)
        try:
            for _ in range(50):
                try: urllib.request.urlopen('http://127.0.0.1:18765/api/health'); break
                except Exception: time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge'); page=browser.new_page(viewport={'width':1440,'height':1000}); errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:18765/'); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-portal.png'),full_page=True)
                page.goto('http://127.0.0.1:18765/drive'); page.locator('#password').fill('browser-test-password'); page.locator('#login-form button').click(); page.locator('#drive').wait_for(state='visible')
                page.locator('#mkdir').click(); page.locator('#folder-name').fill('浏览器测试目录'); page.locator('#folder-form button[type=submit]').click(); page.locator('#tree').get_by_role('button',name='▱ 浏览器测试目录').click()
                page.locator('#picker').set_input_files({'name':'hello.txt','mimeType':'text/plain','buffer':b'hello private hub'})
                page.get_by_role('button',name='▧ hello.txt').wait_for(); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-drive.png'),full_page=True)
                with page.expect_download() as result: page.get_by_role('link',name='下载 hello.txt',exact=True).click()
                assert Path(result.value.path()).read_bytes()==b'hello private hub'
                page.locator('#search').fill('hello'); page.get_by_role('button',name='▧ hello.txt').wait_for()
                page.locator('#grid-view').click(); assert page.locator('#filelist').get_attribute('class')=='file-grid'
                page.locator('#search').fill('not-present'); page.get_by_text('没有找到匹配的文件',exact=True).wait_for()
                page.locator('#search').fill(''); page.locator('#list-view').click()
                page.locator('#picker').set_input_files([{'name':'second.txt','mimeType':'text/plain','buffer':b'second'},{'name':'hello.txt','mimeType':'text/plain','buffer':b'duplicate'}])
                page.locator('#upload-check-confirm').click(); page.locator('#task-launcher').click(); page.get_by_role('button',name='▧ second.txt').wait_for()
                page.set_viewport_size({'width':390,'height':844}); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-drive-mobile.png'),full_page=True)
                page.locator('#toggle-transfers').click(); page.locator('#select-all').check(); page.locator('#delete-selected').click(); page.locator('#delete-confirm').click()
                page.get_by_text('这里还空着，留给新的可能。',exact=True).wait_for()
                page.set_viewport_size({'width':1440,'height':1000})
                folder_path=Path(tmp)/'上传目录'; (folder_path/'子目录').mkdir(parents=True); (folder_path/'子目录'/'week5.html').write_text('<h1>folder upload</h1>'); (folder_path/'note.txt').write_text('folder note')
                page.locator('#folder-picker').set_input_files(str(folder_path)); page.locator('#upload-check-confirm').click()
                page.locator('#tree').get_by_role('button',name='▱ 上传目录',exact=True).click()
                page.get_by_role('button',name='▧ note.txt',exact=True).wait_for()
                page.get_by_role('button',name='移动 note.txt',exact=True).click(); page.locator('#move-search').fill('子目录'); page.locator('#move-tree').get_by_role('button',name='子目录',exact=True).click(); page.locator('#move-form button[type=submit]').click()
                page.locator('#filelist').get_by_role('button',name='▱ 子目录',exact=True).click(); page.get_by_role('button',name='▧ note.txt',exact=True).wait_for(); page.get_by_role('button',name='▧ week5.html',exact=True).wait_for()
                page.locator('#grid-view').click(); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-grid-v2.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844}); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-grid-mobile-v2.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000}); page.locator('#tree').get_by_role('button',name='▱ 上传目录',exact=True).click()
                with page.expect_download() as archive: page.get_by_role('link',name='下载 子目录',exact=True).click()
                import zipfile
                with zipfile.ZipFile(archive.value.path()) as z: assert z.read('子目录/note.txt')==b'folder note'
                page.goto('http://127.0.0.1:18765/dashboard'); page.locator('#dashboard').wait_for(state='visible'); page.locator('#register').click(); page.locator('#software-name').fill('测试设备'); page.locator('#register-submit').click(); page.locator('#credential').wait_for(state='visible'); old_token=page.locator('#secret').input_value(); assert len(old_token)==48 and '{' not in old_token; page.locator('#close-secret').click(); assert page.locator('#secret').input_value()==''
                page.wait_for_function("document.querySelectorAll('#chart .bar').length===120"); assert '最近2小时' in page.locator('#rate').inner_text()
                device=page.request.get('http://127.0.0.1:18765/api/software').json()['software'][0]
                response=page.request.post('http://127.0.0.1:18765/api/messages',headers={'Authorization':'Bearer '+old_token},data={'recipient':device['id'],'body':'dashboard tiny probe'})
                assert response.ok
                page.evaluate('refreshDashboard()'); page.locator('#events').get_by_text('relay 测试设备 ('+device['id']+') → 测试设备 ('+device['id']+')',exact=True).wait_for()
                assert '测试设备' in page.locator('#pending').inner_text()
                page.set_viewport_size({'width':390,'height':844}); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'); page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_text('测试设备',exact=True).wait_for(); page.get_by_text('*******************'+old_token[-3:],exact=True).wait_for(); page.get_by_role('button',name='重新分配 Token',exact=True).click(); page.locator('#confirm-accept').click(); page.locator('#credential').wait_for(state='visible'); new_token=page.locator('#secret').input_value(); assert len(new_token)==48 and new_token!=old_token; page.locator('#close-secret').click(); page.get_by_text('*******************'+new_token[-3:],exact=True).wait_for(); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-dashboard.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844}); page.goto('http://127.0.0.1:18765/'); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.goto('http://127.0.0.1:18765/dashboard'); page.locator('#register').click(); page.locator('#software-name').fill('手机取消测试'); page.set_viewport_size({'width':390,'height':844}); page.screenshot(path=str(Path(os.environ['TEMP'])/'hub-register-mobile.png'),full_page=True); page.keyboard.press('Escape'); assert page.locator('#register-dialog').is_hidden(); page.locator('#software').get_by_role('button',name='删除软件',exact=True).click(); page.locator('#confirm-dialog').wait_for(state='visible'); page.locator('#confirm-cancel').click(); page.get_by_text('测试设备',exact=True).wait_for(); page.locator('#software').get_by_role('button',name='删除软件',exact=True).click(); page.locator('#confirm-accept').click(); page.get_by_text('尚未登记软件。',exact=True).wait_for(); assert not errors,errors; browser.close(); print('Browser PASS: portal, login, folder, upload/download, registration, secret clearing, mobile layout; no JS runtime errors.')
        finally:
            process.terminate(); process.wait(timeout=10)
if __name__=='__main__': main()
