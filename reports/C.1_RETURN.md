# Stage C.1 return: evaluation harness built and frozen, no outcomes

Lead: Opus 5.5 (claude-opus-5-5), effort xhigh. Prompt: docs/prompts/STAGE_C.1.md, run unattended from 2026-10-10 22:58 PDT. The session paused at the user's request from 23:47 to 01:38 PDT.

Commits (no push):
- 2b75aba "C.1 freeze"
- 33cadb3 "C.1 relevance grades"
- this commit, "Stage C.1 harness built and frozen"

## 1. Verdict summary

**Built.** The new package `news_eval/` contains:
- a guarded loader that refuses the live database at the path and inode level
- 11 seeded synthetic scenarios with registered answers
- the statistics core: T, the cluster bootstrap, the permutation null and the 9.8 gate
- the tests P1-P4, E1-E4, S1 and S2, and the verdict mapping
- the report writer, the two-step C.2 runner with its run-once marker, the relevance draw, the freeze script and a numpy guard

**Tests.** 783 passed, 0 skipped. 12 of 12 mutants are killed.

**Fable checks.** The 8a recompute agreed on 112 of 112 rows. The 8b leakage audit found 3 BLOCKING and 7 SHOULD FIX, all fixed; a Fable re-check found them closed and nothing new.

**Manifest.** reports/c1_harness_freeze.json, sha256 77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9.

**Relevance (n = 200).** Company-specific 65.5%, roundup 3.5%, off-topic 31.0%. With 8.2 rule (a) removed: 68.5 / 2.2 / 29.3. Agreement 0.82, kappa 0.65.

**Blindness.** No outcome, scoring_session, judgment, strength or reason value was read. The real database was opened read-only three ways: the status check, the PRAGMA and the six-column draw.

**C.2.** It is unblocked on the harness side once you:
- write the unlock file
- decide D5, the S6 row and 9.12 (section 7)

The repo `.venv` (Python 3.14, numpy 1.26.4) silently miscomputes large-array arithmetic.

## 2. Guardrail evidence

### Start checks (verbatim, reports/c1_scratch/start_checks.txt)

```
### date
Sat Oct 10 22:58:38 PDT 2026
### status
active
=== DAILY RUN 2026-10-10T05:01:49Z ===
action:     collected
target:     2026-10-08
formation:  2026-10-01
GAP:        2 session(s) missing, UNRECOVERABLE by design: 2026-08-28, 2026-09-15
rows:       0 before, 560 after
spend:      0.147118 USD over 267 calls
exit:       4
50|23614|7078
### git status --short
 M COLLECTION_LOG.md
?? reports/c1_scratch/
### git log
c426318 docs: EXPERIMENT.md Amendment 9 (operator approved, blind), Stage C.1 prompt and V1, PropExperiment doc sync
0eda3cd docs: planned cutoff-replay follow-up study, recorded at 45 clusters before any outcome
ee891f3 ops: collection timer to weekdays 22:00 America/Vancouver (operator request), docs window updated, log through 2026-10-01
### sha256 EXPERIMENT.md
641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386  EXPERIMENT.md
### claude procs
27
```

### End checks (verbatim)

Run immediately before commit 3 (reports/c1_scratch/end_checks.txt). The `systemctl --user` query failed in this shell, which has no user-bus environment, so it was repeated read-only with XDG_RUNTIME_DIR set: the timer is active. Counts are unchanged from the start (50|23614|7078); no collection ran over the weekend. No worker or background shell was running at the end.

```
### date
Sun Oct 11 03:50:38 PDT 2026
### status
Failed to connect to user scope bus via local transport: Connection refused
=== DAILY RUN 2026-10-10T05:01:49Z ===
action:     collected
target:     2026-10-08
formation:  2026-10-01
GAP:        2 session(s) missing, UNRECOVERABLE by design: 2026-08-28, 2026-09-15
rows:       0 before, 560 after
spend:      0.147118 USD over 267 calls
exit:       4
50|23614|7078
### git status --short
 M COLLECTION_LOG.md
 M PROGRESS.md
 M RETURN.md
 M docs/STAGES.md
 M docs/prompts/README.md
 M reports/C.1_STATE.md
 M reports/c1_relevance_final.csv
 M reports/c1_relevance_grader_input.csv
 M reports/c1_relevance_grades_fable.csv
 M reports/c1_relevance_grades_opus.csv
 M reports/c1_relevance_scripts/build_final.py
 M reports/c1_relevance_scripts/names_join.py
 M reports/c1_relevance_summary.json
?? reports/C.1_RETURN.md
?? reports/c1_scratch/
### git log
33cadb3 C.1 relevance grades
2b75aba C.1 freeze
c426318 docs: EXPERIMENT.md Amendment 9 (operator approved, blind), Stage C.1 prompt and V1, PropExperiment doc sync
0eda3cd docs: planned cutoff-replay follow-up study, recorded at 45 clusters before any outcome
### sha256 EXPERIMENT.md
641272349a0346f61727ee811b8b69b97b91cc43940db3dc840fff60dea13386  EXPERIMENT.md
### claude procs
26
### full new suite (-q), 03:46:28 to 03:50:32
783 passed in 243.62s (0:04:03)
exit=0
### freeze check
FROZEN: match
### reports/c2*
ls: cannot access 'reports/c2*': No such file or directory
### .pyc under news_eval
0
### status retry (this shell has DBUS_SESSION_BUS_ADDRESS=disabled: and no XDG_RUNTIME_DIR; read-only query repeated with XDG_RUNTIME_DIR=/run/user/$(id -u))
active
NEXT                             LEFT LAST                              PASSED UNIT               ACTIVATES
Mon 2026-10-12 22:00:48 PDT 1 day 18h Fri 2026-10-09 22:01:49 PDT 1 day 5h ago news-collect.timer news-collect.service
```

### Outcome-blindness attestation: every read of the real database

The log is reports/c1_scratch/real_db_reads.log. Every open used `file:news_experiment.db?mode=ro` or the frozen loader's read-only open. These are the only reads:

1. **Status check (CLAUDE.md), start.** 2026-10-10 22:58:38 PDT, by the lead: `sqlite3 "file:news_experiment.db?mode=ro" "SELECT COUNT(DISTINCT query_date), COUNT(*), SUM(state='judged') FROM news_observation WHERE run_kind='collection';"`. It printed counts only. The end check repeats it; see above.
2. **PRAGMA.** 2026-10-11T06:12:30Z (23:12:30 PDT), by HarnessCoder-OpusXHigh: `python -m news_eval.data schema --out news_eval/schema.sql`, which ran `PRAGMA table_info(news_observation)` through the SCHEMA phase. Column names and types only. It ran under the repo `.venv`, before the numpy finding; PRAGMA involves no arithmetic.
3. **Relevance draw.** 2026-10-11T10:30:08Z (03:30:08 PDT), by the lead, after the freeze commit: `nice -n 10 .venv-eval/bin/python -m news_eval.relevance draw --db news_experiment.db --out reports/c1_relevance_sample.csv`.
   - It used the frozen RELEVANCE phase: exactly `id, symbol, query_date, headline, sector, stratum`, with `run_kind = 'collection' AND state = 'judged' AND query_date <= '2026-10-09'`.
   - The population was 7,078 rows and the draw took 200.
   - Sample sha256 c470731e4a6522aa9c0b9d57f839c862dae328867a3d620fc6b0d7ced84b8a76.

No worker opened the real database:
- Every test guards `sqlite3.connect` against it.
- The leakage probes used an unstamped copy of a synthetic fixture as a stand-in.
- The B3 tests name the real path only through `os.stat` and `realpath`, and are refused before connect.

No outcome column was read, printed or aggregated. news_experiment/outcomes.py and scoring.py were not run; they are hashed as manifest inputs. reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json and reports/c2/ were never created.

Other databases, which are not the experiment database:
- **analysis_bars.db:** schema checks (`PRAGMA table_info(universe_asset)`, a source and name-null count) and one narrow `SELECT symbol, name FROM universe_asset WHERE symbol IN (<140 sampled symbols>)` for issuer names.
- **market_ai_lab.db:** `.tables` only.

### Commits: git status --short and git diff --stat

**Commit 1, 2b75aba "C.1 freeze"** (2026-10-11 03:29:57 -0700). Before staging, `git status --short` showed ` M COLLECTION_LOG.md`, plus untracked `news_eval/`, `tests/test_news_eval_*.py` (15), `reports/C.1_STATE.md`, the review and ruling files, `reports/c1_verify/`, `reports/c1_verdict_mapping.md`, `reports/c1_harness_freeze.json` and `reports/c1_scratch/`. Staged by explicit path: 49 files changed, 24,113 insertions(+), 0 deletions:
- news_eval/ (17 files)
- the 15 test files
- reports/c1_harness_freeze.json and reports/c1_verdict_mapping.md
- reports/c1_review_verify.md, c1_review_leakage.md, c1_review_leakage_recheck.md and c1_rulings.md
- reports/c1_verify/: 10 files, the scripts, JSON and comparison. The three 5.7 MB synthetic .db files were not committed; the generator rebuilds them from their seeds.
- reports/C.1_STATE.md

**Commit 2, 33cadb3 "C.1 relevance grades"** (03:39:30 -0700). 11 files changed, 1,479 insertions(+):
- reports/c1_relevance_sample.csv and .meta.json
- c1_relevance_grader_input.csv, c1_relevance_grades_opus.csv and c1_relevance_grades_fable.csv
- c1_relevance_adjudication.md, c1_relevance_final.csv and c1_relevance_summary.json
- reports/c1_relevance_scripts/names_join.py and build_final.py
- reports/C.1_STATE.md

**Commit 3, this commit, "Stage C.1 harness built and frozen".** It stages these files by explicit path:
- reports/C.1_RETURN.md (new)
- reports/C.1_STATE.md
- PROGRESS.md, RETURN.md, docs/STAGES.md and docs/prompts/README.md
- reports/c1_relevance_summary.json, regenerated with input hashes that match the committed LF bytes; the rates are unchanged
- reports/c1_relevance_scripts/names_join.py and build_final.py, which now write LF
- the four relevance CSVs, whose working copies were normalized to the committed LF bytes. Git records no content change for them.

`git show --stat` of this commit has the exact counts. No file in the manifest changes.

COLLECTION_LOG.md (the collector wrapper appends to it) and reports/c1_scratch/ were never staged.

### Order of events (times from `date`, file mtimes, git and transcript timestamps; PDT)

| time | event |
|---|---|
| 2026-10-10 22:58:21 | session start (user prompt) |
| 22:58:38 | start checks |
| 23:06:47 / 23:11:09 | lead writes news_eval/marker.py, then reports/c1_verdict_mapping.md v1 |
| 23:07:47 to 23:21:23 | HarnessCoder (Task 1: constants, loader, schema) |
| 23:08:26 to 23:26:52 | StatsCoder (Task 3) |
| 23:12:31 to 23:37:01 | FixtureCoder (Task 2) |
| 23:12:30 | real-database read 2 (PRAGMA) |
| 23:17:47 | user: "ETA table?" (answered) |
| 23:22:36 to 23:34:52 | GateCoder (Task 5 with relevance.py and freeze.py) |
| 23:27:54 to 23:50:36 | FamilyCoder (Task 4) |
| 23:35:55 to 23:56:52 | RunnerCoder (Task 6) |
| 23:47:06 | user: pause requested. 23:47:16 numpy finding logged; .venv-eval built; suites rerun |
| 23:47 to 01:37:52 | PAUSED (1 h 51 min). FamilyCoder and RunnerCoder, already running, finished inside the pause |
| 2026-10-11 01:37:52 | user: "Resume please" |
| 01:38:43 to 01:39:39 | full suite 575 passed, 1 skipped; mapping A.3 fixed |
| 01:40:40 to 02:14:01 | TestDesigner (Task 7): 662 passed, 1 skipped; 12 of 12 mutants killed |
| 02:14:49 to 02:31:15 | KnownAnswerVerifier (8a) |
| 02:15:10 to 02:38:33 | LeakageAuditor (8b) |
| 02:43:40 | lead rulings (reports/c1_rulings.md); mapping C, D7, D22 and D26 to D30 revised |
| 02:42:35 to 03:12:33 | HarnessFixer (B1 to B3, S1 to S5, S7, N3, N4, N6) |
| 02:42:53 to 02:54:15 | VerdictFixer (S6, N7) |
| 03:12:51 to 03:17:01 | full suite 779 passed, 1 skipped |
| 03:13:01 to 03:24:06 | LeakageAuditor delta re-check (same agent, resumed) |
| 03:25:13 to 03:29:19 | full suite 782 passed, 1 skipped (after lead fixes R1 and R4) |
| 03:29:25 | freeze write; check "FROZEN: match" |
| 03:29:57 | commit 1, 2b75aba |
| 03:30:08 | real-database read 3 (relevance draw) |
| 03:30:52 to 03:36:51 | the two relevance graders |
| 03:39:30 | commit 2, 33cadb3 |
| 03:40:11 to 03:44:22 | Task 10 suite from a fresh pycache prefix: 783 passed, 0 skipped (250.7 s, fresh pycache prefix) |
| 03:50:38 | end checks; commit 3 |

## 3. Results per task

### Modules (news_eval/, all frozen in the manifest)

| module | lines | task | implements |
|---|---|---|---|
| constants.py | 244 | 1 | every bar, floor, seed and label as a named constant: 9.2, 9.5, 9.8, 9.11 stream order, 8.2 rules, the unlock and marker schemas, MIN_MEM_AVAILABLE_MB |
| data.py | 1,090 | 1 | guarded loader. Phases SYNTHETIC, SCHEMA, RELEVANCE, GATE and VERDICT, with column allow-lists and a sqlite authorizer. Live-path refusal by realpath or inode before open. Unlock and marker content checks; immutable non-live opens; sidecar refusal. 9.7, 9.8, 9.13, 9.15; D21, D22, D28, D29 |
| marker.py | 63 | 1 | synthetic-database marker protocol (D27) |
| schema.sql | n/a | 1 | the 61-column news_observation DDL from PRAGMA, plus indexes |
| synthetic.py | 1,284 | 2 | 11 seeded scenarios with registered expected answers |
| stats.py | 908 | 3 | 9.4 T; 9.5 bootstrap, SE, z and interval; Amendment 6 and 9.9 permutation null (within cluster, NEGATIVE-only, block); 9.8 gate quantities; 9.10 S1 and S2 estimators; 9.11 child streams |
| cutoff.py | 210 | 5 | 9.1 day exclusion; 9.7 S* with stale pending rows, over counts only |
| gate.py | 300 | 5 | 8.4 and 9.8 gate step, append-only log. Verifies the manifest for real snapshots. The AST deny-list test passes |
| family.py | 866 | 4 | analysis set, Amendment 6 diagnostics, P1 to P4, E1 to E4, S1, S2, the 8.2 sensitivity reading, halves (9.6), the story version (9.10), companion horizons (9.12) |
| verdict.py | 684 | 4 | statuses (mapping A), gross reading (B, D5), verdict rows (C), verbatim quotes |
| report.py | 611 | 6 | the frozen report: diagnostics first, each primary beside its sensitivity reading, rows quoted, "the pipeline predicts" (9.15) |
| run_c2.py | 911 | 6 | `snapshot`, then `run`. Ordered preconditions (numpy, manifest and loaded modules, unlock, marker absent, snapshot, S*, gate PASS bound to the manifest, relevance summary, outputs absent, memory), the O_EXCL run-once marker, snapshot re-checks before and after compute, and a STOPPED path (9.15, 9.12) |
| relevance.py | 423 | 9 | the 8.3 draw (9.13) and the grading summary |
| freeze.py | 454 | 8c | manifest writer and checker. Pins Python, numpy, SQLite and BLAS; checks loaded modules |
| envcheck.py | 54 | lead | numpy temporary-elision canary; every computing entry point refuses under a bad build |
| requirements-eval.lock | n/a | lead | the .venv-eval lock (numpy 2.5.3, pytest 9.1.1) |

Files over the 800-line guideline: data.py, stats.py, run_c2.py, family.py and synthetic.py. This is a deviation, recorded; splitting them before the freeze was judged riskier than the size.

### Scenario table: expected (synthetic.SCENARIOS, registered before the harness ran) against observed

Observed is "match" when every pinned field agrees in tests/test_news_eval_known_answers.py. Those tests run gate.evaluate, family.compute at 10,000/10,000 and verdict.decide. Every T matched an independent plain-Python recomputation exactly, and every SE agreed within 2%.

| scenario | seed | built to show | gate | primary gross reading and rows | observed |
|---|---|---|---|---|---|
| S-NULL | 35 | no effect | PASS | powered_negative, "Fails gross" | match |
| S-EFFECT | 20261202 | a real effect | PASS | clears_gross. P1 to P4 clear; E1 and E2 clear, E3 abstain_interval, E4 net_negative. "Clears gross, net clears in some strata and fails in S3/S4" plus the Amendment 6 row | match |
| S-PREMIUM | 20261203 | a premium with no skill | PASS | abstention. P1, P3 and P4 blocked_by_null; P2 significant_reversal | match |
| S-UNANIMOUS | 20261204 | 94/6 labels | PASS | abstention. P1 to P4 abstain_null_uninformative, with the UNINFORMATIVE row | match |
| S-REVERSAL | 20261205 | the wrong sign | PASS | powered_negative. P1 to P4 significant_reversal; "Fails gross" | match |
| S-HIGHRHO | 34 | high rho | FAIL (REQUIRED: 6,797 > M 2,526) | powered_negative | match |
| S-THIN | 31 | 45 clusters | FAIL (C) | abstention_floor; P4 abstain_floor | match |
| S-STORY | 20261208 | duplicated stories, share 0.283 | PASS | clears_gross. The story trigger fires; the day version governs | match |
| S-SENS | 20261209 | an effect carried only by the 8.2 exclusions | PASS | primary clears_gross, sensitivity powered_negative. The readings disagree and the summary says so | match |
| S-CLUSTER | 20261210 | clustering by query_date understates SE (3.27 against 10.48) | PASS | abstention (P1 not_clear) | match |
| S-CUTOFF | 35 | a stale pending row | PASS (S* 2026-10-26, stale 2026-10-19) | powered_negative | match |

### Mutant kill table (tests/test_news_eval_mutations.py; details in reports/c1_scratch/task7/task7_report.md)

| mutant | applied as | killed by | observed failure |
|---|---|---|---|
| a. shuffle labels across clusters | family.permutation_strata collapsed to one stratum | toy `confound` (hand-derived exact p) | count_ge 0 instead of 1,000; clear instead of blocked_by_null |
| b. drop the upper-tail rule | verdict.upper_tail always True | toy `anti_skill` | clear instead of blocked_by_null (p = 2/1,001, lower tail) |
| c. mean of cluster means | family.estimate_t | toy `unequal_clusters`, and S-NULL | T 15.5 instead of 20.333; S-NULL T 1.1705 instead of 1.3190 |
| d. cluster on query_date | family.CLUSTER_COLUMN | S-CLUSTER | SE 3.24 instead of 10.5; P1 clear instead of not_clear; D 63 instead of 64 |
| e1. 1.96 interval for primaries and E-tests | K.BAR_PRIMARY_Z | toy, and S-NULL | z 2.2 reads clear; p1_upper 7.36 instead of 9.03 |
| e2. 1.96 interval for S-tests | K.BAR_STRENGTH_Z | toy, and S-NULL | z 2.1 reads clear; S2 upper wrong |
| f1. flip the sign convention | family.signed_values | S-EFFECT | powered_negative instead of clears_gross |
| f2. flip the sign in the null's labels | family.direction_labels | S-EFFECT | P1 to P4 blocked_by_null |
| g. skip the 20% day exclusion | cutoff.excluded_query_dates | S-NULL | excluded [] instead of ['2026-08-25']; M 2,504 instead of 2,470 |
| h. pending treated as resolved | cutoff.compute_s_star and family.scorable_filter | S-CUTOFF | S* 2026-10-28 instead of 2026-10-26 |
| h2. pending passes the scorable filter only | family.scorable_filter | S-CUTOFF (funnel counts) | stale 0 instead of 1; NULL-excess 10 instead of 9 |
| i. skip the 8.2 sensitivity reading | family.build_sensitivity_set | S-SENS | sensitivity clears_gross instead of powered_negative |

12 of 12 are killed. Mutants a and b are killed only by hand-built toys, because no scenario has a day premium that co-varies with the label mix, or a lower-tail significant positive (open choice 6.14).

### Relevance results (reports/c1_relevance_summary.json)

| grade set | n | company-specific | roundup | off-topic |
|---|---|---|---|---|
| final, all rows | 200 | 131 (65.5%) | 7 (3.5%) | 62 (31.0%) |
| final, 8.2 rule (a) exact removed | 181 | 124 (68.5%) | 4 (2.2%) | 53 (29.3%) |
| final, rule (a) plus rule (b) approximation b1 or b2 removed | 180 | 124 (68.9%) | 4 (2.2%) | 52 (28.9%) |
| Opus grader, all rows | 200 | 134 | 38 | 28 |
| Fable grader, all rows | 200 | 131 | 7 | 62 |

- Raw agreement is 0.820 (164 of 200) and Cohen's kappa is 0.648.
- 32 of the 36 disagreements are headlines listing several unnamed stocks, or wraps. The lead graded these off-topic, because the issuer is not named in the headline. Under the alternative reading they would be roundups: roundup 39 (19.5%), off-topic 30 (15.0%).
- The adjudication is in reports/c1_relevance_adjudication.md. Rule (b) is approximate in C.1, and C.2 recomputes it exactly. Nothing is filtered on these grades.
- Issuer names came from analysis_bars.db universe_asset.name for all 140 symbols. No web lookup was needed.

## 4. Delegation record

All spawns used the Agent tool with the agent files under .claude/agents. Times are PDT, from the subagent transcripts; tokens are summed from the same transcripts. In the Tokens column, "in" is uncached input and "cache create" counts tokens written to the prompt cache.

| agent | agent file / model / effort | objective | start to end | status | tokens (in / out / cache read / cache create) | deviations |
|---|---|---|---|---|---|---|
| HarnessCoder-OpusXHigh | worker-xhigh / opus / xhigh | Task 1: constants, loader, schema | 23:07:47 to 23:21:23 | done, 144 tests | 76 / 96,263 / 5,205,791 / 208,190 | schema dump ran under .venv (before the numpy finding) |
| StatsCoder-OpusXHigh | worker-xhigh / opus / xhigh | Task 3: stats.py | 23:08:26 to 23:26:52 | done, 46 tests | 48 / 116,091 / 3,281,536 / 201,784 | first tests ran under the bad numpy; rerun under .venv-eval |
| FixtureCoder-OpusHigh | worker-high / opus / high | Task 2: synthetic.py | 23:12:31 to 23:37:01 | done, 93 tests | 100 / 121,455 / 8,589,943 / 259,368 | calibrations re-verified under .venv-eval |
| GateCoder-OpusXHigh | worker-xhigh / opus / xhigh | Task 5 (HarnessCoder role): cutoff, gate, relevance, freeze | 23:22:36 to 23:34:52 | done, 114 tests | 90 / 87,262 / 6,503,667 / 209,153 | named by role rather than "HarnessCoder #3" |
| FamilyCoder-OpusXHigh | worker-xhigh / opus / xhigh | Task 4 (HarnessCoder role): family, verdict | 23:27:54 to 23:50:36 | done | 88 / 128,958 / 8,515,901 / 297,817 | same naming note |
| RunnerCoder-OpusXHigh | worker-xhigh / opus / xhigh | Task 6 (HarnessCoder role): run_c2, report | 23:35:55 to 23:56:52 | done, 56 tests | 146 / 114,503 / 13,811,886 / 298,741 | found the numpy bug |
| TestDesigner-OpusXHigh | worker-xhigh / opus / xhigh | Task 7 | 01:40:40 to 02:14:01 | done, +87 tests, 12 of 12 killed | 142 / 129,356 / 15,935,281 / 343,165 | none |
| KnownAnswerVerifier-FableXHigh | worker-xhigh / fable / xhigh | 8a | 02:14:49 to 02:31:15 | done, 112 of 112 | 834 / 65,439 / 4,387,590 / 258,207 | none |
| LeakageAuditor-FableMax | worker-max / fable / max | 8b, then the delta re-check after the fixes | 02:15:10 to 02:38:33, and 03:13:01 to 03:24:06 | done | 778 / 142,675 / 7,217,465 / 790,619 | resumed by SendMessage for the re-check (not in the plan) |
| HarnessFixer-OpusXHigh | worker-xhigh / opus / xhigh | fixes for B1 to B3, S1 to S5, S7, N3, N4, N6 | 02:42:35 to 03:12:33 | done | 178 / 145,789 / 20,390,898 / 346,335 | not in the plan (the rulings required fixes) |
| VerdictFixer-OpusXHigh | worker-xhigh / opus / xhigh | fixes for S6 and N7 | 02:42:53 to 02:54:15 | done | 124 / 49,772 / 8,562,206 / 186,883 | not in the plan; probably caused the 02:53 .pyc incident |
| RelevanceGrader-OpusXHigh | worker-xhigh / opus / xhigh | 9b grader | 03:30:52 to 03:34:38 | done | 12 / 26,631 / 369,332 / 101,606 | none |
| RelevanceGrader-FableXHigh | worker-xhigh / fable / xhigh | 9b grader | 03:30:59 to 03:36:51 | done | 130 / 29,625 / 260,139 / 105,210 | none |

NameLookup-OpusMed was not spawned, because every issuer name was available locally. At most 4 workers ran at once.

## 5. Verification: each Fable finding, the ruling, the fix

The full text is in reports/c1_review_verify.md, reports/c1_review_leakage.md, reports/c1_review_leakage_recheck.md and reports/c1_rulings.md (rulings and fix record).

**8a, KnownAnswerVerifier-FableXHigh.** It used its own code (reports/c1_verify/), derived from EXPERIMENT.md before opening stats.py or family.py, on S-EFFECT, S-PREMIUM and S-HIGHRHO. 112 of 112 rows agree. Exact quantities agree to 1e-9 relative; SE and p agree within Monte Carlo tolerance. BLOCKING 0, SHOULD FIX 0, NOTE 9:

| finding | ruling | fix |
|---|---|---|
| N1 S* staleness counts data sessions | accept: conservative, D16 | none |
| N2 the S* scan includes rows on excluded days | accept: the literal 9.7 text; conservative | none |
| N3 D5 conflict | kept; section 7 item 4 | none |
| N4 S2 clusters include strength-3-only clusters | accept: follows 9.2 | none |
| N5 unreachable blocked_by_null on a degenerate null | accept | none |
| N6 block null within size classes | accept: conservative, does not govern | none |
| N7 prompt "n0 floored" against EXPERIMENT.md "rho floored" | contradiction; EXPERIMENT.md followed | none (code already followed it) |
| N8 two encodings of 9.7 | already pinned by known answers across 11 scenarios | none |
| N9 runtime | noted for C.2 | none |

**8b, LeakageAuditor-FableMax.** BLOCKING 3, SHOULD FIX 7, NOTE 12. Every BLOCKING was demonstrated on a stand-in, never on the real database.

| finding | ruling | fix (and the Fable re-check result) |
|---|---|---|
| B1 a planted -wal beside the 0444 snapshot changed the gate's N and M under an unchanged hash | fix | immutable=1 on non-live opens; SidecarPresent refusal before any open; `sidecars_absent` recorded. Closed |
| B2 unlock and marker were existence-only (`--unlock README.md` admitted a real snapshot to GATE) | fix | c2_unlock/1 and c2_run_once/1 content checks; gate and runner bind manifest_sha256; marker bound to the snapshot sha. Closed |
| B3 `--real-db` replaced the compiled live path | fix | the compiled path is always live; overrides add, never replace. Closed |
| S1 snapshot not bound to the real source | fix | source_realpath must equal the real database; NON_SYNTHETIC outside test mode. Closed |
| S2 gate PASS not bound to the frozen code | fix | gate verifies the manifest for real snapshots; manifest_sha256 in every entry, required by the runner. Closed |
| S3 manifest check covered `--repo-root`, not the imported code | fix | loaded-module hash check. Closed, verified under `python -m` |
| S4 snapshot TOCTOU | fix | identity and sha re-check before and after compute; STOPPED on mismatch. Closed; swap, read and swap back between the checks remains a hostile residual |
| S5 `--marker` and other overrides allowed a second run | fix | NEWS_EVAL_TEST_MODE gates every path override. Closed |
| S6 "fails net in every stratum" selected when the E-tests abstained | fix, lead ruling (D7 revised) | new selection `clears_gross_net_abstains`; Amendment 5 quote; no-trade sentence. Selects as ruled on both readings |
| S7 a hard kill after the marker leaves nothing recorded | no resume path (9.15); risk lowered | MemAvailable >= 2,048 MB precondition (fails closed); marker message; thread variables recorded. Verified |
| N1 the synthetic marker can be forged by a writer | accept, residual | none |
| N2 a planted -journal | covered by B1 | B1 |
| N3 environment pins | fix | SQLite pinned and compared; BLAS recorded; thread variables in run_meta |
| N4 the draw defaulted to the live database | fix | `--db` required; envcheck first |
| N5 gate log forgeable | covered by S2 | S2 |
| N6 the 9.12 check used the committer date only | fix | author and committer dates both required; sha recorded |
| N7 story share 0.0 on an empty pool | fix | None, with a reason |
| N8 to N12 | accept | none |

**Re-check (same Fable agent, after the fixes).** No new BLOCKING or SHOULD FIX. Four new NOTEs:
- **R1** (the loader did not require manifest_sha256): fixed inline by the lead; well-formedness is now required.
- **R2** (snapshot.json is self-attesting): accepted; procedural item for C.2, in section 7.
- **R3** (hostile race in the VERDICT open): accepted as a residual.
- **R4** (gate entry lacked test_mode): fixed inline by the lead.

The suite was rerun after every fix round: 779 passed, then 782 passed, then 783 passed, 0 skipped (250.7 s, fresh pycache prefix).

## 6. Open choices (decisions the lead made on its own)

1. **The .venv-eval environment.** `.venv-eval` (uv cpython 3.12.13, numpy 2.5.3, pytest 9.1.1, installed offline from the uv cache, locked in news_eval/requirements-eval.lock). The numpy envcheck guard is wired into gate, family and run_c2. Reason: `.venv`'s numpy silently miscomputes, and the guardrail forbids installing into `.venv`.
2. **Two-step C.2 flow.** `run_c2 snapshot` (backup API, rollback journal, 0444, snapshot.json), then the gate on exactly those bytes, then `run_c2 run`.
3. **The verdict mapping and its definitions.** The mapping is reports/c1_verdict_mapping.md, sections A to C, with definitions D1 to D30. Each D is an open choice. The most consequential:
   - D1: C_G against C_dir, and S* inside G
   - D5: the powered negative needs no bar-met primary
   - D7 as revised
   - D9: 8.2 rule (b) per symbol-formation
   - D16: S* staleness in data sessions
   - D22: unlock schema
   - D23: draw order
   - D25: NULL excluded and counted
   - D28 to D30: test mode, immutable opens, a kill is STOPPED
4. **Mapping A.3.** It omitted the S1/S2 60-cluster floor in v1. EXPERIMENT.md Task 5 Amendment 3 (line 2068) wins; the code already matched, and A.3 row 0 was added.
5. **Prompt/EXPERIMENT.md contradiction (recorded, not a stop).** The prompt says "n0 floored at 0"; EXPERIMENT.md 9.8 floors rho. rho is floored. n0 > 0 whenever C_G >= 2.
6. **S1/S2 abstain_floor when D < 60, and the story-version floor.** The story-version floor counts scoring_session clusters (FamilyCoder, accepted).
7. **Bootstrap reported under abstain_floor.** It is reported for the record and decides nothing (FamilyCoder, accepted).
8. **Sessions with no scored observation.** Their diagnostic rows go to a half by date (FamilyCoder, accepted).
9. **8.2 rule (b) on the relevance sample.** It is approximated two ways (b1, b2) and labelled; C.2 computes it exactly.
10. **Story-version governance.** The day-clustered version governs; the story version is reported beside it (mapping C.2).
11. **S6 ruling, D7 revised.** "Fails net in every stratum" needs every E-test net_negative or below_econ_bar. Otherwise the selection is `clears_gross_net_abstains`, with the line "No E-test cleared, so no Amendment 5 row permits trading on this result." That line is the lead's wording, not a quote.
12. **S7 ruling.** No resume path after the marker. Memory precondition of 2,048 MB.
13. **R1 and R4 inline fixes** by the lead before the freeze.
14. **Mutants a and b** are accepted as killed by hand-built toys with hand-derived exact answers. No twelfth fixture was added.
15. **Scenario seeds.** S-NULL, S-HIGHRHO, S-THIN and S-CUTOFF use small seeds (35, 34, 31, 35), chosen by FixtureCoder during calibration and recorded in SCENARIOS.
16. **Grader input and issuer names.** The relevance grader input carries only id, symbol, issuer_name, headline and name_source (9.13: graders receive the symbol, the issuer name and the headline). Names went in a companion file, because `load_sample` requires exactly the six drawn columns.
17. **Relevance adjudication rule.** The classes describe the headline. An issuer not named, or not referred to unambiguously, is off-topic. The alternative reading's rates are reported. The lead's rulings coincided with the Fable grader on all 36 disagreements.
18. **Relevance scripts.** They are committed under reports/c1_relevance_scripts/ (scratch is never committed) so the final CSV can be reproduced.
19. **CRLF.** The grade CSVs were first written with CRLF; git normalized them to LF (`* text=auto`). In commit 3 they were normalized in the working tree, the scripts were set to LF, and `summarize` was rerun so the summary's input hashes match the committed bytes. The rates are unchanged.
20. **reports/c1_verify/*.db not committed.** They can be rebuilt from the seeds.
21. **Worker names.** The Tasks 4 to 6 workers were named by role (GateCoder, FamilyCoder, RunnerCoder) rather than "HarnessCoder #n".
22. **Files over 800 lines.** data.py, stats.py, run_c2.py, family.py and synthetic.py were kept as they are rather than split before the freeze.
23. **Bytecode incident.** 15 .pyc files appeared in news_eval/__pycache__ at 02:53:37, from an import without PYTHONPYCACHEPREFIX. They were deleted; freeze refuses bytecode. None exist at the freeze or now.
24. **LeakageAuditor re-check.** It was added after the fixes (not in the plan), so that the hinge fixes were verified by Fable and not by the lead alone.

## 7. Decisions for the user

Each item gives the recommendation first, then the reason.

1. **The unlock file. Recommendation: you write `reports/c2_UNLOCK.json` yourself, by hand, as the first act of C.2.** It must be a JSON object with these fields (mapping D22, after review finding 8b B2):
   - `"schema": "c2_unlock/1"`
   - `"stage": "C.2"`
   - `"approver"`: your name
   - `"utc_time"`: for example "2026-10-20T05:00:00Z"
   - `"experiment_sha256"`: from `sha256sum EXPERIMENT.md`
   - `"manifest_sha256"`: from `sha256sum reports/c1_harness_freeze.json`

   The loader refuses anything else, and the gate and runner refuse a manifest hash that differs from the one they verify. run_c2 records the unlock's sha256 in the run-once marker and the results metadata. A session must never create it: it is the one human gate between blind and unblind. C.1 never created it.

2. **The gate cadence (9.8 "Cadence"). Recommendation: run the gate once at C.2 start, on the snapshot taken then. If it fails, rerun only after every 5 new clusters, as 9.8 says, never daily.** Each run appends one line to the gate log and changes nothing else.
   - The gate needs the unlock. For a real snapshot it reads excess_1session and directional counts.
   - C.2's run takes the gate PASS for the exact snapshot sha256, with the same S*. A rerun on a newer snapshot is a new snapshot, a new gate line, and then the run.
   - The gate run never opens the live file. It reads only a `run_c2 snapshot` copy, made through the backup API, set read-only and hashed.

3. **The 9.12 successor draft. Recommendation: commit no successor draft before the C.2 snapshot, unless you already have one you want to commit unchanged.** Without the commit, C.2 does not compute ret_2/5/10session at all, which is the clean default. Writing a successor draft in a hurry to unlock exploratory horizons spends the design space 9.12 protects. If you do want the horizons, the draft must be committed at the fixed path `docs/SUCCESSOR_PREREG_DRAFT.md` before `run_c2 snapshot` runs. run_c2 checks this through git: it takes the last commit time of the draft path and compares it with the snapshot time.

4. **The D5 conflict inside EXPERIMENT.md (the powered negative). Recommendation: keep D5 as built, so a powered negative needs no primary with its bootstrap bar met, and confirm it in C.2's prompt.**
   - 9.5 reads "no primary clears". Through 9.3, a positive that met its bar but was blocked by the null would then count as "not clearing" and feed a negative.
   - The Amendment 6 note on Task 6 says the definition is "untouched", that the confirmation "intercepts positives only", and that an UNINFORMATIVE null "produces an abstention, never a negative".
   - D5 follows Amendment 6. A null-blocked positive is not evidence against the mechanism. No bar, threshold, seed or definition was changed; this is a reading. If you overturn it, edit one branch in `verdict.py` (mapping row B3) before C.2. That breaks the freeze and needs a re-freeze.

5. **The relevance rule (b) approximation. Recommendation: accept it.** 8.2(b) needs the modal sector and its source over a whole formation. The six RELEVANCE columns exclude both, so C.1 reports two labelled approximations, b1 (the Amendment 8 2026-07-01 list) and b2 (b1 plus sampled sector 'N/A'). C.2 recomputes rule (b) exactly on the snapshot for the verdict. Nothing is filtered on the relevance grades in either stage.

6. **Story-version governance. Recommendation: the day-clustered version governs and the story-clustered version is reported beside it (mapping C.2).** This is a reading of 9.10's "robustness figures". If you want the story version to be able to block, say so before C.2. It is one branch in `verdict.py`.

7. **The verdict row when the E-tests abstain (review finding 8b S6, D7 revised). Recommendation: keep the revised rule.**
   - The first mapping chose "Clears gross, fails net in every stratum" whenever no E-test cleared, including when they abstained.
   - Amendment 5 says "a wide interval spanning zero is an abstention, not a negative", and it expects wide E intervals. So that row now needs every E-test to be net_negative or below_econ_bar.
   - Otherwise C.2 reports a gross positive with the Amendment 6 row, every stratum's status, and no Amendment 5 net row, since Amendment 5 registered none for "net abstains".
   - If you would rather treat an abstaining E-test as failing net, say so before C.2. It is one branch in `verdict.py`, followed by a re-freeze.

8. **A kill after the run-once marker (review finding 8b S7). Recommendation: accept "STOPPED, process killed", and do not admit a resume.**
   - 9.15 says any stop after the marker is STOPPED and never a rerun. A resume path would be a second compute path.
   - To lower the risk, the runner refuses before the marker when less than 2,048 MB of memory is available.
   - The C.2 prompt should launch it with `OPENBLAS_NUM_THREADS=1` and outside the collector window, then commit reports/c2_RUN_ONCE.json right after the run so a deleted marker would show in git.

9. **The numpy environment.**
   - **The harness only runs under `.venv-eval` (Python 3.12.13, numpy 2.5.3, `news_eval/requirements-eval.lock`).** C.2 must use `.venv-eval/bin/python`. The repo `.venv` (Python 3.14.4, numpy 1.26.4) silently corrupts arithmetic on arrays of 256 KiB or more. Every computing entry point refuses through `news_eval/envcheck.py` under the bad build.
   - **Leave `.venv-eval` in place and do not upgrade it.** The manifest pins both versions. It is untracked. Adding `.venv-eval/` to `.gitignore` is your call, because C.1 may not edit `.gitignore`.
   - **Outside the experiment, rebuild the repo `.venv` on Python 3.12 or numpy >= 2.x, then audit whatever ran numpy under 3.14.** The collector does not import numpy, so collected data is unaffected. The risk is to anything in AiTrader's `.venv` that does numpy arithmetic on large arrays (ml_factor, backtest analytics, dashboards); it may have produced wrong numbers with no error. That is a separate session.

10. **snapshot.json is self-attesting (Fable re-check note R2). Recommendation: make it procedural in C.2.** The harness cannot prove a snapshot's source without reading the live database, which it must not do before the unlock.
   - Commit snapshot.json and the gate log immediately after each is written.
   - In the C.2 return, compare snapshot.json's collection row count with the status-check count taken at the same time.

**What C.2 must do first:**
1. Status check.
2. `.venv-eval/bin/python -m news_eval.freeze check` must print "FROZEN: match", with the manifest sha256 equal to 77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9.
3. You write reports/c2_UNLOCK.json (item 1).
4. Decide items 3, 4 and 7.
5. `run_c2 snapshot`; commit snapshot.json.
6. Run the gate on that snapshot; commit the gate log.
7. If PASS: `run_c2 run` once, with `OPENBLAS_NUM_THREADS=1` and outside 22:00 to 22:45 PT on weekdays. Then commit reports/c2_RUN_ONCE.json and the outputs.
8. If FAIL: collection continues, and the gate reruns after every 5 new clusters.

All of these use `.venv-eval/bin/python` with `PYTHONPYCACHEPREFIX` set.

## 8. Session cost

Wall clock: 2026-10-10 22:58:21 to 2026-10-11 about 03:55 PDT, about 4 h 57 min. That includes a user pause of 1 h 51 min (23:47:06 to 01:37:52), so the active time was about 3 h 06 min. Times come from the transcripts, `date` and git.

### Final ETA table

All estimates were guesses. The first estimate is the table given at 23:17; the revised one is the table at 01:42, after the pause.

| task | owner (model, effort) | first estimate | revised | actual start to end (PDT) | taken | status, deviations |
|---|---|---|---|---|---|---|
| 0 startup, plan, marker, mapping v1 | lead (opus, xhigh) | 0:13 | n/a | 22:58 to 23:11 | 0:13 | done |
| 1 constants, loader, schema | HarnessCoder (opus, xhigh) | 1:15 | n/a | 23:07:47 to 23:21:23 | 0:14 | done |
| 3 stats | StatsCoder (opus, xhigh) | 1:30 | n/a | 23:08:26 to 23:26:52 | 0:18 | done |
| 2 synthetic | FixtureCoder (opus, high) | 1:30 | n/a | 23:12:31 to 23:37:01 | 0:25 | done |
| 5 cutoff, gate, relevance, freeze | GateCoder (opus, xhigh) | 1:00 | n/a | 23:22:36 to 23:34:52 | 0:12 | done |
| 4 family, verdict | FamilyCoder (opus, xhigh) | 1:30 | n/a | 23:27:54 to 23:50:36 | 0:23 | done; finished inside the pause |
| 6 run_c2, report | RunnerCoder (opus, xhigh) | 1:15 | n/a | 23:35:55 to 23:56:52 | 0:21 | done; found the numpy bug; finished inside the pause |
| numpy finding, .venv-eval, rerun | lead | not planned | n/a | 23:47 to the pause | about 0:10 | deviation (unplanned) |
| PAUSE (user request) | n/a | n/a | n/a | 23:47:06 to 01:37:52 | 1:51 | shown separately |
| resume: STATE, mapping A.3, suite | lead | n/a | n/a | 01:37:52 to 01:40:40 | 0:03 | done |
| 7 known answers and mutants | TestDesigner (opus, xhigh) | 1:30 | 1:15 | 01:40:40 to 02:14:01 | 0:33 | done |
| 8a recompute | KnownAnswerVerifier (fable, xhigh) | 1:15 | 1:15 | 02:14:49 to 02:31:15 | 0:16 | done |
| 8b leakage review | LeakageAuditor (fable, max) | 1:15 | 1:30 | 02:15:10 to 02:38:33 | 0:23 | done |
| 8 rulings, fixes, re-check, suites | lead, HarnessFixer and VerdictFixer (opus, xhigh), LeakageAuditor re-check (fable, max) | 0:45 | 0:30 | 02:38:33 to 03:29:19 | 0:51 | done; two fixers and the re-check not planned |
| 8c freeze, commit 1 | lead | 0:15 | 0:10 | 03:29:19 to 03:29:57 | 0:01 | done |
| 9a draw and names | lead | 0:20 | 0:20 | 03:29:57 to 03:30:52 | 0:01 | done; NameLookup not needed |
| 9b two graders | RelevanceGrader (opus, xhigh; fable, xhigh) | 0:40 | 0:40 | 03:30:52 to 03:36:51 | 0:06 | done |
| 9c adjudication, commit 2 | lead | 0:30 | 0:25 | 03:36:51 to 03:39:30 | 0:03 | done; CRLF fix carried into commit 3 |
| 10 checks | lead | (in 10 to 11) | 0:10 | 03:39:30 to 03:44:22 | 0:05 | done |
| 11 return, tracking files, commit 3 | lead | 0:45 for 10 to 11 | 0:35 | 03:44:22 to about 03:55 | about 0:11 | done |
| **cumulative** | | **10:27, ending 09:25** | **ending 07:20** | **22:58:21 to about 03:55** | **4:57 wall, 3:06 active** | about 5.5 h under the first estimate |

### Tokens per model

Summed from this session's transcript and its 13 subagent transcripts by reports/c1_scratch/session_tokens.py. Assistant records are deduplicated by message id. These are exact counts; nothing is estimated. The lead row runs through 10:50:43Z, the last record before this file was written, so the last few lead turns are not included.

| model | role | input (uncached) | output | cache read | cache creation | total |
|---|---|---|---|---|---|---|
| claude-opus-5-5 | lead | 552 | 329,999 | 54,860,616 | 651,285 | 55,842,452 |
| claude-opus-5-5 | 10 workers | 1,004 | 1,016,080 | 91,166,441 | 2,453,042 | 94,636,567 |
| claude-fable-5-1 | 3 workers (the auditor counted once with its re-check) | 1,742 | 237,739 | 11,865,194 | 1,154,036 | 13,258,711 |
| **all** | | **3,298** | **1,583,818** | **157,892,251** | **4,258,363** | **163,737,730** |

- The lead had 34.1% of all tokens and 20.8% of output tokens; the workers had 65.9% and 79.2%.
- Cache reads are 96.4% of the total.
- Per-spawn counts are in section 4.
