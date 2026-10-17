"""Compose small editable components and an independent source-of-truth plan."""
import argparse
import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from article_contract import credit_contract

REQUIREMENTS = Path(__file__).resolve().parents[1] / 'requirements'
DEFAULT_THEME = {'accent': '#164769', 'heading': '#164769', 'text': '#333333', 'muted': '#666666', 'on_accent': '#FFFFFF'}


class PlanParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self.paragraph = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('p', 'img'):
            node = {'tag': tag.upper(), 'role': attrs['data-wf-role'], 'text': ''}
            self.nodes.append(node)
            if tag == 'p':
                self.paragraph = node

    def handle_data(self, value):
        if self.paragraph is not None:
            self.paragraph['text'] += value

    def handle_endtag(self, tag):
        if tag == 'p':
            self.paragraph = None


def load_brand():
    manifest = json.loads((REQUIREMENTS / 'brand-assets.json').read_text(encoding='utf-8'))
    assets = {}
    for item in manifest['assets']:
        path = REQUIREMENTS / item['path']
        if not path.is_file():
            raise FileNotFoundError('Missing brand asset; follow docs/setup.md: ' + item['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Brand asset changed: ' + item['path'])
        assets[item['role']] = path
    return assets


def compose(data, output, base_dir=None):
    assets = load_brand()
    rows, extra, missing = credit_contract(data)
    # Preserve deliberate blanks in drafts; missing assignments stay in the report.
    spacing = data.get('letter_spacing', 0)
    if isinstance(spacing, bool) or spacing not in (0, 1):
        raise ValueError('letter_spacing must be 0 or 1')
    theme = {**DEFAULT_THEME, **data.get('theme', {})}
    if any(not isinstance(v, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', v) for v in theme.values()):
        raise ValueError('Theme colors must use #RRGGBB')
    blocks = data.get('blocks', [])
    if not any(b.get('type') in ('paragraph', 'lead', 'callout') for b in blocks):
        raise ValueError('At least one body paragraph is required')
    output = Path(output).resolve()
    base_dir = Path(base_dir or Path.cwd()).resolve()
    pieces = []
    esc = lambda value: html.escape(str(value), quote=True).replace('\u3000', '&#12288;')

    def local_path(value):
        p = Path(value)
        p = p if p.is_absolute() else base_dir / p
        if not p.is_file():
            raise FileNotFoundError(p)
        return p.resolve()

    def emit(inner, gap=0, background=None):
        # Top-level sections map to separate Xiumi components; inner sections do not.
        # Component padding survives text edits more reliably than paragraph margins.
        style = f'padding:0px 5px {gap}px;margin:0;box-sizing:border-box;font-size:15px;line-height:2;letter-spacing:{spacing}px'
        if background:
            style += ';background-color:' + background
        pieces.append('<section style="' + style + '">' + inner + '</section>')

    def para(text, role, size=15, align='justify', indent='2em', color=None, weight='normal', line=2):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Nonempty text required for ' + role)
        if role in ('body', 'callout'):
            text = text.lstrip(' \t\u3000')
        style = f'margin:0;padding:0;font-size:{size}px;line-height:{line};letter-spacing:{spacing}px;text-align:{align};text-indent:{indent};color:{color or theme["text"]};font-weight:{weight}'
        return '<p data-wf-role="' + role + '" style="' + style + '">' + esc(text) + '</p>'

    def picture(path, role, width='100%'):
        if not re.fullmatch(r'(?:[1-9][0-9]?(?:\.[0-9]+)?%|100%|[1-9][0-9]{0,2}px)', str(width)):
            raise ValueError('Invalid image width')
        return '<p data-wf-role="image" style="margin:0;padding:0;text-indent:0;text-align:center;line-height:0"><img data-wf-role="' + role + '" alt="' + role + '" src="' + esc(local_path(path)) + '" style="display:inline-block;width:' + str(width) + ';max-width:100%;height:auto;vertical-align:middle"></p>'

    emit(picture(assets['header'], 'brand-header'), 12)
    for i, block in enumerate(blocks):
        kind = block.get('type')
        nxt = blocks[i+1].get('type') if i+1 < len(blocks) else None
        if kind in ('paragraph', 'lead', 'callout'):
            if kind == 'callout' and block.get('head'):
                emit(para(block['head'], 'callout-head', 13, 'center', '0', theme['accent']), 8)
            role = 'callout' if kind == 'callout' else 'body'
            gap = 0 if nxt == 'blank' else 30 if nxt in ('paragraph', 'lead', 'callout') else 15
            emit(para(block['text'], role, color=theme['heading'] if kind != 'paragraph' else None), gap)
        elif kind == 'blank':
            if nxt == 'blank':
                raise ValueError('Consecutive blank blocks would double paragraph spacing')
            emit('<p data-wf-role="blank" style="margin:0;padding:0;font-size:15px;line-height:30px;text-indent:0"><br></p>')
        elif kind in ('heading', 'title', 'subtitle', 'caption', 'endnote'):
            if kind == 'heading' and block.get('kicker'):
                emit(para(block['kicker'], 'kicker', 12, 'center', '0', theme['muted']), 5)
            size = {'title':24, 'heading':18, 'subtitle':13, 'caption':13, 'endnote':12}[kind]
            emit(para(block['text'], kind, size, 'center', '0', theme['heading'] if kind in ('title','heading') else theme['muted'], 'bold' if kind in ('title','heading') else 'normal', 1.6), 12)
        elif kind == 'card':
            if block.get('badge'):
                emit(picture(block['badge'], 'card-badge', block.get('badge_width', '52px')), 5)
            emit(para(block['ribbon'], 'card-ribbon', 16, 'center', '0', theme['on_accent'], 'bold', 2), 0, theme['accent'])
            # Use component padding for visual spacing rather than empty text artifacts.
            pieces[-1] = pieces[-1].replace('padding:0px 5px 0px', 'padding:6px 5px 6px')
        elif kind == 'divider':
            emit(para(block.get('mark', '•'), 'divider-mark', 13, 'center', '0', theme['muted']), 15)
        elif kind == 'image':
            emit(picture(block['path'], 'content-image'), 12)
        else:
            raise ValueError('Unknown content block: ' + str(kind))
    emit(picture(assets['closing_mark'], 'brand-closing', '35%'))
    for row in rows + extra:
        emit(para(row['label'] + '｜' + row['value'], 'credit' if row in rows else 'credit-note', 14, 'center', '0', line=1.6))
    emit(picture(assets['footer'], 'brand-footer'))
    result = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(data.get('title','')) + '</title></head><body style="margin:0">' + ''.join(pieces) + '</body></html>'
    parser = PlanParser(); parser.feed(result)
    plan = {'schema_version':2, 'source_sha256':hashlib.sha256(result.encode('utf-8')).hexdigest(), 'mode':data.get('mode','final'), 'nodes':parser.nodes, 'credit_rows':rows, 'extra_credits':extra, 'pending_credits':missing, 'theme':theme, 'visual_expectations':{'card-ribbon': {'background':theme['accent'], 'font':'16px'}} if any(b.get('type')=='card' for b in blocks) else {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding='utf-8')
    output.with_suffix('.plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('input'); p.add_argument('output')
    args = p.parse_args()
    source = Path(args.input).resolve()
    print(compose(json.loads(source.read_text(encoding='utf-8')),args.output,source.parent))
