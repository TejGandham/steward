"""Packaging tests for steward-prose-gate: its three manifests, the Claude
Code hooks.json. The plugin ships from the Engen-Tech marketplace, so the
root catalogs here no longer list it (tests/test_catalogs.py)."""

import json
import unittest

from helpers import PLUGIN_ROOT

NAME = "steward-prose-gate"
VERSION = "1.0.1"
DISPLAY_NAME = "Steward Prose Gate"
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

    def test_codex_manifest_points_at_its_hooks_and_has_no_skills(self):
        data = load(PLUGIN_ROOT / ".codex-plugin/plugin.json")
        self.assertEqual(data["hooks"], "./codex/hooks.json")
        self.assertNotIn("skills", data)
        self.assertTrue((PLUGIN_ROOT / "codex" / "hooks.json").is_file())

    def test_copilot_manifest_points_at_its_hooks(self):
        data = load(PLUGIN_ROOT / ".github/plugin/plugin.json")
        self.assertEqual(data["hooks"], "copilot/hooks.json")
        self.assertTrue((PLUGIN_ROOT / "copilot" / "hooks.json").is_file())

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


if __name__ == "__main__":
    unittest.main()
