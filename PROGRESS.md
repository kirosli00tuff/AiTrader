# Project Progress

Status tracker for AiTrader. Read at the start of each session. Update at the end of each session.

## Current State

The C++ safety spine builds clean and runs the offline paper loop (`ctest` 5/5). The real LLM council is merged (Opus 4.8, GPT-5.5, Gemini 3.1 Pro) with a free Gemini Flash gate, prompt caching, and cost controls (budget, per-symbol cooldown, token cap, neutral skip). The native strategy layer (momentum + reversion + regime detector, closed-bar eval, native ATR exits) is in; the adaptive tuner learns from real closed-trade PnL (≥30-trade gate); the `dnn_advisory` factor has a real-data walk-forward training pipeline with gated promotion; Coinbase replaces Binance; free-first whale feeds (ClankApp + SEC EDGAR) are wired live-OFF by default; security hardening (loopback bridge, credential masking, pre-commit secrets hook, pinned deps) landed. Council/whale live paths stay behind config/env flags and the bridge. Live trading disabled by default. Next up: venv pytest + real numpy training run, real whale fixtures, residual doc-consistency sweep + AUDIT refresh (see Open Flags).

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

- None active. 12-task master prompt complete (2026-07-04). Follow-up flags open (venv pytest/training run, real whale fixtures, residual doc sweep + AUDIT refresh) — see RETURN.md and "Open Flags / Follow-ups".

## Not Started

- Live-approval workflow end to end (`try_enable_live` still never called by design)
- Real (disabled-by-default) live adapters for Coinbase + IBKR
- True RL for the advisory factor (deferred until ≥500 real closed fills; supervised `dnn_advisory` only today)
- Frontend rebuild in React

## Next Up

1. Run second master prompt: strategy layer, bars storage, real-fill learning, council cost controls, Level 1 defaults, Coinbase, ClankApp, SEC EDGAR
2. Verify paper loop stability over time
3. Then consider frontend rebuild

## Known Issues and Caveats

- Adaptive tuner learns from simulate_outcome, a seeded-RNG toy PnL simulator, not real fills. Ignore improvement signals until real-fill feedback lands.

## Open Flags / Follow-ups (raised 2026-07-03, fix later)

- **pytest AND numpy not runnable in the base environment (py_compile-only verification).** The base `python3` has neither `pytest` nor `numpy`, so (a) the whole Python test suite (credentials, LLM consensus, ml_factor, whale, bridge/council/whale, and the new `test_bridge_bind.py`) cannot be executed in-session, and (b) anything importing numpy — the DNN advisory model (`ml_factor/model.py`) and the new **Task 5 real-data training pipeline** — cannot be *run* here, only `py_compile`-checked and logic-reviewed. Only the C++ ctest suite executes in-session. Consequently, every Python change in the 2026-07-04 session (Task 9 security, Task 5 dnn_advisory pipeline, Task 7 whale wiring, Task 11 pytest additions) is verified by `py_compile` + isolated logic checks + (where deps allow, e.g. `log_safety`, stdlib dataset readers) direct execution — NOT by a full `pytest`/training run. **TODO before merge:** in a venv, `pip install -r python_bridge/requirements.txt -r ui/requirements.txt`, then confirm `pytest tests/ -q` is green and `python -m ml_factor.train_real --db market_ai_lab.db` trains a real-data challenger without error. Master-prompt policy (user, 2026-07-04): finish all 12 tasks first, then fix every flag listed here / in RETURN.md.
- **Session cost / scope.** The Task 2–12 build is large and cross-cutting (bars, strategy, engine rewire, dnn_advisory rename, Coinbase, whale feeds, security). GateGuard fires a fact-forcing preamble on every edit; leaving it on is deliberate but adds cost per file. If a future session needs to move faster, `ECC_GATEGUARD=off` disables it. Not a code defect — tracked so the spend is visible.
- Advisory layers run only with --bridge. Default path uses C++ mocks.
- Whale adapters use assumed payload shapes. Verify against real responses before trusting.
- Live-approval workflow not wired. try_enable_live never called. Safe, but incomplete.
- No historical price data persisted. Bars storage needed before honest backtests or DNN retraining.

## Session Log

Newest entries at top. One entry per session. Format: date, model used, what changed, what is stable, what is next.

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
