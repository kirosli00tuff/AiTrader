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
    return c


def _fill(conn, origin: str, outcome: str = "win", pnl: float | None = 1.0):
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,pnl,"
        "outcome,origin) VALUES('2026-07-16T00:00:00Z','alpaca','SPY','sell',"
        "1,100,100,'paper',?,?,?)", (pnl, outcome, origin))


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
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,pnl,"
        "outcome) VALUES('2026-07-16T00:00:00Z','alpaca','SPY','sell',1,100,"
        "100,'paper',1.0,'win')")
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
