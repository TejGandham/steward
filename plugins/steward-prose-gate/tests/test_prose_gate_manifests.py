"""Packaging tests for steward-prose-gate: its three manifests, the Claude
Code hooks.json, and its entries in the two root marketplace catalogs."""

import json
import unittest

from helpers import PLUGIN_ROOT

REPO_ROOT = PLUGIN_ROOT.parent.parent
NAME = "steward-prose-gate"
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

    def test_codex_manifest_points_at_its_hooks_and_has_no_skills(self):
        data = load(PLUGIN_ROOT / ".codex-plugin/plugin.json")
        self.assertEqual(data["hooks"], "./codex/hooks.json")
        self.assertNotIn("skills", data)
        self.assertTrue((PLUGIN_ROOT / "codex" / "hooks.json").is_file())

    def test_copilot_manifest_points_at_its_hooks(self):
        data = load(PLUGIN_ROOT / ".github/plugin/plugin.json")
        self.assertEqual(data["hooks"], "copilot/hooks.json")
        self.assertTrue((PLUGIN_ROOT / "copilot" / "hooks.json").is_file())


class HooksJsonTests(unittest.TestCase):
    def _load(self):
        return load(PLUGIN_ROOT / "hooks" / "hooks.json")

    @staticmethod
    def _command(mode):
        return 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/prose_gate_hook.py" claude ' + mode

    def test_only_pre_tool_use_and_stop(self):
        self.assertEqual(sorted(self._load()["hooks"]), ["PreToolUse", "Stop"])

    def test_pr_gate_on_bash(self):
        pre = self._load()["hooks"]["PreToolUse"]
        self.assertEqual(len(pre), 1)
        self.assertEqual(pre[0]["matcher"], "^Bash$")
        self.assertEqual(pre[0]["hooks"], [
            {"type": "command", "command": self._command("pr-gate"), "timeout": 10},
        ])

    def test_prose_gate_on_stop(self):
        stop = self._load()["hooks"]["Stop"]
        self.assertEqual(len(stop), 1)
        self.assertNotIn("matcher", stop[0])
        self.assertEqual(stop[0]["hooks"], [
            {"type": "command", "command": self._command("prose-gate"), "timeout": 15},
        ])


class CatalogTests(unittest.TestCase):
    def test_claude_catalog_entry(self):
        _, entry = catalog_entry(".claude-plugin/marketplace.json")
        self.assertEqual(entry["source"], "./plugins/steward-prose-gate")
        self._assert_resolves(entry["source"], ".claude-plugin/plugin.json")

    def test_codex_catalog_entry(self):
        catalog, entry = catalog_entry(".agents/plugins/marketplace.json")
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/steward-prose-gate"})
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
