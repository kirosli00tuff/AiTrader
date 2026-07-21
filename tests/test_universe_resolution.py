"""THE universe: a verified core plus a discovered periphery, resolved once.

The 2026-07-21 state is the spec. The active_quant core declared eight symbols.
SOL/USD read WARM on 8,519 bars that every one carried source 'unknown', so the
warm check passed a symbol the tradeable predicate refuses and the entry path
had already ruled out. AAPL, MSFT, and NVDA sat at zero bars because the
warm-start backfill asked for a hardcoded four-name subset, and the engine's own
instrument list was a second hardcoded four-name literal, so those three were
never polled either. Two lists, two standards, in two languages.

These tests pin the resolution end to end:
  * a symbol with only unknown bars is not tradeable and cannot read WARM,
  * core verification refuses a symbol the venue does not serve, and verifies
    NOTHING when the backfill could not run,
  * the backfill requests every core symbol,
  * the universe resolves in ONE place (no consumer builds its own list),
  * an empty or nearly empty universe raises the loud condition,
  * the discovered periphery joins under the same predicate,
  * the C++ and Python definitions cannot drift.

No network, nothing binds: tmp SQLite DBs, monkeypatches, and source scrapes.
"""
from __future__ import annotations

import os
import re
import sqlite3

import pytest

from api_server import stack
from market_data import alpaca_source, universe

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))


def _mk_db(tmp_path, bars, watchlist=()):
    """bars: (symbol, ts, source) rows. watchlist: (symbol, status) rows."""
    db = tmp_path / "universe.db"
    conn = sqlite3.connect(db)
    alpaca_source.ensure_bars_schema(conn)
    for symbol, ts, source in bars:
        conn.execute(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source) VALUES('alpaca',?,?,?,1,2,0.5,1.5,10,?)",
            (symbol, "5min", ts, source))
    if watchlist:
        from discovery import watchlist as wl
        wl.ensure_schema(conn)
        for symbol, status in watchlist:
            conn.execute(
                "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,"
                "source,reason,sleeve_target,score,status) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (symbol, "crypto", "2026-07-21T00:00:00Z",
                 "2026-07-21T00:00:00Z", "discovery", "test", "quant_core",
                 0.6, status))
    conn.commit()
    conn.close()
    return str(db)


def _pin(monkeypatch, core, *, real=True, discovery=False):
    """Pin the declared core and the path, at their one definition each."""
    monkeypatch.setattr(universe, "declared_core", lambda *a, **k: list(core))
    monkeypatch.setattr(universe, "real_feed_mode", lambda *a, **k: real)
    monkeypatch.setattr(universe, "discovery_enabled",
                        lambda *a, **k: discovery)


def _read(path: str) -> str:
    with open(os.path.join(REPO, path)) as fh:
        return fh.read()


# --- Unknown provenance is not tradeable, and cannot read WARM ---------------

def test_symbol_with_only_unknown_bars_is_not_in_the_universe(tmp_path,
                                                              monkeypatch):
    # THE SOL/USD shape: thousands of bars, every one 'unknown'. Real Alpaca
    # history from before the provenance migration, but unprovable, so the
    # predicate refuses it and the universe holds it out.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", "2026-07-21T07:00:00Z", "backfill")] +
                [("SOL/USD", f"2026-07-20T{i:02d}:00:00Z", "unknown")
                 for i in range(20)])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == ["BTC/USD"]
    assert uni.unserviceable_core == ("SOL/USD",)
    assert uni.enforced is True


def test_a_symbol_with_only_unknown_bars_cannot_read_warm(tmp_path,
                                                          monkeypatch):
    # MUTATION KILLER for the warm check. Revert warm_report to counting bars
    # alone and this fails: nine bars clears a need of two, so the symbol
    # reads WARM while the engine has already ruled it out. The warm check and
    # the entry gate must never disagree.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path,
                [("BTC/USD", f"2026-07-21T0{i}:00:00Z", "backfill")
                 for i in range(5)] +
                [("SOL/USD", f"2026-07-20T0{i}:00:00Z", "unknown")
                 for i in range(9)])
    monkeypatch.setattr(stack, "warm_need", lambda: 2)
    rep = stack.warm_report(db)
    by = {s["symbol"]: s for s in rep["symbols"]}
    assert by["SOL/USD"]["bars"] >= 2          # it HAS the bars
    assert by["SOL/USD"]["warm"] is False      # and is still not warm
    assert by["SOL/USD"]["state"] == "unserviceable"
    assert by["SOL/USD"]["tradeable"] is False
    assert by["BTC/USD"]["state"] == "warm"
    assert rep["all_warm"] is False


def test_the_declared_core_stays_visible_when_it_is_held_out(tmp_path,
                                                             monkeypatch):
    # A symbol held out of the universe must still be REPORTED. Dropping it
    # from the report would make an unserviceable core symbol invisible, which
    # is how it stays broken for days.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", "2026-07-21T07:00:00Z", "backfill")])
    monkeypatch.setattr(stack, "warm_need", lambda: 1)
    names = [s["symbol"] for s in stack.warm_report(db)["symbols"]]
    assert names == ["BTC/USD", "SOL/USD"]


# --- Core verification: the same check discovery runs ------------------------

def test_core_verification_refuses_a_symbol_the_venue_does_not_serve(
        tmp_path, monkeypatch):
    # The backfill RAN (fetch returns a result) and wrote nothing for MANA:
    # the venue does not serve it, so it is unserviceable and held out.
    _pin(monkeypatch, ["BTC/USD", "MANA/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", "2026-07-21T07:00:00Z", "backfill")])
    rep = universe.verify_core(db, fetch=lambda p: {"BTC/USD": 900,
                                                    "MANA/USD": 0})
    assert rep["verified"] is True
    assert rep["serviceable"] == ["BTC/USD"]
    assert rep["unserviceable"] == ["MANA/USD"]


def test_a_backfill_that_cannot_run_verifies_nothing(tmp_path, monkeypatch):
    # No data credentials: nothing was PROVEN, so nothing is condemned.
    # Refusing every core symbol here would turn a missing key into an empty
    # universe, the opposite of the safe direction. Discovery's rule since
    # 2026-07-20, now the core's rule too.
    _pin(monkeypatch, ["BTC/USD", "MANA/USD"])
    db = _mk_db(tmp_path, [])
    rep = universe.verify_core(db, fetch=lambda p: None)
    assert rep["verified"] is False
    assert rep["unserviceable"] == []
    assert "did not run" in rep["reason"]


def test_verification_backfills_first_and_judges_after(tmp_path, monkeypatch):
    # Order is the whole point: only a real request answers "does the venue
    # serve this". Judging before the fetch would condemn every symbol on a
    # fresh database.
    _pin(monkeypatch, ["NEW/USD"])
    db = _mk_db(tmp_path, [])
    calls = []

    def fetch(path):
        calls.append("fetch")
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source) VALUES('alpaca','NEW/USD','5min',"
            "'2026-07-21T07:00:00Z',1,2,0.5,1.5,10,'backfill')")
        conn.commit()
        conn.close()
        return {"NEW/USD": 1}

    rep = universe.verify_core(db, fetch=fetch)
    assert calls == ["fetch"]
    assert rep["serviceable"] == ["NEW/USD"]


# --- The backfill requests every core symbol ---------------------------------

def test_backfill_command_requests_every_core_symbol(monkeypatch):
    # THE AAPL/MSFT/NVDA DEFECT: the command carried no --symbols at all and
    # fell through to a four-name literal, so four of the eight declared core
    # symbols were never once requested.
    monkeypatch.setattr(universe, "declared_core",
                        lambda *a, **k: ["BTC/USD", "SOL/USD", "AAPL", "NVDA"])
    cmd = stack.backfill_cmd("/tmp/x.db")
    assert "--symbols" in cmd
    assert cmd[cmd.index("--symbols") + 1] == "BTC/USD,SOL/USD,AAPL,NVDA"


def test_backfill_default_symbols_come_from_the_core(monkeypatch):
    monkeypatch.setattr(universe, "declared_core",
                        lambda *a, **k: ["AAPL", "MSFT", "NVDA"])
    assert alpaca_source.core_symbols() == ["AAPL", "MSFT", "NVDA"]


def test_the_backfill_module_holds_no_symbol_literal():
    # The literal is gone, not merely unused: a second copy of a list is a
    # copy that goes stale.
    # The ASSIGNMENT is what must stay gone. The names survive in the comment
    # that records why they were removed, which is the point of the comment.
    src = _read("market_data/alpaca_source.py")
    assert not re.search(r"^_WHITELIST_CRYPTO\s*=", src, re.M)
    assert not re.search(r"^_WHITELIST_EQUITY\s*=", src, re.M)


# --- The universe resolves ONCE ----------------------------------------------

_RUNTIME_PACKAGES = ("account_manager", "adaptive", "api_server", "discovery",
                     "llm_consensus", "market_data", "ml_factor", "ops",
                     "python_bridge", "research_satellite", "rl_advisory",
                     "ui", "whale_signal")

# Reading the core out of config, in any of the shapes a consumer might use.
_CORE_READ = re.compile(r'get\("whitelist"|\["whitelist"\]')
# Reading the periphery: the active watchlist members, as a symbol set.
_PERIPHERY_READ = re.compile(r"FROM watchlist\s+WHERE status")


def _runtime_files():
    for pkg in _RUNTIME_PACKAGES:
        for dirpath, _dirs, files in os.walk(os.path.join(REPO, pkg)):
            if "__pycache__" in dirpath:
                continue
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(dirpath, f)
                    with open(path) as fh:
                        yield os.path.relpath(path, REPO), fh.read()


def test_only_the_resolver_parses_the_declared_core():
    # A new consumer must call market_data.universe.declared_core, not read
    # strategy.whitelist itself. Two copies diverged in exactly this way:
    # api_server.controls.whitelist applied no active_quant overlay, so it
    # reported four symbols while the engine traded eight.
    offenders = [rel for rel, body in _runtime_files()
                 if _CORE_READ.search(body)
                 and rel != os.path.join("market_data", "universe.py")]
    assert offenders == [], (
        "these files parse the whitelist out of config instead of calling "
        f"market_data.universe.declared_core: {offenders}")


def test_no_consumer_builds_the_universe_union_itself():
    # THE GUARD: a new consumer cannot construct a universe without going
    # through the resolver. The signature of the offense is one file doing
    # BOTH halves, core and periphery, which is what ops.watchdog,
    # api_server.operator, and api_server.stack each did their own way.
    # discovery/watchlist.py owns the table and may read it; it never reads
    # the core.
    offenders = []
    for rel, body in _runtime_files():
        if rel == os.path.join("market_data", "universe.py"):
            continue
        core = bool(_CORE_READ.search(body)
                    or re.search(r"stack\.whitelist\(|controls\.whitelist\(",
                                 body))
        if core and _PERIPHERY_READ.search(body):
            offenders.append(rel)
    assert offenders == [], (
        "these files build the core-plus-periphery union themselves instead "
        f"of calling market_data.universe.resolve: {offenders}")


def test_every_python_consumer_reaches_the_resolver():
    # The consumers named in CONTEXT.md, pinned lexically so a future edit
    # cannot quietly reintroduce a local list.
    assert "market_data.universe" in _read("api_server/stack.py")
    assert "market_data.universe" in _read("api_server/controls.py")
    assert "market_data.universe" in _read("ops/watchdog.py")
    assert "from market_data import universe" in _read("api_server/operator.py")
    assert "market_data.universe" in _read("discovery/run.py")


# --- The C++ half cannot drift from the Python half --------------------------

def test_cpp_min_universe_matches_python():
    hpp = _read("core/engine.hpp")
    m = re.search(r"kMinTradeableUniverse\s*=\s*(\d+)", hpp)
    assert m, "Engine::kMinTradeableUniverse is gone"
    assert int(m.group(1)) == universe.MIN_TRADEABLE_UNIVERSE


def test_cpp_builds_its_instruments_from_the_declared_core():
    # THE SECOND HALF OF THE COVERAGE DEFECT: all_instruments_ was a hardcoded
    # four-name vector, so a core symbol beyond those four was never polled,
    # never closed a bar, and could not have warmed even with a full backfill.
    engine = _read("core/engine.cpp")
    ctor = re.search(r"Instrument universe[\s\S]{0,1600}?all_instruments_",
                     engine)
    assert ctor, "the instrument-universe block moved"
    body = ctor.group(0)
    assert "cfg_.strategy.whitelist" in body, (
        "the engine no longer builds its instruments from the declared core: "
        "a configured symbol would be declared and never polled")
    for literal in ('{"alpaca", "BTC/USD", "BTC/USD"',
                    '{"alpaca", "SPY", "SPY"'):
        assert literal not in body, (
            f"the hardcoded instrument literal {literal} is back")


def test_cpp_warm_report_consults_the_predicate():
    # MUTATION KILLER, lexical half: warm_states must carry the predicate's
    # answer, or the startup banner can call an unserviceable symbol WARM.
    engine = _read("core/engine.cpp")
    warm = re.search(r"std::vector<Engine::SymbolWarm> Engine::warm_states"
                     r"[\s\S]*?\n\}", engine)
    assert warm and "symbol_is_tradeable(" in warm.group(0), (
        "warm_states no longer consults symbol_is_tradeable: a symbol with "
        "unprovable bars could read WARM again")
    main = _read("core/main.cpp")
    assert "UNSERVICEABLE" in main, (
        "the startup banner no longer distinguishes unserviceable from cold")


def test_cpp_resolves_the_universe_in_one_place():
    engine = _read("core/engine.cpp")
    rep = re.search(r"Engine::UniverseReport Engine::universe_report"
                    r"[\s\S]*?\n\}", engine)
    assert rep and "symbol_is_tradeable(" in rep.group(0)
    assert "universe_report()" in _read("core/main.cpp"), (
        "the startup block no longer reads the engine's resolved universe")


# --- Degrade visibly ----------------------------------------------------------

def test_an_empty_universe_is_a_loud_condition(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"])
    db = _mk_db(tmp_path, [("SOL/USD", "2026-07-21T07:00:00Z", "unknown")])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == []
    assert uni.degraded is True
    assert "TRADEABLE UNIVERSE EMPTY" in uni.degraded_reason
    assert "SOL/USD" in uni.degraded_reason


def test_a_nearly_empty_universe_is_a_loud_condition(tmp_path, monkeypatch):
    # One symbol is below the floor: at one symbol every feed question becomes
    # all-or-nothing and the watchdog's serving scope stops meaning anything.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD", "AAPL"])
    db = _mk_db(tmp_path, [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed")])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == ["BTC/USD"]
    assert uni.degraded is True
    assert "NEARLY EMPTY" in uni.degraded_reason


def test_a_healthy_universe_is_not_degraded(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD", "ETH/USD"])
    db = _mk_db(tmp_path, [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed"),
                           ("ETH/USD", "2026-07-21T07:00:00Z", "backfill")])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == ["BTC/USD", "ETH/USD"]
    assert uni.degraded is False
    assert uni.degraded_reason == ""


def test_offline_modes_are_exempt(tmp_path, monkeypatch):
    # The invariant is a real-path rule. Offline feed modes trade generated
    # data by design, so nothing is held out and nothing is degraded.
    _pin(monkeypatch, ["BTC/USD", "SOL/USD"], real=False)
    db = _mk_db(tmp_path, [])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == ["BTC/USD", "SOL/USD"]
    assert uni.enforced is False
    assert uni.degraded is False


def test_the_watchdog_reports_the_universe_without_remediating_it(monkeypatch):
    # LOUD, never remediating: a restart cannot make a venue serve a symbol,
    # so this is notified like a kill trip and never acted on.
    notes = []
    from ops import watchdog
    monkeypatch.setattr(watchdog, "notify",
                        lambda msg, cfg=None, title="": notes.append(msg))
    # setitem, not assignment: the notify state is module-level, and leaving
    # it degraded would make the NEXT watchdog test see a spurious recovery
    # notification.
    monkeypatch.setitem(watchdog._universe_notified, "degraded", False)
    monkeypatch.setitem(watchdog._universe_notified, "ts", 0.0)
    sent = watchdog._note_universe(
        {"universe_degraded": True,
         "universe_degraded_reason": "TRADEABLE UNIVERSE EMPTY: nothing",
         "universe_symbols": []}, {})
    assert sent is True
    assert "TRADEABLE UNIVERSE EMPTY" in notes[0]
    assert "restart cannot" in notes[0]


# --- The discovered periphery joins under the same predicate -----------------

def test_the_verified_periphery_joins_the_universe(tmp_path, monkeypatch):
    _pin(monkeypatch, ["BTC/USD"], discovery=True)
    db = _mk_db(tmp_path,
                [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed"),
                 ("LDO/USD", "2026-07-21T07:00:00Z", "backfill")],
                watchlist=[("LDO/USD", "active")])
    uni = universe.resolve(db_path=db)
    assert uni.core == ("BTC/USD",)
    assert uni.periphery == ("LDO/USD",)
    assert uni.symbols == ["BTC/USD", "LDO/USD"]


def test_an_unverified_periphery_member_is_held_out(tmp_path, monkeypatch):
    # The MANA/USD shape on the watchlist: added before serviceability was
    # verified, nothing but fabricated bars. Held out, and named.
    _pin(monkeypatch, ["BTC/USD"], discovery=True)
    db = _mk_db(tmp_path,
                [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed"),
                 ("MANA/USD", "2026-07-21T07:00:00Z", "synthetic")],
                watchlist=[("MANA/USD", "active")])
    uni = universe.resolve(db_path=db)
    assert uni.symbols == ["BTC/USD"]
    assert uni.unserviceable_periphery == ("MANA/USD",)


def test_a_referred_member_never_joins(tmp_path, monkeypatch):
    # referred is a candidate the funnel has not confirmed. The engine never
    # merges it, so the universe never contains it.
    _pin(monkeypatch, ["BTC/USD"], discovery=True)
    db = _mk_db(tmp_path,
                [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed"),
                 ("XX/USD", "2026-07-21T07:00:00Z", "backfill")],
                watchlist=[("XX/USD", "referred")])
    assert universe.resolve(db_path=db).symbols == ["BTC/USD"]


def test_the_periphery_is_ignored_while_discovery_is_off(tmp_path,
                                                         monkeypatch):
    _pin(monkeypatch, ["BTC/USD"], discovery=False)
    db = _mk_db(tmp_path,
                [("BTC/USD", "2026-07-21T07:00:00Z", "real_feed"),
                 ("LDO/USD", "2026-07-21T07:00:00Z", "backfill")],
                watchlist=[("LDO/USD", "active")])
    assert universe.resolve(db_path=db).symbols == ["BTC/USD"]


# --- Nothing here binds -------------------------------------------------------

def test_the_resolver_opens_no_socket_and_binds_nothing():
    src = _read("market_data/universe.py")
    for forbidden in ("socket", "bind(", "urlopen", "0.0.0.0"):
        assert forbidden not in src, (
            f"market_data/universe.py touches {forbidden}: the resolver is a "
            "read-only database and config question")
