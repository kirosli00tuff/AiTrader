# Project Progress

Status tracker for AiTrader. Read at the start of each session. Update at the end of each session.

## Current State

The C++ safety spine builds clean and runs the offline paper loop (`ctest` 5/5). The real LLM council is merged (Opus 4.8, GPT-5.5, Gemini 3.1 Pro) with a free Gemini Flash gate, prompt caching, and cost controls (budget, per-symbol cooldown, token cap, neutral skip). The native strategy layer (momentum + reversion + regime detector, closed-bar eval, native ATR exits) is in; the adaptive tuner learns from real closed-trade PnL (≥30-trade gate); the `dnn_advisory` factor has a real-data walk-forward training pipeline with gated promotion; Coinbase replaces Binance; free-first whale feeds (ClankApp + SEC EDGAR) are wired live-OFF by default; security hardening (loopback bridge, credential masking, pre-commit secrets hook, pinned deps) landed. A separate `rl_advisory` PPO module (gym env, real-fill training gate, walk-forward eval, `/score/rl` bridge endpoint) is built but **shipped OFF** — it never touches the ensemble until an operator toggles `rl_enabled` past the `rl_min_real_fills` gate. Two council cost cuts (risk pre-check + equities market-hours skip) short-circuit doomed/after-hours setups before any provider spend. Council/whale live paths stay behind config/env flags and the bridge. Live trading disabled by default. Next up: prove paper-loop stability, then the GUI overhaul (see Next Up).

## Stable and Working

- RiskGate: 14 hard checks, final authority on every order, tested
- Kill switch: latching, manual resume required, tested
- Live-trading gate: four independent blocks, live unreachable by design
- Config validation: throws on unsafe values at load
- Secret handling: encrypted store, env fallback, nothing committed
- Alpaca paper: real HTTP for market data and paper orders
- SQLite DAO: 14 tables, WAL mode, append-only audit log
- Dash UI: paper tab, live tab locked, advanced tab, accounts tab
- Real LLM council: 3 providers, Flash gate, offline mock fallback, 29 tests

## In Progress

- None active. The "close open flags + RL advisory (shipped off) + council cost cuts" prompt is complete (2026-07-05): every follow-up flag from the 12-task prompt is cleared, `rl_advisory` (PPO, shipped off) is built, and the two council cost cuts (risk pre-check + market-hours) are in. See "Open Flags / Follow-ups" and RETURN.md.

## Not Started

- Live-approval workflow end to end (`try_enable_live` still never called by design)
- Real (disabled-by-default) live adapters for Coinbase + IBKR
- Training the RL advisory policy: the `rl_advisory` PPO module is built but shipped OFF and untrained (activates only past the `rl_min_real_fills` gate, default 500 real fills; no synthetic-data path). Supervised `dnn_advisory` is the only Layer-3 signal serving today.
- Frontend rebuild / GUI overhaul (see Next Up + CONTEXT.md GUI Plan)

## Next Up

1. **Paper-loop stability.** Run the offline paper loop continuously and confirm it stays stable over time — no drift, no leaks, tuner behaving sanely once ≥30 closed trades accumulate, DB growing cleanly. This is the gate before any new capability.
2. **GUI overhaul.** Once the loop is proven stable, rebuild the dashboard/control surface (per-layer toggles with safety always on, per-model council toggles, champion/challenger + RL enable controls behind their gates, weight sliders grouped by layer, regime override, budget dial) — see the GUI Plan in CONTEXT.md.

## Known Issues and Caveats

- Advisory factor *scores* on the default (no-`--bridge`) path are deterministic C++ mocks; the real LLM/dnn/whale scores engage only with `--bridge` + the bridge server up. The learning signal the tuner consumes is real (closed-trade PnL), but the verdicts feeding it out-of-box are stand-ins.
- Shipped `dnn_advisory` champion is still synthetic-trained; `rl_advisory` is untrained (real-fill gate unmet) and shipped off. The real-data trainer now DOES train a challenger once enough history exists (verified against a synthetic-regime run: 47,900 samples, `challenger_recorded`).
- Native fills now flow offline via `feed_mode: synthetic_regimes` (or `replay`) + `clock_mode: simulated` — the flat random-walk still produces ~zero native trades by design. **Residual:** in a long synthetic run the adaptive tuner drives the `rule_based` weight toward zero (0.17 → ~2.7e-11), so native entries plateau after ~30 fills / ~2 simulated days. That is enough to exercise the ≥30-trade tuner gate and `train_real`, but sustained fill generation would want a minimum-weight floor for the native factor (or running training with `adaptive_weight_updates_enabled: false`). Follow-up, not a safety issue.

## Open Flags / Follow-ups

Cleared 2026-07-05 (all verified this session): venv created and full `pytest tests/ -q` green (**124 passed**); `python -m ml_factor.train_real` run against the demo DB (refuses cleanly with `insufficient_real_data`, synthetic champion retained); real SEC EDGAR 13F fixture recorded (ClankApp left SYNTHETIC — host DNS-unreachable); residual doc-consistency sweep done (`docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`, `DNN_RL_DESIGN.md`→`DNN_ADVISORY_DESIGN.md`) + AUDIT honest-state refresh; bars OHLCV storage landed (was "no historical price data persisted").

**Paper-loop-stability flag CLEARED 2026-07-05 (feed work):** the offline loop now generates real native fills. Config-tunable strategy thresholds, a deterministic synthetic-regime feed, a historical replay mode, and a simulated clock landed; a verified synthetic run produced 31 closed native trades (momentum + reversion, ATR exits) and `train_real` trained a real-data challenger (47,900 samples). Replaced by the tuner-throttle residual noted in Known Issues above (native entries plateau after ~30 fills as the tuner de-weights `rule_based`).

Still open (not defects — known limits):

- Advisory factor scores run through real Python services only with `--bridge`; the default path uses deterministic C++ mocks.
- Whale live-fetch parsers are verified against one recorded SEC 13F payload only; the other feeds' assumed shapes are still unverified against live responses (and live is off by default behind `WHALE_LIVE_ENABLED` / `SEC_EDGAR_ENABLED`).
- Live-approval workflow not wired end to end (`try_enable_live` never called). Safe, but incomplete.
- Real LLM providers untested against live keys; `rl_advisory` untrained (real-fill gate unmet); `dnn_advisory` still shipping the synthetic champion until enough real labelled samples exist.

New flags from the feed-work session (2026-07-05, `369b6a6`):

- **`rule_based` now carries the native signal's conviction on ALL native runs, not just synthetic** — a real decision-path change (previously the gate's confidence/edge came only from advisory factors). It is what makes fills flow, but with a real LLM council + trained `dnn_advisory` the native setup then contributes to BOTH direction/sizing AND the gate's confidence/edge (mild double-counting). Confirm this is intended before any live-adjacent use. This is the one that matters for future live work.
- **"≥30 closed trades per factor" (Task-5 wording) is not met for momentum:** the real tuner gate is ≥30 TOTAL closed (`learning/adapt_gate.hpp`), and EMA20/100 crossovers are rare (3 fired in the verified run). Total-closed is what the tuner uses; the per-factor phrasing is not satisfied.
- **Cut B (equities market-hours council skip) still uses real wall-clock** (`util::us_equity_market_open()`) even under `clock_mode: simulated`. Benign offline (mock factor values don't depend on the skip), but inconsistent — under simulated time the skip should key off the simulated timestamp.
- **Replay uses a synthetic sequential epoch for council-cooldown timing** (`base + index*bar_seconds`), not the true historical epoch. The per-day trade cap correctly uses the real historical `ts`; only the cooldown spacing is approximate.

## Session Log

Newest entries at top. One entry per session. Format: date, model used, what changed, what is stable, what is next.

### 2026-07-05 (Opus 4.8) — offline loop becomes a real training environment

- **Made the offline paper loop generate real native fills** so it can train the tuner / `dnn_advisory` / (eventually) RL. RiskGate logic, the live-trading gate, and the adaptive limit-weakening invariant untouched; live trading stays off; Alpaca remains paper + market-data only.
- **Config-tunable entry thresholds:** the last hardcoded strategy literal (reversion volume multiple) moved to `strategy.vol_multiple`; the ADX/rvol/ATR/EMA/Bollinger/RSI thresholds were already config-backed. Added load-time validation (periods ≥1, bb_std/vol_multiple >0).
- **Volatility-aware synthetic feed** (`market_data/synthetic_feed.*`, `feed_mode: synthetic_regimes`): a deterministic warmup→uptrend→range→downtrend generator that crosses the ADX + realized-vol thresholds so BOTH momentum and mean-reversion enter. Verified standalone: 3 momentum + 17 reversion signals over 1200 bars under seed 42.
- **Historical replay** (`feed_mode: replay`): drives the loop from real `bars`-table rows in chronological order through the same closed-bar path; configurable date range + `replay_speed`; refuses loudly (run the Alpaca backfill first) when the range is empty — never silently zero. Added `Storage::bars_in_range`.
- **Simulated clock** (`clock_mode: simulated`): bar time advances internally (`util::epoch_to_iso8601`) so finite/synthetic runs actually close bars; real-clock stays default for the continuous loop.
- **Wired the native signal into the ensemble as `rule_based`** so a genuine technical setup's conviction reaches the RiskGate (previously confidence/edge came only from mock advisory factors, which vetoed every native entry on the 0.02 edge floor). No gate logic or threshold changed; no risk value loosened.
- **End-to-end verification (Task 5):** synthetic run closed 48,000 bars, fired 31 native entries (momentum 3 / reversion 28), closed 31 trades (30 win / 1 loss; ATR target 30, stop 1) all under the native whitelist, tuner active past its ≥30 gate, and `python -m ml_factor.train_real` trained a real-data challenger (`challenger_recorded`, 47,900 samples, Sharpe 0.98). Residual: entries plateau after ~30 fills as the tuner de-weights `rule_based` (see Known Issues).
- **Startup transparency:** prints active feed mode, clock mode, and resolved strategy thresholds.
- **Tests:** C++ `feed_modes` (synthetic crosses thresholds + ≥1 momentum & ≥1 reversion under fixed seed; simulated clock closes the expected bar count; replay reads in order + stops + refuses when empty) → **ctest 6/6**; pytest `test_replay_refusal.py` (binary refuses on empty bars) → **pytest 125 passed**.
- **Stable:** clean warning-free build, ctest 6/6, pytest 125. **Next:** address the tuner-throttle residual (min-weight floor for the native factor) so sustained offline training keeps generating fills, then the GUI overhaul.

### 2026-07-05 (Opus 4.8)

- **Closed every open follow-up flag from the 12-task prompt, built the RL advisory module (shipped off), and added two council cost cuts.** RiskGate / live-trading gate / adaptive limit-weakening invariant untouched; live trading stays off.
- **Flags cleared:** created a Python 3.14.4 venv, installed both pinned requirements files, ran the full suite — **124 pytest passed** (pandas pin reconciled to 2.2.3 so it builds against numpy 1.26.4). Ran `python -m ml_factor.train_real` against the demo DB: refuses cleanly (`insufficient_real_data`, 0 real samples < 200, synthetic champion retained). Recorded a **real SEC EDGAR 13F fixture** (5 hits, delayed-disclosure) and updated the parser test; ClankApp left SYNTHETIC (host DNS-unreachable, blocker logged). Residual doc sweep done: Binance→Coinbase and DNN/RL→`dnn_advisory` across `docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`; `git mv docs/DNN_RL_DESIGN.md docs/DNN_ADVISORY_DESIGN.md` + updated every code/README reference; **AUDIT.md refreshed** to honest current state.
- **RL advisory (`rl_advisory/`, Stable-Baselines3 PPO), shipped OFF:** gym `TradingEnv` (rolling-window obs; discrete flat/long/short; equities long-only; reward = realized PnL − mandatory txn cost − drawdown penalty), a hard `rl_min_real_fills` gate (default 500) that refuses **before importing any backend** with **no synthetic-data path**, walk-forward eval + champion/challenger via the shared promotion gate, `/score/rl` bridge endpoint with labelled mock fallback, artifacts registered with provenance. `rl_enabled` defaults false → engine never calls it and the factor (`rl_advisory_factor_weight = 0.0`) stays out of the ensemble. Advisory only, hard-capped at 0.5, never a sole controller.
- **Council cost cuts (in `llm_consensus/consensus.py`, before the Flash gate + providers):** (1) risk pre-check — the engine evaluates cheap RiskGate preconditions read-only and, when already blocked, skips the whole council (logged `risk_precheck`); (2) equities market-hours skip — SPY/QQQ skip the gate+council outside US RTH while crypto stays 24/7 (logged `market_hours`, config `engine.equities_market_hours_only` default true). C++ engine short-circuits before the bridge call; config adds `rl_enabled`/`rl_min_real_fills`/`equities_market_hours_only`; startup block prints RL + market-hours state.
- **Tests added:** `tests/test_rl_advisory.py` (env contract, txn-cost reward, long-only clamp, trainer refuses below gate, `/score/rl` disabled/mock, factor stays out when disabled, walk-forward + challenger gate) and `tests/test_council_cost_cuts.py` (both skips fire before any provider/gate; never skips crypto; disabled-by-config no-op). No network in any test.
- **Stable:** C++ safety spine builds clean, `ctest` **5/5**; full Python suite **124 passed**; RL package stays import-light (torch/SB3 lazy) so the bridge and suite run without them.
- **Next:** prove paper-loop stability over time, then the GUI overhaul (CONTEXT.md GUI Plan).

### 2026-07-04 (Opus 4.8)

- **Completed the 12-task master prompt** on `feat/native-strategy-council-cost-controls`; fast-forwarded onto `origin/main`.
- Task 1 bars OHLCV storage + Alpaca historical backfill; Task 2 native strategy layer (momentum + reversion + regime detector, closed-bar eval, native ATR exits); Task 3 real-fill learning (dropped `simulate_outcome` from the default path, tuner gated at ≥30 closed trades); Task 4 council cost controls (entries-only, Flash gate, daily budget, per-symbol cooldown, token cap, neutral skip, skip logging); Task 5 `dnn_advisory` rename + real-data walk-forward training pipeline + provenance + gated promotion; Task 6 `CoinbaseSimAdapter` replaces Binance; Task 7 free-first whale feeds (ClankApp + SEC EDGAR) live-OFF by default; Task 8 Level-1 config defaults; Task 9 security hardening (loopback bridge, credential masking, pre-commit secrets hook, pinned deps); Task 10 startup transparency block.
- Task 11 (this turn): extracted the tuner ≥30-sample gate into `learning/adapt_gate.hpp` (pure predicate) so it is unit-testable; added `tests/test_tuner_minsample.cpp` (registered in CTest — **5/5 C++ suites green**) and `tests/test_council_cost_controls.py`. Native-exit + council-gate decision logic already covered by `tests/test_strategy.cpp`. Council cost-control test logic verified live (yaml present); pytest itself not runnable in-session (no pytest).
- Task 12 (this turn): CLAUDE.md build-order step 3 + hard-rule aligned to native strategies / `dnn_advisory`; README.md + AUDIT.md corrected Binance→Coinbase and `dnn_advisory`; RETURN.md entry finalized; CONTEXT.md decisions logged.
- **Stable:** C++ safety spine + native strategy + council gate build clean, `ctest` 5/5. Engine refactor (adapt-gate extraction) is behaviour-preserving. RiskGate / live-gate / limit-weakening invariant untouched; live trading OFF by default.
- **Next / flags:** run full `pytest` + real numpy training in a venv; record real ClankApp/SEC-EDGAR fixtures; finish the residual doc-consistency sweep (`docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`, `docs/DNN_RL_DESIGN.md`) + AUDIT honest-state refresh. See RETURN.md + "Open Flags / Follow-ups".

### 2026-07-02 (Opus)

- Implemented real LLM council: OpenAI, Anthropic, Gemini providers plus Gemini Flash gate
- Split consensus.py into focused modules, added prompt caching
- Config flags use_real_council (default false) and gate_enabled (default true)
- 29 council tests, full suite 73 passing, RiskGate untouched
- Stable: council with offline mock fallback, real-vs-mock startup transparency
- Next: second master prompt for strategy layer and supporting infrastructure
