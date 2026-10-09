# Model assignment evidence, 2026-10-09

Evidence gathered for the re-evaluation of every steward profile after Claude Haiku 5.5 launched on 2026-10-07. This file holds facts only. The decision and its reasons are in `skills/delegating/routing.md`.

Sources: Anthropic pages fetched 2026-10-08 (anthropic.com/claude-haiku-5-5, /claude-sonnet-5-5, /claude-opus-5-5; platform.claude.com/docs/en/about-claude/pricing, /models/overview, /about-claude/models/choosing-a-model, /build-with-claude/effort, /about-claude/model-deprecations), Artificial Analysis (artificialanalysis.ai, Intelligence Index v4.3.2, read 2026-10-08), code.claude.com/docs/en/model-config and /sub-agents, and a local probe run on Claude Code 2.1.295 on 2026-10-08 and 2026-10-09.

## Assignments before this evaluation
| Profile | Model | Effort | Work |
|-|-|-|-|
| coder | Opus 5.5 | medium | Implement a clear spec test-first, fix well-defined bugs |
| deep-reasoner | Opus 5.5 | xhigh | Architecture, ambiguous design, security review, subtle review |
| reviewer | Sonnet 5.5 | high | Everyday review of a diff or PR |
| researcher | Sonnet 5.5 | low | Read-only multi-step investigation; findings feed later work |
| writer | Sonnet 5.5 | medium | Docs, PR bodies, plain-language rewrites |
| mechanic | Sonnet 5.5 | low | Single lookups, rote edits, file moves, running a known command |
| reviewer-fable | Fable 5.1 | xhigh | Top-stakes plan and spec review, only on explicit operator request |

## Prices, USD per million tokens (Anthropic pricing page)
| Model | Input | Output | Cache read | 5-minute cache write |
|-|-|-|-|-|
| Haiku 5.5, prompt up to 100K tokens | 0.10 | 0.50 | 0.01 | 0.125 |
| Haiku 5.5, prompt over 100K tokens | 0.50 | 2.50 | 0.05 | 0.625 |
| Sonnet 5.5 | 2 | 10 | 0.10 | 2.50 |
| Opus 5.5 | 4 | 20 | 0.20 | 5 |
| Fable 5.1 | 10 | 50 | 0.25 | 12.50 |

Sonnet 5.5 cache reads were cut from $0.20 to $0.10 on 2026-10-07. Anthropic's wording on the Haiku threshold is "a prompt of over 100,000 tokens pays higher prices"; no page says whether cached tokens count toward the 100K. All four models have a 1M context window and accept effort low, medium, high, xhigh and max. In Claude Code the default effort is medium for Haiku 5.5, Sonnet 5.5 and Opus 5.5.

## Artificial Analysis Intelligence Index by effort (independent)
Each cell is index score, then cost per index task in USD.
| Effort | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 | Fable 5.1 |
|-|-|-|-|-|
| low | 29, 0.02 | 36, 0.35 | 42, 0.55 | 46.8 |
| medium | 34, 0.05 | 41, 0.48 | 51, 1.34 | 48.9 |
| high | 38, 0.08 | 47, 0.88 | 54, 1.82 | 51.2 |
| xhigh | 41, 0.12 | 52, 2.01 | 56, 3.46 | 53.2 |
| max | 43, 0.21 | 56, 5.46 | 58, 5.98 | 53.4 |

Caveats: Haiku costs exclude the over-100K price card. Opus figures come through a relay of AA's pages (beri.net, 2026-09-29) and predate the Sonnet cache-read cut. Fable per-effort scores come through modelfatigue.news (2026-10-04); AA reports Fable costs more per task than Opus at every effort.

Other AA rows, same source:
| Row | Haiku low / medium / high / xhigh / max | Sonnet low / medium / high / xhigh / max |
|-|-|-|
| Terminal-Bench 4.0, % | 12.6 / 15.2 / 21.7 / 29.3 / 32.8 | 20.7 / 29.8 / 43.9 / 57.1 / 63.6 |
| AutomationBench, % | 22.9 / 28.6 / 33.7 / 36.0 / 35.4 | 49.4 / 54.9 / 59.4 / 65.5 / 71.8 |
| GDPval-AA, Elo | 1125 / 1277 / 1420 / 1511 / 1618 | 1179 / 1324 / 1551 / 1730 / 1839 |
| Seconds per index task | 62 / 131 / 202 / 295 / 427 | 93 / 140 / 245 / 458 / 917 |

AA notes Haiku's AutomationBench score is understated by an over-refusal bug. AA-Omniscience (factual recall without tools): Haiku 3 to 11 across efforts, Sonnet 19 to 32.

## Anthropic's own benchmark tables (vendor)
| Benchmark | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 | Fable 5.1 |
|-|-|-|-|-|
| Terminal-Bench 4.0, % | 39.2 | 70.6 | 66.4 (xhigh) | 55.8 |
| FrontierCode 1.1, % | 46.4 | 52.1 (xhigh) | 54.4 | 50.3 |
| CursorBench 4.0, % | not given | 55.5 | 57.8 | 51.8 |
| GDPval-AA v2.1, Elo | 1620 | 1844 | 1846 | 1735 |
| Humanity's Last Exam with tools, % | 57.4 | 64.5 | 67.7 | 65.6 |

Anthropic relayed per-effort Terminal-Bench points (via sharkly.ai, 2026-09-29): Opus medium 57.6%, Sonnet high 43.0%, Sonnet xhigh 61.5%.

## Anthropic's stated fit (quotes)
- Haiku 5.5: "best suited to more narrowly scoped tasks ... like compaction, summarization, or subagent work." "Sonnet 5.5 and Opus 5.5 remain better choices for complex agentic coding tasks."
- Haiku 5.5 effort: "Start with `medium` for most work, including agentic coding. Use `low` ... for chat, short tool tasks, and simple, high-volume requests. In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at `low`. Use `high` for knowledge work, longer agent tasks, and strict instruction following. Use `xhigh` or `max` only where your evals show a quality gain, and compare them with Claude Sonnet 5.5."
- Sonnet 5.5: "strongest at well-scoped everyday tasks, fixing bugs, and creating polished documents." "Opus 5.5 remains clearly stronger at complex, open-ended work requiring sustained judgment." Effort: "For agentic coding and multistep tool use, start with `medium` for well-specified tasks and move to `high` for harder or longer ones."
- Opus 5.5 and Fable 5.1: "start with Claude Opus 5.5 for most workloads. Use Claude Fable 5.1 for demanding reasoning and long-horizon agentic work, or when your evals on Claude Opus 5.5 at higher effort still fall short." Also: "In our own use, the gap between Opus 5.5 and Claude Fable 5.1 is narrower than these scores suggest."

## Other independent or third-party data
- Code review, CodeRabbit's own pipeline, 13 hard known-bug cases: Sonnet 5.5 caught 6 at 41.2% precision; Opus 5.5 caught 8 at 66.7% precision in its standard configuration and 10 at 52.0% in its max configuration. These are pipeline configurations, not single API effort levels. No Haiku 5.5 code-review result was found.
- Agent Arena (via remio.ai, 2026-09-29): Fable 5.1 max first at 13.84, Opus 5.5 high second at 12.15.
- The New Stack, 15 coding runs each: Fable 5.1 15 of 15, Opus 5.5 13 of 15 at 22% lower cost; Fable took a shortcut to pass one test.
- Field reports on Haiku 5.5 as a coding subagent are anecdotes and split: one developer reverted to another small model after more errors, another reported the opposite.
- Not found anywhere: a measured error, early-stop or invented-finding rate for Haiku 5.5; cost per completed task for spec-driven coding on Sonnet versus Opus; any test of dense plan or spec review on Fable versus Opus.

## Local probe (this machine, Claude Code 2.1.295, small sample)
Each run used the real steward profile as a subagent, with the model and effort overridden per run. Model and effort were confirmed from each run's log. Cost is input-side only (input, cache read, cache write); the logs do not record final output tokens. A bare subagent prompt in this harness is about 55K tokens before any work.

Mechanic task: rename a profile across 8 files, change three effort values, run the test suite, report.
| Model, effort | Runs | Correct | Stray edits | Cost per run, USD | Seconds |
|-|-|-|-|-|-|
| Haiku low | 2 | 2 | 0 | 0.011 | 21 |
| Haiku medium | 2 | 2 | 0 | 0.011 to 0.013 | 22 to 38 |
| Haiku high | 1 | 1 | 0 | 0.011 | 24 |
| Sonnet low (current) | 1 | 1 | 0 | 0.136 | 22 |

All six runs produced a byte-identical diff. No run went over a 100K prompt.

Researcher task: read-only question with a 13-item answer key (which files and tests a profile move touches, which tests would fail and why).
| Model, effort | Both failing tests found with cause | Subtle item found (other profiles' descriptions) | False claims | Cost, USD | Seconds | Requests over 100K |
|-|-|-|-|-|-|-|
| Haiku medium | yes | no | 0 | 0.066 | 123 | 6 of 12 |
| Haiku high | yes, and verified by running the suite in a scratch copy | yes | 0 | 0.135 | 195 | 15 of 24 |
| Sonnet low (current) | yes | no | 0 | 0.239 | 47 | 0 of 7 |

Separately, three Sonnet low research runs on the web that same day each ended between 107K and 130K prompt tokens.

Writer task: a 120 to 220 word PR body for a real commit, under the operator's prose rules.
| Model, effort | Prose checks | Accuracy against the diff | Cost, USD | Seconds |
|-|-|-|-|-|
| Haiku high | pass | accurate; omits two fallback paths and the note that the PR gate still blocks; says seven tests, lists six | 0.011 | 22 |
| Sonnet medium (current) | pass | accurate and complete | 0.200 | 17 |

One run per cell for the researcher and writer tasks. These are smoke-level results, not rates.

## Harness facts
- Claude Code 2.1.293 and later resolve the `haiku` alias to Haiku 5.5 on the Anthropic API. Subagent frontmatter `effort` is honored for Haiku 5.5 at all five levels.
- pi 1.0.2, installed here, has no `claude-haiku-5-5` in its model registry; pi 1.1.0 adds `anthropic/claude-haiku-5-5`. The local `amorphic` proxy serves the model, but pi's `amorphic` provider entry in `~/.pi/agent/models.json` does not list it yet.

## Roundtable, 2026-10-09
Four panelists responded (pi-seated DeepSeek, Qwen, MiniMax, Ember); GLM and MiMo returned nothing.
| Profile | Votes |
|-|-|
| mechanic, model | 4 of 4 move to Haiku 5.5 |
| mechanic, effort | 3 low, 1 medium |
| coder | 4 of 4 keep Opus medium |
| deep-reasoner | 4 of 4 keep Opus xhigh |
| writer | 4 of 4 keep Sonnet medium |
| researcher | 2 Sonnet low, 1 Sonnet medium, 1 Haiku high |
| reviewer | 3 Sonnet high, 1 Opus medium |
| reviewer-fable | 2 remove, 1 repoint to Opus max, 1 keep |

The decision taken from this evidence is recorded in `skills/delegating/routing.md`.
