# Stage C.2 rulings (lead, Opus 5.5, effort max)

Written 2026-10-28 by the C.2 lead. The gate failed on the first snapshot,
so Steps 3 to 6 of docs/prompts/STAGE_C.2.md did not run: there is no
VerdictVerifier or VerdictReviewer output to rule on. This file rules on the
one Fable review this session produced, reports/c2_gate_verify.md
(GateVerifier-FableXHigh).

The frozen gate's log line (reports/c2/gate_log.jsonl, line 1) is the
registered result in every case. The verifier's recomputation, with its own
code under reports/c2/verify_gate/, matches it on all 29 compared quantities
and on the pass decision: FAIL, on M >= Required alone.

| finding | class | ruling | action |
|---|---|---|---|
| 1. Pass decision and every quantity match the log | NOTE | accept | none |
| 2. 9.8 writes the constant as 11.156 and names it (2.50 + 0.84)^2 = 11.1556 | NOTE | accept. Task 5 and 9.8 both register the literal 11.156, and the harness and the verifier both used it. The other value moves Required by 0.48 and changes nothing | none |
| 3. The 9.7 staleness rule ("3 sessions") reads as calendar or data sessions | NOTE | accept. The snapshot holds 0 pending judged rows, so both readings give S* 2026-10-27. The frozen harness's reading (mapping D16, data sessions) governs every later gate run. It matters only when a pending row sits next to a session gap | none; recorded for the rerun |
| 4. C_G (n0) and C (pass condition) could diverge on an all-NEUTRAL cluster | NOTE | accept. Both are 65 here. The frozen gate logs them apart (mapping D1), so a divergence will be visible in the log | none |
| 5. 62 collection query_dates against 64 sessions (2026-08-28 and 2026-09-15 missing) | NOTE | accept. These are the two recorded permanent gaps. Gaps stay gaps. All 65 scoring sessions are populated because after-hours rows score the next session | none |
| 6. No reading of the Task 7 denominator brings any day to 20 percent | NOTE | accept. The largest share is 0.0693 (2026-10-07), or at most 0.157 under the narrowest reading. The exclusion set is empty under every reading | none |

Nothing is BLOCKING or SHOULD FIX. No frozen file, EXPERIMENT.md or
collector file was changed.

The verifier's PROJECTION section is arithmetic on the gate quantities and
is not a finding. The return document uses it only under Decisions for the
user, labelled as a projection.
