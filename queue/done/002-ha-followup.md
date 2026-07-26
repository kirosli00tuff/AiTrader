# QUEUE 002: H-A equity overnight premium, properly specified

Model: Fable 5. Status: DONE (executed 2026-07-26, pre-registration d66647a). Written by chat Claude, 2026-07-26.

Read CLAUDE.md, PROGRESS.md, CONTEXT.md, and RETURN.md before starting, including the
2026-07-26 P28 hypothesis session and the 2026-07-26 fee model session. Log this prompt to
RETURN.md before work begins.

CONSTRAINTS. Research only against analysis_bars.db. Live trading stays off. Do not touch
RiskGate logic, the live-trading gate, or the adaptive limit-weakening invariant. Do not
change any Level 1 risk value, any strategy parameter, any threshold, or any engine
behavior. Size parallelism from measured RSS under the established MemoryMax scope and
verify sizing before launching any batch. Apply nothing.

Run autonomously without stopping for confirmation. Commit findings and push before ending.

Writing rules for docs and comments. Clear, spartan, active voice. No em dashes. No
semicolons. No filler adjectives.

## WHERE THIS STARTS

P28 tested H-A, the equity overnight premium, and it passed the written bar at holdout net
+6.19 bp, z 2.91. It was then disqualified by its own pre-registered secondaries and the
session was right to disqualify it. Two faults: the effect concentrated in NVDA with four of
five symbols showing nothing, and the registered per-trade standard error treated five
correlated same-night trades as independent, which inflates the statistic. The labelled
exploratory night-clustered estimate read z 1.73 with an interval spanning zero. Under the
corrected fee model H-A improves to +6.89 net, z 3.24, because equities cost 1.3 bp rather
than the 2 bp assumed. The improvement does not address either fault. This session tests the
hypothesis properly specified. Nothing about the prior result carries forward as support.

## THE GOVERNING RULE

A negative result is the EXPECTED outcome and a fully acceptable one. Three hypothesis
families have already failed. If H-A fails properly specified, report that as the headline
and stop. Do not loosen a specification to keep it alive. Do not substitute a weaker
standard error, a narrower universe, or a friendlier fill assumption after seeing a result.
Every specification below is fixed before the first run and committed in Task 0.

## TASK 0: PRE-REGISTER, COMMIT, THEN LOOK

Before running anything, write into RETURN.md and commit: the exact entry and exit
specification, the universe rule, the clustering unit, the fill model, the metric, the
sample size, the significance bar, and what result counts as a negative. Once committed the
specification is closed. Report the committed hash.

## TASK 1: NIGHT-CLUSTERED ERRORS AS THE PRIMARY SPECIFICATION

The unit of independent observation is the night, not the trade. Five symbols held across
the same overnight session share one market move and are not five independent draws. Cluster
standard errors by night as the PRIMARY specification, not as a robustness check. Report the
effective number of independent observations alongside the raw trade count, since these
differ by roughly the average number of symbols held per night. Report the per-trade
estimate too, labelled as the incorrect specification P28 used, so the difference is visible.

## TASK 2: A HINDSIGHT-FREE UNIVERSE

The P28 effect concentrated in NVDA, and NVDA is in the tested universe partly because its
history is known. Membership must be decided by a rule applied with information available at
the time: liquidity, index membership, or market cap as of the formation date, rebalanced on
a stated schedule, with no symbol admitted or retained on the basis of later performance.
State the rule, state the resulting universe at several points in time, and report how much
it differs from the P28 set. Report the effect with and without any symbol that dominates,
and state plainly whether the result survives the removal of its largest contributor.

## TASK 3: AUCTION-FILL REALISM

An overnight strategy buys at or near the close and sells at or near the open, and both are
auctions. Assuming the printed close and open as fill prices is generous. Model what a
participant would actually receive: closing-auction participation and its price, opening
print versus the first minutes of continuous trading, the spread paid at each end, and the
gap risk of holding through a session with no ability to act. Report the effect under the
naive close-to-open assumption and under the realistic fill model side by side. If the edge
lives entirely in the difference between them, that is the finding.

Apply the fee model built in the 2026-07-26 session at the equity rate rather than a flat
figure, and state the round-trip cost used.

## TASK 4: THE HOLDOUT IS TOUCHED ONCE

Specification, inspection, and every choice happen on the fit period alone. The holdout is
evaluated ONCE, after the specification is locked, and its result is final. A hypothesis
that works in fit and fails holdout is a negative result. Report both. Do not return to fit
after seeing holdout. Note that the P28 holdout has already been seen for this hypothesis,
so state explicitly how you are handling that contamination: either a fresh holdout period
that P28 never touched, or an honest statement that the holdout is no longer virgin and the
result must be read as weaker than a first look. Do not paper over this.

## TASK 5: DOES THE MECHANISM HOLD UP

Overnight premium has a documented rationale: compensation for holding risk when markets are
closed and positions cannot be adjusted. Test whether the data behaves as that mechanism
predicts rather than only whether the average is positive. If the premium is compensation
for gap risk, it should be larger where gap risk is larger, should not be concentrated in
one name, and should persist across regimes rather than living in one period. Report each.
A pattern that does not behave like its mechanism is a pattern, not an edge.

## TASK 6: CAPACITY AND SIZING SANITY

If an edge survives, state what it is worth at this account's scale. Report the per-night
capital required to express it, how many symbols it needs, and what the expected dollar
return is on 100,000 of equity at Level 1 sizing. An edge of a few basis points a night on a
position size the RiskGate permits may be real and still not worth operating. Report the
number rather than an opinion.

## TASK 7: REPORT WITH NEGATIVES FIRST

Write everything into RETURN.md: the committed pre-registration, the night-clustered primary
result, the per-trade figure labelled as incorrect, the hindsight-free universe result, the
naive and realistic fill comparison, the mechanism checks, and the capacity figure. State
plainly whether H-A shows edge surviving costs and correct specification, shows no edge, or
cannot be distinguished from no edge with the data available. If it fails, say so as the
headline and recommend returning to hypothesis generation rather than proposing repairs.
Apply nothing.

Update PROGRESS.md with a dated research session entry, newest at top. Commit and push to
main: H-A follow-up with night-clustered errors, hindsight-free universe, and auction-fill
realism, findings only, nothing applied.

When done, paste back the pre-registration, the night-clustered primary result beside the
per-trade figure, the fill comparison, and the headline verdict. Then set Status at the top
of this file to DONE and move it to queue/done/.
