# Steward for Codex CLI and the ChatGPT desktop app

This port runs in the local Codex runtime in Codex CLI and the desktop app now branded ChatGPT. It adds a separate Codex manifest, skill, and hook adapter. Claude Code, pi, and Copilot keep their existing manifests, profiles, and hook behavior. Hosted ChatGPT Work is outside this port's scope.

## Install from a checkout

On this host, Codex CLI 0.160.0 supports the following commands:

```sh
codex plugin marketplace add /absolute/path/to/steward
codex plugin add steward@steward-codex
python3 /absolute/path/to/steward/codex/install_agents.py
```

The marketplace is `.agents/plugins/marketplace.json`. Its `./` source resolves to the repository root. Codex copies the plugin into its cache; it does not load changes directly from the checkout. Reinstall the local plugin after changing its files. Before upgrading the optional agents, move aside any customized `steward-*.toml` files; the installer refuses to replace different content.

The CLI and desktop app use the same installation when they use the same host and `CODEX_HOME`. Restart the desktop app or start a new CLI session after installing. In Plugins, choose the Steward marketplace and confirm Steward is enabled. The optional installer adds seven named agents under `$CODEX_HOME/agents/` (default `~/.codex/agents/`). These TOML files pin both model and effort without changing global agent defaults or sandbox permissions.

Codex does not automatically trust installed hooks. Use `/hooks` in the CLI, or the app's hook review, to review and trust Steward's current definition. This port does not bypass that review or write hook-trust state. Until then, invoke the `steward:delegating` skill explicitly. After trusted SessionStart hooks run, the edict loads at session start.

## Profiles

`codex/skills/delegating/profiles.json` is the source for role briefs and optional standalone TOML agents. The skill also supports explicit model/effort dispatch on clients whose subagent tools do not select named agents.

|Named agent|Model|Effort|Fallback|
|-|-|-|-|
|`steward-coder`|`gpt-6.1-sol`|high|none|
|`steward-deep-reasoner`|`gpt-6-astra`|xhigh|`gpt-6.1-sol` xhigh|
|`steward-reviewer`|`gpt-6.1-sol`|medium|none|
|`steward-researcher`|`gpt-6.1-sol`|medium|none|
|`steward-writer`|`gpt-6.1-sol`|medium|none|
|`steward-mechanic`|`gpt-6-luna`|high|none|
|`steward-top-reviewer`|`gpt-6-astra`|max|`gpt-6.1-sol` xhigh|

These assignments follow the existing OpenAI routing decision, with neutral role names. The [verified evidence](../evaluations/2026-10-09-openai-model-assignment-evidence.md) confirms published model capabilities and records conflicting AA snapshots. It does not establish task-specific defect recall, writing quality, or invented-finding rates. Account model access still controls whether a profile can run. API rates are not subscription prices or Codex usage-limit weights.

The coder may retry a failed check at Sol xhigh. A mechanic that needs judgment escalates to Sol low or the appropriate stronger role. The top reviewer runs only on explicit user request. Read-only roles receive read-only briefs; the generated TOML files inherit the user's runtime permissions.

Operator decision, 2026-10-09: when Astra is not available, the deep-reasoner and top-reviewer fall back to `gpt-6.1-sol` at xhigh. Astra is unavailable when the client's model list omits `gpt-6-astra` or a dispatch with it is rejected as unavailable; weak results from a worker that ran do not trigger the fallback. profiles.json records the pair in a `fallback` field on those two roles only. The main agent tells the user in one line when it falls back. Every other unavailable configuration is still explained rather than silently lowered. The generated TOML agents pin one model and have no fallback key, and the installer does not write the `fallback` field. If `steward-deep-reasoner` or `steward-top-reviewer` fails because Astra is unavailable, the main agent dispatches the same brief with explicit `model: gpt-6.1-sol` and `reasoning_effort: xhigh` and no named agent, or reports the limitation when the client cannot select a model.

## Hooks and limits

`codex/hooks.json` calls `codex/steward.py`, a separate Python adapter. It imports the existing prose-check helpers without changing the shared hook script.

|Event|Behavior|
|-|-|
|SessionStart|Inject the Codex delegation skill as developer context. No Claude orchestration registry.|
|PreToolUse, Bash|Check `gh pr create` and `gh pr edit` bodies, including `--body-file`, against the prose rules.|
|Stop|Check `last_assistant_message` and request one revision. Respect `stop_hook_active`.|

All commands require `python3` and fail open on errors. Operator prose patterns live in `$CODEX_HOME/steward/prose-patterns`. The prose check can also use an installed plainlanguage skill; the Codex edict carries basic rules so that skill is optional.

Delegation is enforced by instructions on this harness. The documented tool-hook contract shares the parent session id with workers and does not provide a reliable worker identity on every PreToolUse call. The adapter therefore does not run the Claude parent edit counter. It cannot accidentally deny a worker's second edit. The PR gate covers the named shell commands, not PR connector tools, and tool hooks are guardrails rather than a complete enforcement boundary. Codex transcript formats are unstable, so the Stop adapter uses only the documented message field and fails open if it is missing.

## Verification

The port was checked with the actual Codex CLI 0.160.0 marketplace-add, plugin-add, and plugin-list commands using an isolated `CODEX_HOME`. The CLI accepted the manifest, installed `steward@steward-codex`, and reported it enabled. Unit tests cover startup injection, configuration paths, shared parent/worker session ids, PR body files, operator patterns, Stop continuation, missing inputs, profile generation, and preservation of customized agent files. The existing Claude, pi, and Copilot suites are also required to pass.

On the current host, `steward@steward-codex` version 0.8.0 was then installed and reported enabled by the real CLI. All seven standalone agents were installed. The cached plugin files and generated agents matched the checkout, and the installed startup adapter returned the Codex edict. The full suite passed: 246 Python tests and 23 pi tests.

This is package and hook-contract verification. It is not a model-quality evaluation or proof that every desktop client exposes identical agent controls. Live hook execution still requires the user's hook-trust review.

## Sources

- [Official plugin packaging and marketplaces](https://developers.openai.com/codex/plugins/build).
- [Official hook schemas, trust, and tool coverage](https://developers.openai.com/codex/hooks).
- [Official custom agents, models, and reasoning settings](https://learn.chatgpt.com/docs/agent-configuration/subagents).
