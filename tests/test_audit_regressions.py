# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Synthetic, offline regressions for saved article evidence; no account or draft data.

Run: python -m unittest discover -s tests -p test_audit_regressions.py -v
The legacy adapter lets the same counterexamples demonstrate old false positives.
"""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "wechat-editorial-workflow/scripts/audit_article.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("article_audit_under_test", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
LABELS = ("编辑", "校对", "审阅")


def fixture(gap=30):
    """A coherent article: two body paragraphs, one spacer, three credit rows."""
    nodes, expected = [], []

    def add(role, text, top, height, *, tag="P", width=300, image=None):
        body = role in ("body", "callout")
        style = dict(font="15px" if body or role == "blank" else "14px",
                     line="30px" if body or role == "blank" else "22.4px",
                     spacing="0px", align="justify" if body else "center",
                     indent="30px" if body else "0px", mt="0px", mb="0px",
                     ml="0px", mr="0px", pl="0px", pr="0px")
        nodes.append(dict(tag=tag, alt=role if tag == "IMG" else None,
                          role="unmarked", text=text, style=style,
                          rect=dict(top=top, bottom=top + height, width=width, scale=1),
                          horizontal=dict(left=5, right=5), descendants=[], img=image))
        expected.append(dict(tag=tag, role=role, text=text))

    def image(role, top, height, width=300):
        add("image", "", top, height, width=width)
        add(role, "", top, height, tag="IMG", width=width,
            image=dict(src="https://img.xiumi.us/synthetic/" + role + ".png",
                       loaded=True, width=width * 2, height=height * 2))

    image("brand-header", 0, 20)
    add("body", "第一段用于检验正文规范。", 20, 60)
    add("blank", " ", 80, gap)
    add("body", "第二段用于检验保存后的内容。", 80 + gap, 60)
    end = 140 + gap
    image("brand-closing", end, 20, 120)
    end += 20
    credits = dict(zip(LABELS, ("测试甲", "测试乙", "测试丙")))
    for label, value in credits.items():
        add("credit", label + "｜" + value, end, 22.4)
        end += 22.4
    image("brand-footer", end, 100)
    evidence = dict(nodes=nodes, cells=[dict(style={}, scroll=300, width=300, ancestors=[])])
    return evidence, dict(nodes=expected, credits=credits)


def evaluate(evidence, plan):
    evidence, plan = copy.deepcopy(evidence), copy.deepcopy(plan)
    if hasattr(AUDIT, "audit_evidence"):
        return AUDIT.audit_evidence(evidence, plan)

    class RecordedDriver:
        def execute_script(self, *_args):
            return evidence
    return AUDIT.audit(RecordedDriver(), plan)


class AuditRegressions(unittest.TestCase):
    def assert_passes(self, evidence, plan):
        result = evaluate(evidence, plan)
        self.assertTrue(result["passed"], result.get("errors"))
        return result

    def assert_fails(self, evidence, plan):
        result = evaluate(evidence, plan)
        self.assertFalse(result["passed"], "Malformed evidence incorrectly passed")
        self.assertTrue(result["errors"], "Failures need actionable diagnostics")
        return result

    def test_pure_evidence_entrypoint_exists(self):
        self.assertTrue(callable(getattr(AUDIT, "audit_evidence", None)))

    def test_blank_supported_when_total_body_gap_is_30(self):
        self.assert_passes(*fixture())

    def test_blank_cannot_hide_45px_body_gap(self):
        self.assert_fails(*fixture(gap=45))

    def test_gap_comes_from_geometry_not_a_required_margin_property(self):
        evidence, plan = fixture()
        del evidence["nodes"][3]
        del plan["nodes"][3]
        self.assert_passes(evidence, plan)

    def test_callout_obeys_body_typography(self):
        evidence, plan = fixture()
        plan["nodes"][4]["role"] = "callout"
        self.assert_passes(evidence, plan)
        evidence["nodes"][4]["style"].update(font="99px", indent="0px")
        self.assert_fails(evidence, plan)

    def test_unknown_nonempty_role_cannot_bypass_checks(self):
        evidence, plan = fixture()
        plan["nodes"][4]["role"] = "unrecognised-design"
        self.assert_fails(evidence, plan)

    def test_brand_images_preserve_aspect_ratio(self):
        for role in ("brand-header", "brand-closing", "brand-footer"):
            with self.subTest(role=role):
                evidence, plan = fixture()
                index = next(i for i, node in enumerate(plan["nodes"]) if node["role"] == role)
                # Width only: no unrelated footer-adjacency error can mask this check.
                evidence["nodes"][index]["rect"]["width"] /= 2
                self.assert_fails(evidence, plan)

    def test_plan_cannot_remove_an_audit_level(self):
        evidence, plan = fixture()
        del plan["credits"]["校对"]
        index = next(i for i, node in enumerate(plan["nodes"]) if node["text"].startswith("校对｜"))
        removed_height = evidence["nodes"][index]["rect"]["bottom"] - evidence["nodes"][index]["rect"]["top"]
        del evidence["nodes"][index]
        del plan["nodes"][index]
        for node in evidence["nodes"][index:]:
            node["rect"]["top"] -= removed_height
            node["rect"]["bottom"] -= removed_height
        self.assert_fails(evidence, plan)

    def test_legacy_three_credit_rows_remain_supported(self):
        evidence, plan = fixture()
        plan["credit_rows"] = [dict(label=k, value=v) for k, v in plan.pop("credits").items()]
        self.assert_passes(evidence, plan)

    def test_credit_dict_insertion_order_does_not_change_role_order(self):
        evidence, plan = fixture()
        plan["credits"] = dict(reversed(list(plan["credits"].items())))
        self.assert_passes(evidence, plan)

    def test_pending_name_is_never_ready_for_review(self):
        for value in ("", "待确认"):
            for mode in ("draft", "final"):
                with self.subTest(value=value, mode=mode):
                    evidence, plan = fixture()
                    plan["mode"] = mode
                    plan["credits"]["校对"] = value
                    index = next(i for i, node in enumerate(plan["nodes"]) if node["text"].startswith("校对｜"))
                    plan["nodes"][index]["text"] = evidence["nodes"][index]["text"] = "校对｜" + value
                    result = evaluate(evidence, plan)
                    self.assertIs(result.get("ready_for_review"), False)
                    if mode == "draft":
                        self.assertTrue(result["passed"], result.get("errors"))
                    else:
                        self.assertFalse(result["passed"])

    def test_image_wrapper_with_image_is_not_a_stray_empty_paragraph(self):
        self.assert_passes(*fixture())

    def test_actual_body_text_loss_is_rejected(self):
        evidence, plan = fixture()
        evidence["nodes"][2]["text"] = "第一段"
        self.assert_fails(evidence, plan)

    def test_nested_text_cannot_override_body_font(self):
        evidence, plan = fixture()
        nested = dict(evidence["nodes"][2]["style"], font="22px")
        evidence["nodes"][2]["descendants"].append(nested)
        self.assert_fails(evidence, plan)


if __name__ == "__main__":
    unittest.main()
