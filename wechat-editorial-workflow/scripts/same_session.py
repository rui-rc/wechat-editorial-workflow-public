"""Run with python -i. Keeps one WebDriver for import, inspection and edits.
Requires the pinned all-to-xiumi 0.1.0 source described in importer-setup.md.
Does not read or copy credentials. Commands operate only in this browser.
"""
import argparse
import copy
import base64
import hashlib
import time
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from all_to_xiumi.browser import make_browser_options, make_webdriver
from all_to_xiumi import xiumi_publish as xp


def open_session(browser, profile):
    options = make_browser_options(browser, str(Path(profile).resolve()), detach=True)
    options._arguments = [a for a in options.arguments if a not in
                          ('--ignore-certificate-errors', '--allow-insecure-localhost')]
    driver = make_webdriver(browser, options)
    driver._wanyou_browser_name = browser
    return driver


def snapshot(driver):
    return driver.execute_script("""return Array.from(document.querySelectorAll('div[contenteditable="true"]'))
    .filter(e=>e.offsetWidth>0).map(e=>({html:e.innerHTML,text:e.innerText,textContent:e.textContent,
    items:Array.from(e.querySelectorAll('p,img')).map(n=>({tag:n.tagName,text:n.textContent,
    src:n.getAttribute('src'),loaded:n.tagName==='IMG'?n.complete&&n.naturalWidth>0:null,
    font:getComputedStyle(n).fontSize,line:getComputedStyle(n).lineHeight,
    spacing:getComputedStyle(n).letterSpacing,align:getComputedStyle(n).textAlign,indent:getComputedStyle(n).textIndent,margin:getComputedStyle(n).margin,padding:getComputedStyle(n).padding,role:n.getAttribute('data-wf-role')}))}));""")


def wait_editor(driver, timeout=60, expected_text=None):
    def ready(d):
        state=snapshot(d)
        if not state or any(e.is_displayed() for e in d.find_elements(By.CSS_SELECTOR,'section.tn-loading-overlap')):
            return False
        if expected_text and not any(expected_text in c['textContent'] for c in state):
            return False
        return state
    return WebDriverWait(driver,timeout,poll_frequency=.25).until(ready)


def reopen(driver, timeout=60, expected_text=None):
    if getattr(driver,'_wf_save_uncertain',False):
        raise RuntimeError('Save is uncertain; inspect the current page before reloading')
    driver.refresh()
    state=wait_editor(driver,timeout,expected_text)
    driver._wf_confirmed_signature=_signature(state,_metadata(driver))
    return state


def _metadata(driver):
    return driver.execute_script("return Object.fromEntries(['input.title','input.author','textarea.desc','input.link'].map(s=>[s,document.querySelector(s)?.value||'']));")


def _signature(state, metadata=None):
    return hashlib.sha256(json.dumps({'html':[c['html'] for c in state], 'metadata':metadata or {}},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def draft_id(url):
    u=urlparse(url)
    m=re.fullmatch(r'/paper/for/([1-9][0-9]*)/cube/[0-9]+',u.fragment)
    return m.group(1) if u.scheme=='https' and u.netloc=='xiumi.us' and m else None


class SaveBlocked(RuntimeError):
    pass


def classify_save_state(state):
    text=state.get('notice','')
    if re.search(r'(?:上限|已满|不足|超出|用完|达到).{0,18}(?:容量|数量|额度|草稿|图文|空间)|(?:草稿|图文|数量|容量|额度|空间).{0,24}(?:上限|已满|不足|用完|超出)|limit reached|quota|storage.*full',text,re.I):
        return 'capacity'
    if re.search(r'未登录|请.{0,4}登录|登录.{0,8}失效|sign in|log in',text,re.I):
        return 'login'
    if re.search(r'保存失败|操作失败|错误|网络异常|save failed',text,re.I):
        return 'error'
    return None


def dismiss_preview(driver):
    """Close only the observed preview overlay; leave other dialogs untouched."""
    visible = lambda d: [e for e in d.find_elements(By.CSS_SELECTOR, 'iframe.preview-frame') if e.is_displayed()]
    if not visible(driver):
        return
    mask = driver.find_element(By.CSS_SELECTOR, '.modal-dialog .background-mask.paper')
    driver.execute_script('arguments[0].click()', mask)
    WebDriverWait(driver, 10, poll_frequency=.2).until(lambda d: not visible(d))


def save(driver, timeout=40):
    dismiss_preview(driver)
    button=driver.find_element(By.CSS_SELECTOR,'button.btn-img.op-btn.save')
    signature=_signature(snapshot(driver),_metadata(driver))
    if draft_id(driver.current_url) and signature==getattr(driver,'_wf_confirmed_signature',None):
        return {'state':'unchanged','url':driver.current_url}
    driver._wf_save_uncertain=True
    driver.execute_script("""if(document.__wfSaveObserver)document.__wfSaveObserver.disconnect();
    document.__wfSaveSeen=false;
    document.__wfSaveObserver=new MutationObserver(rs=>{
      if(rs.some(r=>r.type==='attributes'&&r.target.matches('button.btn-img.op-btn.save')&&(r.oldValue!==null||r.target.disabled)))document.__wfSaveSeen=true;
      const b=document.querySelector('button.btn-img.op-btn.save');if(b&&b.disabled)document.__wfSaveSeen=true;
    });document.__wfSaveObserver.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeOldValue:true,attributeFilter:['disabled']});""")
    button.click()
    def completed(d):
        state=d.execute_script("""const b=document.querySelector('button.btn-img.op-btn.save');
        const notice=[...document.querySelectorAll('.modal-dialog,.alert,.toast,[role="alert"]')].filter(e=>e.offsetWidth>0).map(e=>e.innerText).join(' ').slice(0,1200);
        return {notice,busy:!!(b&&b.disabled),seen:!!document.__wfSaveSeen};""")
        reason=classify_save_state(state)
        if reason:
            raise SaveBlocked(reason+': '+state['notice'])
        return state if state['seen'] and not state['busy'] else False
    try:
        WebDriverWait(driver,timeout,poll_frequency=.25).until(completed)
        driver._wf_save_uncertain=False
        return {'state':'save_observed','url':driver.current_url}
    except Exception:
        # Keep unsaved state in the current page. Never create another draft to retry.
        raise
    finally:
        try:driver.execute_script('if(document.__wfSaveObserver)document.__wfSaveObserver.disconnect()')
        except Exception:pass


def _checkpoint(path, **changes):
    if path is None:return
    path=Path(path)
    if changes.get('phase')=='starting':
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as stream:
            json.dump(changes,stream,ensure_ascii=False,indent=2)
        return
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    data.update(changes)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def import_new(driver, html_path, title, checkpoint=None, plan_sha256=None):
    """Reserve one draft before uploading, then fill it. Checkpoint prevents blind retries."""
    path=Path(html_path).resolve()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if checkpoint is not None and Path(checkpoint).exists():
        raise RuntimeError('This run already started; resume its recorded draft instead of creating another')
    dismiss_preview(driver)
    _checkpoint(checkpoint,phase='starting',source_sha256=digest,plan_sha256=plan_sha256,title=title)
    if checkpoint is not None:driver._wf_checkpoint=str(checkpoint)
    try:
        html,base=xp._resolve_content_paths(path,'')
        html=xp._prepare_xiumi_images(html,base)
        xp._open_xiumi_editor(driver,'https://xiumi.us/studio/v5?lang=zh_CN#/',300,30)
        if '/for/new/' not in driver.current_url:
            raise RuntimeError('Refusing to replace an existing draft')
        xp._fill_xiumi_fields(driver,title,'','','')
        xp._paste_xiumi_html(driver,'<section><p>排版准备中（非成稿）</p></section>')
        save(driver)
        WebDriverWait(driver,40,poll_frequency=.25).until(lambda d:draft_id(d.current_url))
        url=driver.current_url
        _checkpoint(checkpoint,phase='reserved',draft_url=url,draft_id=draft_id(url))
        # Only the draft just reserved by this call may be filled wholesale.
        xp._fill_xiumi_body_then_images(driver,html,base,preserve_styles=True)
        _checkpoint(checkpoint,phase='filled')
        save(driver)
        if driver.current_url!=url or driver.find_element(By.CSS_SELECTOR,'input.title').get_attribute('value')!=title:
            raise RuntimeError('Saved draft identity does not match')
        _checkpoint(checkpoint,phase='save_observed')
        return url
    except Exception as exc:
        url=getattr(driver,'current_url','')
        _checkpoint(checkpoint,phase='blocked',draft_url=url,draft_id=draft_id(url),error=str(exc))
        raise


def _paragraphs(driver):
    return driver.execute_script("""return [...document.querySelectorAll('div[contenteditable="true"]')].filter(e=>e.offsetWidth>0).flatMap(c=>[...c.querySelectorAll('p')].map(p=>p.textContent));""")


def replace_paragraph(driver, old, new, plan=None, backup_path=None):
    if not isinstance(old,str) or not isinstance(new,str) or not old or '\n' in new:
        raise ValueError('Replace one nonempty source paragraph with plain single-paragraph text')
    before=_paragraphs(driver)
    hits=[i for i,t in enumerate(before) if t==old]
    if len(hits)!=1:
        raise RuntimeError('Expected exactly one matching paragraph')
    index=hits[0]
    updated=None
    if plan is not None:
        updated=copy.deepcopy(plan)
        matches=[n for n in updated['nodes'] if n['tag']=='P' and n['text']==old]
        if len(matches)!=1:
            raise RuntimeError('Authored plan does not uniquely identify the intended change')
        matches[0]['text']=new
    checkpoint=getattr(driver,'_wf_checkpoint',None)
    if backup_path is None and isinstance(checkpoint,(str,Path)):
        backup_path=Path(checkpoint).parent/('before-edit-'+str(time.time_ns())+'.json')
    if backup_path is not None:
        target=Path(backup_path);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps({'url':driver.current_url,'metadata':_metadata(driver),'components':snapshot(driver),'plan':plan},ensure_ascii=False,indent=2),encoding='utf-8')
    chosen=driver.execute_script("""const ps=[...document.querySelectorAll('div[contenteditable="true"]')].filter(e=>e.offsetWidth>0).flatMap(c=>[...c.querySelectorAll('p')]);
    const p=ps[arguments[0]],e=p.closest('[contenteditable="true"]');
    if(p.children.length)return {ok:false,reason:'rich-text paragraph needs scoped native editing'};
    e.focus();const r=document.createRange();r.selectNodeContents(p);const s=window.getSelection();s.removeAllRanges();s.addRange(r);
    return {ok:document.activeElement===e&&s.toString()===arguments[1]};""",index,old)
    if not chosen.get('ok'):
        raise RuntimeError('Target selection is not safe: '+str(chosen))
    expected=before.copy();expected[index]=new
    driver.switch_to.active_element.send_keys(new if new else Keys.BACKSPACE)
    # Native input can re-render the paragraph. Re-read it instead of using a stale element.
    WebDriverWait(driver,10,poll_frequency=.2).until(lambda d:_paragraphs(d)==expected)
    return {'before':before,'expected':expected,'updated_plan':updated,'backup_path':str(backup_path) if backup_path else None}


def capture_saved_preview(driver, output, width=430, expected_text=None):
    """Capture the actual saved preview, not the local source or stitched scroll slices."""
    editor=driver.current_window_handle
    if expected_text is None:
        texts=[item['text'] for cell in snapshot(driver) for item in cell['items'] if item['tag']=='P' and len(item['text'])>20]
        if not texts:raise RuntimeError('No substantive editor text available to validate the preview')
        expected_text=max(texts,key=len)[:40]
    existing=[e for e in driver.find_elements(By.CSS_SELECTOR,'iframe.preview-frame') if e.is_displayed()]
    if not existing:
        driver.find_element(By.CSS_SELECTOR,'button.btn-img.op-btn.preview').click()
    frame=WebDriverWait(driver,30).until(lambda d:next((e for e in d.find_elements(By.CSS_SELECTOR,'iframe.preview-frame') if e.get_attribute('src').startswith('https://')),None))
    preview_url=frame.get_attribute('src')
    parsed=urlparse(preview_url)
    if parsed.hostname not in ('v.xiumi.us','v.xiumius.cn'):
        raise RuntimeError('Unexpected preview origin')
    driver.switch_to.new_window('tab')
    try:
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':True})
        driver.get(preview_url)
        WebDriverWait(driver,40).until(lambda d:expected_text in d.find_element(By.TAG_NAME,'body').text)
        driver.execute_script('window.scrollTo(0,document.body.scrollHeight)')
        WebDriverWait(driver,30).until(lambda d:d.execute_script("const imgs=[...document.images].filter(i=>i.clientWidth>0);return imgs.length>=3&&imgs.every(i=>i.complete&&i.naturalWidth>0)"))
        driver.execute_script('window.scrollTo(0,0)')
        # The preview fades in after text/images load. A mid-transition screenshot
        # incorrectly makes the saved colors look washed out; ignore looping art.
        WebDriverWait(driver,10,poll_frequency=.2).until(lambda d:d.execute_script(
            "return document.getAnimations().every(a=>a.playState!=='running'||a.effect?.getComputedTiming().endTime===Infinity)"))
        size=driver.execute_script('return {height:document.documentElement.scrollHeight,width:document.documentElement.scrollWidth}')
        if size['height']>30000 or size['width']>width+1:
            raise RuntimeError('Preview exceeds expected page bounds: '+str(size))
        shot=driver.execute_cdp_cmd('Page.captureScreenshot',{'format':'png','captureBeyondViewport':True,'clip':{'x':0,'y':0,'width':width,'height':size['height'],'scale':1}})
        target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(shot['data']))
        return {'path':str(target),'source':'saved_xiumi_preview','width':width,'height':size['height']}
    finally:
        driver.close();driver.switch_to.window(editor)
        dismiss_preview(driver)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--browser',choices=['chrome','edge'],required=True)
    p.add_argument('--profile',required=True)
    p.add_argument('--cache',required=True)
    p.add_argument('--resume')
    args=p.parse_args()
    if args.resume:
        u=urlparse(args.resume)
        if not draft_id(args.resume):
            p.error('--resume must be an existing HTTPS Xiumi draft URL')
    cache=Path(args.cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    os.environ['SE_CACHE_PATH']=str(cache)
    temp=cache/'temp';temp.mkdir(exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(temp)
    driver=open_session(args.browser,args.profile)
    if args.resume:driver.get(args.resume)
    print('SESSION_READY: driver, import_new, snapshot, save, reopen, replace_paragraph are available.',flush=True)
    print('Keep this interactive process alive. Do not call driver.quit() until review is finished.',flush=True)
    return driver

if __name__=='__main__':
    driver=main()
