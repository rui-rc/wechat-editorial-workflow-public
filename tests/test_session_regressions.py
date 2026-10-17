"""Offline safety regressions; mocks never connect to a real browser/account."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from selenium.common.exceptions import InvalidSessionIdException, StaleElementReferenceException


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
    driver.activated = False
    driver.rich = False
    driver.text_after_click = None
    driver.target = Mock(spec=["click"])
    active = Mock()
    driver.switch_to.active_element = active
    driver.find_elements.side_effect = AssertionError("Do not retain old paragraph handles")

    def execute(script, *args):
        if "p.children.length" in script:
            index, old = args
            if driver.rich or driver.texts[index] != old or driver.texts.count(old) != 1:
                return {"ok": False, "reason": "target is rich or changed"}
            if "element:p" in script:
                return {"ok": True, "element": driver.target}
            if not driver.activated:
                return {"ok": False, "reason": "native editor was not activated"}
            driver.selected = index
            return {"ok": True}
        return list(driver.texts)

    def activate():
        driver.activated = True
        if driver.text_after_click is not None:
            driver.texts = driver.text_after_click.copy()

    def enter(value):
        fresh = driver.texts.copy()
        fresh[driver.selected] = "" if value == SESSION.Keys.BACKSPACE else value
        driver.texts = fresh

    driver.execute_script.side_effect = execute
    driver.target.click.side_effect = activate
    active.send_keys.side_effect = enter
    return driver


class SessionRegressions(unittest.TestCase):
    @patch.object(SESSION, 'dismiss_preview')
    def test_title_only_change_is_saved(self, _dismiss):
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

    @patch.object(SESSION, 'dismiss_preview')
    def test_blocked_save_preserves_page_and_prevents_reload(self, _dismiss):
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

    def test_browser_failure_keeps_reserved_identity_and_original_error(self):
        reserved = "https://xiumi.us/studio/v5#/paper/for/123/cube/0"

        class FailingBrowser:
            alive = True
            url = "https://xiumi.us/studio/v5#/paper/for/new/cube/0"

            @property
            def current_url(self):
                if not self.alive:
                    raise InvalidSessionIdException("Browser disconnected while reading URL")
                return self.url

        driver = FailingBrowser()
        original = RuntimeError("Original upload failed after draft reservation")

        def fail_upload(*_args, **_kwargs):
            driver.alive = False
            raise original

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "article.html"
            source.write_text("<p>synthetic</p>", encoding="utf-8")
            checkpoint = Path(directory) / "run.json"
            with patch.object(SESSION, "dismiss_preview"), \
                    patch.object(SESSION, "xp") as importer, \
                    patch.object(SESSION, "save", side_effect=lambda d: setattr(d, "url", reserved)), \
                    patch.object(SESSION, "WebDriverWait", OnePollWait):
                importer._resolve_content_paths.return_value = ("<p>synthetic</p>", source.parent)
                importer._prepare_xiumi_images.return_value = "<p>synthetic</p>"
                importer._fill_xiumi_body_then_images.side_effect = fail_upload
                with self.assertRaises(Exception) as caught:
                    SESSION.import_new(driver, source, "Synthetic", checkpoint)
                self.assertIs(caught.exception, original)
                importer._open_xiumi_editor.assert_called_once()
                importer._fill_xiumi_body_then_images.assert_called_once()
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(saved["phase"], "blocked")
            self.assertEqual(saved["draft_url"], reserved)
            self.assertEqual(saved["draft_id"], "123")
            self.assertEqual(saved["error"], str(original))

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
        self.assertIs(driver._wf_save_uncertain, True)
        driver.find_elements.assert_not_called()
        driver.target.click.assert_called_once()
        # Selection after activation uses fresh index/text, never the clicked handle.
        selections = [call for call in driver.execute_script.call_args_list if "createRange" in call.args[0]]
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0].args[1:], (1, "目标文字"))

    def test_rich_or_missing_paragraph_is_rejected_before_activation(self):
        for texts, rich in ((["其他段落"], False), (["目标段落"], True)):
            with self.subTest(texts=texts, rich=rich):
                driver = edit_driver(texts)
                driver.rich = rich
                with self.assertRaises(RuntimeError):
                    SESSION.replace_paragraph(driver, "目标段落", "不应写入")
                driver.target.click.assert_not_called()
                driver.switch_to.active_element.send_keys.assert_not_called()

    def test_target_changed_by_activation_is_rejected_before_input(self):
        driver = edit_driver(["目标段落", "邻居"])
        driver.text_after_click = ["目标已变化", "邻居"]
        with self.assertRaisesRegex(RuntimeError, "selection is not safe"):
            SESSION.replace_paragraph(driver, "目标段落", "不应写入")
        driver.target.click.assert_called_once()
        driver.switch_to.active_element.send_keys.assert_not_called()

    def test_mismatching_plan_is_rejected_before_any_input(self):
        driver = edit_driver(["实际目标段落", "其他段落"])
        plan = {"nodes": [{"tag": "P", "role": "body", "text": "计划记录的是另一篇文章"}]}
        before = driver.texts.copy()
        with patch.object(SESSION, "WebDriverWait", OnePollWait):
            with self.assertRaises(RuntimeError):
                SESSION.replace_paragraph(driver, "实际目标段落", "不应写入", plan)
        driver.switch_to.active_element.send_keys.assert_not_called()
        self.assertEqual(driver.texts, before)

    @patch.object(SESSION, 'dismiss_preview')
    def test_loading_page_is_not_captured_as_finished_preview(self, dismiss):
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
        dismiss.assert_called_once_with(driver)

    def test_preview_overlay_is_closed_before_save(self):
        driver = Mock()
        frame = Mock()
        frame.is_displayed.side_effect = [True, False]
        driver.find_elements.return_value = [frame]
        with patch.object(SESSION, 'WebDriverWait', OnePollWait):
            SESSION.dismiss_preview(driver)
        driver.find_element.assert_called_once_with(SESSION.By.CSS_SELECTOR, '.modal-dialog .background-mask.paper')
        driver.execute_script.assert_called_once_with('arguments[0].click()', driver.find_element.return_value)

    def test_other_dialogs_are_not_dismissed(self):
        driver = Mock()
        driver.find_elements.return_value = []
        SESSION.dismiss_preview(driver)
        driver.find_element.assert_not_called()
        driver.execute_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
