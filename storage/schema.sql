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
    decision_id   INTEGER
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
    UNIQUE(venue, symbol)
);

-- Raw signals from factor families (one row per factor per evaluation).
CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    venue     TEXT,
    symbol    TEXT,
    factor    TEXT NOT NULL,                 -- llm_primary | rule_based | dnn_rl | whale_signal ...
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
    source    TEXT NOT NULL,               -- apify | whale_alert | sec_13f
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
