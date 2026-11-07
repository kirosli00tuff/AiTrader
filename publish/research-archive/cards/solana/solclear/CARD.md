# solclear
Group solana. First commit 2026-08-11, last commit 2026-08-22, 28 commits.

## Question
Given a Solana liquidity pool at launch, will it avoid a hard rug, meaning near-total liquidity removal (README.md)? The question the project existed to reach was whether a basket of cleared pools beats holding SOL (FINDINGS.md section 1).

## Registered before testing
Bars were registered stage by stage in progress.md, first committed 2026-08-11. The Stage E outcome study was registered in progress.md and DECISIONS.md in commit 8a49833 on 2026-08-13, before the Stage E result commit f0244eb the same day. The scorer itself was measured earlier in MLCryptoEngine, against bars that the source says were registered there (FINDINGS.md).

## Dates
First commit 2026-08-11. Last commit 2026-08-22.

## Data
SolRPDS rug labels, Helius RPC and enhanced transactions, GoPlus token security, RugCheck reports, and Wayback captures of a new-pools feed and of per-coin pages (README.md, FINDINGS.md). The data is not included in this archive.

## Method
- Score a pool from its launch-window state with a clearance model trained on SolRPDS labels.
- Retrieve historical launch windows with a depth-independent method (Method B).
- Pass every metered vendor call through a credit gate that prices it before sending.
- Stage E: build a 77-pool cohort, score it, and compare cleared pools with SOL, cash and not-cleared pools at 30 and 90 days, net of 450 bps.

## Result
- On a 2024 holdout the scorer reached 0.984 precision and 0.538 recall for avoiding a hard rug (n = 194). This was measured in MLCryptoEngine (README.md, FINDINGS.md).
- The honest versus soft-rug boundary was measured absent: 0.574 precision against a 0.500 base rate (n = 194) (README.md).
- Stage E answer: no. Every one of the 18 cleared pools realized -100 percent net at 30 days, and all 4 with a 90-day horizon did the same (FINDINGS.md).
- Every comparison sat at p_raw = 1.0 in the adverse direction. The underpowered rule fired (18 cleared < 20), so no significance is claimed (FINDINGS.md).
- Birth-ordered pools died at 97.5 percent within 30 days (n = 40), against 18.75 percent for attention-crawled pools (n = 16) (FINDINGS.md).
- Stage G: only 43 of 60 anchor comparisons were in band against a 90 percent bar, so the anchors are DISTINCT. The confirming test was re-priced at 4,695,489 weighted credits against a 745,915 threshold, NO-GO (README.md, FINDINGS.md).

## Why it stopped
Stage E answered the main question in the negative, and the project closed as a documented public artifact on 2026-08-14. Stage G on 2026-08-22 answered two follow-up questions and re-closed it (DECISIONS.md ADR-015, progress.md).

## One thing learned `[KIROS: confirm]`
Building a memecoin cohort from archived or crawled pages manufactures survivorship, by 60 to 79 points on this cohort (FINDINGS.md section 2).
