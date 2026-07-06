# Market AI Lab — Architecture

> One-line principle: The dnn_advisory model is a core advisory intelligence layer, the
> whale/smart-money system is a second advanced advisory layer powered specifically by
> free-first sources (ClankApp, SEC EDGAR 13F; Whale Alert optional), the visual dashboard is a first-class control
> surface, every model's verdict and weight must be visible and adjustable in the app,
> paper trading is the continuously updating training ground, and **live trading is
> disabled by default behind an explicit in-app approval gate.**

## 1. System Overview

Market AI Lab is a 24/7 multi-venue trading **research + execution** system that runs
continuously in **paper-trading mode**. Paper trading is the primary training and
evaluation environment. The system learns from outcomes over time, uses a dnn_advisory
factor as part of (not the controller of) its decision system, exposes a highly
visual real-time dashboard / control board, and only permits **live** trading through an
explicit, multi-step, in-app approval gate.

```
                         ┌───────────────────────────────────────────────┐
                         │            VISUAL DASHBOARD / CONTROL BOARD     │  (Python · Dash/Plotly)
                         │  perf · trades · exposure · models · whales ·   │
                         │  risk · live-approval · model-weight controls   │
                         └───────────────▲──────────────────┬─────────────┘
                                         │ reads SQLite +    │ control actions
                                         │ event log (truth) │ (weights, mode, approval)
   ┌─────────────────────────────────────┴──────────────────▼─────────────────────────┐
   │                              CORE ENGINE  (C++20)                                   │
   │                                                                                    │
   │   market_data ─┐                                                                   │
   │   news_ingest ─┤                                                                   │
   │                ▼                                                                    │
   │        ┌──────────────────┐   ┌──────────────────────────────────────────────┐    │
   │        │  SIGNAL FAMILIES  │──▶│         FACTOR-COMBINATION ENGINE            │    │
   │        │ rule-based        │   │  weighted ensemble → combined verdict        │    │
   │        │ structure/liq/vol │   │  (manual / adaptive / default weights)       │    │
   │        │ news/catalyst     │   └───────────────┬──────────────────────────────┘    │
   │        │ LLM consensus ◀───┼── python_bridge          │                            │
   │        │ dnn_advisory ◀────┼── ml_factor (Py svc)     │ proposed action            │
   │        │ whale/smart-money◀┼── whale_signal (Py svc)  ▼                            │
   │        │ perf/regime ctx   │   ┌──────────────────────────────────────────────┐    │
   │        └──────────────────┘   │   LAYER 2: ADAPTIVE STRATEGY (learns, tunes)  │    │
   │                                └───────────────┬──────────────────────────────┘    │
   │                                                ▼                                    │
   │                                ┌──────────────────────────────────────────────┐    │
   │                                │   LAYER 1: STATIC SAFETY (FINAL AUTHORITY)   │    │
   │                                │  hard risk limits · kill switch · hard stop  │    │
   │                                └───────────────┬──────────────────────────────┘    │
   │                                                ▼ (approved order only)              │
   │   execution ◀── mode router: recommendation_only | paper | live (gated)            │
   │        │                                                                            │
   │        ├─ Alpaca     → Alpaca paper API (paper)        / live adapter (disabled)    │
   │        ├─ Coinbase   → simulated/test (paper)          / live adapter (disabled)    │
   │        └─ IBKR       → scaffold/sim placeholder        / live adapter (disabled)    │
   │                                                                                    │
   │   storage (SQLite, source of truth) · account_manager · config · logging           │
   │   learning (param history, model versioning, champion/challenger, rollback)         │
   └────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Four-Layer Decision Architecture

The dnn_advisory factor is **important but not sovereign**. Authority flows downward; safety wins.

| Layer | Name | Role | Authority |
|-------|------|------|-----------|
| **1** | **Static Safety** | Enforces hard risk limits, kill switch, hard stops. | **FINAL — never bypassable** by LLMs, DNN, RL, whale logic, adaptive logic, or execution adapters. |
| **2** | **Adaptive Strategy** | Learns gradually from logged paper results; tunes weights/thresholds/sizing within safe ranges. | May propose/adjust, but cannot weaken Layer-1 limits. Every change logged + rollback-able. |
| **3** | **dnn_advisory Factor** (RL split into the separate `rl_advisory` module, shipped OFF behind the `rl_min_real_fills` gate) | Outputs structured advisory signals; evolves via continual learning. | **Advisory only.** Cannot bypass risk or self-enable live. |
| **4** | **Smart-Money / Whale Signal** | Tracks large investor behaviour via ClankApp / SEC EDGAR 13F (Whale Alert optional). | **Advisory only.** Input, not controller. |

### Layer 1 — Static Safety (C++, `risk/`)
Enforces, as hard config, all of:
`max_daily_loss_total`, `max_daily_loss_per_venue`, `max_consecutive_losses`,
`max_trade_size_per_venue`, `max_total_exposure`, `max_exposure_per_symbol`,
`max_exposure_per_market`, `kill_switch_enabled`, `hard_stop_live_if_loss_breach`,
`manual_resume_required_after_kill_switch`.
Implemented as a pure, deterministic gate (`RiskGate::evaluate(order, state) -> Decision`)
with an explicit allow/deny + reason. **Nothing routes to execution without passing it.**

### Layer 2 — Adaptive Strategy (C++, `learning/` + `signal_engine/`)
Tunes within bounded ranges: model weights, trade/no-trade thresholds, confidence
thresholds, sizing multipliers, venue aggressiveness, category prefs, DNN factor weight,
whale-signal weight, consensus weighting, cooldown behaviour. Logs every parameter
update, supports rollback, compares old vs new sets, preserves auditable history, and is
**structurally incapable of lowering Layer-1 hard limits** (validation rejects it).

### Layer 3 — dnn_advisory Factor (Python service, `ml_factor/`)
See `DNN_ADVISORY_DESIGN.md`. Outputs: `dnn_action_bias`, `dnn_confidence`,
`dnn_expected_edge`, `dnn_regime_label`, `dnn_risk_flag`, `dnn_position_scale_hint`.
RL is now a separate advisory module (`rl_advisory`, PPO), shipped OFF behind the
`rl_min_real_fills` gate; it trains only on real fills and shares the 0.5 sizing cap.

### Layer 4 — Whale / Smart-Money (Python service, `whale_signal/`)
Outputs: `whale_bias`, `whale_confidence`, `whale_flow_direction`,
`whale_activity_score`, `whale_follow_signal`, `whale_contradiction_flag`,
`whale_regime_label`. Free-first sources: **ClankApp** (free crypto/on-chain
large transfers — default), **SEC EDGAR 13F**
(free `data.sec.gov` REST, no key — institutional holdings labelled as **delayed
disclosure**, not live trade flow). **Whale Alert API** is an optional key-gated
alternative.

## 3. C++ vs Python Module Map

| Module | Language | Rationale |
|--------|----------|-----------|
| `core/` (engine loop, orchestration) | **C++20** | C++-first preference; deterministic, long-running. |
| `config/` | **C++20** (+ YAML schema) | Typed config + validation is the safety contract. |
| `risk/` (Layer 1) | **C++20** | Must be fast, deterministic, audit-clean. |
| `learning/` (Layer 2, versioning, rollback) | **C++20** | Owns param history + champion/challenger bookkeeping. |
| `signal_engine/` (factor combination, weights) | **C++20** | Core decision math; weight control state. |
| `market_data/` | **C++20** | Streaming ingestion; perf-sensitive. |
| `news_ingestion/` | **C++20** core + **Python** fetchers | C++ holds state; Python for messy API parsing. |
| `execution/` (adapters, mode router) | **C++20** | Routing + order lifecycle; live adapters disabled-by-default. |
| `account_manager/` | **C++20** | Venue/credential/mode state machine. |
| `storage/` (SQLite, event log) | **C++20** | Single source of truth; shared with Python via the same DB file. |
| `llm_consensus/` | **Python bridge** | LLM client libraries + multi-model ensemble live in Python. |
| `ml_factor/` (dnn_advisory) | **Python** | PyTorch/sklearn ecosystem. Justified ML service. |
| `whale_signal/` | **Python** | ClankApp / SEC EDGAR 13F integrations (Whale Alert optional) + scoring. |
| `python_bridge/` | **Python** | Thin RPC/IPC between C++ core and Python services. |
| `ui/` (dashboard / control board) | **Python (Dash/Plotly)** | Fastest path to a rich live web dashboard. |
| `ops/`, `tests/`, `docs/` | mixed | CMake/CTest (C++) + pytest (Python). |

**Bridge mechanism:** C++ core and Python services communicate via (a) the shared
**SQLite** DB (signals, decisions, trades, events — the source of truth) and (b) a thin
local **JSON-over-HTTP / stdio RPC** in `python_bridge/` for request/response calls
(e.g. "score this market state"). Dashboard reads SQLite + event log directly.

## 4. Dashboard Stack Decision

**Chosen: Plotly Dash + SQLite-backed state, refreshed via `dcc.Interval`
(default 5s; optionally `dash-extensions` WebSocket/SSE for high-frequency panels).**

Rationale:
- Fastest path to a rich, interactive, *visual-first* web dashboard in Python.
- Native interactive Plotly charts (equity curve, drawdown, heatmaps, bar/scatter).
- `dcc.Interval` gives near-real-time polling against the SQLite source of truth — matches
  the requirement to use internal event log + API/account data as truth (and to prefer
  API/account data over broker-side chart rendering for Alpaca paper).
- Sliders / numeric inputs / toggles / lock controls map directly to Dash components for
  the model-weight control panel.

## 5. Venue Modes & Execution Routing

Each venue supports: `disabled` · `recommendation_only` · `paper` · `live`.
Defaults: every venue `paper` or `recommendation_only`; **live disabled by default.**

| Mode | Behaviour |
|------|-----------|
| `recommendation_only` | Show trade ideas only; no orders placed. |
| `paper` | Alpaca→Alpaca paper API · Coinbase→sim/test. IBKR is live-only (gated off), not a paper route. |
| `live` | **Only if** credentials present **and** explicitly enabled in-app **and** approval gate passed **and** risk engine allows **and** kill-switch conditions clear. |

## 6. Continuous Learning Loop (paper = training ground)

```
market state + news + decision + outcome ──▶ storage (event log, SQLite)
        ▲                                            │
        │                                            ▼
   execution (paper)                         learning/ + ml_factor/
        ▲                                  param tuning (Layer 2)  ·  dnn_advisory retrain (Layer 3)
        │                                  champion/challenger eval · promotion (manual gate) · rollback
   factor-combination engine ◀──────────── updated weights / promoted model (subordinate to Layer 1)
```

Controlled · versioned · auditable · rollback-capable · always subordinate to Layer 1.

## 7. Build Order (Phases)

1. **Phase 1** — Architecture summary, dnn_advisory design, dashboard stack, C++/Python map. *(this doc set)*
2. **Phase 2** — config, logging, storage, Layer-1 safety, Layer-2 adaptive, account/venue models, dashboard scaffold, default config + validation.
3. **Phase 3** — market/news ingestion, multi-LLM consensus, dnn_advisory factor, whale integrations, factor-combination engine, model-weight control logic.
4. **Phase 4** — Alpaca paper route, full live dashboard (trades/PnL/exposure/risk/learning/approval/model-verdict/weights/whale).
5. **Phase 5** — Coinbase sim/test, IBKR scaffold/data, expanded analytics + learning views.
6. **Phase 6** — in-app live-mode switching, live config forms, approval-gate workflow, venue safety checks, disabled-by-default live adapters.
