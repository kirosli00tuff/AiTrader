"""The curated universe: the OUTER EDGE of the discovery funnel.

Only liquid names belong here. The universe is not a watchlist and not a
portfolio, it is the widest set the funnel is ever allowed to look at. Stage A
ranks all of it for free, so a wide universe costs no LLM tokens, but an
ILLIQUID name that survives to Stage C wastes a full council call on something
the strategies cannot trade well. Both native strategy families (RSI-2 mean
reversion and time-series momentum) fail on thin books, and transaction costs
eat the edge. So the rule is simple: if it is not liquid, it does not go in the
config list.

Two halves, handled differently because they behave differently:
  * EQUITIES are a STABLE curated list. Large-cap US names and liquid ETFs do
    not churn week to week, so the list is edited by hand in config and stays put.
  * CRYPTO composition SHIFTS. Today's top-50 by volume is not next quarter's, so
    a daily refresh selects the active set by liquidity and volume from a broader
    configured list. That broader list is still curated: the refresh ranks WITHIN
    it, it never discovers a new coin on its own.

Editing: both lists live in the ``discovery:`` block of config/default_config.yaml
as comma-separated scalars (the C++ minimal YAML parser has no sequence support,
matching strategy.whitelist). Add or remove a symbol there, nothing else.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from discovery import settings


def is_crypto(symbol: str) -> bool:
    """Crypto symbols carry a quote pair. Mirrors market_data/alpaca_source."""
    s = symbol.upper()
    return "/" in s or s.endswith("-USD") or s.endswith("-USDT")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dollar_volume_by_symbol(db_path: str, symbols: list[str],
                            lookback_hours: int = 24,
                            now: datetime | None = None) -> dict[str, float]:
    """Recent dollar volume (sum of close * volume) per symbol from ``bars``.

    Read-only over the operational DB. A symbol with no stored bars is absent
    from the result, which the caller treats as "no liquidity evidence" rather
    than "zero liquidity". Never raises: an unreadable DB returns {}.
    """
    if not symbols:
        return {}
    now = now or _utcnow()
    cutoff = (now - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, float] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return {}
    try:
        placeholders = ",".join("?" for _ in symbols)
        # FABRICATED VOLUME IS EXCLUDED (2026-07-23), the way the decision
        # path excludes it: only venue-reported provenance counts (backfill /
        # real_feed), and rows quarantined by the fabricated-volume mark are
        # out. The quarantine also zeroed those volumes, so the arithmetic
        # excludes them even on a DB where these columns predate the marks;
        # the predicates make the exclusion structural rather than a property
        # of the data. Columns are probed so an old DB degrades to the
        # widest query instead of erroring into "no evidence".
        cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)")}
        where_extra = ""
        if "source" in cols:
            where_extra += (
                " AND COALESCE(source,'unknown') IN ('backfill','real_feed')")
        if "volume_source" in cols:
            where_extra += (
                " AND COALESCE(volume_source,'') != 'fabricated_zeroed'")
        rows = conn.execute(
            f"SELECT symbol, SUM(close * volume) FROM bars "
            f"WHERE symbol IN ({placeholders}) AND timestamp >= ?"
            f"{where_extra} GROUP BY symbol",
            (*symbols, cutoff)).fetchall()
        for sym, dv in rows:
            if dv is None:
                continue
            try:
                val = float(dv)
            except (TypeError, ValueError):
                continue
            if val > 0:
                out[str(sym)] = val
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return out


def refresh_active_crypto(db_path: str, cfg_path: str | None = None,
                          now: datetime | None = None) -> dict:
    """Select the active crypto set by liquidity and volume. Daily refresh.

    Ranking is deterministic and offline-safe:
      1. Symbols with recent dollar-volume evidence rank first, highest first.
      2. Symbols with no stored bars keep their curated config order behind them.
         Absent evidence is NOT treated as zero liquidity: a symbol the paper
         venue has never fetched bars for has no evidence either way, and
         ranking it last on that basis would be a data artifact, not a fact.
    Returns {"active", "ranked_by", "universe_size", "with_volume",
             "dollar_volume"}.
    """
    universe = settings.crypto_universe(cfg_path)
    limit = max(0, settings.crypto_active_max(cfg_path))
    if not universe:
        return {"active": [], "ranked_by": "config_order", "universe_size": 0,
                "with_volume": 0, "dollar_volume": {}}

    dv = dollar_volume_by_symbol(db_path, universe, now=now)
    with_volume = [s for s in universe if s in dv]
    without = [s for s in universe if s not in dv]
    with_volume.sort(key=lambda s: dv[s], reverse=True)

    active = (with_volume + without)[:limit]
    return {
        "active": active,
        "ranked_by": "volume" if with_volume else "config_order",
        "universe_size": len(universe),
        "with_volume": len(with_volume),
        "dollar_volume": {s: round(dv[s], 2) for s in with_volume[:limit]},
    }


def active_equities(cfg_path: str | None = None) -> list[str]:
    """The stable curated equity list, exactly as configured. No refresh: large
    caps and liquid ETFs do not churn, so churn here would be noise."""
    return settings.equity_universe(cfg_path)


def full_universe(db_path: str, cfg_path: str | None = None,
                  now: datetime | None = None) -> dict:
    """Both halves of the active universe, for a discovery pass or the startup
    block. Crypto is refreshed by liquidity, equities are the curated list."""
    crypto = refresh_active_crypto(db_path, cfg_path, now)
    equities = active_equities(cfg_path)
    return {
        "crypto": crypto["active"],
        "equity": equities,
        "crypto_ranked_by": crypto["ranked_by"],
        "crypto_universe_size": crypto["universe_size"],
        "equity_universe_size": len(equities),
    }


def universe_for(asset_class: str, db_path: str, cfg_path: str | None = None,
                 now: datetime | None = None) -> list[str]:
    """Active symbols for one asset class ("crypto" | "equity")."""
    if asset_class == "crypto":
        return refresh_active_crypto(db_path, cfg_path, now)["active"]
    if asset_class == "equity":
        return active_equities(cfg_path)
    return []
