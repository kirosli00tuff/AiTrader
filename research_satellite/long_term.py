"""The research_satellite long-term strategy: quality and catalyst, plus council.

A blend, in two steps, cheap before expensive (the same discipline as the
discovery funnel):

  1. QUALITY AND CATALYST screen, free. Finnhub fundamentals and analyst data
     establish that the business is worth owning for months, and a CATALYST
     establishes why now: an upcoming earnings event, a strong sentiment shift,
     or an analyst upgrade. Quality without a catalyst is a watchlist entry, not
     a trade. A catalyst without quality is a gamble. Both must hold.
  2. FULL FOUR-LEVEL evaluation on what survives, framed for a LONG horizon. The
     council is asked for a hold thesis, not a scalp, and the DNN and whale
     layers weigh in as advisory exactly as they do for the quant core.

The four levels drive BOTH sleeves. The difference is the horizon and the prompt
framing, short-term-trade mode for the core and long-term-hold mode here, not a
separate brain.

Boundaries this module does NOT cross:
  * It never opens a position. It returns a thesis. The C++ engine applies the
    conviction threshold, the HARD satellite cap (a conviction can never override
    it), and the RiskGate before any order exists.
  * The invalidation level may only TIGHTEN the native stop, never widen it (see
    invalidation_stop). A thesis cannot buy itself more room to be wrong.
  * It ships behind discovery.long_term_sleeve_enabled AND
    sleeves.research_satellite_enabled. Both default false.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("research_satellite.long_term")

# Catalyst window: an earnings print inside this many days is a live catalyst.
EARNINGS_WINDOW_DAYS = 21

# Sentiment shift: how far Finnhub's companyNewsScore must sit from neutral
# (0.5) to count as a catalyst on its own.
SENTIMENT_SHIFT_MIN = 0.20

# Analyst upgrade: consensus score above this counts as a supportive catalyst.
ANALYST_UPGRADE_MIN = 0.35

# Quality floors. Deliberately loose: this screen exists to reject the obviously
# unownable, not to pick winners. The council does the picking.
QUALITY_MIN_SCORE = 0.40
_ROE_GOOD = 15.0          # percent
_MARGIN_GOOD = 10.0       # percent
_GROWTH_GOOD = 5.0        # percent YoY
_PE_SANE_MAX = 60.0       # above this, price already assumes perfection


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def quality_score(fin: dict) -> tuple[float, dict]:
    """Score business quality from parsed Finnhub fundamentals, [0,1].

    Each component contributes only when its metric is PRESENT. A company with no
    reported metric scores the neutral 0.5 for that component rather than 0, so
    thin coverage does not masquerade as poor quality. Returns (score, breakdown).
    """
    if not fin:
        return 0.0, {"reason": "no fundamentals"}

    def _component(value: float | None, good: float) -> float:
        if value is None:
            return 0.5  # no data is not evidence of low quality
        return _clamp01(value / good) if good else 0.5

    roe = _component(fin.get("roe_ttm"), _ROE_GOOD)
    margin = _component(fin.get("net_margin_ttm"), _MARGIN_GOOD)
    growth = _component(fin.get("revenue_growth_yoy"), _GROWTH_GOOD)

    # Valuation: a sane P/E scores well, an absent or negative one is neutral
    # (loss-making is not automatically unownable), an extreme one scores low.
    pe = fin.get("pe_ttm")
    if pe is None or pe <= 0:
        valuation = 0.5
    else:
        valuation = _clamp01(1.0 - (pe / _PE_SANE_MAX))

    score = 0.30 * roe + 0.25 * margin + 0.25 * growth + 0.20 * valuation
    return round(_clamp01(score), 4), {
        "roe": round(roe, 4), "margin": round(margin, 4),
        "growth": round(growth, 4), "valuation": round(valuation, 4),
    }


def find_catalyst(*, earnings: list[dict] | None, sentiment: dict | None,
                  recommendations: dict | None, symbol: str,
                  now: datetime | None = None) -> dict:
    """Identify a live catalyst. Returns {"found", "kind", "detail"}.

    Three kinds, in priority order: a dated earnings event beats a soft signal,
    and a sentiment shift beats a standing analyst view.
    """
    now = now or datetime.now(timezone.utc)

    # 1. Earnings event inside the window.
    horizon = (now + timedelta(days=EARNINGS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    for row in earnings or []:
        if str(row.get("symbol", "")).upper() != symbol.upper():
            continue
        date = str(row.get("date", ""))
        if today <= date <= horizon:
            return {"found": True, "kind": "earnings",
                    "detail": f"earnings {date}, inside {EARNINGS_WINDOW_DAYS}d"}

    # 2. Strong sentiment shift away from neutral.
    if sentiment:
        try:
            score = float(sentiment.get("score", 0.5))
        except (TypeError, ValueError):
            score = 0.5
        shift = score - 0.5
        if abs(shift) >= SENTIMENT_SHIFT_MIN:
            way = "bullish" if shift > 0 else "bearish"
            return {"found": True, "kind": "sentiment_shift",
                    "detail": f"news sentiment {score:.2f} ({way})"}

    # 3. Analyst upgrade / strong consensus.
    if recommendations:
        try:
            rec = float(recommendations.get("score", 0.0))
        except (TypeError, ValueError):
            rec = 0.0
        if rec >= ANALYST_UPGRADE_MIN:
            return {"found": True, "kind": "analyst_upgrade",
                    "detail": f"analyst consensus {rec:+.2f} "
                              f"({recommendations.get('period', '')})"}

    return {"found": False, "kind": "", "detail": "no catalyst"}


def screen(symbol: str, client, now: datetime | None = None) -> dict:
    """Run the free quality-and-catalyst screen for one symbol.

    Costs no LLM tokens: Finnhub REST only. Returns
    {"passes", "quality", "catalyst", "reason", "financials", "quote"}.
    """
    from discovery.finnhub_source import (parse_basic_financials,
                                          parse_earnings_calendar,
                                          parse_news_sentiment, parse_quote,
                                          parse_recommendations)
    now = now or datetime.now(timezone.utc)

    fin = parse_basic_financials(client.basic_financials(symbol))
    q_score, q_breakdown = quality_score(fin)

    sentiment = parse_news_sentiment(client.news_sentiment(symbol))
    recs = parse_recommendations(client.recommendation_trends(symbol))
    earnings = parse_earnings_calendar(client.earnings_calendar(
        now.strftime("%Y-%m-%d"),
        (now + timedelta(days=EARNINGS_WINDOW_DAYS)).strftime("%Y-%m-%d"),
        symbol=symbol))
    catalyst = find_catalyst(earnings=earnings, sentiment=sentiment,
                             recommendations=recs, symbol=symbol, now=now)
    quote = parse_quote(client.quote(symbol))

    # BOTH must hold. Quality alone is a watchlist entry, catalyst alone a gamble.
    if q_score < QUALITY_MIN_SCORE:
        passes, reason = False, f"quality {q_score:.2f} below {QUALITY_MIN_SCORE}"
    elif not catalyst["found"]:
        passes, reason = False, "no catalyst"
    else:
        passes, reason = True, f"quality {q_score:.2f} + {catalyst['kind']}"

    return {
        "symbol": symbol,
        "passes": passes,
        "reason": reason,
        "quality": q_score,
        "quality_breakdown": q_breakdown,
        "catalyst": catalyst,
        "financials": fin,
        "quote": quote,
    }


def derive_target_and_invalidation(*, direction: str, price: float,
                                   conviction: float, fin: dict) -> dict:
    """Derive the price target and the invalidation level.

    DETERMINISTIC on purpose. The council supplies direction, conviction, and the
    reasoning; the concrete levels come from the 52-week range and conviction, so
    a model cannot hallucinate a target that quietly widens risk. When the range
    is unknown the levels fall back to conviction-scaled percentages.

    For a long: the target reaches toward the 52-week high in proportion to
    conviction, and invalidation sits below at a level that says "the thesis was
    wrong", not "the market wiggled".
    """
    if price <= 0:
        return {"target": 0.0, "invalidation_price": 0.0,
                "invalidation": "no price available"}

    hi = fin.get("week52_high") if fin else None
    lo = fin.get("week52_low") if fin else None
    conviction = _clamp01(conviction)

    if direction == "long":
        if hi and hi > price:
            target = price + (hi - price) * (0.5 + 0.5 * conviction)
        else:
            target = price * (1.0 + 0.10 + 0.20 * conviction)
        if lo and lo < price:
            # Invalidation a third of the way down toward the 52w low.
            invalid = price - (price - lo) * 0.33
        else:
            invalid = price * 0.85
        narrative = (f"close below {invalid:.2f} (thesis broken: the quality and "
                     f"catalyst case no longer holds)")
    else:  # short
        if lo and lo < price:
            target = price - (price - lo) * (0.5 + 0.5 * conviction)
        else:
            target = price * (1.0 - 0.10 - 0.20 * conviction)
        if hi and hi > price:
            invalid = price + (hi - price) * 0.33
        else:
            invalid = price * 1.15
        narrative = f"close above {invalid:.2f} (thesis broken)"

    return {"target": round(target, 4),
            "invalidation_price": round(invalid, 4),
            "invalidation": narrative}


def invalidation_stop(*, direction: str, entry_price: float, atr_stop: float,
                      invalidation_price: float) -> float:
    """The native stop for a long-term position.

    SAFETY RULE: the thesis invalidation level may only TIGHTEN the stop, never
    widen it. A thesis cannot buy itself more room to be wrong, so this returns
    whichever stop sits closer to entry. The RiskGate keeps its own limits
    unconditionally either way; this is a native stop, not a Level-1 value.
    """
    if entry_price <= 0 or invalidation_price <= 0:
        return atr_stop
    if direction == "long":
        # Both sit below entry. The tighter (higher) one wins.
        return (max(atr_stop, invalidation_price) if atr_stop > 0
                else invalidation_price)
    # Short: both sit above entry. The tighter (lower) one wins.
    return (min(atr_stop, invalidation_price) if atr_stop > 0
            else invalidation_price)


def long_term_thesis(payload: dict, client=None, providers=None,
                     cfg_path: str | None = None,
                     now: datetime | None = None) -> dict:
    """Produce a structured LONG-TERM thesis for one candidate.

    Shape (consumed by the C++ satellite path and the GUI): direction,
    conviction, horizon, target, invalidation, invalidation_price, rationale,
    verdict, agreement_count, quality, catalyst.

    Never raises. Any failure returns a flat, zero-conviction thesis the engine
    will not act on, the correct degradation for an advisory layer.
    """
    symbol = str(payload.get("symbol", "?"))
    now = now or datetime.now(timezone.utc)

    def _flat(reason: str) -> dict:
        return {"symbol": symbol, "direction": "flat", "conviction": 0.0,
                "horizon": "unknown", "target": 0.0, "invalidation_price": 0.0,
                "invalidation": "", "rationale": reason, "verdict": "hold",
                "agreement_count": 0, "quality": 0.0, "catalyst": ""}

    # Step 1: the free screen. No client means no screen, and no screen means no
    # long-term entry: the strategy is quality-and-catalyst PLUS council, never
    # council alone.
    if client is None:
        from discovery.finnhub_source import FinnhubClient, is_live
        if not is_live():
            return _flat("no FINNHUB_API_KEY resolved, quality screen unavailable")
        client = FinnhubClient()

    try:
        screened = screen(symbol, client, now)
    except Exception:  # noqa: BLE001
        return _flat("quality screen unavailable")
    if not screened["passes"]:
        return _flat(f"screened out: {screened['reason']}")

    # Step 2: the full four levels, framed for a LONG horizon.
    from discovery.evaluate import four_level_evaluator
    price = float((screened.get("quote") or {}).get("price") or
                  payload.get("price") or 0.0)
    evaluator = four_level_evaluator(
        price_for=lambda _s: price,
        category_for=lambda _s: str(payload.get("category", "equity")),
        horizon="months", cfg_path=cfg_path, providers=providers)
    try:
        verdict = evaluator(symbol)
    except Exception:  # noqa: BLE001
        return _flat("council unavailable")

    direction = str(verdict.get("direction", "flat"))
    conviction = float(verdict.get("conviction") or 0.0)
    if direction == "flat":
        return _flat(f"council flat on {symbol}: "
                     f"{verdict.get('rationale', '')}"[:500])

    levels = derive_target_and_invalidation(
        direction=direction, price=price, conviction=conviction,
        fin=screened.get("financials") or {})

    catalyst = screened["catalyst"]
    rationale = (
        f"Long-term {direction} on {symbol}. Quality {screened['quality']:.2f}, "
        f"catalyst {catalyst['kind']} ({catalyst['detail']}). "
        f"{verdict.get('rationale', '')}"
    )[:1000]

    return {
        "symbol": symbol,
        "direction": direction,
        "conviction": round(conviction, 4),
        # A long-term hold. The horizon is months, and the engine sets no time
        # stop for a satellite position, so it exits on target or invalidation
        # only, never on a short-term signal.
        "horizon": "months",
        "target": levels["target"],
        "invalidation_price": levels["invalidation_price"],
        "invalidation": levels["invalidation"],
        "rationale": rationale,
        "verdict": verdict.get("verdict", "avoid"),
        "agreement_count": int(verdict.get("agreement") or 0),
        "quality": screened["quality"],
        "catalyst": catalyst["kind"],
        "entry_price": price,
        "mode": "long_term_hold",
    }
