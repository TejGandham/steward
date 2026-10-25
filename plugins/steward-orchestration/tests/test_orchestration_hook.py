"""Tests for orchestration_hook.py: `orchestration_hook.py claude session-start`.

These tests never touch the real home directory. Every test gets its own
temp dirs for HOME and STEWARD_ORCHESTRATION_DIR.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "hooks" / "orchestration_hook.py"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"

# The retired skill name, built from parts so this plugin's own files never
# carry the old namespace that the binder's grep checks for.
OLD_SKILL = "steward" + ":orchestrating"

RELIES_ON = (
    "This plugin relies on steward-delegation. If the "
    "`steward-delegation:delegating` skill is not in your skill list, tell "
    "the operator once."
)


def run_hook(harness, mode, payload, env):
    """Run the script as `orchestration_hook.py <harness> <mode>`."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), harness, mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


class OrchestrationTestCase(unittest.TestCase):
    """Base case: a throwaway HOME and orchestration dir per test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-orch-test-")
        self.home = os.path.join(self.tmp, "home")
        self.orch = os.path.join(self.tmp, "orch")
        os.makedirs(self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_env(self):
        env = {"PATH": os.environ.get("PATH", "")}
        env["HOME"] = self.home
        env["STEWARD_ORCHESTRATION_DIR"] = self.orch
        return env

    def session_start(self, env=None):
        return run_hook("claude", "session-start", {"session_id": "s1"},
                        env or self.make_env())


class SessionStartTests(OrchestrationTestCase):

    def test_registry_created_once(self):
        self.session_start()
        registry = os.path.join(self.orch, "initiatives.md")
        self.assertTrue(os.path.isfile(registry))
        with open(registry, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Orchestration registry", content)
        self.assertIn("| Initiative |", content)

    def test_registry_not_overwritten(self):
        os.makedirs(self.orch, exist_ok=True)
        registry = os.path.join(self.orch, "initiatives.md")
        with open(registry, "w", encoding="utf-8") as f:
            f.write("custom content that must survive\n")
        self.session_start()
        self.session_start()
        with open(registry, encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "custom content that must survive\n")

    def test_unwritable_orchestration_dir_still_emits_context(self):
        env = self.make_env()
        blocked_parent = os.path.join(self.tmp, "blocked")
        os.makedirs(blocked_parent, exist_ok=True)
        os.chmod(blocked_parent, 0o500)
        env["STEWARD_ORCHESTRATION_DIR"] = os.path.join(blocked_parent, "orch")
        try:
            result = self.session_start(env)
            self.assertEqual(result.returncode, 0)
            out = json.loads(result.stdout)
            self.assertIn("Role check", out["hookSpecificOutput"]["additionalContext"])
        finally:
            os.chmod(blocked_parent, 0o700)

    def test_block_carries_role_check_and_relies_on_sentence(self):
        result = self.session_start()
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        text = out["additionalContext"]
        self.assertIn("Role check", text)
        self.assertIn("initiatives.md", text)
        self.assertIn("$STEWARD_ORCHESTRATION_DIR/initiatives.md", text)
        self.assertIn("`steward-orchestration:orchestrating`", text)
        self.assertNotIn(OLD_SKILL, text)
        self.assertIn(RELIES_ON, text)

    def test_created_registry_names_new_skill_and_minimal_separator(self):
        self.session_start()
        with open(os.path.join(self.orch, "initiatives.md"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("`steward-orchestration:orchestrating`", content)
        self.assertNotIn(OLD_SKILL, content)
        self.assertIn("\n|-|-|-|-|-|\n", content)
        self.assertNotIn("|---", content)

    def test_default_dir_is_under_home_not_config_dir(self):
        env = self.make_env()
        del env["STEWARD_ORCHESTRATION_DIR"]
        env["CLAUDE_CONFIG_DIR"] = os.path.join(self.tmp, "profile")
        self.session_start(env)
        self.assertTrue(os.path.isfile(
            os.path.join(self.home, ".claude", "orchestration", "initiatives.md")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "profile")))

    def test_unknown_harness_exits_zero_silently(self):
        result = run_hook("copilot", "session-start", {}, self.make_env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.orch))

    def test_unknown_mode_exits_zero_silently(self):
        result = run_hook("claude", "prose-gate", {}, self.make_env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(self.orch))


class HooksJsonTests(unittest.TestCase):

    def test_one_session_start_entry(self):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        hooks = data["hooks"]
        self.assertEqual(list(hooks), ["SessionStart"])
        entries = hooks["SessionStart"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "startup|resume|clear|compact|fork")
        self.assertEqual(len(entries[0]["hooks"]), 1)
        hook = entries[0]["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertEqual(hook["timeout"], 10)
        self.assertEqual(
            hook["command"],
            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/orchestration_hook.py" claude session-start',
        )


if __name__ == "__main__":
    unittest.main()
