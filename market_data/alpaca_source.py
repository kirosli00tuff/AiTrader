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

import json
import os
import sys
import urllib.error
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
    """Data-API key/secret: dedicated ALPACA_DATA_* else paper creds."""
    key = (os.environ.get("ALPACA_DATA_API_KEY")
           or _resolve("alpaca_paper_key", ("ALPACA_API_KEY",)))
    secret = (os.environ.get("ALPACA_DATA_API_SECRET")
              or _resolve("alpaca_paper_secret", ("ALPACA_API_SECRET",)))
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
