"""Applying a routed interpretation. Where a decision becomes an effect.

adaptive/actions.py decided WHAT an interpretation is allowed to cause. This
module carries that out, and it is deliberately thin: every write goes through a
path that already exists and already has its own guard.

  a referral       -> discovery/watchlist.py::refer_from_adaptive, which lands it
                      as ``referred`` (not tradeable) and refuses entirely unless
                      the shaping flag is on.
  a prune          -> discovery/watchlist.py::remove_from_adaptive, same gate.
  a defensive act  -> adaptive/store.py::queue_defensive_action, which accepts
                      only a DefensiveAction, which cannot be aggressive.

There is no fourth branch. Nothing here opens or increases a position, and there
is no code to add that would let it: this module cannot reach the engine's entry
path at all, only its exit path (via the queue) and the watchlist.

DOUBLE-GATED ON PURPOSE. The flags are checked in ``route`` AND again inside
watchlist.apply_event. That is redundant and it stays redundant: the two checks
live in different packages, and a layer that can spend money and move positions
should not have a single point of "did we remember to check".
"""
from __future__ import annotations

import logging
import sqlite3

from discovery import watchlist

from .actions import RouteResult
from .store import queue_defensive_action

log = logging.getLogger("adaptive.shaping")


def apply_route(conn: sqlite3.Connection, result: RouteResult) -> dict:
    """Carry out one routed interpretation. Returns {"outcome", "reason"}.

    ``outcome`` is one of: referred, pruned, queued, dropped. It is recorded on
    the interpretation row, so every paid call has a visible consequence (or a
    visible lack of one) rather than vanishing.
    """
    if result.is_noop:
        return {"outcome": "dropped",
                "reason": result.dropped_reason or "no_effect"}

    if result.referral is not None:
        # The ceiling on an aggressive read. Offers the name to the funnel and
        # stops. No position, no traded-universe change, no order.
        r = watchlist.refer_from_adaptive(
            conn, result.referral.symbol,
            reason=f"adaptive: {result.referral.reason}"[:200])
        if not r.get("applied"):
            return {"outcome": "dropped", "reason": r.get("reason", "refused")}
        return {"outcome": "referred", "reason": "offered to the funnel"}

    if result.watchlist_remove:
        r = watchlist.remove_from_adaptive(
            conn, result.watchlist_remove,
            reason=f"adaptive: {result.dropped_reason or 'event'}"[:200])
        if not r.get("applied"):
            return {"outcome": "dropped", "reason": r.get("reason", "refused")}
        return {"outcome": "pruned", "reason": "removed from the watchlist"}

    if result.defensive is not None:
        queue_defensive_action(conn, result.defensive)
        return {"outcome": "queued",
                "reason": f"{result.defensive.action} queued for the engine"}

    # Unreachable: RouteResult sets at most one effect, and is_noop covers none.
    # Kept because "unreachable" and "unreached" are different claims, and this
    # one would otherwise fail silently if RouteResult ever grew a field.
    log.error("apply_route reached an unhandled RouteResult: %r", result)
    return {"outcome": "dropped", "reason": "unhandled_route"}
