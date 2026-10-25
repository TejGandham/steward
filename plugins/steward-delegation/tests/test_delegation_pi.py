"""Tests for the pi branch of delegation_hook.py, run as the pi extension
runs it: `delegation_hook.py pi <mode>` with pi's config dir in
PI_CODING_AGENT_DIR.

These tests never touch the real home directory; see helpers.py.
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import SCRIPT, StewardTestCase, load_hook_module, run_hook  # noqa: E402

hook = load_hook_module()


class PiHarnessCase(StewardTestCase):
    """Adds the pi skill fixture under the temp plugin root."""

    def setUp(self):
        super().setUp()
        self.write_plugin_file(
            "pi/skills/steward-delegating/SKILL.md",
            "---\n"
            "name: steward-delegating\n"
            "description: test fixture skill\n"
            "---\n"
            "Pi body of the edict.\n",
        )

    def pi_env(self, **extra):
        return self.make_env(PI_CODING_AGENT_DIR=self.config, **extra)

    def pi_env_dict(self, **extra):
        return self.env_dict(PI_CODING_AGENT_DIR=self.config, **extra)

    def context(self, env):
        result = run_hook("pi", "session-start", {"session_id": "pi-s1"}, env)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


class PiConfigDirTests(PiHarnessCase):
    def test_pi_agent_dir_from_env(self):
        self.assertEqual(hook.get_config_dir(self.pi_env_dict(), "pi"), self.config)

    def test_pi_default_is_home_pi_agent(self):
        env = {"HOME": self.home}
        self.assertEqual(hook.get_config_dir(env, "pi"), os.path.join(self.home, ".pi", "agent"))

    def test_claude_config_dir_ignored_under_pi(self):
        env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir(env, "pi"), os.path.join(self.home, ".pi", "agent"))


class PiSessionStartTests(PiHarnessCase):
    def test_uses_pi_skill_without_wrapper_tags(self):
        text = self.context(self.pi_env())
        self.assertIn("Pi body of the edict.", text)
        self.assertIn("steward-delegating", text)
        self.assertNotIn("Body text of the delegating skill.", text)
        self.assertNotIn("<STEWARD>", text)
        self.assertNotIn("name: steward-delegating", text)
        # No plainlanguage skill is installed in the temp dirs, and the
        # hook no longer warns about it: the edict says what to do.
        self.assertNotIn("STEWARD WARNING", text)

    def test_does_not_create_orchestration_registry(self):
        self.context(self.pi_env())
        self.assertFalse(os.path.exists(os.path.join(self.orch, "initiatives.md")))

    def test_update_pr_summary_is_optional(self):
        self.write_dep("skills/plainlanguage/SKILL.md")
        text = self.context(self.pi_env())
        self.assertNotIn("STEWARD WARNING", text)
        self.assertNotIn("update-pr-summary", text)


class PiGateTests(PiHarnessCase):
    def _write(self, session_id, path="/some/where/file.txt"):
        return {
            "session_id": session_id, "tool_name": "write",
            "tool_input": {"path": path, "content": "x"}, "cwd": "/some/where",
        }

    def test_second_lowercase_write_denied_with_pi_profile_names(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        self.assertEqual(run_hook("pi", "gate", self._write("pg1"), env).stdout, "")
        out = json.loads(run_hook("pi", "gate", self._write("pg1"), env).stdout)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(reason.startswith("steward delegation gate"), reason)
        self.assertIn("steward.coder ", reason)
        self.assertIn("steward.mechanic ", reason)
        self.assertNotIn("steward.coder-opus-medium", reason)
        self.assertIn("subagent tool", reason)
        self.assertIn(os.path.join(self.config, "steward-delegation", "gate"), reason)
        self.assertIn("STEWARD_DELEGATION_GATE", reason)
        self.assertNotIn("steward:", reason)
        self.assertNotIn("steward-delegation:", reason)

    def test_edit_tool_path_field_is_read(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "pg2", "tool_name": "edit",
            "tool_input": {"path": "/tmp/scratch.txt", "edits": []},
        }
        run_hook("pi", "gate", payload, env)
        # /tmp is allowlisted, so the edit is exempt every time
        self.assertEqual(run_hook("pi", "gate", payload, env).stdout, "")

    def test_extra_file_path_argument_does_not_exempt_a_pi_write(self):
        # pi writes to "path"; a stray "file_path" naming /tmp must not win.
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "pg8", "tool_name": "write",
            "tool_input": {"path": "/some/where/main.ts", "file_path": "/tmp/x", "content": "x"},
        }
        run_hook("pi", "gate", payload, env)
        out = json.loads(run_hook("pi", "gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_lowercase_bash_classified(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "pg3", "tool_name": "bash",
            "tool_input": {"command": "echo hi > /some/where/out.txt"},
        }
        run_hook("pi", "gate", payload, env)
        out = json.loads(run_hook("pi", "gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_lowercase_bash_read_only_passes(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        payload = {"session_id": "pg4", "tool_name": "bash", "tool_input": {"command": "ls -la"}}
        run_hook("pi", "gate", payload, env)
        self.assertEqual(run_hook("pi", "gate", payload, env).stdout, "")

    def test_gate_mode_file_read_from_pi_config_dir(self):
        self.write_dep("steward-delegation/gate", "off\n")
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("pi", "gate", self._write("pg6"), env)
        self.assertEqual(run_hook("pi", "gate", self._write("pg6"), env).stdout, "")

    def test_agents_md_and_dot_pi_allowlisted_only_under_pi(self):
        pi_env = self.pi_env_dict()
        claude_env = self.env_dict()
        for path in ("/repo/AGENTS.md", "/repo/.pi/settings.json"):
            self.assertTrue(hook.is_allowlisted(path, pi_env, harness="pi"), path)
            self.assertFalse(hook.is_allowlisted(path, claude_env), path)

    def test_pi_config_dir_allowlisted(self):
        path = os.path.join(self.config, "settings.json")
        self.assertTrue(hook.is_allowlisted(path, self.pi_env_dict(), harness="pi"))

    def test_claude_names_still_work_under_pi(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "pg7", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/f.txt", "content": "x"},
        }
        run_hook("pi", "gate", payload, env)
        out = json.loads(run_hook("pi", "gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_delegated_resets_the_count(self):
        env = self.pi_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("pi", "gate", self._write("pg9"), env)
        self.assertEqual(run_hook("pi", "delegated", {"session_id": "pg9"}, env).stdout, "")
        self.assertEqual(run_hook("pi", "gate", self._write("pg9"), env).stdout, "")


class PiCliModeExitTests(PiHarnessCase):
    """The three CLI modes: JSON in, JSON out, exit 2 on bad input."""

    def run_cli(self, mode, raw, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "pi", mode, *args], input=raw,
                              capture_output=True, text=True, env=self.pi_env())

    def test_bad_input_exits_2_with_an_error_object(self):
        for mode in ("model-plan", "model-plan-apply", "delegation-stats"):
            out = self.run_cli(mode, "nope")
            self.assertEqual(out.returncode, 2, (mode, out.stderr))
            self.assertIn("error", json.loads(out.stdout))
            self.assertIn(mode + ":", out.stderr)

    def test_other_harnesses_have_no_cli_modes(self):
        for harness in ("claude", "copilot", "codex"):
            out = subprocess.run([sys.executable, str(SCRIPT), harness, "model-plan"], input="nope",
                                 capture_output=True, text=True, env=self.pi_env())
            self.assertEqual((out.returncode, out.stdout), (0, ""), harness)


if __name__ == "__main__":
    unittest.main()
