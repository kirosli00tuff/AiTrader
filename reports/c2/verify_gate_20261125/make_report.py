#!/usr/bin/env python
"""Assemble reports/c2_gate_verify_20261125.md from own_gate.json, the gate log entry and compare.out.

Numbers are inserted from the files, never retyped. Runs no SQL.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

REPO = "/home/kiros-li/Documents/GitHub/AiTrader"
OUT_DIR = REPO + "/reports/c2/verify_gate_20261125"
REPORT = REPO + "/reports/c2_gate_verify_20261125.md"

own = json.load(open(OUT_DIR + "/own_gate.json", encoding="utf-8"))
entries = [json.loads(x) for x in open(REPO + "/reports/c2/gate_log.jsonl", encoding="utf-8") if x.strip()]
sha = own["integrity"]["sha256_computed"]
match = [e for e in entries if e.get("inputs_sha256") == sha]
assert len(match) == 1
e = match[0]
cmp_lines = open(OUT_DIR + "/compare.out", encoding="utf-8").read().splitlines()
result_line = [x for x in cmp_lines if x.startswith("RESULT:")][0]
n_compared = [x for x in cmp_lines if x.startswith("quantities compared:")][0]
max_rel = [x for x in cmp_lines if x.startswith("largest relative difference")][0]
assert "MATCH" in result_line and "MISMATCH" not in result_line


def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def rel(a: float, b: float) -> str:
    if a == b:
        return "0"
    return f"{abs(a - b) / max(abs(a), abs(b)):.3e}"


g, s91, s97, s101 = own["gate"], own["s91"], own["s97"], own["s101"]
l3, l5 = own["added_lines"]["line3"], own["added_lines"]["line5"]
wo = l5["NOT_REGISTERED_without_S_star_cluster"]
integ = own["integrity"]
ma, mb = s91["max_share_a_all_collection_rows"], s91["max_share_b_excluding_excluded_pre_call"]
now = subprocess.run(["date"], capture_output=True, text=True, check=True).stdout.strip()

rows = [
    ("N (gate rows, NEUTRAL included)", g["N"], e["N"], "exact"),
    ("C_G (clusters among gate rows)", g["C_G"], e["C_G"], "exact"),
    ("C (clusters with a directional scorable row)", g["C"], e["C"], "exact"),
    ("M (directional scorable rows)", g["M"], e["M"], "exact"),
    ("null_excess_count", g["null_excess_among_rows_meeting_other_conditions"], e["null_excess_count"], "exact"),
    ("sigma", g["sigma"], e["sigma"], "real"),
    ("MSB", g["MSB"], e["MSB"], "real"),
    ("MSW", g["MSW"], e["MSW"], "real"),
    ("n0", g["n0"], e["n0"], "real"),
    ("rho_raw", g["rho_raw"], e["rho_raw"], "real"),
    ("rho (floored at 0)", g["rho"], e["rho"], "real"),
    ("k_eff", g["k_eff"], e["k_eff"], "real"),
    ("Required", g["Required"], e["required"], "real"),
    ("pass", g["passes"], e["pass"], "exact"),
    ("failing (from my three pass conditions)", ["REQUIRED"] if (g["pass_C_ge_60"] and g["pass_M_ge_1000"]
                                                               and not g["pass_M_ge_Required"]) else "see compare.out",
     e["failing"], "exact"),
    ("failing_detail (M, Required to 3 decimals)", [f"M {g['M']} < Required {g['Required']:.3f}"], e["failing_detail"], "exact"),
    ("s_star", s97["S_star"], e["s_star"], "exact"),
    ("latest_resolved_session", s97["latest_resolved_session"], e["latest_resolved_session"], "exact"),
    ("earliest_nonstale_pending_session", s97["earliest_nonstale_pending_session"], e["earliest_nonstale_pending_session"], "exact"),
    ("stale_pending_count", s97["stale_pending_rows"], e["stale_pending_count"], "exact"),
    ("stale_pending_sessions (derived from stale count 0)", [], e["stale_pending_sessions"], "exact"),
    ("empty_session_pending_count (derived from pending judged count 0)", 0, e["empty_session_pending_count"], "exact"),
    ("excluded_query_dates (9.1; log mapping keys)", sorted(own["s91_excluded_query_dates"]), sorted(e["excluded_query_dates"]), "exact"),
    ("inputs_sha256", sha[:16] + "..", e["inputs_sha256"][:16] + "..", "exact"),
    ("db_path (full strings compared in compare.out)", "..." + own["integrity"]["snapshot_path"][-46:],
     "..." + e["db_path"][-46:], "exact"),
    ("constants.REQUIRED_FACTOR", g["factor"], e["constants"]["REQUIRED_FACTOR"], "real"),
    ("constants.EFFECT_BP", g["delta_bp"], e["constants"]["EFFECT_BP"], "real"),
    ("constants.FLOOR_ANALYSIS_CLUSTERS", 60, e["constants"]["FLOOR_ANALYSIS_CLUSTERS"], "exact"),
    ("constants.FLOOR_SCORABLE", 1000, e["constants"]["FLOOR_SCORABLE"], "exact"),
    ("constants.SOURCE_FAILED_DAY_EXCLUDE", 0.2, e["constants"]["SOURCE_FAILED_DAY_EXCLUDE"], "real"),
    ("constants.STALE_PENDING_SESSIONS", 3, e["constants"]["STALE_PENDING_SESSIONS"], "exact"),
    ("manifest_sha256 vs sha256sum reports/c3_harness_freeze.json",
     sha256_file(REPO + "/reports/c3_harness_freeze.json")[:16] + "..", e["manifest_sha256"][:16] + "..", "exact"),
]
table = ["| # | Quantity | Own | Log | Relative difference |", "|---|---|---|---|---|"]
for i, (label, a, b, kind) in enumerate(rows, 1):
    d = rel(float(a), float(b)) if kind == "real" else ("exact match" if a == b else "DIFFERENT")
    assert d != "DIFFERENT", label
    table.append(f"| {i} | {label} | {a!r} | {b!r} | {d} |")
assert f"quantities compared: {len(rows)} " in n_compared, (len(rows), n_compared)

sf_days = "; ".join(f"{d}: {v['source_failed']} of {v['rows']} rows ({v['excluded_pre_call']} excluded_pre_call)"
                    for d, v in s91["days_with_any_source_failed"].items())
readings = s97["readings"]

md = f"""# C.2b gate verification, attempt date 20261125

**Result: MATCH. Pass decision: the gate does NOT pass (own pass = {g['passes']}, log pass = {e['pass']}).** The one failing condition is M >= Required: M {g['M']} against Required {g['Required']:.3f}. C >= 60 holds ({g['C']}) and M >= 1,000 holds.

{n_compared.replace('  ', ', ')}. {max_rel[0].upper() + max_rel[1:]}. Findings: 0 BLOCKING, 0 SHOULD FIX, 7 NOTE.

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
| This report assembled | {now} |

own_gate.json has the same sha256 ({sha256_file(OUT_DIR + '/own_gate.json')[:16]}..) now as before the log was opened: it was not edited after the comparison.

## Inputs and integrity

- Snapshot: reports/c2/snap_20261125/news_experiment_snapshot.db. sha256 computed {integ['sha256_computed']}, equal to snapshot.json sha256 ({integ['sha256_match']}). Mode {integ['mode_octal']} (0444: {integ['mode_is_0444']}). Bytes {integ['bytes']}, equal to snapshot.json. Sidecars (-wal, -shm, -journal) beside it: {integ['sidecars_present'] or 'none'}. Opened only as `file:<abs path>?mode=ro&immutable=1`, uri=True.
- Table news_observation: {own['table']['rows_total']} rows, {own['table']['collection_rows']} with run_kind collection (snapshot.json collection_rows_total {integ['snapshot_json_collection_rows_total']}), {s91['query_dates']} collection query_dates (snapshot.json {integ['snapshot_json_collection_query_dates']}), latest {l5['latest_query_date_in_snapshot']}. Collection rows by state: {own['table']['collection_state_counts']}.
- Registered text: EXPERIMENT.md read only at lines 842-858, 912-958, 1072-1087, 2475-2484, 2200-2232. No other range was needed.
- analysis_bars.db: opened `file:<abs path>?mode=ro`, one statement, `SELECT date FROM trading_calendar ORDER BY date`. {s101['calendar_dates']} dates, {s101['calendar_first']} to {s101['calendar_last']}, {s101['calendar_weekend_dates']} weekend dates, {s101['calendar_duplicates']} duplicates, none of 2026-09-07, 2026-11-26, 2026-12-25, 2027-01-01 present.
- Gate log: reports/c2/gate_log.jsonl, {len(entries)} entries, exactly {len(match)} with inputs_sha256 equal to the snapshot sha256. Its manifest_sha256 equals `sha256sum reports/c3_harness_freeze.json` ({e['manifest_sha256'][:16]}..). Append-only check by hash: the first 3 lines of the current file hash the same as the file at commit a785999, and the current file equals the file at HEAD c24e037.
- SQL: 6 statements logged in reports/c2/verify_gate_20261125/verify_gate.sql.log (4 distinct: PRAGMA table_info; one SELECT of the seven allowed columns; the calendar statement; the one grouped judgment count in the allowed shape). No row-level judgment, strength or reason was selected, no row was printed, no other outcome column was read. The live news_experiment.db was never opened. news_eval.gate and news_eval.run_c2 were never run.

## Compared quantities

Exact for counts, dates, strings and booleans. Reals within 1e-9 relative. Full output: reports/c2/verify_gate_20261125/compare.out.

{chr(10).join(table)}

Log fields not recomputed: db_class ({e['db_class']!r}; snapshot.json carries the same value), degenerate_condition ({e['degenerate_condition']!r}), s_star_case ({e['s_star_case']!r}), status ({e['status']!r}), test_mode ({e['test_mode']!r}), utc_time ({e['utc_time']!r}). These are harness labels and a timestamp. Nothing in my numbers contradicts them.

Own quantities with no log field (so not compared):

| Quantity | Own value |
|---|---|
| Pending judged collection rows | {s97['pending_judged_rows']} |
| Judged collection rows by outcome_state | {s97['judged_outcome_state_counts']} |
| Hard-stop session (10.1, from trading_calendar) | {s101['hard_stop_session']} |
| Bound min(S*, hard stop) | {s101['bound_min_S_star_hard_stop']} |
| Gate rows dropped by the hard-stop restriction | {s101['gate_rows_dropped_by_hard_stop_restriction']} |
| Rows after S* meeting the other conditions | {s101['rows_after_S_star_meeting_other_conditions']} |
| Largest source_failed share, denominator (a) | {ma['share']:.6f} on {ma['query_date']} ({ma['source_failed']} of {ma['denominator']}) |
| Largest source_failed share, denominator (b) | {mb['share']:.6f} on {mb['query_date']} ({mb['source_failed']} of {mb['denominator']}) |
| sum n_c^2, sum m_c^2 | {g['sum_nc2']}, {g['sum_mc2']} |
| n_c range over the {g['C_G']} clusters | {min(g['n_c'].values())} to {max(g['n_c'].values())} |
| m_c range over the {g['C']} clusters | {min(g['m_c'].values())} to {max(g['m_c'].values())} |
| Clusters {g['first_cluster']} to {g['last_cluster']} with zero directional rows | {len(g['clusters_with_zero_directional'])} |
| Pass conditions | C >= 60: {g['pass_C_ge_60']}. M >= 1,000: {g['pass_M_ge_1000']}. M >= Required: {g['pass_M_ge_Required']} |

m_c and n_c per cluster are in own_gate.json (gate.m_c, gate.n_c). Internal checks: a second numpy route for sigma, MSB, MSW, n0 and rho agrees with the fsum route to {max(own['internal_checks']['numpy_crosscheck_relative_difference'].values()):.1e} relative; SST equals SSB + SSW; every m_c is between 1 and its cluster's n_c.

## The five added report lines

1. **Largest source_failed share, both denominators.** (a) Over every collection row of the query_date: {ma['share']:.6f} on {ma['query_date']} ({ma['source_failed']} of {ma['denominator']}). (b) Over collection rows other than excluded_pre_call: {mb['share']:.6f} on {mb['query_date']} ({mb['source_failed']} of {mb['denominator']}). No day crosses 0.20 under either denominator, so the 9.1 excluded set is empty under both and matches the log. Days with any source_failed row: {sf_days}. Total source_failed rows: {s91['source_failed_rows_total']}.
2. **S\\* under each reading of the 9.7 pending-row rules.** No judged collection row is pending: the {s97['judged_collection_rows']} judged collection rows are {s97['judged_outcome_state_counts']}. So there is one S\\*: {s97['S_star']}. Stale pending rows 0, earliest non-stale pending session none, latest resolved session {s97['latest_resolved_session']}. All {len(readings)} combinations I coded (pending rows with or without an exclusion_reason; stale unit by exchange calendar or by sessions present in the data; candidate sessions from judged rows, resolved judged rows or all collection rows) give {s97['distinct_S_star_values_across_readings']}. No split.
3. **C versus C_G.** C = {l3['C']} and C_G = {l3['C_G']}: equal ({l3['C_equals_C_G']}). One n0 ({g['n0']:.6f}) and one Required ({g['Required']:.3f}).
4. **10.1 bound at the hard-stop snapshot.** Not applicable: S\\* {s101['S_star']} is before the hard-stop session {s101['hard_stop_session']} (session {s101['ordinal']} of trading_calendar counting {s101['first_session']} as session 1; S\\* is session {s97['S_star_calendar_ordinal_from_first_session']}). The restriction was still applied in my compute: bound = min({s101['S_star']}, {s101['hard_stop_session']}) = {s101['bound_min_S_star_hard_stop']}, gate rows dropped {s101['gate_rows_dropped_by_hard_stop_restriction']}.
5. **Is the S\\* cluster final.** No. S\\* session: {l5['S_star']}. Collection rows whose query_date equals S\\*: {l5['collection_rows_with_query_date_eq_S_star']} (latest query_date in the snapshot: {l5['latest_query_date_in_snapshot']}). The S\\* cluster holds {l5['S_star_cluster_gate_rows']} gate rows and {l5['S_star_cluster_directional_rows']} directional rows, all from one query_date: gate rows {l5['S_star_cluster_gate_rows_by_query_date']}, directional rows {l5['S_star_cluster_directional_rows_by_query_date']}. NOT REGISTERED, without that cluster: N {wo['N']}, C_G {wo['C_G']}, C {wo['C']}, sigma {wo['sigma']:.6f}, rho {wo['rho']:.8f}, k_eff {wo['k_eff']:.6f}, M {wo['M']}, Required {wo['Required']:.3f}; C >= 60 {wo['pass_C_ge_60']}, M >= 1,000 {wo['pass_M_ge_1000']}, M >= Required {wo['pass_M_ge_Required']}. The pass decision would not differ ({l5['pass_decision_differs_without_S_star_cluster']}): not passed either way.

## Findings

No BLOCKING finding. No SHOULD FIX finding. Seven NOTE findings.

- **N1 (NOTE). The S\\* cluster is not final, as in attempt 3 F1.** Facts are in added line 5. The registered 9.7 text defines S\\* by pending judged rows only, and by that text S\\* = {s97['S_star']} is correct and the log agrees. The same section says the snapshot "likely moves the readout one day after the gate session's collection"; this snapshot holds no collection for query_date {l5['S_star']}. That sentence is descriptive, not a rule, so I record the difference between the text's expectation and the snapshot and do not count it as a disagreement between the text and the log. Whether query_date {l5['S_star']} is still to be collected or is a gap was not examined: it is outside my inputs.
- **N2 (NOTE). Reading choices I had to make, none of which changes a number here.** (i) 9.1 denominator: primary is every collection row of the day; the alternative gives the same empty excluded set. (ii) S\\* candidate sessions: scoring_session values of judged collection rows; the alternatives give the same date. (iii) The C in the n0 formula: I used C_G, the clusters of the ANOVA over G; C equals C_G here. (iv) "Latest resolved session": over judged collection rows with outcome_state resolved; taking every collection row gives the same date. (v) `exclusion_reason = ''` and the judgment literals were matched exactly as written; exclusion_reason is NULL on {own['table']['exclusion_reason_null_rows_collection']} collection rows. The column rule does not let me check whether any judgment value differs from the literals only in case or spacing.
- **N3 (NOTE). 11.156 against (2.50 + 0.84)^2.** 9.8 writes the formula with 11.156 and says it is (2.50 + 0.84)^2, which is 11.1556. I used 11.156 as the formula is written, and so does the log. With 11.1556, Required would be {g['Required_with_factor_3.34_squared_NOT_REGISTERED']:.3f} instead of {g['Required']:.3f}. The pass decision is the same.
- **N4 (NOTE). {own['table']['collection_state_counts']['model_failed']} model_failed collection rows carry outcome_state resolved, a scoring_session and a non-null excess_1session.** They are outside G because 9.7 requires state = 'judged'. My N and the log's N both exclude them. Separately, {s97['judged_outcome_state_counts'].get('excluded', 0)} judged rows have outcome_state excluded with a non-empty exclusion_reason and a NULL excess; they fail two other conditions as well, so null_excess_count is 0 in both.
- **N5 (NOTE). The log entry has no field for the hard-stop session, the bound or the pending judged row count.** At this snapshot the 10.1 restriction drops 0 rows, so the logged numbers cannot show whether the harness applies it. I did not read the harness code. Added line 4 covers this at the hard-stop snapshot.
- **N6 (NOTE). Use of the calendar beyond the hard stop.** The brief gives trading_calendar for the hard-stop session only. From the one list already read, and with no further statement, I also (a) coded the stale rule's calendar-session reading, which had no rows to act on, and (b) checked that all {s97['judged_sessions_count']} judged scoring_session values are calendar sessions ({s97['judged_sessions_not_in_calendar']} are not) and that S\\* is session {s97['S_star_calendar_ordinal_from_first_session']}.
- **N7 (NOTE). Adjacent to 9.1, not a gate input.** The largest daily share, {ma['share']:.4f} on {ma['query_date']}, is above the 5 percent line at which Task 7 (lines 2475-2477) says a CRITICAL event is emitted. I did not check whether one was.

Process notes: my first syntax check wrote one bytecode file, reports/c2/verify_gate_20261125/__pycache__/verify_gate.cpython-312.pyc; I removed that file and its empty directory by exact absolute path before the compute run. No commit, no git add. Nothing was written outside reports/c2/verify_gate_20261125/ and this report.

## Files

- reports/c2/verify_gate_20261125/verify_gate.py (own code, sha256 {sha256_file(OUT_DIR + '/verify_gate.py')[:16]}..)
- reports/c2/verify_gate_20261125/own_gate.json (own numbers, written before the log was opened)
- reports/c2/verify_gate_20261125/verify_gate.sql.log (every SQL statement)
- reports/c2/verify_gate_20261125/compare.py and compare.out
- reports/c2/verify_gate_20261125/make_report.py (assembles this file from the files above; runs no SQL)

## Unfinished or unverified

Nothing in the brief is unfinished. Not verified, by design of the brief: the harness code itself, the six log fields listed above as not recomputed, and the case or spacing of judgment values.
"""
open(REPORT, "w", encoding="utf-8").write(md)
print("wrote", REPORT, len(md.splitlines()), "lines")
