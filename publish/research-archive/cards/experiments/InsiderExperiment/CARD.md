# InsiderExperiment
Group experiments. First commit 2026-08-25, last commit 2026-08-25, 7 commits.

## Question
Do opportunistic and cluster insider purchases, disclosed on Form 4, predict positive abnormal returns that survive a measured cost band at achievable size? It is a net-of-cost survival test inside a liquid 500-name universe.

## Registered before testing
REGISTRATION.md, first committed 2026-08-25 18:34:56 -0700 with Section 0, the power and corpus gates. Sections 1 to 16 followed at 18:38. The first result commit, the Form 4 corpus, came at 18:47.

## Dates
First commit 2026-08-25. Last commit 2026-08-25.

## Data
SEC structured Form 345 data sets from EDGAR, 53 quarters from 2013q1 to 2026q1. Daily bars from AiTrader's local bar store, read-only. The data is not included in this archive.

## Method
A calendar-time portfolio holds every name inside its post-filing window, one return per day. The primary book is value-weighted by median dollar volume with a six-month hold. Stage A.1 built the corpus and computed a power gate, the minimum detectable effect, without reading any abnormal return. A minimum detectable effect above the registered floor of 40 bp per month fires BLOCKED. Stage B would have fitted a Carhart four-factor alpha.

## Result
The corpus gate passed: 4,585 qualifying events against a floor of 1,000, and 99.5 percent session coverage against 80 percent (REGISTRATION.md). The power gate fired BLOCKED. The primary minimum detectable effect was 49.35 bp per month (REGISTRATION.md). That sits above the decayed literature band of 30 to 40 bp gross and 13 to 35 bp net per month (REGISTRATION.md). The cause was weight concentration. The book held 71.9 names on average but behaved like 29.7 effective names (REGISTRATION.md). The equal-weighted secondary would have fired DEGRADED at 34.29 bp, but it was registered as non-verdict-bearing and was not promoted (REGISTRATION.md). The registration says this is not a null on the hypothesis, because no abnormal return was computed (REGISTRATION.md).

## Why it stopped
The registered primary design could not resolve the effect at achievable power. Stage B was never written and the repo closed on that finding on 2026-08-25 (REGISTRATION.md Section 17, progress.md).

## One thing learned `[KIROS: confirm]`
Weighting by a skewed quantity such as dollar volume can collapse a wide book into a narrow one, and that concentration alone can set the power of the test.
