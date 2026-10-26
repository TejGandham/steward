"""Packaging tests for steward-delegation: its three manifests, the Claude
Code hooks.json. The plugin ships from the Engen-Tech marketplace, so the
root catalogs here no longer list it (tests/test_catalogs.py)."""

import json
import unittest

from helpers import PLUGIN_ROOT

NAME = "steward-delegation"
VERSION = "1.0.1"
DISPLAY_NAME = "Steward Delegation"
MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".github/plugin/plugin.json",
)

AUTHOR = {"name": "Engen Inc.", "url": "https://engen.tech"}
HOMEPAGE = "https://engen.tech"


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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

class BrandingTests(unittest.TestCase):
    def test_every_manifest_names_engen_as_author_and_homepage(self):
        for rel in MANIFESTS:
            with self.subTest(manifest=rel):
                data = load(PLUGIN_ROOT / rel)
                self.assertEqual(data["author"], AUTHOR)
                if rel != ".codex-plugin/plugin.json":
                    self.assertEqual(data["homepage"], HOMEPAGE)

    def test_claude_manifest_display_name(self):
        data = load(PLUGIN_ROOT / ".claude-plugin/plugin.json")
        self.assertEqual(data["displayName"], DISPLAY_NAME)

    def test_codex_interface_branding(self):
        interface = load(PLUGIN_ROOT / ".codex-plugin/plugin.json")["interface"]
        self.assertEqual(interface["displayName"], DISPLAY_NAME)
        self.assertEqual(interface["developerName"], "Engen Inc.")
        self.assertEqual(interface["websiteURL"], HOMEPAGE)
        self.assertEqual(interface["brandColor"], "#B7364A")
        self.assertEqual(interface["logo"], "./assets/logo.png")
        self.assertEqual(interface["composerIcon"], "./assets/icon.png")
        self.assertEqual(png_size(PLUGIN_ROOT / interface["logo"]), (512, 512))
        self.assertEqual(png_size(PLUGIN_ROOT / interface["composerIcon"]), (128, 128))


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


if __name__ == "__main__":
    unittest.main()
