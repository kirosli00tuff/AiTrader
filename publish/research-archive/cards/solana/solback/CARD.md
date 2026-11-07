# solback
Group solana. First commit 2026-09-10, last commit 2026-09-10, 3 commits.

## Question
A backtest harness for Solana tokens that migrate from a launch curve to an AMM pool (README.md). Five draft hypotheses ask whether time to graduation, buyer concentration, deployer history, a post-dump entry or a relaunched name predict outcomes after migration (HYPOTHESES.md).

## Registered before testing
Not pre-registered. HYPOTHESES.md, first committed 2026-09-10, is marked DRAFT with nothing locked. The Phase Zero memo records that a graduation rate was read before the hypotheses were locked (artifacts/PHASE_ZERO_MEMO.md). notes/DECOMP_C0.md locks one exploratory endpoint and its sample before collection, but no C0 result was committed.

## Dates
First commit 2026-09-10. Last commit 2026-09-10.

## Data
The sealed solattn archive of GeckoTerminal birth rows and daily candles, read across a hashed read-only boundary. The C0 step planned Helius enhanced-transaction calls (notes/DECOMP_C0.md). The data is not included in this archive.

## Method
- Read the solattn archive without writing to it, with content hashes taken before and after.
- Pair each launch-curve pool with its later AMM pool to build a migration census.
- Measure the time from curve pool to AMM pool and the candle coverage by birth day.
- Rate each draft hypothesis as testable on free data, testable only on paid data, or not testable.

## Result
- 11,790 migration pairs over 14 days, from 518,524 birth rows and 349,219 mints (artifacts/PHASE_ZERO_MEMO.md).
- Median time from curve pool to AMM pool was 2.27 minutes, and 91.3 percent took under an hour (artifacts/PHASE_ZERO_MEMO.md).
- Candle coverage was 23.0 percent overall. The memo reads this as a collection stop, not survival filtering (artifacts/PHASE_ZERO_MEMO.md).
- Exploratory only: a repeat launch whose earlier same-key mint graduated reached an AMM pool in 16.2 to 34.5 percent of cases, against a baseline of 2.57 to 3.99 percent. The cleanest cell, key size exactly 2, gave 34.54 percent on n=663 against 3.09 percent on n=15,937 (artifacts/PHASE_ZERO_MEMO.md). The memo calls these numbers hypothesis-generating only.
- Hypotheses A and C were rated testable on free data. B and D need paid trade-level data (artifacts/PHASE_ZERO_MEMO.md).

## Why it stopped
Not recorded. The history ends on a commit that locks the C0 sample before collection.

## One thing learned `[KIROS: confirm]`
Once an outcome is read before the hypotheses are locked, that data window is spent for confirmation, and a test needs held-out data (artifacts/PHASE_ZERO_MEMO.md).
