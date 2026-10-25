"""Tests for `delegation_hook.py copilot <mode>` and the Copilot files in
this plugin: session-start (main-session record, fallback edict, bound
profile note), gate and delegated for a recorded main session, the agent
profiles (which must stay in step with the Claude Code ones under the
role-only names in COPILOT_NAMES), the edict skill and copilot/hooks.json.

These tests never touch the real home directory; see helpers.py.
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import PLUGIN_ROOT, StewardTestCase, load_hook_module, load_hooks_json, run_hook  # noqa: E402

hook = load_hook_module()

COPILOT_DIR = PLUGIN_ROOT / "copilot"
COPILOT_AGENTS = COPILOT_DIR / "agents"
COPILOT_SKILLS = COPILOT_DIR / "skills"
# The 0.14.2 key prefix, which the bound-profile note no longer reads.
OLD_CODER_KEY = "steward:" + "coder"
CLAUDE_AGENTS = PLUGIN_ROOT / "agents"

# Claude Code profile name -> Copilot role-only profile name.
COPILOT_NAMES = {
    "coder-opus-medium": "coder",
    "deep-reasoner-opus-xhigh": "deep-reasoner",
    "reviewer-sonnet-high": "reviewer",
    "researcher-sonnet-low": "researcher",
    "writer-sonnet-medium": "writer",
    "mechanic-haiku-medium": "mechanic",
    "reviewer-opus-max": "top-reviewer",
}


def _to_copilot_names(text):
    for old in sorted(COPILOT_NAMES, key=len, reverse=True):
        text = text.replace(old, COPILOT_NAMES[old])
    return text


class CopilotHarnessCase(StewardTestCase):
    """Runs the hook as Copilot does: `delegation_hook.py copilot <mode>`
    with the Copilot config dir in COPILOT_HOME."""

    def setUp(self):
        super().setUp()
        self.write_plugin_file(
            "copilot/skills/delegating/SKILL.md",
            "---\n"
            "name: delegating\n"
            "description: test fixture skill\n"
            "---\n"
            "Copilot body of the edict.\n",
        )

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
        return json.loads(result.stdout)

    def context(self, env, session_id="main-1"):
        return self.start(env, session_id)["additionalContext"]

    def write_settings(self, content):
        self.write_dep("settings.json", content)

    def marker(self, session_id):
        return os.path.join(
            self.state, "steward-delegation", "copilot-main", hook._sanitize_session_id(session_id))


def _deny_reason(result):
    out = json.loads(result.stdout)
    hso = out["hookSpecificOutput"]
    if hso.get("permissionDecision") != "deny":
        return None
    return hso["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# config dir
# ---------------------------------------------------------------------------

class CopilotConfigDirTests(CopilotHarnessCase):
    def test_config_dir_from_copilot_home(self):
        self.assertEqual(hook.get_config_dir(self.co_env_dict(), "copilot"), self.config)

    def test_copilot_home_tilde_expanded(self):
        env = {"HOME": self.home, "COPILOT_HOME": "~/cop"}
        self.assertEqual(hook.get_config_dir(env, "copilot"), os.path.join(self.home, "cop"))

    def test_default_is_home_dot_copilot(self):
        env = {"HOME": self.home, "CLAUDE_CONFIG_DIR": "/elsewhere"}
        self.assertEqual(hook.get_config_dir(env, "copilot"), os.path.join(self.home, ".copilot"))

    def test_claude_config_dir_is_unchanged(self):
        env = {"HOME": self.home, "COPILOT_HOME": "/elsewhere", "CLAUDE_CONFIG_DIR": self.config}
        self.assertEqual(hook.get_config_dir(env), self.config)


# ---------------------------------------------------------------------------
# session-start
# ---------------------------------------------------------------------------

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

    def test_no_plainlanguage_warning(self):
        text = self.context(self.co_env())
        self.assertNotIn("WARNING", text)
        self.assertNotIn("plainlanguage", text)

    def test_records_main_session(self):
        self.start(self.co_env(), "main/1")
        self.assertTrue(os.path.isfile(self.marker("main/1")))

    def test_old_state_dir_is_not_used(self):
        self.start(self.co_env(), "main-old")
        self.assertFalse(os.path.exists(os.path.join(self.state, "steward", "copilot-main")))

    def test_unwritable_state_dir_keeps_injection(self):
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        env = self.co_env(XDG_STATE_HOME=os.path.join(blocker, "sub"))
        self.assertIn("Copilot body of the edict.", self.context(env))

    def test_missing_skill_file_falls_back_and_records_marker(self):
        empty_root = os.path.join(self.tmp, "empty-plugin")
        os.makedirs(empty_root, exist_ok=True)
        out = self.start(self.co_env(STEWARD_DELEGATION_ROOT=empty_root), "main-x")
        self.assertNotIn("hookSpecificOutput", out)
        text = out["additionalContext"]
        self.assertIn("STEWARD WARNING:", text)
        self.assertIn(os.path.join(empty_root, "copilot", "skills", "delegating", "SKILL.md"), text)
        self.assertIn("agent_type steward-delegation:<profile>", text)
        self.assertNotIn("steward:", text)
        self.assertIn("task tool", text)
        self.assertNotIn("dash", text)
        self.assertTrue(os.path.isfile(self.marker("main-x")))

    def test_resumed_session_records_marker(self):
        result = run_hook(
            "copilot", "session-start",
            {"session_id": "resumed-1", "hook_event_name": "SessionStart", "source": "resume"},
            self.co_env(),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Copilot body of the edict.", json.loads(result.stdout)["additionalContext"])
        self.assertTrue(os.path.isfile(self.marker("resumed-1")))

    def test_does_not_create_orchestration_registry(self):
        self.start(self.co_env())
        self.assertFalse(os.path.exists(self.orch))

    def test_default_plugin_root_reads_the_shipped_copilot_skill(self):
        env = self.co_env()
        env.pop("STEWARD_DELEGATION_ROOT")
        text = self.context(env)
        skill = (COPILOT_SKILLS / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(hook.strip_frontmatter(skill).strip("\n"), text)

    def test_bound_profiles_listed(self):
        self.write_settings(json.dumps({"subagents": {"agents": {
            "steward-delegation:coder": {"model": "prov/claude-opus-5-5", "effortLevel": "medium"},
            "other:thing": {"model": "m-other", "effortLevel": "low"},
        }}}))
        text = self.context(self.co_env())
        self.assertIn("Profiles bound in settings.json", text)
        self.assertIn("steward-delegation:coder (model prov/claude-opus-5-5, effort medium)", text)
        self.assertNotIn("other:thing", text)
        self.assertNotIn("m-other", text)

    def test_old_steward_key_not_listed(self):
        self.write_settings(json.dumps({"subagents": {"agents": {
            OLD_CODER_KEY: {"model": "m-old", "effortLevel": "medium"},
            "steward-delegation:mechanic": {"model": "m-new", "effortLevel": "low"},
        }}}))
        text = self.context(self.co_env())
        self.assertIn("steward-delegation:mechanic (model m-new, effort low)", text)
        self.assertNotIn(OLD_CODER_KEY, text)
        self.assertNotIn("m-old", text)

    def test_no_bound_line_with_only_old_steward_keys(self):
        self.write_settings(json.dumps({"subagents": {"agents": {
            OLD_CODER_KEY: {"model": "m-old", "effortLevel": "medium"},
        }}}))
        self.assertNotIn("Profiles bound", self.context(self.co_env()))

    def test_no_bound_line_without_steward_keys(self):
        self.write_settings(json.dumps({"subagents": {"agents": {"x:y": {"model": "m"}}}}))
        self.assertNotIn("Profiles bound", self.context(self.co_env()))

    def test_malformed_settings_ignored(self):
        self.write_settings("{not json")
        text = self.context(self.co_env())
        self.assertIn("Copilot body of the edict.", text)
        self.assertNotIn("Profiles bound", text)


# ---------------------------------------------------------------------------
# gate and delegated
# ---------------------------------------------------------------------------

class CopilotGateTests(CopilotHarnessCase):
    def _edit(self, session_id, path="src/a.py"):
        return {
            "session_id": session_id, "tool_name": "Edit", "cwd": "/repo",
            "tool_input": {"path": path, "old_str": "a", "new_str": "b"},
        }

    def _patch(self, session_id, patch):
        return {"session_id": session_id, "tool_name": "Edit", "cwd": "/repo", "tool_input": patch}

    def _gate(self, payload, env):
        return run_hook("copilot", "gate", payload, env)

    def _assert_second_denied(self, payload, env):
        self.assertEqual(self._gate(payload, env).stdout, "")
        return _deny_reason(self._gate(payload, env))

    def test_main_session_second_edit_denied_with_copilot_message(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m1")
        reason = self._assert_second_denied(self._edit("m1"), env)
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("steward delegation gate"))
        self.assertIn("task tool", reason)
        self.assertIn("steward-delegation:coder for code", reason)
        self.assertIn("steward-delegation:mechanic for rote edits", reason)
        self.assertNotIn("coder-opus-medium", reason)
        self.assertNotIn("steward:", reason)
        self.assertIn(os.path.join(self.config, "steward-delegation", "gate"), reason)
        self.assertIn("STEWARD_DELEGATION_GATE", reason)

    def test_create_payload_counted(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m1c")
        payload = {
            "session_id": "m1c", "tool_name": "Write", "cwd": "/repo",
            "tool_input": {"path": "src/new.py", "file_text": "x"},
        }
        self.assertIsNotNone(self._assert_second_denied(payload, env))

    def test_bash_write_counted(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "mb")
        payload = {
            "session_id": "mb", "tool_name": "Bash", "cwd": "/repo",
            "tool_input": {"command": "python3 build.py > /repo/out.txt"},
        }
        self.assertIsNotNone(self._assert_second_denied(payload, env))

    def test_unrecorded_session_never_denied(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "parent")
        for _ in range(3):
            self.assertEqual(self._gate(self._edit("sub-1"), env).stdout, "")
        self.assertFalse(os.path.exists(
            os.path.join(self.state, "steward-delegation", "sub-1.json")))

    def test_no_session_start_never_denied(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        for _ in range(3):
            self.assertEqual(self._gate(self._edit("never-started"), env).stdout, "")

    def test_agents_md_path_exempt_under_copilot_only(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m2")
        payload = self._edit("m2", "AGENTS.md")
        for _ in range(3):
            self.assertEqual(self._gate(payload, env).stdout, "")
        claude_env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        claude_payload = dict(payload, session_id="c2", tool_input={"file_path": "/repo/AGENTS.md"})
        self.assertEqual(run_hook("claude", "gate", claude_payload, claude_env).stdout, "")
        self.assertIsNotNone(_deny_reason(run_hook("claude", "gate", claude_payload, claude_env)))

    def test_claude_ignores_path_field_when_file_path_present(self):
        claude_env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {
            "session_id": "c3", "tool_name": "Write",
            "tool_input": {"file_path": "/repo/src/a.py", "path": "/tmp/x", "content": "x"},
        }
        self.assertEqual(run_hook("claude", "gate", payload, claude_env).stdout, "")
        self.assertIsNotNone(_deny_reason(run_hook("claude", "gate", payload, claude_env)))

    def test_apply_patch_only_agents_md_exempt(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m3")
        patch = "*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-a\n+b\n*** End Patch\n"
        for _ in range(3):
            self.assertEqual(self._gate(self._patch("m3", patch), env).stdout, "")

    def test_apply_patch_mixed_paths_counted(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m4")
        patch = (
            "*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-a\n+b\n"
            "*** Add File: src/x.py\n+x\n*** End Patch\n"
        )
        self.assertIsNotNone(self._assert_second_denied(self._patch("m4", patch), env))

    def test_apply_patch_move_target_counted(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m4b")
        patch = (
            "*** Begin Patch\n*** Update File: AGENTS.md\n*** Move to: src/y.py\n"
            "*** End Patch\n"
        )
        self.assertIsNotNone(self._assert_second_denied(self._patch("m4b", patch), env))

    def test_apply_patch_without_file_lines_counted(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m5")
        patch = "*** Begin Patch\n*** End Patch\n"
        self.assertIsNotNone(self._assert_second_denied(self._patch("m5", patch), env))

    def test_patch_paths_parsed(self):
        patch = (
            "*** Begin Patch\n*** Add File: b.txt\n+x\n*** Update File: c/d.py\n"
            "*** Delete File: e.md\n*** Move to: f.md\n*** End Patch\n"
        )
        self.assertEqual(hook.apply_patch_paths(patch), ["b.txt", "c/d.py", "e.md", "f.md"])

    def test_claude_gate_ignores_a_bare_string_input(self):
        # Only Copilot passes apply_patch as a bare string; on Claude Code a
        # string tool_input is read as an empty dict, as before.
        claude_env = self.make_env(STEWARD_DELEGATION_GATE="hard")
        payload = {"session_id": "c-str", "tool_name": "Bash", "tool_input": "rm -rf x"}
        for _ in range(3):
            self.assertEqual(run_hook("claude", "gate", payload, claude_env).stdout, "")

    def test_delegated_resets_counter(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m6")
        self._gate(self._edit("m6"), env)
        run_hook("copilot", "delegated",
                 {"session_id": "m6", "tool_name": "Agent", "tool_input": {}}, env)
        self.assertEqual(self._gate(self._edit("m6"), env).stdout, "")

    def test_delegated_ignores_unrecorded_session(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        result = run_hook("copilot", "delegated",
                          {"session_id": "sub-2", "tool_name": "Agent", "tool_input": {}}, env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse(os.path.exists(
            os.path.join(self.state, "steward-delegation", "sub-2.json")))

    def test_gate_mode_file_read_from_copilot_home(self):
        self.write_dep("steward-delegation/gate", "off\n")
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m7")
        self._gate(self._edit("m7"), env)
        self.assertEqual(self._gate(self._edit("m7"), env).stdout, "")

    def test_soft_mode_second_edit_returns_context(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="soft")
        self.start(env, "ms")
        payload = self._edit("ms")
        self.assertEqual(self._gate(payload, env).stdout, "")
        hso = json.loads(self._gate(payload, env).stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hso)
        self.assertIn("task tool", hso["additionalContext"])
        self.assertIn("steward-delegation:coder for code", hso["additionalContext"])

    def test_no_session_id_fails_open(self):
        env = self.co_env(STEWARD_DELEGATION_GATE="hard")
        self.start(env, "m-some")
        payload = self._edit("m-some")
        del payload["session_id"]
        for _ in range(3):
            self.assertEqual(self._gate(payload, env).stdout, "")

    def test_relative_edit_in_chat_session_cwd_counted(self):
        # Outside /tmp, which the allowlist exempts as a whole.
        home = "/nonexistent-steward-home/u"
        copilot_home = os.path.join(home, ".copilot")
        env = self.make_env(HOME=home, COPILOT_HOME=copilot_home, STEWARD_DELEGATION_GATE="hard")
        self.start(env, "chat-1")
        payload = self._edit("chat-1", "src/app.py")
        payload["cwd"] = os.path.join(copilot_home, "chats", "2026-10-09", "x")
        self.assertIsNotNone(self._assert_second_denied(payload, env))

    def test_copilot_config_dir_narrow_entries(self):
        # Outside /tmp, which the allowlist exempts as a whole.
        config = "/nonexistent-steward-home/u/.copilot"
        co = self.env_dict(COPILOT_HOME=config)
        for rel in (
            "steward-delegation/allowlist",
            "steward-prose-gate/prose-patterns",
            "session-state/abc/files/plan.md",
            "settings.json",
            "settings.local.json",
            "copilot-instructions.md",
            "agents/a.agent.md",
            "skills/s/SKILL.md",
            "hooks/h.json",
        ):
            path = os.path.join(config, rel)
            self.assertTrue(hook.is_allowlisted(path, co, harness="copilot"), path)
        for path in (
            os.path.join(config, "steward", "prose-patterns"),
            os.path.join(config, "chats", "2026-10-09", "x", "src", "app.py"),
            "/repo/.copilot/x.py",
        ):
            self.assertFalse(hook.is_allowlisted(path, co, harness="copilot"), path)
        for path in ("/tmp/x", os.path.join(self.home, ".claude", "x"), "/repo/CLAUDE.md"):
            self.assertTrue(hook.is_allowlisted(path, co, harness="copilot"), path)
        claude = self.env_dict(CLAUDE_CONFIG_DIR=config)
        self.assertTrue(hook.is_allowlisted(
            os.path.join(config, "chats", "x", "src", "app.py"), claude))

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
            self.assertTrue(hook.is_allowlisted(path, co, harness="copilot"), path)
        for path in ("/repo/AGENTS.md", "/repo/.github/agents/a.agent.md"):
            self.assertFalse(hook.is_allowlisted(path, claude), path)

    def test_extra_allowlist_file_read_from_copilot_home(self):
        self.write_dep("steward-delegation/allowlist", "/srv/notes/**\n")
        co = self.co_env_dict()
        self.assertTrue(hook.is_allowlisted("/srv/notes/a.md", co, harness="copilot"))
        self.assertFalse(hook.is_allowlisted("/srv/code/a.py", co, harness="copilot"))


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


class CopilotHooksJsonTests(unittest.TestCase):
    def setUp(self):
        self.hooks = load_hooks_json("copilot")

    def _command(self, mode):
        return 'python3 "${PLUGIN_ROOT}/hooks/delegation_hook.py" copilot ' + mode

    def test_events_matchers_timeouts_and_commands(self):
        self.assertEqual(sorted(self.hooks), ["PostToolUse", "PreToolUse", "SessionStart"])
        found = []
        for event, entries in self.hooks.items():
            for entry in entries:
                for h in entry["hooks"]:
                    self.assertEqual(h["type"], "command")
                    found.append((event, entry.get("matcher"), h["command"], h["timeout"]))
        self.assertEqual(sorted(found, key=repr), sorted([
            ("SessionStart", None, self._command("session-start"), 15),
            ("PreToolUse", "Edit|Write|Bash", self._command("gate"), 10),
            ("PreToolUse", "Agent", self._command("delegated"), 10),
            ("PostToolUse", "Agent", self._command("delegated"), 10),
        ], key=repr))

    def test_no_env_prefix(self):
        text = (COPILOT_DIR / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("STEWARD_HARNESS", text)
        self.assertNotIn("=", text)


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
        for path in (p for p in COPILOT_DIR.rglob("*") if p.is_file()):
            text = path.read_text(encoding="utf-8")
            for old in COPILOT_NAMES:
                self.assertNotIn(old, text, "{} in {}".format(old, path))


class CopilotSkillTests(unittest.TestCase):
    def test_skill_names_every_profile(self):
        text = (COPILOT_SKILLS / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        for role in COPILOT_NAMES.values():
            self.assertIn("steward-delegation:" + role, text)
        self.assertNotIn("orchestrat", text.lower())

    def test_skills_ship_delegating_without_orchestrating(self):
        self.assertTrue((COPILOT_SKILLS / "delegating" / "SKILL.md").is_file())
        self.assertFalse(list(COPILOT_SKILLS.rglob("orchestrating*")))

    def test_skill_maps_each_role_to_model_and_effort(self):
        text = (COPILOT_SKILLS / "delegating" / "SKILL.md").read_text(encoding="utf-8")
        for role, model, effort in (
            ("coder", "Claude Opus 5.5", "medium"),
            ("deep-reasoner", "Claude Opus 5.5", "xhigh"),
            ("reviewer", "Claude Sonnet 5.5", "high"),
            ("researcher", "Claude Sonnet 5.5", "low"),
            ("writer", "Claude Sonnet 5.5", "medium"),
            ("mechanic", "Claude Haiku 5.5", "medium"),
            ("top-reviewer", "Claude Opus 5.5", "xhigh"),
        ):
            self.assertIn("| steward-delegation:{} | {} | `{}` |".format(role, model, effort), text)
        self.assertNotIn("family in the profile's name", text)


if __name__ == "__main__":
    unittest.main()
