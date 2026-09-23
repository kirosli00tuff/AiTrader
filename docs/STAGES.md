# Stages

The staged plan for the pre-registered news-drift experiment and what
follows it. Stage names use letters, with a number only for a sub-session
(A, B, C, D.1, D.2). One line per session goes under its stage.
EXPERIMENT.md is the binding contract. This file is the index.

## Stage A: pre-registration (DONE)

- EXPERIMENT.md ACCEPTED and BINDING, with Amendments 1 to 7
  (2026-07-27 to 2026-07-29), all written before the first collection row.
- Primaries read GROSS excess against the equal-weighted band benchmark,
  clustered by trading day, cluster bootstrap 10,000 resamples.
  Amendment 5 split the net economic question into a pre-registered
  secondary family. Amendment 6 added the within-day judgment-permutation
  null and its claim boundary: a gross positive supports "the pipeline
  predicts", never "the model understands".

## Stage B: collection (RUNNING)

- First target session 2026-07-28. news-collect.timer, weekdays 22:30 UTC.
- Exit gate: 60 day-clusters AND at least 1,000 scorable observations AND
  realised power adequate at the realised rho, recomputed, not assumed.
  Per-stratum floor 30 clusters (cleared). Hard stop 120 trading days,
  which ends in an underpowered abstention, not a negative.
- Permanent gaps (unrecoverable by design): 2026-08-28, 2026-09-15.
- Outcome blindness holds for the whole stage. See CLAUDE.md invariants.
- Status 2026-09-22 run: 37 clusters, 17,108 rows, 4,830 judged.
- B.1 "WORKFLOW PORT" (2026-09-23): orchestration files ported from
  PropExperiment (CLAUDE.md session rules, .claude/, docs/ORCHESTRATION.md,
  docs/PROMPT_WRITING.md, docs/prompts/, this file, docs/DECISIONS.md).
  Written by the planning chat through Desktop Commander, no CLI session.

## Stage C: evaluation (NOT STARTED, runs once)

- Starts only after the Stage B exit gate is met and recorded.
- C.1 builds and hash-freezes the evaluation code (outcomes.py,
  scoring.py, the bootstrap, the permutation null, the report writer) and
  tests it on synthetic rows. No real outcome is computed in C.1. The user
  commits the freeze manifest.
- C.2 computes outcomes and runs the pre-registered verdict table exactly
  once, against the frozen hashes. Every number entering a verdict gets an
  independent Fable check. Any change to a frozen file voids the run.
- Deferred to C as reporting questions, not Stage B changes: preferred
  shares and share classes in the universe (ARES.PRB, BAC.PRL, NEE.PRV,
  WFC.PRL, UHAL.B), the strength distribution concentrated at 2 to 4, the
  capability replay on the remaining Anthropic balance.

## Stage D: paper on IBKR Gateway (NOT STARTED, only on a green C)

- D.1 build: IBKR Gateway paper path, a separate fresh paper account (the
  Alpaca paper account carries old July positions and is not evidence),
  borrow data for hard-to-borrow names.
- D.2 validation: paper results must match the Stage C effect within a
  pre-registered tolerance.
- Portfolio gate, pre-registered before D.1 starts: the system must beat
  SPY or QQQ buy-and-hold at the same starting capital, net of fees and
  taxes. Not measurable at Stage C, because the collector has no
  execution path.

## Stage E: live, about $1,000 (NOT STARTED, only on a passed D gate)

- Before funding: record whether the $1,000 is tuition or capital, and
  check capacity and share-price arithmetic at that size.
- Live trading stays behind the existing approval gate.
