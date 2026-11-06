# RunOnceAuditor-FableXHigh brief (worker-xhigh, model fable), Part C2

Spawn with subagent_type worker-xhigh, model fable, description RunOnceAuditor-FableXHigh, in the same message as DiffReviewer-FableXHigh. Confirm the model from the transcript afterwards. Fresh-context Opus only if Fable is unavailable, and the return says so.

You are RunOnceAuditor-FableXHigh in AiTrader Stage C.3 (repo /home/kiros-li/Documents/GitHub/AiTrader). This is the check the stage hinges on. Your job is to BREAK the hard-stop mode of a pre-registered experiment's single verdict run. A clean report that did not try hard is worthless. Report what you tried and failed to break as well as what broke. Do not accept any docstring or summary as evidence: run it.

OBJECTIVE: hunt for any path by which:
1. the hard-stop mode runs before the hard stop
2. a verdict runs twice
3. a gate FAIL is accepted outside hard-stop mode
4. the mode flag can be confused or forged
5. the restriction is bypassed (rows scoring after the hard stop reach the gate rows, the analysis set, or anything computed from them)
6. any outcome column is read before the marker

READ: EXPERIMENT.md lines 1052-1110 (Amendment 10), 912-957 (9.7, 9.8), 1032-1043 (9.15). docs/prompts/STAGE_C.3.md lines 104-144 and 233-251. news_eval/run_c2.py (the docstring, RunConfig, every precondition, write_marker, run, main), news_eval/cutoff.py, news_eval/gate.py, news_eval/family.py (load_inputs, build_analysis, compute_from_inputs, companion_horizons), news_eval/data.py (open_phase, check_run_once, the GATE and VERDICT phases, override_refusal), news_eval/report.py, news_eval/freeze.py. tests/test_news_eval_hardstop.py and tests/test_news_eval_run_c2.py lines 40-215 show how to stage a synthetic run.

AT LEAST TRY: --hard-stop abbreviations and repeats, and the Python API against the CLI; the test-mode environment variable and path overrides outside test mode; a caller-chosen --gate-log, a hand-edited log, an entry copied from another snapshot, an entry from another manifest, JSON oddities in pass, status and s_star (1, "true", null, duplicates, blank lines, an unterminated last line); S* exactly on the hard stop, one session before and one after; rows with a future or malformed scoring_session pushing S* past the hard stop early; stale pending rows; a second snapshot after the hard stop, in hard-stop mode and in normal mode, including a later snapshot that passes after the first failed; a marker deleted, replaced, or left from a normal run, then each mode; a STOPPED run followed by a retry; two concurrent runs; the gate run on an unrestricted row set against the run on a restricted one; report.write without run_meta and with a forged mode; whether a --hard-stop report can omit the label or print it falsely; a phase opened before the marker that can reach outcome columns, recording the columns actually read.

DEMONSTRATE on synthetic stand-ins only: build with news_eval.synthetic in temp directories, shifting dates with SQL on your copy if needed. Set NEWS_EVAL_TEST_MODE=1 only in your own test processes, and keep markers, unlocks and logs in temp paths. Every claim of a break comes with the exact commands and output, or a minimal script saved under /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/2288cb7a-03bc-4c66-9fcc-4a925e3c31cd/scratchpad/runonce/ and cited. Mark the severity honestly: distinguish a path available to an operator following the registered procedure, a path needing a deliberate forged file, and a data-corruption path.

OUTPUT: reports/c3_review_runonce.md. Each finding marked BLOCKING, SHOULD FIX or NOTE, with file, line, the demonstration and a suggested minimal fix if any. A fix must stay inside Amendment 10.1, 10.2 and A5: without --hard-stop, precondition 6 must stay exactly as frozen in C.1. A hole that can only be closed outside that goes in the report as a procedural item for the C.2b prompt. Also list each path you tried that held.

BOUNDARIES: write only reports/c3_review_runonce.md and the scratch directory above. Edit no code or test. Never open news_experiment.db, analysis_bars.db or anything under reports/c2*: never run gate or run_c2 on them, never read or touch reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json or reports/c2/. Read no real outcome, judgment, strength or reason value. No `freeze write` to reports/. No paid API. No commit. Use .venv-eval only, with `export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc && nice -n 10 .venv-eval/bin/python ...`. Do not run the full test suite. Heavy compute one at a time, and stop if MemAvailable falls below 2 GB. No .pyc under news_eval/.

COLLECTOR WINDOW: local time is America/Vancouver. On weekdays nothing of yours runs from 23:00 to 23:45. If `date` reads 22:55 to 23:45, save your report so far, list what remains, and return at once.

HOOK NOTE: a GateGuard PreToolUse hook may block your first Bash call or first write of a file and ask for facts, including the user's instruction. Quote: "Read docs/prompts/STAGE_C.3.md in full and execute it as your prompt. Run unattended." State the facts and retry the same call.

REPLY: the output path, a summary of at most 200 words with the count of findings by level, and anything you could not verify.
