# Project Progress

Status tracker for AiTrader. Read at the start of each session. Update at the end of each session.

## Current State

The C++ safety spine builds clean and runs the offline paper loop. The real LLM council is merged (Opus 4.8, GPT-5.5, Gemini 3.1 Pro) with a free Gemini Flash gate and prompt caching. Council stays behind config flags and the bridge. Live trading disabled. Next up: native strategy layer, historical bars storage, real-fill feedback, whale feeds, Coinbase venue.

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

- None active. Awaiting second master prompt.

## Not Started

- Native strategy layer (momentum, mean reversion, regime detector)
- Historical bars storage
- Real-fill feedback to adaptive tuner
- ClankApp crypto whale feed (adapter stubbed)
- SEC EDGAR equities feed (adapter stubbed)
- Coinbase venue (replacing Binance)
- DNN advisory real-data training pipeline
- Live-approval workflow end to end
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

### 2026-07-02 (Opus)

- Implemented real LLM council: OpenAI, Anthropic, Gemini providers plus Gemini Flash gate
- Split consensus.py into focused modules, added prompt caching
- Config flags use_real_council (default false) and gate_enabled (default true)
- 29 council tests, full suite 73 passing, RiskGate untouched
- Stable: council with offline mock fallback, real-vs-mock startup transparency
- Next: second master prompt for strategy layer and supporting infrastructure
