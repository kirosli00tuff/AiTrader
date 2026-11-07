# Gate verification, Stage C.2b, snapshot 20261106

Worker: GateVerifier-FableXHigh. Model: Fable 5.1 (claude-fable-5-1), effort xhigh.
Brief: reports/c2/verify_gate_20261106/brief.md.

**RESULT: MATCH. Pass decision: the gate does NOT pass (C 72 >= 60 true, M 6653 >= 1000 true, M 6653 >= Required 16067.675 false). Own computation and the registered gate log entry agree on all 31 compared quantities; largest relative difference over reals 2.607e-16.**

## Times (from `date`, MST)

| Event | Time |
|---|---|
| Start, integrity check | Fri Nov 6 00:19:09 MST 2026 |
| own_gate.json on disk (before gate_log.jsonl or news_eval/ were opened) | Fri Nov 6 00:22:45 MST 2026 |
| compare.out written | Fri Nov 6 00:24:02 MST 2026 |
| Report written | Fri Nov 6 00:24:48 MST 2026 |
| Report finished (final `date`) | Fri Nov  6 00:25:49 MST 2026 |

## Inputs and integrity

- Snapshot: /home/kiros-li/Documents/GitHub/AiTrader/reports/c2/snap_20261106/news_experiment_snapshot.db, 28,725,248 bytes, mode 0444, no -wal, -shm or -journal beside it. Computed sha256 `47f2733e6578f2d8c21498e54a4e26c1c5b8deb68b9d6913079c0123b39ad96c` equals snapshot.json. Opened only as `file:<abs>?mode=ro&immutable=1`.
- analysis_bars.db opened `file:<abs>?mode=ro`, one statement `SELECT date FROM trading_calendar ORDER BY date` (2,907 rows, 2016-01-04 to 2027-07-28, strictly increasing).
- Registered text read by `sed -n` ranges only: 842-858 (9.1), 912-958 (9.7, 9.8), 1072-1087 (10.1), 2475-2484 (Task 7 rule), 2200-2232 (Task 5). No other range was needed.
- Column rule: 11 SQL statements, all logged in reports/c2/verify_gate_20261106/verify_gate.sql.log. From news_observation only query_date, scoring_session, state, run_kind, exclusion_reason, outcome_state, excess_1session were selected, plus one `SELECT scoring_session, COUNT(*) ... WHERE <scorable conditions> AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session`. No row printed. No news_eval import. Run with .venv-eval, nice 10, single-threaded BLAS.
- Gate log: reports/c2/gate_log.jsonl has 2 entries; exactly 1 has inputs_sha256 equal to the snapshot sha256 (utc_time 2026-11-06T07:17:13Z, status ok, test_mode false). Its manifest_sha256 `19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8` equals `sha256sum reports/c3_harness_freeze.json`.
- Order of work followed: own code reports/c2/verify_gate_20261106/verify_gate.py and numbers reports/c2/verify_gate_20261106/own_gate.json were on disk before gate_log.jsonl was opened. No mismatch occurred, so news_eval/gate.py, cutoff.py, stats.py and data.py were not opened.

## Own computation, in the order of the brief

- 9.1 excluded query_dates: none. 68 collection query_dates, 34,550 collection rows, 43 source_failed rows. Largest source_failed share 33/476 = 0.069328 on 2026-10-07 (0.071429 with excluded_pre_call removed from the denominator). Limit: strictly greater than 0.20.
- 9.7: judged collection rows 12,614 (outcome_state resolved 12,606, excluded 8; no row pending). Latest resolved session 2026-11-05. Pending judged rows 0, stale pending rows 0, earliest non-stale pending session none. S* = 2026-11-05 under every reading tried (sessions counted on the trading calendar or on the snapshot's own sessions; pending check over all judged rows or only exclusion_reason = '' rows).
- 10.1: hard stop = 120th trading_calendar session counting 2026-07-28 as session 1 = 2027-01-15 (agrees with the text's stated 2027-01-15). Restriction scoring_session <= min(S*, hard stop) = 2026-11-05; it dropped 0 rows (no judged row has a later scoring_session).
- Gate rows G: N = 12,606, C_G = 72 (2026-07-28 to 2026-11-05, n_c from 15 to 619, sum n_c^2 = 3,042,336). NULL excess_1session among rows meeting the other conditions: 0.
- sigma = 481.8044316469854 bp (ddof 1 of 10,000 x excess_1session). SSB 128,041,398.239, SSW 2,798,026,709.782, MSB 1,803,399.9751985404, MSW 223,234.9377518412, n0 174.15013642061797, rho_raw 0.0390583144321253, rho 0.0390583144321253 (floor not applied).
- Directional: M = 6,653, C = 72 (m_c from 5 to 267, sum m_c^2 = 787,469), k_eff = 118.36299413798287. Every G session has at least one directional row, so C = C_G.
- Required = 11.156 x (sigma/30)^2 x (1 + (k_eff - 1) x rho) = 11.156 x 257.9338 x 5.5840007 = 16,067.675160289782. M / Required = 0.414061.
- Pass conditions: C >= 60 true; M >= 1,000 true; M >= Required false. Gate passes: false.

## Comparison table (own vs log; exact for counts, dates, booleans, strings; 1e-9 relative for reals)

| Quantity | Own | Log | Rel. diff | OK |
|---|---|---|---|---|
| inputs_sha256 | 47f2733e...ad96c | 47f2733e...ad96c | exact | yes |
| db_path | .../snap_20261106/news_experiment_snapshot.db | same | exact | yes |
| manifest_sha256 vs sha256sum(c3_harness_freeze.json) | 19dc1da7...8bc8 | 19dc1da7...8bc8 | exact | yes |
| excluded_query_dates | [] | {} | exact | yes |
| latest_resolved_session | 2026-11-05 | 2026-11-05 | exact | yes |
| stale_pending_count | 0 | 0 | exact | yes |
| stale_pending_sessions | [] | [] | exact | yes |
| earliest_nonstale_pending_session | null | null | exact | yes |
| empty_session_pending_count | 0 (no judged collection row has NULL or empty scoring_session) | 0 | exact | yes |
| s_star | 2026-11-05 | 2026-11-05 | exact | yes |
| N | 12606 | 12606 | exact | yes |
| C_G | 72 | 72 | exact | yes |
| null_excess_count | 0 | 0 | exact | yes |
| sigma | 481.8044316469854 | 481.8044316469854 | 0 | yes |
| MSB | 1803399.9751985404 | 1803399.9751985404 | 0 | yes |
| MSW | 223234.9377518412 | 223234.93775184115 | 2.607e-16 | yes |
| n0 | 174.15013642061797 | 174.15013642061797 | 0 | yes |
| rho_raw | 0.0390583144321253 | 0.039058314432125305 | 1.777e-16 | yes |
| rho | 0.0390583144321253 | 0.039058314432125305 | 1.777e-16 | yes |
| M | 6653 | 6653 | exact | yes |
| C | 72 | 72 | exact | yes |
| k_eff | 118.36299413798287 | 118.36299413798287 | 0 | yes |
| required | 16067.675160289782 | 16067.675160289784 | 1.132e-16 | yes |
| pass | false | false | exact | yes |
| failing (own derived from the three conditions) | ["REQUIRED"] | ["REQUIRED"] | exact | yes |
| constants.REQUIRED_FACTOR | 11.156 | 11.156 | 0 | yes |
| constants.EFFECT_BP | 30.0 | 30.0 | 0 | yes |
| constants.FLOOR_ANALYSIS_CLUSTERS | 60 | 60 | exact | yes |
| constants.FLOOR_SCORABLE | 1000 | 1000 | exact | yes |
| constants.SOURCE_FAILED_DAY_EXCLUDE | 0.2 | 0.2 | 0 | yes |
| constants.STALE_PENDING_SESSIONS | 3 | 3 | exact | yes |

31 compared, 31 agree, 0 mismatched. Full output: reports/c2/verify_gate_20261106/compare.out.

Log fields not recomputed: db_class, degenerate_condition, failing_detail, s_star_case, status, test_mode, utc_time. failing_detail "M 6653 < Required 16067.675" is consistent with the recomputed numbers by inspection; s_star_case "latest_session_no_nonstale_pending" is consistent with the recomputed state (no pending row).

Own quantities with no log counterpart: hard-stop session 2027-01-15; total pending judged rows 0; largest source_failed share 33/476 on 2026-10-07; design effect 5.5840007277; Required with (2.50 + 0.84)^2 = 11.1556 instead of 11.156: 16067.099051.

## Findings

1. NOTE (reading chosen, 9.1 / Task 7). "A day's queries" was read as every collection row of the query_date, in any state. With excluded_pre_call rows removed from the denominator instead, the largest share moves from 0.0693 to 0.0714 on 2026-10-07. No day is near 0.20 under either reading, so no exclusion follows and the log's `excluded_query_dates: {}` agrees. The log entry does not record per-day shares or the denominator, so the harness's denominator and its strict/non-strict comparison could not be checked from the entry; they are moot on this snapshot.
2. NOTE (not exercised, 9.7). The snapshot contains no judged collection row with outcome_state 'pending' (12,606 resolved, 8 excluded). The stale rule, the unit in which "3 sessions" is counted (trading calendar versus the snapshot's own sessions), and whether the pending check covers rows with a non-empty exclusion_reason were therefore all vacuous: S* = 2026-11-05 under each reading. This check does not demonstrate that the harness and the text agree on S* when pending rows exist.
3. NOTE (reading chosen, 9.8 rho). The n0 formula writes `C`, and the same section later defines C as the clusters with at least one directional scorable row, while rho is defined "over G". The ANOVA was computed with the cluster count of G (C_G) in MSB, MSW and n0. On this snapshot every G session has a directional row, so C = C_G = 72 and the two readings coincide; which one the harness uses in n0 is not distinguishable from the log entry.
4. NOTE (constant, 9.8). The formula states 11.156 literally and names it (2.50 + 0.84)^2, which is 11.1556. The literal 11.156 was used, matching the log's REQUIRED_FACTOR. With 11.1556 Required would be 16067.099 (relative 3.6e-5), which does not change any pass condition here but would fail the 1e-9 comparison if the harness ever switched to the exact square.
5. NOTE (10.1). The hard stop recomputed from trading_calendar is 2027-01-15, the date the text names. The restriction scoring_session <= min(S*, hard stop) binds at S* = 2026-11-05 and removes no row. The log entry carries no field for the hard-stop session or for the restriction bound actually applied, so for a hard-stop snapshot a verifier could not confirm the 10.1 restriction from the entry alone. Whether the frozen manifest records it elsewhere was not checked (the brief closes the C.3 return and docs/prompts to this worker).
6. NOTE (9.7 exclusion_reason). All 12,614 judged collection rows have a non-NULL exclusion_reason: 12,606 empty, 8 non-empty, and the 8 are exactly the 8 rows with outcome_state 'excluded'. The `exclusion_reason = ''` condition is therefore unambiguous on this snapshot (no NULL to decide about).
7. NOTE (log sanity). The log entry's utc_time 2026-11-06T07:17:13Z is 6 seconds after the snapshot's utc_time 2026-11-06T07:17:07Z; db_class NON_SYNTHETIC agrees with snapshot.json.

No BLOCKING and no SHOULD FIX findings.

## Artifacts

- reports/c2/verify_gate_20261106/verify_gate.py (own computation)
- reports/c2/verify_gate_20261106/own_gate.json (own numbers, mode 0444, written 00:22 MST before the log was opened)
- reports/c2/verify_gate_20261106/verify_gate.sql.log (11 statements)
- reports/c2/verify_gate_20261106/compare.py, compare.out
