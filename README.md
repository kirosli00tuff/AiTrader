# Market AI Lab

A C++20-first, modular, multi-venue **24/7 paper-trading research + execution
system**. It blends a multi-LLM consensus, a rule-based factor, a `dnn_advisory`
(supervised DNN; RL deferred) advisory factor, and a whale/smart-money advisory factor into one weighted
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
- [Discovery funnel + dynamic watchlist (ships DISABLED)](#discovery-funnel--dynamic-watchlist-ships-disabled)
- [Adaptive real-time layer (ships DISABLED)](#adaptive-real-time-layer-ships-disabled)
- [Repository layout](#repository-layout)
- [Quick start (one command)](#quick-start-one-command)
- [Run it 24/7 locally](#run-it-247-locally)
- [Manual build & run](#manual-build--run)
- [The dashboard](#the-dashboard)
- [The React GUI (rebuilt, Alpaca-style, additive)](#the-react-gui-rebuilt-alpaca-style-additive)
- [Advisory services](#advisory-services)
- [Whale / smart-money sources](#whale--smart-money-sources)
- [Configuration & secrets](#configuration--secrets)
- [Testing](#testing)
- [Database schema](#database-schema)
- [TODOs (Coinbase / IBKR)](#todos-coinbase--ibkr)

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
                   Paper adapters (Alpaca, Coinbase)
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

See `docs/ARCHITECTURE.md` and `docs/DNN_ADVISORY_DESIGN.md` for the authoritative
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

## Native strategy: RSI-2 + momentum, regime-driven, two profiles

The native signal layer (`signal_engine/strategy.*`, closed-bar evaluation only)
blends two evidence-backed factors, switched by the regime detector, behind a
`strategy.profile` selector:

- **`swing` (default).** The current stack, unchanged. EMA fast/slow momentum
  crossover plus Bollinger mean reversion. Nothing changes unless you opt in.
- **`active_quant`.** Trades more actively but selectively. A **Connors RSI-2**
  mean-reversion factor: long only, only **above the 200-period trend MA** (buy
  dips inside a confirmed uptrend), on RSI-2 below a config entry threshold
  (crypto 10, equity 5), with an optional **cross-back confirmation**, an **ATR
  volatility band**, and a **volume filter**. It exits on the RSI-2 cross above
  `rsi2_exit` (65 to 70), plus the RiskGate stops and the ATR target. Momentum
  gains a **dual-MA trend filter** (price above a medium and a long MA) for
  trending regimes.

The **regime detector selects which factor leads**: trending favors momentum,
range-bound favors RSI-2, neutral blends. The two profit in opposite regimes,
which smooths the equity curve. The engine persists the regime and the active
factor per symbol for the GUI.

**Two-tier execution (cost-bounded).** Small, low-conviction entries take the
**fast tier**: native signal plus RiskGate only, no council call. Larger or
higher-conviction entries take the **council tier**: gate then council then
RiskGate. A hard **spend ceiling** (`council_daily_spend_ceiling_usd`,
`council_monthly_spend_ceiling_usd`) forces the fast tier when reached, so a
month of `active_quant` stays near or under **100 dollars** (projected ~$20 to
$48). Both tiers respect every Level-1 limit and use native ATR exits.

**Crypto stop.** Crypto uses a wider volatility stop (`crypto_atr_stop_mult`,
default 2x) since crypto sees large two-day selloffs even in uptrends. Equities
keep the existing ATR stop. Every stop stays inside the RiskGate's authority; the
RiskGate keeps its own stops unconditionally, so no native stop weakens a limit.

**Honest expectations.** Realistic target Sharpe is roughly 1.4 to 1.7 with
drawdowns consistent with the Level-1 limits. Any result implying Sharpe above 3
signals a methodology error to investigate, not a win. Realized PnL charges a fee
before it reaches the tuner and the DNN training data, so both learn net of cost.

Select the profile in `config/default_config.yaml` (`strategy.profile:
active_quant`); the `active_quant:` block holds the overriding thresholds,
whitelist, budget, cooldown, and spend ceiling. Every value is operator-tunable
and none touches a Level-1 risk limit.

## Core-satellite hybrid (two sleeves)

The portfolio splits into two sleeves with distinct roles:

- **`quant_core` (systematic core, 70%).** Runs the RSI-2 + momentum stack
  above. Frequent, selective, systematic.
- **`research_satellite` (tactical satellite, 30%).** Uses the LLM council for
  **deep research** on individual instruments, taking **fewer, larger,
  longer-held** positions. Each pass produces a structured thesis (direction,
  conviction, horizon, rationale) persisted with the position. Ships **OFF by
  default** — the operator opts in, and it earns a wider allocation only through
  paper results (the same graduate-when-proven discipline as RL).

**30% is a ceiling, not a floor.** The satellite may sit anywhere at or under it.
It is never *entitled* to its target: widening it from 20% states intent for when
the sleeve earns the allocation, it does not decide that it has.

**The split is enforced mechanically.** The satellite can **never exceed its
target allocation plus the drift band** (30% + 5% = a hard 35% cap in
`core/sleeves.hpp`). A research conviction can never override the cap. When a
sleeve drifts past the band, rules-based **rebalancing** trims the overweight
sleeve back toward target through the normal **RiskGate-approved exit path**
(never a bypass), on a drift trigger and a scheduled cadence, logged with
before/after allocations.

**Every position is tagged to its sleeve** and accounted independently
(`sleeve_history`). The **RiskGate judges every order in both sleeves** with all
Level-1 limits unchanged — the satellite's larger positions still respect every
cap, so a long-term hold never means unbounded size. A **combined monthly spend
ceiling** (quant council + research) pauses both sleeves when reached, keeping the
combined API spend near or under **100 dollars** a month.

The GUI Controls page shows a **sleeve allocation panel** (live split vs target,
drift band, rebalance-due flag), per-sleeve **enable toggles**, a **rebalance-now**
button, and the **research thesis feed** — so the higher-equity long-term
decisions are transparent. Enable via `sleeves.research_satellite_enabled: true`.

## Discovery funnel + dynamic watchlist (ships DISABLED)

A fixed four-name whitelist can only find what is already on it. The discovery
engine screens a **curated universe** down to a few vetted candidates every hour,
**cheap to expensive**, so intelligence is spent only at the bottom:

| Stage | What runs | Input → output | Cost |
| --- | --- | --- | --- |
| **A** | Free pre-screen: price, volume, volatility, momentum, gap, Finnhub **pre-computed** sentiment, native technical signal, **whale activity** | whole universe → **12 finalists** | **0 LLM tokens** |
| **B** | Cheap **Claude Haiku** base-check gate | finalists → **5 survivors** | fractions of a cent each |
| **C** | Full **four-level** evaluation (council + DNN advisory + whale) producing a verdict (`buy`/`sell`/`avoid`), sizing, rationale | survivors → verdicts | full council, **a handful** |

**Why this shape.** Cost, not analysis, is what stops you looking at 150
instruments hourly. Ranking on free data costs nothing per name, so the universe
can be wide while the bill stays flat. Config validation enforces that the funnel
**narrows**: `max_survivors <= max_finalists` and
`max_council_calls_per_pass <= max_survivors`.

**The universe is the outer edge of the funnel, and liquid names only.** Both native
strategy families fail on thin books, so an illiquid name reaching Stage C wastes
a council call. Edit the two lists in the `discovery:` config block:

- **Crypto (55 → active 50).** Composition shifts, so a **daily refresh** picks
  the active set by **liquidity and volume** from the broader curated list. It
  ranks *within* the list, it never discovers a coin on its own.
- **Equities (119, stable).** Large caps and liquid ETFs do not churn, so the
  list is hand-edited and stays put.

**Hard cost ceilings.** `max_finalists` / `max_survivors` /
`max_council_calls_per_pass`, plus a **daily discovery council budget** (12/day)
that is **separate from and additive to** the trading budget, so discovery can
never eat the quant loop's calls. Worst case combined: 52 calls/day × $0.04 × 30 ≈
**$62/month**, under the existing $100 combined ceiling. Every stage's counts and
**every dropped instrument with its stage and reason** persist to
`discovery_pass` / `discovery_drop` / `discovery_candidate`.

**Cadence.** Crypto **hourly, 24/7**. Equities at the **US session open and hourly
through US regular hours** only. An equity pass after hours would rank a market
nobody can trade.

**Whale activity does two jobs, deliberately.** It **surfaces** candidates in
Stage A (a strong signal raises an instrument's free pre-screen rank, so a name
whales moved into can reach the finalist set even when price and volume alone
would not have surfaced it), and it still **evaluates** survivors in Stage C as
the Level-4 advisory factor at its unchanged **0.35 cap**. Same data, two
questions, not a duplication bug: surfacing asks *is this worth looking at*,
evaluation asks *what should we do*. A surfaced name still has to clear the Haiku
gate and the full four levels, so whale only buys a name a look.

`discovery.stage_a_whale_weight` (default **0.15**) tunes surfacing strength
without touching code. The five fixed components sum to 1.0 and whale adds on top
before normalization, so at 0.15 it sits level with sentiment and native and below
momentum and volatility: enough to lift a **borderline** name over the cut, never
enough to rescue a dead-flat one or dominate the tape. Set `0.0` to restore the
exact pre-whale ranking. Candidates whale surfaced are **tagged** in the discovery
and watchlist views. The tag is a *counterfactual*: it fires only when the name
would **not** have made the cut without whale, so it means something.

**Dynamic watchlist.** Stage-C survivors join a living candidate list
(`watchlist`) that **both sleeves draw entry candidates from**; entries prune when
a signal goes **stale** (no pass re-confirmed it in 48h) or a **thesis breaks**,
and the list is capped at 40 on score. It is **event-sourced**: every mutation goes
through one `apply_event` path with an explicit source, journalled to
`watchlist_event`. Today only `discovery` and `prune` are accepted; the
`adaptive_react` source is **reserved and refused** (`source_not_enabled`), the
seam the deferred react layer will use without a rewrite.

**Long-term sleeve strategy** (`research_satellite`, `long_term_sleeve_enabled`):
**quality and catalyst, plus council.** A free Finnhub screen runs first. Quality
(ROE, margin, revenue growth, sane P/E) says the business is worth owning for
months, and a catalyst (earnings inside 21 days, a strong sentiment shift, or an
analyst upgrade) says why now. **Both must hold**: quality alone is a watchlist
entry, a catalyst alone is a gamble. Survivors get the full four levels in
**long-horizon mode**, producing a thesis with **direction, conviction, target,
horizon, and an invalidation condition**, persisted with the position. The four
levels drive **both** sleeves. Only the horizon and prompt framing differ.
Positions are held long-term (no time stop) and exit on **target or thesis
invalidation**, never a short-term signal. A **thesis may only tighten a stop,
never widen it**: target and invalidation are derived deterministically from the
52-week range, so a model cannot hallucinate a level that buys itself more room to
be wrong. The conviction threshold, the hard sleeve cap, and the RiskGate all
still apply.

**It all ships disabled.** `discovery.discovery_enabled: false` and
`discovery.long_term_sleeve_enabled: false`. With the flags off the engine is
exactly the fixed-whitelist two-sleeve system: it never fetches, never scores,
never writes a discovery row, and never reads the watchlist. Verified: a
12000-step run with the flags off produced the same 272 trades / 136 closed on the
same 4 symbols, with zero discovery activity. The startup block prints discovery
state, universe sizes, funnel ceilings, the split, and each flag. Enabling is a
deliberate operator action, and needs a `FINNHUB_API_KEY` (keystore-first, never
logged; without one discovery reports `unavailable` and does nothing).

**Enabling it from the GUI.** Controls has a **Discovery + long-term sleeve**
panel with two enable toggles. Each one **arms before it fires**: the confirm
states plainly what turning it on starts (discovery begins hourly funnel passes
making Finnhub and council calls within the discovery budget; the long-term
sleeve begins evaluating and holding research positions within the 35% hard cap).
Disabling is immediate, because turning a spender **off** should never need a
ceremony.

**Prerequisites are checked before enabling**, so you never enable into a state
that cannot work. Discovery needs a **Finnhub key that resolves** (Stage A is the
funnel's only input) and the **bridge up** (Stage C runs the council on survivors
through it). The long-term sleeve additionally needs the **research_satellite
sleeve** enabled, since the strategy otherwise has nowhere to put a position. A
missing prerequisite blocks the toggle and says exactly what to fix.

The same panel exposes the tunables: the **discovery daily budget**, the
**per-stage counts** (finalists, survivors, council calls per pass), the
**cadence**, and the **whale surfacing weight**. Every value is clamped
server-side into bounds the API itself publishes, and the funnel is always forced
to narrow (survivors at most finalists, council calls at most survivors), so the
GUI can never build a funnel the config validator would refuse. **Level 1 risk
limits are not reachable from this panel and stay read-only**, as everywhere else.

Toggles and settings write through the **same validated control-endpoint channel
as the existing layer toggles** (`controls.json`), and the funnel runner reads
that file, so a change takes effect on the next due pass without a restart. A
missing control file falls back to config, which ships disabled.

Run it from the existing maintenance scheduling, or directly:

```bash
python -m discovery.run --asset-class crypto     # one class, if due
python -m discovery.run --force                  # ignore cadence (still flag-gated)
```

> **Not this layer:** discovery uses Finnhub's **pre-computed** sentiment as a
> cheap number only, one input among price, volume, volatility, momentum, and gap.
> It moves an instrument's **rank in a screen** and reads no articles. Live event
> reading is the separate adaptive layer below, which ships disabled and can
> **refer** a candidate into this funnel but never past it.

## Adaptive real-time layer (ships DISABLED)

Reads live events, and is **allowed to be careful**. Three flags, all default
false. With them false: no poll runs, no client is constructed, no key is read, no
socket opens, no token is spent, and the engine consumes nothing. Verified: a
12000-step flags-off run is behaviorally identical to the pre-adaptive baseline
(272 trades, 136 closed, zero adaptive rows).

### The asymmetry (the whole point)

**A live event can make the engine more cautious. It can never make it more
aggressive.**

| Read | What it may do |
| --- | --- |
| **Defensive** (trim, exit, flag for review) | Acts directly, through the **same native exit path** the engine already uses. Never a bypass, never a new order path. |
| **Aggressive** (open, increase) | **No event path exists.** It becomes a watchlist **referral**: the symbol is offered to the discovery funnel, and Stage A, Stage B, the four levels, and the RiskGate all still have to agree before anything is bought. |

There is **no flag for event-driven entry**, because there is no code path to
enable. A misread headline costs a screening slot and a fraction of a cent. It
cannot cost a position. That is enforced three times, independently, in two
languages:

- `adaptive/actions.py`: `DefensiveAction` **refuses to construct** for a
  non-defensive action, and the queue writer accepts only that type. Not "should
  not be queued": *cannot be built*.
- `discovery/watchlist.py`: an adaptive add lands as `referred`, never `active`.
  The status is derived from the **source**, not requested, so no caller can
  promote a symbol onto the traded universe.
- `core/adaptive_actions.hpp`: `DefensiveKind` has three enumerators and none is
  aggressive. Parsing is an **allowlist**; the engine's consumer never calls the
  entry path.

### The chain (cheapest stage first)

| Stage | Cost | What it does |
| --- | --- | --- |
| **Poll** | free | Finnhub, once a minute, held names first, then watchlist, then general market news. Reuses the discovery client, so one rate limiter, not two. |
| **Filter** | **free, no LLM** | Keywords, sentiment magnitude, event type. Drops the vast majority. Everything dropped is still **stored**, so the cost claim stays checkable. |
| **Interpret** | **the only paid stage** | One cheap Haiku read per escalated event: relevance, direction, severity, suggested action. Never on the raw feed. |
| **Route** | free | `adaptive/actions.py` decides the most it may cause. |
| **Apply** | free | A referral, a prune, or a queued defensive action. |

Budget: **20 reads/day at about $0.02 (about $0.40/day)**, **separate from and
additive to** both the discovery budget and the trading council budget, so this
layer can never eat either one's calls. A per-poll cap means one news storm cannot
spend the day.

### The three flags

```yaml
adaptive_realtime:
  adaptive_news_feed_enabled: false          # observe. The MASTER flag.
  adaptive_watchlist_shaping_enabled: false  # safe half: refer + prune
  adaptive_react_defensive_enabled: false    # react half: trim / exit / flag
```

The feed is the master: the other two are downstream of a poll, so with the feed
off they can do nothing whatever they are set to. Enable them from **Controls**
(each arms and states what it starts) and watch the **Adaptive** page, which shows
the event feed with the dropped rows dimmed and labelled, the interpretations, and
what the engine actually did with each queued action. Graduation criteria are in
`LIVE_READINESS.md`.

> **Naming:** `adaptive_realtime:` is *not* the `adaptive:` block, which is the
> **learning tuner** (weights from closed-trade PnL). They share a word and
> nothing else.

```bash
python -m adaptive.run --once     # one poll (does nothing unless the flag is on)
```

## Unattended week-long run (watchdog, backups, DNN challenger)

For a week-long unattended paper run, the start script launches a **crash
watchdog** (`ops/watchdog.py`) as a separate process (stopped by the teardown
trap). Every few minutes it checks engine/bridge/backend health and crypto bar
staleness, attempts **one clean restart** through the supervisor on a failure, and
sends an **ntfy.sh notification** either way (set `watchdog.ntfy_topic` in config;
notifications carry component status only, never a key or position). It **never
touches the kill-request file**, and a kill-switch trip is **notified but never
auto-resumed** (manual resume stays required).

**Nightly backups** (`python -m ops.backup`, or cron) take a consistent
`sqlite3 .backup` snapshot into the gitignored `backups/` directory with dated
names and a retention count (default 14), restore-verified by counting `trades`
rows. **Events-table pruning** (`ops/maintenance.py`) caps growth over the week
and never deletes trades, positions, bars, or audit-relevant events.

**Mid-week DNN challenger training** runs on a daily schedule
(`ops/maintenance.maybe_train_challenger`): it attempts a real-data challenger from
accumulated fills, refuses cleanly below the sample minimum, and **promotion stays
gated and manual** — a trained challenger waits in the GUI (champion vs challenger
with validation Sharpe and drawdown) for the operator's deliberate **Promote**.

**Week-review digest** (`ops/weeklog.py`) runs daily alongside the backup job and
appends one dated section to `WEEKLOG.md` at the repo root, distilling the prior
24 hours from the database: trades (by sleeve and symbol, win rate, gross and net
PnL, best and worst with entry reasons), risk blocks and a confidence near-miss
table (blocks within 0.10 of the floor, the calibration evidence), council and
cost, sleeves, crypto sessions, health, and anomalies. It is read-only over the
database and never writes a key or credential. At week end run
`python -m ops.weeklog --summarize` to append a week-summary with totals, the full
near-miss table, the pre-registered success-criteria checklist marked from the
data, and open calibration questions. Timestamps show UTC and America/Vancouver.
The operator hands the one file to a reviewer.

Materialize the exact week config with
`python -m api_server.stack week-config .run/week_config.yaml` (both sleeves at
80/20, `active_quant`, all advisory layers on-real, feed `alpaca_paper`, clock
real, **live off**, RL off) and launch the engine with `--config` pointing at it.
The default config stays conservative; the week config is an explicit opt-in file.

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
| `discovery/` | Finnhub client, curated universe, cheap-to-expensive funnel, dynamic watchlist (ships disabled) | Python |
| `research_satellite/` | deep-research thesis + long-term quality-and-catalyst strategy (ships disabled) | Python |
| `whale_signal/` | ClankApp / SEC-EDGAR-13F (+ optional Whale Alert) adapters + scoring | Python |
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

## Full real-time paper trading — all four levels (one command)

`scripts/start_paper_trading.sh` starts everything for real-time Alpaca **paper**
trading with all four decision levels active, in order, with a health check
between steps and clean teardown on exit:

0. **warm-start** — backfill real historical bars into the `bars` table for the
   whitelist and verify every symbol is warm, so the first live bar evaluates
   against warm indicators (the 100-period EMA, ADX, ATR, Bollinger, RSI, volume,
   realized vol) instead of a cold start,
1. the Python bridge (real LLM council + `dnn_advisory` + whale via SEC EDGAR),
2. the C++ engine (`feed_mode alpaca_paper`, `clock real`) on the full whitelist
   (BTC/USD, ETH/USD, SPY, QQQ) — crypto 24/7, equities respect market hours,
3. the GUI backend + frontend (open <http://127.0.0.1:5173>).

The engine seeds its indicators from the backfilled bars on startup and prints a
per-symbol per-indicator warm/cold line. On the real path it **gates entry on
warmth**: a cold symbol waits and never fires on partial data (`warm_state`
events record each cold/warm transition).

```bash
scripts/start_paper_trading.sh                 # full stack + GUI
MAL_HEADLESS=1 MAL_RUN_SECONDS=900 scripts/start_paper_trading.sh   # headless, bounded
```

Live trading stays **OFF** (Alpaca is paper + market-data only). Full activation
assumes you run the bridge and hold keystore keys; without `--bridge` the loop
stays in-process mock, and any provider without a resolvable key degrades to a
labelled mock.

### Start and stop from the GUI (supervisor)

**The GUI backend must be running first.** The supervisor lives inside the
read-only backend, so `scripts/run_gui.sh` (backend + Vite frontend) must be up
before the Start button works. The Start button does not launch the backend it
runs inside, it drives the supervisor in that backend. `run_gui.sh` prints a
"GUI backend is ready" line once you can start the stack.

You can start and stop the same warmed stack from the GUI, without the terminal.
The **Ops** page carries a **Start paper trading** / **Stop** control, mirrored
in the top status strip. A small backend **supervisor** owns the bridge and
engine lifecycle and runs the exact same sequence as the script through one
shared callable (`api_server/stack.py`), so the two never drift:

- **Start** (a confirm step) runs: backfill real bars, verify warm, bring up the
  bridge with the real council, then the engine (`feed_mode alpaca_paper`,
  `clock real`, full whitelist), health checked between steps. It reports the
  live lifecycle: `not_running` → `starting` → `warming` (with per-symbol warm
  progress) → `running`. Start spawns the bridge with the **same whale env flags
  the script exports** and **waits for the bridge to pass a health probe** before
  the engine starts, so the engine never races ahead of the bridge. Strict
  no-silent-mock still applies: if a layer set on-real is unreachable, Start
  **fails loudly** in the GUI with what is missing (surfaced in the Ops panel and
  the status strip), it does not go dark.
- **Stop** is a **graceful shutdown** of the bridge and engine the supervisor
  started. It is not the kill switch.
- **Single instance:** the supervisor refuses a start when an engine already
  runs, whether launched by the script or a prior GUI start (a shared
  `.control/engine.lock` records the pids). A stale lock from a crashed run is
  detected and cleared on the next start.
- Backend endpoints: `GET /engine/state`, `POST /engine/start`,
  `POST /engine/stop`, all read-only on the operational tables and bound to
  loopback.

> The **kill switch stays independent** of the GUI and the supervisor. The C++
> engine reads the kill-request control file itself at the top of every loop
> iteration, so a kill halts the engine even with the GUI, the backend, and the
> supervisor all down. The GUI Stop button is a graceful shutdown, the kill
> switch is the safety halt, they are different and the safety halt never routes
> through the supervisor. The always-visible kill switch is never replaced by the
> Stop button.

### Self-cleaning start (no port collisions)

Both the script and the GUI supervisor self-clean before they start, so a prior
run that crashed and left a process holding a port never blocks the next start:

- **Pre-flight port cleanup** frees the exact ports this stack owns (bridge, GUI
  backend, Vite) if a stale process holds them, graceful signal then force kill,
  one line per port. Only those ports, never a blanket kill. The supervisor
  frees only the bridge port (never the port it is served on, and it never kills
  its own process).
- **PID tracking + clean teardown.** The script records every started pid
  (bridge, engine, backend, frontend) in `.run/pids`. A trap stops them cleanly
  on exit and Ctrl-C, then removes the file. A crashed prior run self-heals on
  the next start: stale pids are stopped and the file is cleared.
- **Single instance.** A healthy full stack already running (pid file + a live
  health check) refuses a second start rather than fighting for ports. A stale
  pid file with dead pids is not a running instance, it is cleared.

The shared logic lives in `api_server/stack.py`, so the script and the supervisor
run one implementation. Pre-flight cleanup never touches the kill-request control
file, so the kill switch stays independent of all of this.

### Per-level toggles: off / on-mock / on-real

Each advisory level has **two independent axes**, surfaced on the Controls page
and the Ops section (validated backend endpoints, safety cannot be altered):

- **Enable** (off / on): off drops that layer's factor from the ensemble.
- **Source** (mock / real, only when on): `on-mock` uses the deterministic
  stand-in even while the bridge is up, `on-real` calls the live service. So each
  layer reads as **off**, **on-mock**, or **on-real** — you can drop any single
  layer to mock mid-run to isolate it, without stopping the loop.

The **static safety layer (Level 1) has neither axis: always on, always real.**
On the real paper path the engine is **strict**: a layer set `on-real` whose real
service is unreachable makes the engine **refuse to start**, printing exactly
what is missing, rather than silently substituting a mock (a layer you set
`on-mock` starts normally — that is a deliberate choice). The startup block prints
the exact state of every level, and the GUI run-state banner mirrors it.

### Feed and clock runtime toggle

The Controls page also switches the **feed mode** (`alpaca_paper`,
`synthetic_regimes`, `replay`, `flat_random_walk`) and **clock mode** (`real`,
`simulated`) at runtime, through the same validated control-file the engine reads
each iteration — no config edit, no restart. The run-state banner and the top
status strip show the current feed and clock.

A feed switch **never orphans an open position**: switching **away from**
`alpaca_paper` while a paper position is open is **refused** (the position keeps
being managed by its native exits on the current feed), and switching **into**
`alpaca_paper` **re-arms the warm-start gate** so evaluation waits until the
indicators are warm on real bars again. A clock switch applies immediately. Every
switch is audited (`feed_mode` / `clock_mode` events); a blocked one logs
`feed_mode_blocked`. A missing or invalid control value keeps the launch
feed/clock, so it never forces an offline run onto the live feed.

### Other live controls and the tuner floor

The remaining Controls-page controls are now consumed by the engine too:

- **Council model toggles** drop a provider (GPT-5.5, Claude Opus 4.8, or Gemini
  3.1 Pro) from the council for that iteration. At least one must stay on, or the
  council falls back to a clearly logged skip.
- **Regime pins** override the detector for a symbol (test-only), affecting the
  surfaced regime and the council neutral-skip.
- **Council budget** (daily budget and per-symbol cooldown) adjusts at runtime
  within validated bounds.
- **Promote / rollback** of the `dnn_advisory` champion execute through the
  registry, gated by the promotion criteria (a runtime promote cannot bypass
  them) and audited.

A **tuner floor** (`adaptive.rule_based_weight_floor`, default 0.35) keeps the
native signal's weight — and its share of the gate verdict — from being starved
by the adaptive tuner, so a long paper run keeps generating native entries
(fills) instead of stalling after ~30. It is an advisory bound and never weakens
a risk limit.

Two states are **on by design and not part of full activation**:

- **RL advisory** ships **OFF**, gated behind `rl_min_real_fills` (default 500
  real fills); it is never force-enabled.
- **Live trading** is **OFF**, behind the in-app approval gate.

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

> **Backend note (modern Ubuntu / GTK4 / Python 3.13+):** pywebview's GTK
> backend can fail to open the window (e.g. a GTK4 `name 'initialized' is not
> defined` error). If that happens, install the **Qt** backend —
> `ops/run_desktop.sh` then prefers it automatically:
>
> ```bash
> source .venv/bin/activate
> pip install pyqt6 pyqt6-webengine qtpy
> bash ops/run_desktop.sh
> ```
>
> Force a backend explicitly with `PYWEBVIEW_GUI=qt` (or `gtk`).
>
> **Tray note (GNOME):** the system-tray icon needs the *AppIndicator* Shell
> extension (`sudo apt install gnome-shell-extension-appindicator`, then enable
> it and log out/in). Without it the app still runs and the window works — the
> tray is simply skipped, and closing the window quits the app (instead of
> hiding to tray). To run the app straight away without installing a launcher,
> use `ops/run_desktop.sh`.

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
(default 5 s, from `dashboard.dashboard_refresh_seconds`). It is laid out as a
clean, broker-style app with **four top-level tabs**:

- **Paper** (default landing page) — a beginner-friendly broker view of the
  paper account: a large **portfolio hero** (total equity, with today's change
  and all-time P/L stacked beneath, green ▲ / red ▼), a row of simple stat cards
  (Total P/L, Win rate, # Trades, Max drawdown, Open positions), the equity
  curve, open positions, and recent activity. Trades are filtered to
  `mode == 'paper'`.
- **Live** — the same skeleton, but **locked by default**: a clear banner states
  that real-money trading is disabled, and the **approval gate** (from
  `approval_state()` + `venue_state()`) is surfaced so you can see what live
  enablement would require. Numbers come from `mode == 'live'` trades / live
  venue balances; with live off (the normal case) it shows zeros / "no live
  activity". This page never enables live on its own.
- **Advanced** — every dense/technical panel, grouped under section headers:
  equity curve, daily realized PnL, drawdown %, trade-by-trade PnL, win/loss
  calendar heatmap, venue allocation, exposure by symbol/market, factor-weight
  contribution, Layer-2 param before/after, dnn_advisory performance, whale-signal
  history, whale-agreement-vs-outcome, the model verdict board, the
  **adjustable model-weight control panel** (numeric inputs, per-factor lock,
  reset-to-defaults; auto-normalized), live-approval readiness, venue state,
  model registry (champion/challenger), recent trades, open positions,
  blocked/rejected (RiskGate), weight-change history, param-change history, and
  the append-only event log.
- **Accounts / Connections** — enter and save credentials per venue (separate
  paper/live) and per data source (see below).

The hero numbers are computed robustly from `equity_curve("AGGREGATE")`: total
value is the latest equity row; today's change is latest minus the first equity
recorded on the latest day; all-time is latest minus the first row. With fewer
than two rows everything shows `$0.00 (0.00%)` rather than erroring, and the
offline / empty-DB path renders friendly empty states everywhere.

The weight control panel (on **Advanced**) is the UI's only writer: it appends to
`weight_changes` and mirrors normalized weights to `ui/weight_overrides.json`.
Adjusting weights only re-blends advisory factors — it can never weaken the
deterministic RiskGate.

## The React GUI (rebuilt, Alpaca-style, additive)

`web/` is a React and TypeScript app, restyled after the Alpaca trading
dashboard: a dark neutral background, one gold accent for interactive elements,
green for gains, red for losses, clean cards and dense tables. It is additive.
The Plotly Dash board above stays in place as a fallback, unchanged. Both read
the same SQLite database.

A left sidebar holds the sections below. A top strip on every page shows engine
state, active mode, portfolio value, daily PnL, kill-switch status, and
discovery state (on or off, watchlist size, last pass time).

The GUI displays every timestamp in the operator's local timezone (default
America/Vancouver, PST or PDT by date, changeable in Settings); storage, the
engine, logs, and the events table stay UTC. This is a display-only preference.

- **Paper** is the default operating view for the Alpaca paper loop, with three
  subpages:
  - **Overview** an equity hero, stat cards (total P/L, win rate, closed
    trades, max drawdown, open positions), the equity curve, open positions, a
    fills-and-signals activity feed, per-symbol regime labels, council verdicts,
    and a kill-switch control with a confirm step.
  - **Stocks** positions, open orders, closed trades, and signals filtered to
    SPY and QQQ.
  - **Crypto** the same tables filtered to BTC/USD and ETH/USD.
  Filtering happens server-side through a `category` query parameter.
- **Live** the same three subpages for the IBKR live venue, locked by default.
  It shows the approval gate and the four safety mechanisms and zeros all
  trading data. No control on any Live page can enable live.
- **Controls** the operator control surface: weight sliders grouped by layer,
  per-layer toggles (safety is always on and has no toggle), per-model council
  toggles plus the Claude Haiku base-check gate, champion and challenger promote
  and rollback with a confirm step, an RL enable toggle gated on the real-fill
  count, per-symbol regime override (test only), and a council budget dial.
  Level 1 risk limits render read-only here. Change them through config or the
  Dash L1 editor, never through this page.
- **Discovery** the latest funnel pass per asset class, drawn as a funnel:
  universe size, Stage A finalists, Stage B gate survivors, Stage C evaluated,
  each bar labelled with what that stage costs (0 tokens, gate calls, council
  calls). The cost this pass shows against the separate discovery budget, and
  every dropped instrument is listed with its stage and reason. Read-only, so
  the operator can confirm at a glance that the funnel spends intelligence only
  at the bottom.
- **Watchlist** the living candidate list both sleeves draw from: each
  instrument, why it is on the list, when it was added, when a pass last
  confirmed it, its sleeve target, and its status, plus a feed of recent adds
  and prunes. A refused event from the not-yet-enabled react source shows as
  REFUSED rather than being hidden.
- **Long-term** the research_satellite sleeve, kept distinct from the quant
  core. Each position renders its full thesis: direction, conviction, target,
  horizon, invalidation condition, entry date, current PnL, and where the
  position sits against its thesis. A research feed lists the recent theses the
  council wrote. This is where the operator reads *why* each long-term position
  is held.
- **Settings** credential entry grouped by category (LLM council, paper venue,
  live venue, crypto venue, whale data), every field masked, plus the active
  council models and a per-group offline connection test.

The three discovery views are **read-only and have no write path**: there is no
POST on any discovery route, and no control on any of those pages. Discovery
ships disabled, so each view renders a clear **disabled state** naming the exact
config key to flip and what would run once enabled, rather than an empty page
that reads as broken.

A thin FastAPI backend in `api_server/` serves the app. It binds loopback only
(127.0.0.1). Every GET is read-only on the operational tables. The control
endpoints validate and clamp every change server-side and record it to the
event log with old and new values. They reuse the Dash weight-override channel
for weights and a `controls.json` control file for the rest. No control endpoint
writes a Level 1 risk value, touches the RiskGate, or can enable live.
Credentials go through the existing encrypted keystore. The frontend loads
initial data over REST and receives live updates over a WebSocket (`/stream`)
on a two-second tick.

Run both together:

```bash
scripts/run_gui.sh
```

That starts the API backend on <http://127.0.0.1:8000> and the Vite dev server
on <http://127.0.0.1:5173>. Open the Vite port (5173) to land on the rebuilt
interface. The Dash board stays available separately (`python ui/app.py`) as
the fallback. For live data the C++ engine and the `python_bridge` should be
running.

Install and test:

```bash
.venv/bin/pip install -r api_server/requirements.txt   # backend deps
pytest tests/test_api_server.py                        # backend tests (36)
cd web && npm install                                  # frontend deps
cd web && npm run typecheck && npm test                # types + render tests (7)
cd web && npm run build                                # production build
```

### Full-system test and live API health

`scripts/test_full_system.sh` runs the whole suite in one pass and prints a
PASS, FAIL, or SKIPPED line per section plus a summary table. It continues past
failures and exits nonzero if any section fails. Sections cover the build
(zero warnings), C++ ctest, Python pytest, config validation, the RiskGate and
kill switch, strategy and regime, real-fill feedback, the council offline,
council cost controls, dnn advisory, RL gating, the whale layer, the API
backend, the frontend, and live exclusion. Two sections are optional and print
SKIPPED unless keys are present in the process environment: the live council
call (needs ANTHROPIC, OPENAI, and GEMINI keys, capped at one gate plus one
council pass) and Alpaca paper (needs Alpaca paper keys, one quote plus an
auth-only account check, never a resting order). Live trading is never touched.
The script cleans up its temp DBs and configs and leaves the repo unchanged.
Expected runtime is roughly one to two minutes offline, a little more when the
optional live sections run.

```bash
bash scripts/test_full_system.sh
```

The **live API health check** verifies each integration with a real round trip,
not just a key-present check. `GET /health/integrations` runs one minimal call
per integration (OpenAI, Anthropic Opus, the Anthropic Haiku gate, Gemini,
Alpaca market data, Alpaca paper trading auth, SEC EDGAR, IBKR gateway
reachability) concurrently with per-check timeouts and returns working,
failing, or not_configured with a short reason and round-trip latency in
milliseconds. It never places a resting order (the Alpaca trade check
authenticates only), never touches live trading, never writes an operational or
Level 1 value, and never logs or returns a key value. An absent key reports
not_configured, not failing. The Health view in the GUI shows each integration
as a colored row and the top status strip shows an aggregate that is green only
when every configured integration passes.

### Operational upgrades

The GUI adds operator panels that improve efficiency and catch problems, all
additive and read-only except the kill switch. No control weakens the RiskGate
and Level 1 stays read-only.

- An always-visible kill switch in the top strip on every page. One click, one
  confirm, then it writes the same kill-request control file the engine
  consumes. It shows armed or tripped. A tripped switch stays latched and needs
  the existing manual resume, the GUI adds no second resume path.
- A run-state banner under the strip: loop mode (offline mock, synthetic_regimes,
  replay, or online alpaca_paper), bridge up or down, and real vs mock council.
- A council skip-reason feed (budget spent, per-symbol cooldown, neutral regime,
  risk pre-check, market hours) read from the event log, on the Paper Overview
  and the Ops page.
- Staleness badges on feed-dependent panels (market data, positions, signals,
  council). A stale panel past its threshold turns a warning color.
- Clickable trade rows open a detail view: order and sizing, regime, the factors
  that fired, the council verdict at entry, and the entry and exit events.
- A day summary card: trades today, win rate today, council calls today against
  the budget, and estimated provider spend today.
- Drawdown shading on the equity curve.
- A provider cost panel. It shows balance where a provider exposes it, else
  provider spend where exposed, else a local estimate that is always computed
  and clearly labeled estimated. No provider exposes a stable prepaid-balance
  endpoint for a plain API key today, so the reported signal is the local
  estimate, computed from the council calls recorded in the database times the
  per-model token prices in config/provider_prices.yaml. Backend endpoint
  GET /providers/cost runs the reads concurrently with a timeout, reports a
  per-provider status of live, estimated, or unavailable, and never returns or
  logs a key value.

### Live integration verification

`scripts/verify_live_integrations.sh` resolves every provider key through the
unified keystore-first resolver (encrypted keystore, then env) and runs one real
minimal round trip per integration. It prints a labeled result table and appends
it to RETURN.md under a verification log section. It never places a resting
order (the Alpaca order-auth check is an authenticated GET on the account),
never touches live trading, and never prints a key value. One minimal call per
provider keeps spend near zero.

```bash
bash scripts/verify_live_integrations.sh
```

A healthy result shows working for every configured integration with a small
latency. failing rows carry a short reason (bad key, rate limit, quota, bad
request, network) so the operator can fix it. not_configured means no key
resolved from the keystore or env, which is not a failure. Because the health
check and the test script use the same resolver, a key saved in the keystore
counts as configured everywhere, so the live sections run instead of skipping.

### Decision-layer toggles

The Controls page and the Ops section expose four per-layer enable toggles:
adaptive strategy, LLM council, dnn_advisory, and whale. They write the same
validated backend endpoint (controls.json). The engine reads controls.json each
loop iteration, the same pattern as the kill-request file. A layer toggled off
drops its factor from the ensemble for that iteration, contributing nothing to
direction, sizing, confidence, or edge. Toggling a layer off removes an advisory
input. It never disables, weakens, or bypasses the RiskGate, the kill switch, or
any Level 1 limit. The static-safety layer has no toggle and always runs, shown
as a fixed always-on indicator. A missing or malformed controls.json means all
layers on. The run-state banner and the engine startup block show which layers
are enabled, so a layer off by operator choice is never mistaken for a broken one.

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

**Whale data does two jobs, deliberately.** It **surfaces** candidates in the
discovery funnel's free Stage-A pre-screen (a strong signal raises an
instrument's rank, so a name whales moved into can reach the finalist set even
when price and volume alone would not have surfaced it), and it still
**evaluates** survivors in Stage C as the Level-4 advisory factor at its
unchanged **0.35 cap**. Same data, two questions, not a duplication bug:
surfacing asks *is this worth looking at*, evaluation asks *what should we do*. A
surfaced name still clears the Haiku gate and the full four levels, so whale only
buys a name a look. Tune surfacing with `discovery.stage_a_whale_weight`
(default 0.15, moderate by design); `0.0` disables surfacing and leaves Level 4
untouched. Both roles ship behind the discovery flags, default off.

Free-first by default — the app runs with **no paid keys**:

| Source | Adapter | Notes |
|--------|---------|-------|
| **ClankApp** (free crypto/on-chain) | `ClankAppAdapter` (**default**) | fully free (~10 calls/min, ~21 chains); `CLANKAPP_API_KEY` optional (email signup); mock fallback |
| **SEC EDGAR 13F** (free) | `Sec13FAdapter` (**default**) | official `data.sec.gov` / `efts.sec.gov` REST — **no key**, just a descriptive `User-Agent`; **DELAYED**, equity-only, down-weighted; `SEC_API_KEY` optional override only |
| Whale Alert API | `WhaleAlertAdapter` (**crypto trial**) | crypto-only, ≥ $500k; one-time **trial evaluation**, opt-in via `whale.whale_alert_enabled` + `WHALE_ALERT_API_KEY`; joins the whale chain for crypto and feeds the **same** advisory factor as SEC EDGAR under the **0.35 cap**; 429 retries with backoff then degrades to mock |

**Whale Alert trial feed (crypto).** Off by default. It is wired as a one-time
trial evaluation, not a recurring free-tier scheme. To enable it, set
`whale.whale_alert_enabled: true` in `config/default_config.yaml` and provide
`WHALE_ALERT_API_KEY` (keystore-first, never committed). `scripts/start_paper_trading.sh`
exports the flag to the bridge as `WHALE_ALERT_ENABLED`. When enabled and keyed
the adapter fetches recent large crypto transfers (developer plan, 10 req/min)
and scores exchange inflow versus outflow into the whale factor. When the key is
absent it reports not configured and the system runs unchanged (SEC EDGAR only).
`GET /health/integrations` reports the trial feed working, failing, or not
configured; the key is never logged.

Live fetches use `requests` with a ~10 s timeout and descriptive User-Agent; any
network error, HTTP 429 (rate limit), or parse failure falls back to a
deterministic mock, so the demo always runs offline. 13F rows are flagged
`delayed=1` everywhere and labelled **DELAYED** in the UI — context, not live
trade flow. These signals are advisory research data for paper/model-training
only — never live order flow.

## Global-session equity rotation (scaffold, disabled)

Global-session equity rotation lets the equity sleeve follow the open regional
market — Asia, then London, then NY — trading each region's equities during its
session. It is **scaffolded for the live IBKR phase and DISABLED now** because
Alpaca is US-only and cannot reach Asian or European exchanges.

The engine enforces a standing **venue-capability** safety rule: it only
evaluates and trades an equity region a connected venue can actually reach. Today
only **NY (Alpaca US equities)** is reachable, so only US equities trade during US
hours, exactly as now. London and Asia are defined but `venue_unavailable`. An
equity order for a region with no capable venue is refused before it reaches any
adapter, logged `venue_unavailable_for_region`; the engine never routes an order
to an unreachable market. **Crypto is never gated** by a regional session — it
trades 24/7. The model is config-driven (`config/regional_session.hpp`, the
`global_sessions` config block) and structured as a venue mapping, so adding IBKR
global routing later is config plus an adapter mapping, not an engine rewrite.
Enabling it needs IBKR global access, per-region whitelists, and
`global_equity_rotation_enabled: true`. See **LIVE_READINESS.md**.

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
   save keys/secrets per venue (Alpaca, Coinbase, IBKR) with
   **separate paper and live fields**, and per data source (SEC EDGAR, free, no
   key needed; Whale Alert, optional, limited free tier; **Finnhub**, free tier,
   60 calls/min, under **Discovery data**, needed only if you enable the
   discovery funnel, which ships off). Secret inputs are masked
   (`type=password`), and a saved value renders as dots, never plaintext.

   Settings groups credentials into categories (LLM council, Paper venue, Live
   venue, Crypto venue, Whale data, Discovery data). Any credential the backend
   registry exposes that no category claims falls through to an **Other
   credentials** panel rather than vanishing, so a newly registered key can never
   be silently unreachable in the UI.
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

### Security hardening

Defence-in-depth for a public repo that touches money and API keys:

- **Pre-commit secrets scan.** `ops/check_secrets.sh` blocks a commit that stages
  a credential-shaped string (`sk-…`, `AKIA…`, `github_pat_…`, `AIza…`, PEM
  private-key blocks, or a real-looking `api_key=` / `secret=` value). Wire it
  once per clone:

  ```bash
  ops/install_git_hooks.sh          # installs .git/hooks/pre-commit
  ops/check_secrets.sh              # or run the scan by hand
  ```

  Placeholders in `.env.example` are ignored; bypass only with
  `git commit --no-verify` (discouraged).
- **Loopback-only bridge.** `python_bridge/server.py` binds `127.0.0.1` and
  *refuses* a non-loopback host (e.g. `0.0.0.0`) unless an operator sets
  `BRIDGE_ALLOW_REMOTE=1`. The advisory bridge is for the local C++ engine only.
- **Masked logs.** `account_manager/log_safety.py` (`mask_secrets` / `safe_print`)
  redacts credential-shaped substrings before anything reaches stdout/stderr, so
  a stray key in an error message is never printed.
- **Pinned dependencies.** `python_bridge/requirements.txt`, `ui/requirements.txt`,
  and `ui/requirements-desktop.txt` use exact `==` pins for reproducible installs
  and no silent supply-chain drift.
- **Git-ignored secrets.** `.gitignore` excludes `.env`, `*.pem`, `*.key`,
  `.keystore/`, and all `*.db*` files.

## Testing

```bash
ctest --test-dir build --output-on-failure     # C++: RiskGate, config, weights
source .venv/bin/activate && pytest tests/ -q   # Python: whale, ml_factor, consensus
```

C++ tests cover the deterministic RiskGate scenarios, config validation
invariants, weight normalization/locking, the 70/30 sleeve split and its hard cap,
and that discovery ships disabled. Python tests cover whale scoring
(bias/flow/contradiction/delayed-downweighting/noisy-actor filtering), DNN IO
round-trip + sizing cap + named fields, LLM consensus determinism/shape, the
credential resolver (encryption round-trip + in-app-overrides-env precedence), and
the discovery funnel: that Stage A spends **zero** LLM tokens, that the gate runs
only on finalists and the council only on survivors, that the per-stage ceilings
and the separate daily budget cap spend, that the watchlist adds and prunes, and
that with the flags off nothing runs at all. Every external feed is mocked; no
test touches the network.

## Database schema

`storage/schema.sql` is the single source of truth; `events` is an **append-only**
audit log (never updated in place). Key operational tables: `trades`, `positions`,
`signals`, `model_outputs`, `model_registry`, `param_history`, `weight_changes`,
`whale_activity`, `whale_signal_history`, `approval_state`, `venue_state`,
`account_balances`, `blocked_trades`, `bars`, `regime_state`, `research_thesis`,
`sleeve_history`.

The C++ engine is the **sole writer of the operational trading tables** (`trades`,
`positions`, `events`). A few advisory tables are written Python-side by the
service that owns them: `bars` (`market_data/alpaca_source.py` backfill),
`model_registry` (`ml_factor/registry.py`), and the **discovery** tables
(`discovery_pass`, `discovery_drop`, `discovery_candidate`, `watchlist`,
`watchlist_event`). The engine only ever **reads** the watchlist, and only when
discovery is enabled.

## TODOs (Coinbase / IBKR)

The architecture is venue-agnostic; two venues are scaffolded but not yet
complete (search the codebase for `TODO:`):

- **Coinbase** — `execution/` `CoinbaseSimAdapter` runs simulated/paper only; the
  live adapter structure exists but live trading is not implemented. Env vars
  `COINBASE_API_KEY` / `COINBASE_API_SECRET` are reserved in `.env.example`.
  (Coinbase replaces Binance for crypto — Binance does not operate in Canada.)
- **IBKR** — `IbkrSimPlaceholderAdapter` is data/recommendation-only; full IBKR
  support (paper + live) is a follow-up. See `docs/FOLLOWUP_CREDENTIALS.md`.

Both remain `live_enabled: false` and route through the same Layer-1 RiskGate and
approval gate as every other venue.
