"""news_eval.family: the analysis set (9.1, 9.7, D1, D16, D18, D25), the 8.2
sensitivity set (D9), the halves (9.6, D17), the story trigger (9.10, D11),
the Amendment 6 diagnostics (D20), the tests' plumbing, and determinism.

Every database is a hand-built synthetic file in tmp_path (schema.sql plus
marker.write_marker). The repository's real database is never opened: an
autouse fixture makes sqlite3.connect refuse it, and data.REAL_DB_PATH points
at a fake. Unit tests run with few draws through K.N_BOOT and K.N_PERM; one
test runs compute() at the registered 10,000 on a tiny database."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from news_eval import constants as K
from news_eval import data
from news_eval import envcheck
from news_eval import family as F
from news_eval import marker
from news_eval import verdict as V

REPO = Path(__file__).resolve().parent.parent
REPO_REAL_DB = os.path.realpath(REPO / "news_experiment.db")
SCHEMA_SQL = (REPO / "news_eval" / "schema.sql").read_text()
_UNPATCHED_CONNECT = sqlite3.connect
POS, NEG, NEU = K.POSITIVE, K.NEGATIVE, K.NEUTRAL
JULY, OCT = "2026-07-01", "2026-10-01"


class RealDatabaseOpened(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _never_the_repo_real_db(monkeypatch, tmp_path):
    def guarded(database, *args, **kwargs):
        text = os.fspath(database) if not isinstance(database, int) else ""
        if text.startswith("file:"):
            text = text[5:].split("?", 1)[0]
        if text and text != ":memory:" and os.path.realpath(text) == REPO_REAL_DB:
            raise RealDatabaseOpened(f"test opened the real database: {database}")
        return _UNPATCHED_CONNECT(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", guarded)
    fake = tmp_path / "fake_repo" / "news_experiment.db"
    monkeypatch.setattr(data, "REAL_DB_PATH", str(fake))
    monkeypatch.setattr(data, "UNLOCK_PATH", str(tmp_path / "fake_repo" / "unlock.json"))
    monkeypatch.setattr(data, "RUN_ONCE_PATH", str(tmp_path / "fake_repo" / "once.json"))


@pytest.fixture()
def few_draws(monkeypatch):
    monkeypatch.setattr(K, "N_BOOT", 199)
    monkeypatch.setattr(K, "N_PERM", 199)


# ------------------------------------------------------------------ builders

def sessions(n: int, start: date = date(2026, 8, 3)) -> list[str]:
    """n distinct ISO dates, one per calendar day."""
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


_BASE = {
    "rule_id": "r", "formation_date": JULY, "symbol": "AAA", "stratum": "S1",
    "sector": "Technology", "sector_source": "finnhub_profile2",
    "state": K.STATE_JUDGED, "exclusion_reason": "", "headline": "h",
    "spec_version": "v", "written_ts": "w", "run_kind": K.RUN_KIND_COLLECTION,
    "outcome_state": K.OUTCOME_RESOLVED, "strength": 3, "strength_parse_ok": 1,
}


def row(rid: int, session: str | None, label: str | None = POS,
        excess: float | None = 0.001, **kw) -> dict:
    """A judged resolved collection row; query_date defaults to the session."""
    out = {**_BASE, "id": rid, "scoring_session": session,
           "query_date": kw.pop("query_date", session or "2026-08-01"),
           "judgment": label, "excess_1session": excess,
           "net_bp": kw.pop("net_bp", 1.0)}
    out.update(kw)
    return out


def failed(rid: int, query_date: str, **kw) -> dict:
    """A source_failed collection row (never resolves, no session)."""
    out = {**_BASE, "id": rid, "state": K.STATE_SOURCE_FAILED,
           "query_date": query_date, "scoring_session": None,
           "outcome_state": K.OUTCOME_PENDING, "judgment": None,
           "strength": None, "strength_parse_ok": None,
           "excess_1session": None, "net_bp": None}
    out.update(kw)
    return out


def make_db(path: Path, rows: list[dict], stamp: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _UNPATCHED_CONNECT(path)
    try:
        conn.executescript(SCHEMA_SQL)
        for r in rows:
            conn.execute(f"INSERT INTO news_observation ({', '.join(r)}) VALUES "
                         f"({', '.join('?' * len(r))})", tuple(r.values()))
        conn.commit()
        if stamp:
            marker.write_marker(conn, "family-test", 1)
    finally:
        conn.close()
    return path


def grid(n_sessions: int, *, start_id: int = 1, effect_bp: float = 0.0,
         strata=("S1", "S2", "S3", "S4"), symbols_per_stratum: int = 2,
         seed: int = 5, neutral_every: int = 4) -> list[dict]:
    """A balanced directional grid: per session, per stratum, a few rows."""
    rng = np.random.default_rng(seed)
    out, rid = [], start_id
    for i, s in enumerate(sessions(n_sessions)):
        for st in strata:
            for k in range(symbols_per_stratum):
                lab = POS if (i + k) % 2 == 0 else NEG
                if (rid % neutral_every) == 0:
                    lab = NEU
                sign = 1 if lab == POS else -1
                ex = (sign * effect_bp + rng.normal(0, 50)) / K.BP_PER_UNIT
                out.append(row(rid, s, lab, ex, symbol=f"{st}X{k}", stratum=st,
                               strength=int(rng.integers(1, 6)),
                               net_bp=sign * ex * K.BP_PER_UNIT - 10.0))
                rid += 1
    return out


def analysis_of(db: Path) -> F.AnalysisSet:
    return F.build_analysis(F.load_inputs(db))


# ------------------------------------------------- 9.7 analysis-set membership

def membership_rows() -> tuple[list[dict], dict]:
    s = sessions(10)
    rows, ids = [], {}
    rid = 1

    def add(r, tag=None):
        nonlocal rid
        rows.append(r)
        if tag:
            ids.setdefault(tag, set()).add(r["id"])
        rid += 1

    for i, sess in enumerate(s):
        add(row(rid, sess, POS), "pos")
        add(row(rid, sess, NEG), "neg")
        add(row(rid, sess, NEU), "neu")
    # day rule (9.1, D18): s[2] carries 2 source_failed of 5 rows (0.40)
    add(failed(rid, s[2]))
    add(failed(rid, s[2]))
    # s[3] carries 1 source_failed of 5 rows (exactly 0.20: kept)
    add(failed(rid, s[3]))
    add(row(rid, None, None, None, query_date=s[3], state=K.STATE_NO_NEWS,
            outcome_state=K.OUTCOME_PENDING))
    # a non-stale pending judged row at s[8]: S* = s[7]
    add(row(rid, s[8], POS, None, outcome_state=K.OUTCOME_PENDING), "pending")
    # a stale pending row at s[1] (9 - 1 > 3): counted, holds nothing back
    add(row(rid, s[1], POS, None, outcome_state=K.OUTCOME_PENDING), "stale")
    # a pending row with an empty session: counted, holds nothing back
    add(row(rid, "", POS, None, query_date=s[4],
            outcome_state=K.OUTCOME_PENDING), "empty")
    # resolved directional with NULL excess (D25)
    add(row(rid, s[5], POS, None), "null_excess")
    # scored directional with NULL net_bp (kept, counted)
    add(row(rid, s[6], NEG, -0.002, net_bp=None), "null_net")
    # outcome excluded, exclusion_reason set
    add(row(rid, s[4], POS, outcome_state=K.OUTCOME_EXCLUDED), "excluded")
    add(row(rid, s[4], POS, exclusion_reason="duplicate_headline"), "reason")
    # demonstration rows every phase ignores: source_failed that would push
    # s[4] over 0.20, a pending row that would hold S* at s[5], a large row
    for _ in range(5):
        add(failed(rid, s[4], run_kind="demonstration"))
    add(row(rid, s[5], POS, None, outcome_state=K.OUTCOME_PENDING,
            run_kind="demonstration"), "demo")
    add(row(rid, s[6], POS, 0.5, run_kind="demonstration"), "demo")
    return rows, ids


def test_analysis_set_membership(tmp_path):
    rows, ids = membership_rows()
    s = sessions(10)
    a = analysis_of(make_db(tmp_path / "m.db", rows))
    by_id = {r["id"]: r for r in rows}

    assert a.excluded_query_dates == (s[2],)
    assert a.day_shares[s[3]] == 0.20
    assert a.s_star.s_star == s[7]
    assert a.s_star.stale_pending == ((s[1], 1),)
    assert a.s_star.empty_session_pending == 1

    expected_scored = {i for i in ids["pos"] | ids["neg"] | ids["null_net"]
                       if by_id[i]["scoring_session"] not in (s[2], s[8], s[9])}
    assert {r["id"] for r in a.scored} == expected_scored
    expected_gate = expected_scored | {
        i for i in ids["neu"]
        if by_id[i]["scoring_session"] not in (s[2], s[8], s[9])}
    assert {r["id"] for r in a.gate_rows} == expected_gate
    for tag in ("pending", "stale", "empty", "null_excess", "excluded",
                "reason", "demo"):
        assert not ids[tag] & {r["id"] for r in a.gate_rows}, tag

    f = a.funnel
    drop = f["dropped_first_reason"]
    assert drop[F.DROP_PENDING] == 3
    assert f["pending"] == {"stale": 1, "not_stale": 1, "empty_session": 1}
    assert drop[F.DROP_OUTCOME_OTHER] == 1
    assert f["outcome_other_by_state"] == {K.OUTCOME_EXCLUDED: 1}
    assert drop[F.DROP_EXCLUSION] == 1
    assert drop[F.DROP_DAY_RULE] == 3
    assert drop[F.DROP_BEYOND_S_STAR] == 6
    assert drop[F.DROP_EXCESS_NULL] == 1
    assert drop[F.DROP_RUN_KIND] == 0 and drop[F.DROP_STATE] == 0
    assert f["scored"] == len(expected_scored)
    assert f["scored_net_bp_null"] == 1
    assert f["judged_beyond_s_star_any_outcome"] == 7   # incl. the pending one
    assert f["gate_rows_by_judgment"][NEU] == 7


def test_null_excess_and_null_net_are_counted_not_zeroed(tmp_path, few_draws):
    s = sessions(3)
    rows = [row(1, s[0], POS, 0.001, net_bp=5.0, stratum="S1"),
            row(2, s[1], NEG, -0.002, net_bp=None, stratum="S1"),
            row(3, s[2], POS, None, stratum="S1"),
            row(4, s[2], NEG, -0.001, net_bp=7.0, stratum="S1")]
    res = F.compute(make_db(tmp_path / "n.db", rows))
    e1 = res["readings"]["primary"]["tests"]["E1"]
    assert (e1["n_scored"], e1["n_net_bp_null"], e1["n_obs"]) == (3, 1, 2)
    assert res["analysis_set"]["funnel"]["dropped_first_reason"][
        F.DROP_EXCESS_NULL] == 1
    p1 = res["readings"]["primary"]["tests"]["P1"]["bootstrap"]
    assert p1["n_obs"] == 3
    assert p1["statistic"] == pytest.approx((10.0 + 20.0 + 10.0) / 3)
    assert res["readings"]["primary"]["tests"]["E1"]["bootstrap"]["statistic"] \
        == pytest.approx(6.0)


def test_pending_seam_changes_the_set(tmp_path, monkeypatch):
    s = sessions(6)
    rows = [row(i + 1, s[i], POS) for i in range(6)]
    # a stale pending row (5 - 1 > 3) carrying an excess: S* is not held
    rows.append(row(7, s[1], POS, 0.001, outcome_state=K.OUTCOME_PENDING))
    db = make_db(tmp_path / "p.db", rows)
    assert analysis_of(db).s_star.s_star == s[5]
    assert analysis_of(db).funnel["pending"]["stale"] == 1
    assert len(analysis_of(db).scored) == 6

    original = F.scorable_filter

    def pending_as_resolved(excluded, s_star):
        inner = original(excluded, s_star)
        return lambda r: inner({**r, "outcome_state": K.OUTCOME_RESOLVED})

    monkeypatch.setattr(F, "scorable_filter", pending_as_resolved)
    assert len(analysis_of(db).scored) == 7


def test_day_exclusion_seam(tmp_path, monkeypatch):
    s = sessions(2)
    rows = [row(1, s[0]), row(2, s[1]), failed(3, s[1]), failed(4, s[1])]
    db = make_db(tmp_path / "d.db", rows)
    assert {r["id"] for r in analysis_of(db).scored} == {1}
    monkeypatch.setattr(F, "day_exclusion", lambda counts: ((), {}))
    assert {r["id"] for r in analysis_of(db).scored} == {1, 2}


def test_no_resolved_session_gives_an_empty_set(tmp_path, few_draws):
    s = sessions(2)
    rows = [row(1, s[0], POS, None, outcome_state=K.OUTCOME_PENDING),
            row(2, s[1], NEG, None, outcome_state=K.OUTCOME_PENDING)]
    res = F.compute(make_db(tmp_path / "e.db", rows))
    assert res["analysis_set"]["cutoff"]["s_star"] is None
    p = res["readings"]["primary"]
    assert (p["D"], p["M"]) == (0, 0)
    assert p["tests"]["P1"]["bootstrap"]["status"] == "degenerate"
    d = V.decide(res)
    assert d["readings"]["primary"]["gross"]["gross_reading"] \
        == V.GROSS_ABSTENTION_FLOOR


# ------------------------------------------------------------ 8.2 rules, D9

def srow(symbol, formation, sector, source="finnhub_profile2",
         run_kind=K.RUN_KIND_COLLECTION):
    return {"symbol": symbol, "formation_date": formation, "sector": sector,
            "sector_source": source, "run_kind": run_kind}


def test_sensitivity_rules_a_and_b_per_formation():
    rows = (
        [srow("BAC.PRL", JULY, "Financial Services")] * 3
        + [srow("BAC.PRL", OCT, "Financial Services")]
        + [srow("STRK", OCT, "Technology")]
        + [srow("STRX", OCT, "Technology")]                     # not listed
        # SECZ-like: 71 Financial Services, 2 N/A -> not excluded
        + [srow("SECZ", JULY, "Financial Services")] * 71
        + [srow("SECZ", JULY, "N/A")] * 2
        # GLQ: modal N/A in July only -> excluded in July only
        + [srow("GLQ", JULY, "N/A")] * 3 + [srow("GLQ", JULY, None)] * 9
        + [srow("GLQ", OCT, "Financial Services")] * 3
        + [srow("GLQ", OCT, "N/A")] * 2
        # a tie in the sector mode goes toward N/A
        + [srow("TIE", JULY, "N/A")] * 2 + [srow("TIE", JULY, "Banking")] * 2
        # N/A modal but the source is another provider -> not excluded
        + [srow("OTH", JULY, "N/A", "manual")] * 3
        # a tie in the source mode goes toward finnhub_profile2
        + [srow("SRC", JULY, "N/A", "manual"), srow("SRC", JULY, "N/A")]
        # null sources are not counted in the source mode
        + [srow("NUL", JULY, "N/A", None)] * 4 + [srow("NUL", JULY, "N/A")]
        # all-null sector -> no modal sector -> not excluded
        + [srow("NOS", JULY, None)] * 2
        # demonstration rows are not collection rows
        + [srow("DEM", JULY, "N/A", run_kind="demonstration")] * 3
    )
    flags = F.flag_sensitivity_pairs(rows)
    assert flags == {
        ("BAC.PRL", JULY): ("a",), ("BAC.PRL", OCT): ("a",),
        ("STRK", OCT): ("a",), ("GLQ", JULY): ("b",), ("TIE", JULY): ("b",),
        ("SRC", JULY): ("b",), ("NUL", JULY): ("b",),
    }


def test_rule_a_and_b_can_both_flag_a_pair():
    rows = [srow("BF.A", JULY, "N/A")] * 2
    assert F.flag_sensitivity_pairs(rows) == {("BF.A", JULY): ("a", "b")}


def test_sensitivity_set_removes_the_flagged_formation_only(tmp_path, few_draws):
    s = sessions(4)
    def no_news(rid, symbol, sector):
        return row(rid, None, None, None, query_date=s[3], symbol=symbol,
                   formation_date=OCT, state=K.STATE_NO_NEWS, sector=sector,
                   outcome_state=K.OUTCOME_PENDING)

    rows = [row(1, s[0], POS, symbol="GLQ", formation_date=JULY, sector="N/A"),
            row(2, s[1], NEG, symbol="GLQ", formation_date=JULY, sector="N/A"),
            # GLQ in October: modal Financial Services over all states
            row(3, s[2], POS, symbol="GLQ", formation_date=OCT,
                sector="Financial Services"),
            no_news(10, "GLQ", "Financial Services"), no_news(11, "GLQ", "N/A"),
            row(4, s[3], NEG, symbol="AAA", formation_date=OCT),
            # CEF in October: its judged row says FS, its no_news rows N/A
            row(6, s[3], POS, symbol="CEF", formation_date=OCT,
                sector="Financial Services"),
            no_news(12, "CEF", "N/A"), no_news(13, "CEF", "N/A")]
    res = F.compute(make_db(tmp_path / "s.db", rows))
    assert res["readings"]["primary"]["M"] == 5
    assert res["readings"]["sensitivity"]["M"] == 2
    sens = res["sensitivity_exclusion"]
    assert sens["rule_b"] == [
        {"symbol": "CEF", "formation_date": OCT, "judged_rows": 1,
         "scored_rows": 1},
        {"symbol": "GLQ", "formation_date": JULY, "judged_rows": 2,
         "scored_rows": 2}]
    assert sens["rule_a"] == []
    assert sens["rule_b_scale"]["scored_rows"] == 3
    assert sens["rule_b_scale"]["scored_share"] == 0.6
    assert sens["rule_b_scale"]["symbols"] == ["CEF", "GLQ"]


def test_build_sensitivity_set_seam(tmp_path, few_draws, monkeypatch):
    s = sessions(2)
    rows = [row(1, s[0], POS, symbol="BAC.PRL"), row(2, s[1], NEG)]
    db = make_db(tmp_path / "k.db", rows)
    assert F.compute(db)["readings"]["sensitivity"]["M"] == 1
    monkeypatch.setattr(F, "build_sensitivity_set", lambda rows, flags: tuple(rows))
    assert F.compute(db)["readings"]["sensitivity"]["M"] == 2


# ------------------------------------------------------------ 9.6 halves, D17

def crow(session):
    return {"scoring_session": session}


@pytest.mark.parametrize("n, n_second, boundary_index", [
    (5, 2, 3), (4, 2, 2), (7, 3, 4), (1, 0, None), (0, 0, None)])
def test_halves(n, n_second, boundary_index):
    s = sessions(n)
    scored = [crow(x) for x in s for _ in range(2)]
    boundary, info = F.half_boundary(scored)
    assert info["D"] == n and info["second_half_clusters"] == n_second
    assert info["first_half_clusters"] == n - n_second
    assert boundary == (s[boundary_index] if boundary_index is not None else None)
    second = [r for r in scored if F.in_second_half(r, boundary)]
    assert len({r["scoring_session"] for r in second}) == n_second


def test_sensitivity_reading_keeps_the_primary_split(tmp_path, few_draws):
    s = sessions(5)
    rows, rid = [], 1
    for i, sess in enumerate(s):
        for lab in (POS, NEG):
            sym = "BAC.PRL" if i < 2 else "AAA"     # 8.2(a) only in s0, s1
            rows.append(row(rid, sess, lab, symbol=sym))
            rid += 1
    res = F.compute(make_db(tmp_path / "h.db", rows))
    assert res["halves"]["second_half_first"] == s[3]
    assert res["readings"]["primary"]["tests"]["P4"]["n_obs"] == 4
    # the sensitivity set holds 3 clusters (s2..s4); its own split would put
    # only s4 in the second half, the primary's split keeps s3 and s4
    sens = res["readings"]["sensitivity"]
    assert sens["D"] == 3
    assert sens["tests"]["P4"]["n_obs"] == 4
    assert sens["diagnostics"]["per_half"]["second"]["total"] == 4


# --------------------------------------------------------- 9.10 story, D11

def strow(group):
    return {"story_group_id": group}


def test_story_trigger_share_and_threshold():
    # 2 of 20 share a group: 0.10 exactly -> does not fire (above 10 percent)
    scored = [strow("g1"), strow("g1")] + [strow(None)] * 9 + [strow("")] * 4 \
        + [strow(f"solo{i}") for i in range(5)]
    t = F.story_trigger(scored)
    assert (t["n_scored"], t["n_shared"], t["n_shared_groups"]) == (20, 2, 1)
    assert t["share"] == 0.10 and t["fired"] is False
    t2 = F.story_trigger(scored + [strow("g1")])
    assert t2["n_shared"] == 3 and t2["fired"] is True
    assert t["reason"] is None and t2["reason"] is None
    assert F.story_trigger([])["fired"] is False


def test_story_trigger_empty_pool_share_is_none_not_zero():
    # N7: an empty scored set has no share; 0.0 would be a zero from nothing.
    t = F.story_trigger([])
    assert t["share"] is None
    assert t["fired"] is False
    assert t["reason"] == F.STORY_EMPTY_POOL_REASON
    assert "empty" in t["reason"]
    assert (t["n_scored"], t["n_shared"], t["n_shared_groups"]) == (0, 0, 0)
    assert t["threshold"] == K.STORY_TRIGGER_SHARE
    assert json.loads(json.dumps(t))["share"] is None


def test_empty_pool_story_trigger_flows_through_compute_and_decide(
        tmp_path, few_draws):
    s = sessions(2)
    rows = [row(1, s[0], POS, None, outcome_state=K.OUTCOME_PENDING),
            row(2, s[1], NEG, None, outcome_state=K.OUTCOME_PENDING)]
    res = F.compute(make_db(tmp_path / "e.db", rows))
    trig = res["story"]["trigger"]
    assert trig["n_scored"] == 0 and trig["share"] is None
    assert trig["fired"] is False and res["story"]["fired"] is False
    assert trig["reason"] == F.STORY_EMPTY_POOL_REASON
    d = V.decide(json.loads(json.dumps(res)))
    assert d["story"]["fired"] is False and d["story"]["statement"] is None


def test_story_version_runs_for_both_readings_when_fired(tmp_path, few_draws):
    s = sessions(6)
    rows, rid = [], 1
    for i, sess in enumerate(s):
        g = f"story{i}"
        for k, lab in enumerate((POS, NEG, POS, NEG)):
            rows.append(row(rid, sess, lab, (k - 1.5) / 1e3,
                            story_group_id=g if k < 2 else None,
                            symbol=f"S{k}"))
            rid += 1
    res = F.compute(make_db(tmp_path / "st.db", rows))
    assert res["story"]["fired"] is True
    assert res["story"]["trigger"]["share"] == 0.5
    st = res["story"]["readings"]
    assert set(st) == {"primary_story", "sensitivity_story"}
    p1 = st["primary_story"]["tests"]["P1"]
    assert p1["clustering"] == "story_group_id"
    assert p1["n_clusters"] == 6                       # 9.2 floor: sessions
    assert p1["bootstrap"]["n_clusters"] == 6 + 12     # 6 groups + 12 singles
    assert p1["permutation"]["blocked"] is True
    assert p1["bootstrap"]["stream_index"] == K.stream_index("P1", "primary_story")
    assert st["sensitivity_story"]["tests"]["P4"]["permutation"]["stream_index"] \
        == K.stream_index("P4", "sensitivity_story")
    plain = res["readings"]["primary"]["tests"]["P1"]
    assert plain["permutation"]["blocked"] is False
    assert plain["bootstrap"]["n_clusters"] == 6


def test_story_version_absent_when_not_fired(tmp_path, few_draws):
    rows = grid(4)
    res = F.compute(make_db(tmp_path / "ns.db", rows))
    assert res["story"]["fired"] is False and res["story"]["readings"] == {}


# ------------------------------------------------- Amendment 6 diagnostics

def test_diagnostics_counts(tmp_path, few_draws):
    s = sessions(4)
    rows = [
        row(1, s[0], POS, stratum="S1", strength=5),
        row(2, s[0], NEG, stratum="S1", strength=1),
        row(3, s[0], NEU, stratum="S2", strength=1),
        row(4, s[1], POS, stratum="S2", strength=4),
        row(5, s[1], POS, stratum="S3", strength=2, strength_parse_ok=0),
        row(6, s[2], NEU, stratum="S3", strength=1),
        row(7, s[2], NEG, stratum="S4", strength=3),
        row(8, s[3], POS, stratum="S4", strength=5),
        row(9, s[3], NEG, stratum="S4", strength=2, excess=-0.003),
    ]
    res = F.compute(make_db(tmp_path / "dg.db", rows))
    p = res["readings"]["primary"]
    d = p["diagnostics"]
    assert d["pooled"]["counts"] == {POS: 4, NEG: 3, NEU: 2, "other": 0}
    assert d["pooled"]["shares"][NEU] == pytest.approx(2 / 9)
    assert d["neutral_rate"] == pytest.approx(2 / 9)
    assert d["neutral_rate_exceeds_bar"] is False
    assert d["per_stratum"]["S2"]["counts"] == {POS: 1, NEG: 0, NEU: 1, "other": 0}
    assert d["per_stratum"]["S4"]["total"] == 3
    # halves: D = 4 clusters holding scored rows -> second half s2, s3
    assert d["per_half"]["first"]["counts"] == {POS: 3, NEG: 1, NEU: 1, "other": 0}
    assert d["per_half"]["second"]["counts"] == {POS: 1, NEG: 2, NEU: 1, "other": 0}
    assert (p["D"], p["M"]) == (4, 7)
    # minority share 3/7; mixed clusters: s0 (POS+NEG) and s3 (POS+NEG)
    assert p["null"]["minority_share"] == pytest.approx(3 / 7)
    assert p["null"]["n_mixed_clusters"] == 2
    assert p["null"]["informative"] is False             # fewer than 30 mixed
    h = d["strength_histogram"]
    assert h["n_parse_ok"] == 6 and h["n_not_parse_ok"] == 1
    assert h["buckets"]["5"] == {"n": 2, "mean_signed_bp": 10.0}
    assert h["buckets"]["2"] == {"n": 1, "mean_signed_bp": 30.0}
    assert h["buckets"]["3"]["n"] == 1 and h["label"] == "descriptive"
    assert d["per_stratum_scored"]["S4"] == {
        "scored": 3, "scored_clusters": 2, "net_bp_non_null": 3,
        "net_bp_null": 0, "net_bp_clusters": 2}
    s1 = p["tests"]["S1"]
    assert s1["n_obs"] == 6 and s1["label"] == V.STRENGTH_LABEL
    assert (p["tests"]["S2"]["n_top"], p["tests"]["S2"]["n_bottom"]) == (3, 2)


def test_neutral_rate_bar(tmp_path, few_draws):
    s = sessions(2)
    rows = [row(1, s[0], POS), row(2, s[1], NEG)] + [
        row(10 + i, s[i % 2], NEU) for i in range(9)]
    d = F.compute(make_db(tmp_path / "nr.db", rows))["readings"]["primary"][
        "diagnostics"]
    assert d["neutral_rate"] == pytest.approx(9 / 11)
    assert d["neutral_rate_exceeds_bar"] is True


# ------------------------------------------------------- the tests' plumbing

def test_primary_subsets_and_permutation_populations(tmp_path, few_draws):
    rows = grid(6)
    db = make_db(tmp_path / "g.db", rows)
    res = F.compute(db)
    p = res["readings"]["primary"]
    scored = [r for r in rows if r["judgment"] in (POS, NEG)]
    n_neg = sum(1 for r in scored if r["judgment"] == NEG)
    thin = [r for r in scored if r["stratum"] in K.THIN_END]
    t = p["tests"]
    assert t["P1"]["n_obs"] == len(scored) == p["M"]
    assert t["P1"]["permutation"]["mode"] == "subset"
    assert t["P2"]["n_obs"] == n_neg
    assert t["P2"]["permutation"]["mode"] == "negative_only"
    assert t["P2"]["permutation"]["n_obs"] == len(scored)
    assert t["P2"]["permutation"]["n_negative"] == n_neg
    assert t["P3"]["n_obs"] == len(thin)
    assert t["P4"]["n_obs"] == sum(1 for r in scored
                                   if r["scoring_session"] >= sessions(6)[3])
    assert t["P4"]["n_clusters"] == 3
    signed = [(1 if r["judgment"] == POS else -1) * r["excess_1session"] * 1e4
              for r in scored]
    assert t["P1"]["bootstrap"]["statistic"] == pytest.approx(np.mean(signed))
    assert t["P1"]["permutation"]["t_obs"] == pytest.approx(np.mean(signed))


def test_streams_and_draw_counts_follow_constants(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "N_BOOT", 123)
    monkeypatch.setattr(K, "N_PERM", 77)
    res = F.compute(make_db(tmp_path / "s.db", grid(4)))
    assert res["settings"]["n_boot"] == 123 and res["settings"]["n_perm"] == 77
    for reading in ("primary", "sensitivity"):
        tests = res["readings"][reading]["tests"]
        for name, test in tests.items():
            assert test["bootstrap"]["stream_index"] == K.stream_index(name, reading)
            if test["bootstrap"]["status"] != "abstain_empty_pool":
                assert test["bootstrap"]["n_draws"] == 123
            if name.startswith("P"):
                assert test["permutation"]["n_perm"] == 77
                assert test["permutation"]["stream_index"] \
                    == K.stream_index(name, reading)


def test_streams_are_the_registered_children(tmp_path, few_draws):
    """Bootstrap of P3 sensitivity uses child stream_index('P3','sensitivity')
    of BOOT_SEED: recomputing with that stream reproduces the SE."""
    from news_eval import stats
    rows = grid(5)
    res = F.compute(make_db(tmp_path / "c.db", rows))
    thin = [r for r in rows if r["judgment"] in (POS, NEG)
            and r["stratum"] in K.THIN_END]
    idx = K.stream_index("P3", "sensitivity")
    again = stats.cluster_bootstrap_ratio(
        F.signed_values(thin), [r["scoring_session"] for r in thin],
        n_draws=K.N_BOOT, rng=stats.child_rng(K.BOOT_SEED, idx),
        bar=K.BAR_PRIMARY_Z)
    got = res["readings"]["sensitivity"]["tests"]["P3"]["bootstrap"]
    assert got["se"] == again.se


def test_cluster_column_seam(tmp_path, few_draws, monkeypatch):
    s = sessions(4)
    # query_date and scoring_session differ: 2 query_dates, 4 sessions
    rows = [row(i + 1, s[i], POS if i % 2 else NEG, query_date=s[0] if i < 2
                else s[2]) for i in range(4)]
    db = make_db(tmp_path / "cc.db", rows)
    assert F.compute(db)["readings"]["primary"]["D"] == 4
    monkeypatch.setattr(F, "CLUSTER_COLUMN", "query_date")
    res = F.compute(db)
    assert res["readings"]["primary"]["D"] == 2
    assert res["settings"]["cluster_column"] == "query_date"
    assert res["readings"]["primary"]["tests"]["P1"]["n_clusters"] == 2


def test_signed_values_and_estimator_seams(tmp_path, few_draws, monkeypatch):
    db = make_db(tmp_path / "sv.db", grid(4, effect_bp=40.0))
    base = F.compute(db)["readings"]["primary"]["tests"]["P1"]["bootstrap"]
    monkeypatch.setattr(F, "signed_values",
                        lambda rows, _orig=F.signed_values: -_orig(rows))
    flipped = F.compute(db)["readings"]["primary"]["tests"]["P1"]["bootstrap"]
    assert flipped["statistic"] == pytest.approx(-base["statistic"])
    monkeypatch.undo()
    monkeypatch.setattr(K, "N_BOOT", 199)
    monkeypatch.setattr(K, "N_PERM", 199)
    seen = []

    def spy(values, clusters, *, rng, _orig=F.estimate_t):
        seen.append(len(values))
        return _orig(values, clusters, rng=rng)
    monkeypatch.setattr(F, "estimate_t", spy)
    F.compute(db)
    assert len(seen) == 16      # P1-P4 and E1-E4, two readings


def test_permutation_strata_seam(tmp_path, few_draws, monkeypatch):
    db = make_db(tmp_path / "ps.db", grid(4))
    calls = []

    def strata(rows):
        calls.append(len(rows))
        return ["one"] * len(rows)
    monkeypatch.setattr(F, "permutation_strata", strata)
    res = F.compute(db)
    assert len(calls) == 8
    assert res["readings"]["primary"]["tests"]["P1"]["permutation"]["n_strata"] == 1


def test_primary_bar_seam_reaches_the_interval(tmp_path, few_draws, monkeypatch):
    db = make_db(tmp_path / "b.db", grid(4))
    monkeypatch.setattr(K, "BAR_PRIMARY_Z", 1.96)
    b = F.compute(db)["readings"]["primary"]["tests"]["P1"]["bootstrap"]
    assert b["bar"] == 1.96
    assert b["lower"] == pytest.approx(b["statistic"] - 1.96 * b["se"])


def test_sector_robustness(tmp_path, few_draws):
    s = sessions(3)
    rows = [row(1, s[0], POS, symbol="A", sector="Tech"),
            row(2, s[1], NEG, symbol="A", sector="Tech"),
            row(3, s[2], POS, symbol="A", sector="Bank"),
            row(4, s[0], NEG, symbol="B", sector="N/A"),
            row(5, s[1], POS, symbol="C", sector=None),
            row(6, s[2], NEG, symbol="D", sector="Bank"),
            row(7, s[2], POS, symbol="E", sector="N/A"),
            row(8, s[1], NEG, symbol="E", sector="Bank")]   # tie -> N/A
    res = F.compute(make_db(tmp_path / "sec.db", rows))
    sec = res["sector_robustness"]
    assert sec["observations_per_sector"] == {
        "Bank": 1, "Tech": 3, K.SECTOR_UNCLASSIFIED: 4}
    assert sec["label"] == "descriptive" and sec["n_clusters"] == 3
    assert sec["statistic"] == pytest.approx(
        res["readings"]["primary"]["tests"]["P1"]["bootstrap"]["statistic"])


# ---------------------------------------------- determinism and boundaries

def test_compute_is_deterministic_at_registered_counts(tmp_path):
    assert K.N_BOOT == 10_000 and K.N_PERM == 10_000
    db = make_db(tmp_path / "det.db", grid(4, symbols_per_stratum=1))
    a = json.dumps(F.compute(db), sort_keys=True)
    b = json.dumps(F.compute(db), sort_keys=True)
    assert a == b
    res = json.loads(a)
    assert res["readings"]["primary"]["tests"]["P1"]["bootstrap"]["n_draws"] \
        == 10_000
    assert res["readings"]["primary"]["tests"]["P1"]["permutation"]["n_perm"] \
        == 10_000
    assert str(tmp_path) not in a
    assert "ret_" not in a


def test_top_level_keys(tmp_path, few_draws):
    res = F.compute(make_db(tmp_path / "k.db", grid(3)))
    assert set(res) == {"settings", "analysis_set", "sensitivity_exclusion",
                        "halves", "readings", "story", "sector_robustness"}
    assert set(res["readings"]) == {"primary", "sensitivity"}
    assert set(res["readings"]["primary"]["tests"]) == {
        "P1", "P2", "P3", "P4", "E1", "E2", "E3", "E4", "S1", "S2"}
    V.decide(res)   # the verdict consumes the shape without error


def test_compute_refuses_a_non_synthetic_database(tmp_path):
    db = make_db(tmp_path / "plain.db", grid(2), stamp=False)
    with pytest.raises(data.UnlockMissing):
        F.compute(db)


def test_compute_refuses_the_real_path(tmp_path, monkeypatch):
    db = make_db(tmp_path / "real_here.db", grid(2))
    monkeypatch.setattr(data, "REAL_DB_PATH", str(db))
    with pytest.raises(data.RealDatabaseRefused):
        F.compute(db)


def test_companion_horizons(tmp_path):
    s = sessions(3)
    rows = [row(1, s[0], POS, ret_2session=0.01, ret_5session=None,
                ret_10session=0.02),
            row(2, s[1], NEG, ret_2session=0.03, ret_5session=0.01,
                ret_10session=None),
            row(3, s[2], NEU, ret_2session=0.5, ret_5session=0.5,
                ret_10session=0.5)]
    out = F.companion_horizons(make_db(tmp_path / "ch.db", rows))
    assert out["label"] == "EXPLORATORY" and out["interval"] is None
    h = out["horizons"]
    assert h["ret_2session"] == {"k": 2, "n_obs": 2, "n_null": 0,
                                 "mean_signed_bp": pytest.approx(-100.0)}
    assert h["ret_5session"]["n_obs"] == 1 and h["ret_5session"]["n_null"] == 1
    assert h["ret_5session"]["mean_signed_bp"] == pytest.approx(-100.0)
    assert h["ret_10session"]["mean_signed_bp"] == pytest.approx(200.0)


def test_compute_never_selects_companion_columns(tmp_path, few_draws, monkeypatch):
    selected = []
    original = data.VerdictPhase.select

    def spy(self, columns, filters=(), order_by=("id",)):
        selected.extend(columns)
        return original(self, columns, filters, order_by)
    monkeypatch.setattr(data.VerdictPhase, "select", spy)
    F.compute(make_db(tmp_path / "cs.db", grid(3)))
    assert selected and not {c for c in selected if c.startswith("ret_")}


def test_compute_refuses_a_broken_numpy_before_any_read(tmp_path, monkeypatch):
    db = make_db(tmp_path / "env.db", grid(2))
    opened = []
    monkeypatch.setattr(data, "open_phase",
                        lambda *a, **k: opened.append(a) or None)
    monkeypatch.setattr(envcheck, "numpy_sane", lambda: False)
    with pytest.raises(envcheck.EnvironmentRefused):
        F.compute(db)
    with pytest.raises(envcheck.EnvironmentRefused):
        F.companion_horizons(db)
    assert opened == []
