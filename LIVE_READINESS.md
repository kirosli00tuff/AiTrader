# Live Readiness

This file tracks what must be true before a capability trades with real money. It
is documentation, not a switch. Live trading is off by default and sits behind
the in-app approval gate. Nothing here enables live.

## Global-session equity rotation

Global-session equity rotation lets the equity sleeve follow the open regional
market, Asia then London then NY, trading each region's equities during its
session. Regional exchange hours are real and non-overlapping, so following the
open session is a real strategy. It requires global venue access.

Status: SCAFFOLDED, DISABLED. Built as a config-driven regional session model
plus a venue-capability gate. It ships off because the paper venue Alpaca is
US-only and cannot reach Asian or European exchanges.

The standing safety rule: the engine only evaluates and trades an equity region
when a connected venue can actually reach that region's exchange. Today only NY
(Alpaca US equities) is reachable, so only US equities trade during US hours,
exactly as now. An equity order for a region with no capable venue is refused
before it reaches any adapter, logged as `venue_unavailable_for_region`. No order
is ever routed to an exchange no connected venue can reach. This rule holds
whether or not the rotation flag is set. Crypto trades 24/7 and is never gated by
a regional session.

### IBKR unlocks it

IBKR is the venue that unlocks global session equity rotation. It reaches global
exchanges (US, Europe, Asia) that Alpaca cannot.

To enable global-session equity rotation, all of the following must be true:

- IBKR connected and authenticated with global market access. The operator runs
  and logs into IB Gateway locally, and `ibkr.connection_enabled` is on.
- Per-region equity whitelists populated. Fill `global_sessions.london_whitelist`
  and `global_sessions.asia_whitelist` (today placeholders, empty), and set each
  region's `*_venue_available` true only once IBKR can actually reach it.
- The rotation flag on. Set `global_sessions.global_equity_rotation_enabled: true`.

It stays off until the operator is deliberately live on IBKR with global access.
No IBKR global routing is wired yet. Adding it later is a venue mapping, region to
IBKR exchange, in the config and the IBKR adapter, not an engine rewrite. The
regional session model (`config/regional_session.hpp`) and the engine gate are
already in place, so wiring IBKR is additive.

### Validation week is unaffected

The current validation week stays US-equities-plus-crypto, exactly as now: US
equities during US hours through Alpaca, crypto 24/7. The global machinery is
dormant. The startup block and run-state banner show the current global session
and which equity region is tradeable, so it is always clear that only US equities
trade and rotation is disabled.

## Real-time news-react adaptive layer (NOT BUILT, deferred, will ship gated)

The layer that interprets breaking news with an LLM and reacts to it is the NEXT
build. It is not in the codebase. Nothing in the discovery build reads a headline
and acts on it.

### What exists today, and what does not

Discovery uses Finnhub's PRE-COMPUTED news sentiment score as a cheap NUMBER in
the Stage A free pre-screen, one input among price, volume, volatility, momentum,
and gap. That is the cheap half of the value: it answers "does this instrument
have unusual news attention right now" for zero LLM cost, and it only ever moves
an instrument's RANK in a screen.

What does NOT exist:

- No live LLM news interpretation. No model reads an article in this build.
- No autonomous event-driven entry or exit. No path opens or closes a position in
  response to an event.
- No headline-triggered anything. Nothing enters on a raw headline.

### Why it is deferred

Reacting to news in real time is the highest-variance thing this system could do,
and it is the one place where a model's mistake becomes an immediate trade. It
needs its own gating, its own cost model, and its own evidence. Bolting it onto a
discovery build would ship all of that untested.

### The rule that holds when it does ship

Every entry routes through the full funnel and the RiskGate. A news event may
SURFACE a candidate. It may never place an order. The react layer ships disabled
behind its own flag, the same graduation the RL advisory and the research
satellite follow: build it, test it, leave it off, and let the operator turn it on
deliberately.

### The seam is already in place

The dynamic watchlist is event-sourced. Every mutation goes through one
`apply_event` path carrying an explicit source, journalled to `watchlist_event`.
The source `adaptive_react` is RESERVED: an event from it parses, is journalled
with `applied=0`, and is REFUSED with `source_not_enabled`. So the react layer
adds a source and a producer, not a rewrite. `tests/test_discovery_watchlist.py`
asserts that the reserved source stays refused.
