"""Small fixes after 0.13.0: the same-family warning and the per-model warnings follow
the binding a profile launches on, not a plan binding that settings override."""

import unittest

from test_pi_model_plan import FIREWORKS, HAIKU, OLLAMA, OPUS, SONNET, PlanTestCase

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

    def test_plan_binding_not_launched_gets_no_per_model_warnings(self):
        # Frontmatter launches the profiles (no settings override); the plan binding on a
        # 16K model with an unsupported level gets no per-model warnings; drift says apply.
        plan = {"version": 1, "judgmentModels": ["amorphic/claude-opus-5*"],
                "roles": {"*": {"model": OLLAMA, "thinking": "xhigh"}}}
        self.user_plan(plan)
        result = self.run_plan(main=OPUS)
        self.assertEqual(self.per_model(result, "plan binding"), [])
        self.assertTrue(self.findings(result, code="binding-drift", role="coder"))

    def test_effective_binding_carries_the_warnings(self):
        self.user_plan(ALL_ON_OLLAMA)
        self.user_settings({"subagents": {"agentOverrides": {
            "steward.coder": {"model": OLLAMA, "thinking": "high"},
            "steward.writer": {"model": OLLAMA, "thinking": "high"}}}})
        result = self.run_plan(main=OPUS)
        low = self.findings(result, code="max-tokens-low")
        self.assertEqual({(f["role"], f["subject"]) for f in low},
                         {("coder", "effective binding"), ("writer", "effective binding")})


if __name__ == "__main__":
    unittest.main()
