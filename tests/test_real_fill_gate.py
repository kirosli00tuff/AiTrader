"""The real-fill gate counts STRATEGY fills only.

count_closed_trades gates the DNN real-data trainer AND the RL 500-fill
activation (`rl_min_real_fills`, a CLAUDE.md hard rule). Both build their
features from `bars`, so this is purely a GATE: it answers "has the policy been
exercised enough to train on", not "have any fills occurred".

An adaptive defensive exit and a sleeve rebalance trim are real fills that moved
real money, but neither is a decision the policy made. Counting them opens a
training gate on trades that taught nothing. These tests fail against the
pre-`origin` code, which counted every closed row.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from ml_factor.real_dataset import count_closed_trades

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "storage", "schema.sql")


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        open(SCHEMA).read().replace("PRAGMA journal_mode = WAL;", ""))
    # The provenance column arrives by migration in production, not in the base
    # schema, so the fixture applies it the same way. Without it the counter
    # can confirm nothing and every case below would read zero for the wrong
    # reason, hiding the origin filter these tests exist to check.
    c.execute("ALTER TABLE trades ADD COLUMN bar_source TEXT")
    return c


def _fill(conn, origin: str, outcome: str = "win", pnl: float | None = 1.0,
          bar_source: str = "real_feed"):
    """A closed fill. bar_source defaults to CONFIRMED REAL so these tests keep
    exercising the origin filter they were written for. Since 2026-07-27 the
    counter counts only provenance-confirmed fills, so leaving it NULL would
    make every case here read zero for the wrong reason."""
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,pnl,"
        "outcome,origin,bar_source) VALUES('2026-07-16T00:00:00Z','alpaca',"
        "'SPY','sell',1,100,100,'paper',?,?,?,?)",
        (pnl, outcome, origin, bar_source))


def test_an_unprovable_fill_does_not_count(conn):
    """THE 2026-07-27 CORRECTION. The provenance column arrived by an ALTER
    that left every pre-existing row at 'unknown', and that bucket is dominated
    by the offline synthetic loop. Counting it read 249 against 9 confirmed
    real fills. A gate that says "not yet" must not count what it cannot
    prove."""
    for _ in range(20):
        _fill(conn, "strategy", bar_source="unknown")
    for _ in range(5):
        _fill(conn, "strategy", bar_source=None)
    assert count_closed_trades(conn) == 0, (
        "unknown and NULL provenance are unprovable, so they do not count")
    for _ in range(3):
        _fill(conn, "strategy", bar_source="real_feed")
    for _ in range(2):
        _fill(conn, "strategy", bar_source="backfill")
    assert count_closed_trades(conn) == 5, (
        "only real_feed and backfill are confirmed real")


def test_only_strategy_fills_count_toward_the_gate(conn):
    for _ in range(3):
        _fill(conn, "strategy")
    for _ in range(5):
        _fill(conn, "adaptive_react")
    for _ in range(4):
        _fill(conn, "rebalance")
    assert count_closed_trades(conn) == 3, (
        "12 closed fills, but only 3 were policy decisions")


def test_a_news_exit_never_opens_the_rl_500_fill_gate(conn):
    """The concrete harm: a busy news week could march the RL activation gate
    toward 500 on exits the policy never chose."""
    for _ in range(600):
        _fill(conn, "adaptive_react")
    assert count_closed_trades(conn) == 0
    from rl_advisory.dataset import count_real_fills  # the gate's real consumer
    assert callable(count_real_fills)


def test_a_rebalance_trim_does_not_count_either(conn):
    """This bug PREDATES the adaptive layer: drift mechanics decided the trim,
    not the strategy. The discriminator fixes both at once."""
    for _ in range(50):
        _fill(conn, "rebalance")
    assert count_closed_trades(conn) == 0


def test_the_default_origin_is_strategy(conn):
    """Every existing call site keeps its meaning without being touched: only
    the two non-strategy paths set origin, so an unset row counts."""
    # origin is left unset on purpose, which is the point of this test. Since
    # 2026-07-27 provenance must also be confirmed, so bar_source is set: the
    # origin DEFAULT is what is under test here, not the provenance rule, which
    # test_an_unprovable_fill_does_not_count covers on its own.
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,pnl,"
        "outcome,bar_source) VALUES('2026-07-16T00:00:00Z','alpaca','SPY',"
        "'sell',1,100,100,'paper',1.0,'win','real_feed')")
    assert count_closed_trades(conn) == 1


def test_an_open_trade_still_does_not_count(conn):
    _fill(conn, "strategy", outcome="open", pnl=None)
    assert count_closed_trades(conn) == 0


def test_an_old_db_without_the_column_falls_back_rather_than_crashing(conn):
    """A DB written before the migration has no column to filter on. The
    information to tell the fills apart was never recorded, so it cannot be
    recovered: falling back to the unfiltered count is the honest option, and
    crashing the trainer is not."""
    old = sqlite3.connect(":memory:")
    old.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, outcome TEXT, "
        "pnl REAL)")
    for _ in range(4):
        old.execute("INSERT INTO trades(ts,outcome,pnl) VALUES('t','win',1.0)")
    assert count_closed_trades(old) == 4, "pre-origin behavior, not a crash"
