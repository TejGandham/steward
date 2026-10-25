"""Tests for the root package.json that `pi install` reads.

The root package is a repo-level file: no plugin's tests may read it, so its
checks live here. Every path in its pi field must exist, it must carry the
pi-package keyword, and no orchestrating skill may ship to pi.
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class PiPackageManifestTests(unittest.TestCase):
    def setUp(self):
        with open(REPO_ROOT / "package.json", encoding="utf-8") as f:
            self.pkg = json.load(f)

    def test_manifest_paths_exist(self):
        pi = self.pkg["pi"]
        for rel in pi["extensions"] + pi["skills"] + pi["subagents"]["agents"]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_pi_package_keyword(self):
        self.assertIn("pi-package", self.pkg["keywords"])

    def test_orchestrating_skill_not_shipped_to_pi(self):
        for rel in self.pkg["pi"]["skills"]:
            root = REPO_ROOT / rel
            self.assertFalse(list(root.rglob("orchestrating*")), rel)
            for skill in root.rglob("SKILL.md"):
                self.assertNotIn("orchestrat", skill.read_text(encoding="utf-8").lower(), skill)


if __name__ == "__main__":
    unittest.main()
