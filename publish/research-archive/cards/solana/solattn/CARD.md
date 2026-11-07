# solattn
Group solana. First commit 2026-08-16, last commit 2026-08-28, 20 commits.

## Question
Does social attention velocity in the first 24 hours after a Solana AMM pool is born predict its forward return? The test compares the top attention quintile with the birth-ordered cohort's own base rate, net of a 300 to 600 bps cost band, at 1, 3 and 7 days (README.md).

## Registered before testing
REGISTRATION.md, first committed 2026-08-16 (commit 0c32387). The first result commit is 2026-08-28 (778fd86), so the registration came first. Seven dated amendments follow in the same file.

## Dates
First commit 2026-08-16. Last commit 2026-08-28. Collection ran 2026-08-16 to 2026-08-29 (README.md).

## Data
New Solana pools and daily OHLCV candles from the GeckoTerminal keyless API. Mentions from Bluesky (Jetstream), Farcaster (a public hub) and public Telegram channels (MTProto). A Coinbase SOL-USD daily benchmark (docs/ACCESS.md). The data is not included in this archive.

## Method
- Enumerate every new Solana AMM pool in birth order, with no attention input in the enumeration.
- Count mentions per source in fixed windows after birth. Match by exact mint address or cashtag. An ambiguous match is attributed to nobody.
- Enter at the daily close two days after birth. Measure returns at 1, 3 and 7 days, with a registered death floor and cost band.
- Compare the top quintile with the cohort using a day-clustered bootstrap, Sidak deflation and registered kill criteria.

## Result
- The primary trial measured a lift of -1.0779 net of 450 bps, with a 95 percent interval of [-3.3354, +0.0204]. The interval includes zero, so kill criterion K1 fired and the hypothesis is closed (FINDINGS.md).
- The cohort held 12,798 AMM pools, 2,107 of them measurable at the entry anchor, with a Q5 cell of 412 (FINDINGS.md).
- All 120 computable cells carry a negative point lift (FINDINGS.md).
- 10,689 of 12,798 pools (83.5 percent) printed no daily candle at the entry anchor (FINDINGS.md).
- 58,097 ingested messages gave 77 exact mint matches (0.13 percent). 26,610 (45.8 percent) were ambiguous (FINDINGS.md).
- The enumeration missed 28 to 35 percent of births (FINDINGS.md).
- The source's verdict: "The instrument worked. The answer is no." (FINDINGS.md)

## Why it stopped
K1 closed the hypothesis on the primary trial. Collection was then stopped by operator decision on 2026-08-29, before the 30-day horizon matured. Those 40 cells were never analysed (progress.md, REGISTRATION.md Amendment 7).

## One thing learned `[KIROS: confirm]`
A study of memecoin returns that does not report the share of pools with no entry mark reports only on the survivors (FINDINGS.md).
