# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Offline safety regressions; mocks never connect to a real browser/account."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from selenium.common.exceptions import StaleElementReferenceException


SCRIPT = Path(__file__).resolve().parents[1] / "wechat-editorial-workflow/scripts/same_session.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("article_session_under_test", SCRIPT)
SESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SESSION)


class OnePollWait:
    def __init__(self, driver, *_args, **_kwargs):
        self.driver = driver

    def until(self, predicate):
        result = predicate(self.driver)
        if not result:
            raise AssertionError("Synthetic state never satisfied the condition")
        return result


class InvalidatedElement:
    @property
    def text(self):
        raise StaleElementReferenceException("Synthetic old node was reused after rendering")


def edit_driver(texts):
    """Input replaces exactly the selected index and invalidates any old node."""
    driver = Mock()
    driver.texts = list(texts)
    driver.selected = None
    active = Mock()
    driver.switch_to.active_element = active
    driver.find_elements.side_effect = AssertionError("Do not retain old paragraph handles")

    def execute(script, *args):
        if "p.children.length" in script:
            driver.selected = args[0]
            return {"ok": True, "element": InvalidatedElement()}
        return list(driver.texts)

    def enter(value):
        fresh = driver.texts.copy()
        fresh[driver.selected] = "" if value == SESSION.Keys.BACKSPACE else value
        driver.texts = fresh

    driver.execute_script.side_effect = execute
    active.send_keys.side_effect = enter
    return driver


class SessionRegressions(unittest.TestCase):
    def test_title_only_change_is_saved(self):
        driver = Mock()
        driver.current_url = "https://xiumi.us/studio/v5#/paper/for/123/cube/0"
        body = [{"html": "<p>unchanged body</p>"}]
        driver._wf_confirmed_signature = SESSION._signature(body, {"input.title": "Old title"})
        driver.execute_script.return_value = {"notice": "", "busy": False, "seen": True}
        with patch.object(SESSION, "snapshot", return_value=body), \
                patch.object(SESSION, "_metadata", return_value={"input.title": "New title"}), \
                patch.object(SESSION, "WebDriverWait", OnePollWait):
            result = SESSION.save(driver)
        self.assertEqual(result["state"], "save_observed")
        driver.find_element.return_value.click.assert_called_once()

    def test_save_notice_classification(self):
        for notice, expected in (("图文数量已达上限", "capacity"),
                                 ("Storage quota exceeded", "capacity"),
                                 ("请重新登录", "login"),
                                 ("保存失败，请稍后重试", "error"),
                                 ("保存中，请稍候", None)):
            with self.subTest(notice=notice):
                self.assertEqual(SESSION.classify_save_state({"notice": notice}), expected)

    def test_blocked_save_preserves_page_and_prevents_reload(self):
        driver = Mock()
        driver.current_url = "https://xiumi.us/studio/v5#/paper/for/new/cube/0"
        driver.execute_script.return_value = {"notice": "图文数量已达上限", "busy": False, "seen": True}
        with patch.object(SESSION, "snapshot", return_value=[{"html": "synthetic"}]), \
                patch.object(SESSION, "WebDriverWait", OnePollWait):
            with self.assertRaisesRegex(SESSION.SaveBlocked, "capacity"):
                SESSION.save(driver)
            self.assertIs(driver._wf_save_uncertain, True)
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                SESSION.reopen(driver)
        driver.refresh.assert_not_called()
        driver.find_element.return_value.click.assert_called_once()

    def test_existing_checkpoint_refuses_duplicate_without_browser_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "article.html"
            source.write_text("<p>synthetic</p>", encoding="utf-8")
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text(json.dumps({"phase": "reserved"}), encoding="utf-8")
            driver = Mock()
            with patch.object(SESSION, "xp") as importer:
                with self.assertRaisesRegex(RuntimeError, "already started"):
                    SESSION.import_new(driver, source, "Synthetic", checkpoint)
                self.assertEqual(importer.mock_calls, [])
            self.assertEqual(driver.mock_calls, [])
            self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8")), {"phase": "reserved"})

    def test_substring_in_other_paragraph_is_unchanged_after_rerender(self):
        driver = edit_driver(["前文含有目标文字", "目标文字", "另一段正文"])
        plan = {"nodes": [{"tag": "P", "role": "body", "text": t} for t in driver.texts]}
        original = copy.deepcopy(plan)
        with patch.object(SESSION, "WebDriverWait", OnePollWait):
            result = SESSION.replace_paragraph(driver, "目标文字", "替换结果", plan)
        self.assertEqual(driver.texts, ["前文含有目标文字", "替换结果", "另一段正文"])
        self.assertEqual(result["expected"], driver.texts)
        self.assertEqual([n["text"] for n in result["updated_plan"]["nodes"]], driver.texts)
        self.assertEqual(plan, original)
        driver.find_elements.assert_not_called()

    def test_mismatching_plan_is_rejected_before_any_input(self):
        driver = edit_driver(["实际目标段落", "其他段落"])
        plan = {"nodes": [{"tag": "P", "role": "body", "text": "计划记录的是另一篇文章"}]}
        before = driver.texts.copy()
        with patch.object(SESSION, "WebDriverWait", OnePollWait):
            with self.assertRaises(RuntimeError):
                SESSION.replace_paragraph(driver, "实际目标段落", "不应写入", plan)
        driver.switch_to.active_element.send_keys.assert_not_called()
        self.assertEqual(driver.texts, before)

    def test_loading_page_is_not_captured_as_finished_preview(self):
        driver=Mock()
        driver.current_window_handle='editor'
        frame=Mock()
        frame.get_attribute.return_value='https://v.xiumius.cn/board/test'
        frame.is_displayed.return_value=True
        driver.find_elements.return_value=[frame]
        driver.find_element.return_value.text='Loading...'
        with tempfile.TemporaryDirectory() as directory, patch.object(SESSION,'WebDriverWait',OnePollWait):
            with self.assertRaises(AssertionError):
                SESSION.capture_saved_preview(driver,Path(directory)/'preview.png',expected_text='合成正文')
        self.assertFalse(any(c.args[0]=='Page.captureScreenshot' for c in driver.execute_cdp_cmd.call_args_list))
        driver.close.assert_called_once()
        driver.switch_to.window.assert_called_with('editor')


if __name__ == "__main__":
    unittest.main()
