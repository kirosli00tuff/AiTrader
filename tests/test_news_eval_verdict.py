"""news_eval.verdict: mapping tables A.1, A.2, A.3, B and C, C.1, C.2, and the
verbatim quotes (reports/c1_verdict_mapping.md; EXPERIMENT.md Amendment 5,
Task 6, Amendment 6, 8.1, 8.2, 9.2, 9.3, 9.5, 9.10; D2 to D8, D24).

Every input is a hand-built results dict. No database is opened."""
from __future__ import annotations

from pathlib import Path

import pytest

from news_eval import constants as K
from news_eval import verdict as V

EXPERIMENT_MD = Path(__file__).resolve().parent.parent / "EXPERIMENT.md"


# ------------------------------------------------------------------ builders

def boot(t=None, se=None, *, status="ok", n_clusters=60):
    ok = status == "ok"
    return {"status": status, "statistic": t if ok else None,
            "se": se if ok else None, "z": (t / se) if ok and se else None,
            "n_clusters": n_clusters}


def perm(p=0.0005, ge=4, le=9997, status="ok"):
    return {"status": status, "p": p if status == "ok" else None,
            "count_ge": ge if status == "ok" else None,
            "count_le": le if status == "ok" else None}


def ptest(t=1.0, se=4.0, *, n_clusters=60, boot_status="ok",
          boot_clusters=None, **perm_kw):
    return {"n_clusters": n_clusters,
            "bootstrap": boot(t, se, status=boot_status,
                              n_clusters=boot_clusters or n_clusters),
            "permutation": perm(**perm_kw)}


def etest(t=-30.0, se=5.0, *, n_clusters=60, boot_status="ok"):
    return {"n_clusters": n_clusters,
            "bootstrap": boot(t, se, status=boot_status, n_clusters=n_clusters)}


def stest(t=0.01, se=0.02, *, n_clusters=60, boot_status="ok"):
    return {"n_clusters": n_clusters,
            "bootstrap": boot(t, se, status=boot_status, n_clusters=n_clusters)}


CLEAR_P = dict(t=20.0, se=2.0)          # z = 10, lower = 15 > 0
NOT_CLEAR_P1 = dict(t=2.0, se=4.0)      # upper = 12 < 30
E_CLEAR = dict(t=20.0, se=2.0)
E_SPAN = dict(t=1.0, se=4.0)
E_NEG = dict(t=-20.0, se=2.0)           # z = -10: net_negative


def reading(p=None, e=None, s=None, *, D=64, M=2400, minority=0.30, mixed=60):
    p = {t: ptest(**NOT_CLEAR_P1) for t in V.PRIMARY_TESTS} | (p or {})
    e = {t: etest(**E_SPAN) for t in V.E_TESTS} | (e or {})
    s = {t: stest() for t in V.STRENGTH_TESTS} | (s or {})
    return {"D": D, "M": M,
            "null": {"minority_share": minority, "n_mixed_clusters": mixed},
            "diagnostics": {"pooled": {"total": 100, "counts": {
                "POSITIVE": 60, "NEGATIVE": 10, "NEUTRAL": 30, "other": 0}}},
            "tests": {**p, **e, **s}}


def results(primary, sensitivity=None, story=None):
    return {"readings": {"primary": primary,
                         "sensitivity": sensitivity or primary},
            "story": story or {"fired": False, "readings": {}},
            "sensitivity_exclusion": {"rule_b_scale": {"pairs": 3}}}


# ------------------------------------------------------- verbatim quotes, D24

def test_every_quoted_string_is_in_experiment_md_byte_for_byte():
    text = EXPERIMENT_MD.read_bytes()
    assert V.VERBATIM_QUOTES, "no quotes registered"
    for name, quote in V.VERBATIM_QUOTES.items():
        assert quote.encode("utf-8") in text, name


def test_verdict_table_cells_rebuild_lines_383_to_388_exactly():
    lines = EXPERIMENT_MD.read_text(encoding="utf-8").split("\n")
    pairs = [(V.ROW_383_OUTCOME, V.ROW_383_VERDICT),
             (V.ROW_384_OUTCOME, V.ROW_384_VERDICT),
             (V.ROW_385_OUTCOME, V.ROW_385_VERDICT),
             (V.ROW_386_OUTCOME, V.ROW_386_VERDICT),
             (V.ROW_387_OUTCOME, V.ROW_387_VERDICT),
             (V.ROW_388_OUTCOME, V.ROW_388_VERDICT)]
    for lineno, (outcome, text) in zip(range(383, 389), pairs):
        assert lines[lineno - 1] == f"| {outcome} | {text} |", lineno


def test_multiline_quotes_keep_their_line_breaks_and_bold():
    assert V.TASK6_ABSTENTION.count("\n") == 1
    assert V.TASK6_ABSTENTION.startswith("**") and V.TASK6_ABSTENTION.endswith("**")
    assert V.MODEL_CUTOFF_8_1.startswith("**Every scored headline postdates")
    assert V.READINGS_DISAGREE_8_2.count("\n") == 3
    assert V.CLOSED_END_FUND_DEFECT_8_2.count("\n") == 4
    assert V.TASK6_POWERED_NEGATIVE.startswith("**A powered negative:**")


def test_rows_carry_the_verbatim_cells():
    for key, (outcome, text) in V.VERDICT_TABLE.items():
        row = V._row(key)
        assert (row["outcome"], row["verdict"]) == (outcome, text)


# --------------------------------------------------- A.1 primary statuses

@pytest.mark.parametrize("test, informative, expected", [
    # row 1: fewer than 30 clusters (9.2), whatever the numbers say
    (ptest(**CLEAR_P, n_clusters=29), True, V.ABSTAIN_FLOOR),
    # row 2: degenerate refusal, SE of zero, fewer than 2 clusters
    (ptest(boot_status="degenerate"), True, V.DEGENERATE),
    (ptest(t=5.0, se=0.0), True, V.DEGENERATE),
    (ptest(**CLEAR_P, boot_clusters=1), True, V.DEGENERATE),
    # row 3: bar met, null UNINFORMATIVE
    (ptest(**CLEAR_P), False, V.ABSTAIN_NULL_UNINFORMATIVE),
    # row 4: bar met, informative, p <= 0.0125, upper tail
    (ptest(**CLEAR_P), True, V.CLEAR),
    (ptest(**CLEAR_P, p=0.0125), True, V.CLEAR),
    # row 5: bar met, informative, p above the bar or not upper tail
    (ptest(**CLEAR_P, p=0.0126), True, V.BLOCKED_BY_NULL),
    (ptest(**CLEAR_P, p=0.0002, ge=9998, le=1), True, V.BLOCKED_BY_NULL),
    (ptest(**CLEAR_P, p=0.0002, ge=40, le=40), True, V.BLOCKED_BY_NULL),  # D4 strict
    (ptest(**CLEAR_P, status="degenerate"), True, V.BLOCKED_BY_NULL),
    # row 6: z <= -2.50
    (ptest(t=-20.0, se=2.0), True, V.SIGNIFICANT_REVERSAL),
    (ptest(t=-5.0, se=2.0), True, V.SIGNIFICANT_REVERSAL),     # z = -2.50
    (ptest(t=-20.0, se=2.0), False, V.SIGNIFICANT_REVERSAL),
    # row 7: interval spans zero
    (ptest(t=2.0, se=4.0), True, V.NOT_CLEAR),
    (ptest(t=-4.0, se=2.0), True, V.NOT_CLEAR),                # z = -2.0
    # D3: z exactly 2.50 makes the lower bound exactly 0: not met
    (ptest(t=2.5, se=1.0), True, V.NOT_CLEAR),
])
def test_primary_status_rows(test, informative, expected):
    assert V.primary_status(test, informative) == expected


def test_null_informative_thresholds_d2():
    assert V.null_informative(0.10, 30) is True
    assert V.null_informative(0.0999, 30) is False
    assert V.null_informative(0.10, 29) is False
    assert V.null_informative(None, 64) is False


def test_primary_bar_read_at_call_time(monkeypatch):
    test = ptest(t=2.2, se=1.0)
    assert V.primary_status(test, True) == V.NOT_CLEAR
    monkeypatch.setattr(K, "BAR_PRIMARY_Z", 1.96)
    assert V.primary_status(test, True) == V.CLEAR


def test_upper_tail_seam_is_looked_up_at_call_time(monkeypatch):
    lower_tail = ptest(**CLEAR_P, p=0.0002, ge=9998, le=1)
    assert V.primary_status(lower_tail, True) == V.BLOCKED_BY_NULL
    monkeypatch.setattr(V, "upper_tail", lambda perm: True)
    assert V.primary_status(lower_tail, True) == V.CLEAR


def test_floor_and_perm_bar_read_at_call_time(monkeypatch):
    monkeypatch.setattr(K, "FLOOR_TEST_CLUSTERS", 61)
    assert V.primary_status(ptest(**CLEAR_P), True) == V.ABSTAIN_FLOOR
    monkeypatch.setattr(K, "FLOOR_TEST_CLUSTERS", 30)
    monkeypatch.setattr(K, "BAR_PERM_P", 0.0001)
    assert V.primary_status(ptest(**CLEAR_P), True) == V.BLOCKED_BY_NULL


# ------------------------------------------------------- A.2 E-test statuses

@pytest.mark.parametrize("test, expected", [
    (etest(**E_CLEAR, n_clusters=29), V.ABSTAIN_FLOOR),
    (etest(boot_status="degenerate"), V.DEGENERATE),
    (etest(t=3.0, se=0.0), V.DEGENERATE),
    (etest(**E_CLEAR), V.CLEAR),
    (etest(t=4.96, se=1.0), V.CLEAR),               # T exactly 4.96 bp
    (etest(t=4.0, se=1.0), V.BELOW_ECON_BAR),       # interval excludes zero
    (etest(t=-20.0, se=2.0), V.NET_NEGATIVE),
    (etest(t=-5.0, se=2.0), V.NET_NEGATIVE),        # z = -2.50
    (etest(**E_SPAN), V.ABSTAIN_INTERVAL),
    (etest(t=2.5, se=1.0), V.ABSTAIN_INTERVAL),     # D3 lower bound exactly 0
])
def test_e_status_rows(test, expected):
    assert V.e_status(test) == expected


def test_econ_bar_read_at_call_time(monkeypatch):
    test = etest(t=8.0, se=1.0)
    assert V.e_status(test) == V.CLEAR
    monkeypatch.setattr(K, "ECON_BAR_BP", 9.0)
    assert V.e_status(test) == V.BELOW_ECON_BAR


# --------------------------------------------------- A.3 strength statuses

@pytest.mark.parametrize("test, expected", [
    (stest(t=0.3, se=0.1, n_clusters=29), V.ABSTAIN_FLOOR),
    (stest(boot_status="abstain_empty_pool"), V.ABSTAIN_EMPTY_POOL),
    (stest(boot_status="abstain_empty_pool", n_clusters=10), V.ABSTAIN_FLOOR),
    (stest(boot_status="degenerate"), V.DEGENERATE),
    (stest(t=0.3, se=0.1), V.CLEAR),                 # z = 3
    (stest(t=0.23, se=0.1), V.CLEAR),                # z = 2.3, clears 2.24
    (stest(t=0.2, se=0.1), V.NOT_CLEAR),             # z = 2.0
    (stest(t=-0.3, se=0.1), V.NOT_CLEAR),            # z = -3: never a clear
])
def test_strength_status_rows(test, expected):
    assert V.strength_status(test) == expected


def test_strength_tests_sit_under_the_60_cluster_analysis_floor():
    """Task 5 Amendment 3: S1 and S2 run "under the same 60-cluster floor"."""
    assert V.strength_status(stest(t=0.3, se=0.1), 59) == V.ABSTAIN_FLOOR
    assert V.strength_status(stest(t=0.3, se=0.1), 60) == V.CLEAR
    d = V.decide(results(reading(D=59, s={"S1": stest(t=0.3, se=0.1)})))
    assert d["readings"]["primary"]["statuses"]["S1"] == V.ABSTAIN_FLOOR


def test_strength_bar_is_not_the_primary_bar():
    assert V.primary_status(ptest(t=2.3, se=1.0), True) == V.NOT_CLEAR
    assert V.strength_status(stest(t=2.3, se=1.0)) == V.CLEAR


# ----------------------------------------------------------- B gross reading

def statuses_of(r):
    informative = V.null_informative(r["null"]["minority_share"],
                                     r["null"]["n_mixed_clusters"])
    return {t: V.primary_status(r["tests"][t], informative)
            for t in V.PRIMARY_TESTS}


@pytest.mark.parametrize("kw, gross, reasons", [
    # row 1: D < 60 or M < 1,000
    (dict(D=59), V.GROSS_ABSTENTION_FLOOR, [V.REASON_D_BELOW_FLOOR]),
    (dict(M=999), V.GROSS_ABSTENTION_FLOOR, [V.REASON_M_BELOW_FLOOR]),
    (dict(D=59, M=999, p={"P1": ptest(**CLEAR_P)}), V.GROSS_ABSTENTION_FLOOR,
     [V.REASON_D_BELOW_FLOOR, V.REASON_M_BELOW_FLOOR]),
    # row 2: one primary clear
    (dict(p={"P3": ptest(**CLEAR_P)}), V.GROSS_CLEARS, []),
    # row 3: P1 not_clear, nothing met its bar, upper < 30
    (dict(), V.GROSS_POWERED_NEGATIVE, []),
    # row 3 with P1 a significant reversal (9.3: it still counts)
    (dict(p={"P1": ptest(t=-20.0, se=2.0)}), V.GROSS_POWERED_NEGATIVE, []),
    # a reversal elsewhere, a floor and a degenerate elsewhere do not block
    (dict(p={"P2": ptest(t=-20.0, se=2.0), "P3": ptest(n_clusters=10),
             "P4": ptest(boot_status="degenerate")}),
     V.GROSS_POWERED_NEGATIVE, []),
    # Amendment 6: an uninformative null does not touch a powered negative
    (dict(minority=0.05), V.GROSS_POWERED_NEGATIVE, []),
    # row 4: P1's interval includes both zero and 30 bp
    (dict(p={"P1": ptest(t=10.0, se=8.0)}), V.GROSS_ABSTENTION,
     [V.REASON_INTERVAL_ZERO_AND_EFFECT]),
    # upper bound exactly 30 is not below 30
    (dict(p={"P1": ptest(t=5.0, se=10.0)}), V.GROSS_ABSTENTION,
     [V.REASON_INTERVAL_ZERO_AND_EFFECT]),
    # D5: P1's bootstrap bar met, the null blocks, upper under 30 bp
    (dict(p={"P1": ptest(t=10.0, se=2.0, p=0.3)}), V.GROSS_ABSTENTION,
     [V.REASON_NULL_INTERCEPTED]),
    # D5: another primary's bar met and blocked, P1 not_clear under 30
    (dict(p={"P2": ptest(**CLEAR_P, p=0.5)}), V.GROSS_ABSTENTION,
     [V.REASON_NULL_INTERCEPTED]),
    # an uninformative null intercepting a positive
    (dict(minority=0.05, p={"P1": ptest(t=10.0, se=2.0)}), V.GROSS_ABSTENTION,
     [V.REASON_NULL_INTERCEPTED]),
    # P1 degenerate
    (dict(p={"P1": ptest(boot_status="degenerate")}), V.GROSS_ABSTENTION,
     [V.REASON_P1_DEGENERATE]),
])
def test_gross_reading_rows(kw, gross, reasons):
    r = reading(**kw)
    out = V.gross_reading(r, statuses_of(r))
    assert out["gross_reading"] == gross
    assert out["reasons"] == reasons


def test_d5_case_is_not_a_powered_negative_under_decide():
    r = reading(p={"P1": ptest(t=10.0, se=2.0, p=0.3)})
    d = V.decide(results(r))["readings"]["primary"]
    assert d["statuses"]["P1"] == V.BLOCKED_BY_NULL
    assert d["gross"]["p1_upper"] < K.EFFECT_BP
    assert d["gross"]["gross_reading"] == V.GROSS_ABSTENTION
    assert d["rows"] == [] and d["outcome_row"] is None


def test_effect_bar_read_at_call_time(monkeypatch):
    r = reading()
    assert V.gross_reading(r, statuses_of(r))["gross_reading"] \
        == V.GROSS_POWERED_NEGATIVE
    monkeypatch.setattr(K, "EFFECT_BP", 10.0)
    assert V.gross_reading(r, statuses_of(r))["gross_reading"] \
        == V.GROSS_ABSTENTION


# ------------------------------------------------------------- C verdict rows

def outcomes(decided):
    return [row["outcome"] for row in decided["rows"]]


def clears(e_clear: tuple[str, ...]):
    e = {t: etest(**E_CLEAR) for t in e_clear}
    return V.decide(results(reading(p={"P1": ptest(**CLEAR_P)}, e=e)))


def test_c_clears_gross_no_e_clear():
    # Every E-test abstain_interval: S6 ruling case (b), no Amendment 5 net
    # row, the Amendment 6 row, and each stratum's status listed so an
    # abstain_interval is never presented as a measured failure.
    d = clears(())["readings"]["primary"]
    assert outcomes(d) == [V.ROW_387_OUTCOME]
    assert d["outcome_row"] == V.CLEARS_GROSS_NET_ABSTAINS
    note = d["net_abstention"]["e_note"]
    for t in V.E_TESTS:          # each stratum's status listed
        assert t in note
    assert V.ABSTAIN_INTERVAL in note


def test_c_clears_gross_some_e_clear_without_thin_end():
    d = clears(("E1", "E2"))["readings"]["primary"]
    assert outcomes(d) == [V.ROW_384_OUTCOME, V.ROW_387_OUTCOME]
    assert d["outcome_row"] == V.ROW_CLEARS_SOME
    assert not any("differs" in n for n in d["rows"][0]["notes"])


def test_c_clears_gross_some_e_clear_with_thin_end_states_the_difference():
    d = clears(("E1", "E3"))["readings"]["primary"]
    assert outcomes(d) == [V.ROW_384_OUTCOME, V.ROW_387_OUTCOME]
    notes = " ".join(d["rows"][0]["notes"])
    assert "differs from the row's description" in notes
    assert "E3 (S3)" in notes and "tradeable where the E-tests cleared" in notes


def test_c_clears_gross_and_net():
    d = clears(V.E_TESTS)["readings"]["primary"]
    assert outcomes(d) == [V.ROW_386_OUTCOME, V.ROW_387_OUTCOME]
    assert d["outcome_row"] == V.ROW_CLEARS_BOTH


def test_c_below_econ_bar_is_not_an_e_clear():
    # E2 to E4 net_negative so the other strata fail net (S6 case (a)); E1
    # below_econ_bar must not count as a clear.
    e = {"E1": etest(t=4.0, se=1.0)} | {t: etest(**E_NEG)
                                         for t in ("E2", "E3", "E4")}
    d = V.decide(results(reading(p={"P1": ptest(**CLEAR_P)}, e=e)))
    d = d["readings"]["primary"]
    assert d["statuses"]["E1"] == V.BELOW_ECON_BAR
    assert d["outcome_row"] == V.ROW_CLEARS_FAILS_NET


# ---------------------------------- S6 ruling: no E-test clear, (a) and (b)

E_BELOW = dict(t=4.0, se=1.0)            # z = 4, lower 1.5 > 0, T < 4.96
E_FLOOR = dict(t=1.0, se=4.0, n_clusters=12)
E_DEGEN = dict(boot_status="degenerate")
NET_ROW_CELLS = (V.ROW_383_OUTCOME, V.ROW_383_VERDICT, V.ROW_384_OUTCOME,
                 V.ROW_384_VERDICT, V.ROW_386_OUTCOME, V.ROW_386_VERDICT)


def every(kw: dict) -> dict:
    return {t: kw for t in V.E_TESTS}


def clears_with(e_kw: dict, sensitivity_e_kw: dict | None = None):
    def build(kw):
        return reading(p={"P1": ptest(**CLEAR_P)},
                       e={t: etest(**k) for t, k in kw.items()})
    sens = build(sensitivity_e_kw) if sensitivity_e_kw is not None else None
    return V.decide(results(build(e_kw), sensitivity=sens))


FAILS_NET_CASES = {
    "all_net_negative": every(E_NEG),
    "all_below_econ_bar": every(E_BELOW),
    "net_negative_and_below_econ_bar": {"E1": E_NEG, "E2": E_BELOW,
                                        "E3": E_NEG, "E4": E_BELOW},
}
NET_ABSTAINS_CASES = {
    "all_abstain_interval": every(E_SPAN),
    "all_abstain_floor": every(E_FLOOR),
    "abstain_and_net_negative": {"E1": E_SPAN, "E2": E_NEG,
                                 "E3": E_FLOOR, "E4": E_NEG},
    "one_degenerate": {"E1": E_NEG, "E2": E_NEG, "E3": E_DEGEN,
                       "E4": E_BELOW},
}


@pytest.mark.parametrize("case", sorted(FAILS_NET_CASES))
def test_s6_case_a_every_e_test_fails_net_selects_fails_net_row(case):
    out = clears_with(FAILS_NET_CASES[case])
    d = out["readings"]["primary"]
    assert all(d["statuses"][t] in V.E_FAILS_NET_STATUSES for t in V.E_TESTS)
    assert d["outcome_row"] == V.ROW_CLEARS_FAILS_NET
    assert outcomes(d) == [V.ROW_383_OUTCOME, V.ROW_387_OUTCOME]
    assert d["net_abstention"] is None
    note = d["rows"][0]["notes"][0]
    assert all(f"{t} ({K.E_TEST_STRATUM[t]})" in note for t in V.E_TESTS)
    assert V.FINDING_ABOUT_MARKETS in out["summary"]
    assert V.NET_ABSTAINS_WORDS not in out["summary"]


@pytest.mark.parametrize("case", sorted(NET_ABSTAINS_CASES))
def test_s6_case_b_any_e_test_abstains_selects_net_abstains(case):
    out = clears_with(NET_ABSTAINS_CASES[case])
    d = out["readings"]["primary"]
    e = {t: d["statuses"][t] for t in V.E_TESTS}
    assert V.CLEAR not in e.values()
    assert any(s in V.E_ABSTAIN_STATUSES for s in e.values())
    assert d["outcome_row"] == V.CLEARS_GROSS_NET_ABSTAINS
    # No Amendment 5 net row is quoted; the Amendment 6 row still is.
    assert outcomes(d) == [V.ROW_387_OUTCOME]
    for row in d["rows"]:
        assert row["outcome"] not in NET_ROW_CELLS
        assert row["verdict"] not in NET_ROW_CELLS
    na = d["net_abstention"]
    assert na["statement"] == ("No Amendment 5 net row applies because the "
                               "E-tests abstained.")
    assert na["quote"] == V.A5_ABSTENTION_NOT_NEGATIVE
    assert na["e_pattern"] == e
    assert na["abstained"] == [t for t in V.E_TESTS
                               if e[t] in V.E_ABSTAIN_STATUSES]
    for t in V.E_TESTS:
        assert (f"{t} ({K.E_TEST_STRATUM[t]}) {V.status_words(e[t])}"
                in na["e_note"])
    # The one-line summary states case (b) in words; no net-negative words.
    assert (f"({V.NET_ABSTAINS_WORDS}: {', '.join(na['abstained'])})"
            in out["summary"])
    assert V.PIPELINE_PREDICTS in out["summary"]
    assert V.FINDING_ABOUT_MARKETS not in out["summary"]
    assert "\n" not in out["summary"]


def test_s6_degenerate_case_is_degenerate_not_a_failure():
    d = clears_with(NET_ABSTAINS_CASES["one_degenerate"])["readings"]["primary"]
    assert d["statuses"]["E3"] == V.DEGENERATE
    assert d["net_abstention"]["abstained"] == ["E3"]


def test_s6_abstention_quote_is_amendment_5_byte_exact():
    assert V.VERBATIM_QUOTES["A5_ABSTENTION_NOT_NEGATIVE"] \
        == V.A5_ABSTENTION_NOT_NEGATIVE
    text = EXPERIMENT_MD.read_text(encoding="utf-8")
    assert V.A5_ABSTENTION_NOT_NEGATIVE in text
    section = text[text.index("### The economic secondary family"):
                   text.index("### The band stays")]
    assert V.A5_ABSTENTION_NOT_NEGATIVE in section


def test_s6_clear_selections_unchanged_by_abstentions():
    some = clears_with({"E1": E_CLEAR, "E2": E_SPAN, "E3": E_FLOOR,
                        "E4": E_DEGEN})["readings"]["primary"]
    assert some["outcome_row"] == V.ROW_CLEARS_SOME
    assert some["net_abstention"] is None
    both = clears_with(every(E_CLEAR))["readings"]["primary"]
    assert both["outcome_row"] == V.ROW_CLEARS_BOTH
    assert both["net_abstention"] is None


def test_s6_non_clearing_gross_readings_carry_no_net_abstention():
    for r in (reading(), reading(p={"P1": ptest(t=10.0, se=8.0)}),
              reading(D=45)):
        d = V.decide(results(r))["readings"]["primary"]
        assert d["outcome_row"] in (None, V.ROW_FAILS_GROSS)
        assert d["net_abstention"] is None


def test_s6_sensitivity_reading_uses_the_same_selection():
    out = clears_with(every(E_NEG), sensitivity_e_kw=every(E_SPAN))
    prim, sens = out["readings"]["primary"], out["readings"]["sensitivity"]
    assert prim["outcome_row"] == V.ROW_CLEARS_FAILS_NET
    assert sens["outcome_row"] == V.CLEARS_GROSS_NET_ABSTAINS
    assert sens["net_abstention"]["quote"] == V.A5_ABSTENTION_NOT_NEGATIVE
    dis = out["sensitivity_disagreement"]
    assert dis["differs"] is True
    assert V.NET_ABSTAINS_WORDS in dis["statement"]
    assert V.ROW_383_OUTCOME in dis["statement"]
    assert dis["statement"] in out["summary"]
    # Reversed: the primary abstains on net, the sensitivity reading fails it.
    rev = clears_with(every(E_FLOOR), sensitivity_e_kw=every(E_BELOW))
    assert rev["readings"]["primary"]["outcome_row"] \
        == V.CLEARS_GROSS_NET_ABSTAINS
    assert rev["readings"]["sensitivity"]["outcome_row"] \
        == V.ROW_CLEARS_FAILS_NET
    assert rev["summary"].startswith(
        "Primary reading (governs): clears_gross (" + V.NET_ABSTAINS_WORDS)


def test_c_powered_negative_is_fails_gross():
    d = V.decide(results(reading()))["readings"]["primary"]
    assert outcomes(d) == [V.ROW_385_OUTCOME]
    assert d["statements"] == [V.TASK6_POWERED_NEGATIVE]


def test_c_abstention_has_no_outcome_row_and_task6_words():
    d = V.decide(results(reading(p={"P1": ptest(t=10.0, se=8.0)})))
    d = d["readings"]["primary"]
    assert d["rows"] == [] and d["outcome_row"] is None
    assert d["statements"] == [V.TASK6_ABSTENTION]


def test_c_abstention_floor_has_no_outcome_row():
    d = V.decide(results(reading(D=45)))["readings"]["primary"]
    assert d["rows"] == [] and d["statements"] == [V.TASK5_FLOOR_ABSTENTION]


def test_c_uninformative_row_names_primaries_with_distribution():
    r = reading(minority=0.05, p={"P1": ptest(**CLEAR_P), "P3": ptest(**CLEAR_P)})
    d = V.decide(results(r))["readings"]["primary"]
    assert d["null_informative"] is False
    assert outcomes(d) == [V.ROW_388_OUTCOME]
    row = d["rows"][0]
    assert row["affected"] == ["P1", "P3"]
    assert row["judgment_distribution"]["minority_share"] == 0.05
    assert row["judgment_distribution"]["pooled"]["counts"]["NEUTRAL"] == 30
    assert d["gross"]["gross_reading"] == V.GROSS_ABSTENTION


def test_c_status_words():
    r = reading(p={"P2": ptest(t=-20.0, se=2.0)},
                e={"E4": etest(t=-20.0, se=2.0)})
    d = V.decide(results(r))["readings"]["primary"]
    assert d["status_words"]["P2"] == "significant reversal"
    assert d["status_words"]["E4"] == "net negative"


# ------------------------------------------------------- C.1, C.2, summary

def test_c1_readings_disagree_stated_primary_governs():
    primary = reading(p={"P1": ptest(**CLEAR_P)})
    out = V.decide(results(primary, sensitivity=reading()))
    dis = out["sensitivity_disagreement"]
    assert dis["differs"] is True and dis["quote"] == V.READINGS_DISAGREE_8_2
    assert "disagrees" in dis["statement"] and "primary governs" in dis["statement"]
    assert dis["statement"] in out["summary"]
    assert out["governing_reading"] == "primary"
    assert "\n" not in out["summary"]
    assert out["summary"].startswith("Primary reading (governs): clears_gross")


def test_c1_same_readings_no_disagreement():
    out = V.decide(results(reading()))
    assert out["sensitivity_disagreement"]["differs"] is False
    assert out["sensitivity_disagreement"]["statement"] is None
    assert "disagrees" not in out["summary"]


def test_c1_same_gross_different_row_is_a_disagreement():
    p = reading(p={"P1": ptest(**CLEAR_P)}, e={"E1": etest(**E_CLEAR)})
    s = reading(p={"P1": ptest(**CLEAR_P)})
    out = V.decide(results(p, sensitivity=s))
    assert out["sensitivity_disagreement"]["differs"] is True


def story_block(p_tests):
    return {"fired": True, "readings": {
        "primary_story": {"tests": p_tests},
        "sensitivity_story": {"tests": p_tests}}}


def test_c2_story_difference_stated_session_version_governs():
    base = reading(p={t: ptest(**CLEAR_P) for t in V.PRIMARY_TESTS})
    story_tests = {t: ptest(**CLEAR_P) for t in V.PRIMARY_TESTS}
    story_tests["P2"] = ptest(t=20.0, se=9.0)     # z = 2.2: not_clear
    out = V.decide(results(base, story=story_block(story_tests)))
    st = out["story"]
    assert st["fired"] is True
    assert {(d["reading"], d["test"]) for d in st["differences"]} == {
        ("primary", "P2"), ("sensitivity", "P2")}
    assert "scoring_session-clustered version governs" in st["statement"]
    assert st["statement"] in out["summary"]
    assert out["readings"]["primary"]["statuses"]["P2"] == V.CLEAR


def test_c2_story_same_statuses_no_statement():
    base = reading(p={t: ptest(**CLEAR_P) for t in V.PRIMARY_TESTS})
    tests = {t: ptest(**CLEAR_P) for t in V.PRIMARY_TESTS}
    out = V.decide(results(base, story=story_block(tests)))
    assert out["story"]["differences"] == [] and out["story"]["statement"] is None


def test_c2_story_not_fired():
    out = V.decide(results(reading()))
    assert out["story"] == {"fired": False, "statuses": {}, "differences": [],
                            "statement": None}


def test_wording_rules_in_summary():
    e = {t: etest(**E_NEG) for t in V.E_TESTS}     # net negative everywhere
    out = V.decide(results(reading(p={"P1": ptest(**CLEAR_P)}, e=e)))
    assert V.PIPELINE_PREDICTS in out["summary"]
    assert V.FINDING_ABOUT_MARKETS in out["summary"]   # gross +, net -
    assert "understands" not in out["summary"]
    neg = V.decide(results(reading()))
    assert V.PIPELINE_PREDICTS not in neg["summary"]


def test_decide_reports_8_1_and_8_2_statements_and_strength_label():
    out = V.decide(results(reading()))
    assert out["statements"]["model_cutoff_8_1"] == V.MODEL_CUTOFF_8_1
    assert out["statements"]["closed_end_fund_defect_8_2"]["quote"] \
        == V.CLOSED_END_FUND_DEFECT_8_2
    assert out["statements"]["closed_end_fund_defect_8_2"]["scale"] == {"pairs": 3}
    label = out["readings"]["primary"]["strength_label"]
    assert V.STRENGTH_WEAKER in label and "never confirmation" in label


def test_decide_is_pure_and_deterministic():
    import json
    r = results(reading(p={"P1": ptest(**CLEAR_P)}))
    before = json.dumps(r, sort_keys=True)
    a = json.dumps(V.decide(r), sort_keys=True)
    b = json.dumps(V.decide(r), sort_keys=True)
    assert a == b and json.dumps(r, sort_keys=True) == before
