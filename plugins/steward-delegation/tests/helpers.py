"""Shared fixtures for the steward-delegation tests.

These tests never touch the real home directory. Every test gets its
own temp dirs for HOME, XDG_STATE_HOME, the harness config dir and
STEWARD_ORCHESTRATION_DIR, and its own temp plugin root (through
STEWARD_DELEGATION_ROOT) so the fixture skill file does not depend on
the real checkout.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "hooks" / "delegation_hook.py"


def load_hooks_json(harness):
    """The parsed `<harness>/hooks.json` shipped in this plugin."""
    with open(PLUGIN_ROOT / harness / "hooks.json", encoding="utf-8") as f:
        return json.load(f)["hooks"]

# Env names the hook reads, or that would point it at the operator's real
# files. Each test clears them and sets its own.
_CLEARED_ENV = (
    "STEWARD_DELEGATION_GATE", "STEWARD_DELEGATION_ROOT",
    "STEWARD_ORCHESTRATION_DIR", "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR",
    "HOME", "PI_CODING_AGENT_DIR", "COPILOT_HOME", "CODEX_HOME",
)


def load_hook_module():
    """Import the hook script as a plain module, so unit tests can call its
    helper functions directly without a subprocess per case."""
    spec = importlib.util.spec_from_file_location("delegation_hook", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(harness, mode, payload, env, script=None):
    """Run the script in a subprocess as `delegation_hook.py <harness> <mode>`
    with the given stdin payload and env."""
    return subprocess.run(
        [sys.executable, str(script or SCRIPT), harness, mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


class StewardTestCase(unittest.TestCase):
    """Base case: gives every test a throwaway HOME, state dir, config dir,
    orchestration dir and plugin root."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-delegation-test-")
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

    def write_plugin_file(self, relative_path, content):
        """Write a fixture file under the temp plugin root."""
        path = os.path.join(self.plugin_root, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def write_dep(self, relative_path, content="stub\n"):
        """Write a file under the temp harness config dir."""
        path = os.path.join(self.config, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def make_env(self, **extra):
        env = os.environ.copy()
        for key in _CLEARED_ENV:
            env.pop(key, None)
        env["HOME"] = self.home
        env["XDG_STATE_HOME"] = self.state
        env["CLAUDE_CONFIG_DIR"] = self.config
        env["STEWARD_ORCHESTRATION_DIR"] = self.orch
        env["STEWARD_DELEGATION_ROOT"] = self.plugin_root
        env.update(extra)
        return env

    def env_dict(self, **extra):
        """A plain dict, for calling module functions directly (no subprocess)."""
        d = {
            "HOME": self.home,
            "XDG_STATE_HOME": self.state,
            "CLAUDE_CONFIG_DIR": self.config,
            "STEWARD_ORCHESTRATION_DIR": self.orch,
            "STEWARD_DELEGATION_ROOT": self.plugin_root,
        }
        d.update(extra)
        return d
