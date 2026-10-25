"""Tests for prose_gate_hook.py on Codex: `prose_gate_hook.py codex
pr-gate|prose-gate`.

Codex children share the parent's session_id, so the PR gate runs for
every call. The Codex prose gate reads only last_assistant_message and
never a transcript, because Codex transcripts are not a stable hook
interface.
"""

import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from helpers import PLUGIN_ROOT, StewardTestCase, load_hook_module, run_hook

hook = load_hook_module()

# Built from a code point, not typed literally, so this file's own bytes
# never contain the character the tests are checking for.
EM_DASH = chr(0x2014)

# Two distinct markers: enough to block on its own.
TWO_MARKERS = "This is crucial and pivotal."

HOOKS_JSON = PLUGIN_ROOT / "codex" / "hooks.json"


def _deny_reason(result):
    if not result.stdout.strip():
        return None
    hso = json.loads(result.stdout)["hookSpecificOutput"]
    if hso.get("permissionDecision") != "deny":
        return None
    return hso["permissionDecisionReason"]


class CodexCase(StewardTestCase):
    """Runs the hook as Codex does: harness argument codex and the Codex
    config dir in CODEX_HOME."""

    def cx_env(self, **extra):
        return self.make_env(CODEX_HOME=self.config, **extra)

    def cx_env_dict(self, **extra):
        return self.env_dict(CODEX_HOME=self.config, **extra)


# ---------------------------------------------------------------------------
# config dir
# ---------------------------------------------------------------------------

class CodexConfigDirTests(CodexCase):
    def test_config_dir_from_codex_home(self):
        self.assertEqual(hook.get_config_dir("codex", self.cx_env_dict()), self.config)

    def test_codex_home_tilde_expanded(self):
        env = {"HOME": self.home, "CODEX_HOME": "~/custom"}
        self.assertEqual(hook.get_config_dir("codex", env), os.path.join(self.home, "custom"))

    def test_default_is_home_dot_codex_and_ignores_claude_config(self):
        env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir("codex", env), os.path.join(self.home, ".codex"))


# ---------------------------------------------------------------------------
# pr-gate
# ---------------------------------------------------------------------------

class CodexPrGateTests(CodexCase):
    def payload(self, body=TWO_MARKERS, **extra):
        payload = {
            "session_id": "shared", "tool_name": "Bash",
            "tool_input": {"command": 'gh pr create --title t --body "%s"' % body},
        }
        payload.update(extra)
        return payload

    def test_pr_body_file_is_checked_against_cwd(self):
        Path(self.tmp, "body.md").write_text(TWO_MARKERS, encoding="utf-8")
        payload = {"session_id": "shared", "tool_name": "Bash", "cwd": self.tmp,
                   "tool_input": {"command": "gh pr create --body-file body.md"}}
        reason = _deny_reason(run_hook("codex", "pr-gate", payload, self.cx_env()))
        self.assertIsNotNone(reason)
        self.assertIn("PR gate", reason)

    def test_shared_session_id_is_gated_on_every_call(self):
        env = self.cx_env()
        for _ in range(3):
            self.assertIsNotNone(_deny_reason(run_hook("codex", "pr-gate", self.payload(), env)))

    def test_child_call_is_gated(self):
        # Codex cannot tell a child from the parent; nothing in the payload
        # turns the gate off for a call.
        env = self.cx_env()
        self.assertIsNotNone(_deny_reason(run_hook(
            "codex", "pr-gate", self.payload(agent_id="child-1"), env)))
        payload = self.payload()
        del payload["session_id"]
        self.assertIsNotNone(_deny_reason(run_hook("codex", "pr-gate", payload, env)))

    def test_delegation_gate_off_leaves_pr_gate_on(self):
        env = self.cx_env(STEWARD_DELEGATION_GATE="off")
        self.assertIsNotNone(_deny_reason(run_hook("codex", "pr-gate", self.payload(), env)))

    def test_prose_gate_switch_turns_pr_gate_off(self):
        env = self.cx_env(STEWARD_PROSE_GATE="off")
        self.assertEqual(run_hook("codex", "pr-gate", self.payload(), env).stdout, "")

    def test_switch_file_read_from_codex_home(self):
        self.write_dep("steward-prose-gate/gate", "off")
        self.assertEqual(run_hook("codex", "pr-gate", self.payload(), self.cx_env()).stdout, "")

    def test_clean_body_passes(self):
        result = run_hook("codex", "pr-gate", self.payload("plain text body"), self.cx_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_non_bash_tool_passes(self):
        payload = self.payload()
        payload["tool_name"] = "apply_patch"
        self.assertEqual(run_hook("codex", "pr-gate", payload, self.cx_env()).stdout, "")

    def test_operator_pattern_from_codex_home(self):
        self.write_dep("steward-prose-gate/prose-patterns", "banned words here\n")
        reason = _deny_reason(run_hook(
            "codex", "pr-gate", self.payload("some banned words here"), self.cx_env()))
        self.assertIn("banned words here", reason)


# ---------------------------------------------------------------------------
# prose-gate
# ---------------------------------------------------------------------------

class CodexProseGateTests(CodexCase):
    def test_markers_in_last_message_block(self):
        payload = {"session_id": "shared", "last_assistant_message": TWO_MARKERS}
        out = json.loads(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("prose gate", out["reason"])

    def test_child_stop_is_gated(self):
        payload = {"session_id": "shared", "agent_id": "child-1",
                   "last_assistant_message": TWO_MARKERS}
        out = json.loads(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout)
        self.assertEqual(out["decision"], "block")

    def test_one_revision_then_pass(self):
        payload = {"last_assistant_message": TWO_MARKERS, "stop_hook_active": True}
        self.assertEqual(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout, "")

    def test_operator_patterns_use_codex_home(self):
        self.write_dep("steward-prose-gate/prose-patterns", "banned phrase\n")
        payload = {"last_assistant_message": "A banned phrase."}
        out = json.loads(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("banned phrase", out["reason"])

    def test_em_dash_alone_does_not_block(self):
        payload = {"last_assistant_message": "Fix " + EM_DASH + " details " + EM_DASH + " more"}
        self.assertEqual(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout, "")

    def test_transcript_is_never_parsed(self):
        transcript = Path(self.tmp) / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": TWO_MARKERS}]}}) + "\n", encoding="utf-8")
        payload = {"session_id": "shared", "transcript_path": str(transcript)}
        self.assertEqual(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout, "")

    def test_transcript_readers_are_not_called(self):
        payload = {"transcript_path": "/any/path.jsonl", "last_assistant_message": ""}
        with mock.patch.object(hook, "_extract_last_assistant_text") as claude_reader, \
                mock.patch.object(hook, "_extract_last_copilot_text") as copilot_reader:
            self.assertIsNone(hook.cmd_prose_gate("codex", payload, self.cx_env_dict()))
        claude_reader.assert_not_called()
        copilot_reader.assert_not_called()


# ---------------------------------------------------------------------------
# fail open
# ---------------------------------------------------------------------------

class CodexFailOpenTests(CodexCase):
    def test_bad_input_fails_open(self):
        import subprocess
        import sys
        for stdin in ("not json", "[1, 2]", ""):
            for mode in ("pr-gate", "prose-gate"):
                result = subprocess.run(
                    [sys.executable, str(hook.__file__), "codex", mode],
                    input=stdin, capture_output=True, text=True, env=self.cx_env())
                self.assertEqual((result.returncode, result.stdout), (0, ""), (stdin, mode))

    def test_unknown_mode_fails_open(self):
        result = run_hook("codex", "session-start", {"session_id": "s1"}, self.cx_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_unreadable_config_fails_open(self):
        # A config dir path that is a file: switch and patterns cannot be read.
        Path(self.config).write_text("not a dir", encoding="utf-8")
        payload = {"last_assistant_message": TWO_MARKERS}
        out = json.loads(run_hook("codex", "prose-gate", payload, self.cx_env()).stdout)
        self.assertEqual(out["decision"], "block")

    def test_unreadable_body_file_fails_open(self):
        payload = {"tool_name": "Bash", "cwd": self.tmp,
                   "tool_input": {"command": "gh pr create --body-file missing.md"}}
        result = run_hook("codex", "pr-gate", payload, self.cx_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))


# ---------------------------------------------------------------------------
# codex/hooks.json
# ---------------------------------------------------------------------------

_COMMAND_RE = re.compile(
    r'^python3 "\$\{PLUGIN_ROOT\}/hooks/prose_gate_hook\.py" codex (pr-gate|prose-gate)$'
)


class CodexHooksJsonTests(unittest.TestCase):
    def setUp(self):
        self.text = HOOKS_JSON.read_text(encoding="utf-8")
        self.hooks = json.loads(self.text)["hooks"]

    def test_events_matchers_timeouts_and_modes(self):
        expected = {
            "PreToolUse": ("^Bash$", "pr-gate", 10),
            "Stop": (None, "prose-gate", 15),
        }
        self.assertEqual(sorted(self.hooks), sorted(expected))
        for event, (matcher, mode, timeout) in expected.items():
            groups = self.hooks[event]
            self.assertEqual(len(groups), 1, event)
            self.assertEqual(groups[0].get("matcher"), matcher, event)
            entries = groups[0]["hooks"]
            self.assertEqual(len(entries), 1, event)
            entry = entries[0]
            self.assertEqual(entry["type"], "command", event)
            self.assertEqual(entry["timeout"], timeout, event)
            m = _COMMAND_RE.match(entry["command"])
            self.assertIsNotNone(m, entry["command"])
            self.assertEqual(m.group(1), mode, event)

    def test_no_harness_env_var(self):
        self.assertNotIn("STEWARD_HARNESS", self.text)


if __name__ == "__main__":
    unittest.main()
