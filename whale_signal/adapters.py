"""Whale data-source adapters with offline MOCK fallbacks.

Each adapter targets exactly one allowed source:
  - ClankAppAdapter    -> ClankApp free crypto/on-chain whale API (DEFAULT)
  - ApifyWhaleAdapter  -> Apify Polymarket whale-tracker actor
  - WhaleAlertAdapter  -> Whale Alert API (crypto on-chain large transfers, key-gated)
  - Sec13FAdapter      -> SEC EDGAR 13F (free, DELAYED institutional holdings)

Live fetches use `requests` with short timeouts and a descriptive User-Agent.
Any network error, HTTP 429 (rate limit), missing dependency, or parse failure
falls back to deterministic mock observations, so the app never crashes offline
and runs with no credentials. These signals are ADVISORY research data for
paper/model-training only — never live order flow.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# Network defaults shared by every live fetch.
_TIMEOUT = 10  # seconds
_USER_AGENT = "MarketAiLab/1.0 (paper-training research; contact admin@marketailab.local)"


def _resolve(env_name: str) -> str | None:
    """Resolve a credential via the shared in-app-then-env resolver.

    Falls back to a raw env lookup if the credential module is unavailable, so
    offline/mock behavior is preserved no matter what.
    """
    try:
        from account_manager.credentials import resolve_env
        return resolve_env(env_name)
    except Exception:
        return os.environ.get(env_name)


def _requests():
    """Lazy-import requests so a missing dependency still mock-falls-back."""
    import requests  # noqa: PLC0415
    return requests


@dataclass
class WhaleActivity:
    source: str          # clankapp | apify | whale_alert | sec_13f
    entity: str          # actor / wallet / exchange / institution
    symbol: str
    direction: str       # inflow | outflow | long | short
    value_usd: float
    delayed: bool        # True => DELAYED disclosure (e.g. 13F)
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_from_epoch(value) -> str:
    """Best-effort convert a unix timestamp (s) to our ISO format."""
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return _now()


def _det(seed: str, mod: int) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16) % mod


def _is_crypto(symbol: str) -> bool:
    s = symbol.upper()
    return any(tok in s for tok in ("USD", "BTC", "ETH", "USDT", "USDC", "-"))


class ClankAppAdapter:
    """ClankApp free crypto/on-chain whale API adapter (DEFAULT source).

    ClankApp is fully free (email-signup key, ~10 calls/min, ~21 chains). An API
    key is OPTIONAL — without one the adapter returns deterministic mock data.
    Endpoint + response shape are parsed defensively; any parse failure falls
    back to mock.
    """

    source = "clankapp"
    BASE_URL = "https://api.clankapp.com/v2/explorer/tx"

    def __init__(self, api_key_env: str = "CLANKAPP_API_KEY",
                 min_value_usd: float = 500_000):
        self.key = _resolve(api_key_env)
        self.min_value_usd = min_value_usd

    def is_live(self) -> bool:
        return bool(self.key)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        # ClankApp covers crypto/on-chain only.
        if not _is_crypto(symbol):
            return []
        if not self.is_live():
            return self._mock(symbol)
        try:
            return self._fetch_live(symbol)
        except Exception:
            # Network down / parse failure / missing dep -> never crash.
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        # Token portion before the quote currency (e.g. BTC-USD -> btc).
        token = symbol.upper().replace("-", "").replace("USDT", "").replace(
            "USDC", "").replace("USD", "").lower() or symbol.lower()
        params = {"symbol": token, "size": 25}
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        if self.key:
            headers["x-api-key"] = self.key
        resp = requests.get(self.BASE_URL, params=params, headers=headers,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:  # rate-limited this cycle -> mock
            return self._mock(symbol)
        resp.raise_for_status()
        payload = resp.json()
        # Response shape is defensively probed: list under common keys.
        rows = payload
        if isinstance(payload, dict):
            for key in ("transactions", "data", "result", "txs", "items"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        if not isinstance(rows, list):
            return self._mock(symbol)
        out: list[WhaleActivity] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = _num(row.get("amount_usd"), row.get("value_usd"),
                        row.get("usd"), row.get("amount"))
            if value is None or value < self.min_value_usd:
                continue
            frm = row.get("from") if isinstance(row.get("from"), dict) else {}
            to = row.get("to") if isinstance(row.get("to"), dict) else {}
            to_type = str(to.get("owner_type", "")).lower()
            frm_type = str(frm.get("owner_type", "")).lower()
            # Deposit to an exchange = inflow (distribution); withdrawal = outflow.
            if to_type == "exchange":
                direction = "inflow"
                entity = to.get("owner") or to.get("address") or "exchange"
            elif frm_type == "exchange":
                direction = "outflow"
                entity = frm.get("owner") or frm.get("address") or "exchange"
            else:
                direction = "inflow" if _det(str(row.get("hash", value)), 2) else "outflow"
                entity = (to.get("owner") or frm.get("owner")
                          or to.get("address") or frm.get("address") or "wallet")
            ts = row.get("timestamp") or row.get("ts")
            out.append(WhaleActivity(
                source=self.source,
                entity=str(entity),
                symbol=symbol,
                direction=direction,
                value_usd=float(value),
                delayed=False,
                ts=_ts_from_epoch(ts) if ts is not None else _now(),
            ))
        if not out:
            return self._mock(symbol)
        return out

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        if not _is_crypto(symbol):
            return []
        out = []
        n = 1 + _det("clank_n" + symbol, 3)
        for i in range(n):
            seed = f"clank{symbol}{i}"
            direction = "inflow" if _det(seed, 2) else "outflow"
            value = float(self.min_value_usd + _det("v" + seed, 8_000_000))
            entity = ("binance" if _det("ex" + seed, 2)
                      else f"wallet_{_det('w' + seed, 9999):04d}")
            out.append(WhaleActivity(
                source=self.source,
                entity=entity,
                symbol=symbol,
                direction=direction,
                value_usd=value,
                delayed=False,
                ts=_now(),
            ))
        return out


class ApifyWhaleAdapter:
    """Apify Polymarket whale-tracker actor adapter."""

    source = "apify"
    BASE_URL = "https://api.apify.com/v2/acts"

    def __init__(self, token_env: str = "APIFY_TOKEN",
                 actor: str = "apimie/polymarket-whales-trader"):
        self.token = _resolve(token_env)
        self.actor = actor

    def is_live(self) -> bool:
        return bool(self.token)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if not self.is_live():
            return self._mock(symbol)
        try:
            return self._fetch_live(symbol)
        except Exception:
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        # Read the actor's last run dataset items (no new run triggered).
        actor_path = self.actor.replace("/", "~")
        url = f"{self.BASE_URL}/{actor_path}/runs/last/dataset/items"
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        resp = requests.get(url, params={"token": self.token, "limit": 50},
                            headers=headers, timeout=_TIMEOUT)
        if resp.status_code == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            return self._mock(symbol)
        out: list[WhaleActivity] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_sym = str(row.get("market") or row.get("symbol") or symbol)
            value = _num(row.get("size_usd"), row.get("value_usd"),
                        row.get("usd"), row.get("amount"), row.get("size"))
            if value is None:
                continue
            side = str(row.get("side") or row.get("outcome") or "").lower()
            direction = "long" if side in ("buy", "yes", "long") else "short"
            entity = (row.get("trader") or row.get("user") or row.get("wallet")
                      or "poly_whale")
            ts = row.get("timestamp") or row.get("ts")
            out.append(WhaleActivity(
                source=self.source,
                entity=str(entity),
                symbol=row_sym,
                direction=direction,
                value_usd=float(value),
                delayed=False,
                ts=_ts_from_epoch(ts) if isinstance(ts, (int, float)) else (str(ts) if ts else _now()),
            ))
        if not out:
            return self._mock(symbol)
        return out

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        out = []
        n = 1 + _det("apify_n" + symbol, 3)
        for i in range(n):
            seed = f"apify{symbol}{i}"
            direction = "long" if _det(seed, 2) else "short"
            out.append(WhaleActivity(
                source=self.source,
                entity=f"poly_whale_{_det('e' + seed, 50):02d}",
                symbol=symbol,
                direction=direction,
                value_usd=float(50_000 + _det("v" + seed, 950_000)),
                delayed=False,
                ts=_now(),
            ))
        return out


class WhaleAlertAdapter:
    """Whale Alert API adapter (large on-chain crypto transfers).

    OPTIONAL key-gated alternative to ClankApp. Its free tier is limited; the
    app works fine with NO Whale Alert key (ClankApp + mock cover the default).
    """

    source = "whale_alert"
    BASE_URL = "https://api.whale-alert.io/v1/transactions"

    def __init__(self, api_key_env: str = "WHALE_ALERT_API_KEY",
                 min_value_usd: float = 500_000):
        self.key = _resolve(api_key_env)
        self.min_value_usd = min_value_usd

    def is_live(self) -> bool:
        return bool(self.key)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if not self.is_live():
            return self._mock(symbol)
        try:
            return self._fetch_live(symbol)
        except Exception:
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        import time
        params = {
            "api_key": self.key,
            "min_value": int(self.min_value_usd),
            "start": int(time.time()) - 3600,  # last hour
            "limit": 50,
        }
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        resp = requests.get(self.BASE_URL, params=params, headers=headers,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("transactions") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return self._mock(symbol)
        token = symbol.upper().replace("-", "").replace("USDT", "").replace(
            "USDC", "").replace("USD", "")
        out: list[WhaleActivity] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol", "")).upper()
            if token and sym and token not in sym and sym not in token:
                continue
            value = _num(row.get("amount_usd"), row.get("value_usd"))
            if value is None or value < self.min_value_usd:
                continue
            frm = row.get("from") if isinstance(row.get("from"), dict) else {}
            to = row.get("to") if isinstance(row.get("to"), dict) else {}
            to_type = str(to.get("owner_type", "")).lower()
            frm_type = str(frm.get("owner_type", "")).lower()
            if to_type == "exchange":
                direction, entity = "inflow", (to.get("owner") or "exchange")
            elif frm_type == "exchange":
                direction, entity = "outflow", (frm.get("owner") or "exchange")
            else:
                direction = "inflow" if _det(str(row.get("hash", value)), 2) else "outflow"
                entity = to.get("owner") or frm.get("owner") or "wallet"
            ts = row.get("timestamp")
            out.append(WhaleActivity(
                source=self.source,
                entity=str(entity),
                symbol=symbol,
                direction=direction,
                value_usd=float(value),
                delayed=False,
                ts=_ts_from_epoch(ts) if ts is not None else _now(),
            ))
        if not out:
            return self._mock(symbol)
        return out

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        # Crypto-only source; non-crypto symbols yield nothing.
        if "USD" not in symbol and "BTC" not in symbol and "ETH" not in symbol:
            return []
        out = []
        n = 1 + _det("wa_n" + symbol, 3)
        for i in range(n):
            seed = f"wa{symbol}{i}"
            direction = "inflow" if _det(seed, 2) else "outflow"
            value = float(self.min_value_usd + _det("v" + seed, 5_000_000))
            out.append(WhaleActivity(
                source=self.source,
                entity=f"wallet_{_det('w' + seed, 9999):04d}",
                symbol=symbol,
                direction=direction,
                value_usd=value,
                delayed=False,
                ts=_now(),
            ))
        return out


class Sec13FAdapter:
    """SEC EDGAR 13F adapter — FREE, DELAYED institutional holdings disclosure.

    Uses the official free SEC EDGAR full-text search REST API at
    efts.sec.gov (NO API key; fair-access requires only a descriptive
    `User-Agent: AppName contact-email` header). 13F filings are quarterly and
    lagged; everything from this source is flagged delayed=True and must be
    treated as context, NOT live trade flow. SEC_API_KEY is an OPTIONAL override
    only — the default path needs no key.
    """

    source = "sec_13f"
    EDGAR_FTS_URL = "https://efts.sec.gov/LATEST/search-index"

    def __init__(self, api_key_env: str = "SEC_API_KEY"):
        # Optional override only; default path needs NO key.
        self.key = _resolve(api_key_env)

    def is_live(self) -> bool:
        # EDGAR is keyless and always available -> always attempt live.
        return True

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        # Equity-style symbols only.
        if any(c in symbol.upper() for c in ("USD", "BTC", "ETH", "-")):
            return []
        try:
            return self._fetch_live(symbol)
        except Exception:
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        # A proper, identifying User-Agent is mandatory for EDGAR fair-access.
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        params = {"q": symbol, "forms": "13F-HR"}
        resp = requests.get(self.EDGAR_FTS_URL, params=params, headers=headers,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        payload = resp.json()
        hits = (((payload or {}).get("hits") or {}).get("hits")
                if isinstance(payload, dict) else None)
        if not isinstance(hits, list) or not hits:
            return self._mock(symbol)
        out: list[WhaleActivity] = []
        for hit in hits[:8]:
            if not isinstance(hit, dict):
                continue
            src = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
            names = src.get("display_names")
            entity = (names[0] if isinstance(names, list) and names
                      else src.get("entity") or "Institution")
            # Strip trailing "(CIK ...)" noise from display name.
            entity = str(entity).split("(CIK")[0].strip() or "Institution"
            file_date = src.get("file_date") or src.get("filed")
            ts = (f"{file_date}T00:00:00Z" if file_date else _now())
            out.append(WhaleActivity(
                source=self.source,
                entity=entity,
                symbol=symbol,
                direction="long",  # 13F discloses long holdings
                value_usd=0.0,      # full-text search exposes no position value
                delayed=True,       # DELAYED quarterly disclosure
                ts=ts,
            ))
        if not out:
            return self._mock(symbol)
        return out

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        # Equity-style symbols only.
        if any(c in symbol.upper() for c in ("USD", "BTC", "ETH", "-")):
            return []
        institutions = ["Berkshire", "Bridgewater", "Renaissance", "Citadel"]
        out = []
        n = 1 + _det("sec_n" + symbol, 2)
        for i in range(n):
            seed = f"sec{symbol}{i}"
            direction = "long" if _det(seed, 2) else "short"
            out.append(WhaleActivity(
                source=self.source,
                entity=institutions[_det("inst" + seed, len(institutions))],
                symbol=symbol,
                direction=direction,
                value_usd=float(10_000_000 + _det("v" + seed, 90_000_000)),
                delayed=True,  # DELAYED disclosure
                ts=_now(),
            ))
        return out


def _num(*candidates):
    """Return the first candidate coercible to a float, else None."""
    for c in candidates:
        if c is None:
            continue
        try:
            return float(c)
        except (TypeError, ValueError):
            continue
    return None


def default_adapters() -> list:
    """Free-first default chain.

    ClankApp (free, keyless-capable crypto) is the primary whale source; Apify
    and the free EDGAR 13F adapter round out coverage. Whale Alert stays
    available as an OPTIONAL key-gated alternative but is not in the default
    chain (its free tier is limited) — add it explicitly if a key is present.
    """
    return [ClankAppAdapter(), ApifyWhaleAdapter(), Sec13FAdapter()]
