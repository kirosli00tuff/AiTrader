"""EXPERIMENT.md transcribed into constants. THE SINGLE SOURCE OF TRUTH.

The specification was ACCEPTED by the operator on 2026-07-28, before any
collection. From that point it is CLOSED: this module transcribes it and does
not revise it. Every number here is quoted from EXPERIMENT.md and carries the
section it came from, so a reader can check the transcription without trusting
it.

`tests/test_news_experiment_spec.py` reads EXPERIMENT.md and asserts the prompt
below is byte-identical to the fenced block in Task 3. That test is what makes
this file a transcription rather than a second opinion.

WHAT THIS MODULE DOES NOT DO: it holds no threshold that gates anything. The
strength field is recorded and never gated (Task 3), and nothing in this
package reaches a trading decision.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

# --- Provenance of the record itself (Task 8) -------------------------------

SPEC_VERSION = "EXPERIMENT.md@amendment-3-accepted-2026-07-28"

# --- The universe rule (Task 2) ---------------------------------------------

# THE RULE ID IS QUOTED VERBATIM AND IT IS STALE. Task 2 names the rule
# `U-NEWS-ADV2M-65M-stk-w60-m40-p5-s400`, whose `p5` encodes the 5.00 USD price
# floor that AMENDMENT 2 replaced with 10.00. The floor used everywhere else in
# the document, including every measured table, is 10.00. Recording the id as
# written is implementing the specification as written; the floor is recorded
# separately on every row (`price_floor_at_formation`) so no consumer has to
# trust the label. Reported to the operator rather than silently relabelled.
RULE_ID = "U-NEWS-ADV2M-65M-stk-w60-m40-p5-s400"

WINDOW_SESSIONS = 60            # Task 2 rule step 2
MIN_WINDOW_BARS = 40            # Task 2 rule step 3
MIN_MEDIAN_CLOSE = 10.00        # AMENDMENT 2, derived from the tick's cost
ADV_BAND_LOW = 2_070_000.0      # Task 2, measured tier-4 ADV floor
ADV_BAND_HIGH = 65_300_000.0    # Task 2, measured tier-2 ADV floor
SAMPLE_TOTAL = 400              # Task 2 rule step 5
SAMPLE_PER_STRATUM = 100        # Task 2, "100 symbols sampled per stratum"

# Four strata of EQUAL WIDTH IN LOG ADV with FIXED thresholds (Task 2). The
# boundaries are constants, not quantiles, so a stratum means the same thing at
# every formation date. Quoted from the restratified table.
STRATA: tuple[tuple[str, float, float], ...] = (
    ("S1", 27_553_544.0, 65_300_000.0),
    ("S2", 11_626_306.0, 27_553_544.0),
    ("S3", 4_905_757.0, 11_626_306.0),
    ("S4", 2_070_000.0, 4_905_757.0),
)

# --- The model (Task 3, AMENDED by Amendment 3) -----------------------------

MODEL_ID = "claude-haiku-4-5"    # one of CLAUDE.md's four approved strings
TEMPERATURE = 0                  # confirmed acceptable on this model
MAX_TOKENS = 60                  # response is ~35 tokens, 60 leaves headroom

# Published rates, USD per 1M tokens (Task 3, "Pricing and cost per call").
PRICE_INPUT_PER_MTOK = 1.00
PRICE_OUTPUT_PER_MTOK = 5.00
PRICE_CACHE_READ_PER_MTOK = 0.10
PRICE_CACHE_WRITE_PER_MTOK = 1.25

# Task 3 projects $0.000465 per call at ~290 input and ~35 output tokens. The
# demonstration reports measured cost against this figure.
PROJECTED_COST_PER_CALL = 0.000465

# Haiku 4.5's minimum cacheable prefix. The system block is ~270 tokens, so
# nothing caches and `cached_input_tokens` is expected 0 on every row. The
# request still SENDS cache_control: without it the field would read 0 by
# construction and the drift canary would be dead rather than quiet.
MIN_CACHEABLE_PREFIX_TOKENS = 4096

# --- The exact prompt, byte for byte (Task 3) -------------------------------

SYSTEM_PROMPT = """You judge whether a news headline is likely to move a US-listed stock's price by the next market close.

Reply with exactly one JSON object and nothing else, in this form:
{"judgment": "POSITIVE", "strength": 3, "reason": "<at most 20 words>"}

judgment must be exactly one of POSITIVE, NEGATIVE, NEUTRAL.

POSITIVE means you expect this stock to outperform the broad market by the next close.
NEGATIVE means you expect this stock to underperform the broad market by the next close.
NEUTRAL means you expect no material difference either way.

strength must be an integer from 1 to 5. It says how strongly this headline points in the direction you chose.
1 means the headline barely tilts the odds, and a move the other way would not surprise you.
5 means you would be surprised if this stock did not move in the stated direction by the next close.
2, 3 and 4 fall between those two points.
When judgment is NEUTRAL, set strength to 1.

You are given the ticker and the headline text. You have no price, no chart, no volume, no indicator, and no other information, and you must not assume any.

Do not answer NEUTRAL to be safe. Answer NEUTRAL only when the headline genuinely carries no directional information about this company."""

USER_PROMPT_TEMPLATE = """TICKER: {ticker}
HEADLINE: {headline}"""


def prompt_sha256() -> str:
    """Hash of the exact system block (Task 8 `prompt_sha256`).

    Recorded on every row so a prompt change mid-collection is detectable from
    the data rather than from the commit log.
    """
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def build_user_prompt(ticker: str, headline: str) -> str:
    """The variable block. The headline is raw text, stripped of leading and
    trailing whitespace and otherwise unmodified: no truncation, no cleaning
    (Task 3)."""
    return USER_PROMPT_TEMPLATE.format(ticker=ticker, headline=headline.strip())


# --- Horizon and the actionable moment (Task 4) -----------------------------

MIN_DELAY_MINUTES = 20          # provisional and conservative, Task 4
REGULAR_OPEN = "09:30"          # America/New_York, Task 4
REGULAR_CLOSE = "16:00"         # the calendar's own close is authoritative
MARKET_TZ = "America/New_York"

ANCHOR_SAME_SESSION_CLOSE = "same_session_close"
ANCHOR_NEXT_SESSION_OPEN = "next_session_open"

# --- De-duplication (Task 5) ------------------------------------------------

DEDUP_WINDOW_HOURS = 24         # near-identical headlines for one ticker
STORY_GROUP_WINDOW_HOURS = 24   # one story naming several tickers

# --- The absent-input rule (Task 7) -----------------------------------------

STATE_NO_NEWS = "no_news"
STATE_JUDGED = "judged"
STATE_MODEL_FAILED = "model_failed"
STATE_EXCLUDED_PRE_CALL = "excluded_pre_call"   # AMENDMENT 4
STATE_SOURCE_FAILED = "source_failed"
STATES = (STATE_NO_NEWS, STATE_JUDGED, STATE_MODEL_FAILED,
          STATE_EXCLUDED_PRE_CALL, STATE_SOURCE_FAILED)

# THE ONE QUESTION THAT SEPARATES THE TWO FAILURE STATES: was a request sent to
# the provider? `model_failed` means yes and it did not return a usable verdict.
# `excluded_pre_call` means no, because the row was never eligible for one.
#
# THEY ANSWER DIFFERENT QUESTIONS AND MUST NEVER BE SUMMED. `model_failed` is an
# OPERATIONAL HEALTH metric: it rises when the provider is unwell and the
# response is to go and look at the provider. `excluded_pre_call` is a SAMPLE
# COMPOSITION metric: it rises when the source serves headlines the design
# cannot use, which means the effective sample is smaller than the raw headline
# count and Task 5's power arithmetic is optimistic. A combined rate answers
# neither. `error_class` remains the cause axis inside each.
ERROR_CLASSES_MODEL_FAILED = ("transport", "timeout", "http_status",
                              "unparseable", "exhausted")
ERROR_CLASSES_PRE_CALL = ("no_publication_time", "clock_inconsistent",
                          "duplicate_headline", "calendar_exhausted")

EXCLUSION_NONE = ""
EXCLUSION_NO_PUBLICATION_TIME = "no_publication_time"
EXCLUSION_CLOCK_INCONSISTENT = "clock_inconsistent"
EXCLUSION_SYMBOL_DID_NOT_TRADE = "symbol_did_not_trade"
EXCLUSION_DUPLICATE_HEADLINE = "duplicate_headline"
EXCLUSION_DAY_EXCLUDED = "day_excluded_source_failures"
# The exchange calendar does not reach far enough to resolve this headline's
# actionable moment. THE CALENDAR'S IGNORANCE IS NOT THE SYMBOL'S SILENCE, and
# conflating them is why this constant exists: the code used to report
# `symbol_did_not_trade`, which names a fact about the market when the fact is
# about our own data. A symbol may have traded perfectly on a session we had
# simply not loaded.
EXCLUSION_CALENDAR_EXHAUSTED = "calendar_exhausted"
# `delay_rolled` REMOVED by AMENDMENT 4. Task 4 scores a rolled headline and
# Task 8 could not simultaneously exclude it. The operator confirmed Task 4:
# the 20-minute delay moves a headline to a moment it could actually have been
# traded, it does not discard it, and excluding late headlines would
# systematically remove those arriving near the close. The roll is recorded on
# its own `delay_rolled` boolean and `exclusion_reason` stays empty.
EXCLUSION_REASONS = (
    EXCLUSION_NONE,
    EXCLUSION_NO_PUBLICATION_TIME,
    EXCLUSION_CLOCK_INCONSISTENT,
    EXCLUSION_SYMBOL_DID_NOT_TRADE,
    EXCLUSION_DUPLICATE_HEADLINE,
    EXCLUSION_DAY_EXCLUDED,
    EXCLUSION_CALENDAR_EXHAUSTED,
)

# SETTLED BY AMENDMENT 4, with the operator's explicit approval. Stage 2 found
# that Task 4 scores a delay-rolled headline while Task 8 listed `delay_rolled`
# as an exclusion reason, and reported the contradiction rather than resolving
# it under a binding specification. The operator confirmed TASK 4 IS CORRECT:
# the 20-minute minimum delay exists to move a headline to a moment at which it
# could actually have been traded, not to discard it, and excluding late
# headlines would systematically remove those arriving near the close, a
# non-random slice of the sample.
#
# A rolled headline is SCORED. `exclusion_reason` stays empty and the roll is
# recorded on the `delay_rolled` boolean. There is no longer a flag here,
# because there is no longer a choice to make.

# Source-failure thresholds (Task 7, "How absence is visible").
SOURCE_FAILED_CRITICAL_FRACTION = 0.05     # emits a CRITICAL event
SOURCE_FAILED_DAY_EXCLUDE_FRACTION = 0.20  # the day leaves the cluster count

# --- Scoring (Task 5) -------------------------------------------------------

JUDGMENT_POSITIVE = "POSITIVE"
JUDGMENT_NEGATIVE = "NEGATIVE"
JUDGMENT_NEUTRAL = "NEUTRAL"
JUDGMENTS = (JUDGMENT_POSITIVE, JUDGMENT_NEGATIVE, JUDGMENT_NEUTRAL)

STRENGTH_MIN = 1
STRENGTH_MAX = 5
STRENGTH_ON_NEUTRAL = 1         # fixed, Task 3 "What strength means for NEUTRAL"

# A NEUTRAL rate above this is itself a reportable failure of the design
# (Task 5, "NEUTRAL verdicts are not scored").
NEUTRAL_RATE_REPORTABLE_FAILURE = 0.80

# Recorded return horizons (Task 8). Only `ret_1session` is scored; the others
# enable pre-registered follow-ups without a second collection.
RETURN_HORIZONS = (1, 2, 5, 10)


@dataclass(frozen=True)
class Stratum:
    name: str
    adv_low: float
    adv_high: float

    def contains(self, adv: float) -> bool:
        """Half-open on the low side so the boundaries partition the band with
        no symbol in two strata. S4's low bound is the band floor and is
        inclusive; every other boundary belongs to the stratum above it."""
        if self.name == "S4":
            return self.adv_low <= adv <= self.adv_high
        return self.adv_low < adv <= self.adv_high


STRATUM_OBJECTS = tuple(Stratum(n, lo, hi) for n, lo, hi in STRATA)


def stratum_for(adv: float) -> str | None:
    """The stratum an ADV falls in, or None when it is outside the band."""
    for s in STRATUM_OBJECTS:
        if s.contains(adv):
            return s.name
    return None
