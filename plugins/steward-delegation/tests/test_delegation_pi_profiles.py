"""Tests for the pi agent profiles and the pi edict skill this plugin ships.

The pi profiles must stay in step with the Claude Code ones: same set of
profiles, same body, and a model and thinking level that match the Claude
Code model alias and effort. The pi edict must name every pi profile.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import PLUGIN_ROOT, load_hook_module  # noqa: E402

hook = load_hook_module()

PI_SKILL = PLUGIN_ROOT / "pi" / "skills" / "steward-delegating" / "SKILL.md"
PI_AGENTS = PLUGIN_ROOT / "pi" / "agents"
CLAUDE_AGENTS = PLUGIN_ROOT / "agents"

# Claude Code profile name -> pi role-only profile name.
PI_NAMES = {
    "coder-opus-medium": "coder",
    "deep-reasoner-opus-xhigh": "deep-reasoner",
    "reviewer-sonnet-high": "reviewer",
    "researcher-sonnet-low": "researcher",
    "writer-sonnet-medium": "writer",
    "mechanic-haiku-medium": "mechanic",
    "reviewer-opus-max": "top-reviewer",
}

# pi role-only profile name -> old pi names kept as pi-subagents aliases.
PI_ALIASES = {new: ["steward." + old] for old, new in PI_NAMES.items()}
PI_ALIASES["top-reviewer"].append("steward.reviewer-fable-xhigh")

MODEL_WORDS = ("opus", "sonnet", "haiku", "fable")


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    fields = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2)
    return fields, m.group(2)


class PiAgentProfileTests(unittest.TestCase):
    MODEL_MAP = {
        "haiku": "anthropic/claude-haiku-5-5",
        "opus": "anthropic/claude-opus-5-5",
        "sonnet": "anthropic/claude-sonnet-5-5",
        "fable": "anthropic/claude-fable-5-1",
    }

    def test_same_profiles_as_claude(self):
        self.assertEqual(
            sorted(p.stem for p in PI_AGENTS.glob("*.md")),
            sorted(PI_NAMES[p.stem] for p in CLAUDE_AGENTS.glob("*.md")),
        )

    def test_each_profile_mirrors_its_claude_twin(self):
        for claude_path in CLAUDE_AGENTS.glob("*.md"):
            with self.subTest(profile=claude_path.stem):
                pi_name = PI_NAMES[claude_path.stem]
                c_fields, c_body = _frontmatter(claude_path)
                p_fields, p_body = _frontmatter(PI_AGENTS / (pi_name + ".md"))
                self.assertEqual(p_fields["name"], pi_name)
                self.assertEqual(p_fields["package"], "steward")
                self.assertEqual(p_fields["model"], self.MODEL_MAP[c_fields["model"]])
                self.assertEqual(p_fields["thinking"], c_fields["effort"])
                self.assertEqual(p_body, c_body)
                self.assertNotIn("steward:", p_fields["description"])

    def test_old_names_kept_as_aliases(self):
        for new, expected in PI_ALIASES.items():
            with self.subTest(profile=new):
                fields, _ = _frontmatter(PI_AGENTS / (new + ".md"))
                aliases = [a.strip() for a in fields.get("aliases", "").split(",") if a.strip()]
                self.assertEqual(aliases, expected)

    def test_edict_defaults_match_profiles(self):
        text = PI_SKILL.read_text(encoding="utf-8")
        rule2 = next(line for line in text.splitlines() if line.startswith("2. "))
        stated = {
            m.group(1): (m.group(2).lower(), m.group(3))
            for m in re.finditer(
                r"`steward\.([\w-]+)` \([^)]*?; (\w+) [\d.]+, (?:thinking )?`(\w+)`\)",
                rule2,
            )
        }
        self.assertEqual(sorted(stated), sorted(PI_NAMES.values()))
        for name, (model_word, thinking) in stated.items():
            with self.subTest(profile=name):
                fields, _ = _frontmatter(PI_AGENTS / (name + ".md"))
                self.assertEqual(fields["model"], self.MODEL_MAP[model_word])
                self.assertEqual(fields["thinking"], thinking)

    def test_profile_names_carry_no_model(self):
        for path in PI_AGENTS.glob("*.md"):
            fields, _ = _frontmatter(path)
            for word in MODEL_WORDS:
                self.assertNotIn(word, fields["name"], path.name)
                self.assertNotIn(word, path.stem, path.name)

    def test_writer_loads_plainlanguage(self):
        fields, _ = _frontmatter(PI_AGENTS / "writer.md")
        self.assertEqual(fields["skills"], "plainlanguage")

    def test_children_see_operator_context(self):
        for path in PI_AGENTS.glob("*.md"):
            fields, _ = _frontmatter(path)
            for key in ("inheritProjectContext", "inheritGlobalContext", "inheritSkills"):
                self.assertEqual(fields[key], "true", f"{path.name} {key}")


class PiSkillTests(unittest.TestCase):
    def test_skill_names_every_pi_profile(self):
        text = PI_SKILL.read_text(encoding="utf-8")
        for path in PI_AGENTS.glob("*.md"):
            self.assertIn("steward." + path.stem, text)
        self.assertNotIn("steward:", text)

    def test_profile_references_carry_no_model(self):
        sources = {
            "pi edict": PI_SKILL.read_text(encoding="utf-8"),
            "pi gate message": hook.gate_message(2, "/h/.pi/agent", "pi"),
        }
        for label, text in sources.items():
            refs = re.findall(r"steward\.([\w-]+)", text)
            self.assertTrue(refs, label)
            for ref in refs:
                for word in MODEL_WORDS:
                    self.assertNotIn(word, ref, f"{label}: steward.{ref}")

    def test_skill_frontmatter_name(self):
        fields, _ = _frontmatter(PI_SKILL)
        self.assertEqual(fields["name"], "steward-delegating")


if __name__ == "__main__":
    unittest.main()
