# solceil
Group solana. First commit 2026-09-04, last commit 2026-09-04, 1 commit.

## Question
Across the pools in the solattn archive that hold outcome candles, does a fixed-entry memecoin strategy that exits at 2x produce expectancy above zero net of cost (PREREGISTRATION.md)? The repo frames this as a ceiling, not a strategy test.

## Registered before testing
Not pre-registered. PREREGISTRATION.md, first committed 2026-09-04, still reads "Status: DRAFT. Locked on the commit that removes this line." No lock commit exists. No result was committed.

## Dates
First commit 2026-09-04. Last commit 2026-09-04.

## Data
The sealed solattn archive of GeckoTerminal birth rows and daily OHLCV candles, read across a hashed read-only boundary (README.md). The data is not included in this archive.

## Method
- Enter at the solattn entry anchor and walk daily bars forward to a 50 percent drawdown, the last bar or the horizon.
- Compute every metric twice, once with each day's high first and once with the low first, because daily bars hide the intraday order.
- Test exactly two exit rules: a full exit at 2x, and a half exit at 2x with a trailing stop on the rest.
- Charge 450 bps round trip. Use a day-clustered bootstrap with Sidak deflation across the four cells.

## Result
No result was committed. The only commit is the scaffold and the read-only boundary. The one measured count is coverage: 13,633 pools hold outcome candles against 518,524 birth rows, about 2.6 percent (README.md, DECISIONS.md ADR-005).

## Why it stopped
Not recorded.

## One thing learned `[KIROS: confirm]`
With daily bars, whether a pool hit 2x before it fell 50 percent cannot be decided within a day, so the result can only be a pair of bounds (DECISIONS.md ADR-003).
