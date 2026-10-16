# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Inspect rendered article rules; run after saving and reopening in the same driver."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen


def verify_uploaded_assets(image_sources):
    manifest=json.loads((Path(__file__).resolve().parents[1]/'requirements/brand-assets.json').read_text(encoding='utf-8'))
    roles={'header':'brand-header','closing_mark':'brand-closing','footer':'brand-footer'}
    result={}
    for asset in manifest['assets']:
        role=roles[asset['role']]
        url=image_sources[role]
        if url.startswith('//'):url='https:'+url
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname!='img.xiumi.us':
            raise ValueError('Expected a persisted Xiumi CDN image')
        original=urlunsplit((u.scheme,u.netloc,u.path,'',''))
        with urlopen(original,timeout=25) as response:
            digest=hashlib.sha256(response.read()).hexdigest()
        result[role]=digest==asset['sha256']
    return result


def audit(driver, plan, expected_image_sources=None):
    credits=plan['credits']
    result = driver.execute_script("""
    const cells=[...document.querySelectorAll('div[contenteditable="true"]')].filter(e=>e.offsetWidth>0);
    const elements=cells.flatMap(c=>[...c.querySelectorAll('p,img')]);
    while(elements.length && elements.at(-1).tagName==='P' && !elements.at(-1).textContent.trim() && !elements.at(-1).querySelector('img'))elements.pop();
    const style=e=>{const s=getComputedStyle(e);return {font:s.fontSize,line:s.lineHeight,spacing:s.letterSpacing,align:s.textAlign,indent:s.textIndent,mt:s.marginTop,mb:s.marginBottom,ml:s.marginLeft,mr:s.marginRight,pl:s.paddingLeft,pr:s.paddingRight}};
    return {nodes:elements.map(e=>({tag:e.tagName,alt:e.getAttribute('alt'),role:'unmarked',text:e.textContent,style:style(e),
      rect:{top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,width:e.getBoundingClientRect().width,scale:e.offsetWidth?e.getBoundingClientRect().width/e.offsetWidth:1},
      horizontal:(()=>{const root=e.closest('.tn-page');if(!root)return null;const r=root.getBoundingClientRect(),b=e.getBoundingClientRect(),scale=r.width/root.offsetWidth;return {left:(b.left-r.left)/scale,right:(r.right-b.right)/scale};})(),
      descendants:[...e.querySelectorAll('span,strong,em,a')].filter(x=>x.textContent.trim()).map(style),
      img:e.tagName==='IMG'?{src:e.getAttribute('src'),loaded:e.complete&&e.naturalWidth>0,width:e.naturalWidth,height:e.naturalHeight}:null})),
      cells:cells.filter(c=>c.textContent.trim()||c.querySelector('img')).map(c=>({style:style(c),scroll:c.scrollWidth,width:c.clientWidth,ancestors:(()=>{let a=[];for(let p=c.parentElement;p&&a.length<8;p=p.parentElement){a.push({tag:p.tagName,classes:p.className,style:style(p)});if(p.tagName==='ARTICLE')break;}return a;})()}))};
    """)
    errors=[]
    nodes=result['nodes']
    if len(nodes)!=len(plan['nodes']):errors.append('Article node count differs from the composition plan')
    for i,(n,expected) in enumerate(zip(nodes,plan['nodes'])):
        if n['tag']!=expected['tag'] or n['text']!=expected['text']:
            errors.append(f'Article node {i+1} differs from expected content or order')
        n['role']=expected['role']
        if n['tag']=='IMG' and n['alt']!=expected['role']:errors.append('Image role differs from source plan')
    body=[n for n in nodes if n['role']=='body']
    if not body:errors.append('No marked body paragraphs found')
    for i,n in enumerate(body):
        s=n['style'];raw=n['text']
        if not (s['font']=='15px' and s['line']=='30px' and s['align']=='justify' and s['spacing'] in ('0px','normal','1px')):
            errors.append(f'Body {i+1}: typography mismatch')
        css=s['indent']=='30px' and not raw.startswith((' ','\t','\u3000'))
        manual=s['indent']=='0px' and raw.startswith('\u3000\u3000') and not raw[2:].startswith((' ','\t','\u3000'))
        if not (css or manual):errors.append(f'Body {i+1}: indentation mismatch')
        if any(d['font']!='15px' or d['line']!='30px' or d['spacing'] not in ('0px','normal','1px') for d in n['descendants']):
            errors.append(f'Body {i+1}: nested text overrides typography')
        if any(s[k]!='0px' for k in ('ml','mr','pl','pr')):errors.append(f'Body {i+1}: extra horizontal spacing')
        h=n['horizontal']
        if h is None or abs(h['left']-5)>1 or abs(h['right']-5)>1:errors.append(f'Body {i+1}: effective margins are not 5px')
    content=[n for n in nodes if n['role'] not in ('image',)]
    for a,b in zip(content,content[1:]):
        if a['role']==b['role']=='body':
            if a['style']['mb']!='30px' or b['style']['mt']!='0px':errors.append('Paragraph gap must be one 30px line')
            if abs((b['rect']['top']-a['rect']['bottom'])/a['rect']['scale']-30)>1:errors.append('Rendered paragraph gap is not 30px')
    for c in result['cells']:
        # Effective page-to-paragraph geometry above includes all intervening containers.
        if c['scroll']>c['width']+1:errors.append('Content overflows horizontally')
    roles=[n['role'] for n in content]
    if 'unmarked' in roles:errors.append('Unmarked content can bypass layout checks')
    if not roles or roles[0]!='brand-header':errors.append('Missing first brand image')
    if roles[-5:]!=['brand-closing','credit','credit','credit','brand-footer']:
        errors.append('Footer must be closing mark, three credit rows, final image')
    credit_nodes=[n for n in content if n['role']=='credit']
    for a,b in zip(content[-4:],content[-3:]):
        if abs((b['rect']['top']-a['rect']['bottom'])/a['rect']['scale'])>1:errors.append('Credit block and footer must be adjacent')
    rows=[n['text'] for n in credit_nodes]
    if rows!=[r+'｜'+credits[r] for r in ('编辑','校对','审阅')]:errors.append('Three credit rows differ from article assignment')
    images=[n for n in content if n['img']]
    if any(not n['img']['loaded'] for n in images):errors.append('An image did not load')
    observed={n['role']:n['img']['src'] for n in images if n['role'].startswith('brand-')}
    if len(observed)!=3:errors.append('Expected three fixed brand assets')
    normalize=lambda u:'https:'+u if u.startswith('//') else u
    if expected_image_sources is not None and {k:normalize(v) for k,v in observed.items()}!={k:normalize(v) for k,v in expected_image_sources.items()}:errors.append('Brand image sources changed after save')
    return {'passed':not errors,'errors':errors,'image_sources':observed,'evidence':result}
