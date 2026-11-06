# STAGE C.3 Part A change record

Scope: docs/prompts/STAGE_C.3.md A1 to A5, EXPERIMENT.md Amendment 10.1 and 10.2, plus the manifest pointer. Author: HarnessCoder-OpusXHigh. Uncommitted in the working tree. One row per `git diff -U0` hunk. Line numbers are the new file's.

"Normal mode" means no `--hard-stop` and S* earlier than `K.HARD_STOP_SESSION`. The required property is that gate.evaluate (except time), family.compute and report.write stay byte-identical to C.1 there. The only unconditional additions are the "mode" key in the marker and in run_meta.

## Hunks

| # | File, new lines | Function | What changed | Why | Maps to | Normal-mode effect |
|---|---|---|---|---|---|---|
| 1 | news_eval/constants.py 164-172 | module | Adds HARD_STOP_SESSION "2027-01-15", HARD_STOP_LABEL, MODE_NORMAL, MODE_HARD_STOP, each with a source comment | A1 and the mode names for A3 | 10.1, 10.2 | Nothing read differently. New public constants enter the freeze pins at the re-freeze |
| 2 | news_eval/cutoff.py 3-4 | module docstring | "Both functions" becomes "The two count functions", rewrapped | The sentence would be false with four functions | 10.1 | Docstring only |
| 3 | news_eval/cutoff.py 12-19 | module docstring | Names analysis_cutoff and hard_stop_record | Brief: mention analysis_cutoff in the docstring | 10.1 | Docstring only |
| 4 | news_eval/cutoff.py 219-245 | analysis_cutoff, hard_stop_record (new) | The single rule: scoring_session <= min(S*, K.HARD_STOP_SESSION), None stays None. The record: {} before the hard stop, else hard_stop_session and analysis_cutoff | A2: one function decides, and the gate and the run call it | 10.1 | analysis_cutoff returns S* unchanged; hard_stop_record returns {} |
| 5 | news_eval/gate.py 13 | module docstring | Default manifest path becomes reports/c3_harness_freeze.json | The old path is now false | A5 | Docstring only |
| 6 | news_eval/gate.py 27-28 | module docstring | Step 3 names cutoff.analysis_cutoff(S*) | The old wording is now false | 10.1 | Docstring only |
| 7 | news_eval/gate.py 31-33 | module docstring | Step 4 names cutoff.analysis_cutoff(S*), rewrapped | The old wording is now false | 10.1 | Docstring only |
| 8 | news_eval/gate.py 105-107 | _read_inputs | limit = cutoff.analysis_cutoff(cut.s_star), passed to gate_rows and directional_counts_by_cluster | 10.1: the gate line is computed on the same restriction | 10.1 | limit equals S*, so both loader calls get the same arguments as C.1 |
| 9 | news_eval/gate.py 203 | evaluate | Adds **cutoff.hard_stop_record(cut.s_star) to the entry; "s_star" stays the raw S* | Records the restriction, and _hard_stop_gate checks analysis_cutoff | 10.1 | Adds no key |
| 10 | news_eval/family.py 344 | _funnel | s_star = cutoff.analysis_cutoff(sstar.s_star) | judged_beyond_s_star_any_outcome must agree with the filter | 10.1 | Same value as S* |
| 11 | news_eval/family.py 381 | build_analysis | scorable_filter(excluded, cutoff.analysis_cutoff(sstar.s_star)) | 10.1: the analysis set restriction; companion_horizons inherits it through build_analysis | 10.1 | Same value as S* |
| 12 | news_eval/family.py 808 | compute_from_inputs | Adds **cutoff.hard_stop_record(analysis.s_star.s_star) inside "analysis_set"; AnalysisSet.s_star stays the raw SStar | Results record the restriction; the report bullet reads it | 10.1 | Adds no key |
| 13 | news_eval/freeze.py 1 | module docstring | "The C.1 harness freeze" becomes "The harness freeze" | The module now writes the C.3 manifest | A5 | Docstring only |
| 14 | news_eval/freeze.py 3-5 | module docstring | States the C.3 re-freeze and that reports/c1_harness_freeze.json stays as the record | Brief | A5 | Docstring only |
| 15 | news_eval/freeze.py 7-10 | module docstring | Usage paths and schema name become c3 | The old paths and schema are now false | A5 | Docstring only |
| 16 | news_eval/freeze.py 61 | SCHEMA | "c3_harness_freeze/1" | A5 | A5 | write and check use the new schema. A c1 manifest no longer passes check. reports/c1_harness_freeze.json is not touched |
| 17 | news_eval/freeze.py 63 | MANIFEST_REL | "reports/c3_harness_freeze.json" | A5: the gate and the runner verify against the new manifest | A5 | Default manifest path moves in freeze, gate and run_c2. No logic change |
| 18 | news_eval/run_c2.py 12-16 | module docstring | Adds the --hard-stop usage | Brief | 10.1 | Docstring only |
| 19 | news_eval/run_c2.py 70-79 | module docstring | Adds a paragraph under precondition 6 describing the mode | Brief | 10.1 | Docstring only |
| 20 | news_eval/run_c2.py 338 | RunConfig | hard_stop: bool = False, last field; __post_init__ unchanged | A3 | 10.1 | Default False |
| 21 | news_eval/run_c2.py 364-368 | _mode (new) | K.MODE_HARD_STOP if cfg.hard_stop else K.MODE_NORMAL | A3: the marker and run_meta record the mode | 10.1 | Returns "normal" |
| 22 | news_eval/run_c2.py 495-536 | _hard_stop_gate (new) | Precondition 6 under --hard-stop. Refuses when S* is before the hard stop, on a degenerate entry for this sha256, when no usable entry exists, or when an earlier entry for another snapshot passed or reached the hard stop. Accepts pass true or false | A3 and the two conditions of 10.1 ("no gate run has passed", "first snapshot") | 10.1 | Not called |
| 23 | news_eval/run_c2.py 544 | _check_gate_pass | others = [] | Input to _hard_stop_gate | 10.1 | List filled and unused |
| 24 | news_eval/run_c2.py 555-558 | _check_gate_pass | Fills others in the scan; if cfg.hard_stop, returns _hard_stop_gate. Every line below is unchanged | A3: without --hard-stop precondition 6 is as frozen in C.1 | 10.1 | Branch not taken; the C.1 lines run unchanged |
| 25 | news_eval/run_c2.py 657 | write_marker | "mode": _mode(cfg) | A3 | 10.1 | UNCONDITIONAL: marker gains "mode": "normal" |
| 26 | news_eval/run_c2.py 761 | _run_meta | "mode": _mode(cfg) | A3 | 10.1 | UNCONDITIONAL: run_meta gains "mode": "normal"; report.write does not print it in this mode |
| 27 | news_eval/run_c2.py 908-909 | _config | Passes hard_stop=args.hard_stop | A3 | 10.1 | False |
| 28 | news_eval/run_c2.py 927-930 | _parser | run gains --hard-stop, store_true, help cites 10.1. Not added to TEST_ONLY_FLAGS | A3 | 10.1 | Flag off by default |
| 29 | news_eval/report.py 164-168 | _analysis | One bullet after S*, only when "hard_stop_session" is in analysis_set | Reader must see the restriction | 10.1 | Key absent, no line |
| 30 | news_eval/report.py 313-314 | _reading_verdict | Signature gains clear_label=False | A4 | 10.2 | Default False |
| 31 | news_eval/report.py 348-349 | _reading_verdict | After the rows and before the statements, the label when clear_label and the gross reading clears | 10.2: "A clear reads as registered, followed by that label" | 10.2 | Not taken |
| 32 | news_eval/report.py 355-380 | _hard_stop_entry, _hard_stop_lines (new); _verdict signature | The entry comes from run_meta when mode is hard_stop. The lines give C, M, Required, sigma, rho and then the label on a FAIL, or the lead's wording on a PASS | 10.2 and the lead's ruling that NOT met after a PASS would be false | 10.2 | _hard_stop_entry returns None |
| 33 | news_eval/report.py 382-384 | _verdict | Adds the gate line after the summary; sets clear_label = hard_stop present and pass False | 10.2: gate line beside the verdict | 10.2 | Adds nothing; clear_label False |
| 34 | news_eval/report.py 386 | _verdict | Passes clear_label to _reading_verdict | 10.2 | 10.2 | False |
| 35 | news_eval/report.py 620-624 | _provenance | One run-mode bullet, only in hard_stop mode | A3: the mode is visible in the report | 10.1 | No line |
| 36 | news_eval/report.py 641 | write | _verdict(results, decision, _hard_stop_entry(run_meta)); write's signature is unchanged | A4 | 10.2 | None passed |
| 37 | tests/test_news_eval_freeze.py 75 | test_manifest_schema_and_pins | Schema assertion becomes "c3_harness_freeze/1" | A5 changes the registered schema | A5 | Test only |
| 38 | tests/test_news_eval_verdict.py 93-94 | test_verdict_table_cells_rebuild_lines_383_to_388_exactly | LEAD HUNK. Line anchor range(383, 389) becomes range(390, 396), with a comment. No expected text changes. Amendment 10's banner (commit 2359d16) moved the table 7 lines, so this test has failed since that commit; the six rows are byte-identical at +7 (old[382:388] == new[389:395], checked by the lead) | The planner's ruling binds the new manifest to the current EXPERIMENT.md, and this test reads that file by line number. Without it the suite cannot pass | A5 (with the planner's 0.1 ruling) | Test only. This is not a known-answer test (tests/test_news_eval_known_answers.py is untouched) |
| 39 | news_eval/gate.py 19-21 | module docstring | LEAD HUNK. States that under --hard-stop run_c2 also accepts a status ok entry that failed | The old sentence is false under 10.1 (coder's observation 1) | 10.1 | Docstring only |
| 40 | news_eval/run_c2.py 138-139 and _hard_stop_gate | GATE_LINE_FIELDS (new); the usable filter | LEAD HUNK. An entry is usable only when C, M, required, sigma and rho are present and numeric | Coder's observation 4: a missing quantity would raise in report.write after the marker, a STOPPED verdict that closes the only run. It must refuse before the marker instead (9.15: preconditions refuse with nothing written) | 10.2 | Not called |
| 41 | news_eval/run_c2.py 77-80 | module docstring | LEAD HUNK, after Part C. One sentence under precondition 6: outside test mode the log must be GATE_LOG_REL | Run-once SF-1; the old text would no longer be complete | 10.1 | Docstring only |
| 42 | news_eval/run_c2.py 154 | module | LEAD HUNK, after Part C. GATE_LOG_REL = "reports/c2/gate_log.jsonl", the log STAGE_C.2.md lines 155, 216 and 248 register | Hunk 43 needs the path | 10.1 | Not read |
| 43 | news_eval/run_c2.py 357-360 | RunConfig.__post_init__ | LEAD HUNK, after Part C. `if self.hard_stop:` adds gate_log to the registered paths, so outside test mode any other log refuses at check config, before anything is written | Run-once SF-1: 10.1's "no gate run has passed" and "first snapshot" hold only over the one log every gate run appends to. Demonstrated by F1 and G3 in reports/c3_review_runonce.md | 10.1 | Branch not taken; the registered dict and the refusal are as in C.1 |

## Left alone, by the brief

verdict.py, so verdict selection does not change. flag_sensitivity_pairs and sensitivity_report treat rows beyond the cutoff as C.1 treats rows beyond S*. AnalysisSet.s_star, the gate entry's "s_star", and the report's S* bullet stay the raw S*.

## Observed, not changed, for the lead

Lead rulings, 2026-11-05: item 1 fixed as hunk 39, item 4 fixed as hunk 40. Items 2 and 3 stay as they are: item 2 is stale comment text in tests outside this change, and item 3's names must stay for byte identity in normal mode (the Hard stop bullet states the restriction).

1. news_eval/gate.py docstring lines 19-20 say run_c2 "accepts only a PASS whose manifest_sha256 is the manifest it verified itself". Under --hard-stop it also accepts a status ok FAIL. The brief limited gate.py docstring edits to the manifest path and steps 3 and 4, so this stays.
2. Stale docstrings in tests the brief forbids editing: tests/test_news_eval_freeze.py line 4 and tests/test_news_eval_gate.py line 638 name the c1 manifest. tests/test_news_eval_freeze.py line 50 still names its tmp manifest c1_harness_freeze.json, which is harmless.
3. The funnel names beyond_s_star and judged_beyond_s_star_any_outcome keep their C.1 names, but past the hard stop they count rows beyond the analysis cutoff. report.py prints the beyond_s_star key through DROP_ORDER. The new Hard stop bullet states the restriction.
4. _hard_stop_gate checks pass, s_star, manifest_sha256 and analysis_cutoff, but not that C, M, required, sigma and rho exist. _hard_stop_lines reads them by key, as the brief's format implies. gate.py always writes them, so only a hand-edited log could lack them, and that would raise KeyError in report.write after the marker, which is a STOPPED verdict.

## Verification

Full suite, run once through the wrapper, started 21:52:20 and ended 21:57:01 local (log: /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/suite_partA.log). Wrapper line: exit=1 seconds=281 lowest_MemAvailable_MB=7055.

    1 failed, 781 passed, 1 skipped, 157 errors in 278.77s (0:04:38)

- **Errors: 157, every one the C2_PATHS guard.** All 157 are at teardown, and `assert [True, False, True] == [False, False, False]` appears 157 times. By file: test_news_eval_known_answers.py 70, test_news_eval_run_c2.py 70, test_news_eval_mutations.py 17. The lead reported this cause as predating Part A (C.2 attempt 1 created reports/c2_UNLOCK.json and reports/c2/). The guards were not edited.
- **Failed: 1, not caused by Part A, needs a lead ruling.** tests/test_news_eval_verdict.py::test_verdict_table_cells_rebuild_lines_383_to_388_exactly fails with `AssertionError: 383`, `assert '### The verd...number exists' == '| Clears gro...gistration. |'`. The test reads EXPERIMENT.md at hard-coded lines 383 to 388. Commit 2359d16 (Amendment 10) inserted 7 lines at line 71, so those rows now sit at lines 390 to 395. Checked directly: all six rows match the verdict.py constants byte for byte at offset +7 and none at offset 0. HEAD's line 383 is the "### The verdicts" heading, and HEAD~4's is the first row. EXPERIMENT.md, verdict.py and this test have no working-tree diff. The test was not edited.
- **Skipped: 1**, the real-manifest test, because reports/c3_harness_freeze.json does not exist yet.
- **Count:** 781 passed + 1 failed = 782, the expected number of test calls.
- **Required property:** the known-answer test bodies passed, and their only errors are the teardown guard. There was no separate byte diff of outputs against HEAD.
- **Hard-stop paths:** no repository test covers them yet, and this brief forbids adding one. An ad-hoc script ran 41 checks on the cutoff functions, every _hard_stop_gate refusal and acceptance branch, normal-mode precondition 6, the flag, the mode and the report lines, with 0 failures (/tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/check_partA.py). It opens no database and did not exercise run_c2 run or report.write end to end in hard-stop mode.
- No .pyc was created under news_eval/.

## git diff --stat

Regenerated by the second lead after the last edit (diff review SF-1). Hunks 41 to 43 and the lead's test additions postdate the Part A verification above. The new test file is untracked, so git does not list it.

     COLLECTION_LOG.md               | 208 ++++++++++++++++++++++++++++++++++++++++
     news_eval/constants.py          |   9 ++
     news_eval/cutoff.py             |  39 +++++++-
     news_eval/family.py             |   5 +-
     news_eval/freeze.py             |  16 ++--
     news_eval/gate.py               |  18 ++--
     news_eval/report.py             |  50 +++++++++-
     news_eval/run_c2.py             |  90 ++++++++++++++++-
     tests/test_news_eval_freeze.py  |   2 +-
     tests/test_news_eval_verdict.py |   3 +-
     10 files changed, 415 insertions(+), 25 deletions(-)

COLLECTION_LOG.md is the collector wrapper's own append. It was already modified when this session started, it grows with each collector run, and it is never staged. Scoped to news_eval/ and tests/: 9 files changed, 207 insertions(+), 25 deletions(-).
