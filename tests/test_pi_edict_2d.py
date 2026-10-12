"""Phase 2d: the pi edict text for the model plan.

The edict names the generated "Model plan" block, limits per-call
`model` to three cases, adds the judgment-floor inline case and the
seven guardrails, and calls subagents only in shapes pi-subagents
0.77.0 accepts from a main session (no in-reply workflow block).
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PI_SKILL = REPO_ROOT / "pi" / "skills" / "steward-delegating" / "SKILL.md"
EM_DASH = chr(0x2014)


def _section(text, heading):
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start: nxt if nxt != -1 else len(text)]


class PiEdictModelPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PI_SKILL.read_text(encoding="utf-8")
        cls.rule2 = next(line for line in cls.text.splitlines() if line.startswith("2. "))

    def test_rule2_names_model_plan_block(self):
        self.assertIn('"Model plan" block', self.rule2)
        self.assertIn("relaunch", self.rule2)
        self.assertIn("escalation", self.rule2)

    def test_rule2_three_cases_for_model(self):
        r = self.rule2
        self.assertRegex(r, r"Pass `model` only")
        self.assertIn("provider error", r)
        self.assertIn("failed check", r)
        self.assertIn("operator asks", r)
        self.assertIn("copy the exact string from the block", r)
        self.assertIn("Fable", r)

    def test_rule2_unavailable_and_no_relaunch(self):
        # Option B: an unavailable binding's row says which model to pass.
        self.assertIn('"pass model X"', self.rule2)
        self.assertIn("With no relaunch string (`none`, or no such column), do not relaunch", self.rule2)

    def test_rule2_blocked_profiles(self):
        self.assertIn("blocked", self.rule2)
        self.assertIn('"do not launch"', self.rule2)

    def test_no_pin_claim(self):
        self.assertNotIn("pins its model", self.text)
        self.assertNotRegex(self.text, r"pins? (its|the) model")

    def test_routing_cheap_workers(self):
        self.assertIn("a coordinator plus cheap workers", self.text)
        self.assertNotIn("sonnet workers", self.text)

    def test_inline_judgment_floor_case(self):
        inline = _section(self.text, "## Keep it inline")
        self.assertIn("the only profile for the task is below the judgment floor in the Model plan block", inline)

    def test_seven_guardrails(self):
        g = _section(self.text, "## Guardrails")
        items = [line for line in g.splitlines() if line.startswith("- ")]
        self.assertEqual(len(items), 7, items)
        joined = "\n".join(items).lower()
        for phrase in ("judgment", "done-condition", "escalat", "fallback is not escalation",
                       "family", "cap", "thinking"):
            self.assertIn(phrase, joined)
        self.assertIn("steward.deep-reasoner", joined)
        self.assertIn("never the same model twice", joined)

    def test_parallel_workflow_shape(self):
        call = _section(self.text, "## How to call")
        self.assertIn('subagent({ workflow: "parallel", args: { tasks: [{ agent, task }, ...] } })', call)

    def test_sequential_dependent_steps(self):
        call = _section(self.text, "## How to call")
        self.assertRegex(call, r"Dependent steps: launch them one after another as separate `subagent` calls")

    def test_script_file_form(self):
        call = _section(self.text, "## How to call")
        self.assertIn('subagent({ workflow: "/abs/path/script.js", args })', call)
        self.assertIn("runs.run(key, { agent, task })", call)
        self.assertIn("runs.run(key, { agent, task, model })", call)

    def test_no_in_reply_workflow_block(self):
        self.assertNotIn("workflow: true", self.text)
        self.assertNotIn("js workflow", self.text)
        self.assertNotIn("in the same reply", self.text)

    def test_style(self):
        self.assertNotIn(EM_DASH, self.text)
        for line in self.text.splitlines():
            if re.fullmatch(r"\|[-:| ]+\|", line):
                self.assertRegex(line, r"^(\|-)+\|$")
        lower = self.text.lower()
        for word in ("load-bearing", "load bearing", "fencing", "earned its keep", "landmine",
                     "footgun", "blast radius", "tripwire", "minefield"):
            self.assertNotIn(word, lower)


if __name__ == "__main__":
    unittest.main()
