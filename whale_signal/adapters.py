"""Whale data-source adapters with offline MOCK fallbacks.

Each adapter targets exactly one allowed source:
  - ApifyWhaleAdapter  -> Apify Polymarket whale-tracker actor
  - WhaleAlertAdapter  -> Whale Alert API (crypto on-chain large transfers)
  - Sec13FAdapter      -> SEC API 13F (DELAYED institutional holdings)

When the relevant API key env var is absent, the adapter returns deterministic
mock observations so the demo runs with no credentials.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


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


@dataclass
class WhaleActivity:
    source: str          # apify | whale_alert | sec_13f
    entity: str          # actor / wallet / institution
    symbol: str
    direction: str       # inflow | outflow | long | short
    value_usd: float
    delayed: bool        # True => DELAYED disclosure (e.g. 13F)
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _det(seed: str, mod: int) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16) % mod


class ApifyWhaleAdapter:
    """Apify Polymarket whale-tracker actor adapter."""

    source = "apify"

    def __init__(self, token_env: str = "APIFY_TOKEN",
                 actor: str = "apimie/polymarket-whales-trader"):
        self.token = _resolve(token_env)
        self.actor = actor

    def is_live(self) -> bool:
        return bool(self.token)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if self.is_live():
            # TODO: call Apify actor run + dataset items endpoint here.
            raise NotImplementedError("Live Apify fetch not implemented.")
        return self._mock(symbol)

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
    """Whale Alert API adapter (large on-chain crypto transfers)."""

    source = "whale_alert"

    def __init__(self, api_key_env: str = "WHALE_ALERT_API_KEY",
                 min_value_usd: float = 500_000):
        self.key = _resolve(api_key_env)
        self.min_value_usd = min_value_usd

    def is_live(self) -> bool:
        return bool(self.key)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if self.is_live():
            # TODO: call https://api.whale-alert.io/v1/transactions here.
            raise NotImplementedError("Live Whale Alert fetch not implemented.")
        return self._mock(symbol)

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
    """SEC API 13F adapter — DELAYED institutional holdings disclosure.

    13F filings are quarterly and lagged; everything from this source is flagged
    delayed=True and must be treated as context, NOT live trade flow.
    """

    source = "sec_13f"

    def __init__(self, api_key_env: str = "SEC_API_KEY"):
        self.key = _resolve(api_key_env)

    def is_live(self) -> bool:
        return bool(self.key)

    def fetch(self, symbol: str) -> list[WhaleActivity]:
        if self.is_live():
            # TODO: call https://api.sec-api.io/form-13f/holdings here.
            raise NotImplementedError("Live SEC 13F fetch not implemented.")
        return self._mock(symbol)

    def _mock(self, symbol: str) -> list[WhaleActivity]:
        # Equity-style symbols only.
        if any(c in symbol for c in ("USD", "BTC", "ETH", "-")):
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


def default_adapters() -> list:
    return [ApifyWhaleAdapter(), WhaleAlertAdapter(), Sec13FAdapter()]
