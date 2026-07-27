# Data Audit, 2026-07-27

Read-only inventory of `market_ai_lab.db` (production) against `analysis_bars.db`
(research) and against what the documents claim. SELECT statements only. No file,
schema, config or row was changed. No process was signalled. No network or
provider call was made. No test suite was run.

Everything under VERIFIED came from a query whose result is quoted. Everything
under INFERRED is reasoning on top of those results and is labelled as such.

---

## THE FINDING THAT CHANGES A CONCLUSION

**`whale_signal` produced 2,162 factor outputs from zero whale data.**

VERIFIED. `whale_activity` holds **0 rows**. `whale_signal_history` holds **0
rows**. Both are empty in production AND in the analysis database. Over the same
period `model_outputs` holds **2,162 `whale_signal` rows**, spanning 2026-06-30
to 2026-07-26, at a mean confidence of 0.5466 and a nonzero weight throughout.

INFERRED. A factor with no source table and no history table cannot have been
reading whale data, so those 2,162 confidences were produced without an input.
That makes `whale_signal` a fabricated input which nonetheless carried 0.10 of
the ensemble weight and sat inside the weight-normalised mean that decides the
Level 1 confidence floor. The 2026-07-27 deactivation was better justified than
the session that performed it knew: it treated `whale_signal` as unmeasured, and
the data says it was unmeasurable.

**This also corrects the framing that motivated this audit.** The earlier session
recorded "the analysis database showed zero whale rows and the production
database showed thousands". Those are two different tables. Whale ACTIVITY is
zero in both stores. Whale SIGNAL OUTPUTS number 2,162 and exist only in
production, because the analysis store holds no factor outputs. The two stores
never disagreed about whale activity. They were asked different questions.

---

## TASK 1: TABLE INVENTORY

31 tables in production, with row counts and reference counts against source
(excluding tests and `build/`) and against the tracking documents.

| table | rows | src refs | doc refs | range |
|---|---|---|---|---|
| bars | 167,680 | 3806 | 151 | 2025-07-15 .. 2026-07-26 |
| account_balances | 80,253 | 10 | 2 | 2026-06-30 .. 2026-07-26 |
| model_outputs | 12,967 | 29 | 4 | 2026-06-30 .. 2026-07-26 |
| signals | 12,967 | 167 | 35 | 2026-06-30 .. 2026-07-26 |
| discovery_drop | 7,928 | 7 | 3 | 2026-07-17 .. 2026-07-26 |
| events | 5,788 | 1956 | 56 | 2026-06-30 .. 2026-07-26 |
| entry_decision | 3,627 | 36 | 8 | 2026-07-14 .. 2026-07-26 |
| blocked_trades | 1,912 | 7 | 2 | 2026-06-30 .. 2026-07-25 |
| weight_changes | 1,452 | 8 | 6 | 2026-06-30 .. 2026-07-14 |
| param_history | 1,434 | 9 | 5 | 2026-06-30 .. 2026-07-02 |
| trades | 265 | 316 | 96 | 2026-06-30 .. 2026-07-26 |
| council_eval_provider | 225 | 10 | 2 | no ts column |
| discovery_candidate | 144 | 12 | 4 | 2026-07-17 .. 2026-07-26 |
| discovery_pass | 138 | 32 | 13 | 2026-07-17 .. 2026-07-26 |
| council_eval | 75 | 25 | 8 | 2026-07-21 .. 2026-07-26 |
| sleeve_history | 74 | 10 | 4 | 2026-07-17 .. 2026-07-26 |
| research_thesis | 31 | 25 | 4 | 2026-07-17 .. 2026-07-26 |
| council_refusal | 26 | 3 | 3 | 2026-07-25 .. 2026-07-26 |
| watchlist_event | 26 | 12 | 6 | 2026-07-17 .. 2026-07-26 |
| regime_state | 14 | 7 | 3 | 2026-07-20 .. 2026-07-26 |
| positions | 10 | 3225 | 47 | no ts column |
| watchlist | 8 | 210 | 73 | 2026-07-20 .. 2026-07-26 |
| venue_state | 5 | 24 | 7 | 2026-07-02 .. 2026-07-26 |
| approval_state | 1 | 11 | 3 | |
| adaptive_action | 0 | 45 | 3 | |
| model_registry | 0 | 25 | 5 | |
| whale_activity | 0 | 19 | 9 | |
| whale_signal_history | 0 | 11 | 2 | |
| adaptive_event | 0 | 18 | **0** | |
| adaptive_interpretation | 0 | 14 | **0** | |
| adaptive_poll | 0 | 10 | **0** | |

**EXISTS AND NO DOCUMENT MENTIONS IT:** `adaptive_event`,
`adaptive_interpretation`, `adaptive_poll`. All three are empty. INFERRED: they
belong to the adaptive real-time layer that ships disabled, so emptiness is
expected, but their existence and schema are described nowhere.

**DESCRIBED BUT EMPTY:** `adaptive_action`, `model_registry`, `whale_activity`,
`whale_signal_history`, plus the three above. `model_registry` is the notable
one and is treated as a contradicted claim below.

**WRITTEN BY NOTHING:** none. Every table has at least one source reference.

---

## TASK 2: DISTINCT VALUES NO DOCUMENT EXPLAINS

**`trades.origin` = `reconciliation`, 3 rows, 2026-07-24.** VERIFIED. CONTEXT.md
documents this column as `strategy | adaptive_react | rebalance`. The data holds
`strategy` (262) and `reconciliation` (3). Same shape as the `dnn_rl` discovery:
a value present in data and in no document.

**Two documented values have never occurred.** VERIFIED: zero `adaptive_react`
rows and zero `rebalance` rows, ever. The `count_closed_trades` origin filter
exists to exclude those two and has never excluded anything. INFERRED: the filter
is still correct to keep, since the adaptive layer would produce such rows if
enabled, but the documentation presents as a historical fix what is a precaution.
Note `reconciliation` is excluded too, because the filter admits only
`strategy`, so the gate is not affected.

**`dnn_rl`, 2,100 rows, 2026-06-30 to 2026-07-02 only.** VERIFIED, previously
recorded, confirmed here. Zero source references. `dnn_advisory` begins
2026-07-14.

**`bars.source` = `unknown`, 6,364 rows** (6,342 at 5min, 22 at 1day). VERIFIED.

**`bars.volume_source` = NULL, 23,556 rows.** VERIFIED. Predates the column.

**`entry_decision.first_reject` = empty string, 12 rows.** VERIFIED. UNCERTAIN
what it means: an entered candidate plausibly has no first refusing condition, so
blank may be correct. Not resolved.

Enumerated and fully documented: `bars.timeframe`, `trades.outcome`,
`trades.mode` (paper for all 265 rows, zero live), `events.severity`,
`events.kind`, `council_eval.verdict`, `council_eval_provider.source`
(real 198, error 27), `council_refusal.reason`, `discovery_drop.stage`,
`blocked_trades.reason`, `watchlist.status`, `positions.side`.

---

## TASK 3: WHERE THE TWO DATABASES DISAGREE

They are not two copies of one thing. They share 21 table names and answer
different questions.

| | production | analysis |
|---|---|---|
| bars rows | 167,680 | **28,854,163** |
| distinct symbols | 20 | **19,747** |
| date range | 2025-07-15 .. 2026-07-26 | **2016-01-04** .. 2026-07-24 |
| provenance mix | backfill 149,284, real_feed 10,175, unknown 6,364, synthetic 1,857 | **backfill, 100 percent** |
| shared symbols | **8** | 8 |
| production-only symbols | **12**, all crypto (AAVE/USD, ARB/USD, AVAX/USD, CRV/USD, DOGE/USD, FIL/USD, GRT/USD, LDO/USD and others) | |
| analysis-only tables | | `universe_membership`, `universe_asset`, `universe_exclusion`, `listing_segment`, `corporate_action`, `delisting_event`, `trading_calendar`, `analysis_meta` |

**MATERIAL DISAGREEMENTS.** Production carries `real_feed`, `unknown` and
`synthetic` bars. Analysis carries none of those and is uniformly `backfill`, so
any provenance question answered against analysis returns "all clean" and is
wrong about the engine. Production covers 20 symbols over one year; analysis
covers 19,747 over ten. Twelve production symbols are absent from analysis.

**WHICH STORE IS AUTHORITATIVE FOR WHICH QUESTION.** Analysis is authoritative
for universe membership, corporate actions, listing segments, long-horizon price
history, and anything cross-sectional. Production is authoritative for anything
about what the engine did: factor outputs, trades, entry decisions, council
evaluations, events, provenance, and every gate count. Tables that are empty in
analysis are empty because that store was never a record of engine behaviour, not
because the behaviour did not happen. **A claim about engine behaviour must be
checked against production. A claim about market history or universe must be
checked against analysis.**

---

## TASK 4: DOCUMENTED CLAIMS THE DATA DOES NOT SUPPORT

**1. The `trades.origin` enum is wrong in both directions.** Documented as
`strategy | adaptive_react | rebalance`. Data holds `strategy` and
`reconciliation`. VERIFIED.

**2. `model_registry` is empty.** VERIFIED, 0 rows. CONTEXT.md and PROGRESS.md
describe champion and challenger registry entries, a promotion path that refuses
a challenger without a signed artifact "before touching the registry", and a
recorded `challenger_recorded` outcome. No registry row exists in production.
INFERRED and NOT RESOLVED: either promotion never ran against this database, or
the registry is file-based under `ml_factor/models/`, which I did not verify. The
documentation reads as though the table is populated.

**3. The whale layer is described as an advisory input at a bounded weight.** It
had a weight and no input. VERIFIED above.

**4. `research_thesis` holds 31 theses and every one is `flat`.** VERIFIED. The
long-term sleeve is documented as producing a thesis with a target view and an
invalidation. It has never produced a directional one.

**5. All 10 `positions` rows have `qty = 0`.** VERIFIED. No open position exists.
Consistent with documented rehydration, recorded because a reader could take a
10-row positions table as 10 open positions.

**6. The real-fill gate**, corrected earlier the same day, confirmed here:
`trades.bar_source` is `unknown` 247, `real_feed` 16, `synthetic` 2. Four
`unknown` rows are dated after 2026-07-17, so that bucket is not purely
historical.

**CHECKED AND SUPPORTED:** live trading off (all 265 trades are `paper`, zero
live rows); zero trades carry a council decision id; council provider errors 27
of 225; the discovery funnel narrows A 5,605, B 1,929, C 394 as documented.

---

## TASK 5: ROWS THAT SHOULD NOT EXIST

**108 `watchdog_restart` events on 2026-07-24 in one-second bursts.** VERIFIED:
18 rows share `2026-07-24T07:15:35Z`, 17 share `07:15:21Z`, 15 share
`07:28:20Z`, 15 share `07:16:29Z`. Known test contamination of an append-only
journal, deliberately left in place. Confirmed still present. INFERRED: it would
corrupt any restart-frequency or stability metric computed from `events`.

**3,411 bars with `source = real_feed` and `volume_source = fabricated_zeroed`.**
VERIFIED. A real price beside an admittedly invented volume. Internally
consistent with the documented two-axis provenance, and it will read as
contradictory to anyone who assumes provenance is one axis. It is two.

**CHECKED AND CLEAN:** zero duplicate `(symbol, timeframe, timestamp)` bar rows.
Zero orphaned `council_eval_provider` rows. Zero positions whose symbol has no
trade. `signals` and `model_outputs` agree exactly at 12,967 rows each.

**NOT RESOLVED:** the 12 blank `entry_decision.first_reject` rows, and whether
the empty `model_registry` means promotion never ran or the registry is
file-based. Both are stated as open rather than guessed.

---

## SUMMARY

The one finding that should change a belief is that `whale_signal` generated
2,162 weighted factor outputs with no source data at all. The rest is smaller:
one undocumented enum value, two documented enum values that have never occurred,
an empty registry the documents describe as populated, a research sleeve that has
only ever said flat, and three undocumented empty tables.

The two databases do not contradict each other. They were asked different
questions and one of them has no opinion about engine behaviour. Writing down
which store answers which question is the durable fix for the confusion that
prompted this audit.
