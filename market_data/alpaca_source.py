"""Alpaca real-time market data + paper order submission (stdlib HTTP only).

Used by the Python bridge to serve two C++ endpoints:
  * ``fetch_prices`` -> latest price per requested symbol (POST /marketdata/alpaca)
  * ``submit_paper_order`` -> Alpaca PAPER trading order (POST /execute/alpaca_paper)

Both work with a *paper / data* key only — NO live brokerage account is needed,
so this is usable from regions where Alpaca live trading is unavailable (e.g.
Canada). Everything degrades gracefully: if no key resolves or the network call
fails, the functions return an "unavailable" marker and the C++ side falls back
to its deterministic offline path. Secrets are resolved via the encrypted
credential store (in-app first) then environment, and are never logged.

Data API:  https://data.alpaca.markets
Paper API: https://paper-api.alpaca.markets
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

# Make repo-root packages importable when imported from the bridge.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from account_manager import credentials
except Exception:  # noqa: BLE001 — credentials optional / cryptography missing
    credentials = None  # type: ignore

_DATA_BASE = os.environ.get("ALPACA_DATA_BASE", "https://data.alpaca.markets")
_PAPER_BASE = os.environ.get("ALPACA_PAPER_BASE",
                             "https://paper-api.alpaca.markets")
_TIMEOUT = float(os.environ.get("ALPACA_HTTP_TIMEOUT", "4.0"))


def _resolve(name: str, env_names: tuple[str, ...]) -> str | None:
    """Resolve a secret via the credential store first, then raw env."""
    if credentials is not None:
        try:
            val = credentials.get_credential(name)
            if val:
                return val
        except Exception:  # noqa: BLE001
            pass
    for env in env_names:
        v = os.environ.get(env)
        if v:
            return v
    return None


def _data_keys() -> tuple[str | None, str | None]:
    """Data-API key/secret via the unified resolver: keystore first, then the
    dedicated ALPACA_DATA_* env, then the generic ALPACA_* env."""
    key = _resolve("alpaca_paper_key", ("ALPACA_DATA_API_KEY", "ALPACA_API_KEY"))
    secret = _resolve("alpaca_paper_secret",
                      ("ALPACA_DATA_API_SECRET", "ALPACA_API_SECRET"))
    return key, secret


def _paper_keys() -> tuple[str | None, str | None]:
    key = _resolve("alpaca_paper_key", ("ALPACA_PAPER_API_KEY", "ALPACA_API_KEY"))
    secret = _resolve("alpaca_paper_secret",
                      ("ALPACA_PAPER_API_SECRET", "ALPACA_API_SECRET"))
    return key, secret


def _auth_headers(key: str, secret: str) -> dict[str, str]:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _http(method: str, url: str, headers: dict[str, str],
          body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            ValueError, TimeoutError):
        return None


def _is_crypto(symbol: str) -> bool:
    s = symbol.upper()
    return "/" in s or s.endswith("-USD") or s.endswith("-USDT")


def _crypto_pair(symbol: str) -> str:
    """Normalize e.g. BTC-USD -> BTC/USD (Alpaca crypto symbol format)."""
    s = symbol.upper()
    if "/" in s:
        return s
    if s.endswith("-USD"):
        return s[:-4] + "/USD"
    if s.endswith("-USDT"):
        return s[:-5] + "/USDT"
    return s


def fetch_prices(symbols: list[str]) -> dict:
    """Return {symbol: latest_price, ..., "source": ...} for resolvable symbols.

    Symbols with no live quote are simply omitted; the C++ feed random-walks
    those from their last price. ``source`` is "alpaca" if any live price was
    returned, else "unavailable".
    """
    out: dict[str, object] = {}
    key, secret = _data_keys()
    if not key or not secret:
        out["source"] = "unavailable"
        return out

    headers = _auth_headers(key, secret)
    equities = [s for s in symbols if not _is_crypto(s)]
    cryptos = [s for s in symbols if _is_crypto(s)]
    any_live = False

    # Equities: latest trade per symbol (batch endpoint).
    if equities:
        q = ",".join(equities)
        url = f"{_DATA_BASE}/v2/stocks/trades/latest?symbols={q}"
        resp = _http("GET", url, headers)
        trades = (resp or {}).get("trades", {}) if isinstance(resp, dict) else {}
        for sym in equities:
            t = trades.get(sym)
            if isinstance(t, dict):
                px = t.get("p")
                if isinstance(px, (int, float)) and px > 0:
                    out[sym] = float(px)
                    any_live = True

    # Crypto: latest trade per pair.
    if cryptos:
        pairs = {s: _crypto_pair(s) for s in cryptos}
        q = ",".join(pairs.values())
        url = f"{_DATA_BASE}/v1beta3/crypto/us/latest/trades?symbols={q}"
        resp = _http("GET", url, headers)
        trades = (resp or {}).get("trades", {}) if isinstance(resp, dict) else {}
        for sym, pair in pairs.items():
            t = trades.get(pair)
            if isinstance(t, dict):
                px = t.get("p")
                if isinstance(px, (int, float)) and px > 0:
                    out[sym] = float(px)
                    any_live = True

    out["source"] = "alpaca" if any_live else "unavailable"
    return out


def submit_paper_order(symbol: str, side: str, qty: float,
                       price: float = 0.0) -> dict:
    """Submit a market order to the Alpaca PAPER trading API.

    Returns a flat dict the C++ adapter understands:
      {"status": "ok", "order_id", "filled_price", "filled_qty"} on success, or
      {"status": "unavailable", "reason": ...} so the C++ side falls back to a
      sim-at-live-price fill (keeps paper trading alive everywhere).
    """
    key, secret = _paper_keys()
    if not key or not secret:
        return {"status": "unavailable", "reason": "no paper credentials"}
    if qty <= 0:
        return {"status": "unavailable", "reason": "non-positive qty"}

    sym = _crypto_pair(symbol) if _is_crypto(symbol) else symbol.upper()
    body = {
        "symbol": sym,
        "qty": str(qty),
        "side": "buy" if side.lower() == "buy" else "sell",
        "type": "market",
        "time_in_force": "gtc" if _is_crypto(symbol) else "day",
    }
    headers = _auth_headers(key, secret)
    resp = _http("POST", f"{_PAPER_BASE}/v2/orders", headers, body)
    if not isinstance(resp, dict) or "id" not in resp:
        return {"status": "unavailable", "reason": "paper API unreachable"}

    filled_price = resp.get("filled_avg_price") or price or 0.0
    filled_qty = resp.get("filled_qty") or resp.get("qty") or qty
    try:
        filled_price = float(filled_price)
    except (TypeError, ValueError):
        filled_price = float(price)
    try:
        filled_qty = float(filled_qty)
    except (TypeError, ValueError):
        filled_qty = float(qty)

    return {
        "status": "ok",
        "order_id": str(resp.get("id", "")),
        "filled_price": filled_price,
        "filled_qty": filled_qty,
        "broker_status": str(resp.get("status", "")),
    }


# --- Historical bar backfill (Task 1) ---------------------------------------
# Populates the shared ``bars`` table for the native-strategy whitelist so the
# C++ engine, DNN training, and backtests have real history. Timeframe labels
# ("1day", "5min") match the engine's ``strategy.bar_timeframe``. Idempotent
# (upsert). Offline / no key => no-op marker.
_WHITELIST_CRYPTO = ("BTC/USD", "ETH/USD")
_WHITELIST_EQUITY = ("SPY", "QQQ")

_BARS_DDL = (
    "CREATE TABLE IF NOT EXISTS bars ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, venue TEXT NOT NULL, symbol TEXT NOT NULL,"
    " timeframe TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL NOT NULL,"
    " high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL,"
    " source TEXT DEFAULT 'unknown',"
    " UNIQUE(venue, symbol, timeframe, timestamp))"
)

# Tolerant provenance migration for a DB created before the column existed.
# Existing rows land 'unknown', never a guess at real. Mirrors the C++
# storage.cpp migration, so whichever side opens the DB first migrates it.
_BARS_MIGRATIONS = (
    "ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
)


def ensure_bars_schema(conn: sqlite3.Connection) -> None:
    """Create the bars table if absent and add the provenance column. Idempotent."""
    conn.execute(_BARS_DDL)
    for mig in _BARS_MIGRATIONS:
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass  # duplicate column: already migrated


def _iso_days_ago(days: int) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_bars(url_base: str, headers: dict[str, str], symbols: list[str],
                api_timeframe: str, start: str) -> dict[str, list]:
    """Fetch bars for symbols, following Alpaca ``next_page_token`` pagination."""
    out: dict[str, list] = {s: [] for s in symbols}
    q = urllib.parse.quote(",".join(symbols), safe=",")
    page_token: str | None = None
    for _ in range(100):  # hard page cap to bound the loop
        url = (f"{url_base}?symbols={q}&timeframe={api_timeframe}"
               f"&start={start}&limit=10000")
        if page_token:
            url += f"&page_token={urllib.parse.quote(page_token)}"
        resp = _http("GET", url, headers)
        if not isinstance(resp, dict):
            break
        bars = resp.get("bars") or {}
        for s in symbols:
            out[s].extend(bars.get(s, []) or [])
        page_token = resp.get("next_page_token")
        if not page_token:
            break
    return out


def _upsert_bars(conn: sqlite3.Connection, venue: str, symbol: str,
                 timeframe: str, bars: list) -> int:
    written = 0
    for b in bars:
        ts, o, h, l, c = b.get("t"), b.get("o"), b.get("h"), b.get("l"), b.get("c")
        if ts is None or o is None or h is None or l is None or c is None:
            continue
        conn.execute(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source) VALUES(?,?,?,?,?,?,?,?,?,'backfill') "
            "ON CONFLICT(venue,symbol,timeframe,timestamp) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, volume=excluded.volume, "
            "source=excluded.source",
            (venue, symbol, timeframe, ts, float(o), float(h), float(l),
             float(c), float(b.get("v", 0) or 0)))
        written += 1
    return written


def backfill(db_path: str = "market_ai_lab.db",
             symbols: list[str] | None = None) -> dict:
    """Backfill 1yr daily + 30d 5-min bars for the whitelist into ``bars``.

    Idempotent (upsert on venue,symbol,timeframe,timestamp). With no data key
    resolvable it is a no-op returning ``{"status": "unavailable"}`` so it is
    safe to call in the offline paper environment.
    """
    key, secret = _data_keys()
    if not key or not secret:
        return {"status": "unavailable", "reason": "no data credentials"}
    headers = _auth_headers(key, secret)

    if symbols is None:
        crypto, equity = list(_WHITELIST_CRYPTO), list(_WHITELIST_EQUITY)
    else:
        crypto = [s for s in symbols if _is_crypto(s)]
        equity = [s for s in symbols if not _is_crypto(s)]

    # (Alpaca timeframe param, DB timeframe label, lookback start).
    plan = (("1Day", "1day", _iso_days_ago(365)),
            ("5Min", "5min", _iso_days_ago(30)))

    conn = sqlite3.connect(db_path)
    written: dict[str, int] = {}
    try:
        ensure_bars_schema(conn)
        for api_tf, db_tf, start in plan:
            if equity:
                got = _fetch_bars(f"{_DATA_BASE}/v2/stocks/bars", headers,
                                  equity, api_tf, start)
                for s in equity:
                    written[f"{s}:{db_tf}"] = _upsert_bars(
                        conn, "alpaca", s, db_tf, got.get(s, []))
            if crypto:
                pairs = [_crypto_pair(s) for s in crypto]
                got = _fetch_bars(f"{_DATA_BASE}/v1beta3/crypto/us/bars", headers,
                                  pairs, api_tf, start)
                for s in crypto:
                    written[f"{s}:{db_tf}"] = _upsert_bars(
                        conn, "alpaca", s, db_tf, got.get(_crypto_pair(s), []))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "written": written}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Backfill Alpaca historical bars into the bars table.")
    ap.add_argument("--db", default="market_ai_lab.db")
    ap.add_argument("--symbols", default="",
                    help="comma-separated; default = strategy whitelist")
    args = ap.parse_args()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
    print(json.dumps(backfill(db_path=args.db, symbols=syms)))
