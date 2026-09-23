# How the planning chat writes stage prompts

Written 2026-09-23. This is the planning chat's own rulebook. The planning
chat (Claude on claude.ai, working with Kiros) writes every stage prompt,
and a Claude Code session in this repo executes it. CLAUDE.md binds the
CLI session. This file binds the author of the prompt. When the two
disagree, CLAUDE.md wins and the prompt is fixed.

The goal: a prompt the lead runs unattended from first read to finished
return document, with no startup questions, no guessing at scope, and a
single file at the end the chat reviews in one read.

## 1. Before writing

1. Read the current state, never recall it:
   - `tail -30 COLLECTION_LOG.md`, the cluster and row counts, the timer.
   - docs/STAGES.md, docs/DECISIONS.md, the newest PROGRESS.md entry.
   - The last return document in reports/.
   - Every file the prompt will name, at the section level. A prompt
     never cites a section, column, function or path the author has not
     opened in this conversation.
2. Check what is running: `ps -eo pid,etime,args | grep claude`. A
   PropExperiment session in flight changes the compute and usage budget.
3. Decide the one question the stage answers and where it stops. If the
   stage has a natural freeze point (code built and hashed before data is
   touched), stop the stage there and put the run in the next stage.
4. List the decisions the lead must not make (amendments, verdict
   thresholds, anything reserved) and the ones it may make and log.

## 2. Naming and files

- Stages use letters, with a number only for a sub-session: A, B, C, C.1,
  D.1, D.2. Never a bare number.
- Header line: `STAGE C.1 "EVALUATION HARNESS BUILD AND FREEZE"`. Title in
  capitals, short, names the output, and says what it does not do when
  that matters, for example "(NO OUTCOMES)".
- File: docs/prompts/STAGE_C.1.md. Add the index row in
  docs/prompts/README.md. Commit both before sending.
- Deliver the identical text in chat as one copy-paste block, never as a
  download. When Kiros is on mobile and several prompts are ready, deliver
  them as a numbered queue in one message, each block complete.

## 3. The header block

    STAGE X.Y "SHORT TITLE"

    BEGIN PROMPT - SUMMARY OF PROMPT

    Summary: <one paragraph>

    Lead: Opus 5.5, effort <xhigh|max>. Ultracode: <on|off>.

    Why this lead and effort: <one paragraph>

    Usage: <one paragraph>

- Summary: what the previous stage left behind (by file path), what this
  session builds or decides, why now, and the exact point where it stops.
  Say what the next session does, so the lead does not drift into it.
- Lead line: always stated. The model is Opus 5.5 for the lead. Fable
  never leads. Never Sonnet for a lead.
- Effort choice for the lead:
  - xhigh: implementation, harness work, maintenance, audits with no new
    judgment. The default.
  - max: pre-registration drafting or amendment, statistical design,
    synthesis of mixed results, the Stage C verdict session.
  - ultracode on: only when the stage has four or more genuinely
    independent workstreams. State why. Ultracode means an interactive
    launch, not headless.
- Why paragraph: tie the choice to CLAUDE.md's routing table and to the
  kind of work (judgment or implementation). One paragraph, no padding.
- Usage paragraph: list each Fable spawn and its purpose. Normally two: one
  fable xhigh number verification, one fable max hinge review. Name any
  expected heavy compute and when it runs relative to the collector
  window.

## 4. The body, section by section

Separate sections with a rule of `=` characters and a capitalized title,
as in PropExperiment's STAGE_D.1f_build.md. Use this order.

### SCOPE

Two lists: "This stage does" and "This stage does NOT". The NOT list is
the more important one. Name the next stage's work in it explicitly
("computing any real outcome belongs to C.2").

### CONTEXT TO READ FIRST

Numbered. Always first: "CLAUDE.md and docs/ORCHESTRATION.md: roles,
routing, worker files, concurrency, artifacts, checkpoints, the ETA table
and the Session cost section. This prompt does not repeat them; on any
conflict CLAUDE.md wins and the conflict is logged." Then each file with
the sections that matter, and whether it is read-only or FROZEN.

### GUARDRAILS

Start with "CLAUDE.md invariants apply in full. This stage adds:" and list
only the stage-specific ones: files hashed and frozen, spend caps with a
quote-first rule, columns or tables unlocked (Stage C only), the exact
start and end checks with the commands to run.

### TASK 1..n

Each task carries five fields:

- Owner: `lead`, or the worker file plus model, for example
  `worker-xhigh on opus`.
- Inputs: file paths, tables, columns. Never "the data".
- Output artifact: exact path and format (reports/c1_bootstrap_tests.md,
  a JSON schema, a test file).
- Done-when: a checkable condition, ideally a command and its expected
  result (`pytest tests/test_scoring.py -q` passes with N tests, a sha256
  written, a row count matching the source).
- Failure path: what the task does when an input is missing or a check
  fails. Absence is loud and distinct: a missing input produces a named
  refusal in the artifact, never a default, a zero, or a plausible fill.

Tasks name the specific failure modes the author already knows about, for
example "the cluster column is `query_date`, not `session_date`" or
"`excluded_pre_call` rows are not scorable and are not zeros".

### DELEGATION PLAN

A table, then the standard block from docs/ORCHESTRATION.md pasted
verbatim.

| Task | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|

Rules for filling the table:

- Route by silent-failure risk, not by task label. Anything whose error
  would look right goes up a tier.
- Haiku only for pure extraction with row counts and source references.
- Keep the lead's reserved work in the lead: decomposition,
  pre-registration content, verdicts, synthesis.
- Parallel only where items are independent. Cap 4. Estimate spawns: each
  costs 25k to 35k tokens of setup, so a task under about 15 minutes of
  work goes inline.
- Agent names follow `<Role>-<Model><Effort>`, for example
  `BootstrapCoder-OpusXHigh`, `NumberVerifier-FableXHigh`,
  `AdvAuditor-FableMax`, `LogReader-HaikuMed`.

### VERIFICATION

- Every number entering a verdict or a decision (cluster counts, n, rho,
  realised power, bootstrap intervals, permutation p-values, spend) gets
  an independent recomputation by a fable xhigh worker that did not
  produce it, from raw inputs.
- One fable max adversarial review on the single thing the stage hinges
  on, with a brief that says what to hunt: leakage, look-ahead, outcome
  exposure, fabrication from absent input, files outside the freeze.
- The lead adjudicates every finding in writing and applies fixes before
  the deliverable.
- If Fable usage runs out, those checks stay pending in the STATE file.
  They are never downgraded to opus.

### WHAT NOT TO DO

Short, blunt, one line each. Repeat the two or three guardrails a lead
under time pressure is most likely to break. Always include "No commits"
unless the stage commits, and "No edit to EXPERIMENT.md".

### DELIVERABLE: one return document

Every session ends by writing reports/<STAGE>_RETURN.md (for example
reports/C.1_RETURN.md). It is self-contained: the chat reads this one
file and nothing else to review the session. Fixed sections, in order:

1. Verdict summary, at most 200 words: what was done, what was not, the
   headline numbers, and whether the next stage is unblocked.
2. Guardrail evidence: the start and end status check output verbatim,
   the outcome-blindness attestation (which columns and scripts were
   touched, if any), `git status --short` and `git diff --stat`, any
   hashes the stage froze.
3. Results per task: what was built or found, artifact paths, test
   counts and what each test proves, failures and non-survivors.
4. Delegation record: one row per spawn with agent name, file, model,
   effort, objective, status, and deviations from the plan.
5. Verification: each Fable finding, the lead's ruling, the fix.
6. Open choices: every decision the lead made on its own, with the
   reason, so Kiros overturns any of them before the next stage.
7. Next session must first: commits the user owes, frozen files, blockers.
8. Session cost: the final ETA table (one row per task and per spawn,
   actual start and end, time taken, tokens from transcripts, status) and
   the per-model token table, per CLAUDE.md. Never estimated.

Also: one short dated entry at the top of PROGRESS.md and RETURN.md that
points to the return document, and one line in docs/STAGES.md.

### OPEN CHOICES and END PROMPT

The last instruction before END PROMPT tells the lead to list its own
open choices in the return document. Then the literal line `END PROMPT`.

## 5. Writing rules for the prompt text

- Plain, specific, active voice. No em dashes, no semicolons, no filler.
- Every claim carries its source: a path, a section, a command, or a
  measured figure with its date. "Measured" means the author saw the
  number in this conversation.
- Numbers in the prompt are the ones the lead checks against, so copy
  them exactly (37 clusters, 17,108 rows as of the 2026-09-22 run).
- Say what a thing is not, when a plausible misreading exists.
- Autonomous by default: "Do not stop to ask. Decide, log the choice in
  OPEN CHOICES, and continue." The only stops are a decision that cannot
  be undone and could reasonably go either way, or a guardrail conflict.
- No instruction lives only in chat. If the chat adds something after
  sending, the prompt file gets a dated addendum and a new commit.
- Length follows the work. A maintenance stage is short. A Stage C prompt
  is long. Never pad a section to fill the template, and never drop the
  SCOPE NOT list, GUARDRAILS, DELEGATION PLAN or DELIVERABLE.

## 6. Stage-specific notes

### Stage B sessions (collection running)

- Maintenance, audits and docs only. The collector, its timer, its
  database writes and COLLECTION_LOG.md are out of scope for every task.
- Allowed reads: state, judgment, strength, error_class, stratum,
  query_date, symbol, counts. Nothing from outcomes.py or scoring.py, and
  no return, excess, benchmark or cost column.
- Schedule heavy work outside 15:30 to 16:30 PT on weekdays.
- Small doc or config commits go through the planning chat via Desktop
  Commander, with no CLI session, when Kiros asks.

### Stage C (evaluation, once)

- Split it: C.1 builds, tests on synthetic rows, and hash-freezes the
  evaluation code with a manifest the user commits. C.2 computes outcomes
  and runs the verdict table once against those hashes.
- The C.2 prompt quotes the pre-registered verdict table from EXPERIMENT.md
  by section and forbids any threshold not in it.
- Lead at max effort for C.2. Fable xhigh recomputes every verdict number.
  Fable max reviews the one verdict before it is written.
- A result that surprises the lead is still reported as computed. No
  rerun with changed settings.

### Stage D (IBKR paper) and E (live)

- D starts with a pre-registration addendum for the portfolio gate (SPY or
  QQQ buy-and-hold, same capital, net of fees and taxes) and the D.2
  paper-matches-C tolerance, written before any paper order.
- Every D and E prompt repeats: RiskGate logic, the live-trading gate and
  the adaptive limit-weakening invariant are never touched, live stays
  behind the approval gate, services bind loopback, keys are never logged.

## 7. Checklist before sending

- [ ] Header, BEGIN PROMPT - SUMMARY OF PROMPT, END PROMPT all present.
- [ ] Lead model and effort stated, with the why and usage paragraphs.
- [ ] SCOPE has a NOT list naming the next stage's work.
- [ ] Every path, section and column named was opened by the author.
- [ ] Each task has owner, inputs, output, done-when, failure path.
- [ ] Delegation table filled, standard block pasted, spawns named.
- [ ] Fable spawns limited to verification and one hinge review.
- [ ] Deliverable is reports/<STAGE>_RETURN.md with the eight sections.
- [ ] No em dashes, no semicolons.
- [ ] Saved to docs/prompts/, index row added, committed, then sent.
