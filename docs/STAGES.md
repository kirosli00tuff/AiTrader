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

- First target session 2026-07-28. news-collect.timer, weekdays 22:30 UTC until 2026-10-02, then 22:00 America/Vancouver (operator request, target sessions unchanged).
- Exit gate: 60 day-clusters AND at least 1,000 scorable observations AND
  realised power adequate at the realised rho, recomputed, not assumed.
  Per-stratum floor 30 clusters (cleared). Hard stop 120 trading days,
  which ends in an underpowered abstention, not a negative.
- Exit gate result 2026-10-28 (C.2 attempt 1, 65 clusters): NOT MET. The
  60 clusters and 1,000 scorable observations are met, but power is not
  (M 5,363 < Required 13,335). Collection continues. Next check on or
  after 2026-11-04, at 65 judged collection days.
- Permanent gaps (unrecoverable by design): 2026-08-28, 2026-09-15.
- Outcome blindness holds for the whole stage. See CLAUDE.md invariants.
- Status 2026-09-22 run: 37 clusters, 17,108 rows, 4,830 judged.
- B.1 "WORKFLOW PORT" (2026-09-23): orchestration files ported from
  PropExperiment (CLAUDE.md session rules, .claude/, docs/ORCHESTRATION.md,
  docs/PROMPT_WRITING.md, docs/prompts/, this file, docs/DECISIONS.md).
  Written by the planning chat through Desktop Commander, no CLI session.
- B.2 "BLIND INTERIM READ" (2026-09-28): pre-outcome fields only, at 41
  clusters. Found preferreds carrying parent or unrelated news, closed-end
  funds past the fund exclusion, and clusters 3.4x the design size. Led
  to EXPERIMENT.md Amendment 8 (operator approved): model cutoff
  attestation, sensitivity exclusion, relevance rate, gate computation.
  reports/B.2_BLIND_INTERIM.md. Planning chat, no CLI session.
- B.3 "C.1 PREPARATION" (2026-10-10): planning chat, no CLI session, at
  50 collection days, 23,614 rows, 7,078 judged. EXPERIMENT.md Amendment 9
  (operator approved, blind): Stage C harness definitions, day cluster =
  scoring_session. Doc sync from PropExperiment (context hygiene, Sonnet
  pin, return section 7). docs/prompts/STAGE_C.1.md written and committed.

## Stage C: evaluation (NOT STARTED, runs once)

- Starts only after the Stage B exit gate is met and recorded.
- C.1 builds the evaluation harness as a new package, news_eval/ (the
  gate step, the bootstrap, the permutation null, the tests, the report
  writer, the C.2 runner), tests it on synthetic rows, and hash-freezes it.
  outcomes.py and scoring.py are NOT evaluation code: scoring.py is the
  Haiku call and parser, outcomes.py the per-row resolver the nightly
  maintenance already runs. Both are hashed as read-only inputs and never
  edited. No real outcome is computed in C.1. Per Amendment 9.15 the C.1
  lead commits the freeze (no push). C.1 also draws and grades the 8.3
  relevance sample (Amendment 9.13).
- C.1 RUN 2026-10-10/11: harness built and frozen (manifest sha256
  77c9bd73…b2a9, 783 tests, Fable reviews closed), relevance sample graded,
  no outcome read; C.2 waits on the user's unlock and the decisions in
  reports/C.1_RETURN.md section 7.
- C.2 first runs the Amendment 8.4 gate step with the frozen harness:
  realised rho and sigma from pooled rows, judgments unread. If power is
  short, collection resumes and C.2 stops there. Otherwise it computes
  the verdict table exactly once, against the frozen hashes, with the
  Amendment 8.2 sensitivity reading beside every primary. Every number entering a verdict gets an
  independent Fable check. Any change to a frozen file voids the run.
- C.2 ATTEMPT 1 2026-10-28: snapshot reports/c2/snap_20261028, 9.8 gate FAIL on power (C 65, M 5,363 < Required 13,335; sigma 442 bp, rho 0.046, k_eff 98), Fable recompute 29 of 29 match; no verdict run, judgments unread; rerun on or after 2026-11-04; reports/C.2_RETURN.md.
- Deferred to C as reporting questions, not Stage B changes: preferred
  shares and share classes in the universe (ARES.PRB, BAC.PRL, NEE.PRV,
  WFC.PRL, UHAL.B), the strength distribution concentrated at 2 to 4, the
  capability replay on the remaining Anthropic balance.

## Planned follow-up: cutoff-replay study (after the Stage C readout, whatever the outcome; stage letter assigned at pre-registration)

Recorded 2026-10-02 at 45 day clusters, before any outcome has been read.

- Idea: score historical headlines from after a model training-data
  cutoff, which the model cannot have seen, as a pseudo-forward test.
  For Claude Haiku 4.5 the window starts after July 2025 (training-data
  cutoff), not February 2025 (reliable-knowledge cutoff).
- Separate study: its own pre-registration, its own database or
  run_kind, its own verdict. Run and read only after Stage C reports,
  so nothing in it can steer an amendment to the live experiment.
  REVISED 2026-10-28 (V4): the replay may run and be read once the live
  experiment is locked, meaning EXPERIMENT.md Amendment 10.3 is in force
  and the C.3 re-freeze is committed. After that point, nothing in the
  live experiment is amendable, so the original rule's intent holds.
  Primary replay model: Claude Haiku 4.5, the same model as the live
  experiment. A possible second rung is Sonnet 4.6. Cutoffs are to be
  confirmed from Anthropic's model pages in the replay's Stage A.
- Leak controls to pre-register: archive timestamps vs first-seen time
  (backfill and re-stamping), a point-in-time universe per quarter
  including delisted names, and a coverage check of historical Finnhub
  news against the live-collected overlap months.
- Optional model ladder: each model scored only on events after its
  own training cutoff, testing whether stronger models predict better.
  Later cutoffs mean shorter windows and less power.

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
