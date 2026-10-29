# C.2 gate verification (independent recomputation)

Worker: GateVerifier-FableXHigh. Stage C.2, 2026-10-28.

Result: **MATCH.** The pass decision (gate FAILS, on the single condition
M >= Required) and all 29 compared quantities agree with the frozen harness
log, counts exactly and reals within 1e-9 relative (largest observed 1.5e-16).
No BLOCKING finding.

## Times (from `date`)

| Event | Time |
|---|---|
| Started (first `date`) | Wed Oct 28 17:25:25 PDT 2026 |
| Schema exploration run | 17:26:52 PDT (file mtime) |
| verify_gate.py started | Wed Oct 28 17:29:10 PDT 2026 |
| own_gate.json written | Wed Oct 28 17:29:11 PDT 2026 (mtime 17:29:11.913 -0700) |
| gate_log.jsonl opened for the first time | Wed Oct 28 17:29:18 PDT 2026 |
| compare.py run | 17:29:49 PDT (file mtime) |

The collector window (22:00 to 22:45 America/Vancouver) was not touched.

## Inputs and integrity

- Snapshot: `/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/snap_20261028/news_experiment_snapshot.db`
- sha256 recomputed: `2b517c70ae61affec18a973952e02714240e8f9086fe3069f3bc1ff8e3ed6500` (matches the expected value and the log's `inputs_sha256`).
- Mode 0444. No `-wal`, `-shm` or `-journal` file beside it.
- Opened only as `file:<abs path>?mode=ro&immutable=1` with `uri=True`.
- Live `news_experiment.db` never opened. Nothing under `news_eval/`, `tests/test_news_eval_*`, `reports/c1_verdict_mapping.md` or `reports/C.1_RETURN.md` was opened at any point (no mismatch arose, so the post-write diagnostic allowance was not used).
- Registered text read only by line range: EXPERIMENT.md 792-808, 835-850, 905-922, 924-950, 2129-2166, plus 2400-2414 and 2440-2450 (located by `grep -n source_failed`) for the Task 7 rule that 9.1 cites but does not define.
- Code: `/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/verify_gate/verify_gate.py` (stdlib only, run under `.venv-eval` with `-I -B`, `nice -n 10`, single-threaded BLAS env), `explore_schema.py`, `explore_day_20261007.py`, `compare.py`. Outputs: `own_gate.json`, `verify_gate.out`, `compare.out`, `*.sql.log`.

Column discipline: only `query_date, scoring_session, state, run_kind, exclusion_reason, outcome_state, excess_1session` were selected. `judgment` appears once, inside `SELECT scoring_session, COUNT(*) ... AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY scoring_session`. No `strength`, `reason`, `ret_*`, `bench_*`, `net_bp`, `cost_bp_round_trip` or `anchor_*` column was read. Row-level `excess_1session` values lived in process memory only; nothing written or printed is finer than a per-cluster count.

## Method and reading of each rule

### 9.1 / Task 7 day exclusion
Reading: for each collection `query_date`, share = rows with `state = 'source_failed'` divided by all `run_kind = 'collection'` rows on that date ("a day's queries"). Excluded when share is strictly greater than 0.20 ("exceeds 20 percent"). Computed as an exact rational to avoid float boundary effects. Applied before clusters form, by removing excluded `query_date`s from G.

Alternative reading: a denominator that drops `excluded_pre_call` rows (or even `no_news`). On the only day with a material count (2026-10-07: source_failed 33, judged 170, model_failed 7, excluded_pre_call 14, no_news 252) the share is 0.0693 under my reading, 0.0714 without `excluded_pre_call`, and 0.157 under the extreme `33 / (170 + 7 + 33)`. No reading reaches 0.20, so the exclusion set is `[]` under every reading. The collector's own marker `exclusion_reason = 'day_excluded_source_failures'` is present on 0 rows, consistent.

### 9.7 cutoff S*
Reading: pending rows are `run_kind='collection' AND state='judged' AND outcome_state='pending'`. Latest resolved session is `MAX(scoring_session)` over resolved judged collection rows. S* is the latest `scoring_session` such that no non-stale pending row has `scoring_session <= S*`; with no non-stale pending rows, S* is the latest `scoring_session` among judged collection rows. A pending row is stale when its session is more than 3 sessions before the latest resolved session.

The "3 sessions" count is ambiguous: (A) NYSE calendar sessions, (B) distinct `scoring_session` values present in the data. I computed both. The snapshot holds **0 pending judged collection rows** (outcome_state is only `resolved` 9759 and `excluded` 4), so stale count is 0 under both readings and S* = 2026-10-27 under both. The ambiguity changes no number today. It would matter only in a future snapshot that still holds a pending row near a data gap (the data has none: all 65 sessions from 2026-07-28 to 2026-10-27 are present, see calendar check).

Applying the cutoff `scoring_session <= S*` removes nothing: N and C_G are 9759 and 65 with and without it.

### 9.8 gate rows G and statistics
- G: `run_kind='collection' AND state='judged' AND outcome_state='resolved' AND exclusion_reason='' AND scoring_session IS NOT NULL AND scoring_session <> '' AND excess_1session IS NOT NULL AND query_date NOT IN (excluded) AND scoring_session <= S*`. Judgment not constrained, so NEUTRAL rows are in G.
- NULL-excess count: same conditions with `excess_1session IS NULL`. Result 0 (every resolved row has a `real`-typed excess).
- sigma: sd with ddof 1 of `10000 x excess_1session` over G, no trimming, no winsorizing. Computed with `math.fsum` and cross-checked against an exact `fractions.Fraction` computation.
- rho: one-way ANOVA ICC over G clustered by `scoring_session`: MSB = SSB/(C-1), MSW = SSW/(N-C), `n0 = (N - sum n_c^2 / N)/(C-1)`, `rho = (MSB - MSW)/(MSB + (n0-1) MSW)`, floored at 0. Reading of C in n0: the number of clusters among G (C_G). The alternative (C = clusters holding a directional row) is identical here, 65 = 65: every G cluster holds at least one directional row.
- k_eff: `sum m_c^2 / M` from the single permitted judgment aggregate. Exact value 526855/5363.
- Required: `11.156 x (sigma/30)^2 x (1 + (k_eff - 1) x rho)` with the literal 11.156 as 9.8 states. The arithmetic it rounds, (2.50+0.84)^2 = 11.1556, is reported alongside; it changes Required by 0.48 (3.6e-5 relative) and nothing else.
- Pass: C >= 60 AND M >= 1000 AND M >= Required.

## Comparison table (own value first, then gate_log.jsonl)

| Quantity | Own | Log | Rel diff | Result |
|---|---|---|---|---|
| snapshot sha256 | 2b517c70...8ed6500 | 2b517c70...8ed6500 | exact | MATCH |
| excluded query_dates | [] | {} | exact | MATCH |
| latest resolved session | 2026-10-27 | 2026-10-27 | exact | MATCH |
| pending judged collection rows | 0 | 0 (stale 0, earliest_nonstale_pending_session null) | exact | MATCH |
| stale count | 0 | 0 | exact | MATCH |
| S* | 2026-10-27 | 2026-10-27 (`latest_session_no_nonstale_pending`) | exact | MATCH |
| N (gate rows G) | 9759 | 9759 | exact | MATCH |
| C_G | 65 | 65 | exact | MATCH |
| NULL-excess count | 0 | 0 | exact | MATCH |
| sigma (bp) | 442.0875909566156 | 442.0875909566156 | 0.0 | MATCH |
| MSB | 1542607.3844763383 | 1542607.384476338 | 1.509e-16 | MATCH |
| MSW | 186547.4190382628 | 186547.4190382628 | 0.0 | MATCH |
| n0 | 149.65570563069986 | 149.65570563069986 | 0.0 | MATCH |
| rho_raw | 0.04632310192106974 | 0.04632310192106974 | 0.0 | MATCH |
| rho (floored) | 0.04632310192106974 | 0.04632310192106974 | 0.0 | MATCH |
| C (clusters with a directional row) | 65 | 65 | exact | MATCH |
| M (directional gate rows) | 5363 | 5363 | exact | MATCH |
| k_eff | 98.2388588476599 | 98.2388588476599 | 0.0 | MATCH |
| Required | 13335.001574131153 | 13335.001574131153 | 0.0 | MATCH |
| cond C >= 60 | True | True (not in `failing`) | exact | MATCH |
| cond M >= 1000 | True | True (not in `failing`) | exact | MATCH |
| cond M >= Required | False | False (`failing: ["REQUIRED"]`, "M 5363 < Required 13335.002") | exact | MATCH |
| **pass** | **False** | **False** | exact | **MATCH** |
| constant 11.156 | 11.156 | 11.156 (`REQUIRED_FACTOR`) | 0.0 | MATCH |
| delta 30 bp | 30.0 | 30.0 | 0.0 | MATCH |
| floor 60 clusters | 60 | 60 | exact | MATCH |
| floor 1000 scorable | 1000 | 1000 | exact | MATCH |
| day-exclusion share 0.2 | 0.2 | 0.2 | 0.0 | MATCH |
| stale sessions 3 | 3 | 3 | exact | MATCH |

Exact-rational cross-check of my own floats: MSB and MSW agree with the Fraction computation to 0.0 relative; rho_raw to 1.5e-16. sigma from the exact variance 195441.43807782387 is 442.0875909566156, identical.

Other log fields read for context: `status: ok`, `test_mode: false`, `db_class: NON_SYNTHETIC`, `degenerate_condition: ""`, `empty_session_pending_count: 0`, `utc_time: 2026-10-29T00:22:34Z` (= 17:22:34 PDT, consistent with the snapshot directory mtime 17:22), `db_path` equal to the snapshot path.

## 9.1 per-day source_failed share (all 62 collection query_dates)

| query_date | collection rows | source_failed | share | excluded |
|---|---|---|---|---|
| 2026-07-28 | 427 | 0 | 0.0000 | no |
| 2026-07-29 | 538 | 0 | 0.0000 | no |
| 2026-07-30 | 489 | 0 | 0.0000 | no |
| 2026-07-31 | 440 | 0 | 0.0000 | no |
| 2026-08-03 | 453 | 0 | 0.0000 | no |
| 2026-08-04 | 477 | 0 | 0.0000 | no |
| 2026-08-05 | 543 | 0 | 0.0000 | no |
| 2026-08-06 | 559 | 0 | 0.0000 | no |
| 2026-08-07 | 507 | 0 | 0.0000 | no |
| 2026-08-10 | 483 | 0 | 0.0000 | no |
| 2026-08-11 | 455 | 0 | 0.0000 | no |
| 2026-08-12 | 432 | 0 | 0.0000 | no |
| 2026-08-13 | 445 | 0 | 0.0000 | no |
| 2026-08-14 | 427 | 0 | 0.0000 | no |
| 2026-08-17 | 426 | 0 | 0.0000 | no |
| 2026-08-18 | 421 | 0 | 0.0000 | no |
| 2026-08-19 | 433 | 0 | 0.0000 | no |
| 2026-08-20 | 444 | 0 | 0.0000 | no |
| 2026-08-21 | 433 | 0 | 0.0000 | no |
| 2026-08-24 | 412 | 0 | 0.0000 | no |
| 2026-08-25 | 409 | 0 | 0.0000 | no |
| 2026-08-26 | 426 | 0 | 0.0000 | no |
| 2026-08-27 | 430 | 0 | 0.0000 | no |
| 2026-08-31 | 434 | 0 | 0.0000 | no |
| 2026-09-01 | 429 | 0 | 0.0000 | no |
| 2026-09-02 | 456 | 0 | 0.0000 | no |
| 2026-09-03 | 454 | 0 | 0.0000 | no |
| 2026-09-04 | 470 | 0 | 0.0000 | no |
| 2026-09-08 | 486 | 0 | 0.0000 | no |
| 2026-09-09 | 504 | 0 | 0.0000 | no |
| 2026-09-10 | 472 | 0 | 0.0000 | no |
| 2026-09-11 | 448 | 0 | 0.0000 | no |
| 2026-09-14 | 510 | 0 | 0.0000 | no |
| 2026-09-16 | 471 | 0 | 0.0000 | no |
| 2026-09-17 | 483 | 0 | 0.0000 | no |
| 2026-09-18 | 488 | 0 | 0.0000 | no |
| 2026-09-21 | 494 | 0 | 0.0000 | no |
| 2026-09-22 | 498 | 0 | 0.0000 | no |
| 2026-09-23 | 498 | 0 | 0.0000 | no |
| 2026-09-24 | 500 | 1 | 0.0020 | no |
| 2026-09-25 | 487 | 0 | 0.0000 | no |
| 2026-09-28 | 485 | 0 | 0.0000 | no |
| 2026-09-29 | 511 | 0 | 0.0000 | no |
| 2026-09-30 | 511 | 0 | 0.0000 | no |
| 2026-10-01 | 492 | 0 | 0.0000 | no |
| 2026-10-02 | 484 | 0 | 0.0000 | no |
| 2026-10-05 | 536 | 0 | 0.0000 | no |
| 2026-10-06 | 468 | 0 | 0.0000 | no |
| 2026-10-07 | 476 | 33 | 0.0693 | no |
| 2026-10-08 | 560 | 0 | 0.0000 | no |
| 2026-10-09 | 516 | 0 | 0.0000 | no |
| 2026-10-12 | 512 | 0 | 0.0000 | no |
| 2026-10-13 | 537 | 0 | 0.0000 | no |
| 2026-10-14 | 505 | 0 | 0.0000 | no |
| 2026-10-15 | 496 | 0 | 0.0000 | no |
| 2026-10-16 | 524 | 0 | 0.0000 | no |
| 2026-10-19 | 587 | 0 | 0.0000 | no |
| 2026-10-20 | 538 | 0 | 0.0000 | no |
| 2026-10-21 | 558 | 0 | 0.0000 | no |
| 2026-10-22 | 620 | 0 | 0.0000 | no |
| 2026-10-23 | 523 | 0 | 0.0000 | no |
| 2026-10-26 | 652 | 0 | 0.0000 | no |

Maximum share 0.0693 (2026-10-07). Excluded dates: none.

## S* derivation

- Latest resolved session: 2026-10-27. Latest judged session of any outcome_state: 2026-10-27.
- Pending judged collection rows: 0 (sessions: none). Stale: 0 under both readings.
- S* = 2026-10-27, set as the latest `scoring_session` among judged collection rows because no pending row exists. Log agrees (`s_star_case: latest_session_no_nonstale_pending`).
- Distinct judged scoring sessions: 65, 2026-07-28 to 2026-10-27, equal to the NYSE session list for that span (no session missing, none on a non-trading day).

## Gate quantities (own)

N = 9759, C_G = 65, NULL-excess = 0, cluster sizes in G min 15, max 289, mean 150.14.
sigma = 442.0875909566156 bp, MSB = 1542607.3844763383, MSW = 186547.4190382628, n0 = 149.65570563069986, rho_raw = rho = 0.04632310192106974 (floor not binding).
C = 65, M = 5363, m_c min 5, max 165, mean 82.51, k_eff = 98.2388588476599 (= 526855/5363).
Required = 13335.001574131153 (11.1556 variant: 13334.523445713292).
Conditions: C >= 60 TRUE; M >= 1000 TRUE; M >= Required FALSE. **Pass: FALSE.**

Decomposition (arithmetic): (sigma/30)^2 is about 217.2 against the 36 the design assumed (180 bp sigma); the design effect 1 + (k_eff - 1) rho is about 5.50 against the assumed 2.95. 11.156 x 217.2 x 5.50 is about 13335.

## Findings

1. **NOTE (no action).** Pass decision and every quantity match the frozen log. Nothing BLOCKING, nothing SHOULD FIX.
2. **NOTE.** 9.8 states the constant as the literal 11.156 while naming it "(2.50 + 0.84)^2", which is 11.1556. Both the harness and this check used 11.156, as the text instructs. Required moves by 0.48 under the other value; neither the pass decision nor the projection changes.
3. **NOTE.** The "3 sessions" staleness rule in 9.7 admits calendar-session and data-session readings. With 0 pending rows in this snapshot both give the same S*, stale count and G. It becomes material only for a future snapshot with pending rows adjacent to a session gap; the data has no session gap today.
4. **NOTE.** The C in the n0 denominator (C_G, clusters among G) and the C of the pass condition (clusters with a directional row) coincide at 65 because every G cluster holds a directional row. Should a future snapshot have an all-NEUTRAL cluster, the two would diverge and the rule's choice should be stated explicitly.
5. **NOTE.** Collection `query_date`s number 62 against 64 NYSE sessions from 2026-07-28 to 2026-10-26; 2026-08-28 and 2026-09-15 have no collection rows. No rule depends on this and gaps stay gaps; recorded only so the lead has the count. All 65 scoring sessions are nonetheless populated because after-hours rows score the next session.
6. **NOTE.** No reading of the Task 7 denominator ("a day's queries") brings 2026-10-07 to 20 percent (0.0693 to 0.157 across readings). The exclusion set is empty under all of them.

## PROJECTION (arithmetic, not a finding)

Holding sigma, rho, k_eff and the mean directional count per cluster at today's values:

- M/C = 5363 / 65 = 82.5077 directional gate rows per cluster.
- Clusters at which M reaches Required: ceil(13335.0016 / 82.5077) = ceil(161.62) = **162** (also 162 under the 11.1556 variant).
- 120th NYSE trading session counting 2026-07-28 as session 1: **2027-01-15** (Friday). Holidays inside the span: 2026-09-07 Labor Day, 2026-11-26 Thanksgiving, 2026-12-25 Christmas, 2027-01-01 New Year's Day. 2026-11-27 (early close) counts as a session. The full holiday table used (2026 and 2027, NYSE) is in `verify_gate.py` `NYSE_HOLIDAYS`; only the four above fall inside the span. Calendar cross-check: the 65 data sessions exactly equal the computed NYSE sessions 2026-07-28 to 2026-10-27, so S* is session 65.
- Sessions from the one after S* (2026-10-28) to the hard stop inclusive: 55. At one new cluster per session with no gaps, clusters at the hard stop would be 120 and M about 120 x 82.51 = 9901, against Required 13335. Clusters needed, 162, exceed 120. This is the stated arithmetic under constant parameters; it is not a verdict and the lead decides what it means.

## Every SQL statement run (verbatim)

### explore_schema.py (schema and categorical counts on permitted columns)

```sql
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;
PRAGMA table_info(news_observation);
SELECT run_kind, COUNT(*) FROM news_observation GROUP BY run_kind ORDER BY run_kind;
SELECT state, COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY state ORDER BY state;
SELECT outcome_state, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY outcome_state ORDER BY outcome_state;
SELECT exclusion_reason, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY exclusion_reason ORDER BY exclusion_reason;
SELECT (exclusion_reason IS NULL) AS is_null, (exclusion_reason = '') AS is_empty, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2;
SELECT (scoring_session IS NULL) AS is_null, (scoring_session = '') AS is_empty, COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1, 2;
SELECT typeof(excess_1session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' AND outcome_state='resolved' GROUP BY 1;
SELECT typeof(scoring_session), typeof(query_date), COUNT(*) FROM news_observation WHERE run_kind='collection' GROUP BY 1, 2;
SELECT MIN(query_date), MAX(query_date), COUNT(DISTINCT query_date), COUNT(*) FROM news_observation WHERE run_kind='collection';
SELECT MIN(scoring_session), MAX(scoring_session), COUNT(DISTINCT scoring_session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' AND scoring_session IS NOT NULL AND scoring_session <> '';
SELECT LENGTH(scoring_session), COUNT(*) FROM news_observation WHERE run_kind='collection' AND state='judged' GROUP BY 1;
```

Results (counts): tables `news_observation`, `sqlite_sequence`; run_kind collection 30182, demonstration 46; collection state: excluded_pre_call 919, judged 9763, model_failed 723, no_news 18743, source_failed 34; judged outcome_state: excluded 4, resolved 9759; judged exclusion_reason: '' 9759, symbol_did_not_trade 4 (none NULL); judged scoring_session never NULL or empty, always length 10; resolved excess_1session typeof real 9759; 62 distinct query_dates 2026-07-28 to 2026-10-26; 65 distinct judged scoring sessions 2026-07-28 to 2026-10-27.

### verify_gate.py (the gate). The one bound parameter `?` was `'2026-10-27'` (S*). No excluded-date parameters were bound because the exclusion set was empty, so the `{excl_sql}` fragment was the empty string shown as a blank line.

```sql
SELECT query_date,
               COUNT(*) AS n_total,
               SUM(state = 'source_failed') AS n_source_failed
        FROM news_observation
        WHERE run_kind = 'collection'
        GROUP BY query_date
        ORDER BY query_date;

SELECT COUNT(*), COUNT(DISTINCT query_date)
        FROM news_observation
        WHERE run_kind = 'collection' AND exclusion_reason = 'day_excluded_source_failures';

SELECT MAX(scoring_session)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged' AND outcome_state = 'resolved'
          AND scoring_session IS NOT NULL AND scoring_session <> '';

SELECT MAX(scoring_session)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
          AND scoring_session IS NOT NULL AND scoring_session <> '';

SELECT scoring_session, COUNT(*)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged' AND outcome_state = 'pending'
        GROUP BY scoring_session
        ORDER BY scoring_session;

SELECT outcome_state, COUNT(*)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
        GROUP BY outcome_state
        ORDER BY outcome_state;

SELECT DISTINCT scoring_session
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
          AND scoring_session IS NOT NULL AND scoring_session <> ''
        ORDER BY scoring_session;

SELECT scoring_session, excess_1session
        FROM news_observation
        WHERE 
        run_kind = 'collection'
        AND state = 'judged'
        AND outcome_state = 'resolved'
        AND exclusion_reason = ''
        AND scoring_session IS NOT NULL AND scoring_session <> ''

          AND excess_1session IS NOT NULL
          
           AND scoring_session <= ?
        ORDER BY scoring_session;

SELECT COUNT(*)
        FROM news_observation
        WHERE 
        run_kind = 'collection'
        AND state = 'judged'
        AND outcome_state = 'resolved'
        AND exclusion_reason = ''
        AND scoring_session IS NOT NULL AND scoring_session <> ''

          AND excess_1session IS NULL
          
           AND scoring_session <= ?;

SELECT COUNT(*), COUNT(DISTINCT scoring_session)
        FROM news_observation
        WHERE 
        run_kind = 'collection'
        AND state = 'judged'
        AND outcome_state = 'resolved'
        AND exclusion_reason = ''
        AND scoring_session IS NOT NULL AND scoring_session <> ''

          AND excess_1session IS NOT NULL;

SELECT scoring_session, COUNT(*)
        FROM news_observation
        WHERE 
        run_kind = 'collection'
        AND state = 'judged'
        AND outcome_state = 'resolved'
        AND exclusion_reason = ''
        AND scoring_session IS NOT NULL AND scoring_session <> ''

          AND excess_1session IS NOT NULL
          
           AND scoring_session <= ?
          AND judgment IN ('POSITIVE', 'NEGATIVE')
        GROUP BY scoring_session
        ORDER BY scoring_session;
```

### explore_day_20261007.py (bounding the alternative 9.1 denominator)

```sql
SELECT state, COUNT(*) FROM news_observation WHERE run_kind='collection' AND query_date='2026-10-07' GROUP BY state ORDER BY state;
```

Result: excluded_pre_call 14, judged 170, model_failed 7, no_news 252, source_failed 33.

## Boundaries kept

Wrote only under `reports/c2/verify_gate/` and this file. No git commands, no network, no workers spawned, no paid calls, no edit to EXPERIMENT.md or any collector file, live database untouched, `news_eval/` and the C.1 artifacts unopened.
