# Stage C.1 verdict mapping (written by the C.1 lead before any harness code)

Written 2026-10-10 by the Stage C.1 lead (Opus 5.5) from EXPERIMENT.md
Amendment 5 (the verdict table), Task 6 (the powered negative), Amendments 6,
8.2 and 9 (9.2, 9.3, 9.5, 9.6, 9.7, 9.9, 9.10). No outcome existed or was read.
This file is hashed in the C.1 freeze manifest. news_eval/family.py and
news_eval/verdict.py implement it. Where this file and EXPERIMENT.md differ,
EXPERIMENT.md governs and the difference is a defect in this file.

Section D lists every definition the lead fixed where the registered text
left a choice. Each is also an open choice in reports/C.1_RETURN.md.

## A. Per-test status

Every test is computed twice: the primary reading (the analysis set) and
the 8.2 sensitivity reading (the analysis set less the 8.2 symbols). Rules
are identical for both readings.

### A.1 Primary tests P1 to P4 (Task 5, Amendment 6, 9.2, 9.3, 9.5)

P1 pooled, P2 NEGATIVE-only, P3 thin-end (S3 and S4), P4 chronological second
half (9.6). The statistic is 9.4's observation-weighted T in bp. Evaluate in
this order and stop at the first that applies:

| order | condition | status |
|---|---|---|
| 1 | fewer than 30 clusters hold the test's scored observations (9.2) | `abstain_floor` |
| 2 | SE = 0 or fewer than 2 clusters (9.5) | `degenerate` (a named refusal, no number) |
| 3 | z >= +2.50 and T - 2.50 x SE > 0, and the reading's null is UNINFORMATIVE (Amendment 6) | `abstain_null_uninformative` |
| 4 | z >= +2.50 and T - 2.50 x SE > 0, null informative, p <= 0.0125 and upper tail (9.3) | `clear` |
| 5 | z >= +2.50 and T - 2.50 x SE > 0, null informative, and p > 0.0125 or not upper tail | `blocked_by_null` |
| 6 | z <= -2.50 | `significant_reversal` (9.3: reported "in those words", never a clear) |
| 7 | otherwise (the interval spans zero) | `not_clear` |

The permutation p, both tail counts and the upper-tail flag are computed and
reported for every primary whatever its status.

"Bootstrap bar met" means statuses 3, 4 and 5: z >= +2.50 with the lower
bound above zero.

### A.2 Economic secondaries E1 to E4 (Amendment 5, Task 6, 9.4, 9.10)

T = (sum of net_bp) / n over the stratum's scored observations with non-null
net_bp. Same estimator. In order:

| order | condition | status |
|---|---|---|
| 1 | fewer than 30 clusters hold the stratum's scored observations with non-null net_bp | `abstain_floor` |
| 2 | SE = 0 or fewer than 2 clusters | `degenerate` |
| 3 | z >= +2.50, T - 2.50 x SE > 0 and T >= 4.96 bp | `clear` |
| 4 | z >= +2.50, T - 2.50 x SE > 0 and T < 4.96 bp | `below_econ_bar` (Task 6: "fails the economic question even if its interval excludes zero") |
| 5 | z <= -2.50 | `net_negative` (9.10: reported as "net negative") |
| 6 | otherwise (the interval spans zero) | `abstain_interval` (Amendment 5: "a wide interval spanning zero is an abstention, not a negative") |

### A.3 Strength secondaries S1 and S2 (Task 5 Amendment 3, 9.10)

Over scored observations with strength_parse_ok = 1. S1 is Spearman(strength,
signed_bp) with average ranks. S2 is the observation-weighted mean signed_bp
over strengths {4, 5} minus the same over {1, 2}. Bar 2.24. In order:

| order | condition | status |
|---|---|---|
| 0 | the analysis set holds fewer than 60 clusters, D < 60 (Task 5 Amendment 3 "under the same 60-cluster floor"; 9.2 keeps 60 as the floor on the set as a whole) | `abstain_floor` |
| 1 | fewer than 30 clusters hold scored observations with strength_parse_ok = 1 (9.2) | `abstain_floor` |
| 2 | S2 only: either pool empty in the observed data (9.10) | `abstain_empty_pool` |
| 3 | SE = 0, fewer than 2 clusters, fewer than 2 defined replicates, or zero rank variance observed | `degenerate` |
| 4 | z >= +2.24 and T - 2.24 x SE > 0 | `clear` |
| 5 | otherwise | `not_clear` (a z at or below -2.24 is reported with its sign and is never a clear) |

Every strength result carries the label: weaker evidence than a primary that
clears 2.50, a property of the model's self-knowledge, and never confirmation
of the hypothesis (Task 5, Amendment 5). The five per-bucket means are
descriptive.

## B. The gross reading (Task 5 floor, Task 6, Amendment 6 note, 9.2, 9.5)

Computed per reading. D = clusters holding the reading's scored
observations; M = the reading's scored observations. In order:

| order | condition | gross reading |
|---|---|---|
| 1 | D < 60 or M < 1,000 | `abstention_floor` ("Below that the result is an abstention regardless of the point estimate", Task 5) |
| 2 | at least one primary is `clear` | `clears_gross` |
| 3 | P1 is `not_clear` or `significant_reversal`, no primary has its bootstrap bar met, and P1's T + 2.50 x SE < 30 bp | `powered_negative` |
| 4 | otherwise | `abstention` |

Under row 4 the report states which applies: P1's interval includes both zero
and 30 bp (Task 6: "An interval that includes both zero and 30 bp gross at the
cluster floor is an abstention, not a negative and not a finding."), a
positive was intercepted by the null (`blocked_by_null` or
`abstain_null_uninformative`; Amendment 6: "a design that cannot tell them
apart should abstain rather than promote"), or P1 is `degenerate`.

A `significant_reversal` does not block row 3 (9.3: "It still counts toward
Task 6's powered-negative reading"). A primary in `abstain_floor` or
`degenerate` other than P1 does not block row 3.

## C. Verdict rows (Amendment 5's table, quoted verbatim; selection by the lead)

Rows are quoted from EXPERIMENT.md lines 383 to 388 byte for byte, bold
markers included. verdict.py holds them as constants, and a test proves each
is a substring of EXPERIMENT.md.

| gross reading of the primary reading | E-test pattern | rows reported |
|---|---|---|
| `clears_gross` | no E-test `clear`, and every E-test `net_negative` or `below_econ_bar` | "Clears gross, fails net in every stratum", plus the Amendment 6 row |
| `clears_gross` | no E-test `clear`, and at least one E-test `abstain_interval`, `abstain_floor` or `degenerate` | no Amendment 5 net row (selection `clears_gross_net_abstains`). The Amendment 6 row is reported, every stratum's status is listed, and the report quotes Amendment 5: "a wide interval spanning zero is an abstention, not a negative" (revised 2026-10-11 on review finding 8b S6, see D7) |
| `clears_gross` | 1 to 3 E-tests `clear` | "Clears gross, net clears in some strata and fails in S3/S4", plus the Amendment 6 row. The realised per-stratum pattern is printed beside it, and if S3 or S4 cleared, the report says the realised pattern differs from the row's description and that the row's sentence ("tradeable where the E-tests cleared") is the one applied |
| `clears_gross` | all four E-tests `clear` | "Clears gross and net", plus the Amendment 6 row |
| `powered_negative` | any | "Fails gross" |
| `abstention` or `abstention_floor` | any | no Amendment 5 outcome row; the abstention is stated in Task 6's words where they apply |
| any | any primary is `abstain_null_uninformative` | also "The permutation null is UNINFORMATIVE under the Amendment 6 thresholds", naming the affected primaries, with the realised judgment distribution beside it |

The E-tests are reported in every case, cleared or not, with intervals
(Amendment 5: "reported whatever it says"). With no E-test `clear`, the report
also lists each stratum's status, so an `abstain_interval` is never presented
as a measured failure.

Wording rules wherever a result is reported (Amendment 5, Amendment 6, 9.15):
a gross positive is worded "the pipeline predicts" and never "the model
understands"; a gross-positive net-negative result is "a finding about
markets" and licenses no trade; no secondary confirms the hypothesis.

### C.1 Primary against sensitivity (8.2)

Both readings get a gross reading and rows. If the two differ in gross
reading or in the selected outcome row, both are reported side by side, the
primary governs, and the one-line summary states the disagreement in words.
Neither reading is dropped.

### C.2 Day-clustered against story-group version (Task 5, 9.10)

When the story trigger fires, P1 to P4 are also computed with the bootstrap
clustered on story_group_id and the block null. Both versions are reported.
The scoring_session-clustered version governs the verdict. If the two
differ in any primary's status, the one-line summary states it in words.

## D. Definitions the lead fixed (each is an open choice in the return)

- D1 Gate rows G (9.8) are the analysis set less the judgment condition: the
  9.7 scorable conditions without the judgment test, the 9.1 day exclusion,
  and the S* cutoff. Reason: the gate decides whether the sample that will be
  analysed is powered; gating on rows the analysis drops could pass a gate
  the analysed sample fails. C_dir (clusters with at least one directional
  scorable row) and C_G (clusters in G, used in n0) are named apart.
- D2 Null informativeness (Amendment 6) is one pooled determination per
  reading. The primary reading uses the analysis set's minority share and
  mixed clusters, the sensitivity reading uses its own, and the determination
  applies to all four primaries of that reading. Per-test subset values are
  reported, descriptive only. Reason: Amendment 6 registers the pooled
  minority share and the mixed-cluster count, nothing per test.
- D3 A clear needs both z >= +2.50 (9.3) and T - 2.50 x SE > 0 (9.5). The two
  coincide except at exact equality, where both readings are applied
  conjunctively.
- D4 Upper tail (9.3) is strict: count(T_perm >= T_obs) < count(T_perm <=
  T_obs).
- D5 Powered negative needs no primary with its bootstrap bar met (B row 3).
  This settles a conflict inside EXPERIMENT.md. Read through 9.3, 9.5's "no
  primary clears" would call a null-blocked positive a negative. The
  Amendment 6 note on Task 6 says the definition is "untouched", that the
  confirmation "intercepts positives only", and that an UNINFORMATIVE null
  "produces an abstention, never a negative". Amendment 9 also says no
  verdict row moves. Reported to the user under Decisions.
- D6 "Clears gross" means at least one primary is `clear` in the primary
  reading.
- D7 The verdict row is chosen by the number of E-tests that are `clear`
  (C table). With none `clear`, "fails net in every stratum" needs every
  E-test to be `net_negative` or `below_econ_bar`. Task 6 counts
  `below_econ_bar` as failing: "fails the economic question even if its
  interval excludes zero". If any E-test abstained or is degenerate, no
  Amendment 5 net row applies (Amendment 5: "a wide interval spanning zero is
  an abstention, not a negative"). Revised 2026-10-11 on finding 8b S6. The
  first version selected "fails net" on zero clears, which read an abstention
  as a negative.
- D8 The E-test statuses are those in A.2, including `below_econ_bar`.
- D9 8.2 rule (a) is by symbol, in every formation. Rule (b) is per (symbol,
  formation_date), over all run_kind = 'collection' rows of that symbol in
  that formation, whatever their state: the modal non-null sector, with ties
  broken toward 'N/A', must be 'N/A', and the modal non-null sector_source
  among that symbol-formation's rows whose sector is 'N/A' must be
  'finnhub_profile2', with ties broken toward 'finnhub_profile2'. A flagged
  (symbol, formation) loses its rows in that formation only. Ties go toward
  exclusion, the conservative side.
- D10 Sector robustness (9.10). The sector for a (symbol, formation) is the
  modal non-null sector over its analysis-set rows. Ties go to 'N/A' when it
  is among the tied values, else to the lexicographically smallest. 'N/A'
  and null both become the cluster 'unclassified'. The figure is P1 primary
  reading only, with a CR1 SE where G/(G-1) is the only correction because
  K = 1. Descriptive.
- D11 The story trigger (9.10) is evaluated on the primary reading's scored
  observations. When it fires, the story version runs for both readings.
  Groups are by story_group_id across sessions for the bootstrap, and by
  (scoring_session, story_group_id) for the block null.
- D12 The block null permutes the label vectors of story groups within each
  (scoring_session, block size) class. Unshared rows are blocks of size 1.
  This holds each session's POSITIVE and NEGATIVE counts and moves every
  judgment with its whole group.
- D13 The RNG streams follow constants.STREAM_ORDER, the 9.11 order (20
  pairs). The story-group versions take indices 20 to 27, appended after the
  registered order so no registered index moves. BOOT_SEED drives bootstrap
  streams and PERM_SEED drives permutation streams, each from
  SeedSequence(seed).spawn(28), child i for stream index i.
- D14 The descriptive percentile interval uses quantiles Phi(-bar) and
  Phi(+bar), at 2.50 for primaries and E-tests and 2.24 for strength tests.
- D15 For S1 and S2, a replicate where the statistic is undefined (an empty
  pool, or zero rank variance) is excluded from the SE and the count is
  reported. Fewer than 2 defined replicates is `degenerate`.
- D16 S* (9.7). Sessions are ordered by the distinct non-empty scoring_session
  values among judged collection rows in the snapshot, as ISO date strings.
  A pending judged collection row is stale when the latest resolved session's
  index minus its own session's index exceeds 3. S* is the latest session
  strictly before the earliest non-stale pending session, or the latest
  session when no non-stale pending row exists. A pending row with an empty
  scoring_session is counted and reported, cannot be placed on the session
  order, and does not hold S* back.
- D17 Halves (9.6) come from the primary reading's D clusters, the clusters
  holding its scored observations, ordered by scoring_session. The
  sensitivity reading uses the same split.
- D18 The 9.1 day rule. For each collection query_date, the share is
  source_failed rows over all run_kind = 'collection' rows of that
  query_date. The day is excluded when the share exceeds 0.20.
- D19 The sensitivity reading applies the B floors (60 clusters, 1,000
  observations) to its own D and M.
- D20 Diagnostics population (Amendment 6). Judgment counts and shares,
  including the NEUTRAL rate, are taken over rows meeting every scorable
  condition except the judgment condition (NEUTRAL included). The minority
  share and mixed clusters are taken over scored observations.
- D21 The GATE and VERDICT loader phases refuse the live database even when
  the unlock file exists, because 9.7 says C.2 reads only the snapshot.
- D22 The unlock is reports/c2_UNLOCK.json and must parse as a JSON object
  with these fields:
  - `schema` = "c2_unlock/1"
  - `stage` = "C.2"
  - `approver` (non-empty)
  - `utc_time` (ISO 8601, ending Z)
  - `experiment_sha256` (the sha256 of EXPERIMENT.md on disk)
  - `manifest_sha256` (the sha256 of reports/c1_harness_freeze.json, checked
    by gate.py and run_c2.py)

  The run-once marker must carry `schema` = "c2_run_once/1" and a
  `snapshot_sha256` equal to the file VERDICT opens. Revised 2026-10-11 on
  finding 8b B2. The first version accepted any existing file.
- D23 Relevance draw (9.13): the population is ordered by id, the generator
  is numpy.random.default_rng(RELEVANCE_SEED), the draw is choice(n, 200,
  replace=False), and the output is sorted by id.
- D24 Quoted EXPERIMENT.md strings keep their bold markers and line breaks
  byte for byte.
- D25 A NULL excess_1session, net_bp or ret_k is excluded and counted, never
  read as 0.
- D26 Companion horizons (9.12) for k in 2, 5 and 10: the observation-weighted
  mean, over scored observations with non-null ret_ksession, of
  +10,000 x ret_ksession for POSITIVE and -10,000 x ret_ksession for
  NEGATIVE. Primary reading only, labelled EXPLORATORY, with no interval and
  no bar. Computed only when docs/SUCCESSOR_PREREG_DRAFT.md is tracked and
  both its last commit's author date and its committer date precede the
  snapshot time. The commit sha and both dates are recorded. Revised
  2026-10-11 on finding 8b N6.
- D27 A database counts as SYNTHETIC only through the marker protocol in
  news_eval/marker.py:
  - the header application_id is 0x4E455653
  - the meta table names news_eval.synthetic as the generator
  - the fingerprint (the news_observation DDL plus the row count) matches

  Residual (8b N1): someone with write access can forge the marker. Doing
  so needs a copy of the real database, which is itself a guardrail breach.
- D28 Test mode is the environment variable NEWS_EVAL_TEST_MODE=1. Outside
  it, the CLI path overrides (`--real-db`, `--unlock`, `--marker`,
  `--repo-root`, `--manifest`) and their run_c2 config equivalents are
  refused. A path override adds a fake live database and never removes the
  repository's news_experiment.db. Test mode refuses any snapshot taken
  from the real database (8b B3, S5).
- D29 Every non-live database is opened `mode=ro&immutable=1`. A non-live
  database with a -wal, -shm or -journal sidecar is refused before it is
  opened. The live file keeps plain `mode=ro` (8b B1).
- D30 A run killed after the run-once marker (marker present, and neither
  results.json nor results_STOPPED.json) is a STOPPED verdict, reason
  "process killed". There is no resume path (9.15). Before the marker,
  the runner refuses when less than 2,048 MB of memory is available
  (8b S7).
