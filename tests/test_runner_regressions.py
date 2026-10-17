# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Runner verdict and resume safeguards; all browser/network work is mocked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "wechat-editorial-workflow/scripts/run_article.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("article_runner_under_test", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
URL = "https://xiumi.us/studio/v5#/paper/for/123/cube/0"


class RunnerRegressions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.html, self.plan, self.checkpoint = root / "article.html", root / "article.plan.json", root / "run.json"
        self.html.write_text("<p>合成测试正文</p>", encoding="utf-8")
        self.plan.write_text(json.dumps({
            "credits": {"编辑": "测试甲", "校对": "测试乙", "审阅": "测试丙"},
            "nodes": [{"tag": "P", "role": "body", "text": "合成测试正文"}],
        }, ensure_ascii=False), encoding="utf-8")
        self.checkpoint.write_text(json.dumps({
            "phase": "save_observed", "draft_url": URL,
            "source_sha256": hashlib.sha256(self.html.read_bytes()).hexdigest(),
            "plan_sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        self.driver = Mock()
        self.driver.current_url = URL
        self.driver._wf_save_uncertain = False
        self.import_new = self.mock_function("import_new", return_value=URL)
        self.reopen = self.mock_function("reopen", return_value=[])
        self.audit = self.mock_function("audit", return_value={
            "passed": True, "errors": [], "ready_for_review": True, "image_sources": {},
        })
        self.assets = self.mock_function("verify_uploaded_assets", return_value={
            "brand-header": True, "brand-closing": True, "brand-footer": True,
        })

    def mock_function(self, name, **kwargs):
        patcher = patch.object(RUNNER, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def run_saved(self):
        return RUNNER.publish_and_check(self.driver, self.html, self.plan, "Synthetic", self.checkpoint, capture=False)

    def assert_needs_attention(self):
        state = json.loads(self.checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(state["phase"], "needs_attention")
        self.assertFalse(self.checkpoint.with_suffix(".audit.json").exists())

    def test_existing_checkpoint_resumes_without_new_draft(self):
        result = self.run_saved()
        self.import_new.assert_not_called()
        self.reopen.assert_called_once()
        self.assertEqual(result["draft_url"], URL)
        self.assertEqual(result["status"], "layout_verified_visual_review_pending")

    def test_failed_audit_cannot_be_verified(self):
        self.audit.return_value = {"passed": False, "errors": ["Synthetic content mismatch"], "image_sources": {}}
        with self.assertRaisesRegex(RuntimeError, "Saved layout failed"):
            self.run_saved()
        self.assets.assert_not_called()
        self.assert_needs_attention()

    def test_failed_brand_hash_cannot_be_verified(self):
        self.assets.return_value["brand-footer"] = False
        with self.assertRaisesRegex(RuntimeError, "brand asset"):
            self.run_saved()
        self.assert_needs_attention()

    def test_uncertain_persisted_phase_cannot_reload_after_process_restart(self):
        state=json.loads(self.checkpoint.read_text(encoding='utf-8'))
        state['phase']='filled'
        self.checkpoint.write_text(json.dumps(state),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'uncertain'):
            self.run_saved()
        self.reopen.assert_not_called()
        self.import_new.assert_not_called()

    def test_failure_does_not_leave_stale_success_as_current_report(self):
        report=self.checkpoint.with_suffix('.audit.json')
        report.write_text(json.dumps({'passed':True}),encoding='utf-8')
        self.audit.return_value={'passed':False,'errors':['Synthetic failure'],'image_sources':{}}
        with self.assertRaises(RuntimeError):
            self.run_saved()
        self.assertFalse(report.exists())
        self.assertEqual(json.loads(self.checkpoint.with_suffix('.failure.json').read_text(encoding='utf-8'))['status'],'failed')
        self.assertEqual(len(list(report.parent.glob('run.audit.previous-*.json'))),1)


if __name__ == "__main__":
    unittest.main()
