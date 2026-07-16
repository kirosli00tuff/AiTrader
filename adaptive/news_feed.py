"""The live news and event feed. The OBSERVE half's eyes.

Polls Finnhub once a minute for news about three sets of instruments, in
descending order of how much the news could matter:

1. HELD instruments. News about something we own can trigger a defensive action,
   so it is never dropped for lack of room in the poll budget.
2. WATCHLIST instruments. News about a candidate can shape the watchlist.
3. GENERAL market news. A macro event that names no symbol we track.

Transport is the existing discovery/finnhub_source.py client, deliberately: it
already resolves the key from the keystore (never logging it), already enforces
the 60-calls-per-minute free-tier limit with a sliding window, already retries a
429 with bounded backoff honoring Retry-After, and already caches per endpoint.
Writing a second HTTP client for the same vendor would mean a second rate limiter
that does not know about the first, and the two would race each other into the
limit. One client, one limiter.

COST. This stage spends no LLM tokens at all. It is HTTP against a free tier.
The paid stage is adaptive/interpret.py, and it only ever sees what survives
adaptive/materiality.py.

Nothing here runs unless ``adaptive_news_feed_enabled`` is on. The flag is
checked by the caller (adaptive/run.py) before this module is constructed, so
with the flag off no client exists, no key is resolved, and no socket opens.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from discovery.finnhub_source import parse_company_news, parse_news_sentiment

log = logging.getLogger("adaptive.news_feed")

_GENERAL_SYMBOL = ""


def held_symbols(conn: sqlite3.Connection) -> list[str]:
    """Symbols with an open position. Read-only.

    Tolerant: a DB with no positions table (or an older schema) degrades to "no
    held names", never to a throw. This layer is advisory and must never be able
    to take the trading loop down.
    """
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM positions WHERE qty != 0 "
            "ORDER BY symbol").fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows if r and r[0]]


def watchlist_symbols(conn: sqlite3.Connection) -> list[str]:
    """Active watchlist symbols. Read-only, tolerant of a missing table."""
    try:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' "
            "ORDER BY symbol").fetchall()
    except sqlite3.Error:
        return []
    return [r[0] for r in rows if r and r[0]]


def poll_targets(conn: sqlite3.Connection, *, max_symbols: int) -> list[dict]:
    """What this poll will ask about, HELD NAMES FIRST, capped at max_symbols.

    Returns [{"symbol": str, "held": bool}]. The cap is a hard bound on the call
    rate: the watchlist can grow, but the calls per minute cannot.

    The ordering is a safety property, not cosmetics. When the cap binds, the
    thing dropped from the poll must be a candidate we might buy, never a
    position we already own and might need to exit.
    """
    held = held_symbols(conn)
    watch = [s for s in watchlist_symbols(conn) if s not in set(held)]
    out = [{"symbol": s, "held": True} for s in held]
    out += [{"symbol": s, "held": False} for s in watch]
    return out[:max(0, int(max_symbols))]


class NewsFeed:
    """One poll of the live feed. Constructed only when the feed flag is on."""

    def __init__(self, client, *, lookback_minutes: int = 15,
                 general: bool = True) -> None:
        self._client = client
        self._lookback = int(lookback_minutes)
        self._general = bool(general)

    def _window(self, now: datetime) -> tuple[str, str, datetime]:
        """The [from, to] date window and the cutoff instant.

        Finnhub's company-news window is DATE granular, so the API call asks for
        whole days while the cutoff below filters to the minute. Asking for
        yesterday too is deliberate: near midnight UTC a window that only asked
        for today would miss an event published four minutes ago.
        """
        cutoff = now - timedelta(minutes=self._lookback)
        return (cutoff.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), cutoff)

    def _fresh(self, articles: list[dict], cutoff: datetime) -> list[dict]:
        """Keep only articles published at or after the cutoff.

        An article with no parseable timestamp is KEPT. Dedupe stops it from
        being re-charged, and the alternative (dropping it) would silently lose
        real events whenever the vendor omits a field.
        """
        out = []
        for a in articles:
            ts = a.get("published_ts") or ""
            if not ts:
                out.append(a)
                continue
            try:
                when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
            except ValueError:
                out.append(a)
                continue
            if when >= cutoff:
                out.append(a)
        return out

    def _sentiment_for(self, symbol: str) -> float:
        """Finnhub's PRE-COMPUTED sentiment for a symbol, as a signed magnitude.

        Aggregate per symbol, not per article: the free tier has no per-article
        score. It is cached hard (15m) by the client, so polling every minute
        does not mean fetching this every minute. Any failure degrades to 0.0,
        which means "sentiment triggers nothing", never a wrong number.
        """
        try:
            s = parse_news_sentiment(self._client.news_sentiment(symbol))
        except Exception:  # noqa: BLE001 - an advisory feed never raises upward
            return 0.0
        # parse_news_sentiment returns {} for a malformed payload, so a missing
        # "score" means "no sentiment known" and must read as 0.0, not as 0.5
        # re-centred. Those are different claims: one is silence, one is neutral.
        score = s.get("score")
        if score is None:
            return 0.0
        try:
            # Finnhub's companyNewsScore is 0..1 centred at 0.5. Re-centre to
            # -1..1 so "magnitude" means "far from neutral" in either direction,
            # which is what the materiality filter asks of it.
            return max(-1.0, min(1.0, (float(score) - 0.5) * 2.0))
        except (TypeError, ValueError):
            return 0.0

    def poll(self, targets: list[dict], *,
             now: datetime | None = None) -> list[dict]:
        """Fetch one round of events. Returns event dicts.

        Never raises: a feed error yields fewer events, never an exception into
        the runner. The runner records what it got and tries again next minute.
        """
        now = now or datetime.now(timezone.utc)
        frm, to, cutoff = self._window(now)
        seen_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        events: list[dict] = []

        for t in targets:
            symbol = t.get("symbol", "")
            if not symbol:
                continue
            try:
                raw = self._client.company_news(symbol, frm, to)
            except Exception as e:  # noqa: BLE001
                log.warning("company_news failed for %s: %s", symbol, e)
                continue
            articles = self._fresh(parse_company_news(raw), cutoff)
            if not articles:
                continue
            sentiment = self._sentiment_for(symbol)
            for a in articles:
                events.append({
                    **a, "ts": seen_ts, "symbol": symbol,
                    "held": bool(t.get("held")), "sentiment": sentiment,
                    "event_type": _event_type_of(a),
                    "category": "company",
                })

        if self._general:
            try:
                raw = self._client.general_news()
            except Exception as e:  # noqa: BLE001
                log.warning("general_news failed: %s", e)
                raw = None
            for a in self._fresh(parse_company_news(raw), cutoff):
                events.append({
                    **a, "ts": seen_ts, "symbol": _GENERAL_SYMBOL,
                    "held": False, "sentiment": 0.0,
                    "event_type": _event_type_of(a), "category": "general",
                })

        return events


# Event-type inference from the headline. Crude on purpose: this feeds the free
# materiality filter, which only needs a hint, and a wrong hint costs at most one
# cheap call. The model does the real reading later, on the few that survive.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("earnings", "earnings"),
    ("q1 results", "earnings"),
    ("q2 results", "earnings"),
    ("q3 results", "earnings"),
    ("q4 results", "earnings"),
    ("guidance", "guidance"),
    ("profit warning", "guidance"),
    ("merger", "merger"),
    ("acquire", "acquisition"),
    ("acquisition", "acquisition"),
    ("takeover", "acquisition"),
    ("buyout", "acquisition"),
    ("halt", "halt"),
    ("delist", "delisting"),
    ("bankrupt", "bankruptcy"),
    ("chapter 11", "bankruptcy"),
    ("sec probe", "regulatory"),
    ("investigation", "regulatory"),
    ("fda", "regulatory"),
    ("lawsuit", "litigation"),
    ("sues", "litigation"),
    ("offering", "offering"),
    ("stock split", "split"),
)


def _event_type_of(article: dict) -> str:
    """Best-effort event type, or "" when nothing matches."""
    text = f"{article.get('headline', '')} {article.get('summary', '')}".lower()
    for needle, etype in _TYPE_HINTS:
        if needle in text:
            return etype
    return ""
