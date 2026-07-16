"""The cheap materiality trigger: the free filter that keeps this layer affordable.

A normal news day produces thousands of headlines about a watchlist of a few
dozen names. Reading all of them with a model would cost more than the account
earns and would add nothing: the overwhelming majority are routine coverage,
price recaps, and syndicated repeats.

So EVERY event passes through this filter first, and it spends nothing. No
network call, no token, no model. It is keyword matching, sentiment magnitude,
and event type over data the poll already fetched. Only what survives is allowed
to reach the paid interpretation stage, and even then a budget caps it.

The filter is deliberately CRUDE. It is not trying to understand the news; that
is the model's job, later, on the few that get through. It is trying to answer
one much easier question for free: "is there any chance this matters?" A crude
filter with a generous threshold is the right tool, because the cost of a false
positive is one Haiku call and the cost of a false negative is missing an event.
That asymmetry is why the bar is set low, not high.

Everything it drops is still STORED (adaptive/store.py), so the claim "the vast
majority is dropped for free" stays checkable rather than being folklore.
"""
from __future__ import annotations

from dataclasses import dataclass

# Event types that are material by their nature, whatever the wording. These are
# structural facts about an instrument, not opinions about it.
HIGH_IMPACT_TYPES = frozenset({
    "earnings", "guidance", "merger", "acquisition", "halt", "delisting",
    "bankruptcy", "regulatory", "litigation", "offering", "split",
})

# A held instrument gets a LOWER bar than a watchlist name. This is safe by
# construction: the only thing an event about a held name can cause is a
# defensive action, so escalating more readily on names we own can make the
# engine more cautious and can never make it more aggressive. Erring toward
# reading the news about what you already own is the cheap direction to err.
HELD_SENTIMENT_DISCOUNT = 0.15


@dataclass(frozen=True)
class MaterialityVerdict:
    """Why one event was kept or dropped. Always carries a reason: a silent drop
    is indistinguishable from a bug."""
    material: bool
    reason: str
    score: float = 0.0

    @property
    def dropped(self) -> bool:
        return not self.material


def _text_of(event: dict) -> str:
    return f"{event.get('headline', '')} {event.get('summary', '')}".lower()


def matched_keywords(event: dict, keywords: list[str]) -> list[str]:
    """Every configured keyword present in the headline or summary."""
    text = _text_of(event)
    return [k for k in keywords if k and k in text]


def assess(event: dict, *, keywords: list[str],
           min_sentiment: float) -> MaterialityVerdict:
    """Decide whether one event is worth a model's attention. Costs nothing.

    Any single trigger is enough. They are OR'd, not AND'd, because they detect
    different things: a keyword catches wording, sentiment catches tone, and the
    event type catches a structural fact that may be reported in flat language. A
    halt announced in a dull sentence is still a halt.
    """
    symbol = (event.get("symbol") or "").strip()
    held = bool(event.get("held"))
    sentiment = abs(float(event.get("sentiment", 0.0) or 0.0))
    threshold = max(0.0, float(min_sentiment) -
                    (HELD_SENTIMENT_DISCOUNT if held else 0.0))

    etype = (event.get("event_type") or "").strip().lower()
    if etype in HIGH_IMPACT_TYPES:
        return MaterialityVerdict(True, f"event_type:{etype}", 1.0)

    hits = matched_keywords(event, keywords)
    if hits:
        return MaterialityVerdict(True, f"keyword:{hits[0]}", 0.9)

    if threshold > 0.0 and sentiment >= threshold:
        return MaterialityVerdict(
            True, f"sentiment:{sentiment:.2f}>={threshold:.2f}", sentiment)

    # An event with no symbol only reaches here from the general-market feed. It
    # cannot be attributed to a position or a candidate, so it is kept only when
    # a trigger above already fired. Saying so explicitly makes the general feed
    # cheap by default rather than by accident.
    if not symbol:
        return MaterialityVerdict(False, "general_news_not_loud", sentiment)

    # The common case, by a wide margin: routine coverage of a name we watch.
    return MaterialityVerdict(False, "no_trigger", sentiment)
