"""Tests for news_eval/report.py, the fixed-template verdict report (STAGE C.1 Task 6; 9.15).

Inputs are real family.compute / verdict.decide outputs on synthetic
databases in tmp_path, computed with K.N_BOOT and K.N_PERM lowered to 300 for
speed (the report formats numbers; it does not depend on the draw count).
The repository's real database is never opened.
"""
from __future__ import annotations

import copy
import os
import re
import sqlite3

import pytest

from news_eval import constants as K
from news_eval import data
from news_eval import family
from news_eval import relevance
from news_eval import report
from news_eval import synthetic
from news_eval import verdict as V

REPO_REAL_DB = os.path.realpath(data.REAL_DB_PATH)  # never opened
_UNPATCHED_CONNECT = sqlite3.connect
EXPERIMENT_MD = (data.REPO_ROOT / "EXPERIMENT.md").read_text(encoding="utf-8")
SCENARIOS = ("S-EFFECT", "S-NULL", "S-STORY", "S-THIN")


def _guarded_connect(database, *args, **kwargs):
    text = os.fspath(database) if not isinstance(database, int) else ""
    if isinstance(text, str) and text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
    if text and text != ":memory:" and os.path.realpath(text) == REPO_REAL_DB:
        raise AssertionError(f"test opened the real database: {database}")
    return _UNPATCHED_CONNECT(database, *args, **kwargs)


def _relevance_summary() -> dict:
    grades = {i: relevance.GRADES[i % 7 % 3] for i in range(1, 201)}
    keep = {relevance.VARIANT_ALL: list(range(1, 201)),
            relevance.VARIANT_A: list(range(1, 186)),
            relevance.VARIANT_A_B1: list(range(1, 181)),
            relevance.VARIANT_A_B2: list(range(1, 176))}
    rates = {g: {v: relevance.class_rates(grades, ids)
                 for v, ids in keep.items()}
             for g in ("opus", "fable", "final")}
    return {"schema": "c1_relevance_summary/1", "n_sample": 200,
            "grades_order": list(relevance.GRADES),
            "agreement_opus_fable": {"raw_agreement": 0.915, "n_agree": 183,
                                     "n_disagree": 17, "cohens_kappa": 0.8612},
            "variants": {v: {"note": "ignored by the report", "n": len(ids),
                             "approximate": v in (relevance.VARIANT_A_B1,
                                                  relevance.VARIANT_A_B2)}
                         for v, ids in keep.items()},
            "rates": rates, "note": "ignored by the report"}


@pytest.fixture(scope="module")
def computed(tmp_path_factory) -> dict:
    base = tmp_path_factory.mktemp("report")
    out = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sqlite3, "connect", _guarded_connect)
        mp.setattr(data, "REAL_DB_PATH", str(base / "absent_live.db"))
        mp.setattr(K, "N_BOOT", 300)
        mp.setattr(K, "N_PERM", 300)
        for name in SCENARIOS:
            db = base / f"{name}.db"
            synthetic.build(name, db)
            results = family.compute(db)
            out[name] = {"results": results,
                         "decision": V.decide(results)}
        out["companion"] = family.companion_horizons(base / "S-EFFECT.db")
    out["relevance"] = _relevance_summary()
    out["run_meta"] = {
        "hashes": {"snapshot_sha256": "a" * 64, "manifest_sha256": "b" * 64},
        "snapshot": {"utc_time": "2026-10-20T06:00:00.000000Z",
                     "method": "sqlite3.Connection.backup"},
        "s_star": "2026-10-26", "utc_start": "2026-10-20T07:00:00Z",
        "utc_marker": "2026-10-20T07:00:05Z",
        "successor_condition_9_12": {"tracked": False, "holds": False,
                                     "last_commit_time": None}}
    return out


def render(c: dict, name: str, **kw) -> str:
    return report.write(c[name]["results"], c[name]["decision"],
                        relevance_summary=c["relevance"], **kw)


def section(text: str, heading: str) -> str:
    start = text.index(heading + "\n")
    nxt = text.find("\n## ", start + len(heading))
    return text[start:] if nxt < 0 else text[start:nxt]


# ------------------------------------------------------------------- order

def test_sections_in_fixed_order_with_every_part(computed):
    text = render(computed, "S-EFFECT", companion=computed["companion"],
                  run_meta=computed["run_meta"])
    heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == list(report.SECTIONS)
    assert heads[0] == report.H_DIAGNOSTICS
    pos = [text.index(h + "\n") for h in report.SECTIONS]
    assert pos == sorted(pos)


def test_companion_and_provenance_only_when_passed(computed):
    for name in SCENARIOS:
        text = render(computed, name)
        assert report.H_COMPANION not in text
        assert "EXPLORATORY" not in text
        assert report.H_PROVENANCE not in text


def test_companion_section_is_exploratory_without_interval_or_bar(computed):
    text = render(computed, "S-EFFECT", companion=computed["companion"])
    comp = section(text, report.H_COMPANION)
    assert comp.count("EXPLORATORY") >= 2
    assert "+/-" not in comp and "[" not in comp
    assert "no interval, no bar" in comp
    for col in ("ret_2session", "ret_5session", "ret_10session"):
        assert f"| {col} |" in comp


# ----------------------------------------------------------------- quotes

def test_verbatim_quotes_present_and_byte_exact(computed):
    text = render(computed, "S-EFFECT")
    for quote in (V.MODEL_CUTOFF_8_1, V.CLOSED_END_FUND_DEFECT_8_2,
                  V.READINGS_DISAGREE_8_2, V.ROW_384_OUTCOME,
                  V.ROW_384_VERDICT, V.ROW_387_OUTCOME, V.ROW_387_VERDICT,
                  V.STRENGTH_LABEL.split(";")[0]):
        assert quote in text
    for quote in (V.MODEL_CUTOFF_8_1, V.CLOSED_END_FUND_DEFECT_8_2,
                  V.READINGS_DISAGREE_8_2, V.ROW_384_VERDICT,
                  V.ROW_387_VERDICT):
        assert quote in EXPERIMENT_MD
    null = render(computed, "S-NULL")
    for quote in (V.ROW_385_OUTCOME, V.ROW_385_VERDICT,
                  V.TASK6_POWERED_NEGATIVE):
        assert quote in null and quote in EXPERIMENT_MD


def test_rows_quoted_from_verdict_constants(computed):
    for name in SCENARIOS:
        text = render(computed, name)
        verdict_part = section(text, report.H_VERDICT)
        for reading in V.READINGS:
            for row in computed[name]["decision"]["readings"][reading]["rows"]:
                outcome, cell = V.VERDICT_TABLE[row["key"]]
                assert outcome in verdict_part and cell in verdict_part
        assert computed[name]["decision"]["summary"] in verdict_part


def test_model_understands_only_inside_the_amendment_quote(computed):
    phrase = re.compile(r"the model understands", re.IGNORECASE)
    for name in SCENARIOS:
        text = render(computed, name, companion=computed["companion"],
                      run_meta=computed["run_meta"])
        assert not phrase.search(text.replace(V.ROW_387_VERDICT, ""))
    assert not phrase.search(render(computed, "S-NULL"))


def test_cutoff_and_defect_sections_carry_scale(computed):
    text = render(computed, "S-EFFECT")
    cut = section(text, report.H_CUTOFF)
    assert V.MODEL_CUTOFF_8_1 in cut
    defect = section(text, report.H_DEFECT)
    scale = computed["S-EFFECT"]["decision"]["statements"][
        "closed_end_fund_defect_8_2"]["scale"]
    assert V.CLOSED_END_FUND_DEFECT_8_2 in defect
    assert f"{scale['judged_rows']} judged rows" in defect
    assert f"{scale['scored_rows']} scored observations" in defect


# ---------------------------------------------------------------- wording

def test_pipeline_predicts_on_gross_positive_only(computed):
    effect = section(render(computed, "S-EFFECT"), report.H_VERDICT)
    assert ("Gross positive in this reading: the pipeline predicts "
            "next-session drift") in effect
    for name in ("S-NULL", "S-THIN"):
        text = render(computed, name)
        assert "Gross positive in this reading" not in text


def test_finding_about_markets_when_net_fails_everywhere(computed):
    decision = copy.deepcopy(computed["S-EFFECT"]["decision"])
    prim = decision["readings"]["primary"]
    prim["outcome_row"] = V.ROW_CLEARS_FAILS_NET
    prim["rows"][0]["key"] = V.ROW_CLEARS_FAILS_NET
    text = report.write(computed["S-EFFECT"]["results"], decision,
                        relevance_summary=computed["relevance"])
    assert "This result is a finding about markets. It licenses no trade." \
        in text
    assert V.ROW_383_VERDICT in text


NET_ROW_CELLS = (V.ROW_383_OUTCOME, V.ROW_383_VERDICT, V.ROW_384_OUTCOME,
                 V.ROW_384_VERDICT, V.ROW_386_OUTCOME, V.ROW_386_VERDICT)


def _with_e_tests(computed, edit) -> tuple[dict, dict]:
    """S-EFFECT (gross clears) with every E-test of both readings edited,
    then decided again through verdict.decide: the S6 cases end to end."""
    results = copy.deepcopy(computed["S-EFFECT"]["results"])
    for reading in V.READINGS:
        for t in V.E_TESTS:
            edit(results["readings"][reading]["tests"][t])
    decision = V.decide(results)
    for reading in V.READINGS:
        assert decision["readings"][reading]["gross"]["gross_reading"] \
            == V.GROSS_CLEARS
    return results, decision


def _below_floor(test: dict) -> None:
    test["n_clusters"] = K.FLOOR_TEST_CLUSTERS - 1


def _net_negative(test: dict) -> None:
    test["bootstrap"] = {**test["bootstrap"], "status": "ok",
                         "statistic": -20.0, "se": 2.0, "z": -10.0,
                         "lower": -25.0, "upper": -15.0}


def test_s6_net_abstains_reports_no_net_row_and_amendment_5_quote(computed):
    results, decision = _with_e_tests(computed, _below_floor)
    for reading in V.READINGS:
        assert decision["readings"][reading]["outcome_row"] \
            == V.CLEARS_GROSS_NET_ABSTAINS
    text = report.write(results, decision,
                        relevance_summary=computed["relevance"])
    for cell in NET_ROW_CELLS:
        assert cell not in text
    verdict_part = section(text, report.H_VERDICT)
    assert verdict_part.count("No Amendment 5 net row applies because the "
                              "E-tests abstained.") == 2
    assert verdict_part.count(V.A5_ABSTENTION_NOT_NEGATIVE) == 2
    assert verdict_part.count("No E-test cleared, so no Amendment 5 row "
                              "permits trading on this result.") == 2
    assert V.A5_ABSTENTION_NOT_NEGATIVE in EXPERIMENT_MD
    for t in V.E_TESTS:
        assert f"{t} ({K.E_TEST_STRATUM[t]}) {V.ABSTAIN_FLOOR}" in verdict_part
    assert V.ROW_387_OUTCOME in verdict_part and V.ROW_387_VERDICT in verdict_part
    assert "This result is a finding about markets" not in text
    assert decision["summary"] in verdict_part
    assert V.NET_ABSTAINS_WORDS in decision["summary"]


def test_s6_net_negative_everywhere_reports_fails_net_row(computed):
    results, decision = _with_e_tests(computed, _net_negative)
    for reading in V.READINGS:
        assert decision["readings"][reading]["outcome_row"] \
            == V.ROW_CLEARS_FAILS_NET
    text = report.write(results, decision,
                        relevance_summary=computed["relevance"])
    verdict_part = section(text, report.H_VERDICT)
    assert V.ROW_383_OUTCOME in verdict_part and V.ROW_383_VERDICT in verdict_part
    assert "This result is a finding about markets. It licenses no trade." \
        in verdict_part
    assert "No Amendment 5 net row applies" not in text
    assert V.A5_ABSTENTION_NOT_NEGATIVE not in verdict_part


def test_n7_empty_story_pool_renders_without_a_share(computed):
    results = copy.deepcopy(computed["S-EFFECT"]["results"])
    results["story"]["trigger"] = family.story_trigger([])
    text = report.write(results, computed["S-EFFECT"]["decision"],
                        relevance_summary=computed["relevance"])
    rob = section(text, report.H_ROBUSTNESS)
    assert f"{report.NA} (0 of 0, 0 shared groups)" in rob
    assert "not fired" in rob
    assert family.STORY_EMPTY_POOL_REASON in rob


def test_abstention_floor_states_task5_words_and_no_row(computed):
    text = section(render(computed, "S-THIN"), report.H_VERDICT)
    assert "No Amendment 5 outcome row applies to this reading." in text
    assert V.TASK5_FLOOR_ABSTENTION in text
    assert "fewer than 60 clusters hold scored observations" in text


# ------------------------------------------------------------- the tables

def test_each_primary_beside_its_sensitivity_reading(computed):
    prim = section(render(computed, "S-EFFECT"), report.H_PRIMARIES)
    rows = [ln for ln in prim.splitlines() if re.match(r"\| P[1-4] \|", ln)]
    keys = [(ln.split("|")[1].strip(), ln.split("|")[3].strip())
            for ln in rows]
    assert keys == [(t, r) for t in ("P1", "P2", "P3", "P4")
                    for r in ("primary", "sensitivity")]
    p1 = computed["S-EFFECT"]["results"]["readings"]["primary"]["tests"]["P1"]
    assert f"| {p1['bootstrap']['statistic']:.2f} |" in rows[0]
    assert rows[0].rstrip(" |").endswith("clear")


def test_diagnostics_report_neutral_rate_and_null(computed):
    diag = section(render(computed, "S-NULL"), report.H_DIAGNOSTICS)
    d = computed["S-NULL"]["results"]["readings"]["primary"]["diagnostics"]
    assert f"NEUTRAL rate {100 * d['neutral_rate']:.1f} percent against the " \
           "80 percent bar" in diag
    assert "Permutation null informative: yes." in diag
    for k in ("pooled", "stratum S1", "stratum S4", "first half",
              "second half"):
        assert f"| {k} |" in diag


def test_secondaries_labelled_weaker_with_status_words(computed):
    sec = section(render(computed, "S-NULL"), report.H_SECONDARIES)
    assert "weaker secondaries" in sec
    assert "No secondary confirms the hypothesis" in sec
    assert V.STRENGTH_LABEL in sec
    statuses = computed["S-NULL"]["decision"]["readings"]["primary"][
        "statuses"]
    if V.NET_NEGATIVE in statuses.values():
        assert "| net negative |" in sec


def test_relevance_rates_reported(computed):
    rel = section(render(computed, "S-EFFECT"), report.H_RELEVANCE)
    final_all = computed["relevance"]["rates"]["final"][
        relevance.VARIANT_ALL]
    assert "Raw agreement 91.5 percent (183 agree, 17 disagree)" in rel
    assert "Cohen's kappa 0.861" in rel
    for g in relevance.GRADES:
        cell = (f"{final_all['counts'][g]} "
                f"({100 * final_all['rates'][g]:.1f} percent)")
        assert cell in rel
    assert "ignored by the report" not in rel
    assert "Nothing is filtered on these grades" in rel


def test_sector_and_story_figures(computed):
    rob = section(render(computed, "S-EFFECT"), report.H_ROBUSTNESS)
    sec = computed["S-EFFECT"]["results"]["sector_robustness"]
    assert f"T {sec['statistic']:.2f} bp, CR1 SE over sectors" in rob
    assert "not fired" in rob and "primary_story" not in rob
    story = section(render(computed, "S-STORY"), report.H_ROBUSTNESS)
    assert computed["S-STORY"]["results"]["story"]["fired"]
    for r in ("primary_story", "sensitivity_story"):
        assert sum(1 for ln in story.splitlines()
                   if f"| {r} |" in ln) == 4


# ------------------------------------------------------------ determinism

def _reversed(obj):
    if isinstance(obj, dict):
        return {k: _reversed(obj[k]) for k in reversed(list(obj))}
    if isinstance(obj, list):
        return [_reversed(v) for v in obj]
    return obj


def test_deterministic_and_independent_of_key_order(computed):
    c = computed["S-STORY"]
    a = report.write(c["results"], c["decision"],
                     relevance_summary=computed["relevance"],
                     companion=computed["companion"])
    b = report.write(_reversed(c["results"]), _reversed(c["decision"]),
                     relevance_summary=_reversed(computed["relevance"]),
                     companion=_reversed(computed["companion"]))
    assert a == b
    assert a == report.write(c["results"], c["decision"],
                             relevance_summary=computed["relevance"],
                             companion=computed["companion"])


def test_data_labels_are_escaped():
    assert report._label("A|B\nC  `D`") == "A\\|B C 'D'"
    assert report._label(None) == report.NA
