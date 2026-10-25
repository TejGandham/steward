"""Repo-level layout tests: each plugin folder is self-contained.

Four rules, one test class each:

1. No file under plugins/<a>/ holds a path into another plugin
   (`plugins/<b>` or `../<b>`), and none names the old monolith hook script.
   Bare plugin names stay allowed: the orchestration block names
   `steward-delegation:delegating` and READMEs list install sets.
2. Each plugin's manifests (.claude-plugin, .codex-plugin, .github/plugin,
   whichever exist) carry one version.
3. No plugin folder holds a package.json.
4. Each plugin folder copied alone to a temp dir runs every hook mode it
   ships, under a temp HOME and temp config and state dirs, and exits as its
   contract says.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
PLUGIN_NAMES = sorted(p.name for p in PLUGINS_DIR.iterdir() if p.is_dir())

# Built in two parts so a whole-tree grep for the old script name stays empty.
OLD_HOOK_NEEDLE = "steward_" + "hook"

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules"}
MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    ".github/plugin/plugin.json",
)
# Where each harness's hooks.json lives inside a plugin folder.
HOOK_FILES = {
    "claude": "hooks/hooks.json",
    "codex": "codex/hooks.json",
    "copilot": "copilot/hooks.json",
}
# The pi modes each plugin's pi extension spawns, with the exit code each
# must give. The delegation CLI modes exit 2 on unusable input.
PI_MODES = {
    "steward-delegation": (
        ("delegation_hook.py", "session-start", "{}", 0),
        ("delegation_hook.py", "gate", '{"toolName": "bash", "input": {"command": "ls"}}', 0),
        ("delegation_hook.py", "delegated", "{}", 0),
        ("delegation_hook.py", "model-plan", "not json", 2),
        ("delegation_hook.py", "model-plan-apply", "not json", 2),
        ("delegation_hook.py", "delegation-stats", "not json", 2),
    ),
    "steward-prose-gate": (
        ("prose_gate_hook.py", "pr-gate", '{"command": "ls"}', 0),
        ("prose_gate_hook.py", "prose-gate", '{"text": "Done."}', 0),
    ),
}
MINIMAL_PAYLOAD = {
    "session_id": "layout-test",
    "sessionId": "layout-test",
    "hook_event_name": "",
    "source": "startup",
    "tool_name": "Bash",
    "toolName": "Bash",
    "tool_input": {"command": "ls"},
    "toolArgs": json.dumps({"command": "ls"}),
}


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def scan_plugin(plugin_dir, other_names):
    """Return (file, line number, match) for every cross-plugin path or old
    hook script name under plugin_dir."""
    needles = [re.escape(OLD_HOOK_NEEDLE)]
    for name in other_names:
        needles.append(re.escape("plugins/" + name))
        needles.append(re.escape("../" + name))
    pattern = re.compile("|".join(needles))
    hits = []
    for path in _walk_files(plugin_dir):
        text = path.read_bytes().decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                hits.append((str(path), lineno, match.group(0)))
    return hits


def _copy_plugin(name, dest_parent):
    dest = Path(dest_parent) / name
    shutil.copytree(PLUGINS_DIR / name, dest,
                    ignore=shutil.ignore_patterns(*SKIP_DIRS))
    return dest


def _isolated_env(tmp):
    """A fresh env: PATH plus temp HOME, state and config dirs. Nothing is
    copied from os.environ, so no root or config override can leak in."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for key, sub in (("HOME", "home"), ("XDG_STATE_HOME", "state"),
                     ("XDG_CONFIG_HOME", "config"),
                     ("CLAUDE_CONFIG_DIR", "claude"),
                     ("COPILOT_HOME", "copilot"), ("CODEX_HOME", "codex"),
                     ("PI_CODING_AGENT_DIR", "pi")):
        path = Path(tmp) / sub
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    return env


def _hook_commands(hooks_json):
    with open(hooks_json, encoding="utf-8") as f:
        data = json.load(f)
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event, hook["command"]


def _run(argv, stdin_text, env, cwd):
    return subprocess.run(argv, input=stdin_text, env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


class NoCrossPluginPathTests(unittest.TestCase):
    def test_plugins_found(self):
        self.assertEqual(PLUGIN_NAMES, ["steward-delegation",
                                        "steward-orchestration",
                                        "steward-prose-gate"])

    def test_no_plugin_points_into_another(self):
        for name in PLUGIN_NAMES:
            others = [n for n in PLUGIN_NAMES if n != name]
            with self.subTest(plugin=name):
                self.assertEqual(scan_plugin(PLUGINS_DIR / name, others), [])

    def test_scanner_flags_planted_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = _copy_plugin("steward-prose-gate", tmp)
            (copy / "planted.md").write_text(
                "see plugins/steward-delegation/x\n", encoding="utf-8")
            hits = scan_plugin(copy, ["steward-delegation"])
            self.assertEqual([(Path(f).name, n, m) for f, n, m in hits],
                             [("planted.md", 1, "plugins/steward-delegation")])

    def test_scanner_flags_old_hook_name_and_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "a"
            planted.mkdir()
            (planted / "x.py").write_text(
                "run('" + OLD_HOOK_NEEDLE + ".py')\nopen('../b/y')\n",
                encoding="utf-8")
            hits = scan_plugin(planted, ["b"])
            self.assertEqual([m for _, _, m in hits], [OLD_HOOK_NEEDLE, "../b"])

    def test_scanner_allows_bare_plugin_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "README.md").write_text(
                "Install steward-delegation and use "
                "`steward-delegation:delegating`.\n", encoding="utf-8")
            self.assertEqual(scan_plugin(tmp, ["steward-delegation"]), [])


class ManifestVersionTests(unittest.TestCase):
    def test_each_plugin_manifests_share_one_version(self):
        for name in PLUGIN_NAMES:
            versions = {}
            for rel in MANIFESTS:
                path = PLUGINS_DIR / name / rel
                if path.exists():
                    with open(path, encoding="utf-8") as f:
                        versions[rel] = json.load(f)["version"]
            with self.subTest(plugin=name):
                self.assertTrue(versions, "no manifest")
                self.assertEqual(len(set(versions.values())), 1, versions)


class NoPluginPackageJsonTests(unittest.TestCase):
    def test_no_package_json_in_plugin_folders(self):
        for name in PLUGIN_NAMES:
            found = [str(p) for p in _walk_files(PLUGINS_DIR / name)
                     if p.name == "package.json"]
            with self.subTest(plugin=name):
                self.assertEqual(found, [])


class CopiedAloneTests(unittest.TestCase):
    """Copy each plugin folder alone to a temp dir and run its hooks there."""

    def _hook_runs(self, name):
        with tempfile.TemporaryDirectory() as tmp:
            copy = _copy_plugin(name, Path(tmp) / "plugin")
            env = _isolated_env(Path(tmp) / "env")
            env["CLAUDE_PLUGIN_ROOT"] = str(copy)
            env["PLUGIN_ROOT"] = str(copy)
            ran = []
            for harness, rel in HOOK_FILES.items():
                hooks_json = copy / rel
                if not hooks_json.exists():
                    continue
                for event, command in _hook_commands(hooks_json):
                    command = (command.replace("${CLAUDE_PLUGIN_ROOT}", str(copy))
                               .replace("${PLUGIN_ROOT}", str(copy)))
                    payload = dict(MINIMAL_PAYLOAD, hook_event_name=event)
                    result = _run(shlex.split(command), json.dumps(payload),
                                  env, env["HOME"])
                    ran.append((harness, event, command, result))
            for script, mode, stdin_text, code in PI_MODES.get(name, ()):
                argv = [sys.executable, str(copy / "hooks" / script), "pi", mode]
                result = _run(argv, stdin_text, env, env["HOME"])
                ran.append(("pi", mode, (script, code), result))
            return ran

    def _check(self, name):
        ran = self._hook_runs(name)
        self.assertTrue(ran, name)
        for harness, event, command, result in ran:
            expected = command[1] if harness == "pi" else 0
            with self.subTest(plugin=name, harness=harness, mode=event):
                self.assertEqual(result.returncode, expected,
                                 (command, result.stdout, result.stderr))
                self.assertNotIn("Traceback", result.stderr)
        return ran

    def _claude_session_context(self, ran):
        for harness, event, command, result in ran:
            if (harness, event) == ("claude", "SessionStart"):
                self.assertTrue(result.stdout.strip(), "session-start printed nothing")
                out = json.loads(result.stdout)
                return out["hookSpecificOutput"]["additionalContext"]
        self.fail("no claude SessionStart hook")

    def test_delegation_copied_alone(self):
        ran = self._check("steward-delegation")
        harnesses = {h for h, *_ in ran}
        self.assertEqual(harnesses, {"claude", "codex", "copilot", "pi"})
        self.assertTrue(self._claude_session_context(ran).strip())

    def test_orchestration_copied_alone(self):
        ran = self._check("steward-orchestration")
        self.assertEqual({h for h, *_ in ran}, {"claude"})
        self.assertTrue(self._claude_session_context(ran).strip())

    def test_prose_gate_copied_alone(self):
        ran = self._check("steward-prose-gate")
        self.assertEqual({h for h, *_ in ran}, {"claude", "codex", "copilot", "pi"})


if __name__ == "__main__":
    unittest.main()
