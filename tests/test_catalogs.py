"""Steward 0.14.2 is the last release of the single-plugin layout. Both
marketplace catalogs pin the `steward` entry to the v0.14.2 tag, so
existing installs keep resolving 0.14.2 while the repo root changes."""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG = "v0.14.2"


def steward_entry(rel_path):
    catalog = json.loads((REPO_ROOT / rel_path).read_text())
    entries = [p for p in catalog["plugins"] if p["name"] == "steward"]
    if len(entries) != 1:
        raise AssertionError("%s has %d steward entries" % (rel_path, len(entries)))
    return entries[0]


def unpinned_entries(rel_path):
    catalog = json.loads((REPO_ROOT / rel_path).read_text())
    return [p for p in catalog["plugins"] if p["name"] != "steward"]


class CatalogPinTests(unittest.TestCase):
    def test_claude_catalog_pins_steward_to_tag(self):
        entry = steward_entry(".claude-plugin/marketplace.json")
        self.assertEqual(entry["source"], {
            "source": "url", "url": "https://github.com/TejGandham/steward.git", "ref": TAG,
        })

    def test_codex_catalog_pins_steward_to_tag(self):
        entry = steward_entry(".agents/plugins/marketplace.json")
        self.assertEqual(entry["source"], {
            "source": "url", "url": "https://github.com/tejgandham/steward.git", "ref": TAG,
        })
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertEqual(entry["category"], "Productivity")


class CatalogResolveTests(unittest.TestCase):
    """Every entry other than the pinned steward points at a plugin folder in
    this repo whose manifest carries the entry's name."""

    def assert_resolves(self, folder, manifest_rel, name):
        self.assertTrue(folder.startswith("./plugins/"), folder)
        manifest = REPO_ROOT / folder / manifest_rel
        self.assertTrue(manifest.is_file(), str(manifest))
        self.assertEqual(json.loads(manifest.read_text())["name"], name)

    def test_claude_catalog_entries_resolve(self):
        entries = unpinned_entries(".claude-plugin/marketplace.json")
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(name=entry["name"]):
                self.assertIsInstance(entry["source"], str)
                self.assert_resolves(entry["source"], ".claude-plugin/plugin.json", entry["name"])

    def test_codex_catalog_entries_resolve(self):
        entries = unpinned_entries(".agents/plugins/marketplace.json")
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(name=entry["name"]):
                self.assertEqual(entry["source"]["source"], "local")
                self.assert_resolves(entry["source"]["path"], ".codex-plugin/plugin.json", entry["name"])

    def test_orchestration_is_claude_only(self):
        claude = [e["name"] for e in unpinned_entries(".claude-plugin/marketplace.json")]
        codex = [e["name"] for e in unpinned_entries(".agents/plugins/marketplace.json")]
        self.assertIn("steward-orchestration", claude)
        self.assertNotIn("steward-orchestration", codex)


if __name__ == "__main__":
    unittest.main()
