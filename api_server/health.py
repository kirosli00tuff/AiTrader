"""Live integration health checks (GET /health/integrations).

Each check does ONE real minimal round trip and reports working, failing, or
not_configured, with a short reason and round-trip latency in milliseconds.
Checks run concurrently with a per-check timeout.

SAFETY. Read-only except the Alpaca trade-auth check, which AUTHENTICATES only
(GET /v2/account) and never creates a resting order or moves money. No check
places an order, touches live trading, or writes an operational or Level-1
value. No key value is ever logged or returned. An absent key reports
not_configured, never failing. SEC EDGAR is checked only when SEC_EDGAR_ENABLED
is on. IBKR is checked only when ibkr.connection_enabled is on, and only for
socket reachability with no order. Reserved paid feeds always report
not_configured (no adapter is wired, no call is made).
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from api_server import store

_TIMEOUT = 6.0
WORKING, FAILING, NOT_CONFIGURED = "working", "failing", "not_configured"


def _key(env: str):
    try:
        from account_manager.credentials import resolve_env
        return resolve_env(env)
    except Exception:
        return os.environ.get(env)


def _alpaca_creds():
    try:
        from account_manager.credentials import get_credential
        return (get_credential("alpaca_paper_key"),
                get_credential("alpaca_paper_secret"))
    except Exception:
        return _key("APCA_API_KEY_ID"), _key("APCA_API_SECRET_KEY")


def _get(url: str, headers: dict) -> int:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310
        return r.status


def _post(url: str, headers: dict, payload: dict) -> int:
    data = json.dumps(payload).encode()
    hdr = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310
        return r.status


# --- individual checks (each returns (state, reason)) -----------------------

def _check_openai():
    key = _key("OPENAI_API_KEY")
    if not key:
        return NOT_CONFIGURED, "OPENAI_API_KEY not set"
    status = _post("https://api.openai.com/v1/chat/completions",
                   {"Authorization": f"Bearer {key}"},
                   {"model": "gpt-5.5",
                    "messages": [{"role": "user", "content": "ping"}],
                    # GPT-5 family: max_completion_tokens (not max_tokens), and
                    # no custom temperature. A tiny cap leaves room past reasoning.
                    "max_completion_tokens": 16})
    return (WORKING, "") if status == 200 else (FAILING, f"HTTP {status}")


def _anthropic(model: str):
    key = _key("ANTHROPIC_API_KEY")
    if not key:
        return NOT_CONFIGURED, "ANTHROPIC_API_KEY not set"
    status = _post("https://api.anthropic.com/v1/messages",
                   {"x-api-key": key, "anthropic-version": "2023-06-01"},
                   {"model": model, "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}]})
    return (WORKING, "") if status == 200 else (FAILING, f"HTTP {status}")


def _check_gemini():
    key = _key("GEMINI_API_KEY")
    if not key:
        return NOT_CONFIGURED, "GEMINI_API_KEY not set"
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-3.1-pro-preview:generateContent")
    status = _post(url, {"x-goog-api-key": key},
                   {"contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1}})
    return (WORKING, "") if status == 200 else (FAILING, f"HTTP {status}")


def _check_alpaca_data():
    k, s = _alpaca_creds()
    if not (k and s):
        return NOT_CONFIGURED, "Alpaca paper keys not set"
    base = os.environ.get("ALPACA_DATA_BASE", "https://data.alpaca.markets")
    status = _get(f"{base}/v2/stocks/SPY/quotes/latest",
                  {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    return (WORKING, "one quote ok") if status == 200 else (FAILING, f"HTTP {status}")


def _check_alpaca_trading():
    # AUTH-ONLY: GET /v2/account. Never creates a resting order or moves money.
    k, s = _alpaca_creds()
    if not (k and s):
        return NOT_CONFIGURED, "Alpaca paper keys not set"
    base = os.environ.get("ALPACA_PAPER_BASE", "https://paper-api.alpaca.markets")
    status = _get(f"{base}/v2/account",
                  {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    return (WORKING, "paper account auth ok") if status == 200 else (FAILING, f"HTTP {status}")


def _check_sec_edgar():
    from whale_signal.adapters import (SEC_EDGAR_ENABLED_ENV, _flag,
                                       _user_agent)
    if not _flag(SEC_EDGAR_ENABLED_ENV):
        return NOT_CONFIGURED, "SEC_EDGAR_ENABLED is off"
    status = _get("https://efts.sec.gov/LATEST/search-index?q=Apple&forms=13F-HR",
                  {"User-Agent": _user_agent(), "Accept": "application/json"})
    return (WORKING, "") if status == 200 else (FAILING, f"HTTP {status}")


def _check_ibkr():
    # Reachability ONLY. No order, no data channel.
    cfg = store.load_config().get("ibkr", {}) or {}
    if not cfg.get("connection_enabled"):
        return NOT_CONFIGURED, "ibkr.connection_enabled is off"
    host = str(cfg.get("gateway_host", "127.0.0.1"))
    port = int(cfg.get("gateway_port", 4001))
    with socket.create_connection((host, port), timeout=_TIMEOUT):
        pass
    return WORKING, f"gateway reachable {host}:{port}"


def _check_reserved(env: str, label: str):
    # Reserved paid feed: no adapter is wired, so we NEVER call. Report
    # not_configured whether or not the key is present.
    return NOT_CONFIGURED, f"{label} reserved, no adapter wired"


def _check_whale_alert():
    # Whale Alert crypto trial feed. Only when opt-in AND keyed do we make one
    # real minimal call. Off or unkeyed reports not_configured (never failing).
    # The key is only ever a query param and is never logged or returned.
    from whale_signal.adapters import (WHALE_ALERT_ENABLED_ENV, _flag,
                                       _user_agent)
    if not _flag(WHALE_ALERT_ENABLED_ENV):
        return NOT_CONFIGURED, "whale_alert_enabled is off"
    key = _key("WHALE_ALERT_API_KEY")
    if not key:
        return NOT_CONFIGURED, "WHALE_ALERT_API_KEY not set"
    start = int(time.time()) - 3600
    url = ("https://api.whale-alert.io/v1/transactions"
           f"?api_key={key}&min_value=500000&start={start}&limit=1")
    status = _get(url, {"User-Agent": _user_agent(), "Accept": "application/json"})
    return (WORKING, "one tx query ok") if status == 200 else (FAILING, f"HTTP {status}")


def _finnhub_once(url: str) -> tuple[int, dict]:
    """One GET, returning (status, response headers) rather than raising.

    _get raises on a non-2xx, but this check has to tell a bad key (401) from a
    transient rate limit (429), and a 429 carries the Retry-After header the
    backoff policy honors. Both arrive as an HTTPError, so the status comes off
    the exception instead of a second request. A transport failure still raises,
    and the caller classifies it.
    """
    try:
        return _get(url, {"Accept": "application/json"}), {}
    except urllib.error.HTTPError as e:
        return int(e.code), dict(getattr(e, "headers", {}) or {})


def _check_finnhub():
    """Finnhub feeds the discovery funnel's free Stage-A pre-screen.

    One minimal real call (a single quote) when a key resolves. No key reports
    not_configured, never failing: discovery ships off, so a missing optional key
    is not a fault, and the operator has to be able to tell that apart from a
    broken one.

    Finnhub carries its token as a QUERY PARAM, not a header, so this check does
    two things the header-authenticated checks above have no need for:

      * It classifies every outcome into a fixed phrase and never lets a raw
        exception reach _run. _run stringifies the exception into `reason`, which
        the endpoint returns and the GUI renders, and this URL holds the token.
      * It retries a 429 with the discovery client's own backoff policy, so a
        transient rate limit reads as busy rather than broken. This check shares
        the 60-calls-per-minute free tier with a running discovery pass, so a 429
        means the budget is in use, not that the key is bad.
    """
    key = _key("FINNHUB_API_KEY")
    if not key:
        return NOT_CONFIGURED, "FINNHUB_API_KEY not set"

    # The discovery client's existing policy, not a second copy of it.
    from discovery.finnhub_source import (RATE_LIMIT_MAX_RETRIES,
                                          retry_after_seconds)

    url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
    status, headers = 0, {}
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            status, headers = _finnhub_once(url)
        except Exception as e:  # noqa: BLE001 — type name only, never the URL
            return FAILING, f"network unreachable ({type(e).__name__})"
        if status != 429:
            break
        if attempt < RATE_LIMIT_MAX_RETRIES:
            time.sleep(retry_after_seconds(headers, attempt))

    if status == 200:
        return WORKING, "one quote ok"
    if status == 429:
        return FAILING, f"rate limited (HTTP 429) after {RATE_LIMIT_MAX_RETRIES} retries"
    if status in (401, 403):
        return FAILING, f"bad key (HTTP {status})"
    return FAILING, f"HTTP {status}"


_CHECKS = [
    ("openai", "OpenAI GPT-5.5", _check_openai),
    ("anthropic_opus", "Anthropic Claude Opus 4.8",
     lambda: _anthropic("claude-opus-4-8")),
    ("anthropic_haiku_gate", "Anthropic Claude Haiku 4.5 (gate)",
     lambda: _anthropic("claude-haiku-4-5")),
    ("gemini", "Google Gemini 3.1 Pro", _check_gemini),
    ("alpaca_data", "Alpaca paper market data", _check_alpaca_data),
    ("alpaca_trading_auth", "Alpaca paper trading auth", _check_alpaca_trading),
    ("finnhub", "Finnhub (discovery pre-screen)", _check_finnhub),
    ("sec_edgar", "SEC EDGAR 13F", _check_sec_edgar),
    ("ibkr_gateway", "IBKR gateway reachability", _check_ibkr),
    ("whale_alert", "Whale Alert (crypto trial)", _check_whale_alert),
    ("unusual_whales", "Unusual Whales Pro (reserved paid)",
     lambda: _check_reserved("UNUSUAL_WHALES_API_KEY", "Unusual Whales Pro")),
]


def _run(name: str, provider: str, fn) -> dict:
    t0 = time.perf_counter()
    try:
        state, reason = fn()
    except Exception as e:  # network / socket / decode -> failing, never raises
        state, reason = FAILING, f"{type(e).__name__}: {e}"[:160]
    ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {"name": name, "provider": provider, "state": state,
            "reason": reason, "latency_ms": ms}


def integrations() -> dict:
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(_CHECKS)) as ex:
        futs = {ex.submit(_run, n, p, fn): n for n, p, fn in _CHECKS}
        try:
            for f in as_completed(futs, timeout=_TIMEOUT * 2 + 2):
                r = f.result()
                out[r["name"]] = r
        except Exception:
            pass
    ordered = []
    for n, p, _fn in _CHECKS:
        ordered.append(out.get(n, {"name": n, "provider": p, "state": FAILING,
                                   "reason": "check timed out", "latency_ms": None}))
    configured = [r for r in ordered if r["state"] != NOT_CONFIGURED]
    all_ok = bool(configured) and all(r["state"] == WORKING for r in configured)
    any_failing = any(r["state"] == FAILING for r in configured)
    return {"integrations": ordered,
            "summary": {"all_ok": all_ok, "any_failing": any_failing,
                        "configured_count": len(configured),
                        "total": len(ordered), "ts": store._now()}}
