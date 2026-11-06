# Stage C.3 diff review: is the working-tree diff Amendment 10 and nothing else?

Reviewer: DiffReviewer-FableXHigh (claude-fable-5-1, xhigh). Independent of the
coder and the lead. Written 2026-11-05, machine clock 22:30 to 22:45 MST.
Diff under review: `git diff c757324 -- news_eval tests` (uncommitted) plus the
new file tests/test_news_eval_hardstop.py. reports/c3_change_record.md was read
as a claim and checked against the diff, never used as evidence.

Verdict: **no BLOCKING finding. 1 SHOULD FIX (a stale block in the change
record, not code). 12 NOTEs.** Every code hunk maps to 10.1, 10.2 or A5; the
restriction is one function called by both the gate and the run; normal mode is
byte-identical on all 11 synthetic scenarios; the in-memory C.3 manifest covers
every changed and new file and pins EXPERIMENT.md at 964996...8ebe; the C.1
manifest is byte-identical to c757324; HARD_STOP_SESSION recomputes to
2027-01-15 two independent ways; no test expectation was weakened and
tests/test_news_eval_known_answers.py is unchanged.

## Findings

### SHOULD FIX

**SF-1. reports/c3_change_record.md lines 79-92: the `git diff --stat` block is
stale.** It shows `news_eval/gate.py | 17`, `news_eval/run_c2.py | 77`, 8 files
scoped, and omits tests/test_news_eval_verdict.py. The actual scoped stat is
gate.py 18, run_c2.py 83, 9 files, 200 insertions, 25 deletions, including
tests/test_news_eval_verdict.py (3 lines). The hunk table itself (rows 39 and
40) does describe the two lead hunks that caused the growth, so the table is
complete; only the stat block and the "Scoped ... 8 files changed, 191
insertions(+), 24 deletions(-)" sentence are out of date. The record is the
Part A gate's artifact ("Every hunk is explained in ..."), so its stat should
match the diff it describes. Evidence: `git diff --stat c757324 -- news_eval
tests`, run 22:31 MST.

### NOTE

**N-1. Machine clock versus the brief's collector-window rule.** `date` prints
MST (UTC-7). ~/.config/systemd/user/news-collect.timer has `OnCalendar=Mon..Fri
*-*-* 23:00:00 America/Vancouver`, which is 00:00 MST in November. The brief's
"if `date` reads 22:55 to 23:45" is therefore one hour early relative to the
real window. I kept to the brief's intent (nothing heavy near the real window;
the only compute was a 36 s targeted pytest at 22:35 MST). The identity script
reports/c3_evidence/normal_mode_identity.py line 39 has the same one-hour
offset (`WINDOW_START, WINDOW_END = 2255, 2345` on `time.localtime()`), which is
conservative and harmless.

**N-2. tests/test_news_eval_verdict.py line 85: the function name still says
`lines_383_to_388` while the body now reads lines 390 to 395.** Cosmetic. The
edit itself is correct (see Check 7).

**N-3. news_eval/run_c2.py 495-540 `_hard_stop_gate` enforces three conditions
A3 does not list** (details under Check 8): (a) the entry's `analysis_cutoff`
must equal `cutoff.analysis_cutoff(S*)`; (b) C, M, required, sigma, rho must be
present and numeric (lead hunk 40); (c) no earlier gate-log entry for another
snapshot may have `pass` true or `s_star >= HARD_STOP_SESSION`. All three are
derivable from the amendment's text: (a) from 10.1 "The gate line for that
snapshot is computed on the same restriction", (b) from 10.2 (the line must be
printable) with 9.15 (preconditions refuse with nothing written), (c) from 10.1
"If no gate run has passed by the hard stop" and "the first snapshot whose S*
is on or after the hard-stop session". Each refuses before the marker; none
touches a bar, test or verdict row. I consider them justified. Two consequences
the lead should hold in mind: (c) makes the runner one-directional in practice:
once any status-ok gate entry with S* at or past the hard stop exists for
snapshot A, no later snapshot B can run `--hard-stop` (and A itself cannot
either if its only entry is degenerate). That is the registered "first
snapshot" rule, not a defect, but it leaves no operational slack. And (c) is
asymmetric: only entries before this snapshot's first entry count, so a later
PASS on another snapshot does not bar the readout. Consistent with "a PASS
before the hard stop runs the verdict as already registered" (a later PASS is
not before the hard stop), covered by test `ACCEPTED_LOGS`.

**N-4. news_eval/report.py 364-377 `_hard_stop_lines`: on a PASS entry the
label is replaced by the sentence "The gate passed on this snapshot, so the
registered power rule is met and the Amendment 10.2 label does not apply."**
10.2 says the gate line goes beside the verdict "with ... the label". The
conditional label and this sentence are the lead's ruling (record row 32). The
amendment text does not address a PASS at or after the hard stop, so this is a
ruling, not an implementation error. Verdict selection is untouched either way
(test_report_write_does_not_change_verdict_decides_output,
test_the_mode_does_not_change_a_result).

**N-5. news_eval/report.py 348-349: the "clear" label is placed after the
Amendment 5 verdict rows and before the Task 5 and Task 6 statement quotes.**
10.2 says "A clear reads as registered, followed by that label." Rows then
label then statements is a defensible reading (the label follows the registered
row), but the literal "followed by" would also admit placing it after the
statements. A lead judgment; flagged only so it is a conscious one.

**N-6. Normal mode output bytes that do change: the run-once marker and
run_meta gain `"mode": "normal"` unconditionally** (run_c2.py 663 and 767).
This is A3's "The marker and run_meta record the mode" and is the only
unconditional addition. gate.evaluate, family.compute, verdict.decide and
report.write are byte-identical in normal mode (Check 3). report.py reads
`mode` only at lines 358 and 621-623, both `== K.MODE_HARD_STOP`, so a
`"mode": "normal"` key in run_meta prints nothing; the identity evidence used a
run_meta without the key, so this last point rests on code reading plus
test_normal_mode_after_the_hard_stop_is_restricted_with_no_gate_line
(`"Run mode" not in text`).

**N-7. Identity method limitation.** normal_mode_identity.py hashes
`json.dumps(obj, sort_keys=True)`, so it would not detect a key-order change.
None is possible here in normal mode: the only dict additions are
`**cutoff.hard_stop_record(...)`, which is `{}` before the hard stop, and the
gate log line is itself written with sort_keys (gate.py 243). Report text is
hashed raw, so that comparison is a true byte check.

**N-8. Paths that select rows without the restriction, all unchanged from C.1
and outside 10.1's "analysis set":** (a) family.sensitivity_report counts
`judged_rows` per pair over every judged row (`inputs.judged`), as C.1 did
beyond S*; (b) family.flag_sensitivity_pairs reads every collection row's
sector, no sessions; (c) the relevance sample (data.RELEVANCE_SQL, bounded by
`K.RELEVANCE_QUERY_DATE_MAX` on query_date, not S*). The 9.7 S* computation
itself stays raw, which is correct: 10.1 restricts the set, it does not move
S*. Change-record item 3 (funnel keys keep the name `beyond_s_star` while
counting beyond the cutoff past the hard stop) is accurate; the new
"Hard stop (10.1)" bullet in the report states the restriction.

**N-9. Stale docstrings in untouched tests** name the c1 manifest
(tests/test_news_eval_gate.py 638, tests/test_news_eval_freeze.py 4; line 50
names a tmp file c1_harness_freeze.json). Harmless; the brief forbade touching
them beyond the schema assertion.

**N-10. tests/test_news_eval_freeze.py 298 skips the real-manifest test until
reports/c3_harness_freeze.json exists.** Expected before the re-freeze; the
lead must see it un-skip and pass after the freeze.

**N-11. news_eval/cutoff.py adds two functions, not one.** `analysis_cutoff`
is the single restriction rule (A2). `hard_stop_record` is a reporting helper
that returns `{}` before the hard stop and the two keys after; it selects no
rows. Both are shared by gate.py and family.py. Consistent with A2.

**N-12. The brief's HOOK NOTE did not fire:** no GateGuard prompt appeared on
any call.

## Checks, with evidence

### Check 1: every hunk maps to 10.1, 10.2 or A5

Read the full diff hunk by hunk. Mapping (new-file lines):

| File | Hunk | Maps to | Does more than required? |
|---|---|---|---|
| constants.py 164-172 | HARD_STOP_SESSION, HARD_STOP_LABEL, MODE_NORMAL, MODE_HARD_STOP | 10.1 (A1), 10.2 (A1), A3 mode names | No. No existing constant changed |
| cutoff.py 3-4, 12-19 | docstring | 10.1 | No |
| cutoff.py 219-245 | analysis_cutoff, hard_stop_record | 10.1 (A2) | No (N-11) |
| family.py 344 | _funnel uses analysis_cutoff | 10.1 | No |
| family.py 381 | build_analysis uses analysis_cutoff | 10.1 | No |
| family.py 808 | results carry hard_stop_record | 10.1 reporting | No |
| freeze.py 1-10 docstring, 61 SCHEMA, 63 MANIFEST_REL | | A5 | No |
| gate.py 13, 19-21, 27-33 docstrings | | A5, 10.1 | No |
| gate.py 105-107 | _read_inputs uses analysis_cutoff for both loader calls | 10.1 "gate line ... same restriction" | No |
| gate.py 204 | entry carries hard_stop_record | 10.1 | No |
| report.py 164-168 | analysis bullet, conditional on hard_stop_session | 10.1 | No |
| report.py 313-314, 348-349 | clear label | 10.2 | No (N-5) |
| report.py 355-384 | _hard_stop_entry, _hard_stop_lines, _verdict | 10.2 (A4) | PASS sentence is a lead ruling (N-4) |
| report.py 620-624 | run-mode provenance bullet, hard-stop only | A3 | No |
| report.py 641 | write passes the entry | 10.2 | No |
| run_c2.py 12-16, 70-79 docstrings | | 10.1 (A3) | No |
| run_c2.py 154 GATE_LINE_FIELDS | | 10.2 (lead hunk 40) | Addition, justified (N-3) |
| run_c2.py 339, 365-367, 911-915, 933-936 | hard_stop field, _mode, _config, --hard-stop flag | A3 | No. Not a test-only flag (test asserts) |
| run_c2.py 496-540 | _hard_stop_gate | A3, 10.1 | Three extra conditions (N-3) |
| run_c2.py 550, 561-564 | others list, hard-stop branch | A3 | No; normal-mode lines unchanged |
| run_c2.py 663, 767 | mode in marker and run_meta | A3 | Unconditional by design (N-6) |
| tests/test_news_eval_freeze.py 75 | schema string | A5 | No |
| tests/test_news_eval_verdict.py 93-94 | line anchors +7 | Consequence of Amendment 10's insertion into EXPERIMENT.md; needed for the suite to pass against the file the new manifest pins | No expected text changed (Check 7) |
| tests/test_news_eval_hardstop.py (new) | | 10.1, 10.2 coverage (Part B) | Test only |

Also verified: no file deleted or renamed under news_eval/ or tests/
(`git status --porcelain` shows only ` M` and `??`); no committed change to
news_eval/ or tests/ between c757324 and HEAD (`git diff --stat c757324 HEAD --
news_eval tests` is empty), so the working-tree diff against c757324 is exactly
this change; verdict.py, stats.py, data.py, synthetic.py are untouched, so no
bar, test, seed, null, floor or verdict row moved. COLLECTION_LOG.md is the
collector wrapper's append and outside this change.

### Check 2: the restriction is one function used by the gate and the run

- `cutoff.analysis_cutoff(s_star) = min(s_star, K.HARD_STOP_SESSION)`, None
  stays None (cutoff.py 221-232).
- Gate: gate.py 106-108 computes `limit` once and passes it to both
  `phase.gate_rows` and `phase.directional_counts_by_cluster`; data.py 843
  applies it as `scoring_session <= limit` in `_gate_filters`, the only
  session filter in data.py (grep of data.py for scoring_session).
- Run: family.py 381 builds `scorable_filter(excluded, analysis_cutoff(S*))`;
  family.py 235 applies `session > s_star` → DROP_BEYOND_S_STAR. Every
  downstream set derives from `analysis.gate_rows` or `analysis.scored`:
  sensitivity set (build_sensitivity_set(analysis.gate_rows), family.py 777),
  halves (half_boundary(analysis.scored), 779), story trigger and story
  readings (analysis.scored, sens_scored, 786-793), sector robustness (816),
  companion horizons (companion_horizons builds its own `analysis` via
  build_analysis and keeps only `analysis.scored` ids, 847-861). The funnel's
  judged_beyond uses the same cutoff (344-348). The report selects no rows.
- Residual raw-S* uses in family.py (grep `sstar.` and `.s_star`): 333
  stale_pending (pending rows, not the set), 806 `cutoff` record (raw S*, as
  registered), 808 hard_stop_record. In gate.py: 101 None check, 202 raw S*
  in the entry. All correct: 10.1 does not move S*.
- Not restricted, by design and unchanged: N-8.
- Mutants M1 (gate only), M5 (analysis only), M9 (funnel) in the new test
  file each target one call site and are killed; the shared-function test
  patches `cutoff.analysis_cutoff` once and sees both the gate entry and the
  analysis set move (test_patching_the_one_function_moves_gate_rows_and_analysis_set).

### Check 3: normal mode is behaviourally identical

Method of reports/c3_evidence/normal_mode_identity.py, checked: it builds every
scenario in `synthetic.SCENARIOS` in a temp directory (sqlite3.connect guarded
to that directory), runs gate.evaluate (hashing the entry without utc_time and
db_path), family.compute, verdict.decide and report.write (fixed relevance
summary, fixed run_meta without a mode key, companion None), and compares
sha256 per scenario per quantity between two trees loaded in separate
processes with the tree first on sys.path and an assertion that news_eval
loaded from it. Result file: 44 MATCH, 0 DIFF, of 44 (11 scenarios x 4).

Provenance I verified myself: the C.1 tree at
.../2288cb7a.../scratchpad/c1_tree/news_eval has sha256-identical
constants, cutoff, family, freeze, gate, report, run_c2, data, stats, verdict
and synthetic to `git show c757324:news_eval/<f>.py`. identity_current.json
(mtime 22:13:19) was measured after the last news_eval edit (run_c2.py
21:59:32, gate.py 21:59:28), so it covers the final code including lead hunks
39 and 40. Every synthetic S* is a 2026 date (the hardstop tests need an
84-day shift to reach 2027-01-15), so all 11 scenarios exercise normal mode.
Limitations: N-6 (mode key absent from the fixed run_meta) and N-7 (sorted
JSON).

Precondition 6 without --hard-stop: run_c2.py 565-581 are the C.1 lines
unchanged (the diff inserts `others = []`, the `elif` that fills it, and the
`if cfg.hard_stop: return ...` branch; nothing below is modified). Covered by
test_normal_mode_refuses_a_fail_entry_after_the_hard_stop and mutant M6.

### Check 4: the new manifest covers every changed file

Computed `news_eval.freeze.build_manifest()` in memory (nothing written;
reports/c3_harness_freeze.json does not exist, confirmed by ls before and
after). Schema `c3_harness_freeze/1`; 34 files, 11 inputs. Every changed and
new path is listed: news_eval/{constants,cutoff,family,freeze,gate,report,
run_c2}.py, tests/test_news_eval_{freeze,hardstop,verdict}.py. All 16
tests/test_news_eval_*.py files are listed. `inputs["EXPERIMENT.md"].sha256`
= 964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe, equal to
`sha256sum EXPERIMENT.md` and to `git show HEAD:EXPERIMENT.md`; EXPERIMENT.md
has no working-tree diff. The four new constants appear in
pins.constants. No .pyc under news_eval/ before or after any of my runs
(`bytecode_files` returned [] and `find` returned 0).

### Check 5: reports/c1_harness_freeze.json

sha256 77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9 both
on disk and from `git show c757324:reports/c1_harness_freeze.json`;
`git diff --quiet c757324 -- reports/c1_harness_freeze.json` exits 0.
Byte-identical. Its EXPERIMENT.md pin is 641272...3386, which is
`git show c757324:EXPERIMENT.md | sha256sum`, consistent with the planner's
ruling that this manifest cannot print FROZEN against the current file.

### Check 6: K.HARD_STOP_SESSION

1. `sqlite3 "file:analysis_bars.db?mode=ro" "SELECT date FROM trading_calendar
   WHERE date>='2026-07-28' ORDER BY date LIMIT 1 OFFSET 119;"` → 2027-01-15.
2. Independent count in Python with no repo input: weekdays from 2026-07-28
   minus NYSE full-day closures (Labor Day 2026-09-07, Thanksgiving
   2026-11-26, Christmas 2026-12-25, New Year's Day 2027-01-01; MLK
   2027-01-18 falls after): session 1 = 2026-07-28, session 119 =
   2027-01-14, session 120 = 2027-01-15, session 121 = 2027-01-19. 124
   weekdays in 2026-07-28..2027-01-15 inclusive minus 4 closures = 120.

Both agree with constants.py `HARD_STOP_SESSION = "2027-01-15"` and with
Amendment 10.1's "The C.2 verifier's calendar puts it at 2027-01-15".

### Check 7: test edits

- tests/test_news_eval_known_answers.py: `git diff --quiet c757324` exits 0.
  Unchanged.
- tests/test_news_eval_freeze.py 75: `"c1_harness_freeze/1"` →
  `"c3_harness_freeze/1"`. Same strictness, follows A5.
- tests/test_news_eval_verdict.py 93-94: `range(383, 389)` → `range(390,
  396)`, plus a comment. The six expected strings are untouched. Git history:
  commit 2359d16 (2026-10-28, "EXPERIMENT.md Amendment 10") has two hunks in
  EXPERIMENT.md, `@@ -68,6 +68,13 @@` (+7 lines, the banner, before line
  383) and `@@ -1042,6 +1049,66 @@` (after the table). `diff <(git show
  c757324:EXPERIMENT.md | sed -n 383,388p) <(git show HEAD:EXPERIMENT.md |
  sed -n 390,395p)` is empty: the six rows are byte-identical at +7. So the
  test matched at c757324, has failed at HEAD since 2359d16, and the edit
  restores the same assertion against the file the new manifest pins. Not a
  weakening. The pytest run confirms it passes (N-2 for the stale name).
- No test was deleted; the only new test file is tests/test_news_eval_hardstop.py.

### Check 8: conditions under --hard-stop against 10.1 and A3

Enforced in `_hard_stop_gate` (run_c2.py 496-540), in order:
1. `S* >= K.HARD_STOP_SESSION`, else refuse "is earlier than" (A3). S* is
   `facts["s_star"]`, recomputed from the snapshot by precondition 5, and the
   entry's `s_star` must equal it (below).
2. No entry for this sha256 with `status != "ok"`, else refuse "degenerate
   entry" (A3 "degenerate"; same policy as C.1's normal mode).
3. At least one usable entry: `pass` is a bool (true or false, A3),
   `s_star == S*`, `manifest_sha256 == facts["manifest_sha256"]` (C.1 ruling
   S2 carried over), `analysis_cutoff == analysis_cutoff(S*)` (addition),
   C, M, required, sigma, rho numeric and not bool (addition, lead hunk 40);
   else refuse "no usable gate entry" (A3 "missing"). The last usable entry
   is taken, as in normal mode.
4. No entry for another snapshot at a line before this snapshot's first entry
   with `pass` true or a string `s_star >= HARD_STOP_SESSION` (addition).
5. Mode recorded in the marker (663) and run_meta (767); `facts["gate_entry"]`
   reaches run_meta and the report (A3).
6. Every other precondition is untouched: the diff changes only
   `_check_gate_pass` among the ten PRECONDITIONS; marker_absent is shared, so
   a hard-stop run and a normal run cannot both happen
   (test_a_completed_run_refuses_every_later_run, mutant M4).

Missing against A3 or 10.1: nothing found. Added beyond A3: 3's two extra
usable conditions and 4, with my view in N-3 (justified by the amendment's
own text, refuse-before-marker, no bar moved). The report-side PASS sentence
is N-4.

### Targeted tests I ran

`nice -n 10 .venv-eval/bin/python -m pytest -q -p no:cacheprovider
--basetemp=<scratch> tests/test_news_eval_hardstop.py
tests/test_news_eval_freeze.py tests/test_news_eval_verdict.py
tests/test_news_eval_cutoff.py tests/test_news_eval_report.py` with
PYTHONPYCACHEPREFIX set, MemAvailable 7.5 GB, no other heavy process:
**285 passed, 1 skipped in 36.10 s** (the skip is N-10). Log:
/tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/3a66552d-c1d6-473e-aa89-0ed2d027fbdb/scratchpad/pt/targeted.log.
No .pyc under news_eval/ afterwards; .pytest_cache in the repo root predates
this session (mtime 2026-07-01) and is gitignored; `git status` shows no new
tracked-tree change from my run. The 16 mutants in the new file were all
killed in this run.

## What I did not check

- The full suite in a clean clone (reports/c3_evidence/run_suite_clean.sh);
  the brief reserves that to the lead. The three files with the pre-existing
  C2_PATHS teardown guards (known_answers, run_c2, mutations) were not run.
- The real gate log under reports/c2/: forbidden. So condition 4's effect on
  the actual log (the single known entry, snap_20261028 FAIL with S*
  2026-10-27, would not bar) is inferred from the brief's facts, not read.
- A byte check of report.write with `"mode": "normal"` present in run_meta:
  code reading and the hardstop test only (N-6).
- No run of gate or run_c2 on real data, no `freeze write`, no paid call,
  no commit, no edit to code or tests.
