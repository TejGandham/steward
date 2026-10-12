# steward

For Codex CLI and the ChatGPT desktop app (formerly the Codex app), see the separate [Codex port](docs/roadmap/codex-port.md). It packages seven OpenAI role profiles and Codex-specific hooks. The Claude Code installation and behavior described below are unchanged.

A Claude Code plugin that packages a delegation edict: the main session hands off every non-trivial task to a pinned subagent chosen by task complexity, and all user-facing prose passes a plain-language check. It also installs as a pi package and as a GitHub Copilot plugin; see [Pi](#pi) and [GitHub Copilot](#github-copilot).

It gives you three things:
- Seven pinned agent profiles, each fixed to a model and reasoning effort for a specific kind of task.
- Two skills that carry the rules: `delegating` (the edict and routing table, loaded automatically at session start) and `orchestrating` (roles for multi-session work). Orchestration is planned to move into its own plugin; see [docs/roadmap/orchestration-split.md](docs/roadmap/orchestration-split.md).
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

Steward expects the `plainlanguage` skill to already be installed at `<config dir>/skills/plainlanguage/SKILL.md`, and does not ship it. The session-start hook warns you if it is missing.

An `update-pr-summary` command at `<config dir>/commands/update-pr-summary.md` is optional. If you have one, the edict uses it to draft PR bodies; if not, PR bodies are drafted from the branch's diff against its base. Steward does not check for it.

`<config dir>` is `$CLAUDE_CONFIG_DIR` if you have set it, otherwise `~/.claude`.

## The subagent profiles

| Profile | Model | Effort | Use for |
|-|-|-|-|
| `steward:coder-opus-medium` | Opus | medium | Implementation with a spec and tests (TDD) |
| `steward:deep-reasoner-opus-xhigh` | Opus | xhigh | Architecture, ambiguous design, security review |
| `steward:reviewer-sonnet-high` | Sonnet | high | Everyday PR and diff review |
| `steward:researcher-sonnet-low` | Sonnet | low | Read-only investigation and search |
| `steward:writer-sonnet-medium` | Sonnet | medium | Docs, PR bodies, plain-language rewrites |
| `steward:mechanic-haiku-medium` | Haiku | medium | Single lookups, rote edits, running known commands |
| `steward:reviewer-opus-max` | Opus | max | Highest-stakes gap review, on request or when a deep-reasoner pass is not enough |

As of 0.9.0 the pinned profiles run on three models: Haiku 5.5, Sonnet 5.5 and Opus 5.5. The top reviewer moved from Fable 5.1 at xhigh to Opus 5.5 at max, because Opus 5.5 now scores higher. Fable 5.1 runs only when you ask for it by name: the edict then calls the top reviewer with a one-off model override to Fable, at the effort you name (xhigh if you name none). The mechanic runs on Haiku 5.5 at medium effort, and pure coding runs on Opus 5.5 at medium effort. Haiku 4.5 and Opus 5 were dropped earlier. On Claude Code the profiles use the `haiku`, `sonnet` and `opus` aliases, which resolve to those three models on Claude Code 2.1.295; the Fable override uses the `fable` alias.

Each profile sets its own effort. Claude Code 2.1.292 and later also let a single Agent call pass an `effort` that overrides the profile's. The edict passes one only when it, a skill, or you name a level.

The full routing table lives in `skills/delegating/routing.md`. The evidence tables are in `docs/evaluations/2026-10-09-model-assignment-evidence.md`, and the reasoning is in `skills/delegating/routing.md`.

## What the hooks do

Steward runs four hooks. Each fails open: if a hook errors or its dependencies are missing, it lets the action through rather than blocking you.

The hooks call `python3`; on Windows you will need a `python3` launcher on PATH.

- **Session start**: injects the `delegating` skill into context and checks that `plainlanguage` is installed, and that the orchestration registry file exists (creating it if not).
- **Delegation gate**: on a direct `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, or a write-shaped Bash command, on the main thread. A write-shaped Bash command is one that changes something on disk or upstream: a redirect to a file, `tee`, `sed -i`, `git commit` or `git push`, `gh pr create` or `gh pr edit`, `mv`/`cp`/`rm`/`mkdir`/`touch`, a package install, or a Python heredoc that writes a file. Read-only commands pass through. The edict allows one such edit; a second in a row is denied (or flagged, in soft mode) until you make an Agent call in between. This only exempts work done inside a subagent; a session started with `--agent` is still gated.
- **Prose gate**: on stop, checks your last reply for em-dashes, common AI-writing tells, and your own banned phrases (see below). It blocks the stop and asks you to revise with the plainlanguage skill when it finds an em-dash, two or more different tells, or any banned phrase.
- **PR-body gate**: on `gh pr create` or `gh pr edit`, denies the command if the PR text contains an em-dash, two or more AI-writing tells, or any of your banned phrases.

### Your own banned phrases

To add your own rules to the prose and PR-body gates, list them in `~/.claude/steward/prose-patterns` (or `$CLAUDE_CONFIG_DIR/steward/prose-patterns`; on pi, `~/.pi/agent/steward/prose-patterns`). Each line is a case-insensitive regular expression, and a single match blocks. `^` and `$` match at the start and end of a line. Lines starting with `#` are comments, and a line that is not a valid expression is skipped. Text in code blocks and inline code is never checked, so you can still quote a banned word in backticks.

```
# words I never want in a reply
load[- ]?bearing
\bfootguns?\b
# narrating a tool call at the start of a line
^\s*(let me|now i'?ll)\b
```

The file is read on every check, so edits apply right away. Without it, the gates use only the built-in checks.

Control the delegation gate by writing `off`, `soft`, or `hard` to the file `~/.claude/steward/gate` (or `$CLAUDE_CONFIG_DIR/steward/gate`):
```
mkdir -p ~/.claude/steward && echo soft > ~/.claude/steward/gate
```
This file is read on every call, so you can change the mode without restarting Claude Code. If the file does not exist, the environment variable `STEWARD_GATE` is used instead (it only applies at the next Claude Code start), and if that is also unset, the default is `hard`.
- `hard`: denies a second direct edit in a row.
- `soft`: allows it, but adds a reminder.
- `off`: turns the gate off entirely.

## Pi

Steward also runs on [pi](https://pi.dev). On pi you get the same edict, the same seven profiles, and the same three gates. The primary and secondary roles (the `orchestrating` skill and its registry) are Claude Code only for now; [docs/roadmap/orchestration-split.md](docs/roadmap/orchestration-split.md) describes how they could reach pi.

Pi has no subagents of its own. Steward uses the community [pi-subagents](https://github.com/nicobailon/pi-subagents) extension for them, so you install both.

### What you need

- pi 1.0 or newer (`pi --version`).
- `python3` on your PATH. The pi gates run the same `hooks/steward_hook.py` as Claude Code.
- The `plainlanguage` skill, in `~/.agents/skills/plainlanguage/` or `~/.pi/agent/skills/plainlanguage/`.
- Optional: an `update-pr-summary` prompt template at `~/.pi/agent/prompts/update-pr-summary.md`. If it is there, the edict uses it to draft PR bodies.

When a session starts, steward tells the model if the plainlanguage skill is missing or pi-subagents is not loaded.

### Install

```
pi install npm:pi-subagents
pi install git:github.com/tejgandham/steward
```

Then restart pi, or run `/reload` in a running session. Both commands write to `~/.pi/agent/settings.json`; add `-l` to install for the current project only.

This installs the latest pi-subagents, and `pi update` keeps it current. Steward was last tested with pi-subagents 0.77.0. pi-subagents ships new versions every few days, so if an update breaks delegation, hold it at a known version with `pi install npm:pi-subagents@0.77.0`.

To check the install, ask pi to "list the available subagents". You should see seven agents whose names start with `steward.`.

### How it works on pi

The pi package has three parts:
- `pi/skills/steward-delegating/`: the edict, written for pi. A pi extension adds it to the system prompt of every main session.
- `pi/agents/`: the seven profiles. pi-subagents loads them as `steward.<name>`, for example `steward.coder`.
- `pi/extensions/steward/`: the extension that adds the edict and runs the gates. It passes each pi event to `hooks/steward_hook.py`, so both harnesses share one set of rules and tests.

The model delegates with pi-subagents' `subagent` tool, for example `subagent({ agent: "steward.mechanic", task: "...", async: false })`.

### Profiles on pi

Each profile ships with a default model ID and thinking level. Settings override them (recipes below), and the [model plan](#model-plan-on-pi) shows what each profile really runs on:

| Profile | Model | Thinking |
|-|-|-|
| `steward.coder` | `anthropic/claude-opus-5-5` | medium |
| `steward.deep-reasoner` | `anthropic/claude-opus-5-5` | xhigh |
| `steward.reviewer` | `anthropic/claude-sonnet-5-5` | high |
| `steward.researcher` | `anthropic/claude-sonnet-5-5` | low |
| `steward.writer` | `anthropic/claude-sonnet-5-5` | medium |
| `steward.mechanic` | `anthropic/claude-haiku-5-5` | medium |
| `steward.top-reviewer` | `anthropic/claude-opus-5-5` | max |

Version 0.11.0 added the model plan and 0.12.0 its `apply` command (see [Model plan on pi](#model-plan-on-pi)). Version 0.10.0 renamed the pi profiles to role-only names. The old names, such as `steward.coder-opus-medium`, still launch the same profile through pi-subagents aliases, and `steward.reviewer-fable-xhigh` launches `steward.top-reviewer`. Settings are different: pi-subagents reads config such as `subagents.agentOverrides` under the new name only, so rename any override keys you saved under an old name, or let `/steward-models apply` move them.

A bare `agent: "coder"`, without the `steward.` prefix, now launches `steward.coder` instead of pi-subagents' builtin `worker` agent. pi-subagents lists `coder` as an alias of `worker`, but it matches an agent's own short name before it looks at aliases. To run `worker`, call it by its own name.

If you ask for Fable by name, the edict runs `steward.top-reviewer` with `model: "anthropic/claude-fable-5-1:xhigh"`. The `:xhigh` suffix sets the thinking level; it becomes the level you name, if you name one.

pi needs version 1.1.0 or later for `anthropic/claude-haiku-5-5`, and a custom provider needs its own `claude-haiku-5-5` model entry.

If you reach Claude through another provider, override the model in `~/.pi/agent/settings.json`. The thinking level stays as the profile sets it unless you override that too:

```json
{
  "subagents": {
    "agentOverrides": {
      "steward.coder": { "model": "openrouter/anthropic/claude-opus-5.5" }
    }
  }
}
```

To run some profiles on other providers today, add overrides to `~/.pi/agent/settings.json`. `agentOverrides` sets a model and thinking level per profile. `agentOverridesByProvider` changes a profile only while the main thread runs on the provider you name. The providers and models below are an example; use any you have credentials for:

```json
{
  "subagents": {
    "agentOverrides": {
      "steward.coder": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.researcher": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.writer": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.mechanic": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "low" },
      "steward.reviewer": { "model": "amorphic/claude-sonnet-5-5", "thinking": "high" },
      "steward.deep-reasoner": { "model": "inherit", "thinking": "xhigh" },
      "steward.top-reviewer": { "model": "amorphic/claude-opus-5-5", "thinking": "max" }
    },
    "agentOverridesByProvider": {
      "amorphic": {
        "steward.reviewer": { "model": "openai-codex/gpt-6.1-sol", "thinking": "medium" }
      }
    }
  }
}
```

Here `inherit` makes the deep-reasoner run on whatever model the main thread uses, and the last block swaps the reviewer to a different model family when the main thread is on `amorphic`. Then run `/reload`, and `/subagents-models` to confirm what each profile now runs on. Use the role-only keys: overrides saved under an old name, such as `steward.coder-opus-medium`, do not apply.

A repository's committed `.pi/settings.json` overrides your user settings field by field. This repo's own file pins every profile to `amorphic/claude-*`, so inside it the `model` values above lose, and `/subagents-models` shows what actually applies. If you decline project trust, pi-subagents 0.77.0 and later ignores that file.

Subagents see your `AGENTS.md` files and your skills catalog. A foreground subagent does not load your pi extensions; a background one does. Steward's gates never apply inside a subagent.

### Model plan on pi

Version 0.11.0 adds a model plan; 0.12.0 adds `/steward-models apply`. **The plan is not applied on its own.** Profiles launch on what pi-subagents settings (`subagents.agentOverrides`) and the profile defaults say, and the block warns where those differ from your plan. Run `/steward-models apply` to write your user plan into those settings. Run it again after you edit the plan, or after `/subagents-load-profile` replaced the mapping.

**What `apply` does**
- It reads your user plan only (`~/.pi/agent/steward/model-plan.json`). A repo's plan file, its `.pi/settings.json` and its provider lists play no part, because user settings apply in every repo. To keep a repo off a provider, pin its profiles in that repo's `.pi/settings.json`.
- It first shows every change, old value to new, and the files it will write, then asks. Without a UI (print mode) it only shows the changes; `/steward-models apply --yes` writes them.
- It writes only the `model` and `thinking` of the `steward.*` entries in `subagents.agentOverrides` and `subagents.agentOverridesByProvider` in `~/.pi/agent/settings.json`. Everything else stays, including other agents' entries and fields such as `machine`. Entries under old profile names, such as `steward.coder-opus-medium`, move to the new names.
- Each profile gets the first model in its list that pi has credentials for. `main` becomes `inherit`. A profile with no usable model is left as it is, and the report says so. Profiles and fields your plan does not name are left as they are, with one exception: for a profile your plan names, apply removes `model` and `thinking` from its `agentOverridesByProvider` entry for any provider the plan no longer lists under `byMainProvider`. Otherwise those old values would still win when the main thread is on that provider. Other fields in that entry, such as `fast`, `disabled` or `machine`, stay. An entry left empty is removed, and the provider's object stays, as `{}` if nothing else is in it. A profile with no usable model keeps its provider entries too. A provider entry apply writes always carries `thinking`, so an old level there cannot win either.
- Before writing it saves a copy, `settings.json.bak-<date>-<time>`. It refuses, and writes nothing, when the plan has an error, the settings file is not valid JSON (a number too large to store, such as `1e400`, counts as invalid), or the plan, the settings file or the profile changed after the preview. A run with nothing to change writes nothing.
- It also writes the pi-subagents profile `~/.pi/agent/profiles/pi-subagents/steward.json` with the whole mapping, other agents' entries included. `/subagents-load-profile steward` restores it. Loading it resets every agent override, steward or not, to what it was at the last apply, so a change you made to another agent since then is lost. An entry the profile format does not allow, such as `"model": false` (settings accept it, profiles do not), is left out of the profile, and the report says so.
- `/subagents-check-profile steward` tests each model with a short live call. A profile set to `inherit` (the deep-reasoner in the example plan) shows as a failure there, because `inherit` is not a model name. That failure is expected.
- If the settings file is written but the profile is not (a full disk, say), the report says so and lists the backups it made (one for each file that existed before), and pi still reloads. Run `/steward-models apply` again before you load the steward profile.
- Then it reloads pi and shows a fresh check.

You write which model and thinking level each profile should use, plus fallbacks and escalations. At session start, and again after you switch model or thinking level, steward adds a "Model plan" block to the main thread's instructions. The block shows:
- what each profile really runs on;
- what to relaunch with after a provider error;
- what to escalate to after a failed check;
- which profiles are blocked.

Without a plan file the block still lists what each profile runs on.

**Where the plan lives**
- `~/.pi/agent/steward/model-plan.json`, or `$PI_CODING_AGENT_DIR/steward/model-plan.json`.
- Per repo: `.pi/steward-model-plan.json`. In a trusted repo it wins over your user plan.
- A repo's `allowProviders` and `denyProviders` are read even when you decline project trust. If a list cannot be read, every profile is marked blocked.

**The provider lists do not stop a launch.** `allowProviders` and `denyProviders` change only what the block tells the main thread about the `steward.*` profiles and what `/steward-models check` reports. pi-subagents still launches whatever its settings say, and other agents, such as its builtin `worker` and `scout`, are not checked at all. To actually stop a launch on a provider, set an enforced, strict `subagents.modelScope` in pi-subagents settings; in an untrusted project pi-subagents ignores the project's copy of that setting.

A small plan:

```json
{
  "version": 1,
  "roles": {
    "*": {
      "model": "anthropic/claude-sonnet-5-5",
      "thinking": "medium",
      "fallback": ["openrouter/anthropic/claude-sonnet-5.5"],
      "escalate": "main:high"
    },
    "reviewer": {
      "thinking": "high",
      "escalate": "role:deep-reasoner"
    },
    "deep-reasoner": {
      "model": "anthropic/claude-opus-5-5",
      "thinking": "xhigh",
      "fallback": null,
      "escalate": null
    },
    "top-reviewer": {
      "model": "anthropic/claude-opus-5-5",
      "thinking": "max",
      "fallback": null,
      "escalate": null
    }
  }
}
```

Every role inherits the `"*"` entry. The reviewer escalates to the `steward.deep-reasoner` profile, which keeps its own model and thinking. Deep-reasoner and top-reviewer clear both the fallback and the escalation: a judgment role should never drop to the Sonnet fallback in `"*"`, and a failed check there stays on the main thread. [docs/roadmap/pi-model-plan.md](docs/roadmap/pi-model-plan.md) describes every field.

**How the main thread uses the block**
- It passes `model` only to relaunch after a provider error, to escalate after a failed check, or when you ask. Fable by name still works.
- A row that says "pass model X" gets `model: "X"` on every launch.
- If there is no relaunch model, it never picks one itself. After an overload, rate-limit or timeout error it retries the same profile once without `model`; otherwise it does small or read-only work itself or tells you.
- A relaunch, escalation or "pass model" string that an enforced `subagents.modelScope` or `subagents.maxThinking` would refuse is shown as `none`; the full report says why.
- It never launches a blocked profile.
- When every profile is marked below the judgment floor, judgment work stays on the main thread. `not checked` sets no floor.

**The seven guardrails** the edict states:
1. Judgment floor: architecture, plans, security review and final synthesis go only to a profile marked judgment-grade `yes`, or stay on the main thread when every profile is `no`. With `not checked` or no block, the routing table decides.
2. Cheap models get bounded tasks with a done-condition that a test, type check, lint or command can prove.
3. One failed check gets one relaunch on the escalation model. With no escalation model, or after a second failure, the work goes to the main thread or `steward.deep-reasoner`.
4. Fallback is not escalation: a provider error gets one relaunch, on the block's relaunch model when there is one, and never on a model the block does not name.
5. Cross-family review: a child's output is reviewed by a profile from another model family when the block shows one; otherwise by the routing table's reviewer.
6. Respect provider caps: never more children at once on a provider than its stated cap.
7. Thinking where it pays: the main thread never raises a cheap role's thinking per call; high thinking belongs to the main thread and the judgment roles.

**How the main thread delegates.** For independent children it uses the built-in `parallel` workflow. For dependent steps it makes separate `subagent` calls, one after another. It uses a workflow script only as a file path. A script written in the reply never reaches pi-subagents on pi 1.1.0 with pi-subagents 0.77.0, so the edict does not use that form.

**Checking and debugging.** `/steward-models check` prints the full report on screen. It does not go into the model's context. To debug the hook, start pi with `STEWARD_HOOK_LOG=<file>`. Each session-start, `model-plan` and `model-plan-apply` hook call then appends one JSON line to that file, holding the full payload and the hook's reply. The session-start payload includes pi's whole model catalog (a few hundred KB with many providers) and your working directory, once per session start and per model or thinking switch. Gate calls are never logged, because they carry your commands, file contents and replies. Delete the file when you are done.

### Gates on pi

The gates behave as described in [What the hooks do](#what-the-hooks-do), with these differences:
- The delegation gate watches pi's `edit` and `write` tools and write-shaped `bash` commands. A `subagent` call resets it once pi-subagents accepts the launch. A call that fails, or one such as `subagent({ action: "list" })` that starts no work, does not.
- If pi-subagents is not loaded, or it is loaded but neither `subagent` nor `subagents_enable` is active in the current session, the model has no way to delegate, so the delegation gate reminds instead of blocking. The note it adds says which case applies. The PR gate still blocks.
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

Eager mode plus `/reload` is also how a conversation that started before pi-subagents was installed gets the tool. Pi restores a conversation's recorded tools when it resumes, so restarting pi and resuming that conversation does not add it; starting a new session does.

### Developing steward for pi

Load your checkout instead of the published package:

```
pi install /path/to/steward
```

A local path install reads the files in place, so edits apply on the next pi start or `/reload`.

## GitHub Copilot

Steward also installs as a GitHub Copilot plugin. You get the same edict, the same seven profiles, and the same three gates. The primary and secondary roles (orchestration) are not part of the Copilot port. The Copilot cloud agent is not covered.

Windows is not supported yet, because the hook commands start with a POSIX `STEWARD_HARNESS=copilot python3 ...` prefix.

### What you need

- `python3` on your PATH.
- The `plainlanguage` skill, in `~/.agents/skills/plainlanguage/` or `~/.copilot/skills/plainlanguage/`.

### Install

From GitHub:

```
copilot plugin install TejGandham/steward
```

Copilot reads `.github/plugin/plugin.json` before `.claude-plugin/plugin.json`, so it gets the Copilot files: `copilot/agents/`, `copilot/skills/delegating/`, and `copilot/hooks.json`. Claude Code keeps using the Claude manifest.

From a checkout, for development:

```
copilot plugin marketplace add /path/to/steward
copilot plugin install steward@steward
```

Copilot loads the plugin live from the checkout. Nothing is copied, and edits apply to the next session.

Close running Copilot sessions before you uninstall or switch steward, or restart them afterwards. Uninstalling or replacing a plugin deletes its folder, but sessions that are still running keep its hooks. Copilot cannot start them (`spawn /bin/bash ENOENT`) and fails closed for PreToolUse hooks, so those sessions get every shell command and file edit denied.

### How the edict gets in

A SessionStart hook adds the Copilot edict as session context at the start of every main session.

### Profiles and models on Copilot

The Copilot profiles carry role-only names. Each profile sets a reasoning effort and `include-custom-instructions: true`, so subagents read `AGENTS.md` and other instruction files:

| Profile | Model | Effort |
|-|-|-|
| `steward:coder` | Claude Opus 5.5 | medium |
| `steward:deep-reasoner` | Claude Opus 5.5 | xhigh |
| `steward:reviewer` | Claude Sonnet 5.5 | high |
| `steward:researcher` | Claude Sonnet 5.5 | low |
| `steward:writer` | Claude Sonnet 5.5 | medium |
| `steward:mechanic` | Claude Haiku 5.5 | medium |
| `steward:top-reviewer` | Claude Opus 5.5 | max |

Copilot does not resolve the `opus`, `sonnet`, `haiku`, and `fable` aliases, and model IDs differ by account and provider (for example a provider-prefixed `<provider>/claude-opus-5-5`). So the Copilot profiles set only `reasoning-effort`.

Instead, the edict tells the main agent to pass two fields on every `task` call: `model`, the role's Claude model from the table above, copied from the task tool's own model list, and `reasoning_effort`, the role's level. `steward:top-reviewer` runs when you ask for the top reviewer or when a deep-reasoner pass is not enough. If you ask for Fable by name, the main agent runs the top reviewer on the Claude Fable 5.1 model from the task tool's list, at the effort you name (xhigh if you name none). If Claude Haiku 5.5 is not listed, the mechanic runs on Claude Sonnet 5.5 at `low`.

### Optional: bind a profile on your machine

To fix a profile's model and effort on one machine, add it to `~/.copilot/settings.json`. The `/subagents` picker writes the same keys.

```json
{
  "subagents": {
    "agents": {
      "steward:coder": { "model": "<id>", "effortLevel": "medium" }
    }
  }
}
```

The binding keys use the role-only names: `steward:coder`, `steward:mechanic`, and so on. Bindings saved under the old names, such as `steward:coder-opus-medium`, no longer match; rename those keys.

The session-start note then lists the bound profiles, and the main agent omits `model` and `reasoning_effort` for them.

### Gates on Copilot

The gates behave as described in [What the hooks do](#what-the-hooks-do), with these differences:
- The config directory is `~/.copilot` (or `$COPILOT_HOME`). The gate mode file is `~/.copilot/steward/gate`, the banned phrases file is `~/.copilot/steward/prose-patterns`, and the extra allowlist is `~/.copilot/steward/allowlist`.
- Subagents are not gated. Copilot does not tell a hook whether a call comes from a subagent, so steward records each main session when it starts and skips any other session. A session that was already running when steward was installed is not gated.
- These files are exempt: `AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/`, `.github/agents/`, `.github/skills/`, and `.github/copilot/`. Inside `~/.copilot`, only `steward/`, `settings.json`, `settings.local.json`, `copilot-instructions.md`, `agents/`, `skills/`, `hooks/`, and `session-state/` are exempt. Copilot app chat sessions run under `~/.copilot/chats/`, and edits there are still gated.
- The prose gate reads Copilot's own transcript (`events.jsonl`) and checks the last reply of the turn and any `task_complete` summary. It waits up to 3 seconds for Copilot to write the final reply before checking. It sends the turn back once.
- The PR-body gate works as on Claude Code.

Set the gate mode with:

```
mkdir -p ~/.copilot/steward && echo soft > ~/.copilot/steward/gate
```

To share one banned-phrases file with Claude Code, symlink it:

```
ln -s ~/.claude/steward/prose-patterns ~/.copilot/steward/prose-patterns
```

## Local development and tests

```
python3 -m unittest discover -s tests
node --test 'tests/pi/*.test.mjs'
```

The Python tests cover the hook script for both harnesses and check that the pi profiles stay in step with the Claude Code ones. They also cover the Copilot harness (`tests/test_copilot_harness.py`), including parity between `copilot/agents/` and `agents/`. The node tests run the pi extension's handlers against the real hook script. Node 22.18 or newer runs the TypeScript extension without a build step.

## If you already have these rules in CLAUDE.md

If your `CLAUDE.md` already spells out the delegation and orchestration rules, installing this plugin loads them twice: once from your `CLAUDE.md`, once from the plugin's skills. Shrink your `CLAUDE.md` section to a pointer instead:

```
# Delegation and orchestration: the steward plugin
Rules, routing table and roles come from the `steward` plugin (`steward:delegating`, `steward:orchestrating`). Operator's edict, verbatim: "you MUST update sauron periodically on your status so corrections and clarifications can be issued back to you and in some cases the orchestrator may correct itself, if you see something off say something. Sauron is your orchestrator and your primary. Violation of this edict is not acceptable."
```
