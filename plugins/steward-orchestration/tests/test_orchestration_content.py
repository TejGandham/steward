"""Tests for the steward-orchestration plugin's shipped content: its
manifest, the orchestrating skill and the onboarding template."""

import json
import re
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
SKILL_DIR = PLUGIN_ROOT / "skills" / "orchestrating"
SKILL = SKILL_DIR / "SKILL.md"
TEMPLATE = SKILL_DIR / "onboarding-template.md"
README = PLUGIN_ROOT / "README.md"

# Built from parts so this file never carries the text the greps look for.
PERSONAL_NAME = "sau" + "ron"
OLD_NAMESPACE = re.compile("steward" + r":[a-z]")
EM_RULE = "em" + ".?" + "dash|" + "u20" + "14|" + chr(0x2014)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    fields = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_name_and_version(self):
        self.assertEqual(self.manifest["name"], "steward-orchestration")
        self.assertEqual(self.manifest["version"], "0.15.0")

    def test_no_dependencies_field(self):
        self.assertNotIn("dependencies", self.manifest)

    def test_no_codex_or_copilot_manifest(self):
        self.assertFalse((PLUGIN_ROOT / ".codex-plugin").exists())
        self.assertFalse((PLUGIN_ROOT / ".github").exists())


class SkillContentTests(unittest.TestCase):
    def test_skill_frontmatter_name(self):
        self.assertEqual(frontmatter(SKILL)["name"], "orchestrating")

    def test_no_personal_name_or_old_namespace(self):
        for path in (SKILL, TEMPLATE, README):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn(PERSONAL_NAME, text.lower())
                self.assertIsNone(OLD_NAMESPACE.search(text))

    def test_new_namespaces_used(self):
        for path in (SKILL, TEMPLATE):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("steward-delegation:delegating", text)
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("steward-orchestration:orchestrating", template)
        self.assertIn("steward-delegation:coder-opus-medium", template)

    def test_both_name_edict_file(self):
        for path in (SKILL, TEMPLATE):
            with self.subTest(path=path.name):
                self.assertIn("edict.md", path.read_text(encoding="utf-8"))

    def test_no_long_dash_rule(self):
        pattern = re.compile(EM_RULE, re.IGNORECASE)
        for path in (SKILL, TEMPLATE, README):
            with self.subTest(path=path.name):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_template_keeps_no_opus_max_rule(self):
        self.assertIn("Claude Opus never runs at max", TEMPLATE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
