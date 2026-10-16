# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Build an editable article with the college's fixed typography and assets."""
import argparse
import hashlib
import html
import json
from html.parser import HTMLParser
from pathlib import Path

class PlanParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes=[]
        self.paragraph=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag in ('p','img'):
            node={'tag':tag.upper(),'role':attrs['data-wf-role'],'text':''}
            self.nodes.append(node)
            if tag=='p':self.paragraph=node

    def handle_data(self, data):
        if self.paragraph is not None:self.paragraph['text']+=data

    def handle_endtag(self, tag):
        if tag=='p':self.paragraph=None


REQUIREMENTS = Path(__file__).resolve().parents[1] / 'requirements'


def load_brand():
    manifest = json.loads((REQUIREMENTS / 'brand-assets.json').read_text(encoding='utf-8'))
    result = {}
    for item in manifest['assets']:
        path = REQUIREMENTS / item['path']
        if not path.is_file():
            raise FileNotFoundError('Brand asset missing; see docs/setup.md and run fetch_brand_assets.py if authorized: ' + item['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Brand asset changed: ' + item['path'])
        result[item['role']] = path
    return result


def compose(data, output):
    assets = load_brand()
    spacing = data.get('letter_spacing', 0)
    if spacing not in (0, 1):
        raise ValueError('letter_spacing must be 0 or 1')
    credits = data.get('credits')
    roles = ['编辑', '校对', '审阅']
    if not isinstance(credits, dict) or set(credits) != set(roles) or not all(isinstance(credits[r], str) and credits[r].strip() for r in roles):
        raise ValueError('Provide exactly 编辑、校对、审阅 with the names for this article')
    blocks = data.get('blocks', [])
    if not blocks or not any(b.get('type') == 'paragraph' for b in blocks):
        raise ValueError('At least one body paragraph is required')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    def image(path, role, width='100%'):
        return '<p data-wf-role="image" style="margin:0;padding:0;text-indent:0;text-align:center;line-height:0"><img data-wf-role="'+role+'" alt="'+role+'" src="'+html.escape(str(Path(path).resolve()), quote=True)+'" style="display:inline-block;width:'+width+';max-width:100%;height:auto;vertical-align:middle"></p>'
    items = [image(assets['header'], 'brand-header')]
    for i, block in enumerate(blocks):
        kind = block.get('type')
        if kind == 'paragraph':
            text = str(block.get('text', '')).lstrip(' \t\u3000')
            if not text.strip():
                raise ValueError('Empty body paragraphs are not spacing controls')
            gap = 30 if i+1 < len(blocks) and blocks[i+1].get('type') == 'paragraph' else 15
            style = f'font-size:15px;line-height:2;letter-spacing:{spacing}px;text-align:justify;text-indent:2em;margin:0 0 {gap}px;padding:0'
            items.append('<p data-wf-role="body" style="'+style+'">'+html.escape(text)+'</p>')
        elif kind == 'heading':
            items.append('<p data-wf-role="heading" style="font-size:18px;line-height:1.6;text-indent:0;text-align:left;margin:15px 0;font-weight:bold">'+html.escape(str(block['text']))+'</p>')
        elif kind == 'image':
            path = Path(block['path']).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            items.append(image(path, 'content-image'))
        elif kind == 'caption':
            items.append('<p data-wf-role="caption" style="font-size:13px;line-height:1.6;text-align:center;text-indent:0;margin:8px 0 15px;padding:0">'+html.escape(str(block['text']))+'</p>')
        else:
            raise ValueError('Unknown content block: '+str(kind))
    items.append(image(assets['closing_mark'], 'brand-closing', '35%'))
    for role in roles:
        items.append('<p data-wf-role="credit" style="font-size:14px;line-height:1.6;letter-spacing:0;text-align:center;text-indent:0;margin:0;padding:0">'+role+'｜'+html.escape(str(credits[role]).strip())+'</p>')
    items.append(image(assets['footer'], 'brand-footer'))
    title = html.escape(str(data.get('title', '')))
    result = '<!doctype html><html><head><meta charset="utf-8"><title>'+title+'</title></head><body style="margin:0"><section style="padding:0 5px;margin:0;box-sizing:border-box">'+''.join(items)+'</section></body></html>'
    output.write_text(result, encoding='utf-8')
    parser=PlanParser();parser.feed(result)
    output.with_suffix('.plan.json').write_text(json.dumps({'nodes':parser.nodes,'credits':credits},ensure_ascii=False,indent=2),encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', help='UTF-8 JSON with blocks, credits and optional letter_spacing')
    parser.add_argument('output', help='Output HTML file')
    args = parser.parse_args()
    source = Path(args.input).resolve()
    data = json.loads(source.read_text(encoding='utf-8'))
    for block in data.get('blocks', []):
        if block.get('type') == 'image' and not Path(block['path']).is_absolute():
            block['path'] = str(source.parent / block['path'])
    print(compose(data, args.output))
