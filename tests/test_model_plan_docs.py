"""The pi model plan as the repo's docs show it: the operator's plan in
docs/roadmap/pi-model-plan.md and the example plan and wording in the
steward-delegation README.

The model plan code and its tests live in plugins/steward-delegation; this
file loads them by path, since plugin tests read only files inside their
plugin.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "roadmap" / "pi-model-plan.md"
README = REPO_ROOT / "plugins" / "steward-delegation" / "README.md"
PLAN_TESTS = REPO_ROOT / "plugins" / "steward-delegation" / "tests" / "test_pi_model_plan.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The plugin's model plan tests: OPERATOR_PLAN, PlanTestCase and the
# model_plan module they load. Kept as a module so discovery does not
# collect the plugin's test classes here as well.
_plan_tests = _load("model_plan_tests_for_docs", PLAN_TESTS)
mp = _plan_tests.mp
OPUS = _plan_tests.OPUS


def doc_operator_plan():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### Operator's case", 1)[1]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)


def readme_plan():
    text = README.read_text(encoding="utf-8")
    section = text.split("### Model plan on pi", 1)[1].split("\n### ", 1)[0]
    block = re.search(r"```json\n(.*?)```", section, re.S).group(1)
    return json.loads(block)


class DocOperatorPlanTests(unittest.TestCase):
    def test_doc_operator_plan_matches_tests(self):
        self.assertEqual(doc_operator_plan(), _plan_tests.OPERATOR_PLAN)
        self.assertIn("anthropic/claude-opus-5*", _plan_tests.OPERATOR_PLAN["judgmentModels"])


class ReadmeExamplePlanTests(_plan_tests.PlanTestCase):
    """N6: the README example keeps judgment roles off a lower tier."""

    def test_deep_reasoner_does_not_fall_back_to_sonnet(self):
        plan = readme_plan()
        dr = plan["roles"]["deep-reasoner"]
        self.assertIn("fallback", dr)
        for ref in dr["fallback"] or []:
            self.assertIn("opus", ref)
        self.assertIn("top-reviewer", plan["roles"])
        self.assertIsNone(plan["roles"]["top-reviewer"]["escalate"])

    def test_example_evaluates_without_plan_errors(self):
        self.user_plan(readme_plan())
        result = self.run_plan(main=OPUS)
        self.assertFalse([f for f in result["findings"] if f["code"].startswith("plan-")])
        for role in ("deep-reasoner", "top-reviewer"):
            relaunch = result["roles"][role]["effectiveRelaunch"]
            self.assertTrue(relaunch is None or "opus" in relaunch["model"], relaunch)
        self.assertNotIn("sonnet", result["roles"]["top-reviewer"]["escalate"] and
                         result["roles"]["top-reviewer"]["escalate"].get("model") or "")


class ReadmeWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = README.read_text(encoding="utf-8")
        cls.section = cls.text.split("### Model plan on pi", 1)[1].split("\n### Gates on pi", 1)[0]

    def test_lists_are_advisory(self):
        self.assertNotIn("apply even when you decline project trust", self.section)
        self.assertIn("modelScope", self.section)
        self.assertIn("do not stop a launch", self.section)

    def test_guardrails_are_the_edicts(self):
        self.assertIn("guardrails** the edict states", self.section)

    def test_hook_log_contents_described(self):
        self.assertIn("STEWARD_DELEGATION_HOOK_LOG", self.section)
        self.assertIn("session-start", self.section)
        self.assertNotIn("every hook call then appends", self.section)

    def test_style(self):
        self.assertNotIn(chr(0x2014), self.section)
        lower = self.section.lower()
        for word in ("load-bearing", "load bearing", "fencing", "earned its keep", "landmine", "footgun"):
            self.assertNotIn(word, lower)


if __name__ == "__main__":
    unittest.main()
