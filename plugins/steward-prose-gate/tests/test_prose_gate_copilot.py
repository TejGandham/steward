"""Tests for prose_gate_hook.py on Copilot: `prose_gate_hook.py copilot
session-start|pr-gate|prose-gate`."""

import json
import os
import re
import threading
import time
import unittest
from unittest import mock

from helpers import PLUGIN_ROOT, StewardTestCase, load_hook_module, run_hook

hook = load_hook_module()

# Built from a code point, not typed literally, so this file's own bytes
# never contain the character the tests are checking for.
EM_DASH = chr(0x2014)

# Two distinct markers: enough to block on its own.
TWO_MARKERS = "This is crucial and pivotal."

HOOKS_JSON = PLUGIN_ROOT / "copilot" / "hooks.json"


class CopilotCase(StewardTestCase):
    """Runs the hook as Copilot does: harness argument copilot and the
    Copilot config dir in COPILOT_HOME."""

    def co_env(self, **extra):
        return self.make_env(COPILOT_HOME=self.config, **extra)

    def co_env_dict(self, **extra):
        return self.env_dict(COPILOT_HOME=self.config, **extra)

    def start(self, env, session_id="main-1"):
        result = run_hook(
            "copilot", "session-start",
            {"session_id": session_id, "hook_event_name": "SessionStart", "source": "startup"},
            env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        return result

    def marker_path(self, session_id):
        return os.path.join(self.state, "steward-prose-gate", "copilot-main",
                            hook._sanitize_session_id(session_id))


# ---------------------------------------------------------------------------
# config dir
# ---------------------------------------------------------------------------

class CopilotConfigDirTests(CopilotCase):
    def test_config_dir_from_copilot_home(self):
        self.assertEqual(hook.get_config_dir("copilot", self.co_env_dict()), self.config)

    def test_copilot_home_tilde_expanded(self):
        env = {"HOME": self.home, "COPILOT_HOME": "~/cop"}
        self.assertEqual(hook.get_config_dir("copilot", env), os.path.join(self.home, "cop"))

    def test_default_is_home_dot_copilot(self):
        env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir("copilot", env), os.path.join(self.home, ".copilot"))

    def test_switch_file_read_from_copilot_home(self):
        env = self.co_env()
        self.start(env, "m1")
        self.write_dep("steward-prose-gate/gate", "off")
        payload = {"session_id": "m1", "last_assistant_message": TWO_MARKERS}
        self.assertEqual(run_hook("copilot", "prose-gate", payload, env).stdout, "")


# ---------------------------------------------------------------------------
# session-start: the main-session record
# ---------------------------------------------------------------------------

class CopilotSessionStartTests(CopilotCase):
    def test_records_main_session_and_prints_nothing(self):
        self.start(self.co_env(), "main/1")
        self.assertTrue(os.path.isfile(self.marker_path("main/1")))

    def test_record_stays_inside_state_dir(self):
        self.start(self.co_env(), "../../evil")
        directory = os.path.join(self.state, "steward-prose-gate", "copilot-main")
        self.assertEqual(os.listdir(directory), [hook._sanitize_session_id("../../evil")])
        self.assertNotIn("/", hook._sanitize_session_id("../../evil"))

    def test_resumed_session_keeps_record(self):
        env = self.co_env()
        self.start(env, "m2")
        self.start(env, "m2")
        self.assertTrue(os.path.isfile(self.marker_path("m2")))

    def test_no_session_id_records_nothing(self):
        result = run_hook("copilot", "session-start", {}, self.co_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.state, "steward-prose-gate", "copilot-main")))

    def test_unwritable_state_dir_fails_open(self):
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        env = self.co_env(XDG_STATE_HOME=blocker)
        result = run_hook("copilot", "session-start", {"session_id": "m3"}, env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_claude_has_no_session_start(self):
        result = run_hook("claude", "session-start", {"session_id": "c1"}, self.make_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.state, "steward-prose-gate", "copilot-main")))


# ---------------------------------------------------------------------------
# pr-gate
# ---------------------------------------------------------------------------

def _deny_reason(result):
    out = json.loads(result.stdout)
    hso = out["hookSpecificOutput"]
    if hso.get("permissionDecision") != "deny":
        return None
    return hso["permissionDecisionReason"]


class CopilotPrGateTests(CopilotCase):
    def payload(self, session_id, body=TWO_MARKERS):
        return {
            "session_id": session_id, "tool_name": "Bash",
            "tool_input": {"command": 'gh pr create --title t --body "%s"' % body},
        }

    def test_pr_gate_in_main_session(self):
        env = self.co_env()
        self.start(env, "m8")
        reason = _deny_reason(run_hook("copilot", "pr-gate", self.payload("m8"), env))
        self.assertIsNotNone(reason)
        self.assertIn("PR gate", reason)

    def test_unrecorded_session_not_gated(self):
        env = self.co_env()
        self.start(env, "m8")
        result = run_hook("copilot", "pr-gate", self.payload("sub-1"), env)
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_no_session_id_not_gated(self):
        env = self.co_env()
        self.start(env, "m8")
        payload = self.payload("m8")
        del payload["session_id"]
        self.assertEqual(run_hook("copilot", "pr-gate", payload, env).stdout, "")

    def test_clean_body_passes(self):
        env = self.co_env()
        self.start(env, "m8")
        result = run_hook("copilot", "pr-gate", self.payload("m8", "plain text body"), env)
        self.assertEqual(result.stdout, "")

    def test_operator_pattern_from_copilot_home(self):
        env = self.co_env()
        self.start(env, "m8")
        self.write_dep("steward-prose-gate/prose-patterns", "banned words here\n")
        reason = _deny_reason(run_hook(
            "copilot", "pr-gate", self.payload("m8", "some banned words here"), env))
        self.assertIn("banned words here", reason)


# ---------------------------------------------------------------------------
# prose-gate: events.jsonl
# ---------------------------------------------------------------------------

class CopilotProseGateTests(CopilotCase):
    STOP_ISO = "2026-10-09T05:47:28.833Z"
    STOP_MS = 1791524848833

    def _transcript(self, events):
        path = os.path.join(self.tmp, "events.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        return path

    @classmethod
    def stop_marker(cls, session_id="m1", ms=None):
        return {
            "type": "hook.start",
            "data": {
                "hookInvocationId": "h",
                "hookType": "agentStop",
                "input": {
                    "sessionId": session_id,
                    "transcriptPath": "/x/events.jsonl",
                    "stopReason": "end_turn",
                    "stop_hook_active": False,
                    "timestamp": cls.STOP_MS if ms is None else ms,
                    "cwd": "/x",
                },
            },
            "id": "hs",
            "timestamp": cls.STOP_ISO,
        }

    @staticmethod
    def user(text):
        return {"type": "user.message", "data": {"content": text}, "id": "u"}

    @staticmethod
    def assistant(text, agent_id=None):
        event = {"type": "assistant.message", "data": {"content": text, "toolRequests": []}, "id": "a"}
        if agent_id:
            event["agentId"] = agent_id
        return event

    def _run(self, events, record=True, marker=True, **extra):
        env = self.co_env()
        if record:
            self.start(env, "m1")
        if marker:
            events = list(events) + [self.stop_marker()]
        payload = {
            "session_id": "m1",
            "transcript_path": self._transcript(events),
            "timestamp": self.STOP_ISO,
        }
        payload.update(extra)
        return run_hook("copilot", "prose-gate", payload, env)

    def _gate(self, events, session_id="m1", timestamp=STOP_ISO):
        """In-process gate call with the main-session marker recorded."""
        env = self.co_env_dict()
        hook._record_copilot_main_session(env, session_id)
        payload = {"session_id": session_id, "transcript_path": self._transcript(events)}
        if timestamp is not None:
            payload["timestamp"] = timestamp
        return hook.cmd_prose_gate("copilot", payload, env)

    # main-session record and skip

    def test_unrecorded_session_passes(self):
        result = self._run([self.user("hi"), self.assistant(TWO_MARKERS)], record=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_recorded_session_blocks(self):
        result = self._run([self.user("hi"), self.assistant(TWO_MARKERS)])
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("crucial", out["reason"])

    def test_recorded_session_blocks_on_last_assistant_message(self):
        env = self.co_env()
        self.start(env, "m1")
        payload = {"session_id": "m1", "last_assistant_message": TWO_MARKERS}
        self.assertEqual(json.loads(run_hook("copilot", "prose-gate", payload, env).stdout)["decision"],
                         "block")

    def test_subagent_stop_with_parent_transcript_passes(self):
        # A subagent's Stop carries its own session id and the parent's
        # transcript path; the parent's prose must not block it.
        result = self._run(
            [self.user("hi"), self.assistant(TWO_MARKERS), self.stop_marker(session_id="sub-9")],
            marker=False,
            session_id="sub-9",
        )
        self.assertEqual(result.stdout, "")

    def test_claude_harness_ignores_copilot_record(self):
        # The Claude Code branch gates every session without a record.
        payload = {"session_id": "never-recorded", "last_assistant_message": TWO_MARKERS}
        result = run_hook("claude", "prose-gate", payload, self.make_env())
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    # events.jsonl wait

    def test_events_after_stop_marker_are_ignored(self):
        out = self._gate([
            self.user("go"),
            self.assistant("Plain reply."),
            self.stop_marker(),
            self.assistant("Later: " + TWO_MARKERS),
        ])
        self.assertIsNone(out)

    def test_stop_marker_with_far_timestamp_is_not_used(self):
        # A marker 5 s away is a different stop, so the gate waits out the
        # limit and parses everything, catching the markers after it.
        with mock.patch.object(hook, "_COPILOT_FLUSH_LIMIT_SECONDS", 0.05), \
                mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            out = self._gate([
                self.user("go"),
                self.assistant("Plain reply."),
                self.stop_marker(ms=self.STOP_MS - 5000),
                self.assistant("Later: " + TWO_MARKERS),
            ])
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_stop_marker_without_payload_timestamp(self):
        out = self._gate([
            self.user("go"),
            self.assistant("Plain reply."),
            self.stop_marker(),
            self.assistant("Later: " + TWO_MARKERS),
        ], timestamp=None)
        self.assertIsNone(out)

    def test_stop_marker_before_last_user_message_is_ignored_without_timestamp(self):
        with mock.patch.object(hook, "_COPILOT_FLUSH_LIMIT_SECONDS", 0.05), \
                mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            out = self._gate([
                self.user("first"),
                self.assistant("Old."),
                self.stop_marker(),
                self.user("second"),
                self.assistant("New: " + TWO_MARKERS),
            ], timestamp=None)
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_missing_marker_waits_limit_then_parses(self):
        with mock.patch.object(hook, "_COPILOT_FLUSH_LIMIT_SECONDS", 0.05), \
                mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            began = time.monotonic()
            out = self._gate([self.user("go"), self.assistant("Final: " + TWO_MARKERS)])
            elapsed = time.monotonic() - began
        self.assertEqual(json.loads(out)["decision"], "block")
        self.assertGreaterEqual(elapsed, 0.05)
        self.assertLess(elapsed, 1.0)

    def test_late_flush_is_caught(self):
        # The first reads miss the final message and the stop marker, as
        # when the hook runs before Copilot flushes events.jsonl.
        short = "\n".join(json.dumps(e) for e in [
            self.user("go"), self.assistant("Working."),
        ]) + "\n"
        full = short + "\n".join(json.dumps(e) for e in [
            self.assistant("Final: " + TWO_MARKERS), self.stop_marker(),
        ]) + "\n"
        reads = iter([short, short, full])
        with mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01), \
                mock.patch.object(hook, "_read_transcript_tail",
                                  side_effect=lambda _p: next(reads, full)):
            out = self._gate([])
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_late_flush_from_writer_thread_is_caught(self):
        path = self._transcript([self.user("go"), self.assistant("Working.")])

        def writer():
            time.sleep(0.05)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.assistant("Final: " + TWO_MARKERS)) + "\n")
                f.write(json.dumps(self.stop_marker()) + "\n")

        env = self.co_env_dict()
        hook._record_copilot_main_session(env, "m1")
        thread = threading.Thread(target=writer)
        with mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            thread.start()
            out = hook.cmd_prose_gate(
                "copilot", {"session_id": "m1", "transcript_path": path, "timestamp": self.STOP_ISO}, env)
            thread.join()
        self.assertEqual(json.loads(out)["decision"], "block")

    # which text counts

    def test_markers_in_last_main_reply_block(self):
        result = self._run([
            self.user("hi"),
            self.assistant(""),
            self.assistant("Done. " + TWO_MARKERS),
        ])
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("pivotal", out["reason"])

    def test_markers_only_in_subagent_event_pass(self):
        result = self._run([
            self.user("hi"),
            self.assistant("sub " + TWO_MARKERS, agent_id="sub-1"),
            dict(self.user("subagent prompt " + TWO_MARKERS), agentId="sub-1"),
            self.assistant("Plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_markers_in_earlier_turn_pass(self):
        result = self._run([
            self.user("first"),
            self.assistant("Old: " + TWO_MARKERS),
            self.user("second"),
            self.assistant("New plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_markers_in_mid_turn_message_pass(self):
        result = self._run([
            self.user("go"),
            self.assistant("Looking: " + TWO_MARKERS),
            self.assistant("Final plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_markers_in_final_message_block(self):
        result = self._run([
            self.user("go"),
            self.assistant("Looking now."),
            self.assistant("Final: " + TWO_MARKERS),
        ])
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_em_dash_alone_does_not_block(self):
        result = self._run([self.user("go"), self.assistant("Done " + EM_DASH + " ok.")])
        self.assertEqual(result.stdout, "")

    # task_complete

    def test_markers_in_task_complete_summary_block(self):
        result = self._run([
            self.user("go"),
            self.assistant("Working."),
            {"type": "session.task_complete", "data": {"summary": TWO_MARKERS, "success": True}},
        ])
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_markers_split_across_message_and_summary_block(self):
        result = self._run([
            self.user("go"),
            self.assistant("This is crucial."),
            {"type": "session.task_complete", "data": {"summary": "A pivotal fix.", "success": True}},
        ])
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_parser_returns_final_message_and_summary(self):
        path = self._transcript([
            self.user("go"),
            self.assistant("one"),
            self.assistant("", agent_id="s"),
            self.assistant("two"),
            self.assistant(""),
            {"type": "session.task_complete", "data": {"summary": "three"}},
        ])
        self.assertEqual(hook._extract_last_copilot_text(path), "two\n\nthree")

    def test_no_user_message_returns_none(self):
        path = self._transcript([
            self.assistant("Old: " + TWO_MARKERS),
            {"type": "session.task_complete", "data": {"summary": "x"}},
        ])
        self.assertIsNone(hook._extract_last_copilot_text(path))

    # fail open

    def test_stop_hook_active_passes(self):
        result = self._run([self.user("x"), self.assistant(TWO_MARKERS)], stop_hook_active=True)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_passes(self):
        env = self.co_env()
        self.start(env, "m1")
        payload = {"session_id": "m1", "transcript_path": os.path.join(self.tmp, "nope.jsonl")}
        result = run_hook("copilot", "prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


# ---------------------------------------------------------------------------
# copilot/hooks.json
# ---------------------------------------------------------------------------

_COMMAND_RE = re.compile(
    r'^python3 "\$\{PLUGIN_ROOT\}/hooks/prose_gate_hook\.py" copilot (session-start|pr-gate|prose-gate)$'
)


class CopilotHooksJsonTests(unittest.TestCase):
    def setUp(self):
        self.text = HOOKS_JSON.read_text(encoding="utf-8")
        self.hooks = json.loads(self.text)["hooks"]

    def test_events_matchers_timeouts_and_modes(self):
        expected = {
            "SessionStart": (None, "session-start", 10),
            "PreToolUse": ("Bash", "pr-gate", 10),
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
