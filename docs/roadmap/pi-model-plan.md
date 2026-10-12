# Proposal: a model plan for steward on pi

Status: proposed, 2026-10-09; refreshed 2026-10-11. Operator decisions are recorded below (2026-10-09, 2026-10-11 and 2026-10-12, including the Phase 2 release review). Phase 1 (role-only pi names with aliases) was built in steward 0.10.0 (`f9e319a`) and is not yet checked in a live pi session. Phase 0 is a settings recipe (now in the README "Profiles on pi" section). Phase 2 is split into four slices: 2a, 2b and 2c are merged (2c in `e164385`); 2d is built on branch `pi-model-plan-2d` (`99a5cd3`, `a7d9a23` and the docs commit), and the final deep-reasoner review of all of Phase 2 ran 2026-10-12; its fixes are on the same branch (see "Release review of Phase 2"). Phase 3 (`apply`) is next; Phases 4 and 5 are not built. In 0.11.0 the plan is checked and shown, not applied (see Phases). The Phase 2 spike ran 2026-10-11 and its answers are recorded below.

## Summary

The operator wants to configure once, per pi installation, which model runs the main thread and which models run steward's delegated profiles, across providers. Example: a main thread on `openai-codex/gpt-6.1-sol` or `amorphic/claude-opus-5-5` at `xhigh`, and most profiles on DeepSeek V4.1 Flash. Steward does not choose the main thread's model; the plan only names the models it expects.

Recommendation: steward builds no model router and owns no main-thread setting. Pi already sets the main thread's model and thinking level, and pi-subagents already binds one model and one thinking level per agent for every launch path. Steward adds four thin pieces on top:

1. **Role-only pi profile names** (`steward.coder`, `steward.deep-reasoner`, ...) with the old names kept as pi-subagents `aliases`, as the Copilot and Codex ports already did.
2. **A steward-owned plan file**, `$PI_CODING_AGENT_DIR/steward/model-plan.json` (default `~/.pi/agent/steward/model-plan.json`). It holds per-role model and thinking plus what pi-subagents refuses to store: ordered fallbacks, escalation targets, provider concurrency caps, and the list of judgment-grade models.
3. **A `/steward-models` command.** `check` is a dry run that prints the resolved per-role mapping, where each binding comes from, and every problem. `apply` compiles the plan into the `steward.*` keys of `subagents.agentOverrides` and `subagents.agentOverridesByProvider` in user settings, with a backup.
4. **A generated "Model plan" block in the edict** at session start, rebuilt on every model switch. It names the model each profile will actually run on, the model to relaunch with after a provider error, and the model to escalate to after a failed check, and it states the guardrails.

Fallback stays an explicit relaunch by the main thread. pi-subagents removed same-launch fallback on purpose and says a different model needs a later explicit launch. Virtual-model failover inside a child is deferred, because foreground children cannot resolve a virtual model that the parent registered. Claude Code, Copilot and Codex behavior does not change.

Path abbreviations used below: `PIDOCS` is `/home/dev/.pi/agent/install/releases/1.1.0/node_modules/@earendil-works/pi-coding-agent/docs`; `PIDIST` is the sibling `dist/core`; `PS` is `/home/dev/.pi/agent/npm/node_modules/pi-subagents` (0.77.0). Repo paths are relative to the steward repo at `f9e319a` (0.10.0, branch `pi-role-names`, on main `a8bb20c`); citations were re-verified against that tree, pi 1.1.0 and pi-subagents 0.77.0 on 2026-10-11.

## Build versus reuse

|Need|Reuse from pi or pi-subagents|Steward builds|
|-|-|-|
|Main-thread model and thinking|`defaultProvider`, `defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels` (`PIDOCS/settings.md:11-16`); `/model` then Ctrl+S, `/thinking` then Ctrl+S, `/scoped-models` (`PIDOCS/models.md:29-33`)|A check only: warn when the session's model is not in the plan, is below the judgment floor, or starts at a different thinking level|
|Per-role model and thinking|`subagents.agentOverrides.<agent>.model` and `.thinking`; `model: "inherit"` (`PS/docs/models.md:14,20`)|The plan file; `apply` writes only `steward.*` keys|
|Choices that depend on the main model|`subagents.agentOverridesByProvider.<parentProvider>.<agent>`, keyed on the active parent model's provider (`PS/docs/models.md:45-64`)|`byMainProvider` in the plan compiles to it|
|Policy limits|`subagents.modelScope` (policy only, `PS/docs/models.md:191-221`), `subagents.maxThinking` (`PS/docs/models.md:125-138`)|The check reads both and reports conflicts. It never writes them|
|Live probe of each model|`/subagents-check-profile <name>`: registry lookup plus a one-shot `pi -p --model X --no-tools` probe with a 45 s timeout (`PS/docs/models.md:251`, `PS/src/profiles/profiles.js:226-234,501-525`)|`apply` also writes a `steward` profile file so that probe can run on the plan|
|Live mapping|`/subagents-models` (`PS/docs/models.md:167-176`)|`/steward-models check` adds plan versus effective binding, sources, fallbacks, warnings|
|Fallback after a provider error|None. `fallbackModels` was removed in 0.68.0 (`PS/CHANGELOG.md:471`) and is rejected by the parsers (`PS/src/agents/agents.js:760-761,1937-1938`, `PS/src/profiles/profiles.js:66-67`)|Rendered relaunch model plus an edict rule|
|Escalation after a failed check|None|Rendered escalation model plus an edict rule|
|Concurrency|`parallel.concurrency` (default 4), `globalConcurrencyLimit` (default 20), `maxActiveAsyncRunsPerSession` (unset), all in `~/.pi/agent/extensions/subagent/config.json` and none per provider (`PS/docs/configuration.md:422-430,454-474,494-505`)|Per-provider `maxConcurrent` in the plan; the check warns; the edict states the cap|

### Why a steward plan file instead of only validating pi-subagents settings

Validating hand-written `subagents.agentOverrides` would be thinner by one file, and Phase 0 below does exactly that with no code. The plan file still pays for itself for four reasons:

- **Fallbacks and escalations have nowhere else to live.** pi-subagents throws on `fallbackModels` in settings and profiles (references above), and it has no escalation field.
- **pi-subagents profile switches erase the mapping.** `/subagents-load-profile` replaces the whole `agentOverrides` object in user settings (`PS/src/profiles/profiles.js:359-386`, "A profile owns the complete agent mapping"). The plan file survives that, and `apply` restores the `steward.*` keys.
- **Role keys outlive runtime names.** The plan says `coder`. `apply` maps that to whatever runtime name the profile has and migrates stale keys. pi-subagents config keys must use canonical names (`PS/docs/agents.md:417`), so a rename otherwise silently orphans overrides.
- **One shape across ports.** Codex already keeps per-role model, effort, a `retry` (escalation) entry (`codex/skills/delegating/profiles.json:7,45`) and, since 0.8.1, a `fallback` entry on deep-reasoner and top-reviewer (`profiles.json:17,55`, `gpt-6.1-sol` at `xhigh`).

Steward does not own the main thread. Pi saves the startup model and thinking level from its own UI (`PIDOCS/models.md:29-31`) and restores a resumed session's model by design (`PIDOCS/models.md:35`). A second writer would only conflict with it.

## The plan file

Location: `get_config_dir(env)/steward/model-plan.json`, the same directory as the gate file (`hooks/steward_hook.py:42-62`, `pi/skills/steward-delegating/SKILL.md:44`). A per-repo override file is also a v1 requirement (see Scope).

### Operator's case: most roles on DeepSeek Flash through Ollama Cloud, judgment roles elsewhere

```json
{
  "version": 1,
  "main": {
    "models": ["openai-codex/gpt-6.1-sol", "amorphic/claude-opus-5-5"],
    "thinking": "xhigh"
  },
  "judgmentModels": ["openai-codex/gpt-6*", "amorphic/claude-opus-5*", "anthropic/claude-opus-5*", "amorphic/claude-fable-5*"],
  "providers": {
    "ollama-cloud": { "maxConcurrent": 3 },
    "fireworks": {}
  },
  "roles": {
    "*": {
      "model": "ollama-cloud/deepseek-v4.1-flash",
      "thinking": "high",
      "fallback": ["fireworks/accounts/fireworks/models/deepseek-v4p1-flash"],
      "escalate": "main:high"
    },
    "mechanic": { "thinking": "low", "escalate": "main:low" },
    "reviewer": {
      "model": "amorphic/claude-sonnet-5-5",
      "thinking": "high",
      "fallback": ["openai-codex/gpt-6.1-sol:medium"],
      "escalate": "role:deep-reasoner",
      "byMainProvider": {
        "amorphic": { "model": "openai-codex/gpt-6.1-sol", "thinking": "medium" }
      }
    },
    "deep-reasoner": {
      "model": "main",
      "thinking": "xhigh",
      "fallback": ["amorphic/claude-opus-5-5", "openai-codex/gpt-6.1-sol"],
      "escalate": null
    },
    "top-reviewer": {
      "model": "amorphic/claude-opus-5-5",
      "thinking": "max",
      "fallback": ["anthropic/claude-opus-5-5:max"],
      "escalate": null
    }
  }
}
```

What this does: coder, researcher, writer and mechanic run on Flash through Ollama Cloud and fall back to the same model on Fireworks. Thinking is `high`, except mechanic on `low`, never `off` (see the Flash thinking section). Deep-reasoner runs on whatever the main thread runs (`inherit`), at `xhigh` where the model supports it. The three non-Flash roles never inherit the `"*"` escalation to `main:high`: the reviewer escalates to `steward.deep-reasoner` (`role:deep-reasoner`, which launches on that profile's own model and thinking), and deep-reasoner and top-reviewer clear it with `"escalate": null`, so a failed check on either stays on the main thread. Their fallbacks are never Flash either: deep-reasoner relaunches on Opus or Sol, top-reviewer on `anthropic/claude-opus-5-5:max` (same model and level, other provider), the reviewer on Sol at `medium`. `main.models` and `main.thinking` are only what the check compares the session against; steward never sets the main thread. The reviewer is never DeepSeek, and it is never the main thread's family either: Sonnet when the main thread is Sol, Sol when the main thread is Opus on `amorphic`. Top-reviewer is Opus 5.5 at `max` (operator decision 2026-10-11; it was Fable 5.1 at `xhigh` when this plan was written). `~/.pi/agent/models.json` declares `max` for `amorphic/claude-opus-5-5` (`thinkingLevelMap` `xhigh` and `max`, `maxTokens` 128000), so pi does not clamp it. A request for Fable by name runs the top reviewer with per-call `model: "anthropic/claude-fable-5-1:xhigh"`; `amorphic/claude-fable-5-1` also declares `max`.

The "everything on Flash" variant is the `"*"` entry alone, with no other roles listed. It is allowed but is not the operator's choice. The check and the edict then warn that deep-reasoner and top-reviewer are below the judgment floor and that the reviewer shares the coder's family, and the edict tells the main thread to keep judgment work inline.

Trade-offs of Ollama first, Fireworks as fallback, on this machine's catalog (`pi --list-models`, 2026-10-09): Ollama Pro allows 3 concurrent requests (the `providers` block carries that cap, and the check and edict state it). `ollama-cloud/deepseek-v4.1-flash` declares only 16.4K max output in `~/.pi/agent/models.json`, which can truncate large coder edits (the check warns below 32K). Its entry also declares no `xhigh` or `max` level, so pi clamps both to `high` (see the Flash thinking section). `fireworks/accounts/fireworks/models/deepseek-v4p1-flash` declares 1M context and 384K max output, so it is the better fallback for long outputs, but it is paid per token. The ids differ between providers (`deepseek-v4p1-flash` against `deepseek-v4.1-flash`), and pi-subagents' fuzzy matching never switches providers (`PS/docs/models.md:178-190`), so each fallback is written out per provider. Pi's catalog declares `off`, `low`, `high`, `max` for the Fireworks Flash entry (anthropic-messages API, base URL `https://api.fireworks.ai/inference`, `maxTokens` 384000, context 1000000; `pi-ai/dist/providers/data/fireworks.json`; probed 2026-10-11), so `max` is not clamped there, unlike on Ollama.

Fireworks fix, 2026-10-11 (operator-approved): pi has had a built-in Fireworks provider since pi 0.68.1 (2026-04-22). The hand-written `fireworks` entry in `~/.pi/agent/models.json` broke it two ways: a provider-level `baseUrl` of `https://api.fireworks.ai/inference/v1` sent the Flash model to `/v1/v1/messages` (HTTP 404), and `apiKey` was the bare string `FIREWORKS_API_KEY`, which pi 1.1.0 sends as a literal key (env interpolation needs `$NAME`, `PIDOCS/models.md:64`), so every Fireworks call through pi got HTTP 401, kimi-k3 included. The entry was removed (backup `models.json.bak-20261011-234310`) and the key stored with `/login fireworks` in `~/.pi/agent/auth.json`. Pi's key order is `--api-key`, `auth.json`, `models.json` `apiKey`, then the provider env var (`PIDOCS/models.md:23`). Verified with `FIREWORKS_API_KEY` unset: `pi auth check --provider fireworks` ready, and live Flash `:high`, Flash `:max` and kimi-k3 runs replied ok. The Fireworks fallback therefore works through pi.

### Fields

|Field|Meaning|Compiles to|
|-|-|-|
|`version`|Schema version, `1`|Nothing|
|`main.models`|Main-thread models the operator expects, `provider/id`|Nothing: check and edict only|
|`main.thinking`|Expected main thinking level|Nothing: compared with `modelThinkingLevels[main]`, then `defaultThinkingLevel`|
|`judgmentModels`|Globs (only `*` is special, as in `modelScope.allow`) for models fit for judgment work|Nothing: floor check and an edict column. Absent means the floor is not checked, and the check says so|
|`providers.<id>.maxConcurrent`|The provider's concurrent-request cap|Nothing: check and edict line|
|`providers.<id>.enabled`|`false` makes `apply` skip that provider|Which candidate `apply` binds|
|`roles.<role>.model`|Primary `provider/id`, or `main`|`agentOverrides["steward.<role>"].model`; `main` becomes `"inherit"`|
|`roles.<role>.thinking`|`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`|`agentOverrides["steward.<role>"].thinking`|
|`roles.<role>.fallback`|Ordered `provider/id[:level]` list; `null` or `[]` clears an inherited `"*"` value|`apply` binds the first available candidate; the next available one is rendered as the relaunch model. A candidate equal to the bound model is skipped|
|`roles.<role>.escalate`|`provider/id[:level]`, `main[:level]`, or `role:<role>` (another steward role, no `:level`: the target profile keeps its own model and thinking; an unknown role or the role itself is a schema error); `null` clears an inherited `"*"` value|Rendered as the escalation model, or as the target profile `steward.<role>` with its effective model and thinking|
|`roles.<role>.byMainProvider.<p>`|`{ model, thinking }` used when the main thread's provider is `p`|`agentOverridesByProvider.<p>["steward.<role>"]`|
|`roles["*"]`|Defaults merged under every role, field by field|Per role|
|`families`|Optional overrides of the built-in family patterns (`*claude*`, `*gpt-*`, `*deepseek*`, `*kimi*`, `*glm*`, `*qwen*`, `*gemma*`, `*minimax*`)|Nothing: cross-family check|

Rules the check enforces:

- **Fully qualified ids only.** A bare id resolves against the current parent provider (`PS/docs/models.md:14`), so it would change meaning when the main thread switches between `openai-codex` and `amorphic`.
- **Versioned ids over router aliases.** `fireworks/accounts/fireworks/routers/deepseek-flash-latest` moves underneath the plan. pi-subagents also verifies the response model id strictly unless `modelResponseAliases` declares it (`PS/docs/configuration.md:51-65`). Warn on `/routers/` and `-latest` ids.

### Scope: user plan plus a required per-repo override

Decision 2026-10-09: a per-repo override is a v1 requirement. A repo must be able to pin steward profiles away from third-party providers, for example to keep everything on Anthropic or OpenAI.

Shape: a project file `<repo>/.pi/steward-model-plan.json`, in the same schema as the user plan, read in full only when the project is trusted (`ctx.isProjectTrusted()`, `PIDIST/extensions/types.d.ts:238`); an untrusted project contributes its two provider lists and nothing else (rules below). Reasons for a separate file over a `steward` block in `.pi/settings.json`: pi-subagents and pi own that file's schema, and an unknown top-level block risks being rejected or rewritten by them; this repo already commits `.pi/settings.json` for a different purpose; a plan file keeps fallbacks, escalations and provider lists, which settings cannot hold.

Rules:
- **Project wins over user**, field by field, role by role, the same merge as `"*"`. Merge order per role field, strongest first: project role, project `"*"`, user role, user `"*"`. The check names the winning file for every binding.
- **`allowProviders` and `denyProviders`** (lists of provider ids, project file only). The check errors when any bound model, fallback or escalation target sits on a denied provider or outside a non-empty allow list, and `apply` skips those candidates. A `role:<role>` escalation is checked against the target profile's effective binding as well, so it cannot route around the lists. A repo with `"allowProviders": ["amorphic", "anthropic"]` can never see a Flash binding.
- **Lists from every project plan up to home.** Every `.pi/steward-model-plan.json` from cwd up to, not including, home contributes its lists: deny lists are unioned, allow lists intersected. Only the plan at the project root contributes roles and other fields. A nested `.pi` (a vendored package) cannot hide the repo's restrictions.
- **Lists honored in an untrusted project** (operator decision 2026-10-12). Declining trust must not unblock a provider the repo denies. From an untrusted project's plan files only `allowProviders` and `denyProviders` are read; every other field is ignored. The lists only restrict, so honoring them never widens what the session may do.
- **One list reader for trusted and untrusted sessions.** Every project plan file's two lists are read the same way in both modes, and `version` does not gate them: a trusted plan with a missing or wrong `version` loses its other fields but keeps its lists, so trusting a repo never loosens its lists. Each file is read up to 64 KiB, as UTF-8 with or without a BOM. Every entry must match a strict provider-id pattern. Findings never echo the file's text.
- **A list that cannot be read fails closed.** When a project plan file's lists cannot be read in full, every binding, candidate, escalation and the main thread error with `provider-not-allowed`, and the result's `listsFailClosed` names the file. That covers: a file that is unreadable, larger than 64 KiB, not JSON or not a JSON object; a list key whose value is not a list; a list longer than 64 entries; a `denyProviders` with any entry that is not a provider id, because dropping it would widen access. An `allowProviders` that is present but has no valid entry (`["Anthropic Inc"]`, or the string `"anthropic"`) is an active, empty allow list, so everything is blocked. An `allowProviders` with some valid entries keeps them, with a finding for the rest. Only an explicit `[]` means no allow list. A hostile repo could block everything with `"allowProviders": ["x"]` anyway, so failing closed costs nothing.
- **Findings are bounded.** A plan file gives at most one finding per list key; `provider-unknown` is one finding per key across all files, and the untrusted-lists notice is one finding for the whole walk. A blocked-provider message names the provider and the file, never the list. Every finding message has control, format and line-separator characters replaced and is capped at 1,000 characters (sources at 512, echoed keys at 64), because 2b renders findings into the system prompt. A test pins a hard upper bound on findings and characters for worst-case files.
- **Agents that replace a steward profile.** With lists active, the user and project agent directories are scanned the way pi-subagents 0.77.0 reads them (`parseFrontmatter`, block scalars included, and `normalizePackageName`); a `steward.<role>` agent there is `agent-shadowed`, and a `role:` escalation to that role errors and is cleared. A scan that stops at 5,000 files in one directory errors with `shadow-scan-truncated`. Known gap: agents from other installed pi packages are not scanned.
- **pi-subagents `.pi/settings.json` overrides still apply** after the plan compiles, field by field (`PS/src/agents/agents.js:1350-1359`), but only in a trusted project. Since pi-subagents 0.77.0, a session that declined project trust ignores project subagent settings, project agents and chains, project-scoped packages and `modelScope`, and its default scope behaves as `user` (`PS/CHANGELOG.md:41-42`, `PS/docs/agents.md:34`, `PS/src/agents/agents.js:2396,2669`). The effective-binding computation in Phase 2 mirrors that: with `project_trusted` false, the project settings layer is dropped, and `.pi/steward-model-plan.json` contributes its two lists only (rule above). `apply` writes user settings only and never writes into a repo.
- Phase 2 builds the merge and enforcement; the tests are listed there.

Known instance: this repo's committed `.pi/settings.json` pins all seven `steward.*` profiles to `amorphic/claude-*` for work inside this repo. It overrides the `model` field of any user plan here, in a trusted project only (see the trust rule above). Its keys moved to the role-only names in 0.10.0 (Phase 1, `.pi/settings.json:4-10`); `steward.top-reviewer` is pinned to `amorphic/claude-opus-5-5`.

## Main thread

- **Steward sets no default.** The main thread runs on whatever model and thinking level pi on the client machine picks: `defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels`, and `/model` (`PIDOCS/models.md:29-33`). Selecting a model in `/model` then Ctrl+S, `/thinking` then Ctrl+S, and `/scoped-models` for Ctrl+P switching are all pi's own.
- **Check, never switch.** At `session_start` and on every `model_select` event (`PIDIST/extensions/types.d.ts:861-866`, sources `set`, `cycle`, `restore`), the extension reads `ctx.model` and `ctx.thinkingLevel` (`types.d.ts:225-234`) and rebuilds the plan block. The next run's system prompt carries the new block; `before_agent_start` already re-adds the edict on every run (`pi/extensions/steward/index.ts:222-240`). A model switch already costs the prompt cache, so the rebuild adds no extra cache miss. A thinking switch (`thinking_level_select`) also rewrites the main-thread line, so the system prompt changes there too; whether that costs a cache miss depends on how the provider caches across thinking changes (not measured).
- **A session on a different model.** If the main model is not in `main.models`, the block opens with a `STEWARD WARNING` telling the main thread to inform the operator and name `/model`. That follows the existing warning pattern (`hooks/steward_hook.py:166-181`). If the model is also outside `judgmentModels`, the warning adds that delegation decisions are unreliable on fast-tier models (Harness Effect, below). Roles bound to `main` inherit that model, so the warning lists them too. `agentOverridesByProvider` follows the new provider at the next launch on its own (`PS/docs/models.md:64`).
- **Thinking drift.** Confirmed startup order (`PIDIST/sdk.js:121-143`, spike 2026-10-11): an explicit option first (`--model x:level` suffix, `main.js:379-385`; `--thinking`, `main.js:412`, applied after and winning); then, for a resumed session, its recorded thinking-level entry, or `defaultThinkingLevel` and then `medium` when it has none (`sdk.js:123-126`; a resumed session never reads `modelThinkingLevels`, with or without an entry); then, for a fresh session, `modelThinkingLevels["<provider>/<id>"]` (`sdk.js:129-133`); then `defaultThinkingLevel` (`sdk.js:135`); then a clamp to the model's supported levels (`sdk.js:143`). So the per-model entry outranks the default for a fresh session only, and the check must treat a resumed session's level as the effective one. Earlier drafts said pi caps `amorphic/claude-opus-5-5` at `high`. That was wrong: it was a stale `modelThinkingLevels` entry (`high`) in `~/.pi/agent/settings.json`, not an amorphic or pi limit. It was set to `xhigh` on 2026-10-09, and a plain `pi -p` run then recorded thinkingLevel `xhigh`. The check still reports a stale per-model entry that differs from `main.thinking`.
- **Not used: `pi.setModel()` and `setThinkingLevel()`** (`types.d.ts:1274-1281`). They would override an explicit operator choice, including a resumed session's restored model.
- **Not used: a steward virtual main model.** With a virtual model selected, `ctx.model` is the virtual selection (`PIDOCS/virtual-models.md:23`). pi-subagents would then key `agentOverridesByProvider` on the virtual provider, and `inherit` would expand to the virtual id (`PS/docs/models.md:221`), which a foreground child cannot resolve (next section).

## Fallback and availability

|Option|Mechanism|Verdict|
|-|-|-|
|A. Static availability at `apply`|Bind the first candidate that is in the registry and whose provider has credentials (`modelRegistry.find`, `hasConfiguredAuth`, `PIDIST/model-registry.d.ts:27-32`); skip providers with `enabled: false`|Build, Phase 3|
|B. Re-check at session start|If the bound model is no longer available, the block's row says to pass the next available candidate as `model` on every launch of that profile until `apply` is rerun|Build, Phase 2|
|C. Relaunch rule in the edict|After a provider error, one explicit relaunch with the rendered model. pi-subagents prescribes this itself: "To try another model, the parent or operator must issue a later explicit launch" (`PS/docs/models.md:106`). Per-call `model` with a `:level` suffix outranks every binding (`PS/docs/models.md:14`, `PS/docs/tool-reference.md:83`)|Build, Phase 2|
|D. Rewrite `subagent` input in `tool_call`|The extension injects `model` (input mutation is allowed, `PIDOCS/extensions.md:105`)|Reject. Workflow scripts carry agent names in the script, not the tool input. Per-call models count as explicit, so an enforced `modelScope` aborts the run instead of warning (`PS/docs/models.md:214`). The transcript would show a model the main thread did not choose|
|E. Virtual model per role that switches on `retry`|`pi.registerVirtualModel` with `request.failed` (`PIDOCS/virtual-models.md:65-86`)|Defer to Phase 5. Explained below|
|F. pi-subagents `fallbackModels`|Removed in 0.68.0 (`PS/CHANGELOG.md:471`)|Not available|

Why E is deferred. Checked in the pi-subagents source:

- **Foreground children cannot see the parent's virtual models.** A foreground child copies the parent's providers only (`inheritParentProviders`, `PS/src/runs/shared/child-session.js:45-75,401-404`). It registers virtual models only from extensions the child itself loads (`child-session.js:229-252`). Foreground children load no ambient extensions (`PS/docs/agents.md:422,520`). So a steward-registered virtual model resolves in the parent at launch time and then fails inside the child, unless every profile lists a router extension in `extensions` or `subagentOnlyExtensions`.
- **That router cannot be the steward extension file.** Its child guard checks only `PI_SUBAGENT_CHILD` (`pi/extensions/steward/index.ts:159`). Only the background runner sets that variable (`PS/src/runs/background/subagent-runner.js:87`), so inside an in-process foreground child the edict and gates would switch on. The other route, `registerRequiredChildExtensions`, needs pi-subagents to be a Node dependency of steward, which a separately installed package is not (`PS/docs/agents.md:449`, `PS/docs/extension-api.md:205`).
- **It would not catch the failures that matter here.** Pi retries only after an error (`retry.*`, `PIDOCS/settings.md:125-131`). A 30-40 s first-token stall like Ollama Cloud's is slow, not failed.
- **Changing models mid-task has costs.** It drops the prompt cache, can change model family halfway through a task, and depends on pi-subagents' response-model verification handling a virtual selection. The 0.77.0 source does handle it: it compares the child's virtual selection exactly with the launch candidate and says `modelResponseAliases` does not apply (`PS/src/runs/shared/model-resolution.js:7-15`, called at `PS/src/runs/foreground/execution.js:1040`). The earlier "unverified" no longer holds for the source; no live run has exercised it.
- **The evidence for routers is weak.** Routers often fail to beat the single best model (Arize, LLMRouterBench).

Relaunch shape in a workflow script: `runs.run(key, params)` with `model` in `params` (key first; `PS/src/workflows/scripted-workflow.js:645-680`). The override resolves as `options.modelOverride ?? agent.model` (`PS/src/runs/foreground/execution.js:1725`), and thinking still comes from the profile unless the model string carries a `:level` suffix. The built-in `parallel` workflow cannot carry a per-child `model`.

Error versus failed check: a provider error (HTTP 429, 5xx, authentication, timeout, empty response, context overflow) means "same tier, other provider", so use the fallback. A failed verifiable check means "stronger model", so use the escalation. The edict keeps the two apart.

## Profile names on pi

Decision: role-only canonical names, with the old names as aliases. Built in 0.10.0 (see Phase 1). This matches the Copilot decision of 2026-10-09 ("A role-and-effort name would be wrong whenever a machine binds a model whose effort differs", `docs/roadmap/copilot-port.md:216-221`) and the Codex names (`docs/roadmap/codex-port.md`, Profiles). Under a mixed plan `steward.coder-opus-medium` would run DeepSeek at `high`, and the main thread reads that name.

|Old runtime name|New canonical name|Alias kept|
|-|-|-|
|`steward.coder-opus-medium`|`steward.coder`|`steward.coder-opus-medium`|
|`steward.deep-reasoner-opus-xhigh`|`steward.deep-reasoner`|`steward.deep-reasoner-opus-xhigh`|
|`steward.reviewer-sonnet-high`|`steward.reviewer`|`steward.reviewer-sonnet-high`|
|`steward.researcher-sonnet-low`|`steward.researcher`|`steward.researcher-sonnet-low`|
|`steward.writer-sonnet-medium`|`steward.writer`|`steward.writer-sonnet-medium`|
|`steward.mechanic-haiku-medium`|`steward.mechanic`|`steward.mechanic-haiku-medium`|
|`steward.reviewer-opus-max` (was `steward.reviewer-fable-xhigh` until 0.9.0)|`steward.top-reviewer`|both `steward.reviewer-opus-max` and `steward.reviewer-fable-xhigh`|

How it works in pi-subagents:

- **Aliases are taken verbatim**, with no package prefix (`PS/src/agents/agents.js:431-433,1930`). Resolution tries canonical names first, then local names, then aliases (`agents.js:444-468`). `subagent({ agent: "steward.coder-opus-medium" })` in `~/AGENTS.md:21`, `~/.pi/agent/AGENTS.md:21`, old briefs and saved workflows keeps working.
- **Config keys do not follow aliases.** "Runtime status, persistence, and config still use the canonical name" (`PS/docs/agents.md:417`). An existing `agentOverrides["steward.coder-opus-medium"]` stops applying silently. The README and this repo's `.pi/settings.json` used the old keys; both moved to the new keys in 0.10.0 (`README.md:138-152`, `.pi/settings.json:4-10`). A user's own `~/.pi/agent/settings.json` is not migrated by 0.10.0. The Phase 2 check flags stale keys, and `apply` moves them.
- **Bare names change meaning slightly.** Bare `coder` now resolves to `steward.coder` by local name before pi-subagents' builtin `worker` alias `coder` (`agents.js:455-468`; alias added in 0.39.0, `PS/CHANGELOG.md:1607`). The edict always uses the `steward.` prefix, so steward's own calls are unaffected.
- **Frontmatter models stay Anthropic** (`pi/agents/*.md:6-7`). That is the default when no plan or override exists, so an install without a plan behaves exactly as it does today.
- **Claude Code keeps its names.** There the frontmatter pins Claude models, so the names stay true.

## Edict changes

### Static text in `pi/skills/steward-delegating/SKILL.md`

- **Rule 2** (`SKILL.md:10`). 0.10.0 changed it to list each profile's default model and thinking inline, since the names no longer carry them; it still forbids per-call `model` except for Fable by name. Phase 2 text to add: pick the profile by task; the model plan decides model and thinking; the "Model plan" block below shows what each profile runs on. Pass `model` only in three cases: to relaunch after a provider error, to escalate after a failed check, or when the operator asks. In each case copy the exact string from the block.
- **Routing table** (`SKILL.md:25-38`): role-only names shipped in 0.10.0. Still to change: "a coordinator plus sonnet workers" becomes "a coordinator plus cheap workers".
- **"Keep it inline" section**: add "the only profile for the task is below the judgment floor in the Model plan block".
- **"How to call"**: the single-child example already uses `steward.mechanic` (0.10.0). pi-subagents 0.77.0 adds a built-in `parallel` workflow, `subagent({ workflow: "parallel", args: { tasks: [{ agent, task }] } })` (`PS/docs/workflows.md:111,116`; the `tasks` form without scripts is `PS/docs/configuration.md:145`). It runs independent children in one batch with no script and no `async: true` ceremony, so Phase 2 can replace the edict's "several children" bullet (a ```` ```js workflow ```` block with `runs.all`) with it for independent fanout. It takes only `{ agent, task }` per child (see Could not confirm), so a per-child relaunch `model` needs a single `subagent` call or a script that calls `runs.run(key, params)` with `model` in `params`, for example `runs.run("probe", { agent: "steward.mechanic", task, model: "anthropic/claude-sonnet-5-5" })` (the object-only form `runs.run({...})` fails with "invalid key"; `PS/src/workflows/scripted-workflow.js:645-680`). Keep the script form for dependent steps. Resolved in 2d: a ```` ```js ```` workflow block written in the reply was not visible to the tool, in a `pi -p` probe and again in an interactive pi session (`subagent({ workflow: true })` failed with "The assistant message that issued this call has no text in the session"; pi 1.1.0, pi-subagents 0.77.0). The edict now uses the built-in `parallel` workflow for independent children, separate sequential calls for dependent steps, and a workflow script only as a file path (`subagent({ workflow: "/path/wf.js" })`). It never puts a script in the reply.
- **New "Guardrails" section** (static):

|Guardrail|Edict wording, short|Evidence|
|-|-|-|
|Judgment stays above the floor|Architecture, plans, security review, and final synthesis go only to a profile whose Judgment-grade cell says `yes`; if every cell says `no`, keep the work on the main thread; `not checked`, or no block, sets no floor and the routing table decides|Delegation is reliable only on the two strongest models (about 0.85) and unusable on the fast tier (about 0.42-0.45) (Writer, arXiv 2607.06906). Performance is limited by the planner, not the executor (arXiv 2601.11327)|
|Cheap models get bounded tasks with a check|A profile below the floor gets a task with a verifiable done-condition: tests, types, lint, or a command whose output proves it|Delegation contract: objective, schema, tools, budget, boundary, done-condition (Zorost). Briefs need objective, output format, tools, boundaries (Anthropic multi-agent research system)|
|Escalate on a failed check|One failed check leads to one relaunch with the escalation model; with no escalation model, or after a second failure, the work goes to the main thread or `steward.deep-reasoner`|Escalation after repeated failure, revert when cheap output gets re-tasked (opencode-subagent-router). Codex `retry` and `fallback` entries (`codex/skills/delegating/profiles.json:7,17,45,55`)|
|Fallback is not escalation|A provider error leads to one relaunch, on the block's relaunch model when the row has one (rule 2 covers rows without: the same profile once without `model` after an overload, rate limit or timeout); never a model the block does not name|pi-subagents: one model per launch, errors are returned (`PS/docs/models.md:18,106`)|
|Cross-family review|When the block shows a profile of another family than the author's, review with it; when all share one family, use the routing table's reviewer|A reviewer from a different family on purpose (nkapila.me opencode config); Copilot's rubber-duck "complementary model strategy" (`docs/roadmap/copilot-port.md:214`)|
|Respect provider caps|Never run more children at once on a provider than its stated cap|Ollama Cloud concurrency was the real limit (nkapila.me; operator: Pro 3, Max 10)|
|Thinking where it pays|Never raise a cheap role's thinking per call; high thinking belongs to the main thread and the judgment roles|Orchestrator thinking gives the largest gains; sub-agent thinking gives little or negative benefit (arXiv 2601.11327)|

### Generated block, appended at session start

Built from the effective bindings, not from the plan alone, so it shows what will actually launch. Example for the plan above with the main thread on Sol:

```text
## Model plan on this machine (generated at session start; rebuilt on a model or thinking switch)
Main thread: openai-codex/gpt-6.1-sol at xhigh. In the plan: yes. Judgment-grade: yes.
| Profile | Runs on | Thinking | Judgment-grade | Family | After a provider error, relaunch with model | After a failed check, relaunch with model |
|-|-|-|-|-|-|-|
| steward.coder | ollama-cloud/deepseek-v4.1-flash | high | no | deepseek | fireworks/accounts/fireworks/models/deepseek-v4p1-flash:high | openai-codex/gpt-6.1-sol:high |
| steward.researcher | ollama-cloud/deepseek-v4.1-flash | high | no | deepseek | fireworks/accounts/fireworks/models/deepseek-v4p1-flash:high | openai-codex/gpt-6.1-sol:high |
| steward.reviewer | amorphic/claude-sonnet-5-5 | high | no | claude | openai-codex/gpt-6.1-sol:medium | use steward.deep-reasoner |
| steward.deep-reasoner | openai-codex/gpt-6.1-sol (inherits the main thread) | xhigh | yes | gpt | amorphic/claude-opus-5-5:xhigh | keep it on the main thread |
| steward.top-reviewer | amorphic/claude-opus-5-5 | max | yes | claude | anthropic/claude-opus-5-5:max | keep it on the main thread |
| ... | | | | | | |
At most 3 children at a time on ollama-cloud.
```

Rules the block follows when settings override the plan:

- **Relaunch follows the effective binding.** The relaunch column is the next usable candidate after the effective model in the role's candidate list (bound model, then fallbacks, after `byMainProvider`), checked against the allow and deny lists, credentials and disabled providers. If the effective model is not in that list, the column says `none` and the full check report gives the reason (`effective-relaunch-none`, info). A candidate outside `judgmentModels` is skipped when the effective model is judgment-grade, so an override to Opus never relaunches on Flash. The result keeps the plan-based `relaunch` for `apply`; the block renders `effectiveRelaunch`.
- **Override warnings are grouped.** `binding-drift` findings with the same source file and hint become one line listing the roles, with the path relative to the cwd or under `~` for the home directory. The full `/steward-models check` report keeps one line per role.
- **Per-model warnings follow the launch.** Output-token, thinking-clamp, model-scope and judgment-floor warnings are checked on the effective binding. The plan binding is checked too only when no settings override applies to it; `binding-drift` covers the mismatch. A provider's concurrency warning counts a role on that provider only by its effective binding, as the cap line does: a plan binding that no settings apply launches nothing until `apply`.

With no plan file, the block still lists the effective bindings from settings and frontmatter, without the last two columns. Without a usable model registry (the extension fails open), there is no block, and the edict reads as it does today.

## Validation: `/steward-models` and the session-start check

Split of work, following the existing architecture where every decision is in `hooks/steward_hook.py` and the extension only translates (`pi/extensions/steward/index.ts:1-12`):

- **The extension gathers registry facts** and adds them to the `session-start` payload, which today carries only `session_id` (`index.ts:200-210`). The facts are: main model and thinking level; available models (`getAvailable()`), each with provider, id, supported thinking levels, `maxTokens` and `api`; and `project_trusted`. For supported levels it calls `getSupportedThinkingLevels` from `@earendil-works/pi-ai` (`.../pi-ai/dist/models.d.ts:262`) directly. The import works in a directory with no `node_modules` because pi's extension loader aliases pi packages (`PIDIST/extensions/loader.js:33-84,471-476`; probed 2026-10-11, `ctx.model` also exposes `reasoning`, `thinkingLevelMap`, `maxTokens`). No `thinkingLevelMap` fallback is needed. The `check` command also sends `getAll()` with auth flags, so it can tell "not in the catalog" from "no credentials".
- **A new `hooks/model_plan.py`** does everything else, imported only for harness `pi`. It parses the plan, merges `"*"`, resolves candidates, and computes effective bindings from user and trusted-project settings using the documented precedence: per-run, then provider-scoped role override, then `agentOverrides`, then frontmatter, then `subagents.defaultModel`, then parent (`PS/docs/models.md:14`). The user layer comes first and the project layer second, each with its provider map merged in (`PS/src/agents/agents.js:1031-1064,1350-1359`). It also renders the block and builds the `apply` patch.
- **Session start stays offline and fast.** It reads files and the registry, with no network calls and no probes, inside the existing 15 s hook timeout (`index.ts:22`). At most one warning line per problem.
- **Rebuilds never leave a stale or missing edict.** The extension rebuilds the edict at session start, on `model_select` and on `thinking_level_select` (pi 1.1.0 emits it with `{level, previousLevel}`, `PIDIST/extensions/types.d.ts:868-872`, from `setThinkingLevel`, `PIDIST/agent-session.js:2052-2071`). A generation counter lets only the newest load land; an older load that ends later changes nothing, and the previous edict stays in place until the new one is ready. `before_agent_start` waits for the running load instead of starting its own. The model and thinking handlers start the load and return, because pi awaits `model_select` handlers inside `setModel`, so a slow hook would otherwise hold up the switch.
- **A facts problem costs the block, never the edict.** When the `session-start` call with `model_facts` gives no edict (timeout, bad JSON, crash), the extension retries once without `model_facts`, so the edict equals the plain edict. It does not send facts again until the next model or thinking switch.
- **The `check` report is display-only.** It is a `steward-models` custom entry (`pi.appendEntry`) drawn by an entry renderer (`pi.registerEntryRenderer`). Custom entries are stored in the session but never sent to the model (`PIDOCS/session-format.md:164-172`; `PIDIST/session-manager.js:166-192` turns only `message`, `custom_message`, `branch_summary` and `compaction` entries into context). Without a UI the report also goes to `ctx.ui.notify`.

|Check|Severity|Source of truth|
|-|-|-|
|Plan parses; known roles; known fields; ids fully qualified; thinking values valid|error|Plan schema|
|Bound and fallback models exist in the registry|error, and the candidate is skipped|`modelRegistry.find` (`model-registry.d.ts:29`)|
|Provider has credentials|error, and the candidate is skipped|`hasConfiguredAuth` / `getAvailable` (`model-registry.d.ts:28,32`)|
|Thinking level supported by the bound model|warn: "clamped to X"; pi clamps silently (`PIDOCS/models.md:125`, `virtual-models.md:65`). A declared level is not proof the provider honors it (Ollama and `max`)|Supported levels|
|`maxTokens` below 32K on `coder` or `writer`|warn: Ollama's 16.4K cap truncates large edits|Registry|
|Router or `-latest` ids|warn: drift, and strict response verification may need `modelResponseAliases`|`PS/docs/configuration.md:51-65`|
|Role on a provider with `maxConcurrent` N while `parallel.concurrency` or `globalConcurrencyLimit` is above N|warn, naming the values to set in `~/.pi/agent/extensions/subagent/config.json`|`PS/docs/configuration.md:422-430,494-505`|
|A judgment role, or the main thread, outside `judgmentModels`|warn|Plan|
|Reviewer family equals coder family, or equals the main family when `byMainProvider` is used|warn|Family patterns|
|Effective binding differs from the plan, with the winning file named (for example this repo's `.pi/settings.json`)|warn: "set subagents.agentOverrides by hand (README Phase 0 recipe)", "project override wins", or the repo's `.pi/settings.json` for a project plan value|Settings files|
|`agentOverrides` keys for old profile names|warn: stale key, no longer applied|`PS/docs/agents.md:417`|
|Plan model outside an enforced `subagents.modelScope`|error for per-call relaunch models (they abort, `PS/docs/models.md:214`); warn for bindings. The block never offers a relaunch, escalation or "pass model" string that would abort: it skips to the next candidate or shows `none` (`effective-relaunch-none`, `escalation-none`, `pass-model-none`). An effective binding outside a strict scope is blocked ("do not launch")|Settings|
|Role thinking above `subagents.maxThinking`|error: the launch fails before start (`PS/docs/models.md:138`). On the effective binding the profile is blocked ("do not launch"); a per-call string above it is not offered|Settings|
|Main model not in `main.models`; effective startup thinking differs from `main.thinking`|warn|`ctx.model`, settings|

`/steward-models` subcommands:

- **`check`** (the default) prints the block, every warning, and the source file of each binding, as a display-only session entry the model never sees. It is a dry run and writes nothing. It complements `/subagents-models`, which stays the authority on the live mapping (`PS/docs/models.md:167-176`). Phase verification compares the two.
- **`apply`** writes the bindings to the user settings file. It touches only `subagents.agentOverrides["steward.*"].model` and `.thinking`, plus `subagents.agentOverridesByProvider.<p>["steward.*"]`. Every other key, and other fields on steward keys such as `machine`, is preserved. Steps:
  - It moves stale old-name steward keys to the new names.
  - It backs the file up to `settings.json.bak-<YYYYMMDD-HHMMSS>`, the operator's convention already present in `~/.pi/agent/`, then writes through a temporary file and a rename.
  - It re-reads the file before writing and refuses if the file changed since it was read.
  - It writes `~/.pi/agent/profiles/pi-subagents/steward.json` in pi-subagents' profile format (`profiles.js:41-71`: `subagents.agentOverrides`, no `fallbackModels`), carrying over the non-steward overrides. `/subagents-check-profile steward` then probes every model live, and `/subagents-load-profile steward` restores the mapping after another profile replaced it.
  - It calls `ctx.reload()` (`PIDIST/extensions/types.d.ts:322`), because pi-subagents' live mapping can lag the file until a reload (`PS/docs/models.md:176`).
  - It never writes `defaultModel`, `modelThinkingLevels`, `enabledModels`, `modelScope`, `maxThinking`, or the subagent `config.json`.

## Doing it today with no code change (Phase 0)

Main thread: `/model`, select Sol, Ctrl+S. Then `/thinking`, `xhigh`, Ctrl+S. If a per-model `modelThinkingLevels` entry is lower than wanted, edit it there (the Opus `high` entry on this machine was such a stale value, now `xhigh`). Steward sets no main-thread default. Then add to `~/.pi/agent/settings.json`:

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
      "amorphic": { "steward.reviewer": { "model": "openai-codex/gpt-6.1-sol", "thinking": "medium" } }
    }
  }
}
```

Then `/reload` and `/subagents-models`. The keys use the 0.10.0 role-only names; overrides saved under an old name stop applying (config keys do not follow aliases). The README "Profiles on pi" section carries this recipe. Limits: since 0.10.0 the names no longer say opus, sonnet or haiku, and edict rule 2 lists each profile's default model and thinking inline, but that text still describes the defaults, not your overrides, and nothing tells the main thread what to relaunch with. In a trusted project, this repo's committed `.pi/settings.json` overrides every `model` field above (a session that declined trust ignores it).

## Phases

Each phase ships on its own and keeps `npm test` green (`python3 -m unittest discover -s tests && node --test 'tests/pi/*.test.mjs'`, `package.json` scripts). Claude Code, Copilot and Codex files are not touched. The existing `ClaudeHarnessUnchangedTests` (`tests/test_pi_harness.py:220-247`) and the Copilot and Codex suites must stay green unmodified.

|Phase|Ships|Depends on|
|-|-|-|
|0|README "Profiles on pi" gains the Phase 0 recipe and the `.pi/settings.json` caveat; this document (done, 2026-10-11)|Nothing|
|1|Role-only pi names with aliases (built in 0.10.0, `f9e319a`; live pi check pending)|Nothing|
|2|Plan file, per-repo override file with `allowProviders`/`denyProviders`, read-only `check`, generated block, guardrails in the edict; four slices 2a to 2d (2a merged in `eb80786`; 2b merged in `f0c5194`; 2c merged in `e164385`; 2d built on `pi-model-plan-2d` in `99a5cd3`, `a7d9a23` and the docs commit, release 0.11.0 pending a final deep-reasoner review of all of Phase 2)|Nothing (role-to-runtime-name map covers both name sets)|
|3|`apply` and the `steward` pi-subagents profile file (so `/subagents-check-profile` can probe every model)|Phase 2|
|4|Per-launch outcome log (ships, decided 2026-10-09)|Phase 2|
|5|Deferred: in-child failover router|Phase 3 and a live probe|

**Phase 1: names. Built in steward 0.10.0 (`f9e319a`, 2026-10-11).**
- Shipped:
  - `pi/agents/*.md` renamed to `coder.md`, `deep-reasoner.md`, `reviewer.md`, `researcher.md`, `writer.md`, `mechanic.md`, `top-reviewer.md`, each with `name:` matching and `aliases: steward.<old-name>` (frontmatter models unchanged: Anthropic, `pi/agents/*.md:6-7`). `top-reviewer` lists both `steward.reviewer-opus-max` and `steward.reviewer-fable-xhigh` (operator decision 2026-10-11, so saved launches under either name keep working).
  - Edict rule 2 lists each profile's default model and thinking inline (`pi/skills/steward-delegating/SKILL.md:10`); the routing table and the call example use the new names.
  - Pi gate message (`hooks/steward_hook.py:857-867`), README Pi sections (`README.md:87-221`), this repo's `.pi/settings.json` keys (`:4-10`) and the version in `package.json` and the three plugin manifests.
- Tests: `PI_NAMES` map (`tests/test_pi_harness.py:24-35`); `test_same_profiles_as_claude` and `test_each_profile_mirrors_its_claude_twin` map through it (`:283-300`); `test_old_names_kept_as_aliases` (`:302`); `test_profile_names_carry_no_model` (`:310`); `test_profile_references_carry_no_model` (`:336`). `npm test` ran green: 254 Python and 23 node tests.
- Checked: a standalone script drove the installed pi-subagents 0.77.0 resolver (`discoverAgents` and `resolveAgentName`) and resolved all 8 old names and all 7 new names.
- Open:
  1. **Live pi session check. Done 2026-10-11 at 7dffda0.** In a live pi 1.1.0 session with pi-subagents 0.77.0, `steward.mechanic-haiku-medium` resolved to `steward.mechanic` (amorphic/claude-haiku-5-5, medium) and `steward.reviewer-fable-xhigh` resolved to `steward.top-reviewer` (amorphic/claude-opus-5-5, max); the empty-directory launch of `steward.mechanic` ran on anthropic/claude-haiku-5-5 at medium. The list also shows the aliases, as designed.
  2. **Operator follow-up.** Update the example at `~/AGENTS.md:21` and `~/.pi/agent/AGENTS.md:21`. These are operator files; the old name keeps resolving meanwhile.

**Phase 2: plan, check, block.** Split into four slices, each shipping with `npm test` green:
- **2a, `hooks/model_plan.py`** (built on branch `pi-model-plan-2a`, worktree `steward-model-plan-2a`; merged to main in `eb80786`): schema, `"*"` merge, user plus per-repo plan merge, `allowProviders`/`denyProviders`, effective-binding precedence including the 0.77.0 untrusted-project rule, and findings. Python tests only. Commits: `d6a6f6a` (core), `9302dfc` (review fixes: fail-closed deny check, robustness, layering), then the commit adding `role:<role>` escalation targets and untrusted-project lists (decisions 2026-10-12). Deep-reasoner reviewed it, because allow/deny decides whether code leaves for third-party providers. Real-resolver results:
  - First fix pass: 300 model spellings went through the installed pi-subagents 0.77.0 resolver. 265 resolve to a denied provider and all 265 error; 35 do not resolve and all 35 error; the Python mirror matched the resolver on 300 of 300.
  - Second review: 16,320 cases through `resolveEffectiveSubagentModel` against the mirror, 0 mismatches; fuzzing (3,000 plan and settings shapes, 2,000 malformed fact sets) gave 0 internal errors.
  - Second fix pass (fail-closed list reading, malformed allow lists, shadowed escalation targets, pi-subagents frontmatter and package-name parity, bounded findings): the drift guard `tests/test_pi_model_plan_resolver.py` runs about 16,000 spellings (the first review's fail-open spellings included), `normalizeModelSegment`, `parsePackageName` and `parseFrontmatter` corpora through both the mirror and the installed pi-subagents via `tests/pi/resolve_model.mjs`, and requires them to agree. It pins pi-subagents 0.77.0 and fails with "re-verify the mirror" on another version; it skips, with the reason, when node or the package is missing (`$PI_SUBAGENTS_DIR` overrides the path). The reviewer's probes and both fuzzers pass, with 0 internal errors.
- **2b, rendering and session start** (built on branch `pi-model-plan-2b`, worktree `steward-model-plan-2b`; merged to main in `f0c5194`): `hooks/model_plan_render.py` renders the block (`render_block`) and the full check report (`render_report`); the pi branch of `cmd_session_start` appends the block. What 2c builds on:
  - **Payload key `model_facts`.** The pi `session-start` payload may carry `model_facts`, exactly the facts contract in the `hooks/model_plan.py` docstring (`main`, `models`, `projectTrusted`, `cwd`). With valid facts the block is appended after the edict, separated by a blank line. Without the key, with facts that `evaluate` reports as `facts-invalid` or `internal-error`, or on any exception, the output is byte-identical to `eb80786`. Claude Code, Copilot and Codex ignore the key.
  - **Subcommand `model-plan`** (pi only), for `/steward-models check`: stdin `{"model_facts": {...}, "cwd": "..."}` (`cwd` fills `model_facts.cwd` when that is missing); stdout `{"report": "<text>"}`, exit 0 with or without findings. The report holds the uncapped block, every finding with severity, code and source file, and the file each binding comes from. Unusable input (not JSON, no `model_facts`, facts that fail `validate_facts`, a harness other than pi) prints `{"error": "model-plan: ..."}`, writes the message to stderr and exits 2. It writes no files.
  - **Block bounds.** At most 30 lines and 5,000 characters; finding lines are cut at 300 characters and `STEWARD WARNING` lines at 400. Lines go in by priority (main-thread and fail-closed warnings, blocked profiles, provider caps, errors, warnings) and the block ends with "N more: run /steward-models check" when any were left out. The same message for several roles is one line.
  - **Blocked profiles.** A role whose effective binding has an error `provider-denied`, `provider-not-allowed`, `effective-model-unverifiable`, `agent-shadowed`, and since the release review `thinking-above-max` or a strict `outside-model-scope`, shows "(blocked)" and "do not launch" in its row plus a "Do not launch steward.<role>" line; fail-closed lists or a truncated agent scan block every profile with one `STEWARD WARNING`.
  - **Fix pass** (review probes and operator report): `|` in a table cell becomes `/` instead of being escaped, and `clamp_block` holds the capped block to 30 lines and 5,000 characters for any input. Plan `providers` keys render only when they match the provider id pattern and name a catalog provider; others are dropped with one quoted `plan-provider-unknown` finding. Family names and `byMainProvider` keys must be plain ids too, and finding messages quote the keys they echo. The relaunch column follows the effective binding, override warnings are grouped, and per-model warnings follow the launch (see Generated block). Facts whose `models` list has no usable entry are `facts-invalid`; `model-plan` rejects a relative `cwd` with exit 2. The regression tests that read `eb80786` with `git show` fail when the commit is missing; `STEWARD_ALLOW_MISSING_BASE_COMMIT=1` turns that into a skip.
  - Real-system check with registry facts from pi 1.1.0 (1,595 models): session start takes 0.04 s, against the 15 s hook timeout.
- **2c, extension** (built on branch `pi-model-plan-2c`, worktree `steward-model-plan-2c`; merged to main in `e164385`). Commits: `d1a16b5` (Python carry-overs from the 2b review), `bb63728` (extension), `3293d34` (review fixes).
  - **Facts.** `gatherModelFacts` in `pi/extensions/steward/index.ts` builds the facts contract from `ctx`: every `modelRegistry.getAll()` model with `provider`, `id`, `available` (`hasConfiguredAuth`, asked once per provider), `thinkingLevels` from pi-ai's `getSupportedThinkingLevels` and `maxTokens`; `main` from `ctx.model` and `ctx.thinkingLevel`, or null with no model; `projectTrusted` from `ctx.isProjectTrusted()`; the absolute cwd. `api` is not sent (the hook does not read it). pi-ai is imported lazily on first use. A missing registry, a failed import, a missing thinking level or any exception omits `model_facts`, and the session-start text is then byte-identical to the plain edict (Node test).
  - **When.** `loadEdict` sends `model_facts` at `session_start` and whenever the edict is rebuilt. `model_select` (sources `set`, `cycle`, `restore`) and `thinking_level_select` rebuild it; pi sets the new model and thinking level before it emits either event, so `ctx` reads the new values, and the next `before_agent_start` carries the new block.
  - **Generation guard.** Each load takes the next generation number and lands only if no newer load started meanwhile, so two quick switches, or a switch during the session-start load, end on the newest block. The previous edict stays in place until a load succeeds, so the `context` reminder and `before_agent_start` always have one; `before_agent_start` shares the running load instead of starting a second one. The `model_select` and `thinking_level_select` handlers do not wait for the hook (pi awaits `model_select` handlers inside `setModel`; a slow hook held up the RPC `set_model` response by the hook's run time before this). `session_start` still waits, as on main.
  - **Plain-edict retry.** A `session-start` call with `model_facts` that gives no edict (15 s timeout, bad JSON, crash) is retried once without `model_facts`, so the edict equals the plain edict; facts are not sent again until the next model or thinking switch, so later prompts do not pay for a failing facts call. A missing python3 is not retried.
  - **`/steward-models`.** `check` (the default) gathers fresh facts, runs the `model-plan` subcommand with `{model_facts, cwd}` (absolute cwd) and shows the report as a display-only `steward-models` custom entry (`pi.appendEntry`, drawn by `pi.registerEntryRenderer` with pi-tui's `Text`, or a plain line wrapper when pi-tui does not load). Custom entries never reach the model (`PIDOCS/session-format.md:164-172`, `PIDIST/session-manager.js:166-192`). Without a UI the text also goes to `ctx.ui.notify`. `apply` and `stats` reply that they arrive in a later phase (3 and 4); any other argument gets the usage line. A failing hook, unparsable output, a hook `error` or a missing python3 gives a one-line `steward: /steward-models check failed: ...` message. A host without `registerCommand` keeps the edict and gates.
  - **Debug variable.** `STEWARD_HOOK_LOG=<file>` appends one JSON line per session-start and `model-plan` hook call (gate calls are not logged since the release review: they carry commands, file contents and reply text) (`subcommand`, `payload`, `stdout`, `ms`, plus `timedOut: true` or `error: <code>` for a call that timed out or could not start) and one per facts gathering (`ms`, `models`, `bytes`). Unset, nothing is written.
  - **Python carry-overs.** A rejected plan provider key is described without its text (`plan-provider-unknown` gives a count; `providers[...]` value errors and `byMainProvider` key errors name a key only when it is a provider id). The "At most N children at a time on <provider>" line renders only for providers that an effective binding or an effective relaunch uses. `test_unknown_provider_keys_are_dropped` and `test_by_main_provider_keys_must_be_ids` changed with the wording.
  - **Python review fixes.** The concurrency warning counts effective bindings only; a binding-drift message for a plan role with no usable model names the plan's thinking instead of printing `None`; blocked-provider messages read "<binding> <model> is blocked: provider X is in denyProviders in <file>." (and "inherits the main thread, which is blocked: ..."). `test_concurrency` in `tests/test_pi_model_plan.py` now adds a settings override, since a plan alone no longer warns.
  - **Tests.** `npm test`: 460 Python tests (drift guard running, no skips; 8 new in `tests/test_pi_model_plan_2c_review.py`) and 50 Node tests (27 in `tests/pi/steward-model-plan.test.mjs`; the five `/steward-models` tests changed from `sendMessage` to entries).
  - **Live check, 2026-10-12** (pi 1.1.0, pi-subagents 0.77.0, only the worktree extension and pi-subagents loaded with `-ne -e`; evidence in `/tmp/steward-2c/live.md`). Real registry: 1,595 models (525 available), facts gathered in 1 to 2 ms, session-start payload 247 KB, hook 36 to 43 ms. In this repo the block row for `steward.mechanic` (amorphic/claude-haiku-5-5, medium) matched the `_meta.json` of a live launch (`amorphic/claude-haiku-5-5:medium`), and all seven rows matched `/subagents-models`; in an empty directory the row and the launch were both `anthropic/claude-haiku-5-5` at medium. Main on Opus and on Sol (`--model`) gave the matching main-thread line. A scratch repo denying `ollama-cloud` and `fireworks`: `/steward-models check` in print mode reported the denied plan binding as `provider-denied` errors, and with a settings override onto the denied model the block marked `steward.coder` blocked with "do not launch". A role overridden onto a model without credentials was reported (`model-no-credentials`, `effective-model-unavailable`) and the block named the next candidate. `model_select` was exercised live through RPC `set_model`: the next run's block showed the new main model.
  - **Live check of the review fixes, 2026-10-12** (same setup plus a request observer extension; evidence in `/tmp/steward-2c/live.md`, "Fix pass"). Two `set_model` calls 0.5 s apart (Sol, then amorphic Sonnet) with the first rebuild's hook delayed 2 s: the Sol load finished 1.5 s after the Sonnet load and was discarded; the next run's block read Sonnet, and both `set_model` responses came back without waiting for the hook. RPC `set_thinking_level low` rebuilt the main-thread line to `at low`. `/steward-models check` appeared as an `entry_appended` custom entry; its report-only lines were in no provider request body and in no message entry of the session file.
  - **Open for 2d.** Rule 2 and the Guardrails text still to write. A model switch in pi also emits `thinking_level_select` when the level changes, so it can start two loads; the generation guard keeps the newest, at the cost of one extra hook call.
- **2d, edict text and docs** (built on branch `pi-model-plan-2d`, worktree `steward-model-plan-2d`; not merged). Commits: `99a5cd3` (`steward 0.11.0: model plan on pi`), `a7d9a23` (unavailable-binding model and no-relaunch case in the edict), `55106f6` (docs), then the release-review fixes (2026-10-12 decisions 5 to 11). Shipped: rule 2 rewording, the Guardrails section, the judgment-floor inline case, the built-in `parallel` workflow for independent fanout, sequential calls for dependent steps, and the README section "Model plan on pi". The in-reply workflow block problem is closed: it failed in an interactive session as well as in print mode (see Edict changes), so the edict no longer relies on it. 0.11.0 checks and shows the plan; it does not apply it. Phase 3 (`apply`) is next.

Detail for the whole phase:
- Files: `hooks/model_plan.py`, plus a pi branch in `cmd_session_start` (`hooks/steward_hook.py:275-305`) that appends the block when the payload has registry facts. The extension gets registry facts in `loadEdict`, a `model_select` handler that clears and reloads the edict, and a `/steward-models` command that runs a new `model-plan` hook subcommand. The edict gains the static guardrails. README documents the plan file.
- Python tests, new `tests/test_pi_model_plan.py`:
  - schema errors: bare id, unknown role, bad thinking value;
  - `"*"` merge;
  - first-available resolution, including a no-credentials candidate;
  - `main` rendered as inherit with the current main model;
  - clamp, `maxTokens`, router-id, concurrency, judgment-floor, family, stale-key, `modelScope` and `maxThinking` findings;
  - effective-binding precedence over fixture user and project settings, with and without `agentOverridesByProvider`, and with an untrusted project's settings ignored;
  - no plan file and no registry facts gives byte-identical session-start output to today (regression);
  - rendered text has no em-dash and uses `|-|` separators;
  - project file: merges over the user plan field by field; when the project is untrusted only its lists apply (invalid entries, an oversize file and bad JSON each give a finding and no exception); `denyProviders` and a non-empty `allowProviders` make the check error on a bound model, fallback or escalation target, and make `apply` skip those candidates; a repo pinned to `amorphic` and `anthropic` never resolves a Flash binding; the winning file is named in the output.
- Node tests in `tests/pi/steward-extension.test.mjs`:
  - payload carries main model and available models from a fake registry;
  - `model_select` triggers a rebuild that the next `before_agent_start` uses;
  - the command is registered and prints hook output;
  - a throwing registry fails open with no block.
- Live check on this machine: the block matches `/subagents-models` for all seven profiles, with main on Sol and then on Opus. A foreground and a background `steward.mechanic` both launch on the Ollama Flash model. In a scratch repo with `.pi/steward-model-plan.json` denying `ollama-cloud` and `fireworks`, `check` reports Flash bindings as errors and the block shows the repo's own models. Temporarily point one role at a model with no credentials: the check reports it, and the block names the next candidate.

**Phase 3: apply.**
- Files: `model_plan.py` apply path, the command wiring, README.
- Python tests on a temporary `PI_CODING_AGENT_DIR`:
  - only steward keys and fields change; unknown keys and `machine` are preserved;
  - one backup per changing run; a second run is idempotent, with no write and no backup;
  - a file changed between read and write makes apply refuse;
  - `byMainProvider` compiles correctly; `main` becomes `inherit`; `enabled: false` skips a provider;
  - stale old-name keys migrate;
  - the profile file passes pi-subagents' profile validation rules (`profiles.js:41-71`).
- Node test: `apply` calls `ctx.reload()`.
- Live check: `apply`, then `/subagents-models` and `/subagents-check-profile steward`. Load another pi-subagents profile, run `check` and see drift reported, then `apply` restores the mapping.

**Phase 4: evidence (ships).** The existing `tool_result` handler (`index.ts:297-305`) appends one JSON line per accepted launch to `$XDG_STATE_HOME/steward/pi-delegations.jsonl`. Each line holds role, `isError`, duration, and whether it was a relaunch or an escalation. Model and thinking come from the child's `_meta.json` (`model`, `requestedModel`; also `workflow-children.jsonl` and the child session file), not from `tool_result`: the launch-time `details` carry `results: []` and `children: []` (`PS/src/runs/foreground/subagent-executor.js:5927`), and the resolved model is set later (`PS/src/runs/foreground/execution.js:1899`). The handler therefore reads the artifacts after the run settles. `/steward-models stats` summarizes success rate per role and model. This is the worker success rate the Zorost rule needs: delegate while worker cost divided by success rate stays below orchestrator cost. Cost per completed task beats per-token price as a measure (Arize). Python tests on the summarizer, node test on the append.

**Phase 5 (deferred): in-child failover.** Entry criteria:
- a live probe shows a foreground child resolving a virtual model registered by a router-only file listed in a package agent's `subagentOnlyExtensions`;
- pi-subagents' response-model verification accepts it;
- Phase 4 data shows provider errors, not stalls, cause most failed launches.

## Alternatives considered

- **Register the profiles at runtime with resolved models** through pi-subagents' `pi-subagents:runtime-agent-register:v1` event (`PS/docs/extension-api.md:174-207`, since 0.58.0). This avoids writing settings and resolves availability per session. Rejected for now:
  - runtime names collide with the package's file agents (collision checks, `PS/CHANGELOG.md:1104`), so steward would have to stop shipping `pi/agents/` and depend entirely on a process-local event contract;
  - `agentOverrides` still win over the definition (`extension-api.md:207`), so drift remains possible anyway.
  - It stays the fallback design if settings writes prove troublesome.
- **Ship plans as pi-subagents profiles only.** A profile cannot carry the main model, fallbacks or escalations. It replaces the whole `agentOverrides` mapping and writes user scope only (`profiles.js:359-386`). Kept as a secondary output of `apply`.
- **A learned or per-request router** (oh-my-openagent fallback chains, opencode-subagent-router task-type routing). Rejected. The plan's static roles with ordered fallbacks already match oh-my-openagent's pipeline: override, then category default, then provider fallback, then system default. Primary agents respect the UI model and subagents follow their own chain. Router benchmarks show little gain over the best single model (Arize).

## Risks

|Risk|Failure scenario|Mitigation|
|-|-|-|
|Precedence replica drifts from pi-subagents|pi-subagents changes layering in a release (it ships every few days, `README.md:111`); the block shows Sonnet while Flash launches|Live check against `/subagents-models` in every phase; the README names the tested pi-subagents version|
|Cheap executor is worse than it looks|Flash passes its own check but the reviewer keeps finding defects; cost per completed task rises above Sonnet's|Escalation rule; Phase 4 data; blackbox.ai showed the executor choice matters (Opus with GLM-5.2: 69.7 on Terminal-Bench 2.0 against 58.4 solo; with Kimi K2.7: no gain)|
|Main thread mis-copies the relaunch model|Typo, so a second failed launch|Exact strings in the block. Copilot's pass-the-model approach worked live (`docs/roadmap/copilot-port.md:27`)|
|Ollama stalls are not errors|A 30-40 s first-token stall per request (seen on minimax-m3) makes Ollama launches slow without failing; Ollama is now the primary Flash provider|Phase 4 outcome log shows duration per role and model; Fireworks fallback; the stall stays an open item|
|Concurrency caps are global, not per provider|A 4-task parallel run on Ollama Pro gets HTTP 429s|Check warning with concrete `config.json` values; the edict cap line|
|Settings write race|Pi saves `defaultModel` (Ctrl+S) while `apply` writes|Explicit command only; re-read and refuse on change; backup|
|Rename orphans overrides|Existing `steward.coder-opus-medium` overrides silently stop applying since 0.10.0|Stale-key check at session start; `apply` migrates; release note|
|Thinking is declared, not honored|Plan says `max` on Ollama, the provider ignores it, and the check passes|The check states that declared levels are not verified; prefer providers that honor them|
|Code leaves for third-party providers|A confidential repo's code is sent to Fireworks or Ollama Cloud|Per-repo `.pi/steward-model-plan.json` with `allowProviders`/`denyProviders` (v1 requirement). In 0.11.0 the lists are advisory: they change what the block tells the main thread about `steward.*` profiles and what the check reports, nothing more. The control that stops a launch is an enforced, strict `subagents.modelScope` in pi-subagents settings, which an untrusted project's copy cannot set|
|`inherit` follows a downgraded main|The operator switches main to Flash mid-session, so deep-reasoner inherits Flash|`model_select` rebuild plus the judgment-floor warning|

Resolved by the Phase 2 spike, 2026-10-11 (evidence commit `986ca75`):
- **Workflow `runs.run` honors a per-child `model`,** with the signature `runs.run(key, params)` (`PS/src/workflows/scripted-workflow.js:645-680`; `runs.run({...})` fails with "invalid key"). Live: `runs.run("probe", { agent: "steward.mechanic", task, model: "anthropic/claude-sonnet-5-5" })` gave meta `model: anthropic/claude-sonnet-5-5:medium`, `requestedModel: anthropic/claude-sonnet-5-5`; thinking came from the profile. Resolution: `PS/src/runs/foreground/execution.js:1725`. The built-in `parallel` workflow still takes only `{ agent, task }` per child; any other field is an error (`PS/src/workflows/structured-workflow-scripts.js:87`, `PS/src/workflows/workflow-resources.js:152-155`).
- **The steward extension can import `@earendil-works/pi-ai`** (`PIDIST/extensions/loader.js:33-84,471-476`). `getSupportedThinkingLevels` works. Supported levels: `amorphic/claude-opus-5-5` off to max; `ollama-cloud/deepseek-v4.1-flash` off, minimal, low, medium, high; Fireworks Flash off, low, high, max. `ctx.model` exposes `reasoning`, `thinkingLevelMap`, `maxTokens`; `ctx.modelRegistry` exposes `getAvailable`, `getAll`, `find`, `hasConfiguredAuth`; `ctx.isProjectTrusted()` exists.
- **`tool_result` for `subagent` does not carry the resolved model** (`PS/src/runs/foreground/subagent-executor.js:5927`: `results: []`, `children: []` at launch). It is in the child's `_meta.json`, `workflow-children.jsonl` and the child session file. Phase 4 reads it there.
- **`modelThinkingLevels` outranks `defaultThinkingLevel`,** with the full order recorded in the Main thread section (`PIDIST/sdk.js:121-143`).
- **Fireworks Flash declares `off`, `low`, `high`, `max`** (`pi-ai/dist/providers/data/fireworks.json`); a live `:max` run recorded thinkingLevel `max`.
- **A live pi session resolves the 0.10.0 aliases** (done 2026-10-11 at `7dffda0`; Phase 1 open item 1).

Closed in 2d: a ```` ```js ```` workflow block written in the assistant reply is not visible to the `subagent` tool, in print mode or in an interactive session. The edict passes scripts as file paths only.

Still open:
- whether a synchronous single-child `subagent` result carries the resolved model in `details.results[]` (findings say sync runs likely do; not probed live);
- whether Fireworks honors `max` beyond recording the level (not measured).

Confirmed since 2026-10-09: `amorphic/claude-opus-5-5` declares `max` in `~/.pi/agent/models.json` (`thinkingLevelMap` `xhigh` and `max`), so the top reviewer's `max` is not clamped. pi-subagents 0.77.0 shipped the project-trust change and the built-in `parallel` workflow noted above (`PS/CHANGELOG.md:5-13`).

## Operator decisions, 2026-10-09

1. **Main thread default: steward sets none.** The main thread runs on whatever model and thinking level pi on the client machine picks (`defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels`, `/model`). The plan's `main.models` list is only what the check compares against. The earlier claim that pi caps `amorphic/claude-opus-5-5` at `high` was wrong: a stale `modelThinkingLevels` entry (`high`) in `~/.pi/agent/settings.json` caused it, not an amorphic or pi limit. It was set to `xhigh` on 2026-10-09, and a plain `pi -p` run then recorded thinkingLevel `xhigh`.
2. **Most roles on DeepSeek V4.1 Flash, not all.** Coder, researcher, writer and mechanic on Flash. Deep-reasoner on the main thread's model (`"model": "main"`). Reviewer on a different family from the main thread. Top-reviewer on Fable. The "all on Flash" variant stays documented as allowed with warnings but is not the operator's choice. (Superseded for top-reviewer on 2026-10-11, see below.)
3. **Flash provider order: Ollama Cloud first, Fireworks as fallback.** Ids: `ollama-cloud/deepseek-v4.1-flash`, then `fireworks/accounts/fireworks/models/deepseek-v4p1-flash`. Ids differ per provider, so fallbacks are written per provider. The `providers` block carries Ollama's cap of 3 concurrent requests on Pro. Trade-offs are in the plan file section.
4. **Thinking on Flash:** coder `high`, researcher `high`, writer `high`, mechanic `low`; never `off`. Evidence in the next section.
5. **Rename the pi profiles to role-only names in 0.9.0**, with the old names kept as pi-subagents aliases. (Update 2026-10-11: shipped as 0.10.0, because 0.9.0 and 0.9.1 went to other changes first. See Phase 1.)
6. **`apply` also writes a pi-subagents profile file** so `/subagents-check-profile` can probe every model. The per-launch outcome log ships (Phase 4).
7. **A per-repo override is required in v1.** A repo can pin profiles away from third-party providers (for example everything on Anthropic or OpenAI). Shape: `.pi/steward-model-plan.json`, project wins over user, `allowProviders`/`denyProviders` enforced by the check (Scope section; tests in Phase 2). As built in 0.11.0 the lists are advisory; see 2026-10-12 decision 9.
8. **Steward's own `.pi/settings.json` is committed.** It pins every `steward.*` profile to `amorphic/claude-*` for work inside this repo. Its keys must move to the role-only names in 0.9.0, and it overrides the user plan inside this repo. (Update 2026-10-11: moved in 0.10.0; the override applies only in a trusted project.)

## Operator decisions, 2026-10-11

Changes since the plan was written; the 2026-10-09 text above stays as history.

1. **Top reviewer moved from Fable 5.1 at `xhigh` to Opus 5.5 at `max`** (steward 0.9.0, `skills/delegating/routing.md`, section "Top reviewer on Opus 5.5 max (operator decision 2026-10-11)"; evidence in `docs/evaluations/2026-10-09-model-assignment-evidence.md`). This replaces the Fable half of 2026-10-09 decision 2. The pi profile `reviewer-fable-xhigh` became `reviewer-opus-max` with no alias at that point; the operator-case plan JSON now uses `amorphic/claude-opus-5-5` at `max`, which that model declares (see Operator's case).
2. **Fable by name is a per-call override.** A request for Fable runs the top reviewer with `model: "anthropic/claude-fable-5-1:xhigh"` (the `:level` suffix sets thinking). This is the one case where the edict allows a per-call `model` besides relaunch, escalation and operator requests.
3. **Everyday review stays on Sonnet 5.5 at `high`** (steward 0.9.1, `routing.md`, section "Reviewer stays on Sonnet 5.5 high (operator decision 2026-10-11)"). Diffs touching auth, payments, concurrency or data migrations go to deep-reasoner. The plan's `reviewer` role keeps its Sonnet default and cross-family rule.
4. **Both old top-reviewer names stay as aliases** (today, 0.10.0): `steward.top-reviewer` lists `steward.reviewer-opus-max` and `steward.reviewer-fable-xhigh`, so a saved launch under either name resolves.
5. **Rename shipped as 0.10.0**, not 0.9.0 (decision 5 above).

## Operator decisions, 2026-10-12

1. **Escalation can name a role.** `escalate` accepts `role:<role>`: the failed check is relaunched on that steward profile with its own model and thinking, so the target takes no `:level`. An unknown role or the role itself is a schema error. The allow/deny lists are checked against the target's effective binding too, so a role target cannot bypass them.
2. **Operator's case plan updated** (see Operator's case): deep-reasoner gets `"escalate": null`; reviewer gets `"escalate": "role:deep-reasoner"`; top-reviewer gets `"fallback": ["anthropic/claude-opus-5-5:max"]` and `"escalate": null`, and stays on `amorphic/claude-opus-5-5` at `max`. No judgment role binds, relaunches or escalates to Flash.
3. **Untrusted projects keep their provider lists.** From an untrusted project's plan files only `allowProviders` and `denyProviders` are read, validated and size-capped; every other field stays ignored. An untrusted project's `.pi/settings.json` stays ignored, as in pi-subagents 0.77.0 (Scope section).
4. **S5: `byMainProvider` drops the replaced model.** When a `byMainProvider` entry replaces a role's model, the replaced model is not kept as a relaunch candidate, so a relaunch never returns to the main thread's family.

### Release review of Phase 2, 2026-10-12

A deep-reasoner release review of `986ca75..55106f6` (evidence in `/tmp/steward-p2-review/review.md`) found the code sound and fail-open, but four edict rules misfired on the block a user without a plan file gets. 0.11.0 is tagged only with these fixes, made on branch `pi-model-plan-2d` after `55106f6`:

5. **Judgment floor applies only to `no`.** Architecture, plans, security review and final synthesis go only to a profile whose Judgment-grade cell says `yes`; if every cell says `no`, the work stays on the main thread. `not checked` (no plan, or a plan without `judgmentModels`) or no block sets no floor: route by the routing table, so `steward.deep-reasoner` keeps that work.
6. **No-relaunch rule.** With no relaunch model (`none`, or no such column), the main thread does not choose a model itself. After an overload, rate-limit or timeout error it relaunches the same profile once, without `model`, after checking what the failed child already changed; after any other provider error, or a second failure, it does small or read-only work itself or tells the operator. pi's own in-child retry (3 retries from 2 s) covers about 14 s, shorter than a typical overload. Guardrail 4 now says "never a model the block does not name" instead of "never the same model twice". With no escalation model, a failed check goes to the main thread or `steward.deep-reasoner`; a row marked unavailable with no model to pass is not launched.
7. **Cross-family review has a target without a plan.** Review with a profile of another family when the block shows one; when all share one family, use the routing table's reviewer.
8. **Per-call strings never abort.** Relaunch, escalation and "pass model X" strings are checked as per-call models against an enforced `subagents.modelScope` and `subagents.maxThinking`. A refused relaunch or pass-model candidate is skipped for the next one; with none left the cell says `none` (or "unavailable; no model to pass") and the full report gives the reason (`effective-relaunch-none`, `escalation-none`, `pass-model-none`). An effective binding above `maxThinking`, or outside a strict enforced scope, is blocked ("do not launch"). A "pass model X" row relaunches on the candidate after X, never on X. The drift hint says to set `subagents.agentOverrides` by hand (README recipe), since 0.11.0 has no `/steward-models apply`.
9. **Provider lists are advisory in 0.11.0.** `allowProviders` and `denyProviders` change what the block tells the main thread and what the check reports. The hard control is an enforced, strict `subagents.modelScope` in pi-subagents settings (an untrusted project's copy is ignored). The README says so.
10. **Smaller fixes.** `STEWARD_HOOK_LOG` records only session-start and `model-plan` calls, and the README says what it holds. The README example plan gives deep-reasoner and top-reviewer `"fallback": null` and `"escalate": null`, so no judgment role falls back to Sonnet, and a test pins that JSON. The block heading says it is rebuilt on a model or thinking switch. The thinking guardrail now reads "never raise a cheap role's thinking per call". The README calls the guardrails the edict's, not the block's.
11. **Left open, with reasons; N9 fixed.** Per-model warnings on a plan binding still fire when only frontmatter differs (review N10): before `apply` exists they are the only notice of a problem in the plan itself, and `apply` (Phase 3) makes the plan binding the launch. N9 (after a switch whose rebuild failed, every later prompt reran the load, and session start could take 30 s) is fixed. The rule: a failed or timed-out load is never retried by a prompt. The prompt keeps the last good edict, or the plain edict from the fallback call, and the next load comes only with the next `model_select`, `thinking_level_select` or new session. The session-start call that carries `model_facts` gets 5 s, and the plain retry gets what is left of the 15 s hook budget, so one load, and so session start, never takes more than 15 s. A plain call with no facts before it keeps the full 15 s. When even the plain call gives no edict and none has loaded yet, the extension does what 0.10.0 did: no edict, and the next prompt tries the plain call again. Two items from the 2a reviews also stay open for Phase 3: an `evaluate` failure while project list files exist drops the block, so no "do not launch" signal appears; and the `scoped` modelScope pattern is assumed empty.

## Thinking levels for DeepSeek V4.1 Flash

Research and local tests, 2026-10-09, to set the per-role levels in the plan.

- **Model card** (huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash): reasoning effort is continuous, 1 to 100. All published results are at max (100).
- **V4.1 report via glbgpt review** (glbgpt.com/hub/deepseek-v4-1-flash-review, 2026-09-11): raising effort from 25 to 100 moved DeepSWE v1.1 from 66.0 to 74.2 and Terminal-Bench 2.1 from 82.4 to 90.6, at about 2.5x output tokens.
- **DeepSeek API thinking-mode guide** (api-docs.deepseek.com/zh-cn/guides/thinking_mode): named levels map low to low, medium to high, high to high, xhigh to high, max to max, ultra to max. **DeepSeek changelog** (api-docs.deepseek.com/updates): low for simple tasks, high for daily agent tasks, max for complex scenarios.
- **Artificial Analysis via The Elec** (thelec.net, 2026-09-16): about 214 output tokens/s and 1.13 s TTFT, so higher effort costs little wall-clock.
- **Local tests on this machine:**
  - (a) pi clamps `--thinking xhigh` and `max` to `high` for `ollama-cloud/deepseek-v4.1-flash` (pi recorded thinkingLevel `high` for both), because its `models.json` entry declares no xhigh or max levels. High is the effective ceiling through pi on Ollama.
  - (b) Direct Ollama calls with `reasoning_effort` `none` gave wrong answers on a two-step arithmetic question (2 of 2 wrong, 11 tokens). Low, medium, high and max all answered correctly with similar token counts (164 to 361).
  - (c) On a modular-arithmetic question, Ollama and Fireworks at low, high and max all answered correctly with 279 to 546 completion tokens and no effort scaling.
  - Short prompts cannot show the effort effect the vendor reports on long agentic tasks.

|Role|Level|Reason|
|-|-|-|
|coder|high|Agentic work with a verifiable check. Max is unreachable through pi on Ollama (test a), and DeepSeek maps medium to high anyway|
|researcher|high|Daily agent task with tool use. Medium is the same as high on DeepSeek's API|
|writer|high|Same reasoning as researcher; the prose rules are many|
|mechanic|low|DeepSeek's simple-task level. Never off (test b)|

Fireworks Flash declares `off`, `low`, `high`, `max` in pi's catalog (no `medium`, no `xhigh`; probed 2026-10-11, live `:high` and `:max` runs ok after the Fireworks fix in the plan file section). Open item, now possible: a failed coder check could escalate to Flash at `max` on Fireworks before escalating to the main model; the Ollama entry stops at `high`. Whether Fireworks honors `max` beyond recording the level is not measured.

## Evidence base

- **Local, read 2026-10-09:**
  - steward `f9e319a` (re-verified 2026-10-11; first read at `a2ab9eb`): files cited above;
  - `~/.pi/agent/settings.json` (`defaultProvider: amorphic`, `defaultModel: claude-opus-5-5`, `defaultThinkingLevel: xhigh`, `modelThinkingLevels`);
  - `~/.pi/agent/models.json` (providers `anthropic`, `ollama-cloud`, `amorphic`; the hand-written `fireworks` provider was removed 2026-10-11);
  - `~/.pi/agent/auth.json` (provider names only: `anthropic`, `openai-codex`, `openai`, and since 2026-10-11 `fireworks`, type `api_key`);
  - `pi --list-models` on pi 1.1.0; pi docs and type declarations under `PIDOCS` and `PIDIST`;
  - pi-subagents 0.77.0 docs and source under `PS` (first read at 0.76.1).
- **OpenCode:** per-agent `model`, `mode: primary|subagent`, subagents inherit the parent model when unset, `small_model` for hidden agents (opencode.ai/docs/agents, opencode.ai/v2/docs/agents). Issue anomalyco/opencode#26925 asks for a per-call model parameter ("Mix Code Mode").
- **nkapila.me/posts/opencode-config (2026-07-13):** boss orchestrator; junior-dev and researcher on deepseek-v4-flash; reviewer on gemma4:31b, a different family on purpose; Ollama Cloud concurrency (Max 10, the orchestrator counts as 1) was the real constraint.
- **oh-my-openagent** (code-yeongyu, `packages/omo-opencode/src/agents/AGENTS.md`): per-agent defaults with ordered fallback chains, `requiresProvider`, and a resolution pipeline of override, then category default, then provider fallback, then system default.
- **opencode-subagent-router:** overrides the subagent model by task type; escalates to the flagship after repeated failure; reverts when cheap output gets re-tasked.
- **Anthropic, anthropic.com/engineering/multi-agent-research-system:** an Opus lead with Sonnet subagents beat single Opus by 90.2%. Token usage explains 80% of the variance, and multi-agent runs use about 15x chat tokens.
- **arXiv 2601.11327**, "Can Small Agents Collaborate...": performance is limited by the planner, not the executor. Orchestrator thinking gives the largest gains, and with it, sub-agent size barely matters.
- **Writer, "Harness Effect", arXiv 2607.06906:** delegation is reliable only on the two strongest models (about 0.85) and unusable on the fast tier (about 0.42-0.45).
- **Arize, 2026-08-07:**
  - a Fable 5 orchestrator with Sonnet 5 workers kept 96% of the all-Fable BrowseComp score at 46% of the cost;
  - cost per completed task matters more than per-token price;
  - LLMRouterBench: routers often fail to beat the single best model.
- **blackbox.ai orchestrator-executor:** Opus 4.8 with a GLM-5.2 executor scored 69.7 on Terminal-Bench 2.0, against 58.4 solo; with a Kimi K2.7 executor, 58.4.
- **Zorost orchestrator-worker guide:** the delegation contract; escalate on judgment through tiers; delegate only while worker cost divided by success rate stays below orchestrator cost; measure worker success rate per subtask type.
- **Operator, 2026-10-09:**
  - Ollama Cloud minimax-m3 had intermittent 30-40 s first-token stalls with a system message;
  - Ollama Pro allows 3 concurrent requests and Max allows 10;
  - deepseek-v4.1-flash is on both Fireworks and Ollama Cloud;
  - Ollama appeared to ignore `reasoning_effort` `max`.
- **DeepSeek Flash thinking research, 2026-10-09:**
  - huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash (model card, effort 1 to 100);
  - glbgpt.com/hub/deepseek-v4-1-flash-review (2026-09-11; effort 25 vs 100 on DeepSWE v1.1 and Terminal-Bench 2.1);
  - api-docs.deepseek.com/zh-cn/guides/thinking_mode and api-docs.deepseek.com/updates (level mapping and guidance);
  - thelec.net (2026-09-16; Artificial Analysis speed figures);
  - local pi and direct-API tests on Ollama Cloud and Fireworks, and the `modelThinkingLevels` correction in `~/.pi/agent/settings.json`.
