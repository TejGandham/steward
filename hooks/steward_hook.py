#!/usr/bin/env python3
"""Steward plugin hook script.

Reads one JSON object from stdin and, depending on the subcommand,
prints at most one JSON object to stdout. Stdlib only, python3.9+.

This script must never raise to whoever called it. Any error, bad
input, or missing file means: exit 0, no output. Fail open, always.
"""

import fnmatch
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

# ---------------------------------------------------------------------------
# Directories and paths
# ---------------------------------------------------------------------------

EM_DASH = chr(0x2014)  # the character itself is never written literally here


def get_harness(env):
    """Which agent harness is calling. The pi extension sets
    STEWARD_HARNESS=pi; anything else is Claude Code."""
    if (env.get("STEWARD_HARNESS") or "").strip().lower() == "pi":
        return "pi"
    return "claude"


def get_config_dir(env):
    """Where the harness keeps its config. Claude Code: $CLAUDE_CONFIG_DIR
    or ~/.claude. pi: $PI_CODING_AGENT_DIR or ~/.pi/agent."""
    home = env.get("HOME") or os.path.expanduser("~")
    if get_harness(env) == "pi":
        value = env.get("PI_CODING_AGENT_DIR")
        if value:
            return _expand_user(value, env)
        return os.path.join(home, ".pi", "agent")
    value = env.get("CLAUDE_CONFIG_DIR")
    if value:
        return value
    return os.path.join(home, ".claude")


def get_state_dir(env):
    """Where the per-session edit counters live."""
    value = env.get("XDG_STATE_HOME")
    if value:
        return os.path.join(value, "steward")
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".local", "state", "steward")


def get_orchestration_dir(env):
    """Where the orchestration registry lives."""
    value = env.get("STEWARD_ORCHESTRATION_DIR")
    if value:
        return value
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".claude", "orchestration")


def get_plugin_root(env):
    """Root of the steward plugin checkout: STEWARD_PLUGIN_ROOT, else two
    directories up from this script (hooks/ is one level under the root)."""
    value = env.get("STEWARD_PLUGIN_ROOT")
    if value:
        return value
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
# session-start
# ---------------------------------------------------------------------------

REGISTRY_SKELETON = (
    "# Orchestration registry\n"
    "\n"
    "One primary per initiative, designated by the operator. The primary keeps "
    "its own entry current: it adds a secondary when it onboards one and "
    "removes it when the initiative ends. Every session reads this file to "
    "work out its role before applying the `steward:orchestrating` skill. "
    "Names are `ListAgents` names; the session id is the tie-breaker if a "
    "name is reused.\n"
    "\n"
    "| Initiative | Primary (ListAgents name, session id) | Secondaries "
    "(ListAgents name, repo) | Decision log | Since |\n"
    "|---|---|---|---|---|\n"
)


def strip_frontmatter(text):
    """Drop a leading YAML frontmatter block (---...---) if present."""
    if not text.startswith("---"):
        return text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n")
    return text


def _ensure_registry(env):
    orch_dir = get_orchestration_dir(env)
    path = os.path.join(orch_dir, "initiatives.md")
    if os.path.exists(path):
        return
    os.makedirs(orch_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(REGISTRY_SKELETON)


def _dependency_warnings(config_dir):
    warnings = []
    plainlanguage_path = os.path.join(config_dir, "skills", "plainlanguage", "SKILL.md")
    if not os.path.isfile(plainlanguage_path):
        warnings.append(
            "STEWARD WARNING: the plainlanguage skill is not installed at "
            + plainlanguage_path
            + ". The edict requires it for every reply, PR body and code "
            "comment. Tell the operator before writing prose."
        )
    # update-pr-summary is optional: the edict uses it when it is installed
    # and drafts PR bodies from the diff otherwise, so its absence is not
    # worth a warning.
    return warnings


def _pi_dependency_warnings(config_dir, env):
    """pi finds skills under its own config dir and under ~/.agents/skills."""
    warnings = []
    home = env.get("HOME") or os.path.expanduser("~")
    plainlanguage_paths = [
        os.path.join(config_dir, "skills", "plainlanguage", "SKILL.md"),
        os.path.join(home, ".agents", "skills", "plainlanguage", "SKILL.md"),
    ]
    if not any(os.path.isfile(p) for p in plainlanguage_paths):
        warnings.append(
            "STEWARD WARNING: the plainlanguage skill is not installed at "
            + " or ".join(plainlanguage_paths)
            + ". The edict requires it for every reply and PR body. Tell "
            "the operator before writing prose."
        )
    return warnings


def cmd_session_start(payload, env):
    harness = get_harness(env)
    plugin_root = get_plugin_root(env)
    if harness == "pi":
        skill_path = os.path.join(
            plugin_root, "pi", "skills", "steward-delegating", "SKILL.md")
    else:
        skill_path = os.path.join(plugin_root, "skills", "delegating", "SKILL.md")
    with open(skill_path, "r", encoding="utf-8") as f:
        raw = f.read()
    skill_body = strip_frontmatter(raw).strip("\n")

    config_dir = get_config_dir(env)

    if harness == "pi":
        # pi wraps the text in a <steward> system-prompt section itself, so
        # no tags here. The orchestration registry is not created: the
        # primary/secondary roles are not part of the pi port.
        warnings = _pi_dependency_warnings(config_dir, env)
        parts = [
            "You run under the steward delegation edict. The full text of "
            "the steward-delegating skill follows; read it as standing "
            "instructions.\n\n"
        ]
        if warnings:
            parts.append("\n".join(warnings) + "\n\n")
        parts.append(skill_body)
        text = "".join(parts)
    else:
        warnings = _dependency_warnings(config_dir)
        header = (
            "<STEWARD>\n"
            "You run under the steward delegation edict. The full text of the "
            "steward:delegating skill follows; read it as standing "
            "instructions.\n\n"
        )
        parts = [header]
        if warnings:
            parts.append("\n".join(warnings) + "\n")
        parts.append(skill_body)
        parts.append("\n</STEWARD>")
        text = "".join(parts)

        # The registry write is best-effort. An unwritable orchestration dir
        # must never cost us the session-start injection built above.
        try:
            _ensure_registry(env)
        except OSError:
            pass

    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    })


# ---------------------------------------------------------------------------
# gate: bash command classification
#
# One table, one place. Add a new family by adding a (name, rule) pair.
# Each rule is a callable command -> bool ("this command writes").
# ---------------------------------------------------------------------------

def _regex_rule(pattern, flags=0):
    compiled = re.compile(pattern, flags)

    def rule(command):
        return compiled.search(command) is not None

    return rule


# Quoted spans (single or double) are masked to a single placeholder char
# before any redirect/tee/etc. rule runs, so a ">" or "|" or "tee" that is
# just part of a quoted string (an argument to awk, psql, grep, git log
# --format, and so on) is never mistaken for real shell syntax. "Q" is not
# a space, so "cat > \"my file.txt\"" still reads as a real redirect.
_QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def _mask_quotes(command):
    return _QUOTED_SPAN_RE.sub("Q", command)


# A heredoc body (the lines between the opener and its terminator line)
# is excised before the generic rules run, so code inside it (like
# "if a > b:") is never mistaken for a real redirect. The opener's own
# line is kept, so a redirect written on that same line (as in
# "cat <<EOF > out.txt") still reads as a real redirect. The
# python-heredoc-write rule below looks at the raw, un-excised body.
_HEREDOC_BLOCK_RE = re.compile(
    r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)",
    re.DOTALL,
)


def _strip_one_heredoc_body(match):
    text = match.group(0)
    newline_at = text.find("\n")
    if newline_at == -1:
        return text
    return text[:newline_at] + "\nQ"


def _strip_heredoc_bodies(command):
    return _HEREDOC_BLOCK_RE.sub(_strip_one_heredoc_body, command)


def _clean_for_classification(command):
    """Quote-masked, heredoc-body-stripped text for the generic rules.
    The python-heredoc-write rule below uses the raw command instead,
    since it needs to read the real heredoc body."""
    return _mask_quotes(_strip_heredoc_bodies(command))


# Redirects that never count as a write: /dev/null targets and fd
# duplication (2>&1, 1>&2, &>/dev/null and friends). Stripped from a
# scratch copy before the generic write-redirect check runs, so the
# generic check never has to special-case them itself.
_SAFE_REDIRECT_RE = re.compile(
    r"&>\s*/dev/null"
    r"|\d*>>?\s*/dev/null"
    r"|\d+>&\d+"
)

# A real redirect to a file: single ">" not part of ">>", followed by a
# real-looking target (not another & | ; or whitespace); or a literal
# ">>" append, once the safe cases above are stripped out.
_WRITE_REDIRECT_RE = re.compile(r"(^|[^>])>(?!>)\s*[^&|;\s]")
_APPEND_RE = re.compile(r">>")


def _write_redirect_rule(command):
    cleaned = _SAFE_REDIRECT_RE.sub(" ", command)
    if _APPEND_RE.search(cleaned):
        return True
    return _WRITE_REDIRECT_RE.search(cleaned) is not None


# tee: anchored to a real command position (start of string, or right
# after a pipe/&&/;), and excludes device targets like /dev/stderr or
# /dev/null (writing there is not really a file write) as well as a
# bare input redirect with no output target at all (tee </dev/null).
_TEE_RE = re.compile(r"(^|\||&&|;)\s*tee\b(?!\s+(-\w+\s+)*(/dev/|<))")


def _tee_rule(command):
    return _TEE_RE.search(command) is not None


# git subcommands that mutate history or state, except the read-only or
# abort/undo flags that just cancel an in-progress operation.
_GIT_MUTATE_RE = re.compile(
    r"\bgit\s+(commit|push|merge|rebase|cherry-pick|am|apply)\b"
    r"(?!\s+--(abort|continue|quit|skip|check|dry-run)\b)"
)


def _git_mutate_rule(command):
    return _GIT_MUTATE_RE.search(command) is not None


# Indicators that a "python3 - <<HEREDOC" body actually writes to disk.
# A heredoc that only reads (json.load, print, and so on) is not a write.
#
# open(...) needs its own check: the mode string must be a short token
# made only of mode letters (r/w/a/x/b/t/+), otherwise a filename that
# happens to contain the letter "x" (like "f.txt") would false-match.
_OPEN_CALL_RE = re.compile(r"open\([^,)]*,\s*['\"]([rwaxbt+]{1,3})['\"]")

_PY_OTHER_WRITE_INDICATOR_RE = re.compile(
    r"\.write_text\("
    r"|\.write_bytes\("
    r"|\.write\("
    r"|\bshutil\."
    r"|\bos\.remove\("
    r"|\bos\.rename\("
    r"|\bos\.makedirs\("
    r"|\bos\.unlink\("
    r"|\.mkdir\("
)


def _has_write_mode_open(text):
    for m in _OPEN_CALL_RE.finditer(text):
        mode = m.group(1)
        if "w" in mode or "a" in mode or "x" in mode:
            return True
    return False


def _has_python_write_indicators(text):
    if _has_write_mode_open(text):
        return True
    return _PY_OTHER_WRITE_INDICATOR_RE.search(text) is not None


_PY_HEREDOC_OPENER_RE = re.compile(r"python3?\s+-\s*<<-?\s*(['\"]?)(\w+)\1")


def _python_heredoc_write_rule(command):
    m = _PY_HEREDOC_OPENER_RE.search(command)
    if not m:
        return False
    terminator = m.group(2)
    rest = command[m.end():]
    term_re = re.compile(r"^[ \t]*" + re.escape(terminator) + r"[ \t]*$", re.MULTILINE)
    tm = term_re.search(rest)
    body = rest[:tm.start()] if tm else rest
    return _has_python_write_indicators(body)


_HEREDOC_OPENER_RE = re.compile(r"<<-?\s*['\"]?\w+['\"]?")


def _heredoc_redirect_rule(command):
    if not _HEREDOC_OPENER_RE.search(command):
        return False
    return _write_redirect_rule(command)


# Each entry is (name, rule, uses_raw_text). Every rule except the
# python-heredoc one runs against the quote-masked, heredoc-stripped
# text; the python-heredoc rule needs the raw command so it can read the
# real heredoc body. Add a new family by adding one more tuple here.
BASH_WRITE_RULES = [
    ("redirect", _write_redirect_rule, False),
    ("tee", _tee_rule, False),
    ("sed-inplace", _regex_rule(r"\bsed\s+(-[a-zA-Z]*i|--in-place)"), False),
    ("perl-inplace", _regex_rule(r"\bperl\s+-[a-zA-Z]*i"), False),
    ("heredoc-redirect", _heredoc_redirect_rule, False),
    ("git-mutate", _git_mutate_rule, False),
    ("gh-pr-mutate", _regex_rule(r"\bgh\s+pr\s+(create|edit|merge)\b"), False),
    ("fs-verbs", _regex_rule(
        r"(^|&&|;|\|)\s*(mv|cp|rm|mkdir|touch|ln|chmod|chown|install)\b"
        r"|\bxargs\s+rm\b",
        re.MULTILINE,
    ), False),
    ("python-heredoc-write", _python_heredoc_write_rule, True),
    ("package-install", _regex_rule(
        r"\bnpm\s+(install|i|uninstall|update)\b"
        r"|\bpip3?\s+install\b"
        r"|\buv\s+(pip|add|remove)\b"
        r"|\bbrew\s+install\b",
        re.MULTILINE,
    ), False),
]


def classify_bash_command(command):
    """True if this Bash command is a direct write, by the rules above."""
    if not command:
        return False
    cleaned = _clean_for_classification(command)
    for _name, rule, uses_raw in BASH_WRITE_RULES:
        target = command if uses_raw else cleaned
        if rule(target):
            return True
    return False


# ---------------------------------------------------------------------------
# gate: allowlist
# ---------------------------------------------------------------------------

def default_allowlist_globs(env):
    config_dir = get_config_dir(env)
    home = env.get("HOME") or os.path.expanduser("~")
    pi_globs = []
    if get_harness(env) == "pi":
        # pi's counterparts of CLAUDE.md and a project's .claude directory.
        pi_globs = ["**/AGENTS.md", "**/.pi/**"]
    return pi_globs + [
        os.path.join(config_dir, "**"),
        os.path.join(home, ".claude", "**"),
        os.path.join(home, ".claude-profiles", "**"),
        "**/memory/**",
        "**/CLAUDE.md",
        "**/*decisions*.md",
        "/tmp/**",
        "/private/tmp/**",
        "**/.claude/**",
    ]


def extra_allowlist_globs(config_dir):
    path = os.path.join(config_dir, "steward", "allowlist")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def is_allowlisted(path, env, cwd=None):
    """A relative path is resolved against cwd (falling back to this
    process's own cwd) before matching, so "CLAUDE.md" or "memory/x.md"
    match the same globs an absolute path would."""
    if not path:
        return False
    config_dir = get_config_dir(env)
    globs = default_allowlist_globs(env) + extra_allowlist_globs(config_dir)
    candidate = _expand_user(path, env)
    if not os.path.isabs(candidate):
        base = cwd or os.getcwd()
        candidate = os.path.abspath(os.path.join(base, candidate))
    for pattern in globs:
        expanded_pattern = _expand_user(pattern, env)
        if fnmatch.fnmatch(candidate, expanded_pattern):
            return True
    return False


_TOKEN_RE = re.compile(r"\S+")

# A bare filename with an extension, like "CLAUDE.md", has no "/" and no
# leading "~" or ".", but is still a path worth checking against the
# allowlist.
_BARE_FILENAME_RE = re.compile(r"^[\w.-]+\.[\w-]+$")


def _path_like_tokens(command):
    tokens = []
    for raw in _TOKEN_RE.findall(command):
        token = raw.strip("'\"")
        if not token:
            continue
        if ("/" in token or token.startswith("~") or token.startswith(".")
                or _BARE_FILENAME_RE.match(token)):
            tokens.append(token)
    return tokens


def bash_command_allowlisted(command, env, cwd=None):
    """A Bash command is exempt only if every path-looking token in it is
    allowlisted, and there is at least one such token. A command that
    touches one allowlisted path and one real path still counts."""
    tokens = _path_like_tokens(command)
    if not tokens:
        return False
    return all(is_allowlisted(t, env, cwd) for t in tokens)


# ---------------------------------------------------------------------------
# gate: tool classification and state
# ---------------------------------------------------------------------------

# pi's built-in edit and write tools take the target in "path".
_PI_EDIT_TOOLS = ("edit", "write")

# Claude Code names first, then pi's.
_DIRECT_EDIT_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit") + _PI_EDIT_TOOLS

# Claude Code calls its shell tool Bash; pi calls it bash.
_BASH_TOOLS = ("Bash", "bash")


def direct_edit_file_path(tool_name, tool_input):
    # Read only the field the tool actually writes to, so an extra argument
    # naming an allowlisted path cannot exempt a real write.
    if tool_name in _PI_EDIT_TOOLS:
        return tool_input.get("path")
    path = tool_input.get("file_path")
    if path:
        return path
    if tool_name == "NotebookEdit":
        return tool_input.get("notebook_path")
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if isinstance(edits, list) and edits:
            first = edits[0]
            if isinstance(first, dict):
                return first.get("file_path")
    return None


def classify_tool_call(tool_name, tool_input, env, cwd=None):
    """Returns (is_direct_edit, is_allowlisted)."""
    if tool_name in _DIRECT_EDIT_TOOLS:
        path = direct_edit_file_path(tool_name, tool_input)
        if not path:
            return True, False
        return True, is_allowlisted(path, env, cwd)
    if tool_name in _BASH_TOOLS:
        command = tool_input.get("command")
        if not isinstance(command, str):
            command = ""
        if not classify_bash_command(command):
            return False, False
        return True, bash_command_allowlisted(command, env, cwd)
    return False, False


# A session id is used as a filename. Keep only safe characters so a
# crafted session id can never point outside the state directory.
_SESSION_ID_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")
_MAX_SESSION_ID_LEN = 200


def _sanitize_session_id(session_id):
    cleaned = _SESSION_ID_UNSAFE_RE.sub("_", session_id)
    return cleaned[:_MAX_SESSION_ID_LEN]


def _state_path(state_dir, session_id):
    return os.path.join(state_dir, _sanitize_session_id(session_id) + ".json")


def _atomic_write_json(path, data):
    """Write via a temp file plus os.replace, so a reader never sees a
    half-written file."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".steward-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _acquire_state_lock(path):
    """An advisory lock on a sidecar file, POSIX only. Returns None (no
    lock) on any platform or error where locking is not available; the
    caller then just falls back to unlocked read-modify-write."""
    if fcntl is None:
        return None
    lock_path = path + ".lock"
    try:
        lock_file = open(lock_path, "a+")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return lock_file
    except OSError:
        return None


def _release_state_lock(lock_file):
    if lock_file is None:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lock_file.close()
    except OSError:
        pass


def _bump_counter(state_dir, session_id):
    os.makedirs(state_dir, exist_ok=True)
    path = _state_path(state_dir, session_id)
    lock_file = _acquire_state_lock(path)
    try:
        now = time.time()
        count = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = int(data.get("count", 0))
            last = float(data.get("last", 0))
            if now - last > 600:
                count = 0
        except (OSError, ValueError, TypeError):
            count = 0
        count += 1
        _atomic_write_json(path, {"count": count, "last": now})
        return count
    finally:
        _release_state_lock(lock_file)


def _reset_counter(state_dir, session_id):
    os.makedirs(state_dir, exist_ok=True)
    path = _state_path(state_dir, session_id)
    lock_file = _acquire_state_lock(path)
    try:
        _atomic_write_json(path, {"count": 0, "last": time.time()})
    finally:
        _release_state_lock(lock_file)


# ---------------------------------------------------------------------------
# gate: runtime mode (file first, then env, then default hard)
# ---------------------------------------------------------------------------

_VALID_MODES = ("off", "soft", "hard")


def _read_gate_mode_file(config_dir):
    path = os.path.join(config_dir, "steward", "gate")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip().lower()
    except OSError:
        return None
    if value in _VALID_MODES:
        return value
    return None


def get_gate_mode(env):
    config_dir = get_config_dir(env)
    file_mode = _read_gate_mode_file(config_dir)
    if file_mode:
        return file_mode
    env_mode = (env.get("STEWARD_GATE") or "").strip().lower()
    if env_mode in _VALID_MODES:
        return env_mode
    return "hard"


def gate_message(count, config_dir, harness="claude"):
    gate_path = os.path.join(config_dir, "steward", "gate")
    if harness == "pi":
        return (
            "steward delegation gate: this is direct edit #{n} on the main "
            "thread with no subagent call in between. The edict says every "
            "non-trivial task runs in a subagent. Delegate it with the "
            "subagent tool (agent steward.coder-opus-medium for code, "
            "steward.mechanic-sonnet-low for rote edits), or ask the operator "
            "to set the gate to soft or off by writing that word to "
            "{gate_path} (takes effect immediately; STEWARD_GATE only "
            "applies at next start)."
        ).format(n=count, gate_path=gate_path)
    return (
        "steward delegation gate: this is direct edit #{n} on the main "
        "thread with no subagent call in between. The edict says every "
        "non-trivial task runs in a subagent (steward:coder-opus-medium "
        "for code, steward:mechanic-sonnet-low for rote edits). Delegate it, or "
        "ask the operator to set the gate to soft or off by writing that "
        "word to {gate_path} (takes effect immediately; STEWARD_GATE only "
        "applies at next start)."
    ).format(n=count, gate_path=gate_path)


# ---------------------------------------------------------------------------
# AI-tell markers, shared by the PR gate and the prose gate
# ---------------------------------------------------------------------------

MARKERS = [
    "delve", "delves", "delving",
    "leverage", "leverages", "leveraging",
    "crucial", "pivotal", "tapestry", "landscape", "vibrant",
    "showcase", "showcases", "intricate", "testament",
    "underscore", "underscores", "underscoring",
    "it's important to note", "it is important to note",
    "it's worth noting", "in summary", "in conclusion",
    "great question", "i hope this helps",
    "stands as", "serves as", "plays a vital role",
    "certainly!", "let me know if",
]


def _compile_marker(marker):
    pattern = r"\b" + re.escape(marker)
    last = marker[-1]
    if last.isalnum() or last == "_":
        pattern += r"\b"
    return re.compile(pattern, re.IGNORECASE)


_MARKER_PATTERNS = [(m, _compile_marker(m)) for m in MARKERS]


def load_operator_patterns(config_dir):
    """The operator's own banned phrases, from <config>/steward/prose-patterns:
    one case-insensitive regular expression per line, # starts a comment,
    blank lines are skipped, and a line that does not compile is ignored.
    ^ and $ match at line boundaries. A missing file means no patterns."""
    path = os.path.join(config_dir, "steward", "prose-patterns")
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
# gate: the "gh pr create|edit" PR-body check
# ---------------------------------------------------------------------------

_GH_PR_CREATE_EDIT_RE = re.compile(r"\bgh\s+pr\s+(create|edit)\b")
_BODY_FILE_RE = re.compile(r"(?:--body-file|-F)\s+(\S+)")

PR_EMDASH_MSG = (
    "steward PR gate: the PR body contains an em-dash. The operator's rule "
    "is zero em-dashes. Redraft it from the branch's diff with the "
    "plainlanguage skill, show the operator, then retry."
)

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
    if cleaned.count(EM_DASH) > 0:
        return PR_EMDASH_MSG
    _hits, names = find_markers(cleaned)
    if len(names) >= 2:
        return PR_MARKER_MSG_TEMPLATE.format(markers=", ".join(names))
    phrases = find_operator_hits(cleaned, operator_patterns)
    if phrases:
        return PR_OPERATOR_MSG_TEMPLATE.format(phrases=", ".join(phrases))
    return None


# ---------------------------------------------------------------------------
# gate subcommand
# ---------------------------------------------------------------------------

def cmd_gate(payload, env):
    if _non_empty_str(payload.get("agent_id")):
        return None

    mode = get_gate_mode(env)
    if mode == "off":
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
            command, cwd, load_operator_patterns(get_config_dir(env)))
        if violation:
            return json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": violation,
                }
            })

    is_edit, allowlisted = classify_tool_call(tool_name, tool_input, env, cwd)
    if not is_edit or allowlisted:
        return None

    session_id = payload.get("session_id")
    if not _non_empty_str(session_id):
        session_id = "unknown"
    state_dir = get_state_dir(env)
    count = _bump_counter(state_dir, session_id)
    if count <= 1:
        return None

    config_dir = get_config_dir(env)
    msg = gate_message(count, config_dir, get_harness(env))
    if mode == "hard":
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": msg,
            }
        })
    if mode == "soft":
        # No permissionDecision here: "allow" would skip the permission
        # prompt outright. Soft mode is only a reminder, so it carries
        # nothing but additionalContext.
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": msg,
            }
        })
    return None


# ---------------------------------------------------------------------------
# delegated subcommand
# ---------------------------------------------------------------------------

def cmd_delegated(payload, env):
    if _non_empty_str(payload.get("agent_id")):
        return None
    session_id = payload.get("session_id")
    if not _non_empty_str(session_id):
        session_id = "unknown"
    state_dir = get_state_dir(env)
    _reset_counter(state_dir, session_id)
    return None


# ---------------------------------------------------------------------------
# prose-gate subcommand
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

_MAX_TAIL_BYTES = 2 * 1024 * 1024


def _clean_text(text):
    text = _FENCED_CODE_RE.sub(" ", text)
    text = _UNTERMINATED_FENCE_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _PATH_LIKE_TOKEN_RE.sub(" ", text)
    return text


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


PROSE_MSG_TEMPLATE = (
    "steward prose gate: your last reply has {n} em-dash(es) and these AI "
    "tells: {markers}. The operator's rule is zero em-dashes and plain "
    "language. Revise the reply with the plainlanguage skill and send it "
    "again."
)


PROSE_OPERATOR_MSG_TEMPLATE = (
    "steward prose gate: your last reply has {found}. The operator's rule "
    "is plain language with zero em-dashes. Revise the reply with the "
    "plainlanguage skill and send it again."
)


def cmd_prose_gate(payload, env):
    if payload.get("stop_hook_active") is True:
        return None
    if _non_empty_str(payload.get("agent_id")):
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
    em_dash_count = cleaned.count(EM_DASH)
    _hits, names = find_markers(cleaned)
    phrases = find_operator_hits(cleaned, load_operator_patterns(get_config_dir(env)))

    # The threshold counts distinct markers, not raw occurrences: the
    # same marker twice is still only one kind of tell. An operator
    # phrase blocks on its own.
    if em_dash_count <= 0 and len(names) < 2 and not phrases:
        return None

    if not phrases:
        reason = PROSE_MSG_TEMPLATE.format(n=em_dash_count, markers=", ".join(names))
    else:
        found = ["phrases the operator bans: " + ", ".join(phrases)]
        if em_dash_count > 0:
            found.append("{n} em-dash(es)".format(n=em_dash_count))
        if names:
            found.append("these AI tells: " + ", ".join(names))
        reason = PROSE_OPERATOR_MSG_TEMPLATE.format(found="; ".join(found))
    return json.dumps({"decision": "block", "reason": reason})


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def _dispatch(argv, stdin_text, env):
    try:
        payload = json.loads(stdin_text) if stdin_text and stdin_text.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    if len(argv) < 2:
        return None
    subcommand = argv[1]

    if subcommand == "session-start":
        return cmd_session_start(payload, env)
    if subcommand == "gate":
        return cmd_gate(payload, env)
    if subcommand == "delegated":
        return cmd_delegated(payload, env)
    if subcommand == "prose-gate":
        return cmd_prose_gate(payload, env)
    return None


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
