#!/usr/bin/env python3
"""steward-prose-gate hook script.

Called as `prose_gate_hook.py <harness> <mode>`. Reads one JSON object
from stdin and prints at most one JSON object to stdout. Stdlib only,
python3.9+.

Harness: claude. Modes: pr-gate (PreToolUse on Bash: deny a
`gh pr create|edit` whose body has AI tells) and prose-gate (Stop: block
a reply that has AI tells).

This script must never raise to whoever called it. Any error, bad
input, unknown harness or mode, or missing file means: exit 0, no
output. Fail open, always.
"""

import json
import os
import re
import sys
from pathlib import Path

PLUGIN_DIR_NAME = "steward-prose-gate"

# ---------------------------------------------------------------------------
# Directories and paths
# ---------------------------------------------------------------------------


def get_config_dir(harness, env):
    """Where the harness keeps its config. Claude Code: $CLAUDE_CONFIG_DIR
    or ~/.claude."""
    home = env.get("HOME") or os.path.expanduser("~")
    value = env.get("CLAUDE_CONFIG_DIR")
    if value:
        return value
    return os.path.join(home, ".claude")


def get_state_dir(env):
    """Where this plugin keeps per-session state."""
    value = env.get("XDG_STATE_HOME")
    if value:
        return os.path.join(value, PLUGIN_DIR_NAME)
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".local", "state", PLUGIN_DIR_NAME)


def get_plugin_root():
    """Root of this plugin: two directories up from this script (hooks/ is
    one level under the root)."""
    return str(Path(__file__).resolve().parent.parent)


def _expand_user(path, env):
    """Expand a leading ~ using the env dict we were given, not os.environ."""
    if not path:
        return path
    if path == "~":
        return env.get("HOME") or os.path.expanduser("~")
    if path.startswith("~/") or path.startswith("~\\"):
        home = env.get("HOME") or os.path.expanduser("~")
        return os.path.join(home, path[2:])
    return path


def _non_empty_str(value):
    return isinstance(value, str) and value != ""


# ---------------------------------------------------------------------------
# The on/off switch (file first, then env, then default on)
# ---------------------------------------------------------------------------

_SWITCH_VALUES = ("on", "off")


def _read_switch_file(config_dir):
    path = os.path.join(config_dir, PLUGIN_DIR_NAME, "gate")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip().lower()
    except OSError:
        return None
    if value in _SWITCH_VALUES:
        return value
    return None


def gate_is_on(harness, env):
    """One switch covers both gates. Read on every call."""
    file_value = _read_switch_file(get_config_dir(harness, env))
    if file_value:
        return file_value == "on"
    env_value = (env.get("STEWARD_PROSE_GATE") or "").strip().lower()
    if env_value in _SWITCH_VALUES:
        return env_value == "on"
    return True


# ---------------------------------------------------------------------------
# AI-tell markers, shared by the PR gate and the prose gate
# ---------------------------------------------------------------------------


def load_markers(path):
    """The AI-tell word list: one literal marker per line, # comments and
    blank lines skipped, whitespace trimmed. A missing or unreadable file
    means no markers."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    markers = []
    for line in lines:
        marker = line.strip()
        if marker and not marker.startswith("#"):
            markers.append(marker)
    return markers


def _compile_marker(marker):
    pattern = r"\b" + re.escape(marker)
    last = marker[-1]
    if last.isalnum() or last == "_":
        pattern += r"\b"
    return re.compile(pattern, re.IGNORECASE)


_MARKER_PATTERNS = [
    (m, _compile_marker(m))
    for m in load_markers(os.path.join(get_plugin_root(), "data", "ai-tells.txt"))
]


def load_operator_patterns(config_dir):
    """The operator's own banned phrases, from
    <config>/steward-prose-gate/prose-patterns: one case-insensitive
    regular expression per line, # starts a comment, blank lines are
    skipped, and a line that does not compile is ignored. ^ and $ match at
    line boundaries. A missing file means no patterns."""
    path = os.path.join(config_dir, PLUGIN_DIR_NAME, "prose-patterns")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    patterns = []
    for line in lines:
        source = line.strip()
        if not source or source.startswith("#"):
            continue
        try:
            patterns.append(re.compile(source, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return patterns


def find_operator_hits(text, patterns):
    """The matched text of every operator pattern that hits, in file order.
    Unlike the built-in markers, a single hit is enough to block."""
    hits = []
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            found = " ".join(m.group(0).split()) or pattern.pattern
            if found not in hits:
                hits.append(found)
    return hits


def find_markers(text):
    """Returns (total hit count, list of distinct markers that hit)."""
    hits = 0
    names = []
    for name, pattern in _MARKER_PATTERNS:
        count = len(pattern.findall(text))
        if count:
            hits += count
            names.append(name)
    return hits, names


# ---------------------------------------------------------------------------
# Text cleaning: code, URLs and paths are not prose
# ---------------------------------------------------------------------------

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
# A fence with no closing ``` strips from the fence to the end of the
# text, rather than leaving everything after it unstripped.
_UNTERMINATED_FENCE_RE = re.compile(r"```.*\Z", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")

# A whole token that is a file path or a bare domain/filename: contains a
# "/", or is dot-separated segments with no slash (like "x.py" or
# "example.com"). Dropped before marker matching so a marker word that
# is only part of a path (like "landscape" in "/src/landscape/x.py")
# does not count as prose.
_PATH_LIKE_TOKEN_RE = re.compile(
    r"(?<!\S)(?:[\w.-]*/[\w./-]*|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)(?!\S)"
)


def _clean_text(text):
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _UNTERMINATED_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _PATH_LIKE_TOKEN_RE.sub(" ", text)
    return text


# ---------------------------------------------------------------------------
# pr-gate: the "gh pr create|edit" PR-body check
# ---------------------------------------------------------------------------

_BASH_TOOLS = ("Bash", "bash")
_GH_PR_CREATE_EDIT_RE = re.compile(r"\bgh\s+pr\s+(create|edit)\b")
_BODY_FILE_RE = re.compile(r"(?:--body-file|-F)\s+(\S+)")

PR_OPERATOR_MSG_TEMPLATE = (
    "steward PR gate: the PR body contains phrases the operator bans: "
    "{phrases}. Redraft it from the branch's diff with the plainlanguage "
    "skill, show the operator, then retry."
)

PR_MARKER_MSG_TEMPLATE = (
    "steward PR gate: the PR body contains these AI tells: {markers}. "
    "Redraft it from the branch's diff with the plainlanguage skill, show "
    "the operator, then retry."
)


def _resolve_against_cwd(path, cwd):
    if os.path.isabs(path):
        return path
    base = cwd or os.getcwd()
    return os.path.join(base, path)


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def pr_gate_violation(command, cwd=None, operator_patterns=()):
    """None if fine, else the deny reason string. When the command passes
    the PR body as a file (--body-file or -F), that file's text is
    checked too, not just the command line itself."""
    if not _GH_PR_CREATE_EDIT_RE.search(command):
        return None
    combined = command
    m = _BODY_FILE_RE.search(command)
    if m:
        body_path = _resolve_against_cwd(m.group(1).strip("'\""), cwd)
        combined = combined + "\n" + _read_text_file(body_path)
    cleaned = _clean_text(combined)
    _hits, names = find_markers(cleaned)
    if len(names) >= 2:
        return PR_MARKER_MSG_TEMPLATE.format(markers=", ".join(names))
    phrases = find_operator_hits(cleaned, operator_patterns)
    if phrases:
        return PR_OPERATOR_MSG_TEMPLATE.format(phrases=", ".join(phrases))
    return None


def cmd_pr_gate(harness, payload, env):
    if _non_empty_str(payload.get("agent_id")):
        return None
    if not gate_is_on(harness, env):
        return None

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = None

    if tool_name in _BASH_TOOLS:
        command = tool_input.get("command")
        if not isinstance(command, str):
            command = ""
        violation = pr_gate_violation(
            command, cwd, load_operator_patterns(get_config_dir(harness, env)))
        if violation:
            return json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": violation,
                }
            })
    return None


# ---------------------------------------------------------------------------
# prose-gate: the Stop-hook reply check
# ---------------------------------------------------------------------------

_MAX_TAIL_BYTES = 2 * 1024 * 1024


def _read_transcript_tail(path):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - _MAX_TAIL_BYTES)
        f.seek(start)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if start > 0:
        idx = text.find("\n")
        if idx != -1:
            text = text[idx + 1:]
    return text


def _extract_last_assistant_text(transcript_path):
    if not transcript_path:
        return None
    path = os.path.expanduser(transcript_path)
    try:
        raw = _read_transcript_tail(path)
    except OSError:
        return None

    parsed = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            parsed.append(obj)

    last_idx = None
    for i in range(len(parsed) - 1, -1, -1):
        if parsed[i].get("type") == "assistant":
            last_idx = i
            break
    if last_idx is None:
        return None

    target_id = None
    last_msg = parsed[last_idx].get("message")
    if isinstance(last_msg, dict):
        target_id = last_msg.get("id")

    run = []
    i = last_idx
    while i >= 0 and parsed[i].get("type") == "assistant":
        run.append(parsed[i])
        i -= 1
    run.reverse()

    if target_id:
        run = [
            p for p in run
            if isinstance(p.get("message"), dict) and p["message"].get("id") == target_id
        ]

    texts = []
    for obj in run:
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = item.get("text")
                    if isinstance(t, str):
                        texts.append(t)
        elif isinstance(content, str):
            texts.append(content)

    if not texts:
        return None
    return "".join(texts)


PROSE_OPERATOR_MSG_TEMPLATE = (
    "steward prose gate: your last reply has {found}. The operator's rule "
    "is plain language. Revise the reply with the plainlanguage skill and "
    "send it again."
)


def cmd_prose_gate(harness, payload, env):
    # One revision per reply: a Stop that follows a block is let through.
    if payload.get("stop_hook_active") is True:
        return None
    if _non_empty_str(payload.get("agent_id")):
        return None
    if not gate_is_on(harness, env):
        return None

    text = payload.get("last_assistant_message")
    if not (isinstance(text, str) and text.strip()):
        transcript_path = payload.get("transcript_path")
        text = None
        if isinstance(transcript_path, str) and transcript_path:
            text = _extract_last_assistant_text(transcript_path)

    if not text:
        return None

    cleaned = _clean_text(text)
    _hits, names = find_markers(cleaned)
    phrases = find_operator_hits(cleaned, load_operator_patterns(get_config_dir(harness, env)))

    # The threshold counts distinct markers, not raw occurrences: the
    # same marker twice is still only one kind of tell. An operator
    # phrase blocks on its own.
    if len(names) < 2 and not phrases:
        return None

    # Name only what was found, so the message never lists an empty kind.
    found = []
    if phrases:
        found.append("phrases the operator bans: " + ", ".join(phrases))
    if names:
        found.append("these AI tells: " + ", ".join(names))
    reason = PROSE_OPERATOR_MSG_TEMPLATE.format(found="; ".join(found))
    return json.dumps({"decision": "block", "reason": reason})


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_MODES = {
    "claude": {
        "pr-gate": cmd_pr_gate,
        "prose-gate": cmd_prose_gate,
    },
}


def _dispatch(argv, stdin_text, env):
    if len(argv) < 3:
        return None
    harness, mode = argv[1], argv[2]
    handler = _MODES.get(harness, {}).get(mode)
    if handler is None:
        return None
    try:
        payload = json.loads(stdin_text) if stdin_text and stdin_text.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return handler(harness, payload, env)


def main():
    try:
        stdin_text = sys.stdin.read()
        output = _dispatch(sys.argv, stdin_text, os.environ)
        if output:
            sys.stdout.write(output)
            if not output.endswith("\n"):
                sys.stdout.write("\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
