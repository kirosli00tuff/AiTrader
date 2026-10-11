"""Pins every Stage C constant (STAGE C.1 Task 1; news_eval/constants.py).

A changed value here is a changed pre-registration: each one is fixed by the
EXPERIMENT.md paragraph its comment in constants.py cites.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from news_eval import constants as K

SCHEMA_SQL = Path(K.__file__).with_name("schema.sql")


def test_bars_pinned():
    assert K.BAR_PRIMARY_Z == 2.50
    assert K.BAR_STRENGTH_Z == 2.24
    assert K.BAR_PERM_P == 0.0125


def test_null_thresholds_pinned():
    assert K.NULL_MIN_MINORITY_SHARE == 0.10
    assert K.NULL_MIN_MIXED_CLUSTERS == 30


def test_floors_pinned():
    assert K.FLOOR_ANALYSIS_CLUSTERS == 60
    assert K.FLOOR_SCORABLE == 1000
    assert K.FLOOR_TEST_CLUSTERS == 30


def test_effects_pinned():
    assert K.EFFECT_BP == 30.0
    assert K.ECON_BAR_BP == 4.96


def test_counts_pinned():
    assert K.N_BOOT == 10_000
    assert K.N_PERM == 10_000
    assert K.REQUIRED_FACTOR == 11.156
    assert K.Z_BETA == 0.84


def test_required_factor_is_task5_arithmetic():
    assert round((K.BAR_PRIMARY_Z + K.Z_BETA) ** 2, 3) == K.REQUIRED_FACTOR


def test_diagnostics_and_rules_pinned():
    assert K.NEUTRAL_RATE_BAR == 0.80
    assert K.STORY_TRIGGER_SHARE == 0.10
    assert K.SOURCE_FAILED_DAY_EXCLUDE == 0.20
    assert K.STALE_PENDING_SESSIONS == 3
    assert K.BP_PER_UNIT == 10_000.0


def test_seeds_pinned():
    assert K.BOOT_SEED == 20261010
    assert K.PERM_SEED == 20261011
    assert K.RELEVANCE_SEED == 20261012


def test_stream_order_is_9_11_order():
    expected = []
    for test in ("P1", "P2", "P3", "P4", "E1", "E2", "E3", "E4", "S1", "S2"):
        expected += [(test, "primary"), (test, "sensitivity")]
    assert K.STREAM_ORDER == tuple(expected)
    assert len(K.STREAM_ORDER) == 20
    assert K.STREAM_ORDER[0] == ("P1", "primary")
    assert K.STREAM_ORDER[1] == ("P1", "sensitivity")
    assert K.STREAM_ORDER[19] == ("S2", "sensitivity")


def test_story_streams_appended_after_registered():
    expected = []
    for test in ("P1", "P2", "P3", "P4"):
        expected += [(test, "primary_story"), (test, "sensitivity_story")]
    assert K.STREAM_ORDER_STORY == tuple(expected)
    assert K.N_STREAMS == 28
    assert K.stream_index("P1", "primary_story") == 20
    assert K.stream_index("P4", "sensitivity_story") == 27
    all_pairs = K.STREAM_ORDER + K.STREAM_ORDER_STORY
    assert len(set(all_pairs)) == len(all_pairs) == 28
    for i, (test, reading) in enumerate(all_pairs):
        assert K.stream_index(test, reading) == i


def test_stream_index_registered_examples_and_unknown():
    assert K.stream_index("P1", "primary") == 0
    assert K.stream_index("P2", "primary") == 2
    assert K.stream_index("E1", "primary") == 8
    assert K.stream_index("S2", "sensitivity") == 19
    with pytest.raises(KeyError):
        K.stream_index("P5", "primary")
    with pytest.raises(KeyError):
        K.stream_index("E1", "primary_story")


@pytest.mark.parametrize("seed", [K.BOOT_SEED, K.PERM_SEED, K.RELEVANCE_SEED])
def test_registered_children_identical_under_spawn_20_and_28(seed):
    twenty = np.random.SeedSequence(seed).spawn(20)
    all_children = np.random.SeedSequence(seed).spawn(K.N_STREAMS)
    for i in range(20):
        assert twenty[i].spawn_key == all_children[i].spawn_key == (i,)
        assert np.array_equal(twenty[i].generate_state(8),
                              all_children[i].generate_state(8))
        assert np.array_equal(
            np.random.default_rng(twenty[i]).random(5),
            np.random.default_rng(all_children[i]).random(5))


def test_sensitivity_rule_pinned():
    assert K.SENS_RULE_A_CHAR == "."
    assert K.SENS_RULE_A_SYMBOLS == ("STRK", "STRF", "STRD", "STRC")
    assert K.SENS_RULE_B_SECTOR == "N/A"
    assert K.SENS_RULE_B_SOURCE == "finnhub_profile2"


def test_strata_pinned():
    assert K.STRATA == ("S1", "S2", "S3", "S4")
    assert K.THIN_END == ("S3", "S4")
    assert K.E_TEST_STRATUM == {"E1": "S1", "E2": "S2", "E3": "S3",
                                "E4": "S4"}
    assert K.S2_TOP == (4, 5)
    assert K.S2_BOTTOM == (1, 2)
    assert K.SECTOR_UNCLASSIFIED == "unclassified"


def test_relevance_pinned():
    assert K.RELEVANCE_N == 200
    assert K.RELEVANCE_QUERY_DATE_MAX == "2026-10-09"
    assert K.RELEVANCE_COLUMNS == ("id", "symbol", "query_date", "headline",
                                   "sector", "stratum")


def test_c2_run_file_settings_pinned():
    # C.1 lead rulings B2 and S7: execution settings, not statistical ones.
    assert K.UNLOCK_SCHEMA == "c2_unlock/1"
    assert K.UNLOCK_STAGE == "C.2"
    assert K.UNLOCK_FIELDS == ("schema", "stage", "approver", "utc_time",
                               "experiment_sha256", "manifest_sha256")
    assert K.RUN_ONCE_SCHEMA == "c2_run_once/1"
    assert K.MIN_MEM_AVAILABLE_MB == 2048


def test_labels_pinned():
    assert (K.POSITIVE, K.NEGATIVE, K.NEUTRAL) == (
        "POSITIVE", "NEGATIVE", "NEUTRAL")
    assert K.DIRECTIONAL == ("POSITIVE", "NEGATIVE")
    assert K.STATES == ("no_news", "judged", "model_failed",
                        "excluded_pre_call", "source_failed")
    assert K.STATE_JUDGED == "judged"
    assert K.STATE_SOURCE_FAILED == "source_failed"
    assert K.RUN_KIND_COLLECTION == "collection"
    assert K.OUTCOME_RESOLVED == "resolved"
    assert K.OUTCOME_PENDING == "pending"
    assert K.OUTCOME_EXCLUDED == "excluded"
    assert K.EXCLUSION_NONE == ""


def _schema_sql_columns() -> tuple[str, ...]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA_SQL.read_text())
        return tuple(r[1] for r in conn.execute(
            "PRAGMA table_info(news_observation)"))
    finally:
        conn.close()


def test_schema_columns_match_schema_sql():
    assert K.SCHEMA_COLUMNS == _schema_sql_columns()
    assert len(K.SCHEMA_COLUMNS) == 61


def test_outcome_columns_derive_from_schema_and_regex():
    derived = tuple(c for c in K.SCHEMA_COLUMNS
                    if K.OUTCOME_COLUMN_RE.fullmatch(c))
    assert K.OUTCOME_COLUMNS == derived
    for col in ("excess_1session", "net_bp", "cost_bp_round_trip",
                "outcome_state", "ret_1session", "bench_1session",
                "anchor_price"):
        assert col in K.OUTCOME_COLUMNS


def test_blind_columns_derive_from_schema_and_regex():
    derived = tuple(c for c in K.SCHEMA_COLUMNS
                    if K.BLIND_COLUMN_RE.fullmatch(c))
    assert set(derived) == set(K.BLIND_COLUMNS)
    assert K.BLIND_COLUMNS == ("scoring_session", "judgment", "strength",
                               "reason")
    # The regex must not fire inside longer names.
    assert not K.BLIND_COLUMN_RE.search("strength_parse_ok")
    assert not K.BLIND_COLUMN_RE.search("exclusion_reason")


def test_guarded_columns_cover_and_exist():
    schema = set(K.SCHEMA_COLUMNS)
    assert set(K.GUARDED_COLUMNS) <= schema
    assert set(K.OUTCOME_COLUMNS) | set(K.BLIND_COLUMNS) \
        <= set(K.GUARDED_COLUMNS)
    for col in K.GUARDED_COLUMNS:
        assert K.GUARDED_COLUMN_RE.fullmatch(col)
    assert not set(K.RELEVANCE_COLUMNS) & set(K.GUARDED_COLUMNS)
    assert set(K.RELEVANCE_COLUMNS) <= schema


def test_constants_agree_with_collector_spec():
    spec = pytest.importorskip("news_experiment.spec")
    assert K.STATES == spec.STATES
    assert (K.POSITIVE, K.NEGATIVE, K.NEUTRAL) == spec.JUDGMENTS
    assert K.NEUTRAL_RATE_BAR == spec.NEUTRAL_RATE_REPORTABLE_FAILURE
    assert K.SOURCE_FAILED_DAY_EXCLUDE \
        == spec.SOURCE_FAILED_DAY_EXCLUDE_FRACTION
    assert K.STRATA == tuple(s[0] for s in spec.STRATA)
    assert K.EXCLUSION_NONE == spec.EXCLUSION_NONE
