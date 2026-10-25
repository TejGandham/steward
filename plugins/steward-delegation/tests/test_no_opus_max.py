"""Operator decision 2026-10-12: Claude Opus never runs at max effort or
thinking. The top reviewer runs Opus 5.5 at xhigh on Claude Code, pi and
GitHub Copilot (skills/delegating/routing.md, section "Top reviewer on Opus
5.5 xhigh; Opus never at max (operator decision 2026-10-12)").

This half checks what ships in steward-delegation: the agent profiles, the
Claude, pi and Copilot edicts and routing.md. The repo root's
tests/test_no_opus_max.py checks the README, the onboarding template, the
repo's .pi/settings.json and the example plans."""

import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ROUTING = PLUGIN_ROOT / "skills" / "delegating" / "routing.md"
EDICTS = (
    PLUGIN_ROOT / "skills" / "delegating" / "SKILL.md",
    PLUGIN_ROOT / "pi" / "skills" / "steward-delegating" / "SKILL.md",
    PLUGIN_ROOT / "copilot" / "skills" / "delegating" / "SKILL.md",
)
PROFILE_DOCS = (ROUTING,) + EDICTS
RULE = "Claude Opus never runs at max"


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    fields = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


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


class NoOpusMaxTests(unittest.TestCase):
    def test_claude_code_agents(self):
        for path in sorted((PLUGIN_ROOT / "agents").glob("*.md")):
            fm = frontmatter(path)
            if is_opus(fm.get("model")):
                self.assertNotEqual(fm.get("effort"), "max", path.name)

    def test_pi_agents(self):
        for path in sorted((PLUGIN_ROOT / "pi" / "agents").glob("*.md")):
            fm = frontmatter(path)
            if is_opus(fm.get("model")):
                self.assertNotEqual(fm.get("thinking"), "max", path.name)

    def test_copilot_agents_against_edict_models(self):
        # Copilot profiles pin no model; the edict's table names it per role.
        edict = EDICTS[2].read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| steward:([a-z-]+) \| ([^|]+?) \|", edict, re.M))
        self.assertIn("top-reviewer", rows)
        efforts = dict(re.findall(r"^\| steward:([a-z-]+) \| [^|]+ \| `([a-z]+)` \|", edict, re.M))
        for path in sorted((PLUGIN_ROOT / "copilot" / "agents").glob("*.agent.md")):
            role = frontmatter(path)["name"]
            if "opus" in rows.get(role, "").lower():
                self.assertNotEqual(frontmatter(path).get("reasoning-effort"), "max", path.name)
                self.assertNotEqual(efforts.get(role), "max", role)

    def test_profile_tables(self):
        for path in PROFILE_DOCS:
            self.assertEqual(table_opus_max_rows(path.read_text(encoding="utf-8")), [], path.name)

    def test_profile_bullets(self):
        for path in PROFILE_DOCS:
            self.assertEqual(PROFILE_PAIR.findall(path.read_text(encoding="utf-8")), [], path.name)

    def test_edicts_carry_the_rule(self):
        for path in EDICTS:
            self.assertIn(RULE, path.read_text(encoding="utf-8"), path)


class HelperTests(unittest.TestCase):
    def test_detects_pairs(self):
        self.assertEqual(len(opus_max_pairs({"a": {"model": "amorphic/claude-opus-5-5", "thinking": "max"}})), 1)
        self.assertEqual(len(opus_max_pairs(["anthropic/claude-opus-5-5:max"])), 1)
        self.assertEqual(opus_max_pairs({"model": "anthropic/claude-fable-5-1", "thinking": "max"}), [])
        self.assertEqual(opus_max_pairs(["fireworks/x/deepseek-v4p1-flash:max"]), [])

    def test_detects_table_rows_and_bullets(self):
        self.assertEqual(len(table_opus_max_rows("| `steward:reviewer-opus-max` | Opus | max | x |")), 1)
        self.assertEqual(len(table_opus_max_rows("| `steward.top-reviewer` | `anthropic/claude-opus-5-5` | max |")), 1)
        self.assertEqual(table_opus_max_rows("| `steward:reviewer-opus-max` | Opus | xhigh | x |"), [])
        self.assertEqual(table_opus_max_rows("| steward:x | Sonnet | max |"), [])
        self.assertEqual(len(PROFILE_PAIR.findall("**steward:reviewer-opus-max** (opus, max): top")), 1)
        self.assertEqual(PROFILE_PAIR.findall("**steward:reviewer-opus-max** (opus, xhigh): top"), [])
        self.assertEqual(PROFILE_PAIR.findall("Why max, not xhigh"), [])


if __name__ == "__main__":
    unittest.main()
