"""Operator decision 2026-10-12: Claude Opus never runs at max effort or
thinking. The top reviewer runs Opus 5.5 at xhigh on Claude Code, pi and
GitHub Copilot (plugins/steward-delegation/skills/delegating/routing.md,
section "Top reviewer on Opus 5.5 xhigh; Opus never at max (operator
decision 2026-10-12)").

This half checks the README, the onboarding template, the repo's
.pi/settings.json and the example plans. The agent profiles, edicts and
routing.md are checked in plugins/steward-delegation/tests/test_no_opus_max.py."""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
PLAN_DOC = REPO_ROOT / "docs" / "roadmap" / "pi-model-plan.md"
ONBOARDING = REPO_ROOT / "plugins" / "steward-orchestration" / "skills" / "orchestrating" / "onboarding-template.md"
PROFILE_DOCS = (README, ONBOARDING)
RULE = "Claude Opus never runs at max"


def is_opus(model):
    return isinstance(model, str) and ("claude-opus" in model.lower() or model.strip().lower() == "opus")


def opus_max_pairs(node, where="$"):
    """Every place in a JSON value that binds an Opus model to max thinking,
    as {model, thinking} objects or as `model:max` reference strings."""
    found = []
    if isinstance(node, dict):
        if is_opus(node.get("model")) and node.get("thinking") == "max":
            found.append(where)
        for key, value in node.items():
            found += opus_max_pairs(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += opus_max_pairs(value, f"{where}[{i}]")
    elif isinstance(node, str) and node.lower().endswith(":max") and is_opus(node.rsplit(":", 1)[0]):
        found.append(f"{where}={node}")
    return found


def table_opus_max_rows(text):
    """Markdown table rows where an Opus model cell is followed by a max effort cell."""
    found = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        for model, effort in zip(cells, cells[1:]):
            if "opus" in model.lower() and "steward" not in model.lower() and effort.lower() == "max":
                found.append(line)
    return found


PROFILE_PAIR = re.compile(r"\((?:opus|[\w/.-]*claude-opus[\w.-]*),\s*max\)", re.I)


def json_blocks(text):
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.S)]


class NoOpusMaxTests(unittest.TestCase):
    def test_repo_pi_settings(self):
        data = json.loads((REPO_ROOT / ".pi" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(opus_max_pairs(data), [])

    def test_operator_case_plan(self):
        section = PLAN_DOC.read_text(encoding="utf-8").split("### Operator's case", 1)[1]
        plan = json.loads(section.split("```json", 1)[1].split("```", 1)[0])
        self.assertEqual(opus_max_pairs(plan), [])
        self.assertEqual(plan["roles"]["top-reviewer"]["thinking"], "xhigh")

    def test_plan_doc_and_readme_json_examples(self):
        for path in (PLAN_DOC, README):
            for block in json_blocks(path.read_text(encoding="utf-8")):
                self.assertEqual(opus_max_pairs(block), [], path.name)

    def test_profile_tables(self):
        for path in PROFILE_DOCS:
            self.assertEqual(table_opus_max_rows(path.read_text(encoding="utf-8")), [], path.name)

    def test_profile_bullets(self):
        for path in PROFILE_DOCS:
            self.assertEqual(PROFILE_PAIR.findall(path.read_text(encoding="utf-8")), [], path.name)

    def test_edicts_carry_the_rule(self):
        self.assertIn(RULE, ONBOARDING.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
