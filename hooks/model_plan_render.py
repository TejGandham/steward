"""Text for the steward model plan on pi (Phase 2b of docs/roadmap/pi-model-plan.md).

Pure functions over the result of ``model_plan.evaluate``. Standard library
only; reads and writes nothing.

- ``render_block(result, capped=True)``: the "Model plan" block appended to
  pi's session-start text. Capped, it holds at most MAX_BLOCK_LINES lines and
  MAX_BLOCK_CHARS characters and ends with "N more: run /steward-models
  check" when anything was left out.
- ``render_report(result)``: the full ``/steward-models check`` report: the
  uncapped block, every finding with severity, code and source file, and the
  file each binding comes from.
- ``session_block(facts, env)``: evaluate plus capped block, or None when the
  facts are malformed or the check failed, so session start fails open.

Every piece of text taken from the result goes through ``_text``: control,
format and line-separator characters become ``?``, em-dashes become ``-``,
box-drawing characters become ``?``, and table cells escape ``|``.
"""

import model_plan as mp

MAX_BLOCK_LINES = 30
MAX_BLOCK_CHARS = 5000
# A finding line, and a STEWARD WARNING line, in the capped block.
MAX_LINE_CHARS = 300
MAX_WARNING_CHARS = 400
# A model string or other value in a table cell.
MAX_CELL_CHARS = 90
MORE_RESERVE = 40  # room kept for the "N more" line

HEADING = "## Model plan on this machine (generated at session start; rebuilt on model switch)"
FAIL_OPEN_CODES = ("facts-invalid", "internal-error")
# Error codes on a role's effective binding that mean "do not launch it".
BLOCK_CODES = ("provider-denied", "provider-not-allowed", "effective-model-unverifiable", "agent-shadowed")
MAIN_WARNING_CODES = ("main-provider-denied", "main-provider-not-allowed", "main-not-in-plan",
                      "main-below-judgment-floor", "main-thinking-drift", "main-startup-thinking-drift")
EM_DASH = chr(0x2014)
MORE_TEXT = "%d more: run /steward-models check"


def _text(value, limit):
    text = mp._sanitize("" if value is None else str(value), limit)
    text = text.replace(EM_DASH, "-")
    return "".join("?" if 0x2500 <= ord(ch) <= 0x257F else ch for ch in text)


def _cell(value, limit=MAX_CELL_CHARS):
    return _text(value, limit).replace("|", "\\|")


def _yes_no(value):
    if value is None:
        return "not checked"
    return "yes" if value else "no"


def usable(result):
    return not any(f.get("code") in FAIL_OPEN_CODES for f in result.get("findings", ()))


def blocked_roles(result):
    """{role: reason} for every profile the main thread must not launch."""
    roles = result.get("roles") or {}
    blocked = {}
    every = None
    if result.get("listsFailClosed"):
        every = "the project's provider lists cannot be read in full, so every provider is blocked"
    for f in result["findings"]:
        if f["severity"] != "error":
            continue
        if f["code"] == "shadow-scan-truncated" and every is None:
            every = f["message"]
        if f["code"] in BLOCK_CODES and f["role"] in roles and f["subject"] == "effective binding":
            blocked.setdefault(f["role"], f["message"])
    if every:
        for role in roles:
            blocked.setdefault(role, every)
    return blocked


def _relaunch_cell(row):
    relaunch = row.get("relaunch")
    return relaunch["launch"] if relaunch and relaunch.get("launch") else "none"


def _escalate_cell(row):
    esc = row.get("escalate")
    if esc:
        if esc.get("role"):
            return "use steward.%s" % esc["role"]
        if esc.get("launch"):
            return esc["launch"]
    plan = row.get("plan")
    if plan and plan.get("escalateCleared"):
        return "keep it on the main thread"
    return "none"


def _runs_on(row, blocked):
    eff = row["effective"]
    model = _cell(eff.get("model")) if eff.get("model") else ""
    notes = []
    if eff.get("inheritsMain"):
        notes.append("inherits the main thread")
    if blocked:
        notes.append("blocked")
    elif eff.get("model") and not eff.get("available"):
        plan = row.get("plan")
        if plan and plan.get("model") and plan["model"] != eff.get("model"):
            notes.append("unavailable; pass model %s" % _cell(mp._launch(plan["model"], plan.get("thinking"))))
        else:
            notes.append("unavailable")
    if not model and not notes:
        return "not known"
    suffix = " ".join("(%s)" % n for n in notes)
    return (model + " " + suffix).strip() if model else suffix


def _thinking(eff):
    level = eff.get("thinking")
    if not level:
        return "not set"
    if eff.get("clampedTo"):
        return "%s (pi clamps to %s)" % (_cell(level, 20), _cell(eff["clampedTo"], 20))
    return _cell(level, 20)


def _table(result, blocked):
    full = bool(result.get("hasPlan"))
    header = ["Profile", "Runs on", "Thinking", "Judgment-grade", "Family"]
    if full:
        header += ["After a provider error, relaunch with model", "After a failed check, relaunch with model"]
    lines = ["| " + " | ".join(header) + " |", "|" + "-|" * len(header)]
    for role in mp.ROLES:
        row = (result.get("roles") or {}).get(role)
        if not row:
            continue
        eff = row["effective"]
        cells = ["steward." + role, _runs_on(row, role in blocked), _thinking(eff),
                 _yes_no(row.get("judgmentGrade")), _cell(row.get("family") or "unknown", 24)]
        if full and role in blocked:
            cells += ["do not launch", "do not launch"]
        elif full:
            cells += [_cell(_relaunch_cell(row)), _cell(_escalate_cell(row))]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _main_line(result):
    main = result.get("main")
    if not main:
        return "Main thread: not known."
    level = _cell(main.get("thinkingLevel"), 20)
    if not result.get("hasPlan"):
        in_plan = "no plan file"
    elif main.get("inPlan") is None:
        in_plan = "not checked"
    else:
        in_plan = _yes_no(main["inPlan"])
    return "Main thread: %s at %s. In the plan: %s. Judgment-grade: %s." % (
        _cell(main.get("model")), level, in_plan, _yes_no(main.get("judgmentGrade")))


def _main_warnings(result, limit):
    main = result.get("main") or {}
    inherited = ", ".join("steward." + r for r in main.get("inheritedBy") or ())
    lines = []
    for f in result["findings"]:
        if f["code"] not in MAIN_WARNING_CODES:
            continue
        line = "STEWARD WARNING: %s Tell the operator." % f["message"]
        if inherited and f["code"] in ("main-not-in-plan", "main-below-judgment-floor",
                                       "main-provider-denied", "main-provider-not-allowed"):
            line += " %s inherit%s this model." % (inherited, "s" if "," not in inherited else "")
        lines.append(_text(line, limit))
    return lines


def _blocked_lines(result, blocked, limit):
    if not blocked:
        return []
    roles = result.get("roles") or {}
    if len(blocked) == len(roles) and (result.get("listsFailClosed") or any(
            f["code"] == "shadow-scan-truncated" for f in result["findings"])):
        if result.get("listsFailClosed"):
            files = ", ".join(_text(p, 200) for p in result["listsFailClosed"][:2])
            why = "The provider lists in %s cannot be read in full, so every provider is blocked." % files
        else:
            why = "The agent scan was cut short, so the provider lists cannot be verified for any profile."
        return [_text("STEWARD WARNING: %s Do not launch any steward profile; keep the work on the main thread "
                      "and tell the operator." % why, limit)]
    return [_text("Do not launch steward.%s: its binding is blocked (%s)" % (role, blocked[role].rstrip(".")) + ".",
                  limit)
            for role in mp.ROLES if role in blocked]


def _cap_lines(result):
    lines = []
    for provider in sorted(result.get("providers") or {}):
        cap = (result["providers"][provider] or {}).get("maxConcurrent")
        if cap:
            lines.append("At most %d children at a time on %s." % (cap, _cell(provider, 64)))
    return lines


def _finding_lines(result, blocked, limit, include_info=False):
    seen = set()
    errors, warns = [], []
    for f in result["findings"]:
        if f["code"] in MAIN_WARNING_CODES:
            continue
        if f["severity"] == "info" and not include_info:
            continue
        if f["role"] in blocked and f["code"] in BLOCK_CODES and f["subject"] == "effective binding":
            continue
        # The same message for several roles or subjects is one problem.
        key = (f["severity"], f["code"], f["message"])
        if key in seen:
            continue
        seen.add(key)
        line = _text("- %s: %s" % (f["severity"], f["message"]), limit)
        (errors if f["severity"] == "error" else warns).append(line)
    return errors + warns


def render_block(result, capped=True):
    """The Model plan block for one evaluate() result."""
    limit = MAX_LINE_CHARS if capped else mp.MAX_MESSAGE_CHARS + 40
    warn_limit = MAX_WARNING_CHARS if capped else limit + 200
    blocked = blocked_roles(result)
    table = _table(result, blocked)
    main_line = _main_line(result)
    blocked_lines = _blocked_lines(result, blocked, warn_limit)
    # A fail-closed notice is a STEWARD WARNING and leads the block.
    warnings = [l for l in blocked_lines if l.startswith("STEWARD WARNING")] + _main_warnings(result, warn_limit)
    blocked_lines = [l for l in blocked_lines if not l.startswith("STEWARD WARNING")]
    caps = _cap_lines(result)
    findings = _finding_lines(result, blocked, limit)

    # Priority when capped: main warnings, blocked profiles, caps, findings.
    flow = [("warn", l) for l in warnings] + [("block", l) for l in blocked_lines] \
        + [("cap", l) for l in caps] + [("find", l) for l in findings]
    fixed = [HEADING, main_line] + table
    if capped:
        used_lines = len(fixed)
        used_chars = sum(len(l) + 1 for l in fixed)
        kept, dropped = [], 0
        for item in flow:
            fits = (used_lines + 2 <= MAX_BLOCK_LINES
                    and used_chars + len(item[1]) + 1 + MORE_RESERVE <= MAX_BLOCK_CHARS)
            if fits and not dropped:
                kept.append(item)
                used_lines += 1
                used_chars += len(item[1]) + 1
            else:
                dropped += 1
        flow = kept
    else:
        dropped = 0

    top = [l for kind, l in flow if kind == "warn"]
    after = [l for kind, l in flow if kind in ("block", "cap")]
    found = [l for kind, l in flow if kind == "find"]
    lines = [HEADING] + top + [main_line] + table + after
    if found:
        lines += found
    if dropped:
        lines.append(MORE_TEXT % dropped)
    return "\n".join(lines)


def _source(value):
    return _text(value, mp.MAX_SOURCE_CHARS) if value else "built-in default"


def render_report(result):
    """The full check report for /steward-models check."""
    lines = [render_block(result, capped=False), "", "## Findings"]
    if not result["findings"]:
        lines.append("None.")
    for f in result["findings"]:
        who = ", ".join(x for x in (("steward." + f["role"]) if f["role"] and f["role"] != "main" else f["role"],
                                    f["subject"]) if x)
        line = "- %s %s%s: %s" % (f["severity"], f["code"], " (%s)" % who if who else "", f["message"])
        if f["source"]:
            line += " Source: %s" % f["source"]
        lines.append(_text(line, mp.MAX_MESSAGE_CHARS + mp.MAX_SOURCE_CHARS + 200))
    lines += ["", "## Where each binding comes from"]
    for role in mp.ROLES:
        row = (result.get("roles") or {}).get(role)
        if not row:
            continue
        eff = row["effective"]
        ms, ts = eff.get("modelSource") or {}, eff.get("thinkingSource") or {}
        line = "- steward.%s: model from %s (%s); thinking from %s (%s)" % (
            role, _source(ms.get("file")), _text(ms.get("key") or "-", 200),
            _source(ts.get("file")), _text(ts.get("key") or "-", 200))
        plan = row.get("plan")
        if plan:
            line += "; plan model from %s, plan thinking from %s" % (
                _source(plan.get("source")), _source(plan.get("thinkingSource")))
        lines.append(line + ".")
    files = result.get("planFiles") or {}
    settings = result.get("settingsFiles") or {}
    lines += ["", "Plan files: user %s; project %s; provider lists %s." % (
        _source(files.get("user")) if files.get("user") else "none",
        _source(files.get("project")) if files.get("project") else "none",
        ", ".join(_source(p) for p in files.get("lists") or ()) or "none"),
        "Settings files: user %s; project %s." % (
        _source(settings.get("user")) if settings.get("user") else "none",
        _source(settings.get("project")) if settings.get("project") else "none")]
    return "\n".join(lines)


def session_block(facts, env):
    """The capped block for session start, or None to leave the text as it is."""
    result = mp.evaluate(facts, env=env)
    if not usable(result):
        return None
    return render_block(result)
