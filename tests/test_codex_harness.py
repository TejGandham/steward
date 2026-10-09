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
        spec = importlib.util.spec_from_file_location("install_agents", REPO_ROOT / "codex/install_agents.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)

    def test_all_seven_agents_pin_supported_model_and_effort(self):
        destination = Path(self.tmp) / "agents"
        self.assertEqual(self.installer.install(destination), 7)
        self.assertEqual(self.installer.install(destination), 7)
        models = {"gpt-6.1-sol": {"low", "medium", "high", "xhigh", "max"},
                  "gpt-6-astra": {"low", "medium", "high", "xhigh", "max"},
                  "gpt-6-luna": {"none", "low", "medium", "high", "xhigh", "max"}}
        for path in destination.glob("*.toml"):
            agent = tomllib.loads(path.read_text())
            self.assertEqual(agent["name"], path.stem)
            self.assertIn(agent["model_reasoning_effort"], models[agent["model"]])
            self.assertTrue(agent["developer_instructions"])
            self.assertNotIn("sandbox_mode", agent)

    def test_collision_preserves_existing_file_and_installs_nothing(self):
        destination = Path(self.tmp) / "agents"
        destination.mkdir()
        existing = destination / "steward-writer.toml"
        existing.write_text("local edits")
        with self.assertRaises(ValueError):
            self.installer.install(destination)
        self.assertEqual(existing.read_text(), "local edits")
        self.assertEqual(list(destination.iterdir()), [existing])


if __name__ == "__main__":
    unittest.main()
