STAGE C.2 "GATE AND THE SINGLE VERDICT RUN"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: Stage C.1 (reports/C.1_RETURN.md, commits 2b75aba, 33cadb3 and
c757324) built the evaluation harness news_eval/. It was tested on
synthetic rows only (783 tests, 12 of 12 mutants killed, Fable
recomputation 112 of 112) and frozen in reports/c1_harness_freeze.json,
sha256 77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9.
C.1 also committed the Amendment 8.3 relevance grades.

This session is the experiment's readout. It has four steps:
1. Snapshot news_experiment.db with the frozen runner.
2. Run the Amendment 8.4 and 9.8 gate on that snapshot.
3. If the gate passes, run the verdict exactly once against the frozen
   hashes.
4. Have Fable recompute every verdict number independently and attack
   the reading.

It writes nothing new into the statistics. Every test, bar, seed and
definition is already frozen in EXPERIMENT.md Amendments 5, 6, 8 and 9
and in the manifest. If the gate fails, the session stops after step 2:
collection continues, and this same prompt reruns after 5 more
clusters. Whatever the verdict, the session reports it as computed and
never reruns it.

Lead: Opus 5.5, effort max. Ultracode: off.

Why this lead and effort: this is the single verdict session of a
pre-registered experiment. docs/PROMPT_WRITING.md section 6 puts the C.2
lead at max. The computation itself is mechanical and frozen. The
judgment is in reading it: the verdict row, the claim boundary ("the
pipeline predicts", never "the model understands"), the 8.2
disagreement rule, and ruling on any Fable finding without a second
evaluation. There is one serial chain with two review spawns, so
ultracode is not justified.

Usage: Fable is used twice. VerdictVerifier-FableXHigh recomputes every
verdict number from the snapshot with its own code, before reading the
harness outputs. VerdictReviewer-FableMax is the one hinge review: the
verdict reading against the registered table. The compute is light. C.1
measured about 10 seconds per synthetic database, so expect under a
few minutes on the real snapshot. Expect 2 to 4 hours, mostly
verification.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue. The
stops are exactly the ones named in this prompt: a missing unlock, the
startup readiness check, a refused precondition, a gate FAIL, and a
STOPPED run. Each one ends the session with a written return document.

============================================================
DECISIONS IN FORCE (docs/DECISIONS.md V1 and V2)
============================================================

V1: EXPERIMENT.md Amendment 9, in full.

V2: the C.1 lead's section 7 recommendations, confirmed by the operator
when he launched this prompt.

1. **The unlock file is Kiros's alone.** reports/c2_UNLOCK.json is written
   by hand by Kiros before launch (schema c2_unlock/1, with fields
   schema, stage, approver, utc_time, experiment_sha256 and
   manifest_sha256). This session never creates, edits or rewrites it.
   If it is absent or refused, stop.
2. **Gate cadence.** The gate runs once per snapshot. If it fails, the
   next attempt comes only after 5 more collection days carrying
   judgments, with a new snapshot in a new directory.
3. **No successor draft.** docs/SUCCESSOR_PREREG_DRAFT.md does not
   exist, so 9.12's companion horizons are not computed. If that file
   exists at startup, stop and report it, because it contradicts V2.
4. **D5 is kept.** A powered negative needs no primary at its bootstrap
   bar. A positive blocked by the null is not evidence against the
   mechanism (Amendment 6).
5. **D7, as revised, is kept.** "Fails net in every stratum" needs every
   E-test to be net_negative or below_econ_bar. If any E-test abstains,
   the result is clears_gross_net_abstains, with no Amendment 5 net row.
6. **The day-clustered version governs.** The story-clustered version is
   reported beside it and never decides.
7. **A kill after the run-once marker is STOPPED.** There is no resume
   and no rerun (9.15).
8. **The harness runs only under .venv-eval/bin/python.** The repo
   .venv's numpy fails the elision canary.

============================================================
SCOPE
============================================================

This stage does:
- the startup readiness check, the snapshot, the gate, and if PASS the
  single run, using only the frozen commands below
- the independent Fable recomputation and the Fable max review, with a
  ruling on each finding
- reports/C.2_RETURN.md and the commits named under GUARDRAILS

This stage does NOT:
- edit any file in the manifest (news_eval/, tests/test_news_eval_*.py,
  reports/c1_verdict_mapping.md), EXPERIMENT.md, news_experiment/,
  backtest/, the collector units or COLLECTION_LOG.md. Any change to a
  frozen file voids the run.
- create or touch reports/c2_UNLOCK.json
- run `run_c2 run` more than once, or rerun anything with changed
  settings, seeds, subsets or definitions, whatever the result
- compute any number outside the frozen harness and the Fable
  verification, or report any exploratory analysis as a finding.
  Diagnostics the harness writes are reported as written.
- compute 2, 5 or 10-session horizons
- commit any database file, including the snapshot (*.db is ignored, so
  keep it that way)
- design the successor study, touch PropExperiment, or touch RiskGate,
  the live gate or the adaptive invariant

============================================================
CONTEXT TO READ FIRST
============================================================

1. CLAUDE.md and docs/ORCHESTRATION.md. This prompt does not repeat
   them. On any conflict CLAUDE.md wins and the conflict is logged.
2. reports/C.1_RETURN.md: sections 1, 3 (modules, scenario table), 5,
   6 and 7 in full. reports/c1_verdict_mapping.md in full.
3. EXPERIMENT.md by section (`grep -n '^## \|^### ' EXPERIMENT.md`):
   - AMENDMENT 5: the verdict table, quoted
   - AMENDMENT 6: the claim boundary
   - AMENDMENT 8: 8.1 and 8.2
   - AMENDMENT 9: in full
   - TASK 6: the powered negative
4. The docstrings of news_eval/run_c2.py (lines 1 to 90) and
   news_eval/gate.py. Read them only. They are frozen.

============================================================
GUARDRAILS
============================================================

CLAUDE.md invariants apply in full, except that the outcome columns
unlock in the order this prompt gives, and only through the frozen
harness and the Fable verifier, reading the snapshot. This stage adds:

- Every harness command runs as
  `cd ~/Documents/GitHub/AiTrader && export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 && nice -n 10 .venv-eval/bin/python -m ...`.
  Never use the repo .venv.
- The live database is never opened by this session except through
  `run_c2 snapshot`, plus the CLAUDE.md status check, which is counts
  only. Every outcome read is from the snapshot copy.
- Nothing runs between 22:00 and 22:45 America/Vancouver on a weekday.
  If startup lands inside that window, wait until 22:45 and log the
  wait. Never stop, restart or edit the collector.
- `run_c2 run` refuses below 2,048 MB of available memory. If it
  refuses for memory, wait and retry the preconditions only, which is
  allowed because nothing is written on a refusal. Never kill another
  session.
- Commits, in this order, explicit paths only, never `git add -A`.
  COLLECTION_LOG.md is never staged.
  1. "C.2 snapshot and gate <YYYY-MM-DD>": reports/c2_UNLOCK.json,
     reports/c2/snap_<YYYYMMDD>/snapshot.json and
     reports/c2/gate_log.jsonl
  2. Only after a PASS run: "C.2 run-once marker and results":
     reports/c2_RUN_ONCE.json and every file the run wrote under
     reports/c2/run/, including results_STOPPED.json if it stopped.
     Push right after this commit, in the background
     (`setsid nohup git push origin main > /tmp/aitrader_push.log 2>&1 &`,
     then read the log), so the marker is on GitHub. This also pushes
     the three C.1 commits.
  3. "Stage C.2 <verdict or gate FAIL>": the return document, the review
     and ruling files, PROGRESS.md, RETURN.md, docs/STAGES.md and
     docs/prompts/README.md. Push in the background.
- Start and end checks, quoted verbatim in the return:
  - the CLAUDE.md status command (export XDG_RUNTIME_DIR first)
  - `git status --short` and `git log --oneline -5`
  - `sha256sum EXPERIMENT.md`, expected
    641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386
  - `.venv-eval/bin/python -m news_eval.freeze check`, which must print
    "FROZEN: match" with the manifest sha256 above. If either check
    differs at start, stop.
  - `ls -la reports/c2* reports/c2/` and `free -m`
- Before ending, confirm no worker or background shell is still running.

============================================================
STEP 0: STARTUP AND READINESS (lead)
============================================================

Run the start checks. Then verify, in order. Each failure ends the
session with a short return document.

1. reports/c2_UNLOCK.json exists. This session does not validate it
   beyond existence. The snapshot command validates it.
2. docs/SUCCESSOR_PREREG_DRAFT.md does not exist (V2 item 3).
3. Readiness, from counts only:
   `sqlite3 "file:news_experiment.db?mode=ro" "SELECT COUNT(DISTINCT query_date) FROM news_observation WHERE run_kind='collection' AND state='judged';"`
   - On the first attempt, at least 60 is required.
   - On a rerun (reports/c2/gate_log.jsonl already exists), the count
     must be at least 5 more than the number of distinct judged
     query_dates in the previous snapshot's snapshot.json.
   Collection days are the pre-unlock proxy for clusters, since each
   adds about one scoring_session cluster. If the check fails, stop
   before any snapshot, and write when to come back.

Print the estimate ETA table in chat. Create reports/C.2_STATE.md and
update it after every step.

============================================================
STEP 1: SNAPSHOT (lead)
============================================================

Take the CLAUDE.md status counts, then immediately run
`... -m news_eval.run_c2 snapshot --source news_experiment.db --out-dir reports/c2/snap_<YYYYMMDD>`
using today's date (`date +%Y%m%d`). Record the exit code.

Then compare snapshot.json's collection row total with the status count
taken just before. They must be equal. This is C.1 return section 7
item 10, because snapshot.json attests to itself. If they differ, stop.

============================================================
STEP 2: GATE (lead, then GateVerifier-FableXHigh)
============================================================

Run `... -m news_eval.gate --db reports/c2/snap_<YYYYMMDD>/news_experiment_snapshot.db --log reports/c2/gate_log.jsonl`.

Record the new last line verbatim: C, M, sigma, rho, n0, k_eff,
Required, S*, pass. Make commit 1.

GateVerifier-FableXHigh (worker-xhigh on fable) then recomputes the gate
from the snapshot with its own code under reports/c2/verify_gate/,
following 9.1, 9.7 and 9.8 literally:
- open the snapshot read-only and immutable
  (`file:<path>?mode=ro&immutable=1`)
- read only query_date, scoring_session, state, run_kind,
  exclusion_reason, outcome_state and excess_1session, plus a judgment
  COUNT GROUP BY scoring_session
- never read a row-level judgment, strength or reason

It matches the log line within 1e-9 relative, and exactly for counts.
Findings go to reports/c2_gate_verify.md.

- **If the gate FAILS** (and the verifier agrees): stop here. Write the
  return document with the gate numbers and the date of the next
  attempt, at 5 more collection days carrying judgments (V2 item 2).
  Make commit 3. Judgments stay unread.
- **If the verifier disagrees with the gate:** the frozen gate's line
  stands. Do not run `run_c2 run`. Stop and report the disagreement
  under Decisions for the user.

============================================================
STEP 3: THE SINGLE RUN (lead, only after a verified PASS)
============================================================

Check `free -m` and that the time is outside the collector window. Then
run, once:
`... -m news_eval.run_c2 run --snapshot reports/c2/snap_<YYYYMMDD>/news_experiment_snapshot.db --out-dir reports/c2/run --gate-log reports/c2/gate_log.jsonl --relevance-summary reports/c1_relevance_summary.json`

Exit codes:
- **0:** results.json, run_meta.json and verdict.md were written.
- **2:** refused, with nothing written and no marker. A memory refusal
  may be retried after waiting. Any other refusal (manifest, unlock,
  marker, snapshot, S*, gate, relevance, outputs) is a stop: report it.
- **3:** STOPPED after the marker. That is the registered result. Never
  rerun.

Make commit 2 and push it in the background at once. Then read
verdict.md and results.json.

============================================================
STEP 4: INDEPENDENT RECOMPUTATION (VerdictVerifier-FableXHigh)
============================================================

The brief to the verifier:
- Do not open reports/c2/run/ or any news_eval/ module until your own
  numbers are written to reports/c2/verify/own_results.json.
- Work from EXPERIMENT.md (Tasks 5 to 7 and Amendments 5, 6, 8 and 9,
  by section) and the snapshot, opened read-only and immutable, in your
  own Python under .venv-eval.
- Recompute:
  - S*, the 9.1 excluded days and the analysis-set counts
  - the Amendment 6 diagnostics
  - T for P1 to P4 and E1 to E4, both readings
  - S1 and S2
  - SE and z with your own seed
  - the permutation p for P1 to P4 with your own seed
  - the 8.2 exclusion sets (rules a and b)
  - the sector CR1 SE and the story-group share
  - the verdict row each status implies under
    reports/c1_verdict_mapping.md
- Then compare with results.json:
  - exact quantities (counts, T, the 8.2 sets, S*): within 1e-9
    relative
  - SE: within 3 percent
  - p: within its Monte Carlo error
  - any bar call that flips between the two computations is flagged
    BLOCKING
- Output: reports/c2_verdict_verify.md, with each finding marked
  BLOCKING, SHOULD FIX or NOTE.

============================================================
STEP 5: THE HINGE REVIEW (VerdictReviewer-FableMax)
============================================================

The brief, after Step 4. Read verdict.md, results.json, the mapping,
Amendment 5's table, Amendment 6's claim boundary, Amendment 8.1 and
8.2, and Amendment 9. Check:
- the Amendment 5 row chosen follows from the statuses
- every sentence stays inside the registered wording ("the pipeline
  predicts", never "the model understands")
- a gross positive with net abstentions or failures licenses no trade
- the 8.2 disagreement rule is applied if the readings differ
- nothing exploratory is presented as a finding
- the relevance rates, the closed-end-fund defect and the 8.1 cutoff
  statement are present

Then list, as caveats only, anything that could make the result an
artifact: the benchmark construction, the formation switch on
2026-10-01, the preferreds, the credit-outage days, the clustering.
Caveats never change the verdict.

Output: reports/c2_verdict_review.md.

============================================================
STEP 6: RULINGS (lead)
============================================================

Rule on every Step 4 and Step 5 finding in reports/c2_rulings.md.

The frozen run's output is the registered result in every case.
- A report wording error is fixed in the return document only. The
  frozen verdict.md is quoted, never edited.
- A demonstrated code error in the frozen harness does not trigger a
  second run. The return gives the registered result, the error, and
  the verifier's corrected figure labelled NOT REGISTERED, under
  Decisions for the user. What follows from it is Kiros's decision, and
  likely needs a new amendment and registration.

============================================================
STEP 7: RETURN AND COMMIT (lead)
============================================================

Write reports/C.2_RETURN.md (DELIVERABLE). Add a dated entry at the top
of PROGRESS.md and of RETURN.md. Add one line under Stage C in
docs/STAGES.md, with the Stage B exit gate result recorded there as
well. Update the C.2 row in docs/prompts/README.md. Make commit 3 and
push it in the background.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| 0, 1, 2, 3, 6, 7 | lead | opus | max | serial | the snapshot, the gate and the single run are reserved to the lead, and so is the verdict reading |
| 2 verify | GateVerifier-FableXHigh | fable | xhigh | after the gate line | gate numbers decide whether outcomes unlock |
| 4 | VerdictVerifier-FableXHigh | fable | xhigh | after Step 3 | every verdict number recomputed by a different model |
| 5 | VerdictReviewer-FableMax | fable | max | after Step 4 | the one hinge review of the verdict reading |

If Fable usage runs out, the Fable steps stay pending in STATE and are
never downgraded. The run itself does not wait for Fable. The return
then says the verification is pending, and the verdict is labelled
UNVERIFIED until it is done.

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each task into subtasks with one objective, inputs, output
       path and format, allowed tools, and boundaries.
    2. Route per CLAUDE.md. State model and effort for each subtask before
       spawning.
    3. At most 4 concurrent. Small tasks needing no isolation go inline.
    4. Collect results as files plus short summaries.
    5. Verify every number entering a verdict with an independent fable
       xhigh worker.
    6. Synthesize in the lead against this prompt, and write the synthesis
       to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to
       reports/<stage>_STATE.md after each task.

============================================================
WHAT NOT TO DO
============================================================

- Never run `run_c2 run` twice, never delete or move the marker, and
  never rerun anything with changed settings.
- Never create or edit reports/c2_UNLOCK.json.
- Never edit a frozen file, EXPERIMENT.md, or the collector.
- No outcome read from the live database. No row-level judgment read
  before a verified gate PASS.
- No 2, 5 or 10-session horizons. No exploratory result reported as a
  finding.
- No commit of any .db file. No `git add -A`.
- Never write "the model understands". Never present a gross-only
  positive as a strategy.

============================================================
DELIVERABLE: ONE RETURN DOCUMENT
============================================================

Write reports/C.2_RETURN.md. Fixed sections, in order:

1. Verdict summary, at most 250 words:
   - the Amendment 5 row verbatim, or "gate FAIL" with C, M and
     Required
   - each primary's status beside its 8.2 reading
   - the E-test statuses
   - the claim-boundary sentence
   - whether Fable confirmed the numbers
2. Guardrail evidence:
   - the start and end checks, verbatim
   - every outcome read and by whom
   - the order of events with timestamps from `date`: snapshot, gate,
     marker, run end, verifier start before outputs were opened
   - `git status --short` and `git diff --stat` for each commit
3. Results: the gate line, the diagnostics, then a table of P1 to P4,
   E1 to E4, S1 and S2 with T, SE, z, interval, p where it applies, and
   status, for both readings. Then the sector and story figures, the
   relevance rates, and verdict.md quoted in full.
4. Delegation record: one row per spawn.
5. Verification: each Fable finding, the ruling and the fix.
6. Open choices.
7. Decisions for the user, each with a recommendation first. Cover what
   the verdict permits next under Amendment 5's table (for example,
   maker execution needs its own pre-registration), the successor
   Stage A, the publishing items in the handoff, and the next gate date
   if the gate failed.
8. Session cost: the final ETA table and the per-model token table, per
   CLAUDE.md. Never estimated.

The last thing before ending: list every open choice in section 6 of the
return document.

END PROMPT
