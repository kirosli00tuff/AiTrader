"""Cheap pre-council base-check gate — a Claude Haiku cost-control screen.

Before the three expensive council providers run, a single cheap
``claude-haiku-4-5`` call decides whether the setup is even worth a full
review. If it says no, the council is skipped and a flat/neutral verdict is
returned. The gate reuses the same Anthropic Messages client (and the same
``ANTHROPIC_API_KEY``) as the council's secondary provider, so it needs no new
credential and each call costs a small fraction of a cent.

Fail-safe posture:
  * gate disabled by config        -> always proceed (AlwaysProceedGate).
  * no ANTHROPIC_API_KEY           -> permissive MOCK gate (always proceed), so
                                      offline behaviour is unchanged.
  * gate call errors / unparseable -> proceed (fail-open): a flaky gate must
                                      never silently suppress real analysis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import http_json
from .providers import (
    _resolve_key, anthropic_request, anthropic_text, build_user_prompt,
)

log = logging.getLogger("llm_consensus")

# The gate reuses the council's Anthropic key — no separate credential needed.
GATE_ENV_VAR = "ANTHROPIC_API_KEY"

# The gate reply is tiny (a yes/no plus a one-line reason), so a small token cap
# keeps each call cheap without truncating the reason.
GATE_MAX_TOKENS = 128

# Stable (cacheable) instruction prefix for the gate. Same evidence rules as
# the council (2026-07-20): absence is not evidence, and the reason comes
# before the decision.
GATE_SYSTEM_PROMPT = (
    "You are a cheap pre-screen for a multi-model trading advisory council. "
    "Given an evidence block, decide whether the setup is worth a full "
    "(expensive) council review. Skip genuinely quiet setups: small moves with "
    "low volatility. This is a COST gate, not a trade decision.\n\n"
    "A field that is absent was NOT measured. Absence is not evidence: never "
    "treat a missing field as zero or calm, and never skip an instrument for "
    "lacking a field that was never offered.\n\n"
    "Respond with a SINGLE JSON object and nothing else, keys in this order, "
    "reason first:\n"
    '  "reason":  one short sentence (<= 140 chars)\n'
    '  "proceed": boolean, true if worth a full council review\n'
    "No markdown, no code fences, no text outside the JSON object."
)


@dataclass
class GateDecision:
    proceed: bool
    reason: str
    model: str = ""
    source: str = "mock"  # "real" | "mock" | "disabled" | "error"

    def to_dict(self) -> dict:
        return {
            "proceed": self.proceed,
            "reason": self.reason,
            "model": self.model,
            "source": self.source,
        }


class AlwaysProceedGate:
    """No-op gate used when the gate is disabled by config.

    The defaults say "gate disabled" / source "disabled" because that is what
    this gate means when CONFIG disables the screen. Do not construct it bare
    to express "already screened elsewhere": that is what PriorScreenGate is
    for, and using this one instead is exactly how 44 discovery evaluations
    came to record an unscreened-looking round for a candidate a real Haiku
    call had screened one stage earlier (2026-07-25).
    """

    def __init__(self, reason: str = "gate disabled", source: str = "disabled",
                 model: str = "") -> None:
        self._reason = reason
        self._source = source
        self._model = model

    def should_review(self, state: dict) -> GateDecision:
        return GateDecision(True, self._reason, self._model, self._source)


class PriorScreenGate:
    """Reports a screen that ALREADY HAPPENED, without calling anything.

    The discovery funnel screens once per stage: Stage B pays a real
    claude-haiku-4-5 call per finalist, and Stage C must not pay a second one
    for the same question (it also must not run the TRADING gate, whose prompt
    renders an order book free Finnhub data does not have, which rejected 12
    of 12 finalists on every pass before 2026-07-20).

    So Stage C does not screen. It REPORTS. This gate carries the Stage-B
    decision forward verbatim, so the persisted round names the model that
    screened the candidate and the reason it gave, instead of a bare
    "disabled" that reads as unscreened. It costs nothing and calls nobody.

    A survivor with no recorded decision (the fail-open path, where the gate
    itself errored) proceeds and says so, because that is the truth about it.
    """

    UNSCREENED = GateDecision(
        True, "stage B gate failed open, this candidate was not screened",
        "", "stage_b_failed_open")

    def __init__(self, decision: GateDecision | None) -> None:
        self._decision = decision

    def should_review(self, state: dict) -> GateDecision:
        if self._decision is None:
            return self.UNSCREENED
        return GateDecision(
            bool(getattr(self._decision, "proceed", True)),
            f"screened at stage B: {getattr(self._decision, 'reason', '')}"[:200],
            str(getattr(self._decision, "model", "")),
            f"stage_b_{getattr(self._decision, 'source', 'unknown')}")


@dataclass
class HaikuGate:
    """Cheap Claude Haiku base-check (env ANTHROPIC_API_KEY, shared with council).

    Reuses the council's Anthropic Messages transport, so no new credential is
    needed. Each call is a single small Haiku request (yes/no plus a one-line
    reason), costing well under a cent.
    """

    model_id: str = "claude-haiku-4-5"
    timeout: float = http_json.DEFAULT_TIMEOUT

    def should_review(self, state: dict) -> GateDecision:
        """THE FAIL DIRECTION, DECIDED DELIBERATELY (2026-07-27).

        This gate exists for one purpose: keep a low-signal setup out of the
        paid three-provider council. So the question on a failure is not "is
        this setup good", it is "what does a gate that CANNOT RUN protect". The
        answer differs by whether money sits behind it, and this method now
        splits on exactly that rather than treating every failure alike.

        NO KEY MEANS OFFLINE, AND IT KEEPS FAILING OPEN. The demo path has no
        gate credential BY DESIGN and the council behind it is free
        deterministic mocks. Refusing there would screen nothing, protect
        nothing, and change offline behaviour for no gain, which is why a
        blanket fail-closed was rejected when this was first analysed. Same
        shape as the tradeable invariant exempting the offline feed modes: a
        rule about real spending does not apply where there is none.

        A LIVE FAILURE NOW FAILS CLOSED, and that is the change. A key is
        present, so real providers with real cost sit behind this gate. A gate
        that errored screened nothing, and proceeding sends every candidate to
        the full three-provider council UNSCREENED, the most expensive possible
        response to a cost control breaking. Worse: the same ANTHROPIC_API_KEY
        powers this gate and one council provider, so the conditions that break
        the gate (auth, quota, transport) are the conditions that make the
        spend it releases most wasteful.

        THE COST OF THE NEW DIRECTION IS REAL AND ACCEPTED, not hidden. A
        transient hiccup now suppresses a council round on a setup that may have
        been genuine. That is survivable because a refused round is not a
        refused trade: composition falls back to the fast tier, which is free,
        already exercised, and the same path a low-signal skip takes.
        Suppressing one paid opinion is recoverable; spending the budget
        unscreened through an outage is not.

        The recorded pattern points the same way for anything that can spend: an
        unreadable control file means NO OVERRIDE and config decides, and config
        ships every spender off, because a broken input must never start a
        spender. The counter-pattern (an unprovable serviceability check must
        not refuse a symbol) is about not silently shrinking a universe on
        absent evidence, which is a different question from releasing money.
        """
        key = _resolve_key(GATE_ENV_VAR)
        if not key:
            return GateDecision(
                True, f"no {GATE_ENV_VAR}: permissive mock gate (proceed)",
                self.model_id, "mock")
        try:
            url, headers, payload = anthropic_request(
                self.model_id, key, GATE_SYSTEM_PROMPT, build_user_prompt(state),
                max_tokens=GATE_MAX_TOKENS)
            resp = http_json.post_json(url, headers, payload, timeout=self.timeout)
            text = anthropic_text(resp)
        except Exception as e:
            log.error("base-check gate (%s) call FAILED, refusing the paid "
                      "council for this candidate: %s", self.model_id, e)
            return GateDecision(
                False, f"gate unavailable, refusing the paid council: {e}"[:200],
                self.model_id, "error_failed_closed")
        obj = http_json.extract_json_object(text)
        if obj is None:
            log.error("base-check gate (%s) returned unparseable output, "
                      "refusing the paid council for this candidate",
                      self.model_id)
            return GateDecision(
                False, "gate output unparseable, refusing the paid council",
                self.model_id, "error_failed_closed")
        proceed = bool(obj.get("proceed", obj.get("review", True)))
        reason = str(obj.get("reason", ""))[:200] or (
            "worth a full review" if proceed else "skip: low-signal setup")
        return GateDecision(proceed, reason, self.model_id, "real")
