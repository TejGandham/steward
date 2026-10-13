"""Small fixes after 0.13.0: the same-family warning and the per-model warnings follow
the binding a profile launches on, not a plan binding that settings override."""

import importlib
import sys
import unittest

from test_pi_model_plan import FIREWORKS, HAIKU, OLLAMA, OPUS, REPO_ROOT, SOL, SONNET, PlanTestCase

if str(REPO_ROOT / "hooks") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "hooks"))
render = importlib.import_module("model_plan_render")
mpa = importlib.import_module("model_plan_apply")

ALL_ON_OLLAMA = {"version": 1, "roles": {"*": {"model": OLLAMA, "thinking": "high", "fallback": [FIREWORKS]}}}

# This repo's .pi/settings.json: every profile pinned to Claude.
CLAUDE_PINS = {"subagents": {"agentOverrides": {
    "steward.coder": {"model": OPUS, "thinking": "medium"},
    "steward.deep-reasoner": {"model": OPUS, "thinking": "xhigh"},
    "steward.mechanic": {"model": HAIKU, "thinking": "medium"},
    "steward.researcher": {"model": SONNET, "thinking": "low"},
    "steward.reviewer": {"model": SONNET, "thinking": "high"},
    "steward.writer": {"model": SONNET, "thinking": "medium"},
    "steward.top-reviewer": {"model": OPUS, "thinking": "xhigh"},
}}}


class SameFamilyTests(PlanTestCase):
    def test_project_pins_compare_the_launching_families(self):
        # The plan puts every role on deepseek; the repo pins coder to Opus and reviewer to
        # Sonnet. Both are claude under the built-in families, so the warning names claude.
        self.user_plan(ALL_ON_OLLAMA)
        path = self.project_settings(CLAUDE_PINS)
        result = self.run_plan(main=OPUS)
        hits = self.findings(result, code="reviewer-same-family")
        self.assertEqual(len(hits), 1)
        self.assertIn("both claude models", hits[0]["message"])
        self.assertNotIn("deepseek", hits[0]["message"])
        self.assertEqual(hits[0]["source"], path)

    def test_project_pins_to_other_family_no_warning(self):
        self.user_plan(ALL_ON_OLLAMA)
        self.project_settings({"subagents": {"agentOverrides": {
            "steward.coder": {"model": OPUS}, "steward.reviewer": {"model": "openai-codex/gpt-6.1-sol"}}}})
        result = self.run_plan(main=OPUS)
        self.assertNotIn("reviewer-same-family", self.codes(result))

    def test_without_overrides_plan_families_still_compared(self):
        self.user_plan(ALL_ON_OLLAMA)
        result = self.run_plan(main=OPUS)
        self.assertIn("reviewer-same-family", self.codes(result))

    def test_effective_same_family_warns_although_plan_differs(self):
        plan = {"version": 1, "roles": {"coder": {"model": OLLAMA}, "reviewer": {"model": "openai-codex/gpt-6.1-sol"}}}
        self.user_plan(plan)
        self.project_settings({"subagents": {"agentOverrides": {
            "steward.coder": {"model": OPUS}, "steward.reviewer": {"model": SONNET}}}})
        result = self.run_plan(main=OPUS)
        hits = self.findings(result, code="reviewer-same-family")
        self.assertEqual(len(hits), 1)
        self.assertIn("claude", hits[0]["message"])


class PerModelWarningsTests(PlanTestCase):
    PER_MODEL = ("max-tokens-low", "thinking-clamped", "below-judgment-floor")

    def per_model(self, result, subject):
        return [f for f in result["findings"] if f["code"] in self.PER_MODEL and f.get("subject") == subject]

    # Frontmatter launches the profiles (no settings override); the plan binding is on a
    # 16K model with an unsupported level, below the judgment floor.
    PLAN_16K = {"version": 1, "judgmentModels": ["amorphic/claude-opus-5*"],
                "roles": {"*": {"model": OLLAMA, "thinking": "xhigh"}}}

    def test_plan_binding_not_launched_gets_no_per_model_warnings(self):
        # The session findings stay quiet about the plan binding; drift says apply
        # and points at the preview; the plan-level warnings are reported apart.
        self.user_plan(self.PLAN_16K)
        result = self.run_plan(main=OPUS)
        self.assertEqual(self.per_model(result, "plan binding"), [])
        drift = self.findings(result, code="binding-drift", role="coder")
        self.assertTrue(drift)
        self.assertIn("preview lists", drift[0]["message"])
        plan_codes = {(f["code"], f["role"]) for f in result["planWarnings"]}
        self.assertIn(("max-tokens-low", "coder"), plan_codes)
        self.assertIn(("thinking-clamped", "coder"), plan_codes)
        self.assertIn(("below-judgment-floor", "deep-reasoner"), plan_codes)
        self.assertTrue(all(f["subject"] == "plan binding" for f in result["planWarnings"]))

    def test_session_block_omits_plan_warnings(self):
        self.user_plan(self.PLAN_16K)
        result = self.run_plan(main=OPUS)
        for capped in (True, False):
            block = render.render_block(result, capped=capped)
            self.assertNotIn("output tokens", block)
            self.assertNotIn("is clamped to", block)

    def test_check_report_has_plan_binding_section(self):
        self.user_plan(self.PLAN_16K)
        report = render.render_report(self.run_plan(main=OPUS))
        self.assertIn("## Plan binding", report)
        section = report.split("## Plan binding", 1)[1].split("\n## ", 1)[0]
        self.assertIn("max-tokens-low (steward.coder", section)
        self.assertIn("thinking-clamped (steward.coder", section)
        self.assertIn("below-judgment-floor (steward.deep-reasoner", section)

    def test_check_report_plan_section_says_none(self):
        self.user_plan(ALL_ON_OLLAMA)
        self.user_settings({"subagents": {"agentOverrides": {
            "steward.%s" % r: {"model": OLLAMA, "thinking": "high"} for r in (
                "coder", "researcher", "writer", "mechanic", "reviewer", "deep-reasoner", "top-reviewer")}}})
        result = self.run_plan(main=OPUS)
        self.assertEqual(result["planWarnings"], [])
        section = render.render_report(result).split("## Plan binding\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(section.endswith("\nNone."))

    def test_apply_preview_lists_plan_warnings(self):
        self.user_plan(self.PLAN_16K)
        result = mpa.apply(self.facts(main=OPUS), env=self.env, dry_run=True)
        self.assertIn(("max-tokens-low", "coder"), {(f["code"], f["role"]) for f in result["planWarnings"]})
        self.assertIn("Plan binding warnings:", result["report"])
        self.assertIn("allows only 16384 output tokens", result["report"])

    def test_effective_binding_carries_the_warnings(self):
        self.user_plan(ALL_ON_OLLAMA)
        self.user_settings({"subagents": {"agentOverrides": {
            "steward.coder": {"model": OLLAMA, "thinking": "high"},
            "steward.writer": {"model": OLLAMA, "thinking": "high"}}}})
        result = self.run_plan(main=OPUS)
        low = self.findings(result, code="max-tokens-low")
        self.assertEqual({(f["role"], f["subject"]) for f in low},
                         {("coder", "effective binding"), ("writer", "effective binding")})


class ReviewerMainFamilyTests(PlanTestCase):
    PLAN = {"version": 1, "roles": {
        "coder": {"model": OLLAMA},
        "reviewer": {"model": SOL, "byMainProvider": {"amorphic": {"model": SOL}}}}}

    def test_override_to_main_family_is_not_blamed_on_by_main_provider(self):
        # byMainProvider keeps the reviewer off claude; a settings pin puts it on Sonnet.
        self.user_plan(self.PLAN)
        self.user_settings({"subagents": {"agentOverrides": {"steward.reviewer": {"model": SONNET}}}})
        result = self.run_plan(main=OPUS)
        self.assertFalse(self.findings(result, code="reviewer-main-family"))

    def test_plan_on_main_family_warns_although_override_moves_it(self):
        plan = {"version": 1, "roles": {
            "coder": {"model": OLLAMA},
            "reviewer": {"model": SOL, "byMainProvider": {"amorphic": {"model": SONNET}}}}}
        self.user_plan(plan)
        self.user_settings({"subagents": {"agentOverrides": {"steward.reviewer": {"model": SOL}}}})
        result = self.run_plan(main=OPUS)
        hits = self.findings(result, code="reviewer-main-family")
        self.assertEqual(len(hits), 1)
        self.assertIn("byMainProvider.amorphic", hits[0]["message"])


if __name__ == "__main__":
    unittest.main()
