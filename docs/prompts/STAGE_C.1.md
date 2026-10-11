STAGE C.1 "EVALUATION HARNESS BUILD AND FREEZE (NO OUTCOMES)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: Stage B collection is running: 50 collection days, 23,614
collection rows and 7,078 judged through session 2026-10-08 (verified by
the planning chat 2026-10-10). The 60-cluster gate is projected near
session 2026-10-23. On 2026-10-10 the operator approved EXPERIMENT.md
Amendment 9, written blind, which fixes every implementation definition
the evaluation needs, starting with this one: the day cluster is
`scoring_session`, not `query_date`. This session builds the Stage C
evaluation harness as a NEW package, news_eval/. It tests the harness on
synthetic rows only, with known answers and mutation tests, and has
Fable verify the numbers and attack the design. It then writes a sha256
freeze manifest and commits the freeze. After the freeze it draws the
Amendment 8.3 relevance sample on six pre-outcome columns, has two
independent workers grade it, adjudicates, and commits the grades. It
reads no outcome column and computes no statistic on real rows. It does
not run the gate on real data. Stage C.2 is a separate prompt, written
after this return is reviewed: it snapshots the database, runs the gate,
and computes the verdict once against these hashes.

Lead: Opus 5.5, effort xhigh. Ultracode: off.

Why this lead and effort: this stage implements a specification that is
now complete. Amendments 5, 6, 8 and 9 fix every test, bar, estimator,
seed and refusal, so the work is careful implementation, not new
statistical design. CLAUDE.md routes code touching the experiment at opus
xhigh. The parts where a subtle error would look right are the
statistics core and the verdict mapping. Both get an opus xhigh author, a
Fable xhigh recomputation from raw synthetic rows, and a Fable max
adversarial review. There are three parallel streams at most (fixtures,
statistics, harness), which does not justify ultracode.

Usage: Fable is used three times. KnownAnswerVerifier-FableXHigh
recomputes the known answers independently. LeakageAuditor-FableMax is
the one hinge review, on blindness, look-ahead and freeze coverage.
RelevanceGrader-FableXHigh is the second, independent grader of 200
short headlines, which Amendment 9.13 requires. Everything else runs on
opus or sonnet. Compute is light: 10,000 bootstrap draws and 10,000
permutations on about 5,000 synthetic rows take seconds to minutes per
scenario with numpy. The laptop is shared: PropExperiment's planning
chat committed a Stage E.20 prompt on 2026-10-10, and that session may
start while this one runs. Expect 4 to 7 hours. The planning chat
launched this session unattended at Kiros's request. Kiros is not
watching.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue. There
are only two stops. One is a guardrail conflict. The other is a
contradiction between this prompt and EXPERIMENT.md. EXPERIMENT.md wins
every such contradiction. Implement what EXPERIMENT.md says, and record
the contradiction in the return document. If the contradiction leaves a
verdict-bearing definition genuinely undecidable, stop, write the STATE
file, and write the return document explaining why.

============================================================
SCOPE
============================================================

This stage does:
- build news_eval/: constants, a guarded loader, synthetic fixtures, the
  statistics core, the analysis-set builder, the diagnostics, the tests
  (P1 to P4, E1 to E4, S1, S2), the gate step, the verdict mapping, the
  report writer, the C.2 runner with its preconditions and run-once
  marker, the 8.3 relevance draw, and the freeze script
- build known-answer tests on synthetic scenarios, refusal tests, an AST
  blindness test, a determinism test and mutation tests
- run Fable verification and the Fable max review, rule on every
  finding, and apply the fixes
- write reports/c1_harness_freeze.json and commit "C.1 freeze"
- draw and double-grade the 200-row relevance sample, adjudicate, and
  commit "C.1 relevance grades"
- write reports/C.1_RETURN.md and commit "Stage C.1 harness built and
  frozen"

This stage does NOT:
- read any outcome column (`ret_*`, `bench_*`, `excess_1session`,
  `net_bp`, `cost_bp_round_trip`, `outcome_state`, `anchor_*`) from the
  real database, or any `scoring_session`, `judgment`, `strength` or
  `reason` value from it. The real database is read only in the three
  ways GUARDRAILS lists.
- run the gate, the bootstrap, the null or any test on real rows.
  Snapshotting the database and running the gate and the verdict
  belong to C.2.
- create reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json, or anything
  under reports/c2/. Those paths belong to C.2. Tests use temporary paths.
- edit EXPERIMENT.md, any file under news_experiment/, backtest/, the
  systemd units, COLLECTION_LOG.md, news_experiment.db, analysis_bars.db,
  or scripts/blind_interim_20260928.py
- install anything into .venv (the collector runs from it), call any paid
  API, read the experiment key, or push
- touch RiskGate logic, the live-trading gate, the adaptive
  limit-weakening invariant, or any PropExperiment file (read-only
  pattern reading is allowed)

============================================================
CONTEXT TO READ FIRST
============================================================

1. CLAUDE.md and docs/ORCHESTRATION.md: roles, routing, worker files,
   concurrency, artifacts, checkpoints, context hygiene, the ETA table
   and the Session cost section. This prompt does not repeat them. On
   any conflict CLAUDE.md wins and the conflict is logged.
2. EXPERIMENT.md, by section (run `grep -n '^## \|^### ' EXPERIMENT.md`
   and read line ranges, never the whole file). BINDING, never edited:
   - AMENDMENT 9 in full. This is the build specification. Every function
     in news_eval/ cites the 9.x paragraph it implements.
   - AMENDMENT 5: the primary family on gross, the E-tests, and the
     verdict table (quote its rows verbatim).
   - AMENDMENT 6: the permutation null, the skew diagnostic, the claim
     boundary.
   - AMENDMENT 8: 8.2 (the sensitivity exclusion rule), 8.3, 8.4.
   - TASK 5: the scored quantity, the clustering unit, the bar, the
     strength secondaries S1 and S2, the required sample.
   - TASK 6: the powered negative and the 4.96 bp comparison.
   - TASK 7: the five states and the 20 percent source_failed day rule.
   - TASK 8: the columns.
3. reports/B.2_BLIND_INTERIM.md and scripts/blind_interim_20260928.py:
   the refusal pattern for outcome columns, to reuse in the loader.
4. Read-only inputs, by section: news_experiment/outcomes.py (how
   excess_1session, net_bp and the band benchmark are produced),
   news_experiment/spec.py (state, judgment and exclusion constants),
   news_experiment/store.py (schema), news_experiment/horizon.py (how
   scoring_session is assigned), news_experiment/collect.py lines 560 to
   710 (resolve_pending, backfill_horizons), backtest/fees.py.
   outcomes.py and scoring.py are collector modules, not evaluation code.
   They are hashed as inputs and never edited.
5. PropExperiment patterns, read-only, at ~/Documents/GitHub/PropExperiment:
   - c1_replication/evaluate.py, top docstring: preconditions that refuse
     with nothing written, and a run-once marker written before any data
     is read
   - reports/stage_e18_freeze.json: the manifest schema
   - tests/test_harness_freeze.py
   - docs/prompts/STAGE_E.18.md
   - reports/E.18_RETURN.md, section 7 item 3: the freeze-writing
     lessons. Define every mean explicitly. Dry-run every guard before
     freezing.

============================================================
GUARDRAILS
============================================================

CLAUDE.md invariants apply in full. This stage adds:

- The real database is opened only read-only (`file:<path>?mode=ro`), and
  only for these three reads:
  1. the CLAUDE.md status check, at start and at end
  2. `PRAGMA table_info(news_observation)`, to copy the schema into the
     synthetic fixtures
  3. Task 9's relevance draw of exactly `id, symbol, query_date,
     headline, sector, stratum`, filtered on `run_kind = 'collection'`,
     `state = 'judged'` and `query_date <= '2026-10-09'`, run through the
     frozen guarded loader
  Any other read of the real database is a guardrail breach. Record it in
  the STATE file and the return document, and do not use its output.
- No outcome column, and no `scoring_session`, `judgment`, `strength` or
  `reason` value, from the real database. Ever.
- `.venv` is the collector's environment and gets no new packages.
  Present: Python 3.14, numpy 1.26.4, pandas 2.2.3, pytest 9.1.1. scipy is
  ABSENT. Implement Spearman with average ranks, normal quantiles and the
  rest with numpy. If something truly needs a new library, create a
  separate .venv-eval, record why, and hash its lock in the manifest.
- Every harness and test command runs with
  `export PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc`, so no bytecode
  lands inside hashed folders.
- New files only under: news_eval/, tests/test_news_eval_*.py,
  reports/c1_* and reports/C.1_*. Synthetic databases and scratch go
  under reports/c1_scratch/ and are never committed. Doc edits are
  limited to the lines named in DELIVERABLE.
- No paid API call. Web lookups are allowed only for Task 9's issuer
  names, and only if no local source exists.
- Collector window: weekdays 22:00 to 22:45 America/Vancouver. This
  session launches on Saturday night. If it is still running on Monday
  at 22:00, hold heavy work until 22:45, and never stop or restart
  news-collect.timer or news-collect.service.
- Commits: exactly three, in this order, staging explicit paths only
  (never `git add -A` or `git add .`), and never pushing:
  "C.1 freeze" (Task 8), "C.1 relevance grades" (Task 9), and
  "Stage C.1 harness built and frozen" (Task 11). COLLECTION_LOG.md
  shows as modified because the wrapper appends to it. Never stage it.
- Start and end checks, quoted verbatim in the return document:
  - the CLAUDE.md status command. Run systemctl after
    `export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.
    Expected at start: 50 | 23614 | 7078. The next collector run is
    Monday 2026-10-12 at 22:00 Pacific.
  - `git status --short` and `git log --oneline -3`
  - `sha256sum EXPERIMENT.md`, expected
    641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386.
    If the start value differs, stop.
  - `ps -eo pid,etime,args | grep -c "[c]laude"`
  - at the end only, the full new test suite with `-q`
- Before ending, confirm no worker or background shell is still running.

============================================================
TASK 0: STARTUP (lead)
============================================================

Run the start checks. Read CONTEXT TO READ FIRST. Plan the stage. Print
the estimate ETA table in chat, per CLAUDE.md, saying which rows are
guesses. Create reports/C.1_STATE.md and update it after every task.

============================================================
TASK 1: PACKAGE, CONSTANTS AND THE GUARDED LOADER
============================================================

Owner: HarnessCoder-OpusXHigh (worker-xhigh on opus). The lead reviews
the allow-lists itself.

Build news_eval/__init__.py and news_eval/constants.py: every number
from Amendments 5, 6, 8 and 9 and Tasks 5 and 6, each with its source
paragraph in a comment:
- the bars: 2.50, 2.24, 0.0125
- the null thresholds: 0.10 minority share and 30 mixed clusters
- the floors: 60, 1,000 and 30
- the effects: 30 bp and 4.96 bp
- the counts: 10,000, 11.156 and 0.84
- the 80 percent NEUTRAL bar and the 10 percent story-group trigger
- the three seeds and the stream order from 9.11
- the 8.2 symbol rule
- the stratum labels S1 to S4, with thin-end = S3 and S4

Build news_eval/data.py, a loader with named phases. Each phase has a
fixed column allow-list. Queries are assembled only from allow-lists,
with no free SQL. Any other column raises a named refusal.

- SYNTHETIC: any database except the real one. The real path is
  resolved with realpath against news_experiment.db, so links and
  copies under another name are caught by inode and by a schema plus
  row-count fingerprint check.
- SCHEMA: PRAGMA only, against the real database.
- RELEVANCE: the six columns of Task 9.
- GATE: only what 9.8 needs: query_date, scoring_session, state,
  run_kind, judgment-free scorable filters, excess_1session, plus one
  function, directional_counts_by_cluster, that returns
  `scoring_session -> count` from a `COUNT ... GROUP BY` and never
  returns a row.
- VERDICT: all columns.

GATE and VERDICT refuse against any non-synthetic database unless
reports/c2_UNLOCK.json exists. VERDICT additionally needs the run-once
marker that the C.2 runner writes. C.1 never creates either file.

Done when: tests cover each refusal, each allow-list and the real-path
detection, using a copied-schema synthetic database renamed to look like
the real one.

============================================================
TASK 2: SYNTHETIC FIXTURES
============================================================

Owner: FixtureCoder-OpusHigh (worker-high on opus).
news_eval/synthetic.py builds SQLite databases with the exact real
schema. Copy the schema once through the SCHEMA phase into
news_eval/schema.sql, which is hashed. Each scenario generator is seeded
and deterministic, and its docstring states the expected answer.

Every scenario includes realistic structure:
- all five states, NEUTRAL rows, excluded and pending rows
- one collection day with source_failed above 20 percent (9.1)
- query_dates whose rows span two scoring sessions
- both formations (2026-07-01 and 2026-10-01)
- preferred and closed-end-fund symbols for 8.2
- story groups
- strengths 1 to 5
- net_bp and cost columns consistent with excess

Scenarios, at least:
1. S-NULL: no skill, 70/30 POSITIVE/NEGATIVE, 64 clusters, small enough
   sigma that P1's upper bound sits under 30 bp. Expected: nothing
   clears, powered negative.
2. S-EFFECT: a planted +40 bp pairing for both directions, 64 clusters.
   Expected: P1 to P4 clear, null p far under 0.0125.
3. S-PREMIUM: no skill, 88/12 skew, and an unconditional +40 bp
   news-day premium on every news name. Expected: P1's bootstrap bar is
   met, the null blocks it, and the result is not a clear. This is the
   Amendment 6 case.
4. S-UNANIMOUS: minority share under 10 percent. Expected: the null is
   UNINFORMATIVE and the primaries abstain.
5. S-REVERSAL: a planted -40 bp effect. Expected: "significant reversal"
   and a powered negative, never a clear.
6. S-HIGHRHO: a strong common cluster component in excess. Expected: the
   gate's Required exceeds M and the gate fails.
7. S-THIN: 45 clusters. Expected: the gate fails on C.
8. S-STORY: more than 10 percent shared story groups. Expected: the
   trigger fires and both versions are produced.
9. S-SENS: the effect lives only in 8.2-excluded symbols. Expected: the
   primary clears and the sensitivity reading does not. Both are
   reported, the primary governs, and the disagreement is stated.
10. S-CLUSTER: SE differs materially between clustering on query_date
    and on scoring_session. Expected: the harness uses scoring_session.
11. S-CUTOFF: pending rows at the edge, plus one stale pending row.
    Expected: S* follows 9.7.

Done when: each scenario builds in under a minute and a test pins its
row counts.

============================================================
TASK 3: STATISTICS CORE
============================================================

Owner: StatsCoder-OpusXHigh (worker-xhigh on opus). Runs in parallel
with Task 2.

news_eval/stats.py implements exactly:
- 9.4: the observation-weighted T. No mean of cluster means anywhere.
- 9.5: the cluster bootstrap that recomputes the ratio with multiplicity,
  SE with ddof 1, z, the 2.50 x SE interval, descriptive percentile
  intervals, and the `degenerate` refusal. For speed, use per-cluster
  sums and counts with multinomial resample counts.
- 9.8: sigma, the ANOVA ICC with n0 floored at 0, k_eff from cluster
  counts, and Required.
- Amendment 6 with 9.3 and 9.9: the within-cluster label shuffle that
  holds each cluster's POSITIVE and NEGATIVE counts, the NEGATIVE-only
  re-formed subset, the doubled one-sided add-one p, the upper-tail
  rule, and the story-group block version.
- Spearman with average ranks.
- The CR1 cluster-robust SE.
- SeedSequence spawn in the 9.11 order.

Each public function's docstring cites its paragraph.

Unit tests:
- hand-computed toy cases
- exact enumeration of every within-cluster permutation on a toy with
  two small clusters, against the Monte Carlo p
- the ICC against a direct formula on a toy
- the bootstrap SE against a brute-force loop on a toy

============================================================
TASK 4: ANALYSIS SET, DIAGNOSTICS, TESTS AND THE VERDICT MAPPING
============================================================

Owner: HarnessCoder-OpusXHigh implements. The lead writes the verdict
mapping table itself first, in reports/c1_verdict_mapping.md, directly
from Amendment 5's table, Task 6, 9.2, 9.3 and 8.2, and hands it to the
worker.

news_eval/family.py:
- the analysis set from 9.7: scorable rows, the 9.1 day exclusion, S*,
  and stale pending rows
- the Amendment 6 diagnostics, reported before the null is
  interpreted: counts and shares pooled, per stratum and per half, the
  NEUTRAL rate against 80 percent, the minority share, and mixed clusters
- the strength histogram and per-stratum cluster counts
- P1 to P4, E1 to E4, S1 and S2, the sector figure and the story trigger
- the 8.2 sensitivity set: rule (a) symbols containing "." plus STRK,
  STRF, STRD, STRC, and rule (b) the modal non-null sector per symbol
  per formation equal to "N/A" with sector_source finnhub_profile2. Ties
  in the mode are broken toward "N/A", the conservative exclusion. Log
  this as an open choice.

news_eval/verdict.py maps results to the verdict rows. Verdict sentences
are copied verbatim from EXPERIMENT.md into constants, and a test greps
EXPERIMENT.md to prove every quoted string exists there byte for byte.

============================================================
TASK 5: THE GATE STEP
============================================================

Owner: HarnessCoder-OpusXHigh.

news_eval/gate.py implements 9.8 through the GATE loader phase only.
Usage: `python -m news_eval.gate --db <path> --log <jsonl>`. It appends
one entry per run (inputs hash, C, M, sigma, rho, n0, k_eff, Required,
pass or fail, UTC time) and never rewrites earlier lines. An AST test
proves gate.py contains no name, attribute or string constant from the
deny list (judgment, strength, reason, POSITIVE, NEGATIVE, NEUTRAL,
net_bp, ret_) except the call to directional_counts_by_cluster.

============================================================
TASK 6: REPORT WRITER AND THE C.2 RUNNER
============================================================

Owner: HarnessCoder-OpusXHigh, with the lead reviewing the precondition
order.

news_eval/report.py writes a fixed template from computed numbers only:
- the diagnostics first
- each primary beside its 8.2 reading
- the verdict rows quoted
- "the pipeline predicts" wording
- the 8.1 model-cutoff statement
- the closed-end-fund defect from 8.2
- the relevance rates from 9.13
- the sector and story-group figures
- exploratory companion horizons only under 9.12

news_eval/run_c2.py runs in this order:
1. Preconditions, each refusing with nothing written, exit 2:
   - every manifest hash matches
   - the unlock file exists
   - the run-once marker is ABSENT
   - the snapshot is made with the SQLite backup API into a
     caller-supplied directory, set to 0444, and hashed
   - S* is computed
   - the gate log holds a PASS for this snapshot's hash
2. Write the run-once marker, recording the manifest sha256 and the
   snapshot sha256.
3. Compute in the 9.11 order.
4. Write results JSON and the verdict markdown.

Any stop after the marker writes a STOPPED result with its reason.

The 9.12 condition is a tracked file, docs/SUCCESSOR_PREREG_DRAFT.md,
whose last commit time precedes the snapshot time. Every path is a
parameter, so tests run end to end on synthetic databases in temporary
directories and never touch reports/c2*.

Done when: an end-to-end dry check on S-EFFECT and S-NULL produces the
expected verdict files, and a second invocation refuses on the marker.

============================================================
TASK 7: KNOWN-ANSWER, DETERMINISM AND MUTATION TESTS
============================================================

Owner: TestDesigner-OpusXHigh (worker-xhigh on opus), after Tasks 2 to 6.

tests/test_news_eval_*.py:
- each Task 2 scenario's expected verdict and gate outcome
- every loader refusal
- the AST blindness test
- the real-path refusal
- the verbatim-quote test
- determinism: two runs with the same seeds give byte-identical results
  JSON
- precondition refusals: a tampered hash, a present marker, a missing
  unlock, a gate FAIL in the log
- NULL handling: a NULL excess_1session or net_bp is excluded and
  counted, never read as 0

Mutation tests (tests/test_news_eval_mutations.py, parametrized). Each
mutant is applied by monkeypatching, and each must make at least one
known-answer test fail:
- shuffle labels across clusters instead of within
- drop the upper-tail rule
- use a mean of cluster means
- cluster on query_date
- use a 1.96 interval
- flip the sign convention
- skip the 20 percent day exclusion
- treat pending rows as resolved
- skip the 8.2 sensitivity reading

The table of mutants and the test that kills each goes in the return
document.

Done when: `pytest -q tests/test_news_eval_*.py` passes, with the count
recorded. Any surviving mutant is a finding fixed before Task 8.

============================================================
TASK 8: VERIFY, REVIEW, FREEZE
============================================================

8a. KnownAnswerVerifier-FableXHigh (worker-xhigh on fable). The brief
says: do not open news_eval/stats.py or family.py first. Write your own
code under reports/c1_verify/ that recomputes, from the raw synthetic
rows of S-EFFECT, S-PREMIUM and S-HIGHRHO, these numbers:
- P1's T, SE (10,000 draws, any seed), z and permutation p
- the minority share and mixed clusters
- sigma, rho, n0, k_eff and Required

Then compare against the harness outputs, within Monte Carlo tolerance
for the stochastic numbers and exactly for the rest. Then read stats.py,
family.py, gate.py and verdict.py line by line against Amendments 5, 6,
8.4 and 9 and Task 6. Findings go to reports/c1_review_verify.md, each
marked BLOCKING, SHOULD FIX or NOTE.

8b. LeakageAuditor-FableMax (worker-max on fable). The brief: hunt for
- every path by which an outcome column, a scoring_session value or a
  judgment value could be read from the real database before C.2's
  marker
- any judgment reaching the gate code
- look-ahead in S*, in pending handling, or in scoring_session versus
  query_date
- fabrication from absent input: NULL to 0, an empty pool read as zero
- any file that could change a verdict while sitting outside the
  manifest
- any way run_c2.py could compute twice
- any divergence between verdict.py and Amendment 5's table or Task 6's
  text

Findings go to reports/c1_review_leakage.md.

The lead rules on every finding in reports/c1_rulings.md. BLOCKING and
SHOULD FIX findings are fixed before the freeze, and the full suite is
rerun.

8c. Freeze (lead). news_eval/freeze.py is a re-runnable script. It
writes reports/c1_harness_freeze.json with schema "c1_harness_freeze/1":
- created_pdt (from `date`)
- pins: the seeds, the constants module's values, the git HEAD before
  the freeze commit, and the Python and numpy versions
- files: the sha256 of every file under news_eval/ (including schema.sql
  and freeze.py), every tests/test_news_eval_*.py, and
  reports/c1_verdict_mapping.md
- inputs: the sha256 of EXPERIMENT.md, news_experiment/outcomes.py,
  scoring.py, spec.py, horizon.py, store.py, collect.py, maintain.py,
  daily.py, backtest/fees.py and scripts/blind_interim_20260928.py
- external: the PropExperiment files read for patterns, by path and
  sha256, for the record only

tests/test_news_eval_freeze.py verifies the manifest against disk. Then
commit "C.1 freeze", staging explicit paths: news_eval/, the new tests,
the manifest, the mapping, the review and ruling files, and
reports/C.1_STATE.md. Record the manifest's own sha256 in STATE.

============================================================
TASK 9: THE 8.3 RELEVANCE SAMPLE (after the freeze commit)
============================================================

9a. The lead runs the frozen draw, news_eval/relevance.py, to produce
reports/c1_relevance_sample.csv: 200 rows, the six columns.

For issuer names, look locally first: a symbol-to-name table in
analysis_bars.db or market_ai_lab.db (schema check, then a narrow
SELECT), or a cached Finnhub profile. If nothing local exists, use one
NameLookup-OpusMed (worker-medium on opus) with web search, quoting the
source per symbol. Record the name source per row in the CSV.

9b. Two graders run in parallel. Each gets the same CSV and neither sees
the other's output:
- RelevanceGrader-OpusXHigh (worker-xhigh on opus)
- RelevanceGrader-FableXHigh (worker-xhigh on fable)

The rubric is Amendment 8.3's three classes, verbatim:
- company-specific: the headline is about the symbol's issuer
- roundup: the issuer is one of several named
- off-topic: the issuer is not the subject. For a preferred share, news
  about the parent company counts as company-specific only if the
  headline is about the issuer itself.

One grade per row, no "unsure", and a reason of at most 12 words.
Outputs: reports/c1_relevance_grades_opus.csv and
reports/c1_relevance_grades_fable.csv.

9c. The lead adjudicates every disagreement in writing in
reports/c1_relevance_adjudication.md. Final grades go to
reports/c1_relevance_final.csv. Report the rates overall and with the
8.2 exclusions removed, the raw agreement, and Cohen's kappa. Commit
"C.1 relevance grades" with explicit paths.

Nothing is filtered on these grades. The sample file is not in the
manifest. relevance.py is.

============================================================
TASK 10: CHECK THE WORK (lead)
============================================================

From a clean PYTHONPYCACHEPREFIX:
- rerun the whole new suite
- rerun freeze.py in check mode and confirm the manifest matches disk
- confirm git shows no change to any file listed in the manifest's
  files or inputs
- confirm reports/c2* does not exist

Then run the end checks.

============================================================
TASK 11: RETURN AND COMMIT (lead)
============================================================

Write reports/C.1_RETURN.md (DELIVERABLE below). Add a dated entry at
the top of PROGRESS.md and of RETURN.md pointing to it. Add one line
under Stage C in docs/STAGES.md. Update the C.1 row in
docs/prompts/README.md to show the run. Commit "Stage C.1 harness built
and frozen" with explicit paths. No push.

============================================================
DELEGATION PLAN
============================================================

| Task | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| 0, 8c, 9a, 9c, 10, 11 | lead | opus | xhigh | serial | freeze, adjudication and synthesis are reserved to the lead |
| 1, 4, 5, 6 | HarnessCoder-OpusXHigh | opus | xhigh | serial chain, parallel with 2 and 3 where independent | experiment code, silent-failure risk |
| 2 | FixtureCoder-OpusHigh | opus | high | parallel with 3 | generator code checkable by its pinned counts |
| 3 | StatsCoder-OpusXHigh | opus | xhigh | parallel with 2 | statistics, highest silent-failure risk |
| 4 mapping table | lead | opus | xhigh | before 4 | verdict semantics stay with the lead |
| 7 | TestDesigner-OpusXHigh | opus | xhigh | after 2 to 6 | test design for known answers and mutants |
| 8a | KnownAnswerVerifier-FableXHigh | fable | xhigh | after 7 | independent recomputation by a different model |
| 8b | LeakageAuditor-FableMax | fable | max | after 7, parallel with 8a | the hinge review |
| 9a names | NameLookup-OpusMed | opus | medium | only if no local source | narrow lookup, research on opus |
| 9b | RelevanceGrader-OpusXHigh and RelevanceGrader-FableXHigh | opus, fable | xhigh | parallel | two independent graders per 9.13 |

At most 4 workers at once. A small fix goes inline in the lead, not to
a new spawn. If Fable usage runs out, 8a, 8b and the Fable grader stay
pending in STATE. They are never downgraded. In that case, do not freeze
or commit. Finish everything else, and the return says the freeze
waits on Fable.

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

- No read of the real database beyond the three allowed reads.
- No outcome column, ever. No scoring_session or judgment value from the
  real database.
- No reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json or reports/c2/.
- No edit to EXPERIMENT.md, news_experiment/, backtest/ or the collector.
- No install into .venv. No paid API call. No push. No `git add -A`.
- No change to any bar, threshold, seed or definition in Amendment 9.
  If one looks wrong, report it under Decisions for the user.

============================================================
DELIVERABLE: ONE RETURN DOCUMENT
============================================================

Write reports/C.1_RETURN.md. Fixed sections, in order:

1. Verdict summary, at most 250 words: what was built, test and mutant
   counts, Fable outcomes, the manifest path and its own sha256, the
   relevance rates, and whether C.2 is unblocked.
2. Guardrail evidence:
   - the start and end checks, verbatim
   - the outcome-blindness attestation: every read of the real database,
     with the command
   - `git status --short` and `git diff --stat` for each commit
   - an order of events with timestamps from `date`
3. Results per task: what each module does and which 9.x paragraph it
   implements, the scenario table (expected against observed), the
   mutant kill table, and the relevance results.
4. Delegation record: one row per spawn.
5. Verification: each Fable finding, the ruling and the fix.
6. Open choices: every decision the lead made on its own, with the
   reason.
7. Decisions for the user, each with a recommendation first, then what
   C.2 must do first. That includes the unlock file, the gate cadence,
   and whether a successor draft (9.12) should be committed before the
   snapshot.
8. Session cost: the final ETA table and the per-model token table, per
   CLAUDE.md. Never estimated.

The last thing before ending: list every open choice in section 6 of the
return document.

END PROMPT
