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

## Real-time news-react adaptive layer (BUILT 2026-07-16, SHIPS DISABLED)

The layer that reads live events and reacts to them is built. It ships behind
three flags, all default false. With them false the engine behaves exactly as it
did before: no poll runs, no client is constructed, no key is read, no socket
opens, no token is spent, and no action reaches the engine. Verified: a
12000-step run with the flags off is behaviorally identical to the pre-adaptive
baseline (272 trades, 136 closed, same symbols, zero adaptive rows).

Discovery still uses Finnhub's PRE-COMPUTED sentiment as a cheap NUMBER in its
Stage A pre-screen. That is unchanged and unrelated: it moves an instrument's
RANK in a screen and costs no tokens.

This section is about what must be true before the react layer is turned ON.

### The asymmetry is the reason this layer is allowed to exist

A live event can make the engine MORE CAUTIOUS directly. It can never make the
engine MORE AGGRESSIVE directly.

- DEFENSIVE (trim, exit, flag for review) may act directly, through the same
  native exit path the engine already uses. Not a bypass, and not a new order
  path.
- AGGRESSIVE (open, increase) has NO event path at all. A bullish read becomes a
  watchlist REFERRAL: the symbol is offered to the discovery funnel, and Stage A,
  Stage B, the four levels, and the RiskGate all still have to agree before
  anything is bought.

There is no flag for event-driven entry, because there is no code path to enable.
That is enforced in three independent places, in two languages:

| Where | What it refuses |
| --- | --- |
| `adaptive/actions.py` | `DefensiveAction` REFUSES TO CONSTRUCT for a non-defensive action. The queue writer accepts only that type, so no value exists that could queue an entry. |
| `discovery/watchlist.py` | An adaptive add lands as `referred`, never `active`. The status is derived from the SOURCE, not requested, so no caller can promote a symbol onto the traded universe. |
| `core/adaptive_actions.hpp` | `DefensiveKind` has three enumerators and none is aggressive. `parse_defensive_kind` is an allowlist returning nullopt for everything else. The engine's consumer never calls the entry path. |

A misread headline costs a screening slot and a fraction of a cent. It cannot
cost a position. `tests/test_adaptive_actions.py` and
`tests/test_adaptive_react.cpp` assert this from both sides, including with every
flag on and severity 1.0.

### What must be true before enabling it

The three flags graduate independently, cheapest and safest first. Each is a
separate deliberate decision, and the order is not arbitrary: the feed is the
master, and the two halves below it are inert without it.

**1. `adaptive_news_feed_enabled` (observe).** Needs a Finnhub key (feed) and an
Anthropic key (event reads). Turning this on alone is the safe way to evaluate
the layer: it spends the adaptive budget and changes NOTHING else. No position
moves, no watchlist entry changes. Run it here first and read the Adaptive page.

Confirm the Finnhub key on the **Health** page before enabling, and read that row
rather than the prerequisite check. The prerequisite asks only whether a value
RESOLVES, which a mistaken paste passes while every real call fails. The Health
row makes one real call and reports `working`, `bad key (HTTP 401)`, or `rate
limited`. Verified working 2026-07-16 (`one quote ok`, about 108ms).

Before going further, confirm from that page:

- The free filter is actually dropping the vast majority. If `events_dropped_free`
  is not overwhelmingly the largest number on the page, the thresholds are wrong
  and the layer is not affordable. Tune `materiality_min_sentiment` first. Read
  `events_unread_budget` next to it: that is material events the budget could not
  afford, a different problem with a different fix (raise the budget or tighten
  the filter). The two are reported apart on purpose, because folding budget
  skips into "dropped free" would flatter the filter exactly on the busy days
  when it is performing worst.
- Spend is inside the budget and matches expectation (worst case 20 reads/day at
  about $0.02 = about $0.40/day, SEPARATE from and additive to the discovery and
  trading budgets).
- The interpretations read sensibly. Look specifically at what the model does with
  ambiguous headlines, and at anything it classed `aggressive`: those are the
  reads that would have been trades in a naive design.

**2. `adaptive_watchlist_shaping_enabled` (shape).** Requires the feed. Lets a
read refer a candidate to the funnel and prune the watchlist. Still opens no
position: a referral is not tradeable and only a funnel pass can promote it.
Before enabling, confirm the discovery funnel is itself enabled and healthy,
otherwise referrals accumulate with nothing to screen them (they expire on
`watchlist_stale_hours`).

**3. `adaptive_react_defensive_enabled` (react).** Requires the feed. This is the
only flag that lets a live event change a position. Before enabling:

- Watch the layer in observe mode long enough to see real events on names you
  actually hold, and check what it WOULD have done. An interpretation logged
  `defensive` with this flag off is a dry run you get for free.
- Satisfy yourself the severity floor is right (`action_min_severity`, default
  0.60). Too low and routine bad news trims positions; too high and a real halt
  is ignored.
- Understand the trim size (`defensive_trim_fraction`, default 0.50) and the
  staleness window (`action_max_age_seconds`, default 300). An action older than
  the window is refused, so news that arrived while the engine was down never
  moves a position on resume.

### What is deliberately still not built

- No aggressive event path, ever. Not deferred: refused as a design.
- No per-article sentiment. Finnhub's free tier gives an aggregate per symbol,
  cached hard, so the sentiment trigger is a coarse magnitude and nothing more.
- No cross-event reasoning. Each event is read alone. Two related headlines are
  two independent reads, not a narrative.
- The engine consumes actions on its LOOP iteration rather than on a bar close, so
  a defensive exit does not wait for a bar. It is still bounded by the loop
  interval: this is not a low-latency reaction and must not be relied on as one.
