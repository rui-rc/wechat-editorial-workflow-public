# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Read-only audit of persisted content against an independent authored plan."""
import copy
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen
from article_contract import BODY_ROLES, IMAGE_ROLES, KNOWN_ROLES, credit_contract


def verify_uploaded_assets(image_sources, cache=None):
    manifest = json.loads((Path(__file__).resolve().parents[1]/'requirements/brand-assets.json').read_text(encoding='utf-8'))
    mapping = {'header':'brand-header','closing_mark':'brand-closing','footer':'brand-footer'}
    results = {}
    for item in manifest['assets']:
        role = mapping[item['role']]
        url = image_sources[role]
        if url.startswith('//'):
            url = 'https:' + url
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'img.xiumi.us':
            raise ValueError('Expected a persisted Xiumi CDN image')
        original = urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))
        key = (original,item['sha256'])
        if cache is not None and key in cache:
            results[role] = cache[key]
            continue
        with urlopen(original,timeout=25) as response:
            data = response.read(10*1024*1024+1)
        if len(data)>10*1024*1024:
            raise ValueError('Brand asset exceeds expected size')
        results[role] = hashlib.sha256(data).hexdigest()==item['sha256']
        if cache is not None and results[role]:
            cache[key] = True
    return results


def _number(value):
    try:
        number=float(str(value).removesuffix('px'))
        return number if math.isfinite(number) else None
    except (TypeError,ValueError):
        return None


def _rgb(value):
    if isinstance(value,str) and len(value)==7 and value.startswith('#'):
        return 'rgb(%d, %d, %d)' % tuple(int(value[i:i+2],16) for i in (1,3,5))
    return value


def audit_evidence(evidence, plan, expected_image_sources=None):
    result=copy.deepcopy(evidence)
    errors=[]
    warnings=[]
    missing=[]
    try:
        rows,extra,missing=credit_contract(plan)
    except (ValueError,KeyError,TypeError) as exc:
        rows,extra=[],[]
        errors.append('Invalid review assignment: '+str(exc))
    if missing:
        warnings.append('Unconfirmed credits: '+', '.join(missing))
    nodes=result.get('nodes',[])
    expected=plan.get('nodes',[])
    if len(nodes)!=len(expected):
        errors.append('Article node count differs from the authored plan')
    for i,(node,want) in enumerate(zip(nodes,expected)):
        role=want.get('role')
        node['role']=role
        if role not in KNOWN_ROLES:
            errors.append(f'Node {i+1}: unknown role {role!r}')
        text_ok = node.get('text')==want.get('text')
        if role=='blank':
            text_ok = not str(node.get('text','')).strip() and not str(want.get('text','')).strip()
        if node.get('tag')!=want.get('tag') or not text_ok:
            errors.append(f'Node {i+1}: content or order differs from authored plan')
        if node.get('tag')=='IMG' and node.get('alt')!=role:
            errors.append(f'Node {i+1}: image role changed')
        if node.get('tag')=='P' and not str(node.get('text','')).strip() and role not in ('image','blank','card-badge'):
            errors.append(f'Node {i+1}: unexpected empty paragraph')
    if any(n.get('role') not in KNOWN_ROLES for n in nodes):
        errors.append('Unclassified content cannot bypass audit')
    bodies=[n for n in nodes if n.get('role') in BODY_ROLES]
    if not bodies:
        errors.append('No body paragraphs found')
    for i,node in enumerate(bodies,1):
        s=node['style'];text=node['text']
        if not (s.get('font')=='15px' and s.get('line')=='30px' and s.get('align')=='justify' and s.get('spacing') in ('0px','normal','1px')):
            errors.append(f'Body {i}: typography mismatch')
        css=s.get('indent')=='30px' and not text.startswith((' ','\t','\u3000'))
        manual=s.get('indent')=='0px' and text.startswith('\u3000\u3000') and not text[2:].startswith((' ','\t','\u3000'))
        if not (css or manual):
            errors.append(f'Body {i}: indentation mismatch')
        if any(d.get('font')!='15px' or d.get('line')!='30px' or d.get('spacing') not in ('0px','normal','1px') for d in node.get('descendants',[])):
            errors.append(f'Body {i}: inline text overrides typography')
        h=node.get('horizontal')
        if not h or abs(h['left']-5)>.75 or abs(h['right']-5)>.75:
            errors.append(f'Body {i}: effective side margins must be 5px')
    # Paragraph geometry spans intervening blank lines. Margin, padding and native
    # paragraph settings are interchangeable only if their rendered result agrees.
    content=[n for n in nodes if not (n.get('tag')=='P' and n.get('role') in ('image','card-badge'))]
    previous=None
    for node in content:
        if node.get('role')=='blank':
            rect=node.get('rect',{});scale=rect.get('scale',1) or 1
            if abs((rect.get('bottom',0)-rect.get('top',0))/scale-30)>1:
                errors.append('Declared blank line must occupy 30px')
            continue
        if node.get('role') in BODY_ROLES:
            if previous is not None:
                scale=previous['rect'].get('scale',1) or 1
                gap=(node['rect']['top']-previous['rect']['bottom'])/scale
                if abs(gap-30)>1:
                    errors.append(f'Rendered body paragraph gap is {gap:.2f}px, expected 30px')
            previous=node
        else:
            previous=None
    for cell in result.get('cells',[]):
        if cell['scroll']>cell['width']+1:
            errors.append('Content overflows horizontally')
    roles=[n.get('role') for n in content]
    if not roles or roles[0]!='brand-header':
        errors.append('Fixed header must be first')
    # A fourth line is an explicitly requested note, never a fourth audit level.
    want_tail=['brand-closing']+['credit']*3+['credit-note']*len(extra)+['brand-footer']
    legacy_tail=['brand-closing']+['credit']*(3+len(extra))+['brand-footer']
    if roles[-len(want_tail):] not in (want_tail,legacy_tail):
        errors.append('Fixed footer must contain all three review roles and the final image')
    actual_rows=[n['text'] for n in content if n.get('role') in ('credit','credit-note')]
    if actual_rows!=[x['label']+'｜'+x['value'] for x in rows+extra]:
        errors.append('Review labels or assigned names differ')
    tail=content[-(len(rows)+len(extra)+1):] if rows else []
    for left,right in zip(tail,tail[1:]):
        scale=left['rect'].get('scale',1) or 1
        if abs((right['rect']['top']-left['rect']['bottom'])/scale)>1:
            errors.append('Credit rows must remain directly above the final image')
    images=[n for n in nodes if n.get('tag')=='IMG']
    for node in images:
        image=node.get('img') or {};rect=node.get('rect') or {}
        nw,nh=image.get('width',0),image.get('height',0)
        rw=rect.get('width',0);rh=rect.get('bottom',0)-rect.get('top',0)
        if not image.get('loaded') or not all(v>0 for v in (nw,nh,rw,rh)):
            errors.append('Image missing or not loaded')
        elif abs(rw/rh/(nw/nh)-1)>.02:
            errors.append('Image aspect ratio changed: '+str(node.get('role')))
    brands=[n for n in images if str(n.get('role')).startswith('brand-')]
    observed={n['role']:n['img']['src'] for n in brands if n.get('img')}
    if len(brands)!=3 or set(observed)!= {'brand-header','brand-closing','brand-footer'}:
        errors.append('Expected exactly three fixed brand images')
    normalize=lambda u:'https:'+u if u.startswith('//') else u
    if expected_image_sources is not None and {k:normalize(v) for k,v in observed.items()}!={k:normalize(v) for k,v in expected_image_sources.items()}:
        errors.append('Brand image sources changed')
    for role,required in plan.get('visual_expectations',{}).items():
        matches=[n for n in nodes if n.get('role')==role]
        if not matches:
            errors.append('Required design element missing: '+role)
        for node in matches:
            if required.get('background') and node.get('effective_bg')!=_rgb(required['background']):
                errors.append('Required design background lost: '+role)
            if required.get('font') and node['style']['font']!=required['font']:
                errors.append('Required design font changed: '+role)
    return {'passed':not errors,'ready_for_review':not errors and not missing,'errors':errors,'warnings':warnings,'image_sources':observed,'evidence':result}


def audit(driver, plan, expected_image_sources=None):
    result = driver.execute_script("""
    const cells=[...document.querySelectorAll('div[contenteditable="true"]')].filter(e=>e.offsetWidth>0);
    const elements=cells.flatMap(c=>[...c.querySelectorAll('p,img')]);
    while(elements.length && elements.at(-1).tagName==='P' && !elements.at(-1).textContent.trim() && !elements.at(-1).querySelector('img'))elements.pop();
    const style=e=>{const s=getComputedStyle(e);return {font:s.fontSize,line:s.lineHeight,spacing:s.letterSpacing,align:s.textAlign,indent:s.textIndent,mt:s.marginTop,mb:s.marginBottom,ml:s.marginLeft,mr:s.marginRight,pl:s.paddingLeft,pr:s.paddingRight}};
    return {nodes:elements.map(e=>({tag:e.tagName,alt:e.getAttribute('alt'),role:'unmarked',text:e.textContent,style:style(e),
      effective_bg:(()=>{for(let p=e;p;p=p.parentElement){let c=getComputedStyle(p).backgroundColor;if(c!=='rgba(0, 0, 0, 0)'&&c!=='transparent')return c;if(p.classList.contains('tn-page'))break;}return 'rgba(0, 0, 0, 0)';})(),
      rect:{top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,width:e.getBoundingClientRect().width,scale:e.offsetWidth?e.getBoundingClientRect().width/e.offsetWidth:1},
      horizontal:(()=>{const root=e.closest('.tn-page');if(!root)return null;const r=root.getBoundingClientRect(),b=e.getBoundingClientRect(),scale=r.width/root.offsetWidth;return {left:(b.left-r.left)/scale,right:(r.right-b.right)/scale};})(),
      descendants:[...e.querySelectorAll('span,strong,em,a')].filter(x=>x.textContent.trim()).map(style),
      img:e.tagName==='IMG'?{src:e.getAttribute('src'),loaded:e.complete&&e.naturalWidth>0,width:e.naturalWidth,height:e.naturalHeight}:null})),
      cells:cells.filter(c=>c.textContent.trim()||c.querySelector('img')).map(c=>({style:style(c),scroll:c.scrollWidth,width:c.clientWidth,ancestors:(()=>{let a=[];for(let p=c.parentElement;p&&a.length<8;p=p.parentElement){a.push({tag:p.tagName,classes:p.className,style:style(p)});if(p.tagName==='ARTICLE')break;}return a;})()}))};
    """)
    return audit_evidence(result, plan, expected_image_sources)
