# solcopy
Group solana. First commit 2026-09-02, last commit 2026-09-02, 11 commits.

## Question
On a birth-ordered Solana population, is return dispersion small enough, and are there enough independent clusters, for any basket-level wallet-following test to tell a lift from zero net of a registered cost band (README.md)? The project asked this power question before any alpha question.

## Registered before testing
REGISTRATION.md, first committed 2026-09-02 at 17:48 (commit 70a6ab7), with sections 1 to 10 added at 17:51 (8b8a660). The first result commit, the dispersion store and corpus gate, came at 17:55 (09e4d45). So the registration came first.

## Dates
First commit 2026-09-02. Last commit 2026-09-02.

## Data
The solattn archive of birth-ordered Solana AMM pools and their outcomes, read across a hashed read-only boundary (REGISTRATION.md). No network request was made (README.md). The data is not included in this archive.

## Method
- Rebuild solattn's committed Stage B figures from the raw archive as a known-answer corpus gate.
- Compute the pooled within-day return dispersion at each horizon.
- Turn dispersion and the count of birth-day clusters into a minimum detectable lift for each registered statistic.
- Compare the primary's minimum detectable lift with a registered BLOCKED ceiling of 2,000 bps and a GO bar of 450 bps.

## Result
- Corpus gate: CORPUS-GO. All ten registered comparisons reproduced from the raw archive (FINDINGS.md).
- Power gate: BLOCKED. The minimum detectable lift on the primary at 7 days is 73,913.9 bps against the 2,000 bps ceiling (FINDINGS.md, reports/stage_a1/power.json).
- This rests on 12,798 AMM pools, 2,107 measurable, over 3 birth-day clusters, at basket size 250 and pooled dispersion 49.03 (FINDINGS.md).
- The 450 bps GO bar would need 24,008 birth-day clusters, which is 65.7 years of forward collection (FINDINGS.md).
- A winsorized mean and the death-rate difference reach GO in 4 clusters. Neither is promoted, as the registration forbids it (FINDINGS.md).

## Why it stopped
The registered power gate fired BLOCKED in Stage A.1. Stage B was never written. The project closed on 2026-09-02 (README.md, FINDINGS.md).

## One thing learned `[KIROS: confirm]`
Detectability is a second moment and needs no mean, so the power arithmetic can run on day one, before any collection (README.md).
