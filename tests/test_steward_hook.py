"""Tests for the steward hook script.

These tests never touch the real home directory. Every test gets its
own temp dirs for HOME, XDG_STATE_HOME, CLAUDE_CONFIG_DIR and
STEWARD_ORCHESTRATION_DIR, and its own temp plugin root so the fixture
skill file does not depend on the real steward checkout.
"""

import importlib.util
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import fcntl as _fcntl_probe
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "hooks" / "steward_hook.py"

# Import the script as a plain module so unit tests can call its
# helper functions directly, without paying for a subprocess per case.
_spec = importlib.util.spec_from_file_location("steward_hook", str(SCRIPT))
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)

# Built from a code point, not typed literally, so this file's own bytes
# never contain the character the tests are checking for.
EM_DASH = chr(0x2014)


def run_hook(subcommand, payload, env):
    """Run the script in a subprocess with the given stdin payload and env."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


class StewardTestCase(unittest.TestCase):
    """Base case: gives every test a throwaway HOME, state dir, config dir,
    orchestration dir and plugin root."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-test-")
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state")
        self.config = os.path.join(self.tmp, "config")
        self.orch = os.path.join(self.tmp, "orch")
        os.makedirs(self.home, exist_ok=True)
        self.plugin_root = self._make_plugin_root()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_plugin_root(self, skill_body=None):
        root = os.path.join(self.tmp, "plugin")
        skill_dir = os.path.join(root, "skills", "delegating")
        os.makedirs(skill_dir, exist_ok=True)
        if skill_body is None:
            skill_body = (
                "---\n"
                "name: delegating\n"
                "description: test fixture skill\n"
                "---\n"
                "Body text of the delegating skill.\n"
                "Second line of the body.\n"
            )
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_body)
        return root

    def make_env(self, **extra):
        env = os.environ.copy()
        for key in ("STEWARD_GATE", "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR",
                    "STEWARD_ORCHESTRATION_DIR", "STEWARD_PLUGIN_ROOT", "HOME"):
            env.pop(key, None)
        env["HOME"] = self.home
        env["XDG_STATE_HOME"] = self.state
        env["CLAUDE_CONFIG_DIR"] = self.config
        env["STEWARD_ORCHESTRATION_DIR"] = self.orch
        env["STEWARD_PLUGIN_ROOT"] = self.plugin_root
        env.update(extra)
        return env

    def env_dict(self, **extra):
        """A plain dict, for calling module functions directly (no subprocess)."""
        d = {
            "HOME": self.home,
            "XDG_STATE_HOME": self.state,
            "CLAUDE_CONFIG_DIR": self.config,
            "STEWARD_ORCHESTRATION_DIR": self.orch,
            "STEWARD_PLUGIN_ROOT": self.plugin_root,
        }
        d.update(extra)
        return d

    def write_dep(self, relative_path, content="stub\n"):
        path = os.path.join(self.config, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


# ---------------------------------------------------------------------------
# session-start
# ---------------------------------------------------------------------------

class SessionStartTests(StewardTestCase):
    def test_output_shape_and_frontmatter_stripped(self):
        env = self.make_env()
        result = run_hook("session-start", {"session_id": "s1", "hook_event_name": "SessionStart"}, env)
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("<STEWARD>", text)
        self.assertIn("</STEWARD>", text)
        self.assertIn("Body text of the delegating skill.", text)
        # frontmatter must not leak into the injected context
        self.assertNotIn("name: delegating", text)
        self.assertNotIn("---", text)

    def test_warning_when_plainlanguage_missing(self):
        env = self.make_env()
        self.write_dep("commands/update-pr-summary.md")
        result = run_hook("session-start", {"session_id": "s1"}, env)
        out = json.loads(result.stdout)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("STEWARD WARNING", text)
        self.assertIn("plainlanguage", text)
        expected_path = os.path.join(self.config, "skills", "plainlanguage", "SKILL.md")
        self.assertIn(expected_path, text)

    def test_warning_when_update_pr_summary_missing(self):
        env = self.make_env()
        self.write_dep("skills/plainlanguage/SKILL.md")
        result = run_hook("session-start", {"session_id": "s1"}, env)
        out = json.loads(result.stdout)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("STEWARD WARNING", text)
        self.assertIn("update-pr-summary", text)
        self.assertIn("PR body", text)
        expected_path = os.path.join(self.config, "commands", "update-pr-summary.md")
        self.assertIn(expected_path, text)

    def test_no_warning_when_deps_present(self):
        env = self.make_env()
        self.write_dep("skills/plainlanguage/SKILL.md")
        self.write_dep("commands/update-pr-summary.md")
        result = run_hook("session-start", {"session_id": "s1"}, env)
        out = json.loads(result.stdout)
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("STEWARD WARNING", text)

    def test_registry_created_once(self):
        env = self.make_env()
        run_hook("session-start", {"session_id": "s1"}, env)
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
        env = self.make_env()
        run_hook("session-start", {"session_id": "s1"}, env)
        with open(registry, encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "custom content that must survive\n")

    def test_missing_skill_file_fails_open(self):
        env = self.make_env()
        # point at a plugin root with no skill file at all
        empty_root = os.path.join(self.tmp, "empty-plugin")
        os.makedirs(empty_root, exist_ok=True)
        env["STEWARD_PLUGIN_ROOT"] = empty_root
        result = run_hook("session-start", {"session_id": "s1"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_unwritable_orchestration_dir_still_emits_context(self):
        env = self.make_env()
        blocked_parent = os.path.join(self.tmp, "blocked")
        os.makedirs(blocked_parent, exist_ok=True)
        os.chmod(blocked_parent, 0o500)
        env["STEWARD_ORCHESTRATION_DIR"] = os.path.join(blocked_parent, "orch")
        try:
            result = run_hook("session-start", {"session_id": "s1"}, env)
            self.assertEqual(result.returncode, 0)
            out = json.loads(result.stdout)
            self.assertIn("<STEWARD>", out["hookSpecificOutput"]["additionalContext"])
        finally:
            os.chmod(blocked_parent, 0o700)


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
        result = run_hook("gate", payload, env)
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
        run_hook("gate", payload, env)
        second = run_hook("gate", payload, env)
        out = json.loads(second.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_gate_off(self):
        env = self.make_env(STEWARD_GATE="off")
        payload = {
            "session_id": "s2", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/file.txt", "content": "x"},
        }
        run_hook("gate", payload, env)
        second = run_hook("gate", payload, env)
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
        result = run_hook("gate", self._edit_payload("s3"), env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_second_direct_edit_denied_hard(self):
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("s4"), env)
        result = run_hook("gate", self._edit_payload("s4"), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("#2", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("steward:coder-opus-medium", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_soft_mode_returns_context_without_permission_decision(self):
        # An "allow" skips the permission prompt entirely; soft mode is a
        # reminder, not a permission grant, so it must omit the key.
        env = self.make_env(STEWARD_GATE="soft")
        run_hook("gate", self._edit_payload("s5"), env)
        result = run_hook("gate", self._edit_payload("s5"), env)
        out = json.loads(result.stdout)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("#2", out["hookSpecificOutput"]["additionalContext"])

    def test_counter_reset_by_delegated(self):
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("s6"), env)
        run_hook("delegated", {"session_id": "s6"}, env)
        result = run_hook("gate", self._edit_payload("s6"), env)
        # after reset, this is edit #1 again: allowed
        self.assertEqual(result.stdout, "")

    def test_ttl_reset(self):
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("s7"), env)
        state_file = os.path.join(self.state, "steward", "s7.json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        data["last"] = time.time() - 700
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = run_hook("gate", self._edit_payload("s7"), env)
        # TTL expired: counter reset, so this is edit #1 again
        self.assertEqual(result.stdout, "")

    def test_denied_attempt_still_increments_counter(self):
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("s8"), env)
        run_hook("gate", self._edit_payload("s8"), env)
        third = run_hook("gate", self._edit_payload("s8"), env)
        out = json.loads(third.stdout)
        self.assertIn("#3", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_multiedit_classified_like_edit(self):
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "s-multi", "tool_name": "MultiEdit",
            "tool_input": {"file_path": "/some/where/f.txt", "edits": [{"old_string": "a", "new_string": "b"}]},
        }
        run_hook("gate", payload, env)
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_multiedit_path_from_first_edit_entry(self):
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "s-multi2", "tool_name": "MultiEdit",
            "tool_input": {"edits": [{"file_path": "/some/where/f.txt", "old_string": "a", "new_string": "b"}]},
        }
        run_hook("gate", payload, env)
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_session_id_sanitized_for_filename(self):
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "../evil", "tool_name": "Write",
            "tool_input": {"file_path": "/some/f.txt", "content": "x"},
        }
        run_hook("gate", payload, env)
        state_dir = os.path.join(self.state, "steward")
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
        path = os.path.join(self.config, "steward", "gate")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)

    def test_file_overrides_env_var(self):
        self._write_gate_file("off")
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("sf1"), env)
        result = run_hook("gate", self._edit_payload("sf1"), env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_invalid_file_value_falls_back_to_env(self):
        self._write_gate_file("banana\n")
        env = self.make_env(STEWARD_GATE="soft")
        run_hook("gate", self._edit_payload("sf2"), env)
        result = run_hook("gate", self._edit_payload("sf2"), env)
        out = json.loads(result.stdout)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_invalid_file_and_no_env_defaults_hard(self):
        self._write_gate_file("nonsense")
        env = self.make_env()
        run_hook("gate", self._edit_payload("sf3"), env)
        result = run_hook("gate", self._edit_payload("sf3"), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_file_whitespace_trimmed(self):
        self._write_gate_file("  soft  \n")
        env = self.make_env(STEWARD_GATE="hard")
        run_hook("gate", self._edit_payload("sf4"), env)
        result = run_hook("gate", self._edit_payload("sf4"), env)
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
        env = self.make_env(STEWARD_GATE="hard")
        path = os.path.join(self.config, "steward", "notes.md")
        run_hook("gate", self._payload("sa1", path), env)
        result = run_hook("gate", self._payload("sa1", path), env)
        self.assertEqual(result.stdout, "")

    def test_tmp_path_allowlisted(self):
        env = self.make_env(STEWARD_GATE="hard")
        path = "/tmp/steward-test-fixture/notes.md"
        run_hook("gate", self._payload("sa2", path), env)
        result = run_hook("gate", self._payload("sa2", path), env)
        self.assertEqual(result.stdout, "")

    def test_claude_md_allowlisted(self):
        # A fabricated path, not under self.tmp: the gate never checks that
        # a path exists, and self.tmp can itself land under /tmp on some
        # platforms, which would pass this test for the wrong reason.
        env = self.make_env(STEWARD_GATE="hard")
        path = "/srv/project/CLAUDE.md"
        run_hook("gate", self._payload("sa3", path), env)
        result = run_hook("gate", self._payload("sa3", path), env)
        self.assertEqual(result.stdout, "")

    def test_memory_dir_allowlisted(self):
        env = self.make_env(STEWARD_GATE="hard")
        path = "/srv/project/memory/notes.md"
        run_hook("gate", self._payload("sa4", path), env)
        result = run_hook("gate", self._payload("sa4", path), env)
        self.assertEqual(result.stdout, "")

    def test_non_allowlisted_path_still_gates(self):
        env = self.make_env(STEWARD_GATE="hard")
        path = "/srv/project/src/main.py"
        run_hook("gate", self._payload("sa5", path), env)
        result = run_hook("gate", self._payload("sa5", path), env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bash_command_with_only_allowlisted_paths_is_exempt(self):
        env = self.make_env(STEWARD_GATE="hard")
        cmd_path = os.path.join(self.config, "steward", "notes.md")
        payload = {
            "session_id": "sa6", "tool_name": "Bash",
            "tool_input": {"command": "echo hi > %s" % cmd_path},
        }
        run_hook("gate", payload, env)
        result = run_hook("gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_bash_command_with_mixed_paths_is_not_exempt(self):
        env = self.make_env(STEWARD_GATE="hard")
        cmd_path = os.path.join(self.config, "steward", "notes.md")
        other_path = "/srv/project/real.txt"
        payload = {
            "session_id": "sa7", "tool_name": "Bash",
            "tool_input": {"command": "cat %s > %s" % (cmd_path, other_path)},
        }
        run_hook("gate", payload, env)
        result = run_hook("gate", payload, env)
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


class PrGateTests(StewardTestCase):
    def test_em_dash_denied(self):
        env = self.make_env()
        payload = {
            "session_id": "p1", "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title x --body 'a " + EM_DASH + " b'"},
        }
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("em-dash", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_marker_denied(self):
        env = self.make_env()
        body = "This is crucial and we leverage the tapestry of ideas"
        payload = {
            "session_id": "p2", "tool_name": "Bash",
            "tool_input": {"command": "gh pr edit 1 --body \"%s\"" % body},
        }
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("crucial", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_clean_pr_body_passes_through_to_normal_gate(self):
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "p3", "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title x --body 'plain text body'"},
        }
        result = run_hook("gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        # it counted as a direct edit: a second one denies
        second = run_hook("gate", payload, env)
        out = json.loads(second.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_em_dash_denied_even_in_soft_mode(self):
        env = self.make_env(STEWARD_GATE="soft")
        payload = {
            "session_id": "p4", "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title x --body 'a " + EM_DASH + " b'"},
        }
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_body_file_em_dash_denied(self):
        env = self.make_env()
        body_path = os.path.join(self.tmp, "body.md")
        with open(body_path, "w", encoding="utf-8") as f:
            f.write("plain text " + EM_DASH + " with a dash")
        payload = {
            "session_id": "p5", "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title x --body-file %s" % body_path},
        }
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("em-dash", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_body_file_relative_resolves_against_cwd(self):
        env = self.make_env()
        with open(os.path.join(self.tmp, "body2.md"), "w", encoding="utf-8") as f:
            f.write("plain text " + EM_DASH + " with a dash")
        payload = {
            "session_id": "p6", "tool_name": "Bash",
            "tool_input": {"command": "gh pr edit 1 -F body2.md"},
            "cwd": self.tmp,
        }
        result = run_hook("gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


# ---------------------------------------------------------------------------
# delegated
# ---------------------------------------------------------------------------

class DelegatedTests(StewardTestCase):
    def test_resets_counter_file(self):
        env = self.make_env()
        result = run_hook("delegated", {"session_id": "d1"}, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        state_file = os.path.join(self.state, "steward", "d1.json")
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
        run_hook("gate", payload, env)
        result = run_hook("delegated", {"session_id": "d2", "agent_id": "sub-1"}, env)
        self.assertEqual(result.stdout, "")
        # delegated must ignore this call (agent_id set): the counter the
        # gate call above bumped to 1 must be left untouched, not reset.
        state_file = os.path.join(self.state, "steward", "d2.json")
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["count"], 1)


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

    def test_stop_hook_active_short_circuits(self):
        env = self.make_env()
        payload = self._payload(stop_hook_active=True, last_assistant_message="bad " + EM_DASH + " text")
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_agent_id_short_circuits(self):
        env = self.make_env()
        payload = self._payload(agent_id="sub-1", last_assistant_message="bad " + EM_DASH + " text")
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_agent_type_alone_does_not_short_circuit(self):
        env = self.make_env()
        payload = self._payload(agent_type="some-persona", last_assistant_message="bad " + EM_DASH + " text")
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")

    def test_em_dash_in_last_assistant_message_blocks_without_transcript(self):
        env = self.make_env()
        payload = self._payload(last_assistant_message="the result " + EM_DASH + " as expected")
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("em-dash", out["reason"])

    def test_em_dash_via_transcript_blocks(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "the plan " + EM_DASH + " revised"}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")

    def test_marker_block(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "This is crucial. Let me know if this helps."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("crucial", out["reason"])

    def test_code_block_stripping_avoids_false_positive(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Here:\n```\na " + EM_DASH + " b\n```\nAll clear."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_inline_code_stripping_avoids_false_positive(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Use `a " + EM_DASH + " b` as the literal marker."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_clean_message_passes(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "The change is done and tests pass."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_missing_transcript_passes(self):
        env = self.make_env()
        payload = self._payload(transcript_path=os.path.join(self.tmp, "does-not-exist.jsonl"))
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_json_line_skipped(self):
        path = os.path.join(self.tmp, "transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json\n")
            f.write(json.dumps({"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "All good here."}
            ]}}) + "\n")
        env = self.make_env()
        payload = self._payload(transcript_path=path)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_multiblock_same_message_id_joined(self):
        # Claude Code can write one JSONL line per content block; blocks
        # sharing message.id belong to the same reply and must be joined.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "thinking", "thinking": "..."}]}},
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "text", "text": "part one, "}]}},
            {"type": "assistant", "message": {"id": "m9", "content": [{"type": "text", "text": "part two " + EM_DASH + " end"}]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")

    def test_stale_earlier_message_not_mixed_in(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "old " + EM_DASH + " text"}]}},
            {"type": "user", "message": {"role": "user", "content": "tool result"}},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "clean new reply"}]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_path_like_token_marker_excluded(self):
        # "landscape" is a marker, but here it is part of a file path, not
        # prose, so it must not count toward the threshold.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "See /src/landscape/x.py for details, it is fine."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_repeated_same_marker_alone_does_not_block(self):
        # Two hits of the same marker are still only one distinct marker.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "We leverage this and leverage that too."}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_unterminated_fence_with_em_dash_passes(self):
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "text", "text": "Here:\n```\ncode with " + EM_DASH + " inside, never closed"}
            ]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript)
        result = run_hook("prose-gate", payload, env)
        self.assertEqual(result.stdout, "")

    def test_last_assistant_message_field_preferred_over_transcript(self):
        # transcript alone would be clean; last_assistant_message carries the
        # real final text per the docs and should be used first.
        transcript = self._write_transcript([
            {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "clean"}]}},
        ])
        env = self.make_env()
        payload = self._payload(transcript_path=transcript, last_assistant_message="bad " + EM_DASH + " text")
        result = run_hook("prose-gate", payload, env)
        out = json.loads(result.stdout)
        self.assertEqual(out["decision"], "block")


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


# ---------------------------------------------------------------------------
# hooks.json shape
# ---------------------------------------------------------------------------

class HooksJsonTests(unittest.TestCase):
    def _load(self):
        with open(REPO_ROOT / "hooks" / "hooks.json", encoding="utf-8") as f:
            return json.load(f)

    def test_matchers_are_anchored(self):
        data = self._load()
        self.assertEqual(
            data["hooks"]["SessionStart"][0]["matcher"],
            "startup|resume|clear|compact|fork",
        )
        pre = data["hooks"]["PreToolUse"]
        self.assertEqual(pre[0]["matcher"], "^(Edit|Write|MultiEdit|NotebookEdit|Bash)$")
        self.assertEqual(pre[1]["matcher"], "^(Task|Agent)$")
        self.assertIn("delegated", pre[1]["hooks"][0]["command"])
        post = data["hooks"]["PostToolUse"]
        self.assertEqual(post[0]["matcher"], "^(Task|Agent)$")
        self.assertIn("delegated", post[0]["hooks"][0]["command"])


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
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "cw1", "tool_name": "Write",
            "tool_input": {"file_path": "CLAUDE.md", "content": "x"},
            "cwd": "/some/project",
        }
        run_hook("gate", payload, env)
        result = run_hook("gate", payload, env)
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
    spec = _ilu.spec_from_file_location("steward_hook_mp_worker", script_path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._bump_counter(state_dir, session_id)


class CounterAtomicityTests(StewardTestCase):
    @unittest.skipUnless(_HAS_FCNTL, "flock-based locking is POSIX-only")
    def test_concurrent_bump_counter_from_two_processes(self):
        state_dir = os.path.join(self.state, "steward")
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


if __name__ == "__main__":
    unittest.main()
