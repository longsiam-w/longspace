"""Small local-only GUI acceptance: temporary data, four tiny files maximum; no load tests."""
import os, sys, time, tempfile, subprocess, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent

def main():
    with tempfile.TemporaryDirectory() as tmp:
        env=os.environ.copy(); env['HUB_DATA']=tmp; env['HUB_ORIGIN']='http://127.0.0.1:18766'
        setup="import server as s; salt='ef'*16; s.DB.execute('INSERT INTO settings VALUES(?,?)',('salt',salt)); s.DB.execute('INSERT INTO settings VALUES(?,?)',('password',s.password_hash('browser-test-password',salt))); s.DB.commit(); s.DB.close()"
        subprocess.run([sys.executable,'-c',setup],cwd=ROOT,env=env,check=True)
        process=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','18766','--no-access-log'],cwd=ROOT,env=env)
        try:
            for _ in range(60):
                try: urllib.request.urlopen('http://127.0.0.1:18766/api/health'); break
                except Exception: time.sleep(.1)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='msedge'); page=browser.new_page(viewport={'width':1440,'height':1000}); errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:18766/'); assert page.title()=='LONGS云 / 云私人数字空间'
                page.goto('http://127.0.0.1:18766/drive'); page.locator('#password').fill('browser-test-password'); page.locator('#login-form button').click(); page.locator('#drive').wait_for(state='visible')
                def post(path,body):
                    result=page.request.post('http://127.0.0.1:18766/api'+path,data=body); assert result.ok,result.text()
                post('/folders/ensure',{'paths':['资料','资料/子目录','其他']})
                page.locator('#refresh').click(); page.locator('#tree').get_by_role('button',name='▱ 资料',exact=True).wait_for()
                page.locator('#picker').set_input_files({'name':'根目录说明.txt','mimeType':'text/plain','buffer':b'local gui'})
                page.get_by_role('button',name='▧ 根目录说明.txt',exact=True).wait_for()
                page.locator('#tree').get_by_role('button',name='▱ 资料',exact=True).click()
                page.locator('#picker').set_input_files({'name':'项目资料说明.txt','mimeType':'text/plain','buffer':b'tiny local file'})
                page.get_by_role('button',name='▧ 项目资料说明.txt',exact=True).wait_for()
                page.locator('#search').fill('根目录'); page.get_by_role('button',name='▧ 根目录说明.txt',exact=True).wait_for()
                page.locator('#search-scope').select_option('current'); page.get_by_text('没有找到匹配的文件',exact=True).wait_for()
                page.locator('#search-scope').select_option('all'); page.get_by_role('button',name='打开所在目录',exact=True).click(); assert page.locator('#search').input_value()==''
                page.get_by_role('button',name='详情与更多操作 根目录说明.txt',exact=True).click(); page.get_by_role('dialog',name='根目录说明.txt',exact=True).wait_for(); page.locator('#item-close').click()
                page.get_by_role('button',name='移动 根目录说明.txt',exact=True).click(); page.locator('#move-search').fill('其他'); page.locator('#move-tree').get_by_role('button',name='其他',exact=True).click(); page.locator('#move-form button[type=submit]').click(); page.get_by_text('已移动 1 项到 其他',exact=True).wait_for()
                page.locator('#task-launcher').click(); assert page.locator('#transfers').is_visible(); page.locator('#toggle-transfers').click(); assert page.locator('#transfers').is_hidden(); page.locator('#task-launcher').click()
                page.locator('#clear-transfers').click(); assert page.locator('#transfers').is_hidden(); assert page.locator('#task-launcher').is_hidden()
                page.locator('#tree').get_by_role('button',name='▱ 资料',exact=True).click(); page.locator('#grid-view').click()
                # Small round-two checks: duplicate rename, blocked nonempty deletion, nested target creation/history.
                page.locator('#picker').set_input_files({'name':'项目资料说明.txt','mimeType':'text/plain','buffer':b'copy'})
                page.locator('#upload-check').wait_for(state='visible'); page.locator('#upload-conflict').select_option('rename'); page.locator('#upload-check-confirm').click()
                page.get_by_role('button',name='▧ 项目资料说明 (2).txt',exact=True).wait_for()
                page.locator('#list-view').click()
                styles=page.locator('.file-row').filter(has=page.get_by_role('button',name='▧ 项目资料说明.txt',exact=True)).locator('.file-actions').evaluate('(e)=>[...e.querySelectorAll(".file-operation")].map(b=>({height:getComputedStyle(b).minHeight,border:getComputedStyle(b).borderTopWidth}))')
                assert all(x['border']=='1px' for x in styles),styles
                page.locator('#tree').get_by_role('button',name='▱ 全部文件',exact=True).click()
                page.get_by_role('button',name='删除 资料',exact=True).click(); assert page.locator('#delete-confirm').is_disabled(); page.locator('#delete-cancel').click()
                page.locator('#tree').get_by_role('button',name='▱ 资料',exact=True).click()
                page.get_by_role('button',name='移动 项目资料说明 (2).txt',exact=True).click()
                page.locator('#move-search').fill('其他'); page.locator('#move-tree').get_by_role('button',name='其他',exact=True).click(); page.locator('#move-mkdir').click()
                page.locator('#folder-name').fill('新目标'); page.locator('#folder-form button[type=submit]').click(); page.locator('#move-dialog').wait_for(state='visible')
                assert '其他/新目标' in page.locator('#move-location').inner_text(); page.locator('#move-form button[type=submit]').click()
                page.locator('#tree').get_by_role('button',name='▱ 其他',exact=True).click(); page.go_back(); page.get_by_role('button',name='▧ 项目资料说明.txt',exact=True).wait_for()
                page.reload(); page.get_by_role('button',name='▧ 项目资料说明.txt',exact=True).wait_for()
                page.locator('#grid-view').click()
                assert page.locator('#upload-menu summary svg').count()==2
                assert page.locator('#tree .directory-row').evaluate_all('''(rows)=>rows.filter(r=>!r.hidden).every(r=>{const path=r.querySelector('.tree-button').title;const depth=path==='全部文件'?0:path.split('/').length;const probe=document.createElement('span');probe.style.width='2ch';probe.style.position='absolute';probe.style.display='block';r.append(probe);const unit=parseFloat(getComputedStyle(probe).width);probe.remove();return Math.abs(parseFloat(getComputedStyle(r).paddingInlineStart)-depth*unit)<1})''')
                assert page.locator('#filelist .name').first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)>=15')
                page.locator('#notice').evaluate('(e)=>e.textContent=""'); page.screenshot(path=str(Path(tmp)/'desktop.png'),full_page=True); assert page.locator('.file-grid .file-actions').evaluate_all('(els)=>els.every(e=>e.getBoundingClientRect().right<=e.closest(".file-row").getBoundingClientRect().right+1)')
                screenshots=ROOT/'gui-验收截图'; screenshots.mkdir(exist_ok=True); (screenshots/'desktop.png').write_bytes((Path(tmp)/'desktop.png').read_bytes())
                for width in [320,390,768,1440]:
                    page.set_viewport_size({'width':width,'height':844}); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.set_viewport_size({'width':390,'height':844}); assert page.locator('#tree').is_hidden(); page.locator('#toggle-tree').click(); assert page.locator('#tree').is_visible(); page.locator('#toggle-tree').click()
                page.get_by_role('button',name='详情与更多操作 项目资料说明.txt',exact=True).click(); page.screenshot(path=str(screenshots/'mobile-detail.png'),full_page=True); page.locator('#item-close').click()
                page.locator('#select-all').check(); assert page.locator('#selection-actions').is_visible(); page.screenshot(path=str(screenshots/'mobile-selection.png'),full_page=True); page.locator('#clear-selection').click(); page.locator('#mkdir').click(); assert '资料' in page.locator('#folder-location').inner_text(); page.keyboard.press('Escape'); assert page.locator('#folder-dialog').is_hidden()
                page.screenshot(path=str(screenshots/'mobile.png'),full_page=True)
                page.locator('.account-menu summary').click(); page.locator('#logout').click(); page.locator('#login').wait_for(state='visible'); assert page.locator('#filelist').inner_text()==''
                assert not errors,errors; browser.close(); print('GUI PASS: title, scoped search, locate, details, filtered move, transfer collapse/clear, 4 viewports, mobile directory, Escape, logout. Only three tiny files uploaded locally; duplicate rename, blocked deletion, nested destination, history and reload also PASS.')
        finally:
            process.terminate(); process.wait(timeout=10)

if __name__=='__main__': main()
