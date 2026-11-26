# C.2b gate verification, attempt date 20261125

**Result: MATCH. Pass decision: the gate does NOT pass (own pass = False, log pass = False).** The one failing condition is M >= Required: M 8802 against Required 17563.805. C >= 60 holds (85) and M >= 1,000 holds.

quantities compared: 32, mismatches: 0. Largest relative difference among reals: 4.131e-16 (rho_raw). Findings: 0 BLOCKING, 0 SHOULD FIX, 7 NOTE.

## Who ran this

GateVerifier-FableXHigh. Model: Fable 5.2, model id claude-fable-5-2, as stated in this session's own system prompt. Agent file and effort per the brief (worker-xhigh); the effort level is not observable from inside the session. No worker was spawned. Own code only: nothing imported from news_eval, no earlier verifier's code or report opened, news_eval/*.py not read at any point (step 4 of the brief applies only on a mismatch, and there was none).

## Times (from `date`, MST)

| Event | Time |
|---|---|
| Start, brief read | Wed Nov 25 17:25:57 MST 2026 |
| own_gate.json on disk (`date` run immediately after) | Wed Nov 25 17:30:45 MST 2026 |
| own_gate.json sha256 recorded (b0ad043ade504498..) | Wed Nov 25 17:30:53 MST 2026 |
| reports/c2/gate_log.jsonl opened for the first time | Wed Nov 25 17:31:11 MST 2026 |
| compare.py final run | Wed Nov 25 17:32:15 MST 2026 |
| This report assembled | Wed Nov 25 17:34:56 MST 2026 |

own_gate.json has the same sha256 (b0ad043ade504498..) now as before the log was opened: it was not edited after the comparison.

## Inputs and integrity

- Snapshot: reports/c2/snap_20261125/news_experiment_snapshot.db. sha256 computed 16d1d18f7ee3cb9f69c0edade5742df704f29cf78ac70a1767d6cd13e667f100, equal to snapshot.json sha256 (True). Mode 0o444 (0444: True). Bytes 36335616, equal to snapshot.json. Sidecars (-wal, -shm, -journal) beside it: none. Opened only as `file:<abs path>?mode=ro&immutable=1`, uri=True.
- Table news_observation: 42533 rows, 42487 with run_kind collection (snapshot.json collection_rows_total 42487), 81 collection query_dates (snapshot.json 81), latest 2026-11-23. Collection rows by state: {'no_news': 23355, 'judged': 16824, 'excluded_pre_call': 1527, 'model_failed': 738, 'source_failed': 43}.
- Registered text: EXPERIMENT.md read only at lines 842-858, 912-958, 1072-1087, 2475-2484, 2200-2232. No other range was needed.
- analysis_bars.db: opened `file:<abs path>?mode=ro`, one statement, `SELECT date FROM trading_calendar ORDER BY date`. 2907 dates, 2016-01-04 to 2027-07-28, 0 weekend dates, 0 duplicates, none of 2026-09-07, 2026-11-26, 2026-12-25, 2027-01-01 present.
- Gate log: reports/c2/gate_log.jsonl, 4 entries, exactly 1 with inputs_sha256 equal to the snapshot sha256. Its manifest_sha256 equals `sha256sum reports/c3_harness_freeze.json` (19dc1da78608f7f9..). Append-only check by hash: the first 3 lines of the current file hash the same as the file at commit a785999, and the current file equals the file at HEAD c24e037.
- SQL: 6 statements logged in reports/c2/verify_gate_20261125/verify_gate.sql.log (4 distinct: PRAGMA table_info; one SELECT of the seven allowed columns; the calendar statement; the one grouped judgment count in the allowed shape). No row-level judgment, strength or reason was selected, no row was printed, no other outcome column was read. The live news_experiment.db was never opened. news_eval.gate and news_eval.run_c2 were never run.

## Compared quantities

Exact for counts, dates, strings and booleans. Reals within 1e-9 relative. Full output: reports/c2/verify_gate_20261125/compare.out.

| # | Quantity | Own | Log | Relative difference |
|---|---|---|---|---|
| 1 | N (gate rows, NEUTRAL included) | 16815 | 16815 | exact match |
| 2 | C_G (clusters among gate rows) | 85 | 85 | exact match |
| 3 | C (clusters with a directional scorable row) | 85 | 85 | exact match |
| 4 | M (directional scorable rows) | 8802 | 8802 | exact match |
| 5 | null_excess_count | 0 | 0 | exact match |
| 6 | sigma | 501.1912644824479 | 501.1912644824478 | 1.134e-16 |
| 7 | MSB | 1904139.092964234 | 1904139.0929642348 | 3.668e-16 |
| 8 | MSW | 242893.37107784612 | 242893.37107784612 | 0 |
| 9 | n0 | 196.76271752828399 | 196.76271752828399 | 0 |
| 10 | rho_raw | 0.03359200417445839 | 0.0335920041744584 | 4.131e-16 |
| 11 | rho (floored at 0) | 0.03359200417445839 | 0.0335920041744584 | 4.131e-16 |
| 12 | k_eff | 139.15382867530107 | 139.15382867530107 | 0 |
| 13 | Required | 17563.80513743205 | 17563.80513743205 | 0 |
| 14 | pass | False | False | exact match |
| 15 | failing (from my three pass conditions) | ['REQUIRED'] | ['REQUIRED'] | exact match |
| 16 | failing_detail (M, Required to 3 decimals) | ['M 8802 < Required 17563.805'] | ['M 8802 < Required 17563.805'] | exact match |
| 17 | s_star | '2026-11-24' | '2026-11-24' | exact match |
| 18 | latest_resolved_session | '2026-11-24' | '2026-11-24' | exact match |
| 19 | earliest_nonstale_pending_session | None | None | exact match |
| 20 | stale_pending_count | 0 | 0 | exact match |
| 21 | stale_pending_sessions (derived from stale count 0) | [] | [] | exact match |
| 22 | empty_session_pending_count (derived from pending judged count 0) | 0 | 0 | exact match |
| 23 | excluded_query_dates (9.1; log mapping keys) | [] | [] | exact match |
| 24 | inputs_sha256 | '16d1d18f7ee3cb9f..' | '16d1d18f7ee3cb9f..' | exact match |
| 25 | db_path (full strings compared in compare.out) | '...s/c2/snap_20261125/news_experiment_snapshot.db' | '...s/c2/snap_20261125/news_experiment_snapshot.db' | exact match |
| 26 | constants.REQUIRED_FACTOR | 11.156 | 11.156 | 0 |
| 27 | constants.EFFECT_BP | 30.0 | 30.0 | 0 |
| 28 | constants.FLOOR_ANALYSIS_CLUSTERS | 60 | 60 | exact match |
| 29 | constants.FLOOR_SCORABLE | 1000 | 1000 | exact match |
| 30 | constants.SOURCE_FAILED_DAY_EXCLUDE | 0.2 | 0.2 | 0 |
| 31 | constants.STALE_PENDING_SESSIONS | 3 | 3 | exact match |
| 32 | manifest_sha256 vs sha256sum reports/c3_harness_freeze.json | '19dc1da78608f7f9..' | '19dc1da78608f7f9..' | exact match |

Log fields not recomputed: db_class ('NON_SYNTHETIC'; snapshot.json carries the same value), degenerate_condition (''), s_star_case ('latest_session_no_nonstale_pending'), status ('ok'), test_mode (False), utc_time ('2026-11-26T00:24:08Z'). These are harness labels and a timestamp. Nothing in my numbers contradicts them.

Own quantities with no log field (so not compared):

| Quantity | Own value |
|---|---|
| Pending judged collection rows | 0 |
| Judged collection rows by outcome_state | {'resolved': 16815, 'excluded': 9} |
| Hard-stop session (10.1, from trading_calendar) | 2027-01-15 |
| Bound min(S*, hard stop) | 2026-11-24 |
| Gate rows dropped by the hard-stop restriction | 0 |
| Rows after S* meeting the other conditions | 0 |
| Largest source_failed share, denominator (a) | 0.069328 on 2026-10-07 (33 of 476) |
| Largest source_failed share, denominator (b) | 0.071429 on 2026-10-07 (33 of 462) |
| sum n_c^2, sum m_c^2 | 4824757, 1224832 |
| n_c range over the 85 clusters | 15 to 718 |
| m_c range over the 85 clusters | 5 to 342 |
| Clusters 2026-07-28 to 2026-11-24 with zero directional rows | 0 |
| Pass conditions | C >= 60: True. M >= 1,000: True. M >= Required: False |

m_c and n_c per cluster are in own_gate.json (gate.m_c, gate.n_c). Internal checks: a second numpy route for sigma, MSB, MSW, n0 and rho agrees with the fsum route to 3.9e-15 relative; SST equals SSB + SSW; every m_c is between 1 and its cluster's n_c.

## The five added report lines

1. **Largest source_failed share, both denominators.** (a) Over every collection row of the query_date: 0.069328 on 2026-10-07 (33 of 476). (b) Over collection rows other than excluded_pre_call: 0.071429 on 2026-10-07 (33 of 462). No day crosses 0.20 under either denominator, so the 9.1 excluded set is empty under both and matches the log. Days with any source_failed row: 2026-09-24: 1 of 500 rows (10 excluded_pre_call); 2026-10-07: 33 of 476 rows (14 excluded_pre_call); 2026-10-27: 9 of 636 rows (28 excluded_pre_call). Total source_failed rows: 43.
2. **S\* under each reading of the 9.7 pending-row rules.** No judged collection row is pending: the 16824 judged collection rows are {'resolved': 16815, 'excluded': 9}. So there is one S\*: 2026-11-24. Stale pending rows 0, earliest non-stale pending session none, latest resolved session 2026-11-24. All 12 combinations I coded (pending rows with or without an exclusion_reason; stale unit by exchange calendar or by sessions present in the data; candidate sessions from judged rows, resolved judged rows or all collection rows) give ['2026-11-24']. No split.
3. **C versus C_G.** C = 85 and C_G = 85: equal (True). One n0 (196.762718) and one Required (17563.805).
4. **10.1 bound at the hard-stop snapshot.** Not applicable: S\* 2026-11-24 is before the hard-stop session 2027-01-15 (session 120 of trading_calendar counting 2026-07-28 as session 1; S\* is session 85). The restriction was still applied in my compute: bound = min(2026-11-24, 2027-01-15) = 2026-11-24, gate rows dropped 0.
5. **Is the S\* cluster final.** No. S\* session: 2026-11-24. Collection rows whose query_date equals S\*: 0 (latest query_date in the snapshot: 2026-11-23). The S\* cluster holds 91 gate rows and 44 directional rows, all from one query_date: gate rows {'2026-11-23': 91}, directional rows {'2026-11-23': 44}. NOT REGISTERED, without that cluster: N 16724, C_G 84, C 84, sigma 501.828897, rho 0.03303599, k_eff 139.631879, M 8758, Required 17418.036; C >= 60 True, M >= 1,000 True, M >= Required False. The pass decision would not differ (False): not passed either way.

## Findings

No BLOCKING finding. No SHOULD FIX finding. Seven NOTE findings.

- **N1 (NOTE). The S\* cluster is not final, as in attempt 3 F1.** Facts are in added line 5. The registered 9.7 text defines S\* by pending judged rows only, and by that text S\* = 2026-11-24 is correct and the log agrees. The same section says the snapshot "likely moves the readout one day after the gate session's collection"; this snapshot holds no collection for query_date 2026-11-24. That sentence is descriptive, not a rule, so I record the difference between the text's expectation and the snapshot and do not count it as a disagreement between the text and the log. Whether query_date 2026-11-24 is still to be collected or is a gap was not examined: it is outside my inputs.
- **N2 (NOTE). Reading choices I had to make, none of which changes a number here.** (i) 9.1 denominator: primary is every collection row of the day; the alternative gives the same empty excluded set. (ii) S\* candidate sessions: scoring_session values of judged collection rows; the alternatives give the same date. (iii) The C in the n0 formula: I used C_G, the clusters of the ANOVA over G; C equals C_G here. (iv) "Latest resolved session": over judged collection rows with outcome_state resolved; taking every collection row gives the same date. (v) `exclusion_reason = ''` and the judgment literals were matched exactly as written; exclusion_reason is NULL on 0 collection rows. The column rule does not let me check whether any judgment value differs from the literals only in case or spacing.
- **N3 (NOTE). 11.156 against (2.50 + 0.84)^2.** 9.8 writes the formula with 11.156 and says it is (2.50 + 0.84)^2, which is 11.1556. I used 11.156 as the formula is written, and so does the log. With 11.1556, Required would be 17563.175 instead of 17563.805. The pass decision is the same.
- **N4 (NOTE). 738 model_failed collection rows carry outcome_state resolved, a scoring_session and a non-null excess_1session.** They are outside G because 9.7 requires state = 'judged'. My N and the log's N both exclude them. Separately, 9 judged rows have outcome_state excluded with a non-empty exclusion_reason and a NULL excess; they fail two other conditions as well, so null_excess_count is 0 in both.
- **N5 (NOTE). The log entry has no field for the hard-stop session, the bound or the pending judged row count.** At this snapshot the 10.1 restriction drops 0 rows, so the logged numbers cannot show whether the harness applies it. I did not read the harness code. Added line 4 covers this at the hard-stop snapshot.
- **N6 (NOTE). Use of the calendar beyond the hard stop.** The brief gives trading_calendar for the hard-stop session only. From the one list already read, and with no further statement, I also (a) coded the stale rule's calendar-session reading, which had no rows to act on, and (b) checked that all 85 judged scoring_session values are calendar sessions (0 are not) and that S\* is session 85.
- **N7 (NOTE). Adjacent to 9.1, not a gate input.** The largest daily share, 0.0693 on 2026-10-07, is above the 5 percent line at which Task 7 (lines 2475-2477) says a CRITICAL event is emitted. I did not check whether one was.

Process notes: my first syntax check wrote one bytecode file, reports/c2/verify_gate_20261125/__pycache__/verify_gate.cpython-312.pyc; I removed that file and its empty directory by exact absolute path before the compute run. No commit, no git add. Nothing was written outside reports/c2/verify_gate_20261125/ and this report.

## Files

- reports/c2/verify_gate_20261125/verify_gate.py (own code, sha256 f83e9a2832ca232b..)
- reports/c2/verify_gate_20261125/own_gate.json (own numbers, written before the log was opened)
- reports/c2/verify_gate_20261125/verify_gate.sql.log (every SQL statement)
- reports/c2/verify_gate_20261125/compare.py and compare.out
- reports/c2/verify_gate_20261125/make_report.py (assembles this file from the files above; runs no SQL)

## Unfinished or unverified

Nothing in the brief is unfinished. Not verified, by design of the brief: the harness code itself, the six log fields listed above as not recomputed, and the case or spacing of judgment values.
