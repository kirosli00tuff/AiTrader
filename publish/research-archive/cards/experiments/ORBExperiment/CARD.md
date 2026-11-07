# ORBExperiment
Group experiments. First commit 2026-08-28, last commit 2026-08-29, 59 commits.

## Question
Among US common stocks with high opening relative volume, does a breakout of the first 5-minute range predict continuation to the close? It must do so by enough to clear modeled commissions, fees, borrow and slippage, out of sample from 2023-01-03 (README.md).

## Registered before testing
REGISTRATION.md, first committed 2026-08-28 19:10:01 -0700 (Section 0). Sections 1 to 14 followed within two minutes. The first measurement commit, the vendor access table, came at 19:18:07 the same evening. The rescue criterion that closed H1 (Amendment 24) was committed on 2026-08-29 at 20:13, before the slippage measurement it judged at 20:41 (HYPOTHESES.md). No outcome value was ever read.

## Dates
First commit 2026-08-28. Last commit 2026-08-29.

## Data
One-minute bars from Alpaca (primary bar vendor) and Massive (reference vendor, the only source of delisting dates), reached with paper-account market-data keys that grant no trading (README.md). The data is not included in this archive.

## Method
Each session at 09:35 New York time, rank US common stocks by first-5-minute volume over its trailing 14-session median and take the top 20, after price, volume and ATR filters. Delisted names are included (REGISTRATION.md).
Go long on the first trade through the opening-range high, short through the low, stop at the opposite extreme, exit at the close (REGISTRATION.md).
Two co-primary tests must both pass: E1, a deflated Sharpe ratio of at least 1.00 on the holdout, and E2, mean net PnL per trade with a lower bound above zero (REGISTRATION.md).
Stage A measured access, bar integrity, costs and power only.

## Result
H1 closed as `cost-bound` (HYPOTHESES.md). The measured slippage band gave a pessimistic-minus-central shift of 0.467065 USD per share against a central mean of 0.040386 (README.md). The pessimistic-cost mean was -0.426679, and E2 power and joint power were 0.000000 (README.md). GO would have needed a 21.89-fold smaller shift (README.md). The band carried from an ETF understated the entry and close pessimistic ends by 8.87 and 13.05 times (README.md). E1 stayed powered at 0.832450 (README.md). The README says this is a finding about this design, not a finding that the effect does not exist (README.md). H1b, the same rule with a higher price floor, is registered and not opened (README.md).

## Why it stopped
H1 closed on cost before the bar-integrity re-pull, due 2026-09-12, could run (progress.md). The last commit is the close-out of that pass.

## One thing learned `[KIROS: confirm]`
The doubt registered first, that realistic slippage could exceed the whole gross edge, is the one that closed the hypothesis, for the reason it gave.
