# STAGE C.3 Part B test record

Scope: docs/prompts/STAGE_C.3.md B1 to B6. Author: TestCoder-OpusXHigh. Uncommitted in the working tree. Nothing under news_eval/ and no existing test file was edited. Synthetic databases and tmp paths only.

Files: tests/test_news_eval_hardstop.py (new), reports/c3_evidence/normal_mode_identity.py, reports/c3_evidence/normal_mode_identity.txt.

## Fixture design, for reading the tables

A scenario is built by synthetic.build, then 84 days are added to scoring_session and query_date by SQL, then RC.stage strips the marker so the copy classifies NON_SYNTHETIC. The real K.HARD_STOP_SESSION is used. Session 2026-10-23 lands exactly on 2027-01-15, one full resolved session (2026-10-26) lands after it as 2027-01-18, and that is S*. A shift of 91 days, which was tried on paper first, would leave C = 58 and turn S-EFFECT's PASS into a FAIL on C, so 84 is the only 7-day multiple that keeps both weekdays and the S-EFFECT PASS.

Measured on the shifted copies (gate.evaluate, read before the tests were written):

| Scenario | S* | analysis_cutoff | C | N | M | Required | pass | failing |
|---|---|---|---|---|---|---|---|---|
| S-HIGHRHO | 2027-01-18 | 2027-01-15 | 63 | 3553 | 2478 | 6713.9 | false | REQUIRED |
| S-EFFECT | 2027-01-18 | 2027-01-15 | 63 | 3501 | 2450 | 166.2 | true | none |

Expected counts in the tests never come from these numbers or from the harness: sql_counts is raw SQL on the shifted copy, with 9.1, 9.7 and 9.8 written out in the test file.

Full computes: three, module scoped (fail_run, pass_hs_run, pass_normal_run). Refusals and mutants use check_preconditions, gate.evaluate, family.build_analysis on loaded inputs and report.write on cached results.

The guard compares (exists, size, mtime_ns) of reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json and reports/c2, refuses news_experiment.db and analysis_bars.db by name and by inode, sets the test-mode env and fixes run_c2._mem_available_mb. It does not copy the `[False] * 3` assertion and imports no existing `_guards`.

## B1 byte identity against C.1

Tree: `git archive c757324 news_eval` into the scratchpad. The C.1 tree's cutoff.py has 0 lines naming analysis_cutoff and the working tree's has 5, and the script asserts news_eval loaded from the tree it was given.

Two separate processes, one after the other, each under `nice -n 10` with PYTHONPYCACHEPREFIX set:

- C.1 tree: 22:08:46 to 22:11:03 local.
- Working tree: 22:11:03 to 22:13:19 local.
- Compare: 22:13:25 local. MemAvailable before the runs: 6531260 kB.

Result, verbatim from reports/c3_evidence/normal_mode_identity.txt:

    44 MATCH, 0 DIFF, of 44

11 scenarios (S-NULL, S-EFFECT, S-PREMIUM, S-UNANIMOUS, S-REVERSAL, S-HIGHRHO, S-THIN, S-STORY, S-SENS, S-CLUSTER, S-CUTOFF), 4 quantities each (gate entry without utc_time and db_path, family.compute, verdict.decide, report.write with a fixed relevance summary and a run_meta with no "mode" key). No DIFF. The unconditional "mode" key in the marker and in run_meta is not among these four quantities: this identity does not cover those two files.

## Tests

One row per test function. A count in brackets is the number of parametrized cases.

| Test | What it proves | B item |
|---|---|---|
| test_guard_refuses_the_real_databases_before_opening | The guard raises for news_experiment.db and analysis_bars.db before any open | guard |
| test_entry_before_the_hard_stop_gains_no_hard_stop_key | A real gate entry with S* before the hard stop has no hard_stop_session or analysis_cutoff key | B1 |
| test_gate_counts_before_the_hard_stop_are_the_unrestricted_counts | Unshifted N, M, C equal independent SQL at S*, with nothing beyond it | B1 |
| test_shifted_fixture_straddles_the_hard_stop | SQL: latest resolved 2027-01-18, rows on the hard stop, rows and directional rows after it | B2 |
| test_hard_stop_run_exits_zero_on_a_real_required_fail | run_c2.main --hard-stop exits 0 on a real FAIL on REQUIRED alone, on a NON_SYNTHETIC snapshot, no STOPPED file | B2 |
| test_gate_line_and_label_sit_beside_the_verdict_in_section_4 | Gate line and label in section 4, after the summary and before the readings; label printed once when nothing clears | B2 |
| test_gate_line_numbers_are_the_gate_entrys | C, M, Required, sigma, rho printed are the entry's, and M is below Required | B2 |
| test_marker_and_run_meta_record_the_hard_stop_mode | "mode": "hard_stop" in marker and run_meta; run_meta holds the entry; the provenance line prints | B2 |
| test_results_record_the_hard_stop_session_and_cutoff | results analysis_set has both keys, S* stays raw, the report bullet prints | B2 |
| test_gate_counts_match_independent_restricted_sql | Gate N, M, C, C_G equal restricted SQL | B2 |
| test_funnel_counts_match_independent_restricted_sql | Funnel gate_rows, scored, judged_beyond and the beyond drop equal SQL | B2 |
| test_no_row_after_the_hard_stop_is_in_the_gate_rows_or_analysis_set | gate._read_inputs rows, directional counts, analysis gate_rows and scored all end exactly on the hard stop | B2 |
| test_gate_sigma_and_rho_are_computed_on_the_restricted_rows | sigma, rho, Required equal stats on SQL-fetched restricted rows, and differ from the unrestricted rows | B2 |
| test_verdict_phase_opens_only_after_the_marker_exists | Through main, every VERDICT open happens with the marker on disk | B2, B4 |
| test_clear_with_a_fail_entry_puts_the_label_after_the_registered_row | S-EFFECT with a pass-false entry: label after every registered row in both clearing readings, 3 labels in total | B2 |
| test_report_write_does_not_change_verdict_decides_output | report.write leaves the decision equal, and it equals a fresh verdict.decide | B2 |
| test_hard_stop_report_only_adds_lines_to_the_normal_report | Removing the gate line, the labels and the run-mode line gives the no-mode report byte for byte | B2 |
| test_hard_stop_with_a_pass_entry_runs_without_the_label | --hard-stop with a PASS: no label anywhere, the lead's sentence and the gate line present, mode hard_stop | B2 |
| test_s_effect_stays_a_pass_and_a_clear_after_the_restriction | Shifted S-EFFECT counts equal SQL, C is above the floor, primary clears | B2 |
| test_normal_mode_after_the_hard_stop_is_restricted_with_no_gate_line | Normal with PASS after the hard stop: restricted, mode normal, bullet present, no gate line, label, sentence or run-mode line | B2 |
| test_the_mode_does_not_change_a_result | results.json byte-identical between --hard-stop and normal on the same rows | B2 |
| test_hard_stop_refuses_s_star_before_the_hard_stop | Unshifted snapshot, real ok entry: exit 2, nothing written | B3 |
| test_s_star_guard_refuses_alone_even_with_an_otherwise_usable_entry [2] | The S* guard refuses by itself, pass true or false | B3 |
| test_hard_stop_refuses_s_star_the_day_before_the_hard_stop | Boundary: S* 2027-01-14 refuses | B3 |
| test_hard_stop_accepts_s_star_exactly_on_the_hard_stop | Boundary: S* 2027-01-15 passes the preconditions; counts equal SQL; nothing written | B3 |
| test_hard_stop_refuses_an_empty_gate_log | Missing entry: empty log | B3 |
| test_hard_stop_refuses_a_log_holding_only_another_snapshot | Missing entry: only another sha256 | B3 |
| test_hard_stop_refuses_a_missing_gate_log_file | Log file absent | B3 |
| test_hard_stop_refuses_a_log_line_that_is_not_json | Corrupt log | B3 |
| test_hard_stop_refuses_a_degenerate_entry | Degenerate entry | B3 |
| test_hard_stop_refuses_a_degenerate_entry_beside_an_ok_entry | Any degenerate entry for this sha256 refuses | B3 |
| test_hard_stop_refuses_an_entry_with_no_status | A missing status counts as not ok | B3 |
| test_hard_stop_refuses_when_a_marker_is_present | Marker present: exit 2 at marker_absent, nothing written | B3 |
| test_hard_stop_refuses_an_unusable_entry [30] | Another or no manifest, another or no S*, no or raw analysis_cutoff, non-bool or absent pass, and each of C, M, required, sigma, rho missing, string, null or bool | B3 |
| test_the_quantities_tested_are_the_ones_the_runner_requires | run_c2.GATE_LINE_FIELDS is the five quantities | B3 |
| test_hard_stop_refuses_an_earlier_entry_for_another_snapshot [3] | Earlier other entry that passed, or reached the hard stop (after it, exactly on it) | B3 |
| test_normal_mode_refuses_a_fail_entry_after_the_hard_stop | Normal mode with FAIL on a post-hard-stop snapshot refuses | B3 |
| test_a_completed_run_refuses_every_later_run [4] | After a hard-stop run or a normal run, both --hard-stop and normal refuse at marker_absent | B3 |
| test_other_snapshot_entries_that_do_not_bar_the_run_are_accepted [4] | A later other entry that reached the hard stop or passed, or an earlier other that failed before it, leaves the first snapshot runnable | B3 |
| test_hard_stop_flag_defaults_off_and_is_not_a_test_only_flag | Default False; usable outside test mode | B3 |
| test_gate_and_results_agree_on_the_cutoff_and_counts | Entry and results agree on analysis_cutoff; N = gate_rows; M = scored | B4 |
| test_patching_the_one_function_moves_gate_rows_and_analysis_set | Patching cutoff.analysis_cutoff to 2026-12-31 moves both sets to the SQL counts at that date | B4 |
| test_analysis_cutoff_is_the_minimum_of_s_star_and_the_hard_stop [6] | None, before, equal, after | B4 |
| test_hard_stop_record_is_empty_before_the_hard_stop [4] | None, before, equal, after | B4 |
| test_a_row_scoring_exactly_on_the_hard_stop_is_included | scorable_filter on rows at, before and after the hard stop | B4 |
| test_the_hard_stop_session_row_count_enters_on_the_snapshot | Rows on 2027-01-15 in the analysis set equal SQL, more than zero | B4 |
| test_companion_horizons_read_only_the_restricted_scored_rows | The 9.12 path reads the restricted scored rows | B4 |
| test_hard_stop_session_is_session_120_from_the_weekday_calendar | Weekdays since 2026-07-28 minus the four holidays reach session 120 on 2027-01-15; no database | B4 pin |
| test_hard_stop_label_is_quoted_verbatim_from_experiment_md | The label appears in EXPERIMENT.md in quotes | B4 pin |
| test_preconditions_under_hard_stop_open_only_the_gate_phase | check_preconditions under --hard-stop opens GATE only, never VERDICT | B4 pin |
| test_mutant_is_killed [15] | Mutant table below | B5 |
| test_under_m2_a_real_early_entry_still_refuses_at_the_usable_filter | Documents why M2's check crafts its entry | B5 |
| test_under_m4_main_still_refuses_at_the_exclusive_create | Documents why M4's check avoids main: O_EXCL refuses, same check name | B5 |

Total: 113 test cases.

## B5 mutant kill table

Method for every row: inspect.getsource on the function, the old text must occur exactly once (the test fails otherwise), it is replaced, compiled with the module's __dict__ as globals, and monkeypatched in. A mutant of a function in run_c2 also swaps the function object inside run_c2.PRECONDITIONS, which holds references, so patching the module attribute alone would leave check_preconditions unmutated. Each kill check passes unmutated, fails mutated, and passes again after the patch is undone. The test asserts the failing checks are exactly those listed, so a survivor fails the test.

M1 to M9 are the briefed mutants. M2b, M3a, M3b, M7b, M8a and M8b are added sharper variants.

| Mutant | Function and edit | Check that kills it | Result |
|---|---|---|---|
| M1 restriction on the analysis set only | gate._read_inputs: `limit = cutoff.analysis_cutoff(cut.s_star)` to `limit = cut.s_star` | kill_gate_counts: gate.evaluate N, M, C against SQL | KILLED |
| M2 --hard-stop allows S* before the hard stop | run_c2._hard_stop_gate: `if s_star < K.HARD_STOP_SESSION:` to `if False:` | kill_s_star_guard: crafted otherwise usable entry on the unshifted snapshot must refuse with "is earlier than" | KILLED |
| M2b refuses S* on the hard stop | run_c2._hard_stop_gate: `<` to `<=` | kill_s_star_on_the_hard_stop_accepted: S* 2027-01-15 must pass the preconditions | KILLED |
| M3 label dropped in both places | report._hard_stop_lines and report._reading_verdict: the label `out +=` line to `pass` | kill_label_on_fail_entry and kill_label_after_clear | KILLED |
| M3a label dropped from the gate line | report._hard_stop_lines only | kill_label_on_fail_entry and kill_label_after_clear | KILLED |
| M3b label dropped after a clear | report._reading_verdict only | kill_label_after_clear (kill_label_on_fail_entry cannot see it, nothing clears there) | KILLED |
| M4 --hard-stop skips marker-absent | run_c2._check_marker_absent: `if os.path.lexists(cfg.marker):` to `if not cfg.hard_stop and os.path.lexists(cfg.marker):` | kill_marker_precondition: check_preconditions(cfg) directly must raise Refused with check marker_absent | KILLED |
| M5 restriction on the gate only | family.build_analysis: `scorable_filter(excluded, cutoff.analysis_cutoff(sstar.s_star))` to `scorable_filter(excluded, sstar.s_star)` | kill_analysis_counts: funnel gate_rows and scored against SQL | KILLED |
| M6 normal mode accepts a FAIL entry | run_c2._check_gate_pass: drops `e.get("pass") is not True or` from the bad filter | kill_normal_refuses_fail | KILLED |
| M7 label on the gate line after a PASS | report._hard_stop_lines: `if entry["pass"] is False:` to `if True:` | kill_no_label_after_pass | KILLED |
| M7b label after a clear on a PASS | report._verdict: `clear_label = hard_stop is not None and hard_stop["pass"] is False` to `clear_label = hard_stop is not None` | kill_no_label_after_pass | KILLED |
| M8 earlier-PASS and first-snapshot check dropped | run_c2._hard_stop_gate: `if earlier:` to `if False:` | kill_earlier_pass_refused and kill_earlier_reached_refused | KILLED |
| M8a earlier-PASS clause dropped | run_c2._hard_stop_gate: removes `e.get("pass") is True or` | kill_earlier_pass_refused | KILLED |
| M8b first-snapshot clause dropped | run_c2._hard_stop_gate: removes the `s_star >= K.HARD_STOP_SESSION` clause | kill_earlier_reached_refused | KILLED |
| M9 _funnel keeps the raw S* | family._funnel: `s_star = cutoff.analysis_cutoff(sstar.s_star)` to `s_star = sstar.s_star` | kill_funnel_beyond: judged_beyond_s_star_any_outcome against SQL | KILLED |

Verbatim, `pytest -v -k "mutant or under_m"`, 22:26:29 to 22:26:50 local, repo root:

    test_mutant_is_killed[M1_restriction_on_the_analysis_set_only] PASSED
    test_mutant_is_killed[M2_hard_stop_allows_s_star_before_it] PASSED
    test_mutant_is_killed[M2b_hard_stop_refuses_s_star_on_the_hard_stop] PASSED
    test_mutant_is_killed[M3_label_dropped_in_both_places] PASSED
    test_mutant_is_killed[M3a_label_dropped_from_the_gate_line] PASSED
    test_mutant_is_killed[M3b_label_dropped_after_a_clear] PASSED
    test_mutant_is_killed[M4_hard_stop_skips_marker_absent] PASSED
    test_mutant_is_killed[M5_restriction_on_the_gate_only] PASSED
    test_mutant_is_killed[M6_normal_mode_accepts_a_fail_entry] PASSED
    test_mutant_is_killed[M7_label_on_the_gate_line_after_a_pass_entry] PASSED
    test_mutant_is_killed[M7b_label_after_a_clear_on_a_pass_entry] PASSED
    test_mutant_is_killed[M8_earlier_pass_and_first_snapshot_check_dropped] PASSED
    test_mutant_is_killed[M8a_earlier_pass_check_dropped] PASSED
    test_mutant_is_killed[M8b_first_snapshot_check_dropped] PASSED
    test_mutant_is_killed[M9_funnel_keeps_the_raw_s_star] PASSED
    test_under_m2_a_real_early_entry_still_refuses_at_the_usable_filter PASSED
    test_under_m4_main_still_refuses_at_the_exclusive_create PASSED
    17 passed, 96 deselected in 21.41s

**Survivors: 0.** Notes:

- **M2:** a kill through a real early entry is impossible without reading the message, because a real entry before the hard stop has no analysis_cutoff and the usable filter refuses it as well (pinned by test_under_m2_a_real_early_entry_still_refuses_at_the_usable_filter). The check crafts an otherwise usable entry, so only the S* guard can refuse it. The guard is therefore a second layer in real use.
- **M4:** killed on check_preconditions directly, as briefed. Through main the mutant still exits 2 at marker_absent through write_marker's O_EXCL, with the message "appeared" (pinned by test_under_m4_main_still_refuses_at_the_exclusive_create).

## B6 suites

Both through the wrappers, one after the other, on the final test file. Times are from `date`, local.

**Clean clone, the run that decides B6.** Start 22:16:05, end 22:21:06. Log: /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/suite_partB_clean.log

    clone identical to working tree on harness, tests and inputs; head 86adee9
    895 passed, 1 skipped in 297.11s (0:04:57)
    exit=0 seconds=301 lowest_MemAvailable_MB=6087

This is the expected count: 782 plus 113 new tests. 0 failed, 0 errors. The suite log runs with `-q` and does not name the skip. A separate `pytest -q -rs tests/test_news_eval_freeze.py` in the repo root at 22:27 gave `SKIPPED [1] tests/test_news_eval_freeze.py:298: manifest not yet written (pre-freeze)` and `37 passed, 1 skipped`, which is the real-manifest test the brief expects until the lead's re-freeze. That the suite's one skip is this same test is inferred from the matching count.

The test file's last edit was 22:15:16, before both suites, and it is byte-identical to the clone's copy.

**Repo root, for the record.** Start 22:21:15, end 22:26:16. Log: /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/suite_partB_root.log

    895 passed, 1 skipped, 157 errors in 296.17s (0:04:56)
    exit=1 seconds=301 lowest_MemAvailable_MB=5997

Errors classified from that log: 157 ERROR lines, 157 `ERROR at teardown` headers and no ERROR header of any other kind, and `assert [True, False, True] == [False, False, False]` appears 157 times. By file: test_news_eval_known_answers.py 70, test_news_eval_run_c2.py 70, test_news_eval_mutations.py 17. In tests/test_news_eval_hardstop.py: 0. FAILED lines: 0. Those three existing files were not edited; this is the known stale guard. The wrapper's exit 1 comes from these errors.

Neither wrapper exited 75. No .pyc under news_eval/ after both runs (`find` count 0).

An earlier targeted run of the new file alone: `113 passed in 33.90s`, repo root, 22:15:21 to 22:15:56.

## Observations for the lead, nothing changed

1. tests/test_news_eval_hardstop.py matches freeze.TESTS_GLOB, so it enters the re-freeze manifest. The re-freeze has to follow the last edit of this file.
2. The file is 1,288 lines. tests/test_news_eval_run_c2.py is 1,047. The brief names one output file, so it was not split.
3. _hard_stop_gate takes usable[-1], so a log holding a pass-true then a pass-false entry for one snapshot and one manifest prints the label. gate.evaluate is deterministic, so only a hand-edited log can do this. No test pins it either way.
4. Nothing in the file asserts which gross reading the hard-stop S-HIGHRHO run gives. 10.2's third bullet stays covered only by the verdict tests, which are unchanged.

## After the reviews (second lead, 2026-11-05)

Lead's edits to tests/test_news_eval_hardstop.py, after Part C, to go with hunks 41 to 43 and reports/c3_rulings.md. No expected value in an earlier test changed. Total now 122 cases: 113 plus these 9.

| Test | What it proves | Source |
|---|---|---|
| test_hard_stop_refuses_another_gate_log_outside_test_mode | RunConfig refuses at check config, naming gate_log | Run-once SF-1 |
| test_hard_stop_accepts_the_registered_gate_log_outside_test_mode | The registered path is accepted, relative from the repo root and absolute | Run-once SF-1 |
| test_normal_mode_leaves_the_gate_log_free_as_in_c1 | Without the flag the log stays free, as frozen | A3 |
| test_the_cli_refuses_hard_stop_with_another_gate_log | run_c2.main exits 2 at config and creates no out-dir | Run-once SF-1, F1 and G3 |
| test_the_last_usable_entry_is_the_one_read | A conflicting log reads its last usable entry, as normal mode does | Observation 3 |
| test_the_normal_mode_key_changes_no_report_byte | "mode": "normal" in run_meta changes no report byte | Diff review N-6 |
| test_a_powered_negative_on_a_fail_run_meets_the_10_2_interval_rule | S-HIGHRHO's hard-stop FAIL reads powered_negative in both readings, with P1's upper bound below 30 bp and no primary clearing | Observation 4, 10.2 third bullet |
| test_an_abstention_is_reported_in_those_words | The report prints "Gross reading: abstention." | Observation 4, 10.2 fourth bullet |
| test_mutant_is_killed[M10_hard_stop_leaves_the_gate_log_unpinned] | The mutant below | Run-once SF-1 |

| Mutant | Function and edit | Check that kills it | Result |
|---|---|---|---|
| M10 gate log unpinned | run_c2.RunConfig.__post_init__: `if self.hard_stop:` to `if False:` | kill_gate_log_pin: another log outside test mode must refuse, naming gate_log | KILLED |

apply_edit now dedents the source and accepts a class, for M10. Top-level functions dedent to themselves, so the other 15 mutants compile the same source. Mutants: 16 of 16 killed.

The first run of the file, 22:45:26 to 22:46:01, gave `2 failed, 119 passed`. Both were the lead's test bugs. The gross-reading test guessed abstention, and S-HIGHRHO reads powered_negative. kill_gate_log_pin used pytest.raises, whose Failed is a BaseException that failing_checks does not catch. After the fixes, 22:46:41 to 22:47:19: `122 passed in 37.66s`.

Third lead, targeted check after the collector window, 23:45:41 to 23:46:14 local, repo root, on the final test file (it includes the non-empty guard added after the clean-clone suite started, fix check NOTE 1): `122 passed in 32.70s`, exit 0.

Third lead, normal-mode identity rerun on the final code, after hunks 41 to 43, 23:46:46 to 23:49:10 local: `44 MATCH, 0 DIFF, of 44`, measure and compare both exit 0. Output: reports/c3_evidence/normal_mode_identity_final.txt. Compared against the same C.1 measurement as the 22:13 run; that C.1 tree was first checked file by file against `git show c757324:news_eval/...`, 0 mismatches. This replaces inference with measurement: only run_c2.py changed after 22:13, and its four quantities do not go through run_c2.

## Part D suites (third lead, after the re-freeze)

**D3, clean clone from a fresh PYTHONPYCACHEPREFIX, the run that decides D3.** Start 23:49:45, end 23:55:12. Log: reports/c3_evidence/suite_D3_clean.log.

    clone identical to working tree on harness, tests and inputs; head 86adee9
    905 passed in 322.73s (0:05:22)
    exit=0 seconds=326 lowest_MemAvailable_MB=5220

904 plus the real-manifest test, which no longer skips. 0 failed, 0 errors, 0 skipped. `find news_eval -name '*.pyc' | wc -l` read 0 afterwards, and `freeze check` printed FROZEN: match.

**Repo root, for the record.** Start 23:55:12, end 00:00:38.

    905 passed, 157 errors in 321.87s (0:05:21)
    exit=1 seconds=326 lowest_MemAvailable_MB=3828

Errors classified from that log: 157 ERROR lines, 157 `ERROR at teardown` headers and no ERROR header of any other kind, and `assert [True, False, True] == [False, False, False]` appears 157 times. By file: test_news_eval_known_answers.py 70, test_news_eval_run_c2.py 70, test_news_eval_mutations.py 17. FAILED lines: 0. The stale C2_PATHS guard, as before. The wrapper's exit 1 comes from these errors. No .pyc under news_eval/ afterwards.
