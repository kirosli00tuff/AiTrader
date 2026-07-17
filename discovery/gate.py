"""Stage-B gate for discovery, prompted for the data discovery actually has.

WHY THIS EXISTS, and why it is not the council's gate.

llm_consensus.gate.HaikuGate was built for the TRADING loop, whose market state
carries an order book and a news catalyst. Its prompt renders seven fields, and
llm_consensus.providers.build_user_prompt defaults a missing one to 0.0. So the
model cannot tell "measured, and it is zero" from "we do not have this".

Discovery's Stage-A pre-screen is free Finnhub data: price, change, high, low,
open, previous close. There is NO order book on the free tier, and no crypto news
sentiment. So every discovery candidate reached the trading gate declaring
catalyst 0.0 and order-book imbalance 0.0, and the model read that as a flat,
signal-less instrument and skipped it. Measured against the live funnel: it
rejected 12 of 12 finalists on every pass, and rejected a SYNTHETIC +14% move
with a 14% intraday range as a "flat, rangebound setup". That is not a market
read, it is a model correctly describing the zeros it was handed. Stage B was a
wall no candidate could pass, in any market, so Stage C could never run.

The fix is to ask a question the data can answer. This gate:
  * shows only the fields discovery HAS, and says so, so absent reads as absent
    rather than as zero.
  * judges movement, which is the entire question Stage A already scored and the
    only question free data supports.
  * keeps the trading loop's gate untouched. That gate guards real orders on real
    state, and nothing here changes its prompt, its model, or its behavior.

Same model (claude-haiku-4-5), same shared ANTHROPIC_API_KEY, same tiny reply, so
the cost per call is unchanged: well under a cent, inside the existing discovery
budget.

Fail-safe posture matches the council gate deliberately: an error, an unparseable
reply, or a missing key all PROCEED. A flaky cost gate must never silently
suppress a real candidate, and the hard max_survivors ceiling still bounds spend,
so failing open cannot blow the budget. The expensive direction is a wasted
council call; the cheap direction is never seeing an opportunity.
"""
from __future__ import annotations

import json
import logging

from llm_consensus import http_json
from llm_consensus.gate import GATE_ENV_VAR, GATE_MAX_TOKENS, GateDecision
from llm_consensus.providers import (_resolve_key, anthropic_request,
                                     anthropic_text)

log = logging.getLogger("discovery.gate")

GATE_MODEL = "claude-haiku-4-5"

# Names the absent fields explicitly. Without this the model reasons about what is
# missing rather than what is present, which is exactly the failure being fixed:
# it must not read "no order book data" as "no order book pressure".
DISCOVERY_GATE_SYSTEM_PROMPT = (
    "You are a cheap pre-screen for a multi-model trading advisory council. "
    "You are screening instruments surfaced by a FREE market-data scan, so you "
    "see ONLY price, daily return, and intraday volatility. There is no order "
    "book and no news sentiment available for these instruments. Their absence "
    "is not evidence of a flat market: judge ONLY on the fields you are given, "
    "and never skip an instrument for lacking a field that was never offered.\n\n"
    "Decide whether the price action alone is worth a full (expensive) council "
    "review. A large move, in either direction, is worth a look; direction is "
    "the council's job, not yours. Skip genuinely quiet instruments: a small "
    "return with low volatility. This is a COST gate, not a trade decision.\n\n"
    "Respond with a SINGLE JSON object and nothing else:\n"
    '  "proceed": boolean — true if worth a full council review\n'
    '  "reason":  one short sentence (<= 140 chars)\n'
    "No markdown, no code fences, no text outside the JSON object."
)


def build_discovery_prompt(state: dict) -> str:
    """Render ONLY the fields discovery has. Absent stays absent.

    Deliberately not llm_consensus.providers.build_user_prompt: that one emits
    catalyst_score and order_book_imbalance as 0.0 when they are missing, and
    those two zeros are what made the gate reject everything.
    """
    snapshot = {
        "symbol": state.get("symbol", "?"),
        "price": state.get("price", 0.0),
        "daily_return": state.get("ret_5", 0.0),
        "intraday_volatility": state.get("volatility", 0.0),
    }
    # Equities carry Finnhub's precomputed sentiment. Crypto does not, so the key
    # appears only when there is a real number behind it.
    if state.get("catalyst"):
        snapshot["news_sentiment"] = state["catalyst"]
    return ("Instrument from a free pre-screen scan:\n" +
            json.dumps(snapshot, sort_keys=True) +
            "\nReturn your screen decision as the required JSON object.")


class DiscoveryGate:
    """Stage-B screen. Same interface as llm_consensus's gate: should_review."""

    def __init__(self, model_id: str = GATE_MODEL,
                 timeout: float = http_json.DEFAULT_TIMEOUT):
        self.model_id = model_id
        self.timeout = timeout

    def should_review(self, state: dict) -> GateDecision:
        key = _resolve_key(GATE_ENV_VAR)
        if not key:
            return GateDecision(
                True, f"no {GATE_ENV_VAR}: permissive mock gate (proceed)",
                self.model_id, "mock")
        try:
            url, headers, payload = anthropic_request(
                self.model_id, key, DISCOVERY_GATE_SYSTEM_PROMPT,
                build_discovery_prompt(state), max_tokens=GATE_MAX_TOKENS)
            resp = http_json.post_json(url, headers, payload,
                                       timeout=self.timeout)
            text = anthropic_text(resp)
        except Exception as e:  # noqa: BLE001 — fail open, never suppress
            log.warning("discovery gate (%s) call failed: %s", self.model_id,
                        type(e).__name__)
            return GateDecision(True,
                                f"gate error, proceeding: {type(e).__name__}",
                                self.model_id, "error")
        obj = http_json.extract_json_object(text)
        if obj is None:
            log.warning("discovery gate (%s) returned unparseable output",
                        self.model_id)
            return GateDecision(True, "gate output unparseable, proceeding",
                                self.model_id, "error")
        proceed = bool(obj.get("proceed", obj.get("review", True)))
        reason = str(obj.get("reason", ""))[:200] or (
            "worth a full review" if proceed else "skip: quiet instrument")
        return GateDecision(proceed, reason, self.model_id, "real")
