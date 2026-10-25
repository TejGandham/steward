"""Fixes from the 0.11.0 release review (docs/roadmap/pi-model-plan.md,
"Release review"): edict wording for rows the no-plan block shows, per-call
models checked against an enforced modelScope and maxThinking, the relaunch
after a "pass model X" row and the drift hint. The README example plan cases
live in the repo's tests/test_model_plan_docs.py.

Every test builds its own temp HOME, agent dir and project dir.
"""

import unittest

from test_pi_model_plan import OPUS, SOL, SONNET, OLLAMA, PLUGIN_ROOT, PlanTestCase, mp
from test_pi_model_plan_render import render, table_rows

PI_SKILL = PLUGIN_ROOT / "pi" / "skills" / "steward-delegating" / "SKILL.md"
NOCREDS = "openai/gpt-6.1-nocreds"
# Edict size at 55106f6 was 10,251 bytes; the fixes may add a little.
# The edict rides in every pi request's system prompt, so the budget stays tight.
# 0.11.1 adds the ad-hoc browser chores routing row (about 210 bytes); its
# hand-back rule lives in skills/delegating/routing.md, not here.
EDICT_MAX_BYTES = 11200


def _section(text, heading):
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start: nxt if nxt != -1 else len(text)]


class EdictReleaseReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PI_SKILL.read_text(encoding="utf-8")
        cls.rule2 = next(line for line in cls.text.splitlines() if line.startswith("2. "))
        cls.guard = _section(cls.text, "## Guardrails")

    def test_judgment_floor_only_on_no(self):
        floor = next(l for l in self.guard.splitlines() if l.startswith("- Judgment floor"))
        self.assertIn("Judgment-grade cell says `yes`", floor)
        self.assertIn("every cell says `no`", floor)
        self.assertIn("`not checked`, or no block", floor)
        self.assertIn("route by the routing table", floor)

    def test_no_relaunch_rule(self):
        r = self.rule2
        self.assertNotIn("do not relaunch; tell the operator", r)
        self.assertIn("With no relaunch model (`none`, or no such column), do not choose a model yourself", r)
        self.assertIn("After an overload, rate-limit or timeout error, repeat the same launch once (same profile, "
                      "plus the row's `model` if it says \"pass model X\"; never any other model), "
                      "after checking what the failed child already changed", r)
        self.assertNotIn("without `model`", r)
        self.assertIn("after any other provider error, or a second failure", r)

    def test_unavailable_without_model_to_pass(self):
        self.assertIn("no model to pass", self.rule2)

    def test_cross_family_has_a_target_without_plan(self):
        line = next(l for l in self.guard.splitlines() if l.startswith("- Cross-family"))
        self.assertIn("another family than the author's", line)
        self.assertIn("all share one family", line)
        self.assertIn("routing table's reviewer", line)

    def test_escalation_none(self):
        line = next(l for l in self.guard.splitlines() if l.startswith("- Escalate"))
        self.assertIn("`none`", line)
        self.assertIn("steward.deep-reasoner", line)

    def test_fallback_guardrail_names_block_models_only(self):
        line = next(l for l in self.guard.splitlines() if l.startswith("- Fallback is not escalation"))
        self.assertIn("never a model the block does not name", line)

    def test_per_child_model_includes_pass_model(self):
        call = _section(self.text, "## How to call")
        self.assertIn("A per-child `model` (relaunch, escalation or pass model)", call)

    def test_thinking_guardrail_is_actionable(self):
        line = next(l for l in self.guard.splitlines() if l.startswith("- Thinking"))
        self.assertIn("never raise a cheap role's thinking per call", line)

    def test_size(self):
        self.assertLessEqual(len(PI_SKILL.read_bytes()), EDICT_MAX_BYTES)


class PerCallScopeTests(PlanTestCase):
    """S3: relaunch, escalation and pass-model strings are per-call models."""

    def scope(self, allow, **extra):
        sub = {"modelScope": {"enforce": True, "allow": allow}}
        sub.update(extra)
        return sub

    def test_relaunch_skips_candidate_outside_scope(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "fallback": [OLLAMA, SONNET]}}})
        self.user_settings({"subagents": dict(self.scope(["amorphic/*"]),
                                              agentOverrides={"steward.coder": {"model": OPUS}})})
        result = self.run_plan(main=OPUS)
        self.assertEqual(result["roles"]["coder"]["effectiveRelaunch"]["model"], SONNET)

    def test_relaunch_none_when_every_candidate_aborts(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "fallback": [OLLAMA]}}})
        self.user_settings({"subagents": dict(self.scope(["amorphic/*"]),
                                              agentOverrides={"steward.coder": {"model": OPUS}})})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["effectiveRelaunch"])
        rows = table_rows(render.render_block(result))
        self.assertEqual(rows["steward.coder"][5], "none")
        info = self.findings(result, code="effective-relaunch-none", role="coder")
        self.assertTrue(any("modelScope" in f["message"] for f in info), info)
        self.assertIn("modelScope", render.render_report(result))

    def test_relaunch_skips_candidate_above_max_thinking(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "thinking": "medium",
                                                          "fallback": [SONNET + ":max"]}}})
        self.user_settings({"subagents": {"maxThinking": "high",
                                          "agentOverrides": {"steward.coder": {"model": OPUS}}}})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["effectiveRelaunch"])
        info = self.findings(result, code="effective-relaunch-none", role="coder")
        self.assertTrue(any("maxThinking" in f["message"] for f in info), info)

    def test_escalation_outside_scope_is_none(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "escalate": SOL + ":high"}}})
        self.user_settings({"subagents": self.scope(["amorphic/*", "anthropic/*"])})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["escalate"])
        rows = table_rows(render.render_block(result))
        self.assertEqual(rows["steward.coder"][6], "none")
        none = self.findings(result, code="escalation-none", role="coder")
        self.assertEqual(len(none), 1)
        self.assertIn("modelScope", none[0]["message"])
        self.assertIn("escalation-none", render.render_report(result))
        self.assertNotIn(SOL, render.render_block(result))

    def test_escalation_above_max_thinking_is_none(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS, "escalate": OPUS + ":max"}}})
        self.user_settings({"subagents": {"maxThinking": "xhigh"}})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["escalate"])
        self.assertTrue(self.findings(result, code="escalation-none", role="coder"))

    def test_pass_model_outside_scope_takes_next_candidate(self):
        # agentB from the review: the pass-model string is a per-call model.
        self.user_plan({"version": 1, "roles": {"coder": {"model": SOL, "thinking": "medium",
                                                          "fallback": [SONNET]}}})
        self.user_settings({"subagents": dict(self.scope(["amorphic/*", "anthropic/*", "openai/*", "inherit"]),
                                              agentOverrides={"steward.coder": {"model": NOCREDS}})})
        result = self.run_plan(main=OPUS)
        self.assertEqual(result["roles"]["coder"]["passModel"]["launch"], SONNET + ":medium")
        rows = table_rows(render.render_block(result))
        self.assertIn("pass model %s:medium" % SONNET, rows["steward.coder"][1])
        self.assertNotIn(SOL, rows["steward.coder"][1])

    def test_pass_model_none_when_every_candidate_aborts(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": SOL, "thinking": "medium"}}})
        self.user_settings({"subagents": dict(self.scope(["amorphic/*", "openai/*", "inherit"]),
                                              agentOverrides={"steward.coder": {"model": NOCREDS}})})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["passModel"])
        rows = table_rows(render.render_block(result))
        self.assertIn("unavailable; no model to pass", rows["steward.coder"][1])
        none = self.findings(result, code="pass-model-none", role="coder")
        self.assertEqual(len(none), 1)
        self.assertIn("modelScope", none[0]["message"])

    def test_effective_above_max_thinking_is_do_not_launch(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        self.user_settings({"subagents": {"maxThinking": "high"}})
        result = self.run_plan(main=OPUS)
        rows = table_rows(render.render_block(result))
        # deep-reasoner's frontmatter asks for xhigh, top-reviewer for max
        self.assertEqual(rows["steward.deep-reasoner"][5], "do not launch")
        self.assertEqual(rows["steward.top-reviewer"][5], "do not launch")
        self.assertNotEqual(rows["steward.coder"][5], "do not launch")

    def test_effective_outside_strict_scope_is_do_not_launch(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        self.user_settings({"subagents": {"modelScope": {"enforce": True, "strict": True,
                                                         "allow": ["anthropic/claude-opus*"]}}})
        result = self.run_plan(main=OPUS)
        rows = table_rows(render.render_block(result))
        self.assertEqual(rows["steward.reviewer"][5], "do not launch")
        self.assertNotEqual(rows["steward.deep-reasoner"][5], "do not launch")


class PassModelRelaunchTests(PlanTestCase):
    """S4: a "pass model X" row relaunches on the candidate after X."""

    def test_relaunch_after_pass_model(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": NOCREDS, "thinking": "medium",
                                                          "fallback": [OPUS, SONNET]}}})
        self.user_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": NOCREDS}}}})
        result = self.run_plan(main=OPUS)
        row = result["roles"]["coder"]
        self.assertEqual(row["passModel"]["model"], OPUS)
        self.assertEqual(row["effectiveRelaunch"]["model"], SONNET)
        rows = table_rows(render.render_block(result))
        self.assertIn("pass model %s:medium" % OPUS, rows["steward.coder"][1])
        self.assertEqual(rows["steward.coder"][5], SONNET + ":medium")

    def test_pass_model_alone_gives_no_relaunch_on_itself(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": NOCREDS, "thinking": "medium",
                                                          "fallback": [OPUS]}}})
        self.user_settings({"subagents": {"agentOverrides": {"steward.coder": {"model": NOCREDS}}}})
        result = self.run_plan(main=OPUS)
        self.assertIsNone(result["roles"]["coder"]["effectiveRelaunch"])
        rows = table_rows(render.render_block(result))
        self.assertEqual(rows["steward.coder"][5], "none")


class DriftHintTests(PlanTestCase):
    """S5, updated in 0.12.0: apply exists, so user-plan drift names it."""

    def test_hint_names_apply(self):
        self.user_plan({"version": 1, "roles": {"coder": {"model": OPUS}}})
        result = self.run_plan(main=OPUS)
        drift = self.findings(result, code="binding-drift", role="coder")
        self.assertEqual(len(drift), 1)
        self.assertIn("run /steward-models apply", drift[0]["message"])
        self.assertNotIn("by hand", drift[0]["message"])


class HeadingTests(PlanTestCase):
    def test_heading_names_thinking_switch(self):
        self.assertIn("rebuilt on a model or thinking switch", render.HEADING)


if __name__ == "__main__":
    unittest.main()
