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
- Shipped `dnn_advisory` champion is still synthetic-trained; the real-data trainer refuses (`insufficient_real_data`) until the DB holds ≥200 real labelled samples. `rl_advisory` is untrained (real-fill gate unmet) and shipped off.

## Open Flags / Follow-ups

Cleared 2026-07-05 (all verified this session): venv created and full `pytest tests/ -q` green (**124 passed**); `python -m ml_factor.train_real` run against the demo DB (refuses cleanly with `insufficient_real_data`, synthetic champion retained); real SEC EDGAR 13F fixture recorded (ClankApp left SYNTHETIC — host DNS-unreachable); residual doc-consistency sweep done (`docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`, `DNN_RL_DESIGN.md`→`DNN_ADVISORY_DESIGN.md`) + AUDIT honest-state refresh; bars OHLCV storage landed (was "no historical price data persisted").

Still open (not defects — known limits):

- Advisory factor scores run through real Python services only with `--bridge`; the default path uses deterministic C++ mocks.
- Whale live-fetch parsers are verified against one recorded SEC 13F payload only; the other feeds' assumed shapes are still unverified against live responses (and live is off by default behind `WHALE_LIVE_ENABLED` / `SEC_EDGAR_ENABLED`).
- Live-approval workflow not wired end to end (`try_enable_live` never called). Safe, but incomplete.
- Real LLM providers untested against live keys; `rl_advisory` untrained (real-fill gate unmet); `dnn_advisory` still shipping the synthetic champion until enough real labelled samples exist.

## Session Log

Newest entries at top. One entry per session. Format: date, model used, what changed, what is stable, what is next.

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
