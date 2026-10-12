"""`/steward-models apply` for pi (Phase 3 of docs/roadmap/pi-model-plan.md).

Compiles the USER model plan (``<agent-dir>/steward/model-plan.json``) into
pi-subagents user settings (``<agent-dir>/settings.json``) and writes the
pi-subagents profile file ``<agent-dir>/profiles/pi-subagents/steward.json``.
It never reads cwd, a project plan, project settings or allow/deny lists:
user settings apply in every repo, so per-repo pinning stays in the repo's
own ``.pi/settings.json``.

What it writes
--------------
Only ``subagents.agentOverrides["steward.<role>"].model`` and ``.thinking``,
and ``subagents.agentOverridesByProvider.<p>["steward.<role>"]`` (model,
thinking). Stale old-name steward keys (``STALE_KEYS``) move to the
role-only names, keeping every field of the old entry the new entry lacks.
Every other key, and other fields on steward entries such as ``machine``,
stay as they are. It never writes ``defaultModel``, ``modelThinkingLevels``,
``enabledModels``, ``modelScope``, ``maxThinking`` or the subagent
``config.json``.

Rules
-----
- A binding is the first available candidate of the role (bound model, then
  fallbacks): in the registry facts, with credentials, its provider not
  ``enabled: false`` in the plan. ``main`` becomes ``"inherit"``. Thinking is
  the candidate's ``:level`` when a fallback carries one, else the role's
  level as written (never clamped).
- ``byMainProvider.<p>`` compiles to ``agentOverridesByProvider.<p>``, with
  the same candidate order and the same rank rule as the check (a ``"*"``
  entry does not replace a role's own model or thinking).
- Apply sets only what the plan names. A role, field or provider entry the
  plan does not name is left as it is and reported (``leftover-override``,
  ``thinking-not-in-plan``). A role with no available candidate is left
  unchanged, with a ``no-available-candidate`` finding. Nothing that is not a
  steward key is ever removed.
- Refusals (``Refused``, nothing written): no user plan, a plan that is not
  JSON or has any schema error, settings that are not JSON or have a
  ``subagents`` shape pi-subagents would reject, a file changed since the
  preview (``expect`` hashes) or between the first read and the write, or a
  settings lock held by another writer.

Writing
-------
Read, compute, then under pi's settings lock (``settings.json.lock``,
proper-lockfile) and pi-subagents' lease (``<real path>.write-lock``) re-read
and refuse on any change (sha256 of the bytes), back up once per changing
run to ``settings.json.bak-<YYYYMMDD-HHMMSS>``, write a temp file in the
same directory, fsync, rename over the real file (a symlinked settings file
stays a symlink) and fsync the directory. Mode is kept. Formatting follows
the file: its indent unit (pi writes two spaces), its trailing newline
(pi writes none) and its key order. A run that changes nothing writes
nothing and makes no backup. The profile file gets the same temp-file and
rename, a backup when it exists and changes, and pi-subagents' own style
(``JSON.stringify(value, null, 2) + "\\n"``, PS/src/profiles/profiles.js:18-21).

Sources (pi 1.1.0, pi-subagents 0.77.0): pi settings writes,
PI/dist/core/settings-manager.js:126-171,450-471; pi-subagents profile
format and load, PS/src/profiles/profiles.js:39-71,359-386; leases,
PS/src/shared/file-lease.js and settings-file-lease.js.
"""

import copy
import datetime
import errno
import hashlib
import json
import os
import socket
import tempfile
import time
import uuid

import model_plan as mp

STALE_KEYS = mp.STALE_KEYS
ROLES = mp.ROLES
PROFILE_NAME = "steward"
# proper-lockfile's default stale time; a pi lock younger than this is live.
PI_LOCK_STALE_S = 10.0
DEFAULT_LOCK_WAIT_S = 1.0


class Refused(Exception):
    """apply wrote nothing, for the reason in the message."""


def content_hash(data):
    """sha256 of a file's bytes; None for a missing file."""
    if data is None:
        return None
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Refused("%s could not be read (%s)" % (path, exc.strerror or type(exc).__name__))


def _decode(data, path):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("%s is not UTF-8" % path)
    bom = text.startswith("\ufeff")
    return (text[1:] if bom else text), bom


def _style(text):
    """(indent unit, trailing newline) of a JSON file's text."""
    indent = "  "
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" \t")
        if stripped and len(stripped) < len(line):
            indent = line[: len(line) - len(stripped)]
            break
    return indent, text.endswith("\n")


def _dump(value, indent, newline, bom=False):
    text = json.dumps(value, indent=indent, ensure_ascii=False)
    return ("\ufeff" if bom else "") + text + ("\n" if newline else "")


# ---------------------------------------------------------------- inputs

def _clean_models(facts):
    if not isinstance(facts, dict) or not isinstance(facts.get("models"), list):
        raise ValueError("model_facts.models must be a list")
    findings = mp._Findings()
    models = mp._clean_models(facts["models"], findings)
    if not models:
        raise ValueError("model_facts.models has no usable entry")
    return models


def _read_user_plan(agent_dir):
    path = os.path.join(agent_dir, "steward", "model-plan.json")
    data = _read_bytes(path)
    if data is None:
        raise Refused("no user plan at %s; write one first (README \"Model plan on pi\")" % path)
    text, _ = _decode(data, path)
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise Refused("the user plan %s is not valid JSON (%s)" % (path, str(exc)[:200]))
    plan, found = mp.parse_plan(parsed, path, False)
    errors = [item for item in found if item["severity"] == "error"]
    if plan is None or errors:
        shown = "; ".join(item["message"] for item in errors[:3])
        more = " and %d more" % (len(errors) - 3) if len(errors) > 3 else ""
        raise Refused("the user plan %s has %d schema error(s): %s%s. Fix them (/steward-models check lists "
                      "them); nothing was written" % (path, len(errors), shown, more))
    return path, plan


def _read_settings(path):
    """(bytes, data, style). Refused when pi-subagents could not use the file."""
    raw = _read_bytes(path)
    if raw is None:
        return None, {}, ("  ", False, False)
    text, bom = _decode(raw, path)
    try:
        data = json.loads(text) if text.strip() else {}
    except (ValueError, RecursionError) as exc:
        raise Refused("%s is not valid JSON (%s); nothing was written" % (path, str(exc)[:200]))
    if not isinstance(data, dict):
        raise Refused("%s must hold a JSON object; nothing was written" % path)
    sub = data.get("subagents")
    if sub is not None:
        if not isinstance(sub, dict):
            raise Refused("%s: subagents must be an object; nothing was written" % path)
        overrides = sub.get("agentOverrides")
        if overrides is not None:
            if not isinstance(overrides, dict):
                raise Refused("%s: subagents.agentOverrides must be an object; nothing was written" % path)
            for key, value in overrides.items():
                if not isinstance(value, dict):
                    raise Refused("%s: subagents.agentOverrides[%s] must be an object; nothing was written"
                                  % (path, json.dumps(key)))
        by_provider = sub.get("agentOverridesByProvider")
        if by_provider is not None:
            if not isinstance(by_provider, dict):
                raise Refused("%s: subagents.agentOverridesByProvider must be an object; nothing was written" % path)
            for prov, entries in by_provider.items():
                if not isinstance(entries, dict) or not all(isinstance(v, dict) for v in entries.values()):
                    raise Refused("%s: subagents.agentOverridesByProvider[%s] must be an object of objects; "
                                  "nothing was written" % (path, json.dumps(prov)))
    indent, newline = _style(text)
    return raw, data, (indent, newline, bom)


# ---------------------------------------------------------------- compile

def _availability(model, catalog, providers):
    """None when the candidate can bind, else why not."""
    provider = model.split("/", 1)[0]
    enabled = providers.get(provider, {}).get("enabled")
    if enabled and enabled[0] is False:
        return "its provider %s is disabled in the plan" % provider
    entry = catalog.get(model)
    if entry is None:
        return "it is not in pi's model catalog"
    if not entry["available"]:
        return "it has no configured credentials"
    return None


def _first_available(role, candidates, catalog, providers, findings, where):
    """(setting, level, fromFallback) of the first candidate that can bind, or None."""
    for ref, level, is_fallback in candidates:
        if ref["main"]:
            return "inherit", level, is_fallback
        why = _availability(ref["model"], catalog, providers)
        if why is None:
            return ref["model"], level, is_fallback
        findings.add("info", "candidate-skipped", role,
                     "%s: %s is skipped because %s." % (where, ref["model"], why))
    return None


def compile_plan(plan, plan_path, models):
    """Targets from the user plan: {role: {"overrides": {field: value},
    "byProvider": {p: {field: value}}, "named": bool}} plus findings."""
    findings = mp._Findings()
    merged = mp.merge_plans(plan, plan_path, None, None)
    catalog = {"%s/%s" % (m["provider"], m["id"]): m for m in models}
    providers = merged["providers"]
    targets = {}
    for role in ROLES:
        fields = merged["roles"].get(role) or {}

        def value(key):
            item = fields.get(key)
            return item[0] if item else None

        def rank(key):
            item = fields.get(key)
            return item[2] if item else -1

        model_ref, thinking, fallback = value("model"), value("thinking"), value("fallback") or []
        target = {"overrides": {}, "byProvider": {}, "unchanged": False}

        def candidates(first, level):
            out = [(first, level, False)] if first else []
            out.extend((ref, ref["thinking"] or level, True) for ref in fallback)
            return out

        base = candidates(model_ref, thinking)
        if base:
            bound = _first_available(role, base, catalog, providers, findings, "steward.%s" % role)
            if bound is None:
                target["unchanged"] = True
                findings.add("warn", "no-available-candidate", role,
                             "No candidate for steward.%s is available (bound model and every fallback skipped); "
                             "its settings are left unchanged." % role)
            else:
                setting, level, _ = bound
                target["overrides"]["model"] = setting
                if level is not None:
                    target["overrides"]["thinking"] = level
        elif thinking is not None:
            target["overrides"]["thinking"] = thinking

        by_main = fields.get("byMainProvider", (None, None, None))[0] or {}
        for prov, sub in by_main.items():
            entry = {}
            sub_model = sub.get("model")
            sub_thinking = sub.get("thinking")
            use_model = sub_model is not None and sub_model[0] is not None and sub_model[2] >= rank("model")
            use_thinking = (sub_thinking is not None and sub_thinking[0] is not None
                            and sub_thinking[2] >= rank("thinking"))
            level = sub_thinking[0] if use_thinking else None
            if use_model:
                where = "steward.%s with the main thread on %s" % (role, prov)
                bound = _first_available(role, candidates(sub_model[0], level), catalog, providers, findings, where)
                if bound is None:
                    findings.add("warn", "no-available-candidate", role,
                                 "No candidate for %s is available; agentOverridesByProvider.%s is left unchanged."
                                 % (where, prov))
                    continue
                setting, bound_level, _ = bound
                entry["model"] = setting
                if bound_level is not None:
                    entry["thinking"] = bound_level
            elif use_thinking:
                entry["thinking"] = level
            if entry:
                target["byProvider"][prov] = entry
        target["named"] = bool(target["overrides"] or target["byProvider"] or target["unchanged"])
        targets[role] = target
    return targets, findings


def _rename_key(mapping, old, new):
    """Rename a key in place, keeping its position."""
    items = [(new if key == old else key, value) for key, value in mapping.items()]
    mapping.clear()
    mapping.update(items)


def _migrate(entries, where, changes, findings):
    for old in [key for key in entries if key in STALE_KEYS]:
        new = "steward." + STALE_KEYS[old]
        if new not in entries:
            _rename_key(entries, old, new)
            changes.append("%s: moved \"%s\" to \"%s\"" % (where, old, new))
            continue
        moved = [field for field in entries[old] if field not in entries[new]]
        for field in moved:
            entries[new][field] = entries[old][field]
        del entries[old]
        changes.append("%s: merged \"%s\" into \"%s\"%s" % (
            where, old, new, " (%s)" % ", ".join(moved) if moved else " (no field moved)"))
        findings.add("info", "stale-key-merged", STALE_KEYS[old],
                     "%s: \"%s\" and \"%s\" both existed; the new key's fields were kept and the old key removed."
                     % (where, old, new))


def _show(value):
    return "(unset)" if value is None else json.dumps(value)


def build_settings(data, targets, findings):
    """(new settings data, change lines). data is not modified."""
    new = copy.deepcopy(data)
    changes = []
    sub = new.get("subagents") if isinstance(new.get("subagents"), dict) else None

    if sub is not None:
        if isinstance(sub.get("agentOverrides"), dict):
            _migrate(sub["agentOverrides"], "agentOverrides", changes, findings)
        for prov, entries in (sub.get("agentOverridesByProvider") or {}).items():
            _migrate(entries, "agentOverridesByProvider.%s" % prov, changes, findings)

    def section(*keys):
        nonlocal sub
        if sub is None:
            sub = new.setdefault("subagents", {})
        node = sub
        for key in keys:
            node = node.setdefault(key, {})
        return node

    for role in ROLES:
        key = "steward." + role
        target = targets[role]
        if target["overrides"]:
            overrides = section("agentOverrides")
            entry = overrides.setdefault(key, {})
            for field, value in target["overrides"].items():
                if entry.get(field) != value:
                    changes.append("%s %s: %s -> %s" % (key, field, _show(entry.get(field)), _show(value)))
                    entry[field] = value
            if "thinking" not in target["overrides"] and "thinking" in entry:
                findings.add("info", "thinking-not-in-plan", role,
                             "%s keeps thinking %s: the plan names no thinking level for it." % (key, _show(entry["thinking"])))
        for prov, fields in target["byProvider"].items():
            entry = section("agentOverridesByProvider", prov).setdefault(key, {})
            for field, value in fields.items():
                if entry.get(field) != value:
                    changes.append("agentOverridesByProvider.%s %s %s: %s -> %s"
                                   % (prov, key, field, _show(entry.get(field)), _show(value)))
                    entry[field] = value

        current = sub or {}
        existing = (current.get("agentOverrides") or {}).get(key) or {}
        if not target["named"] and ("model" in existing or "thinking" in existing):
            findings.add("info", "leftover-override", role,
                         "%s is not in the plan; its settings (%s) are left as they are." % (
                             key, ", ".join("%s %s" % (f, _show(existing[f])) for f in ("model", "thinking") if f in existing)))
        for prov, entries in (current.get("agentOverridesByProvider") or {}).items():
            if key in entries and prov not in target["byProvider"]:
                findings.add("info", "leftover-override", role,
                             "agentOverridesByProvider.%s %s is not in the plan; it is left as it is." % (prov, key))
    return new, changes


def build_profile(settings):
    """pi-subagents profile data carrying the whole mapping after apply."""
    sub = settings.get("subagents") if isinstance(settings.get("subagents"), dict) else {}
    out = {"agentOverrides": copy.deepcopy(sub.get("agentOverrides") or {})}
    by_provider = sub.get("agentOverridesByProvider")
    if by_provider:
        out["agentOverridesByProvider"] = copy.deepcopy(by_provider)
    return {"subagents": out}


# ---------------------------------------------------------------- writing

def _proc_start(pid):
    """/proc/<pid>/stat start time, as pi-subagents records it (file-lease.js:9-17)."""
    try:
        with open("/proc/%d/stat" % pid, "r") as handle:
            raw = handle.read()
        return raw[raw.rindex(")") + 1:].split()[19]
    except (OSError, ValueError, IndexError):
        return None


class _Locks:
    """pi's proper-lockfile lock and pi-subagents' settings lease, both
    mkdir-based. Never removes a lock another process holds."""

    def __init__(self, settings_path, wait):
        self.pi_lock = os.path.abspath(settings_path) + ".lock"
        real = os.path.realpath(settings_path)
        self.lease = real + ".write-lock"
        self.wait = wait
        self.held = []
        self.token = str(uuid.uuid4())

    def _take(self, path, owner):
        deadline = time.monotonic() + self.wait
        while True:
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise Refused("another process holds the settings lock %s; try again in a moment "
                                  "(nothing was written)" % path)
                time.sleep(0.02)
                continue
            self.held.append(path)
            if owner:
                body = json.dumps({"token": self.token, "pid": os.getpid(), "hostname": socket.gethostname(),
                                   "processStart": _proc_start(os.getpid())})
                fd = os.open(os.path.join(path, "owner.json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    handle.write(body)
            return

    def __enter__(self):
        try:
            self._take(self.pi_lock, False)
            self._take(self.lease, True)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        for path in reversed(self.held):
            try:
                owner = os.path.join(path, "owner.json")
                if os.path.exists(owner):
                    with open(owner, "r") as handle:
                        if json.load(handle).get("token") != self.token:
                            continue
                    os.unlink(owner)
                os.rmdir(path)
            except (OSError, ValueError):
                pass
        self.held = []
        return False


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _backup(path, data, mode, now):
    stamp = now.strftime("%Y%m%d-%H%M%S")
    base = "%s.bak-%s" % (path, stamp)
    candidate, n = base, 1
    while True:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            break
        except FileExistsError:
            n += 1
            candidate = "%s-%d" % (base, n)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(candidate, mode)
    return candidate


def _default_mode():
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def _atomic_write(path, text):
    """Temp file beside the real file, fsync, rename. Keeps a symlink and the mode."""
    target = os.path.realpath(path)
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    try:
        st = os.stat(target)
        mode, owner = st.st_mode & 0o7777, (st.st_uid, st.st_gid)
    except FileNotFoundError:
        mode, owner = _default_mode(), None
    fd, tmp = tempfile.mkstemp(dir=directory, prefix="." + os.path.basename(target) + ".steward-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        if owner is not None:
            try:
                os.chown(tmp, *owner)
            except OSError:
                pass
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(directory)


def _mode_of(path):
    try:
        return os.stat(path).st_mode & 0o7777
    except OSError:
        return 0o600


# ---------------------------------------------------------------- entry

def apply(facts, env=None, dry_run=True, expect=None, now=None, before_write=None,
          lock_wait=DEFAULT_LOCK_WAIT_S):
    """Compile the user plan and, unless dry_run, write it. Returns a
    JSON-safe result; raises Refused (nothing written) or ValueError (bad
    facts). `expect` is the `hashes` of an earlier dry run: the files must
    still match it. `before_write` is a test hook run after the first read."""
    env = dict(os.environ if env is None else env)
    models = _clean_models(facts)
    agent_dir = mp.agent_dir_from_env(env)
    plan_path, plan = _read_user_plan(agent_dir)
    settings_path = os.path.join(agent_dir, "settings.json")
    profile_path = os.path.join(agent_dir, "profiles", "pi-subagents", PROFILE_NAME + ".json")

    settings_raw, settings, (indent, newline, bom) = _read_settings(settings_path)
    profile_raw = _read_bytes(profile_path)
    hashes = {"settings": content_hash(settings_raw), "profile": content_hash(profile_raw)}
    if expect is not None:
        for key, path in (("settings", settings_path), ("profile", profile_path)):
            if key in expect and expect[key] != hashes[key]:
                raise Refused("%s changed since the preview; run /steward-models apply again (nothing was written)" % path)

    targets, findings = compile_plan(plan, plan_path, models)
    new_settings, changes = build_settings(settings, targets, findings)
    settings_changed = new_settings != settings
    settings_text = _dump(new_settings, indent, newline, bom) if settings_changed else None

    profile_text = _dump(build_profile(new_settings), 2, True)
    profile_changed = profile_raw is None or profile_raw.decode("utf-8", "replace") != profile_text
    if profile_changed:
        changes.append("profile %s: %s" % (profile_path, "create" if profile_raw is None else "update"))

    result = {
        "dryRun": bool(dry_run), "changed": settings_changed or profile_changed,
        "settingsChanged": settings_changed, "profileChanged": profile_changed,
        "planFile": plan_path, "settingsFile": settings_path, "profileFile": profile_path,
        "changes": changes, "findings": findings.items, "backups": [], "hashes": hashes,
        "newSettings": new_settings,
    }
    if dry_run or not result["changed"]:
        result["report"] = render(result)
        return result

    now = now or datetime.datetime.now()
    if before_write:
        before_write()
    with _Locks(settings_path, lock_wait):
        if content_hash(_read_bytes(settings_path)) != hashes["settings"]:
            raise Refused("%s changed while apply was running; run /steward-models apply again "
                          "(nothing was written)" % settings_path)
        if content_hash(_read_bytes(profile_path)) != hashes["profile"]:
            raise Refused("%s changed while apply was running; run /steward-models apply again "
                          "(nothing was written)" % profile_path)
        if settings_changed:
            if settings_raw is not None:
                result["backups"].append(_backup(settings_path, settings_raw, _mode_of(settings_path), now))
            _atomic_write(settings_path, settings_text)
    if profile_changed:
        if profile_raw is not None:
            result["backups"].append(_backup(profile_path, profile_raw, _mode_of(profile_path), now))
        _atomic_write(profile_path, profile_text)
    result["report"] = render(result)
    return result


def render(result):
    """Plain-text summary for the /steward-models apply preview and result."""
    if result["dryRun"]:
        head = "steward model plan apply: preview (nothing written yet)"
    elif result["changed"]:
        head = "steward model plan apply: written"
    else:
        head = "steward model plan apply: nothing to change"
    lines = [head, "", "Plan: %s" % result["planFile"],
             "Settings: %s%s" % (result["settingsFile"], "" if result["settingsChanged"] else " (no change)"),
             "Profile: %s%s" % (result["profileFile"], "" if result["profileChanged"] else " (no change)")]
    if result["changes"]:
        lines += ["", "Changes:"] + ["- %s" % line for line in result["changes"]]
    elif result["dryRun"]:
        lines += ["", "Nothing to change: settings and the steward profile already match the plan."]
    if result["backups"]:
        lines += ["", "Backups:"] + ["- %s" % path for path in result["backups"]]
    shown = [f for f in result["findings"] if f["severity"] in ("error", "warn")]
    notes = [f for f in result["findings"] if f["severity"] == "info"]
    if shown or notes:
        lines += ["", "Findings:"]
        lines += ["- %s %s: %s" % (f["severity"], f["code"], f["message"]) for f in shown + notes]
    return "\n".join(lines)
