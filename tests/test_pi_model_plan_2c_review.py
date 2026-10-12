"""Phase 2c review fixes in hooks/model_plan.py (docs/roadmap/pi-model-plan.md):
the concurrency warning counts effective bindings only, the binding-drift
message never prints None for a plan role without a usable model, and the
blocked-provider messages read as whole sentences."""

import re
import unittest

from test_pi_model_plan import OLLAMA, OPERATOR_PLAN, OPUS, SOL, SONNET
from test_pi_model_plan_render import PHASE0_SETTINGS, RenderCase


class ConcurrencyCountsEffectiveBindings(RenderCase):
    def test_plan_binding_alone_does_not_warn(self):
        # The plan puts every role on ollama-cloud, but no settings apply it:
        # each profile launches on its frontmatter model until apply.
        self.user_plan(OPERATOR_PLAN)
        result = self.run_plan()
        for role in result["roles"].values():
            self.assertFalse((role["effective"]["model"] or "").startswith("ollama-cloud/"))
        self.assertEqual(self.findings(result, code="concurrency-above-cap"), [])

    def test_effective_binding_warns_and_names_only_those_roles(self):
        self.user_plan(OPERATOR_PLAN)
        self.user_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": OLLAMA}}}})
        warn = self.findings(self.run_plan(), code="concurrency-above-cap")
        self.assertEqual(len(warn), 1)
        self.assertIn("runs steward.coder,", warn[0]["message"])
        self.assertNotIn("steward.mechanic", warn[0]["message"])

    def test_applied_plan_warns(self):
        self.user_plan(OPERATOR_PLAN)
        self.user_settings(PHASE0_SETTINGS)
        self.assertEqual(len(self.findings(self.run_plan(main=SOL), code="concurrency-above-cap")), 1)


class DriftMessageWithoutPlanModel(RenderCase):
    def test_no_none_when_the_plan_role_has_no_usable_model(self):
        self.project_plan({"version": 1, "denyProviders": ["ollama-cloud"],
                           "roles": {"coder": {"model": OLLAMA, "thinking": "low"}}})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["plan"]["model"])
        drift = self.findings(result, code="binding-drift", role="coder")
        self.assertEqual(len(drift), 1, result["findings"])
        message = drift[0]["message"]
        self.assertNotIn("None", message)
        self.assertIn("not the plan's thinking low", message)

    def test_plan_model_still_named_when_set(self):
        self.project_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        drift = self.findings(self.run_plan(), code="binding-drift", role="coder")
        self.assertEqual(len(drift), 1)
        self.assertIn("not the plan's %s at " % OPUS, drift[0]["message"])


class BlockedProviderSentences(RenderCase):
    def messages(self, result):
        return [f["message"] for f in result["findings"]
                if f["code"] in ("provider-denied", "provider-not-allowed") and f["subject"] == "effective binding"]

    def assert_clean(self, messages):
        self.assertTrue(messages)
        for message in messages:
            self.assertNotIn("on a blocked", message)
            self.assertNotRegex(message, r"blocked provider \S+ is in")
            self.assertTrue(message.endswith("."), message)
            self.assertNotIn("..", message)

    def test_effective_binding_on_denied_provider(self):
        self.project_plan({"version": 1, "denyProviders": ["ollama-cloud"]})
        self.project_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": OLLAMA}}}})
        messages = self.messages(self.run_plan(main=OPUS))
        self.assert_clean(messages)
        self.assertTrue(any(re.search(r"steward\.coder %s is blocked: provider ollama-cloud is in denyProviders"
                                      % re.escape(OLLAMA), m) for m in messages), messages)

    def test_inherited_main_on_denied_provider(self):
        self.project_plan({"version": 1, "denyProviders": ["openai-codex"]})
        self.project_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": "inherit"}}}})
        messages = self.messages(self.run_plan(main=SOL))
        self.assert_clean(messages)
        self.assertTrue(any("inherits the main thread, which is blocked: provider openai-codex" in m
                            for m in messages), messages)

    def test_main_thread_on_denied_provider(self):
        self.project_plan({"version": 1, "denyProviders": ["openai-codex"]})
        result = self.run_plan(main=SOL)
        messages = [f["message"] for f in result["findings"] if f["code"] == "main-provider-denied"]
        self.assertTrue(messages, result["findings"])
        for message in messages:
            self.assertNotIn("on a blocked", message)
        self.assertTrue(any("The main thread runs %s, which is blocked: provider openai-codex is in denyProviders" % SOL
                            in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
