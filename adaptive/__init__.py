"""Adaptive real-time layer: reads live events, and is allowed to be careful.

Two halves, flagged separately, all three flags default FALSE.

OBSERVE AND SHAPE. A Finnhub poller (once a minute) pulls news for held names,
watchlist names, and the general market. A free filter drops the vast majority
with no model involved. What survives gets one cheap structured read. The result
may add a funnel referral or prune the watchlist: it changes what the system
LOOKS AT, never what it holds.

REACT. A read may also queue a DEFENSIVE action (trim, exit, flag for review),
which the engine applies through the same native exit path it already uses.

THE ASYMMETRY IS THE POINT. A live event can make this system more cautious
directly. It can never make it more aggressive directly. There is no flag for
that, because there is no code path for it: an aggressive read becomes a funnel
REFERRAL, and Stage A, Stage B, the four levels, and the RiskGate all still have
to agree before anything is bought. A misread headline can cost a screening slot
and a fraction of a cent. It cannot cost a position.

That is enforced in three independent places, in two languages:
  adaptive/actions.py       DefensiveAction refuses to CONSTRUCT if not defensive
  discovery/watchlist.py    an adaptive add lands as `referred`, not tradeable
  core/adaptive_actions.hpp the engine re-checks the allowlist on read and never
                            calls the entry path

Everything here ships DISABLED. With the flags off no poll runs, no client is
constructed, no key is read, no socket opens, and the engine behaves exactly as
it does today. See CONTEXT.md and LIVE_READINESS.md.

NAMING. Not to be confused with the LEARNING tuner, which is also called
"adaptive" (config block ``adaptive:``, learning/adaptive_tuner). That one tunes
factor weights from closed-trade PnL. This one reads news. The config block here
is ``adaptive_realtime:``.
"""
