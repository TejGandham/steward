"""Steward 0.14.2 is the last release of the single-plugin layout, and this
repo is no longer a distribution point: the plugins ship from the Engen-Tech
marketplace. Both catalogs here keep only the `steward` entry, pinned to the
v0.14.2 tag, so existing installs keep resolving 0.14.2."""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TAG = "v0.14.2"


def only_entry(rel_path):
    catalog = json.loads((REPO_ROOT / rel_path).read_text())
    names = [p["name"] for p in catalog["plugins"]]
    if names != ["steward"]:
        raise AssertionError("%s lists %r, want only steward" % (rel_path, names))
    return catalog["plugins"][0]


class CatalogPinTests(unittest.TestCase):
    def test_claude_catalog_lists_only_pinned_steward(self):
        entry = only_entry(".claude-plugin/marketplace.json")
        self.assertEqual(entry["source"], {
            "source": "url", "url": "https://github.com/TejGandham/steward.git", "ref": TAG,
        })

    def test_codex_catalog_lists_only_pinned_steward(self):
        entry = only_entry(".agents/plugins/marketplace.json")
        self.assertEqual(entry["source"], {
            "source": "url", "url": "https://github.com/tejgandham/steward.git", "ref": TAG,
        })
        self.assertEqual(entry["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertEqual(entry["category"], "Productivity")


if __name__ == "__main__":
    unittest.main()
