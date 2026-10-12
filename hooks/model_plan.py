"""Steward model plan core for pi (Phase 2a of docs/roadmap/pi-model-plan.md).

Pure Python, standard library only. It reads files and never writes any.
The hook imports it only for harness pi; nothing here renders text (2b).

Inputs
------
1. Registry facts gathered by the pi extension (2c), this shape::

    { "main": {"provider": str, "id": str, "thinkingLevel": str} | null,
      "models": [{"provider": str, "id": str, "available": bool,
                  "thinkingLevels": [str, ...], "maxTokens": int, ...}],
      "projectTrusted": bool, "cwd": str }

   ``available`` means the model is in pi's registry and its provider has
   configured auth. ``thinkingLevels`` is pi-ai's
   ``getSupportedThinkingLevels(model)``. ``provider``, ``id`` and
   ``available`` are required per entry; an entry without them is skipped
   with a ``facts-bad-model`` finding. ``thinkingLevels`` and ``maxTokens``
   are optional: without them the clamp and output-size checks are skipped
   for that model. Other keys are ignored. A ``provider/id`` missing from
   ``models`` is not in the catalog.

2. Files, read only:
   - user plan ``<agent-dir>/steward/model-plan.json``;
   - project plan ``<project>/.pi/steward-model-plan.json`` (trusted only);
     every ``.pi/steward-model-plan.json`` from cwd up to home adds its
     ``allowProviders`` and ``denyProviders`` (see ``project_plan_files``);
   - user pi settings ``<agent-dir>/settings.json``;
   - project pi settings ``<project>/.pi/settings.json`` (trusted only);
   - pi-subagents config ``<agent-dir>/extensions/subagent/config.json``;
   - profile frontmatter ``pi/agents/<role>.md`` in this package;
   - when allow/deny lists are active, the user and project agent
     directories pi-subagents scans, for agents that shadow ``steward.*``.
   ``<agent-dir>`` is ``$PI_CODING_AGENT_DIR`` or ``~/.pi/agent``.

Output
------
``evaluate(facts, env)`` never raises. It returns a JSON-safe dict::

    { "hasPlan": bool,
      "planFiles": {"user": path|None, "project": path|None, "lists": [path, ...]},
      "settingsFiles": {"user": path|None, "project": path|None},
      "main": None | {"model", "provider", "id", "thinkingLevel", "inPlan",
                      "expectedThinking", "judgmentGrade", "family",
                      "startupThinking": {"level", "requested", "key", "source"},
                      "inheritedBy": [role, ...]},
      "roles": { role: {
          "runtimeName": "steward.<role>",
          "plan": None | {"setting", "model", "thinking", "inheritsMain",
                          "source", "thinkingSource", "byMainProvider",
                          "fromFallback", "available", "clampedTo",
                          "judgmentGrade", "family"},
          "effective": {"model", "requested", "exact", "thinking",
                        "inheritsMain", "available",
                        "modelSource": {"file", "key"},
                        "thinkingSource": {"file", "key"},
                        "clampedTo", "judgmentGrade", "family"},
          "relaunch": None | {"model", "thinking", "launch"},
          "escalate": None | {"model", "thinking", "launch", "inheritsMain"},
          "judgmentGrade": bool|None, "family": str|None } },
      "providers": {provider: {"maxConcurrent"?, "enabled"?}},
      "allowProviders": [...], "denyProviders": [...],
      "concurrency": {"parallel": int, "global": int, "source": path|None},
      "findings": [{"severity": "error"|"warn"|"info", "code", "role",
                    "message", "source", "subject"}] }

``plan.setting`` is what Phase 3 ``apply`` would write as the model
(``"inherit"`` for ``main``). ``plan.source`` and ``effective.modelSource``
name the file that won. ``effective.requested`` is the settings or
frontmatter model string (without a ``:level`` suffix), ``effective.model``
what pi-subagents resolves it to, and ``effective.exact`` whether the string
is already an exact, available ``provider/id``. The row-level
``judgmentGrade`` and ``family`` describe the effective binding, the one that
will launch. ``finding.subject`` names the binding a finding is about
(``"plan binding"``, ``"effective binding"``, ``"relaunch model"``,
``"escalation model"``, ``"latent binding"``) or is ``None``.

When facts are malformed, or anything unexpected goes wrong, the result has
empty roles and a single ``facts-invalid`` or ``internal-error`` finding, so
session start can fail open.

Sources mirrored (pi 1.1.0 at PI=.../releases/1.1.0/node_modules, and
pi-subagents 0.77.0 at PS=~/.pi/agent/npm/node_modules/pi-subagents) are
cited beside the code that mirrors them.
"""

import json
import os
import re
from pathlib import Path

ROLES = ("coder", "deep-reasoner", "reviewer", "researcher", "writer", "mechanic", "top-reviewer")
JUDGMENT_ROLES = ("deep-reasoner", "top-reviewer")
LARGE_OUTPUT_ROLES = ("coder", "writer")
# pi-ai EXTENDED_THINKING_LEVELS order (PI/@earendil-works/pi-ai/dist/models.js:678).
THINKING_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
# pi's DEFAULT_THINKING_LEVEL (PI/@earendil-works/pi-coding-agent/dist/core/defaults.js:1).
PI_DEFAULT_THINKING = "medium"
# "32K" in the plan spec; 32,000 so a vendor's 32,000-token cap does not warn.
MIN_OUTPUT_TOKENS = 32000
# pi-subagents defaults (PS/docs/configuration.md "parallel" and "globalConcurrencyLimit").
DEFAULT_PARALLEL_CONCURRENCY = 4
DEFAULT_GLOBAL_CONCURRENCY = 20

PLAN_FILE = "steward-model-plan.json"
# A provider id as written in allowProviders/denyProviders, before normalising.
PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Old runtime names. pi-subagents config keys use canonical names only
# (PS/docs/agents.md:417), so overrides under these keys no longer apply.
STALE_KEYS = {
    "steward.coder-opus-medium": "coder",
    "steward.deep-reasoner-opus-xhigh": "deep-reasoner",
    "steward.reviewer-sonnet-high": "reviewer",
    "steward.researcher-sonnet-low": "researcher",
    "steward.writer-sonnet-medium": "writer",
    "steward.mechanic-haiku-medium": "mechanic",
    "steward.reviewer-opus-max": "top-reviewer",
    "steward.reviewer-fable-xhigh": "top-reviewer",
}

BUILTIN_FAMILIES = (
    ("claude", ("*claude*",)),
    ("gpt", ("*gpt-*",)),
    ("deepseek", ("*deepseek*",)),
    ("kimi", ("*kimi*",)),
    ("glm", ("*glm*",)),
    ("qwen", ("*qwen*",)),
    ("gemma", ("*gemma*",)),
    ("minimax", ("*minimax*",)),
)

TOP_FIELDS = {"version", "main", "judgmentModels", "providers", "roles", "families",
              "allowProviders", "denyProviders"}
PROJECT_ONLY_FIELDS = ("allowProviders", "denyProviders")
MAIN_FIELDS = {"models", "thinking"}
PROVIDER_FIELDS = {"maxConcurrent", "enabled"}
ROLE_FIELDS = {"model", "thinking", "fallback", "escalate", "byMainProvider"}
BY_MAIN_FIELDS = {"model", "thinking"}

DEFAULT_AGENTS_DIR = Path(__file__).resolve().parent.parent / "pi" / "agents"

# Agent discovery (PS/src/agents/agents.js:1611-1621,1688-1758).
DISCOVERY_PRUNED_DIR_NAMES = {".git", "node_modules", ".pi", "sync-backups"}
MAX_DISCOVERY_FILES = 5000


# ---------------------------------------------------------------- helpers

def clamp_thinking(level, supported):
    """Mirror pi-ai clampThinkingLevel (PI/@earendil-works/pi-ai/dist/models.js:691-709):
    keep a supported level, else search upward, then downward."""
    supported = list(supported or [])
    if level in supported:
        return level
    if level not in THINKING_LEVELS:
        return supported[0] if supported else "off"
    index = THINKING_LEVELS.index(level)
    for candidate in THINKING_LEVELS[index:]:
        if candidate in supported:
            return candidate
    for candidate in reversed(THINKING_LEVELS[:index]):
        if candidate in supported:
            return candidate
    return supported[0] if supported else "off"


def glob_match(text, pattern):
    """Only `*` is special, case-insensitive, whole string. Mirrors
    pi-subagents globToRegExp (PS/src/runs/shared/model-scope.js:22-25)."""
    regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return re.match(regex, text, re.IGNORECASE) is not None


def split_level(text):
    """Split a known `:level` suffix, as pi-subagents applyThinkingSuffix does
    (PS/src/runs/shared/child-tool-plan.js:48-57). An unknown suffix stays
    part of the id."""
    base, sep, tail = text.rpartition(":")
    if sep and tail in THINKING_LEVELS and base:
        return base, tail
    return text, None


def normalize_segment(text):
    """pi-subagents normalizeModelSegment (PS/src/runs/shared/model-resolution.js:70-76):
    case-fold, dots and underscores to dashes, collapse and trim dashes."""
    text = re.sub(r"[._]+", "-", text.lower())
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _plausible_date(year, month, day):
    return 1900 <= int(year) <= 2099 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31


def _strip_date(segment):
    """stripTrailingDateStamp (model-resolution.js:84-93)."""
    match = re.fullmatch(r"(.*)-(\d{4})-(\d{2})-(\d{2})", segment)
    if match and _plausible_date(*match.groups()[1:]):
        return match.group(1)
    match = re.fullmatch(r"(.*)-(\d{4})(\d{2})(\d{2})", segment)
    if match and _plausible_date(*match.groups()[1:]):
        return match.group(1)
    return segment


def _full(entry):
    return "%s/%s" % (entry["provider"], entry["id"])


def _registered(provider, available):
    norm = normalize_segment(provider)
    return any(normalize_segment(entry["provider"]) == norm for entry in available)


def _split_qualified(base, available):
    """splitQualifiedModelQuery (model-resolution.js:103-122): a `/`, `:` or
    `.` prefix is a provider only when it names a registered provider."""
    index = base.find("/")
    if index != -1:
        part = base[:index]
        if _registered(part, available):
            return normalize_segment(part), base[index + 1:]
        return None, base
    for separator in (":", "."):
        index = base.find(separator)
        if index <= 0:
            continue
        part = base[:index]
        if _registered(part, available):
            return normalize_segment(part), base[index + 1:]
    return None, base


def _fuzzy_resolve(base, available, preferred):
    """fuzzyResolveModel (model-resolution.js:166-185)."""
    query_provider, raw_id = _split_qualified(base, available)
    query_id = normalize_segment(raw_id)
    query_no_date = _strip_date(query_id)
    candidates = []
    for entry in available:
        entry_id = normalize_segment(entry["id"])
        if entry_id != query_id and _strip_date(entry_id) != query_no_date:
            continue
        if query_provider is not None and normalize_segment(entry["provider"]) != query_provider:
            continue
        candidates.append(entry)
    if not candidates:
        return None
    if preferred:
        norm = normalize_segment(preferred)
        for entry in candidates:
            if normalize_segment(entry["provider"]) == norm:
                return _full(entry)
    return _full(candidates[0]) if len(candidates) == 1 else None


def _resolve_base(base, available, preferred):
    """resolveBaseModelCandidate (model-resolution.js:134-151)."""
    for entry in available:
        if _full(entry) == base:
            return base
    query_provider, _ = _split_qualified(base, available)
    if query_provider is None:
        exact = [entry for entry in available if entry["id"] == base]
        if preferred:
            for entry in exact:
                if entry["provider"] == preferred:
                    return _full(entry)
        if len(exact) == 1:
            return _full(exact[0])
    fuzzy = _fuzzy_resolve(base, available, preferred)
    if fuzzy or query_provider is None:
        return fuzzy
    query_id = normalize_segment(base)
    matches = [entry for entry in available if normalize_segment(entry["id"]) == query_id
               and normalize_segment(entry["provider"]) == query_provider]
    return _full(matches[0]) if len(matches) == 1 else None


def resolve_subagent_model(model, available, preferred):
    """resolveSubagentModelCandidate (model-resolution.js:212-220), matching
    only `getAvailable()` models (PS/src/runs/foreground/subagent-executor.js:1039).
    Returns the resolved `provider/id[:level]`, or None when pi-subagents
    would pass the raw string through to the child."""
    if not available:
        return model
    whole = _resolve_base(model, available, preferred)
    if whole:
        return whole
    base, level = split_level(model)
    if level:
        resolved = _resolve_base(base, available, preferred)
        if resolved:
            return "%s:%s" % (resolved, level)
    return None


def agent_dir_from_env(env):
    """$PI_CODING_AGENT_DIR or ~/.pi/agent. Same result as
    steward_hook.get_config_dir for harness pi (hooks/steward_hook.py:42-62)
    and pi-subagents getAgentDir (PS/src/shared/utils.js:80-87). Inlined so
    steward_hook can import this module without a cycle."""
    home = env.get("HOME") or os.path.expanduser("~")
    value = env.get("PI_CODING_AGENT_DIR")
    if value:
        if value == "~":
            return home
        if value.startswith("~/") or value.startswith("~\\"):
            return os.path.join(home, value[2:])
        return value
    return os.path.join(home, ".pi", "agent")


def _home_dirs(env):
    homes = set()
    for value in (env.get("HOME"), env.get("USERPROFILE"), os.path.expanduser("~")):
        if value and os.path.isdir(value):
            homes.add(os.path.realpath(value))
    return homes


def _walk_up(cwd, env):
    """Directories from cwd upward; the home directory ends the walk and is
    not included (PS/src/agents/agents.js:573-652)."""
    homes = _home_dirs(env)
    current = os.path.abspath(cwd)
    while True:
        if os.path.isdir(current) and os.path.realpath(current) in homes:
            return
        yield current
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def find_project_root(cwd, env):
    """Mirror pi-subagents findConfiguredProjectRoot
    (PS/src/agents/agents.js:573-652): walk up from cwd; a directory with
    `.pi` or `.agents` is a candidate; the home directory is never a project
    and ends the walk; `subagents.projectRootResolution` ("nearest" or
    "git-root") in a candidate's .pi/settings.json picks between them."""
    candidates = [d for d in _walk_up(cwd, env)
                  if os.path.isdir(os.path.join(d, ".pi")) or os.path.isdir(os.path.join(d, ".agents"))]
    if not candidates:
        return None
    nearest = candidates[0]
    policy_root, policy_index = None, -1
    for index, candidate in enumerate(candidates):
        data, _ = _read_json(os.path.join(candidate, ".pi", "settings.json"))
        sub = data.get("subagents") if isinstance(data, dict) else None
        mode = sub.get("projectRootResolution") if isinstance(sub, dict) else None
        if mode == "nearest":
            return nearest
        if mode == "git-root":
            policy_root, policy_index = candidate, index
            break
    if policy_root is None:
        return nearest
    git_root = None
    current = os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            git_root = current
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if git_root:
        for candidate in candidates[policy_index:]:
            if os.path.abspath(candidate) == os.path.abspath(git_root):
                return candidate
    if os.path.exists(os.path.join(policy_root, ".git")):
        return policy_root
    return nearest


def project_plan_files(cwd, env, trusted, project_root):
    """Every project plan this session reads, as (root_plan, list_plans).

    Trust gating of project plans is decided here and only here. The plan at
    the project root (found as pi-subagents finds it) contributes every field.
    Each `.pi/steward-model-plan.json` on the walk from cwd up to, not
    including, home contributes its allowProviders and denyProviders: a
    nested `.pi` directory (a vendored package) must not hide the repo's
    restrictions. An untrusted project contributes nothing."""
    if not trusted:
        return None, []
    root_plan = os.path.join(project_root, ".pi", PLAN_FILE) if project_root else None
    lists = []
    for directory in _walk_up(cwd, env):
        path = os.path.join(directory, ".pi", PLAN_FILE)
        if os.path.isfile(path):
            lists.append(path)
    if root_plan and os.path.isfile(root_plan) and root_plan not in lists:
        lists.append(root_plan)
    return root_plan, lists


def _read_json(path):
    """(data, error). Missing file gives (None, None)."""
    if not path or not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError, RecursionError) as exc:
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:200])


def read_frontmatter(path):
    """Flat `key: value` frontmatter of a pi agent file."""
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return out
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if not sep or line[:1].isspace():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def validate_facts(facts):
    """Raise ValueError unless the top level of facts matches the contract.
    Model entries are checked one by one in _clean_models."""
    if not isinstance(facts, dict):
        raise ValueError("facts must be an object")
    for key in ("main", "models", "projectTrusted", "cwd"):
        if key not in facts:
            raise ValueError("facts missing %r" % key)
    main = facts["main"]
    if main is not None:
        if not isinstance(main, dict) or not all(isinstance(main.get(k), str) and main.get(k)
                                                 for k in ("provider", "id", "thinkingLevel")):
            raise ValueError("facts.main must be null or {provider, id, thinkingLevel}")
    if not isinstance(facts["models"], list):
        raise ValueError("facts.models must be a list")
    if not isinstance(facts["projectTrusted"], bool):
        raise ValueError("facts.projectTrusted must be a boolean")
    if not isinstance(facts["cwd"], str) or not facts["cwd"]:
        raise ValueError("facts.cwd must be a non-empty string")


def _clean_models(models, findings):
    """Keep the model entries usable by the checks; skip the rest with a finding."""
    out = []
    for index, entry in enumerate(models):
        if not (isinstance(entry, dict) and isinstance(entry.get("provider"), str) and entry["provider"]
                and isinstance(entry.get("id"), str) and entry["id"]
                and isinstance(entry.get("available"), bool)):
            findings.add("warn", "facts-bad-model", None,
                         "facts.models entry %d lacks provider, id or available; it is skipped." % index)
            continue
        levels = entry.get("thinkingLevels")
        if not (isinstance(levels, list) and all(isinstance(level, str) for level in levels)):
            levels = None
        max_tokens = entry.get("maxTokens")
        if type(max_tokens) is not int or max_tokens <= 0:
            max_tokens = None
        out.append({"provider": entry["provider"], "id": entry["id"], "available": entry["available"],
                    "thinkingLevels": levels, "maxTokens": max_tokens})
    return out


class _Findings:
    def __init__(self):
        self.items = []
        self._seen = set()

    def add(self, severity, code, role, message, source=None, subject=None):
        key = (severity, code, role, message, subject)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append({"severity": severity, "code": code, "role": role,
                           "message": message, "source": source, "subject": subject})


def _empty_result(findings):
    return {"hasPlan": False, "planFiles": {"user": None, "project": None, "lists": []},
            "settingsFiles": {"user": None, "project": None}, "main": None, "roles": {},
            "providers": {}, "allowProviders": [], "denyProviders": [],
            "concurrency": {"parallel": DEFAULT_PARALLEL_CONCURRENCY, "global": DEFAULT_GLOBAL_CONCURRENCY,
                            "source": None},
            "findings": findings}


# ---------------------------------------------------------------- plan schema

def parse_ref(text, allow_main, allow_level):
    """Parse `provider/id[:level]` or `main[:level]`.
    Returns (ref, error_code); ref = {"main", "model", "thinking"}."""
    if not isinstance(text, str) or not text.strip():
        return None, "plan-bad-value"
    text = text.strip()
    if any(ch.isspace() for ch in text):
        return None, "plan-bad-value"
    base, level = split_level(text)
    if level and not allow_level:
        return None, "plan-level-in-model"
    if base == "main":
        if not allow_main:
            return None, "plan-bad-value"
        return {"main": True, "model": None, "thinking": level}, None
    provider, sep, mid = base.partition("/")
    if not sep or not provider or not mid:
        return None, "plan-bare-id"
    return {"main": False, "model": base, "thinking": level}, None


def parse_escalate(value):
    """The escalation target of a role: `main[:level]` or `provider/id[:level]`.
    `null` is an explicit unset. Returns (ref_or_None, error_code). New
    target kinds belong here."""
    if value is None:
        return None, None
    return parse_ref(value, True, True)


def parse_plan(data, source, project):
    """Validate one plan file. Returns (plan, findings_list). Invalid entries
    are dropped with an error finding; a file with a bad version is dropped.
    `null` for a role's model, thinking or escalate (and `null` or `[]` for
    fallback) is kept as an explicit unset that wins in the merge."""
    found = []

    def err(code, message, role=None):
        found.append({"severity": "error", "code": code, "role": role, "message": message,
                      "source": source, "subject": None})

    if not isinstance(data, dict):
        err("plan-bad-value", "The model plan must be a JSON object.")
        return None, found
    version = data.get("version")
    if type(version) is not int or version != 1:
        err("plan-bad-version", "The model plan needs \"version\": 1; the file is ignored.")
        return None, found
    plan = {}
    for key in data:
        if key not in TOP_FIELDS:
            err("plan-unknown-field", "Unknown top-level field %r." % key)
        elif key in PROJECT_ONLY_FIELDS and not project:
            err("plan-project-only-field", "%r is allowed only in a project plan (.pi/steward-model-plan.json); ignored." % key)

    def ref_message(code, where, value):
        if code == "plan-bare-id":
            return "%s %r is a bare id; write provider/id so it does not change meaning when the main provider changes." % (where, value)
        if code == "plan-level-in-model":
            return "%s %r carries a :level suffix; put the level in \"thinking\"." % (where, value)
        return "%s has an invalid value." % where

    def thinking_ok(value, where, role=None):
        if value in THINKING_LEVELS:
            return True
        err("plan-bad-thinking", "%s is not a thinking level (%s)." % (where, ", ".join(THINKING_LEVELS)), role)
        return False

    def str_list(value, where):
        if isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value):
            return [v.strip() for v in value]
        err("plan-bad-value", "%s must be a list of non-empty strings." % where)
        return None

    def provider_list(value, where):
        if not isinstance(value, list):
            err("plan-bad-value", "%s must be a list of provider ids." % where)
            return None
        out = []
        for index, item in enumerate(value):
            if isinstance(item, str) and PROVIDER_ID_RE.match(item.strip()):
                norm = normalize_segment(item.strip())
                if norm and norm not in out:
                    out.append(norm)
            else:
                err("plan-bad-value", "%s entry %d is not a provider id; it is ignored." % (where, index + 1))
        return out

    main = data.get("main")
    if main is not None:
        if not isinstance(main, dict):
            err("plan-bad-value", "\"main\" must be an object.")
        else:
            out = {}
            for key, value in main.items():
                if key not in MAIN_FIELDS:
                    err("plan-unknown-field", "Unknown field %r in \"main\"." % key)
                elif key == "models":
                    items = str_list(value, "main.models")
                    if items is not None:
                        good = []
                        for item in items:
                            ref, code = parse_ref(item, False, False)
                            if code:
                                err(code, ref_message(code, "main.models entry", item))
                            else:
                                good.append(ref["model"])
                        out["models"] = good
                elif key == "thinking" and thinking_ok(value, "main.thinking"):
                    out["thinking"] = value
            plan["main"] = out

    if "judgmentModels" in data:
        items = str_list(data["judgmentModels"], "judgmentModels")
        if items is not None:
            plan["judgmentModels"] = items

    providers = data.get("providers")
    if providers is not None:
        if not isinstance(providers, dict):
            err("plan-bad-value", "\"providers\" must be an object keyed by provider.")
        else:
            plan["providers"] = {}
            for name, value in providers.items():
                if not isinstance(value, dict):
                    err("plan-bad-value", "providers.%s must be an object." % name)
                    continue
                entry = {}
                for key, field in value.items():
                    if key not in PROVIDER_FIELDS:
                        err("plan-unknown-field", "Unknown field %r in providers.%s." % (key, name))
                    elif key == "maxConcurrent":
                        if type(field) is int and field > 0:
                            entry[key] = field
                        else:
                            err("plan-bad-value", "providers.%s.maxConcurrent must be a positive integer." % name)
                    elif key == "enabled":
                        if isinstance(field, bool):
                            entry[key] = field
                        else:
                            err("plan-bad-value", "providers.%s.enabled must be true or false." % name)
                plan["providers"][name] = entry

    families = data.get("families")
    if families is not None:
        if not isinstance(families, dict):
            err("plan-bad-value", "\"families\" must be an object of name to glob or globs.")
        else:
            plan["families"] = {}
            for name, value in families.items():
                globs = [value] if isinstance(value, str) else value
                items = str_list(globs, "families.%s" % name)
                if items:
                    plan["families"][name] = items

    if project:
        for key in PROJECT_ONLY_FIELDS:
            if key in data:
                items = provider_list(data[key], key)
                if items is not None:
                    plan[key] = items

    roles = data.get("roles")
    if roles is not None:
        if not isinstance(roles, dict):
            err("plan-bad-value", "\"roles\" must be an object keyed by role.")
        else:
            plan["roles"] = {}
            for role, value in roles.items():
                if role != "*" and role not in ROLES:
                    err("plan-unknown-role", "Unknown role %r; roles are %s or \"*\"." % (role, ", ".join(ROLES)))
                    continue
                label = None if role == "*" else role
                if not isinstance(value, dict):
                    err("plan-bad-value", "roles.%s must be an object." % role, label)
                    continue
                entry = {}
                for key, field in value.items():
                    where = "roles.%s.%s" % (role, key)
                    if key not in ROLE_FIELDS:
                        err("plan-unknown-field", "Unknown field %r in roles.%s." % (key, role), label)
                    elif key == "model":
                        if field is None:
                            entry["model"] = None
                            continue
                        ref, code = parse_ref(field, True, False)
                        if code:
                            err(code, ref_message(code, where, field), label)
                        else:
                            entry["model"] = ref
                    elif key == "thinking":
                        if field is None or thinking_ok(field, where, label):
                            entry["thinking"] = field
                    elif key == "fallback":
                        if field is None:
                            entry["fallback"] = []
                            continue
                        if not isinstance(field, list):
                            err("plan-bad-value", "%s must be a list." % where, label)
                            continue
                        refs = []
                        for item in field:
                            ref, code = parse_ref(item, False, True)
                            if code:
                                err(code, ref_message(code, where + " entry", item), label)
                            else:
                                refs.append(ref)
                        entry["fallback"] = refs
                    elif key == "escalate":
                        ref, code = parse_escalate(field)
                        if code:
                            err(code, ref_message(code, where, field), label)
                        else:
                            entry["escalate"] = ref
                    elif key == "byMainProvider":
                        if not isinstance(field, dict):
                            err("plan-bad-value", "%s must be an object keyed by provider." % where, label)
                            continue
                        by = {}
                        for prov, sub in field.items():
                            if not isinstance(sub, dict):
                                err("plan-bad-value", "%s.%s must be an object." % (where, prov), label)
                                continue
                            item = {}
                            for skey, sval in sub.items():
                                swhere = "%s.%s.%s" % (where, prov, skey)
                                if skey not in BY_MAIN_FIELDS:
                                    err("plan-unknown-field", "Unknown field %r in %s.%s." % (skey, where, prov), label)
                                elif sval is None:
                                    item[skey] = None
                                elif skey == "model":
                                    ref, code = parse_ref(sval, True, False)
                                    if code:
                                        err(code, ref_message(code, swhere, sval), label)
                                    else:
                                        item["model"] = ref
                                elif thinking_ok(sval, swhere, label):
                                    item["thinking"] = sval
                            by[prov] = item
                        entry["byMainProvider"] = by
                plan["roles"][role] = entry
    return plan, found


def merge_plans(user, user_path, project, project_path):
    """Merge the user and project plans. Precedence for each role field,
    strongest first: project role, project "*", user role, user "*". Each
    value carries the file it came from and its rank in that order, so a
    byMainProvider entry replaces a model only from an equal or stronger
    layer. allowProviders and denyProviders are collected by _collect_lists."""
    layers = [(p, path, index) for index, (p, path) in enumerate(((user, user_path), (project, project_path)))
              if p is not None]
    merged = {"main": {}, "judgmentModels": None, "judgmentSource": None, "providers": {},
              "families": {}, "roles": {}}
    for plan, path, _ in layers:
        for key, value in plan.get("main", {}).items():
            merged["main"][key] = (value, path)
        if "judgmentModels" in plan:
            merged["judgmentModels"] = plan["judgmentModels"]
            merged["judgmentSource"] = path
        for name, entry in plan.get("providers", {}).items():
            slot = merged["providers"].setdefault(name, {})
            for key, value in entry.items():
                slot[key] = (value, path)
        for name, globs in plan.get("families", {}).items():
            merged["families"][name] = globs
    for role in ROLES:
        fields = {}
        by_main = {}
        for plan, path, layer in layers:
            roles = plan.get("roles", {})
            for name in ("*", role):
                entry = roles.get(name)
                if not entry:
                    continue
                rank = layer * 2 + (1 if name == role else 0)
                for key, value in entry.items():
                    if key == "byMainProvider":
                        for prov, sub in value.items():
                            slot = by_main.setdefault(prov, {})
                            for skey, sval in sub.items():
                                slot[skey] = (sval, path, rank)
                    else:
                        fields[key] = (value, path, rank)
        if by_main:
            fields["byMainProvider"] = (by_main, None, None)
        if fields:
            merged["roles"][role] = fields
    return merged


def _collect_lists(list_plans):
    """Union the deny lists and intersect the allow lists of every project plan.
    Returns (deny {norm: source}, allow_lists [(set, source)])."""
    deny = {}
    allow_lists = []
    for plan, path in list_plans:
        for provider in plan.get("denyProviders", []):
            deny.setdefault(provider, path)
        if plan.get("allowProviders"):
            allow_lists.append((list(plan["allowProviders"]), path))
    return deny, allow_lists


# ---------------------------------------------------------------- evaluation

class _Context:
    def __init__(self, facts, models, findings, merged, deny, allow_lists):
        self.facts = facts
        self.findings = findings
        self.models = models
        self.catalog = {_full(m): m for m in models}
        self.available = [m for m in models if m["available"]]
        main = facts["main"]
        self.main = "%s/%s" % (main["provider"], main["id"]) if main else None
        self.main_provider = main["provider"] if main else None
        self.merged = merged
        self.deny = deny
        self.allow_lists = allow_lists
        self.lists_active = bool(deny) or bool(allow_lists)
        self.families = []
        overrides = merged["families"] if merged else {}
        for name, globs in overrides.items():
            self.families.append((name, tuple(globs)))
        for name, globs in BUILTIN_FAMILIES:
            if name not in overrides:
                self.families.append((name, globs))
        self.judgment = merged["judgmentModels"] if merged else None

    def allowed_providers(self):
        if not self.allow_lists:
            return []
        first = self.allow_lists[0][0]
        return [p for p in first if all(p in allowed for allowed, _ in self.allow_lists[1:])]

    def family(self, model):
        if not model:
            return None
        for name, globs in self.families:
            if any(glob_match(model, g) for g in globs):
                return name
        return None

    def judgment_grade(self, model):
        if self.judgment is None or not model:
            return None
        return any(glob_match(model, g) for g in self.judgment)

    def provider_entry(self, provider):
        if not self.merged:
            return {}
        return self.merged["providers"].get(provider, {})

    def provider_block(self, provider):
        """(code, reason, source) when the allow/deny lists exclude a provider.
        Both sides are compared after normalize_segment."""
        norm = normalize_segment(provider)
        if norm in self.deny:
            return "provider-denied", "provider %s is in denyProviders" % provider, self.deny[norm]
        for allowed, path in self.allow_lists:
            if norm not in allowed:
                return ("provider-not-allowed", "provider %s is outside allowProviders (%s)"
                        % (provider, ", ".join(allowed)), path)
        return None

    def policy_block(self, model):
        return self.provider_block(model.split("/", 1)[0])


def _candidate_ok(ctx, role, ref, what, source, subject):
    """Resolve one plan candidate. Returns the resolved provider/id, or None
    after recording why it is skipped."""
    f = ctx.findings
    if ref["main"]:
        if not ctx.main:
            f.add("warn", "main-model-unknown", role, "%s is \"main\", but the main thread's model is not known." % what,
                  source, subject)
            return None
        model = ctx.main
    else:
        model = ref["model"]
    blocked = ctx.policy_block(model)
    if blocked:
        f.add("error", blocked[0], role, "%s %s is skipped: %s." % (what, model, blocked[1]), blocked[2], subject)
        return None
    provider = model.split("/", 1)[0]
    enabled = ctx.provider_entry(provider).get("enabled")
    if enabled and enabled[0] is False:
        f.add("info", "provider-disabled", None, "Provider %s is disabled in the plan; its candidates are skipped." % provider, enabled[1])
        return None
    if ref["main"]:
        return model  # the running main model needs no registry check
    entry = ctx.catalog.get(model)
    if entry is None:
        f.add("error", "model-not-in-catalog", role, "%s %s is not in pi's model catalog; skipped." % (what, model),
              source, subject)
        return None
    if not entry["available"]:
        f.add("error", "model-no-credentials", role, "%s %s has no configured credentials; skipped." % (what, model),
              source, subject)
        return None
    return model


def _launch(model, level):
    return "%s:%s" % (model, level) if level else model


def _resolve_plan_role(ctx, role, fields):
    """Plan binding, relaunch and escalation for one role."""
    def value(key):
        item = fields.get(key)
        return (item[0], item[1]) if item else (None, None)

    def rank(key):
        item = fields.get(key)
        return item[2] if item else -1

    model_ref, model_src = value("model")
    thinking, thinking_src = value("thinking")
    model_rank, thinking_rank = rank("model"), rank("thinking")
    by_used = None
    by_main = fields.get("byMainProvider", (None, None, None))[0] or {}
    if ctx.main_provider and ctx.main_provider in by_main:
        sub = by_main[ctx.main_provider]
        # A byMainProvider entry replaces a field only from an equal or
        # stronger layer than the value it replaces.
        if "model" in sub and sub["model"][2] >= model_rank:
            model_ref, model_src = sub["model"][0], sub["model"][1]
            by_used = ctx.main_provider
        if "thinking" in sub and sub["thinking"][2] >= thinking_rank:
            thinking, thinking_src = sub["thinking"][0], sub["thinking"][1]
            by_used = ctx.main_provider
    fallback, fallback_src = value("fallback")
    candidates = []
    if model_ref:
        candidates.append((model_ref, thinking, model_src, False, "Bound model"))
    for ref in fallback or []:
        candidates.append((ref, ref["thinking"] or thinking, fallback_src, True, "Fallback"))

    binding = None
    relaunch = None
    for ref, level, src, is_fallback, what in candidates:
        if binding and not ref["main"] and ref["model"] == binding["model"]:
            continue
        if binding and ref["main"] and ctx.main == binding["model"]:
            continue
        subject = "plan binding" if binding is None else "relaunch model"
        model = _candidate_ok(ctx, role, ref, what, src, subject)
        if not model:
            continue
        if binding is None:
            binding = {"model": model, "thinking": level, "ref": ref, "source": src,
                       "fromFallback": is_fallback, "thinkingSource": thinking_src if not ref["thinking"] else src}
        elif model != binding["model"]:
            relaunch = {"model": model, "thinking": level, "launch": _launch(model, level)}
            break
    if candidates and binding is None:
        ctx.findings.add("error", "no-available-candidate", role,
                         "No model in the plan for %s is usable (bound model and every fallback skipped)." % role,
                         model_src or fallback_src, "plan binding")

    plan = {"setting": None, "model": None, "thinking": thinking, "inheritsMain": False,
            "source": model_src, "thinkingSource": thinking_src, "byMainProvider": by_used,
            "fromFallback": False, "available": None, "clampedTo": None,
            "judgmentGrade": None, "family": None}
    if binding:
        plan.update({
            "setting": "inherit" if binding["ref"]["main"] else binding["model"],
            "model": binding["model"], "thinking": binding["thinking"],
            "inheritsMain": binding["ref"]["main"], "source": binding["source"],
            "thinkingSource": binding["thinkingSource"], "fromFallback": binding["fromFallback"],
            "available": True,
        })

    escalate = None
    esc_ref, esc_src = value("escalate")
    if esc_ref:
        model = _candidate_ok(ctx, role, esc_ref, "Escalation target", esc_src, "escalation model")
        if model:
            escalate = {"model": model, "thinking": esc_ref["thinking"],
                        "launch": _launch(model, esc_ref["thinking"]), "inheritsMain": esc_ref["main"]}

    # Latent bindings: byMainProvider entries for other main providers apply
    # after a /model switch, so the lists are checked now.
    for prov, sub in by_main.items():
        if prov == ctx.main_provider or "model" not in sub:
            continue
        ref, src = sub["model"][0], sub["model"][1]
        if not ref or ref["main"]:
            continue
        blocked = ctx.policy_block(ref["model"])
        if blocked:
            ctx.findings.add("error", blocked[0], role,
                             "byMainProvider.%s binds %s to %s when the main thread runs on %s: %s."
                             % (prov, role, ref["model"], prov, blocked[1]), blocked[2], "latent binding")

    # router ids anywhere in the plan's candidates
    refs = [(c[0], c[2]) for c in candidates]
    for prov, sub in by_main.items():
        if sub.get("model") and sub["model"][0]:
            refs.append((sub["model"][0], sub["model"][1]))
    if esc_ref:
        refs.append((esc_ref, esc_src))
    for ref, src in refs:
        if not ref["main"]:
            _check_router(ctx, role, ref["model"], src)
    return plan, relaunch, escalate


def _check_router(ctx, role, model, source):
    mid = model.split("/", 1)[1] if "/" in model else model
    if "/routers/" in "/" + mid or "-latest" in mid:
        ctx.findings.add("warn", "router-id", role,
                         "%s is a router or -latest id: it can change under the plan, and strict response "
                         "verification may need modelResponseAliases." % model, source)


def _settings_subagents(data):
    sub = data.get("subagents") if isinstance(data, dict) else None
    return sub if isinstance(sub, dict) else {}


def _dict_at(container, key):
    value = container.get(key) if isinstance(container, dict) else None
    return value if isinstance(value, dict) else {}


def _resolve_settings_model(ctx, value, preferred):
    """Resolve a settings model string the way pi-subagents does
    (resolve_subagent_model); an unresolved string is passed through raw
    (PS/src/runs/shared/model-resolution.js:296-334)."""
    resolved = resolve_subagent_model(value, ctx.available, preferred)
    return resolved or value


def _effective_binding(ctx, role, frontmatter, fm_path, layers):
    """The binding pi-subagents will launch steward.<role> with.

    Order mirrored from PS 0.77.0: defaults are applied to agents that lack
    the field (applySubagentDefaults, PS/src/agents/agents.js:1179-1181;
    defaultModel and defaultProvider :1085-1114, defaultThinking :1115-1132),
    then the user override, then the project override, field by field
    (applyCustomAgentOverrides, :1374-1387, "Apply user then project so
    project fields win"). Inside one settings file the provider-scoped entry
    for the parent provider layers over the plain agentOverrides entry
    (selectProviderOverrides, :1073-1084, called at :2511,2516). `false`
    clears a field (applyBuiltinOverride, :1237-1257). The agent's
    modelProvider, else the parent provider, is the preferred provider for a
    bare or fuzzy id (subagent-executor.js:2775,3114). An absent model or
    "inherit" means the parent session model
    (PS/src/runs/shared/model-resolution.js:296-331)."""
    name = "steward." + role
    user_sub, user_path, project_sub, project_path = layers
    model = frontmatter.get("model") or None
    model_src = {"file": fm_path, "key": "model"} if model else None
    thinking = frontmatter.get("thinking") or None
    thinking_src = {"file": fm_path, "key": "thinking"} if thinking else None

    def pick_default(key):
        if project_path and key in project_sub:
            return project_sub[key], project_path
        if key in user_sub:
            return user_sub[key], user_path
        return None, None

    value, _ = pick_default("defaultProvider")
    model_provider = value.strip() if isinstance(value, str) and value.strip() else None
    if model is None:
        value, path = pick_default("defaultModel")
        if isinstance(value, str) and value:
            model, model_src = value, {"file": path, "key": "subagents.defaultModel"}
    if thinking is None:
        value, path = pick_default("defaultThinking")
        if isinstance(value, str) and value:
            thinking, thinking_src = value, {"file": path, "key": "subagents.defaultThinking"}

    for sub, path in ((user_sub, user_path), (project_sub, project_path)):
        if path is None:
            continue
        fields = {}
        plain = _dict_at(sub, "agentOverrides").get(name)
        if isinstance(plain, dict):
            for key in ("model", "thinking", "defaultProvider"):
                if key in plain:
                    fields[key] = (plain[key], 'subagents.agentOverrides["%s"].%s' % (name, key))
        scoped = _dict_at(sub, "agentOverridesByProvider").get(ctx.main_provider) if ctx.main_provider else None
        scoped = scoped.get(name) if isinstance(scoped, dict) else None
        if isinstance(scoped, dict):
            for key in ("model", "thinking", "defaultProvider"):
                if key in scoped:
                    fields[key] = (scoped[key], 'subagents.agentOverridesByProvider.%s["%s"].%s'
                                   % (ctx.main_provider, name, key))
        if "model" in fields:
            value, key = fields["model"]
            model = value if isinstance(value, str) and value else None
            model_src = {"file": path, "key": key}
        if "thinking" in fields:
            value, key = fields["thinking"]
            thinking = value if isinstance(value, str) and value else None
            thinking_src = {"file": path, "key": key}
        if "defaultProvider" in fields:
            value, _ = fields["defaultProvider"]
            model_provider = value.strip() if isinstance(value, str) and value.strip() else None

    inherits = model is None or model.strip() == "inherit"
    requested = None
    exact = False
    if inherits:
        resolved = ctx.main
        if model_src is None:
            model_src = {"file": None, "key": "parent session model"}
    else:
        base, suffix = split_level(model.strip())
        if suffix:
            # A model's own :level suffix wins over the thinking field
            # (applyThinkingSuffix, PS/src/runs/shared/child-tool-plan.js:48-57).
            thinking, thinking_src = suffix, dict(model_src)
        requested = base
        entry = ctx.catalog.get(base)
        exact = bool(entry and entry["available"])
        resolved = _resolve_settings_model(ctx, base, model_provider or ctx.main_provider)
    if thinking_src is None:
        thinking_src = {"file": None, "key": None}
    entry = ctx.catalog.get(resolved) if resolved else None
    available = True if inherits and resolved else bool(entry and entry["available"])
    clamped = None
    if entry and entry["thinkingLevels"] is not None and thinking and thinking in THINKING_LEVELS:
        level = clamp_thinking(thinking, entry["thinkingLevels"])
        if level != thinking:
            clamped = level
    return {"model": resolved, "requested": requested, "exact": exact, "thinking": thinking,
            "inheritsMain": inherits, "available": available,
            "modelSource": model_src, "thinkingSource": thinking_src, "clampedTo": clamped,
            "judgmentGrade": ctx.judgment_grade(resolved), "family": ctx.family(resolved)}


def _check_binding_policy(ctx, role, subject, inherits, requested, resolved, main_provider, source, describe):
    """Fail-closed allow/deny check of one settings binding. Call only when
    the lists are active. `describe` names the binding in the message;
    `source` is the file that sets the binding, the one to fix."""
    f = ctx.findings
    if inherits:
        if not main_provider:
            f.add("error", "effective-model-unverifiable", role,
                  "%s inherits the main thread's model, which is not known, so allowProviders/denyProviders "
                  "cannot be checked." % describe, source, subject)
            return
        blocked = ctx.provider_block(main_provider)
        if blocked:
            f.add("error", blocked[0], role, "%s inherits the main thread on a blocked %s." % (describe, blocked[1]),
                  source, subject)
        return
    entry = ctx.catalog.get(requested)
    if entry and entry["available"]:
        blocked = ctx.policy_block(requested)
        if blocked:
            f.add("error", blocked[0], role, "%s %s is on a blocked %s." % (describe, requested, blocked[1]),
                  source, subject)
        return
    target = resolved if resolved and resolved != requested and resolved in ctx.catalog else None
    f.add("error", "effective-model-unverifiable", role,
          "%s %r is not an exact, available provider/id%s, so allowProviders/denyProviders cannot be verified; "
          "write the exact provider/id." % (describe, requested,
                                             "; pi-subagents resolves it to %s" % target if target else ""),
          source, subject)
    if target:
        blocked = ctx.policy_block(target)
        if blocked:
            f.add("error", blocked[0], role, "%s resolves to %s, on a blocked %s." % (describe, target, blocked[1]),
                  source, subject)


def _check_latent_settings(ctx, layers):
    """agentOverridesByProvider entries for other main providers apply after a
    /model switch; check them against the lists now."""
    user_sub, user_path, project_sub, project_path = layers
    current = normalize_segment(ctx.main_provider) if ctx.main_provider else None
    for sub, path in ((user_sub, user_path), (project_sub, project_path)):
        if path is None:
            continue
        default = sub.get("defaultProvider")
        default = default.strip() if isinstance(default, str) and default.strip() else None
        plain_all = _dict_at(sub, "agentOverrides")
        for prov, entries in _dict_at(sub, "agentOverridesByProvider").items():
            if not isinstance(entries, dict) or normalize_segment(prov) == current:
                continue
            for role in ROLES:
                name = "steward." + role
                scoped = entries.get(name)
                if not isinstance(scoped, dict) or "model" not in scoped:
                    continue
                value = scoped["model"]
                inherits = not isinstance(value, str) or not value.strip() or value.strip() == "inherit"
                requested = resolved = None
                if not inherits:
                    requested, _ = split_level(value.strip())
                    plain = plain_all.get(name) if isinstance(plain_all.get(name), dict) else {}
                    preferred = None
                    for candidate in (scoped.get("defaultProvider"), plain.get("defaultProvider"), default, prov):
                        if isinstance(candidate, str) and candidate.strip():
                            preferred = candidate.strip()
                            break
                    resolved = _resolve_settings_model(ctx, requested, preferred)
                describe = ('subagents.agentOverridesByProvider.%s["%s"] (used when the main thread runs on %s)'
                            % (prov, name, prov))
                _check_binding_policy(ctx, role, "latent binding", inherits, requested, resolved, prov, path, describe)


def _agent_scan_dirs(agent_dir, env, cwd, project_root, settings_paths):
    """The user and project agent directories pi-subagents scans
    (buildAgentDiscoverySources, PS/src/agents/agents.js:2385-2414;
    expandAgentScanDirPattern :2253-2282)."""
    home = env.get("HOME") or os.path.expanduser("~")
    dirs = []
    extra = env.get("PI_SUBAGENT_EXTRA_AGENT_DIRS")
    if extra:
        dirs.extend(d.strip() for d in extra.split(os.pathsep) if d.strip())
    for path in settings_paths:
        data, _ = _read_json(path)
        entries = _settings_subagents(data).get("agentScanDirs")
        for entry in entries if isinstance(entries, list) else ():
            if not isinstance(entry, str) or not entry.strip():
                continue
            text = entry.strip()
            if text == "~" or text.startswith("~/"):
                text = os.path.join(home, text[2:])
            text = os.path.join(cwd, text)
            if "*" not in text:
                dirs.append(text)
                continue
            parts = text.split(os.sep)
            stars = [i for i, part in enumerate(parts) if "*" in part]
            if len(stars) != 1 or parts[stars[0]] != "*" or text.count("*") != 1:
                continue
            base = os.sep.join(parts[:stars[0]]) or os.sep
            try:
                names = sorted(os.listdir(base))
            except OSError:
                continue
            for item in names:
                if os.path.isdir(os.path.join(base, item)):
                    dirs.append(os.path.join(base, item, *parts[stars[0] + 1:]))
    dirs.append(os.path.join(agent_dir, "agents"))
    dirs.append(os.path.join(home, ".agents"))
    if project_root:
        dirs.append(os.path.join(project_root, ".agents"))
        dirs.append(os.path.join(project_root, ".pi", "agents"))
    return dirs


def _agent_files(root):
    """Agent definition files under root (inspectAgentDefinitionDirectory)."""
    out = []
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return out
    seen = set()
    stack = [root]
    while stack and len(out) < MAX_DISCOVERY_FILES:
        current = stack.pop()
        try:
            real = os.path.realpath(current)
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        try:
            names = sorted(os.listdir(current))
        except OSError:
            continue
        for name in names:
            path = os.path.join(current, name)
            if os.path.isdir(path):
                if name in DISCOVERY_PRUNED_DIR_NAMES or os.path.exists(os.path.join(path, ".git")):
                    continue
                if os.path.isdir(os.path.join(path, ".pi")) or os.path.isdir(os.path.join(path, ".agents")):
                    continue
                stack.append(path)
            elif name.endswith(".md") and not name.endswith(".chain.md"):
                parts = [p.lower() for p in os.path.relpath(path, root).split(os.sep)]
                if os.path.basename(root).lower() == ".agents":
                    parts.insert(0, ".agents")
                if any(p == ".agents" and parts[i + 1:i + 2] == ["skills"] for i, p in enumerate(parts)):
                    continue
                out.append(path)
    return out


def _check_shadowing(ctx, agent_dir, env, cwd, project_root, settings_paths, package_dir):
    """A user or project agent whose runtime name is steward.<role> replaces
    the package profile (mergeAgentsForScope, PS/src/agents/agent-selection.js:1-21;
    runtime name `<package>.<name>`, PS/src/agents/identity.js:18-21)."""
    package_dir = os.path.realpath(str(package_dir))
    for directory in _agent_scan_dirs(agent_dir, env, cwd, project_root, settings_paths):
        for path in _agent_files(directory):
            if os.path.dirname(os.path.realpath(path)) == package_dir:
                continue
            fm = read_frontmatter(path)
            if not fm.get("name") or not fm.get("description"):
                continue
            package = fm.get("package", "").strip()
            runtime = "%s.%s" % (package, fm["name"]) if package else fm["name"]
            if not runtime.startswith("steward.") or runtime[len("steward."):] not in ROLES:
                continue
            role = runtime[len("steward."):]
            ctx.findings.add("error", "agent-shadowed", role,
                             "%s defines %s and replaces the steward profile, so its model cannot be checked "
                             "against allowProviders/denyProviders; remove or rename it." % (path, runtime),
                             path, "effective binding")


def _startup_thinking(ctx, user_data, user_path, project_data, project_path):
    """Main thread startup level for a fresh session: modelThinkingLevels
    ["provider/id"], then defaultThinkingLevel, then "medium", then clamp
    (PI/.../pi-coding-agent/dist/core/sdk.js:121-143). Settings are global
    deep-merged with <cwd>/.pi/settings.json when trusted
    (dist/core/settings-manager.js:123-124,220)."""
    main = ctx.facts["main"]
    key_name = "%s/%s" % (main["provider"], main["id"])
    requested, key, source = None, None, None
    for data, path in ((project_data, project_path), (user_data, user_path)):
        levels = data.get("modelThinkingLevels") if isinstance(data, dict) else None
        if isinstance(levels, dict) and isinstance(levels.get(key_name), str):
            requested, key, source = levels[key_name], 'modelThinkingLevels["%s"]' % key_name, path
            break
    if requested is None:
        for data, path in ((project_data, project_path), (user_data, user_path)):
            if isinstance(data, dict) and isinstance(data.get("defaultThinkingLevel"), str):
                requested, key, source = data["defaultThinkingLevel"], "defaultThinkingLevel", path
                break
    if requested is None:
        requested, key = PI_DEFAULT_THINKING, "pi default"
    entry = ctx.catalog.get(key_name)
    if entry and entry["thinkingLevels"] is not None:
        level = clamp_thinking(requested, entry["thinkingLevels"])
    else:
        level = requested
    return {"level": level, "requested": requested, "key": key, "source": source}


def evaluate(facts, env=None, agent_dir=None, agents_dir=None):
    """Compute the model plan result for one session. Never writes files and
    never raises: malformed facts or an unexpected error give a result with a
    single error finding."""
    try:
        validate_facts(facts)
    except ValueError as exc:
        findings = _Findings()
        findings.add("error", "facts-invalid", None, "The registry facts are malformed (%s); no checks ran." % exc)
        return _empty_result(findings.items)
    try:
        return _evaluate(facts, env, agent_dir, agents_dir)
    except Exception as exc:  # session start must fail open
        findings = _Findings()
        findings.add("error", "internal-error", None,
                     "The model plan check failed (%s: %s); no checks ran." % (type(exc).__name__, str(exc)[:200]))
        return _empty_result(findings.items)


def _read_plan(path, is_project, findings):
    data, error = _read_json(path)
    if error:
        findings.add("error", "plan-unreadable", None, "The model plan could not be read (%s); the file is ignored." % error, path)
    if data is None:
        return None
    plan, found = parse_plan(data, path, is_project)
    for item in found:
        findings.add(**item)
    return plan


def _evaluate(facts, env, agent_dir, agents_dir):
    env = dict(os.environ if env is None else env)
    agent_dir = agent_dir or agent_dir_from_env(env)
    agents_dir = Path(agents_dir) if agents_dir else DEFAULT_AGENTS_DIR
    trusted = facts["projectTrusted"]
    cwd = facts["cwd"]
    findings = _Findings()
    models = _clean_models(facts["models"], findings)

    # Project root as pi-subagents finds it; an untrusted project
    # contributes nothing (PS/src/agents/agents.js:2385-2396).
    project_root = find_project_root(cwd, env) if trusted else None

    # ---- plans
    user_plan_path = os.path.join(agent_dir, "steward", "model-plan.json")
    root_plan_path, list_paths = project_plan_files(cwd, env, trusted, project_root)
    user_plan = _read_plan(user_plan_path, False, findings)
    parsed = {}
    for path in [root_plan_path] + list_paths:
        if path and path not in parsed:
            parsed[path] = _read_plan(path, True, findings)
    project_plan = parsed.get(root_plan_path) if root_plan_path else None
    list_plans = [(parsed[path], path) for path in list_paths if parsed.get(path) is not None]
    for plan, path in list_plans:
        if path != root_plan_path and any(k not in PROJECT_ONLY_FIELDS for k in plan):
            findings.add("info", "plan-lists-only", None,
                         "This project plan is above the project root; only its allowProviders and denyProviders "
                         "apply.", path)
    has_plan = user_plan is not None or project_plan is not None or bool(list_plans)
    merged = None
    if has_plan:
        merged = merge_plans(user_plan, user_plan_path, project_plan, root_plan_path)
    deny, allow_lists = _collect_lists(list_plans)

    ctx = _Context(facts, models, findings, merged, deny, allow_lists)

    known = {normalize_segment(m["provider"]) for m in models}
    for plan, path in list_plans:
        for key in PROJECT_ONLY_FIELDS:
            for provider in plan.get(key, []):
                if provider not in known:
                    findings.add("warn", "provider-unknown", None,
                                 "%s names provider %s, which no model in pi's catalog uses. The lists name pi "
                                 "provider ids, not upstream vendors." % (key, provider), path)
    if allow_lists and not ctx.allowed_providers():
        findings.add("error", "allow-lists-disjoint", None,
                     "The allowProviders lists share no provider, so every model is blocked.",
                     allow_lists[0][1])

    # ---- settings
    user_settings_path = os.path.join(agent_dir, "settings.json")
    project_settings_path = os.path.join(project_root, ".pi", "settings.json") if project_root else None
    user_data, error = _read_json(user_settings_path)
    if error:
        findings.add("warn", "settings-unreadable", None, "Settings could not be read: %s." % error, user_settings_path)
    project_data, error = _read_json(project_settings_path)
    if error:
        findings.add("warn", "settings-unreadable", None, "Settings could not be read: %s." % error, project_settings_path)
    user_found = user_settings_path if user_data is not None else None
    project_found = project_settings_path if project_data is not None else None
    user_sub = _settings_subagents(user_data)
    project_sub = _settings_subagents(project_data)
    layers = (user_sub, user_found or user_settings_path, project_sub, project_found)

    # pi's own settings for the main thread read <cwd>/.pi only, not the walk.
    pi_project_path = os.path.join(cwd, ".pi", "settings.json") if trusted else None
    pi_project_data, _ = _read_json(pi_project_path)

    for sub, path in ((user_sub, user_found), (project_sub, project_found)):
        for key in _dict_at(sub, "agentOverrides"):
            if key in STALE_KEYS:
                findings.add("warn", "stale-override-key", STALE_KEYS[key],
                             "subagents.agentOverrides[\"%s\"] uses an old profile name and is no longer applied; "
                             "move it to \"steward.%s\"." % (key, STALE_KEYS[key]), path)
        for prov, entries in _dict_at(sub, "agentOverridesByProvider").items():
            for key in entries if isinstance(entries, dict) else ():
                if key in STALE_KEYS:
                    findings.add("warn", "stale-override-key", STALE_KEYS[key],
                                 "subagents.agentOverridesByProvider.%s[\"%s\"] uses an old profile name and is no "
                                 "longer applied; move it to \"steward.%s\"." % (prov, key, STALE_KEYS[key]), path)

    # Project modelScope replaces the user one; maxThinking project wins
    # (PS/src/agents/agents.js:1133-1137,2563; PS/docs/models.md "Model scope enforcement").
    if project_found and "modelScope" in project_sub:
        scope, scope_src = project_sub.get("modelScope"), project_found
    else:
        scope, scope_src = user_sub.get("modelScope"), user_found
    if project_found and isinstance(project_sub.get("maxThinking"), str):
        max_thinking, max_src = project_sub["maxThinking"], project_found
    else:
        max_thinking, max_src = (user_sub.get("maxThinking"), user_found) if isinstance(user_sub.get("maxThinking"), str) else (None, None)

    # ---- roles
    roles = {}
    for role in ROLES:
        fm_path = agents_dir / ("%s.md" % role)
        frontmatter = read_frontmatter(fm_path)
        effective = _effective_binding(ctx, role, frontmatter, str(fm_path), layers)
        plan = relaunch = escalate = None
        if merged and role in merged["roles"]:
            plan, relaunch, escalate = _resolve_plan_role(ctx, role, merged["roles"][role])
            if plan["model"]:
                entry = ctx.catalog.get(plan["model"])
                if entry and entry["thinkingLevels"] is not None and plan["thinking"]:
                    level = clamp_thinking(plan["thinking"], entry["thinkingLevels"])
                    plan["clampedTo"] = level if level != plan["thinking"] else None
                plan["judgmentGrade"] = ctx.judgment_grade(plan["model"])
                plan["family"] = ctx.family(plan["model"])
        roles[role] = {"runtimeName": "steward." + role, "plan": plan, "effective": effective,
                       "relaunch": relaunch, "escalate": escalate,
                       "judgmentGrade": effective["judgmentGrade"], "family": effective["family"]}

    # ---- per-role checks
    for role, row in roles.items():
        plan, eff = row["plan"], row["effective"]
        subjects = []  # (label, model, thinking, explicit, source)
        if plan and plan["model"]:
            subjects.append(("plan binding", plan["model"], plan["thinking"], False, plan["source"]))
        if eff["model"]:
            subjects.append(("effective binding", eff["model"], eff["thinking"], False, eff["modelSource"]["file"]))
        if row["relaunch"]:
            subjects.append(("relaunch model", row["relaunch"]["model"], row["relaunch"]["thinking"], True, plan and plan["source"]))
        if row["escalate"]:
            subjects.append(("escalation model", row["escalate"]["model"], row["escalate"]["thinking"], True, plan and plan["source"]))

        for label, model, thinking, explicit, source in subjects:
            entry = ctx.catalog.get(model)
            if entry and entry["thinkingLevels"] is not None and thinking in THINKING_LEVELS:
                level = clamp_thinking(thinking, entry["thinkingLevels"])
                if level != thinking:
                    findings.add("warn", "thinking-clamped", role,
                                 "%s at %s is clamped to %s: the model does not declare %s. A declared level is not "
                                 "proof the provider honors it." % (model, thinking, level, thinking), source, label)
            if role in LARGE_OUTPUT_ROLES and not explicit and entry and entry["maxTokens"] is not None \
                    and entry["maxTokens"] < MIN_OUTPUT_TOKENS:
                findings.add("warn", "max-tokens-low", role,
                             "%s allows only %d output tokens; large %s output can be truncated (below 32K)."
                             % (model, entry["maxTokens"], role), source, label)
            if max_thinking in THINKING_LEVELS and thinking in THINKING_LEVELS \
                    and THINKING_LEVELS.index(thinking) > THINKING_LEVELS.index(max_thinking):
                findings.add("error", "thinking-above-max", role,
                             "The %s %s asks for %s, above subagents.maxThinking %s; the launch fails before start."
                             % (label, model, thinking, max_thinking), max_src, label)
            _check_scope(ctx, role, label, model, explicit, scope, scope_src)
            if role in JUDGMENT_ROLES and ctx.judgment is not None and not ctx.judgment_grade(model):
                findings.add("warn", "below-judgment-floor", role,
                             "The %s %s for %s is outside judgmentModels." % (label, model, role),
                             ctx.merged["judgmentSource"], label)

        if ctx.lists_active:
            _check_binding_policy(ctx, role, "effective binding", eff["inheritsMain"], eff["requested"],
                                  eff["model"], ctx.main_provider, eff["modelSource"]["file"],
                                  "The effective binding of steward.%s" % role)
        if eff["model"] and not eff["inheritsMain"]:
            _check_router(ctx, role, eff["model"], eff["modelSource"]["file"])
        if eff["model"] and not eff["available"]:
            why = "is not in pi's model catalog" if eff["model"] not in ctx.catalog else "has no configured credentials"
            findings.add("warn", "effective-model-unavailable", role,
                         "The effective binding %s for %s %s; pass the next available candidate as model until fixed."
                         % (eff["model"], role, why), eff["modelSource"]["file"], "effective binding")

        if plan:
            model_differs = plan["model"] is not None and (
                plan["inheritsMain"] != eff["inheritsMain"]
                or (not plan["inheritsMain"] and plan["model"] != eff["model"]))
            thinking_differs = plan["thinking"] is not None and plan["thinking"] != eff["thinking"]
            if model_differs or thinking_differs:
                won = eff["modelSource"] if model_differs else eff["thinkingSource"]
                plan_src = plan["source"] if model_differs else plan["thinkingSource"]
                if won["file"] and won["file"] == project_found:
                    hint = "project override wins"
                elif plan_src and plan_src == root_plan_path and project_root:
                    # apply writes user settings only; a repo's choice belongs in the repo.
                    hint = "the plan value comes from the project plan; set it in %s" % os.path.join(
                        project_root, ".pi", "settings.json")
                else:
                    hint = "run /steward-models apply"
                findings.add("warn", "binding-drift", role,
                             "steward.%s launches on %s at %s, not the plan's %s at %s (from %s %s): %s."
                             % (role, eff["model"], eff["thinking"], plan["setting"] or plan["model"],
                                plan["thinking"], won["file"] or "built-in default", won["key"] or "", hint),
                             won["file"])

    if ctx.lists_active:
        _check_latent_settings(ctx, layers)
        _check_shadowing(ctx, agent_dir, env, cwd, project_root,
                         [p for p in (user_settings_path, project_settings_path) if p], agents_dir)

    # ---- cross-role checks
    if ctx.judgment is None:
        findings.add("info", "judgment-floor-unchecked", None,
                     "No judgmentModels in the plan, so the judgment floor is not checked.", None)

    if has_plan:
        def fam(role):
            row = roles[role]
            if row["plan"] and row["plan"]["model"]:
                return row["plan"]["family"]
            return row["effective"]["family"]
        rev, cod = fam("reviewer"), fam("coder")
        if rev and rev == cod:
            findings.add("warn", "reviewer-same-family", "reviewer",
                         "The reviewer and the coder are both %s models; cross-family review is lost." % rev,
                         roles["reviewer"]["plan"] and roles["reviewer"]["plan"]["source"])
        rplan = roles["reviewer"]["plan"]
        if rplan and rplan["byMainProvider"] and ctx.main and rev and rev == ctx.family(ctx.main):
            findings.add("warn", "reviewer-main-family", "reviewer",
                         "byMainProvider.%s puts the reviewer on the main thread's family (%s)." % (rplan["byMainProvider"], rev),
                         rplan["source"])

    concurrency = _read_concurrency(agent_dir)
    if merged:
        for provider, entry in merged["providers"].items():
            cap = entry.get("maxConcurrent")
            if not cap:
                continue
            limit, src = cap
            on = sorted(r for r, row in roles.items()
                        if any(b and b.get("model") and b["model"].split("/", 1)[0] == provider
                               for b in (row["plan"], row["effective"])))
            if on and (concurrency["parallel"] > limit or concurrency["global"] > limit):
                findings.add("warn", "concurrency-above-cap", None,
                             "%s allows %d concurrent requests and runs %s, but parallel.concurrency is %d and "
                             "globalConcurrencyLimit is %d; set both to %d in %s." % (
                                 provider, limit, ", ".join("steward." + r for r in on), concurrency["parallel"],
                                 concurrency["global"], limit,
                                 os.path.join(agent_dir, "extensions", "subagent", "config.json")), src)

    # ---- main thread
    main_out = None
    if facts["main"]:
        fm = facts["main"]
        expected_models = merged["main"].get("models") if merged else None
        expected_thinking = merged["main"].get("thinking") if merged else None
        startup = _startup_thinking(ctx, user_data, user_found, pi_project_data,
                                    pi_project_path if pi_project_data is not None else None)
        main_out = {"model": ctx.main, "provider": fm["provider"], "id": fm["id"],
                    "thinkingLevel": fm["thinkingLevel"],
                    "inPlan": (ctx.main in expected_models[0]) if expected_models else None,
                    "expectedThinking": expected_thinking[0] if expected_thinking else None,
                    "judgmentGrade": ctx.judgment_grade(ctx.main), "family": ctx.family(ctx.main),
                    "startupThinking": startup,
                    "inheritedBy": [r for r, row in roles.items()
                                    if (row["plan"] and row["plan"]["inheritsMain"]) or row["effective"]["inheritsMain"]]}
        blocked = ctx.provider_block(fm["provider"])
        if blocked:
            findings.add("error", "main-" + blocked[0], "main",
                         "The main thread runs %s, on a blocked %s; use /model to switch." % (ctx.main, blocked[1]),
                         blocked[2])
        if expected_models and not main_out["inPlan"]:
            findings.add("warn", "main-not-in-plan", "main",
                         "The main thread runs %s, which is not in main.models (%s); use /model to switch."
                         % (ctx.main, ", ".join(expected_models[0])), expected_models[1])
        if main_out["judgmentGrade"] is False:
            findings.add("warn", "main-below-judgment-floor", "main",
                         "The main thread runs %s, outside judgmentModels; delegation decisions are unreliable on "
                         "fast-tier models." % ctx.main, merged["judgmentSource"])
        if expected_thinking:
            want = expected_thinking[0]
            started = "a fresh session starts at %s (%s, from %s)" % (
                startup["level"],
                startup["key"] + (" %s clamped" % startup["requested"] if startup["requested"] != startup["level"] else ""),
                startup["source"] or "pi's built-in default")
            if fm["thinkingLevel"] != want:
                findings.add("warn", "main-thinking-drift", "main",
                             "%s runs at %s, not main.thinking %s; %s. Use /thinking to switch." % (
                                 ctx.main, fm["thinkingLevel"], want, started),
                             startup["source"] if startup["level"] != want else None)
            elif startup["level"] != want:
                findings.add("warn", "main-startup-thinking-drift", "main",
                             "%s runs at main.thinking %s now, but %s." % (ctx.main, want, started),
                             startup["source"])

    providers_out = {}
    if merged:
        for name, entry in merged["providers"].items():
            providers_out[name] = {k: v[0] for k, v in entry.items()}
    return {
        "hasPlan": has_plan,
        "planFiles": {"user": user_plan_path if user_plan is not None else None,
                      "project": root_plan_path if project_plan is not None else None,
                      "lists": [path for _, path in list_plans]},
        "settingsFiles": {"user": user_found, "project": project_found},
        "main": main_out,
        "roles": roles,
        "providers": providers_out,
        "allowProviders": ctx.allowed_providers(),
        "denyProviders": sorted(ctx.deny),
        "concurrency": concurrency,
        "findings": findings.items,
    }


def _check_scope(ctx, role, label, model, explicit, scope, source):
    """Mirror resolveModelScopesForAgent and checkModelScope
    (PS/src/runs/shared/model-scope.js:40-64,115-145): the model must pass the
    global list and the agent list; `inherit` and `scoped` expand to the main
    model (the scoped set is not in the facts, so an empty set is assumed);
    explicit per-call models error, others warn unless strict."""
    if not isinstance(scope, dict):
        return
    rules = []
    if isinstance(scope.get("allow"), list):
        rules.append((scope.get("allow"), scope.get("enforce"), scope.get("strict"), "modelScope"))
    agents = scope.get("agents") if isinstance(scope.get("agents"), dict) else {}
    agent_rule = agents.get("steward." + role)
    if isinstance(agent_rule, dict) and isinstance(agent_rule.get("allow"), list):
        rules.append((agent_rule["allow"],
                      agent_rule.get("enforce", scope.get("enforce")),
                      agent_rule.get("strict", scope.get("strict")),
                      "modelScope.agents.steward.%s" % role))
    for allow, enforce, strict, origin in rules:
        if enforce is not True:
            continue
        allow = [pattern for pattern in allow if isinstance(pattern, str)]
        patterns = [(ctx.main or pattern) if pattern in ("inherit", "scoped") else pattern for pattern in allow]
        if any(glob_match(model, p) for p in patterns):
            continue
        severity = "error" if explicit or strict is True else "warn"
        ctx.findings.add(severity, "outside-model-scope", role,
                         "The %s %s is outside %s (%s)%s." % (
                             label, model, origin, ", ".join(allow),
                             "; a per-call model aborts the run" if explicit else ""), source, label)


def _read_concurrency(agent_dir):
    path = os.path.join(agent_dir, "extensions", "subagent", "config.json")
    data, _ = _read_json(path)
    parallel, global_limit = DEFAULT_PARALLEL_CONCURRENCY, DEFAULT_GLOBAL_CONCURRENCY
    if isinstance(data, dict):
        par = data.get("parallel")
        if isinstance(par, dict) and type(par.get("concurrency")) is int and par["concurrency"] > 0:
            parallel = par["concurrency"]
        limit = data.get("globalConcurrencyLimit")
        if type(limit) is int and limit > 0:
            global_limit = limit
    return {"parallel": parallel, "global": global_limit, "source": path if data is not None else None}
