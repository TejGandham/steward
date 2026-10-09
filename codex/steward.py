#!/usr/bin/env python3
"""Codex hook adapter. Reuses text checks without changing other harnesses."""
import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    spec = importlib.util.spec_from_file_location("steward_text_checks", ROOT / "hooks/steward_hook.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
except Exception:
    checks = None


def config_dir(env):
    return checks._expand_user(env.get("CODEX_HOME") or
                               str(Path(env.get("HOME") or str(Path.home())) / ".codex"), env)


def dispatch(command, payload, env):
    if checks is None:
        return None
    if command == "session-start":
        root = Path(env.get("STEWARD_PLUGIN_ROOT") or str(ROOT))
        text = checks.strip_frontmatter((root / "codex/skills/delegating/SKILL.md").read_text()).strip()
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}

    if command == "gate":
        # Codex shares session_id with children and does not document a child
        # identity on PreToolUse. Never apply the parent edit counter here.
        args = payload.get("tool_input")
        if payload.get("tool_name") != "Bash" or not isinstance(args, dict):
            return None
        shell = args.get("command")
        if not isinstance(shell, str):
            return None
        violation = checks.pr_gate_violation(shell, payload.get("cwd"),
                                             checks.load_operator_patterns(config_dir(env)))
        if violation:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                    "permissionDecision": "deny", "permissionDecisionReason": violation}}
        return None

    if command == "prose-gate":
        if payload.get("stop_hook_active") is True:
            return None
        text = payload.get("last_assistant_message")
        # Codex transcripts are not a stable hook interface. Fail open if the
        # documented message field is absent instead of guessing the format.
        if not isinstance(text, str) or not text.strip():
            return None
        cleaned = checks._clean_text(text)
        _, markers = checks.find_markers(cleaned)
        phrases = checks.find_operator_hits(cleaned, checks.load_operator_patterns(config_dir(env)))
        dashes = cleaned.count(checks.EM_DASH)
        if not dashes and len(markers) < 2 and not phrases:
            return None
        found = []
        if phrases:
            found.append("phrases the operator bans: " + ", ".join(phrases))
        if dashes:
            found.append(f"{dashes} em-dash(es)")
        if markers:
            found.append("these AI tells: " + ", ".join(markers))
        return {"decision": "block", "reason": checks.PROSE_OPERATOR_MSG_TEMPLATE.format(found="; ".join(found))}
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or len(sys.argv) < 2:
            return
        output = dispatch(sys.argv[1], payload, os.environ)
        if output:
            print(json.dumps(output))
    except Exception:
        # Match Steward's fail-open policy, including bad input and I/O errors.
        return


if __name__ == "__main__":
    main()
