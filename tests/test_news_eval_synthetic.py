"""Pins the synthetic fixtures (STAGE C.1 Task 2): counts, structure, determinism.

Every scenario is built once per module into a temporary directory. The
expected verdicts themselves are checked by the harness tests; this file pins
what the fixtures contain so a generator change cannot move them silently.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import pytest

from news_eval import marker
from news_eval import synthetic as syn

REPO = Path(__file__).resolve().parent.parent

# (total rows, demonstration rows, collection rows by state,
#  collection rows by outcome_state)
PINNED = {
    "S-NULL": (7660, 60, {"excluded_pre_call": 167, "judged": 3664, "model_failed": 94, "no_news": 3521, "source_failed": 154}, {"excluded": 213, "pending": 3701, "resolved": 3686}),
    "S-EFFECT": (7772, 60, {"excluded_pre_call": 197, "judged": 3667, "model_failed": 138, "no_news": 3584, "source_failed": 126}, {"excluded": 240, "pending": 3738, "resolved": 3734}),
    "S-PREMIUM": (7798, 60, {"excluded_pre_call": 178, "judged": 3794, "model_failed": 126, "no_news": 3505, "source_failed": 135}, {"excluded": 245, "pending": 3670, "resolved": 3823}),
    "S-UNANIMOUS": (7785, 60, {"excluded_pre_call": 195, "judged": 3632, "model_failed": 160, "no_news": 3595, "source_failed": 143}, {"excluded": 240, "pending": 3767, "resolved": 3718}),
    "S-REVERSAL": (7761, 60, {"excluded_pre_call": 190, "judged": 3636, "model_failed": 127, "no_news": 3602, "source_failed": 146}, {"excluded": 237, "pending": 3783, "resolved": 3681}),
    "S-HIGHRHO": (7807, 60, {"excluded_pre_call": 175, "judged": 3725, "model_failed": 144, "no_news": 3558, "source_failed": 145}, {"excluded": 212, "pending": 3737, "resolved": 3798}),
    "S-THIN": (5461, 60, {"excluded_pre_call": 119, "judged": 2551, "model_failed": 109, "no_news": 2517, "source_failed": 105}, {"excluded": 154, "pending": 2650, "resolved": 2597}),
    "S-STORY": (7735, 60, {"excluded_pre_call": 174, "judged": 3700, "model_failed": 129, "no_news": 3513, "source_failed": 159}, {"excluded": 217, "pending": 3701, "resolved": 3757}),
    "S-SENS": (7734, 60, {"excluded_pre_call": 208, "judged": 3666, "model_failed": 132, "no_news": 3513, "source_failed": 155}, {"excluded": 245, "pending": 3693, "resolved": 3736}),
    "S-CLUSTER": (7748, 60, {"excluded_pre_call": 167, "judged": 3714, "model_failed": 135, "no_news": 3515, "source_failed": 157}, {"excluded": 208, "pending": 3708, "resolved": 3772}),
    "S-CUTOFF": (7871, 60, {"excluded_pre_call": 171, "judged": 3788, "model_failed": 125, "no_news": 3595, "source_failed": 132}, {"excluded": 214, "pending": 3818, "resolved": 3779}),
}
NAMES = sorted(PINNED)
STATUS_WORDS = {"abstain_floor", "degenerate", "abstain_null_uninformative",
                "clear", "blocked_by_null", "significant_reversal",
                "not_clear"}
E_WORDS = {"abstain_floor", "degenerate", "clear", "below_econ_bar",
           "net_negative", "abstain_interval"}
GROSS_WORDS = {"abstention_floor", "clears_gross", "powered_negative",
               "abstention"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    info = {}
    for name in NAMES:
        t0 = time.perf_counter()
        summary = syn.build(name, out / f"{name}.db")
        info[name] = (out / f"{name}.db", summary, time.perf_counter() - t0)
    return info


def _dump_hash(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()
    finally:
        conn.close()


def _rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_scenario_registry_matches_the_brief():
    assert set(syn.SCENARIOS) == set(PINNED)
    for name, sc in syn.SCENARIOS.items():
        assert sc.name == name and isinstance(sc.seed, int)
        assert "Expected" in sc.description and "Calibration" in sc.description


@pytest.mark.parametrize("name", NAMES)
def test_builds_fast_and_pins_counts(built, name):
    path, summary, seconds = built[name]
    total, demo, by_state, by_outcome = PINNED[name]
    assert seconds < 60
    assert summary["total_rows"] == total
    assert summary["demonstration_rows"] == demo
    assert summary["by_state"] == by_state
    assert summary["by_outcome_state"] == by_outcome
    assert 4000 <= total <= 8000
    assert set(by_state) == set(syn.STATES)


@pytest.mark.parametrize("name", NAMES)
def test_expected_counts_match_the_built_rows(built, name):
    _, summary, _ = built[name]
    ex = syn.SCENARIOS[name].expected
    for key, value in ex["counts"].items():
        assert summary[key] == value, key
    assert summary["s_star"] == ex["s_star"]
    assert summary["excluded_query_dates"] == list(ex["excluded_query_dates"])
    assert summary["null_excess_resolved_judged"] == dict(
        ex["null_excess_resolved_judged"])
    assert summary["stale_pending_sessions"] == list(
        ex.get("stale_pending_sessions", []))
    assert summary["analysis_null_net"] == 0
    if name not in ("S-THIN",):
        assert summary["analysis_scored"] >= 1000


@pytest.mark.parametrize("name", NAMES)
def test_source_failed_day_rule(built, name):
    _, summary, _ = built[name]
    assert len(summary["excluded_query_dates"]) == 1
    assert summary["excluded_day_share"] > 0.20
    assert summary["max_other_day_share"] < 0.15


@pytest.mark.parametrize("name", NAMES)
def test_formations_and_82_symbols(built, name):
    path, summary, _ = built[name]
    assert summary["formations"] == [syn.FORMATION_JULY, syn.FORMATION_OCT]
    rows = _rows(path, "SELECT DISTINCT query_date, formation_date FROM "
                       "news_observation WHERE run_kind='collection'")
    assert all(f == syn.formation_for(q) for q, f in rows)
    symbols = {r[0] for r in _rows(path, "SELECT DISTINCT symbol FROM "
                                         "news_observation")}
    assert set(syn.RULE_A) <= symbols and set(syn.RULE_B) <= symbols
    assert {syn.SECZ_LIKE, syn.FORMATION_ONLY_NA} <= symbols
    flagged = set(summary["flagged_82"])
    want = {f"{s}@{f}" for s in syn.RULE_A + syn.RULE_B
            for f in (syn.FORMATION_JULY, syn.FORMATION_OCT)}
    want.add(f"{syn.FORMATION_ONLY_NA}@{syn.FORMATION_JULY}")
    assert flagged == want
    na_secz = _rows(path, "SELECT COUNT(*) FROM news_observation WHERE "
                          "symbol='SECZ' AND sector='N/A'")[0][0]
    assert na_secz > 0


@pytest.mark.parametrize("name", NAMES)
def test_marker_and_schema(built, name):
    path, _, _ = built[name]
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert marker.is_synthetic(conn)
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                           "AND name='news_observation'").fetchone()[0]
    finally:
        conn.close()
    assert ddl in syn.SCHEMA_PATH.read_text()


@pytest.mark.parametrize("name", NAMES)
def test_build_is_deterministic(built, name, tmp_path):
    path, _, _ = built[name]
    again = tmp_path / f"{name}.db"
    syn.build(name, again)
    assert _dump_hash(path) == _dump_hash(again)


@pytest.mark.parametrize("name", NAMES)
def test_row_shapes_follow_the_collector(built, name):
    path, summary, _ = built[name]
    q = lambda sql: _rows(path, sql)[0][0]  # noqa: E731
    judged = summary["by_state"]["judged"]
    neutral = summary["by_judgment"].get("NEUTRAL", 0)
    assert 0.25 <= neutral / judged <= 0.35
    # net_bp = signed_bp - cost on directional rows, NULL on NEUTRAL
    assert q("SELECT COUNT(*) FROM news_observation WHERE run_kind='collection' "
             "AND judgment='NEUTRAL' AND net_bp IS NOT NULL") == 0
    assert q("SELECT MAX(ABS(net_bp - (CASE judgment WHEN 'POSITIVE' THEN 1 "
             "ELSE -1 END) * excess_1session * 10000 + cost_bp_round_trip)) "
             "FROM news_observation WHERE run_kind='collection' AND "
             "judgment IN ('POSITIVE','NEGATIVE') AND net_bp IS NOT NULL") < 1e-6
    assert q("SELECT MAX(ABS(ret_1session - bench_1session - excess_1session)) "
             "FROM news_observation WHERE excess_1session IS NOT NULL") < 1e-12
    # strengths: 1..5 on directional rows, 1 on NEUTRAL, a few unparsed
    assert q("SELECT COUNT(DISTINCT strength) FROM news_observation WHERE "
             "judgment IN ('POSITIVE','NEGATIVE') AND strength_parse_ok=1") == 5
    assert q("SELECT COUNT(*) FROM news_observation WHERE judgment='NEUTRAL' "
             "AND strength != 1") == 0
    assert q("SELECT COUNT(*) FROM news_observation WHERE strength_parse_ok=0 "
             "AND state='judged' AND strength IS NULL") > 0
    # states carry the collector's strings
    assert {r[0] for r in _rows(path, "SELECT DISTINCT error_class FROM "
            "news_observation WHERE state='excluded_pre_call'")} == set(
        syn.PRE_CALL_CLASSES)
    assert q("SELECT COUNT(*) FROM news_observation WHERE state='excluded_pre_call' "
             "AND (exclusion_reason != error_class OR outcome_state != 'excluded')") == 0
    assert q("SELECT COUNT(*) FROM news_observation WHERE state='model_failed' "
             "AND (judgment IS NOT NULL OR scoring_session IS NULL)") == 0
    assert q("SELECT COUNT(*) FROM news_observation WHERE state IN "
             "('no_news','source_failed') AND outcome_state != 'pending'") == 0
    assert q("SELECT COUNT(*) FROM news_observation WHERE outcome_state='excluded' "
             "AND state='judged' AND exclusion_reason='symbol_did_not_trade'") > 0
    # query_dates span two scoring sessions
    span = _rows(path, "SELECT query_date, COUNT(DISTINCT scoring_session) "
                       "FROM news_observation WHERE state='judged' AND "
                       "run_kind='collection' GROUP BY query_date")
    assert all(n == 2 for _, n in span)
    assert q("SELECT COUNT(*) FROM news_observation WHERE run_kind NOT IN "
             "('collection','demonstration')") == 0


@pytest.mark.parametrize("name", NAMES)
def test_story_share_and_expected_vocabulary(built, name):
    _, summary, _ = built[name]
    ex = syn.SCENARIOS[name].expected
    assert ex["story_trigger"] == (summary["story_shared_share"] > 0.10)
    assert ex["gate"]["status"] in ("PASS", "FAIL")
    assert set(ex["gate"]["failing"]) <= {"C", "M", "REQUIRED"}
    assert (ex["gate"]["status"] == "FAIL") == bool(ex["gate"]["failing"])
    text = (REPO / "EXPERIMENT.md").read_text()
    for reading in ex["readings"].values():
        assert reading["gross"] in GROSS_WORDS
        assert set(reading["statuses"].values()) <= STATUS_WORDS
        assert set(reading["e_statuses"].values()) <= E_WORDS
        for row in reading["rows"]:
            assert f"| {row} |" in text


def test_spec_strings_match_the_collector():
    from news_experiment import spec
    assert syn.RULE_ID == spec.RULE_ID
    assert syn.SPEC_VERSION == spec.SPEC_VERSION
    assert syn.MODEL_ID == spec.MODEL_ID
    assert syn.STATES == spec.STATES
    assert set(syn.PRE_CALL_CLASSES) <= set(spec.ERROR_CLASSES_PRE_CALL)
    assert set(syn.MODEL_FAILED_CLASSES + (syn.EXHAUSTED,)) <= set(
        spec.ERROR_CLASSES_MODEL_FAILED)
    assert syn.DID_NOT_TRADE == spec.EXCLUSION_SYMBOL_DID_NOT_TRADE
    assert (syn.ANCHOR_CLOSE, syn.ANCHOR_OPEN) == (
        spec.ANCHOR_SAME_SESSION_CLOSE, spec.ANCHOR_NEXT_SESSION_OPEN)


def test_calendar_skips_holidays():
    assert syn.SESSIONS[0] == "2026-07-28"
    assert "2026-09-07" not in syn.SESSIONS
    assert "2026-11-26" not in syn.SESSIONS
    assert "2026-09-08" in syn.SESSIONS


def test_refuses_real_database_name_and_foreign_files(tmp_path):
    with pytest.raises(PermissionError):
        syn.build("S-NULL", tmp_path / "news_experiment.db")
    foreign = tmp_path / "foreign.db"
    sqlite3.connect(foreign).close()
    foreign.write_bytes(b"not a synthetic database")
    with pytest.raises(FileExistsError):
        syn.build("S-NULL", foreign)


def test_cli_build_all(tmp_path, capsys):
    assert syn.main(["build-all", "--out", str(tmp_path)]) == 0
    assert sorted(p.stem for p in tmp_path.glob("*.db")) == NAMES
    assert '"S-CUTOFF"' in capsys.readouterr().out
