# PMExperiment
Group experiments. First commit 2026-08-29, last commit 2026-09-02, 36 commits.

## Question
Are prediction-market prices mis-calibrated by enough to survive the costs a Canadian retail participant actually pays (README.md)?

## Registered before testing
REGISTRATION.md, first committed 2026-08-29 00:09:55 -0700 as an empty scaffold. Its Section 0 (gates, effect band, cost model, outcome blindness) was committed at 00:37:33 the same day. The first result commit, Stage A firing PENDING_ACCESS, came at 00:53:10. The operator prior slot was never filled, so the 5 to 8 percent prior is stated, not registered (README.md).

## Dates
First commit 2026-08-29. Last commit 2026-09-02.

## Data
Kalshi public market data and settlement history, read with 11 keyless probe requests and nothing retained (README.md). Polymarket was named as a second venue but received zero market-data requests (README.md). No price series was ever collected. The data is not included in this archive.

## Method
Two gates fire before any price is related to an outcome. The access gate checks that the data is reachable, deep enough and permitted. The power gate computes a minimum detectable effect from a bucket count and a dispersion only (REGISTRATION.md).
The power result is judged against a registered effect band of 0.02 to 0.08 (REGISTRATION.md). A fee-versus-edge band from Amendment 2 fires before the power gate (REGISTRATION.md).
Each claim about what a source permits must carry a quoted clause, an effective date and a fetch date, or it is recorded UNMEASURED (README.md, ADR-012).

## Result
Terminal on 2026-09-02: H1 is unmeasurable here, "not disproven, not unlikely" (README.md). Both venues closed on their own terms, and all three licence candidates failed (README.md). The power gate never fired, and no statistic relating a price to an outcome was ever computed (README.md).
The one number produced is BAND-OPEN: over entry prices of 91 to 99 cents held to resolution, an edge above 5.85 points is required, against a registered band top of 8.00 points (README.md). The README says this is a cost finding with no calibration measurement behind it, and not evidence that an edge exists (README.md).

## Why it stopped
The one route left, Kalshi Internal Use, needs an established legal entity. The operator does not hold one and decided not to create one (README.md). The README records this as a cost decision, not evidence about H1 (README.md).

## One thing learned `[KIROS: confirm]`
A claim about what a source permits needs a quoted clause, its effective date and its fetch date, or it is recorded as unmeasured.
