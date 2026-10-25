"""Tests for prose_gate_hook.py on pi: `prose_gate_hook.py pi
pr-gate|prose-gate`.

The pi extension spawns the script with the payloads it builds from pi
events: tool_name bash, tool_input and cwd for the PR gate;
last_assistant_message and stop_hook_active for the prose gate. It
registers nothing in a pi-subagents child, so the script needs no child
check of its own.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from helpers import StewardTestCase, load_hook_module, run_hook

hook = load_hook_module()

# Two distinct markers: enough to block on its own.
TWO_MARKERS = "This is crucial and pivotal."


def _deny_reason(result):
    if not result.stdout.strip():
        return None
    hso = json.loads(result.stdout)["hookSpecificOutput"]
    if hso.get("permissionDecision") != "deny":
        return None
    return hso["permissionDecisionReason"]


class PiCase(StewardTestCase):
    """Runs the hook as the pi extension does: harness argument pi and
    pi's config dir in PI_CODING_AGENT_DIR."""

    def pi_env(self, **extra):
        return self.make_env(PI_CODING_AGENT_DIR=self.config, **extra)

    def pi_env_dict(self, **extra):
        return self.env_dict(PI_CODING_AGENT_DIR=self.config, **extra)


# ---------------------------------------------------------------------------
# config dir
# ---------------------------------------------------------------------------

class PiConfigDirTests(PiCase):
    def test_config_dir_from_pi_coding_agent_dir(self):
        self.assertEqual(hook.get_config_dir("pi", self.pi_env_dict()), self.config)

    def test_pi_coding_agent_dir_tilde_expanded(self):
        env = {"HOME": self.home, "PI_CODING_AGENT_DIR": "~/custom"}
        self.assertEqual(hook.get_config_dir("pi", env), os.path.join(self.home, "custom"))

    def test_default_is_home_dot_pi_agent_and_ignores_claude_config(self):
        env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir("pi", env), os.path.join(self.home, ".pi", "agent"))


# ---------------------------------------------------------------------------
# pr-gate
# ---------------------------------------------------------------------------

class PiPrGateTests(PiCase):
    def payload(self, body=TWO_MARKERS):
        return {
            "tool_name": "bash", "cwd": self.tmp,
            "tool_input": {"command": 'gh pr create --title t --body "%s"' % body},
        }

    def test_pr_gate_on_lowercase_bash(self):
        out = json.loads(run_hook("pi", "pr-gate", self.payload(), self.pi_env()).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("PR gate", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_pr_body_file_is_checked_against_cwd(self):
        Path(self.tmp, "body.md").write_text(TWO_MARKERS, encoding="utf-8")
        payload = {"tool_name": "bash", "cwd": self.tmp,
                   "tool_input": {"command": "gh pr edit --body-file body.md"}}
        self.assertIsNotNone(_deny_reason(run_hook("pi", "pr-gate", payload, self.pi_env())))

    def test_clean_body_passes(self):
        result = run_hook("pi", "pr-gate", self.payload("plain text body"), self.pi_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_switch_file_read_from_pi_config_dir(self):
        self.write_dep("steward-prose-gate/gate", "off\n")
        self.assertEqual(run_hook("pi", "pr-gate", self.payload(), self.pi_env()).stdout, "")

    def test_prose_gate_env_switch_turns_pr_gate_off(self):
        env = self.pi_env(STEWARD_PROSE_GATE="off")
        self.assertEqual(run_hook("pi", "pr-gate", self.payload(), env).stdout, "")

    def test_operator_pattern_from_pi_config_dir(self):
        self.write_dep("steward-prose-gate/prose-patterns", "banned words here\n")
        reason = _deny_reason(run_hook(
            "pi", "pr-gate", self.payload("some banned words here"), self.pi_env()))
        self.assertIn("banned words here", reason)


# ---------------------------------------------------------------------------
# prose-gate
# ---------------------------------------------------------------------------

class PiProseGateTests(PiCase):
    def test_markers_in_last_message_block(self):
        payload = {"last_assistant_message": TWO_MARKERS, "stop_hook_active": False}
        out = json.loads(run_hook("pi", "prose-gate", payload, self.pi_env()).stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("prose gate", out["reason"])

    def test_one_revision_then_pass(self):
        payload = {"last_assistant_message": TWO_MARKERS, "stop_hook_active": True}
        self.assertEqual(run_hook("pi", "prose-gate", payload, self.pi_env()).stdout, "")

    def test_clean_reply_passes(self):
        payload = {"last_assistant_message": "All done.", "stop_hook_active": False}
        self.assertEqual(run_hook("pi", "prose-gate", payload, self.pi_env()).stdout, "")

    def test_pi_reads_patterns_from_pi_config_dir(self):
        payload = {"last_assistant_message": "A banned phrase here."}
        env = self.pi_env()
        self.assertEqual(run_hook("pi", "prose-gate", payload, env).stdout, "")
        self.write_dep("steward-prose-gate/prose-patterns", "banned phrase\n")
        out = json.loads(run_hook("pi", "prose-gate", payload, env).stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("banned phrase", out["reason"])

    def test_claude_config_dir_patterns_are_not_read(self):
        claude_dir = os.path.join(self.tmp, "claude")
        os.makedirs(os.path.join(claude_dir, "steward-prose-gate"))
        Path(claude_dir, "steward-prose-gate", "prose-patterns").write_text(
            "banned phrase\n", encoding="utf-8")
        env = self.pi_env(CLAUDE_CONFIG_DIR=claude_dir)
        payload = {"last_assistant_message": "A banned phrase here."}
        self.assertEqual(run_hook("pi", "prose-gate", payload, env).stdout, "")


# ---------------------------------------------------------------------------
# fail open
# ---------------------------------------------------------------------------

class PiFailOpenTests(PiCase):
    def test_bad_input_fails_open(self):
        for stdin in ("not json", "[1, 2]", ""):
            for mode in ("pr-gate", "prose-gate"):
                result = subprocess.run(
                    [sys.executable, str(hook.__file__), "pi", mode],
                    input=stdin, capture_output=True, text=True, env=self.pi_env())
                self.assertEqual((result.returncode, result.stdout), (0, ""), (stdin, mode))

    def test_unknown_mode_fails_open(self):
        result = run_hook("pi", "session-start", {"session_id": "s1"}, self.pi_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))
