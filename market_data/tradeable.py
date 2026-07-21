"""THE tradeable invariant, Python side (2026-07-20).

On the real path (feed_mode alpaca_paper) a symbol with no real bar history is
NOT TRADEABLE. It is not evaluated, no bar is ever fabricated for it, and it
never contributes to a stack-level alarm. Its only condition is
symbol_unavailable: contained, per-symbol, prune-worthy, never remediation.

This module is the ONE Python enforcement point. Every Python consumer (the
watchdog's feed health, discovery onboarding) calls ``symbol_is_tradeable``
rather than re-deriving the check. Adding a new bar-consuming path means
calling this predicate, not writing a new check: a guard test
(tests/test_tradeable_invariant.py) pins the consumers and refuses ad-hoc
provenance queries elsewhere.

Real bar history means at least one bar whose provenance is REAL_SOURCES
(real_feed or backfill), any timeframe. The C++ enforcement point is
Engine::symbol_is_tradeable over Storage::has_real_bars, the same definition
against the same table; a drift-guard test pins the two source sets equal.

Why history and not the newest bar: the newest bar is a freshness and
substitution question. History answers a different one, has the venue EVER
served this symbol. A symbol the venue has never served (MANA/USD and RUNE/USD
on Alpaca, live 2026-07-20) can never go stale and can never be substituted,
because it was never fresh and never real. It can only be unavailable.
"""
from __future__ import annotations

import sqlite3

# The provenances that count as REAL market data. Must match the source set in
# Storage::has_real_bars (storage/storage.cpp) and core/provenance.hpp.
REAL_SOURCES = ("real_feed", "backfill")


def symbol_is_tradeable(conn: sqlite3.Connection, symbol: str) -> bool:
    """Whether ``symbol`` has real bar history. THE predicate.

    A DB whose bars table predates the provenance migration has no source
    column and cannot prove provenance. There, any bar counts as history: the
    old semantics are kept rather than grounding every symbol on a DB that
    cannot answer the question. A missing bars table means no history.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM bars WHERE symbol=? AND source IN (?,?) LIMIT 1",
            (symbol, *REAL_SOURCES)).fetchone()
        return row is not None
    except sqlite3.OperationalError as e:
        if "no such column" in str(e):
            try:
                row = conn.execute(
                    "SELECT 1 FROM bars WHERE symbol=? LIMIT 1",
                    (symbol,)).fetchone()
                return row is not None
            except sqlite3.OperationalError:
                return False
        return False  # no bars table: no history


def untradeable_symbols(conn: sqlite3.Connection,
                        symbols: list[str]) -> list[str]:
    """The subset of ``symbols`` failing the predicate, order preserved."""
    return [s for s in symbols if not symbol_is_tradeable(conn, s)]


def real_bar_rows(conn: sqlite3.Connection, symbol: str,
                  timeframe: str = "5min", limit: int = 288) -> list[tuple]:
    """Newest-first (timestamp, close, volume, source) rows with REAL
    provenance, for consumers that must show only real market data (the
    council evidence renderer). Lives here so the provenance source set stays
    in this one module, per the tradeable invariant's guard.

    A pre-provenance DB (no source column) returns NO rows: evidence labelled
    "real venue bars" must never rest on unprovable provenance. That is
    deliberately stricter than symbol_is_tradeable's fallback, which answers a
    different question.
    """
    try:
        return conn.execute(
            "SELECT timestamp, close, volume, source FROM bars "
            "WHERE symbol=? AND timeframe=? AND source IN (?,?) "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, timeframe, *REAL_SOURCES, int(limit))).fetchall()
    except sqlite3.OperationalError:
        return []
