"""The action taxonomy, and the asymmetry that is the point of this layer.

A live event can make the engine MORE CAUTIOUS directly. It can never make the
engine MORE AGGRESSIVE directly. That asymmetry is the whole safety argument for
reacting to news at all, so it is built as STRUCTURE here, not as a check that a
later caller has to remember to run.

Three action classes:

* DEFENSIVE (exit, trim, flag_for_review). Reduces or freezes exposure. May be
  queued for the engine, which applies it through the same native exit path it
  already uses. Gated on ``adaptive_react_defensive_enabled``.
* SHAPING (watchlist_add, watchlist_remove). Changes what is LOOKED AT, never
  what is held. Gated on ``adaptive_watchlist_shaping_enabled``.
* AGGRESSIVE (open, increase). Never reaches the engine from here. At most it
  becomes a funnel REFERRAL, which is a shaping action: the symbol is offered to
  the next discovery pass, and Stage A, Stage B, the four levels, and the
  RiskGate all still have to agree before anything is bought.

How the asymmetry is enforced, in order of strength:

1. ``DefensiveAction`` REFUSES TO CONSTRUCT for a non-defensive action. The queue
   writer (adaptive/store.py) accepts only that type. So there is no value that
   can be put on the engine's queue that opens or increases a position. Not
   "should not" but cannot: the constructor raises.
2. The classification is an ALLOWLIST. An unrecognized action class is dropped,
   never passed through. A future model that invents a new action name gets
   silence, not a trade.
3. ``route`` has no branch that returns an engine action for an aggressive class.
   The aggressive branch's only output is a referral.
4. The C++ consumer (core/adaptive_actions.hpp) re-checks the allowlist on read
   and never calls the entry path. Two independent sides both have to be wrong.

tests/test_adaptive_actions.py asserts each of these, including the constructor
refusal and the "misread headline cannot buy" property.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- The taxonomy -----------------------------------------------------------

# Reduces or freezes exposure. The ONLY class the engine will act on directly.
DEFENSIVE_ACTIONS = frozenset({"exit", "trim", "flag_for_review"})

# Changes what is looked at, never what is held. Safe half.
SHAPING_ACTIONS = frozenset({"watchlist_add", "watchlist_remove"})

# Increases exposure. NEVER direct, from any source, under any flag. There is no
# flag that turns this into an engine action, because that code path is not
# written. The only honest response to one of these is to offer the name to the
# funnel and let the funnel decide.
AGGRESSIVE_ACTIONS = frozenset({"open", "increase"})

# Explicitly "do nothing". A model that reads an event and concludes it does not
# matter is the common case and must be cheap and silent.
NEUTRAL_ACTIONS = frozenset({"none", "hold", "monitor"})

CLASS_DEFENSIVE = "defensive"
CLASS_SHAPING = "shaping"
CLASS_AGGRESSIVE = "aggressive"
CLASS_NEUTRAL = "neutral"
CLASS_UNKNOWN = "unknown"

# The watchlist source this layer writes under. Reserved by discovery/watchlist.py
# since the discovery build; refused there unless the shaping flag is on.
REACT_SOURCE = "adaptive_react"


def classify(action: str) -> str:
    """Which class an action name belongs to. ALLOWLIST: anything unrecognized
    is ``unknown`` and is dropped by the caller, never treated as safe."""
    a = (action or "").strip().lower()
    if a in DEFENSIVE_ACTIONS:
        return CLASS_DEFENSIVE
    if a in SHAPING_ACTIONS:
        return CLASS_SHAPING
    if a in AGGRESSIVE_ACTIONS:
        return CLASS_AGGRESSIVE
    if a in NEUTRAL_ACTIONS:
        return CLASS_NEUTRAL
    return CLASS_UNKNOWN


def is_defensive(action: str) -> bool:
    return classify(action) == CLASS_DEFENSIVE


def is_aggressive(action: str) -> bool:
    return classify(action) == CLASS_AGGRESSIVE


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- The only type the engine queue accepts ---------------------------------

@dataclass(frozen=True)
class DefensiveAction:
    """A request that the engine reduce or freeze exposure. Immutable.

    This type is the gate. adaptive/store.py::queue_defensive_action takes a
    DefensiveAction and nothing else, so the set of things that can reach the
    engine is exactly the set of values this constructor permits. It permits no
    aggressive action: constructing one raises ValueError rather than returning
    something a caller might forget to check.
    """
    symbol: str
    action: str
    reason: str
    severity: float = 0.0
    event_id: int = 0
    ts: str = field(default_factory=_utcnow_iso)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("DefensiveAction requires a symbol")
        if self.action not in DEFENSIVE_ACTIONS:
            # The load-bearing line of this module. An aggressive or unknown
            # action cannot become a queued engine action by any route, because
            # the value cannot be built in the first place.
            raise ValueError(
                f"DefensiveAction refuses non-defensive action {self.action!r}. "
                f"Allowed: {sorted(DEFENSIVE_ACTIONS)}. Aggressive actions route "
                f"through the discovery funnel, never through this queue.")
        if not 0.0 <= float(self.severity) <= 1.0:
            raise ValueError("DefensiveAction severity must be within 0..1")


# --- Routing ----------------------------------------------------------------

@dataclass(frozen=True)
class Referral:
    """An aggressive read, defused into a funnel referral.

    This is what "route it through the funnel" means concretely: the symbol is
    offered to the next discovery pass as a Stage-A input. It is not on the
    traded universe, no position exists, and none will unless Stage A ranks it,
    Stage B gates it, the four levels evaluate it, and the RiskGate approves the
    resulting order. A misread headline buys a screening slot, not an asset.
    """
    symbol: str
    reason: str


@dataclass(frozen=True)
class RouteResult:
    """What one interpretation is allowed to cause. At most one of these is set.

    ``dropped_reason`` is always populated when nothing happened, so a no-op is
    explainable rather than silent. Every route is journalled by the caller.
    """
    action_class: str
    defensive: DefensiveAction | None = None
    watchlist_remove: str = ""
    referral: Referral | None = None
    dropped_reason: str = ""

    @property
    def is_noop(self) -> bool:
        return (self.defensive is None and self.referral is None
                and not self.watchlist_remove)


def route(*, symbol: str, action: str, severity: float, reason: str,
          min_severity: float, defensive_enabled: bool, shaping_enabled: bool,
          event_id: int = 0, ts: str = "") -> RouteResult:
    """Turn one LLM interpretation into the most it is permitted to cause.

    The flags are passed in rather than read here so this stays a pure function
    the tests can drive through every combination. The caller (adaptive/run.py)
    reads them from adaptive/settings.py.

    Note the shape of the aggressive branch: it does not consult
    ``defensive_enabled``, and there is no third flag it could consult. An
    aggressive read produces a referral or nothing, whatever the flags say.
    """
    cls = classify(action)

    if cls == CLASS_UNKNOWN:
        return RouteResult(cls, dropped_reason="unknown_action_class")
    if cls == CLASS_NEUTRAL:
        return RouteResult(cls, dropped_reason="no_action_suggested")

    # Severity floor applies to everything that would DO something. A weak read
    # is logged and dropped, whichever direction it points.
    if float(severity) < float(min_severity):
        return RouteResult(cls, dropped_reason="below_min_severity")

    if cls == CLASS_AGGRESSIVE:
        # The asymmetry, in one branch. An aggressive read never returns a
        # defensive action and never touches the engine queue. The strongest
        # thing it can do is ask the funnel to look, which is a SHAPING action
        # and so is gated on the shaping flag, not on any react flag.
        if not shaping_enabled:
            return RouteResult(cls, dropped_reason="shaping_disabled")
        return RouteResult(cls, referral=Referral(symbol, reason))

    if cls == CLASS_SHAPING:
        if not shaping_enabled:
            return RouteResult(cls, dropped_reason="shaping_disabled")
        if action == "watchlist_add":
            # Even an explicit "add this" is a referral, not a promotion: it
            # enters as a funnel candidate, not onto the traded universe.
            return RouteResult(cls, referral=Referral(symbol, reason))
        return RouteResult(cls, watchlist_remove=symbol)

    # Defensive.
    if not defensive_enabled:
        return RouteResult(cls, dropped_reason="defensive_disabled")
    return RouteResult(cls, defensive=DefensiveAction(
        symbol=symbol, action=action, reason=reason,
        severity=float(severity), event_id=event_id,
        ts=ts or _utcnow_iso()))
