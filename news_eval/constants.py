"""Every fixed number and label of the Stage C evaluation (STAGE C.1 Task 1).

Each constant cites the EXPERIMENT.md paragraph that fixes it. Nothing here is
tuned, estimated or chosen by the harness: Amendments 5, 6, 8 and 9 and Tasks
5 to 8 fix every value, and Amendment 9 (closing paragraph) states that no bar,
threshold, count or seed moves. tests/test_news_eval_constants.py pins each
value.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ the bars

# Task 5 "The bar" and Amendment 5 "The primary family": |z| >= 2.50,
# Bonferroni 0.05/4; 9.3 makes the clear one-sided (z >= +2.50). The E-tests
# carry the same 2.50 (Amendment 5 "The economic secondary family", 9.10).
BAR_PRIMARY_Z = 2.50
# Task 5 "Secondary tests on strength" (Amendment 3): 0.05 split two ways,
# |z| >= 2.24 on S1 and S2; 9.10 clears at z >= +2.24.
BAR_STRENGTH_Z = 2.24
# Amendment 6 "The permutation null, specified": p <= 0.0125 (0.05/4).
BAR_PERM_P = 0.0125

# ------------------------------------------- null informativeness (Amendment 6)

# Amendment 6 "The skew diagnostic": UNINFORMATIVE when the pooled minority
# directional share falls below 10 percent ...
NULL_MIN_MINORITY_SHARE = 0.10
# ... or fewer than 30 clusters are mixed (at least one POSITIVE and one
# NEGATIVE scored observation). Clusters are scoring_session (9.1, 9.9).
NULL_MIN_MIXED_CLUSTERS = 30

# ------------------------------------------------------------------ the floors

# Task 5 "Required sample size" and Amendment 5: 60 day clusters gate the
# analysis set as a whole (9.2; stop rule 8.4, 9.8).
FLOOR_ANALYSIS_CLUSTERS = 60
# Task 5 "Required sample size": 1,000 scorable observations (8.4, 9.8: M).
FLOOR_SCORABLE = 1000
# 9.2: each primary test needs 30 clusters holding its own scored
# observations; reuses Amendment 5's E-test per-stratum floor of 30. S1 and S2
# need 30 clusters with strength_parse_ok = 1 (9.2).
FLOOR_TEST_CLUSTERS = 30

# ----------------------------------------------------------------- the effects

# Task 5 "Required sample size": assumed effect 30 bp gross; Task 6 powered
# negative (upper bound below 30 bp, 9.5).
EFFECT_BP = 30.0
# Task 6 capacity gate as re-scoped by Amendment 5 and corrected by Amendment 7:
# 2,500 / (2,520 x 2,000) = 4.96 bp; 9.10 E-test clear needs T >= 4.96 bp.
ECON_BAR_BP = 4.96

# ------------------------------------------------------------------ the counts

# 9.5 (Amendment 5 estimator): 10,000 bootstrap draws.
N_BOOT = 10_000
# 9.9 and Amendment 6: 10,000 permutations.
N_PERM = 10_000
# 9.8 and Task 5 "Required sample size": (2.50 + 0.84)^2 = 11.1556 -> 11.156.
REQUIRED_FACTOR = 11.156
# Task 5 "Required sample size": z_beta for 80 percent power.
Z_BETA = 0.84

# ---------------------------------------------------------- diagnostics, rules

# Task 5 "The scored quantity": a NEUTRAL rate above 80 percent is a
# reportable failure of the design.
NEUTRAL_RATE_BAR = 0.80
# Task 5 "The clustering unit" and 9.10: above 10 percent of scored
# observations sharing a story_group_id, P1 to P4 re-run on story groups.
STORY_TRIGGER_SHARE = 0.10
# Task 7 "How absence is visible" and 9.1: a query_date whose source_failed
# share EXCEEDS 20 percent leaves the analysis set (strictly greater than).
SOURCE_FAILED_DAY_EXCLUDE = 0.20
# 9.7: a pending row more than 3 sessions before the latest resolved session
# is stale and does not hold S* back.
STALE_PENDING_SESSIONS = 3
# 9.4: signed_bp = +/-10,000 x excess_1session; 9.8 sigma is of 10,000 x excess.
BP_PER_UNIT = 10_000.0

# ------------------------------------------------------------------- the seeds

# 9.11 seeds.
BOOT_SEED = 20261010
PERM_SEED = 20261011
RELEVANCE_SEED = 20261012

# 9.11 stream order: P1, P2, P3, P4, E1 to E4, S1, S2, each primary reading
# first and the 8.2 sensitivity reading second. Indices 0 to 19.
_REGISTERED_TESTS = ("P1", "P2", "P3", "P4", "E1", "E2", "E3", "E4",
                     "S1", "S2")
STREAM_ORDER: tuple[tuple[str, str], ...] = tuple(
    (test, reading) for test in _REGISTERED_TESTS
    for reading in ("primary", "sensitivity"))
# The 9.10 story-group re-run of P1 to P4 also needs streams. 9.11 does not
# list it, so (lead choice, STAGE C.1) its pairs are APPENDED after index 19:
# appending never moves a registered index. Indices 20 to 27.
STREAM_ORDER_STORY: tuple[tuple[str, str], ...] = tuple(
    (test, reading) for test in ("P1", "P2", "P3", "P4")
    for reading in ("primary_story", "sensitivity_story"))
N_STREAMS = len(STREAM_ORDER) + len(STREAM_ORDER_STORY)  # 28
# Children come from numpy.random.SeedSequence(seed).spawn(N_STREAMS) on a
# FRESH SeedSequence. Child i has spawn_key (i,), so the registered 20 children
# are identical whether 20 or 28 are spawned (pinned in the constants test).


def stream_index(test: str, reading: str) -> int:
    """Index of a (test, reading) pair in STREAM_ORDER + STREAM_ORDER_STORY (9.11)."""
    try:
        return (STREAM_ORDER + STREAM_ORDER_STORY).index((test, reading))
    except ValueError:
        raise KeyError(f"no 9.11 stream for ({test!r}, {reading!r})") from None


# --------------------------------------------- 8.2 sensitivity exclusion rule

# 8.2(a): any symbol containing "." plus the four Strategy Inc. preferreds.
SENS_RULE_A_CHAR = "."
SENS_RULE_A_SYMBOLS = ("STRK", "STRF", "STRD", "STRC")
# 8.2(b): modal non-null sector per symbol per formation is "N/A" with
# sector_source = finnhub_profile2.
SENS_RULE_B_SECTOR = "N/A"
SENS_RULE_B_SOURCE = "finnhub_profile2"

# ------------------------------------------------------------------ the strata

# Task 5 thin-end test (P3) is S3 and S4; Amendment 5 E1 to E4, one per stratum.
STRATA = ("S1", "S2", "S3", "S4")
THIN_END = ("S3", "S4")
E_TEST_STRATUM = {"E1": "S1", "E2": "S2", "E3": "S3", "E4": "S4"}
# Task 5 S2 "TOP AGAINST BOTTOM": strengths {4, 5} minus {1, 2}; 3 excluded.
S2_TOP = (4, 5)
S2_BOTTOM = (1, 2)
# 9.10 sector robustness: N/A and null pool into one cluster named so.
SECTOR_UNCLASSIFIED = "unclassified"

# ------------------------------------------------------- 8.3 relevance draw

# 9.13: 200 rows, uniform without replacement, RELEVANCE_SEED, judged
# collection rows with query_date at or before 2026-10-09, six columns only
# (C.1 GUARDRAILS read 3).
RELEVANCE_N = 200
RELEVANCE_QUERY_DATE_MAX = "2026-10-09"
RELEVANCE_COLUMNS = ("id", "symbol", "query_date", "headline", "sector",
                     "stratum")

# ------------------------------------- C.2 run files (9.15; C.1 rulings B2, S7)

# Execution settings, not statistical ones: no bar, threshold or seed. The
# unlock file reports/c2_UNLOCK.json is a JSON object with UNLOCK_FIELDS
# (C.1 lead ruling B2). news_eval.data checks the first five (schema, stage,
# a non-empty approver, a UTC time ending Z, and the sha256 of EXPERIMENT.md
# on disk); news_eval.gate and news_eval.run_c2 also bind manifest_sha256 to
# the manifest they verified.
UNLOCK_SCHEMA = "c2_unlock/1"
UNLOCK_STAGE = "C.2"
UNLOCK_FIELDS = ("schema", "stage", "approver", "utc_time",
                 "experiment_sha256", "manifest_sha256")
# The run-once marker reports/c2_RUN_ONCE.json (9.15; ruling B2): its schema,
# and its snapshot_sha256 must equal the sha256 of the file VERDICT opens.
RUN_ONCE_SCHEMA = "c2_run_once/1"
# Ruling S7: run_c2 refuses, with nothing written, unless /proc/meminfo
# MemAvailable is at least this many MB just before the marker.
MIN_MEM_AVAILABLE_MB = 2048

# ------------------------------------------------------------- labels (Task 7)

# Task 3 / Task 5 judgments (news_experiment/spec.py JUDGMENTS).
POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"
NEUTRAL = "NEUTRAL"
DIRECTIONAL = (POSITIVE, NEGATIVE)
# Task 7 "The rule": the five states (Amendment 4 added excluded_pre_call).
STATE_NO_NEWS = "no_news"
STATE_JUDGED = "judged"
STATE_MODEL_FAILED = "model_failed"
STATE_EXCLUDED_PRE_CALL = "excluded_pre_call"
STATE_SOURCE_FAILED = "source_failed"
STATES = (STATE_NO_NEWS, STATE_JUDGED, STATE_MODEL_FAILED,
          STATE_EXCLUDED_PRE_CALL, STATE_SOURCE_FAILED)
# Task 8 "Provenance of the record itself"; 9.7 scorable run_kind.
RUN_KIND_COLLECTION = "collection"
# Task 8 "Prices and outcome"; 9.7 scorable outcome_state and S* pending rows.
OUTCOME_RESOLVED = "resolved"
OUTCOME_PENDING = "pending"
# news_experiment/collect.py writes this for rows priced out before scoring.
OUTCOME_EXCLUDED = "excluded"
# 9.7 scorable: exclusion_reason = '' (news_experiment/spec.py EXCLUSION_NONE).
EXCLUSION_NONE = ""

# ------------------------------------------------- the columns (Task 8, 9.15)

# news_eval/schema.sql column order (PRAGMA table_info of the real database,
# Task 8). The constants test checks this tuple against schema.sql.
SCHEMA_COLUMNS = (
    "id", "rule_id", "formation_date", "symbol", "adv_usd_at_formation",
    "liquidity_rank", "stratum", "median_close_at_formation",
    "price_floor_at_formation", "sector", "sector_source", "query_date",
    "state", "exclusion_reason", "headline", "source_name",
    "source_article_id", "published_ts", "fetched_ts", "story_group_id",
    "model_id", "prompt_sha256", "temperature", "called_ts", "latency_ms",
    "raw_response", "judgment", "strength", "strength_parse_ok",
    "neutral_strength_anomaly", "reason", "parse_ok", "error_class",
    "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd",
    "credential_shared", "etb", "shortable", "etb_source", "anchor_kind",
    "anchor_ts", "anchor_price", "scoring_session", "delay_rolled",
    "outcome_state", "ret_intraday", "ret_1session", "ret_2session",
    "ret_5session", "ret_10session", "bench_1session", "excess_1session",
    "bar_source", "cost_bp_round_trip", "net_bp", "spec_version",
    "collector_git_sha", "run_kind", "written_ts",
)

# Outcome columns (STAGE C.1 SCOPE; Amendment 9 "When and what data existed"):
# never readable outside GATE (its allow-list) or VERDICT. The tuple is every
# schema column OUTCOME_COLUMN_RE matches, in schema order (pinned by test).
OUTCOME_COLUMN_RE = re.compile(
    r"\b(ret_\w+|bench_\w+|anchor_\w+|excess_\w+|net_bp|cost_bp_round_trip"
    r"|outcome_state)\b")
OUTCOME_COLUMNS = (
    "anchor_kind", "anchor_ts", "anchor_price", "outcome_state",
    "ret_intraday", "ret_1session", "ret_2session", "ret_5session",
    "ret_10session", "bench_1session", "excess_1session",
    "cost_bp_round_trip", "net_bp",
)
# Blind columns (C.1 GUARDRAILS; 9.8 "No row-level judgment, strength or
# reason"): never readable from a non-synthetic database outside GATE (which
# allows scoring_session only, and judgment only inside one COUNT) or VERDICT.
BLIND_COLUMN_RE = re.compile(r"\b(scoring_session|judgment|strength|reason)\b")
BLIND_COLUMNS = ("scoring_session", "judgment", "strength", "reason")
# Added by the Task 1 author, beyond the brief, so a text or AST guard can
# catch them too. raw_response holds the model's full answer (judgment,
# strength, reason); neutral_strength_anomaly and strength_parse_ok are
# derived from judgment and strength. bar_source and delay_rolled were on the
# B.2 blind-interim script's forbidden list (outcome provenance, horizon).
# No loader phase except SYNTHETIC and VERDICT can read any of them.
JUDGMENT_DERIVED_COLUMNS = ("raw_response", "strength_parse_ok",
                            "neutral_strength_anomaly")
OUTCOME_ADJACENT_COLUMNS = ("delay_rolled", "bar_source")
GUARDED_COLUMNS = (OUTCOME_COLUMNS + BLIND_COLUMNS + JUDGMENT_DERIVED_COLUMNS
                   + OUTCOME_ADJACENT_COLUMNS)
GUARDED_COLUMN_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in GUARDED_COLUMNS) + r")\b")
