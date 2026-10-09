# OpenAI model assignment evidence, 2026-10-09

Evidence gathered to give each steward profile an OpenAI model and effort, for use through GitHub Copilot (see `docs/roadmap/copilot-port.md`). This file holds facts only. The matrix and its reasons are in `docs/roadmap/copilot-port.md`, section "Using OpenAI models". The Anthropic counterpart is `2026-10-09-model-assignment-evidence.md`.

Sources:

- **OpenAI** (vendor), fetched 2026-10-09: developers.openai.com/api/docs/pricing and /api/docs/models/<id>, openai.com/index/gpt-5-6/, and deploymentsafety.openai.com/gpt-6-1-sol.
- **GitHub** (vendor), fetched 2026-10-09: docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing, and the changelog post of 2026-09-22 (github.blog/changelog/2026-09-22-openais-gpt-6-sol-and-gpt-6-luna-now-available/).
- **Artificial Analysis (AA)**, Intelligence Index v4.3.2. The per-effort cells come through a relay, respan.ai/articles/gpt-6-sol-vs-luna-vs-astra (2026-09-30). The max-effort cells were confirmed on AA's own pages.
- **This machine's Copilot model catalog**, CLI runtime 1.0.94-3, read from a debug log on 2026-10-09.
- **A model panel** (roundtable), 2026-10-09.

## Candidates

|Model|Copilot ID|Kept|Why|
|-|-|-|-|
|GPT-6 Astra|`gpt-6-astra`|yes|Top of the GPT-6 family|
|GPT-6.1 Sol|`gpt-6.1-sol`|yes|Released 2026-09-29. Same $2/$10 as GPT-6 Sol with cheaper cache reads, and 4 AA points higher at max|
|GPT-6 Luna|`gpt-6-luna`|yes|Cheapest GPT-6 model|
|GPT-6 Sol|`gpt-6-sol`|no|Same price as 6.1 Sol (cache read $0.20 versus $0.10), AA max 48 versus 52|
|GPT-5.6 Sol|`gpt-5.6-sol`|no|$4/$20 (promotional through at least 2026-11-21). AA max is 5 below 6.1 Sol, at $1.99 per task versus $0.72|
|GPT-5.6 Terra|`gpt-5.6-terra`|no|$2/$12, the same input price as 6.1 Sol and more for output. OpenAI says it "roughly corresponds to the mini model tier"|
|GPT-5.6 Luna|`gpt-5.6-luna`|no|$0.20/$1.20, twice GPT-6 Luna on input and 2.4x on output. AA max costs $0.18 per task versus $0.07|
|GPT-5 mini|`gpt-5-mini`|no|$0.25/$2, 400K context, effort only low/medium/high. OpenAI points new low-latency work to GPT-5.6 Terra instead|
|GPT-5.3-Codex|`gpt-5.3-codex`|no|$1.75/$14, 400K context, effort low to xhigh. No current AA data. Newest coding-specific OpenAI model found|

## Prices, USD per million tokens

OpenAI pricing page and GitHub's Copilot pricing page give the same list prices.

|Model|Input|Cached input|Output|Over 272K input tokens|
|-|-|-|-|-|
|GPT-6 Astra|10|1.00|50|20 / 2.00 / 75|
|GPT-6.1 Sol|2|0.10|10|4 / 0.20 / 15|
|GPT-6 Luna|0.10|0.01|0.50|0.20 / 0.02 / 0.75|
|GPT-6 Sol|2|0.20|10|not found|
|GPT-5.6 Sol|4|0.40|20|8 / 0.80 / 30|
|GPT-5.6 Terra|2|0.20|12|not found|
|GPT-5.6 Luna|0.20|0.02|1.20|not found|
|GPT-5 mini|0.25|0.025|2|not found|
|GPT-5.3-Codex|1.75|0.175|14|not found|

- Once a prompt passes 272K input tokens, the whole request bills at the long-context rate.
- Reasoning tokens bill as output.
- GitHub's page says the GPT-5.6 and GPT-6 models also charge for cache writes. The respan.ai relay gives 1.25x the uncached input rate for Astra, 6.1 Sol and Luna ($12.50, $2.50, $0.125). The vendor amount was not captured.
- OpenAI Batch and Flex cost 50% of standard, and Fast costs 2x. Copilot does not expose these.

For comparison, from the Anthropic evidence: Haiku 5.5 is $0.10/$0.50, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20, and Fable 5.1 $10/$50.

## Context and effort levels

|Model|Context / max output|Effort (OpenAI docs)|Effort (this machine's Copilot catalog)|Default|
|-|-|-|-|-|
|GPT-6 Astra|1.05M / 128K|low to max|low to max|not stated|
|GPT-6.1 Sol|1.05M / 128K|low to max (no none)|none to max|medium|
|GPT-6 Luna|1.05M / 128K|none to max|none to max|medium|

Profiles avoid `none`, so the 6.1 Sol mismatch between OpenAI's docs and the Copilot catalog does not affect them.

## Artificial Analysis Intelligence Index by effort

Each cell is index score, then USD per index task. AA index v4.3.2 is the same version as the Anthropic table.

|Effort|GPT-6 Astra|GPT-6.1 Sol|GPT-6 Luna|
|-|-|-|-|
|max|53, 3.26|52, 0.72|37, 0.07|
|xhigh|52, 2.31|51, 0.39|34, 0.04|
|high|51, 1.73|50, 0.32|32, 0.03|
|medium|50, 1.54|48, 0.21|29, 0.02|
|low|46, 0.82|42, 0.13|21, 0.0045|
|none|n/a|n/a|18, 0.01|

Caveats:

- The max row was confirmed on AA's pages. The other rows come through the respan.ai relay.
- Other models at max: GPT-6 Sol 48 at $1.06, and GPT-5.6 Sol 47 at $1.99, both AA. GPT-5.6 Luna's max costs $0.18 per task; its score was not found.
- At max, 6.1 Sol uses about 38K output tokens per index task against Astra's 27K. That is why its per-task cost gap to Astra is narrower than the 5x rate-card gap.
- Luna at `none` costs more per task than at `low`, because it spends more output tokens.

The same scale for Claude, copied from the Anthropic evidence (AA v4.3.2, read 2026-10-08). As noted there, the Opus cells come through a beri.net relay and the Fable score through modelfatigue.news:

- Haiku 5.5 medium: 34, $0.05
- Sonnet 5.5 low: 36, $0.35
- Sonnet 5.5 medium: 41, $0.48
- Sonnet 5.5 high: 47, $0.88
- Sonnet 5.5 xhigh: 52, $2.01
- Opus 5.5 medium: 51, $1.34
- Opus 5.5 xhigh: 56, $3.46
- Opus 5.5 max: 58, $5.98
- Fable 5.1 xhigh: 53.2 (no cost cell)

## Other AA rows

|Row|GPT-6 Astra|GPT-6.1 Sol|GPT-6 Sol|GPT-6 Luna|
|-|-|-|-|-|
|Terminal-Bench 4.0, %, max|59 (xhigh: 60)|56|44|13|
|AutomationBench-AA, %, max|69 (xhigh: 67)|65|62|53|
|GDPval-AA v2.1, Elo, max|not found (xhigh: 1516)|1575|1508|1432|
|Coding Agent Index, max, Codex harness|62|60|57|41|

- Astra's max and xhigh cells come from different AA pages, an article and a comparison page. That is why Astra's Terminal-Bench cell reads higher at xhigh (60) than at max (59).
- Per-effort Terminal-Bench, AutomationBench and GDPval rows below max were not found.
- For scale, from the Anthropic evidence, AA Terminal-Bench 4.0:
  - Sonnet 5.5: 43.9 at high, 57.1 at xhigh, 63.6 at max.
  - Haiku 5.5: 32.8 at max.
- Coding Agent Index for Opus 5.5 in Claude Code: 66, effort not stated, against 57 for GPT-6 Sol in Codex, through thestackedhq.com (2026-09-28). That is a different harness from the Codex rows.
- OpenAI's GPT-5.6 page claims 80 on the AA Coding Agent Index for GPT-5.6 Sol at max. That cannot sit on the same scale as the rows above, which suggests a different index version. It is not used.

Latency (AA via respan.ai):

- Astra time to first token: about 3 s at low, 6.2 s at medium, 58 s at high, 315 s at max.
- 6.1 Sol follows nearly the same curve, starting from 2.1 s at low.
- Output speed: 6.1 Sol 59 to 66 tokens per second, Astra 44 to 51. Luna speed was not found.

## OpenAI's stated fit (quotes)

- GPT-6 Astra: "our most capable model for the most demanding work. Use it for complex reasoning, coding, computer use, research, and document creation."
- GPT-6.1 Sol: "near-Astra performance at a lower cost for complex coding, computer use, and professional work." The 6.1 Sol system card (2026-09-29) treats it as Critical in cybersecurity capability.
- GPT-6 Luna: "our most efficient model for focused, high-volume tasks."
- GitHub's positioning (changelog 2026-09-22): GPT-6 Sol is "balanced for interactive and agentic coding"; Luna is "lightweight, lowest-cost in the GPT-6 family".

## Copilot availability

- GPT-6 Sol is available on Pro+, Max, Business and Enterprise; GPT-6 Luna on Pro and above. Both are billed by usage (GitHub changelog, 2026-09-22). Plan availability for Astra and 6.1 Sol was not found.
- On Business and Enterprise, the admin model policy controls access.
- This machine's account, 2026-10-09, is on Copilot Free (`access_type_sku: free_limited_copilot`, from `gh api /copilot_internal/user`). The catalog marks `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5-mini` and `gpt-4.1` as enabled. `gpt-6-astra`, `gpt-6-sol` and `gpt-6.1-sol` show a disabled access toggle ("Enable access to the latest ... model from OpenAI") and list `restricted_to: pro_plus, business, enterprise, max`, so they cannot be enabled on Free. `gpt-6-luna` lists `free`. The monthly chat allowance is 200 credits, all used, resetting 2026-11-01 00:00 UTC.
- On the same day, three steward profiles bound to `gpt-5-mini` and `gpt-6-luna` were selected as bound, then each call failed with "402 You have exceeded your monthly quota".

## Other third-party data

- No code-review evaluation (bugs caught, precision) was found for any of these OpenAI models. Searched for CodeRabbit, Greptile, Graphite and Qodo.
- No writing or summarization quality evaluation was found.
- thestackedhq.com (2026-09-28) reports that GPT-6 Sol breaks previously working code in about 1 of 4 runs, and Opus 5.5 "rarely". No sample size is given. This is an anecdote, and it is about GPT-6 Sol, not 6.1 Sol.
- benchlm.ai lists SWE-bench Pro at 89.9% for Opus 5.5 and 64.6% for GPT-5.6 Sol. Who produced the numbers was not established, so they are not used.
- Not found anywhere:
  - a measured invented-finding rate for any OpenAI model;
  - cost per completed spec-coding task;
  - a same-harness head-to-head of 6.1 Sol or Astra against Opus 5.5.

## Local probe

Not run. The Anthropic evaluation ran each profile on this machine. That was not possible here, for two reasons: the Copilot Free account's monthly allowance is used up (402), and 6.1 Sol and Astra are not part of the Free plan. Every assignment below rests on published data and the panel vote, with no local run.

## Roundtable, 2026-10-09

Eight panelists responded: antigravity, codex, fireworks-deepseek, fireworks-ember, fireworks-glm5p3, fireworks-minimax, fireworks-qwen and openrouter-mimo. Each saw only the evidence above and voted on a draft:

- coder: 6.1 Sol high
- deep-reasoner: 6.1 Sol xhigh
- reviewer: 6.1 Sol medium
- researcher: 6.1 Sol low
- writer: 6.1 Sol medium
- mechanic: Luna high
- top-reviewer: Astra max

|Profile|Votes|
|-|-|
|coder|5 keep 6.1 Sol high, 3 move to 6.1 Sol xhigh|
|deep-reasoner|3 keep 6.1 Sol xhigh, 3 Astra xhigh, 2 Astra max|
|reviewer|8 of 8 keep 6.1 Sol medium|
|researcher|5 move to 6.1 Sol medium, 3 keep 6.1 Sol low|
|writer|8 of 8 keep 6.1 Sol medium|
|mechanic|4 keep Luna high, 2 Luna xhigh, 1 Luna medium, 1 6.1 Sol low|
|top-reviewer|8 of 8 keep Astra max|

Least-confident cell named by panelists: researcher 5, deep-reasoner 2, reviewer 1. Each named a measurement that would settle it:

- researcher: the invented-finding rate at 6.1 Sol low versus medium on known-answer investigations;
- deep-reasoner: seeded-bug recall and false positives, Astra against Opus 5.5 (one panelist), or a security and architecture review benchmark, Astra xhigh against 6.1 Sol (another);
- reviewer: defect recall and precision on real diffs.

Recurring caveats from the panel:

- Luna's 13% Terminal-Bench makes it risky for a profile that runs shell commands.
- No OpenAI configuration reaches Opus 5.5 xhigh's 56 on the index.
- The 272K long-context surcharge most affects the researcher.
