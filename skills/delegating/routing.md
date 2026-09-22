# Routing knowledge base

Routing knowledge base for the orchestrator. WHICH model and effort to pick is here; HOW to set it is in "Model and effort mechanics" below. Built 2026-09-03 from Anthropic's pricing and docs via web search; revised 2026-09-22 for Opus 5.5's launch, the drop of Haiku 4.5 and Opus 5 from the matrix, and the move of the coder profile from Sonnet 5 xhigh to Opus 5.5 medium.

## Cost ranking (per MTok, input / output / cache read), cheapest to dearest (cited: platform.claude.com/docs/en/about-claude/pricing, fetched 2026-09-22)
| Model | Input | Output | Cache read |
|-|-|-|-|
| Sonnet 5 | $2 | $10 | $0.20 |
| Opus 5.5 | $4 | $20 | $0.20 |
| Fable 5.1 = Mythos 5.1 | $10 | $50 | $0.25 |

The pricing page states the $2/$10 Sonnet 5 price, originally introductory, is now standard; the planned 2026-09-01 increase to $3/$15 did not happen. Opus 5.5's price comes from anthropic.com/claude-opus-5-5, not yet on the pricing page at fetch time.

Sonnet is 5x cheaper than Fable and 2x cheaper than Opus 5.5; Opus 5.5 is 2.5x cheaper than Fable. Cache reads: Sonnet 5 and Opus 5.5 tie at $0.20, Fable 5.1 is $0.25. Any correct delegation off the main thread saves tokens.

Prices and model ids are as of 2026-09-22; the profiles use aliases (sonnet, opus, fable) so they track each machine's current model, which means this table can drift. Re-check before quoting a number.

## Opus 5.5 (launched 2026-09-22, cited: anthropic.com/claude-opus-5-5)
- "It performs at the level of Claude Fable 5.1 on most work and costs 40% less to run than Opus 5."
- "Input and output tokens are $4 and $20 per million, 20% less than Opus 5. Cache reads (which make up the majority of agentic and coding work costs) are $0.20 per million tokens, 60% less than Opus 5."
- "Opus 5.5 also generates output more than 30% faster than Opus 5."
- "much less likely than recent models to take hard-to-reverse actions or act outside the boundaries it's been given, and it's more resistant than Opus 5 to prompt injection."
- "Because Opus 5.5 is comparable to Claude Mythos 5.1 in biology and cybersecurity, we're deploying it with safeguards similar to those on Claude Fable 5.1."

Effort: Opus 5.5 accepts low, medium, high, xhigh, max. Anthropic's pre-launch Opus 5.5 migration guide (bundled inside Claude Code's `claude-api` skill, cached 2026-06-24; not a public web page, so treat as unconfirmed on the web) says the API default effort is `medium` (Opus 5's was `high`), thinking cannot be disabled, and at a given level Opus 5.5 thinks more per turn than Opus 5, especially at xhigh and max, so turns run longer. Steward profiles set effort explicitly, so the default does not affect them; the longer-turn point is why steward:deep-reasoner-opus-xhigh stays at xhigh only for the hardest work.

### Coder on Opus 5.5 (2026-09-22)
The earlier "Sonnet 5 xhigh for pure coding" preference was a Sonnet-versus-Haiku choice made 2026-09-03, before Opus 5.5 existed. It was never a preference against Opus 5.5, so Opus 5.5's launch supersedes it rather than overriding it.

Anthropic's pre-launch Opus 5.5 migration guide (same source as above: bundled in Claude Code's `claude-api` skill, cached 2026-06-24, not a public web page, unconfirmed on the web) states that at its default `medium` effort, Opus 5.5 "matched or beat Claude Opus 5's high-effort results" on multistep work in a real codebase, carrying a change through a large repository until its tests pass, "in fewer steps and with about half the tokens." It adds that "on several coding evaluations `low` comes close to it at much lower cost," and recommends: "Start at medium and test the neighboring levels; reserve xhigh and max for work where you have measured a quality gain." That workload, carrying a spec-and-tests change through a repository to green, is exactly the coder profile's job. `steward:coder-opus-medium` is set at `medium` on that basis.

Cost per token is 2x Sonnet 5 on input and output ($4/$20 versus $2/$10, see "Cost ranking" above), but cache reads tie at $0.20, and Anthropic's launch page says cache reads "make up the majority of agentic and coding work costs" (anthropic.com/claude-opus-5-5, 2026-09-22). Fewer steps and fewer tokens per task, per the migration guide's claim above, narrow the per-token gap further. What matters is cost per completed task, not cost per token, and nobody has measured that for this profile yet; say so plainly rather than implying a saving that has not been checked.

If a `steward:coder-opus-medium` run misses its gate, escalate in one step: rerun the same profile (its frontmatter effort stands; do not invent a per-invocation effort override, since a bare `Agent(model=...)` call cannot set effort) and flag the miss to the deep-reasoner, or hand the task to `steward:deep-reasoner-opus-xhigh` directly.

Sonnet 5 stays pinned for everyday review, research, writing, and mechanical work. Its price is the point there, and the high-stakes path already runs on Opus.

## Dropped models (2026-09-22)
- **Haiku 4.5** ($1/$5/$0.10): dropped. Nearest retirement floor of any model in the matrix (tentative, not sooner than 2026-10-15, three weeks out at drop time; platform.claude.com/docs/en/about-claude/model-deprecations, fetched 2026-09-22), 200K context versus 1M for the rest, no effort dial, and Sonnet 5 at `low` effort now covers the same rote work with an explicit effort setting. Cost for that rote work doubles per token, $1/$5 to $2/$10.
- **Opus 5** ($5/$25/$0.50): dropped. Superseded by Opus 5.5 at a 20% lower input/output price, 60% lower cache reads, and Fable-level quality on most work (anthropic.com/claude-opus-5-5, quoted above). The `opus` alias already resolves to Opus 5.5 on the installed Claude Code 2.1.280 binary here; see the alias-lag caveat below. Deprecation page: Active, tentative retirement not sooner than 2027-07-24.

Other matrix models' tentative retirement floors, same deprecations page: Sonnet 5 2027-06-30, Fable 5.1 2027-09-01. Opus 5.5 is not yet listed there.

## Pinned profiles (in the steward plugin `agents/` directory), delegate by subagent_type
- **steward:coder-opus-medium** (opus, medium): pure implementation with spec and tests (TDD), well-defined bug fixes, approved plans. See "Coder on Opus 5.5" above for why it moved off Sonnet 5 xhigh.
- **steward:deep-reasoner-opus-xhigh** (opus, xhigh): architecture, ambiguous design, cross-repo synthesis/plans, security review, high-stakes/subtle code review. Escalate to the main thread only if it falls short.
- **steward:reviewer-sonnet-high** (sonnet, high): everyday code review of a diff/PR.
- **steward:researcher-sonnet-low** (sonnet, low): thorough read-only investigation/search, plan inputs, findings docs.
- **steward:writer-sonnet-medium** (sonnet, medium): docs, README sections, substantive PR bodies, plain-language rewrites.
- **steward:mechanic-sonnet-low** (sonnet, low): single lookups, rote edits, file ops, running known commands, status collation, trivial PR one-liners. Replaces the mechanic-haiku profile as of 0.2.0, when Haiku 4.5 was dropped from the matrix; see "Dropped models" above.
- **steward:reviewer-fable-xhigh** (fable, xhigh): highest-stakes gap reviews of plans/specs; reserve for explicit operator requests, since Opus 5.5 is at Fable 5.1 level on most work for 40% of the price (cost: highest).

## Rubric (task to profile)
| Task | Profile |
|-|-|
| Pure coding, spec+tests (TDD) | steward:coder-opus-medium (steward:mechanic-sonnet-low if single trivial file) |
| Refactor / simplify | steward:coder-opus-medium (steward:mechanic-sonnet-low for small rote refactors) |
| Deep architecture / ambiguous design | steward:deep-reasoner-opus-xhigh, escalate to main thread if short |
| Cross-repo synthesis / plan writing | steward:deep-reasoner-opus-xhigh (or a coordinator plus sonnet workers if huge and splittable) |
| Read-only investigation / search | steward:researcher-sonnet-low (steward:mechanic-sonnet-low for one targeted lookup) |
| Code review | steward:reviewer-sonnet-high (steward:deep-reasoner-opus-xhigh for high-stakes/complex) |
| Security review | steward:deep-reasoner-opus-xhigh |
| Mechanical edits / file ops | steward:mechanic-sonnet-low |
| Docs / prose | steward:writer-sonnet-medium (steward:mechanic-sonnet-low for short) |
| PR-body drafting | steward:writer-sonnet-medium (steward:mechanic-sonnet-low for trivial diffs) |
| Status / collation | steward:mechanic-sonnet-low (steward:researcher-sonnet-low if reconciling conflicting reports) |

## Keep it inline on the main thread when
one dependent chain fits a single context with no splittable pieces; every step needs frontier judgment; the context is already resident in the orchestrator thread; it is the final synthesis/arbitration the orchestrator owns; or there is no cheap way to verify a delegate's output.

## Caveats to remember (do not overclaim)
- "Mythos-class, tier above Opus" is cited: anthropic.com/claude/fable says "Claude Fable 5.1 is a Mythos-level model." Primary-source validation on 2026-09-03 confirmed every other cited fact too (prices, 0.025x vs 0.1x cache reads, cost ranking, all four model ids then in the matrix, 1M/1M/1M/200K context windows, the Opus-at-half-price quote, the 47-55% savings figure). The 2026-09-22 revision re-verified pricing and deprecations against primary sources; see "Cost ranking", "Opus 5.5", and "Dropped models" above for those citations.
- Multi-model cost-savings percentages (the 40%, 20%, 60%, 30% figures above) are Anthropic's own comparisons against Opus 5, not guaranteed on any particular workload; measure before trusting a specific number.
- A bare `Agent(model=...)` call cannot set effort; to get a profile's effort you must delegate by subagent_type (see "Model and effort mechanics" below).
- Alias lag: code.claude.com/docs/en/model-config, as crawled 2026-09-22, still says `opus` resolves to Opus 4.8 and `sonnet` to Sonnet 4.6, both behind the current launches. The installed Claude Code 2.1.280 binary on this machine labels its Opus picker entry "Opus 5.5 - best for everyday, complex tasks" and its default-model string names Opus 5.5, so `opus` means Opus 5.5 here; check the binary, not just the docs page, before trusting an alias. The env vars `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` override what an alias resolves to, and a full id in agent frontmatter overrides the alias too.

# Model and effort mechanics

Operational reference for choosing and setting a subagent's model and reasoning effort. Effort is definition-only, so effort control requires an agent file. Pair with the routing knowledge base above to decide WHICH model and effort; this section is HOW to set it. Sources: code.claude.com/docs/en/sub-agents.md and code.claude.com/docs/en/model-config.md (confirmed 2026-09-03).

## Frontmatter keys (agent file in the steward plugin `agents/` directory)
Same YAML block:
- `model`: alias `sonnet` | `opus` | `haiku` | `fable`, OR a full id (for example `claude-sonnet-5`), OR `inherit`. `haiku` remains a valid alias, but no profile has used it since 0.2.0, when Haiku 4.5 was dropped from the matrix.
- `effort`: `low` | `medium` | `high` | `xhigh` | `max` (which levels are valid is model-dependent).

Minimal example:
```markdown
---
name: example-profile-name
description: <when to use>
model: claude-sonnet-5
effort: xhigh
tools: <optional; omit to inherit all>
---
<system prompt>
```

## The rule that decides routing
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
