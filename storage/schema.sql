-- Market AI Lab — SQLite schema (single source of truth).
-- Shared by the C++ core (writer) and the Python services + Dash UI (readers).
-- The `events` table is an APPEND-ONLY audit log: it is never updated in place.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Append-only event log — the canonical audit trail of everything that happens.
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,           -- ISO-8601 UTC
    kind         TEXT    NOT NULL,           -- e.g. signal, decision, trade, risk_block, kill_switch, weight_change, approval
    venue        TEXT,
    symbol       TEXT,
    severity     TEXT    DEFAULT 'info',     -- info | warn | critical
    message      TEXT    NOT NULL,
    payload_json TEXT                        -- structured detail
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

-- Executed (paper or live) trades.
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    venue         TEXT    NOT NULL,
    symbol        TEXT    NOT NULL,
    market        TEXT,
    category      TEXT,
    side          TEXT    NOT NULL,          -- buy | sell
    qty           REAL    NOT NULL,
    price         REAL    NOT NULL,
    notional      REAL    NOT NULL,
    fee           REAL    DEFAULT 0,
    mode          TEXT    NOT NULL,          -- paper | live
    pnl           REAL,                      -- realized pnl when closed
    outcome       TEXT,                      -- win | loss | open | flat
    combined_conf REAL,
    combined_edge REAL,
    decision_id   INTEGER,
    sleeve        TEXT    DEFAULT 'quant_core'  -- quant_core | research_satellite
);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts);

-- Open positions (current portfolio state).
CREATE TABLE IF NOT EXISTS positions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    venue     TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    market    TEXT,
    category  TEXT,
    side      TEXT NOT NULL,
    qty       REAL NOT NULL,
    avg_price REAL NOT NULL,
    notional  REAL NOT NULL,
    opened_ts TEXT NOT NULL,
    unrealized_pnl REAL DEFAULT 0,
    sleeve    TEXT DEFAULT 'quant_core',  -- quant_core | research_satellite
    UNIQUE(venue, symbol)
);

-- Research satellite theses. One row per LLM deep-research decision. Attached to
-- a research_satellite position so the operator can read why each long-term hold
-- exists. rationale is council prose, never a key value.
CREATE TABLE IF NOT EXISTS research_thesis (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    direction  TEXT,                        -- long | short | flat
    conviction REAL,                        -- council conviction [0,1]
    horizon    TEXT,                         -- e.g. weeks | months
    rationale  TEXT,
    status     TEXT DEFAULT 'open',          -- open | invalidated | target | closed
    -- Long-term strategy fields (discovery.long_term_sleeve_enabled, default
    -- OFF). NULL on a thesis written by the original council-mapped path, which
    -- carries no target or invalidation. A long-term hold exits on target or
    -- invalidation, never on a short-term signal, so both persist with the
    -- position. An existing DB gains these via the ALTER path in storage.cpp.
    target             REAL,                 -- price target
    invalidation_price REAL,                 -- level at which the thesis is broken
    invalidation       TEXT,                 -- readable invalidation condition
    entry_price        REAL
);
CREATE INDEX IF NOT EXISTS idx_research_symbol ON research_thesis(symbol, status);

-- Discovery funnel audit trail (discovery.discovery_enabled, default OFF). One
-- row per pass per asset class, plus every instrument dropped at each stage with
-- its reason, plus the Stage-C verdicts. These are DISCOVERY tables, not
-- operational trading tables: the Python discovery package writes them, the same
-- way market_data/alpaca_source.py writes `bars`. The C++ engine remains the
-- sole writer of trades, positions, and events.
CREATE TABLE IF NOT EXISTS discovery_pass (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    asset_class      TEXT NOT NULL,          -- crypto | equity
    universe_count   INTEGER DEFAULT 0,
    finalists_count  INTEGER DEFAULT 0,      -- Stage A survivors
    survivors_count  INTEGER DEFAULT 0,      -- Stage B survivors
    evaluated_count  INTEGER DEFAULT 0,      -- Stage C evaluated
    council_calls    INTEGER DEFAULT 0,      -- full-council calls (the paid stage)
    gate_calls       INTEGER DEFAULT 0,      -- cheap Haiku gate calls
    est_cost_usd     REAL DEFAULT 0,
    budget_remaining INTEGER DEFAULT 0,      -- of the daily discovery budget
    status           TEXT DEFAULT 'ok',
    reason           TEXT
);
CREATE INDEX IF NOT EXISTS idx_discovery_pass_ts ON discovery_pass(asset_class, ts);

CREATE TABLE IF NOT EXISTS discovery_drop (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_id INTEGER NOT NULL,
    ts      TEXT NOT NULL,
    symbol  TEXT NOT NULL,
    stage   TEXT NOT NULL,                   -- A | B | C
    reason  TEXT NOT NULL,
    score   REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_discovery_drop_pass ON discovery_drop(pass_id);

CREATE TABLE IF NOT EXISTS discovery_candidate (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_id       INTEGER NOT NULL,
    ts            TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    verdict       TEXT,                      -- buy | sell | avoid
    direction     TEXT,                      -- long | short | flat
    conviction    REAL DEFAULT 0,
    edge          REAL DEFAULT 0,
    agreement     INTEGER DEFAULT 0,
    size_pct      REAL DEFAULT 0,            -- ADVISORY sizing; the RiskGate rules
    horizon       TEXT,
    sleeve_target TEXT,                      -- quant_core | research_satellite
    rationale     TEXT,
    extra_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_discovery_candidate_pass ON discovery_candidate(pass_id);

-- The dynamic watchlist: the narrow end of the funnel. Discovery adds Stage-C
-- survivors; entries prune when the signal goes stale or a thesis breaks. Both
-- sleeves draw entry candidates from here. Event-sourced (see watchlist_event)
-- so the deferred react layer can add and remove via events without a rewrite.
CREATE TABLE IF NOT EXISTS watchlist (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT NOT NULL UNIQUE,
    asset_class    TEXT,
    added_ts       TEXT NOT NULL,
    updated_ts     TEXT NOT NULL,            -- last confirmed by a pass (staleness)
    source         TEXT NOT NULL,            -- discovery | prune
    reason         TEXT,
    sleeve_target  TEXT DEFAULT 'quant_core',
    score          REAL DEFAULT 0,
    status         TEXT DEFAULT 'active',    -- active | removed
    removed_ts     TEXT,
    removed_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status, symbol);

-- Every requested watchlist mutation, applied or refused. A refused event from a
-- not-yet-enabled source (the reserved adaptive_react source) is journalled with
-- applied=0 rather than being silent.
CREATE TABLE IF NOT EXISTS watchlist_event (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    action  TEXT NOT NULL,                   -- add | remove
    symbol  TEXT NOT NULL,
    source  TEXT NOT NULL,
    reason  TEXT,
    applied INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_watchlist_event_ts ON watchlist_event(ts);

-- Per-sleeve accounting history for the GUI (a snapshot per sleeve over time).
CREATE TABLE IF NOT EXISTS sleeve_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    sleeve         TEXT NOT NULL,            -- quant_core | research_satellite
    allocation     REAL DEFAULT 0,           -- capital deployed in the sleeve
    realized_pnl   REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    wins           INTEGER DEFAULT 0,
    losses         INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sleeve_history_ts ON sleeve_history(sleeve, ts);

-- Raw signals from factor families (one row per factor per evaluation).
CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    venue     TEXT,
    symbol    TEXT,
    factor    TEXT NOT NULL,                 -- llm_primary | rule_based | dnn_advisory | whale_signal ...
    bias      REAL NOT NULL,                 -- signed [-1,1]
    confidence REAL NOT NULL,                -- [0,1]
    edge      REAL,                          -- expected edge
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);

-- Per-model structured outputs (verdict board source).
CREATE TABLE IF NOT EXISTS model_outputs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    model      TEXT NOT NULL,
    verdict    TEXT,                         -- strong_sell..strong_buy
    confidence REAL,
    edge       REAL,
    weight     REAL,
    extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_model_outputs_ts ON model_outputs(ts);

-- DNN/RL model registry (champion/challenger versioning).
CREATE TABLE IF NOT EXISTS model_registry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    model_id     TEXT NOT NULL,             -- semantic id
    role         TEXT NOT NULL,             -- champion | challenger | retired
    metrics_json TEXT,
    notes        TEXT
);

-- Layer-2 adaptive parameter history (audit + rollback).
CREATE TABLE IF NOT EXISTS param_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    param     TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source    TEXT NOT NULL,                -- adaptive | manual | rollback
    reason    TEXT
);

-- Weight-change audit (model-weight control panel history).
CREATE TABLE IF NOT EXISTS weight_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    factor      TEXT NOT NULL,
    old_weight  REAL,
    new_weight  REAL,
    source      TEXT NOT NULL,             -- manual | adaptive | reset
    locked      INTEGER DEFAULT 0
);

-- Recent whale activity (raw observations from adapters).
CREATE TABLE IF NOT EXISTS whale_activity (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    source    TEXT NOT NULL,               -- clankapp | whale_alert | sec_13f
    delayed   INTEGER DEFAULT 0,           -- 1 => DELAYED disclosure (e.g. 13F)
    entity    TEXT,
    symbol    TEXT,
    direction TEXT,                        -- inflow | outflow | long | short
    value_usd REAL,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_whale_activity_ts ON whale_activity(ts);

-- Whale signal history (scored outputs over time) + agreement vs outcome.
CREATE TABLE IF NOT EXISTS whale_signal_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    symbol        TEXT,
    whale_bias    REAL,
    whale_confidence REAL,
    whale_flow_direction TEXT,
    whale_activity_score REAL,
    whale_follow_signal INTEGER,
    whale_contradiction_flag INTEGER,
    whale_regime_label TEXT,
    agreed_with_trade INTEGER,             -- did signal agree with the taken trade
    trade_outcome TEXT                     -- win | loss | open
);

-- Live-approval gate state (single current row id=1).
CREATE TABLE IF NOT EXISTS approval_state (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    live_enabled             INTEGER DEFAULT 0,
    manual_confirmation      INTEGER DEFAULT 0,
    last_checked_ts          TEXT,
    readiness_json           TEXT
);

-- Per-venue runtime state machine.
CREATE TABLE IF NOT EXISTS venue_state (
    venue          TEXT PRIMARY KEY,
    mode           TEXT NOT NULL,          -- disabled | recommendation_only | paper | live
    live_enabled   INTEGER DEFAULT 0,
    credentials_connected INTEGER DEFAULT 0,
    kill_switch_tripped INTEGER DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    cooldown_until_ts TEXT,
    updated_ts     TEXT
);

-- Account balances / equity snapshots (per venue + aggregate).
CREATE TABLE IF NOT EXISTS account_balances (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    venue     TEXT NOT NULL,               -- 'AGGREGATE' for portfolio total
    equity    REAL NOT NULL,
    cash      REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    drawdown_pct REAL
);
CREATE INDEX IF NOT EXISTS idx_balances_ts ON account_balances(ts);

-- Blocked / rejected trades (RiskGate denials) — for the blocked table panel.
CREATE TABLE IF NOT EXISTS blocked_trades (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    venue     TEXT,
    symbol    TEXT,
    side      TEXT,
    qty       REAL,
    reason    TEXT NOT NULL,               -- RiskGate denial reason
    layer     TEXT                          -- which layer blocked (Layer1/Layer2)
);
CREATE INDEX IF NOT EXISTS idx_blocked_ts ON blocked_trades(ts);

-- Historical OHLCV bars per venue/symbol/timeframe. Feeds the native strategy
-- layer, dnn_advisory training, and backtests. UNIQUE(venue,symbol,timeframe,
-- timestamp) so a re-fetch upserts in place instead of duplicating.
CREATE TABLE IF NOT EXISTS bars (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    venue     TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    timeframe TEXT NOT NULL,               -- e.g. 1Day | 5Min
    timestamp TEXT NOT NULL,               -- ISO-8601 UTC bar open time
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    volume    REAL NOT NULL,
    UNIQUE(venue, symbol, timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_bars_lookup ON bars(symbol, timeframe, timestamp);

-- Current market regime per symbol (trending | range_bound | neutral). Written
-- by the regime detector; read by the dashboard to show the per-symbol regime.
CREATE TABLE IF NOT EXISTS regime_state (
    symbol        TEXT PRIMARY KEY,
    regime        TEXT NOT NULL,           -- trending | range_bound | neutral
    adx           REAL,
    rvol          REAL,
    active_factor TEXT,                    -- momentum | reversion | blend (regime-selected)
    updated_ts    TEXT NOT NULL
);
