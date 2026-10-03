# Future: split orchestration out of steward

Status: deferred. Recorded 2026-10-03. Nothing here is built yet.

## Summary

Steward does two separate jobs. The first is delegation: one session hands its work to pinned subagents, and the gates enforce that. The second is orchestration: one primary session directs secondary sessions, each working in its own repo. The plan is to move orchestration into its own plugin, built so that each harness only has to supply a small adapter. Until then, orchestration stays in steward and works on Claude Code only.

## The two jobs today

| | Delegation | Orchestration |
|-|-|-|
| What it covers | One session and its subagents | Several sessions, one repo each |
| How it is enforced | Code: the delegation, prose and PR gates in `hooks/steward_hook.py`, with tests | Nothing in code: the `orchestrating` skill asks the model to follow its rules |
| Harnesses | Claude Code and pi | Claude Code only |
| Files | `skills/delegating/`, `agents/`, `hooks/`, `pi/` | `skills/orchestrating/`, the registry created by the session-start hook |

The two touch in only a few places:
- the "Role check" paragraph and the "Everyone" heading in `skills/delegating/SKILL.md`;
- the session-start hook, which creates `~/.claude/orchestration/initiatives.md`;
- the README.

## Why split them

- Every Claude Code session creates the registry file and carries the role-check text, even though nearly every session has no role.
- The operator's personal "sauron" edict is quoted word for word inside a plugin that others can install.
- The two parts change for different reasons. Delegation changes with models and harness APIs; orchestration changes with how the operator runs multi-repo work. One version number covers both today.

## Why orchestration is Claude Code only

The rules themselves do not depend on a harness:
- one primary per initiative;
- briefs sent one step at a time;
- the decision log wins over a brief;
- status reports without being asked;
- no work before the operator authorizes it.

Four things do depend on the harness:
1. How a session is named and found. Claude Code: `ListAgents`.
2. How a message reaches another session. Claude Code: `SendMessage`.
3. Where the registry lives. Today: `~/.claude/orchestration/`.
4. Where a secondary keeps its rules so a context summary cannot lose them. Today: Claude project memory.

## Proposed shape

- **Steward** keeps delegation, routing, the profiles and the gates. It has no mention of roles.
- **A separate orchestration plugin** holds the protocol (the rules above) and depends on steward's rules instead of repeating them.
- **One small adapter per harness** says how to list sessions, send a message, and where state lives.
  - Claude Code: `ListAgents` and `SendMessage`.
  - pi: [pi-intercom](https://github.com/nicobailon/pi-intercom), which sends 1:1 messages between named pi sessions on the same machine and already works with pi-subagents. Build this adapter only when there is a multi-session initiative to run on pi.
- **Mixed harnesses** (for example a Claude Code primary directing a pi secondary) have no shared way to send messages today. They would need a common channel, such as a mailbox directory both sides read. Leave this out until it is needed.

## Problems to fix as part of the split

- **Memory.** The orchestrating skill, the onboarding template and delegating rule 7 tell sessions to save rules in agent memory. The operator's global rules forbid agent memory. Keep the rules in a committed file instead, for example the initiative's decision log.
- **Session identity.** Roles are matched by session name, and names drift. The current registry names its secondary `homelab-docs`, while the session that did the work was `homelab-docs-07`. Match on session id instead.
- **Stale entries.** Nothing removes an initiative when it ends; the one registry row has not changed since 2026-09-14. The primary should close its row when the operator closes the initiative.
- **Personal text.** Move the "sauron" edict out of the plugin into the operator's own `AGENTS.md`, or into a per-operator config file that the orchestration plugin reads.

## Alternative considered

Keep one plugin and turn orchestration off unless a config file turns it on. This saves an install step, but both parts would still share one version and one release. Choose it only if a second install is a real burden.
