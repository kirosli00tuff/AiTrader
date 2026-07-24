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

## 2026-07-24 PRE-FLIGHT BASELINE AND SUCCESS CRITERIA (written before any week data exists)

### The state the week starts from

- Code: HEAD 66103ae at capture; the pre-flight commit recording this baseline lands immediately after and is the week's code state.
- Config: config/default_config.yaml sha256 1c7de026ff3af3a4 (prefix), ships profile swing. Active profile: active_quant, resolved from the control-file lever (`strategy_profile` in .control/controls.json), printed by the startup banner as `active_quant [control file]`.
- Equity: $100,000.00 paper. Lifetime realized PnL across 247 closed rows: +$420.87. Today (2026-07-24) realized: -$8.40 (the two deliberate rehydrated stop exits).
- Open positions: ZERO. ETH/USD and SPY exited through the rehydrated exit path at 07:45:00Z (stop fills, -$6.42 and -$1.99, matching the pre-restart projections). BTC-USD, PRES-2028-YES, FED-CUT-Q3 reconciled out through the journalled event path at 07:32:23Z. No position_unmanageable condition remains at startup.
- Universe: 8 of 8 declared core tradeable, all WARM on 300 bars each (BTC/USD, ETH/USD, SOL/USD, SPY, QQQ, AAPL, MSFT, NVDA), every indicator warm, no unserviceable symbol.
- Safety spine: kill switch untripped on every venue, manual-resume armed. approval_state live_enabled=0, manual_confirmation=0; all four independent live blocks confirmed in config (live off everywhere, Alpaca has no live adapter). alpaca consecutive_losses = 2 of max 3 (the two stop exits): ONE more consecutive loss triggers the Level 1 cooldown, which would be the limit working, not a defect. Trades today 0 of 10. RL gate: counter reads 243 of 500, with the standing caveat that most counted fills are offline synthetic-feed fills; real-path native exits total 6 lifetime.
- Database: 30.3 MB; events 5,077, trades 253, bars 95,549, entry_decision 12, signals 12,925.
- Suites at capture: pytest 914, ctest 30 of 30, vitest 136, tsc and build clean.
- Spend: council estimate $0.056/round everywhere; ceilings $5/day and $100/month council, discovery 12 Stage-C calls/day with 4 reserved for the equity session, research 6/day at $0.056; combined worst case ~$97/month, measured production run-rate ~$0.73/day.
- Watchdog: NOT running at capture (the operator starts it with the week). It restarts on a down stack, a degraded bridge, and live feed substitution past the startup grace; holds instead of looping; notifies on kill trips and universe degradation; every restart now journals watchdog_restart and every stop names its caller.

### What the week must show to count as a PASS

1. STABILITY. The engine runs the full window with every stop attributed (an engine_stop_requested or process_stop event pairing each continuous_stop) and the heartbeat gap never exceeding a few loop intervals except across attributed restarts. No fd regression (bridge fd flat), no fabrication guard firing, no unmanaged position: any position past its stop must show the health banner AND exit on the next closed bar.
2. TRADE AND SIGNAL RATE, with its uncertainty stated up front: two OPPOSING entry-rate changes just landed (the fast-tier denominator fix makes confidence reachable, projecting roughly 6 clearing candidates/day from recorded history; the now-real live volume filter rejects 42-63 percent of measurable bars). The honest expectation is therefore a WIDE band: 0 to ~8 native entries/day, entry_decision recording ~2,000-2,700 rows/day regardless. A LOW TRADE COUNT IS NOT ATTRIBUTABLE to either change individually and must not be read as a verdict on either: attribution needs the entry_decision joins against outcomes, which is what the week accumulates.
3. SPEND. Council + discovery + research spend at or under the measured run rate's order of magnitude and strictly under the ceilings; the equity session records Stage-C calls on at least some weekdays (the reservation working).
4. DATA. Every live bar carries venue or absent volume (never invented), decision records accumulate with rejections included, and the daily digests append cleanly.

### What ends the run EARLY (and what does not)

- ENDS THE RUN: an unattributable stop (the exact 2026-07-21 failure), a fabrication guard trip, a position stranded unmanaged past its stop without exiting on the next bar, database corruption, or spend crossing a hard ceiling unexpectedly.
- DOES NOT END THE RUN: a Level 1 halt doing its job. A daily-loss halt or a kill trip on a genuine loss breach is the safety spine working: record it, wait for the reset or the manual resume, and continue. The week measures the system as built, limits included.
