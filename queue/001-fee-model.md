# QUEUE 001: Cost every fill and every backtest from published live fee schedules

Model: Opus. Status: PENDING. Written by chat Claude, 2026-07-26.

Read CLAUDE.md, PROGRESS.md, CONTEXT.md, and RETURN.md before starting, including the
2026-07-25 P26 no-edge research, the 2026-07-26 P28 hypothesis session, and the backtest
harness sessions. Log this prompt to RETURN.md before work begins. Do not touch RiskGate
logic, the live-trading gate, or the adaptive limit-weakening invariant. Live trading stays
off. Do not change any Level 1 risk value, any strategy parameter, any threshold, or any
entry or exit logic.

Run autonomously without stopping for confirmation. Pick the safest option when ambiguous,
note it in RETURN.md, and continue. Commit and push before ending.

Writing rules for docs and comments. Clear, spartan, active voice. No em dashes. No
semicolons. No filler adjectives.

## THE PROBLEM

Every result this project has produced was costed at roughly 2 bp per round trip, a figure
derived from Alpaca paper fills. Alpaca's published live crypto schedule is volume-tiered
maker/taker starting at 0.15 percent maker and 0.25 percent taker for accounts under 100,000
USD of 30-day crypto volume. Position sizing at 0.5 percent risk on 100,000 equity keeps this
account in the base tier indefinitely, and the engine sends market orders, which are taker.
So a live crypto round trip costs roughly 50 bp, not 2. Alpaca US equities are commission
free, so the equity round trip is spread plus small regulatory fees, roughly 1 to 2 bp. The
costs are inverted by asset class and the system has treated them as identical. The paper
venue's fee modeling is not a promise of live fees and must never again be the source of
truth.

## TASK 1: AN EXPLICIT FEE MODEL, SOURCED FROM LIVE SCHEDULES

Build a fee model that both the engine and the research harness consult, expressing cost per
venue, per asset class, and per order type: crypto maker and taker rates, equity commission
and regulatory fees, and a spread component. Values come from published live schedules,
recorded with their source and the date read, never inferred from a fill. Verify Alpaca's
current published crypto tier table and equity fee disclosure and record what you find,
including the volume thresholds, so a tier change is visible rather than silent. Do the same
for IBKR's schedule on the live path, and note explicitly where a rate could not be
established rather than guessing. Report every rate, its source, and its date.

## TASK 2: PAPER FILLS GET COSTED BY THE MODEL, NOT BY THE SIMULATOR

Every paper fill is costed by this model rather than by whatever the paper venue charges.
Record both figures on each fill: the model's cost and the venue's reported cost, so the
divergence is measurable rather than assumed. Report the measured divergence across the
existing recorded fills. Do not alter any historical row, add the model's figure alongside.

## TASK 3: THE HARNESS PRICES WHAT LIVE TRADING WOULD PAY

The backtest harness applies the same model, so a crypto hypothesis is measured against its
real hurdle and an equity hypothesis against its own. A strategy's reported net expectancy
must reflect the venue and asset class it would actually trade. Re-run the P26 default
strategy measurement and the three P28 hypotheses under the corrected model and report every
number before and after. State plainly which conclusions change and which do not. The
expectation is that no conclusion reverses and several worsen. Report it either way.

## TASK 4: THE ORDER TYPE IS PART OF THE COST

The engine sends market orders, which pay the taker rate. Record the assumed order type on
every costed fill and make the maker and taker distinction explicit in both the model and the
harness, so a future maker-execution study can be priced without rebuilding this. Do not
change what the engine sends. This is measurement only.

## TASK 5: THE HURDLE IS VISIBLE WHERE DECISIONS ARE MADE

Surface the applicable round-trip cost in the startup block, the GUI, and any research
report, per venue and asset class, so no future session can quote a hurdle without seeing the
real one. A strategy whose expected move is smaller than its round-trip cost is not a
marginal case and the interface should make that obvious.

## TASK 6: TESTS

Tests covering each: the model returns the correct rate per venue, asset class, and order
type, a paper fill records both model and venue cost, the harness applies the model per asset
class, the tier boundary is respected and a tier change is visible, and the hurdle appears
where decisions are made. Mutation-test the crypto taker rate and the equity rate, both must
fail the suite when reverted to a flat 2 bp. Full suite green.

## TASK 7: DOCUMENT AND COMMIT

Update PROGRESS.md with a dated session entry, newest at top. Update CONTEXT.md Key
Decisions: cost comes from published live schedules rather than paper fills, the fee model is
consulted by both the engine and the harness, order type is part of cost, and a paper venue
is an execution simulator whose fee reporting is not evidence. Complete the RETURN.md entry
with every rate and source, the measured paper-versus-live divergence, the before and after
table for P26 and P28, and the commit message. Commit and push to main: Cost every fill and
every backtest from published live fee schedules rather than paper fills, live trading
untouched.

When done, paste back the rate table with sources and the before-and-after comparison for P26
and P28. Then set Status at the top of this file to DONE and move it to queue/done/.
