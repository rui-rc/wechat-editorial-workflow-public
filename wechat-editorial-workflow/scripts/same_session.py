# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Run with python -i. Keeps one WebDriver for import, inspection and edits.
Requires the pinned all-to-xiumi 0.1.0 source described in importer-setup.md.
Does not read or copy credentials. Commands operate only in this browser.
"""
import argparse
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


def reopen(driver):
    driver.refresh()
    WebDriverWait(driver,60).until(lambda d: len(snapshot(d))>0 and not any(
        e.is_displayed() for e in d.find_elements(By.CSS_SELECTOR,'section.tn-loading-overlap')))
    return snapshot(driver)


def draft_id(url):
    u=urlparse(url)
    m=re.fullmatch(r'/paper/for/([1-9][0-9]*)/cube/[0-9]+',u.fragment)
    return m.group(1) if u.scheme=='https' and u.netloc=='xiumi.us' and m else None


def save(driver):
    button=driver.find_element(By.CSS_SELECTOR,'button.btn-img.op-btn.save')
    # The observed editor disables this button while isSavingShowData is true.
    driver.execute_script("""const b=arguments[0];
    if(b.__saveObserver)b.__saveObserver.disconnect();
    b.__saveSeen=false;
    b.__saveObserver=new MutationObserver(rs=>{
      if(rs.some(r=>r.attributeName==='disabled'&&(r.oldValue!==null||b.disabled)))b.__saveSeen=true;
    });b.__saveObserver.observe(b,{attributes:true,attributeOldValue:true,attributeFilter:['disabled']});""",button)
    button.click()
    try:
        WebDriverWait(driver,40,poll_frequency=0.1).until(lambda d:
            d.execute_script('return arguments[0].__saveSeen && !arguments[0].disabled',button))
    finally:
        driver.execute_script('arguments[0].__saveObserver.disconnect()',button)
    # Completion barrier only; caller must still reload and compare persisted content.



def import_new(driver, html_path, title):
    """New drafts only. Never use this to overwrite an existing article."""
    path=Path(html_path).resolve()
    html,base=xp._resolve_content_paths(path,'')
    html=xp._prepare_xiumi_images(html,base)
    xp._open_xiumi_editor(driver,'https://xiumi.us/studio/v5?lang=zh_CN#/',300,30)
    if '/for/new/' not in driver.current_url:
        raise RuntimeError('Refusing to replace an existing draft')
    xp._fill_xiumi_fields(driver,title,'','','')
    xp._fill_xiumi_body_then_images(driver,html,base,preserve_styles=True)
    save(driver)
    WebDriverWait(driver,40).until(lambda d: draft_id(d.current_url))
    if driver.find_element(By.CSS_SELECTOR,'input.title').get_attribute('value') != title:
        raise RuntimeError('Saved editor title does not match')
    return driver.current_url


def replace_paragraph(driver, old, new):
    matches=[p for p in driver.find_elements(By.CSS_SELECTOR,'div[contenteditable="true"] p')
             if p.text==old]
    if len(matches)!=1:
        raise RuntimeError('Expected exactly one matching paragraph')
    p=matches[0]
    if p.find_elements(By.CSS_SELECTOR,'*'):
        raise RuntimeError('Only plain-text paragraphs may be replaced')
    first=snapshot(driver)
    selected=driver.execute_script("""const p=arguments[0],e=p.closest('[contenteditable="true"]');
    e.focus();const r=document.createRange();r.selectNodeContents(p);
    const s=window.getSelection();s.removeAllRanges();s.addRange(r);
    return document.activeElement===e && s.toString()===p.textContent;""",p)
    if not selected:raise RuntimeError('Selection did not remain in target editor')
    driver.switch_to.active_element.send_keys(new if new else Keys.BACKSPACE)
    if p.text != new:raise RuntimeError('Paragraph replacement failed')
    current=snapshot(driver)
    if [c['text'] for c in current] != [c['text'].replace(old,new,1) for c in first]:
        raise RuntimeError('Unexpected text outside the target paragraph changed')


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
