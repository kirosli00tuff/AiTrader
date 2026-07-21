"""THE tradeable universe, resolved once (2026-07-21).

The universe is TWO PARTS UNDER ONE STANDARD:

  * the CORE, a small config-declared set of stable liquid instruments that
    should always be present (``strategy.whitelist``, overlaid by the active
    profile exactly as ``config.cpp`` overlays it), and
  * the PERIPHERY, whatever the discovery funnel has verified and onboarded
    (the active watchlist members, when discovery is on).

Both are held to the SAME rule: a symbol is in the tradeable universe only if
``market_data.tradeable.symbol_is_tradeable`` returns true. Nothing enters on
unknown or synthetic bars. Discovery has verified serviceability before
onboarding since 2026-07-20; the core was ASSUMED, which is the defect this
module closes. SOL/USD sat in the active_quant core reading WARM on 8,519 bars
that all carried source ``unknown``, so the warm check passed a symbol the
predicate refuses, while AAPL, MSFT, and NVDA sat at zero bars because the
warm-start backfill asked for a hardcoded four-symbol subset.

WHY ONE MODULE. Before this, four places built a symbol list their own way:
``api_server.stack.whitelist`` (config only), ``api_server.controls.whitelist``
(config only, a second copy), ``ops.watchdog.tradeable_symbols`` (config plus
watchlist), and ``market_data.alpaca_source`` (a hardcoded literal). Two lists
with two standards is how a symbol reads WARM in one consumer and unavailable
in another. Every Python consumer now calls ``resolve`` (or the declared-set
helpers underneath it) and nothing re-derives the union. The C++ enforcement
point is ``Engine::tradeable_universe`` over the same predicate against the
same table; a drift-guard test pins the two definitions equal, and a lexical
guard test refuses a new consumer that builds a universe of its own.

OFFLINE IS EXEMPT, exactly as the predicate is. The invariant is a real-path
rule (``feed_mode: alpaca_paper``). Under the synthetic and replay feed modes
every declared symbol is in the universe, because those modes trade generated
data by design.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from market_data.tradeable import symbol_is_tradeable

# The feed mode that IS the real path. Mirrors Engine::symbol_is_tradeable.
REAL_PATH_FEED_MODE = "alpaca_paper"

# Below this many verified symbols the universe is a LOUD condition, not a
# quiet one. Two is the smallest universe where "some symbols are serving
# while others are stale" is a meaningful statement, which is exactly what the
# watchdog's any_tradeable_serving scope keys off: at one symbol every feed
# question becomes all-or-nothing, and at zero the stack is running with
# nothing to trade while every per-symbol alarm stays correctly silent. The
# 2026-07-20 failure was a universe collapsing quietly, so the floor exists to
# make the collapse audible rather than to change any trading behavior.
MIN_TRADEABLE_UNIVERSE = 2

_DEFAULT_CORE = "BTC/USD,ETH/USD,SPY,QQQ"


# --- the declared sets -------------------------------------------------------

def declared_core(cfg_path: str | None = None) -> list[str]:
    """The config-declared core, profile-resolved. DECLARED, not verified.

    ``config.cpp`` load_config overlays the ``active_quant`` block over
    ``strategy`` when ``strategy.profile`` selects it, so reading
    ``strategy.whitelist`` alone reports the swing set while an active_quant
    engine trades the wider one. The overlay is mirrored here so every Python
    consumer sees the symbols the engine actually polls.
    """
    from llm_consensus.config_access import config_block
    strat = config_block("strategy", cfg_path)
    raw = str(strat.get("whitelist", _DEFAULT_CORE))
    if str(strat.get("profile", "swing")) == "active_quant":
        aq = config_block("active_quant", cfg_path)
        raw = str(aq.get("whitelist", raw) or raw)
    out: list[str] = []
    for s in raw.split(","):
        s = s.strip()
        if s and s not in out:
            out.append(s)
    return out


def discovery_enabled(cfg_path: str | None = None) -> bool:
    """Whether discovery is on, resolved the way the engine resolves it
    (controls.json over config). Unprovable reads as off."""
    try:
        from discovery import settings as discovery_settings
        return bool(discovery_settings.discovery_enabled(cfg_path))
    except Exception:  # noqa: BLE001 - an advisory read is never fatal
        return False


def real_feed_mode(cfg_path: str | None = None) -> bool:
    """True when the loop runs the real path, read the same way the engine
    reads it: controls.json wins, config seeds. Unreadable means not-real, so
    an offline run is never held to the real-path bar."""
    try:
        from llm_consensus import control_file
        from llm_consensus.config_access import config_block
        feed = control_file.control_state().get("feed_mode")
        if not feed:
            feed = config_block("simulation", cfg_path).get("feed_mode", "")
        return str(feed) == REAL_PATH_FEED_MODE
    except Exception:  # noqa: BLE001
        return False


def declared_periphery(conn: sqlite3.Connection,
                       cfg_path: str | None = None,
                       discovery_on: bool | None = None) -> list[str]:
    """The discovered periphery: active watchlist members, when discovery is on.

    ``active`` is the only status the engine merges (a ``referred`` member is a
    candidate the funnel has not confirmed). A missing or unreadable watchlist
    table degrades to no members: the periphery is advisory and must never
    block a consumer or create schema.

    ``discovery_on`` overrides the flag read. Two callers need it: the
    watchdog resolves the flag itself (that read is its test seam), and the
    diagnostics view passes True on purpose, so a leftover active member stays
    visible to be pruned even while the engine is not merging it.
    """
    if discovery_on is None:
        discovery_on = discovery_enabled(cfg_path)
    if not discovery_on:
        return []
    try:
        from discovery.watchlist import STATUS_ACTIVE
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status=? ORDER BY symbol",
            (STATUS_ACTIVE,)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for r in rows:
        if r and r[0] and str(r[0]) not in out:
            out.append(str(r[0]))
    return out


# --- the resolved universe ---------------------------------------------------

@dataclass(frozen=True)
class Universe:
    """One resolution of the tradeable universe. Verified core plus verified
    periphery, under one predicate."""

    core: tuple[str, ...] = ()                # declared core that verified
    unserviceable_core: tuple[str, ...] = ()  # declared core that did not
    periphery: tuple[str, ...] = ()           # discovered members that verified
    unserviceable_periphery: tuple[str, ...] = ()
    declared_core: tuple[str, ...] = ()
    enforced: bool = False   # was the predicate applied (real path) at all
    reason: str = ""

    @property
    def symbols(self) -> list[str]:
        """The tradeable universe: verified core union verified periphery."""
        return list(self.core) + [s for s in self.periphery
                                  if s not in self.core]

    @property
    def unserviceable(self) -> list[str]:
        return list(self.unserviceable_core) + list(self.unserviceable_periphery)

    @property
    def degraded(self) -> bool:
        """True when the universe is empty or nearly empty. A LOUD condition:
        the stack must never run with a silently empty universe."""
        return self.enforced and len(self.symbols) < MIN_TRADEABLE_UNIVERSE

    @property
    def degraded_reason(self) -> str:
        if not self.degraded:
            return ""
        n = len(self.symbols)
        head = ("TRADEABLE UNIVERSE EMPTY" if n == 0
                else f"TRADEABLE UNIVERSE NEARLY EMPTY ({n} symbol)")
        detail = (f"{len(self.declared_core)} core symbol(s) declared, "
                  f"{len(self.core)} verified")
        if self.unserviceable:
            detail += ", unserviceable: " + ", ".join(self.unserviceable)
        return f"{head}: {detail}. The engine has nothing it may trade."

    def to_dict(self) -> dict:
        return {"symbols": self.symbols,
                "core": list(self.core),
                "periphery": list(self.periphery),
                "declared_core": list(self.declared_core),
                "unserviceable_core": list(self.unserviceable_core),
                "unserviceable_periphery": list(self.unserviceable_periphery),
                "unserviceable": self.unserviceable,
                "enforced": self.enforced,
                "degraded": self.degraded,
                "degraded_reason": self.degraded_reason,
                "reason": self.reason}


def declared_symbols(conn: sqlite3.Connection,
                     cfg_path: str | None = None,
                     discovery_on: bool | None = None) -> list[str]:
    """Every symbol the engine POLLS: declared core union declared periphery,
    before the predicate is applied.

    Distinct from ``resolve().symbols``, which is what the engine may TRADE.
    The watchdog needs this one: a symbol is polled so it can prove itself,
    and a declared symbol that fails the predicate must still be named as
    ``symbol_unavailable`` rather than disappearing from the report.
    """
    core = declared_core(cfg_path)
    return core + [s for s in declared_periphery(conn, cfg_path, discovery_on)
                   if s not in core]


def _connect_ro(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)


def resolve(conn: sqlite3.Connection | None = None, *,
            db_path: str | None = None,
            cfg_path: str | None = None,
            discovery_on: bool | None = None) -> Universe:
    """THE resolution point. Verified core union verified periphery.

    Pass a live connection, or a db path to open read-only. On the real path
    every candidate is put to ``symbol_is_tradeable`` and a symbol that fails
    is held OUT of the universe and named in ``unserviceable_*``. Offline the
    predicate does not apply and every declared symbol is in.
    """
    core_declared = declared_core(cfg_path)
    enforced = real_feed_mode(cfg_path)

    own = False
    if conn is None:
        if not db_path:
            return Universe(core=tuple(core_declared),
                            declared_core=tuple(core_declared),
                            enforced=False,
                            reason="no database given, declared core only")
        try:
            conn = _connect_ro(db_path)
            own = True
        except Exception:  # noqa: BLE001
            return Universe(core=tuple(core_declared),
                            declared_core=tuple(core_declared),
                            enforced=False,
                            reason="database unreadable, declared core only")
    try:
        periphery_declared = declared_periphery(conn, cfg_path, discovery_on)
        if not enforced:
            return Universe(
                core=tuple(core_declared),
                periphery=tuple(s for s in periphery_declared
                                if s not in core_declared),
                declared_core=tuple(core_declared),
                enforced=False,
                reason="offline feed mode, the real-path invariant does not apply")
        ok_core = [s for s in core_declared if symbol_is_tradeable(conn, s)]
        bad_core = [s for s in core_declared if s not in ok_core]
        ok_per, bad_per = [], []
        for s in periphery_declared:
            if s in core_declared:
                continue
            (ok_per if symbol_is_tradeable(conn, s) else bad_per).append(s)
        return Universe(core=tuple(ok_core),
                        unserviceable_core=tuple(bad_core),
                        periphery=tuple(ok_per),
                        unserviceable_periphery=tuple(bad_per),
                        declared_core=tuple(core_declared),
                        enforced=True,
                        reason="real path, tradeable predicate enforced")
    finally:
        if own:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# --- serviceability verification (the check discovery already runs) ----------

@dataclass(frozen=True)
class Serviceability:
    """The outcome of ATTEMPTING a backfill and then asking the predicate.

    ``verified`` false means the backfill could not run at all (no data
    credentials, the offline test environment). Nothing was proven, so no
    caller may refuse a symbol on this result. That is discovery's rule since
    2026-07-20 and the core is now held to the same one.
    """

    verified: bool = False
    serviceable: tuple[str, ...] = ()
    unserviceable: tuple[str, ...] = ()
    bars_written: dict = field(default_factory=dict)
    status: str = "noop"
    reason: str = ""


def judge_serviceable(conn: sqlite3.Connection, symbols: list[str],
                      bars_written: dict | None = None) -> Serviceability:
    """THE JUDGMENT half: after a backfill attempt, ask the predicate.

    Separated from the fetch so both callers run the identical judgment.
    Discovery fetches in-process and judges here; startup fetches through the
    bounded backfill subprocess and judges here. The bar a symbol has to clear
    is the same function either way.
    """
    ok, bad = [], []
    for s in symbols:
        (ok if symbol_is_tradeable(conn, s) else bad).append(s)
    return Serviceability(verified=True, serviceable=tuple(ok),
                          unserviceable=tuple(bad),
                          bars_written=dict(bars_written or {}), status="ok")


def verify_serviceable(conn: sqlite3.Connection, symbols: list[str],
                       db_path: str) -> Serviceability:
    """Attempt the venue backfill for ``symbols``, then ask THE predicate.

    This is the one serviceability check in the system. Discovery calls it
    before onboarding a Stage-C survivor, and startup runs the same check
    against every core symbol, so a configured symbol is held to exactly the
    bar a discovered one is held to. It backfills FIRST and judges AFTER,
    because the question is whether the execution venue serves the symbol, and
    only a real request answers that.
    """
    if not symbols:
        return Serviceability(status="noop", reason="no symbols")
    try:
        from market_data.alpaca_source import backfill
    except Exception as e:  # noqa: BLE001 - optional deps in a minimal env
        return Serviceability(status="unavailable", reason=type(e).__name__)
    try:
        res = backfill(db_path, list(symbols))
    except Exception as e:  # noqa: BLE001 - never fatal
        return Serviceability(status="error", reason=type(e).__name__)
    if res.get("status") != "ok":
        return Serviceability(status=str(res.get("status", "error")),
                              reason=str(res.get("reason", "")))
    written = res.get("written", {}) or {}
    per_symbol = {s: sum(int(n) for k, n in written.items()
                         if k.rsplit(":", 1)[0] == s)
                  for s in symbols}
    return judge_serviceable(conn, symbols, per_symbol)


def verify_core(db_path: str, cfg_path: str | None = None,
                fetch=None) -> dict:
    """Verify every CORE symbol at startup instead of assuming it.

    Runs the same serviceability check discovery runs: attempt the backfill,
    then check the predicate. A core symbol that verifies is warmed and
    tradeable. One that fails is reported unserviceable and held out of the
    universe, exactly as discovery refuses an unserviceable candidate.

    ``fetch`` is the backfill attempt, injected so the start sequence can use
    its existing bounded subprocess while the JUDGMENT stays the one shared
    function. It takes the db path and returns a truthy value when the fetch
    ran at all; ``None`` means fetch in-process exactly as discovery does. A
    fetch that could not run (no data credentials, the offline test
    environment) verifies NOTHING, and the report says so rather than
    condemning every symbol: that is discovery's rule since 2026-07-20.

    Returns a report dict. It never raises and never edits config. Holding a
    symbol out of the universe is the runtime consequence, and it is the
    resolved universe that carries it.
    """
    core = declared_core(cfg_path)
    report = {"core": core, "verified": False, "serviceable": [],
              "unserviceable": [], "bars_written": {}, "status": "noop",
              "reason": "", "enforced": real_feed_mode(cfg_path)}
    if not core:
        report["reason"] = "no core symbols declared"
        return report
    fetched = None
    if fetch is not None:
        try:
            fetched = fetch(db_path)
        except Exception as e:  # noqa: BLE001 - a start must not die here
            report["status"] = "error"
            report["reason"] = f"backfill failed ({type(e).__name__})"
            return report
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
    except Exception as e:  # noqa: BLE001
        report["status"] = "error"
        report["reason"] = type(e).__name__
        return report
    try:
        if fetch is None:
            s = verify_serviceable(conn, core, db_path)
        elif not fetched:
            # The fetch could not run, so nothing was proven. Refusing every
            # core symbol here would turn a missing credential into an empty
            # universe, which is the opposite of the safe direction.
            s = Serviceability(status="unavailable",
                               reason="backfill did not run, nothing verified")
        else:
            s = judge_serviceable(conn, core,
                                  fetched if isinstance(fetched, dict) else {})
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    report.update({"verified": s.verified, "serviceable": list(s.serviceable),
                   "unserviceable": list(s.unserviceable),
                   "bars_written": s.bars_written, "status": s.status,
                   "reason": s.reason})
    return report
