# C.2b gate verification, attempt date 20261116

**Result: MATCH.** Pass decision: **the gate does not pass** (own `False`, log `pass = False`). The one failing condition is M at least Required: M 8,054 against Required 18,397.87. C at least 60 holds (79) and M at least 1,000 holds.

32 comparisons, 0 mismatches. Largest relative difference on a real: 3.98e-16 (rho_raw), against a tolerance of 1e-9. Findings: 0 BLOCKING, 1 SHOULD FIX, 8 NOTE.

## Who ran this

GateVerifier-FableXHigh, the one review of this gate under the review cap. Model as reported by my runtime: Fable 5.2 (`claude-fable-5-2`). Effort xhigh is what the brief and the agent file state; I cannot observe it, so confirm it from the transcript. No worker spawned.

## Times

All from `date` or file mtimes on this machine, whose clock prints MST.

| Event | Time (2026-11-16) | Source |
|---|---|---|
| Start, brief read | 23:21:16 | `date` |
| verify_gate.py final | 23:24:50 | mtime |
| own_gate.json written | 23:24:52 | mtime, and `date` run right after |
| Gate log first opened | after 23:24:52, before 23:26:53 | the two `date` readings around it |
| compare.out written | 23:28:06 | mtime and `date` |
| Post-log sensitivity | 23:28:41 | mtime |
| Report written | see the last line | `date` |

own_gate.json was not changed after 23:24:52.

## Inputs and integrity

- Snapshot `reports/c2/snap_20261116/news_experiment_snapshot.db`: sha256 `3893d9095293cdd0b345326b58a25fe7a6452ba59d3f82a35276e2d3a85ad7f9`, equal to the `sha256` field of snapshot.json. Mode 0444. 33,492,992 bytes, equal to the manifest. No -wal, -shm or -journal beside it. Opened only as `file:<abs path>?mode=ro&immutable=1`.
- Collection rows 39,305, equal to the manifest. 75 query dates, 2026-07-28 to 2026-11-13. The 46 demonstration rows are not used.
- Gate log `reports/c2/gate_log.jsonl`: 3 entries, exactly 1 with `inputs_sha256` equal to the snapshot sha256. Its `manifest_sha256` `19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8` equals `sha256sum reports/c3_harness_freeze.json`.
- analysis_bars.db opened `file:<abs path>?mode=ro`, one statement, `SELECT date FROM trading_calendar ORDER BY date`: 2,907 dates, 2016-01-04 to 2027-07-28, no duplicate, no weekend date. All 79 scoring sessions of the gate rows are in it.
- EXPERIMENT.md read by the five ranges in the brief only: 842-858, 912-958, 1072-1087, 2475-2484, 2200-2232. No other range was needed.
- Not opened at any point: the live news_experiment.db, anything under news_eval/, the earlier verifiers' code and reports, docs/prompts/, the STATE and RETURN files. No news_eval import. No git add, no commit, and no git command that shows file content; one `git status --short` at the end, to confirm that only the two output locations are new. Because the result is a MATCH, step 4 of the brief (reading news_eval code) was never reached.
- SQL log `verify_gate.sql.log`: 110 lines. explore.py 10, verify_gate.py 16 (15 on the snapshot, 1 on trading_calendar), extra_counts.py 83, sens_last_cluster.py 1. Exactly one statement reads `judgment`, the allowed grouped count. No row was printed and no mean or per-cluster aggregate of excess_1session was written anywhere.

## Compared quantities

Rows 1 to 23 are the gate entry (14 exact, 8 reals, 1 formatted string). Rows 24 to 29 are the log's constants against the registered text as fixed in verify_gate.py before the log was opened. Rows 30 to 32 are identity fields.

| # | Log field | Own value | Log value | Rule | Relative difference |
|---|---|---|---|---|---|
| 1 | N | 15451 | 15451 | exact | equal |
| 2 | C_G | 79 | 79 | exact | equal |
| 3 | C | 79 | 79 | exact | equal |
| 4 | M | 8054 | 8054 | exact | equal |
| 5 | null_excess_count | 0 | 0 | exact | equal |
| 6 | excluded_query_dates | [] | [] | exact | equal |
| 7 | latest_resolved_session | '2026-11-16' | '2026-11-16' | exact | equal |
| 8 | s_star | '2026-11-16' | '2026-11-16' | exact | equal |
| 9 | earliest_nonstale_pending_session | None | None | exact | equal |
| 10 | stale_pending_count | 0 | 0 | exact | equal |
| 11 | stale_pending_sessions (own: empty because no judged collection row is pending) | [] | [] | exact | equal |
| 12 | empty_session_pending_count | 0 | 0 | exact | equal |
| 13 | sigma | 503.59151962817856 | 503.59151962817856 | 1e-9 rel | 0.00e+00 |
| 14 | MSB | 1963937.3724936396 | 1963937.3724936403 | 1e-9 rel | 3.56e-16 |
| 15 | MSW | 244925.91419173867 | 244925.91419173867 | 1e-9 rel | 0.00e+00 |
| 16 | n0 | 194.3507996329173 | 194.3507996329173 | 1e-9 rel | 0.00e+00 |
| 17 | rho_raw | 0.03485385207480393 | 0.034853852074803945 | 1e-9 rel | 3.98e-16 |
| 18 | rho | 0.03485385207480393 | 0.034853852074803945 | 1e-9 rel | 3.98e-16 |
| 19 | k_eff | 140.22547802334245 | 140.22547802334245 | 1e-9 rel | 0.00e+00 |
| 20 | required | 18397.86872872078 | 18397.868728720783 | 1e-9 rel | 1.98e-16 |
| 21 | pass | False | False | exact | equal |
| 22 | failing (own: the conditions that are false) | ['REQUIRED'] | ['REQUIRED'] | exact | equal |
| 23 | failing_detail (string, Required rounded to 3 places) | 'M 8054 < Required 18397.869' | 'M 8054 < Required 18397.869' | exact | equal |
| 24 | constants.REQUIRED_FACTOR | 11.156 | 11.156 | 1e-9 rel | 0.00e+00 |
| 25 | constants.EFFECT_BP | 30.0 | 30.0 | 1e-9 rel | 0.00e+00 |
| 26 | constants.FLOOR_ANALYSIS_CLUSTERS | 60 | 60 | 1e-9 rel | 0.00e+00 |
| 27 | constants.FLOOR_SCORABLE | 1000 | 1000 | 1e-9 rel | 0.00e+00 |
| 28 | constants.SOURCE_FAILED_DAY_EXCLUDE | 0.2 | 0.2 | 1e-9 rel | 0.00e+00 |
| 29 | constants.STALE_PENDING_SESSIONS | 3 | 3 | 1e-9 rel | 0.00e+00 |
| 30 | inputs_sha256 | '3893d9095293cdd0...' | '3893d9095293cdd0...' | exact | equal |
| 31 | manifest_sha256 (own: sha256 of reports/c3_harness_freeze.json) | '19dc1da78608f7f9...' | '19dc1da78608f7f9...' | exact | equal |
| 32 | db_path (own: the snapshot path opened) | 'reports/c2/snap_20261116/news_experiment_snapshot.db' | 'reports/c2/snap_20261116/news_experiment_snapshot.db' | exact | equal |

Log fields I did not recompute (6): `db_class` ('NON_SYNTHETIC', equal to the snapshot.json field), `degenerate_condition` (''), `s_star_case` ('latest_session_no_nonstale_pending'), `status` ('ok'), `test_mode` (False), `utc_time` ('2026-11-17T06:19:05Z', 8 seconds after the snapshot.json `utc_time`). No log field is unaccounted for: 33 top-level keys, 26 compared, `constants` compared by its 6 members, 6 named here.

Own quantities the log entry has no field for:

| Quantity | Own value |
|---|---|
| 9.1 source_failed rows, and query dates holding any | 43 rows on 3 query dates |
| 9.1 excluded query dates | 0 |
| 9.7 pending judged collection rows | 0 |
| 10.1 hard-stop session | 2027-01-15 |
| 10.1 bound min(S*, hard stop) | 2026-11-16 |
| Gate rows dropped by the bound | 0 |
| Rows on the base conditions (collection, judged, resolved, empty exclusion_reason) | 15,451 |
| Dropped for empty scoring_session, for a 9.1 date | 0, 0 |
| n_c smallest, largest, sum of squares | 15, 718, 4,506,093 |
| m_c smallest, largest, sum of squares | 5, 342, 1,129,376 |
| Gate clusters with no directional row | 0 |
| C at least 60, M at least 1,000, M at least Required | true, true, false |

Self-checks on my own arithmetic: an exact rational recomputation agrees with the float pipeline to 1.2e-16 or better on sigma, MSB, MSW, n0 and rho_raw; numpy gives the same sigma; SST equals SSB plus SSW.

## The four added report lines

1. **Largest source_failed share, both denominators.** (a) Over every collection row of the query_date: 0.069328 (33 of 476) on 2026-10-07. (b) Over the collection rows other than excluded_pre_call: 0.071429 (33 of 462) on 2026-10-07. No day crosses 0.20 under either. Excluded query dates: none under both.
2. **S\* under the 9.7 pending-row readings.** No judged collection row is pending (15,451 resolved, 8 excluded, 0 pending), so the stale-unit and exclusion_reason readings have nothing to act on. The one S\* is 2026-11-16, which is also the latest resolved session. No split. See finding F1 for a different axis on the same S\*.
3. **C against C_G.** C equals C_G: 79 and 79. Not applicable: n0 is 194.3508 and Required is 18,397.87 under both.
4. **The 10.1 bound.** Hard-stop session recomputed from trading_calendar: 2027-01-15, the 120th session counting 2026-07-28 as session 1, equal to the date the registered text names. min(S\*, hard stop) is 2026-11-16. It drops 0 gate rows. The hard stop does not bind: S\* is before it, so this is not the hard-stop snapshot.

## Findings

**BLOCKING: none.**

**SHOULD FIX**

- **F1. The S\* cluster is not final in this snapshot. A reading question for the lead, with no effect on this entry.** S\* is 2026-11-16 by the literal 9.7 rule, and the log reads it the same way. The snapshot's latest query_date is 2026-11-13. In the snapshot, 7,793 of the 15,451 gate rows have scoring_session equal to their own query_date, across 73 of the 79 gate sessions (median 92 such rows per session that has any). Session 2026-11-16 has none: its 96 gate rows (52 directional) all come from query_date 2026-11-13. A row collected for query_date 2026-11-16 and scored on that session would carry a scoring_session at or before this S\*. The 9.7 cutoff tests only for pending rows that exist in the snapshot, so it cannot see this. The last 9.7 bullet says the snapshot "likely moves the readout one day after the gate session's collection", which here would mean a snapshot holding query_date 2026-11-16. Timing facts: snapshot.json `utc_time` 2026-11-17T06:18:57Z (23:18:57 on this clock), source file mtime 06:14:56Z; CLAUDE.md gives the collector window as about 23:00 to 23:45 Pacific on weekdays. I did not check whether a collection run was in progress, which is outside this brief. Sensitivity, not the registered gate, same arithmetic with session 2026-11-16 left out (`sens_last_cluster.json`): N 15,355, C_G 78, C 78, M 8,002, sigma 504.1057, rho 0.035011, k_eff 140.7988, Required 18,567.69, does not pass. So the decision on this entry is the same under both readings. Which reading governs a snapshot whose gate passes, or the hard-stop snapshot, is not mine to decide.

**NOTE**

- **N1. The 10.1 restriction is not exercised and not visible in the log.** The entry has no field for the hard-stop session or the bound. On this snapshot the restriction drops 0 rows, so the comparison cannot show whether the harness applies it. I did not read news_eval code, which the brief allows only on a mismatch.
- **N2. Reading choice, n0.** 9.8 writes `(C - 1)` in n0 and later defines C as the clusters with a directional scorable row. I used C_G, the cluster count of the ANOVA itself, as primary. C equals C_G here, so nothing depends on it.
- **N3. Reading choice, 9.1 denominator.** I took denominator (a) as primary. (b) gives the same empty exclusion set. The largest share, 6.9 or 7.1 percent, is above the 5 percent line at which Task 7 (2475-2477) calls for a CRITICAL event. That line is a collector event rule and not a gate condition.
- **N4. The factor.** 9.8 writes 11.156 and says it is (2.50 + 0.84)^2, which is 11.1556. I used the literal 11.156, as the log does. With 11.1556 Required is 18,397.21. Same decision.
- **N5. Judgment vocabulary not checkable under the column rule.** Only the one grouped count may touch `judgment`, so I could not count other spellings of POSITIVE or NEGATIVE. 7,397 gate rows are non-directional by the exact-string test. My M equals the log's, so both apply the same test; neither result shows the vocabulary is clean.
- **N6. 9.7 reading choices that do not split here.** "Judged collection row" is read as `run_kind='collection' AND state='judged'`. 21,798 other collection rows (no_news 21,755, source_failed 43) carry outcome_state 'pending' with a NULL scoring_session and are outside the pending rule on that reading. 738 model_failed rows carry outcome_state 'resolved' with a scoring_session; they are not judged and not in G. The latest resolved session is 2026-11-16 with or without them. With nothing pending I took S\* as the latest scoring_session among judged collection rows; it is the same date over every collection row and over every row in the table. I applied the S\* cutoff to the gate rows as the brief says, although the 9.8 "Gate rows" bullet names only the scorable conditions; the cutoff drops 0 rows, so the two agree.
- **N7. Six log fields not recomputed**, named under the table. They are harness labels and a timestamp, not gate quantities.
- **N8. My own process, for the record.** (i) Before the compute I read the keys of snapshot.json with .venv-eval python without the brief's env exports and nice; no database was touched. (ii) extra_counts.py ran one statement, `SELECT DISTINCT query_date ... WHERE run_kind='collection'`, 79 times through a comprehension; every run is logged. (iii) extra_counts.py and sens_last_cluster.py were written after the gate log was opened, to support F1. They read allowed columns only, reuse m_c from own_gate.json, and run no new judgment query. (iv) compare_table.md was generated by an inline script from own_gate.json and the log entry; compare.out is the binding comparison. (v) One `git status --short` after the report was written.

## Files

All under `reports/c2/verify_gate_20261116/`: verify_gate.py, own_gate.json, verify_gate.sql.log, compare.py, compare.out, compare_table.md, explore.py, extra_counts.py, extra_counts.json, sens_last_cluster.py, sens_last_cluster.json. Nothing was written elsewhere except this report. No git add and no commit.

Unfinished: nothing. Not verifiable from this snapshot: N1 and N5.

Report written: Mon Nov 16 23:30:53 MST 2026
Report last edited (git statement corrected): Mon Nov 16 23:31:08 MST 2026
