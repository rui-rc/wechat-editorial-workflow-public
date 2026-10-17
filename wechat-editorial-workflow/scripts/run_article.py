# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""One task runner: one durable draft, authored-plan verification, recoverable evidence."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from article_contract import credit_contract
from compose_article import compose
from audit_article import audit, verify_uploaded_assets
from same_session import open_session, import_new, reopen, draft_id, _checkpoint, capture_saved_preview


def publish_and_check(driver, html_path, plan_path, title, checkpoint, capture=True):
    html_path,plan_path,checkpoint=map(Path,(html_path,plan_path,checkpoint))
    digest=hashlib.sha256(html_path.read_bytes()).hexdigest()
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    credit_contract(plan)
    if plan.get('source_sha256') and plan['source_sha256']!=digest:
        raise ValueError('HTML no longer matches the authored plan')
    plan_digest=hashlib.sha256(plan_path.read_bytes()).hexdigest()
    if checkpoint.exists():
        state=json.loads(checkpoint.read_text(encoding='utf-8'))
        if state.get('source_sha256')!=digest or state.get('plan_sha256') not in (None,plan_digest):
            raise ValueError('Source changed: review an explicit revision rather than overwrite the main draft')
        if state.get('phase') not in ('save_observed','layout_verified'):
            raise RuntimeError('Previous phase is uncertain; inspect and reconcile the existing draft before resume')
        url=state.get('draft_url','')
        if not draft_id(url):
            raise RuntimeError('Previous attempt has no confirmed draft ID; inspect its page instead of recreating')
        if getattr(driver,'_wf_save_uncertain',False):
            raise RuntimeError('Unsaved page must be reconciled before resume')
        if driver.current_url!=url:
            driver.get(url)
    else:
        url=import_new(driver,html_path,title,checkpoint,plan_sha256=plan_digest)
    driver._wf_checkpoint=str(checkpoint)
    _checkpoint(checkpoint,plan_sha256=plan_digest)
    try:
        first_body=next(n['text'] for n in plan['nodes'] if n['role'] in ('body','callout'))
        reopen(driver,expected_text=first_body)
        result=audit(driver,plan)
        if not result['passed']:
            raise RuntimeError('Saved layout failed: '+'; '.join(result['errors']))
        cache=getattr(driver,'_wf_asset_cache',None)
        if not isinstance(cache,dict):cache={};driver._wf_asset_cache=cache
        proof=verify_uploaded_assets(result['image_sources'],cache=cache)
        if not all(proof.values()):
            raise RuntimeError('A fixed brand asset differs from its verified original')
        result['brand_asset_integrity']=proof
        result['draft_url']=url
        if capture:
            result['preview']=capture_saved_preview(driver,checkpoint.with_suffix('.preview.png'))
        # Human preference/approval is distinct from machine layout verification.
        result['status']='layout_verified_visual_review_pending' if result['ready_for_review'] else 'draft_layout_verified_pending_credits'
        checkpoint.with_suffix('.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        _checkpoint(checkpoint,phase='layout_verified',draft_url=url)
        return result
    except Exception as exc:
        audit_path=checkpoint.with_suffix('.audit.json')
        if audit_path.exists():
            audit_path.replace(checkpoint.with_suffix('.audit.previous-'+str(time.time_ns())+'.json'))
        checkpoint.with_suffix('.failure.json').write_text(json.dumps({'status':'failed','error':str(exc),'draft_url':url,'source_sha256':digest,'plan_sha256':plan_digest},ensure_ascii=False,indent=2),encoding='utf-8')
        _checkpoint(checkpoint,phase='needs_attention',error=str(exc),draft_url=url)
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('input',help='Authored material JSON')
    p.add_argument('--work-dir',required=True)
    p.add_argument('--browser',choices=['chrome','edge'],required=True)
    p.add_argument('--profile',required=True)
    p.add_argument('--cache',required=True)
    args=p.parse_args()
    source=Path(args.input).resolve();work=Path(args.work_dir).resolve();work.mkdir(parents=True,exist_ok=True)
    data=json.loads(source.read_text(encoding='utf-8'))
    output=compose(data,work/'article.html',source.parent)
    cache=Path(args.cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    os.environ['SE_CACHE_PATH']=str(cache)
    temp=cache/'temp';temp.mkdir(exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(temp)
    driver=open_session(args.browser,args.profile)
    # Keep driver reachable for diagnosis even if the one-shot operation raises.
    globals()['driver']=driver
    result=publish_and_check(driver,output,output.with_suffix('.plan.json'),data['title'],work/'run.json')
    print(json.dumps({k:v for k,v in result.items() if k!='evidence'},ensure_ascii=False,indent=2))
    return driver,result


if __name__=='__main__':
    driver,result=main()
