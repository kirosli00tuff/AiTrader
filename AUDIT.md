# AiTrader / Market AI Lab — Repository Audit

**Date:** 2026-07-05 (refreshed; originally audited 2026-07-01)
**Method:** Read the actual source (not the README claims), built the C++ core, ran the C++ tests, ran the full Python suite in the project venv, executed the trainers against the demo DB, and grepped the tree for wiring. Findings below cite `file:line`.

**One-paragraph verdict (blunt):** The **C++ safety-and-execution spine is real, clean, warning-free, and tested** — it builds and the offline paper loop runs today. The intelligence layers have moved from scaffolding toward real-data plumbing, but the *default running system is still mostly deterministic*: the multi-LLM "council" makes *zero* external API calls out of the box (real providers exist behind keys + `--bridge` + `use_real_council`, otherwise labelled mocks); the adaptive tuner now learns from **real closed-trade PnL** (gated until ≥30 closed trades) rather than a toy RNG; `dnn_advisory` now has a **real-data trainer with expanding walk-forward validation and gated (manual) promotion**, but the *shipped* champion is still the synthetic NumPy MLP because the demo DB does not yet hold enough real labelled samples (trainer correctly refuses: 0 real samples < 200). RL is now a **separate `rl_advisory` PPO module, shipped OFF** behind a `rl_min_real_fills` gate (default 500) with **no synthetic-data training path**. The whale layer has real network code, now **live-OFF by default** behind `WHALE_LIVE_ENABLED` / `SEC_EDGAR_ENABLED`, still **unverified against most live payloads** (one real SEC 13F capture is recorded as a fixture; ClankApp remains synthetic — DNS-unreachable here). Coinbase replaced Binance (Binance is unavailable in Canada). Two council cost cuts now short-circuit doomed/after-hours setups before any provider spend. **Live trading remains gated to the point of being unreachable** (the enable function exists but is never called). This is an honest skeleton growing real muscle — not vaporware, and not yet the full "multi-LLM + dnn_advisory + whale intelligence" headline in the running system.

---

## 1. Project structure

**One repo, two languages, loosely coupled.** 96 tracked files.

| Language | Lines | Where |
|---|---|---|
| C++20 | ~3,610 (2,531 `.cpp` + 1,079 `.hpp`) | `core/ config/ risk/ learning/ signal_engine/ market_data/ news_ingestion/ account_manager/ execution/ storage/` |
| Python | ~5,667 across 34 files | `llm_consensus/ ml_factor/ whale_signal/ python_bridge/ market_data/alpaca_source.py account_manager/credentials.py news_ingestion/fetchers.py ui/` |
| SQL / YAML | 194 / 344 | `storage/schema.sql`, `config/*.yaml` |

**Build systems:** CMake (`CMakeLists.txt`, C++20, `-Wall -Wextra`, links system SQLite3 or a bundled amalgamation). Python via `pip` + venv (`python_bridge/requirements.txt`, `ui/requirements.txt`).

**Is it a C++ core plus a separate frontend?** Yes. It is a **C++ engine core** plus a **separate Python advisory-service + Dash UI tier**. They communicate two ways:

1. **Shared SQLite DB (primary, asynchronous).** The C++ engine is the *sole writer* of operational tables; the Dash UI (`ui/db.py`, opened `mode=ro`) and Python services *read*. The UI's only writes are manual weight overrides and the L1-config editor — neither touches the RiskGate. (`README.md:70-73`, `ui/db.py:1-7`.)
2. **JSON-over-HTTP bridge (optional, synchronous).** `python_bridge/server.py` (stdlib `http.server` on `:8765`) exposes `/score/llm`, `/score/dnn`, `/score/whale`, `/marketdata/alpaca`, `/execute/alpaca_paper`. The C++ engine calls it **only when launched with `--bridge`** — `EngineOptions.use_bridge` defaults to `false` (`core/engine.hpp:33`, `core/main.cpp:62-68`).

There is also a desktop wrapper (`ui/desktop.py`, pywebview + system tray) and a PyInstaller spec (`ui/MarketAILab.spec`) for a Windows `.exe`.

## 2. Build status

**It builds cleanly, right now.** Toolchain here: cmake 4.2.3, g++ 15.2.0, system SQLite3 3.46.1.

```
configure_exit=0
build_exit=0
error:/warning: count = 0        # clean under -Wall -Wextra
-> produces mal_engine + test_config + test_risk_gate + test_weights
```

**C++ unit tests:** `ctest` → **5/5 pass** (`risk_gate`, `config`, `weights`, `strategy`, `tuner_minsample`).

**Python:** the **full suite now runs green in the project venv — 124 passed** (Python 3.14.4 with the pinned `python_bridge/requirements.txt` + `ui/requirements.txt`; `rl_advisory` env tests need only `gymnasium`, torch/SB3 stay lazy/optional). Both trainers were exercised against the demo DB: `python -m ml_factor.train_real` refuses with `insufficient_real_data` (0 real samples < 200; synthetic champion retained), and the RL trainer refuses below its real-fill gate — both with clear messages and no synthetic fallback for RL.

## 3. The four layers

### Layer 1 — Static safety (RiskGate) — **FULLY IMPLEMENTED** ✅
- `risk/risk_gate.hpp` / `risk/risk_gate.cpp`. Pure, deterministic, side-effect-free gate; **14 hard checks**: kill-switch/manual-resume/cooldown, daily-loss total + per-venue, per-trade notional cap, total open risk, position counts (total + per-venue), exposure per symbol/market/category, consecutive losses, confidence/edge/agreement/staleness gates, and a live hard-stop on loss breach (`risk/risk_gate.cpp:16-97`).
- **Wired as final authority:** every order in the loop passes `gate_->evaluate(o, pstate_)` before any routing (`core/engine.cpp:219`); denials are persisted to `blocked_trades` (`:222-228`).
- **Kill switch:** latching state machine with manual-resume requirement (`risk/risk_gate.cpp:99-114`); trips on daily-loss breach in the loop (`core/engine.cpp:291-299`).
- **Live-trading gate:** `ModeRouter::route` refuses the `Live` branch unless `live_enabled` is true, and `DisabledLiveAdapter::place` refuses unconditionally (`execution/execution.cpp:101-116`, `:148-162`). See §6.
- **Tested:** 12 scenarios incl. the kill-switch state machine, all passing (`tests/test_risk_gate.cpp`).

### Layer 2 — Adaptive strategy — **IMPLEMENTED (bounded, real-fill gated)** ✅
- `learning/adaptive.{hpp,cpp}`. Nudges ensemble weights toward better-performing factors (clamped to `max_single_weight`, skips locked/disabled), records every change to `param_history`, supports `rollback_last`.
- **Structural safety invariant:** `validate_not_weakening_limits` rejects any risk-config change that would enlarge a loss/exposure ceiling, shrink a quality gate, or disable a safety toggle (`learning/adaptive.cpp:17-70`).
- **Now learns from real fills:** the toy `simulate_outcome` RNG driver is gone. The tuner attributes the **realized win/loss of each closed paper trade** to the factors whose direction agreed with the move (`core/engine.cpp:297+`), and it only runs once at least **30 closed trades** exist — `learning/adapt_gate.hpp:15` (`kMinClosedTradesForAdapt = 30`), enforced at `core/engine.cpp:652`. Below the gate it stays inert rather than learning against noise (covered by the `tuner_minsample` C++ test).

### Layer 3 — dnn_advisory (supervised) + rl_advisory (PPO, shipped off) — **PARTIALLY IMPLEMENTED** ⚠️
- `ml_factor/model.py`: a **real NumPy MLP** — shared ReLU trunk + 5 heads (direction softmax, edge regression, regime softmax, risk logistic, scale sigmoid). Ships a committed champion (`ml_factor/models/champion.npz`). Advisory sizing hint hard-capped at 0.5 (`ml_factor/factor.py:36-52`).
- **Real-data trainer now exists:** `ml_factor/train_real.py` builds a labelled dataset from real closed trades, validates it **walk-forward** (expanding chronological folds — never a random split), records a *challenger* in `model_registry` with explicit `provenance="real-data"`, and promotes only via `registry.meets_promotion_criteria` + an explicit operator call (`dnn_auto_promote_if_better: false`). Verified: against the demo DB it refuses with `insufficient_real_data` (0 real samples < 200) and keeps the synthetic champion — an honest refusal, not a silent synthetic promotion.
- **RL is now its own module — `rl_advisory/` (Stable-Baselines3 PPO), SHIPPED OFF.** Gym `TradingEnv` (rolling-window obs, discrete flat/long/short, reward = realized PnL − mandatory txn cost − drawdown penalty), a hard `rl_min_real_fills` gate (default 500) that **refuses before importing any backend**, **no synthetic-data training path**, walk-forward eval + champion/challenger via the shared promotion gate, and a `/score/rl` bridge endpoint with a labelled mock fallback. `rl_enabled` defaults false → the engine never calls it and the factor stays out of the ensemble entirely (`rl_advisory_factor_weight = 0.0`).
- **Still honest about the ceiling:** the *shipped* Layer-3 signal is the synthetic-trained MLP; no real-data DNN challenger has been promoted (not enough real samples yet), and no RL policy has been trained (real-fill gate unmet). The referenced optional PyTorch trainer for the MLP (`train_torch.py`) still does not exist.

### Layer 4 — Whale / smart-money advisory — **PARTIALLY IMPLEMENTED** (most complete Python advisor) ⚠️
- `whale_signal/adapters.py`: **3 adapters** (ClankApp default, Whale Alert optional, SEC EDGAR 13F) each with a **real `requests` live-fetch path** *and* a deterministic mock fallback that never raises offline. The Apify Polymarket adapter was removed with Polymarket (2026-07-06). `whale_signal/scoring.py`: real scorer — value×actor-usefulness weighting, noisy-actor filtering, delayed-disclosure down-weighting (×0.4), contradiction flag, regime label. Advisory cap 0.35.
- **Live is OFF by default:** every live fetch is gated — ClankApp/Whale Alert behind `WHALE_LIVE_ENABLED`, SEC EDGAR behind `SEC_EDGAR_ENABLED`, both default false. The SEC User-Agent contact is read from the environment (`SEC_EDGAR_CONTACT_EMAIL`), never committed.
- **Caveats:** the live-fetch parsers defensively probe **undocumented/assumed response shapes** and are **still unverified against most live payloads**. There is now **one real recorded fixture** — a genuine SEC EDGAR 13F capture (`tests/fixtures/sec_edgar_13f_sample.json`, 5 hits, delayed-disclosure), and the parser test asserts against it; **ClankApp remains synthetic** (its host was DNS-unreachable here, marked SYNTHETIC in the fixture header). `actor_usefulness` is still a **SHA-256 hash stand-in**, not a learned hit-rate (`whale_signal/scoring.py:39-45`).

### ⚠️ Cross-cutting reality check for Layers 3–4 (and the LLM council)
In the **default engine run (no `--bridge`), the factor *scores* — `llm_*`, `dnn_advisory`, `whale_signal` — are still in-process deterministic C++ mocks** (`core/engine.cpp`, `mock_factor`). The sophisticated Python implementations are reached **only** when the engine is started with `--bridge` and `python_bridge/server.py` is running. What *has* become real on the default path is the **learning signal**: the tuner now trains on realized closed-trade PnL (§Layer 2), not a toy simulator. So out of the box the *advisory verdicts* are momentum-shaped deterministic stand-ins, but the *adaptation* they feed is grounded in real fills. `rl_advisory` is absent from this path entirely until `rl_enabled` is turned on.

## 4. LLM council integration

**There is no external LLM API code anywhere.** `git grep` for `openrouter|api.anthropic|api.openai|generativelanguage|import openai|import anthropic|google.generativeai` → **zero hits**.

- The three council slots are all `MockLLMProvider` (deterministic, hash-derived) — `llm_consensus/consensus.py:148-162`.
- `OpenAIProvider.score()` **raises `NotImplementedError`** if `OPENAI_API_KEY` is present, and returns a mock otherwise (`llm_consensus/consensus.py:107-123`). It is never selected by `default_providers()` anyway.
- **It does NOT use OpenRouter** — nor any direct provider API. It uses nothing. The ensemble math (weighted bias/confidence/edge, agreement count, per-model verdicts) is real; the "intelligence" is not.

**Exact model strings found** (labels only — config-driven "single source of truth", surfaced in the UI and attached to verdicts; they reach a real API only with keys + `--bridge` + `use_real_council`): `config/default_config.yaml:255-259`
```
llm_models:
  llm_primary:   gpt-5.5
  llm_secondary: claude-opus-4-8
  llm_tertiary:  gemini-3.1-pro
  llm_gate:      claude-haiku-4-5  # base-check gate (Anthropic client)
```
**Model strings now correct** (the earlier drift is fixed): they match the four approved strings in `CLAUDE.md` exactly, and the base-check gate `claude-haiku-4-5` is present.

**Council cost controls (real, tested):** beyond the token cap / daily budget / per-symbol cooldown, two cuts now fire **before any provider spend** in `llm_consensus/consensus.py`: (1) a **risk pre-check** — when the engine's read-only RiskGate already blocks the trade, the council is skipped entirely (logged `risk_precheck`); (2) a **market-hours skip** — equities (SPY, QQQ) skip the gate+council outside US regular trading hours while crypto stays 24/7 (logged `market_hours`, config `engine.equities_market_hours_only`, default true). Covered by `tests/test_council_cost_cuts.py`.

## 5. Venue integrations

| Venue | Status | Evidence |
|---|---|---|
| **Alpaca** | **REAL — paper + market data only** | `market_data/alpaca_source.py`: real HTTP to `data.alpaca.markets` (latest trades, equities `/v2/stocks/trades/latest` + crypto `/v1beta3/crypto`) and `paper-api.alpaca.markets` (`POST /v2/orders`), APCA auth headers, graceful degradation. Reached via bridge `/marketdata/alpaca` + `/execute/alpaca_paper` and `AlpacaPaperAdapter` (`execution/execution.cpp:42-89`). **No live-brokerage path** — paper/data key only. |
| **Coinbase** | **Placeholder** | `CoinbaseSimAdapter` = sim fill; `// TODO: Coinbase …`. Env vars (`COINBASE_API_KEY/SECRET`) reserved in `.env.example`. Coinbase replaces Binance (Binance does not operate in Canada). |
| **IBKR** | **Live adapter wired, DISABLED behind the gate** | `IbkrLiveAdapter` (live-only) POSTs to the bridge `/execute/ibkr_live` only through the gated Live branch. Python `execution/ibkr_adapter.py` maps the order to an IBKR contract/order and places/cancels/reports status via `ib_insync` (imported lazily, pinned optional) against a locally run IB Gateway. No IBKR credentials pass through the app. A missing Gateway returns unavailable, never a simulated fill. `recommendation_only` mode + `live_enabled: false` keep it off this session. |

Polymarket was **removed** (region reasons, 2026-07-06): no adapter, routing, config, or whale source remains (guard: `tests/test_no_polymarket.py`). Alpaca's and Coinbase's **live** adapters are `DisabledLiveAdapter` (refuse). IBKR's live adapter exists but is unreachable while `live_enabled` is false and the approval gate is closed.

## 6. Paper vs live gating — the exact code path

Live is blocked by **four independent mechanisms**, and is currently **unreachable**:

1. **Config, validated at load:** `system.live_mode_default_enabled: false`, every venue `live_enabled: false`, modes are `paper`/`recommendation_only` (`config/default_config.yaml:13, 40-69`).
2. **Engine hardcodes it off:** the loop calls `router_.route(venue_cfg->mode, alp, live, o, /*live_enabled=*/false)` — the flag is a literal `false`. The paper adapter is always Alpaca; the live adapter is `IbkrLiveAdapter` for the `ibkr` venue and `DisabledLiveAdapter` otherwise, and the literal-false flag means neither live adapter is ever invoked.
3. **Router refusal:** `ModeRouter::route`'s `Live` case returns "live not enabled — refused" unless `live_enabled`; `DisabledLiveAdapter` refuses regardless (`execution/execution.cpp:148-162, 101-116`).
4. **Only enable path is gated:** `AccountManager::try_enable_live` sets `live_enabled=true` **only** if `approval_passed && credentials_connected && !kill_switch_tripped`, and `set_mode` refuses a direct switch to `Live` (`account_manager/account_manager.cpp:27-59`).

**Is it enforced or just a flag?** It is genuinely enforced — and stronger than "a flag": **`try_enable_live` is never called anywhere** (`git grep` finds only its definition + comments), and `set_approval_state` is only ever invoked once, at startup, with `(false, false)` (`core/engine.cpp:69`). Nothing in the system computes the `live_approval` readiness verdict or flips live on. The UI "Live" tab is **read-only** — it surfaces `approval_state`/`venue_state` but has no callback to enable live (`ui/app.py:1015-1070`).

➡️ **Net:** live trading cannot happen today. The flip side of that safety win: the **approval-gate *workflow* is not implemented end-to-end** — the seven `live_approval.*` checks (`config/config.hpp:105-113`) are parsed and displayed but never evaluated into an enable decision. It's scaffolding + a latent, uncalled enable function.

## 7. Dashboard / UI

- **Framework:** Plotly **Dash** (Python), `ui/app.py` (1,767 lines). No JS/TS/HTML in the repo.
- **Tabs:** **Paper** (default; broker-style hero, stat cards, equity/positions/activity, filtered to `mode=='paper'`), **Live** (locked; surfaces the approval gate, zeros when live off), **Advanced** (all technical panels: equity/daily-PnL/drawdown/trade-PnL/calendar/allocation/exposure/weights/learning/DNN/whale charts, model verdict board, **adjustable weight control panel**, **L1 risk-gate editor with typed `CONFIRM`**, approval readiness, venue state, model registry, trades, blocked trades, weight/param history, event log), **Accounts/Connections** (credential entry per venue paper/live + per data source).
- **How it gets data:** reads the shared SQLite DB via `ui/db.py` (read-only, `mode=ro`), refreshing on `dcc.Interval` (5 s). The C++ engine writes; the UI reads. UI write paths (weight overrides, L1-config edit, credential save, `credentials_connected`) are explicitly incapable of weakening the RiskGate (`ui/db.py:252-281`, `ui/app.py:542-605`).

## 8. Data layer

**SQLite, plain.** `storage/schema.sql` defines **14 tables** in WAL mode: `events` (append-only audit log — never updated in place), `trades`, `positions`, `signals`, `model_outputs`, `model_registry`, `param_history`, `weight_changes`, `whale_activity`, `whale_signal_history`, `approval_state`, `venue_state`, `account_balances`, `blocked_trades`. C++ RAII DAO in `storage/storage.{hpp,cpp}` (links `libsqlite3`); it is the single source of truth. The DB file is gitignored and regenerated by `ops/demo.py`.

**Not a time-series DB** — no InfluxDB/Timescale/Parquet; market data is not persisted as history beyond `signals`/`trades`/`account_balances` snapshots. Fine for this scale; a real research loop on real data would outgrow it.

## 9. Config and secrets

- **Config:** YAML (`config/default_config.yaml`, `config/example_live_disabled.yaml`) parsed by a hand-rolled C++ YAML-subset parser (`config/yaml.cpp`) into typed structs and **strictly validated at load** (`config::load_config` throws on unsafe values). `config/schema.md` documents fields.
- **Secrets handling:** **keys are never stored in YAML** — config references only env-var *names* (`config/default_config.yaml:183-199`). Single runtime resolver `account_manager/credentials.py`: in-app **encrypted store first** (Fernet; `.keystore/credentials.sqlite`, key at `.keystore/secret.key`, `0600`), then env/`.env`. Values are masked in the UI (`_mask` → `••••••••`) and never logged.
- **Any keys hardcoded / committed?** **No.** `.gitignore` excludes `.env`, `*.key`, `*.pem`, `.keystore/`, `*.db`. `git grep` for hardcoded key material (`sk-…`, `AKIA…`, `-----BEGIN`, inline `api_key=`) → **nothing**. The only "credential"-named tracked files are the code module, a design doc, and a test. `.env.example` contains empty placeholders only. ✅ Clean.

## 10. Tests

- **C++ (CTest) — runs and passes:** `risk_gate` (12 scenarios incl. kill-switch latch/resume), `config` (validation invariants), `weights` (normalization/locking). Hand-rolled `check()/report()` harness (`tests/test_util.hpp`) — no GoogleTest dependency.
- **Python (pytest) — 6 files, well-structured (AAA):** `test_whale_signal.py` (12 tests), `test_ml_factor.py`, `test_llm_consensus.py`, `test_credentials.py` (encryption round-trip + in-app-overrides-env precedence), `test_config_editor.py`, `test_weight_tuner.py`. **Not runnable in this environment** (needs the venv deps); the stdlib modules do execute.
- **Coverage gaps:** **nothing** tests the C++ engine loop/orchestration, the storage DAO, the bridge server, the Dash UI callbacks, or the Alpaca/whale **HTTP clients** (no mocked-network or integration tests). No coverage measurement is wired. Against the whole tree this is well under an 80% bar — though the single most safety-critical unit (RiskGate) is thoroughly covered.

## 11. Prioritized gap list

> Note: the **default offline paper loop already works** (mock feed, deterministic) — so little *blocks* the mock loop. These gaps are ordered by what stands between the current state and a *meaningful* paper-trading loop (real data + real advisors) that matches the advertised architecture.

1. **Advisory layers are off the default path.** Real LLM/DNN/whale run only with `--bridge` + the bridge server up; otherwise the engine uses C++ mocks (`core/engine.cpp:105-127`). Either make the bridge the default or state plainly that "AI engages only with the bridge." Highest-leverage fix.
2. **LLM council is mock on the default path.** Real OpenAI/Anthropic/Google providers exist behind keys + `--bridge` + `use_real_council`, but the out-of-box run is deterministic mocks. Model strings are now correct (§4); the remaining gap is exercising the real providers against live keys. Biggest gap versus the pitch.
3. **dnn_advisory ships the synthetic champion.** A real-data trainer with walk-forward validation + gated promotion now exists (`train_real.py`), but no real challenger has been promoted yet because the DB lacks enough real labelled samples; the shipped MLP is still synthetic-trained, and `train_torch.py` still does not exist. RL (`rl_advisory`) is built but shipped off and untrained (real-fill gate unmet).
4. **Live-approval workflow not wired.** `try_enable_live` is never called; the 7 `live_requires_*` checks are never evaluated into a decision. Safe today, but the feature is incomplete.
5. **Real execution is Alpaca-paper only.** Coinbase is a sim. IBKR has a wired live adapter but it is unreachable while live is disabled behind the gate. Live HTTP paths (Alpaca paper + IBKR live + all whale adapters) are unverified against real payloads and have no integration tests. The IBKR adapter is covered by unit tests with a fake `ib_insync` (mapping, place/cancel/status, connection loss), not against a real Gateway.
6. **~~Adaptive layer learns from a toy simulator.~~ RESOLVED.** The tuner now learns from realized closed-trade PnL, gated until ≥30 closed trades (`learning/adapt_gate.hpp`); the `simulate_outcome` RNG driver is gone (`tuner_minsample` test covers the gate).
7. **Test/coverage holes (narrowing).** The Python suite now runs green in the venv (**124 passed**) and RL-env / cost-cut / real-fill-gate paths are covered with mocked HTTP. Still no tests for the C++ engine loop, storage DAO, bridge server, Dash UI callbacks, or the Alpaca/whale **live HTTP clients** (one recorded SEC fixture aside); no coverage gate wired; overall still below 80%.
8. **`news_ingestion` is a stub.** Mock catalyst scoring only; real providers are TODO (`news_ingestion/fetchers.py:7, 32`). Minor.

---

### What is genuinely good (so this isn't only a list of holes)
- The **C++ core is well-architected and honest**: pure deterministic RiskGate as final authority, a structural "adaptive can never weaken a hard limit" invariant, clean RAII SQLite DAO, an append-only audit log, graceful-degradation everywhere, builds warning-free, and a passing safety test suite.
- **Secret hygiene is correct** (encryption at rest, env fallback, masking, nothing committed).
- The **README is unusually accurate** and up-front about its TODOs — the code matches the prose far more than is typical for projects at this stage.
