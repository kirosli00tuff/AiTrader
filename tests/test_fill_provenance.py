"""Fill provenance: `unclassified` is a live marker, `unknown` stays history.

THE DEFECT (diagnosed 2026-07-27). `trades.bar_source` collapsed four different
conditions onto the single literal `unknown`: no provenance available, written
before provenance was known, written by a path that never set the column, and
inheriting the ALTER default. Two silent fallbacks did it, a struct field
default (`storage.hpp`) and an empty-string ternary (`storage.cpp`), and
neither left an event or a log. The trades table held ZERO NULLs, so even the
migration left no marker separating history from a live gap.

THE SPLIT. `unknown` keeps ONE meaning, an unmigrated historical row, and no
live write can produce it any more. A live write whose bar provenance cannot be
established records `unclassified` and SUCCEEDS, because insert_trade records a
fill that already happened at the venue: refusing would destroy the only record
it occurred and hide the position from reconciliation and rehydration. That is
the opposite of the bar path, where a refused bar can be refetched. Because a
silent marker is how three fabrication defects survived, every such write emits
a CRITICAL fill_provenance_unclassified event and surfaces in the GUI.

These tests cover the Python-visible half plus the guards:
  * historical `unknown` rows are untouched by the change,
  * the fresh-database and migrated-database schemas agree about the column,
  * the real-fill gate excludes `unclassified` by the same rule that already
    excludes `unknown`,
  * and the two silent fallbacks stay removed (mutation guard).

The C++ write behaviour itself is pinned by ctest `provenance`.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess

import pytest

from api_server.operator import WATCHDOG_KINDS
from market_data.tradeable import REAL_SOURCES
from ml_factor.real_dataset import count_closed_trades

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "storage", "schema.sql")
STORAGE_HPP = os.path.join(REPO, "storage", "storage.hpp")
STORAGE_CPP = os.path.join(REPO, "storage", "storage.cpp")

UNCLASSIFIED = "unclassified"
HISTORICAL = "unknown"

# The one route the column takes into `trades`, from storage.cpp's migration
# list. schema.sql declares no bar_source on trades, so a fresh database and a
# migrated one both get the column from exactly this statement.
MIGRATION = "ALTER TABLE trades ADD COLUMN bar_source TEXT DEFAULT 'unknown'"


def _db(migrate: bool = True) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.executescript(
        open(SCHEMA).read().replace("PRAGMA journal_mode = WAL;", ""))
    if migrate:
        c.execute(MIGRATION)
    return c


def _fill(conn, bar_source, origin="strategy", outcome="win", pnl=1.0):
    conn.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,pnl,"
        "outcome,origin,bar_source) VALUES('2026-07-27T00:00:00Z','alpaca',"
        "'SPY','sell',1,100,100,'paper',?,?,?,?)",
        (pnl, outcome, origin, bar_source))


# --- the real-fill gate ----------------------------------------------------- #

def test_the_gate_excludes_unclassified_by_the_same_rule_as_unknown():
    """No new rule. count_closed_trades counts REAL_SOURCES only, so a fill
    whose provenance was never established is excluded for exactly the reason
    an unmigrated historical one is: the gate cannot prove it."""
    conn = _db()
    for _ in range(30):
        _fill(conn, UNCLASSIFIED)
    assert count_closed_trades(conn) == 0
    for _ in range(30):
        _fill(conn, HISTORICAL)
    assert count_closed_trades(conn) == 0, (
        "unclassified and unknown must both be uncountable, and for the same "
        "reason")
    for _ in range(4):
        _fill(conn, "real_feed")
    assert count_closed_trades(conn) == 4, (
        "only provenance-confirmed fills count; the 60 unprovable ones do not")


def test_unclassified_is_not_in_the_real_source_set():
    """The marker can never drift into the set that opens the RL gate."""
    assert UNCLASSIFIED not in REAL_SOURCES
    assert HISTORICAL not in REAL_SOURCES
    assert REAL_SOURCES == ("real_feed", "backfill")


# --- historical rows -------------------------------------------------------- #

def test_historical_unknown_rows_are_untouched_by_the_split():
    """The change adds a value; it rewrites nothing. A row written before the
    split still reads `unknown` afterwards, and reading it does not rewrite
    it."""
    conn = _db()
    for _ in range(5):
        _fill(conn, HISTORICAL)
    before = conn.execute(
        "SELECT id,ts,symbol,origin,bar_source FROM trades ORDER BY id"
    ).fetchall()
    assert count_closed_trades(conn) == 0
    after = conn.execute(
        "SELECT id,ts,symbol,origin,bar_source FROM trades ORDER BY id"
    ).fetchall()
    assert before == after, "reading the gate must not rewrite a historical row"
    assert {r[4] for r in after} == {HISTORICAL}


def test_no_code_path_rewrites_an_existing_bar_source():
    """A migration of the 247 historical rows was considered and rejected: the
    information to reclassify them was never recorded, so any rewrite would be
    a guess. Nothing may UPDATE the column."""
    src = open(STORAGE_CPP).read()
    assert not re.search(r"UPDATE\s+trades\s+SET[^\"]*bar_source", src,
                         re.IGNORECASE), (
        "storage must never rewrite a recorded fill provenance")
    for stmt in re.findall(r'"(ALTER TABLE trades[^"]*)"', src):
        assert "bar_source" not in stmt or "ADD COLUMN" in stmt, (
            f"only an additive migration is allowed, found: {stmt}")


# --- fresh vs migrated schema ----------------------------------------------- #

def test_a_fresh_database_and_a_migrated_one_agree_about_the_column():
    """TASK 1, CHECKED RATHER THAN ASSUMED. The diagnosis claimed schema.sql
    declared trades.bar_source with no default while the migration used
    DEFAULT 'unknown', so the two paths disagreed. They do not: schema.sql
    declares no bar_source on `trades` at all (line 481 is entry_decision's own
    column), so the ALTER is the ONLY route on both paths and both get the same
    default. Pinned here so the disagreement cannot be introduced later."""
    fresh, migrated = _db(migrate=True), _db(migrate=True)
    for c in (fresh, migrated):
        cols = {r[1]: r[4] for r in c.execute("PRAGMA table_info(trades)")}
        assert "bar_source" in cols
        assert cols["bar_source"] == "'unknown'", (
            "both paths must agree an omitted column means the historical "
            f"marker, got {cols['bar_source']!r}")
    # And omitting the column really does yield that value, not NULL.
    migrated.execute(
        "INSERT INTO trades(ts,venue,symbol,side,qty,price,notional,mode,"
        "outcome) VALUES('2026-07-27T00:00:00Z','alpaca','SPY','buy',1,100,"
        "100,'paper','open')")
    assert migrated.execute(
        "SELECT bar_source FROM trades").fetchone()[0] == HISTORICAL


def test_schema_sql_declares_no_bar_source_on_trades():
    """The premise behind the fresh-versus-migrated worry, pinned. If someone
    adds the column to the CREATE TABLE without a matching default, the two
    paths start disagreeing about an omitted column and this fails."""
    text = open(SCHEMA).read()
    block = re.search(r"CREATE TABLE IF NOT EXISTS trades \((.*?)\n\);", text,
                      re.S)
    assert block, "trades block not found in schema.sql"
    assert "bar_source" not in block.group(1), (
        "trades.bar_source now exists in schema.sql; it must carry "
        "DEFAULT 'unknown' to match the migration, or the two paths disagree")


# --- the mutation guard ----------------------------------------------------- #

def test_the_struct_field_default_stays_removed():
    """MUTATION GUARD 1. `std::string bar_source = "unknown";` pre-substituted
    the HISTORICAL marker before the write path could see the omission. Its
    removal is what makes an unset field detectable at all."""
    decl = re.search(r"^\s*std::string bar_source\s*(=[^;]*)?;",
                     _strip_line_comments(open(STORAGE_HPP).read()), re.M)
    assert decl, "TradeRow::bar_source declaration not found"
    assert decl.group(1) is None, (
        "TradeRow::bar_source has a default again: a caller that forgets to "
        "state provenance would silently write the historical marker")


def _strip_line_comments(src: str) -> str:
    """Comments are prose, not behaviour. The guards below scan CODE: the
    removed ternary is quoted verbatim in a comment explaining why it went, and
    a guard that cannot tell those apart fails on its own documentation."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.splitlines())


def test_the_empty_string_ternary_stays_removed():
    """MUTATION GUARD 2. `t.bar_source.empty() ? "unknown" : t.bar_source` sent
    an unestablished live fill to the historical bucket with no event."""
    body = re.search(r"long long Storage::insert_trade\(.*?\n\}",
                     open(STORAGE_CPP).read(), re.S)
    assert body, "insert_trade body not found"
    src = _strip_line_comments(body.group(0))
    assert '"unknown"' not in src, (
        "insert_trade names the historical marker again; a live write must "
        "never be able to produce it")
    assert "provenance::fill::classify" in src, (
        "insert_trade must classify its provenance, not substitute a literal")
    assert "fill_provenance_unclassified" in src, (
        "the marker must never travel without its CRITICAL event")
    assert '"critical"' in src, "the event must be severity critical"


def test_every_engine_trade_write_states_its_provenance():
    """MUTATION GUARD 3. The compiler cannot force a struct field to be set, so
    a guard test does for trades what engine.hpp's required `bar_source`
    parameter does for bars. Every insert_trade call site in the engine must
    assign the field first, or a forgotten one silently becomes unclassified in
    production."""
    src = open(os.path.join(REPO, "core", "engine.cpp")).read()
    sites = [m.start() for m in re.finditer(r"insert_trade\(tr\)", src)]
    assert len(sites) >= 6, f"expected the known call sites, found {len(sites)}"
    for at in sites:
        window = src[max(0, at - 2500):at]
        row = window.rfind("storage::TradeRow tr;")
        assert row != -1, "insert_trade(tr) with no TradeRow in scope"
        assert "tr.bar_source" in window[row:], (
            "an engine trade write does not state its bar provenance; it "
            "would land unclassified with a CRITICAL event")


# --- GUI surfacing ---------------------------------------------------------- #

def test_the_event_surfaces_in_the_gui():
    """A CRITICAL event nobody can see is the silent marker in another shape."""
    assert "fill_provenance_unclassified" in WATCHDOG_KINDS
    panels = open(os.path.join(REPO, "web", "src", "components",
                               "DiagnosticsPanels.tsx")).read()
    assert "fill_provenance_unclassified" in panels, (
        "the diagnostics view must label and style the condition")


# --- end to end through the real writer -------------------------------------- #

@pytest.mark.skipif(
    not os.path.exists(os.path.join(REPO, "build", "tests", "test_provenance")),
    reason="C++ suite not built")
def test_the_cpp_writer_agrees_with_this_module():
    """The C++ binary is the only thing that writes trades, so the Python view
    of the rule is checked against it rather than restated."""
    out = subprocess.run(
        [os.path.join(REPO, "build", "tests", "test_provenance")],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "lands unclassified" in out.stdout
