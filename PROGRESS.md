# Project Progress

Status tracker for AiTrader. Read at the start of each session. Update at the end of each session.

## Current State

The C++ safety spine builds clean and runs the offline paper loop (`ctest` 7/7). Polymarket is fully removed (region). Alpaca paper is the primary online loop (`feed_mode: alpaca_paper`, paper + market-data only, no live path). IBKR is wired as the live-only venue via a locally run IB Gateway but stays DISABLED behind the approval gate. The real LLM council is merged (Opus 4.8, GPT-5.5, Gemini 3.1 Pro) with a Claude Haiku 4.5 base-check gate, prompt caching, and cost controls (budget, per-symbol cooldown, token cap, neutral skip). The native strategy layer (momentum + reversion + regime detector, closed-bar eval, native ATR exits) is in; the adaptive tuner learns from real closed-trade PnL (≥30-trade gate); the `dnn_advisory` factor has a real-data walk-forward training pipeline with gated promotion; Coinbase replaces Binance; free-first whale feeds (ClankApp + SEC EDGAR) are wired live-OFF by default; security hardening (loopback bridge, credential masking, pre-commit secrets hook, pinned deps) landed. A separate `rl_advisory` PPO module (gym env, real-fill training gate, walk-forward eval, `/score/rl` bridge endpoint) is built but **shipped OFF** — it never touches the ensemble until an operator toggles `rl_enabled` past the `rl_min_real_fills` gate. Two council cost cuts (risk pre-check + equities market-hours skip) short-circuit doomed/after-hours setups before any provider spend. Council/whale live paths stay behind config/env flags and the bridge. Live trading disabled by default. A React and TypeScript GUI (three pages Settings, Paper, Live) served by a thin read-only FastAPI backend (api_server/) over the same SQLite database is now built and additive to the Dash UI. Next up: extend it with the CONTEXT.md GUI Plan controls, and prove paper-loop stability.

## Stable and Working

- RiskGate: 14 hard checks, final authority on every order, tested
- Kill switch: latching, manual resume required, tested
- Live-trading gate: four independent blocks, live unreachable by design
- Config validation: throws on unsafe values at load
- Secret handling: encrypted store, env fallback, nothing committed
- Alpaca paper: real HTTP for market data and paper orders
- SQLite DAO: 14 tables, WAL mode, append-only audit log
- Dash UI: paper tab, live tab locked, advanced tab, accounts tab
- Real LLM council: 3 providers, Claude Haiku base-check gate, offline mock fallback, 29 tests
- Kill-request wiring: engine consumes the GUI/API halt-request control file each iteration and trips the same latching kill switch (archived to avoid re-trip, manual resume required), ctest-covered

## In Progress

- GUI overhaul (React + TypeScript, additive). Three pages built (Settings and APIs, Paper, Live) served by a read-only FastAPI backend (api_server/) over the same SQLite DB, loopback only. Coinbase Pro dark theme, sidebar + status bar, WebSocket live stream. Dash UI retained as fallback. Backend 22 pytest, frontend 3 render tests + typecheck + build all green. The engine now consumes the GUI kill-request control file and trips the latching kill switch (2026-07-09), so the kill button actually halts the loop. Next: the CONTEXT.md GUI Plan controls (per-layer + per-model toggles, champion/challenger + RL enable, weight sliders, regime override, budget dial).
- None active. The "close open flags + RL advisory (shipped off) + council cost cuts" prompt is complete (2026-07-05): every follow-up flag from the 12-task prompt is cleared, `rl_advisory` (PPO, shipped off) is built, and the two council cost cuts (risk pre-check + market-hours) are in. See "Open Flags / Follow-ups" and RETURN.md.

## Not Started

- Live-approval workflow end to end (`try_enable_live` still never called by design)
- Real (disabled-by-default) live adapter for Coinbase (IBKR live adapter is now wired behind the gate, 2026-07-06)
- Training the RL advisory policy: the `rl_advisory` PPO module is built but shipped OFF and untrained (activates only past the `rl_min_real_fills` gate, default 500 real fills; no synthetic-data path). Supervised `dnn_advisory` is the only Layer-3 signal serving today.
- Remaining GUI Plan controls (per-layer + per-model toggles, champion/challenger + RL enable, weight sliders, regime override, budget dial). The base React GUI (three pages + read-only backend) is now In Progress; these advanced controls are still to build.

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

### 2026-07-09 (Opus 4.8) — wire the GUI kill-request control file into the engine kill switch

- **The GUI kill button now actually halts the engine.** New `Engine::consume_operator_kill_request()` (`core/engine.cpp`) reads the API backend's control file (`.control/kill_request.json`, env `MAL_CONTROL_DIR` overrides, matching config `system.control_dir`) at the top of BOTH per-iteration entry points — `run_iteration` (tick / alpaca_paper online loop) and `step_bar_mode` (bar-driven synthetic_regimes / replay) — BEFORE any signal is evaluated.
- **Same latching mechanism, not a separate path.** When `requested` is true it trips the existing kill switch exactly as a loss breach does: `kill_switch_.trip(reason)` + per-venue `accounts_->trip_kill_switch` + a `kill_switch` critical event. It reads a control file only; it never touches the RiskGate.
- **No re-trip on restart.** The processed request is archived to `kill_request.processed.json` (atomic rename, delete fallback), so a stale file never re-trips on a later run.
- **Manual resume unchanged.** The switch stays latching; an operator halt requires the same manual resume as a loss-triggered halt. No new resume path.
- **Supporting bits:** `SystemConfig::control_dir` (config.hpp/.cpp/default_config.yaml), a `json_get_bool` JSON helper (`core/bridge_client.*`) mirroring the existing tiny readers, and read-only `Engine::kill_switch_tripped()` / `manual_resume_pending()` accessors.
- **Verified end to end (synthetic_regimes + the real POST /kill endpoint):** baseline 800-step synthetic run opened 52 paper trades; with a pending request the same run tripped on iteration 1 (event order startup -> kill_switch -> summary), opened 0 trades, and archived the request (wall-clock 0.17s). On the tick path, the operator halt persisted `venue_state.kill_switch_tripped=1` for alpaca/coinbase/ibkr via the existing `snapshot_balances`, so the GUI reflects it.
- **Stable:** C++ ctest 8/8 (new `test_kill_switch`: 14/14 checks). Python pytest 160 passed (added the control-file shape-contract test). RiskGate logic, the live-trading gate, and the adaptive limit-weakening invariant untouched. Live trading stays OFF.
- **Next:** the CONTEXT.md GUI Plan controls; prove paper-loop stability.

### 2026-07-08 (Opus 4.8) — replace the Gemini 3 Flash base-check gate with Claude Haiku 4.5

- **Base-check gate now runs on Claude Haiku 4.5** (`llm_consensus/gate.py`: `GeminiFlashGate` -> `HaikuGate`). It reuses the council's Anthropic Messages client and the same `ANTHROPIC_API_KEY`, so no new credential is needed. Same screening prompt and same yes/no-plus-reason JSON contract; the gate still skips the council on "no".
- **Shared Anthropic transport extracted** (`llm_consensus/providers.py`: new `anthropic_request` + `anthropic_text`, mirroring `gemini_request`/`gemini_text`). `AnthropicProvider` was refactored onto them so the council secondary and the gate share one transport (DRY). Gate response capped at 128 tokens.
- **Config**: `config/default_config.yaml` `llm_gate: gemini-3-flash` -> `claude-haiku-4-5`, commented that the gate uses Haiku through the Anthropic client and reuses `ANTHROPIC_API_KEY`. `gate_enabled` unchanged.
- **Env**: `.env.example` keeps `GEMINI_API_KEY` (still used by the tertiary council slot `gemini-3.1-pro`); only the gate comment moved to `ANTHROPIC_API_KEY`. No new credential.
- **Startup line**: `python_bridge/server.py` prints the gate model via `council_status_line`, now showing `claude-haiku-4-5`.
- **Fail-safe posture preserved**: gate disabled -> AlwaysProceedGate; no key -> permissive mock (proceed); call error / unparseable -> fail-open (proceed).
- **Tests**: `tests/test_llm_consensus.py` gate tests moved to Haiku mocks (Anthropic envelope, `ANTHROPIC_API_KEY`); `tests/test_council_cost_controls.py` stub gate model string updated. Full Python suite green (159 pytest passed).
- **Docs**: CONTEXT.md (API Notes + Cost Notes + Key Decisions); CLAUDE.md approved-model-strings rule; AUDIT.md; "Flash gate" -> "base-check gate" comment sweep across consensus.py/config_access.py/core/engine.cpp/config/config.hpp.
- **NOT touched**: RiskGate logic, the live-trading gate, the adaptive limit-weakening invariant. Live trading stays OFF.
- **Next**: consume the kill-request file in the engine, then the CONTEXT.md GUI Plan controls; prove paper-loop stability.

### 2026-07-06 (Opus 4.8) — React + TypeScript trading GUI (Settings, Paper, Live) on a read-only FastAPI backend

- **Built a React + TypeScript GUI in web/**, Coinbase Pro dark theme, additive to the Dash UI (which stays as the fallback, untouched). Left sidebar + top status bar (engine state, active view, kill switch, bridge). Three routed pages: Settings and APIs, Paper, Live. Dependency-free SVG equity chart, typed API client, REST for initial load, WebSocket for live updates, loading and error states throughout.
- **Thin read-only FastAPI backend in api_server/.** Endpoints: /health, /account, /positions, /orders, /trades, /pnl, /signals, /council, /whale, /risk, /venues, /approval, /credentials (GET masked + POST encrypted), /credentials/test, /kill (GET + POST), and the /stream WebSocket on a 2s tick. Binds 127.0.0.1 only. Read-only on the operational tables. The only write paths are credential entry through the existing encrypted keystore and a kill-switch halt request written to a control file (.control/), never an operational table and never the RiskGate.
- **Kill switch, honestly.** The engine trips its own kill switch and reflects it in venue_state; the GUI shows that state and records a durable operator halt request through the control-file channel. Wiring the engine to consume the request file is a flagged follow-up.
- **LLM council keys** (OpenAI, Anthropic, Google) added to the credential registry so the Settings page manages them; they resolve through the existing resolve_env path (in-app first, then env), so a saved key flows to the council with no provider change.
- **Verified live** against the real market_ai_lab.db: /health shows engine running + bridge reachable, /account paper equity resolves, /venues lists alpaca/coinbase/ibkr, /approval reports all four mechanisms with live locked.
- **Stable:** backend 22 pytest (full Python suite 159 passed), frontend 3 render tests + typecheck clean + production build. No real network in any test. RiskGate, live-trading gate, and the adaptive limit-weakening invariant untouched. Live trading stays OFF.
- **Next:** consume the kill-request file in the engine, then the CONTEXT.md GUI Plan controls.

### 2026-07-06 (Opus 4.8) — remove Polymarket, Alpaca paper as primary online loop, IBKR wired live behind the gate

- **Removed Polymarket fully.** Deleted PolymarketPaperAdapter and all Polymarket routing (execution + engine, both the native and legacy bootstrap-sim paths), the Apify Polymarket whale adapter, and every Polymarket/Apify reference in config, credentials, the dashboard groups, schema comments, and the demo. Added tests/test_no_polymarket.py as a regression guard.
- **Alpaca paper is the primary ONLINE loop.** `feed_mode: alpaca_paper` forces the online AlpacaFeed (real 5-minute bars over the bridge, paper orders to Alpaca paper) through the same closed-bar path. Startup now prints an alpaca line and an online-mode note. Alpaca still has NO live path (live_adapter none).
- **IBKR wired as the live-only venue behind the gate.** IbkrLiveAdapter replaced the sim placeholder and POSTs to the bridge /execute/ibkr_live only through the gated Live branch. New execution/ibkr_adapter.py maps orders to IBKR contracts/orders and places/cancels/reports status via ib_insync (imported lazily, pinned optional). A missing IB Gateway or dropped socket returns unavailable and never simulates. Startup probes IB Gateway reachability when ibkr.connection_enabled is true. Live stays DISABLED behind the approval gate.
- **Verified (synthetic_regimes + simulated clock, 4000 iterations):** 16000 bars closed, 31 native entries (reversion 28, momentum 3), 31 exits (target 30, stop 1), tuner 623 weight changes within clamps, train_real challenger_recorded (15900 samples, sharpe 0.9392).
- **Stable:** C++ ctest 7/7 (added test_ibkr_routing), Python pytest 137 passed (added test_ibkr_adapter, test_no_polymarket). No network or socket in any test.
- **Next:** wire the live-approval workflow end to end, then the GUI overhaul (CONTEXT.md GUI Plan).

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
