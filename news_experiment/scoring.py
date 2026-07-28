"""The model call, the parse, the cost, and the spend ceiling.

THE CEILING IS ENFORCED BEFORE THE FIRST CALL, not after the first overrun.
`SpendCeiling.check` refuses when the NEXT call could cross the limit, using
the projected per-call cost rather than a measured one, because the cost of a
call that has not happened is unknowable and an optimistic estimate is how a
ceiling gets crossed by exactly one call.

THE PARSE IS LENIENT ON FORM AND STRICT ON MEANING. A model returning
`"Positive"` plainly considered the headline, so rejecting it would inflate
`model_failed`, a state Task 7 reserves for "the model never considered it".
Case is normalised and surrounding prose tolerated. What is NOT tolerated is a
judgment outside the three values, because that is not a judgment.

STRENGTH PARSES INDEPENDENTLY OF JUDGMENT (Task 3). A missing or malformed
strength leaves the judgment intact, sets `strength` NULL and
`strength_parse_ok` 0, and the row stays scoreable. Strength gates nothing, so
letting it invalidate the primary field would trade the measurement for the
diagnostic.

CACHE CONTROL IS SENT EVEN THOUGH NOTHING CACHES. The system block is about
270 tokens against Haiku 4.5's 4,096-token minimum cacheable prefix, so
`cache_read_input_tokens` comes back 0. Sending `cache_control` anyway keeps
that zero MEANINGFUL: without the request the field would read 0 by
construction and the prompt-drift canary in Task 3 would be dead rather than
quiet. A non-zero value means the prompt grew past the minimum unnoticed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from llm_consensus import provider_health
from llm_consensus.http_json import LLMHTTPError, extract_json_object, post_json

from . import spec

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

ERROR_TRANSPORT = "transport"
ERROR_TIMEOUT = "timeout"
ERROR_HTTP_STATUS = "http_status"
ERROR_UNPARSEABLE = "unparseable"
ERROR_EXHAUSTED = "exhausted"


class SpendCeilingReached(RuntimeError):
    """Raised instead of making a call that could cross the ceiling."""


@dataclass
class SpendCeiling:
    """A hard USD ceiling across every call this process makes."""
    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    projected_per_call: float = spec.PROJECTED_COST_PER_CALL

    def check(self) -> None:
        if self.spent_usd + self.projected_per_call > self.limit_usd:
            raise SpendCeilingReached(
                f"ceiling {self.limit_usd:.4f} USD would be crossed: spent "
                f"{self.spent_usd:.6f}, next call projected "
                f"{self.projected_per_call:.6f}")

    def record(self, cost: float) -> None:
        self.spent_usd += max(0.0, float(cost))
        self.calls += 1

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)


def cost_usd(input_tokens: int, output_tokens: int, cache_read: int = 0,
             cache_write: int = 0) -> float:
    """Cost of one call from its recorded token counts and the recorded rates.

    Anthropic reports `input_tokens` as the UNCACHED remainder, with cache
    reads and writes counted separately, so the four terms do not overlap.
    """
    return (input_tokens * spec.PRICE_INPUT_PER_MTOK / 1e6
            + output_tokens * spec.PRICE_OUTPUT_PER_MTOK / 1e6
            + cache_read * spec.PRICE_CACHE_READ_PER_MTOK / 1e6
            + cache_write * spec.PRICE_CACHE_WRITE_PER_MTOK / 1e6)


@dataclass
class ParsedVerdict:
    judgment: str | None
    strength: int | None
    reason: str
    parse_ok: bool
    strength_parse_ok: bool
    neutral_strength_anomaly: bool = False


def parse_verdict(text: str) -> ParsedVerdict:
    """Pull judgment, strength and reason out of the model's raw response."""
    obj = extract_json_object(text or "")
    if not isinstance(obj, dict):
        return ParsedVerdict(None, None, "", False, False)

    raw_judgment = obj.get("judgment")
    judgment = None
    if isinstance(raw_judgment, str):
        candidate = raw_judgment.strip().upper()
        if candidate in spec.JUDGMENTS:
            judgment = candidate
    if judgment is None:
        return ParsedVerdict(None, None, "", False, False)

    strength: int | None = None
    raw_strength = obj.get("strength")
    if isinstance(raw_strength, bool):
        raw_strength = None          # a bool is not a strength, it is a bug
    if isinstance(raw_strength, (int, float)):
        as_int = int(raw_strength)
        if (as_int == raw_strength
                and spec.STRENGTH_MIN <= as_int <= spec.STRENGTH_MAX):
            strength = as_int
    elif isinstance(raw_strength, str):
        try:
            parsed_int: int | None = int(raw_strength.strip())
        except ValueError:
            parsed_int = None
        if (parsed_int is not None
                and spec.STRENGTH_MIN <= parsed_int <= spec.STRENGTH_MAX):
            strength = parsed_int

    reason_raw = obj.get("reason")
    reason = reason_raw.strip() if isinstance(reason_raw, str) else ""

    anomaly = (judgment == spec.JUDGMENT_NEUTRAL and strength is not None
               and strength != spec.STRENGTH_ON_NEUTRAL)
    return ParsedVerdict(judgment=judgment, strength=strength, reason=reason,
                         parse_ok=True,
                         strength_parse_ok=strength is not None,
                         neutral_strength_anomaly=anomaly)


@dataclass
class ScoreResult:
    """Everything one model call produces, success or failure."""
    state: str
    raw_response: str = ""
    judgment: str | None = None
    strength: int | None = None
    reason: str = ""
    parse_ok: bool = False
    strength_parse_ok: bool = False
    neutral_strength_anomaly: bool = False
    error_class: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def build_request(ticker: str, headline: str, key: str) -> tuple[str, dict, dict]:
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": spec.MODEL_ID,
        "max_tokens": spec.MAX_TOKENS,
        "temperature": spec.TEMPERATURE,
        "system": [{"type": "text", "text": spec.SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user",
                      "content": spec.build_user_prompt(ticker, headline)}],
    }
    return ANTHROPIC_URL, headers, payload


def _usage(resp: dict) -> tuple[int, int, int, int]:
    usage = resp.get("usage") or {}
    return (int(usage.get("input_tokens") or 0),
            int(usage.get("cache_read_input_tokens") or 0),
            int(usage.get("cache_creation_input_tokens") or 0),
            int(usage.get("output_tokens") or 0))


def _text_of(resp: dict) -> str:
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text", ""))
    return ""


@dataclass
class Scorer:
    """One model client. Holds the key, the ceiling and the latch label."""
    key: str
    label: str
    ceiling: SpendCeiling
    poster: object = None        # seam: callable(url, headers, payload) -> dict
    calls: int = 0
    failures: int = 0
    _post: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._post = self.poster or post_json

    def score(self, ticker: str, headline: str) -> ScoreResult:
        """Score one headline. Never raises except on the spend ceiling."""
        if provider_health.is_exhausted(self.label):
            return ScoreResult(state=spec.STATE_MODEL_FAILED,
                               error_class=ERROR_EXHAUSTED, raw_response="")
        self.ceiling.check()

        url, headers, payload = build_request(ticker, headline, self.key)
        started = time.monotonic()
        try:
            resp = self._post(url, headers, payload)  # type: ignore[operator]
        except LLMHTTPError as exc:
            latency = int((time.monotonic() - started) * 1000)
            self.failures += 1
            kind = provider_health.classify(exc, label=self.label)
            if kind == provider_health.EXHAUSTED:
                provider_health.mark_exhausted(self.label,
                                               model_id=spec.MODEL_ID,
                                               detail=str(exc)[:200])
                error_class = ERROR_EXHAUSTED
            elif getattr(exc, "status", None) is not None:
                error_class = ERROR_HTTP_STATUS
            elif "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                error_class = ERROR_TIMEOUT
            else:
                error_class = ERROR_TRANSPORT
            return ScoreResult(state=spec.STATE_MODEL_FAILED,
                               raw_response=str(getattr(exc, "text", "") or exc),
                               error_class=error_class, latency_ms=latency)
        except Exception as exc:  # noqa: BLE001 - a transport fault is data
            latency = int((time.monotonic() - started) * 1000)
            self.failures += 1
            return ScoreResult(state=spec.STATE_MODEL_FAILED,
                               raw_response=str(exc)[:2000],
                               error_class=ERROR_TRANSPORT, latency_ms=latency)

        latency = int((time.monotonic() - started) * 1000)
        self.calls += 1
        payload_resp = resp if isinstance(resp, dict) else {}
        inp, cache_read, cache_write, out = _usage(payload_resp)
        cost = cost_usd(inp, out, cache_read, cache_write)
        self.ceiling.record(cost)

        raw = _text_of(payload_resp)
        parsed = parse_verdict(raw)
        state = spec.STATE_JUDGED if parsed.parse_ok else spec.STATE_MODEL_FAILED
        return ScoreResult(
            state=state, raw_response=raw, judgment=parsed.judgment,
            strength=parsed.strength, reason=parsed.reason,
            parse_ok=parsed.parse_ok,
            strength_parse_ok=parsed.strength_parse_ok,
            neutral_strength_anomaly=parsed.neutral_strength_anomaly,
            error_class="" if parsed.parse_ok else ERROR_UNPARSEABLE,
            latency_ms=latency, input_tokens=inp,
            cached_input_tokens=cache_read, output_tokens=out, cost_usd=cost)
