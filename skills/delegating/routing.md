# Routing knowledge base

Routing knowledge base for the orchestrator. WHICH model and effort to pick is here; HOW to set it is in "Model and effort mechanics" below. Built 2026-09-03 from Anthropic's pricing and docs via web search; revised 2026-09-22 for Opus 5.5's launch, the drop of Haiku 4.5 and Opus 5 from the matrix, and the move of the coder profile from Sonnet 5 xhigh to Opus 5.5 medium; revised 2026-10-03 for Sonnet 5.5 replacing Sonnet 5; revised 2026-10-09 for Haiku 5.5 and the mechanic's move to it.

## Cost ranking (per MTok, input / output / cache read), cheapest to dearest (cited: platform.claude.com/docs/en/about-claude/pricing, fetched 2026-09-22, re-fetched 2026-10-03 and 2026-10-08)
| Model | Input | Output | Cache read |
|-|-|-|-|
| Haiku 5.5 | $0.10 (over 100K-token prompts: $0.50) | $0.50 ($2.50) | $0.01 ($0.05) |
| Sonnet 5.5 | $2 | $10 | $0.10 |
| Opus 5.5 | $4 | $20 | $0.20 |
| Fable 5.1 = Mythos 5.1 | $10 | $50 | $0.25 |

The 2026-10-03 pricing page lists Sonnet 5.5 at the same $2/$10/$0.20 as Sonnet 5 and now includes Opus 5.5 at $4/$20/$0.20 (its cache reads are priced at 0.05x input). On 2026-09-22 the page said the $2/$10 Sonnet 5 price, originally introductory, had become standard; the planned 2026-09-01 increase to $3/$15 did not happen. Sonnet 5.5 cache reads were halved to $0.10 on 2026-10-07 (anthropic.com/claude-haiku-5-5), so Sonnet and Opus no longer tie on cache reads (Opus $0.20).

Sonnet is 5x cheaper than Fable and 2x cheaper than Opus 5.5; Opus 5.5 is 2.5x cheaper than Fable. Haiku 5.5 is 20x cheaper than Sonnet on input and output and 10x on cache reads below 100K prompt tokens, 4x and 2x above. Cache reads: Sonnet 5.5 $0.10, Opus 5.5 $0.20, Fable 5.1 $0.25. Any correct delegation off the main thread saves tokens.

Prices and model ids are as of 2026-10-08; the Claude Code profiles use aliases (haiku, sonnet, opus, fable) so they track each machine's current model, which means this table can drift. Re-check before quoting a number.

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

Cost per token is 2x Sonnet 5 on input and output ($4/$20 versus $2/$10, see "Cost ranking" above), but cache reads tie at $0.20, and Anthropic's launch page says cache reads "make up the majority of agentic and coding work costs" (anthropic.com/claude-opus-5-5, 2026-09-22). Note 2026-10-09: the tie ended 2026-10-07, when Sonnet 5.5 cache reads dropped to $0.10 against Opus 5.5's $0.20. Fewer steps and fewer tokens per task, per the migration guide's claim above, narrow the per-token gap further. What matters is cost per completed task, not cost per token, and nobody has measured that for this profile yet; say so plainly rather than implying a saving that has not been checked.

If a `steward:coder-opus-medium` run misses its gate, escalate in one step: rerun the same profile (its frontmatter effort stands; do not invent a per-invocation effort override, since a bare `Agent(model=...)` call cannot set effort) and flag the miss to the deep-reasoner, or hand the task to `steward:deep-reasoner-opus-xhigh` directly.

Sonnet 5.5 stays pinned for everyday review, research, and writing; mechanical work moved to Haiku 5.5 on 2026-10-09 (see "Haiku 5.5" below). Its price is the point there, and the high-stakes path already runs on Opus.

## Sonnet 5.5 (launched 2026-09-28, cited: platform.claude.com/docs/en/models/sonnet-5-5/overview, fetched 2026-10-03)
- Model id `claude-sonnet-5-5`; 1M context, 128K max output; adaptive thinking; API default effort `high`; knowledge cutoff Jun 2026.
- Price is the same as Sonnet 5: $2/$10, cache reads $0.20 (pricing page, fetched 2026-10-03). Note 2026-10-09: cache reads dropped to $0.10 on 2026-10-07, ending the tie with Opus 5.5 at $0.20. Moving the sonnet profiles to it cost nothing extra per token; three sonnet profiles remain after 2026-10-09, when the mechanic moved to Haiku 5.5.
- Effort: the Models API on this machine's proxy reports low, medium, high, xhigh and max as supported (`GET /v1/models/claude-sonnet-5-5`, 2026-10-03), so the profiles' low, medium and high settings all apply.
- On Claude Code the profiles use the `sonnet` alias, which already resolves to Sonnet 5.5 here (see the alias caveat below). On pi the profiles name it directly: `anthropic/claude-sonnet-5-5`.

## Haiku 5.5 (launched 2026-10-07, cited: anthropic.com/claude-haiku-5-5, platform.claude.com/docs/en/build-with-claude/effort, fetched 2026-10-08)
- Model id `claude-haiku-5-5`; 1M context, 128K max output; the first Haiku with effort levels, all five (low, medium, high, xhigh, max); default effort `medium`.
- Two price cards: $0.10/$0.50, cache reads $0.01 for prompts up to 100K tokens; $0.50/$2.50, cache reads $0.05 for prompts over 100K tokens.
- Fit, in Anthropic's words: "best suited to more narrowly scoped tasks ... like compaction, summarization, or subagent work" and "Sonnet 5.5 and Opus 5.5 remain better choices for complex agentic coding tasks".
- Effort guidance: "Start with `medium` for most work, including agentic coding ... In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at `low`". A bare steward subagent prompt is about 55K tokens, which is a long agent prompt, so the mechanic is pinned at medium, not low.
- Local probe, 2026-10-08: the same rename-and-test task gave a byte-identical correct diff on Haiku low (2 runs), medium (2), high (1) and Sonnet low (1), at $0.011 to $0.013 input-side cost per Haiku run against $0.136 for Sonnet low, at the same wall time, with no request over 100K.

### Why the other Sonnet profiles did not move
- Researcher: in the probe (one run per cell) Haiku high found more than Sonnet low at $0.135 versus $0.239, but took 195s versus 47s with 15 of 24 requests over the 100K card, and no measured invented-finding rate exists.
- Writer: in the probe Haiku high passed the prose checks but omitted facts Sonnet medium included.
- Reviewer: no Haiku code-review result exists, and on Artificial Analysis Terminal-Bench Haiku max scores 32.8% versus Sonnet high 43.9%.
- Coder: stays on Opus medium (Artificial Analysis index 51 at $1.34 per task versus Sonnet high 47 at $0.88 and Sonnet xhigh 52 at $2.01); cost per completed spec-coding task is still unmeasured.

Roundtable, 2026-10-09: four responding panelists (pi-seated DeepSeek, Qwen, MiniMax, Ember; GLM and MiMo returned nothing) agreed 4 of 4 on mechanic to Haiku and on keeping coder, deep-reasoner and writer; they split on mechanic effort (3 low, 1 medium), researcher (2 Sonnet low, 1 Sonnet medium, 1 Haiku high), reviewer (3 Sonnet high, 1 Opus medium) and the Fable profile (2 remove, 1 repoint to Opus max, 1 keep). The tables behind all of this are in `docs/evaluations/2026-10-09-model-assignment-evidence.md`.

### Open questions (2026-10-09)
- Fable 5.1 scores below Opus 5.5 at xhigh on the Artificial Analysis index (53.2 versus 56.0) and on every row of Anthropic's own table, at 2.5x the token price. Nothing tests dense plan or spec review, so `reviewer-fable-xhigh` stays as an explicit-request profile pending the operator's call.
- Reviewer on Opus medium is the other open option (CodeRabbit: Opus caught 8 of 13 hard bugs at 66.7% precision, Sonnet 6 of 13 at 41.2%).

## Dropped models (2026-09-22)
- **Haiku 4.5** ($1/$5/$0.10): dropped. Nearest retirement floor of any model in the matrix (tentative, not sooner than 2026-10-15, three weeks out at drop time; platform.claude.com/docs/en/about-claude/model-deprecations, fetched 2026-09-22), 200K context versus 1M for the rest, no effort dial, and Sonnet 5 at `low` effort now covers the same rote work with an explicit effort setting. Cost for that rote work doubles per token, $1/$5 to $2/$10. Those reasons (200K context, no effort dial, near retirement) do not apply to Haiku 5.5, which took the mechanic profile back on 2026-10-09; see "Haiku 5.5" above.
- **Opus 5** ($5/$25/$0.50): dropped. Superseded by Opus 5.5 at a 20% lower input/output price, 60% lower cache reads, and Fable-level quality on most work (anthropic.com/claude-opus-5-5, quoted above). The `opus` alias already resolves to Opus 5.5 on the installed Claude Code 2.1.280 binary here; see the alias-lag caveat below. Deprecation page: Active, tentative retirement not sooner than 2027-07-24.

Other matrix models' tentative retirement floors, same deprecations page: Sonnet 5 2027-06-30, Fable 5.1 2027-09-01. The models overview (platform.claude.com/docs/en/models/overview, fetched 2026-10-03) gives Opus 5.5 not sooner than 2027-09-22 and Sonnet 5.5 not sooner than 2027-09-28.

## Pinned profiles (in the steward plugin `agents/` directory), delegate by subagent_type
- **steward:coder-opus-medium** (opus, medium): pure implementation with spec and tests (TDD), well-defined bug fixes, approved plans. See "Coder on Opus 5.5" above for why it moved off Sonnet 5 xhigh.
- **steward:deep-reasoner-opus-xhigh** (opus, xhigh): architecture, ambiguous design, cross-repo synthesis/plans, security review, high-stakes/subtle code review. Escalate to the main thread only if it falls short.
- **steward:reviewer-sonnet-high** (sonnet, high): everyday code review of a diff/PR.
- **steward:researcher-sonnet-low** (sonnet, low): thorough read-only investigation/search, plan inputs, findings docs.
- **steward:writer-sonnet-medium** (sonnet, medium): docs, README sections, substantive PR bodies, plain-language rewrites.
- **steward:mechanic-haiku-medium** (haiku, medium): single lookups, rote edits, file ops, running known commands, status collation, trivial PR one-liners. Returned to Haiku on 2026-10-09 (0.6.0), after running on Sonnet at low effort from 0.2.0, when Haiku 4.5 was dropped; see "Haiku 5.5" above.
- **steward:reviewer-fable-xhigh** (fable, xhigh): highest-stakes gap reviews of plans/specs; reserve for explicit operator requests, since Opus 5.5 is at Fable 5.1 level on most work for 40% of the price (cost: highest).

## Rubric (task to profile)
| Task | Profile |
|-|-|
| Pure coding, spec+tests (TDD) | steward:coder-opus-medium (steward:mechanic-haiku-medium if single trivial file) |
| Refactor / simplify | steward:coder-opus-medium (steward:mechanic-haiku-medium for small rote refactors) |
| Deep architecture / ambiguous design | steward:deep-reasoner-opus-xhigh, escalate to main thread if short |
| Cross-repo synthesis / plan writing | steward:deep-reasoner-opus-xhigh (or a coordinator plus sonnet workers if huge and splittable) |
| Read-only investigation / search | steward:researcher-sonnet-low (steward:mechanic-haiku-medium for one targeted lookup) |
| Code review | steward:reviewer-sonnet-high (steward:deep-reasoner-opus-xhigh for high-stakes/complex) |
| Security review | steward:deep-reasoner-opus-xhigh |
| Mechanical edits / file ops | steward:mechanic-haiku-medium |
| Docs / prose | steward:writer-sonnet-medium (steward:mechanic-haiku-medium for short) |
| PR-body drafting | steward:writer-sonnet-medium (steward:mechanic-haiku-medium for trivial diffs) |
| Status / collation | steward:mechanic-haiku-medium (steward:researcher-sonnet-low if reconciling conflicting reports) |

## Keep it inline on the main thread when
one dependent chain fits a single context with no splittable pieces; every step needs frontier judgment; the context is already resident in the orchestrator thread; it is the final synthesis/arbitration the orchestrator owns; or there is no cheap way to verify a delegate's output.

## Caveats to remember (do not overclaim)
- "Mythos-class, tier above Opus" is cited: anthropic.com/claude/fable says "Claude Fable 5.1 is a Mythos-level model." Primary-source validation on 2026-09-03 confirmed every other cited fact too (prices, 0.025x vs 0.1x cache reads, cost ranking, all four model ids then in the matrix, 1M/1M/1M/200K context windows, the Opus-at-half-price quote, the 47-55% savings figure). The 2026-09-22 revision re-verified pricing and deprecations against primary sources; see "Cost ranking", "Opus 5.5", and "Dropped models" above for those citations.
- Multi-model cost-savings percentages (the 40%, 20%, 60%, 30% figures above) are Anthropic's own comparisons against Opus 5, not guaranteed on any particular workload; measure before trusting a specific number.
- A bare `Agent(model=...)` call cannot set effort; to get a profile's effort you must delegate by subagent_type (see "Model and effort mechanics" below).
- Aliases checked 2026-10-03 on Claude Code 2.1.288 by running `claude -p --model <alias>` and reading the model id from the JSON output: `sonnet` ran `claude-sonnet-5-5`, `opus` ran `claude-opus-5-5`, `fable` ran `claude-fable-5-1`. Checked 2026-10-08 on Claude Code 2.1.295: `haiku` ran `claude-haiku-5-5`; the docs require 2.1.293 or later.
- Alias lag: code.claude.com/docs/en/model-config, as crawled 2026-09-22, still says `opus` resolves to Opus 4.8 and `sonnet` to Sonnet 4.6, both behind the current launches. The installed Claude Code 2.1.280 binary on this machine labels its Opus picker entry "Opus 5.5 - best for everyday, complex tasks" and its default-model string names Opus 5.5, so `opus` means Opus 5.5 here; check the binary, not just the docs page, before trusting an alias. The env vars `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_FABLE_MODEL` override what an alias resolves to, and a full id in agent frontmatter overrides the alias too.

# Model and effort mechanics

Operational reference for choosing and setting a subagent's model and reasoning effort. Effort is definition-only, so effort control requires an agent file. Pair with the routing knowledge base above to decide WHICH model and effort; this section is HOW to set it. Sources: code.claude.com/docs/en/sub-agents.md and code.claude.com/docs/en/model-config.md (confirmed 2026-09-03).

Caveat: Claude Code 2.1.295's Agent tool exposes a per-invocation `effort` parameter (seen in the tool schema 2026-10-08 and confirmed in run logs); the statements here that effort is definition-only predate it. Pinned profiles stay the rule, because the parameter is meant for explicitly requested effort levels.

## Frontmatter keys (agent file in the steward plugin `agents/` directory)
Same YAML block:
- `model`: alias `sonnet` | `opus` | `haiku` | `fable`, OR a full id (for example `claude-sonnet-5-5`), OR `inherit`. The mechanic profile uses `haiku` as of 0.6.0.
- `effort`: `low` | `medium` | `high` | `xhigh` | `max` (which levels are valid is model-dependent).

Minimal example:
```markdown
---
name: example-profile-name
description: <when to use>
model: claude-sonnet-5-5
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
