"""Finnhub client for the discovery funnel's free pre-screen (stdlib HTTP only).

Serves the cheap Stage-A signals: real-time quotes, company news, Finnhub's
pre-computed news sentiment, basic fundamentals, analyst ratings, and the
earnings calendar. None of these calls spends an LLM token, which is the point:
Stage A ranks the whole universe for free and only a handful of finalists ever
reach a paid model.

Posture:
  * The key resolves keystore-first through ``account_manager.credentials``
    (in-app saved value, then FINNHUB_API_KEY env / .env). It is never
    hardcoded, never logged, and never echoed in an error. The token is injected
    only into the final URL, so it never reaches a cache key or a log line.
  * The free tier allows 60 calls per minute. A sliding-window rate limiter
    holds the client under that, and a 429 retries with bounded backoff
    (honoring Retry-After) before degrading.
  * Every call degrades to ``None`` rather than raising, so a Finnhub outage
    pauses discovery instead of breaking the engine.
  * Responses are cached with a per-endpoint TTL, so one pass over a 150-name
    universe does not re-fetch what it already holds.

Docs: https://finnhub.io/docs/api
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from account_manager import credentials
except Exception:  # noqa: BLE001 — credentials optional / cryptography missing
    credentials = None  # type: ignore

log = logging.getLogger("discovery.finnhub")

BASE_URL = os.environ.get("FINNHUB_BASE", "https://finnhub.io/api/v1")
HTTP_TIMEOUT = float(os.environ.get("FINNHUB_HTTP_TIMEOUT", "6.0"))

# Free tier: 60 calls/minute.
RATE_LIMIT_CALLS = int(os.environ.get("FINNHUB_RATE_LIMIT", "60"))
RATE_LIMIT_WINDOW_SECONDS = 60.0

# 429 retry policy. Mirrors the existing whale-adapter policy (bounded
# exponential backoff, honor a numeric Retry-After, hard cap) so the two feeds
# behave the same under a rate limit. A 429 is the only status worth retrying:
# it is transient by definition. Anything else fails fast to the caller.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_BASE_BACKOFF_S = 1.0
RATE_LIMIT_BACKOFF_CAP_S = 5.0

# Per-endpoint cache TTL in seconds. A quote goes stale fast; fundamentals and
# analyst ratings barely move intraday, so they are cached hard.
#
# ORDER MATTERS. _ttl_for prefix-matches, so a shorter key that prefixes a longer
# one must come AFTER it: "news-sentiment" is listed before "news", otherwise
# every sentiment read would silently inherit the 60s live-news TTL and re-fetch
# an aggregate that only moves daily.
#
# The two live-news TTLs are 60s because the adaptive layer polls once a minute,
# and a news cache longer than the poll interval would hand it stale headlines and
# make a live feed look broken while quietly seeing nothing. Nothing else calls
# company-news or news, and news-sentiment keeps its hard 15m cache, so the short
# TTL adds no call anywhere else.
CACHE_TTL_SECONDS: dict[str, float] = {
    "quote": 30.0,
    "news-sentiment": 900.0,
    "company-news": 60.0,
    "stock/metric": 21600.0,          # 6h: fundamentals move on earnings, not ticks
    "stock/recommendation": 21600.0,  # 6h: analyst ratings change slowly
    "calendar/earnings": 3600.0,
    "news": 60.0,                     # general market news; keep last (prefix)
}
_DEFAULT_TTL = 300.0


def retry_after_seconds(headers, attempt: int) -> float:
    """Backoff for a 429: honor a numeric Retry-After header, else exponential.

    Bounded and safe: a malformed or missing header falls back to
    RATE_LIMIT_BASE_BACKOFF_S * 2**attempt, capped so a retry never stalls a
    discovery pass. Never raises.
    """
    try:
        raw = None
        if headers:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            return max(0.0, min(float(raw), RATE_LIMIT_BACKOFF_CAP_S))
    except (TypeError, ValueError, AttributeError):
        pass
    return min(RATE_LIMIT_BASE_BACKOFF_S * (2 ** attempt), RATE_LIMIT_BACKOFF_CAP_S)


class RateLimiter:
    """Sliding-window limiter: at most ``calls`` starts per ``window`` seconds.

    Thread-safe. ``acquire`` blocks until a slot frees, so a caller cannot exceed
    the free-tier ceiling by looping. ``try_acquire`` reports instead of waiting,
    which the funnel uses to stop a pass early rather than stall it.
    """

    def __init__(self, calls: int = RATE_LIMIT_CALLS,
                 window: float = RATE_LIMIT_WINDOW_SECONDS) -> None:
        self.calls = max(1, int(calls))
        self.window = float(window)
        self._starts: list[float] = []
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        self._starts = [t for t in self._starts if t > cutoff]

    def try_acquire(self, now: float | None = None) -> bool:
        """Take a slot if one is free right now. Never blocks."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            if len(self._starts) < self.calls:
                self._starts.append(now)
                return True
            return False

    def acquire(self) -> None:
        """Take a slot, waiting for the window to roll if the limit is hit."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._starts) < self.calls:
                    self._starts.append(now)
                    return
                sleep_for = self.window - (now - self._starts[0]) + 0.01
            time.sleep(max(0.01, sleep_for))


class _Cache:
    """TTL cache keyed by (path, sorted params minus the token). Thread-safe."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float) -> object | None:
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            stored_at, value = hit
            if time.monotonic() - stored_at > ttl:
                self._data.pop(key, None)
                return None
            return value

    def put(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def resolve_key() -> str | None:
    """Resolve FINNHUB_API_KEY keystore-first, then env. Never logged."""
    if credentials is not None:
        try:
            val = credentials.get_credential("finnhub_key")
            if val:
                return val
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("FINNHUB_API_KEY") or None


def is_live() -> bool:
    """True when a Finnhub key resolves, so a caller can degrade cleanly."""
    return bool(resolve_key())


class FinnhubClient:
    """Finnhub REST client: rate-limited, cached, key never logged.

    Every method returns parsed JSON or ``None`` when the call is unavailable
    (no key, network error, non-429 HTTP error, exhausted 429 retry, or the rate
    limiter refusing in non-blocking mode).
    """

    def __init__(self, api_key: str | None = None, *,
                 limiter: RateLimiter | None = None,
                 opener=None, block_on_limit: bool = True) -> None:
        # api_key resolves lazily so a key saved in the GUI mid-run is picked up
        # without reconstructing the client.
        self._api_key = api_key
        self._limiter = limiter or RateLimiter()
        self._cache = _Cache()
        # Injection seam for tests: callable(url) -> (status, body_bytes, headers).
        # Keeps the whole suite off the network.
        self._opener = opener
        self._block_on_limit = block_on_limit
        self.calls_made = 0
        self.rate_limited = 0

    # --- internals ----------------------------------------------------------

    def _key(self) -> str | None:
        return self._api_key or resolve_key()

    def _cache_key(self, path: str, params: dict) -> str:
        # The token is never part of the cache key.
        safe = {k: v for k, v in sorted(params.items()) if k != "token"}
        return path + "?" + urllib.parse.urlencode(safe)

    def _ttl_for(self, path: str) -> float:
        for prefix, ttl in CACHE_TTL_SECONDS.items():
            if path.startswith(prefix):
                return ttl
        return _DEFAULT_TTL

    def _fetch(self, url: str) -> tuple[int, bytes, dict]:
        if self._opener is not None:
            return self._opener(url)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return resp.status, resp.read(), dict(resp.headers or {})
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:  # noqa: BLE001
                body = b""
            return e.code, body, dict(getattr(e, "headers", {}) or {})

    def _get(self, path: str, params: dict) -> object | None:
        """Rate-limited, cached GET with bounded 429 retry. Never raises."""
        key = self._key()
        if not key:
            log.debug("finnhub: no api key resolved, skipping %s", path)
            return None

        ck = self._cache_key(path, params)
        cached = self._cache.get(ck, self._ttl_for(path))
        if cached is not None:
            return cached

        query = dict(params)
        query["token"] = key
        url = f"{BASE_URL}/{path}?" + urllib.parse.urlencode(query)

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            if self._block_on_limit:
                self._limiter.acquire()
            elif not self._limiter.try_acquire():
                self.rate_limited += 1
                log.debug("finnhub: local rate limit reached, skipping %s", path)
                return None
            try:
                status, body, headers = self._fetch(url)
                self.calls_made += 1
            except Exception as e:  # noqa: BLE001 — network/transport failure
                # Log the exception TYPE only. The URL carries the token, so
                # neither it nor the raw exception text is ever logged.
                log.debug("finnhub: transport error on %s (%s)", path,
                          type(e).__name__)
                return None

            if status == 429:
                self.rate_limited += 1
                if attempt >= RATE_LIMIT_MAX_RETRIES:
                    log.debug("finnhub: rate limited on %s, giving up", path)
                    return None
                time.sleep(retry_after_seconds(headers, attempt))
                continue
            if status != 200:
                # 401/403 means the key is missing or wrong. Report the status,
                # never the key.
                log.debug("finnhub: HTTP %s on %s", status, path)
                return None
            try:
                parsed = json.loads(body) if body else None
            except ValueError:
                log.debug("finnhub: unparseable body on %s", path)
                return None
            if parsed is None:
                return None
            self._cache.put(ck, parsed)
            return parsed
        return None

    # --- endpoints ----------------------------------------------------------

    def quote(self, symbol: str) -> dict | None:
        """Real-time quote. Keys: c current, d change, dp change pct, h high,
        l low, o open, pc previous close, t epoch timestamp."""
        r = self._get("quote", {"symbol": symbol})
        return r if isinstance(r, dict) else None

    def company_news(self, symbol: str, frm: str, to: str) -> list | None:
        """Company news over [frm, to] (YYYY-MM-DD). List of article dicts."""
        r = self._get("company-news", {"symbol": symbol, "from": frm, "to": to})
        return r if isinstance(r, list) else None

    def general_news(self, category: str = "general") -> list | None:
        """Market-wide news, not tied to one instrument. List of article dicts,
        same shape as company_news. Used by the adaptive layer so a macro event
        (a rate decision, an index-wide halt) is seen even when it names no
        symbol on the watchlist."""
        r = self._get("news", {"category": category})
        return r if isinstance(r, list) else None

    def news_sentiment(self, symbol: str) -> dict | None:
        """Finnhub's PRE-COMPUTED news sentiment. A cheap numeric signal, NOT
        live LLM news interpretation (that layer is deferred, see CONTEXT.md).
        Keys: companyNewsScore, sentiment{bullishPercent,bearishPercent},
        buzz{articlesInLastWeek,weeklyAverage,buzz}."""
        r = self._get("news-sentiment", {"symbol": symbol})
        return r if isinstance(r, dict) else None

    def basic_financials(self, symbol: str, metric: str = "all") -> dict | None:
        """Basic fundamentals. The ``metric`` block carries e.g.
        peBasicExclExtraTTM, roeTTM, netProfitMarginTTM, revenueGrowthTTMYoy."""
        r = self._get("stock/metric", {"symbol": symbol, "metric": metric})
        return r if isinstance(r, dict) else None

    def recommendation_trends(self, symbol: str) -> list | None:
        """Analyst ratings per period: strongBuy, buy, hold, sell, strongSell."""
        r = self._get("stock/recommendation", {"symbol": symbol})
        return r if isinstance(r, list) else None

    def earnings_calendar(self, frm: str, to: str,
                          symbol: str | None = None) -> dict | None:
        """Earnings calendar over [frm, to] (YYYY-MM-DD).
        Returns {"earningsCalendar": [{symbol, date, epsEstimate, ...}, ...]}."""
        params: dict = {"from": frm, "to": to}
        if symbol:
            params["symbol"] = symbol
        r = self._get("calendar/earnings", params)
        return r if isinstance(r, dict) else None

    def clear_cache(self) -> None:
        self._cache.clear()


# --- parsers (pure, fixture-testable) ---------------------------------------
# Separate from transport so tests exercise real payload shapes with no network.
# Every parser tolerates a missing or malformed field: a bad parse in a money
# loop must degrade to "no signal", never to a wrong number.

def parse_quote(payload: dict | None) -> dict:
    """Normalize a quote to {price, change_pct, high, low, open, prev_close}.

    Returns {} when the payload carries no usable price, so a caller can test
    truthiness instead of sentinel-checking every field.
    """
    if not isinstance(payload, dict):
        return {}
    try:
        price = float(payload.get("c") or 0.0)
    except (TypeError, ValueError):
        return {}
    if price <= 0.0:
        return {}

    def _f(key: str) -> float:
        try:
            return float(payload.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "price": price,
        "change_pct": _f("dp"),
        "high": _f("h"),
        "low": _f("l"),
        "open": _f("o"),
        "prev_close": _f("pc"),
    }


def parse_news_sentiment(payload: dict | None) -> dict:
    """Normalize news sentiment to {score, bullish_pct, bearish_pct, buzz, ...}.

    ``score`` is Finnhub's companyNewsScore in [0,1] (0.5 = neutral).
    """
    if not isinstance(payload, dict):
        return {}
    sentiment = payload.get("sentiment") or {}
    buzz = payload.get("buzz") or {}

    def _f(src: dict, key: str, default: float = 0.0) -> float:
        try:
            v = src.get(key)
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "score": max(0.0, min(1.0, _f(payload, "companyNewsScore", 0.5))),
        "bullish_pct": _f(sentiment, "bullishPercent"),
        "bearish_pct": _f(sentiment, "bearishPercent"),
        "buzz": _f(buzz, "buzz"),
        "articles_last_week": _f(buzz, "articlesInLastWeek"),
    }


def parse_company_news(payload: list | None) -> list[dict]:
    """Normalize a news list to the adaptive layer's event shape.

    Finnhub article keys: id, datetime (epoch seconds), headline, summary,
    source, url, related (comma-separated symbols), category.

    An article with no id cannot be deduped, and an un-dedupable article would be
    re-read and re-charged on every overlapping poll, so it is DROPPED rather
    than passed through. Losing an occasional malformed article is cheaper than
    paying for the same headline sixty times an hour.
    """
    if not isinstance(payload, list):
        return []
    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if raw_id in (None, "", 0):
            continue
        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue
        epoch = item.get("datetime")
        published = ""
        try:
            if epoch:
                published = datetime.fromtimestamp(
                    float(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OSError):
            published = ""
        related = str(item.get("related") or "").strip()
        out.append({
            "dedupe_key": f"finnhub:{raw_id}",
            "published_ts": published,
            "headline": headline,
            "summary": str(item.get("summary") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "category": str(item.get("category") or "").strip(),
            "related": related,
        })
    return out


def parse_recommendations(payload: list | None) -> dict:
    """Latest analyst period -> counts plus a signed [-1,1] consensus ``score``
    (+1 all strong buy, -1 all strong sell). Returns {} with no usable rows."""
    if not isinstance(payload, list) or not payload:
        return {}
    rows = [r for r in payload if isinstance(r, dict)]
    if not rows:
        return {}
    # Finnhub returns newest first, but sort defensively on the period label.
    latest = sorted(rows, key=lambda r: str(r.get("period", "")), reverse=True)[0]

    def _i(key: str) -> int:
        try:
            return int(latest.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    sb, b, h, s, ss = (_i("strongBuy"), _i("buy"), _i("hold"), _i("sell"),
                       _i("strongSell"))
    total = sb + b + h + s + ss
    if total <= 0:
        return {}
    score = (sb * 1.0 + b * 0.5 + s * -0.5 + ss * -1.0) / total
    return {
        "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss,
        "total": total, "period": str(latest.get("period", "")),
        "score": round(max(-1.0, min(1.0, score)), 4),
    }


def parse_basic_financials(payload: dict | None) -> dict:
    """Pull the quality metrics the long-term screen uses.

    Returns {} when the metric block is absent. An individual missing metric
    comes back as None so the screen can tell "no data" from "a real zero".
    """
    if not isinstance(payload, dict):
        return {}
    metric = payload.get("metric")
    if not isinstance(metric, dict):
        return {}

    def _of(key: str) -> float | None:
        v = metric.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "pe_ttm": _of("peBasicExclExtraTTM"),
        "roe_ttm": _of("roeTTM"),
        "net_margin_ttm": _of("netProfitMarginTTM"),
        "revenue_growth_yoy": _of("revenueGrowthTTMYoy"),
        "week52_high": _of("52WeekHigh"),
        "week52_low": _of("52WeekLow"),
        "beta": _of("beta"),
    }


def parse_earnings_calendar(payload: dict | None) -> list[dict]:
    """Flatten the earnings calendar to [{symbol, date, eps_estimate}, ...]."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("earningsCalendar")
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym, date = r.get("symbol"), r.get("date")
        if not sym or not date:
            continue
        eps = r.get("epsEstimate")
        try:
            eps = float(eps) if eps is not None else None
        except (TypeError, ValueError):
            eps = None
        out.append({"symbol": str(sym), "date": str(date), "eps_estimate": eps})
    return out
