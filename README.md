# steward

Steward is a set of plugins for coding agents. They make the main agent hand work to subagents, keep its writing plain, and run primary and secondary sessions for work that spans several repos. They run on Claude Code, GitHub Copilot, Codex and pi, except orchestration, which is Claude Code only.

> **Staying on 0.14.2.** Steward 0.14.2 is the last release as one plugin. The repo is being split into separate plugins, and the files at the repo root will change. The tag `v0.14.2` keeps the 0.14.2 code.
>
> - Claude Code and Copilot `steward@steward`, and Codex `steward@steward-codex`: the marketplace entry now points at the tag `v0.14.2`. You stay on 0.14.2 and need to do nothing.
> - Copilot installed straight from the repo (`copilot plugin install TejGandham/steward`): that install follows the repo root. To stay on 0.14.2, uninstall it and install `steward@steward` from the marketplace.
> - pi: an unpinned `git:github.com/tejgandham/steward` follows the main branch. To stay on 0.14.2, pin it before you next run `pi update`:
>
>   ```
>   pi install git:github.com/tejgandham/steward@v0.14.2
>   ```
>
>   If pi refuses because the package is already installed, run `pi remove git:github.com/tejgandham/steward` first.
> - If an install moves off 0.14.2 anyway, reinstall it from the tag `v0.14.2`.

## The plugins

- **plainlanguage**: the writing skill. The agent uses it to rewrite prose for you and PR bodies in plain words. It lives in the separate common-skills repository, not here.
- **[steward-prose-gate](plugins/steward-prose-gate/README.md)**: sends back replies, and denies PR commands, whose text reads like AI-generated writing.
- **[steward-delegation](plugins/steward-delegation/README.md)**: the delegation edict, seven pinned subagent profiles chosen by how hard the task is, and a gate that denies a second direct edit in a row.
- **[steward-orchestration](plugins/steward-orchestration/README.md)**: primary and secondary session roles for initiatives that span several sessions. Claude Code only.

Each plugin README says what it ships on each harness and how to configure it.

## Which plugins to install

No plugin declares a dependency on another, so you install each one yourself. Pick a set:

| You want | Install |
|-|-|
| Plain prose only | plainlanguage, steward-prose-gate |
| Delegation | plainlanguage, steward-delegation; add steward-prose-gate to enforce the prose half of the edict |
| Orchestration (Claude Code) | all four |

A plugin never fails because another one is missing. steward-delegation tells the agent to apply its short writing rules when plainlanguage is not installed. steward-orchestration tells you once when steward-delegation is missing.

## Install

### Claude Code

```
claude plugin marketplace add tejgandham/steward
claude plugin install steward-prose-gate@steward --scope user
claude plugin install steward-delegation@steward --scope user
claude plugin install steward-orchestration@steward --scope user
```

Install only the plugins in your set. If you use several `CLAUDE_CONFIG_DIR` profiles, install once per profile.

### GitHub Copilot

```
copilot plugin marketplace add tejgandham/steward
copilot plugin install steward-prose-gate@steward
copilot plugin install steward-delegation@steward
```

Close running Copilot sessions before you install, remove or replace a plugin. A running session keeps the hooks of a deleted plugin folder, and Copilot then denies every edit and shell command in it. Copilot lists steward-orchestration too, because it reads the same catalog, but nothing in it runs on Copilot.

### Codex

```
codex plugin marketplace add tejgandham/steward
codex plugin add steward-prose-gate@steward-codex
codex plugin add steward-delegation@steward-codex
```

A local checkout path works in place of `tejgandham/steward`. Checked on codex-cli 0.164.0.

Codex does not run the hooks of a plugin you have not trusted. In an interactive session, review and trust each plugin's hooks once with `/hooks`. In `codex exec`, hooks of an untrusted plugin are skipped silently: no edict, no gate, no warning. For automation, run `codex exec --dangerously-bypass-hook-trust`. The Codex docs name that flag for vetted automation.

### pi

```
pi install npm:pi-subagents
pi install git:github.com/tejgandham/steward
```

Then restart pi, or run `/reload` in a running session. steward-delegation needs pi-subagents for its profiles; steward-prose-gate does not.

pi installs one package per git URL, so the repository's root `package.json` holds the pi parts of both steward-delegation and steward-prose-gate. To load only some of them, replace the plain entry in the `packages` list of `~/.pi/agent/settings.json` with the object form and a filter.

Everything except the prose gate:

```json
{
  "source": "git:github.com/tejgandham/steward",
  "extensions": ["-plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"]
}
```

Only the prose gate:

```json
{
  "source": "git:github.com/tejgandham/steward",
  "extensions": ["plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"],
  "skills": []
}
```

Only delegation:

```json
{
  "source": "git:github.com/tejgandham/steward",
  "extensions": ["plugins/steward-delegation/pi/extensions/steward-delegation/index.ts"]
}
```

If you installed from a local path, the `source` value in these snippets must match the string pi wrote into `settings.json` at install time. pi stores a local install as a relative path, so copy that string. Otherwise the filter does not apply.

pi's filters do not cover pi-subagents' own `subagents.agents` key, so the seven `steward.*` agents may still be listed when you filter out delegation. That does no harm.

### plainlanguage

plainlanguage is a skill folder with three files: `SKILL.md`, `de-llm.md` and `ste100.md`. Keep them together, in the skill directory your harness reads:

| Harness | Skill directory |
|-|-|
| Claude Code | `<config dir>/skills/plainlanguage/`, where `<config dir>` is `$CLAUDE_CONFIG_DIR` or `~/.claude` |
| GitHub Copilot | `~/.agents/skills/plainlanguage/` or `~/.copilot/skills/plainlanguage/` |
| Codex | `~/.agents/skills/plainlanguage/` |
| pi | `~/.agents/skills/plainlanguage/` or `~/.pi/agent/skills/plainlanguage/` |

## Local development and tests

To run Claude Code against one plugin in a checkout, point `--plugin-dir` at its folder:

```
claude --plugin-dir /path/to/steward/plugins/steward-delegation
```

For pi, `pi install /path/to/steward` loads the checkout in place, so edits apply on the next pi start or `/reload`.

Run the full suite from the repository root:

```
npm test
```

It runs the repo-level tests in `tests/` (catalogs, layout, docs), each plugin's Python tests, and the pi extension tests with node. Node 22.18 or newer runs the TypeScript extensions without a build step. The tests that check against a real pi-subagents install look for it at `$PI_SUBAGENTS_DIR`; set it to a missing path, such as `/nonexistent`, to skip them.
