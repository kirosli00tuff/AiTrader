# Week-Review Log

Automated daily digest of the paper-trading week, appended by `ops.weeklog` (read-only over the database). Each dated section below summarizes the prior 24 hours: trades, blocks and near-misses, council and cost, sleeves, sessions, health, and anomalies. Run `python -m ops.weeklog --summarize` at week end to append a week-summary with totals, the full near-miss table, the success-criteria checklist, and open calibration questions. The operator hands this one file to a reviewer for calibration analysis. Raw data stays in the database, unchanged. Timestamps show UTC and America/Vancouver. No keys or credentials appear here.

## 2026-07-16 daily digest

Window: 2026-07-15 03:42 UTC / 2026-07-14 08:42 PM PDT  ->  2026-07-16 03:42 UTC / 2026-07-15 08:42 PM PDT

### Trades
- Total rows 4 | entries 2 | closed 2 (win 1, loss 1, win rate 50.0%)
- PnL net $11.7869 | gross $11.818 | fees $0.031 | avg hold 0.12 h
- By sleeve: quant_core 4
- By symbol: QQQ 4
- Best: QQQ $12.5339 (momentum (trending)) at 2026-07-15 23:50 UTC / 2026-07-15 04:50 PM PDT
- Worst: QQQ $-0.747 (reversion (trending)) at 2026-07-15 23:35 UTC / 2026-07-15 04:35 PM PDT

### Blocks and near-misses
- risk_block by reason: (empty payload) 4, confidence below min_confidence_default 2
- Near-misses (confidence within 0.10 of the floor):

| ts (UTC / Vancouver) | symbol | confidence | min | agreement | tier | council_ran |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-16 02:15 UTC / 2026-07-15 07:15 PM PDT | ETH/USD | 0.6416 | 0.65 | 3 | council | yes |

### Council and cost
- Council calls 0 / budget 40 | est spend day $0.0 | week $0.0 (@ $0.04/call)
- Gate skips by reason: skip_cooldown 2, market_hours 2
- Provider verdicts: none | errors: none

### Sleeves
- Allocation: no sleeve snapshots in window (research_satellite ships off by default)
- Per-sleeve PnL: none | rebalance events 0
- Research theses: none (satellite off or no new theses)

### Sessions (crypto, tagged by UTC session window)
- Trades: none
- PnL: none

### Health
- Engine starts 8 | stops 3 | watchdog restarts 0 | kill-switch changes 0
- DNN challenger attempts 0 | RL fills 240 / 500 gate

### Anomalies
- 4 risk_block events with an empty payload (pre-dates the confidence-logging fix, or a miswrite)
