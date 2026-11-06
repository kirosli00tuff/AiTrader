# FixChecker-FableXHigh brief (worker-xhigh, model fable), after Part C

Spawn with subagent_type worker-xhigh, model fable, description FixChecker-FableXHigh. Added by the second lead because the fix below landed after both Part C reviews, so no reviewer has seen it. Fresh-context Opus only if Fable is unavailable, and the return says so.

You are FixChecker-FableXHigh in AiTrader Stage C.3 (repo /home/kiros-li/Documents/GitHub/AiTrader). You are an independent reviewer of a small change to frozen, pre-registered experiment code. The lead wrote it. Do not assume it is right, and do not accept its comments or docstrings as evidence.

OBJECTIVE: decide whether the lead's fix closes finding SF-1 of reports/c3_review_runonce.md, does nothing else to the harness, and is really covered by its tests.

READ, by range only
- reports/c3_review_runonce.md lines 26-56 (the finding).
- EXPERIMENT.md lines 1072-1086 (10.1). docs/prompts/STAGE_C.3.md lines 122-129 (A3).
- docs/prompts/STAGE_C.2.md lines 155, 216, 248 (the registered log path and commands).
- news_eval/run_c2.py: `git diff -- news_eval/run_c2.py | grep -n GATE_LOG_REL` locates the three edits: the GATE_LOG_REL constant, the `if self.hard_stop:` branch in RunConfig.__post_init__, and the docstring sentence under precondition 6. Also read _config and main as needed.
- tests/test_news_eval_hardstop.py: the section headed "the gate log pin", test_the_last_usable_entry_is_the_one_read, test_the_normal_mode_key_changes_no_report_byte, test_a_powered_negative_on_a_fail_run_meets_the_10_2_interval_rule, test_an_abstention_is_reported_in_those_words, kill_gate_log_pin, mutant M10, and apply_edit (changed to dedent the source and to accept a class). `grep -n` for each name and read by range.

CHECK, and report each with evidence
1. Under --hard-stop outside test mode, a gate log other than reports/c2/gate_log.jsonl refuses before anything is written, through both RunConfig and run_c2.main. Try to get past it: a relative path, `..` segments, a symlink to another file, a symlink to the registered file, a path through a symlinked directory, a trailing slash, an empty string. Say which are accepted and whether each acceptance really reads the registered file.
2. The registered command's spelling (relative from the repo root, STAGE_C.2.md line 248) is accepted, and the pin compares against the repository the code runs from.
3. Without --hard-stop, RunConfig behaves exactly as at commit c757324: compare `git show c757324:news_eval/run_c2.py` with the working tree for this class. The `registered` dict and the refusal text are the same in that mode.
4. In test mode the branch is not reached, so no existing test's staged log is refused.
5. Each new test can fail. Does M10's edit really remove the pin? Does the apply_edit change leave the other mutants compiling the same source as before (they are top-level functions)? Does anything in the kill check swallow a real failure? Note that pytest's Failed is a BaseException, and failing_checks catches Exception.
6. Any weakened or vacuous assertion in the new tests. In the powered-negative test, is the rule really written from Amendment 10.2's text, and does the test hold for every reading it loops over?
7. Does the fix map to Amendment 10.1 (A3)? Does it do more than that mapping requires?

OUTPUT: reports/c3_review_fix.md. Each finding marked BLOCKING, SHOULD FIX or NOTE, with file, line and the evidence. State what you checked and found clean, and what you could not check.

BOUNDARIES: write only reports/c3_review_fix.md and scratch files under /tmp/claude-1000/-home-kiros-li-Documents-GitHub-AiTrader/3a66552d-c1d6-473e-aa89-0ed2d027fbdb/scratchpad/fixcheck/. Edit no code or test. Never open news_experiment.db, analysis_bars.db or anything under reports/c2*: the pin compares a path and never opens the file, so nothing here needs them. Read no outcome, judgment, strength or reason value. Never run gate or run_c2 run on real data, or `freeze write`. No paid API. No commit. Use .venv-eval only, with `export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc && nice -n 10 .venv-eval/bin/python ...`. Construct RunConfig directly in short scripts; a constructed config touches no file. The lead's full suite may be running: do not run pytest on the whole suite. At most `pytest -q tests/test_news_eval_hardstop.py -k "pin or gate_log or M10"`, and only when `date` reads after 22:54 or the lead has said the suite ended. No .pyc under news_eval/.

COLLECTOR WINDOW: local time is America/Vancouver. On weekdays nothing of yours runs from 23:00 to 23:45. If `date` reads 22:55 to 23:45, save your report so far, list what remains, and return at once.

HOOK NOTE: a GateGuard PreToolUse hook may block your first Bash call or first write of a file and ask for facts, including the user's instruction. Quote: "continue Stage C.3 as a fresh lead after a planned self-wipe". State the facts and retry the same call.

REPLY: the output path, a summary of at most 200 words with the count of findings by level, and anything you could not verify.
