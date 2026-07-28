"""Trading scope: US equities only, crypto retained as DATA (2026-07-27).

WHY THE SCOPE NARROWED, all of it measured in this repository:
  * a crypto round trip costs 50 bp against 1.14 to 4.87 bp for equities in
    the tradeable liquidity bands,
  * the re-costed P26 result splits -48.78 bp crypto against -2.73 equity,
  * the council abstained on 87 to 94 percent of crypto calls against 43 to 47
    percent on equities.
Crypto also carried a 24/7 loop, regional-session carve-outs, venue
serviceability checks, and its own fee schedule.

THIS IS A SCOPE CHANGE, NOT A DELETION, and the tests split along exactly that
line. What must STOP: any crypto symbol reaching an entry decision, by any
path. What must CONTINUE: polling, provenance, storage, the stored history, the
crypto fee schedule, the venue plumbing, and every exit.

A partial removal that leaves one path open is worse than none, so the paths
are enumerated here as tests rather than trusted.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess

import pytest

from market_data.tradeable import (TRADEABLE_ASSET_CLASSES, asset_class,
                                   symbol_in_trading_scope)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, "build", "mal_engine")
SCOPE_HPP = os.path.join(REPO, "core", "trading_scope.hpp")
ENGINE_CPP = os.path.join(REPO, "core", "engine.cpp")
UNIVERSE_PY = os.path.join(REPO, "market_data", "universe.py")

CRYPTO = ("BTC/USD", "ETH/USD", "SOL/USD", "SHIB/USD", "UNI/USD")
EQUITY = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")


# ---- the rule itself ------------------------------------------------------

def test_the_scope_set_is_equities_only():
    assert TRADEABLE_ASSET_CLASSES == ("equity",)


def test_classification_uses_the_slash_rule_the_engine_already_used():
    for s in CRYPTO:
        assert asset_class(s) == "crypto"
    for s in EQUITY:
        assert asset_class(s) == "equity"
    assert asset_class("BRK.B") == "equity"


def test_no_crypto_symbol_is_in_trading_scope():
    for s in CRYPTO:
        assert not symbol_in_trading_scope(s)
    for s in EQUITY:
        assert symbol_in_trading_scope(s)


def test_an_unknown_class_is_excluded_rather_than_admitted():
    """Absence of evidence is not evidence. A class nobody classified must not
    default into the traded universe, the same shape as the universe rule's
    unclassified exclusion."""
    assert "politics" not in TRADEABLE_ASSET_CLASSES


# ---- the universe layer is the single point of exclusion ------------------

def test_the_resolver_holds_crypto_out_and_names_it():
    """THE PYTHON RESOLUTION POINT. Every consumer calls resolve, so excluding
    here excludes everywhere without each path filtering for itself."""
    from market_data import universe
    u = universe.resolve(db_path=None)
    assert all(symbol_in_trading_scope(s) for s in u.symbols)
    assert all(symbol_in_trading_scope(s) for s in u.core)
    assert set(u.out_of_scope) >= {"BTC/USD", "ETH/USD"}
    # OUT OF SCOPE IS NOT UNSERVICEABLE. The feed serves these perfectly.
    assert not set(u.out_of_scope) & set(u.unserviceable)


def test_out_of_scope_is_reported_separately_from_unserviceable():
    """Reporting a healthy feed as unserviceable would raise a feed alarm about
    a feed that is working, which is the false alarm this split prevents."""
    from market_data import universe
    u = universe.resolve(db_path=None)
    assert u.unserviceable == []
    assert u.out_of_scope


def test_discovery_yields_no_crypto_candidates():
    """The funnel must not rank, screen, or pay a council round for a symbol
    that could not be bought afterwards."""
    from discovery import universe as duniverse
    assert duniverse.universe_for("crypto", ":memory:", None, None) == []


# ---- the two language halves agree ----------------------------------------

def test_the_cpp_and_python_scope_sets_are_equal():
    """Two copies of a scope rule is how two halves of a system come to
    disagree about what may be traded."""
    src = open(SCOPE_HPP).read()
    body = re.search(r"inline bool is_tradeable_class\((.*?)\n\}", src, re.S)
    assert body, "is_tradeable_class not found"
    for cls in TRADEABLE_ASSET_CLASSES:
        assert f"== k{cls.capitalize()}" in body.group(1), (
            f"C++ scope set omits {cls}")
    assert "kCrypto" not in body.group(1), (
        "the C++ half admits crypto while the Python half does not")


# ---- the mutation guard ---------------------------------------------------

def test_the_universe_layer_exclusion_stays_in_place():
    """MUTATION GUARD. Reverting the universe-level exclusion is the whole
    change undone: every consumer inherits from this one filter, so removing
    it re-admits crypto to every path at once."""
    src = open(UNIVERSE_PY).read()
    assert "symbol_in_trading_scope" in src, (
        "market_data/universe.py no longer applies the scope rule; crypto is "
        "back in the traded universe on every consumer")
    assert re.search(r"core_declared = \[s for s in core_declared\s*\n?\s*"
                     r"if symbol_in_trading_scope\(s\)\]", src), (
        "the core is no longer scope-filtered at the resolution point")


def test_the_engine_entry_paths_all_carry_the_scope_gate():
    """MUTATION GUARD, C++ side. Every entry path must refuse an out-of-scope
    class: the native bar close, the legacy bootstrap-sim loop, and the
    research satellite, which has its own whitelist."""
    src = "\n".join(re.sub(r"//.*$", "", ln)
                    for ln in open(ENGINE_CPP).read().splitlines())
    assert "scope::symbol_in_scope" in src, (
        "the engine no longer consults the trading scope")
    assert src.count("scope::symbol_in_scope") >= 4, (
        "an entry path lost its scope gate; a partial removal that leaves one "
        "path open is worse than none")


# ---- the data path is retained --------------------------------------------

@pytest.mark.skipif(not os.path.exists(ENGINE), reason="engine not built")
def test_crypto_bars_still_store_with_provenance(tmp_path):
    """THE RETENTION HALF. Crypto is collected, labelled, and stored exactly as
    before. Only trading stopped."""
    db = str(tmp_path / "scope.db")
    subprocess.run(
        [ENGINE, "--db", db, "--iterations", "600",
         "--feed-mode", "synthetic_regimes", "--clock-mode", "simulated"],
        capture_output=True, text=True, cwd=REPO, timeout=600)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT symbol, COUNT(*) FROM bars WHERE symbol LIKE '%/%' "
        "GROUP BY symbol").fetchall()
    assert rows, "no crypto bars stored: the data path was removed, not retained"
    for symbol, n in rows:
        assert n > 0, f"{symbol} stored no bars"
    bad = conn.execute(
        "SELECT COUNT(*) FROM bars WHERE symbol LIKE '%/%' "
        "AND (source IS NULL OR source='')").fetchone()[0]
    assert bad == 0, "crypto bars lost their provenance label"


@pytest.mark.skipif(not os.path.exists(ENGINE), reason="engine not built")
def test_no_crypto_reaches_an_entry_decision_or_a_trade(tmp_path):
    """THE REMOVAL HALF, end to end through the real engine rather than by
    inspection. The whitelist still declares BTC/USD, ETH/USD and SOL/USD and
    they still produce bars, so this proves the gate rather than an empty
    universe."""
    db = str(tmp_path / "scope2.db")
    subprocess.run(
        [ENGINE, "--db", db, "--iterations", "1500",
         "--feed-mode", "synthetic_regimes", "--clock-mode", "simulated"],
        capture_output=True, text=True, cwd=REPO, timeout=900)
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM bars WHERE symbol LIKE '%/%'").fetchone()[0] > 0, (
        "the run produced no crypto bars, so it cannot prove the gate")
    assert conn.execute(
        "SELECT COUNT(*) FROM entry_decision WHERE symbol LIKE '%/%'"
    ).fetchone()[0] == 0, "a crypto symbol reached an entry decision"
    assert conn.execute(
        "SELECT COUNT(*) FROM trades WHERE symbol LIKE '%/%'"
    ).fetchone()[0] == 0, "a crypto symbol was traded"
    assert conn.execute(
        "SELECT COUNT(*) FROM entry_decision WHERE symbol NOT LIKE '%/%'"
    ).fetchone()[0] > 0, "no equity decisions either: the universe collapsed"


# ---- market hours: entry only, never exits, collection continues ----------

def test_exits_are_exempt_from_the_market_hours_restriction():
    """A position is NEVER trapped. The gate names equity ENTRY and the exit
    path runs above it in handle_bar_close, so an exit cannot reach it."""
    src = open(ENGINE_CPP).read()
    gate = src.index("equity_entry_blocked_by_market_hours")
    entry_marker = src.index("---------- ENTRY path")
    assert gate > entry_marker, (
        "the market-hours gate moved above the entry marker; it could now "
        "block an exit and trap a position")


def test_the_scope_gate_sits_below_the_exit_path_so_it_cannot_trap_a_position():
    """Same reasoning for the scope gate itself: a crypto position opened
    before the narrowing must still be managed and closed."""
    src = open(ENGINE_CPP).read()
    entry_marker = src.index("---------- ENTRY path")
    first_scope_gate = src.index("scope::symbol_in_scope", entry_marker)
    assert first_scope_gate > entry_marker, (
        "the scope gate moved above the exit path and would trap a position")


def test_off_hours_collection_is_not_gated():
    """Material news arrives after the close, so the loop keeps collecting
    outside the session. Only ENTRY is restricted, and bar ingestion consults
    neither the market-hours gate nor the scope gate."""
    src = open(ENGINE_CPP).read()
    fn = re.search(r"void Engine::on_closed_bar\(.*?\n\}", src, re.S)
    assert fn, "on_closed_bar not found"
    assert "equity_entry_blocked_by_market_hours" not in fn.group(0), (
        "bar ingestion consults the market-hours gate; collection would stop "
        "outside the session")
    assert "scope::symbol_in_scope" not in fn.group(0), (
        "bar ingestion consults the scope gate; crypto collection would stop")
