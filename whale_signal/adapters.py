"""Whale data-source adapters with offline MOCK fallbacks.

SEC EDGAR is the sole ACTIVE source. Adapters:
  - Sec13FAdapter      -> SEC EDGAR 13F (free, DELAYED institutional holdings), ACTIVE
  - WhaleAlertAdapter  -> Whale Alert API (crypto on-chain, key-gated), RESERVED
ClankApp was removed on 2026-07-10: its host api.clankapp.com is confirmed
DNS-unreachable and dead. Whale Alert and Unusual Whales Pro stay reserved as
documented paid options (see default_adapters).

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


# Live network fetches are OFF by default (Task 7): the whole app runs offline on
# deterministic mocks unless an operator explicitly opts in. Crypto/on-chain
# whale feeds (Whale Alert, reserved) are gated by WHALE_LIVE_ENABLED.
# SEC EDGAR is gated separately by SEC_EDGAR_ENABLED. Both default false.
WHALE_LIVE_ENABLED_ENV = "WHALE_LIVE_ENABLED"
SEC_EDGAR_ENABLED_ENV = "SEC_EDGAR_ENABLED"

# Whale Alert is wired for a one-time TRIAL evaluation as a crypto whale feed. It
# is opt-in behind WHALE_ALERT_ENABLED (exported from whale.whale_alert_enabled in
# config, default OFF), so the system runs unchanged without it. The key is a
# RESERVED credential resolved keystore-first via WHALE_ALERT_API_KEY, never
# hardcoded, never logged.
WHALE_ALERT_ENABLED_ENV = "WHALE_ALERT_ENABLED"

# Whale Alert developer plan rate limit: 10 requests per minute. On HTTP 429 we
# retry with bounded exponential backoff, honoring a Retry-After header when the
# server sends one, then degrade cleanly to the deterministic mock.
_RATE_LIMIT_MAX_RETRIES = 2
_RATE_LIMIT_BASE_BACKOFF_S = 1.0


def _flag(name: str, default: bool = False) -> bool:
    """Read a boolean opt-in flag from the environment (default OFF)."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _user_agent() -> str:
    """Descriptive User-Agent; SEC fair-access needs a real contact.

    The contact email comes from SEC_EDGAR_CONTACT_EMAIL (env only — NEVER
    committed to YAML). When unset we send an explicit self-describing note
    instead of a fake address so the header is honest.
    """
    contact = (_resolve("SEC_EDGAR_CONTACT_EMAIL") or "").strip()
    who = f"contact {contact}" if contact else "contact: set SEC_EDGAR_CONTACT_EMAIL"
    return f"MarketAiLab/1.0 (paper-training research; {who})"


@dataclass
class WhaleActivity:
    source: str          # whale_alert | sec_13f | sec_form4
    entity: str          # actor / wallet / exchange / institution / insider
    symbol: str
    direction: str       # inflow | outflow | long | short
    value_usd: float
    delayed: bool        # True => DELAYED disclosure (e.g. 13F, Form 4)
    ts: str
    # Human-readable delay magnitude so the specific lag surfaces, not just the
    # delayed bool: ~45 days for quarterly 13F, ~2 business days for Form 4.
    delay_label: str = ""

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


# ClankApp adapter REMOVED 2026-07-10: host api.clankapp.com is confirmed
# DNS-unreachable and dead. SEC EDGAR is the sole active whale source.
# Whale Alert and Unusual Whales Pro remain reserved (see default_adapters).


class WhaleAlertAdapter:
    """Whale Alert API adapter (large on-chain crypto transfers).

    TRIAL evaluation crypto whale feed. Opt-in behind WHALE_ALERT_ENABLED (from
    whale.whale_alert_enabled in config, default OFF) plus a resolved
    WHALE_ALERT_API_KEY. When enabled and keyed it fetches recent large crypto
    transfers from the documented transactions endpoint and feeds the SAME whale
    scoring path SEC EDGAR uses, under the same 0.35 advisory cap. When the key is
    absent it reports not live and the app runs unchanged. Any network error, an
    exhausted 429 retry, a missing dependency, or a parse failure degrades to the
    deterministic mock, so nothing ever raises. This is a one-time trial, not a
    recurring free-tier scheme. The key is a RESERVED credential, never logged.
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
        # Crypto whale feed: non-crypto symbols never hit it.
        if not _is_crypto(symbol):
            return []
        # Trial feed: live requires the opt-in flag AND a resolved key.
        if not (_flag(WHALE_ALERT_ENABLED_ENV) and self.is_live()):
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
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        # Respect the 10 req/min developer limit: on a 429 retry with bounded
        # backoff (honoring Retry-After), then degrade to the mock. One request
        # per fetch keeps the steady-state call rate well under the limit.
        resp = None
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            resp = requests.get(self.BASE_URL, params=params, headers=headers,
                                timeout=_TIMEOUT)
            if getattr(resp, "status_code", None) != 429:
                break
            if attempt >= _RATE_LIMIT_MAX_RETRIES:
                return self._mock(symbol)  # rate limit persisted: degrade cleanly
            time.sleep(_retry_after_seconds(resp, attempt))
        if resp is None or getattr(resp, "status_code", None) == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        parsed = self._parse(resp.json(), symbol)
        return parsed if parsed else self._mock(symbol)

    def _parse(self, payload, symbol: str) -> list[WhaleActivity]:
        """Parse a Whale Alert transactions payload into WhaleActivity rows (pure).

        The uniform Whale Alert schema across chains: transactions[] each with
        hash, blockchain, symbol, amount, amount_usd, from/to {owner, owner_type,
        address}, and a unix timestamp. The transparent heuristic reads owner_type:
        a transfer TO an exchange is an inflow (selling pressure), a transfer FROM
        an exchange is an outflow (accumulation). Extracted so fixtures exercise
        parsing with NO network call. Every row is delayed=False (near real time).
        """
        rows = payload.get("transactions") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        token = _token_of(symbol)
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
        # SEC EDGAR live is OFF unless the operator opts in (SEC_EDGAR_ENABLED).
        if not _flag(SEC_EDGAR_ENABLED_ENV):
            return self._mock(symbol)
        try:
            return self._fetch_live(symbol)
        except Exception:
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        # A proper, identifying User-Agent is mandatory for EDGAR fair-access;
        # the contact email comes from SEC_EDGAR_CONTACT_EMAIL (env, never YAML).
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        params = {"q": symbol, "forms": "13F-HR"}
        resp = requests.get(self.EDGAR_FTS_URL, params=params, headers=headers,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        parsed = self._parse(resp.json(), symbol)
        return parsed if parsed else self._mock(symbol)

    def _parse(self, payload, symbol: str) -> list[WhaleActivity]:
        """Parse an EDGAR full-text-search payload into WhaleActivity rows (pure).

        Extracted so fixtures exercise parsing without a live call. All 13F
        evidence is delayed=True (quarterly, ~45-day lag) — context, not flow.
        """
        hits = (((payload or {}).get("hits") or {}).get("hits")
                if isinstance(payload, dict) else None)
        if not isinstance(hits, list) or not hits:
            return []
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
                delay_label=SEC_13F_DELAY_LABEL,
            ))
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
                delay_label=SEC_13F_DELAY_LABEL,
            ))
        return out


# Delay-magnitude labels (surfaced on every SEC row so the lag is explicit).
SEC_13F_DELAY_LABEL = "~45 day lag (quarterly 13F)"
SEC_FORM4_DELAY_LABEL = "~2 business day lag (Form 4 insider)"


class SecForm4Adapter:
    """SEC EDGAR Form 4 (insider transactions) adapter.

    Officers, directors, and 10% owners must file Form 4 within two business
    days of a transaction, so it is much fresher than a quarterly 13F but still
    DELAYED, near-real-time context, not a live feed. Uses the same free,
    keyless EDGAR full-text search (efts.sec.gov) with a descriptive User-Agent.
    Every row is delayed=True with the ~2-business-day label. Equities only.
    """

    source = "sec_form4"
    EDGAR_FTS_URL = "https://efts.sec.gov/LATEST/search-index"

    def is_live(self) -> bool:
        return True  # EDGAR is keyless and always available

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if any(c in symbol.upper() for c in ("USD", "BTC", "ETH", "-")):
            return []                              # equities only
        if not _flag(SEC_EDGAR_ENABLED_ENV):
            return self._mock(symbol)
        try:
            return self._fetch_live(symbol)
        except Exception:
            return self._mock(symbol)

    def _fetch_live(self, symbol: str) -> list[WhaleActivity]:
        requests = _requests()
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        params = {"q": symbol, "forms": "4"}
        resp = requests.get(self.EDGAR_FTS_URL, params=params, headers=headers,
                            timeout=_TIMEOUT)
        if resp.status_code == 429:
            return self._mock(symbol)
        resp.raise_for_status()
        parsed = self._parse(resp.json(), symbol)
        return parsed if parsed else self._mock(symbol)

    def _parse(self, payload, symbol: str) -> list[WhaleActivity]:
        """Parse an EDGAR full-text-search Form 4 payload into rows (pure).

        Extracted so fixtures exercise parsing without a live call. Direction is
        long (the insider filing side; FTS does not expose acquire/dispose
        reliably), value 0 (not in FTS), and every row is delayed=True with the
        ~2-business-day Form 4 label.
        """
        hits = (((payload or {}).get("hits") or {}).get("hits")
                if isinstance(payload, dict) else None)
        if not isinstance(hits, list) or not hits:
            return []
        out: list[WhaleActivity] = []
        for hit in hits[:8]:
            if not isinstance(hit, dict):
                continue
            src = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
            names = src.get("display_names")
            entity = (names[0] if isinstance(names, list) and names
                      else src.get("entity") or "Insider")
            entity = str(entity).split("(CIK")[0].strip() or "Insider"
            file_date = src.get("file_date") or src.get("filed")
            ts = (f"{file_date}T00:00:00Z" if file_date else _now())
            out.append(WhaleActivity(
                source=self.source,
                entity=entity,
                symbol=symbol,
                direction="long",   # insider filing side (FTS has no dispose flag)
                value_usd=0.0,       # not exposed by full-text search
                delayed=True,        # DELAYED ~2 business days
                ts=ts,
                delay_label=SEC_FORM4_DELAY_LABEL,
            ))
        return out

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        if any(c in symbol.upper() for c in ("USD", "BTC", "ETH", "-")):
            return []
        insiders = ["CEO", "CFO", "Director", "10% Owner"]
        seed = f"form4{symbol}"
        return [WhaleActivity(
            source=self.source,
            entity=insiders[_det("ins" + seed, len(insiders))],
            symbol=symbol,
            direction="long" if _det(seed, 2) else "short",
            value_usd=0.0,
            delayed=True,
            ts=_now(),
            delay_label=SEC_FORM4_DELAY_LABEL,
        )]


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


def _token_of(symbol: str) -> str:
    """Base token of a trading symbol, for matching Whale Alert's `symbol` field.

    BTC/USD -> BTC, ETH-USD -> ETH, USDT/USD -> USDT, BTCUSD -> BTC. A pair keeps
    its base (the part before the separator); a bare symbol drops a trailing
    stablecoin/USD quote.
    """
    s = symbol.upper()
    for sep in ("/", "-"):
        if sep in s:
            return s.split(sep)[0]
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote) and s != quote:
            return s[: -len(quote)]
    return s


def _retry_after_seconds(resp, attempt: int) -> float:
    """Backoff for a 429: honor a numeric Retry-After header, else exponential.

    Bounded and safe: a malformed or missing header falls back to
    _RATE_LIMIT_BASE_BACKOFF_S * 2**attempt, capped so a retry never stalls the
    loop. Never raises.
    """
    try:
        headers = getattr(resp, "headers", {}) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            return max(0.0, min(float(raw), 5.0))
    except (TypeError, ValueError):
        pass
    return min(_RATE_LIMIT_BASE_BACKOFF_S * (2 ** attempt), 5.0)


# --- Reserved integrations (NOT in the active default chain) ----------------
# SEC EDGAR is the sole ACTIVE whale source (see default_adapters below). The
# following stay wired and importable but are OFF the default chain, following
# one reserved-integration pattern:
#   - ClankApp REMOVED 2026-07-10 (host api.clankapp.com dead, DNS-unreachable).
#   - WhaleAlertAdapter  reserved optional crypto/on-chain feed (key-gated).
#   - Unusual Whales Pro RESERVED real-time PAID upgrade for richer EQUITIES
#     smart-money data (options flow, dark pool, congressional, insider, and
#     13F), at roughly 48 dollars per month. No adapter is wired. Only the
#     UNUSUAL_WHALES_API_KEY env var is reserved (unset), pending an operator
#     decision.


def default_adapters() -> list:
    """The ACTIVE whale source chain.

    SEC EDGAR 13F is the sole active whale source: free, keyless, and DELAYED
    institutional context (quarterly, ~45-day lag). The reserved crypto adapter
    (Whale Alert) and the reserved Unusual Whales Pro paid upgrade are
    OPTIONAL and NOT in this chain. Add a crypto or paid adapter explicitly only
    if an operator opts in. Every adapter keeps its deterministic mock fallback,
    so this runs offline with no keys.

    Two SEC EDGAR forms are active: quarterly 13F (institutional holdings, ~45
    day lag) and Form 4 (insider transactions, ~2 business day lag). Both are
    free, keyless, and DELAYED context, gated by SEC_EDGAR_ENABLED.

    Whale Alert joins the chain ONLY for the opt-in crypto trial: when
    WHALE_ALERT_ENABLED is on AND the key resolves. Enabled without a key, or
    disabled, leaves the chain exactly as before (SEC EDGAR only), so the default
    behavior is unchanged and no crypto whale mock is injected.
    """
    adapters = [Sec13FAdapter(), SecForm4Adapter()]
    if _flag(WHALE_ALERT_ENABLED_ENV):
        wa = WhaleAlertAdapter()
        if wa.is_live():  # trial feed active only with a resolved key
            adapters.append(wa)
    return adapters
