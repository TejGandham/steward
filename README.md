# steward

A Claude Code plugin that packages a delegation edict: the main session hands off every non-trivial task to a pinned subagent chosen by task complexity, and all user-facing prose passes a plain-language check. It also installs as a pi package; see [Pi](#pi).

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
| `steward:coder-opus-medium` | Opus | medium | Implementation with a spec and tests (TDD) |
| `steward:deep-reasoner-opus-xhigh` | Opus | xhigh | Architecture, ambiguous design, security review |
| `steward:reviewer-sonnet-high` | Sonnet | high | Everyday PR and diff review |
| `steward:researcher-sonnet-low` | Sonnet | low | Read-only investigation and search |
| `steward:writer-sonnet-medium` | Sonnet | medium | Docs, PR bodies, plain-language rewrites |
| `steward:mechanic-sonnet-low` | Sonnet | low | Single lookups, rote edits, running known commands |
| `steward:reviewer-fable-xhigh` | Fable | xhigh | Highest-stakes gap review, only on explicit request (Opus 5.5 covers most of this now) |

As of 0.3.0 the profiles run on three models, Sonnet 5, Opus 5.5, and Fable 5.1; pure coding runs on Opus 5.5 at medium effort; Haiku 4.5 and Opus 5 were dropped, and `routing.md` says why.

The full routing table and the reasoning behind it live in `skills/delegating/routing.md`.

## What the hooks do

Steward runs four hooks. Each fails open: if a hook errors or its dependencies are missing, it lets the action through rather than blocking you.

The hooks call `python3`; on Windows you will need a `python3` launcher on PATH.

- **Session start**: injects the `delegating` skill into context and checks that `plainlanguage` and `update-pr-summary` are installed, and that the orchestration registry file exists (creating it if not).
- **Delegation gate**: on a direct `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or a write-shaped Bash command, on the main thread. A write-shaped Bash command is one that changes something on disk or upstream: a redirect to a file, `tee`, `sed -i`, `git commit` or `git push`, `gh pr create` or `gh pr edit`, `mv`/`cp`/`rm`/`mkdir`/`touch`, a package install, or a Python heredoc that writes a file. Read-only commands pass through. The edict allows one such edit; a second in a row is denied (or flagged, in soft mode) until you make an Agent call in between. This only exempts work done inside a subagent; a session started with `--agent` is still gated.
- **Prose gate**: on stop, checks your last reply for em-dashes or common AI-writing tells. If it finds any, it blocks the stop and asks you to revise with the plainlanguage skill.
- **PR-body gate**: on `gh pr create` or `gh pr edit`, denies the command if the PR text contains an em-dash or two or more AI-writing tells.

Control the delegation gate by writing `off`, `soft`, or `hard` to the file `~/.claude/steward/gate` (or `$CLAUDE_CONFIG_DIR/steward/gate`):
```
mkdir -p ~/.claude/steward && echo soft > ~/.claude/steward/gate
```
This file is read on every call, so you can change the mode without restarting Claude Code. If the file does not exist, the environment variable `STEWARD_GATE` is used instead (it only applies at the next Claude Code start), and if that is also unset, the default is `hard`.
- `hard`: denies a second direct edit in a row.
- `soft`: allows it, but adds a reminder.
- `off`: turns the gate off entirely.

## Pi

Steward also runs on [pi](https://pi.dev). On pi you get the same edict, the same seven profiles, and the same three gates. The primary and secondary roles (the `orchestrating` skill and its registry) are Claude Code only for now.

Pi has no subagents of its own. Steward uses the community [pi-subagents](https://github.com/nicobailon/pi-subagents) extension for them, so you install both.

### What you need

- pi 1.0 or newer (`pi --version`).
- `python3` on your PATH. The pi gates run the same `hooks/steward_hook.py` as Claude Code.
- The `plainlanguage` skill, in `~/.agents/skills/plainlanguage/` or `~/.pi/agent/skills/plainlanguage/`.
- An `update-pr-summary` prompt template at `~/.pi/agent/prompts/update-pr-summary.md`.

Steward checks the last two when a session starts and tells the model if either is missing. It also warns when pi-subagents is not loaded.

### Install

```
pi install npm:pi-subagents@0.75.0
pi install git:github.com/tejgandham/steward
```

Then restart pi, or run `/reload` in a running session. Both commands write to `~/.pi/agent/settings.json`; add `-l` to install for the current project only.

pi-subagents ships new versions every few days, so the command above pins the version steward was tested with. Move the pin when you choose to upgrade.

To check the install, ask pi to "list the available subagents". You should see seven agents whose names start with `steward.`.

### How it works on pi

The pi package has three parts:
- `pi/skills/steward-delegating/`: the edict, written for pi. A pi extension adds it to the system prompt of every main session.
- `pi/agents/`: the seven profiles. pi-subagents loads them as `steward.<name>`, for example `steward.coder-opus-medium`.
- `pi/extensions/steward/`: the extension that adds the edict and runs the gates. It passes each pi event to `hooks/steward_hook.py`, so both harnesses share one set of rules and tests.

The model delegates with pi-subagents' `subagent` tool, for example `subagent({ agent: "steward.mechanic-sonnet-low", task: "...", async: false })`.

### Profiles on pi

Each profile pins a full model ID and a thinking level:

| Profile | Model | Thinking |
|-|-|-|
| `steward.coder-opus-medium` | `anthropic/claude-opus-5-5` | medium |
| `steward.deep-reasoner-opus-xhigh` | `anthropic/claude-opus-5-5` | xhigh |
| `steward.reviewer-sonnet-high` | `anthropic/claude-sonnet-5` | high |
| `steward.researcher-sonnet-low` | `anthropic/claude-sonnet-5` | low |
| `steward.writer-sonnet-medium` | `anthropic/claude-sonnet-5` | medium |
| `steward.mechanic-sonnet-low` | `anthropic/claude-sonnet-5` | low |
| `steward.reviewer-fable-xhigh` | `anthropic/claude-fable-5-1` | xhigh |

If you reach Claude through another provider, override the model in `~/.pi/agent/settings.json`. The thinking level stays as the profile sets it unless you override that too:

```json
{
  "subagents": {
    "agentOverrides": {
      "steward.coder-opus-medium": { "model": "openrouter/anthropic/claude-opus-5.5" }
    }
  }
}
```

Subagents see your `AGENTS.md` files and your skills catalog. A foreground subagent does not load your pi extensions; a background one does. Steward's gates never apply inside a subagent.

### Gates on pi

The gates behave as described in [What the hooks do](#what-the-hooks-do), with these differences:
- The delegation gate watches pi's `edit` and `write` tools and write-shaped `bash` commands. A `subagent` call resets it once pi-subagents accepts the launch. A call that fails, or one such as `subagent({ action: "list" })` that starts no work, does not.
- If pi-subagents is not loaded, the model has no way to delegate, so the delegation gate reminds instead of blocking. The PR gate still blocks.
- Edits to `AGENTS.md` and to anything under a `.pi/` directory are exempt, as `CLAUDE.md` and `.claude/` are on Claude Code.
- The prose gate sends the reply back once, with a message saying what to fix. A revised reply is not sent back a second time.
- The gate mode file is `~/.pi/agent/steward/gate` (or `$PI_CODING_AGENT_DIR/steward/gate`):

```
mkdir -p ~/.pi/agent/steward && echo soft > ~/.pi/agent/steward/gate
```

If `python3` is missing, steward shows a warning and lets everything through.

Some turns start without a prompt from you, for example when a background subagent finishes. Pi builds those turns without the usual system prompt additions, so steward adds the edict to that turn's messages instead. Nothing extra is saved in the session.

### Optional: show the subagent tool from the start

On some models pi-subagents first offers a small `subagents_enable` tool and adds `subagent` only after the model calls it. The edict tells the model to do that. To skip the step, create `~/.pi/agent/extensions/subagent/config.json` with:

```json
{ "toolActivation": "eager" }
```

### Developing steward for pi

Load your checkout instead of the published package:

```
pi install /path/to/steward
```

A local path install reads the files in place, so edits apply on the next pi start or `/reload`.

## Local development and tests

```
python3 -m unittest discover -s tests
node --test 'tests/pi/*.test.mjs'
```

The Python tests cover the hook script for both harnesses and check that the pi profiles stay in step with the Claude Code ones. The node tests run the pi extension's handlers against the real hook script. Node 22.18 or newer runs the TypeScript extension without a build step.

## If you already have these rules in CLAUDE.md

If your `CLAUDE.md` already spells out the delegation and orchestration rules, installing this plugin loads them twice: once from your `CLAUDE.md`, once from the plugin's skills. Shrink your `CLAUDE.md` section to a pointer instead:

```
# Delegation and orchestration: the steward plugin
Rules, routing table and roles come from the `steward` plugin (`steward:delegating`, `steward:orchestrating`). Operator's edict, verbatim: "you MUST update sauron periodically on your status so corrections and clarifications can be issued back to you and in some cases the orchestrator may correct itself, if you see something off say something. Sauron is your orchestrator and your primary. Violation of this edict is not acceptable."
```
