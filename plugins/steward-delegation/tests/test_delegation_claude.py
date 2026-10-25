"""Tests for `delegation_hook.py claude <mode>`: session-start, gate and
delegated on Claude Code.

These tests never touch the real home directory; see helpers.py.
"""

import json
import multiprocessing
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import PLUGIN_ROOT, SCRIPT, StewardTestCase, load_hook_module, run_hook  # noqa: E402

try:
    import fcntl as _fcntl_probe  # noqa: F401
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

hook = load_hook_module()


# ---------------------------------------------------------------------------
# session-start
# ---------------------------------------------------------------------------

class SessionStartTests(StewardTestCase):
    def test_output_shape_and_frontmatter_stripped(self):
        env = self.make_env()
        result = run_hook("claude", "session-start",
                          {"session_id": "s1", "hook_event_name": "SessionStart"}, env)
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertTrue(text.startswith("<STEWARD>\n"))
        self.assertTrue(text.endswith("\n</STEWARD>"))
        self.assertIn("Body text of the delegating skill.", text)
        # frontmatter must not leak into the injected context
        self.assertNotIn("name: delegating", text)
        self.assertNotIn("---", text)

    def test_header_names_the_namespaced_skill(self):
        env = self.make_env()
        result = run_hook("claude", "session-start", {"session_id": "s1"}, env)
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("steward-delegation:delegating skill", text)

    def test_missing_skill_file_fails_open(self):
        env = self.make_env()
        # point at a plugin root with no skill file at all
        empty_root = os.path.join(self.tmp, "empty-plugin")
        os.makedirs(empty_root, exist_ok=True)
        env["STEWARD_DELEGATION_ROOT"] = empty_root
        result = run_hook("claude", "session-start", {"session_id": "s1"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_default_plugin_root_is_two_directories_up(self):
        # Without the test override the script reads the skill that ships
        # beside it, in this plugin folder.
        env = self.make_env()
        env.pop("STEWARD_DELEGATION_ROOT")
        result = run_hook("claude", "session-start", {"session_id": "s1"}, env)
        self.assertEqual(result.returncode, 0)
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        skill = (PLUGIN_ROOT / "skills" / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        body = hook.strip_frontmatter(skill).strip("\n")
        self.assertIn(body, text)

    def test_never_creates_the_orchestration_registry(self):
        env = self.make_env()
        result = run_hook("claude", "session-start", {"session_id": "s1"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(self.orch))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "orchestration")))

    def test_no_plainlanguage_warning(self):
        # The plainlanguage file probe is gone: no skill in the config dir,
        # and still no warning.
        env = self.make_env()
        result = run_hook("claude", "session-start", {"session_id": "s1"}, env)
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("WARNING", text)
        self.assertNotIn("plainlanguage", text)
        self.assertFalse(os.path.exists(self.config))


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

class GateSubagentAndOffTests(StewardTestCase):
    def test_allows_inside_subagent_via_agent_id(self):
        env = self.make_env()
        payload = {
            "session_id": "s1", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
            "agent_id": "agent-123",
        }
        result = run_hook("claude", "gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_agent_type_alone_does_not_exempt(self):
        # agent_type is set for whole sessions started with --agent; those
        # are main threads the gate must still cover.
        env = self.make_env()
        payload = {
            "session_id": "s-agent-type", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
            "agent_type": "some-persona",
        }
        run_hook("claude", "gate", payload, env)
        second = run_hook("claude", "gate", payload, env)
        out = json.loads(second.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_gate_off(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="off")
        payload = {
            "session_id": "s2", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
        }
        run_hook("claude", "gate", payload, env)
        second = run_hook("claude", "gate", payload, env)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(second.stdout, "")


class GateCounterTests(StewardTestCase):
    def _edit_payload(self, session_id, path="/some/where/file.txt"):
        return {
            "session_id": session_id, "tool_name": "Write",
            "tool_input": {"file_path": path, "content": "x"},
        }

    def test_first_direct_edit_allowed(self):
        env = self.make_env()
        result = run_hook("claude", "gate", self._edit_payload("s3"), env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_second_direct_edit_denied_hard(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("s4"), env)
        result = run_hook("claude", "gate", self._edit_payload("s4"), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("#2", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("steward-delegation:coder-opus-medium", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_soft_mode_returns_context_without_permission_decision(self):
        # An "allow" skips the permission prompt entirely; soft mode is a
        # reminder, not a permission grant, so it must omit the key.
        env = self.make_env(STEWARD_DELEGATION_GATE="soft")
        run_hook("claude", "gate", self._edit_payload("s5"), env)
        result = run_hook("claude", "gate", self._edit_payload("s5"), env)
        out = json.loads(result.stdout)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("#2", out["hookSpecificOutput"]["additionalContext"])

    def test_counter_reset_by_delegated(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("s6"), env)
        run_hook("claude", "delegated", {"session_id": "s6"}, env)
        result = run_hook("claude", "gate", self._edit_payload("s6"), env)
        # after reset, this is edit #1 again: allowed
        self.assertEqual(result.stdout, "")

    def test_ttl_reset(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("s7"), env)
        state_file = os.path.join(self.state, "steward-delegation", "s7.json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        data["last"] = time.time() - 700
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = run_hook("claude", "gate", self._edit_payload("s7"), env)
        # TTL expired: counter reset, so this is edit #1 again
        self.assertEqual(result.stdout, "")

    def test_denied_attempt_still_increments_counter(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("s8"), env)
        run_hook("claude", "gate", self._edit_payload("s8"), env)
        third = run_hook("claude", "gate", self._edit_payload("s8"), env)
        out = json.loads(third.stdout)
        self.assertIn("#3", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_multiedit_classified_like_edit(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "s-multi", "tool_name": "MultiEdit",
            "tool_input": {"file_path": "/some/where/f.txt", "edits": [{"old_string": "a", "new_string": "b"}]},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_multiedit_path_from_first_edit_entry(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "s-multi2", "tool_name": "MultiEdit",
            "tool_input": {"edits": [{"file_path": "/some/where/f.txt", "old_string": "a", "new_string": "b"}]},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_session_id_sanitized_for_filename(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "../evil", "tool_name": "Write",
            "tool_input": {"file_path": "/some/f.txt", "content": "x"},
        }
        run_hook("claude", "gate", payload, env)
        state_dir = os.path.join(self.state, "steward-delegation")
        for name in os.listdir(state_dir):
            self.assertNotIn("/", name)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.json")))


class GateModeFileTests(StewardTestCase):
    def _edit_payload(self, session_id):
        return {
            "session_id": session_id, "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
        }

    def _write_gate_file(self, value):
        path = os.path.join(self.config, "steward-delegation", "gate")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)

    def test_file_overrides_env_var(self):
        self._write_gate_file("off")
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("sf1"), env)
        result = run_hook("claude", "gate", self._edit_payload("sf1"), env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_invalid_file_value_falls_back_to_env(self):
        self._write_gate_file("banana\n")
        env = self.make_env(STEWARD_DELEGATION_GATE="soft")
        run_hook("claude", "gate", self._edit_payload("sf2"), env)
        result = run_hook("claude", "gate", self._edit_payload("sf2"), env)
        out = json.loads(result.stdout)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_invalid_file_and_no_env_defaults_hard(self):
        self._write_gate_file("nonsense")
        env = self.make_env()
        run_hook("claude", "gate", self._edit_payload("sf3"), env)
        result = run_hook("claude", "gate", self._edit_payload("sf3"), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_file_whitespace_trimmed(self):
        self._write_gate_file("  soft  \n")
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        run_hook("claude", "gate", self._edit_payload("sf4"), env)
        result = run_hook("claude", "gate", self._edit_payload("sf4"), env)
        out = json.loads(result.stdout)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("additionalContext", out["hookSpecificOutput"])


class GateAllowlistTests(StewardTestCase):
    def _payload(self, session_id, path):
        return {
            "session_id": session_id, "tool_name": "Write",
            "tool_input": {"file_path": path, "content": "x"},
        }

    def test_config_dir_path_allowlisted(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        path = os.path.join(self.config, "steward-delegation", "notes.md")
        run_hook("claude", "gate", self._payload("sa1", path), env)
        result = run_hook("claude", "gate", self._payload("sa1", path), env)
        self.assertEqual(result.stdout, "")

    def test_tmp_path_allowlisted(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        path = "/tmp/steward-test-fixture/notes.md"
        run_hook("claude", "gate", self._payload("sa2", path), env)
        result = run_hook("claude", "gate", self._payload("sa2", path), env)
        self.assertEqual(result.stdout, "")

    def test_claude_md_allowlisted(self):
        # A fabricated path, not under self.tmp: the gate never checks that
        # a path exists, and self.tmp can itself land under /tmp on some
        # platforms, which would pass this test for the wrong reason.
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        path = "/srv/project/CLAUDE.md"
        run_hook("claude", "gate", self._payload("sa3", path), env)
        result = run_hook("claude", "gate", self._payload("sa3", path), env)
        self.assertEqual(result.stdout, "")

    def test_memory_dir_allowlisted(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        path = "/srv/project/memory/notes.md"
        run_hook("claude", "gate", self._payload("sa4", path), env)
        result = run_hook("claude", "gate", self._payload("sa4", path), env)
        self.assertEqual(result.stdout, "")

    def test_non_allowlisted_path_still_gates(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        path = "/srv/project/src/main.py"
        run_hook("claude", "gate", self._payload("sa5", path), env)
        result = run_hook("claude", "gate", self._payload("sa5", path), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bash_command_with_only_allowlisted_paths_is_exempt(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        cmd_path = os.path.join(self.config, "steward-delegation", "notes.md")
        payload = {
            "session_id": "sa6", "tool_name": "Bash",
            "tool_input": {"command": "echo hi > %s" % cmd_path},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_bash_command_with_mixed_paths_is_not_exempt(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        cmd_path = os.path.join(self.config, "steward-delegation", "notes.md")
        other_path = "/srv/project/real.txt"
        payload = {
            "session_id": "sa7", "tool_name": "Bash",
            "tool_input": {"command": "cat %s > %s" % (cmd_path, other_path)},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class BashClassificationTests(unittest.TestCase):
    """Direct unit tests of the classification table. One positive and one
    negative case per regex family named in the spec, plus the corrected
    dev/null and python-heredoc rules."""

    def assertWrite(self, command):
        self.assertTrue(hook.classify_bash_command(command), command)

    def assertRead(self, command):
        self.assertFalse(hook.classify_bash_command(command), command)

    # redirect family
    def test_redirect_write_positive(self):
        self.assertWrite("echo hi > out.txt")

    def test_redirect_append_positive(self):
        self.assertWrite("echo hi >> out.txt")

    def test_redirect_devnull_negative(self):
        self.assertRead("some-command >/dev/null")

    def test_redirect_devnull_with_space_negative(self):
        self.assertRead("some-command > /dev/null")

    def test_redirect_stderr_devnull_negative(self):
        self.assertRead("some-command 2>/dev/null")

    def test_redirect_fd_dup_negative(self):
        self.assertRead("some-command 2>&1")

    def test_redirect_fd_dup_reverse_negative(self):
        self.assertRead("some-command 1>&2")

    def test_redirect_both_to_devnull_negative(self):
        self.assertRead("some-command &>/dev/null")

    # tee family
    def test_tee_positive(self):
        self.assertWrite("echo hi | tee out.txt")

    def test_tee_negative(self):
        self.assertRead("echo hi | grep h")

    # sed -i family
    def test_sed_inplace_positive(self):
        self.assertWrite("sed -i 's/a/b/' file.txt")

    def test_sed_no_inplace_negative(self):
        self.assertRead("sed 's/a/b/' file.txt")

    # perl -i family
    def test_perl_inplace_positive(self):
        self.assertWrite("perl -i -pe 's/a/b/' file.txt")

    def test_perl_no_inplace_negative(self):
        self.assertRead("perl -e 'print 1'")

    # heredoc + redirect family
    def test_heredoc_with_redirect_positive(self):
        self.assertWrite("cat <<EOF > out.txt\nhello\nEOF")

    def test_heredoc_without_redirect_negative(self):
        self.assertRead("cat <<EOF\nhello\nEOF")

    # git mutating commands
    def test_git_commit_positive(self):
        self.assertWrite("git commit -m 'msg'")

    def test_git_push_positive(self):
        self.assertWrite("git push origin main")

    def test_git_status_negative(self):
        self.assertRead("git status")

    def test_git_diff_negative(self):
        self.assertRead("git diff")

    def test_git_log_negative(self):
        self.assertRead("git log")

    # gh pr mutating commands
    def test_gh_pr_create_positive(self):
        self.assertWrite("gh pr create --title x --body y")

    def test_gh_pr_list_negative(self):
        self.assertRead("gh pr list")

    # filesystem verbs
    def test_rm_at_start_positive(self):
        self.assertWrite("rm -rf foo")

    def test_rm_after_and_positive(self):
        self.assertWrite("ls && rm -rf foo")

    def test_rm_after_semicolon_positive(self):
        self.assertWrite("ls; rm -rf foo")

    def test_rm_after_pipe_positive(self):
        self.assertWrite("true | rm -rf foo")

    def test_ls_negative(self):
        self.assertRead("ls -la")

    def test_installer_word_boundary_negative(self):
        self.assertRead("installer.sh --run")

    # python heredoc write, conditional on body indicators
    def test_python_heredoc_write_positive(self):
        cmd = "python3 - <<EOF\nopen('f.txt', 'w').write('x')\nEOF"
        self.assertWrite(cmd)

    def test_python_heredoc_read_only_negative(self):
        cmd = "python3 - <<EOF\nimport json\nprint(json.load(open('f.txt')))\nEOF"
        self.assertRead(cmd)

    # package installs
    def test_npm_install_positive(self):
        self.assertWrite("npm install left-pad")

    def test_npm_test_negative(self):
        self.assertRead("npm test")

    def test_pip_install_positive(self):
        self.assertWrite("pip3 install requests")

    def test_uv_add_positive(self):
        self.assertWrite("uv add requests")

    def test_uv_run_negative(self):
        self.assertRead("uv run --with pkg python script.py")

    def test_brew_install_positive(self):
        self.assertWrite("brew install wget")

    # general reads named in the spec
    def test_cat_file_negative(self):
        self.assertRead("cat file.txt")

    def test_find_negative(self):
        self.assertRead("find . -name '*.py'")

    def test_python_unittest_negative(self):
        self.assertRead("python3 -m unittest discover -s tests")

    # quote-aware masking: a ">" or "|" inside quotes is not a redirect
    def test_git_log_format_arrow_negative(self):
        self.assertRead("git log --format='%h -> %s'")

    def test_awk_comparison_in_quotes_negative(self):
        self.assertRead("awk '$3 > 100 {print}' f")

    def test_grep_arrow_pattern_negative(self):
        self.assertRead("grep -- '->' file.py")

    def test_jq_comparison_in_quotes_negative(self):
        self.assertRead("jq '.items[] | select(.n>2)' f.json")

    def test_python_c_comparison_in_double_quotes_negative(self):
        self.assertRead('python3 -c "print(1 > 0)"')

    def test_psql_comparison_in_quotes_negative(self):
        self.assertRead("psql -c 'select * from t where a > 1'")

    def test_echo_comparison_in_quotes_negative(self):
        self.assertRead("echo 'a > b'")

    def test_python_heredoc_body_comparison_negative(self):
        cmd = "python3 - <<EOF\nif a > b:\n    pass\nEOF"
        self.assertRead(cmd)

    def test_redirect_still_matches_with_quoted_filename(self):
        self.assertWrite('cat > "my file.txt" <<EOF\nhello\nEOF')

    def test_redirect_write_positive_plain(self):
        self.assertWrite("echo x > out.txt")

    def test_redirect_append_positive_plain(self):
        self.assertWrite("cmd >> log")

    # git-mutate: abort/continue/quit/skip/check/dry-run are not writes
    def test_git_rebase_abort_negative(self):
        self.assertRead("git rebase --abort")

    def test_git_rebase_continue_negative(self):
        self.assertRead("git rebase --continue")

    def test_git_rebase_quit_negative(self):
        self.assertRead("git rebase --quit")

    def test_git_rebase_skip_negative(self):
        self.assertRead("git rebase --skip")

    def test_git_merge_abort_negative(self):
        self.assertRead("git merge --abort")

    def test_git_cherry_pick_abort_negative(self):
        self.assertRead("git cherry-pick --abort")

    def test_git_am_abort_negative(self):
        self.assertRead("git am --abort")

    def test_git_apply_check_negative(self):
        self.assertRead("git apply --check")

    def test_git_push_dry_run_negative(self):
        self.assertRead("git push --dry-run")

    # tee: anchored to command position, device targets excluded
    def test_tee_stderr_device_negative(self):
        self.assertRead("echo x | tee /dev/stderr")

    def test_tee_input_from_devnull_negative(self):
        self.assertRead("tee </dev/null")

    def test_tee_as_argument_to_man_negative(self):
        self.assertRead("man tee")

    def test_tee_mentioned_in_quotes_negative(self):
        self.assertRead("echo 'use tee here'")

    def test_tee_file_positive(self):
        self.assertWrite("echo x | tee out.txt")

    # xargs rm counts as a write
    def test_xargs_rm_positive(self):
        self.assertWrite("find . -name '*.tmp' | xargs rm")

    # a verb after a bare newline (no && ; |) still counts
    def test_verb_after_newline_positive(self):
        self.assertWrite("echo hi\nrm -rf foo")


# ---------------------------------------------------------------------------
# delegated
# ---------------------------------------------------------------------------

class DelegatedTests(StewardTestCase):
    def test_resets_counter_file(self):
        env = self.make_env()
        result = run_hook("claude", "delegated", {"session_id": "d1"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        state_file = os.path.join(self.state, "steward-delegation", "d1.json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["count"], 0)

    def test_ignored_when_agent_id_present(self):
        env = self.make_env()
        # bump the counter first (as a fake main-thread edit history)
        payload = {
            "session_id": "d2", "tool_name": "Write",
            "tool_input": {"file_path": "/some/f.txt", "content": "x"},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "delegated", {"session_id": "d2", "agent_id": "sub-1"}, env)
        self.assertEqual(result.stdout, "")
        # delegated must ignore this call (agent_id set): the counter the
        # gate call above bumped to 1 must be left untouched, not reset.
        state_file = os.path.join(self.state, "steward-delegation", "d2.json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["count"], 1)


# ---------------------------------------------------------------------------
# allowlist: relative path resolution against cwd
# ---------------------------------------------------------------------------

class AllowlistCwdResolutionTests(StewardTestCase):
    def test_relative_claude_md_with_cwd_is_allowlisted(self):
        env = self.env_dict()
        self.assertTrue(hook.is_allowlisted("CLAUDE.md", env, cwd="/some/project"))

    def test_relative_memory_path_with_cwd_is_allowlisted(self):
        env = self.env_dict()
        self.assertTrue(hook.is_allowlisted("memory/note.md", env, cwd="/some/project"))

    def test_unrelated_relative_path_with_cwd_is_not_allowlisted(self):
        env = self.env_dict()
        self.assertFalse(hook.is_allowlisted("src/main.py", env, cwd="/some/project"))

    def test_gate_uses_payload_cwd_for_relative_path(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "cw1", "tool_name": "Write",
            "tool_input": {"file_path": "CLAUDE.md", "content": "x"},
            "cwd": "/some/project",
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        # exempt every time: this always resolves to an allowlisted path
        self.assertEqual(result.stdout, "")


# ---------------------------------------------------------------------------
# session id sanitization
# ---------------------------------------------------------------------------

class SanitizeSessionIdTests(unittest.TestCase):
    def test_strips_slash(self):
        self.assertNotIn("/", hook._sanitize_session_id("a/b"))

    def test_strips_traversal_slash(self):
        cleaned = hook._sanitize_session_id("../evil")
        self.assertNotIn("/", cleaned)

    def test_keeps_ordinary_id_unchanged(self):
        self.assertEqual(hook._sanitize_session_id("abc-123_ok.1"), "abc-123_ok.1")


# ---------------------------------------------------------------------------
# counter atomicity across processes
# ---------------------------------------------------------------------------

def _mp_bump_counter_worker(state_dir, session_id, script_path):
    """Runs in a separate process: loads the hook module fresh and bumps
    the counter once. Module-level so it can be pickled by multiprocessing."""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("delegation_hook_mp_worker", script_path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._bump_counter(state_dir, session_id)


class CounterAtomicityTests(StewardTestCase):
    @unittest.skipUnless(_HAS_FCNTL, "flock-based locking is POSIX-only")
    def test_concurrent_bump_counter_from_two_processes(self):
        state_dir = os.path.join(self.state, "steward-delegation")
        os.makedirs(state_dir, exist_ok=True)
        session_id = "concurrent-session"
        p1 = multiprocessing.Process(
            target=_mp_bump_counter_worker, args=(state_dir, session_id, str(SCRIPT))
        )
        p2 = multiprocessing.Process(
            target=_mp_bump_counter_worker, args=(state_dir, session_id, str(SCRIPT))
        )
        p1.start()
        p2.start()
        p1.join(timeout=15)
        p2.join(timeout=15)
        self.assertFalse(p1.is_alive())
        self.assertFalse(p2.is_alive())
        state_file = os.path.join(state_dir, session_id + ".json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["count"], 2)


# ---------------------------------------------------------------------------
# what the split changes
# ---------------------------------------------------------------------------

class PrBodyIsNotThisPluginsJobTests(StewardTestCase):
    """The PR gate lives in steward-prose-gate. Here a `gh pr create` is only
    a direct edit, whatever its body says."""

    def test_pr_body_with_two_markers_counts_only_as_a_direct_edit(self):
        env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        body = "This is crucial and we leverage the tapestry of ideas"
        payload = {
            "session_id": "p3", "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title x --body '%s'" % body},
        }
        first = run_hook("claude", "gate", payload, env)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout, "")
        # it counted as a direct edit: a second one is denied by the
        # delegation gate, not by a PR-body check
        second = run_hook("claude", "gate", payload, env)
        out = json.loads(second.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(reason.startswith("steward delegation gate"))
        self.assertIn("#2", reason)


class GateMessageTests(StewardTestCase):
    def test_message_names_new_profiles_path_and_env(self):
        msg = hook.gate_message(2, self.config)
        self.assertTrue(msg.startswith("steward delegation gate"))
        self.assertIn("#2", msg)
        self.assertIn("steward-delegation:coder-opus-medium", msg)
        self.assertIn("steward-delegation:mechanic-haiku-medium", msg)
        self.assertIn(os.path.join(self.config, "steward-delegation", "gate"), msg)
        self.assertIn("STEWARD_DELEGATION_GATE", msg)
        self.assertNotIn("steward:", msg)

    def test_denied_reason_carries_the_message(self):
        env = self.make_env()
        payload = {
            "session_id": "gm1", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertEqual(reason, hook.gate_message(2, self.config))

    def test_old_gate_file_and_env_are_ignored(self):
        old_file = os.path.join(self.config, "steward", "gate")
        os.makedirs(os.path.dirname(old_file), exist_ok=True)
        with open(old_file, "w", encoding="utf-8") as f:
            f.write("off")
        env = self.make_env(STEWARD_GATE="off")
        payload = {
            "session_id": "gm2", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
        }
        run_hook("claude", "gate", payload, env)
        result = run_hook("claude", "gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class ExtraAllowlistFileTests(StewardTestCase):
    def _write(self, relative, lines):
        path = os.path.join(self.config, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_globs_from_the_plugin_allowlist_file_exempt(self):
        self._write("steward-delegation/allowlist", ["/srv/notes/**", ""])
        env = self.env_dict()
        self.assertTrue(hook.is_allowlisted("/srv/notes/a.md", env))
        self.assertFalse(hook.is_allowlisted("/srv/code/a.py", env))

    def test_old_allowlist_file_is_ignored(self):
        self._write("steward/allowlist", ["/srv/notes/**"])
        self.assertFalse(hook.is_allowlisted("/srv/notes/a.md", self.env_dict()))


class UnknownHarnessAndModeTests(StewardTestCase):
    EDIT = {
        "session_id": "u1", "tool_name": "Write",
        "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
    }

    def _assert_silent(self, result):
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_unknown_harness_exits_0_with_no_output(self):
        env = self.make_env()
        for mode in ("session-start", "gate", "delegated"):
            self._assert_silent(run_hook("emacs", mode, self.EDIT, env))
            self._assert_silent(run_hook("emacs", mode, self.EDIT, env))
        self.assertFalse(os.path.exists(self.state))

    def test_unknown_mode_exits_0_with_no_output(self):
        env = self.make_env()
        self._assert_silent(run_hook("claude", "prose-gate", self.EDIT, env))
        self._assert_silent(run_hook("claude", "pr-gate", self.EDIT, env))
        self._assert_silent(run_hook("claude", "bogus", self.EDIT, env))

    def test_missing_arguments_exit_0_with_no_output(self):
        env = self.make_env()
        for argv in ([], ["claude"]):
            result = subprocess.run(
                [sys.executable, str(SCRIPT)] + argv, input=json.dumps(self.EDIT),
                capture_output=True, text=True, env=env)
            self._assert_silent(result)

    def test_bad_stdin_exits_0(self):
        env = self.make_env()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "claude", "gate"], input="not json",
            capture_output=True, text=True, env=env)
        self._assert_silent(result)


if __name__ == "__main__":
    unittest.main()
