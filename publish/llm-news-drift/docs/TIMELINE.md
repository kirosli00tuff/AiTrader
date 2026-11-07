# Timeline

Every dated event in this experiment, from Stage A on 2026-07-27 to Stage P.1
on 2026-11-07. One row per event. Each row names the commit in this
repository that records it.

## How to read it

- Dates are calendar dates in UTC-7, the zone of almost every commit here.
  Three commits on 2026-07-29 carry +0000 times. They fall on the same date
  in UTC-7. Times quoted from the collection log are UTC and end in Z.
- "Commit" is the short id in this repository. "AiTrader" is the id of the
  same commit in the original working repository. Documents and commit
  messages here quote AiTrader ids, and the messages are kept byte for byte.
  The AiTrader column maps those quotes to the commits here.
- An event with no commit of its own shows the first commit that records it.
- Check a row with `git show <commit>`. List every commit with
  `git log --format='%h %ad %s' --date=short`.
- No row reports a result. Gate verdicts appear as the files word them.
- This history starts at AiTrader 74532e7, the first Stage A commit. Earlier
  engine history is not here. Eight later AiTrader commits touched no
  published file and were dropped. They are listed at the end.
- Prompts for sessions before 2026-09-23 were not archived. AiTrader's
  RETURN.md holds their summaries. That file is not in this repository.
- July commit messages number the work as stages 0, 1 and 2. From
  2026-09-23 the stage plan in docs/STAGES.md uses letters.

## July 2026

| Date | Event | Commit | AiTrader |
|---|---|---|---|
| 2026-07-27 | Stage A starts. The first commit creates EXPERIMENT.md and proposes the "stage 0" pre-registration: specification only, nothing built, pending operator review. | `f99fe72` | `74532e7` |
| 2026-07-27 | Level 1 sizer and trade and position limits set from derived values. The derivations are pre-registered. Live trading untouched. | `51e37a3` | `82e8e72` |
| 2026-07-27 | Every Level 1 key audited for enforcement. Unenforced keys removed or wired. Live trading untouched. | `0af9219` | `d3fedc1` |
| 2026-07-27 | Amendment 1: the universe rule moves from liquidity rank to absolute ADV thresholds. | `c053992` | `9bae8dd` |
| 2026-07-27 | Amendment 2: the eligibility price floor is derived from the tick. | `c4f3931` | `55130b1` |
| 2026-07-27 | Stage 1 feasibility measurement: coverage, arrival rate, ETB fraction, latency, tick multiple and a model comparison. Measurement only, nothing built. EXPERIMENT.md dates the results 2026-07-28, the UTC date of this commit. | `0be7fbc` | `9ca628a` |
| 2026-07-27 | The quoted spread and tick multiple are measured in regular trading hours for the fee model. Measurement only. | `2135dd0` | `937526c` |
| 2026-07-27 | The blocked regular-hours tick measurement is recorded. | `fb121c1` | `2635ad9` |
| 2026-07-28 | Amendment 3: the model becomes Claude Haiku 4.5, with a five-point strength field that is recorded and gates nothing. | `e7d03f4` | `5518051` |
| 2026-07-28 | EXPERIMENT.md is marked accepted by the operator, binding and closed, before any collection. The same commit builds the stage 2 news collector to that specification, with its own credential. Collection not started. | `0f1e279` | `2903f79` |
| 2026-07-28 | The regular-hours spread measurement is recorded as unusable on an IEX-only feed. Fee model and specification unchanged. | `f32745b` | `96ec3c7` |
| 2026-07-28 | Amendment 4, approved explicitly by the operator: a fifth state, `excluded_pre_call`. Delay-rolled headlines are scored, not excluded. | `e93e7f9` | `7a549e2` |
| 2026-07-28 | The exchange calendar is filled forward. The collector refuses a session it cannot resolve instead of assuming one. | `f742fcc` | `7029959` |
| 2026-07-29 | The tick multiple is measured from historical consolidated quotes and the fee model is updated. Specification unchanged. | `2c5a074` | `a641824` |
| 2026-07-29 | Amendment 5: the gross signal question is separated from the net economic question. | `b6b31ab` | `2ade4fb` |
| 2026-07-29 | Independent audit after the Level 1 re-derivation and five amendments. Assessment only, nothing changed. The commit touched no published file. | none | `ec348a9` |
| 2026-07-29 | Amendment 6: a within-day judgment-permutation null, its skew diagnostic, and the claim boundary on a gross positive. | `cfe7228` | `8a3bc4b` |
| 2026-07-29 | Three latent cost and usage fallbacks closed. Stale hurdle and test-count figures corrected. Live trading untouched. | `7e62dca` | `d1769c3` |
| 2026-07-29 | Amendment 7: stale Level 1 figures corrected, the trade-cap mechanism verified, and the collection start preconditions documented. Amendments 1 to 7 all come before the first collection row. | `be028b6` | `c173b53` |
| 2026-07-29 | Collection start anchor logged at 2026-07-29T22:54:53Z. It names AiTrader commit c173b53. | `ecdef20` | `685d7f4` |
| 2026-07-29 | Clean-tree anchor logged at 2026-07-29T22:59:09Z on AiTrader 685d7f4. | `eb1f6b1` | `129a953` |
| 2026-07-29 | Stage B starts. The first target session, 2026-07-28, is collected. | `2f3b397` | `45e437f` |
| 2026-07-29 | Daily collection is scheduled from the trading calendar, with gap detection and idempotence. The timer runs weekdays at 22:30 UTC. | `948f78e` | `284e720` |
| 2026-07-29 | Rows excluded for absent bars reopen, longer horizons fill as their bars appear, and each row is benchmarked against its own formation's band. No judgment altered. | `de46747` | `647a8ab` |

## August 2026

| Date | Event | Commit | AiTrader |
|---|---|---|---|
| 2026-08-04 | Collection log committed for target sessions 2026-07-29 to 2026-07-31. | `d2a3ac5` | `8a49239` |
| 2026-08-06 | Collection log committed. The commit message says "through 2026-07-31", but the commit adds the runs for target sessions 2026-08-03 to 2026-08-05. | `eb693bf` | `f1fb308` |
| 2026-08-18 | Collection log committed through target session 2026-08-14. | `9e58849` | `b5c2236` |
| 2026-08-24 | Collection log committed through target session 2026-08-21. | `0fd5e27` | `705e0ed` |
| 2026-08-31 | Session 2026-08-28 becomes the first permanent gap. The run at 2026-08-31T22:51:02Z refuses it (`refused_bars`, exit 5): "only 0.0% of the band holds a bar for 2026-08-31". The refusal says the session stays collectable. The next run, at 2026-09-02T01:54:41Z, collects 2026-08-31 and logs 2026-08-28 as unrecoverable. Why the bars were missing: cause not recorded. | `f7e2482` | `4c7ba69` |

## September 2026

| Date | Event | Commit | AiTrader |
|---|---|---|---|
| 2026-09-02 to 09-04 | Target session 2026-09-02 appears in the log only as raw collector output, with no DAILY RUN entry. It sits between the runs of 2026-09-03T00:04:10Z and 2026-09-04T22:37:41Z, after a `database is locked` traceback. Who ran it, when, and why: not recorded. | `f7e2482` | `4c7ba69` |
| 2026-09-16 | Session 2026-09-15 becomes the second permanent gap. The run at 2026-09-16T23:58:17Z refuses it (`refused_bars`, exit 5) with the same detail for 2026-09-16. The next run, at 2026-09-17T22:30:12Z, collects 2026-09-16 and logs 2026-09-15 as unrecoverable. Why the bars were missing: cause not recorded. | `f7e2482` | `4c7ba69` |
| 2026-09-23 | Stage B.1, workflow port. The planning chat ports the orchestration files from PropExperiment: CLAUDE.md session rules, .claude/, docs/ORCHESTRATION.md, docs/PROMPT_WRITING.md, docs/prompts/, docs/STAGES.md and docs/DECISIONS.md. No CLI session and no prompt file. From this date each new prompt is committed before it is sent. | `f7e2482` | `4c7ba69` |
| 2026-09-23 | docs/DECISIONS.md records the orchestration rules: an Opus 5.5 lead, workers on haiku, sonnet, opus or fable, and Fable for independent verification only. docs/STAGES.md lists the two permanent gaps. The collection log is committed through 2026-09-21. | `f7e2482` | `4c7ba69` |
| 2026-09-28 | Phidias is recorded as a venue candidate, not adopted. Stages D and E stay on IBKR. Collection log committed through 2026-09-25. | `f7742dc` | `ef87da6` |
| 2026-09-28 | Stage B.2, blind interim read, by the planning chat at 41 clusters. Pre-outcome fields only. No CLI session. Return: reports/B.2_BLIND_INTERIM.md. | `9105182` | `0ec89ac` |
| 2026-09-28 | Amendment 8, operator approved: model cutoff, sensitivity exclusion, relevance rate, and the gate computation. | `9105182` | `0ec89ac` |
| 2026-09-28 | docs/STAGES.md: C.2 runs the Amendment 8.4 gate step before any effect. | `1894ff8` | `d594e50` |

## October 2026

| Date | Event | Commit | AiTrader |
|---|---|---|---|
| 2026-10-02 | The collection timer moves to weekdays 22:00 America/Vancouver at the operator's request. Target sessions unchanged. Collection log committed through 2026-10-01. | `d58ecde` | `ee891f3` |
| 2026-10-02 | A cutoff-replay follow-up study is planned and recorded at 45 day clusters, before any outcome. It is a separate study with its own pre-registration. | `c66716e` | `0eda3cd` |
| 2026-10-10 | Stage B.3, C.1 preparation, by the planning chat at 50 collection days. No CLI session. | `3fa575e` | `c426318` |
| 2026-10-10 | Amendment 9, operator approved and blind: implementation definitions for the Stage C harness, fixed before the build. The day cluster is `scoring_session`. | `3fa575e` | `c426318` |
| 2026-10-10 | Amendment 9.14: the 2026-10-02 and 2026-10-05 headlines that failed with `error_class = 'exhausted'` stay `model_failed` and are not re-judged. V1, in the same commit, puts the credit-outage headlines at 349. | `3fa575e` | `c426318` |
| 2026-10-10 | V1: take every planning-chat recommendation for Stage C, recorded as Amendment 9. Two independent workers grade the 8.3 relevance sample. | `3fa575e` | `c426318` |
| 2026-10-10 | Stage C.1 prompt committed: docs/prompts/STAGE_C.1.md. At the user's request the planning chat launches C.1 itself, unattended. The run starts at 22:58. | `3fa575e` | `c426318` |
| 2026-10-11 | C.1 freeze. The harness news_eval/, its tests and reports/c1_harness_freeze.json are committed. Manifest sha256 77c9bd73...b2a9. | `847d381` | `2b75aba` |
| 2026-10-11 | C.1 relevance grades for the Amendment 8.3 sample. | `40add55` | `33cadb3` |
| 2026-10-11 | Stage C.1 return: reports/C.1_RETURN.md. The harness is built on synthetic rows and frozen. No outcome read. The session paused at the user's request from 23:47 to 01:38. | `ca3cbc4` | `c757324` |
| 2026-10-15 | V2: the C.1 recommendations. Kiros alone writes the unlock file by hand. After a gate FAIL the gate retries after 5 more collection days carrying judgments. The harness runs only under .venv-eval. | `4eee167` | `820ca5c` |
| 2026-10-15 | Stage C.2 prompt committed: docs/prompts/STAGE_C.2.md. | `4eee167` | `820ca5c` |
| 2026-10-22 | Session 2026-10-22 is lost to an empty experiment credit balance: 357 headlines `model_failed` (exhausted), 0 judged. It stays as recorded. The credit was restored before the 2026-10-26 run. Recorded in V3. | `5681f74` | `e70c5a8` |
| 2026-10-28 | V3: the C.2 unlock. Kiros, away from the laptop, told the planning chat in writing "Write the unlock". The planning chat wrote reports/c2_UNLOCK.json at 2026-10-29T00:19:45Z with Kiros as approver. This departs from V2 item 1, and V3 says so. | `5681f74` | `e70c5a8` |
| 2026-10-28 | Stage C.2, attempt 1, starts at 17:20. The unlock file, snapshot reports/c2/snap_20261028 and the gate log are committed. | `0df977a` | `a1eabc2` |
| 2026-10-28 | Stage C.2 return: reports/C.2_RETURN.md. The 9.8 gate reads "gate FAIL", on power, at 65 day clusters. No verdict run, judgments unread. Fable recomputed the gate and matched 29 of 29 quantities. | `64791a6` | `d936d9c` |
| 2026-10-28 | Amendment 10, operator approved: the readout at the hard stop, and the lock. If no gate run has passed by the 120th trading session, C.2 runs the verdict once on the hard-stop snapshot. After the C.3 re-freeze, EXPERIMENT.md is not amended again before the readout, except to correct a demonstrated defect. | `c915772` | `2359d16` |
| 2026-10-28 | V4: Amendment 10 approved as drafted. The V3 unlock is void once this commit lands. Stage C.3 is defined. Collection continues to the hard stop. The replay ordering and the prompt structure are set. | `c915772` | `2359d16` |
| 2026-10-28 | Stage C.3 prompt committed: docs/prompts/STAGE_C.3.md. It waits for Kiros to say go. | `c915772` | `2359d16` |

## November 2026

| Date | Event | Commit | AiTrader |
|---|---|---|---|
| 2026-11-02 | A shutdown kills the 22:02 collector run with SIGTERM 22 seconds in, during the bar top-up. Started-then-killed runs are not retried. V5 records session 2026-10-30 as a new permanent gap. Likely root cause, as recorded: suspend and sleep had been masked since 2026-07-15, so closing the lid never suspended the laptop, and it was shut down to be carried. | `3a22e99` | `e8b3d2c` |
| 2026-11-04 | V5: the collection timer moves to weekdays 23:00 America/Vancouver at the operator's request. The target session rule is unchanged. The C.3 prompt gets the new collector window. | `3a22e99` | `e8b3d2c` |
| 2026-11-05 | V6: the public repository llm-news-drift, built locally by Stage P.1 from Stage A onward with a deterministic extraction. Stage P.1 prompt committed: docs/prompts/STAGE_P.1.md. | `5cf5860` | `66b9e3c` |
| 2026-11-05 | The Stage P.1 prompt gets a note on the GitHub CLI keyring. | `09a900d` | `86adee9` |
| 2026-11-05 | Stage C.3 starts at 21:37, unattended. | `a92da39` | `84cb7fb` |
| 2026-11-05 | V7: the public profile layout. P.1 and P.2 merge into one Stage P.1 that creates every new repository private. AiTrader stays public until the January 2027 readout. The order becomes C.3, then C.2b attempt 2, then P.1. The C.3 start gate in the prompt was a planner defect, ruled on during the run. | `de51fd5` | `f4e2f3a` |
| 2026-11-05 | V8, at 22:00: the second unlock and Stage C.2b. Kiros: "I unlock it. Run tonight". | `de51fd5` | `f4e2f3a` |
| 2026-11-05 | V9: the PropExperiment prompt structure update. The lead self-wipes at about 150k tokens of context, workers are routed by complexity, and briefs are lean. | `de51fd5` | `f4e2f3a` |
| 2026-11-06 | Stage C.3 return: reports/C.3_RETURN.md. Amendment 10.1 and 10.2 are built into news_eval and the harness is re-frozen in reports/c3_harness_freeze.json, sha256 19dc1da7...8bc8. Hard stop: session 120, 2027-01-15. 905 tests passed in a clean clone. No outcome read. | `a92da39` | `84cb7fb` |
| 2026-11-06 | The planning chat writes the second reports/c2_UNLOCK.json at 07:13Z on Kiros's instruction, after reviewing the C.3 commit. It binds the EXPERIMENT.md of Amendment 10 and the C.3 manifest. | `fc56589` | `7d01388` |
| 2026-11-06 | The Stage C.2b prompt and the merged Stage P.1 prompt are committed with V7 to V9. | `de51fd5` | `f4e2f3a` |
| 2026-11-06 | Stage C.2b, attempt 2, starts at 00:15. Snapshot reports/c2/snap_20261106 and the gate log are committed. | `fc56589` | `7d01388` |
| 2026-11-06 | The C.2b lead stops at 00:25 on the 5-hour usage limit. The laptop reboots at 10:35. | `2357dd9` | `fb858af` |
| 2026-11-07 | The planner restarts the C.2b lead at 01:58. | `2357dd9` | `fb858af` |
| 2026-11-07 | Stage C.2b return: reports/C.2b_RETURN_20261106.md. The 9.8 gate reads "Gate FAIL", on power, at 72 day clusters. No verdict run, judgments unread. Fable recomputed the gate and matched 31 of 31 quantities. | `2357dd9` | `fb858af` |
| 2026-11-07 | Stage P.1 builds this repository from AiTrader and writes its public documents, this file among them. Its return stays in AiTrader. | the commit that adds this file | the commit that adds this file |

## Scheduled in the files, not yet happened

- On or after 2026-11-13: C.2b attempt 3, at 71 judged collection days
  (docs/STAGES.md).
- 2027-01-15, session 120: the hard stop. C.2b runs once in `--hard-stop`
  mode on the first snapshot whose S* is on or after this date
  (docs/prompts/README.md, reports/C.3_RETURN.md).

## AiTrader commits not in this history

These eight AiTrader commits come after 74532e7 and touched no published
file. The extraction drops empty commits, so they have no id here. Check
them in AiTrader with `git show <id>`.

| Date | AiTrader | Subject, shortened |
|---|---|---|
| 2026-07-27 | `4e20a20` | Pre-register the derived Level 1 sizing and limit values before applying any of them |
| 2026-07-27 | `45367a6` | Stop before applying the Level 1 changes |
| 2026-07-28 | `c8766b2` | Correct the test count in the calendar session record |
| 2026-07-28 | `e60232a` | Find a free consolidated quote source on the existing credential, no amendment made |
| 2026-07-29 | `ec348a9` | Independent audit after the Level 1 re-derivation and five amendments, assessment only |
| 2026-07-29 | `952cf8e` | Record the queue opt-in convention |
| 2026-07-29 | `c197201` | Ignore stale electron scaffolding and model binaries |
| 2026-07-29 | `f819b68` | Replace the GUI landing view with collection monitoring that cannot display an outcome |
