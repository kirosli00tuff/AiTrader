# research-archive

These are the smaller experiments I ran from July to September 2026. They ran while
[llm-news-drift](https://github.com/kirosli00tuff/llm-news-drift) was collecting data, and most ended
before [PropExperiment](https://github.com/kirosli00tuff/PropExperiment) began on 2026-09-17. Those two
are my main projects. Each repo here keeps its own Git history, plus one card that sums it up.

## The experiments

Dates are first and last commit. Results are short. Each card gives the figures and the files they come from.

| Name | Dates | Question | Result | Card |
|---|---|---|---|---|
| MLCryptoEngine | 2026-07-30 to 08-22 | Can a model trained on order book data find short-term crypto patterns that pay for trading costs? | No strategy that could be deployed | [card](experiments/MLCryptoEngine/CARD.md) |
| solclear | 2026-08-11 to 08-22 | Can a score pick new Solana pools that avoid a rug, and does a basket of them beat holding SOL? | No. All 18 cleared pools lost 100 percent in 30 days | [card](solana/solclear/CARD.md) |
| solattn | 2026-08-16 to 08-28 | Does early social attention predict a new Solana pool's return? | Closed. The lift was negative and its interval included zero | [card](solana/solattn/CARD.md) |
| HFExperiment | 2026-08-23 to 08-28 | Does a five-name momentum book beat its universe after costs, and can a broker run it at micro size? | Blocked. The broker API refused every fractional order | [card](experiments/HFExperiment/CARD.md) |
| NPDExperiment | 2026-08-25 | Does an LLM rank next-window returns from anonymized numbers better than simple baselines? | Verdict "does not beat coin" | [card](experiments/NPDExperiment/CARD.md) |
| InsiderExperiment | 2026-08-25 | Do insider purchases on Form 4 predict returns that survive costs? | Blocked on its power gate | [card](experiments/InsiderExperiment/CARD.md) |
| NPLExperiment | 2026-08-26 to 09-21 | Do newly listed Hyperliquid perps fall by more than a short pays? | H1 failed. H3 and H4 blocked on venue rates | [card](experiments/NPLExperiment/CARD.md) |
| ETFExperiment | 2026-08-28 | Do spot Bitcoin ETF flows predict the next day's BTC return after costs? | Untestable at achievable power | [card](experiments/ETFExperiment/CARD.md) |
| ORBExperiment | 2026-08-28 to 08-29 | Does a breakout of the first 5-minute range predict a move to the close after costs? | Cost-bound. Measured slippage erased it | [card](experiments/ORBExperiment/CARD.md) |
| PMExperiment | 2026-08-29 to 09-02 | Are prediction market prices wrong by more than a Canadian retail trader pays? | Unmeasurable here. No price series was collected | [card](experiments/PMExperiment/CARD.md) |
| retail-power-limits | 2026-08-29 | In four earlier tests, was the limit the effect or the sample's power to detect it? | A note on four cases. It computes no new statistic | [card](experiments/retail-power-limits/CARD.md) |
| VRPExperiment | 2026-08-29 to 08-30 | Do options charge more volatility than BTC and ETH deliver, and can I harvest it with about $1,000? | Premium measured. Blocked at the venue, one route left open | [card](experiments/VRPExperiment/CARD.md) |
| program-audit | 2026-08-29 to 09-13 | A neutral audit: did the program close too early or claim too much? | Incomplete. Two of its three agents stopped at 10 of 13 repos | [card](experiments/program-audit/CARD.md) |
| solcopy | 2026-09-02 | Could any wallet-following test on Solana pools tell a lift from zero? | Blocked on power | [card](solana/solcopy/CARD.md) |
| MBTExperiment | 2026-09-02 to 09-12 | Does that open route, CME Micro Bitcoin options through IBKR Canada, fit the margin and cost limits? | Blocked at the venue. Margin on the hedge leg alone was 1.6 times the limit | [card](experiments/MBTExperiment/CARD.md) |
| solceil | 2026-09-04 | As a ceiling, does a memecoin strategy that exits at 2x make money after costs? | No result. The draft was never locked | [card](solana/solceil/CARD.md) |
| soltool | 2026-09-05 to 09-10 | A read-only screener for a Solana token, from seven public sources | A tool, not an experiment | [card](solana/soltool/CARD.md) |
| solback | 2026-09-10 | A backtest harness for Solana tokens that move to an AMM pool | First counts only, exploratory | [card](solana/solback/CARD.md) |

The solana group is included pending my check. [KIROS: confirm]

## What came of it

None of these found an edge that survives costs and that I could trade. Some were read and came out
negative. Most of the rest stopped on costs, power or venue access before an effect could be read.
VRPExperiment measured a premium, but the venue blocked
it, and MBTExperiment closed the one route it left open.

Some things carried into PropExperiment. Its files say so:

- Its rules engine borrows HFExperiment's intent and gate pattern (PropExperiment docs/DECISIONS.md).
- Its Stage D.1 prompt weighs ORBExperiment's slippage result (docs/prompts/STAGE_D.1.md).
- It shares MLCryptoEngine's data vendor account and reads that repo's spend ledger (docs/ACCESS.md).
- Its Stage A.1 prompt names program-audit as the pattern for work split across agents that check each
  other (docs/prompts/STAGE_A.1.md).

llm-news-drift names these repos only in a decision about which repos are public (its docs/DECISIONS.md,
V7). Its pre-registration was written on 2026-07-27, before any of them began.

## How AI was used here

This comes from the commit history only.

- 11 of the 18 repos have a CLAUDE.md file in their history. That is the instruction file Claude Code reads.
- 141 commits carry a Co-Authored-By line that names Claude, and a Claude-Session line. Claude Opus 5
  (1M context) appears on 57 of them, in InsiderExperiment, MBTExperiment, NPLExperiment, PMExperiment,
  solclear, solcopy and soltool. Claude Fable 5.1 appears on 83, of which 82 are in program-audit. Claude
  Fable 5 appears on 1, in NPLExperiment.
- program-audit ran as three agents. Agent A and Agent B each audited the program and Agent C refereed
  them (its findings/METHOD.md).
- The other commits name no AI tool. That does not show they were written without one. MLCryptoEngine,
  for example, has a CLAUDE.md and no such line. No commit message names any other coding assistant.
- NPDExperiment called an OpenAI model as the thing under test, not as a coding tool.

The way I work now is in llm-news-drift's
[docs/AI_USE.md](https://github.com/kirosli00tuff/llm-news-drift/blob/main/docs/AI_USE.md). I set that up
later. Do not read it back into these repos.

## Layout

- `experiments/<name>/` and `solana/<name>/`: each repo's files and full history, with its CARD.md.
- `EXCLUDE.txt`: the path rules used to build this archive.
- `README.md`: this file.

Each history was rewritten with git-filter-repo to move it into its folder and remove excluded paths, so
commit ids differ from the original repos. One mailmap line gives every commit the same author name and
address. Personal contact details and one broker paper account ID were replaced in files and messages.

Data files are not here. EXCLUDE.txt removes databases, model files, archives, data and log folders,
recorded vendor replies used as test fixtures, program-audit's work/ folder, key and env files, saved
web pages and vendor price tables. It also removes any JSON shaped like a Solana keypair and any non-code file over 1 MB. Tests that
read a removed fixture will not find it. The tests in this archive were not run when it was built.

Two removals show up in the cards:

- MBTExperiment's CME margin rate export, docs/evidence/cme_outright_rates_crypto_20260903.csv, is
  removed from the whole history. It is exchange data, and nothing shows I may share it.
- soltool's docs/gui.md links a screenshot, docs/screenshots/result-full.png, that the build removed as a
  non-code file over 1 MB. That image link is broken here.

## Licence

I have not chosen a licence yet. Until I do, the default applies: all rights reserved. [KIROS: confirm]

These repos quote some third-party text. That text belongs to its owners. A licence I pick later will not
cover it.

## Tests

I ran every project's tests on 2026-11-07 in a fresh clone of this archive. Each test run used a clean environment with no keys and no network. Installs used the project's lock file where it has one. Tests that need removed data fail here. I did not fix them.

- solattn: `pytest`, 216 passed.
- solback: `pytest`, 12 passed.
- solceil: `pytest`, 4 passed, 4 failed. The failures read the solattn candle archive, which is not here.
- solclear: `pytest`, 96 passed, 3 failed. The failures read data/snapshots files, which are removed.
- solcopy: `pytest`, 221 passed, 1 failed, 2 skipped. The failure expects the removed .env.example.
- soltool: `pytest --continue-on-collection-errors`, 1746 passed, 306 failed, 1 error, 1 skipped, 12 live tests deselected. Plain `pytest` stops at the error. The failures read removed tests/fixtures files, plus the removed screenshot. The 12 live tests call vendor APIs and were not run.
- ETFExperiment: `pytest`, 241 passed, 1 skipped.
- HFExperiment: `pytest`, 149 passed, 9 failed. The failures come from the replaced paper account ID. The tests pin that ID, and the replacement text is not a valid account.
- InsiderExperiment: `pytest`, 101 passed, 4 skipped. The skips need data stores that are not here.
- MBTExperiment: `pytest`, 180 passed, 1 failed. The failure expects the removed .env.example.
- MLCryptoEngine: `pytest`, 494 passed, 21 failed, 2 skipped. The failures read removed recorded exchange messages in tests/fixtures. The desktop app has no tests.
- NPDExperiment: `pytest`, 114 passed, 1 skipped.
- NPLExperiment: `pytest`, 446 passed, 1 skipped.
- ORBExperiment: `pytest`, 418 passed, 1 skipped.
- PMExperiment: `pytest`, 110 passed, 1 failed. The failure reads the removed .env.example.
- VRPExperiment: `pytest`, 50 passed.
- retail-power-limits: `pytest`, 112 passed.
- program-audit: `python3 tools/test_orchestrator_lock.py`, 6 passed.
