# Proposal: a model plan for steward on pi

Status: proposed, 2026-10-09. Operator decisions recorded the same day; nothing is built yet.

## Summary

The operator wants to configure once, per pi installation, which model runs the main thread and which models run steward's delegated profiles, across providers. Example: a main thread on `openai-codex/gpt-6.1-sol` or `amorphic/claude-opus-5-5` at `xhigh`, and most profiles on DeepSeek V4.1 Flash. Steward does not choose the main thread's model; the plan only names the models it expects.

Recommendation: steward builds no model router and owns no main-thread setting. Pi already sets the main thread's model and thinking level, and pi-subagents already binds one model and one thinking level per agent for every launch path. Steward adds four thin pieces on top:

1. **Role-only pi profile names** (`steward.coder`, `steward.deep-reasoner`, ...) with the old names kept as pi-subagents `aliases`, as the Copilot and Codex ports already did.
2. **A steward-owned plan file**, `$PI_CODING_AGENT_DIR/steward/model-plan.json` (default `~/.pi/agent/steward/model-plan.json`). It holds per-role model and thinking plus what pi-subagents refuses to store: ordered fallbacks, escalation targets, provider concurrency caps, and the list of judgment-grade models.
3. **A `/steward-models` command.** `check` is a dry run that prints the resolved per-role mapping, where each binding comes from, and every problem. `apply` compiles the plan into the `steward.*` keys of `subagents.agentOverrides` and `subagents.agentOverridesByProvider` in user settings, with a backup.
4. **A generated "Model plan" block in the edict** at session start, rebuilt on every model switch. It names the model each profile will actually run on, the model to relaunch with after a provider error, and the model to escalate to after a failed check, and it states the guardrails.

Fallback stays an explicit relaunch by the main thread. pi-subagents removed same-launch fallback on purpose and says a different model needs a later explicit launch. Virtual-model failover inside a child is deferred, because foreground children cannot resolve a virtual model that the parent registered. Claude Code, Copilot and Codex behavior does not change.

Path abbreviations used below: `PIDOCS` is `/home/dev/.pi/agent/install/releases/1.1.0/node_modules/@earendil-works/pi-coding-agent/docs`; `PIDIST` is the sibling `dist/core`; `PS` is `/home/dev/.pi/agent/npm/node_modules/pi-subagents` (0.76.1). Repo paths are relative to the steward repo at `a2ab9eb`.

## Build versus reuse

|Need|Reuse from pi or pi-subagents|Steward builds|
|-|-|-|
|Main-thread model and thinking|`defaultProvider`, `defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels` (`PIDOCS/settings.md:11-16`); `/model` then Ctrl+S, `/thinking` then Ctrl+S, `/scoped-models` (`PIDOCS/models.md:29-33`)|A check only: warn when the session's model is not in the plan, is below the judgment floor, or starts at a different thinking level|
|Per-role model and thinking|`subagents.agentOverrides.<agent>.model` and `.thinking`; `model: "inherit"` (`PS/docs/models.md:14,20`)|The plan file; `apply` writes only `steward.*` keys|
|Choices that depend on the main model|`subagents.agentOverridesByProvider.<parentProvider>.<agent>`, keyed on the active parent model's provider (`PS/docs/models.md:45-64`)|`byMainProvider` in the plan compiles to it|
|Policy limits|`subagents.modelScope` (policy only, `PS/docs/models.md:191-221`), `subagents.maxThinking` (`PS/docs/models.md:125-138`)|The check reads both and reports conflicts. It never writes them|
|Live probe of each model|`/subagents-check-profile <name>`: registry lookup plus a one-shot `pi -p --model X --no-tools` probe with a 45 s timeout (`PS/docs/models.md:251`, `PS/src/profiles/profiles.js:226-234,501-525`)|`apply` also writes a `steward` profile file so that probe can run on the plan|
|Live mapping|`/subagents-models` (`PS/docs/models.md:167-176`)|`/steward-models check` adds plan versus effective binding, sources, fallbacks, warnings|
|Fallback after a provider error|None. `fallbackModels` was removed in 0.68.0 (`PS/CHANGELOG.md:404`) and is rejected by the parsers (`PS/src/agents/agents.js:736-737`, `PS/src/profiles/profiles.js:66-67`)|Rendered relaunch model plus an edict rule|
|Escalation after a failed check|None|Rendered escalation model plus an edict rule|
|Concurrency|`parallel.concurrency` (default 4), `globalConcurrencyLimit` (default 20), `maxActiveAsyncRunsPerSession` (unset), all in `~/.pi/agent/extensions/subagent/config.json` and none per provider (`PS/docs/configuration.md:373-381,405-411,447-456`)|Per-provider `maxConcurrent` in the plan; the check warns; the edict states the cap|

### Why a steward plan file instead of only validating pi-subagents settings

Validating hand-written `subagents.agentOverrides` would be thinner by one file, and Phase 0 below does exactly that with no code. The plan file still pays for itself for four reasons:

- **Fallbacks and escalations have nowhere else to live.** pi-subagents throws on `fallbackModels` in settings and profiles (references above), and it has no escalation field.
- **pi-subagents profile switches erase the mapping.** `/subagents-load-profile` replaces the whole `agentOverrides` object in user settings (`PS/src/profiles/profiles.js:359-386`, "A profile owns the complete agent mapping"). The plan file survives that, and `apply` restores the `steward.*` keys.
- **Role keys outlive runtime names.** The plan says `coder`. `apply` maps that to whatever runtime name the profile has and migrates stale keys. pi-subagents config keys must use canonical names (`PS/docs/agents.md:355`), so a rename otherwise silently orphans overrides.
- **One shape across ports.** Codex already keeps per-role model, effort and a `retry` (escalation) entry in `codex/skills/delegating/profiles.json:7,41`.

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
  "judgmentModels": ["openai-codex/gpt-6*", "amorphic/claude-opus-5*", "amorphic/claude-fable-5*"],
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
      "byMainProvider": {
        "amorphic": { "model": "openai-codex/gpt-6.1-sol", "thinking": "medium" }
      }
    },
    "deep-reasoner": {
      "model": "main",
      "thinking": "xhigh",
      "fallback": ["amorphic/claude-opus-5-5", "openai-codex/gpt-6.1-sol"]
    },
    "top-reviewer": { "model": "amorphic/claude-fable-5-1", "thinking": "xhigh" }
  }
}
```

What this does: coder, researcher, writer and mechanic run on Flash through Ollama Cloud and fall back to the same model on Fireworks. Thinking is `high`, except mechanic on `low`, never `off` (see the Flash thinking section). Deep-reasoner runs on whatever the main thread runs (`inherit`), at `xhigh` where the model supports it. `main.models` and `main.thinking` are only what the check compares the session against; steward never sets the main thread. The reviewer is never DeepSeek, and it is never the main thread's family either: Sonnet when the main thread is Sol, Sol when the main thread is Opus on `amorphic`. Top-reviewer stays on Fable.

The "everything on Flash" variant is the `"*"` entry alone, with no other roles listed. It is allowed but is not the operator's choice. The check and the edict then warn that deep-reasoner and top-reviewer are below the judgment floor and that the reviewer shares the coder's family, and the edict tells the main thread to keep judgment work inline.

Trade-offs of Ollama first, Fireworks as fallback, on this machine's catalog (`pi --list-models`, 2026-10-09): Ollama Pro allows 3 concurrent requests (the `providers` block carries that cap, and the check and edict state it). `ollama-cloud/deepseek-v4.1-flash` declares only 16.4K max output in `~/.pi/agent/models.json`, which can truncate large coder edits (the check warns below 32K). Its entry also declares no `xhigh` or `max` level, so pi clamps both to `high` (see the Flash thinking section). `fireworks/accounts/fireworks/models/deepseek-v4p1-flash` declares 1M context and 384K max output, so it is the better fallback for long outputs, but it is paid per token. The ids differ between providers (`deepseek-v4p1-flash` against `deepseek-v4.1-flash`), and pi-subagents' fuzzy matching never switches providers (`PS/docs/models.md:178-190`), so each fallback is written out per provider.

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
|`roles.<role>.fallback`|Ordered `provider/id[:level]` list|`apply` binds the first available candidate; the next available one is rendered as the relaunch model. A candidate equal to the bound model is skipped|
|`roles.<role>.escalate`|`provider/id[:level]` or `main[:level]`|Rendered as the escalation model|
|`roles.<role>.byMainProvider.<p>`|`{ model, thinking }` used when the main thread's provider is `p`|`agentOverridesByProvider.<p>["steward.<role>"]`|
|`roles["*"]`|Defaults merged under every role, field by field|Per role|
|`families`|Optional overrides of the built-in family patterns (`*claude*`, `*gpt-*`, `*deepseek*`, `*kimi*`, `*glm*`, `*qwen*`, `*gemma*`, `*minimax*`)|Nothing: cross-family check|

Rules the check enforces:

- **Fully qualified ids only.** A bare id resolves against the current parent provider (`PS/docs/models.md:14`), so it would change meaning when the main thread switches between `openai-codex` and `amorphic`.
- **Versioned ids over router aliases.** `fireworks/accounts/fireworks/routers/deepseek-flash-latest` moves underneath the plan. pi-subagents also verifies the response model id strictly unless `modelResponseAliases` declares it (`PS/docs/configuration.md:51-65`). Warn on `/routers/` and `-latest` ids.

### Scope: user plan plus a required per-repo override

Decision 2026-10-09: a per-repo override is a v1 requirement. A repo must be able to pin steward profiles away from third-party providers, for example to keep everything on Anthropic or OpenAI.

Shape: a project file `<repo>/.pi/steward-model-plan.json`, in the same schema as the user plan, read only when the project is trusted (`ctx.isProjectTrusted()`, `PIDIST/extensions/types.d.ts:236`). Reasons for a separate file over a `steward` block in `.pi/settings.json`: pi-subagents and pi own that file's schema, and an unknown top-level block risks being rejected or rewritten by them; this repo already commits `.pi/settings.json` for a different purpose; a plan file keeps fallbacks, escalations and provider lists, which settings cannot hold.

Rules:
- **Project wins over user**, field by field, role by role, the same merge as `"*"`. The check names the winning file for every binding.
- **`allowProviders` and `denyProviders`** (lists of provider ids, project file only). The check errors when any bound model, fallback or escalation target sits on a denied provider or outside a non-empty allow list, and `apply` skips those candidates. A repo with `"allowProviders": ["amorphic", "anthropic"]` can never see a Flash binding.
- **pi-subagents `.pi/settings.json` overrides still apply** after the plan compiles, field by field (`PS/src/agents/agents.js:1347-1359`). `apply` writes user settings only and never writes into a repo.
- Phase 2 builds the merge and enforcement; the tests are listed there.

Known instance: this repo's committed `.pi/settings.json` pins all seven `steward.*` profiles to `amorphic/claude-*` for work inside this repo. It overrides the `model` field of any user plan here. Its keys are old profile names and must move to the role-only names in 0.9.0 (Phase 1).

## Main thread

- **Steward sets no default.** The main thread runs on whatever model and thinking level pi on the client machine picks: `defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels`, and `/model` (`PIDOCS/models.md:29-33`). Selecting a model in `/model` then Ctrl+S, `/thinking` then Ctrl+S, and `/scoped-models` for Ctrl+P switching are all pi's own.
- **Check, never switch.** At `session_start` and on every `model_select` event (`PIDIST/extensions/types.d.ts:861-866`, sources `set`, `cycle`, `restore`), the extension reads `ctx.model` and `ctx.thinkingLevel` (`types.d.ts:225-234`) and rebuilds the plan block. The next run's system prompt carries the new block; `before_agent_start` already re-adds the edict on every run (`pi/extensions/steward/index.ts:222-240`). A model switch already costs the prompt cache, so the rebuild adds no extra cache miss.
- **A session on a different model.** If the main model is not in `main.models`, the block opens with a `STEWARD WARNING` telling the main thread to inform the operator and name `/model`. That follows the existing warning pattern (`hooks/steward_hook.py:166-181`). If the model is also outside `judgmentModels`, the warning adds that delegation decisions are unreliable on fast-tier models (Harness Effect, below). Roles bound to `main` inherit that model, so the warning lists them too. `agentOverridesByProvider` follows the new provider at the next launch on its own (`PS/docs/models.md:64`).
- **Thinking drift.** The effective startup level is `modelThinkingLevels["<provider>/<id>"]`, falling back to `defaultThinkingLevel` (`PIDOCS/settings.md:13-14`; per-model precedence is inferred from the description, verify it). Earlier drafts said pi caps `amorphic/claude-opus-5-5` at `high`. That was wrong: it was a stale `modelThinkingLevels` entry (`high`) in `~/.pi/agent/settings.json`, not an amorphic or pi limit. It was set to `xhigh` on 2026-10-09, and a plain `pi -p` run then recorded thinkingLevel `xhigh`. The check still reports a stale per-model entry that differs from `main.thinking`.
- **Not used: `pi.setModel()` and `setThinkingLevel()`** (`types.d.ts:1274-1281`). They would override an explicit operator choice, including a resumed session's restored model.
- **Not used: a steward virtual main model.** With a virtual model selected, `ctx.model` is the virtual selection (`PIDOCS/virtual-models.md:23`). pi-subagents would then key `agentOverridesByProvider` on the virtual provider, and `inherit` would expand to the virtual id (`PS/docs/models.md:221`), which a foreground child cannot resolve (next section).

## Fallback and availability

|Option|Mechanism|Verdict|
|-|-|-|
|A. Static availability at `apply`|Bind the first candidate that is in the registry and whose provider has credentials (`modelRegistry.find`, `hasConfiguredAuth`, `PIDIST/model-registry.d.ts:27-32`); skip providers with `enabled: false`|Build, Phase 3|
|B. Re-check at session start|If the bound model is no longer available, the block's row says to pass the next available candidate as `model` on every launch of that profile until `apply` is rerun|Build, Phase 2|
|C. Relaunch rule in the edict|After a provider error, one explicit relaunch with the rendered model. pi-subagents prescribes this itself: "To try another model, the parent or operator must issue a later explicit launch" (`PS/docs/models.md:106`). Per-call `model` with a `:level` suffix outranks every binding (`PS/docs/models.md:14`, `PS/docs/tool-reference.md:78`)|Build, Phase 2|
|D. Rewrite `subagent` input in `tool_call`|The extension injects `model` (input mutation is allowed, `PIDOCS/extensions.md:105`)|Reject. Workflow scripts carry agent names in the script, not the tool input. Per-call models count as explicit, so an enforced `modelScope` aborts the run instead of warning (`PS/docs/models.md:214`). The transcript would show a model the main thread did not choose|
|E. Virtual model per role that switches on `retry`|`pi.registerVirtualModel` with `request.failed` (`PIDOCS/virtual-models.md:65-86`)|Defer to Phase 5. Explained below|
|F. pi-subagents `fallbackModels`|Removed in 0.68.0 (`PS/CHANGELOG.md:404`)|Not available|

Why E is deferred. Checked in the pi-subagents source:

- **Foreground children cannot see the parent's virtual models.** A foreground child copies the parent's providers only (`inheritParentProviders`, `PS/src/runs/shared/child-session.js:45-75,401-404`). It registers virtual models only from extensions the child itself loads (`child-session.js:229-252`). Foreground children load no ambient extensions (`PS/docs/agents.md:360,457`). So a steward-registered virtual model resolves in the parent at launch time and then fails inside the child, unless every profile lists a router extension in `extensions` or `subagentOnlyExtensions`.
- **That router cannot be the steward extension file.** Its child guard checks only `PI_SUBAGENT_CHILD` (`pi/extensions/steward/index.ts:159`). Only the background runner sets that variable (`PS/src/runs/background/subagent-runner.js:87`), so inside an in-process foreground child the edict and gates would switch on. The other route, `registerRequiredChildExtensions`, needs pi-subagents to be a Node dependency of steward, which a separately installed package is not (`PS/docs/extension-api.md:191`).
- **It would not catch the failures that matter here.** Pi retries only after an error (`retry.*`, `PIDOCS/settings.md:125-131`). A 30-40 s first-token stall like Ollama Cloud's is slow, not failed.
- **Changing models mid-task has costs.** It drops the prompt cache, can change model family halfway through a task, and depends on pi-subagents' response-model verification handling `virtualModelId` (`PS/src/runs/foreground/execution.js:1037`), which is unverified.
- **The evidence for routers is weak.** Routers often fail to beat the single best model (Arize, LLMRouterBench).

Error versus failed check: a provider error (HTTP 429, 5xx, authentication, timeout, empty response, context overflow) means "same tier, other provider", so use the fallback. A failed verifiable check means "stronger model", so use the escalation. The edict keeps the two apart.

## Profile names on pi

Decision: role-only canonical names, with the old names as aliases. This matches the Copilot decision of 2026-10-09 ("A role-and-effort name would be wrong whenever a machine binds a model whose effort differs", `docs/roadmap/copilot-port.md:216-221`) and the Codex names (`docs/roadmap/codex-port.md`, Profiles). Under a mixed plan `steward.coder-opus-medium` would run DeepSeek at `high`, and the main thread reads that name.

|Old runtime name|New canonical name|Alias kept|
|-|-|-|
|`steward.coder-opus-medium`|`steward.coder`|`steward.coder-opus-medium`|
|`steward.deep-reasoner-opus-xhigh`|`steward.deep-reasoner`|`steward.deep-reasoner-opus-xhigh`|
|`steward.reviewer-sonnet-high`|`steward.reviewer`|`steward.reviewer-sonnet-high`|
|`steward.researcher-sonnet-low`|`steward.researcher`|`steward.researcher-sonnet-low`|
|`steward.writer-sonnet-medium`|`steward.writer`|`steward.writer-sonnet-medium`|
|`steward.mechanic-haiku-medium`|`steward.mechanic`|`steward.mechanic-haiku-medium`|
|`steward.reviewer-fable-xhigh`|`steward.top-reviewer`|`steward.reviewer-fable-xhigh`|

How it works in pi-subagents:

- **Aliases are taken verbatim**, with no package prefix (`PS/src/agents/agents.js:406-410,1903`). Resolution tries canonical names first, then local names, then aliases (`agents.js:420-448`). `subagent({ agent: "steward.coder-opus-medium" })` in `~/AGENTS.md:21`, `~/.pi/agent/AGENTS.md:21`, old briefs and saved workflows keeps working.
- **Config keys do not follow aliases.** "Runtime status, persistence, and config still use the canonical name" (`PS/docs/agents.md:355`). An existing `agentOverrides["steward.coder-opus-medium"]` stops applying silently. The README entry (`README.md:138-148`) and this repo's `.pi/settings.json` both use the old keys. The check flags stale keys, and `apply` moves them.
- **Bare names change meaning slightly.** Bare `coder` now resolves to `steward.coder` by local name before pi-subagents' builtin `worker` alias `coder` (`agents.js:431-438`; alias added in 0.39.0, `PS/CHANGELOG.md:1540`). The edict always uses the `steward.` prefix, so steward's own calls are unaffected.
- **Frontmatter models stay Anthropic** (`pi/agents/*.md:5-6`). That is the default when no plan or override exists, so an install without a plan behaves exactly as it does today.
- **Claude Code keeps its names.** There the frontmatter pins Claude models, so the names stay true.

## Edict changes

### Static text in `pi/skills/steward-delegating/SKILL.md`

- **Rule 2** (`SKILL.md:10`) today says each profile "pins its model and thinking level" and forbids per-call `model`. New text: pick the profile by task; the model plan decides model and thinking; the "Model plan" block below shows what each profile runs on. Pass `model` only in three cases: to relaunch after a provider error, to escalate after a failed check, or when the operator asks. In each case copy the exact string from the block.
- **Routing table** (`SKILL.md:25-38`): role-only names. "a coordinator plus sonnet workers" becomes "a coordinator plus cheap workers".
- **"Keep it inline" section**: add "the only profile for the task is below the judgment floor in the Model plan block".
- **"How to call"**: the example becomes `subagent({ agent: "steward.mechanic", ... })`.
- **New "Guardrails" section** (static):

|Guardrail|Edict wording, short|Evidence|
|-|-|-|
|Judgment stays above the floor|Architecture, plans, security review, and final synthesis go only to a profile marked judgment-grade in the block; if none is, keep the work on the main thread|Delegation is reliable only on the two strongest models (about 0.85) and unusable on the fast tier (about 0.42-0.45) (Writer, arXiv 2607.06906). Performance is limited by the planner, not the executor (arXiv 2601.11327)|
|Cheap models get bounded tasks with a check|A profile below the floor gets a task with a verifiable done-condition: tests, types, lint, or a command whose output proves it|Delegation contract: objective, schema, tools, budget, boundary, done-condition (Zorost). Briefs need objective, output format, tools, boundaries (Anthropic multi-agent research system)|
|Escalate on a failed check|One failed check leads to one relaunch with the escalation model; a second failure goes to the main thread or `steward.deep-reasoner`|Escalation after repeated failure, revert when cheap output gets re-tasked (opencode-subagent-router). Codex `retry` entries (`codex/skills/delegating/profiles.json:7,41`)|
|Fallback is not escalation|A provider error leads to one relaunch with the fallback model, never the same model twice on the same error|pi-subagents: one model per launch, errors are returned (`PS/docs/models.md:18,106`)|
|Cross-family review|Review a child's output with a profile whose family differs from the author's; the block shows families|A reviewer from a different family on purpose (nkapila.me opencode config); Copilot's rubber-duck "complementary model strategy" (`docs/roadmap/copilot-port.md:214`)|
|Respect provider caps|Never run more children at once on a provider than its stated cap|Ollama Cloud concurrency was the real limit (nkapila.me; operator: Pro 3, Max 10)|
|Thinking where it pays|Thinking goes to the main thread and the judgment roles; cheap roles default to `medium` or lower|Orchestrator thinking gives the largest gains; sub-agent thinking gives little or negative benefit (arXiv 2601.11327)|

### Generated block, appended at session start

Built from the effective bindings, not from the plan alone, so it shows what will actually launch. Example for the plan above with the main thread on Sol:

```text
## Model plan on this machine (generated at session start; rebuilt on model switch)
Main thread: openai-codex/gpt-6.1-sol at xhigh. In the plan: yes. Judgment-grade: yes.
| Profile | Runs on | Thinking | Judgment-grade | Family | After a provider error, relaunch with model | After a failed check, relaunch with model |
|-|-|-|-|-|-|-|
| steward.coder | ollama-cloud/deepseek-v4.1-flash | high | no | deepseek | fireworks/accounts/fireworks/models/deepseek-v4p1-flash:high | openai-codex/gpt-6.1-sol:high |
| steward.researcher | ollama-cloud/deepseek-v4.1-flash | high | no | deepseek | fireworks/accounts/fireworks/models/deepseek-v4p1-flash:high | openai-codex/gpt-6.1-sol:high |
| steward.reviewer | amorphic/claude-sonnet-5-5 | high | no | claude | openai-codex/gpt-6.1-sol:medium | use steward.deep-reasoner |
| steward.deep-reasoner | openai-codex/gpt-6.1-sol (inherits the main thread) | xhigh | yes | gpt | amorphic/claude-opus-5-5:xhigh | keep it on the main thread |
| ... | | | | | | |
At most 3 children at a time on ollama-cloud.
```

With no plan file, the block still lists the effective bindings from settings and frontmatter, without the last two columns. Without a usable model registry (the extension fails open), there is no block, and the edict reads as it does today.

## Validation: `/steward-models` and the session-start check

Split of work, following the existing architecture where every decision is in `hooks/steward_hook.py` and the extension only translates (`pi/extensions/steward/index.ts:1-12`):

- **The extension gathers registry facts** and adds them to the `session-start` payload, which today carries only `session_id` (`index.ts:200-210`). The facts are: main model and thinking level; available models (`getAvailable()`), each with provider, id, supported thinking levels, `maxTokens` and `api`; and `project_trusted`. For supported levels it uses `getSupportedThinkingLevels` from `@earendil-works/pi-ai` (`.../pi-ai/dist/models.d.ts:262`) if the extension can import it; otherwise it reads `reasoning` and `thinkingLevelMap`, where `null` marks a level unsupported. The `check` command also sends `getAll()` with auth flags, so it can tell "not in the catalog" from "no credentials".
- **A new `hooks/model_plan.py`** does everything else, imported only for harness `pi`. It parses the plan, merges `"*"`, resolves candidates, and computes effective bindings from user and trusted-project settings using the documented precedence: per-run, then provider-scoped role override, then `agentOverrides`, then frontmatter, then `subagents.defaultModel`, then parent (`PS/docs/models.md:14`). The user layer comes first and the project layer second, each with its provider map merged in (`PS/src/agents/agents.js:1046-1056,1347-1359`). It also renders the block and builds the `apply` patch.
- **Session start stays offline and fast.** It reads files and the registry, with no network calls and no probes, inside the existing 15 s hook timeout (`index.ts:22`). At most one warning line per problem.

|Check|Severity|Source of truth|
|-|-|-|
|Plan parses; known roles; known fields; ids fully qualified; thinking values valid|error|Plan schema|
|Bound and fallback models exist in the registry|error, and the candidate is skipped|`modelRegistry.find` (`model-registry.d.ts:29`)|
|Provider has credentials|error, and the candidate is skipped|`hasConfiguredAuth` / `getAvailable` (`model-registry.d.ts:28,32`)|
|Thinking level supported by the bound model|warn: "clamped to X"; pi clamps silently (`PIDOCS/models.md:125`, `virtual-models.md:65`). A declared level is not proof the provider honors it (Ollama and `max`)|Supported levels|
|`maxTokens` below 32K on `coder` or `writer`|warn: Ollama's 16.4K cap truncates large edits|Registry|
|Router or `-latest` ids|warn: drift, and strict response verification may need `modelResponseAliases`|`PS/docs/configuration.md:51-65`|
|Role on a provider with `maxConcurrent` N while `parallel.concurrency` or `globalConcurrencyLimit` is above N|warn, naming the values to set in `~/.pi/agent/extensions/subagent/config.json`|`PS/docs/configuration.md:373-381,447-456`|
|A judgment role, or the main thread, outside `judgmentModels`|warn|Plan|
|Reviewer family equals coder family, or equals the main family when `byMainProvider` is used|warn|Family patterns|
|Effective binding differs from the plan, with the winning file named (for example this repo's `.pi/settings.json`)|warn: "run /steward-models apply" or "project override wins"|Settings files|
|`agentOverrides` keys for old profile names|warn: stale key, no longer applied|`PS/docs/agents.md:355`|
|Plan model outside an enforced `subagents.modelScope`|error for per-call relaunch models (they abort, `PS/docs/models.md:214`); warn for bindings|Settings|
|Role thinking above `subagents.maxThinking`|error: the launch fails before start (`PS/docs/models.md:138`)|Settings|
|Main model not in `main.models`; effective startup thinking differs from `main.thinking`|warn|`ctx.model`, settings|

`/steward-models` subcommands:

- **`check`** (the default) prints the block, every warning, and the source file of each binding. It is a dry run and writes nothing. It complements `/subagents-models`, which stays the authority on the live mapping (`PS/docs/models.md:167-176`). Phase verification compares the two.
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
      "steward.coder-opus-medium": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.researcher-sonnet-low": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.writer-sonnet-medium": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "high" },
      "steward.mechanic-haiku-medium": { "model": "ollama-cloud/deepseek-v4.1-flash", "thinking": "low" },
      "steward.reviewer-sonnet-high": { "model": "amorphic/claude-sonnet-5-5", "thinking": "high" },
      "steward.deep-reasoner-opus-xhigh": { "model": "inherit", "thinking": "xhigh" },
      "steward.reviewer-fable-xhigh": { "model": "amorphic/claude-fable-5-1", "thinking": "xhigh" }
    },
    "agentOverridesByProvider": {
      "amorphic": { "steward.reviewer-sonnet-high": { "model": "openai-codex/gpt-6.1-sol", "thinking": "medium" } }
    }
  }
}
```

Then `/reload` and `/subagents-models`. Limits: the edict still says "Each profile pins its model", the names still say opus, sonnet and haiku, and nothing tells the main thread what to relaunch with. In this repo, the committed `.pi/settings.json` overrides every `model` field above.

## Phases

Each phase ships on its own and keeps `npm test` green (`python3 -m unittest discover -s tests && node --test 'tests/pi/*.test.mjs'`, `package.json` scripts). Claude Code, Copilot and Codex files are not touched. The existing `ClaudeHarnessUnchangedTests` (`tests/test_pi_harness.py:200-226`) and the Copilot and Codex suites must stay green unmodified.

|Phase|Ships|Depends on|
|-|-|-|
|0|README "Profiles on pi" gains the Phase 0 recipe and the `.pi/settings.json` caveat; this document|Nothing|
|1|Role-only pi names with aliases (0.9.0)|Nothing|
|2|Plan file, per-repo override file with `allowProviders`/`denyProviders`, read-only `check`, generated block, guardrails in the edict|Nothing (role-to-runtime-name map covers both name sets)|
|3|`apply` and the `steward` pi-subagents profile file (so `/subagents-check-profile` can probe every model)|Phase 2|
|4|Per-launch outcome log (ships, decided 2026-10-09)|Phase 2|
|5|Deferred: in-child failover router|Phase 3 and a live probe|

**Phase 1: names.**
- Files:
  - Rename `pi/agents/*.md` to `coder.md`, `deep-reasoner.md`, `reviewer.md`, `researcher.md`, `writer.md`, `mechanic.md`, `top-reviewer.md`, with `name:` matching and `aliases: steward.<old-name>`. Descriptions that name other profiles move to the new names (for example `researcher-sonnet-low.md:4`, `reviewer-fable-xhigh.md:4`).
  - Edict rule 2, the routing table and the call examples.
  - The pi gate message (`hooks/steward_hook.py:857-867`).
  - README Pi sections (`README.md:113-150`).
  - Version bump in `package.json` and the plugin manifests (`tests/test_pi_harness.py:249` checks they match).
  - This repo's committed `.pi/settings.json`: move its seven keys from the old names to the role-only names, so it keeps overriding the user plan inside this repo.
- Tests:
  - `tests/test_pi_harness.py` gets a `PI_NAMES` map like `COPILOT_NAMES` (`tests/test_copilot_harness.py:29-37`). `test_same_profiles_as_claude` and `test_each_profile_mirrors_its_claude_twin` (`:263-279`) map through it. A new test asserts that each pi profile lists its old runtime name in `aliases`, and that no pi profile, the pi edict or the pi gate message contains `opus`, `sonnet`, `haiku` or `fable` in a profile name.
  - `test_skill_names_every_pi_profile` (`:293-298`) keeps working by file stem.
  - Update the name assertions at `tests/test_pi_harness.py:119` and `tests/pi/steward-extension.test.mjs:103,131,258,375`.
- Live check: `subagent({ action: "list" })` shows seven `steward.*` role names, and launching `steward.mechanic-haiku-medium` resolves to `steward.mechanic`.
- Operator follow-up: update the example at `~/AGENTS.md:21` and `~/.pi/agent/AGENTS.md:21`. These are operator files; the old name keeps resolving meanwhile.

**Phase 2: plan, check, block.**
- Files: `hooks/model_plan.py`, plus a pi branch in `cmd_session_start` (`hooks/steward_hook.py:275-305`) that appends the block when the payload has registry facts. The extension gets registry facts in `loadEdict`, a `model_select` handler that clears and reloads the edict, and a `/steward-models` command that runs a new `model-plan` hook subcommand. The edict gains the static guardrails. README documents the plan file.
- Python tests, new `tests/test_pi_model_plan.py`:
  - schema errors: bare id, unknown role, bad thinking value;
  - `"*"` merge;
  - first-available resolution, including a no-credentials candidate;
  - `main` rendered as inherit with the current main model;
  - clamp, `maxTokens`, router-id, concurrency, judgment-floor, family, stale-key, `modelScope` and `maxThinking` findings;
  - effective-binding precedence over fixture user and project settings, with and without `agentOverridesByProvider`, and with an untrusted project ignored;
  - no plan file and no registry facts gives byte-identical session-start output to today (regression);
  - rendered text has no em-dash and uses `|-|` separators;
  - project file: merges over the user plan field by field; ignored when the project is untrusted; `denyProviders` and a non-empty `allowProviders` make the check error on a bound model, fallback or escalation target, and make `apply` skip those candidates; a repo pinned to `amorphic` and `anthropic` never resolves a Flash binding; the winning file is named in the output.
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

**Phase 4: evidence (ships).** The existing `tool_result` handler (`index.ts:297-305`) appends one JSON line per accepted launch to `$XDG_STATE_HOME/steward/pi-delegations.jsonl`. Each line holds role, the model the result reports if present, `isError`, duration, and whether it was a relaunch or an escalation. `/steward-models stats` summarizes success rate per role and model. This is the worker success rate the Zorost rule needs: delegate while worker cost divided by success rate stays below orchestrator cost. Cost per completed task beats per-token price as a measure (Arize). Python tests on the summarizer, node test on the append.

**Phase 5 (deferred): in-child failover.** Entry criteria:
- a live probe shows a foreground child resolving a virtual model registered by a router-only file listed in a package agent's `subagentOnlyExtensions`;
- pi-subagents' response-model verification accepts it;
- Phase 4 data shows provider errors, not stalls, cause most failed launches.

## Alternatives considered

- **Register the profiles at runtime with resolved models** through pi-subagents' `pi-subagents:runtime-agent-register:v1` event (`PS/docs/extension-api.md:158-195`, since 0.58.0). This avoids writing settings and resolves availability per session. Rejected for now:
  - runtime names collide with the package's file agents (collision checks, `PS/CHANGELOG.md:1037`), so steward would have to stop shipping `pi/agents/` and depend entirely on a process-local event contract;
  - `agentOverrides` still win over the definition (`extension-api.md:193`), so drift remains possible anyway.
  - It stays the fallback design if settings writes prove troublesome.
- **Ship plans as pi-subagents profiles only.** A profile cannot carry the main model, fallbacks or escalations. It replaces the whole `agentOverrides` mapping and writes user scope only (`profiles.js:359-386`). Kept as a secondary output of `apply`.
- **A learned or per-request router** (oh-my-openagent fallback chains, opencode-subagent-router task-type routing). Rejected. The plan's static roles with ordered fallbacks already match oh-my-openagent's pipeline: override, then category default, then provider fallback, then system default. Primary agents respect the UI model and subagents follow their own chain. Router benchmarks show little gain over the best single model (Arize).

## Risks

|Risk|Failure scenario|Mitigation|
|-|-|-|
|Precedence replica drifts from pi-subagents|pi-subagents changes layering in a release (it ships every few days, `README.md:109`); the block shows Sonnet while Flash launches|Live check against `/subagents-models` in every phase; the README names the tested pi-subagents version|
|Cheap executor is worse than it looks|Flash passes its own check but the reviewer keeps finding defects; cost per completed task rises above Sonnet's|Escalation rule; Phase 4 data; blackbox.ai showed the executor choice matters (Opus with GLM-5.2: 69.7 on Terminal-Bench 2.0 against 58.4 solo; with Kimi K2.7: no gain)|
|Main thread mis-copies the relaunch model|Typo, so a second failed launch|Exact strings in the block. Copilot's pass-the-model approach worked live (`docs/roadmap/copilot-port.md:27`)|
|Ollama stalls are not errors|A 30-40 s first-token stall per request (seen on minimax-m3) makes Ollama launches slow without failing; Ollama is now the primary Flash provider|Phase 4 outcome log shows duration per role and model; Fireworks fallback; the stall stays an open item|
|Concurrency caps are global, not per provider|A 4-task parallel run on Ollama Pro gets HTTP 429s|Check warning with concrete `config.json` values; the edict cap line|
|Settings write race|Pi saves `defaultModel` (Ctrl+S) while `apply` writes|Explicit command only; re-read and refuse on change; backup|
|Rename orphans overrides|Existing `steward.coder-opus-medium` overrides silently stop applying after 0.9.0|Stale-key check at session start; `apply` migrates; release note|
|Thinking is declared, not honored|Plan says `max` on Ollama, the provider ignores it, and the check passes|The check states that declared levels are not verified; prefer providers that honor them|
|Code leaves for third-party providers|A confidential repo's code is sent to Fireworks or Ollama Cloud|Per-repo `.pi/steward-model-plan.json` with `allowProviders`/`denyProviders`, enforced by the check (v1 requirement)|
|`inherit` follows a downgraded main|The operator switches main to Flash mid-session, so deep-reasoner inherits Flash|`model_select` rebuild plus the judgment-floor warning|

Could not confirm:
- whether workflow `runs.run(...)` accepts a per-child `model` (the docs show none, `PS/docs/workflows.md:95-142`);
- whether the steward extension can import `@earendil-works/pi-ai`;
- whether `tool_result` for `subagent` reports the resolved model;
- that `modelThinkingLevels` outranks `defaultThinkingLevel`;
- which levels pi's catalog declares for the Fireworks Flash entry (the Ollama entry declares no `xhigh` or `max`; tested 2026-10-09).

## Operator decisions, 2026-10-09

1. **Main thread default: steward sets none.** The main thread runs on whatever model and thinking level pi on the client machine picks (`defaultModel`, `defaultThinkingLevel`, `modelThinkingLevels`, `/model`). The plan's `main.models` list is only what the check compares against. The earlier claim that pi caps `amorphic/claude-opus-5-5` at `high` was wrong: a stale `modelThinkingLevels` entry (`high`) in `~/.pi/agent/settings.json` caused it, not an amorphic or pi limit. It was set to `xhigh` on 2026-10-09, and a plain `pi -p` run then recorded thinkingLevel `xhigh`.
2. **Most roles on DeepSeek V4.1 Flash, not all.** Coder, researcher, writer and mechanic on Flash. Deep-reasoner on the main thread's model (`"model": "main"`). Reviewer on a different family from the main thread. Top-reviewer on Fable. The "all on Flash" variant stays documented as allowed with warnings but is not the operator's choice.
3. **Flash provider order: Ollama Cloud first, Fireworks as fallback.** Ids: `ollama-cloud/deepseek-v4.1-flash`, then `fireworks/accounts/fireworks/models/deepseek-v4p1-flash`. Ids differ per provider, so fallbacks are written per provider. The `providers` block carries Ollama's cap of 3 concurrent requests on Pro. Trade-offs are in the plan file section.
4. **Thinking on Flash:** coder `high`, researcher `high`, writer `high`, mechanic `low`; never `off`. Evidence in the next section.
5. **Rename the pi profiles to role-only names in 0.9.0**, with the old names kept as pi-subagents aliases.
6. **`apply` also writes a pi-subagents profile file** so `/subagents-check-profile` can probe every model. The per-launch outcome log ships (Phase 4).
7. **A per-repo override is required in v1.** A repo can pin profiles away from third-party providers (for example everything on Anthropic or OpenAI). Shape: `.pi/steward-model-plan.json`, project wins over user, `allowProviders`/`denyProviders` enforced by the check (Scope section; tests in Phase 2).
8. **Steward's own `.pi/settings.json` is committed.** It pins every `steward.*` profile to `amorphic/claude-*` for work inside this repo. Its keys must move to the role-only names in 0.9.0, and it overrides the user plan inside this repo.

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

Open item: if the Fireworks fallback gets a `models.json` `thinkingLevelMap` with `max`, a failed coder check could escalate to Flash at max on Fireworks before escalating to the main model.

## Evidence base

- **Local, read 2026-10-09:**
  - steward `a2ab9eb`: files cited above;
  - `~/.pi/agent/settings.json` (`defaultProvider: amorphic`, `defaultModel: claude-opus-5-5`, `defaultThinkingLevel: xhigh`, `modelThinkingLevels`);
  - `~/.pi/agent/models.json` (providers `anthropic`, `ollama-cloud`, `amorphic`, `fireworks`);
  - `~/.pi/agent/auth.json` (provider names only: `anthropic`, `openai-codex`, `openai`);
  - `pi --list-models` on pi 1.1.0; pi docs and type declarations under `PIDOCS` and `PIDIST`;
  - pi-subagents 0.76.1 docs and source under `PS`.
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
