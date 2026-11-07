# NPLExperiment
Group experiments. First commit 2026-08-26, last commit 2026-09-21, 41 commits in the original repo. Here `git log -- experiments/NPLExperiment/` shows 42: the extra one adds this card.

## Question
Do newly listed Hyperliquid perpetuals drift down over 30 and 90 days by more than a short pays in funding and fees? This founding hypothesis is H1. Later entries in the same register (H2 to H5) tested narrower versions of it.

## Registered before testing
REGISTRATION.md, first committed 2026-08-26 17:54:38 -0700. Its commit message and header say it was registered before any network call. The first result commit, the single Stage B read, came on 2026-08-27. HYPOTHESES.md and the later files under registrations/ were committed after the H1 read. The README says the H2 amendments were made before any H2 pair outcome existed.

## Dates
First commit 2026-08-26. Last commit 2026-09-21.

## Data
The Hyperliquid public info endpoint, reached with a keyless request: listings, daily closes and funding for the main dex and the HIP-3 builder dexes (docs/ACCESS.md). Ledgers, census files and sealed outcomes were kept in a local data folder outside Git (README.md). The data is not included in this archive.

## Method
Every perp listing is an event, ordered by listing date, with no attention or performance input. Entry is the second daily close. The outcome is the net short return: minus the price return, plus the funding a short receives, minus a registered cost band, at 30 days (primary) and 90 days.
Three co-primary tests must all pass. P1 is an exact lower bound of at least 0.60 on the share of profitable shorts. P2 is a sign test that the median move clears -15 percent net. P3 is a sign test against funding-matched controls aged 180 days or more (README.md).
Delisted perps stay in the sample, cut at their last served close (README.md). The verdict came from one sealed read at alpha_adj 0.016952 per test (report.md).

## Result
H1 fired FAIL on its sealed read (report.md). P1: 197 of 312 shorts were profitable (63.14%), with a lower bound of 0.5707 against the 0.60 bar (report.md). P2: 111 of 312 fell at least 15 percent net (35.58%), p = 1.000 (report.md). P3 passed: 114 of 175 young perps did worse than their controls (65.14%), p = 3.767e-05 (report.md). The verdict held at every registered cost band (report.md). Over 30 days the average short earned about +2.2 percent net, mostly from funding rather than price (report.md).
H3 and H4 fired BLOCKED on measured venue rates (HYPOTHESES.md). H2 had 55 of 63 events paired and zero reads taken when the project ended (DECISIONS.md). H5 was never read (DECISIONS.md).

## Why it stopped
H1 closed on its FAIL read, and its collectors were disarmed (report.md). The operator then cancelled the whole project on 2026-09-21 to move attention to other work. The record calls this a scope decision, not a verdict, and says no hypothesis was disproven by it (DECISIONS.md, the second ADR-035).

## One thing learned
The market priced most of the decline of new listings into funding, and the drift left over was too small for the registered trade.
