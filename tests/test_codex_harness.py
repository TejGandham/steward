"""Codex hook contracts and optional agent installation, using isolated homes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

from test_steward_hook import EM_DASH, REPO_ROOT, StewardTestCase

_spec = importlib.util.spec_from_file_location("codex_steward", REPO_ROOT / "codex/steward.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


SUPPORTED_EFFORTS = {"gpt-6.1-sol": {"low", "medium", "high", "xhigh", "max"},
                     "gpt-6-astra": {"low", "medium", "high", "xhigh", "max"},
                     "gpt-6-luna": {"none", "low", "medium", "high", "xhigh", "max"}}
PROFILES_PATH = REPO_ROOT / "codex/skills/delegating/profiles.json"
SKILL_PATH = REPO_ROOT / "codex/skills/delegating/SKILL.md"
ASTRA_ROLES = {"deep-reasoner", "top-reviewer"}


def load_installer(path):
    spec = importlib.util.spec_from_file_location("install_agents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(command, payload, env):
    return subprocess.run([sys.executable, str(REPO_ROOT / "codex/steward.py"), command],
                          input=json.dumps(payload), text=True, capture_output=True, env=env)


class CodexHarnessTests(StewardTestCase):
    def setUp(self):
        super().setUp()
        skill = Path(self.plugin_root) / "codex/skills/delegating/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: delegating\ndescription: fixture\n---\nCodex delegation edict.\n")

    def env(self, **extra):
        return self.make_env(STEWARD_HARNESS="codex", CODEX_HOME=self.config, **extra)

    def test_startup_injects_codex_edict_without_claude_registry(self):
        result = run_hook("session-start", {"session_id": "s1", "source": "startup"}, self.env())
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertEqual(output["additionalContext"], "Codex delegation edict.")
        self.assertFalse(Path(self.orch, "initiatives.md").exists())

    def test_config_uses_codex_home_and_ignores_claude_config(self):
        self.assertEqual(hook.config_dir({"HOME": self.home, "STEWARD_HARNESS": "codex"}),
                         str(Path(self.home) / ".codex"))
        self.assertEqual(hook.config_dir({"HOME": self.home, "STEWARD_HARNESS": "codex",
                                              "CODEX_HOME": "~/custom"}), str(Path(self.home) / "custom"))

    def test_shared_session_id_never_blocks_parent_or_worker_edits(self):
        for tool, args in [("apply_patch", {"command": "*** Begin Patch\n*** Add File: code.py\n+x\n*** End Patch"}),
                           ("Bash", {"command": "python3 build.py > result.txt"})]:
            for _ in range(3):
                output = run_hook("gate", {"session_id": "shared", "tool_name": tool,
                                            "tool_input": args}, self.env(STEWARD_GATE="hard"))
                self.assertEqual(output.stdout, "")

    def test_pr_body_file_is_checked_against_cwd_even_with_gate_off(self):
        body = Path(self.tmp) / "body.md"
        body.write_text("Fix " + EM_DASH + " details")
        payload = {"session_id": "shared", "tool_name": "Bash", "cwd": self.tmp,
                   "tool_input": {"command": "gh pr create --body-file body.md"}}
        output = json.loads(run_hook("gate", payload, self.env(STEWARD_GATE="off")).stdout)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_operator_patterns_use_codex_config(self):
        self.write_dep("steward/prose-patterns", "banned phrase\n")
        output = run_hook("prose-gate", {"last_assistant_message": "A banned phrase."}, self.env())
        self.assertEqual(json.loads(output.stdout)["decision"], "block")

    def test_stop_requests_one_revision_and_does_not_parse_unstable_transcript(self):
        payload = {"last_assistant_message": "Fix " + EM_DASH + " details"}
        self.assertEqual(json.loads(run_hook("prose-gate", payload, self.env()).stdout)["decision"], "block")
        payload["stop_hook_active"] = True
        self.assertEqual(run_hook("prose-gate", payload, self.env()).stdout, "")
        transcript = Path(self.tmp) / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "Fix " + EM_DASH + " details"}]}}) + "\n")
        self.assertEqual(run_hook("prose-gate", {"transcript_path": str(transcript)}, self.env()).stdout, "")

    def test_portable_launcher_uses_codex_not_claude_skill(self):
        result = subprocess.run([sys.executable, str(REPO_ROOT / "codex/steward.py"), "session-start"],
                                input="{}", text=True, capture_output=True,
                                env=self.make_env(STEWARD_PLUGIN_ROOT=str(REPO_ROOT)))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("gpt-6.1-sol", text)
        self.assertNotIn("coder-opus-medium", text)

    def test_missing_skill_fails_open(self):
        result = run_hook("session-start", {}, self.env(STEWARD_PLUGIN_ROOT=self.tmp))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class CodexAgentInstallTests(StewardTestCase):
    def setUp(self):
        super().setUp()
        self.installer = load_installer(REPO_ROOT / "codex/install_agents.py")

    def test_all_seven_agents_pin_supported_model_and_effort(self):
        destination = Path(self.tmp) / "agents"
        self.assertEqual(self.installer.install(destination), 7)
        self.assertEqual(self.installer.install(destination), 7)
        models = SUPPORTED_EFFORTS
        for path in destination.glob("*.toml"):
            agent = tomllib.loads(path.read_text())
            self.assertEqual(agent["name"], path.stem)
            self.assertIn(agent["model_reasoning_effort"], models[agent["model"]])
            self.assertTrue(agent["developer_instructions"])
            self.assertNotIn("sandbox_mode", agent)

    def test_fallback_field_does_not_change_generated_agents(self):
        profiles = json.loads(PROFILES_PATH.read_text())
        stripped = {role: {k: v for k, v in p.items() if k != "fallback"} for role, p in profiles.items()}
        copy_root = Path(self.tmp) / "codex"
        (copy_root / "skills/delegating").mkdir(parents=True)
        (copy_root / "install_agents.py").write_text((REPO_ROOT / "codex/install_agents.py").read_text())
        (copy_root / "skills/delegating/profiles.json").write_text(json.dumps(stripped))
        baseline = load_installer(copy_root / "install_agents.py").render_agents()
        rendered = self.installer.render_agents()
        self.assertEqual(rendered, baseline)
        for text in rendered.values():
            self.assertNotIn("fallback", tomllib.loads(text))

    def test_collision_preserves_existing_file_and_installs_nothing(self):
        destination = Path(self.tmp) / "agents"
        destination.mkdir()
        existing = destination / "steward-writer.toml"
        existing.write_text("local edits")
        with self.assertRaises(ValueError):
            self.installer.install(destination)
        self.assertEqual(existing.read_text(), "local edits")
        self.assertEqual(list(destination.iterdir()), [existing])


class CodexAstraFallbackTests(unittest.TestCase):
    def test_only_astra_roles_fall_back_to_sol_xhigh(self):
        profiles = json.loads(PROFILES_PATH.read_text())
        astra = {role for role, p in profiles.items() if p["model"] == "gpt-6-astra"}
        self.assertEqual(astra, ASTRA_ROLES)
        for role, profile in profiles.items():
            if role in ASTRA_ROLES:
                fallback = profile["fallback"]
                self.assertEqual(fallback, {"model": "gpt-6.1-sol", "reasoning_effort": "xhigh"})
                self.assertIn(fallback["reasoning_effort"], SUPPORTED_EFFORTS[fallback["model"]])
            else:
                self.assertNotIn("fallback", profile, role)

    def test_skill_names_the_fallback_and_named_agent_workaround(self):
        text = SKILL_PATH.read_text()
        self.assertIn("Operator decision, 2026-10-09", text)
        self.assertIn("fall back to `gpt-6.1-sol` at xhigh", text)
        self.assertIn("steward-deep-reasoner", text)
        self.assertIn("steward-top-reviewer", text)
        self.assertNotIn(EM_DASH, text)


if __name__ == "__main__":
    unittest.main()
