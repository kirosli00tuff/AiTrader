"""The observation record (EXPERIMENT.md Task 8).

ONE ROW PER SYMBOL-DAY QUERIED, in a table this collector owns, in a database
this collector owns. It never opens `market_ai_lab.db`: the C++ engine is the
sole writer of the operational tables, and a research collector writing beside
it is how two writers come to disagree about what a row means.

RECORDING IS FREE AND UNRECORDED FIELDS ARE UNRECOVERABLE, so the schema is
deliberately wider than the primary test needs. Six fields beyond Task 8's list
are recorded, each because this session found something Task 8 could not have
anticipated:

  price_floor_at_formation  the rule id string says `p5` and Amendment 2 set
                            the floor to 10.00. Recording the floor makes every
                            row self-describing whatever the label says.
  delay_rolled              Task 4 says a rolled headline is scored, Task 8
                            lists `delay_rolled` as an exclusion reason. The
                            flag records the fact without resolving the
                            contradiction. See spec.DELAY_ROLL_IS_EXCLUSION.
  credential_shared         1 when the collector fell back to the council's key
                            (Open Question 9). The coupling is then in the data
                            rather than in a log.
  sector_source             so a NULL sector is distinguishable from a sector
                            nobody queried. Absence of evidence is not evidence
                            of absence, and this project has paid for that
                            distinction five times.
  outcome_state             pending | resolved | excluded. A freshly collected
                            row HAS no outcome, and a NULL return must never be
                            read as a zero return.
  run_kind                  demonstration | collection. A demonstration row can
                            never be counted toward the pre-registered sample.

`bar_source` follows the provenance rule already established: it records where
each price came from, and an unestablishable provenance is `unclassified`,
never a silent default.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime, timezone

from . import spec

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(_REPO_ROOT, "news_experiment.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS news_observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity and universe
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

    -- The observation state
    query_date TEXT NOT NULL,
    state TEXT NOT NULL,
    exclusion_reason TEXT NOT NULL DEFAULT '',

    -- The headline
    headline TEXT,
    source_name TEXT,
    source_article_id TEXT,
    published_ts TEXT,
    fetched_ts TEXT,
    story_group_id TEXT,

    -- The model call
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

    -- Tradeability at decision time
    etb INTEGER,
    shortable INTEGER,
    etb_source TEXT,

    -- Prices and outcome
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

    -- Provenance of the record itself
    spec_version TEXT NOT NULL,
    collector_git_sha TEXT,
    run_kind TEXT NOT NULL DEFAULT 'collection',
    written_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_symbol_day
    ON news_observation(symbol, query_date);
CREATE INDEX IF NOT EXISTS idx_obs_state ON news_observation(state);
CREATE INDEX IF NOT EXISTS idx_obs_story ON news_observation(story_group_id);
"""

# Every column the writer may set, in one place so a typo raises at write time
# rather than silently dropping a field.
COLUMNS = (
    "rule_id", "formation_date", "symbol", "adv_usd_at_formation",
    "liquidity_rank", "stratum", "median_close_at_formation",
    "price_floor_at_formation", "sector", "sector_source",
    "query_date", "state", "exclusion_reason",
    "headline", "source_name", "source_article_id", "published_ts",
    "fetched_ts", "story_group_id",
    "model_id", "prompt_sha256", "temperature", "called_ts", "latency_ms",
    "raw_response", "judgment", "strength", "strength_parse_ok",
    "neutral_strength_anomaly", "reason", "parse_ok", "error_class",
    "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd",
    "credential_shared",
    "etb", "shortable", "etb_source",
    "anchor_kind", "anchor_ts", "anchor_price", "scoring_session",
    "delay_rolled", "outcome_state", "ret_intraday", "ret_1session",
    "ret_2session", "ret_5session", "ret_10session", "bench_1session",
    "excess_1session", "bar_source", "cost_bp_round_trip", "net_bp",
    "spec_version", "collector_git_sha", "run_kind", "written_ts",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collector_git_sha() -> str:
    """The commit the collector ran at, so a code change mid-collection is
    visible in the data (Task 8). Empty when git cannot answer, never a
    plausible-looking placeholder."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, cwd=_REPO_ROOT)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - provenance absent is recorded as absent
        return ""


def open_store(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_observation(conn: sqlite3.Connection, row: dict) -> int:
    """Write one observation. Unknown keys raise rather than being dropped."""
    unknown = set(row) - set(COLUMNS)
    if unknown:
        raise KeyError(f"unknown observation columns: {sorted(unknown)}")
    values = dict(row)
    values.setdefault("spec_version", spec.SPEC_VERSION)
    values.setdefault("written_ts", now_iso())
    cols = [c for c in COLUMNS if c in values]
    placeholders = ",".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO news_observation ({','.join(cols)}) "
        f"VALUES ({placeholders})", [values[c] for c in cols])
    return int(cur.lastrowid or 0)


def coverage_summary(conn: sqlite3.Connection, query_date: str | None = None
                     ) -> dict:
    """The daily coverage summary (Task 7, "How absence is visible").

    Computed from the rows rather than kept as a second table, so it can never
    disagree with what was written.
    """
    where = "WHERE query_date = ?" if query_date else ""
    args: tuple = (query_date,) if query_date else ()
    counts = {s: 0 for s in spec.STATES}
    for state, n in conn.execute(
            f"SELECT state, COUNT(*) FROM news_observation {where} "
            f"GROUP BY state", args):
        counts[state] = n
    total = sum(counts.values())
    failed = counts.get(spec.STATE_SOURCE_FAILED, 0)
    fraction = (failed / total) if total else 0.0
    joiner = "AND" if where else "WHERE"
    anomalies = conn.execute(
        f"SELECT COUNT(*) FROM news_observation {where} "
        f"{joiner} neutral_strength_anomaly = 1", args).fetchone()[0]
    unparseable = conn.execute(
        f"SELECT COUNT(*) FROM news_observation {where} "
        f"{joiner} state = 'judged' AND strength_parse_ok = 0",
        args).fetchone()[0]
    return {
        "query_date": query_date or "ALL",
        "symbols_queried": total,
        **counts,
        "source_failed_fraction": fraction,
        "source_failed_critical":
            fraction > spec.SOURCE_FAILED_CRITICAL_FRACTION,
        "day_excluded": fraction > spec.SOURCE_FAILED_DAY_EXCLUDE_FRACTION,
        "strength_unparseable": unparseable,
        "neutral_strength_not_one": anomalies,
    }


def strength_distribution(conn: sqlite3.Connection) -> dict:
    """The strength histogram over SCORED observations (Open Question 10).

    NEUTRAL is excluded because its strength is fixed at 1 by the prompt and
    carries no information by construction, so including it would manufacture a
    spike at 1 and make a degenerate distribution look like a real one.
    """
    rows = conn.execute(
        "SELECT strength, COUNT(*) FROM news_observation "
        "WHERE state='judged' AND judgment IN ('POSITIVE','NEGATIVE') "
        "AND strength_parse_ok=1 GROUP BY strength ORDER BY strength"
    ).fetchall()
    hist = {int(s): int(n) for s, n in rows if s is not None}
    total = sum(hist.values())
    top = max(hist.values()) if hist else 0
    return {
        "histogram": hist,
        "scored_directional": total,
        "distinct_values": len(hist),
        # Task 5's recorded reversal condition for the five-point scale.
        "degenerate": bool(total) and (top / total > 0.80 or len(hist) < 3),
    }
