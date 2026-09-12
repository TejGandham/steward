# steward

A Claude Code plugin that packages a delegation edict: the main session hands off every non-trivial task to a pinned subagent chosen by task complexity, and all user-facing prose passes a plain-language check.

It gives you three things:
- Seven pinned agent profiles, each fixed to a model and reasoning effort for a specific kind of task.
- Two skills that carry the rules: `delegating` (the edict and routing table, loaded automatically at session start) and `orchestrating` (roles for multi-session work).
- Hooks that enforce the edict: a delegation gate, a prose gate, and a PR-body gate.

## Install

```
claude plugin marketplace add tejgandham/steward
claude plugin install steward@steward --scope user
```

If you use several `CLAUDE_CONFIG_DIR` profiles, each has its own `settings.json` with its own enabled plugins. Install once per profile.

For local development, run Claude Code against the repo directly instead of installing it:

```
claude --plugin-dir /path/to/steward
```

## Dependencies

Steward expects two things to already be installed, and does not ship them:
- The `plainlanguage` skill, at `<config dir>/skills/plainlanguage/SKILL.md`.
- The `update-pr-summary` command, at `<config dir>/commands/update-pr-summary.md`.

`<config dir>` is `$CLAUDE_CONFIG_DIR` if you have set it, otherwise `~/.claude`. The session-start hook checks both paths and warns you if either is missing.

## The subagent profiles

| Profile | Model | Effort | Use for |
|---|---|---|---|
| `steward:coder-sonnet-xhigh` | Sonnet | xhigh | Implementation with a spec and tests (TDD) |
| `steward:deep-reasoner-opus-xhigh` | Opus | xhigh | Architecture, ambiguous design, security review |
| `steward:reviewer-sonnet-high` | Sonnet | high | Everyday PR and diff review |
| `steward:researcher-sonnet-low` | Sonnet | low | Read-only investigation and search |
| `steward:writer-sonnet-medium` | Sonnet | medium | Docs, PR bodies, plain-language rewrites |
| `steward:mechanic-haiku` | Haiku | none | Single lookups, rote edits, running known commands |
| `steward:reviewer-fable-xhigh` | Fable | xhigh | Highest-stakes gap review, only on explicit request |

The full routing table and the reasoning behind it live in `skills/delegating/routing.md`.

## What the hooks do

Steward runs four hooks. Each fails open: if a hook errors or its dependencies are missing, it lets the action through rather than blocking you.

The hooks call `python3`; on Windows you will need a `python3` launcher on PATH.

- **Session start**: injects the `delegating` skill into context and checks that `plainlanguage` and `update-pr-summary` are installed, and that the orchestration registry file exists (creating it if not).
- **Delegation gate**: on a direct `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or a write-shaped Bash command, on the main thread. A write-shaped Bash command is one that changes something on disk or upstream: a redirect to a file, `tee`, `sed -i`, `git commit` or `git push`, `gh pr create` or `gh pr edit`, `mv`/`cp`/`rm`/`mkdir`/`touch`, a package install, or a Python heredoc that writes a file. Read-only commands pass through. The edict allows one such edit; a second in a row is denied (or flagged, in soft mode) until you make an Agent call in between. This only exempts work done inside a subagent; a session started with `--agent` is still gated.
- **Prose gate**: on stop, checks your last reply for em-dashes or common AI-writing tells. If it finds any, it blocks the stop and asks you to revise with the plainlanguage skill.
- **PR-body gate**: on `gh pr create` or `gh pr edit`, denies the command if the PR text contains an em-dash.

Control the delegation gate by writing `off`, `soft`, or `hard` to the file `~/.claude/steward/gate` (or `$CLAUDE_CONFIG_DIR/steward/gate`):
```
mkdir -p ~/.claude/steward && echo soft > ~/.claude/steward/gate
```
This file is read on every call, so you can change the mode without restarting Claude Code. If the file does not exist, the environment variable `STEWARD_GATE` is used instead (it only applies at the next Claude Code start), and if that is also unset, the default is `hard`.
- `hard`: denies a second direct edit in a row.
- `soft`: allows it, but adds a reminder.
- `off`: turns the gate off entirely.

## Local development and tests

```
python3 -m unittest discover -s tests
```

## If you already have these rules in CLAUDE.md

If your `CLAUDE.md` already spells out the delegation and orchestration rules, installing this plugin loads them twice: once from your `CLAUDE.md`, once from the plugin's skills. Shrink your `CLAUDE.md` section to a pointer instead:

```
# Delegation and orchestration: the steward plugin
Rules, routing table and roles come from the `steward` plugin (`steward:delegating`, `steward:orchestrating`). Operator's edict, verbatim: "you MUST update sauron periodically on your status so corrections and clarifications can be issued back to you and in some cases the orchestrator may correct itself, if you see something off say something. Sauron is your orchestrator and your primary. Violation of this edict is not acceptable."
```
