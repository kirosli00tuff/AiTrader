# Market AI Lab

A C++20-first, modular, multi-venue **24/7 paper-trading research + execution
system**. It blends a multi-LLM consensus, a rule-based factor, a DNN/RL
advisory factor, and a whale/smart-money advisory factor into one weighted
ensemble — then routes every proposed order through a **deterministic Layer-1
RiskGate** before (paper) execution. A Plotly Dash control board visualizes and
controls everything from the shared SQLite database.

> **Live trading is DISABLED by default on every venue** and can only be enabled
> through an explicit in-app approval gate. The static safety layer is the final
> authority and is never bypassable.

The entire system runs **fully offline with no API keys** — every external data
source has a deterministic mock fallback.

---

## Table of contents

- [Architecture](#architecture)
- [Safety model (the four layers)](#safety-model-the-four-layers)
- [Repository layout](#repository-layout)
- [Quick start (one command)](#quick-start-one-command)
- [Run it 24/7 locally](#run-it-247-locally)
- [Manual build & run](#manual-build--run)
- [The dashboard](#the-dashboard)
- [Advisory services](#advisory-services)
- [Whale / smart-money sources](#whale--smart-money-sources)
- [Configuration & secrets](#configuration--secrets)
- [Testing](#testing)
- [Database schema](#database-schema)
- [TODOs (Binance / IBKR)](#todos-binance--ibkr)

---

## Architecture

```
                 market data + news (mock or live)
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                            │
   Advisory factors                            Rule-based factor
   ─ multi-LLM consensus  (llm_consensus)            │
   ─ DNN / RL             (ml_factor)                 │
   ─ whale / smart-money  (whale_signal)              │
        │                                            │
        └──────────────► weighted ensemble ◄─────────┘   (signal_engine)
                              │  CombinedVerdict {bias, confidence, edge}
                              ▼
                   ┌────────────────────┐
   Layer 2  ──────►│  Layer 1 RiskGate  │  deterministic, FINAL authority
   adaptive tuner  │  (risk/)           │  (never weakened by Layer 2)
   (learning/)     └─────────┬──────────┘
                             │ approved? sized?
                             ▼
                   ModeRouter (execution/)  disabled│reco│paper│live
                             │ live guarded by approval gate + kill switch
                             ▼
                   Paper adapters (Polymarket, Alpaca, …)
                             │
                             ▼
                   SQLite (storage/) ── single source of truth
                             │
                             ▼
                   Plotly Dash control board (ui/)
```

The C++ core is the sole writer of operational tables; the Python advisory
services are reached either in-process (demo seeding) or over a small
JSON-over-HTTP **python_bridge**. The Dash UI is a reader (its only write path
is manual ensemble-weight overrides, which never touch the RiskGate).

See `docs/ARCHITECTURE.md` and `docs/DNN_RL_DESIGN.md` for the authoritative
design.

## Safety model (the four layers)

1. **Layer 1 — Static Safety (`risk/`).** A pure, deterministic `RiskGate`
   enforces the hard limits in the `risk:` config block: daily-loss caps,
   per-trade / total / position / exposure caps, confidence/edge/agreement/
   staleness gates, the kill switch, and a hard stop for live on loss breach.
   **This layer is the final authority and is never bypassable.**
2. **Layer 2 — Adaptive (`learning/`).** May tune parameters and ensemble
   weights *within* safe ranges. Every change is logged with rollback. It is
   structurally incapable of weakening a hard limit
   (`validate_not_weakening_limits`).
3. **Layer 3 — DNN / RL (`ml_factor/`).** Advisory only. Emits exactly
   `dnn_action_bias, dnn_confidence, dnn_expected_edge, dnn_regime_label,
   dnn_risk_flag, dnn_position_scale_hint`. Sizing hint hard-capped at **0.5**.
4. **Layer 4 — Whale / smart-money (`whale_signal/`).** Advisory only. Emits
   `whale_bias, whale_confidence, whale_flow_direction, whale_activity_score,
   whale_follow_signal, whale_contradiction_flag, whale_regime_label`. Sizing
   capped at **0.35**. Delayed (13F) evidence is down-weighted and labelled.

Live enablement requires passing **all** `live_approval:` checks (connected
credentials, kill switch configured, visible recent performance, positive paper
expectancy, drawdown below threshold, explicit manual confirmation).

## Repository layout

| Path | Module | Language |
|------|--------|----------|
| `config/` | YAML parser + typed config structs + validation | C++ |
| `storage/` | SQLite schema + RAII DAO | C++ |
| `risk/` | Layer-1 deterministic RiskGate + kill switch | C++ |
| `learning/` | Layer-2 bounded adaptive tuner | C++ |
| `signal_engine/` | weighted factor combination + weight state | C++ |
| `market_data/` | feed abstraction + deterministic mock feed | C++ |
| `news_ingestion/` | catalyst scoring (+ Python fetcher stubs) | C++/Py |
| `account_manager/` | per-venue state + live-enable gating | C++ |
| `execution/` | venue adapters + mode router | C++ |
| `core/` | engine loop, bridge client, CLI entry | C++ |
| `tests/` | CTest C++ unit tests + pytest Python tests | C++/Py |
| `llm_consensus/` | multi-LLM consensus advisory service | Python |
| `ml_factor/` | NumPy DNN advisory factor + registry + trainer | Python |
| `whale_signal/` | Apify / Whale Alert / SEC-13F adapters + scoring | Python |
| `python_bridge/` | JSON-over-HTTP RPC server + client | Python |
| `ui/` | Plotly Dash control board | Python |
| `ops/` | `run_demo.sh`/`demo.py` offline demo; `start.sh`/`start.bat`/`stop.sh` 24/7 local launchers | Bash/Bat/Py |

## Quick start (one command)

Requires `cmake`, a C++20 compiler, `libsqlite3-dev`, and Python 3.11+.

```bash
ops/run_demo.sh
```

This builds the C++ engine, creates a venv, installs the UI + bridge
requirements, runs the paper loop to seed SQLite, populates the whale tables,
then launches the dashboard at <http://127.0.0.1:8050>. No API keys needed.

Seed only (no dashboard):

```bash
ops/run_demo.sh --no-dash
ITER=40 ops/run_demo.sh           # custom iteration count
```

## Run it 24/7 locally

The finite demo above runs a fixed number of ticks and exits. To keep the engine
trading **continuously, in real time, on your own desktop**, use the one-click
launchers. They build the engine if needed, set up the venv, start the
`python_bridge` and the C++ engine in **continuous (24/7) paper mode** in the
background, then open the dashboard at <http://localhost:8050>.

```bash
ops/start.sh                       # macOS / Linux — mock feed, offline-safe
ops\start.bat                      # Windows
```

```bash
ops/stop.sh                        # clean shutdown (engine finishes its tick, flushes, exits)
```

Real-time **Alpaca** market data (stocks + crypto) needs only a **paper / data
key — NOT a live brokerage account**, so it works from regions where Alpaca live
trading is unavailable (e.g. Canada):

```bash
# Put ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET in .env (see .env.example),
# or save them on the in-app Accounts/Connections page, then:
DATA_SOURCE=alpaca ops/start.sh
INTERVAL=10 DATA_SOURCE=alpaca ops/start.sh   # override the loop interval (s)
```

**Offline / no-key behavior is automatic.** If the bridge is unreachable or a
symbol has no quote, the feed advances that symbol with a deterministic walk; if
the Alpaca paper API is unreachable/unauthorized/geo-blocked, orders fall back to
a **sim-at-live-price** fill (marked in the trade note). Either way the engine
keeps ticking and **live trading stays DISABLED** behind the approval gate.

The continuous loop runs `--continuous` with `engine.loop_interval_seconds`
between ticks. With `engine.respect_market_hours: true` it skips US-equity ticks
when the regular session is closed, while crypto and prediction markets keep
trading 24/7. `SIGINT`/`SIGTERM` (Ctrl-C or `ops/stop.sh`) trigger a graceful
shutdown: the current tick completes, state is flushed to SQLite, and it exits 0.

Directly, without the launcher:

```bash
build/mal_engine --continuous --data-source alpaca \
                 --interval-seconds 15 --bridge 127.0.0.1:8765 \
                 --db market_ai_lab.db --schema storage/schema.sql
```

## Desktop app (.exe) — true 24/7 Windows application

For a real desktop experience, Market AI Lab ships as a native Windows app: a
single `MarketAILab.exe` that opens a **native OS window** (not a browser tab)
showing the full dashboard, while supervising the C++ engine + `python_bridge`
in the background so the system keeps trading **24/7**.

* **Native window** via pywebview (uses the built-in Windows WebView2 runtime).
* **System-tray icon** with: *Open dashboard*, *Engine: start/stop*, *Quit*.
* **Close-to-tray:** closing the window does **not** stop trading — it hides to
  the tray and the engine keeps running. The app only fully exits via tray ->
  *Quit*, which cleanly stops the engine and bridge.
* **Self-healing:** if the engine or bridge crashes, the supervisor restarts it.
* Launches the engine with the same `--continuous` paper-mode flags as the
  launchers above, so **live trading stays DISABLED** and Layer-1 safety remains
  the final authority.

### Run from source (any OS, for development)

```bash
pip install -r ui/requirements.txt -r ui/requirements-desktop.txt
python ui/desktop.py
```

### Linux / Ubuntu desktop app (pin to dock + autostart 24/7)

On Ubuntu you run the app from source (no `.exe`) and install a proper desktop
launcher you can pin to the dock/taskbar and start automatically at login.

**1. Install OS prerequisites** (build tools + the GTK WebKit backend that the
native window needs):

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3-venv python3-pip \
    libsqlite3-dev \
    python3-gi gir1.2-webkit2-4.1 gir1.2-gtk-3.0 \
    libcairo2-dev libgirepository1.0-dev pkg-config
```

**2. Build** (one command — builds the C++ engine, creates the venv, installs
deps, generates the icon). It will print the exact `apt` line if anything is
still missing:

```bash
git clone https://github.com/kirosli00tuff/AiTrader.git
cd AiTrader
bash ops/build_linux.sh
```

**3. Install the launcher + pin to the taskbar:**

```bash
bash ops/install_desktop.sh
```

Then open *Market AI Lab* from your app grid (Activities / Show Apps). While
it's running, right-click its dock icon and choose **Pin to Dash** /
**Add to Favorites** to keep it on your bottom taskbar for one-click launch.

**4. Autostart 24/7 at login** (optional):

```bash
bash ops/install_desktop.sh --autostart
```

The app then launches automatically every time you log in and keeps trading in
the background (close the window -> hides to tray; quit only from the tray).
To stop autostart later: `rm ~/.config/autostart/market-ai-lab.desktop`.
To remove the launcher entirely: `bash ops/install_desktop.sh --uninstall`.

> GNOME note: the system-tray icon needs the *AppIndicator and KStatusNotifier*
> Shell extension (`sudo apt install gnome-shell-extension-appindicator`, then
> enable it). Close-to-background and the window still work without it; the
> tray menu just won't show until the extension is enabled. To run the app
> straight away without installing a launcher, use `ops/run_desktop.sh`.

### Build the Windows .exe (one command)

```bat
ops\build_exe.bat
```

This (1) builds the C++ engine with **MSVC / CMake** in Release, (2) creates a
venv and installs the UI + desktop + bridge deps, and (3) runs **PyInstaller**
(`ui/MarketAILab.spec`) to produce `dist\MarketAILab.exe` bundling the Dash UI,
the Python advisory services, the icon, and the engine. Double-click the result
to launch the 24/7 app.

**Prerequisites (install once):**

* **Visual Studio Build Tools 2022** -> *Desktop development with C++* workload
  (provides MSVC, the Windows SDK, and CMake). Run `build_exe.bat` from a
  *Developer Command Prompt for VS 2022* so `cl.exe` is on `PATH`.
* **Python 3.12 64-bit** (3.13 also works) with *Add to PATH* checked.
* **Git for Windows**. WebView2 runtime is built into Windows 10/11.

### Building on a non-C: drive (e.g. E:) / low disk space

The venv + PyInstaller scratch need **~5-10 GB free**. If your `C:` drive is
full, put the whole project on another drive and redirect the build's temp
folder there too. Note MSVC itself still installs on `C:` (one-time, ~3-6 GB),
so keep a little `C:` headroom for the toolchain.

```bat
REM 1. Put the repo on E:
E:
cd E:\
git clone https://github.com/kirosli00tuff/AiTrader.git
cd E:\AiTrader

REM 2. Redirect build temp to E: (multi-GB PyInstaller/pip scratch)
mkdir E:\maltmp
set TEMP=E:\maltmp
set TMP=E:\maltmp

REM 3. Build (venv, build\, dist\ all land on E: automatically)
ops\build_exe.bat
```

Use a real fixed/SSD drive (not a slow USB stick or network drive). Verify the
repo's location any time with `git rev-parse --show-toplevel`.

### Keep it running 24/7 (auto-start at logon)

To have the app start automatically and trade around the clock:

* **Startup folder (simplest):** press `Win+R`, type `shell:startup`, and drop a
  shortcut to `dist\MarketAILab.exe` in the folder that opens. It launches at
  every logon (and minimizes to the tray).
* **Task Scheduler (more control):** create a task -> trigger *At log on* ->
  action *Start a program* -> point at `MarketAILab.exe`, and tick *Run with
  highest privileges* if needed.
* **Prevent sleep** so it keeps trading overnight:

  ```bat
  powercfg /change standby-timeout-ac 0
  powercfg /change monitor-timeout-ac 10
  ```

## Manual build & run

```bash
# 1. Build the C++ core
cmake -S . -B build
cmake --build build -j
ctest --test-dir build --output-on-failure      # Layer-1 / config / weights tests

# 2. Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r python_bridge/requirements.txt -r ui/requirements.txt

# 3. Run the paper loop (seeds market_ai_lab.db)
build/mal_engine --config config/default_config.yaml \
                 --db market_ai_lab.db --schema storage/schema.sql --iterations 25

# 4. (optional) seed whale tables + registry, or just launch the UI
python ops/demo.py --no-dash        # full offline seeding incl. whale data
MAL_DB_PATH=$PWD/market_ai_lab.db python ui/app.py   # dashboard only
```

Run with the live python_bridge instead of in-process mocks:

```bash
python -m python_bridge.server &                       # serves :8765
build/mal_engine --bridge 127.0.0.1:8765 --iterations 25
```

## The dashboard

`ui/app.py` reads the shared SQLite DB and refreshes via `dcc.Interval`
(default 5 s, from `dashboard.dashboard_refresh_seconds`). Panels:

- **Performance** — equity curve, daily realized PnL, drawdown %, trade-by-trade
  PnL (+ cumulative), win/loss calendar heatmap
- **Allocation / exposure** — venue allocation pie, exposure by symbol/market
- **Models** — verdict-comparison board (verdict / confidence / edge / weight),
  factor-weight contribution chart, weight-change history table, and an
  **adjustable model-weight control panel** (numeric inputs, per-factor lock,
  reset-to-defaults; auto-normalized)
- **Learning** — Layer-2 param-change history table, before/after chart, DNN/RL
  performance chart, model registry (champion/challenger)
- **Whale** — recent whale activity table, whale-signal history chart,
  whale-agreement-vs-outcome chart
- **Trading** — recent trades, open positions, blocked/rejected (RiskGate) table
- **Safety** — live-approval readiness panel, venue-state table, append-only
  event log

The weight control panel is the UI's only writer: it appends to `weight_changes`
and mirrors normalized weights to `ui/weight_overrides.json`. Adjusting weights
only re-blends advisory factors — it can never weaken the deterministic RiskGate.

## Advisory services

- **`llm_consensus`** — `consensus(state)` returns a weighted ensemble verdict
  (`bias, confidence, edge, verdict, agreement_count, per_model`). Three mock
  providers map to the C++ factor names `llm_primary/secondary/tertiary`;
  `OpenAIProvider` is scaffolded to drop in a real key and falls back to mock.
- **`ml_factor`** — a small NumPy MLP (`DnnModel`) with multi-task heads. A tiny
  champion (`ml_factor/models/champion.npz`) is shipped and auto-trains on first
  use. `score_state(state)` emits the named DNN fields plus bridge aliases and
  caps the sizing hint. Champion/challenger promotion is gated (`registry.py`).
  PyTorch is intentionally optional (commented in requirements) so install/tests
  stay green; the shipped model is NumPy-based.
- **`whale_signal`** — three source adapters with offline mocks + value/usefulness
  weighting, noisy-actor filtering, delayed-disclosure down-weighting, and a
  contradiction flag.

## Whale / smart-money sources

| Source | Adapter | Notes |
|--------|---------|-------|
| Apify Polymarket whale-tracker | `ApifyWhaleAdapter` (`apimie/polymarket-whales-trader`) | needs `APIFY_TOKEN`; mock otherwise |
| Whale Alert API | `WhaleAlertAdapter` | crypto-only, ≥ $500k; needs `WHALE_ALERT_API_KEY` |
| SEC 13F | `Sec13FAdapter` | **DELAYED** disclosure, equity-only, down-weighted; needs `SEC_API_KEY` |

Each adapter mocks deterministically when its key is absent, so the demo always
runs. 13F rows are flagged `delayed=1` everywhere and labelled **DELAYED** in the
UI — context, not live trade flow.

## Configuration & secrets

- `config/default_config.yaml` — safe defaults (live disabled everywhere).
- `config/example_live_disabled.yaml` — copy-and-run paper-only profile.
- `config/schema.md` — documentation of every config field.

**API keys are never stored in YAML.** Config only references env-var *names*
(`data_sources.*.token_env` / `api_key_env`). Put secrets in `.env` (see
`.env.example`); they are git-ignored. Enabling live trading is a separate
in-app approval action regardless of which keys are set.

### Accounts / Connections (in-app entry + .env fallback)

Credentials can be entered two ways, with a single runtime resolver
(`account_manager/credentials.py`) used everywhere a key is consumed:

1. **In-app** — the dashboard's **Accounts / Connections** tab lets you type and
   save keys/secrets per venue (Alpaca, Binance, IBKR, Polymarket) with
   **separate paper and live fields**, and per data source (Apify, Whale Alert,
   SEC API). Secret inputs are masked (`type=password`).
2. **Environment / .env** — the existing `*_env` names, plus paper/live-specific
   variants (e.g. `ALPACA_LIVE_API_KEY`, falling back to `ALPACA_API_KEY`).

**Resolution order for every secret: (1) in-app saved credential, else (2) env /
.env.** In-app values always override the environment.

In-app credentials are **encrypted at rest** with a locally-generated Fernet key.
The key lives in `.keystore/secret.key` (generated on first use, `0600`) and the
encrypted values in `.keystore/credentials.sqlite` — both git-ignored, and kept
separate from the operational DB so a demo reseed never wipes saved keys. Secret
values are never written to YAML/config and never logged; status reporting masks
them.

The Accounts page shows per-connection status (`in-app` / `from-env` / `missing`)
and an offline-safe **Test / validate connection** action (checks that required
credentials resolve; makes no network calls). Testing a venue's **live**
connection mirrors resolved readiness into `venue_state.credentials_connected`,
which is exactly what the C++ approval gate
(`live_requires_connected_credentials` → `try_enable_live`) checks — so the gate
honors the **resolved** live credential (in-app or env). This only reports
readiness; live trading remains disabled by default behind the full approval gate.

## Testing

```bash
ctest --test-dir build --output-on-failure     # C++: RiskGate, config, weights
source .venv/bin/activate && pytest tests/ -q   # Python: whale, ml_factor, consensus
```

C++ tests cover the deterministic RiskGate scenarios, config validation
invariants, and weight normalization/locking. Python tests cover whale scoring
(bias/flow/contradiction/delayed-downweighting/noisy-actor filtering), DNN IO
round-trip + sizing cap + named fields, LLM consensus determinism/shape, and the
credential resolver (encryption round-trip + in-app-overrides-env precedence).

## Database schema

`storage/schema.sql` defines 14 tables; `events` is an **append-only** audit log
(never updated in place). Key tables: `trades`, `positions`, `signals`,
`model_outputs`, `model_registry`, `param_history`, `weight_changes`,
`whale_activity`, `whale_signal_history`, `approval_state`, `venue_state`,
`account_balances`, `blocked_trades`. SQLite is the single source of truth shared
by the C++ writer and the Python/Dash readers.

## TODOs (Binance / IBKR)

The architecture is venue-agnostic; two venues are scaffolded but not yet
complete (search the codebase for `TODO:`):

- **Binance** — `execution/` `BinanceSimAdapter` runs simulated/paper only; the
  live adapter structure exists but live trading is not implemented. Env vars
  `BINANCE_API_KEY` / `BINANCE_API_SECRET` are reserved in `.env.example`.
- **IBKR** — `IbkrSimPlaceholderAdapter` is data/recommendation-only; full IBKR
  support (paper + live) is a follow-up. See `docs/FOLLOWUP_CREDENTIALS.md`.

Both remain `live_enabled: false` and route through the same Layer-1 RiskGate and
approval gate as every other venue.
