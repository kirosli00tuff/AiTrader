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
