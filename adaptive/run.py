"""The adaptive layer's runner: one poll, start to finish.

The whole chain, cheapest stage first, each one narrowing what reaches the next:

  poll      free HTTP    every event about held names, watchlist names, market
  filter    free         adaptive/materiality.py drops the vast majority
  interpret PAID         at most max_interpretations_per_poll, within the budget
  route     free         adaptive/actions.py decides what it may cause
  apply     free         adaptive/shaping.py carries out exactly that

FLAGS-OFF MEANS OFF. ``run_once`` returns before constructing a client when
``adaptive_news_feed_enabled`` is false. Not "returns early after setting up" but
before: with the flag off there is no client, no key resolution, no socket, no
row written, and no poll recorded. tests/test_adaptive_run.py asserts this
against a client that raises on ANY attribute access, so "zero adaptive API
calls" is proven rather than claimed.

The feed flag is the MASTER. With the feed off, the other two flags are
unreachable whatever they are set to: shaping and defensive actions are both
downstream of an event, and with no poll there are no events. That ordering is
deliberate. An operator who wants everything off has to be sure of one flag, not
three.
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from discovery.finnhub_source import FinnhubClient, resolve_key

from . import settings, store
from .actions import route
from .interpret import interpreter_for
from .materiality import assess
from .news_feed import NewsFeed, poll_targets
from .shaping import apply_route

log = logging.getLogger("adaptive.run")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def due(conn: sqlite3.Connection, *, interval_seconds: int,
        now: datetime | None = None) -> bool:
    """Whether enough time has passed since the last poll."""
    now = now or _utcnow()
    last = store.last_poll(conn)
    if not last or not last.get("ts"):
        return True
    try:
        when = datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return now - when >= timedelta(seconds=max(0, interval_seconds))


def run_once(conn: sqlite3.Connection, *, client=None, interpreter=None,
             now: datetime | None = None, cfg_path: str | None = None) -> dict:
    """One complete poll. Returns the stats it recorded.

    Never raises on a feed or model failure: this layer is advisory and must not
    be able to take anything else down. A failure means fewer events this minute.
    """
    now = now or _utcnow()
    ts = _iso(now)

    # THE FIRST THING, before any construction. Everything below this line costs
    # something (a socket, a key read, a row), so nothing below it may run while
    # the layer is off.
    if not settings.news_feed_enabled(cfg_path):
        return {"status": "disabled", "reason": "adaptive_news_feed_enabled off",
                "events_seen": 0, "llm_calls": 0}

    budget = settings.adaptive_daily_llm_budget(cfg_path)
    used = store.llm_calls_today(conn, ts)
    stats: dict = {"symbols_polled": 0, "events_seen": 0, "events_new": 0,
                   "events_material": 0, "events_escalated": 0, "llm_calls": 0,
                   "actions_queued": 0, "referrals": 0, "est_cost_usd": 0.0,
                   "budget_remaining": max(0, budget - used), "status": "ok",
                   "reason": ""}

    if client is None:
        if not resolve_key():
            stats.update(status="skipped", reason="no_finnhub_key")
            store.record_poll(conn, stats, ts)
            conn.commit()
            return stats
        client = FinnhubClient()

    targets = poll_targets(
        conn, max_symbols=settings.max_symbols_per_poll(cfg_path))
    stats["symbols_polled"] = len(targets)

    feed = NewsFeed(client,
                    lookback_minutes=settings.news_lookback_minutes(cfg_path),
                    general=settings.general_news_enabled(cfg_path))
    try:
        events = feed.poll(targets, now=now)
    except Exception as e:  # noqa: BLE001 - an advisory feed never raises upward
        log.warning("adaptive poll failed: %s", e)
        stats.update(status="error", reason=f"feed error: {e}"[:200])
        store.record_poll(conn, stats, ts)
        conn.commit()
        return stats
    stats["events_seen"] = len(events)

    keywords = settings.materiality_keywords(cfg_path)
    min_sentiment = settings.materiality_min_sentiment(cfg_path)

    # Free filter over everything, then escalate only the material few.
    scored: list[tuple[dict, int]] = []
    for ev in events:
        verdict = assess(ev, keywords=keywords, min_sentiment=min_sentiment)
        ev["material"] = verdict.material
        ev["material_reason"] = verdict.reason
        event_id = store.record_event(conn, ev)
        if event_id is None:
            continue  # already seen: never re-read, never re-charged
        stats["events_new"] += 1
        if verdict.material:
            stats["events_material"] += 1
            scored.append((ev, event_id))

    # Held names first, so a binding per-poll ceiling spends its calls on
    # positions we own rather than on candidates we merely watch.
    scored.sort(key=lambda p: (not p[0].get("held"), p[0].get("symbol") or ""))

    per_poll = settings.max_interpretations_per_poll(cfg_path)
    min_severity = settings.action_min_severity(cfg_path)
    min_relevance = settings.interpretation_min_relevance(cfg_path)
    defensive_on = settings.react_defensive_enabled(cfg_path)
    shaping_on = settings.watchlist_shaping_enabled(cfg_path)
    cost_per = settings.adaptive_est_cost_per_call_usd(cfg_path)

    if interpreter is None:
        interpreter = interpreter_for(settings.interpretation_model(cfg_path))

    for ev, event_id in scored:
        if stats["llm_calls"] >= per_poll:
            stats["reason"] = "per_poll_cap_reached"
            break
        if used + stats["llm_calls"] >= budget:
            # The hard ceiling. Material events past this point are STORED and
            # left uninterpreted: the day's budget is spent, so the layer goes
            # quiet rather than over.
            stats.update(status="budget_exhausted",
                         reason="adaptive daily budget spent")
            break

        interp = interpreter.interpret(ev)
        stats["llm_calls"] += 1
        stats["events_escalated"] += 1
        store.mark_escalated(conn, event_id)

        # Relevance is a MODEL output, so it gates here rather than in the free
        # filter. A read about a name the model itself says the item is barely
        # about must not move anything.
        if interp.relevance < min_relevance:
            store.record_interpretation(
                conn, event_id, interp.to_dict(), model=interp.model,
                cost=cost_per, outcome="dropped",
                outcome_reason="below_min_relevance", ts=ts)
            continue

        result = route(symbol=ev.get("symbol", ""), action=interp.action,
                       severity=interp.severity, reason=interp.rationale,
                       min_severity=min_severity,
                       defensive_enabled=defensive_on,
                       shaping_enabled=shaping_on, event_id=event_id, ts=ts)
        applied = apply_route(conn, result)
        store.record_interpretation(
            conn, event_id, {**interp.to_dict(),
                             "action_class": result.action_class},
            model=interp.model, cost=cost_per, outcome=applied["outcome"],
            outcome_reason=applied["reason"], ts=ts)
        if applied["outcome"] == "queued":
            stats["actions_queued"] += 1
        elif applied["outcome"] == "referred":
            stats["referrals"] += 1

    stats["est_cost_usd"] = round(stats["llm_calls"] * cost_per, 4)
    stats["budget_remaining"] = max(0, budget - used - stats["llm_calls"])
    store.record_poll(conn, stats, ts)
    conn.commit()
    return stats


def run_due(conn: sqlite3.Connection, *, client=None, interpreter=None,
            now: datetime | None = None, cfg_path: str | None = None) -> dict:
    """Poll if the cadence says it is time. The loop's per-tick entry point."""
    now = now or _utcnow()
    if not settings.news_feed_enabled(cfg_path):
        return {"status": "disabled", "reason": "adaptive_news_feed_enabled off",
                "events_seen": 0, "llm_calls": 0}
    if not due(conn, interval_seconds=settings.poll_interval_seconds(cfg_path),
               now=now):
        return {"status": "not_due", "reason": "", "events_seen": 0,
                "llm_calls": 0}
    return run_once(conn, client=client, interpreter=interpreter, now=now,
                    cfg_path=cfg_path)


def _db_path() -> str:
    from llm_consensus.config_access import config_block
    return (os.environ.get("MAL_DB_PATH")
            or config_block("system", None).get("db_path")
            or "market_ai_lab.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adaptive real-time layer: one poll of the live event feed. "
                    "Does nothing unless adaptive_news_feed_enabled is on.")
    parser.add_argument("--db", default=None, help="SQLite path")
    parser.add_argument("--once", action="store_true",
                        help="poll now, ignoring the cadence")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = args.db or _db_path()
    conn = sqlite3.connect(db)
    try:
        stats = (run_once(conn) if args.once else run_due(conn))
    finally:
        conn.close()

    if stats.get("status") == "disabled":
        print("adaptive: OFF (adaptive_news_feed_enabled is false). "
              "No poll, no events, no spend.")
        return 0
    print(f"adaptive: {stats.get('status')} "
          f"seen={stats.get('events_seen', 0)} "
          f"material={stats.get('events_material', 0)} "
          f"escalated={stats.get('events_escalated', 0)} "
          f"llm_calls={stats.get('llm_calls', 0)} "
          f"queued={stats.get('actions_queued', 0)} "
          f"referrals={stats.get('referrals', 0)} "
          f"est_cost=${stats.get('est_cost_usd', 0.0):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
