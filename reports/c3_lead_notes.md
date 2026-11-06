# Stage C.3 lead notes

Everything the lead decided or found so far, kept here so a lead after a self-wipe has it. Feeds the return, sections 2, 3, 5, 6 and 7. Times are from `date`, America/Vancouver.

## Start gates, verbatim evidence

- reports/c3_evidence/start_checks_21h37.txt: the 0.1 and 0.2 commands. `freeze check` printed NOT FROZEN, 2 differences, both EXPERIMENT.md. Hard stop computed: 2027-01-15.
- reports/c3_evidence/ruling_gate_21h40.txt: the replacement gate after the planner's ruling, PASS.
- Quote both in section 2. Also quote the planner's ruling text from reports/C.3_STATE.md (the 21:40 line) in section 2 and section 6.

## Open choices so far (section 6)

1. **0.1 freeze gate replaced by the planner's ruling.** Not the lead's choice. Recorded as the ruling requires. Lead had been about to rule on it when the ruling arrived.
2. **Context-wipe rule replaced by the planner's self-wipe note**, /home/kiros-li/planner-drafts/C3_SELFWIPE_NOTE.md, received 22:06. Lead context read 359k tokens from the transcript at that moment, already past the threshold, so the wipe waited for the first quiet point rather than stopping a worker. Worker briefs moved to disk under reports/c3_briefs/.
3. **"Free memory" means MemAvailable,** the `available` column of `free -m`. The `free` column read 577 MB at the start, under 2 GB before any job ran, with War Thunder holding 5 GB (no other process was touched). run_c2's own precondition 9 uses MemAvailable, and CLAUDE.md's compute rules concern what is available. Both wrappers enforce it.
4. **The suite decision is made in a clean clone.** See "Second defect" below.
5. **Hunk 38, the line anchor,** mapped to A5 with the planner's ruling. See "Third defect".
6. **The 10.2 label is conditional on the entry's pass.** A3 accepts pass true or false under --hard-stop, and A4 says the line carries the label. Printing "registered power rule NOT met" after a PASS would be false, and 10.1 applies only "If no gate run has passed". After a PASS entry the report prints the gate line and says the label does not apply.
7. **Two refusals added under --hard-stop beyond the prompt's list:** an earlier gate log entry for ANOTHER snapshot that passed, or that already reached the hard stop. They enforce 10.1's "If no gate run has passed by the hard stop" and "the FIRST snapshot whose S* is on or after". They look only at earlier lines, so a later snapshot's entry does not void the first one. They run only under --hard-stop.
8. **Hunk 40:** an entry is usable under --hard-stop only if C, M, required, sigma and rho are present and numeric, because a missing one would raise in report.write after the marker, a STOPPED verdict that closes the only run. It refuses before the marker instead.
9. **analysis_cutoff and hard_stop_session appear in the gate entry and results only once S* reaches the hard stop,** so pre-hard-stop bytes do not change. The only unconditional additions are "mode" in the marker and in run_meta (A3). `s_star` stays the raw S* everywhere.
10. **Rows beyond the cutoff still count in flag_sensitivity_pairs and sensitivity_report's judged counts,** exactly as C.1 treats rows beyond S*. Neither is an outcome-derived quantity, and 10.1 changes no definition. Coder's note: funnel names (beyond_s_star, judged_beyond_s_star_any_outcome) keep C.1 names for byte identity; past the hard stop they count rows beyond the analysis cutoff, and the report's Hard stop bullet states the restriction.
11. **Stale comment text left in tests** (tests/test_news_eval_freeze.py line 4, tests/test_news_eval_gate.py line 638, name the c1 manifest): outside A5's need.
12. **Extra files committed with the stage:** reports/c3_evidence/ (start checks, wrappers, identity script and output), reports/c3_briefs/, reports/c3_lead_notes.md, reports/c3_tests_record.md. All are this stage's own files.
13. **Mutants at source level plus five beyond the required four.** The monkeypatch style of C.1 would not have exercised the exact conditions. M4's kill goes through check_preconditions because write_marker's O_EXCL masks it through run_c2.main.
14. **The 0.3 estimate table went to chat first and into STATE only at 21:53,** after the planner's correction. Lead's miss.
15. **Order against V6:** V6 says P.1 runs before C.3. No reports/P.1* exists; the operator launched C.3 explicitly at 21:37, and that governs.

16. **Four SHOULD FIX findings went to the C.2b prompt rather than into code** (run-once SF-2 to SF-5). The prompt says SHOULD FIX findings are fixed; the auditor's brief says a hole that can only be closed outside 10.1, 10.2 and A5 goes in the report as a procedural item. SF-3 is the lead's closest call: a hard-stop-only code fix was possible and was declined, reasons in reports/c3_rulings.md. Planner may reverse it, which would mean another re-freeze.
17. **Run-once SF-1 fixed by the lead inline** (hunks 41 to 43): RunConfig pins --gate-log under --hard-stop outside test mode. `--gate-log` was not on A3's list of changes, but without it 10.1's two conditions were decided by whichever file the caller named.
18. **FixChecker-FableXHigh added by the lead,** not in the prompt's delegation plan, because that fix landed after both reviews and frozen code should not enter the manifest unreviewed. Brief: reports/c3_briefs/FixChecker-FableXHigh.md. Output: reports/c3_review_fix.md, added to the commit list.
19. **Diff review N-1 rejected on the facts:** this machine's America/Vancouver reads MST, -0700, and the timer's next fire read 23:00:58 on this clock. The pause stands as the operator set it.
20. **The briefs' scratch path changed** to the second lead's session when spawning. Nothing else in the text changed.
21. **The lead added three tests that no finding strictly demanded** (observation 3's pin, the abstention wording, the normal-mode key byte test), to close gaps the reviews named without changing behaviour.

## Defects found that are not Amendment 10 (section 7)

**Second defect: stale C2_PATHS guards.** The autouse guards at tests/test_news_eval_run_c2.py:95, tests/test_news_eval_known_answers.py:119 and tests/test_news_eval_mutations.py:49 assert reports/c2_UNLOCK.json and reports/c2/ do not exist. C.2 attempt 1 created both on 2026-10-28, so since then every test in those files errors at teardown in the repo root. Reproduced at 21:48 on one test: `1 passed, 1 error`. Repo-root suite after Part A: `1 failed, 781 passed, 1 skipped, 157 errors`, all 157 this assertion (known_answers 70, run_c2 70, mutations 17). The prompt forbids touching reports/c2* and any hunk outside 10.1, 10.2 and A5, so the guards stay. Lead ruling: B6 and D3 are decided by the same command from a sparse clone that never materialises those paths (reports/c3_evidence/run_suite_clean.sh; it cmp-checks harness, tests and inputs against the working tree first). The repo-root result is reported beside it. Baseline clean clone with the lead hunks: `782 passed, 1 skipped in 288.85s`, 21:59:57 to 22:04:49. Planner told in chat at about 22:05 that a change to the guards would have to come before D1.
- Recommendation for the user: if a later re-freeze happens, change the three guards to compare before and after, not absence. Until then every suite run uses the clean clone. The C.2b prompt must not require a green repo-root suite.
- P.1 is exposed too: docs/prompts/STAGE_P.1.md lines 90-91, 230 and 293 require FROZEN: match (line 293 "on the C.1 manifest"), and it runs the tests in a fresh clone. On the committed tree after this stage, FROZEN passes only against the c3 manifest, and a clone holding reports/c2* errors at those guards. The planner has a newer draft at /home/kiros-li/planner-drafts/STAGE_P.1.md that this session did not read.

**Third defect: hard-coded EXPERIMENT.md line numbers.** tests/test_news_eval_verdict.py::test_verdict_table_cells_rebuild_lines_383_to_388_exactly has failed since commit 2359d16, because Amendment 10's banner moved the table 7 lines. old[382:388] == new[389:395] checked by the lead. Fixed as hunk 38: range only, no expected text. Row names ROW_383 and so on keep C.1's numbering.

**Prompt's first defect** is the 0.1 gate, ruled by the planner.

## Section 7 material still to finish after D1

- **Unlock command.** Kiros writes it; this session must not. Schema from news_eval/data.py load_unlock and K.UNLOCK_FIELDS: schema c2_unlock/1, stage C.2, approver, utc_time (ISO ending Z), experiment_sha256 964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe, manifest_sha256 = the new manifest's. The old unlock (V3) binds 641272 and 77c9bd73, so it is void since 2359d16. The command must overwrite reports/c2_UNLOCK.json in place; validate with data.load_unlock.
- **C.2b prompt must change:** expected hashes (EXPERIMENT 964996..., manifest c3); `freeze check` prints FROZEN on the c3 manifest; `--hard-stop` at the hard-stop snapshot only; per-attempt return file names (reports/C.2_RETURN.md and C.2_STATE.md must not be overwritten); the collector window 23:00 to 23:45; exactly one snapshot once S* reaches 2027-01-15, because normal mode's precondition 6 is frozen and cannot see an earlier failed hard-stop snapshot; do not rely on the repo-root suite. The gate log reports/c2/gate_log.jsonl keeps its 2026-10-28 line, which the new code reads as another snapshot's FAIL before the hard stop, so harmless.
- **Gate-rerun cadence:** 9.8 registers a rerun after every 5 new clusters until the hard stop; V4 item 6 leaves the method open (planner-run frozen commands against a full session per rerun). C.2 attempt 1 was at 65 clusters. Collection read 67 judged query_dates at the 21:37 start check.
- Commit message: "Stage C.3 hard-stop readout build and re-freeze". No push; the planner reviews sections 1 and 7, then pushes.

## Transcripts for section 8

Lead before any wipe: ~/.claude/projects/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd.jsonl. Its subagents: the same path without .jsonl, then subagents/. A wiped lead may run under a new session file in that project folder: sum both. Spawns so far: HarnessCoder-OpusXHigh (opus xhigh), TestCoder-OpusXHigh (opus xhigh). Token counts only, never estimated. Lead's context size at 22:06 read 359,399 tokens.

Second lead: ~/.claude/projects/-home-kiros-li-Documents-GitHub-AiTrader/3a66552d-c1d6-473e-aa89-0ed2d027fbdb.jsonl, subagents under that path without .jsonl, then subagents/: DiffReviewer-FableXHigh (agent-a1bd177ee9b5a9227), RunOnceAuditor-FableXHigh (agent-aa9a4ea6ebf91a5bb), FixChecker-FableXHigh (agent-a136379edfd93eb11), each fable, xhigh by agent file. Second lead's context read 266,777 tokens at 22:50. A third lead runs under a newer session file: sum all three.
