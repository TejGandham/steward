# Proposal: split steward into four plugins

Status: design only, recorded 2026-10-24 against main at c5fd21b (steward 0.14.2). Nothing is built. This document supersedes [orchestration-split.md](orchestration-split.md). It is self-contained: the decision log and the harness facts it rests on are in the two appendices, so work can resume from this file alone.

Marks used below:
- **(operator decided)**: the operator stated it. Do not change it without asking.
- **(orchestrator's call)**: chosen by the session that wrote this design. The operator has not confirmed it; each one is listed again in [Decided versus left to the builder](#decided-versus-left-to-the-builder).

Line numbers point into the tree at c5fd21b. Re-check them before editing.

## Summary

Steward 0.14.2 is one plugin that does four jobs for four harnesses from one 1,638-line hook script (`hooks/steward_hook.py`). The split cuts it into four plugins that each do one thing:

| Plugin | One job | Lives in |
|-|-|-|
| `plainlanguage` | The writing skill | `/mnt/agent-storage/vader/src/common-skills/plainlanguage/` (unchanged home) |
| `steward-prose-gate` | Block AI-tell prose in replies and PR bodies | `plugins/steward-prose-gate/` in this repo |
| `steward-delegation` | Make the main session hand work to pinned subagents | `plugins/steward-delegation/` |
| `steward-orchestration` | Primary and secondary session roles (Claude Code only) | `plugins/steward-orchestration/` |

Four facts keep the reorg simple:
1. **Tag, then pin.** Tag `v0.14.2` at c5fd21b and point the root catalog entry for `steward` at that tag. From then on nothing at the repo root is what `steward@steward` installs, so the tree is free to move.
2. **Paths are depth-relative.** Every resolver climbs a fixed number of directories from its own file: `get_plugin_root` two up (`hooks/steward_hook.py:82-88`), the pi `PLUGIN_ROOT` three up (`pi/extensions/steward/index.ts:41`), the Codex adapter two up (`codex/steward.py:10`), every test's `REPO_ROOT` two up (for example `tests/test_steward_hook.py:27`). Each plugin folder copies today's layout, so those resolvers need no new logic.
3. **Copy, cut over, delete.** Each plugin is built beside the monolith with its own script and tests, then its hook entries take over, then the monolith code and its tests are deleted. The suite stays green at every step.
4. **Dependencies stay manual (operator decided).** No harness dependency field is used. Install docs list which plugins go together. At runtime a plugin only adds a short note for the model.

## Why

Steward grew into a monolith. One script holds the delegation gate, the prose gate, the PR gate, the orchestration registry, the pi model plan and four harness adapters (`hooks/steward_hook.py:32-39` picks the harness; Copilot and pi branches run through the whole file). The cost shows in four places:
- **Switches leak.** `STEWARD_GATE=off` also turns off the PR gate, because `pr_gate_violation` runs inside `cmd_gate` after the `off` return (`hooks/steward_hook.py:1171-1172`, `1184-1197`).
- **You cannot take one part.** A user who wants only the prose gate gets the delegation edict, seven agents and the registry file too. Codex already runs the prose and PR gates without the delegation gate (`codex/steward.py:32-46`), which shows the gates stand alone.
- **Personal text ships to everyone.** The operator's "sauron" edict (`skills/orchestrating/SKILL.md:21`, `onboarding-template.md:15`) and the zero-em-dash rule (`skills/delegating/SKILL.md:12`) are in a plugin others can install.
- **One version for unrelated changes.** Model-plan work on pi and an orchestration wording fix bump the same number in four manifests.

The split follows the unix philosophy **(operator decided)**: small units, each does one thing, and they combine.

## Goals

- Four plugins with one job each, combinable in any order the dependency table allows.
- Each plugin folder is self-contained and releasable on its own: its own manifests per harness, hooks, skills or agents, tests, version and README. Nothing under one plugin imports or reads a file from another.
- Existing 0.14.2 users keep working with no action (Claude Code, Copilot and Codex marketplace installs) or one documented action (pi, direct Copilot installs).
- Each plugin has its own config directory and its own on/off switch.

## Non-goals

- Building the Engen-Tech/plugins marketplace (see `/mnt/agent-storage/vader/src/hatch/docs/backlog/engen-tech-plugin-marketplace/FINDINGS.md`). This design only leaves each plugin ready for its release script to copy. Its steward facts are stale; see [Appendix B](#appendix-b-harness-facts).
- Backward compatibility for the new plugins **(operator decided)**: names, plugin ids, env vars and config paths all change.
- Behavior changes beyond what the split forces. The open items in orchestration-split.md (memory rule, session identity, stale registry rows) stay open; see [steward-orchestration](#steward-orchestration).
- Orchestration on pi, Copilot or Codex. It stays Claude Code only **(operator decided)**.
- A generator for the four profile copies or the four edict forks.

## Anti-goals

- No shared library, no `plugins/common/`, no import or `sys.path` reach across plugin folders. Small helpers are copied **(orchestrator's call, from the decision log)**.
- No harness dependency fields, no auto-install chains **(operator decided)**.
- No migration code that reads old config paths. The README says what to move.
- No user override layer for the AI-tell word list **(operator decided)**.
- No machinery kept "for later": if a step does not serve a goal above, cut it.

## The four plugins

### What each plugin ships per harness

| | Claude Code | Copilot CLI | Codex CLI | pi |
|-|-|-|-|-|
| `plainlanguage` | skill | skill | skill | skill (pi already finds `~/.agents/skills/plainlanguage/`) |
| `steward-prose-gate` | Stop prose gate; PreToolUse `^Bash$` PR gate | SessionStart (records the main session only); PreToolUse `Bash` PR gate; Stop prose gate | PreToolUse `^Bash$` PR gate; Stop prose gate | extension: `tool_call` on `bash` (PR gate), `agent_before_settle` (prose gate) |
| `steward-delegation` | SessionStart edict; 7 agents; `delegating` skill with `routing.md`; delegation gate; `delegated` counter reset | SessionStart edict and bound-profile note; 7 agents; Copilot edict skill; delegation gate; `delegated` reset | SessionStart edict; Codex edict skill with `profiles.json`; `install_agents.py`. **No delegation gate** | extension: edict, model plan block, `/steward-models` (check, apply, stats), launch log, delegation gate; 7 agents; `steward-delegating` skill |
| `steward-orchestration` | `orchestrating` skill and onboarding template; SessionStart (creates registry, adds role check) | not shipped | not shipped | not shipped |

Codex keeps no delegation gate because Codex children share the parent's `session_id`, so a per-session edit counter would count child edits against the parent (`codex/steward.py:33-34`) **(operator decided, as today)**.

### plainlanguage

Job: the writing skill (`SKILL.md`, `de-llm.md`, `ste100.md`). No hooks. Needs nothing. Source stays canonical in common-skills, per the "Deploying skills from common-skills" rule in `~/AGENTS.md` **(orchestrator's call, from the decision log)**. The work there is short:
- Add `plainlanguage/.claude-plugin/plugin.json`, `.codex-plugin/plugin.json` and `.github/plugin/plugin.json`, shaped like `common-skills/exa-rest/.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`.
- Choose the folder shape there. A plugin's skills sit under `skills/<name>/`, while the deploy rule copies `plainlanguage/` whole to `~/.claude/skills/plainlanguage/` and `~/.agents/skills/plainlanguage/`. Either move the three files to `plainlanguage/skills/plainlanguage/` and update the deploy path, or point the manifest `skills` field at the folder itself if the harness accepts that. `SKILL.md` names `de-llm.md` and `ste100.md` as siblings, so the three files stay together.
- Add the entry to common-skills' `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` (marketplace `stackhouse-common`).
- No pi package: pi already reads `~/.agents/skills/`.

This is work for the common-skills repo, not for this one.

### steward-prose-gate

Job: block a reply or a `gh pr create|edit` body that has two or more distinct AI tells or any operator pattern. One plugin holds both gates because they share the word list, `_clean_text`, and the operator patterns loader (roundtable result, [Appendix A](#appendix-a-decision-log)). Needs nothing: its block messages name the plainlanguage skill as the way to revise, but work without it.

Contents:
```
plugins/steward-prose-gate/
  .claude-plugin/plugin.json      .codex-plugin/plugin.json      .github/plugin/plugin.json
  package.json                    (pi: extensions ./pi/extensions/steward-prose-gate/index.ts)
  README.md
  data/ai-tells.txt               (the word list; see "Word list")
  hooks/hooks.json                (Claude Code)
  hooks/prose_gate_hook.py
  copilot/hooks.json
  codex/hooks.json
  pi/extensions/steward-prose-gate/index.ts
  tests/                          (Python) and tests/pi/*.test.mjs
```

Behavior kept from today:
- Subagent calls are not gated: on Claude Code the hook returns early on a payload `agent_id` (`hooks/steward_hook.py:1161-1162`, `1504-1505`); on Copilot only a recorded main session is gated (`:1167-1168`, `1509-1510`); on pi the extension registers nothing in a pi-subagents child (`index.ts:519`). Codex cannot tell a child from the parent, so its PR gate runs everywhere, as today (`codex/steward.py:32-46`).
- One revision per reply: `stop_hook_active` skips the check (`:1502-1503`); pi passes it from `isProseRevision` (`index.ts:186-197`, `1136-1140`).
- Codex reads only `last_assistant_message`, never a transcript (`codex/steward.py:51-56`).

New:
- Its own switch: `<config>/steward-prose-gate/gate` holding `on` or `off`, read on every call; when the file is absent, env `STEWARD_PROSE_GATE` (`on`|`off`); default `on`. One switch covers both gates. A Stop hook has no soft form, so there is no `soft` value **(orchestrator's call)**.
- On Copilot it needs its own SessionStart hook that records the main session under its own state dir. Today the delegation side records it (`hooks/steward_hook.py:242-248`) and both gates read it (`:1167`, `:1509`); without its own record the prose and PR gates would fail open for every Copilot session **(orchestrator's call)**.
- No built-in em-dash rule. See [Personal content](#personal-content) **(orchestrator's call)**.

### steward-delegation

Job: the delegation edict, injected at session start; the routing table; the seven pinned profiles; the delegation gate and its `delegated` counter reset; on pi, the model plan, `/steward-models`, the launch log and delegation stats **(operator decided)**. Needs plainlanguage (soft) and, on pi, pi-subagents (as today).

Contents (same relative paths as today, moved under the plugin folder):
```
plugins/steward-delegation/
  .claude-plugin/plugin.json      .codex-plugin/plugin.json      .github/plugin/plugin.json
  package.json                    (pi: extension, skills, subagents.agents)
  README.md
  agents/*.md                     (7, Claude Code)
  skills/delegating/SKILL.md, routing.md
  hooks/hooks.json                (Claude Code)
  hooks/delegation_hook.py
  hooks/model_plan.py, model_plan_render.py, model_plan_apply.py, delegation_stats.py   (about 3,850 lines, pi only)
  copilot/agents/*.agent.md, copilot/skills/delegating/SKILL.md, copilot/hooks.json
  codex/skills/delegating/SKILL.md, codex/skills/delegating/profiles.json, codex/install_agents.py, codex/hooks.json
  pi/agents/*.md, pi/skills/steward-delegating/SKILL.md, pi/extensions/steward-delegation/index.ts
  tests/                          (Python) and tests/pi/*.test.mjs, profile_check.mjs, resolve_model.mjs
```

Changes the split forces:
- No PR gate inside `gate` (move `hooks/steward_hook.py:1184-1197` out).
- No registry creation (drop `_ensure_registry` and its call, `:140-147`, `:449-454`).
- No "Role check" section in the Claude edict (`skills/delegating/SKILL.md:41-42` moves to steward-orchestration).
- The plainlanguage file probe goes (see [Dependencies](#dependencies-manual-on-every-harness)).

### steward-orchestration

Job: primary and secondary session roles for multi-session initiatives, Claude Code only **(operator decided)**. Needs steward-delegation: the orchestrating skill applies the delegating skill's "Everyone" rules (`skills/orchestrating/SKILL.md:9`, `23`).

Contents:
```
plugins/steward-orchestration/
  .claude-plugin/plugin.json
  README.md
  skills/orchestrating/SKILL.md, onboarding-template.md
  hooks/hooks.json                (SessionStart, matcher startup|resume|clear|compact|fork)
  hooks/orchestration_hook.py
  tests/
```

Its SessionStart hook does two things **(operator decided: it creates the registry; orchestrator's call: it also carries the role check)**:
1. Creates `~/.claude/orchestration/initiatives.md` from the skeleton if missing, best effort (today `hooks/steward_hook.py:111-124`, `140-147`).
2. Adds a short context block: the Role check paragraph moved from `skills/delegating/SKILL.md:42`, and one sentence: "This plugin relies on steward-delegation. If the `steward-delegation:delegating` skill is not in your skill list, tell the operator once."

The registry stays where it is, `~/.claude/orchestration/` with override `STEWARD_ORCHESTRATION_DIR` (`:73-79`). It is deliberately under `~/.claude`, not `$CLAUDE_CONFIG_DIR`, so sessions in different config profiles share one registry, and the env var already carries the plugin's name **(orchestrator's call)**.

Carried from orchestration-split.md, not part of the split, follow-ups for later: the memory rule (`skills/orchestrating/SKILL.md:15`, `26`; `skills/delegating/SKILL.md:15`) conflicts with the operator's no-memory rule; roles match on session name, which drifts; nothing closes a finished initiative's row.

## Dependencies: manual on every harness

**(operator decided)**: no plugin declares a dependency in any manifest, including Claude Code's `dependencies` field, which exists ([Appendix B](#appendix-b-harness-facts)). Install docs list the sets. A plugin never fails because another is missing.

| Plugin | Relies on | When it is missing |
|-|-|-|
| `plainlanguage` | nothing | n/a |
| `steward-prose-gate` | nothing | n/a. Block messages still say to revise with the plainlanguage skill; the model can revise without it |
| `steward-delegation` | `plainlanguage` (soft); pi-subagents on pi | The edict's rule 4 says: use the plainlanguage skill; if it is not in your skill list, tell the operator once and apply the rules in this rule directly (the Codex edict already does this, `codex/skills/delegating/SKILL.md:40`). On pi the pi-subagents warning stays as is (`index.ts:271-275`, `569`) |
| `steward-orchestration` | `steward-delegation` | The sentence in its session-start block (above) |

The missing-dependency note is text the model acts on, not a file probe **(orchestrator's call)**. Today's probe (`hooks/steward_hook.py:150-181`) checks only skill folders, so it cannot see a plugin-installed plainlanguage and would warn wrongly every session; the model already sees its own skill list on every harness. `_dependency_warnings` and `_pi_dependency_warnings` are dropped. steward-delegation owns the plainlanguage note; steward-prose-gate emits none.

Install sets for the READMEs:
- Prose rules only: `plainlanguage` + `steward-prose-gate`.
- Delegation: `plainlanguage` + `steward-delegation`, plus `steward-prose-gate` to enforce the prose half of the edict.
- Orchestration (Claude Code): all four.

## Repo layout after the reorg

```
.claude-plugin/marketplace.json   catalog "steward": steward pinned to v0.14.2, plus the three new plugins
.agents/plugins/marketplace.json  catalog "steward-codex": steward pinned to v0.14.2, plus steward-delegation, steward-prose-gate
package.json                      private; pi entry for git installs; scripts.test runs every suite
.pi/settings.json                 dev-only profile overrides for this checkout (unchanged)
.gitignore
README.md                         index: the four plugins, install sets, staying on 0.14.2
docs/                             unchanged; this file added
tests/                            repo-level tests only (catalogs, layout, docs)
plugins/steward-delegation/
plugins/steward-prose-gate/
plugins/steward-orchestration/
```

Deleted from the root: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.github/plugin/plugin.json`, `agents/`, `skills/`, `hooks/`, `copilot/`, `codex/`, `pi/`. Everything under them either moves into a plugin folder or is retired (see [Hook split](#hook-split)).

Catalog entries on main **(orchestrator's call: one catalog per harness keeps the frozen monolith and the new plugins; marketplace names `steward` and `steward-codex` are unchanged)**:

```json
{"name": "steward", "source": {"source": "github", "repo": "tejgandham/steward", "ref": "v0.14.2"}}
{"name": "steward-delegation", "source": "./plugins/steward-delegation"}
```

Codex (`.agents/plugins/marketplace.json`):
```json
{"name": "steward", "source": {"source": "url", "url": "https://github.com/tejgandham/steward.git", "ref": "v0.14.2"}}
{"name": "steward-delegation", "source": {"source": "local", "path": "./plugins/steward-delegation"}}
```

The Codex docs show `ref` on a `git-subdir` source; if Codex rejects `ref` on `url`, use `{"source": "git-subdir", "url": "...", "path": "./", "ref": "v0.14.2"}`. Keep each entry's `policy` and `category` as today. Copilot reads `.claude-plugin/marketplace.json`, so it sees `steward-orchestration` too; its README says Claude Code only. The later Engen-Tech release script lifts these entries and rewrites `source` (FINDINGS.md "Release flow", step 3).

### Versions and tags

- Each new plugin starts at **0.15.0** and moves on its own after that **(orchestrator's call)**. It reads as newer than 0.14.2 in any listing, says "the next steward release, split", and does not claim the stability a 1.0.0 would while orchestration has open problems.
- All of one plugin's manifests carry the same version: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.github/plugin/plugin.json`, `package.json` (whichever exist). A test enforces it, including Codex, which no test checks today.
- Release tags are `<plugin>--v<version>`, for example `steward-delegation--v0.15.0` **(orchestrator's call)**. This is Claude Code's documented form for one repo holding several plugins ([Appendix B](#appendix-b-harness-facts)) and cannot collide with the existing `v*` tags.
- The root `package.json` is not a plugin. Its `version` stays `0.15.0` and is not a release number; no test ties it to a plugin.

## Existing users: tag and pin

**(operator decided)**: 0.14.2 is the last monolith release, and existing installs stay on it.

| Install | What happens | Action |
|-|-|-|
| Claude Code `steward@steward` | The catalog entry resolves the tag. Version stays 0.14.2, so nothing updates | none |
| Copilot `steward@steward` (marketplace) | Same catalog file, same pin | none |
| Copilot direct `copilot plugin install TejGandham/steward` | Tracks the repo root, which loses its manifests | reinstall from the marketplace (`steward@steward`) to stay on 0.14.2, or install the new plugins by subfolder (`copilot plugin install TejGandham/steward:plugins/steward-delegation`) |
| Codex `steward@steward-codex` | Pinned entry; hook trust keys `steward@steward-codex:codex/hooks.json:*` still match the tag's tree | none |
| pi `git:github.com/tejgandham/steward` (unpinned) | `pi update` moves to main and loads the new delegation and prose-gate extensions | pin before the merge: `pi install git:github.com/tejgandham/steward@v0.14.2`, or accept the new layout and move config |

The README notice about pinning goes onto main before the reorg merges (build step 1).

## Pi packaging

Constraint: pi installs one package per git URL and cannot install a subfolder of a repo; git identity is the URL without the ref; filters narrow what one package exposes ([Appendix B](#appendix-b-harness-facts)).

Scheme **(orchestrator's call)**:
- Each plugin folder has its own `package.json` with a `pi` field. That keeps the folder self-contained, and a local path install (`pi install /path/to/steward/plugins/steward-delegation`) works for development and for anyone who clones.
- The root `package.json` on main is the git-install entry. It exposes both pi plugins:
  ```json
  "pi": {
    "extensions": ["./plugins/steward-delegation/pi/extensions/steward-delegation/index.ts",
                   "./plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"],
    "skills": ["./plugins/steward-delegation/pi/skills"],
    "subagents": {"agents": ["./plugins/steward-delegation/pi/agents"]}
  }
  ```
  `pi install git:github.com/tejgandham/steward` therefore gives pi users what 0.14.2 gave them: edict, gates, profiles, model plan.
- Selective install uses the settings object form, documented in the README:
  ```json
  {"source": "git:github.com/tejgandham/steward",
   "extensions": ["-plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"]}
  ```
  drops the prose gate; `"extensions": ["plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"], "skills": []` keeps only the prose gate. The seven `steward.*` agents are declared under pi-subagents' own `subagents.agents` key, which pi's filters do not cover, so they may still be listed; that is harmless.
- Do not install the root package and a plugin folder at the same time; both would load.
- Rejected: npm packages (a publish step and an account for no gain today); one repo per plugin (the operator decided on one repo); a stub extension that only says "moved" (machinery).

Pinned users (`@v0.14.2`) never move: "Git tags and commits are also pinned; package updates reconcile the checkout but do not move a configured ref" (`earendil-pi packages/coding-agent/docs/packages.md:40`). An unpinned user on `pi update` gets the split layout; their old files under `~/.pi/agent/steward/` (gate, model-plan.json, the prose-patterns link) are no longer read, and the launch log starts a new file. No code migrates them **(orchestrator's call)**.

Names that stay on pi **(orchestrator's call)**: profiles `steward.<role>` (they come from `package: steward` in `pi/agents/*.md` frontmatter, not from the package name), the skill `steward-delegating`, the command `/steward-models`, the repo plan `.pi/steward-model-plan.json`, the pi-subagents profile `profiles/pi-subagents/steward.json` (`hooks/model_plan_apply.py:88`). Renaming them would churn the model-plan code and the operator's `agentOverrides` keys for no gain. The same holds for Codex named agents `steward-<role>`.

## Hook split

**(orchestrator's call, from the decision log)**: one hook script per plugin; `hooks/steward_hook.py` and `codex/steward.py` are retired; small helpers are copied; no cross-plugin import.

**(orchestrator's call)**: the harness is the first argument, `<script> <harness> <mode>` with harness `claude|copilot|codex|pi`. Each hooks.json already belongs to one harness, so it names it. This removes `STEWARD_HARNESS`, removes the POSIX `VAR=value` prefix from the Copilot commands (README:330), and leaves no env var to rename. An unknown harness or mode exits 0 with no output (fail open).

### Hook entries

| Plugin | Harness | Event and matcher | Command (after `python3 "${...ROOT}/hooks/`) | Timeout |
|-|-|-|-|-|
| delegation | Claude | SessionStart `startup\|resume\|clear\|compact\|fork` | `delegation_hook.py" claude session-start` | 15 |
| delegation | Claude | PreToolUse `^(Edit\|Write\|MultiEdit\|NotebookEdit\|Bash)$` | `... claude gate` | 10 |
| delegation | Claude | PreToolUse and PostToolUse `^(Task\|Agent)$` | `... claude delegated` | 10 |
| delegation | Copilot | SessionStart; PreToolUse `Edit\|Write\|Bash`; Pre and PostToolUse `Agent` | `... copilot session-start\|gate\|delegated` | 15/10/10 |
| delegation | Codex | SessionStart | `... codex session-start` | 15 |
| delegation | pi | extension spawns | `... pi session-start\|gate\|delegated\|model-plan\|model-plan-apply\|delegation-stats` | as today |
| prose-gate | Claude | PreToolUse `^Bash$`; Stop | `prose_gate_hook.py" claude pr-gate\|prose-gate` | 10/15 |
| prose-gate | Copilot | SessionStart; PreToolUse `Bash`; Stop | `... copilot session-start\|pr-gate\|prose-gate` | 10/10/15 |
| prose-gate | Codex | PreToolUse `^Bash$`; Stop | `... codex pr-gate\|prose-gate` | 10/15 |
| prose-gate | pi | extension spawns | `... pi pr-gate\|prose-gate` | as today |
| orchestration | Claude | SessionStart `startup\|resume\|clear\|compact\|fork` | `orchestration_hook.py" claude session-start` | 10 |

Claude Code commands use `${CLAUDE_PLUGIN_ROOT}`; Copilot and Codex use `${PLUGIN_ROOT}`, as today (`hooks/hooks.json`, `copilot/hooks.json`, `codex/hooks.json`). The pi extensions spawn `process.env.STEWARD_DELEGATION_PYTHON || "python3"` and `STEWARD_PROSE_GATE_PYTHON` (today `STEWARD_PYTHON`, `index.ts:116`).

### Map of `hooks/steward_hook.py`

`D` = `delegation_hook.py`, `P` = `prose_gate_hook.py`, `O` = `orchestration_hook.py`. "Copy" means each listed script keeps its own copy.

| Lines | Code | Goes to |
|-|-|-|
| 29 | `EM_DASH` | dropped (see Personal content) |
| 32-39 | `get_harness` | dropped; harness is `argv[1]` in D, P, O |
| 42-61 | `get_config_dir` | copy in D (claude, copilot, pi) and P (claude, copilot, pi, plus codex: `$CODEX_HOME` or `~/.codex`, from `codex/steward.py:19-21`) |
| 64-70 | `get_state_dir` | copy in D (`steward-delegation`) and P (`steward-prose-gate`) |
| 73-79 | `get_orchestration_dir` | O |
| 82-88 | `get_plugin_root` | D (env override `STEWARD_DELEGATION_ROOT`, tests only) |
| 91-104 | `_expand_user`, `_non_empty_str` | copy in D and P; `_non_empty_str` also O |
| 111-124 | `REGISTRY_SKELETON` | O (namespace `steward-orchestration:orchestrating`) |
| 127-137 | `strip_frontmatter` | D |
| 140-147 | `_ensure_registry` | O |
| 150-181 | `_dependency_warnings`, `_pi_dependency_warnings` | dropped |
| 184-208 | `_copilot_bound_profiles_note` | D (key prefix `steward-delegation:`, line 197) |
| 211-229 | Copilot main-session record and check | copy in D and P, each under its own state dir |
| 232-239 | `_COPILOT_FALLBACK_EDICT` | D (new `agent_type` prefix, no em-dash clause) |
| 242-272 | `_copilot_session_start` | D; P gets a Copilot `session-start` that only records the main session and prints nothing |
| 275-397 | model-plan contract, `_hook_module`, `_pi_model_plan_block`, `cmd_model_plan`, `cmd_model_plan_apply` | D |
| 400-464 | `cmd_session_start` | D, minus the registry call and warnings; gains the Codex branch from `codex/steward.py:27-30` |
| 467-468 | `block_launches_ok` | D |
| 471-673 | Bash write classification, `BASH_WRITE_RULES` | D |
| 676-779 | allowlist | D (config file `steward-delegation/allowlist`; Copilot glob `steward/**` at line 702 becomes `steward-*/**`) |
| 782-947 | tool classification, session id, atomic counter | D; `_sanitize_session_id` (863-865) also copied to P for the Copilot record |
| 950-977 | gate mode | D (file `steward-delegation/gate`, env `STEWARD_DELEGATION_GATE`); P gets its own `on`/`off` reader |
| 980-1012 | `gate_message` | D (new names, new path and env) |
| 1019-1030 | `MARKERS` | `data/ai-tells.txt` in P's plugin |
| 1033-1041 | `_compile_marker`, `_MARKER_PATTERNS` | P, compiled from the data file at load |
| 1044-1089 | operator patterns, `find_operator_hits`, `find_markers` | P (file `steward-prose-gate/prose-patterns`) |
| 1092-1153 | PR gate (`_GH_PR_CREATE_EDIT_RE`, messages, `pr_gate_violation`) | P, em-dash branch and `PR_EMDASH_MSG` removed |
| 1160-1231 | `cmd_gate` | D without lines 1184-1197; P gets `cmd_pr_gate` = the `agent_id` skip (1161-1162), the Copilot main check (1167-1168), its switch, and lines 1184-1197 |
| 1238-1246 | `cmd_delegated` | D |
| 1253-1278 | `_clean_text` and its regexes | P |
| 1281-1361 | transcript tail, `_extract_last_assistant_text` | P |
| 1366-1491 | Copilot `events.jsonl` reader | P |
| 1494-1549 | `PROSE_OPERATOR_MSG_TEMPLATE`, `cmd_prose_gate` | P, em-dash count removed; Codex branch from `codex/steward.py:48-65` |
| 1556-1576 | `_dispatch` | one per script |
| 1579-1605 | `cmd_delegation_stats` | D |
| 1608-1634 | `main` | one per script; D keeps the three CLI modes with exit codes 2 and 3 |

`codex/steward.py` (87 lines) is retired: its `session-start` goes to D, its `gate` and `prose-gate` to P. Rough sizes: D about 1,000 lines plus the model-plan modules, P about 500, O about 60. Copied helpers are about 30 lines per script.

### Pi extensions

- `plugins/steward-delegation/pi/extensions/steward-delegation/index.ts` is today's `pi/extensions/steward/index.ts` (1,332 lines) minus the prose gate handler (`:1127-1153`), `isProseRevision`, `lastAssistantText` and the PR-gate comment path in `tool_call` (`:1081-1086` stays: it downgrades only the delegation gate). `HOOK_SCRIPT` (`:42`) becomes `hooks/delegation_hook.py`, called with `pi` as the first argument. The launch log moves from `resolve(state, "steward", ...)` (`:300`) to `steward-delegation`.
- `plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts` is new and small: a copy of `runHook` (`:96-150`) without the debug log, `lastAssistantText` (`:169-184`), `isProseRevision` (`:186-197`), the child check (`:519`), a `tool_call` handler for `bash` that blocks on a `pr-gate` deny, and today's `agent_before_settle` handler (`:1127-1153`). It notifies once when python3 is missing.

### Behavior changes the split causes

- A `gh pr create` that the PR gate denies now also counts as one direct edit for the delegation gate, because the two PreToolUse hooks run independently (today the PR gate returns before the counter, `:1184-1199`). Accepted; the alternative couples the plugins **(orchestrator's call)**.
- `STEWARD_DELEGATION_GATE=off` no longer turns off the PR gate.
- The plainlanguage warning is text in the edict, not a hook warning.
- Sessions without steward-orchestration no longer create the registry or carry the role check.
- Two python processes per Bash call where both plugins are installed (one per plugin).

## Word list

**(operator decided)**: `MARKERS` (`hooks/steward_hook.py:1019-1030`) leaves the code for a data file inside steward-prose-gate. No skill reads it (`de-llm.md` is a separate catalog the gate never reads), so it lives with the code that reads it. Changes ship as a steward-prose-gate release. There is no per-user add or remove layer.

File: `plugins/steward-prose-gate/data/ai-tells.txt`, UTF-8. Format **(orchestrator's call)**:
- One marker per line, a literal word or phrase, not a regex.
- Lines starting with `#` and blank lines are skipped; surrounding whitespace is trimmed.
- Matching is unchanged from `_compile_marker` (`:1033-1038`): case-insensitive, `\b` before, and `\b` after when the last character is a word character.
- The gate blocks on two or more distinct markers, as today (`:1150`, `:1536`).
- A missing or unreadable file means no markers (fail open). A test asserts the shipped file parses to exactly the 30 entries of today's list.

Initial content, copied from `:1019-1030`:
```
delve
delves
delving
leverage
leverages
leveraging
crucial
pivotal
tapestry
landscape
vibrant
showcase
showcases
intricate
testament
underscore
underscores
underscoring
it's important to note
it is important to note
it's worth noting
in summary
in conclusion
great question
i hope this helps
stands as
serves as
plays a vital role
certainly!
let me know if
```

The operator's patterns file is personal config **(operator decided)**: it moves from `<config>/steward/prose-patterns` to `<config>/steward-prose-gate/prose-patterns`. Format unchanged (`:1044-1064`): one case-insensitive regex per line, `#` comments, `^` and `$` per line, a bad line skipped, one hit blocks. Steward ships no default file.

## Config, state and env vars

`<config>` per harness: Claude Code `$CLAUDE_CONFIG_DIR` or `~/.claude`; pi `$PI_CODING_AGENT_DIR` or `~/.pi/agent`; Copilot `$COPILOT_HOME` or `~/.copilot`; Codex `$CODEX_HOME` or `~/.codex` (`codex/steward.py:19-21`). `<state>` is `$XDG_STATE_HOME` or `~/.local/state`.

**(orchestrator's call, from the decision log)**: each plugin has its own config dir named after it, its own switch, and env vars carrying its name.

| Old | New | Plugin |
|-|-|-|
| `<config>/steward/gate` (`off\|soft\|hard`) | `<config>/steward-delegation/gate` (same values, default `hard`) | delegation |
| env `STEWARD_GATE` | env `STEWARD_DELEGATION_GATE` | delegation |
| `<config>/steward/allowlist` | `<config>/steward-delegation/allowlist` | delegation |
| `~/.pi/agent/steward/model-plan.json` (`model_plan.py:1907`, `model_plan_apply.py:154`) | `~/.pi/agent/steward-delegation/model-plan.json` | delegation |
| `.pi/steward-model-plan.json`, `profiles/pi-subagents/steward.json` | unchanged | delegation |
| `<state>/steward/<session>.json` and `.lock` | `<state>/steward-delegation/<session>.json` | delegation |
| `<state>/steward/copilot-main/` | `<state>/steward-delegation/copilot-main/` and `<state>/steward-prose-gate/copilot-main/` | both |
| `<state>/steward/pi-delegations.jsonl*` (`delegation_stats.py:37-38`, `index.ts:300`) | `<state>/steward-delegation/pi-delegations.jsonl*` | delegation |
| env `STEWARD_PLUGIN_ROOT` | env `STEWARD_DELEGATION_ROOT` (tests only; the pi extension stops setting it, `index.ts:117`) | delegation |
| env `STEWARD_HOOK_LOG` | env `STEWARD_DELEGATION_HOOK_LOG` | delegation |
| env `STEWARD_PYTHON` | `STEWARD_DELEGATION_PYTHON`, `STEWARD_PROSE_GATE_PYTHON` | each pi extension |
| env `STEWARD_HARNESS` | removed; first argument | all |
| env `STEWARD_ALLOW_MISSING_BASE_COMMIT` | removed with its tests | n/a |
| `<config>/steward/prose-patterns` | `<config>/steward-prose-gate/prose-patterns` | prose-gate |
| none (PR gate shared `STEWARD_GATE`) | `<config>/steward-prose-gate/gate` (`on\|off`, default `on`), env `STEWARD_PROSE_GATE` | prose-gate |
| `~/.claude/orchestration/initiatives.md`, env `STEWARD_ORCHESTRATION_DIR` | unchanged | orchestration |
| "sauron" text in the skill | `~/.claude/orchestration/edict.md` (optional, operator-owned) | orchestration |

Harness-owned variables stay as they are: `CLAUDE_CONFIG_DIR`, `PI_CODING_AGENT_DIR`, `COPILOT_HOME`, `CODEX_HOME`, `XDG_STATE_HOME`, `HOME`, `PI_SUBAGENT_CHILD`, `CLAUDE_PLUGIN_ROOT`, `PLUGIN_ROOT`.

## Names

Claude Code and Copilot namespace skills and agents by plugin name, so those names change. Skills keep their short names `delegating` and `orchestrating`; the namespace already says which plugin **(orchestrator's call)**.

| Old | New |
|-|-|
| `steward:delegating` (Claude, Copilot, Codex) | `steward-delegation:delegating` |
| `steward:orchestrating` | `steward-orchestration:orchestrating` |
| `steward:coder-opus-medium` and the six other Claude profiles | `steward-delegation:coder-opus-medium` and so on |
| Copilot `steward:<role>`, and `subagents.agents."steward:<role>"` keys in `~/.copilot/settings.json` | `steward-delegation:<role>` |
| plugin id `steward@steward` | `steward-delegation@steward`, `steward-prose-gate@steward`, `steward-orchestration@steward` |
| plugin id `steward@steward-codex` | `steward-delegation@steward-codex`, `steward-prose-gate@steward-codex` |
| pi `steward.<role>`, `steward-delegating`, `/steward-models`; Codex agents `steward-<role>` | unchanged |

Places the names are written out, for the builder to update (counts are `grep -c 'steward:'` at c5fd21b):
- Edicts: `skills/delegating/SKILL.md` (14: rule 2, routing table, Role check, Hooks section lines 44-45 with paths and `STEWARD_GATE`), `copilot/skills/delegating/SKILL.md` (22, Hooks section line 62), `pi/skills/steward-delegating/SKILL.md` (Hooks section line 57: paths and env), `codex/skills/delegating/SKILL.md` (skill self-references).
- `skills/delegating/routing.md` (32).
- `skills/orchestrating/onboarding-template.md` (3) and `skills/orchestrating/SKILL.md`.
- Code: `REGISTRY_SKELETON` (`hooks/steward_hook.py:116`), session-start header (`:439`), `_copilot_bound_profiles_note` (`:197`), `_COPILOT_FALLBACK_EDICT` (`:232-239`), `gate_message` (`:980-1012`).
- Copilot agent descriptions, which the parity test rewrites names in (`tests/test_copilot_harness.py:728`).
- Tests: `test_steward_hook.py` (1), `test_copilot_harness.py` (8), `test_no_opus_max.py` (7), `test_routing_tables.py` (3), `test_pi_harness.py` (4).
- `README.md` (18). History docs (`docs/roadmap/codex-port.md`, `copilot-port.md`) keep their text and get a one-line pointer to this file.

Done-check: `grep -rnE 'steward:[a-z]' plugins/` returns nothing. (The pi extension's message prefixes are `steward: ` followed by a space and do not match.)

## Personal content

**(orchestrator's call, from the decision log)**: personal content leaves the shipped plugins and moves to operator config.

- **"sauron" edict** (`skills/orchestrating/SKILL.md:21`, `onboarding-template.md:15`, `README.md:434`). Removed. The orchestrating skill instead says: if `<registry dir>/edict.md` exists, the primary sends its text verbatim in the onboarding message and secondaries follow it. No code reads the file **(orchestrator's call)**. The operator writes `~/.claude/orchestration/edict.md` from `git show v0.14.2:skills/orchestrating/SKILL.md` line 21.
- **Zero em-dash rule.** It is the operator's rule, and it overrides the plainlanguage skill, which allows an em-dash for an ordinary aside (`common-skills/plainlanguage/SKILL.md:77`). Removed from every shipped text and check **(orchestrator's call)**: the edict sentence in rule 4 (`skills/delegating/SKILL.md:12`, `pi/skills/steward-delegating/SKILL.md:12`, `copilot/skills/delegating/SKILL.md:12`, `codex/skills/delegating/SKILL.md:40`), agent bodies (`agents/reviewer-opus-max.md:10`, `agents/writer-sonnet-medium.md:12` and their pi, Copilot and Codex copies), `onboarding-template.md:13`, `_COPILOT_FALLBACK_EDICT`, the gate messages, and the `EM_DASH` checks (`hooks/steward_hook.py:1145`, `1530`). The operator keeps the rule in two places: one line `\u2014` in `prose-patterns` (Python `re` reads `\u2014` as the character; one hit blocks, as today), and one sentence in `~/AGENTS.md`. If the operator prefers to keep the built-in check, keep `EM_DASH` in `prose_gate_hook.py` and skip the patterns line; nothing else in this design changes. Done-check: `grep -rniE 'em.?dash|2014' plugins/` finds only tests that assert the built-in check is gone.

## Profiles and edict copies

The seven profiles stay in four hand-kept copies (`agents/`, `pi/agents/`, `copilot/agents/`, `codex/skills/delegating/profiles.json`) and the edict in four forks, all inside steward-delegation, with no generator. The tests that keep them in step move with them unchanged except for paths:
- `test_pi_harness.py:289-300` `test_each_profile_mirrors_its_claude_twin` (body, model map, thinking equals effort).
- `test_copilot_harness.py:728` (description with names rewritten, body).
- `test_codex_harness.py` (pinned model and effort, fallback, installer).
- `test_routing_tables.py` (routing tables in the four edicts agree with `routing.md`).
- `test_no_opus_max.py` (no "Opus max" in routing, edicts, template, agents).
- `test_pi_harness.py:269-272` and `test_copilot_harness.py:690-697` become one version test per plugin covering every manifest it has.

## Tests

Baseline at c5fd21b on the operator's machine, 2026-10-24: 608 Python tests, 2 failing (`test_pi_model_plan_apply` `test_version_is_pinned` and `test_pi_model_plan_resolver` `test_installed_version_is_the_mirrored_one`: installed pi-subagents is 0.82.0, mirrored is 0.78.0); 102 node tests, all passing. The two failures come from the machine, not the code. Either install `npm:pi-subagents@0.78.0` for the build or carry them as the known baseline; no step may add a failure.

Each plugin owns `plugins/<name>/tests/` (Python) and `plugins/<name>/tests/pi/` (node). Plugin tests read only files inside their plugin folder. Shared fixtures (`StewardTestCase`, `run_hook`, `EM_DASH` from `tests/test_steward_hook.py:52`, imported by `test_copilot_harness.py:19` and `test_codex_harness.py:11`) are copied into each plugin's `tests/helpers.py`. Root `tests/` keeps repo-level checks only.

The full suite is `npm test` from the repo root, which runs `package.json` `scripts.test`. At the end it is:
```
python3 -m unittest discover -s tests
 && python3 -m unittest discover -s plugins/steward-delegation/tests
 && python3 -m unittest discover -s plugins/steward-prose-gate/tests
 && python3 -m unittest discover -s plugins/steward-orchestration/tests
 && node --test 'plugins/*/tests/pi/*.test.mjs'
```
(one line in the file). Separate processes per plugin avoid module-name clashes between test folders.

| Today | Goes to |
|-|-|
| `test_steward_hook.py` `SessionStartTests` (`:123`) | delegation (injection, frontmatter, missing skill fails open); orchestration (registry created once, not overwritten, unwritable dir); dropped: plainlanguage warning tests |
| `GateSubagentAndOffTests`, `GateCounterTests`, `GateModeFileTests`, `GateAllowlistTests`, `BashClassificationTests`, `DelegatedTests`, `AllowlistCwdResolutionTests`, `SanitizeSessionIdTests`, `CounterAtomicityTests` (`:216-470`, `782`, `1052-1135`) | delegation |
| `PrGateTests` (`:702`), `ProseGateTests` (`:815`), `MarkerRegexTests` (`:1011`), `OperatorPatternTests` (`:1136`) | prose-gate; em-dash cases rewritten as operator-pattern cases; `test_clean_pr_body_passes_through_to_normal_gate` becomes one test per plugin |
| `HooksJsonTests` (`:1028`) | one per plugin, for its own hooks.json |
| `test_copilot_harness.py` (63) | delegation (session-start, bound note, gate, agents parity, manifest); prose-gate (main-session record, `events.jsonl`, `task_complete`, PR gate) |
| `test_codex_harness.py` (13) | delegation (profiles, installer, session-start); prose-gate (gate, prose-gate, fail open) |
| `test_pi_harness.py` (35), `test_pi_edict_2d.py`, `test_routing_tables.py`, `test_no_opus_max.py` (skill and agent parts) | delegation |
| `test_no_opus_max.py` README and `docs/roadmap/pi-model-plan.md` parts | root `tests/` |
| ten `test_pi_model_plan*.py`, `test_pi_delegation_stats.py`, `test_pi_release_review.py`, `test_pi_small_fixes.py` | delegation |
| `test_pi_model_plan_render.py` regression tests against `BASE_COMMIT` eb80786 (`:34-37`, `320-...`) | retired: they compare with `git show eb80786:hooks/steward_hook.py`, a script that no longer exists in any plugin; replace with fixed expected output |
| `tests/pi/steward-extension.test.mjs` | delegation; its PR-gate and prose-gate cases (the PR halves of `:150-198`, and `:319`, `:345-401`, `:429`) to prose-gate |
| `tests/pi/steward-delegation-log`, `steward-model-apply`, `steward-model-plan`, `steward-write-stdout` tests, `profile_check.mjs`, `resolve_model.mjs` | delegation |

New root tests: `tests/test_catalogs.py` (the `steward` entries pin `v0.14.2`; every other entry's path exists and its name matches its plugin manifest) and `tests/test_layout.py` (no file under `plugins/<a>/` names another plugin's folder or `steward_hook`; each plugin's manifests share one version; the root `package.json` pi paths exist; each plugin folder copied alone to a temp dir runs every hook mode for every harness it ships with a minimal payload and exits as its contract says: 0 for hook modes, 2 for the pi CLI modes on bad input, `hooks/steward_hook.py:299`, `361`).

## Release and migration

- README: the root README becomes an index (what each plugin does, install sets per harness, "Staying on 0.14.2", local development and tests). Today's sections move to the plugin READMEs. Delegation: README.md:35-51 (profiles), 53-60 (hooks, delegation gate), 78-85 (gate mode), 87-324 (pi), 326-417 (Copilot) and 428-435 without the sauron quote, each minus its prose-gate parts. Prose gate: 61-76 (prose and PR gates, banned phrases) and the prose-gate parts of 289-305 and 398-417. Orchestration: the roles text and the `edict.md` note.
- `docs/roadmap/orchestration-split.md` gets its status line changed to "Superseded by plugin-split.md".
- Plugin releases are tagged `<plugin>--v<version>`.

### Operator's machine

Claude Code, in each `CLAUDE_CONFIG_DIR` profile:
1. `claude plugin uninstall steward@steward`, then `claude plugin marketplace update steward`.
2. `claude plugin install steward-delegation@steward --scope user`, the same for `steward-prose-gate` and `steward-orchestration`.
3. Keep plainlanguage deployed in `~/.claude/skills/plainlanguage/`, or switch to the common-skills plugin once it exists; not both.
4. `mkdir -p ~/.claude/steward-delegation ~/.claude/steward-prose-gate`, `mv ~/.claude/steward/gate ~/.claude/steward-delegation/gate`, `mv ~/.claude/steward/prose-patterns ~/.claude/steward-prose-gate/prose-patterns`, add the line `\u2014` to that file, `rmdir ~/.claude/steward`.
5. Write `~/.claude/orchestration/edict.md` with the sauron text.
6. In `~/AGENTS.md`: add the zero em-dash sentence; update the steward section (skill names, `~/.claude/steward-prose-gate/prose-patterns`, `~/.pi/agent/steward-prose-gate/prose-patterns`).

Copilot:
1. Close running Copilot sessions first; a session that outlives its plugin folder fails closed on every PreToolUse (README:356).
2. `copilot plugin uninstall steward`, refresh the `steward` marketplace, `copilot plugin install steward-delegation@steward` and `steward-prose-gate@steward`.
3. Point the link at the new file: `mkdir -p ~/.copilot/steward-prose-gate && ln -s ~/.claude/steward-prose-gate/prose-patterns ~/.copilot/steward-prose-gate/prose-patterns`, then remove `~/.copilot/steward/`.
4. Rename any `steward:<role>` keys in `~/.copilot/settings.json` `subagents.agents`.

Codex:
1. Remove `steward@steward-codex`; add `steward-delegation@steward-codex` and `steward-prose-gate@steward-codex` (the marketplace source is this checkout, `~/.codex/config.toml:240-242`).
2. Review and trust the new hooks with `/hooks`. New keys: `steward-delegation@steward-codex:codex/hooks.json:session_start:0:0`, `steward-prose-gate@steward-codex:codex/hooks.json:pre_tool_use:0:0` and `:stop:0:0`. Delete the old `steward@steward-codex:*` trust entries (`~/.codex/config.toml:154-161`).
3. Optional agents: `python3 plugins/steward-delegation/codex/install_agents.py` (same `steward-<role>` names; it refuses on a differing file).

pi:
1. Choose: `pi install /mnt/agent-storage/vader/src/steward` (local path, reads the checkout in place) in place of the unpinned git entry in `~/.pi/agent/settings.json`, or keep the git entry and `pi update` after the merge.
2. `mkdir -p ~/.pi/agent/steward-delegation ~/.pi/agent/steward-prose-gate`; move `gate` and `model-plan.json` (and its `.bak-*` files) from `~/.pi/agent/steward/` to `steward-delegation/`; link `~/.pi/agent/steward-prose-gate/prose-patterns` to the Claude file; remove `~/.pi/agent/steward/`.
3. Optional, to keep stats history: `mkdir -p ~/.local/state/steward-delegation && mv ~/.local/state/steward/pi-delegations.jsonl* ~/.local/state/steward-delegation/`. Old counter files can be deleted.

## Build sequence

Guidance for the implementation plan, not the plan. Each step is one commit, about one sitting, on a branch off main (merge with `--no-ff`, never rebase). "Suite" means `npm test` from the repo root; at step 1 it equals today's `python3 -m unittest discover -s tests && node --test 'tests/pi/*.test.mjs'`, and any step that adds a test folder extends `scripts.test` in the same commit. Every done-check includes: suite passes with no failure beyond the known baseline, and the printed test totals drop only by tests the step names as retired. Merge steps 0 and 1 to main on their own, before anything moves, so the pin and the pi notice are live first.

| # | Step | Files | Done-check |
|-|-|-|-|
| 0 | Tag the monolith | `git tag -a v0.14.2 c5fd21b`; push the tag (operator authorizes) | `git rev-parse v0.14.2^{commit}` prints c5fd21b2600b6fcbd137db80fd30f5dd2317d341; `git ls-remote origin refs/tags/v0.14.2` is non-empty |
| 1 | Pin the catalogs; README notice | `.claude-plugin/marketplace.json`, `.agents/plugins/marketplace.json` (`steward` entries to the tag); `README.md` top notice with the pi pin; new `tests/test_catalogs.py` | suite; a scratch `CLAUDE_CONFIG_DIR` that adds this checkout as a marketplace installs `steward@steward` at 0.14.2 with `hooks/steward_hook.py` in its cache |
| 2 | Prose gate, Claude Code | `plugins/steward-prose-gate/hooks/prose_gate_hook.py` (claude), `data/ai-tells.txt`, `tests/helpers.py`, `tests/test_prose_gate_claude.py`; `package.json` scripts.test | suite; ported prose, PR, marker and operator-pattern cases pass; the word-list file parses to the source list |
| 3 | Prose gate, Copilot | Copilot branch and `session-start` record in `prose_gate_hook.py`; `copilot/hooks.json`; `tests/test_prose_gate_copilot.py` | suite; main-session record and skip, `events.jsonl` wait, `task_complete` cases pass |
| 4 | Prose gate, Codex | Codex branch; `codex/hooks.json`; `tests/test_prose_gate_codex.py` | suite; ported Codex gate and prose-gate cases pass |
| 5 | Prose gate, pi | `pi/extensions/steward-prose-gate/index.ts`; `tests/pi/prose-gate-extension.test.mjs`; scripts.test node glob | suite; ported pi PR-gate, prose-gate, `isProseRevision`, `lastAssistantText`, child and no-python cases pass |
| 6 | Prose gate packaging | its `.claude-plugin/`, `.codex-plugin/`, `.github/plugin/` manifests, `package.json`, `hooks/hooks.json`, `README.md`, `tests/test_prose_gate_manifests.py`; catalog entries | suite; `claude --plugin-dir plugins/steward-prose-gate` in a scratch session sends back a reply with two markers and denies a `gh pr create` whose body has two markers |
| 7 | Orchestration hook | `plugins/steward-orchestration/hooks/orchestration_hook.py`, `hooks/hooks.json`, `tests/test_orchestration_hook.py`; scripts.test | suite; registry created once, never overwritten, unwritable dir still prints the context block |
| 8 | Orchestration content and packaging | `git mv skills/orchestrating plugins/steward-orchestration/skills/`; namespace, sauron and `edict.md` edits; `.claude-plugin/plugin.json`, `README.md`; catalog entry; `tests/test_no_opus_max.py` template path | suite; `grep -rn sauron plugins/` is empty |
| 9 | Delegation content move | `git mv` `agents/`, `skills/delegating/`, `copilot/agents/`, `copilot/skills/`, `codex/skills/`, `codex/install_agents.py`, `pi/agents/`, `pi/skills/` to the same paths under `plugins/steward-delegation/`; repoint the monolith's reads (`hooks/steward_hook.py:250`, `407`, `409`; `codex/steward.py:29`; root `.github/plugin/plugin.json`, `.codex-plugin/plugin.json`, `package.json` pi paths) and test path constants | suite with the same totals as step 8 |
| 10 | Delegation hook, Claude Code | `plugins/steward-delegation/hooks/delegation_hook.py` (claude: session-start, gate, delegated), `tests/helpers.py`, `tests/test_delegation_claude.py`; scripts.test | suite; ported gate, counter, mode, allowlist, Bash-rule and `delegated` cases pass |
| 11 | Delegation hook, Copilot and Codex | Copilot and Codex branches; `copilot/hooks.json`, `codex/hooks.json`; ported delegation parts of `test_copilot_harness.py` and `test_codex_harness.py`, profile parity included | suite; bound-profile note uses `steward-delegation:` keys |
| 12 | Model plan move | `git mv hooks/model_plan*.py hooks/delegation_stats.py plugins/steward-delegation/hooks/`; pi branch and the three CLI modes in `delegation_hook.py`; one-line `_hook_module` repoint in the monolith (`hooks/steward_hook.py:302-308`); `git mv` the 13 model-plan and stats test files, switched to `delegation_hook.py pi ...`; retire the `BASE_COMMIT` tests | suite; model-plan totals drop only by the retired tests |
| 13 | Delegation pi extension | `git mv pi/extensions/steward plugins/steward-delegation/pi/extensions/steward-delegation`; hook path and `pi` argument; prose and PR gate code out; log and plan paths to `steward-delegation` (`index.ts:300`, `model_plan.py:1907`, `model_plan_apply.py:154`, `delegation_stats.py:37-38`); `git mv tests/pi/*` minus cases ported in step 5; port the pi parts of `test_pi_harness.py`; root `package.json` pi field to its final shape | suite; `pi install <checkout>` in a scratch `PI_CODING_AGENT_DIR` with pi-subagents lists seven `steward.*` agents |
| 14 | Edict texts | the four edicts, `routing.md`, agent bodies (four copies); namespaces, Role check out, plainlanguage fallback sentence in, em-dash text out, Hooks sections with new paths and env; `git mv` `test_routing_tables.py`, `test_pi_edict_2d.py` and the skill and agent parts of `test_no_opus_max.py` into the plugin's tests | suite; the `steward:[a-z]` and em-dash greps above are clean |
| 15 | Delegation packaging | its four manifests, `hooks/hooks.json`, `README.md`, version test; catalog entries | suite; `claude --plugin-dir plugins/steward-delegation` in a scratch session injects the edict and denies a second direct edit |
| 16 | Retire the monolith | delete `hooks/steward_hook.py`, root `hooks/hooks.json`, `codex/steward.py`, `codex/hooks.json`, `copilot/hooks.json`, root `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.github/plugin/plugin.json`; delete `tests/test_steward_hook.py`, `test_copilot_harness.py`, `test_codex_harness.py`, `test_pi_harness.py` after checking each test is ported or listed as retired | suite; `grep -rn steward_hook --exclude-dir=docs .` is empty |
| 17 | Repo-level tests | `tests/test_layout.py` | suite; the copied-folder smoke runs for all three plugins |
| 18 | Docs | root `README.md`, the three plugin READMEs, status line of `orchestration-split.md`, pointers in `codex-port.md` and `copilot-port.md` | suite; every install command in the READMEs was run in step 19 |
| 19 | Live checks | none (scratch config dirs per harness) | Claude Code, Copilot, Codex and pi each: install the new plugins from the checkout, see one prose-gate block, one PR-gate deny, and (except Codex) one delegation-gate deny; Copilot finds `.github/plugin/plugin.json` inside a `plugins/<name>/` folder |
| 20 | Merge and tag | merge to main with `--no-ff`; tags `steward-delegation--v0.15.0`, `steward-prose-gate--v0.15.0`, `steward-orchestration--v0.15.0` (operator authorizes the push) | tags point at the merge commit |
| 21 | Operator machine | the checklist above | each harness starts a session with one edict and no duplicate gates |
| 22 | plainlanguage manifests | common-skills repo | `claude plugin install plainlanguage@stackhouse-common` in a scratch profile lists the skill with its two sibling files |

The prose-gate steps (2-6) and the orchestration steps (7-8) can swap. Step 13 needs step 5. Step 22 can run any time.

## Decided versus left to the builder

Operator decided (details in [Appendix A](#appendix-a-decision-log)): the four plugins, their names and boundaries; the unix principle; no backward compatibility for the new plugins; both gates in their own plugin; the word list in a data file with no user override; the prose-patterns file as personal config in the prose gate's config dir; the reorg in this repo; the marketplace out of scope; tag and pin; orchestration Claude Code only and depending on delegation; model plan and stats in delegation; dependencies manual on every harness; keep it simple.

Orchestrator's calls carried from the decision log: one hook script per plugin with copied helpers and no cross-plugin imports; a config dir, switch and env names per plugin; plugins as folders in this repo with their own manifests, versions, hooks and tests; plainlanguage stays in common-skills; personal content leaves the plugins; this file supersedes orchestration-split.md.

Orchestrator's calls new in this document (the operator should check these):
1. Versions start at 0.15.0; tags `<plugin>--v<version>`; the root `package.json` version is not a release number.
2. Root catalogs keep the pinned `steward` entry and list the new plugins; marketplace names unchanged.
3. Pi: root `package.json` exposes delegation and prose gate; per-plugin `package.json` for local installs; filters for selective install; no migration code.
4. Pi profile, skill, command and plan-file names and Codex agent names unchanged.
5. Harness passed as the first argument; `STEWARD_HARNESS` removed.
6. Prose gate switch is `on|off`, one switch for both gates.
7. Copilot prose gate gets its own SessionStart hook to record main sessions.
8. Missing-dependency notes are edict text, not file probes; delegation owns the plainlanguage note.
9. The Role check moves into steward-orchestration's SessionStart block.
10. The registry stays at `~/.claude/orchestration/`; the sauron text goes to `edict.md` beside it, read by the primary through the skill text.
11. The em-dash rule leaves all shipped texts and checks; the operator keeps it in `prose-patterns` and `~/AGENTS.md`.
12. Skills keep the names `delegating` and `orchestrating`.
13. A PR-gate deny now also counts as one direct edit for the delegation gate.
14. `ai-tells.txt` format; retiring the `BASE_COMMIT` regression tests; new root tests.

Left to the builder: function bodies and exact wording of messages; how tests are grouped within a plugin; README prose; the common-skills folder shape for plainlanguage.

## Open questions

- Does a Claude Code agent's `skills: [plainlanguage]` (`agents/writer-sonnet-medium.md:6-7`) still preload the skill when plainlanguage comes from a plugin, where its full name is `plainlanguage:plainlanguage`? Check at step 19; if not, list the namespaced name too, after confirming an unknown name in that list is ignored rather than fatal.
- Checks for step 19 that need no operator input, each with its fallback:
  - Codex accepts `ref` on a `url` source (else `git-subdir` with `path: "./"`).
  - Copilot finds `.github/plugin/plugin.json` in a subfolder (FINDINGS.md lists it as unconfirmed).
  - Codex loads a hooks-only `.codex-plugin/plugin.json` (prose gate has no `skills`; every documented example has one). A load failure here is a manifest question, not a hook bug.
  - pi filter paths match without the `./` the manifest uses. A wrong form loads everything silently, so check that the excluded extension is really absent.
  - `pi install git:github.com/tejgandham/steward@v0.14.2` over an existing unpinned entry: pi identifies git packages by URL without the ref, so it may update the ref or refuse. If it refuses, the README pin line says `pi remove git:github.com/tejgandham/steward` first.

## Appendix A: Decision log

From the conversation of 2026-10-24. "Operator" is the repo owner.

**Principle (operator decided).** Steward became a monolith. The split follows the unix philosophy: small units that each do one thing and can be combined. Backward compatibility is not required for the new plugins; names, ids, env vars and config paths may all change.

**The four plugins (operator decided names and boundaries).**

| Plugin | Job | Needs |
|-|-|-|
| plainlanguage | The writing skill only (SKILL.md, de-llm.md, ste100.md). No hooks. | nothing |
| steward-prose-gate | Prose gate (Stop) and PR-body gate (`gh pr create/edit`), together. Own on/off switch, own config dir, owns the operator's prose-patterns file location. | nothing (block messages name plainlanguage, do not require it) |
| steward-delegation | Delegation edict (session-start injection), routing table, seven pinned profiles, delegation gate (and `delegated` counter reset), pi model plan and delegation stats. | uses plainlanguage (soft) |
| steward-orchestration | Primary/secondary session roles. Claude Code only for now. Owns its own SessionStart hook that creates the registry (delegation stops creating it). | steward-delegation |

The name `plainlanguage` stays as is; the other three are prefixed `steward-`. Two levels in the operator's framing: delegation is the base level that enforces subagent use; orchestration is the upper level that adds primary and secondary roles on supported harnesses, on top of delegation.

**Prose and PR gate placement (roundtable deliberate, 2026-10-24, 8 panelists).**
- A (gates in plainlanguage): antigravity, codex, kimi-k3, minimax. C (own plugin): deepseek, qwen, glm-5.3, mimo. B (in delegation): nobody. D (split the two gates): rejected by all 8.
- Unanimous: the two gates stay together (they share the markers, `_clean_text`, the em-dash rule and the operator patterns loader); gates do not belong in delegation (Codex runs the prose and PR gates without the delegation gate); gates need their own switch (today `STEWARD_GATE=off` also disables the PR gate, because `pr_gate_violation` runs inside `cmd_gate`).
- All four A voters said they would pick C if plainlanguage must stay hook-free. The unix principle settles it: C. Operator accepted.
- Keep today's behavior that subagent `gh pr` calls are not gated (glm). Codex's current hook set (Bash PreToolUse and Stop, no delegation gate) is exactly steward-prose-gate's hook set (antigravity, kimi).

**AI-tell word list (operator decided).** The hard-coded list (`hooks/steward_hook.py:1019-1030`) moves out of code into a data file shipped inside steward-prose-gate. No skill uses it (`de-llm.md` is a separate catalog the gate never reads), so it lives with the code that reads it. Changes ship as a steward-prose-gate release. No per-user add or remove override (the operator rejected that layer). The operator's prose-patterns file (one regex per line, operator-authored, today at `~/.claude/steward/prose-patterns`, linked from `~/.pi/agent/steward/` and `~/.copilot/steward/`) stays personal config, moved to steward-prose-gate's config dir.

**Where code lives (operator decided).** The reorg happens in this repo. Once the plugin sources are ready, the Engen-Tech marketplace (Engen-Tech/plugins, see hatch's FINDINGS.md) is created separately to release them. Building the marketplace is out of scope; the design only has to make each plugin releasable as a self-contained folder.

**Existing users (operator decided: "Tag and pin").** Steward 0.14.2 is the last release of the monolith; existing installs stay on it. Tag `v0.14.2` on main at c5fd21b before the reorg (tags stopped at v0.8.1). Keep root catalog files on main pointing at that tag so `steward@steward` (Claude, Copilot) and `steward@steward-codex` (Codex) keep resolving 0.14.2 and never update. Pi installs `git:github.com/tejgandham/steward` from the default branch: the design must say how pi users stay on 0.14.2 and what the root `package.json` does.

**Dependencies (operator decided, relayed by the coordinator during this design).** Plugin dependencies stay manual on every harness, including Claude Code; do not use Claude Code's `dependencies` field. Install docs say which plugins go together; at runtime a plugin may tell the model in a short session-start note when a plugin it relies on is missing. Do not make this complicated for the sake of complexity: prefer the simplest scheme that works, cut optional machinery, keep the doc as short as a builder can use.

**Resumability (operator requirement, relayed by the coordinator).** Work may stop when quota runs out and resume in a fresh session, so this document carries its own decision log and harness facts, and the build is cut into small steps that each leave the suite green.

**Orchestrator calls recorded in the log before this document.** One hook script per plugin; the 1,638-line `hooks/steward_hook.py` is retired; shared helpers (config dir, harness detection and the like) are copied, about 30 lines each; no cross-plugin imports at runtime. Each plugin has its own config dir and switch, for example `<config>/steward-prose-gate/{gate,prose-patterns}` and `<config>/steward-delegation/{gate,allowlist}`; env vars renamed per plugin. All three steward plugins live as separate folders in this repo (`plugins/<name>/`), each with its own per-harness manifests, version, hooks and tests. plainlanguage source stays canonical in common-skills; its plugin manifests are added there. Personal content ("sauron" edict text, em-dash override) leaves the shipped plugins and moves to operator config. This design supersedes orchestration-split.md.

## Appendix B: Harness facts

Researched 2026-10-24 unless marked. Each harness's own docs are the source; recheck before encoding a fact.

**Claude Code.** Source: https://code.claude.com/docs/en/plugins/dependencies and https://code.claude.com/docs/en/plugins/marketplace-reference.md.
- A plugin may list `dependencies` in `.claude-plugin/plugin.json` or its marketplace entry; missing ones are auto-installed. A dependency from another marketplace needs `allowCrossMarketplaceDependenciesOn` in the root marketplace. The operator declined the field.
- Version ranges resolve against git tags named `<plugin-name>--v<version>`; "The plugin-name prefix lets one marketplace repository host several plugins with independent version histories."
- Remote plugin sources include `{"source":"github","repo":"owner/repo","ref":"...","sha":"..."}`, `url` and `git-subdir` (FINDINGS.md "Harness facts", 2026-10-03). Plugin id is `<name>@<marketplace>`; skills and agents are namespaced by the manifest name.

**Codex CLI.** Source: https://developers.openai.com/codex/plugins/build.
- No dependency field; open request https://github.com/openai/codex/issues/23531.
- "Use `"source": "url"` when the plugin lives at the repository root, or `"source": "git-subdir"` when the plugin lives in a subdirectory"; the documented `git-subdir` example carries `"ref"`. Local sources are `{"source":"local","path":"./..."}`, relative to the marketplace root.
- "Installing or enabling a plugin doesn't automatically trust its hooks." Trust keys look like `<plugin>@<marketplace>:<hooks path>:<event>:0:0` (`~/.codex/config.toml:154-161` on the operator's machine), so new plugin ids need a fresh `/hooks` review.
- Codex copies a plugin into its cache at install; it does not load a checkout live (`docs/roadmap/codex-port.md`).

**GitHub Copilot CLI.** Source: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference.
- No dependency field; "Unknown top-level fields are reported and ignored." Open request https://github.com/github/copilot-cli/issues/2113.
- Install forms: `plugin@marketplace`, `OWNER/REPO:PATH/TO/PLUGIN`, a git URL. It also reads `.claude-plugin/marketplace.json`. Marketplace entries take a relative path or `{"source":"github","repo":"owner/repo","ref":"...","path":"..."}`.
- Steward's root `.github/plugin/plugin.json` is read before `.claude-plugin/plugin.json` (README:345). Whether that holds inside a marketplace subfolder is unconfirmed (FINDINGS.md).
- Removing a plugin while sessions run leaves them failing closed on PreToolUse (README:356).

**pi.** Source: local checkout `/mnt/agent-storage/vader/src/earendil-pi/packages/coding-agent`.
- Git sources have no subdirectory form: `GitSource` holds type, repo, host, path (`user/repo`), ref, pinned (`src/utils/git.ts:6-19`; `buildGitSource` at `:104-111`).
- "Git tags and commits are also pinned; package updates reconcile the checkout but do not move a configured ref." (`docs/packages.md:40`)
- Git packages are identified "by repository URL without the ref" (`docs/packages.md:129`), so one scope holds one install of this repo.
- Filters narrow one package's `extensions`, `skills`, `prompts`, `themes`: `!pattern`, `+path`, `-path`; "Filters narrow the package manifest. They do not expose resources that the package itself did not declare." (`docs/packages.md:96-121`)
- A package can depend on another pi package only by bundling it through npm `dependencies` (`docs/packages.md:80-94`).
- A local path install loads in place without copying (`docs/packages.md:38`, `42`).
