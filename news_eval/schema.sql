-- news_eval/schema.sql: the news_observation table as the real
-- database declares it (STAGE C.1 Task 1; GUARDRAILS read 2;
-- Amendment 9.15). Written by the loader's SCHEMA phase:
--   python -m news_eval.data schema --out news_eval/schema.sql
-- which ran `PRAGMA table_info(news_observation)` on
--   file:news_experiment.db?mode=ro (read-only URI)
-- at 2026-10-11T06:12:30Z and read nothing else.
-- Column order, declared type, NOT NULL and DEFAULT text are exactly
-- what PRAGMA returned.
-- AUTOINCREMENT on id: not visible to PRAGMA; news_experiment/store.py declares it.
-- PRAGMA and news_experiment/store.py's DDL agree on every column, type, NOT NULL, DEFAULT and key.
CREATE TABLE news_observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id TEXT NOT NULL,
    formation_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    adv_usd_at_formation REAL,
    liquidity_rank INTEGER,
    stratum TEXT,
    median_close_at_formation REAL,
    price_floor_at_formation REAL,
    sector TEXT,
    sector_source TEXT,
    query_date TEXT NOT NULL,
    state TEXT NOT NULL,
    exclusion_reason TEXT NOT NULL DEFAULT '',
    headline TEXT,
    source_name TEXT,
    source_article_id TEXT,
    published_ts TEXT,
    fetched_ts TEXT,
    story_group_id TEXT,
    model_id TEXT,
    prompt_sha256 TEXT,
    temperature REAL,
    called_ts TEXT,
    latency_ms INTEGER,
    raw_response TEXT,
    judgment TEXT,
    strength INTEGER,
    strength_parse_ok INTEGER,
    neutral_strength_anomaly INTEGER,
    reason TEXT,
    parse_ok INTEGER,
    error_class TEXT,
    input_tokens INTEGER,
    cached_input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    credential_shared INTEGER NOT NULL DEFAULT 0,
    etb INTEGER,
    shortable INTEGER,
    etb_source TEXT,
    anchor_kind TEXT,
    anchor_ts TEXT,
    anchor_price REAL,
    scoring_session TEXT,
    delay_rolled INTEGER NOT NULL DEFAULT 0,
    outcome_state TEXT NOT NULL DEFAULT 'pending',
    ret_intraday REAL,
    ret_1session REAL,
    ret_2session REAL,
    ret_5session REAL,
    ret_10session REAL,
    bench_1session REAL,
    excess_1session REAL,
    bar_source TEXT,
    cost_bp_round_trip REAL,
    net_bp REAL,
    spec_version TEXT NOT NULL,
    collector_git_sha TEXT,
    run_kind TEXT NOT NULL DEFAULT 'collection',
    written_ts TEXT NOT NULL
);
-- Indexes: taken verbatim from news_experiment/store.py's SCHEMA text, not read from the real database.
CREATE INDEX IF NOT EXISTS idx_obs_symbol_day
    ON news_observation(symbol, query_date);
CREATE INDEX IF NOT EXISTS idx_obs_state ON news_observation(state);
CREATE INDEX IF NOT EXISTS idx_obs_story ON news_observation(story_group_id);
