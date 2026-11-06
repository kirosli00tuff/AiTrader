
STAGE C.2b "GATE RERUN AND THE SINGLE VERDICT RUN (CONTINUATION)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: C.2 attempt 1 (reports/C.2_RETURN.md, 2026-10-28) took a
snapshot and ran the gate. It failed: C = 65, M = 5,363 against a
Required of 13,335, with sigma 442 bp against the 180 bp assumed.
Amendment 10 then registered a hard stop at session 120 (2027-01-15).
Stage C.3 (reports/C.3_RETURN.md) built the hard-stop mode into
news_eval/ and re-froze the harness as reports/c3_harness_freeze.json.

This prompt is reusable. Each launch is one attempt, named by its date
<YYYYMMDD> from `date +%Y%m%d` at Step 1. Each attempt does exactly what
C.2 did, against the new hashes:
1. Snapshot news_experiment.db with the frozen runner.
2. Run the gate on that snapshot, and have Fable recompute it.
3. If the gate passes, run the verdict exactly once.
4. If the snapshot's S* is on or after the hard stop, that snapshot is
   the hard-stop snapshot (C.3 item P1). The verdict runs exactly once on
   it in `--hard-stop` mode, whether the gate passed or failed, and no
   later snapshot is gated or run.
5. After any run, Fable recomputes every verdict number and attacks the
   reading.
If the gate fails before the hard stop, the attempt ends after step 2,
judgments stay unread, and collection continues.

Lead: Opus 5.5, effort max. Ultracode: off.
- Reviewers: Fable, with the model confirmed from each reviewer's
  transcript. Opus max in a fresh context only if Fable is unavailable,
  and the return says so.

Why this lead and effort: this session may be the single verdict run of
a pre-registered experiment. The compute is frozen and mechanical. The
judgment is in the gates, the mode choice, the verdict reading and the
rulings. That needs max. One serial chain with review spawns does not
justify ultracode.

Usage and time: a gate FAIL attempt takes about 1 hour, mostly the Fable
gate recomputation. A run attempt takes 2 to 4 hours, mostly
verification. Launch outside 23:00 to 23:45 America/Vancouver on
weekdays. If 22:55 arrives mid-run, finish the current tool call, start
nothing new, checkpoint STATE, and resume at 23:45. Never start
`run_c2 run` after 22:30 on a weekday. Checkpoint to
reports/C.2b_STATE_<D>.md after every step.

- Self-wipe (V9, from PropExperiment V60): at about 150k tokens of lead
  context, at a quiet point (no worker or foreground job running, detached
  jobs may continue), and never between writing the run-once marker and the run's end:
  1. write a RESUME HERE section of at most 60 lines in reports/C.2b_STATE_<D>.md: what is
     done, what is next, the exact continuation commands, each unfinished
     worker with its brief path, and each detached job allowed to keep
     running
  2. append "READY FOR WIPE <time>" to the STATE file
  3. run this one command, then end the turn with no further tool call:
     setsid nohup bash -c 'sleep 30; tmux send-keys -t stage-c2b "/clear"; sleep 1; tmux send-keys -t stage-c2b Enter; sleep 8; tmux send-keys -t stage-c2b "Read the newest RESUME HERE section of reports/C.2b_STATE_<D>.md and every STATE line after it, then the parts of docs/prompts/STAGE_C.2b.md it points to, and continue Stage C.2b as a fresh lead after a planned self-wipe. First append a line Lead self-wipe done to the STATE file with the time. Earlier workers cannot be messaged: re-spawn any unfinished worker from its brief. A detached job still running is checked from disk and never started twice. Do not redo finished work. Run unattended."; sleep 1; tmux send-keys -t stage-c2b Enter' >/dev/null 2>&1 &
  Replace <D> with the attempt date in the command. The /clear keeps the
  same CLI process, model and effort.
- A usage-limit stop or a shutdown: write RESUME HERE if possible. The
  claude-auto-retry monitor resumes after a usage limit. The planner
  resumes anything else.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue. The
stops are exactly the ones named in this prompt. Each one ends the
session with a written return document.

============================================================
DECISIONS IN FORCE (docs/DECISIONS.md V1 to V8)
============================================================

V2 holds in full, as written for C.2, with these changes:
1. **The unlock (V8).** reports/c2_UNLOCK.json was rewritten on
   2026-11-06 by the planning chat on Kiros's explicit instruction
   (2026-11-05 22:00 America/Vancouver), binding the Amendment 10
   EXPERIMENT.md and the C.3 manifest. The attempt-1 unlock stays in git
   history. This session never creates, edits or rewrites the unlock. If
   it is absent or refused, stop.
2. **Gate cadence (V2 item 2).** One gate per snapshot. The next attempt
   needs at least 5 more distinct judged collection query_dates than
   the previous snapshot, and a new snapshot directory.
3. **The hard stop (Amendment 10, V4).** HARD_STOP_SESSION is 2027-01-15.
   The analysis set and the gate rows are restricted to
   scoring_session <= min(S*, HARD_STOP_SESSION) by the frozen code. The
   hard-stop run happens at most once, on the first snapshot whose S* is
   on or after the hard stop, whatever its gate says, and only if no
   earlier run exists.
6. **C.3's procedural items P1 to P6** (reports/C.3_RETURN.md section 7
   item 2, verbatim from reports/c3_rulings.md) bind this stage. Steps 2
   to 3 carry each one, by its number.
4. **Run once, ever (9.15).** reports/c2_RUN_ONCE.json is written by the
   first `run_c2 run`, in either mode, and never by anything else. If it
   exists at startup, stop: the verdict has already run.
5. V2 items 3 to 8 hold unchanged: no successor draft, D5 and revised
   D7 kept, the day-clustered version governs, a kill after the marker
   is STOPPED, and the harness runs only under .venv-eval/bin/python.

Binding, in priority order:
1. EXPERIMENT.md, sha256
   964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe. It is
   locked (10.3).
2. The C.3 manifest reports/c3_harness_freeze.json, sha256
   19dc1da78608f7f9d5fdf1fedc0edf024bb39529be1dabbc45681ce393d38bc8. `freeze check` must print FROZEN: match on it.
3. reports/c2_UNLOCK.json, whose experiment_sha256 and manifest_sha256
   must equal items 1 and 2.
4. This prompt.

============================================================
SCOPE
============================================================

This stage does:
- the startup readiness check, the snapshot, the gate and its Fable
  recomputation, and if allowed the single run, using only the frozen
  commands below
- after a run, the Fable recomputation and the Fable max review, with a
  ruling on each finding
- the per-attempt return document and the commits named under
  GUARDRAILS

This stage does NOT:
- edit any file in the C.3 manifest, EXPERIMENT.md, news_experiment/,
  backtest/, the collector units or COLLECTION_LOG.md. Any change to a
  frozen file voids the run.
- create or touch reports/c2_UNLOCK.json
- run `run_c2 run` more than once in the life of the experiment, or
  rerun anything with changed settings, seeds, subsets or definitions
- run `--hard-stop` before S* reaches the hard stop, or run without it
  once S* has reached the hard stop
- gate or run any snapshot after the hard-stop snapshot (P1)
- run the test suite. The autouse guards in three test files assume
  reports/c2* do not exist (found in C.3). Tests are not part of this
  stage.
- compute any number outside the frozen harness and the Fable
  verification, report exploratory analysis as a finding, or compute 2,
  5 or 10-session horizons
- commit any database file, including the snapshot
- design the successor study, touch PropExperiment, or touch RiskGate,
  the live gate or the adaptive invariant

============================================================
CONTEXT TO READ FIRST
============================================================

1. CLAUDE.md and docs/ORCHESTRATION.md. On any conflict CLAUDE.md wins
   and the conflict is logged.
2. reports/C.2_RETURN.md sections 1, 3 and 7. reports/C.3_RETURN.md
   sections 1, 3 and 7, for the exact `--hard-stop` interface and the
   label. reports/C.1_RETURN.md sections 3 and 7.
   reports/c1_verdict_mapping.md in full.
3. EXPERIMENT.md by section (`grep -n '^## \|^### ' EXPERIMENT.md`):
   Amendment 5's verdict table, quoted, Amendment 6's claim boundary,
   8.1 and 8.2, Amendment 9 in full, Amendment 10 in full, and Task 6.
4. The docstrings of news_eval/run_c2.py and news_eval/gate.py. Read
   them only. They are frozen.
5. Every earlier per-attempt return, reports/C.2b_RETURN_*.md, if any.

============================================================
GUARDRAILS
============================================================

CLAUDE.md invariants apply in full, except that the outcome columns
unlock in the order this prompt gives, and only through the frozen
harness and the Fable verifier, reading the snapshot. This stage adds:

- Every harness command runs as
  `cd ~/Documents/GitHub/AiTrader && export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 && nice -n 10 .venv-eval/bin/python -m ...`.
  Never use the repo .venv.
- The live database is never opened except through `run_c2 snapshot`
  and the counts-only checks in Step 0 and Step 1. Every outcome read is
  from the snapshot copy.
- Nothing runs between 23:00 and 23:45 America/Vancouver on a weekday.
  Never stop, restart or edit the collector.
- `run_c2 run` refuses below 2,048 MB of available memory. On a memory
  refusal, wait and retry the preconditions only. Never kill another
  session.
- Per-attempt file names, with <D> = `date +%Y%m%d` taken once at
  Step 0 and used for the whole attempt:
  reports/C.2b_STATE_<D>.md, reports/C.2b_RETURN_<D>.md,
  reports/c2/snap_<D>/, reports/c2/verify_gate_<D>/ and
  reports/c2_gate_verify_<D>.md. Never overwrite an attempt-1 file or an
  earlier attempt's file. The run files (reports/c2/run/,
  reports/c2/verify/, reports/c2_verdict_verify.md,
  reports/c2_verdict_review.md, reports/c2_rulings.md) exist at most
  once.
- Commits, in this order, explicit paths only, never `git add -A`.
  COLLECTION_LOG.md is never staged.
  1. "C.2b snapshot and gate <D>": reports/c2_UNLOCK.json if it changed,
     reports/c2/snap_<D>/snapshot.json and reports/c2/gate_log.jsonl
  2. Only after a run: "C.2b run-once marker and results <mode>":
     reports/c2_RUN_ONCE.json and every file the run wrote under
     reports/c2/run/, including results_STOPPED.json if it stopped. Push
     right after this commit so the marker is on GitHub.
  3. "Stage C.2b <D> <verdict, hard-stop verdict, or gate FAIL>": the
     return document, STATE, the verify and review files, the ruling
     file, PROGRESS.md, RETURN.md, docs/STAGES.md and
     docs/prompts/README.md. Push.
- Push in the foreground with
  `export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus && timeout 60 git push origin main`.
  On failure, retry once, then record it under Decisions for the user.
  A background push failed silently before.
- Start and end checks, quoted verbatim in the return:
  - the CLAUDE.md status command (export XDG_RUNTIME_DIR first)
  - `git status --short` and `git log --oneline -5`
  - `sha256sum EXPERIMENT.md`, which must equal Binding item 1
  - `... -m news_eval.freeze check`, which must print FROZEN: match on
    Binding item 2
  - `cat reports/c2_UNLOCK.json`, whose two hashes must equal Binding
    items 1 and 2
  - `ls -la reports/c2* reports/c2/` and `free -m`
  If any check differs at start, stop.
- Before ending, confirm no worker or background shell is still running.

============================================================
STEP 0: STARTUP AND READINESS (lead)
============================================================

Run the start checks. Then verify, in order. Each failure ends the
session with a short return document.

1. reports/c2_UNLOCK.json exists and matches Binding items 1 and 2.
2. reports/c2_RUN_ONCE.json does NOT exist (V8 item 4).
3. docs/SUCCESSOR_PREREG_DRAFT.md does not exist.
4. Readiness, from counts only:
   `sqlite3 "file:news_experiment.db?mode=ro" "SELECT COUNT(DISTINCT query_date) FROM news_observation WHERE run_kind='collection' AND state='judged';"`
   The count must be at least 5 more than the same count on the most
   recent snapshot in reports/c2/, opened read-only and immutable
   (`file:<path>?mode=ro&immutable=1`). The planner measured 60 on
   snap_20261028 and 65 live at 2026-11-05 22:10. If the check fails,
   stop before any snapshot, and write when to come back.
5. The mode. HARD_STOP_SESSION comes from news_eval/constants.py. If
   today's date is earlier than the hard stop, this attempt is
   NORMAL-ONLY: it may run only after a gate PASS. Otherwise it is
   HARD-STOP-ELIGIBLE, decided finally by the snapshot's S* in Step 2.

Print the estimate ETA table in chat. Create reports/C.2b_STATE_<D>.md
and update it after every step.

============================================================
STEP 1: SNAPSHOT (lead)
============================================================

Take the CLAUDE.md status counts, then immediately run
`... -m news_eval.run_c2 snapshot --source news_experiment.db --out-dir reports/c2/snap_<D>`.
Record the exit code. If reports/c2/snap_<D>/ already exists, stop: one
attempt per day.

Then compare snapshot.json's collection row total with the status count
taken just before. They must be equal. If they differ, stop.

============================================================
STEP 2: GATE (lead, then GateVerifier-FableXHigh)
============================================================

Run `... -m news_eval.gate --db reports/c2/snap_<D>/news_experiment_snapshot.db --log reports/c2/gate_log.jsonl`.

Record the new last line verbatim: C, M, sigma, rho, n0, k_eff,
Required, S*, pass, manifest_sha256. Check that its manifest_sha256 is
Binding item 2. Make commit 1.

GateVerifier-FableXHigh (worker-xhigh on fable) then recomputes the gate
from the snapshot with its own code under reports/c2/verify_gate_<D>/,
following 9.1, 9.7, 9.8 and 10.1 literally, including the hard-stop
restriction of the gate rows:
- open the snapshot read-only and immutable
- read only query_date, scoring_session, state, run_kind,
  exclusion_reason, outcome_state and excess_1session, plus a judgment
  COUNT GROUP BY scoring_session
- never read a row-level judgment, strength or reason

It matches the log line within 1e-9 relative, and exactly for counts.
Findings go to reports/c2_gate_verify_<D>.md.

Then exactly one branch applies:
- **S* is earlier than HARD_STOP_SESSION, verified PASS:** go to Step
  2b, then Step 3 in normal mode.
- **S* is earlier than HARD_STOP_SESSION, verified FAIL:** stop
  here. Write the return document with the gate numbers, the change
  since each earlier attempt (C, M, Required, sigma, rho), and the
  earliest date of the next attempt at 5 more judged collection days.
  Make commit 3. Judgments stay unread.
- **S* is on or after HARD_STOP_SESSION:** this is the hard-stop
  snapshot (P1). Go to Step 2b, then Step 3 in hard-stop mode, whether
  the gate passed or failed. If the gate is degenerate on it, stop for
  the planner, because the code refuses every later snapshot too.
- **The verifier disagrees with the gate:** the frozen gate's line
  stands, and nothing runs. Stop and report the disagreement under
  Decisions for the user.

============================================================
STEP 2b: PRE-RUN CHECKS (only before a run: P2, P3, P4, P6)
============================================================

- **P2:** every gate run and the run use `--gate-log
  reports/c2/gate_log.jsonl`, spelled relative from the repo root. The
  run spells `--hard-stop` in full. `--hard-stop` with any other log
  exits 2.
- **P3:** GateIntegrity-FableXHigh (worker-xhigh on fable) reruns the
  frozen gate on the snapshot into a scratch log, never the registered
  one, and compares every registered log entry for that snapshot's
  sha256 with its output, field by field except the time. It also checks
  `git log -p -- reports/c2/gate_log.jsonl` shows only appended lines,
  none removed or changed. Commit 1 must already hold the log. Output:
  reports/c2_gate_integrity_<D>.md. Any mismatch stops the stage.
- **P4:** the same verifier confirms that no file carrying
  `c2_run_once/1` exists anywhere in the repo outside
  reports/c2_RUN_ONCE.json, and that reports/c2_RUN_ONCE.json itself does
  not exist.
- **P6:** the lead confirms S* is not later than the snapshot's date, and
  compares the count of sessions on or before the hard stop with 120
  minus the recorded gaps. Counts only.


Check `free -m`, that no marker exists, and that the time is before
22:30 on a weekday or any time on a weekend. Then run, once, the
command for the branch:
- normal mode:
  `... -m news_eval.run_c2 run --snapshot reports/c2/snap_<D>/news_experiment_snapshot.db --out-dir reports/c2/run --gate-log reports/c2/gate_log.jsonl --relevance-summary reports/c1_relevance_summary.json`
- hard-stop mode: the same command with `--hard-stop`, exactly as
  documented in reports/C.3_RETURN.md section 3. If C.3 documents a
  different form, the documented form governs and the difference is
  logged.

Exit codes:
- **0:** results.json, run_meta.json and verdict.md were written.
  run_meta records the mode.
- **2:** refused, with nothing written and no marker. A memory refusal
  may be retried after waiting. Any other refusal is a stop: report it.
- **3:** STOPPED after the marker. That is the registered result. Never
  rerun.

Make commit 2 and push it at once. **P5:** the marker and the whole
out-dir go in that one commit, and the return records the marker's
sha256 and the commit hash. Then read verdict.md and results.json. In hard-stop mode, confirm that verdict.md carries the
label "registered power rule NOT met" beside the gate line.

============================================================
STEP 4: INDEPENDENT RECOMPUTATION (VerdictVerifier-FableXHigh)
============================================================

Only after a run. The brief to the verifier, as in C.2 Step 4, plus the
restriction:
- Do not open reports/c2/run/ or any news_eval/ module until your own
  numbers are written to reports/c2/verify/own_results.json.
- Work from EXPERIMENT.md (Tasks 5 to 7 and Amendments 5, 6, 8, 9 and
  10, by section) and the snapshot, opened read-only and immutable, in
  your own Python under .venv-eval.
- Recompute: S*, the 10.1 restriction, the 9.1 excluded days and the
  analysis-set counts, the Amendment 6 diagnostics, T for P1 to P4 and
  E1 to E4 in both readings, S1 and S2, SE and z with your own seed, the
  permutation p for P1 to P4 with your own seed, the 8.2 exclusion sets
  (rules a and b), the sector CR1 SE and the story-group share, and the
  verdict row each status implies under reports/c1_verdict_mapping.md.
- Compare with results.json: exact quantities within 1e-9 relative, SE
  within 3 percent, p within its Monte Carlo error. Any bar call that
  flips is BLOCKING.
- Output: reports/c2_verdict_verify.md, each finding marked BLOCKING,
  SHOULD FIX or NOTE.

============================================================
STEP 5: THE HINGE REVIEW (VerdictReviewer-FableMax)
============================================================

Only after Step 4. Read verdict.md, results.json, the mapping, Amendment
5's table, Amendment 6's claim boundary, 8.1, 8.2, and Amendments 9 and
10. Check:
- the Amendment 5 row follows from the statuses
- every sentence stays inside the registered wording ("the pipeline
  predicts", never "the model understands")
- a gross positive with net abstentions or failures licenses no trade
- the 8.2 disagreement rule is applied if the readings differ
- in hard-stop mode, the power shortfall and its label sit beside the
  verdict, and a null is never written as evidence of no effect
- nothing exploratory is presented as a finding
- the relevance rates, the closed-end-fund defect and the 8.1 cutoff
  statement are present
Then list, as caveats only: the benchmark construction, the formation
switch on 2026-10-01, the preferreds, the credit-outage days, the gaps,
and the clustering. Caveats never change the verdict.

Output: reports/c2_verdict_review.md.

============================================================
STEP 6: RULINGS (lead)
============================================================

Rule on every Step 2, 4 and 5 finding in reports/c2_rulings.md (after a
run) or in the return (after a gate FAIL). The frozen output is the
registered result in every case. A wording error is fixed in the return
only, and verdict.md is quoted, never edited. A demonstrated code error
in the frozen harness never triggers a second run. The return gives the
registered result, the error, and the verifier's figure labelled NOT
REGISTERED, under Decisions for the user.

============================================================
STEP 7: RETURN AND COMMIT (lead)
============================================================

Write reports/C.2b_RETURN_<D>.md. Add a dated entry at the top of
PROGRESS.md and of RETURN.md, one line under Stage C in docs/STAGES.md,
and the attempt in the C.2b row of docs/prompts/README.md. Make commit 3
and push.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| 0, 1, 2, 3, 6, 7 | lead | opus | max | serial | the snapshot, the gate, the mode choice and the single run are reserved to the lead, and so is the verdict reading |
| 2 verify | GateVerifier-FableXHigh | fable | xhigh | after the gate line | gate numbers decide whether outcomes unlock |
| 2b | GateIntegrity-FableXHigh | fable | xhigh | only before a run | P3 and P4: the log and the marker path are untampered |
| 4 | VerdictVerifier-FableXHigh | fable | xhigh | after Step 3 | every verdict number recomputed by a different model |
| 5 | VerdictReviewer-FableMax | fable | max | after Step 4 | the one hinge review of the verdict reading |

If Fable is unavailable, each Fable step runs on Opus max in a fresh
context and the return says so. The run itself never waits for
Fable. If verdict verification is pending, the verdict is labelled
UNVERIFIED until it is done.

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each task into subtasks with one objective, inputs, output
       path and format, allowed tools, and boundaries.
    2. Route per CLAUDE.md. State model and effort for each subtask before
       spawning; confirm each reviewer's model from its transcript.
    3. At most 4 concurrent. Small tasks needing no isolation go inline.
    4. Collect results as files plus short summaries.
    5. Verify every number entering a verdict with an independent fable
       worker.
    6. Synthesize in the lead against this prompt, and write the synthesis
       to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to
       reports/C.2b_STATE_<D>.md after each task.

============================================================
WHAT NOT TO DO
============================================================

- Never run `run_c2 run` twice, never delete or move the marker, and
  never rerun anything with changed settings.
- Never run `--hard-stop` before S* reaches the hard stop, and never
  run without it once S* has reached the hard stop.
- Never create or edit reports/c2_UNLOCK.json.
- Never edit a frozen file, EXPERIMENT.md, or the collector.
- No outcome read from the live database. No row-level judgment read
  before a verified gate PASS or a verified hard-stop FAIL.
- No 2, 5 or 10-session horizons. No exploratory result reported as a
  finding.
- No commit of any .db file. No `git add -A`.
- Never write "the model understands". Never present a gross-only
  positive as a strategy.

============================================================
DELIVERABLE: ONE RETURN DOCUMENT PER ATTEMPT
============================================================

Write reports/C.2b_RETURN_<D>.md. Fixed sections, in order:

1. Summary, at most 250 words: "gate FAIL" with C, M and Required and
   the next attempt date, or the Amendment 5 row verbatim with the mode,
   each primary's status beside its 8.2 reading, the E-test statuses,
   the claim-boundary sentence, the hard-stop label if it applies, and
   whether Fable confirmed the numbers.
2. Guardrail evidence: the start and end checks verbatim, every outcome
   read and by whom, the order of events with timestamps from `date`,
   and `git status --short` and `git diff --stat` for each commit.
3. Results: the gate line, and a table of every attempt so far (date, C,
   M, Required, sigma, rho, k_eff, S*, pass). After a run: the
   diagnostics, the P1 to P4, E1 to E4, S1 and S2 table in both readings,
   the sector and story figures, the relevance rates, and verdict.md
   quoted in full. After a run: the marker sha256 and its commit (P5), and
   a statement that family.compute was called only through run_c2 (P4).
4. Delegation record: one row per spawn, with each reviewer's model
   confirmed from its transcript.
5. Verification: each Fable finding, the ruling and the fix.
6. Open choices.
7. Decisions for the user, each with a recommendation first. After a
   FAIL: the next attempt date. After a run: what the verdict permits
   next under Amendment 5's table, the successor Stage A, the publishing
   refresh (llm-news-drift), and archiving AiTrader.
8. Session cost: the final ETA table and the per-model token table, per
   CLAUDE.md. Never estimated.

The last thing before ending: list every open choice in section 6.

END PROMPT
