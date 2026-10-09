# Proposal: steward delegation on GitHub Copilot

Status: built in steward 0.7.0, live-verified 2026-10-09 in the Copilot app (runtime 1.0.94). Scope is the delegation half of steward only (profiles, edict, delegation gate, prose gate, PR gate). The primary/secondary roles stay out, as on pi; see [orchestration-split.md](orchestration-split.md). The sections after "Built in 0.7.0" are the proposal as recorded before the build. Where the build differs, this section wins.

## Built in 0.7.0

Operator decision, 2026-10-09: pinning a model per profile is too hard on Copilot, so assume a Copilot install runs Anthropic models.

|Part|What shipped|
|-|-|
|Manifest|`.github/plugin/plugin.json` points at `copilot/agents/`, `copilot/skills/`, `copilot/hooks.json`. Claude Code still reads `.claude-plugin/plugin.json`. Both are at 0.7.0, as is `package.json`|
|Profiles|`copilot/agents/*.agent.md`: same names, descriptions and bodies as `agents/`. `reasoning-effort` equals the Claude `effort`. `include-custom-instructions: true`. No `model`|
|Model choice|The Copilot edict (`copilot/skills/delegating/SKILL.md`) tells the main agent to pass `model` (the Claude model of the profile's family, copied from the `task` tool's own list) and `reasoning_effort` on every call. If Haiku 5.5 is not listed, the mechanic runs on Sonnet 5.5 at `low`. A profile bound in `~/.copilot/settings.json` `subagents.agents` is listed at session start, and the main agent omits both arguments for it|
|Hooks|`copilot/hooks.json` uses PascalCase events and the commands `STEWARD_HARNESS=copilot python3 "${PLUGIN_ROOT}/hooks/steward_hook.py" <subcommand>`|
|Session start|Prints flat `additionalContext`. Records the main session id before reading the skill. Falls back to a short built-in edict if the skill file is missing. Lists bound profiles. Creates no orchestration registry|
|Delegation gate|Skips any session that session start did not record: subagents, and sessions that predate the install. Reads `path` and apply_patch strings. The Copilot allowlist covers the instruction files and, inside `~/.copilot`, only `steward/`, `settings*.json`, `copilot-instructions.md`, `agents/`, `skills/`, `hooks/` and `session-state/`. App chat sessions under `~/.copilot/chats/` stay gated|
|Prose gate|Main sessions only (Copilot also fires `Stop` for subagents, with the parent's transcript). Waits up to 3 s for this stop's `hook.start` line to reach `events.jsonl`, then checks the last main reply of the turn plus any `task_complete` summary|
|Config|`~/.copilot/steward/` (or `$COPILOT_HOME/steward/`) holds `gate`, `prose-patterns` and `allowlist`. On this machine `prose-patterns` is a symlink to `~/.claude/steward/prose-patterns`|
|Tests|`tests/test_copilot_harness.py`: 236 Python tests and 23 node tests pass|

Live checks, 2026-10-09, in throwaway child sessions:

|Check|Result|
|-|-|
|Edict in context at start|Yes: the `<STEWARD>` block was present, with skill `delegating` (plugin) and no `orchestrating`|
|Profiles loaded|All seven `steward:*` agents were listed by the `task` tool|
|Model and effort|The main agent passed `<provider>/claude-sonnet-5-5` at `low` to the mechanic (Haiku 5.5 is not offered here); `subagent.configured` showed `reasoningEffort: low`|
|Subagent writes|Three separate file creates in one subagent all succeeded|
|Main-thread gate|The second direct create was denied with the Copilot message naming `~/.copilot/steward/gate`|
|Prose gate|It blocked a `task_complete` summary with an em-dash. The agent revised it once, and the next stop passed. The subagent's own stop was not checked|

Findings from the build:

- **Uninstalling breaks running sessions.** Uninstalling a plugin deletes its folder, but sessions already running keep its hooks. Copilot then cannot start them ("spawn /bin/bash ENOENT") and fails closed on `preToolUse`, so every shell command and edit in those sessions is denied. On this machine the old install's path was restored as a symlink to the checkout (`~/.copilot/installed-plugins/_direct/TejGandham--steward`) so sessions started before the switch keep working. Remove it once those sessions are closed.
- **Plan mode counts edits it later blocks.** A create that plan mode blocks still counts as a direct edit, because `preToolUse` runs first.
- **The prose gate raced the transcript.** The final reply had not reached `events.jsonl` when the `Stop` hook first ran (about 6 ms after the message). Waiting for the stop's own `hook.start` line fixed it.
- **The app's own scratch dirs live under `~/.copilot`.** Those are app chat working directories, so a blanket `~/.copilot/**` allowlist would have exempted every chat session.

## Summary

Copilot CLI 1.0.94 (and the Copilot app, which runs the same runtime) already loads steward as a Claude-format plugin. This machine has steward 0.5.1 installed that way (`~/.copilot/config.json`, source `TejGandham/steward`). Its hooks run, but most of steward misfires under Copilot:

- Every profile pins `model: opus|sonnet|haiku|fable`. Copilot does not resolve these aliases, so a dispatch without an explicit model fails outright.
- Every profile sets `effort:`. Copilot reads only `reasoning-effort:`, so no profile gets its effort.
- The session-start edict injection never reaches the model.
- The delegation gate also gates subagents, so a coder subagent is denied after its first write.
- The prose gate never fires.
- The delegation gate works on the main thread, apart from its allowlist. The PR-body gate works as designed.

The Copilot equivalent is a second manifest in this repo, `.github/plugin/plugin.json`, which Copilot reads before `.claude-plugin/plugin.json`. It points at Copilot-specific profiles, edict text and hooks. The hook script gains a `copilot` harness mode, as it did for pi. Model IDs are bound per machine through Copilot's `subagents.agents.<name>` setting, because valid IDs differ by account and provider.

## Evidence base

- **Live, this machine, 2026-10-09.** Copilot app on CLI runtime 1.0.94-3, this session and two throwaway child sessions. User-level probe agents were created, dispatched through the `task` tool with no model or effort arguments, then removed. `~/.copilot/settings.json` was backed up, changed, and restored byte for byte. Results come from `subagent.started` / `subagent.configured` events in `~/.copilot/session-state/<id>/events.jsonl`.
- **History, this machine.** Earlier sessions' `events.jsonl` files (steward 0.5.1 under Copilot, 2026-10-03 to 2026-10-08).
- **karta probe.** `karta docs/backlog/copilot-parity-gaps/FINDINGS.md` (Copilot CLI 1.0.92-3 on Linux and a Windows 11 PC, plus 1.0.91 on a hosted Windows runner and the bundled 1.0.80): payload shapes, exit-code semantics, the `reasoning-effort` key (G21), the SessionStart output shape (G5), and deny reasons (G18).
- **Docs.** [hooks reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference), [plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference), [custom agents configuration](https://docs.github.com/en/copilot/reference/custom-agents-configuration), [Agent Plugins 1.0 changelog](https://github.blog/changelog/2026-08-12-agent-plugins-1-0-in-vs-code-copilot-cli-and-the-copilot-app/), [selective delegation post](https://github.blog/ai-and-ml/how-we-made-github-copilot-cli-more-selective-about-delegation/), and the bundled `changelog.json` in `~/.cache/copilot/pkg/linux-x64/1.0.94-3/`.

## What happens today (steward 0.5.1 under Copilot 1.0.94)

|Part|What Copilot does|Evidence|
|-|-|-|
|Profiles, model|`model: sonnet` is not resolved. Dispatching `steward:mechanic-sonnet-low` with no model argument failed: "Model 'sonnet' is not available. Available models: ..."|live|
|Profiles, effort|`effort:` is ignored. `reasoning-effort: low` was applied (`subagent.configured` showed `reasoningEffort: low`). Steward subagents in past sessions show no `reasoningEffort` at all|live; karta G21; changelog 1.0.66, 1.0.88|
|Why it seemed to work|The main agent passed an explicit `model` on every steward dispatch (`modelSelectionSource: explicit_override`, `taskModelSource: task_argument`, 45 dispatches). Effort was never passed|history|
|Edict injection|Steward returns `hookSpecificOutput.additionalContext`. This session's SessionStart `hook.end` output was `{}`, and the edict was not in context until the skill was loaded by hand. karta found only flat `additionalContext` reaches the model for SessionStart|live; karta G5|
|Delegation gate, main thread|Works. PascalCase hooks get Claude-shaped payloads with Claude tool names (`bash`/`powershell` become `Bash`, `edit`/`apply_patch` become `Edit`, `task` becomes `Agent`; a file create arrived as `Edit` with a patch string on Linux and as `Write` on the Windows PC). The `^(Task|Agent)$` reset fires. The deny is exit 0 plus JSON, so the reason reaches the model|live; hooks reference tool table|
|Delegation gate, subagents|Broken. Copilot sends no `agent_id`. A subagent's tool calls carry the subagent's own id as `session_id`. Steward treats each subagent as a main thread and denies its second write: 25 denials inside subagents in session `15739b0e`, each saying "direct edit #2 on the main thread"|history|
|Gate allowlist|Never matches. Copilot sends `path` (`{path, file_text}`, `{path, old_str, new_str}`) or a raw `*** Begin Patch` string, not `file_path`. Every edit counts, including edits to instruction files|karta G3, G16; `steward_hook.py` `direct_edit_file_path`|
|Gate config dir|Resolves to `~/.claude/steward/` (gate file, prose-patterns), shared with Claude Code. No per-harness setting|live deny message|
|Prose gate|Inert. Copilot's Stop payload has `transcript_path` (Copilot `events.jsonl`) and `stop_hook_active`, but no `last_assistant_message`. Steward's parser looks for Claude `type: "assistant"` lines; Copilot writes `assistant.message` with `data.content`. `_extract_last_assistant_text` returned `None` on this session's transcript. No prose-gate block appears in 227 `agentStop` events on this machine|live; history|
|PR-body gate|Works for `gh pr create` / `gh pr edit` through the shell. The deny JSON with exit 0 delivers the reason|code path shared with the gate|
|Orchestration registry|Created on every Copilot session start, though it is not wanted on Copilot|`cmd_session_start`|

## Copilot building blocks

|Steward need|Claude Code|Copilot (1.0.94)|
|-|-|-|
|Packaging|`.claude-plugin/plugin.json`|Manifest lookup order: `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json`. Component paths (`agents`, `skills`, `hooks`, `extensions`) are set in the manifest. Agent Plugins 1.0 also defines a `com.github.copilot/` directory for Copilot-only files|
|Pinned profile|`agents/*.md` with `model`, `effort`|`*.agent.md` (plain `.md` also loads from plugins) with `model` and `reasoning-effort`. Also `tools`, `user-invocable`, `disable-model-invocation`, and `include-custom-instructions: true` (1.0.86) so a subagent reads AGENTS.md|
|Model binding per profile|Alias in frontmatter|An exact ID the account offers. Observed precedence: explicit `task` argument, then `subagents.agents.<name>` in `~/.copilot/settings.json` (also set from `/subagents`), then frontmatter `model`, then the session model|
|Delegation tool|`Agent` / `Task` with `subagent_type`|`task` with `agent_type`, plus optional `model`, `reasoning_effort`, `context_tier`, `mode`. Plugin agents are namespaced `steward:<name>`|
|Edict in context|SessionStart `additionalContext`|SessionStart flat `additionalContext`. `subagentStart` can prepend text to each subagent prompt (matcher on agent name; the docs say the built-in `general-purpose` agent does not emit it, which is untested, and karta saw `SubagentStop` fire for it)|
|Gate events|PreToolUse, Stop|`preToolUse`/`PreToolUse` (deny: exit 0 plus `permissionDecision: "deny"` keeps the reason; exit 2 drops it), `agentStop`/`Stop` (block: JSON `decision: "block"`; exit 2 alone only warns; 8-block runaway cap), `subagentStart`, `subagentStop`|
|Plugin env|`CLAUDE_PLUGIN_ROOT`|`PLUGIN_ROOT`, `COPILOT_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`, `COPILOT_PLUGIN_DATA`, `CLAUDE_PLUGIN_DATA`, `COPILOT_PROJECT_DIR`, `CLAUDE_PROJECT_DIR`|
|In-process alternative|none|SDK extensions (`onPreToolUse`, `onSessionStart`, `onSubagentStart`, ...), shippable through the plugin `extensions` field. This is the analogue of the pi extension. Not needed if the hook script is fixed|

## Proposed design

### Packaging

Add `.github/plugin/plugin.json` beside the Claude manifest:

```json
{
  "name": "steward",
  "version": "0.7.0",
  "description": "Delegation edict for GitHub Copilot: pinned subagent profiles, plain-language prose, and gates that enforce both.",
  "agents": "copilot/agents/",
  "skills": ["copilot/skills/"],
  "hooks": "copilot/hooks.json"
}
```

Claude Code keeps reading `.claude-plugin/plugin.json` and the root `agents/`, `skills/`, `hooks/`. Copilot checks `.github/plugin/plugin.json` before `.claude-plugin/plugin.json`, so it never loads the Claude-only skill text or the orchestrating skill. `copilot plugin install TejGandham/steward` keeps working. The `com.github.copilot/` layout from Agent Plugins 1.0 is the newer alternative; it was not tried.

### Profiles: `copilot/agents/*.agent.md`

Same seven names, so `steward:<name>` stays stable across harnesses. Each file:

- `reasoning-effort:` with the profile's level. Kebab-case only: `effort` and `reasoningEffort` are ignored.
- No `model:`. A wrong ID fails the dispatch, and valid IDs differ by account and provider. On this machine the app offers Claude 5.x only under a provider prefix (`5130b6bd-b44d-4974-818c-8fced7c642f3/claude-opus-5-5` and so on). `claude-sonnet-5.5`, `claude-sonnet-5-5`, and a two-item list of both all failed with "not available". The list did not fall back. With no `model`, an unbound profile inherits the session model instead of failing.
- `include-custom-instructions: true`, so subagents see AGENTS.md (attribution rule, search rules).
- Body: the Claude profile body, with "subagent_type" wording changed to the Copilot terms.

Haiku 5.5 is not offered on this machine: the app offers `claude-haiku-4.5`, and the provider has no Haiku. Steward 0.6.0's `mechanic-haiku-medium` needs a fallback here, either Sonnet 5.5 at low effort (the 0.5.1 mapping) or Haiku 4.5.

### Model binding: per machine

Bind each profile in `~/.copilot/settings.json`. This was verified live: an override keyed by the namespaced plugin name replaced the broken `sonnet` alias, and the dispatch ran on Sonnet 5.5 at low effort (`modelSelectionSource: configured_preference`).

```json
"subagents": {
  "agents": {
    "steward:coder-opus-medium":         {"model": "<opus id>",   "effortLevel": "medium"},
    "steward:deep-reasoner-opus-xhigh":  {"model": "<opus id>",   "effortLevel": "xhigh"},
    "steward:reviewer-sonnet-high":      {"model": "<sonnet id>", "effortLevel": "high"},
    "steward:researcher-sonnet-low":     {"model": "<sonnet id>", "effortLevel": "low"},
    "steward:writer-sonnet-medium":      {"model": "<sonnet id>", "effortLevel": "medium"},
    "steward:mechanic-haiku-medium":     {"model": "<haiku or sonnet id>", "effortLevel": "medium"},
    "steward:reviewer-fable-xhigh":      {"model": "<fable id>",  "effortLevel": "xhigh"}
  }
}
```

The `/subagents` picker writes the same keys. The session-start hook should warn, by name, about each steward profile with no `subagents.agents` entry. Then the operator finds out at session start instead of on the first dispatch.

The edict also tells the main agent to pass `model` and `reasoning_effort` on a `task` call when the profile is not bound. Copilot honors explicit model and effort preferences from instructions (changelog 1.0.85), and the `task` tool's `model` enum lists the IDs that are valid in that session.

Caveat: the app and the terminal CLI share `settings.json`. On this machine the terminal CLI could not start with `gpt-5.4-mini` or `gpt-5.6-luna`, and its CAPI catalog lists Claude 5.x as disabled: the account is on Copilot Free, and those models list Pro (Sonnet) or Pro+ (Opus, Fable) and up. A provider-prefixed ID bound for the app may not resolve in a terminal session. Not tested.

### Edict: `copilot/skills/steward-delegating/SKILL.md`

A Copilot rewrite of the edict, as `pi/skills/steward-delegating/` is for pi:

- The delegation call is `task` with `agent_type: "steward:<profile>"`. It says when to pass `model`/`reasoning_effort`, using the binding rule above.
- It states that it overrides the harness's built-in delegation guidance. Copilot's system prompt tells the model not to delegate work it can finish in five or fewer tool calls. That rule shipped as "smarter subagent delegation" in 1.0.42 and is still in the 1.0.94 prompt. Without an explicit override the two rules conflict, and the gate becomes the only enforcement.
- It drops the role check and every reference to orchestration.

### Hooks: `copilot/hooks.json` plus a `copilot` harness in `steward_hook.py`

Keep PascalCase event names, so payloads stay Claude-shaped and the shared script and its tests still apply. Each command sets `STEWARD_HARNESS=copilot`, for example `STEWARD_HARNESS=copilot python3 "${PLUGIN_ROOT}/hooks/steward_hook.py" gate`.

|Event|Matcher|Change for the `copilot` harness|
|-|-|-|
|`SessionStart`|none|Print flat `{"additionalContext": ...}` with the Copilot edict. Record `session_id` as a main session in the state dir. Warn about unbound profiles and a missing plainlanguage skill (`~/.agents/skills/` or `~/.copilot/skills/`). Skip the orchestration registry|
|`PreToolUse`|`Edit|Write|Bash`|Subagent exemption: skip any `session_id` that SessionStart never recorded. In 15739b0e, all 8 `sessionStart` hooks fired on main sessions and none inside the 48 subagents, while subagent tool calls carried the subagent id as `session_id`. Read `path` and `file_text`, and the `*** Add File:` / `*** Update File:` lines of a patch string, before `file_path`. Copilot allowlist: `AGENTS.md`, `.github/copilot-instructions.md`, `.github/instructions/`, `.github/agents/`, `.copilot/`. Config dir `~/.copilot/steward/` (or `$COPILOT_HOME/steward/`) for `gate` and `prose-patterns`|
|`PreToolUse`, `PostToolUse`|`Agent`|Unchanged: reset the counter. Already fires|
|`Stop`|none|Read the last main-agent turn from Copilot `events.jsonl`: `assistant.message` events with no `agentId`, joining `data.content` after the last `user.message`. Keep `stop_hook_active` and the JSON `decision: "block"` form|
|`SubagentStart` (new)|`steward:.*`|Optional: return `additionalContext` with the standing brief rules (output cap, plain language), so every steward subagent gets them without the main agent repeating them. Use a valid regex; karta found that `"*"` makes Copilot skip the hook|

The PR-body gate needs no Copilot change. If the GitHub MCP server's PR-writing tools are enabled (they are not in the default CLI subset), add their names to the gate's matcher.

Windows needs `powershell` entries ending in `; exit $LASTEXITCODE`, plus a Python launcher (karta G1, G17). That is only needed if steward on Copilot has to run on Windows.

### Tests

Extend `tests/test_steward_hook.py` with Copilot-shaped fixtures. Each one below is a payload or file observed above, not an invented shape:

- a `PreToolUse` payload with `{path, file_text}`, one with a patch string, and one with an unrecorded `session_id`;
- a `Stop` payload pointing at a Copilot `events.jsonl` excerpt;
- the flat SessionStart output.

Add a parity test, as the pi profiles have, that keeps `copilot/agents/` in step with `agents/`: same names and descriptions, and `reasoning-effort` equal to the Claude `effort`.

## Using OpenAI models

The binding mechanism works the same for any vendor: a `subagents.agents` entry takes an OpenAI ID as readily as a Claude one.

**Live, 2026-10-09.** `steward:researcher-sonnet-low` was bound to `gpt-5-mini` at `low`, `steward:reviewer-sonnet-high` to `gpt-6-luna` at `xhigh`, and `steward:writer-sonnet-medium` to `gpt-5-mini` at `xhigh`. All three were selected as bound (`modelSelectionSource: configured_preference`). All three calls then failed with "402 You have exceeded your monthly quota". The Claude 5.x models run through the app's own provider (`5130b6bd-...`) and were not affected.

**This account's Copilot catalog (1.0.94-3, read from the debug log).** The account is on Copilot Free (`free_limited_copilot`). Enabled OpenAI models: `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5-mini`, `gpt-4.1`. Disabled: `gpt-6-astra`, `gpt-6-sol`, `gpt-6.1-sol`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`. The catalog lists the plans for GPT-6 Astra, Sol and 6.1 Sol as Pro+, Business, Enterprise and Max (`restricted_to`). So "disabled" here comes from the plan, not from a setting that can be switched on. GPT-6 Luna lists Free among its plans.

**Effort levels differ by model.** `gpt-6-*` and `gpt-5.6-*` offer `none` to `max`. `gpt-5-mini` and `mai-code-1.1-flash` offer `low`, `medium`, `high`. `gpt-4.1` offers none. A level the model lacks still shows in `subagent.configured`: `gpt-5-mini` showed `xhigh`. But the level is not sent (changelog 1.0.88), and karta G21 saw the request go out at `medium`.

**Routing matrix.** The evidence is in `docs/evaluations/2026-10-09-openai-model-assignment-evidence.md`. Each cell follows the model panel's majority. Scores are the Artificial Analysis Intelligence Index v4.3.2, the same scale as the Claude evidence, with USD per index task.

|Profile|Model|Effort|Score, $/task|Claude counterpart|Basis|
|-|-|-|-|-|-|
|coder|`gpt-6.1-sol`|high|50, 0.32|Opus 5.5 medium: 51, 1.34|Panel 5 of 8. On a missed gate, rerun at xhigh (51, 0.39)|
|deep-reasoner|`gpt-6-astra`|xhigh|52, 2.31|Opus 5.5 xhigh: 56, 3.46|Panel 5 of 8 wanted Astra (3 xhigh, 2 max). Open, see below|
|reviewer|`gpt-6.1-sol`|medium|48, 0.21|Sonnet 5.5 high: 47, 0.88|Panel 8 of 8. No OpenAI code-review evaluation exists|
|researcher|`gpt-6.1-sol`|medium|48, 0.21|Sonnet 5.5 low: 36, 0.35|Panel 5 of 8: low drops 6 points. Least-confident cell|
|writer|`gpt-6.1-sol`|medium|48, 0.21|Sonnet 5.5 medium: 41, 0.48|Panel 8 of 8. No writing evaluation exists|
|mechanic|`gpt-6-luna`|high|32, 0.03|Haiku 5.5 medium: 34, 0.05|Panel 4 of 8. Luna scores 13% on Terminal-Bench at max, so rerun on `gpt-6.1-sol` low after a miss|
|reviewer-fable|`gpt-6-astra`|max|53, 3.26|Fable 5.1 xhigh: 53.2|Panel 8 of 8. Only on explicit operator request|

What the numbers say:

- **Price at equal scores:** OpenAI costs 3 to 4 times less per index task. 6.1 Sol at xhigh matches Opus 5.5 medium (51) for $0.39 against $1.34. 6.1 Sol at medium edges Sonnet 5.5 high (48 against 47) for $0.21 against $0.88.
- **Top end:** no OpenAI setting reaches Opus 5.5 at xhigh (56) or max (58). Astra at max, 53, is the ceiling. For the deep-reasoner's work, Claude stays ahead on this index.
- **Agentic coding:** there is no comparison in the same harness. In Codex, AA's Coding Agent Index gives 6.1 Sol 60 and Astra 62. A third-party relay gives Opus 5.5 66 in Claude Code.
- **Effort as the dial:** five of seven profiles land on 6.1 Sol, and effort does the rest, as it does between Opus and Sonnet.
- **Latency:** on Astra and 6.1 Sol, the first token takes about 58 s at high and about 5 min at max. That is acceptable for background profiles. The reviewer at medium stays at a few seconds.

Open, for the operator:

- **deep-reasoner:** three options.
  - Astra xhigh, at $2.31.
  - 6.1 Sol xhigh, at $0.39, with 3 votes.
  - Keep Opus 5.5 xhigh in a mixed setup.

  Astra xhigh and 6.1 Sol max tie on the index at 52. Astra xhigh leads on Terminal-Bench (60 against 56) for 3x the cost.
- **researcher effort:** medium or low. A known-answer test of invented findings would settle it.
- **Not run on this machine:** none of this has run here. The Copilot Free allowance (200 credits) is used up until 2026-11-01 00:00 UTC, and 6.1 Sol and Astra need Copilot Pro+ or higher.

**Mixing vendors.** Binding the reviewers to GPT while the coder stays on Claude gives each review a second model family. Copilot's built-in rubber-duck agent does this by design ("complementary model strategy", changelog 1.0.64).

**Profile names.** The names carry Claude family names (`coder-opus-medium`). Under per-machine binding, the name no longer says which model runs. There are two ways to handle it:

- Keep the names. They are the keys shared with the Claude Code routing table and `~/AGENTS.md`.
- Give the Copilot port role-and-effort names, such as `coder-medium`.

This is a decision for the operator.

**BYOK.** The CLI's documented BYOK mode (`COPILOT_PROVIDER_BASE_URL`, `COPILOT_MODEL`) points a whole session at one provider. Whether a subagent binding can then name a different model on that provider was not tested.

## Doing it today with no code change

1. `copilot plugin update steward` (installed 0.5.1; repo is 0.6.0).
2. Add the `subagents.agents` block above with this machine's IDs. That fixes model and effort for every profile.
3. Load the `delegating` skill by hand at session start. The prose gate stays off, and the gate still blocks subagents after their first write until the hook script changes.

## Open questions

- The effort actually sent was read from `subagent.configured`, not from the request log. karta saw `configured` claim `xhigh` while a model without `xhigh` received `medium`. Claude 5.x offers `low` to `max`, so this should hold, but it is unverified.
- Whether `effortLevel` in `subagents.agents` or frontmatter `reasoning-effort` wins when both are set.
- `subagents.disabledSubagents`, `excludedBuiltinAgents` and `includedBuiltinAgents` are present in the 1.0.94 runtime but undocumented. Hiding `general-purpose` and `explore` could push the model toward steward profiles. Untested.
- `${PLUGIN_ROOT}` versus `${CLAUDE_PLUGIN_ROOT}` in a `.github/plugin/` manifest's hook commands (both env vars are set; substitution was probed only for the Claude manifest).
- VS Code reads the same `.agent.md` files, but its `model` takes "Name (vendor)" strings or a priority list, and agent-scoped hooks are preview-only (`chat.useCustomAgentHooks`). Not in scope here.
- Copilot cloud agent: hooks fire there (`preToolUse`, `agentStop`), and agents load from `.github/agents/` on the default branch. Not in scope here.
