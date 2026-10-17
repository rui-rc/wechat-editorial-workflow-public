"""Static preflight for the conservative, custom single-column HTML route.

This reports source risks, not Xiumi compatibility, institutional compliance or
visual quality. Never use it to flatten an existing native Xiumi component.
Exit codes: 0=no detected source risks; 1=targeted checks needed; 2=repair source.
"""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re


class LayoutCheck(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors=[];self.risks=[];self.sections=0;self.section_depth=0
        self.paragraph_depth=0;self.head_depth=0;self.images=[];self.structural_stack=[]

    def finding(self,level,code,message):
        getattr(self,level).append({'line':self.getpos()[0],'code':code,'message':message})

    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('section','div','p'):self.structural_stack.append(tag)
        if tag=='head':self.head_depth+=1
        if tag=='section':
            if self.section_depth:self.finding('risks','nested_section','嵌套section会被当前导入器扁平化；改成顶层块，或改用原生结构并单独验证。')
            else:self.sections+=1
            self.section_depth+=1
        if tag=='div' and self.section_depth:
            self.finding('risks','nested_div','section内部div会被当前导入器转换；不要依赖其网页容器布局。')
        if tag in ('script','style','iframe','form','canvas'):
            self.finding('errors','active_or_external_layout','保守导入路径不承载'+tag+'；使用内联静态样式或相应原生组件。')
        if tag=='link' and 'stylesheet' in a.get('rel','').lower():
            self.finding('errors','stylesheet','外链样式不能作为保留外观的依据；将必要样式内联。')
        if any(k.startswith('on') for k in a):
            self.finding('errors','event_handler','HTML事件处理不能作为公众号交互实现；改用已验证的原生交互。')
        if tag in ('svg','table','video','audio'):
            self.finding('risks','special_structure',tag+'不在本路径的保守积木范围内，按专用路径验证，不自动删除。')
        if tag=='p':
            if self.paragraph_depth:self.finding('errors','nested_paragraph','p不能嵌套p；浏览器自动纠正可能改变结构和空白。')
            self.paragraph_depth+=1
        if tag in ('p','img') and not self.section_depth and not self.head_depth:
            self.finding('errors','outside_component','正文段落或图片没有顶层section承载，可能不进入样式化组件列表。')
        style=a.get('style','')
        if tag=='section' and self.section_depth==1 and 'style' in a and not re.search(r'\sstyle="',self.get_starttag_text()):
            self.finding('errors','style_serialization','顶层style统一写成style="..."，等号两侧不加空格；当前导入器不是通用属性解析器。')
        if tag=='section' and self.section_depth==1 and ('\"' in style or "'" in style):
            self.finding('errors','top_style_quotes','当前导入器的顶层style解析会被内部引号截断；字体放到内层文字或使用不带引号的通用字体名。')
        if a.get('class') and not style:
            self.finding('risks','class_dependency','检查是否依赖class提供外观；类名会留下，但外部样式不会因此自动带入。')
        if re.search(r'display\s*:\s*(?:inline-)?(?:flex|grid)|position\s*:\s*(?:absolute|fixed|sticky)|\bfloat\s*:',style,re.I):
            self.finding('risks','web_layout','发现定位、浮动或多列网页布局；简单单列改为普通文档流，复杂效果优先原生。')
        if re.search(r'var\(|calc\(|(?:\d|\.)\s*(?:vw|vh|vmin|vmax)\b',style,re.I):
            self.finding('risks','runtime_css','CSS变量、计算式或视口单位需针对目标导入和窄屏检查，不能仅凭本地浏览器效果。')
        if re.search(r'box-sizing\s*:',style,re.I) and re.search(r'(?:^|;)\s*width\s*:',style,re.I):
            self.finding('risks','box_sizing','顶层样式转换会忽略box-sizing；固定宽度加padding/border时检查实际宽度。')
        if re.search(r'(?:^|;)\s*(?:height|max-height)\s*:\s*\d+(?:\.\d+)?px',style,re.I) and tag!='img':
            self.finding('risks','fixed_text_height','固定文字容器高度可能裁字；优先随内容增高，或核对完整可见性。')
        if tag=='img':
            src=a.get('src','');self.images.append(src)
            if not src:self.finding('errors','empty_image','图片缺少来源。')
            elif src.startswith(('data:','blob:')):
                self.finding('errors','temporary_image','这条样式保留路径不会自动上传已有data/blob图源；改用可读取的本地原文件或已核实的持久图源。')
            elif src.startswith('file:'):
                self.finding('risks','temporary_image','将file URI整理为当前工具支持的本地文件路径，再检查实际上传和复开加载。')
            if src and not re.search(r'\ssrc="',self.get_starttag_text()):
                self.finding('errors','image_src_quotes','图片属性统一写成src="..."，等号两侧不加空格；当前上传和替换依赖这一序列化形式。')
        if tag not in ('html','head','title','meta','body'):
            for value in a.values():self.check_placeholders(value)

    def handle_endtag(self,tag):
        if tag in ('section','div','p'):
            if not self.structural_stack or tag not in self.structural_stack:
                self.finding('errors','unexpected_close','出现多余的闭合标签：'+tag)
            elif self.structural_stack[-1]!=tag:
                self.finding('errors','crossed_structure','结构标签闭合顺序错误：'+tag)
                self.structural_stack.remove(tag)
            else:self.structural_stack.pop()
        if tag=='section':self.section_depth=max(0,self.section_depth-1)
        if tag=='p':self.paragraph_depth=max(0,self.paragraph_depth-1)
        if tag=='head':self.head_depth=max(0,self.head_depth-1)

    def handle_data(self,data):
        self.check_placeholders(data)
        if data.strip() and not self.section_depth and not self.head_depth:
            self.finding('errors','outside_text','可见文字位于顶层section之外；先明确它属于哪个组件。')

    def check_placeholders(self,value):
        if re.search(r'\{\{[^{}]+\}\}',value):
            self.finding('errors','placeholder','仍有未填写的占位项；填写已确认内容或移除无依据元素。')


def check_source(source):
    parser=LayoutCheck();parser.feed(source);parser.close()
    if '\u3000' in source:
        parser.risks.append({'line':source[:source.index('\u3000')].count('\n')+1,'code':'literal_fullwidth_space','message':'原始全角空格可能被导入器压缩；必须保留时使用&#12288;，或按规范采用CSS缩进。'})
    if not parser.sections:
        parser.finding('errors','no_components','未找到顶层section；这不是当前保守导入路径的组件结构。')
    if parser.section_depth or parser.paragraph_depth or parser.structural_stack:
        parser.finding('errors','unclosed_structure','section或p未闭合；先修正结构。')
    return {'status':'repair_source' if parser.errors else 'targeted_check' if parser.risks else 'no_source_risks_detected',
            'top_level_sections':parser.sections,'image_count':len(parser.images),'errors':parser.errors,'risks':parser.risks,
            'scope':'仅静态预检；仍需实际导入、保存复开、窄屏和当前规范检查。'}


def check_file(path):
    path=Path(path).resolve();source=path.read_text(encoding='utf-8-sig')
    result=check_source(source);parser=LayoutCheck();parser.feed(source)
    for src in parser.images:
        if not src or re.match(r'^(?:https?:|data:|blob:|file:|//)',src,re.I):continue
        image=Path(src)
        if not image.is_absolute():image=path.parent/image
        if not image.is_file():result['errors'].append({'line':None,'code':'missing_local_image','message':'本地图片不存在：'+src})
    if result['errors']:result['status']='repair_source'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('html');args=p.parse_args()
    result=check_file(args.html)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(2 if result['errors'] else 1 if result['risks'] else 0)
