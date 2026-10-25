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


if __name__ == "__main__":
    unittest.main()
