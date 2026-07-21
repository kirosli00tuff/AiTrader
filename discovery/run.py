"""Scheduled discovery runner: decide if a pass is due, run it, persist it.

Cadence, per the design:
  * CRYPTO  hourly, around the clock. Crypto never closes.
  * EQUITY  at the US session open and hourly through US regular hours. An
            equity pass outside US hours would rank a market nobody can trade,
            and after-hours prints are thin-market artifacts (the same reason
            the engine refuses equity entries outside RTH, see CONTEXT.md).

Everything here is a no-op while ``discovery.discovery_enabled`` is false, which
is the default. With the flag off this module never fetches, never scores, never
writes, and the engine behaves exactly as the fixed-whitelist system.

Run it from the existing maintenance scheduling, or directly:
    python -m discovery.run --asset-class crypto
    python -m discovery.run --force        # ignore the cadence, still flag-gated
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

from discovery import (evaluate, funnel, settings, store, universe,
                       watchlist, whale_surfacer)

log = logging.getLogger("discovery.run")

# Repo-anchored default DB, never cwd-relative (the adaptive/run.py bug
# class). Callers that pass an explicit path are honored as given.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_REPO_ROOT, "market_ai_lab.db")

# US regular trading hours in UTC minutes-of-day: 13:30-20:00 UTC.
# Mirrors the NY window in config/regional_session.hpp (810-1200).
US_RTH_OPEN_MINUTE = 810
US_RTH_CLOSE_MINUTE = 1200

ASSET_CLASSES = ("crypto", "equity")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def us_market_open(now: datetime) -> bool:
    """True during US regular trading hours (weekday, 13:30-20:00 UTC).

    Holidays are not modelled: a holiday pass costs a few free Finnhub calls and
    finds a flat tape, which Stage A drops for free. That is a cheaper error than
    wrongly skipping a real session.
    """
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    minute = now.hour * 60 + now.minute
    return US_RTH_OPEN_MINUTE <= minute < US_RTH_CLOSE_MINUTE


def due(asset_class: str, last_ts: str | None, now: datetime,
        cfg_path: str | None = None) -> tuple[bool, str]:
    """Is a pass due for this asset class? Pure, so it is directly testable.

    Returns (due, reason). The reason is always populated, so a skipped pass can
    say why rather than being silent.
    """
    if asset_class == "equity" and not us_market_open(now):
        return False, "outside US regular trading hours"

    interval = (settings.crypto_interval_minutes(cfg_path)
                if asset_class == "crypto"
                else settings.equity_interval_minutes(cfg_path))
    last = _parse_iso(last_ts)
    if last is None:
        # No pass on record. At the equity open this is exactly the first pass of
        # the session, which is the one we most want.
        return True, "no previous pass"
    elapsed_min = (now - last).total_seconds() / 60.0
    if elapsed_min < interval:
        return False, f"last pass {elapsed_min:.0f}m ago, interval {interval}m"
    return True, f"last pass {elapsed_min:.0f}m ago"


def _category_for(symbol: str) -> str:
    return "crypto" if universe.is_crypto(symbol) else "equity"


def due_status(asset_class: str, db_path: str = _DEFAULT_DB,
               cfg_path: str | None = None,
               now: datetime | None = None) -> dict:
    """Is a pass due for this asset class right now, and why or why not?

    The engine triggers passes but does NOT decide the cadence: it asks here.
    One authority, so the engine, the maintenance job, and the CLI can never
    drift on when a pass is due, and the US-hours rule for equities is not
    written twice in two languages.

    Cheap: one indexed SQLite read, no Finnhub call and no LLM call, so the
    engine can ask on a short interval without cost.
    """
    now = now or _utcnow()
    if not settings.discovery_enabled(cfg_path):
        return {"enabled": False, "due": False, "asset_class": asset_class,
                "reason": "discovery.discovery_enabled is false"}
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            store.ensure_schema(conn)
            last_ts = store.last_pass_ts(conn, asset_class)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — advisory layer, never fatal
        return {"enabled": True, "due": False, "asset_class": asset_class,
                "reason": f"cannot read pass history ({type(e).__name__})"}
    is_due, reason = due(asset_class, last_ts, now, cfg_path)
    return {"enabled": True, "due": is_due, "asset_class": asset_class,
            "reason": reason, "last_pass_ts": last_ts or ""}


def onboard(symbols: list[str], db_path: str = _DEFAULT_DB) -> dict:
    """Backfill bars for newly surfaced symbols so the engine can warm them.

    Surfacing a symbol only NAMES it. Without bars it has no indicator history,
    so the engine's warm gate refuses it forever and a discovered candidate can
    never become a trade. This pulls the same 1yr-daily + 30d-5min history the
    whitelist gets at startup, through the SAME backfill, so a discovered symbol
    warms through the same path a configured one does and gets no special case.

    The engine seeds its in-memory history from the `bars` table, so writing
    there is the whole handoff: no direct engine call, and the C++ side stays the
    sole writer of the operational tables.

    Failure-isolated like the rest of the pass. Without data credentials the
    backfill is a no-op and the symbol stays cold, which the engine reports as
    cold rather than trading on nothing.
    """
    if not symbols:
        return {"status": "noop", "onboarded": []}
    try:
        from market_data.alpaca_source import backfill
    except Exception as e:  # noqa: BLE001 — optional deps in a minimal env
        return {"status": "unavailable", "reason": type(e).__name__,
                "onboarded": []}
    try:
        res = backfill(db_path, list(symbols))
    except Exception as e:  # noqa: BLE001 — advisory layer, never fatal
        log.warning("discovery: onboarding backfill failed (%s)",
                    type(e).__name__)
        return {"status": "error", "reason": type(e).__name__, "onboarded": []}
    if res.get("status") != "ok":
        return {"status": res.get("status", "error"),
                "reason": res.get("reason", ""), "onboarded": []}
    written = res.get("written", {})
    # A symbol counts as onboarded only if bars actually landed. A zero-bar
    # symbol is reported unonboarded rather than silently called ready.
    got = {s: sum(int(n) for k, n in written.items()
                  if k.rsplit(":", 1)[0] == s)
           for s in symbols}
    return {"status": "ok",
            "onboarded": sorted(s for s, n in got.items() if n > 0),
            "no_bars": sorted(s for s, n in got.items() if n == 0),
            "bars_written": got}


def run_once(asset_class: str, *, db_path: str = _DEFAULT_DB,
             cfg_path: str | None = None, client=None, gate=None,
             evaluator=None, now: datetime | None = None,
             force: bool = False) -> dict:
    """Run one discovery pass for one asset class, if enabled and due.

    Returns a status dict. Never raises: discovery is an advisory layer and must
    never take the loop down. Providers are injectable so the tests drive the
    whole path with mocks and no network.
    """
    now = now or _utcnow()

    if not settings.discovery_enabled(cfg_path):
        return {"status": "disabled",
                "reason": "discovery.discovery_enabled is false"}

    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        store.ensure_schema(conn)
        watchlist.ensure_schema(conn)

        last_ts = store.last_pass_ts(conn, asset_class)
        if not force:
            is_due, reason = due(asset_class, last_ts, now, cfg_path)
            if not is_due:
                return {"status": "not_due", "reason": reason,
                        "asset_class": asset_class}

        # Stage A input: the active universe, and free Finnhub data over it.
        symbols = universe.universe_for(asset_class, db_path, cfg_path, now)
        if not symbols:
            return {"status": "empty_universe", "asset_class": asset_class,
                    "reason": f"no {asset_class} symbols configured"}

        if client is None:
            from discovery.finnhub_source import FinnhubClient, is_live
            if not is_live():
                return {"status": "unavailable", "asset_class": asset_class,
                        "reason": "no FINNHUB_API_KEY resolved, discovery needs "
                                  "the free pre-screen data"}
            client = FinnhubClient()

        # Whale surfacing: free, keyless, bounded, and cached hard. Absent whale
        # data simply scores 0, which is the pre-whale ranking. The SAME whale
        # data still evaluates survivors at its bounded advisory weight in Stage C.
        whale = None
        if settings.stage_a_whale_weight(cfg_path) > 0:
            whale = whale_surfacer.WhaleSurfacer()
        snapshots = funnel.build_snapshots(symbols, client, whale=whale)
        if not snapshots:
            return {"status": "no_data", "asset_class": asset_class,
                    "reason": "no quotes resolved for the universe"}

        if gate is None:
            # Discovery's OWN Stage-B gate, not the council's. Same model and
            # same key, different prompt: the council's gate renders an order
            # book and a news catalyst that free Finnhub data does not have, and
            # defaults both to 0.0, so it read every discovery candidate as flat
            # and rejected 12 of 12 on every pass. See discovery/gate.py.
            from discovery.gate import DiscoveryGate
            gate = DiscoveryGate()

        prices = {s["symbol"]: s.get("price", 0.0) for s in snapshots}
        by_symbol = {str(s.get("symbol", "")): s for s in snapshots}
        if evaluator is None:
            evaluator = evaluate.four_level_evaluator(
                price_for=lambda s: prices.get(s, 0.0),
                # The council judges MOVEMENT. Without the snapshot it sees a
                # price and zeros, and returns avoid at conviction 0.0 for every
                # survivor, every pass, at a full council call each.
                snapshot_for=lambda s: by_symbol.get(s, {}),
                category_for=_category_for, cfg_path=cfg_path,
                # db turns on evidence enrichment (real bars, regime, position)
                # and per-provider persistence for replay (2026-07-20).
                db_path=db_path)

        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = funnel.run_pass(
            asset_class, snapshots=snapshots, gate=gate, evaluator=evaluator,
            calls_used_today=store.council_calls_today(
                conn, now.strftime("%Y-%m-%d")),
            cfg_path=cfg_path, ts=ts)

        payload = result.to_dict()
        pass_id = store.record_pass(conn, payload)
        whale_surfaced = set(payload.get("whale_surfaced") or [])
        whale_reasons = {f.symbol: f.whale_reason for f in result.finalists
                         if f.whale_surfaced}

        # Stage-C survivors join the watchlist. An "avoid" verdict is NOT
        # added: the watchlist is a CANDIDATE list, not an archive of
        # rejections. The pass record still shows the funnel looked and
        # declined.
        #
        # SERVICEABILITY IS VERIFIED FIRST (2026-07-20). Discovery ranks its
        # universe through Finnhub while onboarding backfills through Alpaca,
        # and the venues do not carry the same pairs: MANA/USD and RUNE/USD
        # surfaced, backfilled ZERO bars, and sat active with nothing but
        # fabricated data until two unserviceable symbols stopped the stack.
        # So the backfill now runs BEFORE the add, and a candidate joins the
        # watchlist only if the tradeable predicate confirms real bar history
        # afterward. A refused candidate is journalled (applied=0) and logged.
        # When the backfill cannot run at all (no data credentials, the
        # offline environment), nothing can be verified and the add proceeds
        # as before: offline modes are exempt from the real-path invariant,
        # and on the real path every consumer of the predicate still refuses
        # the symbol.
        candidates = [c for c in payload.get("candidates", [])
                      if c.get("verdict") != "avoid"]
        conn.commit()  # release the write lock before backfill's own writes
        onboarded = onboard([str(c.get("symbol", "")) for c in candidates],
                            db_path)
        verified = onboarded.get("status") == "ok"
        from market_data.tradeable import symbol_is_tradeable
        added, refused = [], []
        for c in candidates:
            # Say WHY it is on the list, including when whale surfaced it, so
            # the operator can tell a whale-found name from a technical one.
            sym = str(c.get("symbol", ""))
            reason = (f"discovery {c.get('verdict')} conviction "
                      f"{c.get('conviction')}")
            if sym in whale_surfaced:
                reason += f" · surfaced by {whale_reasons.get(sym, 'whale activity')}"
            if verified and not symbol_is_tradeable(conn, sym):
                watchlist.journal_onboarding_refusal(
                    conn, sym, ts=ts,
                    reason="onboarding refused: backfill returned no bars, "
                           "the venue does not serve this symbol")
                log.warning(
                    "discovery: refused to onboard %s: backfill returned "
                    "nothing (venue unserviceable)", sym)
                refused.append(sym)
                continue
            r = watchlist.add_from_discovery(
                conn, sym,
                reason=reason,
                sleeve_target=str(c.get("sleeve_target", "quant_core")),
                score=float(c.get("conviction") or 0.0),
                asset_class=asset_class, ts=ts)
            if r["applied"]:
                added.append(sym)

        pruned = watchlist.prune_stale(
            conn, settings.watchlist_stale_hours(cfg_path), now)
        capped = watchlist.enforce_max_size(
            conn, settings.watchlist_max_size(cfg_path), ts)
        conn.commit()

        return {
            "status": payload.get("status", "ok"),
            "asset_class": asset_class,
            "pass_id": pass_id,
            "onboarded": onboarded.get("onboarded", []),
            "onboard_status": onboarded.get("status", "noop"),
            "onboard_refused": refused,
            "universe_count": payload["universe_count"],
            "finalists": payload["finalists_count"],
            "survivors": payload["survivors_count"],
            "evaluated": payload["evaluated_count"],
            "council_calls": payload["council_calls"],
            "est_cost_usd": payload["est_cost_usd"],
            "whale_surfaced": payload.get("whale_surfaced", []),
            "watchlist_added": added,
            "watchlist_pruned": pruned["pruned"],
            "watchlist_capped": capped["dropped"],
        }
    except Exception as e:  # noqa: BLE001 — advisory layer, never fatal
        log.warning("discovery: pass failed for %s (%s)", asset_class,
                    type(e).__name__)
        return {"status": "error", "asset_class": asset_class,
                "reason": type(e).__name__}
    finally:
        conn.close()


def run_due(db_path: str = _DEFAULT_DB, cfg_path: str | None = None,
            now: datetime | None = None, force: bool = False) -> dict:
    """Run every asset class whose cadence is due. The maintenance entry point."""
    now = now or _utcnow()
    if not settings.discovery_enabled(cfg_path):
        return {"status": "disabled",
                "reason": "discovery.discovery_enabled is false"}
    return {"status": "ok",
            "passes": {ac: run_once(ac, db_path=db_path, cfg_path=cfg_path,
                                    now=now, force=force)
                       for ac in ASSET_CLASSES}}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Run the discovery funnel for a due asset class.")
    ap.add_argument("--db", default=_DEFAULT_DB)
    ap.add_argument("--config", default=None)
    ap.add_argument("--asset-class", choices=ASSET_CLASSES, default=None,
                    help="default: every class that is due")
    ap.add_argument("--force", action="store_true",
                    help="ignore the cadence (still refuses when the flag is off)")
    args = ap.parse_args()

    if args.asset_class:
        out = run_once(args.asset_class, db_path=args.db, cfg_path=args.config,
                       force=args.force)
    else:
        out = run_due(db_path=args.db, cfg_path=args.config, force=args.force)
    print(json.dumps(out, indent=2))
