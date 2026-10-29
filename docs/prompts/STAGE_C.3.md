STAGE C.3 "HARD-STOP READOUT BUILD AND RE-FREEZE (NO OUTCOMES)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: the first C.2 gate run (reports/C.2_RETURN.md) failed. M was
5,363 against a Required of 13,335, because sigma came in at 442 bp
against the 180 bp assumed. The gate is projected to pass near 162
clusters, but the 120-session hard stop falls near 2027-01-15. EXPERIMENT.md
Amendment 10 (operator approved 2026-10-28, V4) registers what happens
then: if the gate has not passed by the hard stop, the verdict runs once
on the hard-stop snapshot, unchanged, and the power shortfall is reported
beside it. The amendment then locks EXPERIMENT.md.

This stage implements Amendment 10.1 and 10.2 in news_eval/ as the
smallest change that does it, tests it on synthetic rows only, has Fable
review the diff, and re-freezes the harness under a new manifest.

- **Outcome reads:** none. No snapshot is taken, no gate or run touches
  real data, and no judgment is read.
- **Spend:** none. No paid API call.
- **Hypothesis count:** unchanged. Amendment 10 adds no test.

The next steps belong to the planner and Kiros: a new unlock written by
Kiros, then gate reruns under a continuation prompt C.2b.

Decisions in force: docs/DECISIONS.md V1 to V4.

Binding, in priority order:
1. EXPERIMENT.md. Its sha256, checked at start, must be
   964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe.
   Amendment 10 is the build specification, read with 9.7, 9.8 and 9.15.
2. The C.1 harness manifest reports/c1_harness_freeze.json, sha256
   77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9.
   This is the base being changed. `freeze check` must print FROZEN: match
   against it at start.
3. This prompt.

Read first:
- CLAUDE.md and docs/ORCHESTRATION.md
- docs/PROMPT_WRITING.md section 8
- EXPERIMENT.md by search only: `grep -n '^## \|^### ' EXPERIMENT.md`,
  then read Amendment 10 in full, and 9.7, 9.8, 9.11, 9.12 and 9.15
- reports/C.2_RETURN.md sections 1, 3 and 7
- reports/C.1_RETURN.md section 3 (the module table)
- news_eval/run_c2.py lines 1 to 120 and the precondition function
- news_eval/gate.py, news_eval/cutoff.py, news_eval/freeze.py and
  news_eval/report.py, by search for the functions you change
- tests/test_news_eval_*.py, by search

Lead: Opus 5.5, effort max. Ultracode: off.
- Reviewers: Fable xhigh, with the model confirmed from each reviewer's
  transcript. Opus in a fresh context only if Fable is unavailable, and
  the return says so.
- Coding workers: Opus xhigh.
- At most 4 workers at once, and at most 1 heavy compute job (the full
  test suite).

Why this lead and effort: this edits frozen experiment code between two
freezes. The risks are a change wider than Amendment 10, a hard-stop path
that lets the verdict run before the hard stop or twice, a restriction
applied to one part of the computation but not another, and a manifest
that misses a changed file. Each of those would look right and void the
readout, which justifies max.

Usage and time:
- Launch at the operator's go-ahead, outside 22:00 to 22:45 America/
  Vancouver on weekdays. No fixed end. Expect 2 to 4 hours.
- Checkpoint to reports/C.3_STATE.md after every step, and resume from it
  after any usage limit or reboot.
- Context wipe: if the lead's context passes about 300k tokens and no
  worker or job is running, write a RESUME HERE block and
  "READY FOR WIPE <time>" to STATE, and stop.
- Never sacrifice a check to save usage.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue.

============================================================
PART 0: START GATES (FIXED HERE)
============================================================

0.1 Start checks, quoted verbatim in the return:
- the CLAUDE.md status command (export XDG_RUNTIME_DIR first)
- `git status --short` and `git log --oneline -3`
- `sha256sum EXPERIMENT.md`, which must equal the Binding value
- `PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc .venv-eval/bin/python -m news_eval.freeze check`,
  which must print FROZEN: match on 77c9bd73...b2a9
- `ls -la reports/c2* reports/c2/`
- `free -m`

If either hash check fails, stop.

0.2 Record the hard stop. Compute session 120 from
analysis_bars.db trading_calendar, read-only, counting 2026-07-28 as
session 1:
`sqlite3 "file:analysis_bars.db?mode=ro" "SELECT date FROM trading_calendar WHERE date>='2026-07-28' ORDER BY date LIMIT 1 OFFSET 119;"`
The planning chat got 2027-01-15. If you get a different date, the
computed date governs (10.1) and the difference goes under Decisions for
the user.

0.3 Write reports/C.3_STATE.md and the estimate ETA table.

============================================================
PART A: THE CHANGE (FIXED HERE)
============================================================

Objective: implement 10.1 and 10.2 and nothing else. Owner:
HarnessCoder-OpusXHigh (worker-xhigh on opus), with the lead reviewing
every hunk.

A1. constants.py: `HARD_STOP_SESSION` = the 0.2 date, citing 10.1. Also
`HARD_STOP_LABEL = "registered power rule NOT met"`, quoted from 10.2.

A2. The restriction (10.1 "Its analysis set"). A single function decides
which scoring sessions enter. In both modes, the analysis set and the gate
rows G are restricted to `scoring_session <= min(S*, HARD_STOP_SESSION)`.
Before the hard stop, S* is earlier than HARD_STOP_SESSION, so normal-mode
results on any pre-hard-stop snapshot are byte-identical to C.1's. The
existing known-answer tests prove that, and none of them may change. The
gate and the run must call the same function.

A3. The hard-stop mode. `run_c2 run` gains `--hard-stop`. In this mode
precondition 6 (gate) accepts a gate log entry for this snapshot's sha256
with status ok, with pass either true or false, and with the snapshot's S*
on or after HARD_STOP_SESSION. Every other precondition is unchanged.
- The mode refuses (exit 2, nothing written) when S* is earlier than
  HARD_STOP_SESSION, or when the entry is degenerate or missing.
- Without `--hard-stop`, precondition 6 is exactly as frozen in C.1.
- The marker and run_meta record the mode.

A4. The report (10.2). In hard-stop mode, report.py places the hard-stop
gate line (C, M, Required, sigma, rho) beside the verdict, with the
HARD_STOP_LABEL. A clear gets the label after its registered row.
Verdict selection does not change.

A5. The manifest pointer. freeze.MANIFEST_REL becomes
"reports/c3_harness_freeze.json", and the freeze schema becomes
"c3_harness_freeze/1". reports/c1_harness_freeze.json stays committed and
byte-identical as the record. The gate and the runner verify against the
new manifest.

Gate: `git diff --stat` touches only news_eval/ and
tests/test_news_eval_*.py. Every hunk is explained in
reports/c3_change_record.md, mapped to 10.1, 10.2 or A5.

============================================================
PART B: TESTS ON SYNTHETIC ROWS (FIXED HERE)
============================================================

Owner: TestCoder-OpusXHigh (worker-xhigh on opus), after Part A.

New tests in tests/test_news_eval_hardstop.py. Use synthetic databases
and temporary paths only. Never use reports/c2*.

B1. Normal mode is unchanged. Every C.1 known-answer test passes, with
783 or more passing in total, and the scenario outputs are byte-identical
to C.1 for pre-hard-stop snapshots.

B2. The hard-stop happy path. A synthetic snapshot has S* after
HARD_STOP_SESSION and a gate FAIL entry. `--hard-stop` runs, the label is
present, the marker records the mode, and rows scoring after the hard
stop are excluded from both the gate rows and the analysis set.

B3. Hard-stop refusals:
- S* earlier than the hard stop
- a missing gate entry
- a degenerate entry
- a marker already present
Each refuses with nothing written.

B4. The restriction is shared. Gate rows and analysis rows use the same
cutoff on the same snapshot.

B5. Mutants. Each must be killed:
- apply the restriction to the analysis set only
- allow `--hard-stop` with S* earlier than the hard stop
- drop the label
- let `--hard-stop` skip the marker-absent precondition

B6. The full suite passes:
`PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc .venv-eval/bin/python -m pytest -q tests/test_news_eval_*.py`.
Stop the job if free memory falls below 2 GB.

============================================================
PART C: REVIEW (FIXED HERE)
============================================================

Two reviewers run in parallel after Part B. Each has its model confirmed
from its transcript.

C1. DiffReviewer-FableXHigh (worker-xhigh on fable). The brief:
- read Amendment 10 and `git diff` against the C.1 base commit
  (c757324)
- check that every hunk maps to 10.1, 10.2 or A5, and that nothing else
  changed
- check that the restriction is one function, used by both the gate and
  the run
- check that normal mode is behaviorally identical
- check that the new manifest covers every changed file

Output: reports/c3_review_diff.md, with each finding marked BLOCKING,
SHOULD FIX or NOTE.

C2. RunOnceAuditor-FableXHigh (worker-xhigh on fable). The brief: hunt
for any path by which:
- the hard-stop mode runs before the hard stop
- a verdict runs twice
- a gate FAIL is accepted outside hard-stop mode
- the mode flag can be confused or forged
- the restriction is bypassed
- any outcome column is read before the marker

Demonstrate on synthetic stand-ins only. Output:
reports/c3_review_runonce.md.

The lead rules on every finding in reports/c3_rulings.md. BLOCKING and
SHOULD FIX findings are fixed and the suite is rerun before Part D.

============================================================
PART D: RE-FREEZE (FIXED HERE)
============================================================

D1. `.venv-eval/bin/python -m news_eval.freeze write` writes
reports/c3_harness_freeze.json, then `freeze check` must print
FROZEN: match on it. Record its sha256 in STATE.

D2. Confirm reports/c1_harness_freeze.json is byte-identical to commit
c757324.

D3. The suite passes once more from a fresh PYTHONPYCACHEPREFIX, and no
.pyc file exists under news_eval/.

============================================================
SCOPE
============================================================

This stage does NOT:
- read any outcome, judgment, strength or reason value, or any
  scoring_session value, from news_experiment.db. The only database reads
  are the CLAUDE.md status counts and the 0.2 trading_calendar query.
- take a snapshot, run the gate or `run_c2` on real data, or create,
  edit or delete reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json or
  anything under reports/c2/
- edit EXPERIMENT.md (locked by 10.3), news_experiment/, backtest/, the
  collector units, COLLECTION_LOG.md, reports/c1_harness_freeze.json or
  any C.1 or C.2 report
- change any bar, test, seed, null, floor, verdict row or mapping
  definition, or anything outside 10.1, 10.2 and A5
- write the C.2b rerun prompt or a new unlock. Both belong to the
  planner and Kiros.
- install into .venv, call a paid API, print a key, or push

============================================================
GUARDRAILS
============================================================

- Start and end checks quoted verbatim, as in 0.1. At the end, the freeze
  check runs against the new manifest and the old manifest is
  byte-compared.
- Every harness command:
  `export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc && nice -n 10 .venv-eval/bin/python ...`.
  Never use the repo .venv.
- At most 1 heavy compute job, the test suite. Stop it if free memory
  falls below 2 GB.
- Nothing runs between 22:00 and 22:45 America/Vancouver on weekdays.
  Never touch news-collect.timer or news-collect.service.
- Commits touch only this stage's files, staged by explicit path. There
  is one named final commit and no push. COLLECTION_LOG.md is never
  staged.
- Before ending, confirm no worker or shell is still running.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| Part 0, A review, rulings, D, return | lead | opus | max | serial | edits frozen experiment code, so the lead keeps decisions and the freeze |
| A1 to A5 | HarnessCoder-OpusXHigh | opus | xhigh | serial | experiment code, silent-failure risk |
| B1 to B6 | TestCoder-OpusXHigh | opus | xhigh | after A | known answers and mutants |
| C1 | DiffReviewer-FableXHigh | fable | xhigh | parallel with C2 | independent check that the diff is only Amendment 10 |
| C2 | RunOnceAuditor-FableXHigh | fable | xhigh | parallel with C1 | the hinge: no early, double or ungated run |

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each part into subtasks with one objective, inputs, output
       path and format, allowed tools, and boundaries.
    2. Route per CLAUDE.md. State model and effort for each subtask before
       spawning; confirm each reviewer's model from its transcript.
    3. Run independent workers at once, within the worker cap.
    4. Collect results as files plus short summaries.
    5. Verify with independent reviewers as listed.
    6. Synthesize in the lead against this prompt, and write the synthesis
       to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to
       reports/C.3_STATE.md after each step.

============================================================
DELIVERABLE
============================================================

Write reports/C.3_RETURN.md. Also write one dated entry at the top of
PROGRESS.md and of RETURN.md, one docs/STAGES.md line under Stage C, and
the C.3 row's Run column in docs/prompts/README.md. Then make one final
commit, "Stage C.3 hard-stop readout build and re-freeze". No push.

The return has these fixed sections:
1. Summary, at most 250 words. It includes the hard-stop date, the new
   manifest sha256, test and mutant counts, and the review outcomes.
2. Guardrail evidence: start and end checks verbatim, and the order of
   events.
3. Results: the change record by hunk, the tests and what each proves,
   the mutant kill table, and both manifests with their sha256.
4. Delegation record, with each reviewer's model confirmed from its
   transcript.
5. Verification: each finding, the ruling and the fix.
6. Open choices.
7. Decisions for the user, each with a recommendation. It must include:
   - the exact new unlock command Kiros runs (EXPERIMENT.md sha256 and
     the new manifest sha256)
   - what the C.2b rerun prompt must change: the expected hashes, the
     `--hard-stop` use at the hard-stop snapshot, and per-attempt return
     file names
   - the gate-rerun cadence
8. Session cost: the final ETA table and per-model token counts from the
   transcripts, never estimated.

The last thing before ending: list every open choice in section 6.

END PROMPT
