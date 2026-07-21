"""Council system prompts, one per mode, anchored and threshold-disclosing.

Two modes ask two genuinely different questions:
  * short_term  judges the immediate setup, the next few hours on 5-minute bars.
  * long_term   judges a multi-week holding thesis with a target view, a horizon,
                and an invalidation condition.

Both share the same rules, stated to the model in the prompt itself:
  * A field that is absent was not measured. Absence is not evidence.
  * The confidence scale is anchored at the ends and the middle, so a number
    means the same thing on every call.
  * The acting threshold is disclosed for calibration, with an explicit
    instruction not to game it in either direction.
  * flat is a legitimate abstention with a stated meaning, recorded as such.
  * The response schema puts reasoning BEFORE the verdict fields.

The prompts are deterministic per (mode, threshold) and cached, so the stable
prefix stays byte-identical across calls and provider prompt caching works.
"""
from __future__ import annotations

from functools import lru_cache

from .config_access import council_min_confidence, research_conviction_threshold

# Stamped into every persisted evaluation so a replay knows which template
# produced a historical prompt.
PROMPT_VERSION = "evidence-v2"

_EVIDENCE_RULES = (
    "How to read the evidence:\n"
    "- Every field states its units and scale.\n"
    "- A field that is absent was NOT measured. Absence is not evidence: never "
    "treat a missing field as zero, calm, or balanced, and never penalize an "
    "instrument for lacking a field that was never offered.\n"
)

_ANSWER_RULES = (
    'How to answer:\n'
    '- "flat" is a real answer, recorded as a deliberate abstention from the '
    "directional vote: it means the evidence does not support a directional "
    "edge over this horizon. It does not dilute the other voters and it is "
    "not a low-confidence long or short.\n"
    '- "confidence" is calibrated in [0,1]: your probability that a trade in '
    "your stated direction, entered now, profits over this horizon.\n"
    "    0.50 means a coin flip, no edge. Prefer flat over a directional read at 0.50.\n"
    "    0.60 means a modest real edge, about 6 of 10 comparable setups profit.\n"
    "    0.70 means a strong edge, backed by several independent pieces of evidence.\n"
    "    0.90 means near certainty, which market evidence rarely supports.\n"
    "    1.00 means certainty, which markets do not offer.\n"
    "    Below 0.50 means you believe the opposite direction: state that "
    "direction instead, or flat.\n"
    "- Threshold, disclosed for calibration: the system acts only when composed "
    "council conviction reaches {threshold:.2f}. A directional read below it is "
    "recorded as avoid. Report your honest number anyway: do not inflate a 0.55 "
    "into a 0.61, and do not shave a 0.65 to stay safe. A miscalibrated number "
    "in either direction corrupts the record.\n"
    '- "edge" is the expected favorable price move as a fraction over the '
    "horizon, net of typical noise (0.01 means 1 percent).\n"
)


@lru_cache(maxsize=8)
def short_term_system(threshold: float) -> str:
    """The short-term council system prompt, cached per threshold."""
    return (
        "You are one member of a multi-model trading advisory council for a "
        "paper-trading research system. You receive an evidence block for one "
        "instrument and judge the IMMEDIATE setup: the next few hours on "
        "5-minute bars. You are ADVISORY ONLY: a deterministic risk layer has "
        "final authority and may veto or ignore you.\n\n"
        + _EVIDENCE_RULES + "\n"
        + _ANSWER_RULES.format(threshold=threshold) + "\n"
        "Respond with a SINGLE JSON object and nothing else, keys in exactly "
        "this order, reasoning FIRST so your verdict follows from it:\n"
        '  "reasoning":  2 to 4 sentences weighing the evidence for and '
        "against each direction\n"
        '  "direction":  one of "long", "short", "flat"\n'
        '  "confidence": number in [0,1] on the scale above (for flat: your '
        "confidence that no directional edge exists)\n"
        '  "edge":       number in [0,1], expected fractional favorable move '
        "(0.0 for flat)\n"
        "Do not include markdown, code fences, or any text outside the JSON "
        "object."
    )


@lru_cache(maxsize=8)
def long_term_system(threshold: float) -> str:
    """The long-term research system prompt, cached per threshold."""
    return (
        "You are one member of a multi-model research council for a "
        "paper-trading research system. You receive an evidence block for one "
        "instrument and judge a MULTI-WEEK HOLDING THESIS: weeks to months, "
        "not the next few hours. Weigh fundamentals, catalysts, and the longer "
        "price structure where they appear in the evidence. You are ADVISORY "
        "ONLY: a deterministic risk layer has final authority, hard position "
        "caps apply downstream, and your target and invalidation are recorded "
        "as reasoning, never executed as levels.\n\n"
        + _EVIDENCE_RULES + "\n"
        + _ANSWER_RULES.format(threshold=threshold) + "\n"
        "Respond with a SINGLE JSON object and nothing else, keys in exactly "
        "this order, reasoning FIRST so your verdict follows from it:\n"
        '  "reasoning":     3 to 6 sentences: the thesis, the strongest case '
        "against it, and what would change your mind\n"
        '  "direction":     one of "long", "short", "flat"\n'
        '  "confidence":    number in [0,1] on the scale above (for flat: your '
        "confidence that no viable thesis exists)\n"
        '  "edge":          number in [0,1], expected fractional favorable '
        "move over the horizon\n"
        '  "target_view":   expected percent move if the thesis works, a '
        'string like "+15 percent"\n'
        '  "horizon_weeks": integer, expected weeks for the thesis to play out\n'
        '  "invalidation":  one sentence, the observable condition that would '
        "prove the thesis wrong\n"
        "Do not include markdown, code fences, or any text outside the JSON "
        "object."
    )


def prompt_mode(state: dict) -> str:
    """The prompt mode for a state dict: long_term or short_term.

    Callers set state["mode"]. Legacy research states carried mode
    deep_research, which is the long-term question, so it maps there rather
    than silently falling back to short-term.
    """
    mode = str(state.get("mode", "short_term")).strip().lower()
    if mode in ("long_term", "deep_research"):
        return "long_term"
    return "short_term"


def system_prompt_for(state: dict, cfg_path: str | None = None) -> str:
    """The system prompt for this state's mode, threshold from config.

    The disclosed threshold is the gate the answer actually feeds: the
    council_min_confidence floor for the short-term question, the satellite's
    research_conviction_threshold for the multi-week thesis.
    """
    if prompt_mode(state) == "long_term":
        return long_term_system(research_conviction_threshold(cfg_path))
    return short_term_system(council_min_confidence(cfg_path))
