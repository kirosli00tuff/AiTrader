# Build Spec — handoff for implementation

Read `docs/ARCHITECTURE.md`, `docs/DNN_RL_DESIGN.md`, and `config/default_config.yaml`
FIRST. They are authoritative. Do not contradict them. Build into the EXISTING workspace
at `/home/user/workspace/market-ai-lab` (directory skeleton already created).

## Tech stack (locked)
- Core: **C++20**, build with **CMake** (+ CTest). Storage: **SQLite** (single DB file =
  source of truth, shared between C++ core and Python services).
- Python services: **llm_consensus**, **ml_factor** (DNN/RL, PyTorch), **whale_signal**
  (Apify / Whale Alert / SEC 13F), **python_bridge** (thin JSON-over-HTTP/stdio RPC), and
  **ui** = **Plotly Dash** dashboard (refresh via `dcc.Interval`, default 5s).
- Python deps go in `python_bridge/requirements.txt` and `ui/requirements.txt`.

## Hard requirements (non-negotiable)
1. **Live trading disabled by default** for ALL venues. Live can ONLY be enabled by explicit
   in-app user action through the approval gate (all `live_approval.*` conditions must hold).
2. **Layer 1 (static safety) is final authority** and never bypassable by LLM/DNN/RL/whale/
   adaptive/execution. Implement as a deterministic `RiskGate` in `risk/` returning
   allow/deny + reason; nothing reaches execution without passing it.
3. **Layer 2 adaptive** may tune weights/thresholds/sizing within safe ranges, must log every
   change, support rollback, compare old vs new, and **must validate that it never weakens any
   Layer-1 hard limit** (reject such changes).
4. **DNN/RL (Layer 3)** and **whale (Layer 4)** are ADVISORY factors only. Outputs exactly the
   fields named in the design docs. DNN sizing capped by `dnn_position_scale_cap`, whale by
   `whale_position_scale_cap`.
5. Whale module uses ONLY: Apify Polymarket whale-tracker, Whale Alert API, SEC API 13F
   (13F clearly labelled DELAYED disclosure, not live flow). Wrap each in `whale_signal/` with
   a clean adapter + a MOCK/offline fallback so the demo runs without live keys.
6. Every model's verdict + confidence + edge + weight must be visible AND adjustable in the UI.

## Modules to implement (languages per ARCHITECTURE §3)
- `config/` C++: load+validate `default_config.yaml`, typed structs, hard-limit validation,
  reject invalid/unsafe values. Provide `config/schema.md`.
- `storage/` C++: SQLite schema + DAO. Tables: events (append-only log = source of truth),
  trades, positions, signals, model_outputs, model_registry, param_history, weight_changes,
  whale_activity, whale_signal_history, approval_state, venue_state, account_balances,
  blocked_trades. Provide migrations.
- `risk/` C++: Layer-1 RiskGate (all `risk.*` limits), kill switch, hard-stop on loss breach,
  manual-resume-after-kill-switch state machine.
- `learning/` C++: Layer-2 adaptive tuner, param history, model versioning bookkeeping,
  champion/challenger records, rollback, audit.
- `signal_engine/` C++: factor-combination engine (weighted ensemble → combined verdict),
  weight state (manual/adaptive/default + locks + enable/disable), normalization, validation,
  "preview verdict on weight change", weight-change audit.
- `market_data/` C++: streaming/poll ingestion abstraction (mock feed for demo).
- `news_ingestion/` C++ core + python fetchers: catalyst score.
- `execution/` C++: mode router (recommendation_only|paper|live) + per-venue adapter
  interface. Paper adapters: Polymarket→polymarket-paper-trader bridge, Alpaca→paper API,
  Binance→sim, IBKR→placeholder/sim. Live adapters present but DISABLED by default with
  clear TODO markers for Binance + IBKR.
- `account_manager/` C++: venue/credential/mode state machine + connections model.
- `llm_consensus/` Python: multi-LLM ensemble → consensus verdict/confidence (mock providers
  ok; structure for real keys).
- `ml_factor/` Python: DNN/RL advisory factor per DNN_RL_DESIGN.md — Stage A supervised DNN
  first (PyTorch), training/eval pipeline, model versioning, champion/challenger, rollback,
  logged outputs. Ship a tiny trained/initialized model so the demo emits real signals.
- `whale_signal/` Python: Apify + Whale Alert + SEC 13F adapters (with mocks) → whale outputs
  + actor ranking + useful-vs-noisy scoring.
- `python_bridge/` Python: RPC server exposing llm/ml/whale scoring to C++ core over local
  JSON; also a Python client the C++ side calls.
- `ui/` Python (Dash): the full dashboard/control board — ALL panels and ALL charts/tables
  listed in the user's spec (daily perf, live trade activity, portfolio/exposure, strategy/
  DNN/RL/model-verdict, smart-money/whale, risk/safety, live-approval, model-weight control).
  Charts: equity curve, daily PnL bar, drawdown, trade-by-trade PnL, win/loss calendar
  heatmap, venue allocation, exposure by symbol/market, model-contribution/factor-weight,
  recent trades table, open positions table, blocked/rejected table, param-change history
  table, learning before/after chart, DNN/RL perf chart, live-approval readiness panel,
  model-verdict comparison table, weight-change history table, recent whale activity table,
  whale-signal history chart, whale-agreement-vs-outcome chart. Read SQLite + event log as
  source of truth.

## Demo (must run end-to-end, offline, no live keys)
Provide `ops/run_demo.sh` (or `ops/demo.py`) that: seeds the SQLite DB, runs a paper loop
across Polymarket(paper) + Alpaca(paper) with mock market data, produces multi-LLM consensus,
DNN/RL advisory signal, whale signal, risk-gated paper execution, and launches the Dash
dashboard. README documents exact build + run steps.

## Deliverables
- Working scaffolded codebase that **CMake-configures and builds the C++ targets** and whose
  **Python services + Dash UI import and run** with mock data.
- `README.md` covering EVERY topic in the user's deliverables list (build, run, venue setup,
  dashboard overview, model-weight control, whale signal, paper/live behaviour, live
  approval-gate behaviour, account connection setup, 4-layer architecture, DNN/RL explanation,
  kill-switch behaviour, default control values, external data-source setup for Apify / Whale
  Alert / SEC API 13F).
- `.env.example` with APIFY_TOKEN, WHALE_ALERT_API_KEY, SEC_API_KEY, ALPACA_* etc.
- Example configs with safe defaults (already at `config/default_config.yaml`; add a
  `config/example_live_disabled.yaml` showing a fully-paper safe profile).
- Clear `TODO:` markers for incomplete Binance + IBKR features.
- Unit tests: C++ (CTest) for RiskGate + config validation + weight normalization; pytest for
  whale scoring + ml_factor IO + consensus.

## Style
Idiomatic modern C++20 (RAII, std::optional/expected-style error handling, no raw owning
pointers). Clean Python (type hints, small modules). Keep it modular and readable — this is a
long-lived, continuously-evolving codebase. Comment the safety-critical paths.
