"""news_eval.relevance: the 9.13 draw (D23) and the grading summary (8.3).

Synthetic databases only, in tmp_path; data.REAL_DB_PATH points at a fake
"real" database in tmp_path and sqlite3.connect refuses the repository's
real file. The real draw is run by the C.1 lead after the freeze.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from news_eval import constants as K
from news_eval import data
from news_eval import envcheck
from news_eval import marker
from news_eval import relevance as rel

SCHEMA_SQL = Path(data.SCHEMA_SQL_PATH).read_text()
REPO_REAL_DB = os.path.realpath(data.REAL_DB_PATH)  # never opened
_UNPATCHED_CONNECT = sqlite3.connect


class ConnectCalled(BaseException):
    """Raised by the patched sqlite3.connect."""


def _touches_repo_real(target: object) -> bool:
    text = os.fspath(target) if not isinstance(target, int) else ""
    if isinstance(text, bytes):
        text = text.decode()
    if text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
        while text.startswith("//"):
            text = text[1:]
    if not text or text == ":memory:":
        return False
    if os.path.realpath(text) == REPO_REAL_DB:
        return True
    try:
        a, b = os.stat(text), os.stat(REPO_REAL_DB)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


@pytest.fixture(autouse=True)
def _never_the_repo_real_db(monkeypatch):
    def guarded(database, *args, **kwargs):
        if _touches_repo_real(database):
            raise ConnectCalled(f"test opened the real database: {database}")
        return _UNPATCHED_CONNECT(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", guarded)


@pytest.fixture(autouse=True)
def _test_mode(monkeypatch):
    """C.1 ruling S5: the CLI's --real-db is accepted only in test mode."""
    monkeypatch.setenv(data.TEST_MODE_ENV, "1")


@pytest.fixture()
def fake_real(tmp_path, monkeypatch) -> Path:
    path = make_db(tmp_path / "repo" / "news_experiment.db",
                   population_rows(230, 20), stamp=False)
    monkeypatch.setattr(data, "REAL_DB_PATH", str(path))
    return path


_BASE = {
    "rule_id": "r", "formation_date": "2026-07-01", "stratum": "S2",
    "sector": "Technology", "sector_source": "finnhub_profile2",
    "state": K.STATE_JUDGED, "exclusion_reason": "", "spec_version": "v",
    "written_ts": "w", "run_kind": K.RUN_KIND_COLLECTION,
}
SYMBOLS = ("AAPL", "BAC.PRL", "STRK", "BCX", "MSFT", "GLQ", "ZZZ", "KO")


def population_rows(n_eligible: int, n_noise: int) -> list[dict]:
    """n_eligible judged collection rows (query_date <= 2026-10-09) with
    n_noise rows the draw must never see, interleaved by id."""
    out = []
    for i in range(n_eligible):
        sym = SYMBOLS[i % len(SYMBOLS)]
        out.append({**_BASE, "symbol": sym,
                    "query_date": "2026-10-09" if i % 13 == 0 else
                    f"2026-{8 + i % 2:02d}-{1 + i % 28:02d}",
                    "headline": f"{sym} headline {i}, with \"quotes\"\nline",
                    "sector": None if i % 17 == 0 else (
                        "N/A" if sym == "GLQ" else "Technology"),
                    "stratum": K.STRATA[i % 4]})
        if i % max(1, n_eligible // max(1, n_noise)) == 0 and n_noise:
            out.append(_noise(len(out)))
            n_noise -= 1
    return out


def _noise(k: int) -> dict:
    kind = k % 3
    row = {**_BASE, "symbol": "NOISE", "query_date": "2026-09-01",
           "headline": "noise"}
    if kind == 0:
        row["state"] = K.STATE_MODEL_FAILED
    elif kind == 1:
        row["run_kind"] = "demonstration"
    else:
        row["query_date"] = "2026-10-12"
    return row


def make_db(path: Path, rows: list[dict], stamp: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _UNPATCHED_CONNECT(path)
    try:
        conn.executescript(SCHEMA_SQL)
        for r in rows:
            cols = ", ".join(r)
            conn.execute(f"INSERT INTO news_observation ({cols}) VALUES "
                         f"({', '.join('?' * len(r))})", tuple(r.values()))
        conn.commit()
        if stamp:
            marker.write_marker(conn, "relevance-test", 1)
    finally:
        conn.close()
    return path


def eligible_ids(path: Path) -> list[int]:
    conn = _UNPATCHED_CONNECT(path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT id FROM news_observation WHERE run_kind = 'collection' "
            "AND state = 'judged' AND query_date <= '2026-10-09' "
            "ORDER BY id")]
    finally:
        conn.close()


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


# --------------------------------------------------------------------- draw

def test_draw_two_hundred_rows_six_columns_sorted_and_filtered(tmp_path,
                                                                 fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 40))
    out = tmp_path / "sample.csv"
    meta = rel.draw(db, out)
    header, rows = read_csv(out)
    assert tuple(header) == K.RELEVANCE_COLUMNS
    assert len(rows) == 200 and all(len(r) == 6 for r in rows)
    ids = [int(r[0]) for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == 200
    pop = eligible_ids(db)
    assert len(pop) == 260 and set(ids) <= set(pop)
    conn = _UNPATCHED_CONNECT(db)
    try:
        kinds = conn.execute(
            "SELECT SUM(state = 'model_failed'), "
            "SUM(run_kind = 'demonstration'), SUM(query_date > '2026-10-09'),"
            " SUM(query_date = '2026-10-09' AND symbol != 'NOISE') "
            "FROM news_observation").fetchone()
    finally:
        conn.close()
    assert all(k > 0 for k in kinds), kinds  # each excluded kind is present
    assert all(r[1] != "NOISE" for r in rows)
    assert all(r[2] <= "2026-10-09" for r in rows)
    assert meta["population_count"] == 260
    assert meta["n_drawn"] == 200


def test_draw_matches_the_registered_procedure(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 40))
    out = tmp_path / "sample.csv"
    rel.draw(db, out)
    pop = eligible_ids(db)
    rng = np.random.default_rng(20261012)
    want = sorted(pop[i] for i in rng.choice(len(pop), 200, replace=False))
    assert [int(r[0]) for r in read_csv(out)[1]] == want


def test_draw_deterministic_twice(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 40))
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    rel.draw(db, a)
    rel.draw(db, b)
    assert a.read_bytes() == b.read_bytes()


def test_csv_round_trips_quotes_newlines_and_null_sector(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 0))
    out = tmp_path / "sample.csv"
    rel.draw(db, out)
    conn = _UNPATCHED_CONNECT(db)
    try:
        src = {r[0]: r for r in conn.execute(
            "SELECT id, symbol, query_date, headline, sector, stratum "
            "FROM news_observation")}
    finally:
        conn.close()
    for r in read_csv(out)[1]:
        s = src[int(r[0])]
        assert r[1:] == [s[1], s[2], s[3], s[4] or "", s[5]]
    assert b"\r\n" not in out.read_bytes().replace(b'line', b'')


def test_sidecar(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 40))
    out = tmp_path / "sample.csv"
    rel.draw(db, out)
    meta = json.loads(rel.meta_path(out).read_text())
    pop = eligible_ids(db)
    assert meta["population_count"] == 260
    assert meta["population_min_id"] == pop[0]
    assert meta["population_max_id"] == pop[-1]
    assert meta["population_max_query_date"] <= "2026-10-09"
    assert meta["seed"] == K.RELEVANCE_SEED == 20261012
    assert meta["csv_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert "choice(n, 200, replace=False)" in meta["draw_method"]
    assert meta["utc_time"].endswith("Z")
    assert rel.meta_path(out).name == "sample.csv.meta.json"


def test_refuses_under_two_hundred(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(199, 30))
    out = tmp_path / "sample.csv"
    with pytest.raises(rel.RelevanceRefusal, match="199"):
        rel.draw(db, out)
    assert not out.exists() and not rel.meta_path(out).exists()


def test_exactly_two_hundred_draws_everything(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(200, 5))
    out = tmp_path / "sample.csv"
    rel.draw(db, out)
    assert [int(r[0]) for r in read_csv(out)[1]] == eligible_ids(db)


def test_refuses_overwrite_unless_asked(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(220, 0))
    out = tmp_path / "sample.csv"
    rel.draw(db, out)
    before = out.read_bytes()
    with pytest.raises(rel.RelevanceRefusal, match="overwrite"):
        rel.draw(db, out)
    rel.draw(db, out, overwrite=True)
    assert out.read_bytes() == before


def test_draw_on_the_live_path_uses_the_relevance_phase(tmp_path, fake_real):
    # The fake "real" database carries no marker; RELEVANCE admits it as
    # LIVE_REAL (guardrail read 3) with the fixed 2026-10-09 filter.
    out = tmp_path / "sample.csv"
    meta = rel.draw(fake_real, out)
    assert meta["population_count"] == 230
    assert len(read_csv(out)[1]) == 200


def test_non_synthetic_copy_refused(tmp_path, fake_real):
    copy = tmp_path / "copy.db"
    shutil.copy2(fake_real, copy)
    with pytest.raises(data.NotSyntheticRefused):
        rel.draw(copy, tmp_path / "sample.csv")
    assert not (tmp_path / "sample.csv").exists()


def test_cli_draw_with_overrides(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(220, 10))
    out = tmp_path / "cli.csv"
    assert rel._main(["draw", "--out", str(out), "--db", str(db),
                      "--real-db", str(fake_real)]) == 0
    assert len(read_csv(out)[1]) == 200
    small = make_db(tmp_path / "small.db", population_rows(50, 0))
    assert rel._main(["draw", "--out", str(tmp_path / "x.csv"),
                      "--db", str(small)]) == 2


def test_cli_draw_requires_an_explicit_db(tmp_path, fake_real, capsys):
    """C.1 ruling N4: no default database, so no casual live read."""
    with pytest.raises(SystemExit) as exc:
        rel._main(["draw", "--out", str(tmp_path / "x.csv")])
    assert exc.value.code == 2 and "--db" in capsys.readouterr().err
    assert not (tmp_path / "x.csv").exists()


def test_cli_real_db_refused_outside_test_mode(tmp_path, fake_real,
                                               monkeypatch, capsys):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    db = make_db(tmp_path / "s.db", population_rows(220, 10))
    out = tmp_path / "cli.csv"
    assert rel._main(["draw", "--out", str(out), "--db", str(db),
                      "--real-db", str(fake_real)]) == 2
    err = capsys.readouterr().err
    assert "--real-db" in err and "test mode" in err and not out.exists()
    assert rel._main(["draw", "--out", str(out), "--db", str(db)]) == 0


def test_draw_checks_numpy_before_any_read(tmp_path, fake_real, monkeypatch):
    db = make_db(tmp_path / "s.db", population_rows(220, 10))
    out = tmp_path / "sample.csv"
    monkeypatch.setattr(envcheck, "numpy_sane", lambda: False)

    def no_connect(*args, **kwargs):
        raise AssertionError("connect before the numpy check")
    monkeypatch.setattr(sqlite3, "connect", no_connect)
    with pytest.raises(envcheck.EnvironmentRefused):
        rel.draw(db, out)
    assert rel._main(["draw", "--out", str(out), "--db", str(db)]) == 2
    assert not out.exists()


# ------------------------------------------------------------------- grades

def write_grades(path: Path, grades: dict[int, str],
                 header=("id", "grade", "reason")) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, g in grades.items():
            w.writerow([i, g, "short reason"][:len(header)])
    return path


C, R, O = rel.GRADES


def _from_confusion(m: list[list[int]]) -> tuple[dict, dict]:
    a, b, k = {}, {}, 0
    for i, gi in enumerate(rel.GRADES):
        for j, gj in enumerate(rel.GRADES):
            for _ in range(m[i][j]):
                a[k], b[k] = gi, gj
                k += 1
    return a, b


def test_kappa_hand_computed_three_by_three():
    m = [[40, 5, 5], [3, 20, 2], [2, 3, 20]]
    a, b = _from_confusion(m)
    # p_o = 80/100; marginals a = .50/.25/.25, b = .45/.28/.27;
    # p_e = .225 + .07 + .0675 = .3625; kappa = .4375 / .6375.
    assert rel.raw_agreement(a, b) == pytest.approx(0.80)
    assert rel.confusion(a, b) == m
    assert rel.cohens_kappa(a, b) == pytest.approx(0.4375 / 0.6375,
                                                    rel=1e-12)


def test_kappa_perfect_and_degenerate():
    a = {1: C, 2: R, 3: O}
    assert rel.cohens_kappa(a, dict(a)) == pytest.approx(1.0)
    same = {1: C, 2: C}
    assert rel.cohens_kappa(same, dict(same)) is None


def test_kappa_refuses_different_id_sets():
    with pytest.raises(rel.RelevanceRefusal):
        rel.cohens_kappa({1: C}, {2: C})


@pytest.mark.parametrize("bad", ["Company-specific", "unsure", "", "on-topic",
                                 "roundup?"])
def test_invalid_grade_refused(tmp_path, bad):
    path = write_grades(tmp_path / "g.csv", {1: C, 2: bad})
    with pytest.raises(rel.RelevanceRefusal, match="grade"):
        rel.load_grades(path)


def test_grade_whitespace_stripped(tmp_path):
    path = write_grades(tmp_path / "g.csv", {1: " roundup ", 2: O})
    assert rel.load_grades(path) == {1: R, 2: O}


def test_duplicate_missing_and_unexpected_ids_refused(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("id,grade,reason\n1,roundup,x\n1,off-topic,y\n")
    with pytest.raises(rel.RelevanceRefusal, match="duplicate"):
        rel.load_grades(p)
    p.write_text("id,grade,reason\n,roundup,x\n")
    with pytest.raises(rel.RelevanceRefusal, match="missing id"):
        rel.load_grades(p)
    p.write_text("id,grade,reason\nabc,roundup,x\n")
    with pytest.raises(rel.RelevanceRefusal, match="integer"):
        rel.load_grades(p)
    write_grades(p, {1: C, 2: R})
    with pytest.raises(rel.RelevanceRefusal, match="missing"):
        rel.load_grades(p, expected_ids={1, 2, 3})
    with pytest.raises(rel.RelevanceRefusal, match="extra"):
        rel.load_grades(p, expected_ids={1})
    write_grades(p, {1: C}, header=("id", "grade"))
    with pytest.raises(rel.RelevanceRefusal, match="header"):
        rel.load_grades(p)


def test_class_rates():
    out = rel.class_rates({1: C, 2: C, 3: R, 4: O})
    assert out["n"] == 4
    assert out["counts"] == {C: 2, R: 1, O: 1}
    assert out["rates"] == {C: 0.5, R: 0.25, O: 0.25}
    assert rel.class_rates({1: C}, ids=[])["rates"][C] is None


def test_exclusion_rules():
    assert rel.rule_a("BAC.PRL") and rel.rule_a("BF.A") and rel.rule_a("STRK")
    assert rel.rule_a("STRC") and not rel.rule_a("AAPL")
    assert rel.rule_b1("BCX") and rel.rule_b1("PSUS") and not rel.rule_b1("GLQ")
    assert rel.rule_b2("GLQ", "N/A") and rel.rule_b2("BCX", "Technology")
    assert not rel.rule_b2("AAPL", None)
    assert len(rel.RULE_B_2026_07_01) == 9


def test_variant_ids():
    sample = {1: {"symbol": "AAPL", "sector": "Technology"},
              2: {"symbol": "BAC.PRL", "sector": "Financial Services"},
              3: {"symbol": "BCX", "sector": "N/A"},
              4: {"symbol": "GLQ", "sector": "N/A"},
              5: {"symbol": "KO", "sector": ""}}
    keep = rel.variant_ids(sample)
    assert keep[rel.VARIANT_ALL] == [1, 2, 3, 4, 5]
    assert keep[rel.VARIANT_A] == [1, 3, 4, 5]
    assert keep[rel.VARIANT_A_B1] == [1, 4, 5]
    assert keep[rel.VARIANT_A_B2] == [1, 5]


def test_summarize_end_to_end(tmp_path, fake_real):
    db = make_db(tmp_path / "s.db", population_rows(260, 10))
    sample = tmp_path / "sample.csv"
    rel.draw(db, sample)
    ids = [int(r[0]) for r in read_csv(sample)[1]]
    opus = {i: rel.GRADES[i % 3] for i in ids}
    fable = {i: rel.GRADES[(i // 2) % 3] for i in ids}
    final = {i: opus[i] for i in ids}
    paths = {name: write_grades(tmp_path / f"{name}.csv", g)
             for name, g in (("opus", opus), ("fable", fable),
                             ("final", final))}
    out = tmp_path / "summary.json"
    assert rel._main(["summarize", "--sample", str(sample),
                      "--opus", str(paths["opus"]),
                      "--fable", str(paths["fable"]),
                      "--final", str(paths["final"]),
                      "--out", str(out)]) == 0
    s = json.loads(out.read_text())
    agr = s["agreement_opus_fable"]
    assert agr["raw_agreement"] == pytest.approx(rel.raw_agreement(opus,
                                                                   fable))
    assert agr["n_agree"] + agr["n_disagree"] == 200
    assert agr["cohens_kappa"] == pytest.approx(rel.cohens_kappa(opus, fable))
    assert set(s["rates"]) == {"opus", "fable", "final"}
    for grade_set in s["rates"].values():
        assert set(grade_set) == set(rel.VARIANT_NOTES)
        assert grade_set[rel.VARIANT_ALL]["n"] == 200
    assert s["variants"][rel.VARIANT_A_B1]["approximate"] is True
    assert s["variants"][rel.VARIANT_A]["approximate"] is False
    n_a = s["variants"][rel.VARIANT_A]["n"]
    assert n_a < 200 and s["variants"][rel.VARIANT_A_B2]["n"] <= \
        s["variants"][rel.VARIANT_A_B1]["n"] <= n_a


def test_summarize_refuses_a_grade_set_missing_a_sample_id(tmp_path,
                                                           fake_real):
    db = make_db(tmp_path / "s.db", population_rows(220, 0))
    sample = tmp_path / "sample.csv"
    rel.draw(db, sample)
    ids = [int(r[0]) for r in read_csv(sample)[1]]
    full = write_grades(tmp_path / "full.csv", {i: C for i in ids})
    short = write_grades(tmp_path / "short.csv", {i: C for i in ids[1:]})
    with pytest.raises(rel.RelevanceRefusal, match="missing"):
        rel.summarize(sample, full, short, full)
