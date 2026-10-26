# steward

Steward is a set of plugins for coding agents. They make the main agent hand work to subagents, keep its writing plain, and run primary and secondary sessions for work that spans several repos. They run on Claude Code, GitHub Copilot, Codex and pi, except orchestration, which is Claude Code only.

This repo is where the plugins are built. You install them from the Engen-Tech marketplace, [Engen-Tech/plugin-marketplace](https://github.com/Engen-Tech/plugin-marketplace). The marketplace id of each plugin ends in `@engen-tech`.

> **Staying on 0.14.2.** Steward 0.14.2 is the last release as one plugin. The repo is now split into separate plugins, and the files at the repo root have changed. The tag `v0.14.2` keeps the 0.14.2 code.
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

- **plainlanguage**: the writing skill. The agent uses it to rewrite prose for you and PR bodies in plain words. It is built in the separate common-skills repository and installs from the marketplace as `plainlanguage@engen-tech`.
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

A plugin never fails because another one is missing. The delegation edict and the prose gate's block messages name the plainlanguage skill, but both work without it: steward-delegation tells the agent to apply its short writing rules instead. steward-orchestration tells you once when steward-delegation is missing.

## Install

Install only the plugins in your set. If you used steward before, read [Moving from the steward marketplace](#moving-from-the-steward-marketplace) first.

### Claude Code

```
claude plugin marketplace add https://github.com/Engen-Tech/plugin-marketplace.git
claude plugin install plainlanguage@engen-tech --scope user
claude plugin install steward-prose-gate@engen-tech --scope user
claude plugin install steward-delegation@engen-tech --scope user
claude plugin install steward-orchestration@engen-tech --scope user
```

Use the HTTPS URL as shown. If you use several `CLAUDE_CONFIG_DIR` profiles, install once per profile.

### GitHub Copilot

```
copilot plugin marketplace add Engen-Tech/plugin-marketplace
copilot plugin install plainlanguage@engen-tech
copilot plugin install steward-prose-gate@engen-tech
copilot plugin install steward-delegation@engen-tech
```

Close running Copilot sessions before you install, remove or replace a plugin. A running session keeps the hooks of a deleted plugin folder, and Copilot then denies every edit and shell command in it. Copilot lists steward-orchestration too, because it reads the same catalog, but nothing in it runs on Copilot. Do not install it there.

### Codex

```
codex plugin marketplace add Engen-Tech/plugin-marketplace
codex plugin add plainlanguage@engen-tech
codex plugin add steward-prose-gate@engen-tech
codex plugin add steward-delegation@engen-tech
```

Codex does not run the hooks of a plugin you have not trusted. In an interactive session, review and trust each plugin's hooks once with `/hooks`. In `codex exec`, hooks of an untrusted plugin are skipped silently: no edict, no gate, no warning. For automation, run `codex exec --dangerously-bypass-hook-trust`. The Codex docs name that flag for vetted automation.

### pi

```
pi install npm:pi-subagents
pi install git:github.com/Engen-Tech/plugin-marketplace
```

Then restart pi, or run `/reload` in a running session. steward-delegation needs pi-subagents for its profiles; steward-prose-gate does not.

pi installs one package per git URL, so the marketplace's root `package.json` holds the pi parts of every plugin. To load only some of them, replace the plain entry in the `packages` list of `~/.pi/agent/settings.json` with the object form and a filter.

Everything except the prose gate:

```json
{
  "source": "git:github.com/Engen-Tech/plugin-marketplace",
  "extensions": ["-plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"]
}
```

Only the prose gate:

```json
{
  "source": "git:github.com/Engen-Tech/plugin-marketplace",
  "extensions": ["plugins/steward-prose-gate/pi/extensions/steward-prose-gate/index.ts"],
  "skills": []
}
```

Only delegation:

```json
{
  "source": "git:github.com/Engen-Tech/plugin-marketplace",
  "extensions": ["plugins/steward-delegation/pi/extensions/steward-delegation/index.ts"]
}
```

`"skills": []` drops every skill in the package, plainlanguage too.

pi's filters do not cover pi-subagents' own `subagents.agents` key, so the seven `steward.*` agents may still be listed when you filter out delegation. That does no harm.

### plainlanguage copies you placed by hand

Before the marketplace, plainlanguage was a skill folder you copied into your harness's skill directory, such as `~/.claude/skills/plainlanguage/` or `~/.agents/skills/plainlanguage/`. Once `plainlanguage@engen-tech` is installed, you can delete those copies.

## Moving from the steward marketplace

Steward 1.0.0 and later ship only from the Engen-Tech marketplace. To move an install:

| You have | Do this |
|-|-|
| Claude Code `steward@steward` 0.14.2 | Run `claude plugin uninstall steward@steward` and `claude plugin marketplace remove steward`. Add the Engen-Tech marketplace and install your set. In your config directory, move `steward/gate` to `steward-delegation/gate` and `steward/prose-patterns` to `steward-prose-gate/prose-patterns`. |
| Copilot `steward@steward` 0.14.2, or a direct `TejGandham/steward` install at 0.13.0 | Close running sessions. Run `copilot plugin uninstall steward` and remove the `steward` marketplace. Add the Engen-Tech marketplace and install your set. Point your prose-patterns link at `~/.copilot/steward-prose-gate/prose-patterns`, and rename `steward:<role>` keys under `subagents.agents` in `~/.copilot/settings.json` to `steward-delegation:<role>`. |
| Codex `steward@steward-codex` 0.14.2 | Remove the plugin and the `steward-codex` marketplace. Add the Engen-Tech marketplace and `codex plugin add` your set. Trust the new hook keys `steward-delegation@engen-tech:codex/hooks.json:session_start:0:0`, `steward-prose-gate@engen-tech:codex/hooks.json:pre_tool_use:0:0` and `steward-prose-gate@engen-tech:codex/hooks.json:stop:0:0`. Delete the old `steward@steward-codex:*` entries. |
| pi `git:github.com/tejgandham/steward`, pinned or not | Run `pi remove` on that entry, then `pi install git:github.com/Engen-Tech/plugin-marketplace`. Move `gate` and `model-plan.json` from `~/.pi/agent/steward/` to `~/.pi/agent/steward-delegation/`, and `prose-patterns` to `~/.pi/agent/steward-prose-gate/`. |
| `<x>@steward` 0.15.0 from steward main | Uninstall it before you install `<x>@engen-tech`. If both are installed, both load and their parts collide. |

If you do nothing, you stay on 0.14.2: the steward catalogs still pin `steward` to the tag `v0.14.2`.

## Local development and tests

This section is for working on the plugins in a steward checkout. It is not a way to install them.

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
