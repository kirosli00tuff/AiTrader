"""The asymmetry. The most important tests in the adaptive layer.

One claim, tested from every angle worth trying:

    A live event can make the engine more cautious. It cannot make the engine
    more aggressive. Not with every flag on, not with a maximum-severity read,
    not with a model that explicitly says "buy", not with a headline written by
    an attacker.

If a future change breaks that, one of these fails.
"""
from __future__ import annotations

import sqlite3

import pytest

from adaptive import store
from adaptive.actions import (
    AGGRESSIVE_ACTIONS, CLASS_AGGRESSIVE, CLASS_DEFENSIVE, CLASS_NEUTRAL,
    CLASS_SHAPING, CLASS_UNKNOWN, DEFENSIVE_ACTIONS, DefensiveAction, classify,
    is_aggressive, is_defensive, route,
)

TS = "2026-07-16T09:30:00Z"


def _conn(tmp_path) -> sqlite3.Connection:
    c = sqlite3.connect(str(tmp_path / "a.db"))
    store.ensure_schema(c)
    return c


def _route(action: str, **kw):
    """Route with everything MAXIMALLY permissive: both flags on, severity 1.0,
    and a severity floor of 0. If the asymmetry holds here, it holds."""
    base = dict(symbol="SPY", action=action, severity=1.0, reason="test",
                min_severity=0.0, defensive_enabled=True, shaping_enabled=True)
    base.update(kw)
    return route(**base)


# --- The type refuses to hold an aggressive action --------------------------

@pytest.mark.parametrize("action", sorted(AGGRESSIVE_ACTIONS))
def test_defensive_action_refuses_to_construct_for_an_aggressive_action(action):
    """The load-bearing line. Not "should not be queued" but CANNOT BE BUILT.

    adaptive/store.py::queue_defensive_action accepts only this type, so if the
    constructor refuses, there is no value in the program that could reach the
    engine and open a position.
    """
    with pytest.raises(ValueError, match="refuses non-defensive"):
        DefensiveAction(symbol="SPY", action=action, reason="the news is good")


@pytest.mark.parametrize("action", ["watchlist_add", "none", "monitor", "",
                                    "buy", "BUY", "exit ", "nonsense"])
def test_defensive_action_refuses_everything_not_on_the_allowlist(action):
    """ALLOWLIST, not denylist. An action name this build has never heard of is
    refused by default. A future model, a typo, and an attack all land here."""
    with pytest.raises(ValueError):
        DefensiveAction(symbol="SPY", action=action, reason="x")


@pytest.mark.parametrize("action", sorted(DEFENSIVE_ACTIONS))
def test_defensive_action_constructs_for_every_defensive_action(action):
    a = DefensiveAction(symbol="SPY", action=action, reason="halted",
                        severity=0.9, ts=TS)
    assert a.action == action
    assert a.symbol == "SPY"


def test_defensive_action_is_immutable():
    """Frozen: nothing downstream can retarget an approved action at another
    symbol, or upgrade a trim into an exit, after it was built."""
    a = DefensiveAction(symbol="SPY", action="trim", reason="x")
    with pytest.raises(Exception):
        a.action = "exit"  # type: ignore[misc]
    with pytest.raises(Exception):
        a.symbol = "QQQ"  # type: ignore[misc]


def test_defensive_action_rejects_a_missing_symbol_and_bad_severity():
    with pytest.raises(ValueError, match="requires a symbol"):
        DefensiveAction(symbol="", action="exit", reason="x")
    with pytest.raises(ValueError, match="severity"):
        DefensiveAction(symbol="SPY", action="exit", reason="x", severity=1.5)


# --- The queue accepts nothing else -----------------------------------------

def test_the_queue_refuses_anything_that_is_not_a_defensive_action(tmp_path):
    """Defence in depth. Even holding a duck-typed lookalike, the writer refuses.

    This is what stops a future caller from building their own little object with
    action="open" and handing it over.
    """
    c = _conn(tmp_path)

    class Lookalike:
        symbol, action, reason, severity, event_id, ts = (
            "SPY", "open", "moon", 1.0, 1, TS)

    with pytest.raises(TypeError, match="only a DefensiveAction"):
        store.queue_defensive_action(c, Lookalike())  # type: ignore[arg-type]
    assert store.recent_actions(c) == []


def test_a_queued_action_lands_defensive_and_attributed(tmp_path):
    c = _conn(tmp_path)
    store.queue_defensive_action(c, DefensiveAction(
        symbol="SPY", action="exit", reason="trading halted", severity=0.95,
        event_id=7, ts=TS))
    rows = store.recent_actions(c)
    assert len(rows) == 1
    assert rows[0]["action"] == "exit"
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["source"] == "adaptive_react"
    assert rows[0]["event_id"] == 7


def test_every_row_the_queue_can_ever_hold_is_defensive(tmp_path):
    """The property the C++ consumer relies on, stated as a test.

    core/adaptive_actions.hpp re-checks this on read, but this asserts the
    writer's half: there is no sequence of legal calls that puts a non-defensive
    action name into the table.
    """
    c = _conn(tmp_path)
    for action in sorted(DEFENSIVE_ACTIONS):
        store.queue_defensive_action(c, DefensiveAction(
            symbol="SPY", action=action, reason="x", ts=TS))
    for action in sorted(AGGRESSIVE_ACTIONS):
        with pytest.raises(ValueError):
            store.queue_defensive_action(c, DefensiveAction(
                symbol="SPY", action=action, reason="x", ts=TS))
    assert {r["action"] for r in store.recent_actions(c)} == DEFENSIVE_ACTIONS


# --- Routing: the asymmetry ------------------------------------------------

@pytest.mark.parametrize("action", sorted(AGGRESSIVE_ACTIONS))
def test_an_aggressive_read_never_produces_an_engine_action(action):
    """THE CENTRAL TEST.

    Every flag on. Severity 1.0. Severity floor 0. The model explicitly says to
    buy. The result is a REFERRAL to the discovery funnel and nothing else: no
    defensive action, nothing queued, no position touched.
    """
    r = _route(action)
    assert r.action_class == CLASS_AGGRESSIVE
    assert r.defensive is None, "an aggressive read must never queue an action"
    assert r.referral is not None, "it becomes a funnel referral instead"
    assert r.referral.symbol == "SPY"
    assert not r.watchlist_remove


@pytest.mark.parametrize("action", sorted(AGGRESSIVE_ACTIONS))
def test_no_flag_combination_turns_an_aggressive_read_into_an_action(action):
    """There is no fourth flag, and no combination of the three that unlocks it.

    Exhaustive over the flag space: the aggressive branch never returns a
    defensive action in ANY of the four states.
    """
    for defensive_on in (True, False):
        for shaping_on in (True, False):
            r = _route(action, defensive_enabled=defensive_on,
                       shaping_enabled=shaping_on)
            assert r.defensive is None, (
                f"aggressive read produced an engine action with "
                f"defensive={defensive_on} shaping={shaping_on}")


def test_the_defensive_flag_does_not_unlock_aggressive_referrals():
    """A referral is a SHAPING act, so it answers to the shaping flag.

    Turning on the react half must not quietly grant the power to put new names
    in front of the funnel: those are different capabilities with different
    flags.
    """
    r = _route("open", defensive_enabled=True, shaping_enabled=False)
    assert r.referral is None
    assert r.defensive is None
    assert r.dropped_reason == "shaping_disabled"


def test_an_explicit_watchlist_add_is_a_referral_not_a_promotion():
    """Even when the model says "add this to the watchlist", it is only OFFERED.

    A referral is not tradeable. discovery/watchlist.py lands it as `referred`,
    and only a discovery pass can promote it to active.
    """
    r = _route("watchlist_add")
    assert r.action_class == CLASS_SHAPING
    assert r.referral is not None
    assert r.defensive is None


# --- Routing: the defensive half works -------------------------------------

@pytest.mark.parametrize("action", sorted(DEFENSIVE_ACTIONS))
def test_a_defensive_read_queues_when_the_react_flag_is_on(action):
    r = _route(action)
    assert r.action_class == CLASS_DEFENSIVE
    assert r.defensive is not None
    assert r.defensive.action == action
    assert r.referral is None


@pytest.mark.parametrize("action", sorted(DEFENSIVE_ACTIONS))
def test_a_defensive_read_does_nothing_while_the_react_flag_is_off(action):
    r = _route(action, defensive_enabled=False)
    assert r.defensive is None
    assert r.dropped_reason == "defensive_disabled"
    assert r.is_noop


def test_the_shaping_flag_does_not_unlock_defensive_actions():
    """The safe half being on must not grant the power to move a position."""
    r = _route("exit", defensive_enabled=False, shaping_enabled=True)
    assert r.defensive is None
    assert r.dropped_reason == "defensive_disabled"


def test_a_prune_is_a_shaping_action():
    r = _route("watchlist_remove")
    assert r.action_class == CLASS_SHAPING
    assert r.watchlist_remove == "SPY"
    assert r.defensive is None


# --- Routing: floors and unknowns ------------------------------------------

def test_a_weak_read_causes_nothing_in_either_direction():
    for action in ("exit", "open", "watchlist_remove"):
        r = _route(action, severity=0.2, min_severity=0.6)
        assert r.is_noop
        assert r.dropped_reason == "below_min_severity"


def test_an_unknown_action_is_dropped_not_guessed_at():
    """A model that invents an action name gets silence, not a best guess."""
    r = _route("liquidate_everything_now")
    assert r.action_class == CLASS_UNKNOWN
    assert r.is_noop
    assert r.dropped_reason == "unknown_action_class"


def test_a_neutral_read_is_the_cheap_common_case():
    for action in ("none", "hold", "monitor"):
        r = _route(action)
        assert r.action_class == CLASS_NEUTRAL
        assert r.is_noop
        assert r.dropped_reason == "no_action_suggested"


def test_a_dropped_route_always_says_why():
    """A silent no-op is indistinguishable from a bug."""
    for r in (_route("open", shaping_enabled=False),
              _route("exit", defensive_enabled=False),
              _route("exit", severity=0.1, min_severity=0.9),
              _route("gibberish"),
              _route("none")):
        assert r.is_noop
        assert r.dropped_reason, "every no-op must carry a reason"


# --- Classification --------------------------------------------------------

def test_the_three_classes_do_not_overlap():
    assert DEFENSIVE_ACTIONS & AGGRESSIVE_ACTIONS == set()
    for a in DEFENSIVE_ACTIONS:
        assert classify(a) == CLASS_DEFENSIVE and is_defensive(a)
        assert not is_aggressive(a)
    for a in AGGRESSIVE_ACTIONS:
        assert classify(a) == CLASS_AGGRESSIVE and is_aggressive(a)
        assert not is_defensive(a)


def test_classification_is_lenient_but_the_type_is_not():
    """classify() tolerates model sloppiness so a read is still UNDERSTOOD.

    The type does not tolerate it, so a sloppy string is never ACTED on: route()
    normalizes before it decides, and DefensiveAction takes only the exact name.
    That split keeps the audit trail honest without loosening the gate.
    """
    assert classify("  EXIT ") == CLASS_DEFENSIVE
    assert classify(" Open") == CLASS_AGGRESSIVE
    with pytest.raises(ValueError):
        DefensiveAction(symbol="SPY", action=" EXIT ", reason="x")
