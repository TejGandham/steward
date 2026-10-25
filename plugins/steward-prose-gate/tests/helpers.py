"""Shared fixtures for the steward-prose-gate tests.

These tests never touch the real home directory. Every test gets its
own temp dirs for HOME, XDG_STATE_HOME and the harness config dir.
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
SCRIPT = PLUGIN_ROOT / "hooks" / "prose_gate_hook.py"
AI_TELLS = PLUGIN_ROOT / "data" / "ai-tells.txt"


def load_hook_module():
    """Import the hook script as a plain module, so unit tests can call its
    helper functions directly without a subprocess per case."""
    spec = importlib.util.spec_from_file_location("prose_gate_hook", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_hook(harness, mode, payload, env):
    """Run the script in a subprocess as `prose_gate_hook.py <harness> <mode>`
    with the given stdin payload and env."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), harness, mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


class StewardTestCase(unittest.TestCase):
    """Base case: gives every test a throwaway HOME, state dir and config
    dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-prose-gate-test-")
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state")
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.home, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_env(self, **extra):
        env = os.environ.copy()
        for key in ("STEWARD_PROSE_GATE", "XDG_STATE_HOME", "CLAUDE_CONFIG_DIR",
                    "HOME", "PI_CODING_AGENT_DIR", "COPILOT_HOME", "CODEX_HOME"):
            env.pop(key, None)
        env["HOME"] = self.home
        env["XDG_STATE_HOME"] = self.state
        env["CLAUDE_CONFIG_DIR"] = self.config
        env.update(extra)
        return env

    def env_dict(self, **extra):
        """A plain dict, for calling module functions directly (no subprocess)."""
        d = {
            "HOME": self.home,
            "XDG_STATE_HOME": self.state,
            "CLAUDE_CONFIG_DIR": self.config,
        }
        d.update(extra)
        return d

    def write_dep(self, relative_path, content="stub\n"):
        path = os.path.join(self.config, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
