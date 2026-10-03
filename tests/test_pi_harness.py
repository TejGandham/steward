"""Tests for the pi side of steward.

Two groups:
- the hook script in pi mode (STEWARD_HARNESS=pi), run the same way the pi
  extension runs it;
- the pi package files themselves: the manifest, the pi agent profiles (which
  must stay in step with the Claude Code ones) and the pi edict skill.
"""

import json
import os
import re
import unittest

from test_steward_hook import EM_DASH, REPO_ROOT, StewardTestCase, hook, run_hook


PI_SKILL = REPO_ROOT / "pi" / "skills" / "steward-delegating" / "SKILL.md"
PI_AGENTS = REPO_ROOT / "pi" / "agents"
CLAUDE_AGENTS = REPO_ROOT / "agents"


class PiHarnessCase(StewardTestCase):
    """Runs the hook as the pi extension does: STEWARD_HARNESS=pi and pi's
    config dir in PI_CODING_AGENT_DIR."""

    def setUp(self):
        super().setUp()
        skill_dir = os.path.join(self.plugin_root, "pi", "skills", "steward-delegating")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                "name: steward-delegating\n"
                "description: test fixture skill\n"
                "---\n"
                "Pi body of the edict.\n"
            )

    def pi_env(self, **extra):
        return self.make_env(STEWARD_HARNESS="pi", PI_CODING_AGENT_DIR=self.config, **extra)

    def pi_env_dict(self, **extra):
        return self.env_dict(STEWARD_HARNESS="pi", PI_CODING_AGENT_DIR=self.config, **extra)

    def context(self, env):
        result = run_hook("session-start", {"session_id": "pi-s1"}, env)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


class PiConfigDirTests(PiHarnessCase):
    def test_pi_agent_dir_from_env(self):
        self.assertEqual(hook.get_config_dir(self.pi_env_dict()), self.config)

    def test_pi_default_is_home_pi_agent(self):
        env = {"HOME": self.home, "STEWARD_HARNESS": "pi"}
        self.assertEqual(hook.get_config_dir(env), os.path.join(self.home, ".pi", "agent"))

    def test_claude_config_dir_ignored_under_pi(self):
        env = {"HOME": self.home, "STEWARD_HARNESS": "pi", "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir(env), os.path.join(self.home, ".pi", "agent"))

    def test_harness_defaults_to_claude(self):
        self.assertEqual(hook.get_harness({}), "claude")
        self.assertEqual(hook.get_harness({"STEWARD_HARNESS": "PI "}), "pi")


class PiSessionStartTests(PiHarnessCase):
    def test_uses_pi_skill_without_wrapper_tags(self):
        text = self.context(self.pi_env())
        self.assertIn("Pi body of the edict.", text)
        self.assertIn("steward-delegating", text)
        self.assertNotIn("Body text of the delegating skill.", text)
        self.assertNotIn("<STEWARD>", text)
        self.assertNotIn("name: steward-delegating", text)

    def test_does_not_create_orchestration_registry(self):
        self.context(self.pi_env())
        self.assertFalse(os.path.exists(os.path.join(self.orch, "initiatives.md")))

    def test_warns_about_missing_deps_at_pi_paths(self):
        text = self.context(self.pi_env())
        self.assertIn(os.path.join(self.config, "skills", "plainlanguage", "SKILL.md"), text)
        self.assertIn(os.path.join(self.home, ".agents", "skills", "plainlanguage", "SKILL.md"), text)

    def test_update_pr_summary_is_optional(self):
        self.write_dep("skills/plainlanguage/SKILL.md")
        text = self.context(self.pi_env())
        self.assertNotIn("STEWARD WARNING", text)
        self.assertNotIn("update-pr-summary", text)

    def test_plainlanguage_in_agents_skills_dir_is_enough(self):
        path = os.path.join(self.home, ".agents", "skills", "plainlanguage", "SKILL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("stub\n")
        text = self.context(self.pi_env())
        self.assertNotIn("STEWARD WARNING", text)

    def test_plainlanguage_in_pi_skills_dir_is_enough(self):
        self.write_dep("skills/plainlanguage/SKILL.md")
        self.assertNotIn("STEWARD WARNING", self.context(self.pi_env()))


class PiGateTests(PiHarnessCase):
    def _write(self, session_id, path="/some/where/file.txt"):
        return {
            "session_id": session_id, "tool_name": "write",
            "tool_input": {"path": path, "content": "x"}, "cwd": "/some/where",
        }

    def test_second_lowercase_write_denied_with_pi_profile_names(self):
        env = self.pi_env(STEWARD_GATE="hard")
        self.assertEqual(run_hook("gate", self._write("pg1"), env).stdout, "")
        out = json.loads(run_hook("gate", self._write("pg1"), env).stdout)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("steward.coder-opus-medium", reason)
        self.assertIn("subagent tool", reason)
        self.assertIn(os.path.join(self.config, "steward", "gate"), reason)
        self.assertNotIn("steward:", reason)

    def test_edit_tool_path_field_is_read(self):
        env = self.pi_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "pg2", "tool_name": "edit",
            "tool_input": {"path": "/tmp/scratch.txt", "edits": []},
        }
        run_hook("gate", payload, env)
        # /tmp is allowlisted, so the edit is exempt every time
        self.assertEqual(run_hook("gate", payload, env).stdout, "")

    def test_extra_file_path_argument_does_not_exempt_a_pi_write(self):
        # pi writes to "path"; a stray "file_path" naming /tmp must not win.
        env = self.pi_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "pg8", "tool_name": "write",
            "tool_input": {"path": "/some/where/main.ts", "file_path": "/tmp/x", "content": "x"},
        }
        run_hook("gate", payload, env)
        out = json.loads(run_hook("gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_lowercase_bash_classified(self):
        env = self.pi_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "pg3", "tool_name": "bash",
            "tool_input": {"command": "echo hi > /some/where/out.txt"},
        }
        run_hook("gate", payload, env)
        out = json.loads(run_hook("gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_lowercase_bash_read_only_passes(self):
        env = self.pi_env(STEWARD_GATE="hard")
        payload = {"session_id": "pg4", "tool_name": "bash", "tool_input": {"command": "ls -la"}}
        run_hook("gate", payload, env)
        self.assertEqual(run_hook("gate", payload, env).stdout, "")

    def test_pr_gate_on_lowercase_bash(self):
        env = self.pi_env()
        payload = {
            "session_id": "pg5", "tool_name": "bash",
            "tool_input": {"command": 'gh pr create --title t --body "a ' + EM_DASH + ' b"'},
        }
        out = json.loads(run_hook("gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("PR gate", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertNotIn("update-pr-summary", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_gate_mode_file_read_from_pi_config_dir(self):
        self.write_dep("steward/gate", "off\n")
        env = self.pi_env(STEWARD_GATE="hard")
        run_hook("gate", self._write("pg6"), env)
        self.assertEqual(run_hook("gate", self._write("pg6"), env).stdout, "")

    def test_agents_md_and_dot_pi_allowlisted_only_under_pi(self):
        pi_env = self.pi_env_dict()
        claude_env = self.env_dict()
        for path in ("/repo/AGENTS.md", "/repo/.pi/settings.json"):
            self.assertTrue(hook.is_allowlisted(path, pi_env), path)
            self.assertFalse(hook.is_allowlisted(path, claude_env), path)

    def test_pi_config_dir_allowlisted(self):
        path = os.path.join(self.config, "settings.json")
        self.assertTrue(hook.is_allowlisted(path, self.pi_env_dict()))

    def test_claude_names_still_work_under_pi(self):
        env = self.pi_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "pg7", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/f.txt", "content": "x"},
        }
        run_hook("gate", payload, env)
        out = json.loads(run_hook("gate", payload, env).stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class ClaudeHarnessUnchangedTests(StewardTestCase):
    def test_claude_gate_message_keeps_colon_names(self):
        env = self.make_env(STEWARD_GATE="hard")
        payload = {
            "session_id": "c1", "tool_name": "Write",
            "tool_input": {"file_path": "/some/where/f.txt", "content": "x"},
        }
        run_hook("gate", payload, env)
        out = json.loads(run_hook("gate", payload, env).stdout)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("steward:coder-opus-medium", reason)
        self.assertNotIn("steward.coder-opus-medium", reason)


# ---------------------------------------------------------------------------
# package files
# ---------------------------------------------------------------------------

def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    fields = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2)
    return fields, m.group(2)


class PiPackageManifestTests(unittest.TestCase):
    def setUp(self):
        with open(REPO_ROOT / "package.json", encoding="utf-8") as f:
            self.pkg = json.load(f)

    def test_manifest_paths_exist(self):
        pi = self.pkg["pi"]
        for rel in pi["extensions"] + pi["skills"] + pi["subagents"]["agents"]:
            self.assertTrue((REPO_ROOT / rel).exists(), rel)

    def test_pi_package_keyword(self):
        self.assertIn("pi-package", self.pkg["keywords"])

    def test_orchestrating_skill_not_shipped_to_pi(self):
        for rel in self.pkg["pi"]["skills"]:
            root = REPO_ROOT / rel
            self.assertFalse(list(root.rglob("orchestrating*")), rel)
            for skill in root.rglob("SKILL.md"):
                self.assertNotIn("orchestrat", skill.read_text(encoding="utf-8").lower(), skill)

    def test_version_matches_claude_plugin(self):
        with open(REPO_ROOT / ".claude-plugin" / "plugin.json", encoding="utf-8") as f:
            plugin = json.load(f)
        self.assertEqual(self.pkg["version"], plugin["version"])


class PiAgentProfileTests(unittest.TestCase):
    MODEL_MAP = {
        "opus": "anthropic/claude-opus-5-5",
        "sonnet": "anthropic/claude-sonnet-5",
        "fable": "anthropic/claude-fable-5-1",
    }

    def test_same_profiles_as_claude(self):
        self.assertEqual(
            sorted(p.name for p in PI_AGENTS.glob("*.md")),
            sorted(p.name for p in CLAUDE_AGENTS.glob("*.md")),
        )

    def test_each_profile_mirrors_its_claude_twin(self):
        for claude_path in CLAUDE_AGENTS.glob("*.md"):
            with self.subTest(profile=claude_path.stem):
                c_fields, c_body = _frontmatter(claude_path)
                p_fields, p_body = _frontmatter(PI_AGENTS / claude_path.name)
                self.assertEqual(p_fields["name"], c_fields["name"])
                self.assertEqual(p_fields["package"], "steward")
                self.assertEqual(p_fields["model"], self.MODEL_MAP[c_fields["model"]])
                self.assertEqual(p_fields["thinking"], c_fields["effort"])
                self.assertEqual(p_body, c_body)
                self.assertNotIn("steward:", p_fields["description"])

    def test_writer_loads_plainlanguage(self):
        fields, _ = _frontmatter(PI_AGENTS / "writer-sonnet-medium.md")
        self.assertEqual(fields["skills"], "plainlanguage")

    def test_children_see_operator_context(self):
        for path in PI_AGENTS.glob("*.md"):
            fields, _ = _frontmatter(path)
            for key in ("inheritProjectContext", "inheritGlobalContext", "inheritSkills"):
                self.assertEqual(fields[key], "true", f"{path.name} {key}")


class PiSkillTests(unittest.TestCase):
    def test_skill_names_every_pi_profile(self):
        text = PI_SKILL.read_text(encoding="utf-8")
        for path in PI_AGENTS.glob("*.md"):
            self.assertIn("steward." + path.stem, text)
        self.assertNotIn("steward:", text)
        self.assertNotIn(EM_DASH, text)

    def test_skill_frontmatter_name(self):
        fields, _ = _frontmatter(PI_SKILL)
        self.assertEqual(fields["name"], "steward-delegating")


if __name__ == "__main__":
    unittest.main()
