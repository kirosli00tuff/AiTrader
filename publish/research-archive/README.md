# research-archive

These are the smaller experiments I ran from July to September 2026, while
[llm-news-drift](https://github.com/kirosli00tuff/llm-news-drift) collected data. Most ended before
[PropExperiment](https://github.com/kirosli00tuff/PropExperiment) began on 2026-09-17. Those two are my
main projects. Each repo here keeps its Git history and a card that sums it up.

## The experiments

Dates are first and last commit. Each card gives the figures and the files they come from.

| Card | Dates | Question | Result |
|---|---|---|---|
| [MLCryptoEngine](experiments/MLCryptoEngine/CARD.md) | 2026-07-30 to 08-22 | Can order book models find crypto patterns that pay for costs? | No deployable strategy |
| [HFExperiment](experiments/HFExperiment/CARD.md) | 2026-08-23 to 08-28 | Does a five-name momentum book beat its universe after costs? | Blocked. The broker refused every fractional order |
| [NPDExperiment](experiments/NPDExperiment/CARD.md) | 2026-08-25 | Does an LLM ranking of anonymized numbers beat simple baselines? | "Does not beat coin" |
| [InsiderExperiment](experiments/InsiderExperiment/CARD.md) | 2026-08-25 | Do Form 4 insider purchases predict returns after costs? | Blocked on its power gate |
| [NPLExperiment](experiments/NPLExperiment/CARD.md) | 2026-08-26 to 09-21 | Do new Hyperliquid perps fall by more than a short pays? | H1 failed. H3 and H4 blocked on venue rates |
| [ETFExperiment](experiments/ETFExperiment/CARD.md) | 2026-08-28 | Do spot Bitcoin ETF flows predict next-day BTC returns after costs? | Untestable at achievable power |
| [ORBExperiment](experiments/ORBExperiment/CARD.md) | 2026-08-28 to 08-29 | Does a 5-minute opening range breakout predict the close after costs? | Cost-bound. Measured slippage erased it |
| [PMExperiment](experiments/PMExperiment/CARD.md) | 2026-08-29 to 09-02 | Are prediction market prices wrong by more than a Canadian retail trader pays? | Unmeasurable. No price series was collected |
| [retail-power-limits](experiments/retail-power-limits/CARD.md) | 2026-08-29 | In four earlier tests, was the limit the effect or the power? | A note. No new statistic |
| [VRPExperiment](experiments/VRPExperiment/CARD.md) | 2026-08-29 to 08-30 | Do BTC and ETH options overprice volatility, and can $1,000 harvest it? | Premium measured. Venue blocked, one route left open |
| [program-audit](experiments/program-audit/CARD.md) | 2026-08-29 to 09-13 | Did the program close too early or claim too much? | Incomplete. Two agents stopped at 10 of 13 repos |
| [MBTExperiment](experiments/MBTExperiment/CARD.md) | 2026-09-02 to 09-12 | Do CME Micro Bitcoin options via IBKR Canada, the open route, fit the margin and cost limits? | Blocked at the venue. Hedge-leg margin alone was 1.6 times the limit |

## What came of it

None of these found an edge that survives costs and that I could trade. Some were read and came out
negative. Most of the rest stopped on costs, power or venue access before an effect could be
read. PropExperiment's docs name what it took from here: HFExperiment's gate pattern, ORBExperiment's slippage result, MLCryptoEngine's vendor
account and spend ledger, and program-audit's cross-checking agents. llm-news-drift's pre-registration
(2026-07-27) predates all of these.

## How AI was used here

From the commit history: 8 of the 12 repos have a CLAUDE.md, the file Claude Code reads. 121 commits name
Claude in a Co-Authored-By line and carry a Claude-Session line: Claude Opus 5 (1M context) on 39, Claude
Fable 5.1 on 81, all in program-audit, and Claude Fable 5 on 1. Other commits name no AI tool, which does
not show none was used. How I work now is in llm-news-drift's
[docs/AI_USE.md](https://github.com/kirosli00tuff/llm-news-drift/blob/main/docs/AI_USE.md), set up later.
Do not read it back into these repos.

## Layout and removals

`experiments/<name>/` holds each repo's files, history and CARD.md. Histories were rewritten with
git-filter-repo, so commit ids differ from the original repos. One mailmap line sets one author name and
address. My full name became my handle, kirosli00tuff. Personal contact details and one broker paper
account ID were also replaced, in files and messages.

`EXCLUDE.txt` lists what the build removed: databases, model files, archives, data and log folders,
recorded vendor replies, program-audit's work/ folder and its findings on two of the repos it audited, key
and env files, saved web pages, vendor price tables, bulk vendor reference data, wallet keypair files and
non-code files over 1 MB. That includes .env.example, so setup steps that copy it do not run as written.
Two removals appear in the cards: MBTExperiment's CME margin export and ORBExperiment's delisted-ticker
listing. Nothing shows I may share either.

## Licence

I have not chosen a licence yet. Until I do, the default applies: all rights reserved.

These repos quote some third-party text. That text belongs to its owners. A licence I pick later will not
cover it.

## Tests

On 2026-11-07 I ran each project's tests in a fresh clone, with no keys, no network and lock files where
present. All use `pytest`, except program-audit's `python3 tools/test_orchestrator_lock.py`. Tests that
need removed or replaced data fail. I did not fix them.

- No failures: ETFExperiment 241 passed, 1 skipped. NPDExperiment 114 passed, 1 skipped. NPLExperiment
  446 passed, 1 skipped. ORBExperiment 418 passed, 1 skipped. InsiderExperiment 101 passed, 4 skipped
  (data stores not here). VRPExperiment 50, retail-power-limits 112, program-audit 6 passed.
- Failures: MBTExperiment 180 passed, 1 failed, and PMExperiment 110 passed, 1 failed (.env.example).
  HFExperiment 149 passed, 9 failed (the replaced paper account ID). MLCryptoEngine 494 passed, 21
  failed, 2 skipped (removed recorded exchange messages).
