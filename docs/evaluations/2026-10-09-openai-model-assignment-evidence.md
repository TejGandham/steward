# OpenAI model assignment evidence, 2026-10-09

Evidence gathered to give each steward profile an OpenAI model and effort, for use through GitHub Copilot and the Codex CLI/ChatGPT desktop plugin (see `docs/roadmap/copilot-port.md` and `docs/roadmap/codex-port.md`). This file separates published evidence from historical local observations and panel recommendations. The matrix and its reasons are in `docs/roadmap/copilot-port.md`, section "Using OpenAI models". The Anthropic counterpart is `2026-10-09-model-assignment-evidence.md`.

Sources:

- **OpenAI** (vendor), fetched 2026-10-09: developers.openai.com/api/docs/pricing and /api/docs/models/<id>, openai.com/index/gpt-5-6/, and deploymentsafety.openai.com/gpt-6-1-sol.
- **GitHub** (vendor), fetched 2026-10-09: docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing, and the changelog post of 2026-09-22 (github.blog/changelog/2026-09-22-openais-gpt-6-sol-and-gpt-6-luna-now-available/).
- **Artificial Analysis (AA)**, Intelligence Index v4.3.2. The original pass used respan.ai/articles/gpt-6-sol-vs-luna-vs-astra (2026-09-30). The verification now uses AA primary comparisons; conflicting snapshots are noted above.
- **This machine's Copilot model catalog**, CLI runtime 1.0.94-3, read from a debug log on 2026-10-09.
- **A model panel** (roundtable), 2026-10-09.

## Verification with Exa, 2026-10-09

Rechecked the named model pages, pricing, GitHub availability, AA comparisons and launch articles, the respan relay, and the Sol system card with Exa `/contents`. Discovery searches were paired with Parallel. Exa reported cached retrievals, so this is verification of the returned source snapshots, not a guarantee of live freshness. Some Parallel and locale-specific AA snapshots still show older values.

|Claims|Result|
|-|-|
|OpenAI prices, selected-model context and effort support|Confirmed against model pages and pricing. Added vendor cache-write prices and previously missing long-context rates below. API prices do not describe Codex/ChatGPT subscription allowances.|
|Astra and 6.1 Sol effort scores and task costs|Confirmed directly on AA; relay no longer needed for these cells.|
|Luna effort scores|Exa's English AA release comparison gives 38/35/33/30/22/18; the original relay and several Parallel snapshots give 37/34/32/29/21/18. Costs agree. The table below uses the English comparison returned by Exa and records the discrepancy; no reason for it was established.|
|GDPval and performance rows|Corrected Astra max to 1542, Sol max to 1487, Luna max to 1437 in the returned comparisons. Replaced latency estimates; per-effort benchmark rows are available.|
|Coding Agent Index|AA launch articles confirm Astra 62, Sol 57, Luna 41; 6.1 Sol max 60 is derived from AA's stated three-point gain over Sol. 6.1 Sol xhigh beats its max by three points on that index.|
|GitHub plan access|Confirmed Sol/Luna launch-plan availability. Account-specific catalog toggles, quota, reset and failed calls remain historical observations, not independently reproduced here.|
|Panel votes and original local probe|No raw transcripts or probe logs are committed. The vote counts and local account assertions cannot be independently verified from web sources. They are retained as reports from the original evaluation.|
|Claude comparison cells and anecdotes|The companion evidence contains the Claude figures. This OpenAI verification did not independently re-evaluate them. The anecdotes and unattributed SWE-bench numbers remain unverified and are not used to pin Codex profiles.|
|Claims that no evaluation exists|Restricted to what the original search found. AA does measure knowledge hallucination, but it does not establish Steward's invented-finding rate or code-review precision.|

Primary sources used in the verification:

- [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna). Excluded candidates were also checked on their `/api/docs/models/<id>` pages.
- [GitHub pricing](https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing) and [Sol/Luna availability](https://github.blog/changelog/2026-09-22-openais-gpt-6-sol-and-gpt-6-luna-now-available/).
- [AA Sol/Astra release comparison](https://artificialanalysis.ai/models/releases/comparisons/gpt-6-1-sol-vs-gpt-6-astra), [Sol/Luna release comparison](https://artificialanalysis.ai/models/releases/comparisons/gpt-6-1-sol-vs-gpt-6-luna), and [6.1 Sol/Sol comparison](https://artificialanalysis.ai/models/comparisons/gpt-6-1-sol-vs-gpt-6-sol).
- [AA Astra launch](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra), [6.1 Sol launch](https://artificialanalysis.ai/articles/gpt-6-1-sol-replaces-gpt-6-sol-after-just-7-days-with-near-astra-intelligence), and [Sol/Luna launch](https://artificialanalysis.ai/articles/gpt-6-sol-and-luna-push-the-cost-efficiency-frontier).
- [6.1 Sol system card](https://deploymentsafety.openai.com/gpt-6-1-sol). Its cybersecurity classification and September 29 publication are confirmed.

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
|GPT-6 Sol|2|0.20|10|4 / 0.40 / 15|
|GPT-5.6 Sol|4|0.40|20|8 / 0.80 / 30|
|GPT-5.6 Terra|2|0.20|12|4 / 0.40 / 18|
|GPT-5.6 Luna|0.20|0.02|1.20|0.40 / 0.04 / 1.80|
|GPT-5 mini|0.25|0.025|2|not found|
|GPT-5.3-Codex|1.75|0.175|14|not found|

- Once a prompt passes 272K input tokens, the whole request bills at the long-context rate.
- Reasoning tokens bill as output.
- OpenAI and GitHub publish cache-write rates of 1.25x uncached input: Astra $12.50, 6.1 Sol $2.50, Luna $0.125 per million short-context tokens. Long-context cache writes are $25, $5, and $0.25. OpenAI also lists Ultrafast pricing for Astra and 6.1 Sol; the original comparison did not cover it.
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
|max|53, 3.26|52, 0.72|38, 0.07|
|xhigh|52, 2.31|51, 0.39|35, 0.04|
|high|51, 1.73|50, 0.32|33, 0.03|
|medium|50, 1.54|48, 0.21|30, 0.02|
|low|46, 0.82|42, 0.13|22, 0.0045|
|none|n/a|n/a|18, 0.01|

Caveats:

- All effort rows above now come from primary AA English release comparisons returned by Exa. Luna differs from the original relay and some Parallel snapshots, as described in the verification table.
- Other models at max: GPT-6 Sol 48 at $1.06, and GPT-5.6 Sol 47 at $1.99, both AA. GPT-5.6 Luna's max costs $0.18 per task; the original pass did not find its score. AA's v4.3 announcement gives 38 at max.
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
|GDPval-AA v2.1, Elo, max|1542 (xhigh: 1516)|1575|1487|1437|
|Coding Agent Index, max, Codex harness|62|60|57|41|

- AA's primary comparison gives Astra Terminal-Bench 59.1% at max and 59.6% at xhigh. Higher effort does not guarantee a higher score.
- Per-effort Terminal-Bench, AutomationBench and GDPval rows are available in the primary release comparisons linked above. For example, 6.1 Sol high scores 51.5% on Terminal-Bench versus 48.0% at medium; Luna high scores 4.5%.
- AA reports 6.1 Sol xhigh three points above max on the Coding Agent Index. This is a different index from the Intelligence Index and supports evaluating coding effort on actual tasks.
- For scale, from the Anthropic evidence, AA Terminal-Bench 4.0:
  - Sonnet 5.5: 43.9 at high, 57.1 at xhigh, 63.6 at max.
  - Haiku 5.5: 32.8 at max.
- Coding Agent Index for Opus 5.5 in Claude Code: 66, effort not stated, against 57 for GPT-6 Sol in Codex, through thestackedhq.com (2026-09-28). That is a different harness from the Codex rows.
- OpenAI's GPT-5.6 page claims 80 on the AA Coding Agent Index for GPT-5.6 Sol at max. That cannot sit on the same scale as the rows above, which suggests a different index version. It is not used.

Latency (AA primary release comparison returned by Exa):

- Astra time to first token: 2.59 s low, 6.03 s medium, 83.11 s high, 216.48 s xhigh, 410.56 s max.
- 6.1 Sol: 2.85 s low, 6.27 s medium, 58.26 s high, 140.76 s xhigh, 314.47 s max.
- Output speed in that same snapshot: Sol 48 to 54 tokens/s, Astra 41 to 45. The Sol/Luna comparison gives Luna 112 to 128 tokens/s where reported.
- These are source snapshots, not service guarantees. Separate AA comparisons and the relay show different speed/latency measurements; do not merge their cells into a single curve.

## OpenAI's stated fit (quotes)

- GPT-6 Astra: "our most capable model for the most demanding work. Use it for complex reasoning, coding, computer use, research, and document creation."
- GPT-6.1 Sol: "near-Astra performance at a lower cost for complex coding, computer use, and professional work." The 6.1 Sol system card (2026-09-29) treats it as Critical in cybersecurity capability.
- GPT-6 Luna: "our most efficient model for focused, high-volume tasks."
- GitHub's positioning (changelog 2026-09-22): GPT-6 Sol is "balanced for interactive and agentic coding"; Luna is "lightweight, lowest-cost in the GPT-6 family".

## Copilot availability (published and historical local observations)

- GPT-6 Sol is available on Pro+, Max, Business and Enterprise; GPT-6 Luna on Pro and above. Both are billed by usage (GitHub changelog, 2026-09-22). Plan availability for Astra and 6.1 Sol was not found.
- On Business and Enterprise, the admin model policy controls access.
- This machine's account, 2026-10-09, is on Copilot Free (`access_type_sku: free_limited_copilot`, from `gh api /copilot_internal/user`). The catalog marks `gpt-6-luna`, `gpt-5.6-luna`, `gpt-5-mini` and `gpt-4.1` as enabled. `gpt-6-astra`, `gpt-6-sol` and `gpt-6.1-sol` show a disabled access toggle ("Enable access to the latest ... model from OpenAI") and list `restricted_to: pro_plus, business, enterprise, max`, so they cannot be enabled on Free. `gpt-6-luna` lists `free`. The monthly chat allowance is 200 credits, all used, resetting 2026-11-01 00:00 UTC.
- On the same day, three steward profiles bound to `gpt-5-mini` and `gpt-6-luna` were selected as bound, then each call failed with "402 You have exceeded your monthly quota".

## Other third-party data

- The original search found no targeted code-review evaluation (bugs caught, precision) for these OpenAI models. Searched for CodeRabbit, Greptile, Graphite and Qodo.
- The original search found no targeted writing or summarization quality evaluation. AA-Briefcase and GDPval assess broader professional deliverables; this is not a claim that no prose-related evaluation exists.
- thestackedhq.com (2026-09-28) reports that GPT-6 Sol breaks previously working code in about 1 of 4 runs, and Opus 5.5 "rarely". No sample size is given. This is an anecdote, and it is about GPT-6 Sol, not 6.1 Sol.
- benchlm.ai lists SWE-bench Pro at 89.9% for Opus 5.5 and 64.6% for GPT-5.6 Sol. Who produced the numbers was not established, so they are not used.
- Not established by the original search or this verification:
  - a measured invented-finding rate for any OpenAI model;
  - cost per completed spec-coding task;
  - a same-harness head-to-head of 6.1 Sol or Astra against Opus 5.5.

## Original Copilot local probe

Not run successfully in the original evaluation. The Anthropic evaluation ran each profile on this machine. That was not possible here, for two reasons: the Copilot Free account's monthly allowance is used up (402), and 6.1 Sol and Astra are not part of the Free plan. The original assignments rest on published data and the reported panel vote, with no successful Copilot task run. Codex packaging and smoke verification are documented separately in `docs/roadmap/codex-port.md`.

## Roundtable, 2026-10-09 (reported, not independently verified)

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
