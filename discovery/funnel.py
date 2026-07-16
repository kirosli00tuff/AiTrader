"""The discovery funnel: cheap to expensive, narrowing at every stage.

The whole design exists to bound cost. Intelligence is spent only at the bottom:

  Stage A  free pre-screen   whole universe -> ~10-15 finalists   0 LLM tokens
  Stage B  Haiku gate        finalists      -> ~3-6 survivors      1 cheap call each
  Stage C  four-level eval   survivors      -> verdicts            full council, a handful

Stage A ranks on Finnhub quant data (price, volume, volatility, momentum, gap),
Finnhub's PRE-COMPUTED news sentiment, and the native technical signal the engine
already computes. It spends nothing, so it can afford to look at everything.
Stage B pays fractions of a cent per finalist. Only Stage C pays for a full
council, and only for the few names that earned it.

Every stage is bounded by a hard config ceiling (max_finalists, max_survivors,
max_council_calls_per_pass) AND by a daily discovery council budget that is
SEPARATE from and ADDITIVE to the trading council budget, so a discovery pass can
never eat the quant loop's calls. Every drop is recorded with its stage and
reason, so the operator can see exactly why an instrument fell out.

This module is pure orchestration over injected providers. It opens no sockets
itself, which is what lets the tests drive the whole funnel with mocks and prove
Stage A spends no tokens.

NOT here: live news interpretation. Finnhub sentiment is a cheap precomputed
number, not an LLM reading a headline. The react layer is deferred (CONTEXT.md).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from discovery import settings, universe

log = logging.getLogger("discovery.funnel")

STAGE_A = "A"
STAGE_B = "B"
STAGE_C = "C"


@dataclass(frozen=True)
class Drop:
    """One instrument leaving the funnel, with the stage and why."""
    symbol: str
    stage: str
    reason: str
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "stage": self.stage,
                "reason": self.reason, "score": round(self.score, 4)}


@dataclass(frozen=True)
class Finalist:
    """A Stage-A survivor plus the free signals that ranked it."""
    symbol: str
    score: float
    signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "score": round(self.score, 4),
                "signals": self.signals}


@dataclass
class PassResult:
    """One complete discovery pass over one asset class."""
    ts: str
    asset_class: str
    universe_count: int = 0
    finalists: list[Finalist] = field(default_factory=list)
    survivors: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    drops: list[Drop] = field(default_factory=list)
    council_calls: int = 0
    gate_calls: int = 0
    est_cost_usd: float = 0.0
    budget_remaining: int = 0
    status: str = "ok"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "asset_class": self.asset_class,
            "universe_count": self.universe_count,
            "finalists_count": len(self.finalists),
            "survivors_count": len(self.survivors),
            "evaluated_count": len(self.candidates),
            "finalists": [f.to_dict() for f in self.finalists],
            "survivors": list(self.survivors),
            "candidates": list(self.candidates),
            "drops": [d.to_dict() for d in self.drops],
            "council_calls": self.council_calls,
            "gate_calls": self.gate_calls,
            "est_cost_usd": round(self.est_cost_usd, 4),
            "budget_remaining": self.budget_remaining,
            "status": self.status,
            "reason": self.reason,
        }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --- Stage A: free pre-screen ----------------------------------------------
# Pure scoring over a snapshot dict. No network, no tokens. Each component is
# normalized to [0,1] and weighted, so one loud component cannot dominate.

# Component weights. Momentum and volatility carry the most because the native
# strategies key off them. Sentiment is a tiebreaker, not a thesis.
_W_MOMENTUM = 0.30
_W_VOLATILITY = 0.25
_W_GAP = 0.15
_W_SENTIMENT = 0.15
_W_NATIVE = 0.15

# Normalization scales: the move size at which a component saturates to 1.0.
_MOMENTUM_FULL_PCT = 5.0     # a 5% daily move is a strong signal
_VOLATILITY_FULL = 0.06      # 6% intraday range saturates
_GAP_FULL_PCT = 3.0          # a 3% gap saturates


def prescreen_score(snap: dict) -> tuple[float, dict]:
    """Score one instrument on free data. Returns (score, component breakdown).

    A snapshot needs at minimum a positive ``price``. A missing component scores
    0 rather than blocking, so a name with partial data still ranks on what is
    known. Score is in [0,1].
    """
    try:
        price = float(snap.get("price") or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0.0:
        return 0.0, {"reason": "no price"}

    def _f(key: str) -> float:
        try:
            return float(snap.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # Momentum: absolute daily change. Direction is the council's job, Stage A
    # only asks whether anything is happening here at all.
    momentum = _clamp01(abs(_f("change_pct")) / _MOMENTUM_FULL_PCT)

    # Volatility: intraday range as a fraction of price. Both strategies need
    # movement to have an edge, so a dead-flat name is not worth a token.
    high, low = _f("high"), _f("low")
    volatility = (_clamp01(((high - low) / price) / _VOLATILITY_FULL)
                  if high > low else 0.0)

    # Gap: overnight jump versus the previous close. A real catalyst leaves a gap.
    prev_close, open_px = _f("prev_close"), _f("open")
    gap = 0.0
    if prev_close > 0 and open_px > 0:
        gap = _clamp01(abs((open_px - prev_close) / prev_close) * 100.0
                       / _GAP_FULL_PCT)

    # Sentiment: Finnhub's precomputed companyNewsScore, [0,1] with 0.5 neutral.
    # Score its DEVIATION from neutral: strongly bearish news is as interesting
    # as strongly bullish. Absent sentiment (crypto, or no coverage) scores 0.
    sentiment = 0.0
    if snap.get("sentiment_score") is not None:
        sentiment = _clamp01(abs(_f("sentiment_score") - 0.5) * 2.0)

    # Native technical strength from the engine's own strategy layer, [0,1].
    native = _clamp01(_f("native_strength"))

    score = (_W_MOMENTUM * momentum + _W_VOLATILITY * volatility +
             _W_GAP * gap + _W_SENTIMENT * sentiment + _W_NATIVE * native)
    components = {
        "momentum": round(momentum, 4),
        "volatility": round(volatility, 4),
        "gap": round(gap, 4),
        "sentiment": round(sentiment, 4),
        "native": round(native, 4),
    }
    return round(_clamp01(score), 4), components


def prescreen(snapshots: list[dict], max_finalists: int,
              min_score: float) -> tuple[list[Finalist], list[Drop]]:
    """Stage A. Rank the universe for free, keep the top ``max_finalists``.

    Two drop reasons, both explicit:
      * below_min_score  too quiet to be worth even a cent
      * not_top_ranked   cleared the floor but lost the ranking
    Spends NO LLM tokens by construction: this function takes no gate and no
    council, so it cannot call one.
    """
    scored: list[tuple[float, Finalist]] = []
    drops: list[Drop] = []
    for snap in snapshots:
        symbol = str(snap.get("symbol", ""))
        if not symbol:
            continue
        score, components = prescreen_score(snap)
        if score < min_score:
            drops.append(Drop(symbol, STAGE_A, "below_min_score", score))
            continue
        scored.append((score, Finalist(symbol, score, components)))

    # Highest score first, symbol as a stable tiebreaker so a pass is reproducible.
    scored.sort(key=lambda t: (-t[0], t[1].symbol))
    limit = max(0, max_finalists)
    keep = [f for _, f in scored[:limit]]
    for _, f in scored[limit:]:
        drops.append(Drop(f.symbol, STAGE_A, "not_top_ranked", f.score))
    return keep, drops


# --- Stage B: Haiku gate on finalists only ----------------------------------

def gate_finalists(finalists: list[Finalist], gate,
                   max_survivors: int) -> tuple[list[str], list[Drop], int]:
    """Stage B. Screen the finalists down to the few worth a full council.

    ``gate`` is any object with ``should_review(state) -> GateDecision`` (the
    existing Haiku base-check gate, or a mock). It runs ONLY on finalists, never
    on the universe, which is the whole point of Stage A running first.

    Fail-open on a gate error matches the council's posture: a flaky cheap gate
    must never silently suppress a real candidate. The hard ``max_survivors``
    ceiling still bounds cost, so fail-open cannot blow the budget.
    """
    survivors: list[str] = []
    drops: list[Drop] = []
    calls = 0
    for f in finalists:
        if len(survivors) >= max(0, max_survivors):
            drops.append(Drop(f.symbol, STAGE_B, "survivor_ceiling_reached",
                              f.score))
            continue
        state = {"symbol": f.symbol, "score": f.score, "mode": "discovery",
                 **f.signals}
        try:
            decision = gate.should_review(state)
            calls += 1
        except Exception:  # noqa: BLE001 — a broken gate must not break a pass
            log.debug("discovery: gate error on %s, failing open", f.symbol)
            survivors.append(f.symbol)
            continue
        if getattr(decision, "proceed", True):
            survivors.append(f.symbol)
        else:
            reason = getattr(decision, "reason", "") or "gate_rejected"
            drops.append(Drop(f.symbol, STAGE_B, f"gate: {reason}"[:200], f.score))
    return survivors, drops, calls


# --- Stage C: four-level evaluation on survivors only ------------------------

def evaluate_survivors(survivors: list[str], evaluator, *,
                       max_council_calls: int, budget_remaining: int,
                       finalist_scores: dict[str, float] | None = None,
                       ) -> tuple[list[dict], list[Drop], int]:
    """Stage C. Full four-level evaluation, the only stage that spends council.

    ``evaluator`` is a callable(symbol) -> verdict dict carrying at least
    ``direction`` and ``conviction``. The C++ engine supplies the real one via
    the bridge (council + DNN advisory + whale), tests supply a mock.

    Two hard ceilings bound the spend, whichever binds first:
      * max_council_calls   the per-pass ceiling
      * budget_remaining    what is left of the SEPARATE daily discovery budget
    A survivor past either ceiling is dropped with that reason, never evaluated.
    """
    finalist_scores = finalist_scores or {}
    candidates: list[dict] = []
    drops: list[Drop] = []
    calls = 0
    allowed = max(0, min(max_council_calls, budget_remaining))
    for symbol in survivors:
        score = finalist_scores.get(symbol, 0.0)
        if calls >= allowed:
            # Name the ceiling that actually bound, so the drop reason is true.
            reason = ("daily_budget_exhausted" if budget_remaining <= max_council_calls
                      else "pass_council_ceiling")
            drops.append(Drop(symbol, STAGE_C, reason, score))
            continue
        try:
            verdict = evaluator(symbol)
            calls += 1
        except Exception:  # noqa: BLE001 — one bad evaluation must not kill a pass
            log.debug("discovery: evaluator error on %s", symbol)
            drops.append(Drop(symbol, STAGE_C, "evaluator_error", score))
            continue
        if not isinstance(verdict, dict) or not verdict:
            drops.append(Drop(symbol, STAGE_C, "no_verdict", score))
            continue
        verdict = dict(verdict)
        verdict.setdefault("symbol", symbol)
        verdict.setdefault("prescreen_score", score)
        candidates.append(verdict)
    return candidates, drops, calls


# --- Sleeve routing ---------------------------------------------------------

def sleeve_target_for(verdict: dict, cfg_path: str | None = None) -> str:
    """Which sleeve a Stage-C verdict feeds.

    The four levels drive BOTH sleeves. The difference is the HORIZON, not the
    machinery: a long-horizon high-conviction thesis is a research_satellite
    candidate, everything else is quant_core. This only ROUTES. It can never
    size or open anything: the engine applies the hard satellite cap and the
    RiskGate regardless of what lands here.
    """
    from llm_consensus.config_access import research_conviction_threshold

    if not settings.long_term_sleeve_enabled(cfg_path):
        return "quant_core"
    horizon = str(verdict.get("horizon", "")).lower()
    try:
        conviction = float(verdict.get("conviction") or 0.0)
    except (TypeError, ValueError):
        conviction = 0.0
    long_horizon = horizon in ("weeks", "months", "weeks_to_months", "quarters")
    if long_horizon and conviction >= research_conviction_threshold(cfg_path):
        return "research_satellite"
    return "quant_core"


# --- Full pass --------------------------------------------------------------

def build_snapshots(symbols: list[str], client, *,
                    native_strength: dict[str, float] | None = None,
                    with_sentiment: bool = True) -> list[dict]:
    """Assemble Stage-A snapshots from free Finnhub data plus native technicals.

    Costs no LLM tokens. A symbol with no resolvable quote is skipped: no price
    means no score. Sentiment is fetched only for equities (Finnhub does not
    cover crypto news sentiment) and only when asked, since it is one extra REST
    call per name against the 60/min ceiling.
    """
    from discovery.finnhub_source import parse_news_sentiment, parse_quote

    native_strength = native_strength or {}
    out: list[dict] = []
    for symbol in symbols:
        quote = parse_quote(client.quote(symbol))
        if not quote:
            continue
        snap: dict = {"symbol": symbol, **quote,
                      "native_strength": native_strength.get(symbol, 0.0)}
        if with_sentiment and not universe.is_crypto(symbol):
            sentiment = parse_news_sentiment(client.news_sentiment(symbol))
            if sentiment:
                snap["sentiment_score"] = sentiment.get("score")
                snap["buzz"] = sentiment.get("buzz")
        out.append(snap)
    return out


def run_pass(asset_class: str, *, snapshots: list[dict], gate, evaluator,
             calls_used_today: int = 0, cfg_path: str | None = None,
             ts: str | None = None) -> PassResult:
    """Run one full funnel pass over one asset class.

    Takes prepared snapshots, so the fetching stays the caller's business and
    this stays pure orchestration. Returns a PassResult the engine persists:
    per-stage counts, every drop with its reason, and the cost.

    Cost accounting is honest: only Stage-C council calls count against the
    discovery budget and the estimated spend. Haiku gate calls are counted
    separately (gate_calls) because they cost a fraction of a cent, the same way
    the trading council accounts for its own gate.
    """
    ts = ts or _utcnow_iso()
    result = PassResult(ts=ts, asset_class=asset_class,
                        universe_count=len(snapshots))

    daily_budget = settings.discovery_daily_council_budget(cfg_path)
    remaining = max(0, daily_budget - max(0, calls_used_today))
    result.budget_remaining = remaining

    # Stage A: free. No gate and no council are in scope here, so no token can
    # be spent even by accident.
    finalists, drops_a = prescreen(snapshots,
                                   settings.max_finalists(cfg_path),
                                   settings.prescreen_min_score(cfg_path))
    result.finalists = finalists
    result.drops.extend(drops_a)
    if not finalists:
        result.status = "no_finalists"
        result.reason = "every instrument scored below the pre-screen floor"
        return result

    # Stage B: cheap gate, finalists only.
    survivors, drops_b, gate_calls = gate_finalists(
        finalists, gate, settings.max_survivors(cfg_path))
    result.survivors = survivors
    result.drops.extend(drops_b)
    result.gate_calls = gate_calls
    if not survivors:
        result.status = "no_survivors"
        result.reason = "the gate rejected every finalist"
        return result

    # Stage C: the only paid stage, bounded twice over.
    if remaining <= 0:
        for s in survivors:
            result.drops.append(Drop(s, STAGE_C, "daily_budget_exhausted", 0.0))
        result.status = "budget_exhausted"
        result.reason = (f"discovery daily council budget {daily_budget} spent, "
                         f"no council call made this pass")
        return result

    scores = {f.symbol: f.score for f in finalists}
    candidates, drops_c, calls = evaluate_survivors(
        survivors, evaluator,
        max_council_calls=settings.max_council_calls_per_pass(cfg_path),
        budget_remaining=remaining, finalist_scores=scores)
    result.drops.extend(drops_c)
    result.council_calls = calls
    result.est_cost_usd = calls * settings.discovery_est_cost_per_call_usd(cfg_path)
    result.budget_remaining = max(0, remaining - calls)

    # Route each verdict to a sleeve. Routing only, the engine enforces the cap.
    for verdict in candidates:
        verdict["sleeve_target"] = sleeve_target_for(verdict, cfg_path)
    result.candidates = candidates
    return result
