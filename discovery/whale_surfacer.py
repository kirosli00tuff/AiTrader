"""Whale activity as a Stage-A candidate-surfacing signal.

Whale data does TWO jobs, deliberately:

  1. SURFACING (here, Stage A). A strong whale signal raises an instrument's
     free pre-screen rank, so a name whales moved into can reach the finalist set
     even when its price and volume alone would not have surfaced it. This is a
     cheap ranking input. It costs no LLM tokens.
  2. EVALUATION (Stage C, unchanged). The existing Level-4 whale advisory layer
     still informs the verdict and sizing on survivors, capped at 0.35, exactly
     as before.

That is the SAME data serving two different questions, not a duplication bug.
Surfacing asks "is this worth looking at". Evaluation asks "what should we do".
An instrument surfaced by whale activity still has to survive the Haiku gate and
still gets judged by the full four levels, so whale never shortcuts anything: it
only buys a name a look.

Sources: whatever the whale layer already has active (SEC EDGAR 13F and Form 4
for equities, the crypto whale feed for crypto). This module adds no new feed and
no new credential.

Cost posture. The whale layer fetches per symbol, so ranking a 119-name universe
is a real fetch cost even though it is free of charge. Two bounds handle it:
  * A hard TTL cache. 13F lags about 45 days and Form 4 about 2 days, so the
    underlying data cannot change within an hour. Caching hard is correct here,
    not a shortcut.
  * A per-pass fetch budget. Once spent, the remaining symbols score 0 for whale
    and rank on their technicals alone, which is the pre-whale behavior.
Any failure degrades to 0 (no boost), never to a wrong number.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("discovery.whale")

# 13F is quarterly with a ~45-day lag; Form 4 lags ~2 business days. Neither can
# change inside an hour, so an hourly pass re-fetching them would buy nothing.
CACHE_TTL_SECONDS = 6 * 3600

# Max whale fetches in one pass. Bounds the load on SEC EDGAR (fair access is
# roughly 10 req/s) and keeps a pass from stalling. Symbols past this score 0 for
# whale, so they rank on technicals exactly as they did before.
DEFAULT_FETCH_BUDGET = 60

# An instrument needs at least this much whale activity before it contributes
# anything. Below it the evidence is noise, and boosting on noise would surface
# names for no reason.
MIN_ACTIVITY_SCORE = 0.35


class WhaleSurfacer:
    """Scores whale activity per symbol for the Stage-A pre-screen.

    ``scorer`` is injectable: it defaults to the existing whale layer's
    ``whale_signal_for``, and tests pass a mock. This module never opens a socket
    itself.
    """

    def __init__(self, scorer=None, *, fetch_budget: int = DEFAULT_FETCH_BUDGET,
                 ttl: float = CACHE_TTL_SECONDS) -> None:
        self._scorer = scorer
        self._cache: dict[str, tuple[float, dict]] = {}
        self._ttl = float(ttl)
        self.fetch_budget = int(fetch_budget)
        self.fetches = 0
        self.cache_hits = 0
        self.budget_skips = 0

    def _default_scorer(self, symbol: str) -> dict:
        from whale_signal import whale_signal_for
        # market_bias 0.0 on purpose: surfacing asks whether whales are ACTIVE
        # here, not whether they agree with a view we do not have yet. Passing a
        # bias would make the contradiction logic fire against nothing.
        sig, _ = whale_signal_for(symbol, market_bias=0.0)
        return sig.to_dict() if hasattr(sig, "to_dict") else {}

    def signal_for(self, symbol: str) -> dict:
        """Whale signal dict for one symbol, cached. {} when unavailable."""
        now = time.monotonic()
        hit = self._cache.get(symbol)
        if hit and now - hit[0] <= self._ttl:
            self.cache_hits += 1
            return hit[1]

        if self.fetches >= self.fetch_budget:
            self.budget_skips += 1
            return {}

        scorer = self._scorer or self._default_scorer
        try:
            sig = scorer(symbol) or {}
            self.fetches += 1
        except Exception:  # noqa: BLE001 — an advisory input must never break a pass
            log.debug("discovery: whale signal unavailable for %s", symbol)
            return {}
        if not isinstance(sig, dict):
            return {}
        self._cache[symbol] = (now, sig)
        return sig

    def reset_pass(self) -> None:
        """Clear the per-pass fetch budget. The TTL cache survives."""
        self.fetches = 0
        self.cache_hits = 0
        self.budget_skips = 0


def _f(src: dict, key: str, default: float = 0.0) -> float:
    try:
        v = src.get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def whale_component(sig: dict) -> float:
    """Score whale activity for SURFACING, in [0,1]. Pure.

    What earns a boost is ACCUMULATION with real evidence behind it:
      * activity score, how much whale evidence exists at all, and
      * |bias|, how directional it is.
    Both must be present. Loud but directionless flow is noise, and a confident
    read on no evidence is not a read.

    Accumulation surfaces harder than distribution. Surfacing asks "is this worth
    a look", and both native strategy families are long-biased in paper (equities
    are long-only and crypto shorts are off), so a name whales are dumping is
    less likely to become a tradeable candidate. Distribution still contributes,
    at half weight, because a sharp exit is information worth a look. Direction is
    decided later by the council either way, never here.

    DELAYED-only evidence (13F, ~45 days) is down-weighted, matching the existing
    Level-4 posture: slow institutional context is real, but it is not live flow.
    """
    if not sig:
        return 0.0
    activity = max(0.0, min(1.0, _f(sig, "whale_activity_score")))
    if activity < MIN_ACTIVITY_SCORE:
        return 0.0

    bias = max(-1.0, min(1.0, _f(sig, "whale_bias", _f(sig, "bias"))))
    if abs(bias) < 1e-9:
        return 0.0

    # Evidence times conviction. Neither alone is a signal.
    strength = activity * abs(bias)

    # Accumulation full weight, distribution half.
    if bias < 0:
        strength *= 0.5

    # Delayed-only evidence is context, not flow.
    if int(_f(sig, "delayed_only")) == 1:
        strength *= 0.6

    return round(max(0.0, min(1.0, strength)), 4)


def surfacing_label(sig: dict) -> str:
    """A short human reason for the GUI and the watchlist entry."""
    if not sig:
        return ""
    regime = str(sig.get("whale_regime_label", "") or "")
    delayed = int(_f(sig, "delayed_only")) == 1
    bias = _f(sig, "whale_bias", _f(sig, "bias"))
    label = regime or ("accumulation" if bias > 0 else "distribution")
    return f"whale {label}{' (delayed)' if delayed else ''}"
