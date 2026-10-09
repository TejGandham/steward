"""Tests for the GitHub Copilot side of steward.

Two groups:
- the hook script in copilot mode (STEWARD_HARNESS=copilot), with
  Copilot-shaped payloads and events.jsonl transcripts;
- the Copilot plugin files: the manifest, hooks.json, the agent profiles
  (which must stay in step with the Claude Code ones under the role-only
  names in COPILOT_NAMES) and the edict skill.
"""

import json
import os
import re
import threading
import time
import unittest
from unittest import mock

from test_steward_hook import EM_DASH, REPO_ROOT, StewardTestCase, hook, run_hook


COPILOT_DIR = REPO_ROOT / "copilot"
COPILOT_AGENTS = COPILOT_DIR / "agents"
COPILOT_SKILLS = COPILOT_DIR / "skills"
CLAUDE_AGENTS = REPO_ROOT / "agents"
COPILOT_MANIFEST = REPO_ROOT / ".github" / "plugin" / "plugin.json"

# Claude Code profile name -> Copilot role-only profile name.
COPILOT_NAMES = {
    "coder-opus-medium": "coder",
    "deep-reasoner-opus-xhigh": "deep-reasoner",
    "reviewer-sonnet-high": "reviewer",
    "researcher-sonnet-low": "researcher",
    "writer-sonnet-medium": "writer",
    "mechanic-haiku-medium": "mechanic",
    "reviewer-fable-xhigh": "top-reviewer",
}


def _to_copilot_names(text):
    for old in sorted(COPILOT_NAMES, key=len, reverse=True):
        text = text.replace(old, COPILOT_NAMES[old])
    return text


class CopilotHarnessCase(StewardTestCase):
    """Runs the hook as Copilot does: STEWARD_HARNESS=copilot and the
    Copilot config dir in COPILOT_HOME."""

    def setUp(self):
        super().setUp()
        skill_dir = os.path.join(self.plugin_root, "copilot", "skills", "delegating")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: delegating\n"
                "description: test fixture skill\n"
                "---\n"
                "Copilot body of the edict.\n"
            )

    def make_env(self, **extra):
        env = super().make_env(**extra)
        if "COPILOT_HOME" not in extra:
            env.pop("COPILOT_HOME", None)
        return env

    def co_env(self, **extra):
        return self.make_env(STEWARD_HARNESS="copilot", COPILOT_HOME=self.config, **extra)

    def co_env_dict(self, **extra):
        return self.env_dict(STEWARD_HARNESS="copilot", COPILOT_HOME=self.config, **extra)

    def start(self, env, session_id="main-1"):
        result = run_hook(
            "session-start",
            {"session_id": session_id, "hook_event_name": "SessionStart", "source": "startup"},
            env,
        )
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)

    def context(self, env, session_id="main-1"):
        return self.start(env, session_id)["additionalContext"]

    def write_settings(self, content):
        path = os.path.join(self.config, "settings.json")
        os.makedirs(self.config, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def _deny_reason(result):
    out = json.loads(result.stdout)
    hso = out["hookSpecificOutput"]
    if hso.get("permissionDecision") != "deny":
        return None
    return hso["permissionDecisionReason"]


class CopilotConfigDirTests(CopilotHarnessCase):
    def test_config_dir_from_copilot_home(self):
        self.assertEqual(hook.get_config_dir(self.co_env_dict()), self.config)

    def test_copilot_home_tilde_expanded(self):
        env = {"HOME": self.home, "STEWARD_HARNESS": "copilot", "COPILOT_HOME": "~/cop"}
        self.assertEqual(hook.get_config_dir(env), os.path.join(self.home, "cop"))

    def test_default_is_home_dot_copilot(self):
        env = {"HOME": self.home, "STEWARD_HARNESS": "copilot", "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir(env), os.path.join(self.home, ".copilot"))

    def test_harness_detection(self):
        self.assertEqual(hook.get_harness({}), "claude")
        self.assertEqual(hook.get_harness({"STEWARD_HARNESS": "Copilot "}), "copilot")


class CopilotSessionStartTests(CopilotHarnessCase):
    def test_flat_additional_context(self):
        out = self.start(self.co_env())
        self.assertNotIn("hookSpecificOutput", out)
        text = out["additionalContext"]
        self.assertTrue(text.startswith("<STEWARD>\n"))
        self.assertTrue(text.endswith("\n</STEWARD>"))
        self.assertIn("Copilot body of the edict.", text)
        self.assertNotIn("Body text of the delegating skill.", text)
        self.assertNotIn("name: delegating", text)

    def test_records_main_session(self):
        self.start(self.co_env(), "main/1")
        marker = os.path.join(self.state, "steward", "copilot-main", hook._sanitize_session_id("main/1"))
        self.assertTrue(os.path.isfile(marker))

    def test_unwritable_state_dir_keeps_injection(self):
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        env = self.co_env(XDG_STATE_HOME=os.path.join(blocker, "sub"))
        self.assertIn("Copilot body of the edict.", self.context(env))

    def test_missing_skill_file_falls_back_and_records_marker(self):
        empty_root = os.path.join(self.tmp, "empty-plugin")
        os.makedirs(empty_root, exist_ok=True)
        out = self.start(self.co_env(STEWARD_PLUGIN_ROOT=empty_root), "main-x")
        self.assertNotIn("hookSpecificOutput", out)
        text = out["additionalContext"]
        self.assertIn("STEWARD WARNING:", text)
        self.assertIn(os.path.join(empty_root, "copilot", "skills", "delegating", "SKILL.md"), text)
        self.assertIn("steward:", text)
        self.assertIn("task tool", text)
        self.assertNotIn(EM_DASH, text)
        marker = os.path.join(self.state, "steward", "copilot-main", hook._sanitize_session_id("main-x"))
        self.assertTrue(os.path.isfile(marker))

    def test_resumed_session_records_marker(self):
        result = run_hook(
            "session-start",
            {"session_id": "resumed-1", "hook_event_name": "SessionStart", "source": "resume"},
            self.co_env(),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Copilot body of the edict.", json.loads(result.stdout)["additionalContext"])
        marker = os.path.join(self.state, "steward", "copilot-main", hook._sanitize_session_id("resumed-1"))
        self.assertTrue(os.path.isfile(marker))

    def test_does_not_create_orchestration_registry(self):
        self.start(self.co_env())
        self.assertFalse(os.path.exists(os.path.join(self.orch, "initiatives.md")))

    def test_warns_when_plainlanguage_missing(self):
        text = self.context(self.co_env())
        self.assertIn("STEWARD WARNING", text)
        self.assertIn(os.path.join(self.config, "skills", "plainlanguage", "SKILL.md"), text)
        self.assertIn(os.path.join(self.home, ".agents", "skills", "plainlanguage", "SKILL.md"), text)

    def test_plainlanguage_in_agents_skills_dir_is_enough(self):
        path = os.path.join(self.home, ".agents", "skills", "plainlanguage", "SKILL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("stub\n")
        self.assertNotIn("STEWARD WARNING", self.context(self.co_env()))

    def test_plainlanguage_in_copilot_skills_dir_is_enough(self):
        self.write_dep("skills/plainlanguage/SKILL.md")
        self.assertNotIn("STEWARD WARNING", self.context(self.co_env()))

    def test_bound_profiles_listed(self):
        self.write_settings(json.dumps({"subagents": {"agents": {
            "steward:coder": {"model": "prov/claude-opus-5-5", "effortLevel": "medium"},
            "other:thing": {"model": "m-other", "effortLevel": "low"},
        }}}))
        text = self.context(self.co_env())
        self.assertIn("Profiles bound in settings.json", text)
        self.assertIn("steward:coder (model prov/claude-opus-5-5, effort medium)", text)
        self.assertNotIn("other:thing", text)
        self.assertNotIn("m-other", text)

    def test_no_bound_line_without_steward_keys(self):
        self.write_settings(json.dumps({"subagents": {"agents": {"x:y": {"model": "m"}}}}))
        self.assertNotIn("Profiles bound", self.context(self.co_env()))

    def test_malformed_settings_ignored(self):
        self.write_settings("{not json")
        text = self.context(self.co_env())
        self.assertIn("Copilot body of the edict.", text)
        self.assertNotIn("Profiles bound", text)


class CopilotGateTests(CopilotHarnessCase):
    def _edit(self, session_id, path="src/a.py"):
        return {
            "session_id": session_id, "tool_name": "Edit", "cwd": "/repo",
            "tool_input": {"path": path, "old_str": "a", "new_str": "b"},
        }

    def _patch(self, session_id, patch):
        return {"session_id": session_id, "tool_name": "Edit", "cwd": "/repo", "tool_input": patch}

    def _assert_second_denied(self, payload, env):
        self.assertEqual(run_hook("gate", payload, env).stdout, "")
        return _deny_reason(run_hook("gate", payload, env))

    def test_main_session_second_edit_denied_with_copilot_message(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m1")
        reason = self._assert_second_denied(self._edit("m1"), env)
        self.assertIsNotNone(reason)
        self.assertIn("task tool", reason)
        self.assertIn("steward:coder for code", reason)
        self.assertIn("steward:mechanic for rote edits", reason)
        self.assertNotIn("coder-opus-medium", reason)
        self.assertIn(os.path.join(self.config, "steward", "gate"), reason)

    def test_create_payload_counted(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m1c")
        payload = {
            "session_id": "m1c", "tool_name": "Write", "cwd": "/repo",
            "tool_input": {"path": "src/new.py", "file_text": "x"},
        }
        self.assertIsNotNone(self._assert_second_denied(payload, env))

    def test_unrecorded_session_never_denied(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "parent")
        for _ in range(3):
            self.assertEqual(run_hook("gate", self._edit("sub-1"), env).stdout, "")

    def test_agents_md_path_exempt_under_copilot_only(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m2")
        payload = self._edit("m2", "AGENTS.md")
        for _ in range(3):
            self.assertEqual(run_hook("gate", payload, env).stdout, "")
        claude_env = self.make_env(STEWARD_GATE="hard")
        claude_payload = dict(payload, session_id="c2")
        self.assertIsNotNone(self._assert_second_denied(claude_payload, claude_env))

    def test_claude_ignores_path_field_when_file_path_present(self):
        claude_env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "c3", "tool_name": "Write",
            "tool_input": {"file_path": "/repo/src/a.py", "path": "/tmp/x", "content": "x"},
        }
        self.assertIsNotNone(self._assert_second_denied(payload, claude_env))

    def test_apply_patch_only_agents_md_exempt(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m3")
        patch = "*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-a\n+b\n*** End Patch\n"
        for _ in range(3):
            self.assertEqual(run_hook("gate", self._patch("m3", patch), env).stdout, "")

    def test_apply_patch_mixed_paths_counted(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m4")
        patch = (
            "*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-a\n+b\n"
            "*** Add File: src/x.py\n+x\n*** End Patch\n"
        )
        self.assertIsNotNone(self._assert_second_denied(self._patch("m4", patch), env))

    def test_apply_patch_move_target_counted(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m4b")
        patch = (
            "*** Begin Patch\n*** Update File: AGENTS.md\n*** Move to: src/y.py\n"
            "*** End Patch\n"
        )
        self.assertIsNotNone(self._assert_second_denied(self._patch("m4b", patch), env))

    def test_apply_patch_without_file_lines_counted(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m5")
        patch = "*** Begin Patch\n*** End Patch\n"
        self.assertIsNotNone(self._assert_second_denied(self._patch("m5", patch), env))

    def test_patch_paths_parsed(self):
        patch = (
            "*** Begin Patch\n*** Add File: b.txt\n+x\n*** Update File: c/d.py\n"
            "*** Delete File: e.md\n*** Move to: f.md\n*** End Patch\n"
        )
        self.assertEqual(hook.apply_patch_paths(patch), ["b.txt", "c/d.py", "e.md", "f.md"])

    def test_delegated_resets_counter(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m6")
        run_hook("gate", self._edit("m6"), env)
        run_hook("delegated", {"session_id": "m6", "tool_name": "Agent", "tool_input": {}}, env)
        self.assertEqual(run_hook("gate", self._edit("m6"), env).stdout, "")

    def test_gate_mode_file_read_from_copilot_home(self):
        self.write_dep("steward/gate", "off\n")
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m7")
        run_hook("gate", self._edit("m7"), env)
        self.assertEqual(run_hook("gate", self._edit("m7"), env).stdout, "")

    def test_pr_gate_in_main_session(self):
        env = self.co_env()
        self.start(env, "m8")
        payload = {
            "session_id": "m8", "tool_name": "Bash",
            "tool_input": {"command": 'gh pr create --title t --body "a' + EM_DASH + 'b"'},
        }
        reason = _deny_reason(run_hook("gate", payload, env))
        self.assertIsNotNone(reason)
        self.assertIn("PR gate", reason)

    def test_soft_mode_second_edit_returns_context(self):
        env = self.co_env(STEWARD_GATE="soft")
        self.start(env, "ms")
        payload = self._edit("ms")
        self.assertEqual(run_hook("gate", payload, env).stdout, "")
        hso = json.loads(run_hook("gate", payload, env).stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)
        self.assertIn("task tool", hso["additionalContext"])
        self.assertIn("steward:coder for code", hso["additionalContext"])

    def test_no_session_id_fails_open(self):
        env = self.co_env(STEWARD_GATE="hard")
        self.start(env, "m-some")
        payload = self._edit("m-some")
        del payload["session_id"]
        for _ in range(3):
            self.assertEqual(run_hook("gate", payload, env).stdout, "")

    def test_relative_edit_in_chat_session_cwd_counted(self):
        # Outside /tmp, which the allowlist exempts as a whole.
        home = "/nonexistent-steward-home/u"
        copilot_home = os.path.join(home, ".copilot")
        env = self.make_env(
            STEWARD_HARNESS="copilot", HOME=home, COPILOT_HOME=copilot_home, STEWARD_GATE="hard")
        self.start(env, "chat-1")
        payload = self._edit("chat-1", "src/app.py")
        payload["cwd"] = os.path.join(copilot_home, "chats", "2026-10-09", "x")
        self.assertIsNotNone(self._assert_second_denied(payload, env))

    def test_copilot_config_dir_narrow_entries(self):
        # Outside /tmp, which the allowlist exempts as a whole.
        config = "/nonexistent-steward-home/u/.copilot"
        co = self.env_dict(STEWARD_HARNESS="copilot", COPILOT_HOME=config)
        for rel in (
            "steward/prose-patterns",
            "session-state/abc/files/plan.md",
            "settings.json",
            "settings.local.json",
            "copilot-instructions.md",
            "agents/a.agent.md",
            "skills/s/SKILL.md",
            "hooks/h.json",
        ):
            path = os.path.join(config, rel)
            self.assertTrue(hook.is_allowlisted(path, co), path)
        for path in (
            os.path.join(config, "chats", "2026-10-09", "x", "src", "app.py"),
            "/repo/.copilot/x.py",
        ):
            self.assertFalse(hook.is_allowlisted(path, co), path)
        for path in ("/tmp/x", os.path.join(self.home, ".claude", "x"), "/repo/CLAUDE.md"):
            self.assertTrue(hook.is_allowlisted(path, co), path)
        claude = self.env_dict(CLAUDE_CONFIG_DIR=config)
        self.assertTrue(hook.is_allowlisted(
            os.path.join(config, "chats", "x", "src", "app.py"), claude))
        pi = self.env_dict(STEWARD_HARNESS="pi", PI_CODING_AGENT_DIR=config)
        self.assertTrue(hook.is_allowlisted(
            os.path.join(config, "chats", "x", "src", "app.py"), pi))

    def test_copilot_allowlist_entries(self):
        co = self.co_env_dict()
        claude = self.env_dict()
        for path in (
            "/repo/AGENTS.md",
            "/repo/.github/copilot-instructions.md",
            "/repo/.github/instructions/x.instructions.md",
            "/repo/.github/agents/a.agent.md",
            "/repo/.github/skills/s/SKILL.md",
            "/repo/.github/copilot/settings.json",
            os.path.join(self.config, "settings.json"),
        ):
            self.assertTrue(hook.is_allowlisted(path, co), path)
        for path in ("/repo/AGENTS.md", "/repo/.github/agents/a.agent.md"):
            self.assertFalse(hook.is_allowlisted(path, claude), path)


class CopilotProseGateTests(CopilotHarnessCase):
    def _transcript(self, events):
        path = os.path.join(self.tmp, "events.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        return path

    STOP_ISO = "2026-10-09T05:47:28.833Z"
    STOP_MS = 1791524848833

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
        return run_hook("prose-gate", payload, env)

    def _gate(self, events, session_id="m1", timestamp=STOP_ISO):
        """In-process gate call with the main-session marker recorded."""
        env = self.co_env_dict()
        hook._record_copilot_main_session(env, session_id)
        payload = {"session_id": session_id, "transcript_path": self._transcript(events)}
        if timestamp is not None:
            payload["timestamp"] = timestamp
        return hook.cmd_prose_gate(payload, env)

    def test_unrecorded_session_passes(self):
        result = self._run(
            [self.user("hi"), self.assistant("Done " + EM_DASH + " ok.")],
            record=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_recorded_session_blocks(self):
        result = self._run([self.user("hi"), self.assistant("Done " + EM_DASH + " ok.")])
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_subagent_stop_with_parent_transcript_passes(self):
        # A subagent's Stop carries its own session id and the parent's
        # transcript path; the parent's prose must not block it.
        result = self._run(
            [self.user("hi"), self.assistant("Done " + EM_DASH + " ok."),
             self.stop_marker(session_id="sub-9")],
            marker=False,
            session_id="sub-9",
        )
        self.assertEqual(result.stdout, "")

    def test_events_after_stop_marker_are_ignored(self):
        out = self._gate([
            self.user("go"),
            self.assistant("Plain reply."),
            self.stop_marker(),
            self.assistant("Later " + EM_DASH + " message."),
        ])
        self.assertIsNone(out)

    def test_stop_marker_with_far_timestamp_is_not_used(self):
        # A marker 5 s away is a different stop, so the gate waits out the
        # limit and parses everything, catching the em-dash after it.
        with mock.patch.object(hook, "_COPILOT_FLUSH_LIMIT_SECONDS", 0.05), \
                mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            out = self._gate([
                self.user("go"),
                self.assistant("Plain reply."),
                self.stop_marker(ms=self.STOP_MS - 5000),
                self.assistant("Later " + EM_DASH + " message."),
            ])
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_stop_marker_without_payload_timestamp(self):
        out = self._gate([
            self.user("go"),
            self.assistant("Plain reply."),
            self.stop_marker(),
            self.assistant("Later " + EM_DASH + " message."),
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
                self.assistant("New " + EM_DASH + " reply."),
            ], timestamp=None)
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_missing_marker_waits_limit_then_parses(self):
        with mock.patch.object(hook, "_COPILOT_FLUSH_LIMIT_SECONDS", 0.05), \
                mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            began = time.monotonic()
            out = self._gate([self.user("go"), self.assistant("Final " + EM_DASH + " reply.")])
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
            self.assistant("Final " + EM_DASH + " reply."), self.stop_marker(),
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
                f.write(json.dumps(self.assistant("Final " + EM_DASH + " reply.")) + "\n")
                f.write(json.dumps(self.stop_marker()) + "\n")

        env = self.co_env_dict()
        hook._record_copilot_main_session(env, "m1")
        thread = threading.Thread(target=writer)
        with mock.patch.object(hook, "_COPILOT_FLUSH_POLL_SECONDS", 0.01):
            thread.start()
            out = hook.cmd_prose_gate(
                {"session_id": "m1", "transcript_path": path, "timestamp": self.STOP_ISO}, env)
            thread.join()
        self.assertEqual(json.loads(out)["decision"], "block")

    @staticmethod
    def user(text):
        return {"type": "user.message", "data": {"content": text}, "id": "u"}

    @staticmethod
    def assistant(text, agent_id=None):
        event = {"type": "assistant.message", "data": {"content": text, "toolRequests": []}, "id": "a"}
        if agent_id:
            event["agentId"] = agent_id
        return event

    def test_em_dash_in_last_main_reply_blocks(self):
        result = self._run([
            self.user("hi"),
            self.assistant(""),
            self.assistant("Done " + EM_DASH + " all good."),
        ])
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("em-dash", out["reason"])

    def test_em_dash_only_in_subagent_event_passes(self):
        result = self._run([
            self.user("hi"),
            self.assistant("sub " + EM_DASH + " text", agent_id="sub-1"),
            self.user("subagent prompt " + EM_DASH) | {"agentId": "sub-1"},
            self.assistant("Plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_em_dash_in_earlier_turn_passes(self):
        result = self._run([
            self.user("first"),
            self.assistant("Old " + EM_DASH + " reply."),
            self.user("second"),
            self.assistant("New plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_em_dash_in_task_complete_summary_blocks(self):
        result = self._run([
            self.user("go"),
            self.assistant("Working."),
            {"type": "session.task_complete", "data": {"summary": "Done " + EM_DASH + " ok", "success": True}},
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

    def test_em_dash_in_mid_turn_message_passes(self):
        result = self._run([
            self.user("go"),
            self.assistant("Looking " + EM_DASH + " now."),
            self.assistant("Final plain reply."),
        ])
        self.assertEqual(result.stdout, "")

    def test_em_dash_in_final_message_blocks(self):
        result = self._run([
            self.user("go"),
            self.assistant("Looking now."),
            self.assistant("Final " + EM_DASH + " reply."),
        ])
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_no_user_message_returns_none(self):
        path = self._transcript([
            self.assistant("Old " + EM_DASH + " reply."),
            {"type": "session.task_complete", "data": {"summary": "x"}},
        ])
        self.assertIsNone(hook._extract_last_copilot_text(path))

    def test_stop_hook_active_passes(self):
        result = self._run([self.user("x"), self.assistant("a " + EM_DASH)], stop_hook_active=True)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_passes(self):
        payload = {"session_id": "m1", "transcript_path": os.path.join(self.tmp, "nope.jsonl")}
        result = run_hook("prose-gate", payload, self.co_env())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


# ---------------------------------------------------------------------------
# plugin files
# ---------------------------------------------------------------------------

def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    fields = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([\w-]+):\s*(.*)$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2)
    return fields, m.group(2)


class CopilotManifestTests(unittest.TestCase):
    def setUp(self):
        with open(COPILOT_MANIFEST, encoding="utf-8") as f:
            self.manifest = json.load(f)

    def test_paths_exist(self):
        self.assertTrue((REPO_ROOT / self.manifest["agents"]).is_dir())
        for rel in self.manifest["skills"]:
            self.assertTrue((REPO_ROOT / rel).is_dir(), rel)
        self.assertTrue((REPO_ROOT / self.manifest["hooks"]).is_file())

    def test_name_and_versions_match(self):
        self.assertEqual(self.manifest["name"], "steward")
        with open(REPO_ROOT / ".claude-plugin" / "plugin.json", encoding="utf-8") as f:
            claude = json.load(f)
        with open(REPO_ROOT / "package.json", encoding="utf-8") as f:
            pkg = json.load(f)
        self.assertEqual(self.manifest["version"], claude["version"])
        self.assertEqual(self.manifest["version"], pkg["version"])

    def test_hook_commands_use_copilot_harness(self):
        with open(COPILOT_DIR / "hooks.json", encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        commands = []
        for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop"):
            self.assertIn(event, hooks)
            for entry in hooks[event]:
                for h in entry["hooks"]:
                    self.assertEqual(h["type"], "command")
                    commands.append(h["command"])
        self.assertTrue(commands)
        for command in commands:
            self.assertIn("STEWARD_HARNESS=copilot", command)
            self.assertIn("hooks/steward_hook.py", command)

    def test_skills_ship_delegating_without_orchestrating(self):
        self.assertTrue((COPILOT_SKILLS / "delegating" / "SKILL.md").is_file())
        self.assertFalse(list(COPILOT_SKILLS.rglob("orchestrating*")))


class CopilotAgentProfileTests(unittest.TestCase):
    def test_role_only_names_cover_every_claude_profile(self):
        self.assertEqual(sorted(COPILOT_NAMES), sorted(p.stem for p in CLAUDE_AGENTS.glob("*.md")))
        self.assertEqual(
            sorted(p.name[: -len(".agent.md")] for p in COPILOT_AGENTS.glob("*.agent.md")),
            sorted(COPILOT_NAMES.values()),
        )
        self.assertEqual(len(list(COPILOT_AGENTS.iterdir())), 7)

    def test_each_profile_mirrors_its_claude_twin(self):
        for claude_path in CLAUDE_AGENTS.glob("*.md"):
            with self.subTest(profile=claude_path.stem):
                c_fields, c_body = _frontmatter(claude_path)
                role = COPILOT_NAMES[claude_path.stem]
                co_fields, co_body = _frontmatter(COPILOT_AGENTS / (role + ".agent.md"))
                self.assertEqual(co_fields["name"], role)
                self.assertEqual(co_fields["description"], _to_copilot_names(c_fields["description"]))
                self.assertEqual(co_fields["reasoning-effort"], c_fields["effort"])
                self.assertEqual(co_fields["include-custom-instructions"], "true")
                self.assertNotIn("model", co_fields)
                self.assertNotIn("skills", co_fields)
                self.assertEqual(co_body, _to_copilot_names(c_body))

    def test_no_old_profile_names_in_copilot_files(self):
        paths = [p for p in COPILOT_DIR.rglob("*") if p.is_file()] + [COPILOT_MANIFEST]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for old in COPILOT_NAMES:
                self.assertNotIn(old, text, "{} in {}".format(old, path))


class CopilotSkillTests(unittest.TestCase):
    def test_skill_names_every_profile_and_has_no_em_dash(self):
        text = (COPILOT_SKILLS / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        for role in COPILOT_NAMES.values():
            self.assertIn("steward:" + role, text)
        self.assertNotIn(EM_DASH, text)
        self.assertNotIn("orchestrat", text.lower())

    def test_skill_maps_each_role_to_model_and_effort(self):
        text = (COPILOT_SKILLS / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        for role, model, effort in (
            ("coder", "Claude Opus 5.5", "medium"),
            ("deep-reasoner", "Claude Opus 5.5", "xhigh"),
            ("reviewer", "Claude Sonnet 5.5", "high"),
            ("researcher", "Claude Sonnet 5.5", "low"),
            ("writer", "Claude Sonnet 5.5", "medium"),
            ("mechanic", "Claude Haiku 5.5", "medium"),
            ("top-reviewer", "Claude Fable 5.1", "xhigh"),
        ):
            self.assertIn("| steward:{} | {} | `{}` |".format(role, model, effort), text)
        self.assertNotIn("family in the profile's name", text)


if __name__ == "__main__":
    unittest.main()
