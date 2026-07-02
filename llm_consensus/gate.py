"""Free base-check gate — a cheap pre-council cost-control screen.

Before the three expensive providers run, a single cheap ``gemini-3-flash`` call
decides whether the setup is even worth a full review. If it says no, the council
is skipped and a flat/neutral verdict is returned.

Fail-safe posture:
  * gate disabled by config        -> always proceed (AlwaysProceedGate).
  * no GEMINI_API_KEY              -> permissive MOCK gate (always proceed), so
                                      offline behaviour is unchanged.
  * gate call errors / unparseable -> proceed (fail-open): a flaky gate must
                                      never silently suppress real analysis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import http_json
from .providers import _resolve_key, build_user_prompt, gemini_request, gemini_text

log = logging.getLogger("llm_consensus")

GATE_ENV_VAR = "GEMINI_API_KEY"

# Stable (cacheable) instruction prefix for the gate.
GATE_SYSTEM_PROMPT = (
    "You are a cheap pre-screen for a multi-model trading advisory council. "
    "Given a compact market snapshot, decide whether the setup is worth a full "
    "(expensive) council review. Skip flat, rangebound, or low-signal setups. "
    "This is a COST gate, not a trade decision.\n\n"
    "Respond with a SINGLE JSON object and nothing else:\n"
    '  "proceed": boolean — true if worth a full council review\n'
    '  "reason":  one short sentence (<= 140 chars)\n'
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
    """No-op gate used when the gate is disabled by config."""

    def __init__(self, reason: str = "gate disabled", source: str = "disabled",
                 model: str = "") -> None:
        self._reason = reason
        self._source = source
        self._model = model

    def should_review(self, state: dict) -> GateDecision:
        return GateDecision(True, self._reason, self._model, self._source)


@dataclass
class GeminiFlashGate:
    """Cheap Gemini-Flash base-check (env GEMINI_API_KEY, free tier)."""

    model_id: str = "gemini-3-flash"
    timeout: float = http_json.DEFAULT_TIMEOUT

    def should_review(self, state: dict) -> GateDecision:
        key = _resolve_key(GATE_ENV_VAR)
        if not key:
            return GateDecision(
                True, f"no {GATE_ENV_VAR}: permissive mock gate (proceed)",
                self.model_id, "mock")
        try:
            url, headers, payload = gemini_request(
                self.model_id, key, GATE_SYSTEM_PROMPT, build_user_prompt(state))
            resp = http_json.post_json(url, headers, payload, timeout=self.timeout)
            text = gemini_text(resp)
        except Exception as e:
            log.warning("base-check gate (%s) call failed: %s", self.model_id, e)
            return GateDecision(True, f"gate error, proceeding: {e}",
                                self.model_id, "error")
        obj = http_json.extract_json_object(text)
        if obj is None:
            log.warning("base-check gate (%s) returned unparseable output",
                        self.model_id)
            return GateDecision(True, "gate output unparseable, proceeding",
                                self.model_id, "error")
        proceed = bool(obj.get("proceed", obj.get("review", True)))
        reason = str(obj.get("reason", ""))[:200] or (
            "worth a full review" if proceed else "skip: low-signal setup")
        return GateDecision(proceed, reason, self.model_id, "real")
