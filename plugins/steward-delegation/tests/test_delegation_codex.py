"""Tests for `delegation_hook.py codex <mode>` and the Codex files in this
plugin: session-start injects the Codex edict, there is no gate and no
delegated mode (Codex children share the parent's session_id), the
optional agent installer, the profile fallbacks and codex/hooks.json.

These tests never touch the real home directory; see helpers.py.
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import PLUGIN_ROOT, StewardTestCase, load_hook_module, load_hooks_json, run_hook  # noqa: E402

hook = load_hook_module()

SUPPORTED_EFFORTS = {"gpt-6.1-sol": {"low", "medium", "high", "xhigh", "max"},
                     "gpt-6-astra": {"low", "medium", "high", "xhigh", "max"},
                     "gpt-6-luna": {"none", "low", "medium", "high", "xhigh", "max"}}
CODEX_DIR = PLUGIN_ROOT / "codex"
INSTALLER_PATH = CODEX_DIR / "install_agents.py"
PROFILES_PATH = CODEX_DIR / "skills" / "delegating" / "profiles.json"
SKILL_PATH = CODEX_DIR / "skills" / "delegating" / "SKILL.md"
ASTRA_ROLES = {"deep-reasoner", "top-reviewer"}


def load_installer(path):
    spec = importlib.util.spec_from_file_location("install_agents", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexHookTests(StewardTestCase):
    def setUp(self):
        super().setUp()
        self.write_plugin_file(
            "codex/skills/delegating/SKILL.md",
            "---\nname: delegating\ndescription: fixture\n---\nCodex delegation edict.\n",
        )

    def env(self, **extra):
        return self.make_env(CODEX_HOME=self.config, **extra)

    def test_startup_injects_codex_edict_without_registry(self):
        result = run_hook("codex", "session-start", {"session_id": "s1", "source": "startup"}, self.env())
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertEqual(output["additionalContext"], "Codex delegation edict.")
        self.assertFalse(os.path.exists(self.orch))

    def test_default_plugin_root_uses_codex_not_claude_skill(self):
        env = self.env()
        env.pop("STEWARD_DELEGATION_ROOT")
        result = run_hook("codex", "session-start", {}, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gpt-6.1-sol", text)
        self.assertNotIn("coder-opus-medium", text)

    def test_missing_skill_fails_open(self):
        empty_root = os.path.join(self.tmp, "empty-plugin")
        os.makedirs(empty_root, exist_ok=True)
        result = run_hook("codex", "session-start", {}, self.env(STEWARD_DELEGATION_ROOT=empty_root))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_config_uses_codex_home_and_ignores_claude_config(self):
        self.assertEqual(hook.get_config_dir({"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}, "codex"),
                         str(Path(self.home) / ".codex"))
        self.assertEqual(hook.get_config_dir({"HOME": self.home, "CODEX_HOME": "~/custom"}, "codex"),
                         str(Path(self.home) / "custom"))
        self.assertEqual(hook.get_config_dir({"HOME": self.home, "CODEX_HOME": self.config}, "codex"),
                         self.config)

    def test_codex_gate_is_silent_and_keeps_no_counter(self):
        # Codex children share the parent's session_id, so a per-session
        # counter would charge a worker's edits to the parent. No gate.
        for tool, args in [("apply_patch", {"command": "*** Begin Patch\n*** Add File: code.py\n+x\n*** End Patch"}),
                           ("Bash", {"command": "python3 build.py > result.txt"}),
                           ("Edit", {"file_path": "/repo/a.py"})]:
            for _ in range(3):
                result = run_hook("codex", "gate", {"session_id": "shared", "tool_name": tool,
                                                    "tool_input": args},
                                  self.env(STEWARD_DELEGATION_GATE="hard"))
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.state))

    def test_codex_delegated_is_silent(self):
        result = run_hook("codex", "delegated", {"session_id": "shared"}, self.env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.state))


class CodexHooksJsonTests(unittest.TestCase):
    def test_session_start_only(self):
        hooks = load_hooks_json("codex")
        self.assertEqual(list(hooks), ["SessionStart"])
        self.assertEqual(len(hooks["SessionStart"]), 1)
        entries = hooks["SessionStart"][0]["hooks"]
        self.assertEqual(entries, [{
            "type": "command",
            "command": 'python3 "${PLUGIN_ROOT}/hooks/delegation_hook.py" codex session-start',
            "timeout": 15,
        }])

    def test_no_env_prefix(self):
        text = (CODEX_DIR / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("STEWARD_HARNESS", text)
        self.assertNotIn("steward.py", text)


class CodexAgentInstallTests(StewardTestCase):
    def setUp(self):
        super().setUp()
        self.installer = load_installer(INSTALLER_PATH)

    def test_all_seven_agents_pin_supported_model_and_effort(self):
        destination = Path(self.tmp) / "agents"
        self.assertEqual(self.installer.install(destination), 7)
        self.assertEqual(self.installer.install(destination), 7)
        for path in destination.glob("*.toml"):
            agent = tomllib.loads(path.read_text())
            self.assertEqual(agent["name"], path.stem)
            self.assertIn(agent["model_reasoning_effort"], SUPPORTED_EFFORTS[agent["model"]])
            self.assertTrue(agent["developer_instructions"])
            self.assertNotIn("sandbox_mode", agent)

    def test_fallback_field_does_not_change_generated_agents(self):
        profiles = json.loads(PROFILES_PATH.read_text())
        stripped = {role: {k: v for k, v in p.items() if k != "fallback"} for role, p in profiles.items()}
        copy_root = Path(self.tmp) / "codex"
        (copy_root / "skills/delegating").mkdir(parents=True)
        (copy_root / "install_agents.py").write_text(INSTALLER_PATH.read_text())
        (copy_root / "skills/delegating/profiles.json").write_text(json.dumps(stripped))
        baseline = load_installer(copy_root / "install_agents.py").render_agents()
        rendered = self.installer.render_agents()
        self.assertEqual(rendered, baseline)
        for text in rendered.values():
            self.assertNotIn("fallback", tomllib.loads(text))

    def test_collision_preserves_existing_file_and_installs_nothing(self):
        destination = Path(self.tmp) / "agents"
        destination.mkdir()
        existing = destination / "steward-writer.toml"
        existing.write_text("local edits")
        with self.assertRaises(ValueError):
            self.installer.install(destination)
        self.assertEqual(existing.read_text(), "local edits")
        self.assertEqual(list(destination.iterdir()), [existing])


class CodexAstraFallbackTests(unittest.TestCase):
    def test_only_astra_roles_fall_back_to_sol_xhigh(self):
        profiles = json.loads(PROFILES_PATH.read_text())
        astra = {role for role, p in profiles.items() if p["model"] == "gpt-6-astra"}
        self.assertEqual(astra, ASTRA_ROLES)
        for role, profile in profiles.items():
            if role in ASTRA_ROLES:
                fallback = profile["fallback"]
                self.assertEqual(fallback, {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
                self.assertIn(fallback["reasoning_effort"], SUPPORTED_EFFORTS[fallback["model"]])
            else:
                self.assertNotIn("fallback", profile, role)

    def test_skill_names_the_fallback_and_named_agent_workaround(self):
        text = SKILL_PATH.read_text()
        self.assertIn("Operator decision, 2026-10-09", text)
        self.assertIn("fall back to `gpt-6.1-sol` at xhigh", text)
        self.assertIn("steward-deep-reasoner", text)
        self.assertIn("steward-top-reviewer", text)


if __name__ == "__main__":
    unittest.main()
