# steward-delegation

steward-delegation makes the main agent hand work to subagents instead of doing it all itself. It has three parts:

- **The delegation edict**: rules added to every main session at start. They say which kind of task goes to which subagent, and how to brief it.
- **Seven pinned profiles**: subagents with a fixed model and effort, chosen by how hard the task is. The routing table in `skills/delegating/routing.md` maps tasks to profiles.
- **The delegation gate**: the main agent may make one direct edit. A second direct edit in a row is denied until a subagent call happens in between.

It works on Claude Code, GitHub Copilot, Codex and pi.

## What it ships on each harness

| Harness | What you get |
|-|-|
| Claude Code | SessionStart edict; 7 agents; `delegating` skill with `routing.md`; delegation gate; a subagent call resets the gate's counter |
| GitHub Copilot | SessionStart edict and a note on the profiles you bound; 7 agents; Copilot edict skill; delegation gate; a subagent call resets the counter |
| Codex | SessionStart edict; Codex edict skill with `profiles.json`; `install_agents.py`. No delegation gate |
| pi | extension: edict, model plan block, `/steward-models` (`check`, `apply`, `stats`), launch log, delegation gate; 7 agents; `steward-delegating` skill |

Codex has no delegation gate because Codex subagents share the parent's session id, so a per-session edit count would count a subagent's edits against the main session.

## What else to install

The plugin declares no dependencies on any harness. Install these yourself:

- **plainlanguage** (recommended): the writing skill the edict tells the agent to use for prose it writes to you and for PR bodies. It is a separate plugin; install it alongside this one. If it is missing, the agent applies the edict's short writing rules directly; on Claude Code, Copilot and pi it also tells you once.
- **pi-subagents** (pi only, required): pi has no subagents of its own, and the steward profiles run through this extension. Without it, the gate reminds instead of blocking, because the agent has no way to delegate.
- **steward-prose-gate** (optional): enforces the prose half of the edict by sending back replies and PR bodies that read like AI-generated text.

## Install

Claude Code:

```
claude plugin marketplace add tejgandham/steward
claude plugin install steward-delegation@steward --scope user
```

If you use several `CLAUDE_CONFIG_DIR` profiles, install once per profile.

GitHub Copilot:

```
copilot plugin marketplace add tejgandham/steward
copilot plugin install steward-delegation@steward
```

Close running Copilot sessions before you install, remove or replace the plugin. A running session keeps the hooks of a deleted plugin folder, and Copilot then denies every edit and shell command in it.

Codex: add this repository as a marketplace, then install `steward-delegation@steward-codex`. Codex asks you to review and trust the session-start hook with `/hooks` before it runs. To add the seven profiles as standalone Codex agents (`steward-<role>`), run `python3 plugins/steward-delegation/codex/install_agents.py`; it refuses to overwrite an agent file that differs.

pi:

```
pi install npm:pi-subagents
pi install git:github.com/tejgandham/steward
```

The repository's root package holds the pi extensions of both steward-delegation and steward-prose-gate. To load only the delegation extension, use the object form in `~/.pi/agent/settings.json`:

```json
{
  "source": "git:github.com/tejgandham/steward",
  "extensions": ["plugins/steward-delegation/pi/extensions/steward-delegation/index.ts"]
}
```

For local development, run Claude Code against this folder:

```
claude --plugin-dir /path/to/steward/plugins/steward-delegation
```

## Names

Claude Code and Copilot put the plugin name in front of each skill and agent:

- the skill is `steward-delegation:delegating`;
- the Claude Code profiles are `steward-delegation:coder-opus-medium`, `steward-delegation:deep-reasoner-opus-xhigh`, `steward-delegation:reviewer-sonnet-high`, `steward-delegation:researcher-sonnet-low`, `steward-delegation:writer-sonnet-medium`, `steward-delegation:mechanic-haiku-medium` and `steward-delegation:reviewer-opus-max`;
- the Copilot profiles carry role-only names, such as `steward-delegation:coder` and `steward-delegation:top-reviewer`.

If you bound Copilot profiles in `~/.copilot/settings.json` under `subagents.agents`, the keys use these names too; rename keys saved under the 0.14.2 plugin's prefix.

The plugin ids are `steward-delegation@steward` (Claude Code, Copilot) and `steward-delegation@steward-codex` (Codex). Names on pi (`steward.<role>`, `steward-delegating`, `/steward-models`) and Codex agent names (`steward-<role>`) did not change.

## The delegation gate

The gate watches direct edits on the main thread: Edit, Write, MultiEdit, NotebookEdit, and write-shaped shell commands such as a file redirect, `tee`, `sed -i`, `git commit` or `git push`, `gh pr create` or `gh pr edit`, `mv`, `cp`, `rm`, `mkdir`, `touch`, a package install, or a Python heredoc that writes a file. Read-only commands pass. Work done inside a subagent is not gated.

Set the mode by writing `off`, `soft` or `hard` to the file `<config>/steward-delegation/gate`:

```
mkdir -p ~/.claude/steward-delegation && echo soft > ~/.claude/steward-delegation/gate
```

- `hard`: denies a second direct edit in a row.
- `soft`: allows it, with a reminder.
- `off`: turns the gate off.

The file is read on every call, so a change applies right away. If the file does not exist, the environment variable `STEWARD_DELEGATION_GATE` is used; it applies only at the next session start. If that is also unset, the mode is `hard`.

`<config>` depends on the harness:

| Harness | Config directory |
|-|-|
| Claude Code | `$CLAUDE_CONFIG_DIR`, else `~/.claude` |
| GitHub Copilot | `$COPILOT_HOME`, else `~/.copilot` |
| Codex | `$CODEX_HOME`, else `~/.codex` |
| pi | `$PI_CODING_AGENT_DIR`, else `~/.pi/agent` |

### Files the gate never counts

Some edits are exempt, such as `CLAUDE.md`, `AGENTS.md`, memory folders, `/tmp`, and the harness's own config directory. On Copilot only parts of `~/.copilot` are exempt (settings, agents, skills, hooks, session state and the `steward-*` folders), because Copilot app chats run inside it. To add your own, list one glob per line in `<config>/steward-delegation/allowlist`:

```
/home/me/notes/**
**/scratch/*.md
```

A shell command is exempt only when every path it writes is on the list.

## pi settings

- `STEWARD_DELEGATION_PYTHON`: the Python interpreter the extension runs the hook with. Default `python3`. If it cannot be found, the extension shows a warning, and the edict and the gate are off for that session.
- `STEWARD_DELEGATION_HOOK_LOG`: a file path. When set, the extension appends one JSON line per hook call, for debugging. The lines can hold commands, file contents and replies, so leave it unset in normal use.

The model plan, `/steward-models` and the launch log are pi only. The plan file is `~/.pi/agent/steward-delegation/model-plan.json`, and the launch log is `$XDG_STATE_HOME/steward-delegation/pi-delegations.jsonl` (by default under `~/.local/state`).
