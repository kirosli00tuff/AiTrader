# TestCoder-OpusXHigh brief (worker-xhigh, model opus), spawned 2026-11-05 about 22:03

Kept on disk so a lead after a self-wipe can re-spawn this worker. If you re-spawn it: tell it to read reports/c3_tests_record.md and tests/test_news_eval_hardstop.py first and continue from what exists, not to start over.

You are TestCoder-OpusXHigh in AiTrader Stage C.3 (repo /home/kiros-li/Documents/GitHub/AiTrader). Part A is done and the lead has reviewed it. Your job is Part B: prove the hard-stop readout works and that normal mode did not change.

OBJECTIVE: implement B1 to B6 of docs/prompts/STAGE_C.3.md lines 146-182.

READ (by line range): docs/prompts/STAGE_C.3.md lines 104-182. EXPERIMENT.md lines 1072-1102 (Amendment 10). reports/c3_change_record.md (the hunks). news_eval/run_c2.py: _hard_stop_gate, _check_gate_pass, _check_marker_absent, check_preconditions, write_marker, run, _parser. news_eval/report.py: _hard_stop_entry, _hard_stop_lines, _verdict, _reading_verdict, _analysis, _provenance. news_eval/cutoff.py lines 219-245. news_eval/gate.py lines 93-108. news_eval/family.py build_analysis, _funnel. tests/test_news_eval_run_c2.py lines 40-215 (the helpers to reuse: write_unlock, _demark, stage, tree, refuses, config, RELEVANCE_FIXTURE). news_eval/synthetic.py: grep for SCENARIOS and def build. tests/test_news_eval_mutations.py lines 1-60 for the kill-check pattern.

OUTPUTS
1. tests/test_news_eval_hardstop.py (new file; follow the style of the existing test files).
2. reports/c3_evidence/normal_mode_identity.py and reports/c3_evidence/normal_mode_identity.txt (B1, below).
3. reports/c3_tests_record.md: one table row per test (name, what it proves, B item); the mutant kill table (mutant, how applied, the check that kills it, result); the suite result lines verbatim, with times from `date`.

FIXED DESIGN POINTS

Guard: the new file needs its own autouse guard. Do NOT copy the `[False] * 3` assertion: reports/c2_UNLOCK.json and reports/c2/ legitimately exist now, and that stale guard is why 157 teardowns error in the repo root (a known defect; do not edit it in any existing file). Your guard asserts that (exists, size, mtime_ns) of reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json and reports/c2 is unchanged by the test, patches sqlite3.connect so the repo's real database can never open, sets the test-mode env, and patches run_c2._mem_available_mb. The new tests must pass both in the repo root and in the clean clone. Do not import the existing `_guards` fixture by name.

The synthetic snapshot straddling the hard stop: build with synthetic.build into tmp, then shift dates in the copy with SQL so that S* lands after K.HARD_STOP_SESSION with a known number of scored rows after it (for example, add a fixed number of days to scoring_session and query_date). Use the REAL constant "2027-01-15"; do not patch K.HARD_STOP_SESSION in the happy path. Use _demark so the path is NON_SYNTHETIC, as the real run will be. S-HIGHRHO gives a real gate FAIL on REQUIRED; S-EFFECT gives PASS and a clear. Compute the expected restricted counts in the test with independent SQL on the shifted synthetic copy, and assert that rows after the hard stop exist and are excluded. Do not derive expected counts from the code under test.

Speed: family.compute runs 10,000 bootstrap draws and permutations per run. Use module-scoped fixtures so only a few full runs happen. Refusal and mutant checks should use check_preconditions, gate.evaluate, family.build_analysis on loaded inputs, and report.write on cached results. Do not run a full compute for each.

B1 byte identity against C.1 (one-off evidence, not a pytest test). Extract the C.1 code into the scratchpad: `git archive c757324 news_eval | tar -x -C <scratch>/c1_tree`. Write normal_mode_identity.py taking <tree root> and <out json>; it puts that tree first on sys.path, asserts news_eval loaded from it, and for EVERY scenario in synthetic.SCENARIOS builds the database in a temp dir and records sha256 of: gate.evaluate's entry as sorted JSON without utc_time and db_path; family.compute as sorted JSON; verdict.decide as sorted JSON; report.write with a fixed relevance summary and a fixed run_meta (no "mode" key). Run it once per tree, as two separate processes, one after the other, each under `nice -n 10` with PYTHONPYCACHEPREFIX set, then compare. normal_mode_identity.txt lists every scenario and quantity with MATCH or DIFF. Any DIFF is a blocking finding: report it, do not explain it away. Check MemAvailable first and stop if it is under 2 GB.

B2 happy path, end to end through run_c2.main with --hard-stop on the shifted S-HIGHRHO snapshot and its real FAIL entry: exit 0; verdict.md holds the gate line (C, M, Required, sigma, rho) and K.HARD_STOP_LABEL beside the verdict in section 4; marker and run_meta carry "mode": "hard_stop"; results.json analysis_set has hard_stop_session and analysis_cutoff; the gate's N, M and C and the analysis funnel's gate_rows and scored match your independent restricted SQL counts; no row after the hard stop is in either. Also:
- A clear with a FAIL entry: on S-EFFECT results and a run_meta holding a pass-false entry, the label comes after the registered row in each reading that clears, and report.write does not change verdict.decide's output.
- --hard-stop with a PASS entry: it runs, no K.HARD_STOP_LABEL anywhere in verdict.md, and the sentence that the label does not apply is present (the lead's ruling).
- Normal mode on a post-hard-stop snapshot with a PASS entry: it runs, is restricted, mode "normal", no gate line, no label.

B3 refusals, each exit 2 with nothing written (tree() compared before and after, no marker): S* earlier than the hard stop (an unshifted snapshot with an ok entry); a missing gate entry (empty log, and a log holding only another snapshot); a degenerate entry; a marker already present. Also from the design: an entry under another manifest_sha256; an entry with another S*; an entry without analysis_cutoff; an entry missing a gate-line quantity, or with a string value in one; a non-bool pass; an earlier entry for another snapshot with pass true; an earlier entry for another snapshot with S* at or after the hard stop. And: normal mode with a FAIL entry on a post-hard-stop snapshot refuses; after a completed hard-stop run, both a second --hard-stop and a normal run refuse.

Also test acceptance when a LATER entry for another snapshot has reached the hard stop: the first snapshot stays runnable.

B4 the restriction is shared: on one snapshot the gate entry's analysis_cutoff equals results' analysis_cutoff, and gate N equals funnel gate_rows, gate M equals funnel scored. Prove one function: patch cutoff.analysis_cutoff to return a sentinel earlier date and show BOTH the gate rows and the analysis set move. Unit-test analysis_cutoff and hard_stop_record at None, before, equal to and after the hard stop, and that a row scoring exactly on the hard stop is included.

Also pin: K.HARD_STOP_SESSION == "2027-01-15", recomputed in the test from weekdays since 2026-07-28 minus the holidays 2026-09-07, 2026-11-26, 2026-12-25, 2027-01-01 (session 120, no database); K.HARD_STOP_LABEL occurs verbatim in EXPERIMENT.md; and `check_preconditions` under --hard-stop opens only the GATE phase, never VERDICT (record phases by wrapping data.open_phase), so no outcome column is read before the marker.

B5 mutants. Apply each at SOURCE level to one function: take inspect.getsource, require the exact old text to be present (fail the test if it is absent), replace it, compile it with the module's __dict__ as globals, and monkeypatch the module attribute. For each mutant run its kill checks unmutated (all must pass), then mutated (at least one must fail). Required four:
 M1 apply the restriction to the analysis set only (gate._read_inputs keeps cut.s_star).
 M2 allow --hard-stop with S* earlier than the hard stop.
 M3 drop the label (both places it prints).
 M4 let --hard-stop skip the marker-absent precondition. WARNING: write_marker's O_EXCL still refuses under this mutant with the same check name, so a kill check through run_c2.main will NOT kill it. Kill it by calling check_preconditions(cfg) directly and asserting Refused with check marker_absent.
Add these, same method:
 M5 restriction on the gate only (build_analysis keeps sstar.s_star).
 M6 normal mode accepts a FAIL entry.
 M7 label printed after a PASS entry.
 M8 drop the earlier-PASS and first-snapshot check.
 M9 _funnel keeps the raw S*.
A surviving mutant is a finding: report it, do not weaken the mutant to get a kill.

B6 suites, both through the wrappers. Each takes about 5 minutes; run them one at a time, as background Bash calls or with a timeout of 600000:
 Clean clone, the one that decides B6:
  /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/run_suite_clean.sh /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/suite_partB_clean.log
  Expected: 782 plus your new tests passed, 1 skipped (the real-manifest test until the lead's re-freeze), 0 failed, 0 errors. The wrapper's clone copies your test file by the glob.
 Repo root, for the record:
  /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/run_suite.sh /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/suite_partB_root.log
  Expected: the same passes, plus teardown errors that are ALL the C2_PATHS guard (`assert [True, False, True] == [False, False, False]`), none in your new file. List any other error or FAILED line by name.
Exit 75 means refused or stopped for memory or the collector window: report it, and never free memory by touching another process. Never two heavy runs at once. Targeted runs: export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc && nice -n 10 .venv-eval/bin/python -m pytest -q tests/test_news_eval_hardstop.py with output to a file; read the tail only.

Copies of both wrappers are at reports/c3_evidence/run_suite.sh and reports/c3_evidence/run_suite_clean.sh.

BOUNDARIES
- Edit nothing under news_eval/ and no existing test file. If a test shows a harness bug, write the failing test, stop, and report it; the lead rules and fixes.
- Synthetic databases and tmp paths only. Never open news_experiment.db, analysis_bars.db, or anything under reports/c2*. Never read real judgments or outcomes. Never run freeze write, or gate or run_c2 on real data. No paid API call. Only .venv-eval; no install. No commit, no push. Do not edit reports/C.3_STATE.md or reports/c3_change_record.md. No .pyc under news_eval/.

COLLECTOR WINDOW: machine local time is America/Vancouver. Check `date` before each test run, and before any long write. At or after 22:55 today start no new run: save your work, update reports/c3_tests_record.md with exactly what is done and what remains, and return. Nothing of yours may run between 23:00 and 23:45.

HOOK NOTE: a GateGuard PreToolUse hook may block your first Bash call or first edit or write of a file and ask you to state facts, including the user's instruction. The instruction to quote is: "Read docs/prompts/STAGE_C.3.md in full and execute it as your prompt. Run unattended." State the facts in plain text and retry the same call. Check that a blocked edit actually got applied.

REPLY: the output paths, a summary of at most 200 words with the test and mutant counts and both suite result lines, and anything unfinished or unverified.
