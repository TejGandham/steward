"""Packaging tests for steward-delegation: its three manifests, the Claude
Code hooks.json, and its entries in the two root marketplace catalogs."""

import json
import unittest

from helpers import PLUGIN_ROOT

REPO_ROOT = PLUGIN_ROOT.parent.parent
NAME = "steward-delegation"
VERSION = "0.15.0"
MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".github/plugin/plugin.json",
)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def catalog_entry(rel_path):
    catalog = load(REPO_ROOT / rel_path)
    entries = [p for p in catalog["plugins"] if p["name"] == NAME]
    if len(entries) != 1:
        raise AssertionError("%s has %d %s entries" % (rel_path, len(entries), NAME))
    return catalog, entries[0]


class ManifestTests(unittest.TestCase):
    def test_every_manifest_has_the_name_and_one_version(self):
        for rel in MANIFESTS:
            with self.subTest(manifest=rel):
                data = load(PLUGIN_ROOT / rel)
                self.assertEqual(data["name"], NAME)
                self.assertEqual(data["version"], VERSION)

    def test_no_manifest_declares_dependencies(self):
        for rel in MANIFESTS:
            with self.subTest(manifest=rel):
                self.assertNotIn("dependencies", load(PLUGIN_ROOT / rel))

    def test_claude_manifest_uses_default_paths(self):
        data = load(PLUGIN_ROOT / ".claude-plugin/plugin.json")
        for key in ("agents", "skills", "hooks"):
            self.assertNotIn(key, data)
        self.assertTrue((PLUGIN_ROOT / "agents").is_dir())
        self.assertTrue((PLUGIN_ROOT / "skills" / "delegating" / "SKILL.md").is_file())
        self.assertTrue((PLUGIN_ROOT / "hooks" / "hooks.json").is_file())

    def test_codex_manifest_paths_exist(self):
        data = load(PLUGIN_ROOT / ".codex-plugin/plugin.json")
        self.assertEqual(data["skills"], "./codex/skills/")
        self.assertEqual(data["hooks"], "./codex/hooks.json")
        self.assertTrue((PLUGIN_ROOT / data["skills"]).is_dir())
        self.assertTrue((PLUGIN_ROOT / data["hooks"]).is_file())
        self.assertEqual(data["interface"]["category"], "Productivity")

    def test_copilot_manifest_paths_exist(self):
        data = load(PLUGIN_ROOT / ".github/plugin/plugin.json")
        self.assertEqual(data["agents"], "copilot/agents/")
        self.assertEqual(data["skills"], ["copilot/skills/"])
        self.assertEqual(data["hooks"], "copilot/hooks.json")
        self.assertTrue((PLUGIN_ROOT / data["agents"]).is_dir())
        for rel in data["skills"]:
            self.assertTrue((PLUGIN_ROOT / rel).is_dir(), rel)
        self.assertTrue((PLUGIN_ROOT / data["hooks"]).is_file())

    def test_copilot_skills_ship_delegating_without_orchestrating(self):
        skills = PLUGIN_ROOT / "copilot" / "skills"
        self.assertTrue((skills / "delegating" / "SKILL.md").is_file())
        self.assertFalse(list(skills.rglob("orchestrating*")))


class HooksJsonTests(unittest.TestCase):
    def _load(self):
        return load(PLUGIN_ROOT / "hooks" / "hooks.json")["hooks"]

    @staticmethod
    def _hook(mode, timeout):
        return {
            "type": "command",
            "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/delegation_hook.py" claude ' + mode,
            "timeout": timeout,
        }

    def test_events_and_no_stop(self):
        self.assertEqual(sorted(self._load()), ["PostToolUse", "PreToolUse", "SessionStart"])

    def test_session_start(self):
        start = self._load()["SessionStart"]
        self.assertEqual(len(start), 1)
        self.assertEqual(start[0]["matcher"], "startup|resume|clear|compact|fork")
        self.assertEqual(start[0]["hooks"], [self._hook("session-start", 15)])

    def test_matchers_are_anchored(self):
        pre = self._load()["PreToolUse"]
        self.assertEqual(len(pre), 2)
        self.assertEqual(pre[0]["matcher"], "^(Edit|Write|MultiEdit|NotebookEdit|Bash)$")
        self.assertEqual(pre[0]["hooks"], [self._hook("gate", 10)])
        self.assertEqual(pre[1]["matcher"], "^(Task|Agent)$")
        self.assertEqual(pre[1]["hooks"], [self._hook("delegated", 10)])
        post = self._load()["PostToolUse"]
        self.assertEqual(len(post), 1)
        self.assertEqual(post[0]["matcher"], "^(Task|Agent)$")
        self.assertEqual(post[0]["hooks"], [self._hook("delegated", 10)])


class CatalogTests(unittest.TestCase):
    def test_claude_catalog_entry(self):
        _, entry = catalog_entry(".claude-plugin/marketplace.json")
        self.assertEqual(entry["source"], "./plugins/steward-delegation")
        self._assert_resolves(entry["source"], ".claude-plugin/plugin.json")

    def test_codex_catalog_entry(self):
        catalog, entry = catalog_entry(".agents/plugins/marketplace.json")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/steward-delegation"})
        steward = [p for p in catalog["plugins"] if p["name"] == "steward"][0]
        self.assertEqual(entry["policy"], steward["policy"])
        self.assertEqual(entry["category"], steward["category"])
        self._assert_resolves(entry["source"]["path"], ".codex-plugin/plugin.json")

    def _assert_resolves(self, rel_dir, manifest):
        plugin_dir = (REPO_ROOT / rel_dir).resolve()
        self.assertEqual(plugin_dir, PLUGIN_ROOT)
        self.assertEqual(load(plugin_dir / manifest)["name"], NAME)


if __name__ == "__main__":
    unittest.main()
