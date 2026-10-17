"""Draft assignment handling, using synthetic brand files and no account data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'wechat-editorial-workflow/scripts'))
import compose_article


class DraftCredits(unittest.TestCase):
    def test_requested_blank_is_preserved_but_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); image=root/'synthetic.png'; image.write_bytes(b'synthetic')
            data={'mode':'draft','credits':{'编辑':'测试甲','校对':'','审阅':'测试乙'},
                  'blocks':[{'type':'paragraph','text':'合成测试正文。'}]}
            with patch.object(compose_article,'load_brand',return_value=dict.fromkeys(('header','closing_mark','footer'),image)):
                output=compose_article.compose(data,root/'article.html')
                plan=json.loads(output.with_suffix('.plan.json').read_text(encoding='utf-8'))
                self.assertIn('校对｜',[n['text'] for n in plan['nodes']])
                self.assertEqual(plan['pending_credits'],['校对'])
                self.assertNotIn('待确认',output.read_text(encoding='utf-8'))
                data['mode']='final'
                with self.assertRaisesRegex(ValueError,'Unconfirmed credit'):
                    compose_article.compose(data,root/'final.html')


if __name__=='__main__':
    unittest.main()
