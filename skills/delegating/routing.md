# Routing knowledge base

Routing knowledge base for the orchestrator. WHICH model and effort to pick is here; HOW to set it is in "Model and effort mechanics" below. Built 2026-09-03 from Anthropic's pricing and docs via web search.

## Cost ranking (per MTok input/output), cheapest to dearest (cited: platform.claude.com pricing, 2026-09-03)
- Haiku 4.5: $1 / $5
- Sonnet 5: $2 / $10
- Opus 5: $5 / $25
- Fable 5.1 = Mythos 5.1: $10 / $50 (the main/orchestrator thread; also 4x cheaper cache reads)

So Sonnet is about 5x cheaper than Fable, Opus about 2x cheaper. Any correct delegation off the main thread saves tokens.

Prices and model ids are as of 2026-09-03; the profiles use aliases (sonnet, opus, haiku, fable) so they track each machine's current model, which means this table can drift. Re-check before quoting a number.

## Pinned profiles (in the steward plugin `agents/` directory), delegate by subagent_type
- **steward:coder-sonnet-xhigh** (sonnet, xhigh): pure implementation with spec and tests (TDD), well-defined bug fixes, approved plans. Honors the operator's stated preference of Sonnet 5 xhigh for pure coding.
- **steward:deep-reasoner-opus-xhigh** (opus, xhigh): architecture, ambiguous design, cross-repo synthesis/plans, security review, high-stakes/subtle code review. Escalate to the main thread only if it falls short.
- **steward:reviewer-sonnet-high** (sonnet, high): everyday code review of a diff/PR.
- **steward:researcher-sonnet-low** (sonnet, low): thorough read-only investigation/search, plan inputs, findings docs.
- **steward:writer-sonnet-medium** (sonnet, medium): docs, README sections, substantive PR bodies, plain-language rewrites.
- **steward:mechanic-haiku** (haiku, no effort dial): single lookups, rote edits, file ops, running known commands, status collation, trivial PR one-liners.
- **steward:reviewer-fable-xhigh** (fable, xhigh): highest-stakes gap reviews of plans/specs; reserve for explicit operator requests or when steward:deep-reasoner-opus-xhigh falls short (cost: highest).

## Rubric (task to profile)
| Task | Profile |
|---|---|
| Pure coding, spec+tests (TDD) | steward:coder-sonnet-xhigh (steward:mechanic-haiku if single trivial file) |
| Refactor / simplify | steward:coder-sonnet-xhigh (steward:mechanic-haiku for small rote refactors) |
| Deep architecture / ambiguous design | steward:deep-reasoner-opus-xhigh, escalate to main thread if short |
| Cross-repo synthesis / plan writing | steward:deep-reasoner-opus-xhigh (or a coordinator plus sonnet workers if huge and splittable) |
| Read-only investigation / search | steward:researcher-sonnet-low (steward:mechanic-haiku for one targeted lookup) |
| Code review | steward:reviewer-sonnet-high (steward:deep-reasoner-opus-xhigh for high-stakes/complex) |
| Security review | steward:deep-reasoner-opus-xhigh |
| Mechanical edits / file ops | steward:mechanic-haiku |
| Docs / prose | steward:writer-sonnet-medium (steward:mechanic-haiku for short) |
| PR-body drafting | steward:writer-sonnet-medium (steward:mechanic-haiku for trivial diffs) |
| Status / collation | steward:mechanic-haiku (steward:researcher-sonnet-low if reconciling conflicting reports) |

## Keep it inline on the main thread when
one dependent chain fits a single context with no splittable pieces; every step needs frontier judgment; the context is already resident in the orchestrator thread; it is the final synthesis/arbitration the orchestrator owns; or there is no cheap way to verify a delegate's output.

## Caveats to remember (do not overclaim)
- Haiku has no reasoning-effort dial: its profile omits `effort`; effort settings do not apply to it.
- "Mythos-class, tier above Opus" is cited: anthropic.com/claude/fable says "Claude Fable 5.1 is a Mythos-level model." Primary-source validation on 2026-09-03 confirmed every other cited fact too (prices, 0.025x vs 0.1x cache reads, cost ranking, all four model ids, no "Haiku 5", Haiku 4.5 has no effort dial, 1M/1M/1M/200K context windows, the Opus-at-half-price quote, the 47-55% savings figure). The knowledge base is validated; refresh if Anthropic changes pricing.
- Multi-model cost-savings percentages are Anthropic's own "directional" benchmarks, not guaranteed on any particular workload; measure before trusting a specific number.
- A bare `Agent(model=...)` call cannot set effort; to get a profile's effort you must delegate by subagent_type (see "Model and effort mechanics" below).

**2026-09-10 addition:** seventh pinned profile `steward:reviewer-fable-xhigh` (fable, xhigh) for highest-stakes gap reviews of plans/specs; reserve for explicit operator requests or when steward:deep-reasoner-opus-xhigh falls short (cost: highest).

# Model and effort mechanics

Operational reference for choosing and setting a subagent's model and reasoning effort. Effort is definition-only, so effort control requires an agent file. Pair with the routing knowledge base above to decide WHICH model and effort; this section is HOW to set it. Sources: code.claude.com/docs/en/sub-agents.md and code.claude.com/docs/en/model-config.md (confirmed 2026-09-03).

## Frontmatter keys (agent file in the steward plugin `agents/` directory)
Same YAML block:
- `model`: alias `sonnet` | `opus` | `haiku` | `fable`, OR a full id (for example `claude-sonnet-5`), OR `inherit`.
- `effort`: `low` | `medium` | `high` | `xhigh` | `max` (which levels are valid is model-dependent).

Minimal example:
```markdown
---
name: coder-sonnet-xhigh
description: <when to use>
model: claude-sonnet-5
effort: xhigh
tools: <optional; omit to inherit all>
---
<system prompt>
```

## The load-bearing rule for routing
**Effort is definition-only for subagents.** The Agent/Task tool exposes a per-invocation `model` param but no effort param. So:
- To run a subagent at a chosen effort you must delegate via `subagent_type` to an agent file whose frontmatter sets `effort:`. A bare `Agent` call that only overrides `model` runs at the inherited/default effort, not a chosen one.
- `model` can still be overridden per-invocation (Agent tool `model`), and that override sits at the top of the model-resolution order. But it does not carry an effort.

## Independence and inheritance
- `model` and `effort` do not interact: overriding the model does not reset effort.
- `model: inherit` does not imply effort inherits. Effort inherits from the parent only when the `effort` key is omitted. Set both explicitly to be safe.

## Effort can be set four ways (scope, highest-precedence-while-active first)
1. Agent-file frontmatter `effort:`, wins while that subagent is active (use this for pinned profiles).
2. Env `CLAUDE_CODE_EFFORT_LEVEL` / `--effort` flag, session/run scope.
3. `/effort` command, interactive session scope.
4. `settings.json` `effortLevel` or `modelSettings.<model>.effortLevel`, global default.

## Caveats
- Version note: before v2.1.251, `CLAUDE_CODE_SUBAGENT_MODEL` outranked both per-invocation `model` and frontmatter `model`; on current versions per-invocation `model` is top.
- Unconfirmed community report (GitHub #81677, v2.1.219/220): `effort` frontmatter may be silently ignored on the `--agent <name>` session-persona path while `model` still applies; reportedly does not affect normal Task-tool-invoked subagents. If a pinned profile seems to ignore effort, suspect this and verify.

## How to apply this
Delegate by `subagent_type` to the pinned profile agents in the steward plugin `agents/` directory (model and effort fixed) for the recurring task archetypes. Use the Agent `model` override only to swap the model of an existing profile when its effort is still appropriate. Never rely on a bare `Agent(model=...)` call to get a specific effort; it will not work.
