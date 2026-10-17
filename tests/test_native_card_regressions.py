"""Offline native-card text safeguards; no browser/network or private materials."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from selenium.common.exceptions import StaleElementReferenceException


SCRIPT = Path(__file__).resolve().parents[1] / "wechat-editorial-workflow/scripts/native_cards.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("native_cards_under_test", SCRIPT)
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class OnePollWait:
    def __init__(self, driver, *_args, **_kwargs):
        self.driver = driver

    def until(self, predicate):
        result = predicate(self.driver)
        if not result:
            raise AssertionError("Replacement was not observed")
        return result


def cell(text, markup):
    return {"textContent": text, "html": markup}


class NativeCardRegressions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.backup = Path(directory.name) / "before.json"
        self.driver = Mock()

    def test_repeated_cell_text_is_rejected_before_input(self):
        before = [cell("标题", "<p>标题</p>"), cell("标题", "<strong>标题</strong>")]
        with patch.object(NATIVE, "snapshot", return_value=before):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                NATIVE.replace_native_text(self.driver, "标题", "新标题", self.backup)
        self.driver.execute_script.assert_not_called()
        self.driver.execute_cdp_cmd.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_anchor_wait_requeries_after_selection_rerenders(self):
        element=Mock()
        invalidated=False
        def execute(script,*args):
            nonlocal invalidated
            if 'scrollIntoView' in script:
                return element
            if 'dispatchEvent' in script:
                invalidated=True
                return None
            if invalidated and any(arg is element for arg in args):
                raise StaleElementReferenceException('Old anchor was replaced')
            if script=='return document.activeElement.isContentEditable':
                return False
            self.assertEqual(args,('唯一锚点',))
            return True
        self.driver.execute_script.side_effect=execute
        with patch.object(NATIVE,'ActionChains'),patch.object(NATIVE,'WebDriverWait',OnePollWait):
            NATIVE.select_component_anchor(self.driver,'唯一锚点')
        self.assertTrue(invalidated)

    def test_text_split_across_runs_is_rejected_before_input(self):
        before = [cell("分开排版", "<p><strong>分开</strong><span>排版</span></p>")]
        with patch.object(NATIVE, "snapshot", return_value=before):
            with self.assertRaisesRegex(ValueError, "multiple runs"):
                NATIVE.replace_native_text(self.driver, "分开排版", "替换内容", self.backup)
        self.driver.execute_script.assert_not_called()
        self.driver.execute_cdp_cmd.assert_not_called()
        self.assertFalse(self.backup.exists())

    def run_single_edit(self, corrupt_neighbor=False):
        before = [cell("旁边也提到标题", "<p>旁边也提到标题</p>"),
                  cell("标题", '<p style="color:red"><strong>标题</strong></p>')]
        after = copy.deepcopy(before)
        after[1] = cell("新题 & <说明>", '<p style="color:red"><strong>新题 &amp; &lt;说明&gt;</strong></p>')
        if corrupt_neighbor:
            after[0]["html"] = "<p>邻居被意外改动</p>"
        element = Mock()
        self.driver.execute_script.side_effect = [element, True]
        with patch.object(NATIVE, "snapshot", side_effect=[before, after, after]), \
                patch.object(NATIVE, "WebDriverWait", OnePollWait):
            result = NATIVE.replace_native_text(self.driver, "标题", "新题 & <说明>", self.backup)
        return before, after, result

    def test_strong_and_neighbor_preserved_with_only_target_text_changed(self):
        before, after, result = self.run_single_edit()
        self.assertEqual(result["cell_index"], 1)
        self.assertEqual(result["expected_html"], [c["html"] for c in after])
        self.assertEqual(after[0], before[0])
        self.assertIn("<strong>新题 &amp; &lt;说明&gt;</strong>", result["expected_html"][1])
        self.driver.execute_cdp_cmd.assert_called_once_with("Input.insertText", {"text": "新题 & <说明>"})
        self.assertEqual(json.loads(self.backup.read_text(encoding="utf-8"))["before"], before)
        self.assertIs(self.driver._wf_save_uncertain, True)

    def test_neighbor_mutation_prevents_success_and_preserves_backup(self):
        with self.assertRaisesRegex(RuntimeError, "another cell"):
            self.run_single_edit(corrupt_neighbor=True)
        self.assertTrue(self.backup.exists())
        self.assertIs(self.driver._wf_save_uncertain, True)
        self.driver.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
