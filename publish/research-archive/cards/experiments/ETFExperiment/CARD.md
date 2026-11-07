# ETFExperiment
Group experiments. First commit 2026-08-28, last commit 2026-08-28, 28 commits.

## Question
Do US spot Bitcoin ETF net flow prints predict the next day's BTC return, out of sample, by enough to clear a round trip on Hyperliquid perps? The test uses only values published before the entry time.

## Registered before testing
REGISTRATION.md, first committed 2026-08-28 01:07:59 -0700. Its commit message says it was written before any network call. The first measurement commit came at 13:04 the same day. HYPOTHESES.md followed at 01:11.

## Dates
First commit 2026-08-28. Last commit 2026-08-28.

## Data
Daily ETF flow tables from Farside Investors, with SoSoValue as a cross-check only. Archived copies of the flow page from the Wayback Machine. Hyperliquid BTC perp hourly candles and funding. The data is not included in this archive.

## Method
The signal is the aggregate net flow of five named ETFs, as printed before the entry time. Go long above +100 million USD, short below -100 million USD, flat otherwise, and exit 24 hours later. Net return counts price, funding and a registered round-trip cost. Two co-primary tests: a permutation test on rank correlation and an economic test. Stage A measured only access, publication lag, revision and sample size. It never read an outcome value.

## Result
Closed as untestable at achievable power (HYPOTHESES.md). Only 11 of 333 printed out-of-sample days had an archive capture that served a value before the entry time, against a registered bar of 0.60 (report.md). The archive crawl rate was 0.316 captures per calendar day (report.md). Forward collection added 20.8 admissible days per month. That projects 163 days at the 2027-03-31 deadline against a governing minimum of 300 (report.md). Even the smallest minimum on record, 237, falls short by 74 days (report.md). The report says nothing here is evidence about whether flow prints predict the next day's return (report.md).

## Why it stopped
The sample could not arrive before the registered deadline. The operator closed H1 on that finding on 2026-08-28, before the outcome map fully fired. The last commit disarmed the remaining collector (report.md, Postscript).

## One thing learned `[KIROS: confirm]`
An archive index tells you a capture exists, but only fetching the capture tells you whether it holds a value, and only the second answers the registered question.
