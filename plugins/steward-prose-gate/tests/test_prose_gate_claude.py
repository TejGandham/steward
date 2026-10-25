"""Tests for prose_gate_hook.py on Claude Code: `prose_gate_hook.py claude
pr-gate|prose-gate`."""

import json
import os
import subprocess
import sys
import unittest

from helpers import AI_TELLS, SCRIPT, StewardTestCase, load_hook_module, run_hook

hook = load_hook_module()

# Built from a code point, not typed literally, so this file's own bytes
# never contain the character the tests are checking for.
EM_DASH = chr(0x2014)

# The 30 AI-tell markers the gate shipped with before the word list moved
# into data/ai-tells.txt, in their original order.
MARKERS = [
    "delve", "delves", "delving",
    "leverage", "leverages", "leveraging",
    "crucial", "pivotal", "tapestry", "landscape", "vibrant",
    "showcase", "showcases", "intricate", "testament",
    "underscore", "underscores", "underscoring",
    "it's important to note", "it is important to note",
    "it's worth noting", "in summary", "in conclusion",
    "great question", "i hope this helps",
    "stands as", "serves as", "plays a vital role",
    "certainly!", "let me know if",
]

# Two distinct markers: enough to block on its own.
TWO_MARKERS = "This is crucial and pivotal."


def pr_payload(command, **extra):
    payload = {"session_id": "p1", "tool_name": "Bash", "tool_input": {"command": command}}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# pr-gate
# ---------------------------------------------------------------------------

class PrGateTests(StewardTestCase):
    def pr(self, payload, **extra):
        return run_hook("claude", "pr-gate", payload, self.make_env(**extra))

    def test_marker_denied(self):
        body = "This is crucial and we leverage the tapestry of ideas"
        result = self.pr(pr_payload("gh pr edit 1 --body \"%s\"" % body))
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("crucial", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_clean_pr_body_passes(self):
        result = self.pr(pr_payload("gh pr create --title x --body 'plain text body'"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_em_dash_alone_does_not_block_pr_body(self):
        result = self.pr(pr_payload("gh pr create --title x --body 'a " + EM_DASH + " b'"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_body_file_marker_denied(self):
        body_path = os.path.join(self.tmp, "body.md")
        with open(body_path, "w", encoding="utf-8") as f:
            f.write(TWO_MARKERS)
        result = self.pr(pr_payload("gh pr create --title x --body-file %s" % body_path))
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("pivotal", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_body_file_em_dash_alone_passes(self):
        body_path = os.path.join(self.tmp, "body.md")
        with open(body_path, "w", encoding="utf-8") as f:
            f.write("plain text " + EM_DASH + " with a dash")
        result = self.pr(pr_payload("gh pr create --title x --body-file %s" % body_path))
        self.assertEqual(result.stdout, "")

    def test_body_file_relative_resolves_against_cwd(self):
        with open(os.path.join(self.tmp, "body2.md"), "w", encoding="utf-8") as f:
            f.write(TWO_MARKERS)
        result = self.pr(pr_payload("gh pr edit 1 -F body2.md", cwd=self.tmp))
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_non_pr_command_passes(self):
        result = self.pr(pr_payload("echo " + TWO_MARKERS))
        self.assertEqual(result.stdout, "")

    def test_subagent_call_not_gated(self):
        payload = pr_payload("gh pr create --body '%s'" % TWO_MARKERS, agent_id="sub-1")
        self.assertEqual(self.pr(payload).stdout, "")

    def test_non_bash_tool_not_gated(self):
        payload = pr_payload("gh pr create --body '%s'" % TWO_MARKERS)
        payload["tool_name"] = "Write"
        self.assertEqual(self.pr(payload).stdout, "")


# ---------------------------------------------------------------------------
# prose-gate
# ---------------------------------------------------------------------------

class ProseGateTests(StewardTestCase):
    def _payload(self, **kwargs):
        base = {"session_id": "pg1"}
        base.update(kwargs)
        return base

    def _write_transcript(self, lines):
        path = os.path.join(self.tmp, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
        return path

    def _run(self, payload, **extra):
        return run_hook("claude", "prose-gate", payload, self.make_env(**extra))

    def test_stop_hook_active_short_circuits(self):
        result = self._run(self._payload(stop_hook_active=True, last_assistant_message=TWO_MARKERS))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_agent_id_short_circuits(self):
        result = self._run(self._payload(agent_id="sub-1", last_assistant_message=TWO_MARKERS))
        self.assertEqual(result.stdout, "")

    def test_agent_type_alone_does_not_short_circuit(self):
        result = self._run(self._payload(agent_type="some-persona", last_assistant_message=TWO_MARKERS))
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")

    def test_markers_in_last_assistant_message_block_without_transcript(self):
        result = self._run(self._payload(last_assistant_message=TWO_MARKERS))
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("crucial", out["reason"])

    def test_em_dash_alone_does_not_block_reply(self):
        result = self._run(self._payload(last_assistant_message="the result " + EM_DASH + " as expected"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_markers_via_transcript_block(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "the plan is " + TWO_MARKERS}
            ]}},
        ])
        out = json.loads(self._run(self._payload(transcript_path=transcript)).stdout)
        self.assertEqual(out["decision"], "block")

    def test_marker_block(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "This is crucial. Let me know if this helps."}
            ]}},
        ])
        out = json.loads(self._run(self._payload(transcript_path=transcript)).stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("crucial", out["reason"])

    def test_code_block_stripping_avoids_false_positive(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Here:\n```\n" + TWO_MARKERS + "\n```\nAll clear."}
            ]}},
        ])
        result = self._run(self._payload(transcript_path=transcript))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_inline_code_stripping_avoids_false_positive(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Use `" + TWO_MARKERS + "` as the literal marker."}
            ]}},
        ])
        self.assertEqual(self._run(self._payload(transcript_path=transcript)).stdout, "")

    def test_clean_message_passes(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "The change is done and tests pass."}
            ]}},
        ])
        result = self._run(self._payload(transcript_path=transcript))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_passes(self):
        result = self._run(self._payload(transcript_path=os.path.join(self.tmp, "does-not-exist.jsonl")))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_json_line_skipped(self):
        path = os.path.join(self.tmp, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json\n")
            f.write(json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "All good here."}
            ]}}) + "\n")
        result = self._run(self._payload(transcript_path=path))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_multiblock_same_message_id_joined(self):
        # Claude Code can write one JSONL line per content block; blocks
        # sharing message.id belong to the same reply and must be joined.
        # Each block carries one marker, so only the joined text blocks.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "thinking", "thinking": "..."}]}},
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "text", "text": "part one is crucial, "}]}},
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "text", "text": "part two is pivotal"}]}},
        ])
        out = json.loads(self._run(self._payload(transcript_path=transcript)).stdout)
        self.assertEqual(out["decision"], "block")

    def test_stale_earlier_message_not_mixed_in(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "old " + TWO_MARKERS}]}},
            {"type": "user", "message": {"role": "user", "content": "tool result"}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "clean new reply"}]}},
        ])
        self.assertEqual(self._run(self._payload(transcript_path=transcript)).stdout, "")

    def test_path_like_token_marker_excluded(self):
        # "landscape" is a marker, but here it is part of a file path, not
        # prose, so it must not count toward the threshold.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "See /src/landscape/x.py for details, it is crucial."}
            ]}},
        ])
        self.assertEqual(self._run(self._payload(transcript_path=transcript)).stdout, "")

    def test_repeated_same_marker_alone_does_not_block(self):
        # Two hits of the same marker are still only one distinct marker.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "We leverage this and leverage that too."}
            ]}},
        ])
        self.assertEqual(self._run(self._payload(transcript_path=transcript)).stdout, "")

    def test_unterminated_fence_with_markers_passes(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Here:\n```\ncode that is " + TWO_MARKERS + " never closed"}
            ]}},
        ])
        self.assertEqual(self._run(self._payload(transcript_path=transcript)).stdout, "")

    def test_last_assistant_message_field_preferred_over_transcript(self):
        # transcript alone would be clean; last_assistant_message carries the
        # real final text per the docs and should be used first.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "clean"}]}},
        ])
        payload = self._payload(transcript_path=transcript, last_assistant_message=TWO_MARKERS)
        out = json.loads(self._run(payload).stdout)
        self.assertEqual(out["decision"], "block")


# ---------------------------------------------------------------------------
# markers and the word list
# ---------------------------------------------------------------------------

class MarkerRegexTests(unittest.TestCase):
    def test_certainly_with_punctuation_matches(self):
        hits, names = hook.find_markers("Certainly! Here is the answer.")
        self.assertIn("certainly!", names)

    def test_word_boundary_avoids_substring_false_positive(self):
        # "underscore" must not match inside "underscored_variable_name":
        # the trailing \b requires a non-word character right after the
        # marker, and here it is followed by "d", another word character.
        hits, names = hook.find_markers("The underscored_variable_name is fine")
        self.assertEqual(hits, 0)


class WordListTests(StewardTestCase):
    def test_shipped_file_parses_to_the_30_markers_in_order(self):
        markers = hook.load_markers(str(AI_TELLS))
        self.assertEqual(len(markers), 30)
        self.assertEqual(markers, MARKERS)

    def test_loaded_patterns_come_from_the_shipped_file(self):
        self.assertEqual([name for name, _ in hook._MARKER_PATTERNS], MARKERS)

    def test_comments_blanks_and_whitespace(self):
        path = os.path.join(self.tmp, "tells.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# a comment\n\n  delve  \n   # indented comment\nserves as\n")
        self.assertEqual(hook.load_markers(path), ["delve", "serves as"])

    def test_missing_file_means_no_markers(self):
        self.assertEqual(hook.load_markers(os.path.join(self.tmp, "absent.txt")), [])


# ---------------------------------------------------------------------------
# operator patterns
# ---------------------------------------------------------------------------

class OperatorPatternTests(StewardTestCase):
    PATTERNS = (
        "# the operator's own bans\n"
        "\n"
        "load[- ]?bearing\n"
        "\\blandmines?\\b\n"
        "^\\s*(let me|now i'?ll)\\b\n"
        "[unclosed\n"
    )

    def setUp(self):
        super().setUp()
        self.write_dep("steward-prose-gate/prose-patterns", self.PATTERNS)

    def prose(self, text, **extra):
        result = run_hook("claude", "prose-gate", {"last_assistant_message": text}, self.make_env(**extra))
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_missing_file_means_no_patterns(self):
        os.remove(os.path.join(self.config, "steward-prose-gate", "prose-patterns"))
        self.assertIsNone(self.prose("This is a load-bearing wall."))

    def test_old_location_is_not_read(self):
        os.remove(os.path.join(self.config, "steward-prose-gate", "prose-patterns"))
        self.write_dep("steward/prose-patterns", self.PATTERNS)
        self.assertIsNone(self.prose("This is a load-bearing wall."))

    def test_comments_blanks_and_bad_regex_skipped(self):
        patterns = hook.load_operator_patterns(self.config)
        self.assertEqual(len(patterns), 3)

    def test_single_operator_phrase_blocks(self):
        out = self.prose("This is a load-bearing wall.")
        self.assertEqual(out["decision"], "block")
        self.assertIn("phrases the operator bans: load-bearing", out["reason"])
        self.assertNotIn("AI tells", out["reason"])

    def test_line_anchored_pattern(self):
        self.assertEqual(self.prose("Done.\nLet me check the logs.")["decision"], "block")
        self.assertIsNone(self.prose("Tell me if you want more and I will let me know."))

    def test_code_is_not_prose(self):
        self.assertIsNone(self.prose("The rule bans `load-bearing`.\n```\nlandmine = 1\n```"))

    def test_reason_never_lists_an_empty_kind(self):
        os.remove(os.path.join(self.config, "steward-prose-gate", "prose-patterns"))
        out = self.prose(TWO_MARKERS)
        self.assertIn("these AI tells: crucial, pivotal", out["reason"])
        self.assertNotIn("operator bans", out["reason"])

    def test_reason_lists_everything_found(self):
        out = self.prose("A landmine " + EM_DASH + " crucial and pivotal.")
        self.assertIn("phrases the operator bans: landmine", out["reason"])
        self.assertIn("crucial", out["reason"])
        self.assertNotIn(EM_DASH, out["reason"])

    def test_revision_is_not_blocked_again(self):
        result = run_hook(
            "claude", "prose-gate",
            {"last_assistant_message": "Still load-bearing.", "stop_hook_active": True},
            self.make_env(),
        )
        self.assertEqual(result.stdout, "")

    def test_pr_gate_uses_operator_patterns(self):
        payload = pr_payload('gh pr create --title t --body "Removes a landmine."')
        out = json.loads(run_hook("claude", "pr-gate", payload, self.make_env()).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("landmine", out["hookSpecificOutput"]["permissionDecisionReason"])


# ---------------------------------------------------------------------------
# the on/off switch
# ---------------------------------------------------------------------------

class SwitchTests(StewardTestCase):
    def both(self, **extra):
        env = self.make_env(**extra)
        prose = run_hook("claude", "prose-gate", {"last_assistant_message": TWO_MARKERS}, env)
        pr = run_hook("claude", "pr-gate", pr_payload("gh pr create --body '%s'" % TWO_MARKERS), env)
        return prose.stdout, pr.stdout

    def write_switch(self, value):
        self.write_dep("steward-prose-gate/gate", value)

    def test_default_is_on(self):
        prose, pr = self.both()
        self.assertEqual(json.loads(prose)["decision"], "block")
        self.assertEqual(json.loads(pr)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_file_off_turns_both_gates_off(self):
        self.write_switch("off\n")
        self.assertEqual(self.both(), ("", ""))

    def test_env_off_turns_both_gates_off(self):
        self.assertEqual(self.both(STEWARD_PROSE_GATE="off"), ("", ""))

    def test_file_wins_over_env(self):
        self.write_switch(" ON \n")
        prose, pr = self.both(STEWARD_PROSE_GATE="off")
        self.assertEqual(json.loads(prose)["decision"], "block")
        self.assertEqual(json.loads(pr)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_file_read_on_every_call(self):
        self.write_switch("off")
        self.assertEqual(self.both(), ("", ""))
        self.write_switch("on")
        prose, _pr = self.both()
        self.assertEqual(json.loads(prose)["decision"], "block")

    def test_old_steward_switch_is_ignored(self):
        self.write_dep("steward/gate", "off")
        prose, _pr = self.both(STEWARD_GATE="off")
        self.assertEqual(json.loads(prose)["decision"], "block")

    def test_unknown_values_fall_back_to_default(self):
        self.write_switch("soft")
        prose, _pr = self.both(STEWARD_PROSE_GATE="maybe")
        self.assertEqual(json.loads(prose)["decision"], "block")

    def test_claude_config_dir_default_is_home_dot_claude(self):
        env = self.env_dict()
        del env["CLAUDE_CONFIG_DIR"]
        self.assertEqual(hook.get_config_dir("claude", env), os.path.join(self.home, ".claude"))


# ---------------------------------------------------------------------------
# dispatch: harness and mode
# ---------------------------------------------------------------------------

class DispatchTests(StewardTestCase):
    def test_unknown_harness_exits_0_with_no_output(self):
        for harness in ("nope", "", "CLAUDE"):
            result = run_hook(harness, "prose-gate", {"last_assistant_message": TWO_MARKERS}, self.make_env())
            self.assertEqual(result.returncode, 0, harness)
            self.assertEqual(result.stdout, "", harness)
            self.assertEqual(result.stderr, "", harness)

    def test_unknown_mode_exits_0_with_no_output(self):
        for mode in ("gate", "session-start", "bogus"):
            result = run_hook("claude", mode, {"last_assistant_message": TWO_MARKERS}, self.make_env())
            self.assertEqual(result.returncode, 0, mode)
            self.assertEqual(result.stdout, "", mode)
            self.assertEqual(result.stderr, "", mode)

    def test_no_arguments_exits_0_with_no_output(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], input="{}",
                                capture_output=True, text=True, env=self.make_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_bad_stdin_fails_open(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "claude", "prose-gate"], input="not json",
                                capture_output=True, text=True, env=self.make_env())
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_state_dir_is_named_after_the_plugin(self):
        self.assertEqual(hook.get_state_dir(self.env_dict()), os.path.join(self.state, "steward-prose-gate"))
        env = self.env_dict()
        del env["XDG_STATE_HOME"]
        self.assertEqual(hook.get_state_dir(env),
                         os.path.join(self.home, ".local", "state", "steward-prose-gate"))


if __name__ == "__main__":
    unittest.main()
