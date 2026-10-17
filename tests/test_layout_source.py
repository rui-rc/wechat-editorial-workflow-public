from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'wechat-editorial-workflow/scripts'))
from check_layout_source import check_source

class SourceChecks(unittest.TestCase):
    def test_simple_editable_sections_pass(self):
        source='<html><head><title>试样</title></head><body><section style="background-color:#701111"><p style="font-size:24px">标题</p></section><section><p>正文<strong>重点</strong></p><p><img src="assets/photo.jpg"></p></section></body></html>'
        report=check_source(source)
        self.assertEqual(report['status'],'no_source_risks_detected')
        self.assertEqual(report['top_level_sections'],2)
        self.assertEqual(report['image_count'],1)

    def test_nested_layout_is_a_risk_not_a_platform_ban(self):
        report=check_source('<section><div style="display:grid"><section><p>标题</p></section></div></section>')
        self.assertFalse(report['errors'])
        self.assertEqual(report['status'],'targeted_check')
        self.assertTrue({'nested_div','nested_section','web_layout'}<={x['code'] for x in report['risks']})

    def test_unfilled_sample_cannot_be_imported_as_finished_content(self):
        report=check_source('<section><p>{{主标题}}</p></section>')
        self.assertIn('placeholder',[x['code'] for x in report['errors']])

    def test_external_css_and_unwrapped_text_are_reported(self):
        report=check_source('<head><link rel="stylesheet" href="theme.css"></head><p>遗漏正文</p><section><p>正文</p></section>')
        self.assertTrue({'stylesheet','outside_component'}<={x['code'] for x in report['errors']})

    def test_image_and_clipping_risks_do_not_modify_source(self):
        source='<section style="height:100px"><p>长文</p><p><img src="data:image/png;base64,AA=="></p></section>'
        report=check_source(source)
        self.assertIn('fixed_text_height',[x['code'] for x in report['risks']])
        self.assertIn('temporary_image',[x['code'] for x in report['errors']])
        self.assertEqual(source,'<section style="height:100px"><p>长文</p><p><img src="data:image/png;base64,AA=="></p></section>')

    def test_importer_quote_limits_are_not_missed(self):
        report=check_source('''<section style="font-family:'Noto Serif',serif;color:red"><p>标题</p><p><img src='local.png'></p></section>''')
        self.assertTrue({'top_style_quotes','image_src_quotes'}<={x['code'] for x in report['errors']})

    def test_fullwidth_entity_avoids_literal_whitespace_risk(self):
        literal=check_source('<section><p>\u3000\u3000正文</p></section>')
        entity=check_source('<section><p>&#12288;&#12288;正文</p></section>')
        self.assertIn('literal_fullwidth_space',[x['code'] for x in literal['risks']])
        self.assertNotIn('literal_fullwidth_space',[x['code'] for x in entity['risks']])

    def test_extra_and_crossed_structural_closings_cannot_pass(self):
        for source in ('</section><section><p>正文</p></section>',
                       '<section><p>甲</p></section></section><section><p>乙</p></section>',
                       '<section><p>正文</section></p>'):
            with self.subTest(source=source):
                self.assertEqual(check_source(source)['status'],'repair_source')

    def test_attribute_spacing_that_breaks_importer_is_reported(self):
        report=check_source('<section style = "color:red"><p><img src = "picture.png"></p></section>')
        self.assertTrue({'style_serialization','image_src_quotes'}<={x['code'] for x in report['errors']})

if __name__=='__main__':unittest.main()
