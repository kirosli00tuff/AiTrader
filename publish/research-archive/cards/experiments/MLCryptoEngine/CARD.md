# MLCryptoEngine
Group experiments. First commit 2026-07-30, last commit 2026-08-22, 91 commits in the original repo. Here `git log -- experiments/MLCryptoEngine/` shows 92: the extra one adds this card.

## Question
Can a machine learning model trained on tick-level order book data find short-horizon microstructure patterns in crypto that pay for the cost of trading them? The project later tested a register of strategy hypotheses against measured venue costs.

## Registered before testing
Not pre-registered as a whole. HYPOTHESES.md was first committed 2026-08-04, after H1 and H2 had closed. Later stages were pre-registered in commits before their data: the C.17 bars and the binding end condition in progress.md (f0e5bc7, 2026-08-06 07:02), the H6 census bars in progress.md (3a26c5e, 2026-08-06 12:18), and the D.1d replay policy in report.md (4ec20ee, 2026-08-11 22:46).

## Dates
First commit 2026-07-30. Last commit 2026-08-22.

## Data
Public WebSocket order book and trade feeds recorded from Kraken spot, Coinbase Advanced Trade and Hyperliquid perps. CME Micro Bitcoin futures depth bought from Databento. Free historical archives with per-file provenance. The data is not included in this archive.

## Method
Recorders captured raw feeds with nanosecond receive times, and a harness rebuilt and validated the books. Phase B built 42 features on event bars and fitted gradient boosted trees with purged cross-validation. Each hypothesis was judged on capture net of measured fees. The thin-perp census was scored against bars fixed in advance, then sent to an order-lifecycle fill simulation.

## Result
No deployable strategy (HYPOTHESES.md). H1 closed cost-bound: AUC 0.596 and 3.31 bps gross capture against an 80.00 bps maker round trip on Coinbase, a figure later superseded across more days (HYPOTHESES.md). At 100 ms the model scored AUC 0.9432 and captured 0.0291 bps per trade (docs/notes/h1-predictability-without-capturability.md). H2 on CME micro bitcoin closed signal-absent at AUC 0.501 (HYPOTHESES.md). C.17 failed all six bars on all forty registered cells, which ended the alpha search (HYPOTHESES.md). The H6 thin-perp positive did not survive the fill model. The corrected figures are PUMP -4.81 bps and MERL -4.35 bps (HYPOTHESES.md).

## Why it stopped
The alpha search ended by decision on 2026-08-06 under the end condition registered in f0e5bc7. H6 closed on 2026-08-12. A commit that day records that recording ends on 2026-08-13 and the register has no open items. The last commits wrote up H1 as a standalone note.

## One thing learned
A model can predict direction well and still capture almost nothing, so accuracy without capture, cost and confidence structure is half a result.
