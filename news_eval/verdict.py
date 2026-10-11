"""From the family's numbers to statuses, the gross reading and the verdict rows (STAGE C.1 Task 4).

Pure: no database, no file, no random number. Input is the dict
news_eval.family.compute returns (or a hand-built dict of the same shape).
Every bar, floor and threshold is read as K.NAME from news_eval.constants at
call time, so a test can move one and see the decision move.

Spec, in order of authority: EXPERIMENT.md (Amendment 5's verdict table, Task 6,
Amendment 6, 8.1, 8.2, 9.2, 9.3, 9.5, 9.10), then reports/c1_verdict_mapping.md
(tables A.1, A.2, A.3, B, C, sections C.1 and C.2, definitions D2 to D8), with
the lead's S6 ruling in reports/c1_rulings.md (D7 revised: a clearing gross
reading whose E-tests abstained selects CLEARS_GROSS_NET_ABSTAINS, not the
fails-net row).

Every sentence quoted from EXPERIMENT.md is held below as a constant, copied
byte for byte with its bold markers and its line breaks where the source wraps
(D24). tests/test_news_eval_verdict.py proves each one is a substring of
EXPERIMENT.md.
"""
from __future__ import annotations

from typing import Any, Mapping

from news_eval import constants as K

# --------------------------------------------------------------- statuses

# A.1 primaries (9.2, 9.3, 9.5, Amendment 6).
ABSTAIN_FLOOR = "abstain_floor"
DEGENERATE = "degenerate"
ABSTAIN_NULL_UNINFORMATIVE = "abstain_null_uninformative"
CLEAR = "clear"
BLOCKED_BY_NULL = "blocked_by_null"
SIGNIFICANT_REVERSAL = "significant_reversal"
NOT_CLEAR = "not_clear"
# A.2 E-tests (Amendment 5, Task 6, 9.10).
BELOW_ECON_BAR = "below_econ_bar"
NET_NEGATIVE = "net_negative"
ABSTAIN_INTERVAL = "abstain_interval"
# A.3 strength tests (9.10).
ABSTAIN_EMPTY_POOL = "abstain_empty_pool"

# A.1: "Bootstrap bar met" means statuses 3, 4 and 5.
BAR_MET_STATUSES = (ABSTAIN_NULL_UNINFORMATIVE, CLEAR, BLOCKED_BY_NULL)
NULL_INTERCEPTED_STATUSES = (ABSTAIN_NULL_UNINFORMATIVE, BLOCKED_BY_NULL)

# S6 ruling (reports/c1_rulings.md, D7 revised): with no E-test clear, an
# E-test fails the net question when it is net_negative or below_econ_bar
# (Task 6: "fails the economic question even if its interval excludes
# zero"); abstain_interval, abstain_floor and degenerate are abstentions
# (Amendment 5: "a wide interval spanning zero is an abstention, not a
# negative").
E_FAILS_NET_STATUSES = (NET_NEGATIVE, BELOW_ECON_BAR)
E_ABSTAIN_STATUSES = (ABSTAIN_INTERVAL, ABSTAIN_FLOOR, DEGENERATE)

# B gross readings (Task 5 floor, Task 6, 9.5).
GROSS_ABSTENTION_FLOOR = "abstention_floor"
GROSS_CLEARS = "clears_gross"
GROSS_POWERED_NEGATIVE = "powered_negative"
GROSS_ABSTENTION = "abstention"

# B row 4: which abstention applies (reported, several may hold).
REASON_D_BELOW_FLOOR = "D_below_floor"
REASON_M_BELOW_FLOOR = "M_below_floor"
REASON_INTERVAL_ZERO_AND_EFFECT = "p1_interval_includes_zero_and_30bp"
REASON_NULL_INTERCEPTED = "positive_intercepted_by_null"
REASON_P1_DEGENERATE = "p1_degenerate"
REASON_P1_FLOOR = "p1_abstain_floor"

PRIMARY_TESTS = ("P1", "P2", "P3", "P4")
E_TESTS = ("E1", "E2", "E3", "E4")
STRENGTH_TESTS = ("S1", "S2")
READINGS = ("primary", "sensitivity")
STORY_READINGS = {"primary": "primary_story", "sensitivity": "sensitivity_story"}
GOVERNING_READING = "primary"

# C row keys (Amendment 5 table rows, by outcome).
ROW_CLEARS_FAILS_NET = "clears_gross_fails_net_every_stratum"
ROW_CLEARS_SOME = "clears_gross_net_clears_some_strata"
ROW_FAILS_GROSS = "fails_gross"
ROW_CLEARS_BOTH = "clears_gross_and_net"
ROW_ANY_GROSS_POSITIVE = "any_gross_positive_amendment_6"
ROW_NULL_UNINFORMATIVE = "permutation_null_uninformative"
OUTCOME_ROWS = (ROW_CLEARS_FAILS_NET, ROW_CLEARS_SOME, ROW_FAILS_GROSS,
                ROW_CLEARS_BOTH)
# S6 ruling: the selection when the gross reading clears, no E-test is clear
# and at least one E-test abstained. It is NOT an Amendment 5 row and has no
# VERDICT_TABLE entry: no Amendment 5 net row is quoted, the Amendment 6 row
# still is, and the reading carries "net_abstention" (see net_abstention()).
CLEARS_GROSS_NET_ABSTAINS = "clears_gross_net_abstains"

# ------------------------------------------- verbatim quotes (D24, byte exact)

# Amendment 5 verdict table, EXPERIMENT.md lines 383 to 388: outcome cell and
# verdict cell of each row.
ROW_383_OUTCOME = "Clears gross, fails net in every stratum"
ROW_383_VERDICT = (
    "**The signal exists and is not tradeable at taker execution at this "
    "sizing. A finding about markets, not a strategy. The correct response is "
    "not to trade it anyway.** The named next step is the maker-execution "
    "measurement below, under its own pre-registration.")
ROW_384_OUTCOME = "Clears gross, net clears in some strata and fails in S3/S4"
ROW_384_VERDICT = (
    "The signal exists band-wide and is tradeable where the E-tests cleared. "
    "Trading only the cleared strata is permitted ONLY as a new pre-registered "
    "deployment decision with its own capacity arithmetic. It is never a "
    "post-hoc restriction of this result.")
ROW_385_OUTCOME = "Fails gross"
ROW_385_VERDICT = (
    "**The hypothesis is dead** per the powered-negative definition (Task 6, "
    "gross). It is not re-tested with a different horizon, prompt or band.")
ROW_386_OUTCOME = "Clears gross and net"
ROW_386_VERDICT = (
    "Proceed per the capacity gate, which still separates a finding from a "
    "strategy at the configured sizing.")
ROW_387_OUTCOME = "Any gross positive, whatever net says (AMENDMENT 6)"
ROW_387_VERDICT = (
    "**Supports \"this pipeline's judgment predicts next-session drift on the "
    "names its news source covers\", and never \"the model understands the "
    "news.\"** No baseline comparator exists, so attribution to model "
    "capability is unavailable by design. The comparator the stronger claim "
    "would need is recorded in Amendment 6 and is not added. The conclusion "
    "is worded as \"the pipeline predicts\" everywhere it is reported.")
ROW_388_OUTCOME = ("The permutation null is UNINFORMATIVE under the "
                   "Amendment 6 thresholds")
ROW_388_VERDICT = (
    "**The affected primary is an abstention**, not a negative and not a "
    "positive, reported in those words with the realised judgment "
    "distribution beside it.")

VERDICT_TABLE = {
    ROW_CLEARS_FAILS_NET: (ROW_383_OUTCOME, ROW_383_VERDICT),
    ROW_CLEARS_SOME: (ROW_384_OUTCOME, ROW_384_VERDICT),
    ROW_FAILS_GROSS: (ROW_385_OUTCOME, ROW_385_VERDICT),
    ROW_CLEARS_BOTH: (ROW_386_OUTCOME, ROW_386_VERDICT),
    ROW_ANY_GROSS_POSITIVE: (ROW_387_OUTCOME, ROW_387_VERDICT),
    ROW_NULL_UNINFORMATIVE: (ROW_388_OUTCOME, ROW_388_VERDICT),
}

# Task 6, lines 2172 to 2177: the powered-negative definition.
TASK6_POWERED_NEGATIVE = (
    "**A powered negative:** at 60 or more day clusters, the pooled GROSS "
    "excess\ninterval's upper bound sits below the assumed 30 bp gross effect "
    "while no\nprimary test clears `|z| >= 2.50`. This mirrors the council "
    "measurement that\nproduced this project's first powered negative, and "
    "the hypothesis is then\ndead. It is not re-tested with a different "
    "horizon, prompt, or band, because\neach of those is a new hypothesis "
    "needing its own pre-registration.")
# Task 6, lines 2179 and 2180: the abstention sentence.
TASK6_ABSTENTION = (
    "**An interval that includes both zero and 30 bp gross at the cluster "
    "floor is\nan abstention, not a negative and not a finding.**")
# Task 5 "The bar", lines 2031 to 2032 (mapping B row 1).
TASK5_FLOOR_ABSTENTION = (
    "Below that the\n  result is an abstention regardless of the point "
    "estimate")
# Amendment 6, lines 523 to 524 (mapping B row 4).
A6_ABSTAIN_RATHER_THAN_PROMOTE = (
    "a design that cannot tell them apart should\nabstain rather than "
    "promote")
# 9.3: a z at or below -2.50 is reported "in those words".
SIGNIFICANT_REVERSAL_WORDS = "significant reversal"
# 9.10: an E-test z at or below -2.50 is reported as "net negative".
NET_NEGATIVE_WORDS = "net negative"
# Amendment 5 table row 387 and 9.15: the wording of any gross positive.
PIPELINE_PREDICTS = "the pipeline predicts"
# Amendment 5, line 391: a gross-positive net-negative result's words.
FINDING_ABOUT_MARKETS = "a finding about markets"
# Amendment 5, line 342 (the economic family's power statement): quoted when
# the E-tests abstained and no Amendment 5 net row applies (S6 ruling).
A5_ABSTENTION_NOT_NEGATIVE = (
    "a wide interval spanning zero is an abstention, not a negative")
# 8.1, lines 735 to 737.
MODEL_CUTOFF_8_1 = (
    "**Every scored headline postdates the\nmodel's training data by about a "
    "year, so a positive result cannot come from\nthe model recalling the "
    "event or its aftermath.**")
# 8.2, lines 768 to 772: the closed-end-fund defect.
CLOSED_END_FUND_DEFECT_8_2 = (
    "**The closed-end funds are a defect in the fund exclusion**, the same "
    "class\nas the admit-by-default fund classifier recorded in Task 7: "
    "closed-end funds\nlist as ordinary shares, so an exclusion built on the "
    "ETF flag admits them.\nThe collector is not changed mid-collection. "
    "Stage C reports the defect, its\nscale, and the sensitivity result "
    "together.")
# 8.2, lines 774 to 777: when the two readings disagree.
READINGS_DISAGREE_8_2 = (
    "**When the two readings disagree.** If the primary and the excluded "
    "version\nreach different verdicts under the pre-registered verdict "
    "table, both are\nreported side by side, the primary governs, and the "
    "one-line summary states\nthe disagreement in words. Neither reading is "
    "dropped.")
# Task 5 (line 2101) and Task 5 Amendment 3 (line 2061): the strength label.
STRENGTH_WEAKER = "weaker evidence than a primary that clears 2.50"
STRENGTH_SELF_KNOWLEDGE = "a property of the model's self-knowledge"

VERBATIM_QUOTES = {
    "ROW_383_OUTCOME": ROW_383_OUTCOME, "ROW_383_VERDICT": ROW_383_VERDICT,
    "ROW_384_OUTCOME": ROW_384_OUTCOME, "ROW_384_VERDICT": ROW_384_VERDICT,
    "ROW_385_OUTCOME": ROW_385_OUTCOME, "ROW_385_VERDICT": ROW_385_VERDICT,
    "ROW_386_OUTCOME": ROW_386_OUTCOME, "ROW_386_VERDICT": ROW_386_VERDICT,
    "ROW_387_OUTCOME": ROW_387_OUTCOME, "ROW_387_VERDICT": ROW_387_VERDICT,
    "ROW_388_OUTCOME": ROW_388_OUTCOME, "ROW_388_VERDICT": ROW_388_VERDICT,
    "TASK6_POWERED_NEGATIVE": TASK6_POWERED_NEGATIVE,
    "TASK6_ABSTENTION": TASK6_ABSTENTION,
    "TASK5_FLOOR_ABSTENTION": TASK5_FLOOR_ABSTENTION,
    "A6_ABSTAIN_RATHER_THAN_PROMOTE": A6_ABSTAIN_RATHER_THAN_PROMOTE,
    "SIGNIFICANT_REVERSAL_WORDS": SIGNIFICANT_REVERSAL_WORDS,
    "NET_NEGATIVE_WORDS": NET_NEGATIVE_WORDS,
    "PIPELINE_PREDICTS": PIPELINE_PREDICTS,
    "FINDING_ABOUT_MARKETS": FINDING_ABOUT_MARKETS,
    "A5_ABSTENTION_NOT_NEGATIVE": A5_ABSTENTION_NOT_NEGATIVE,
    "MODEL_CUTOFF_8_1": MODEL_CUTOFF_8_1,
    "CLOSED_END_FUND_DEFECT_8_2": CLOSED_END_FUND_DEFECT_8_2,
    "READINGS_DISAGREE_8_2": READINGS_DISAGREE_8_2,
    "STRENGTH_WEAKER": STRENGTH_WEAKER,
    "STRENGTH_SELF_KNOWLEDGE": STRENGTH_SELF_KNOWLEDGE,
}

# Status words used in reports where EXPERIMENT.md fixes the words.
STATUS_WORDS = {
    SIGNIFICANT_REVERSAL: SIGNIFICANT_REVERSAL_WORDS,
    NET_NEGATIVE: NET_NEGATIVE_WORDS,
}

# The label every strength result carries (A.3; Task 5 Amendment 3, Amendment 5).
STRENGTH_LABEL = (f"{STRENGTH_WEAKER}; {STRENGTH_SELF_KNOWLEDGE}; never "
                  "confirmation of the hypothesis")

# S6 ruling: the words for CLEARS_GROSS_NET_ABSTAINS (template text, not a
# quote), used in the report, the 8.2 disagreement and the one-line summary.
NET_ABSTAINS_WORDS = ("no Amendment 5 net row applies because the E-tests "
                      "abstained")


# ------------------------------------------------------ number primitives

def null_informative(minority_share: float | None, n_mixed: int | None) -> bool:
    """Amendment 6 skew diagnostic with D2: the null is informative only when
    the pooled minority directional share is at least
    K.NULL_MIN_MINORITY_SHARE and at least K.NULL_MIN_MIXED_CLUSTERS clusters
    are mixed. No directional row at all is uninformative."""
    if minority_share is None or n_mixed is None:
        return False
    return (float(minority_share) >= K.NULL_MIN_MINORITY_SHARE
            and int(n_mixed) >= K.NULL_MIN_MIXED_CLUSTERS)


def estimate(boot: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """(T, SE) of a usable 9.5 bootstrap, else None (9.5: an SE of zero or
    fewer than 2 clusters is the named refusal "degenerate")."""
    if not boot or boot.get("status") != "ok":
        return None
    t, se = boot.get("statistic"), boot.get("se")
    if t is None or se is None or not float(se) > 0:
        return None
    if int(boot.get("n_clusters", 0)) < 2:
        return None
    return float(t), float(se)


def interval(t: float, se: float, bar: float) -> tuple[float, float]:
    """9.5: T plus or minus bar x SE."""
    return t - bar * se, t + bar * se


def bar_met(t: float, se: float, bar: float) -> bool:
    """9.3 with 9.5 and D3: z >= +bar AND T - bar x SE > 0, conjunctively."""
    return t / se >= bar and t - bar * se > 0


def upper_tail(perm: Mapping[str, Any] | None) -> bool | None:
    """9.3 with D4: the observed statistic is in the upper tail of the null
    when count(T_perm >= T_obs) is STRICTLY below count(T_perm <= T_obs).
    None when the null was not computed."""
    if not perm or perm.get("status") != "ok":
        return None
    ge, le = perm.get("count_ge"), perm.get("count_le")
    if ge is None or le is None:
        return None
    return int(ge) < int(le)


def permutation_confirms(perm: Mapping[str, Any] | None) -> bool:
    """Amendment 6 with 9.3: p <= K.BAR_PERM_P and the upper tail. A null
    that was not computed confirms nothing."""
    if not perm or perm.get("status") != "ok" or perm.get("p") is None:
        return False
    return float(perm["p"]) <= K.BAR_PERM_P and upper_tail(perm) is True


# ------------------------------------------------------- per-test status

def primary_status(test: Mapping[str, Any], informative: bool) -> str:
    """Mapping A.1 (9.2, 9.3, 9.5, Amendment 6, D3, D4), first row that applies.

    test: one family primary dict ("n_clusters" is the count of
    scoring_session clusters holding the test's scored observations, the 9.2
    floor's count; "bootstrap" and "permutation" are the stats results).
    informative: the reading's single D2 determination."""
    if int(test["n_clusters"]) < K.FLOOR_TEST_CLUSTERS:
        return ABSTAIN_FLOOR
    tse = estimate(test.get("bootstrap"))
    if tse is None:
        return DEGENERATE
    t, se = tse
    if bar_met(t, se, K.BAR_PRIMARY_Z):
        if not informative:
            return ABSTAIN_NULL_UNINFORMATIVE
        if permutation_confirms(test.get("permutation")):
            return CLEAR
        return BLOCKED_BY_NULL
    if t / se <= -K.BAR_PRIMARY_Z:
        return SIGNIFICANT_REVERSAL
    return NOT_CLEAR


def e_status(test: Mapping[str, Any]) -> str:
    """Mapping A.2 (Amendment 5, Task 6 4.96 bp, 9.4, 9.10, D8), first row
    that applies. "n_clusters" counts clusters holding the stratum's scored
    observations with non-null net_bp."""
    if int(test["n_clusters"]) < K.FLOOR_TEST_CLUSTERS:
        return ABSTAIN_FLOOR
    tse = estimate(test.get("bootstrap"))
    if tse is None:
        return DEGENERATE
    t, se = tse
    if bar_met(t, se, K.BAR_PRIMARY_Z):
        return CLEAR if t >= K.ECON_BAR_BP else BELOW_ECON_BAR
    if t / se <= -K.BAR_PRIMARY_Z:
        return NET_NEGATIVE
    return ABSTAIN_INTERVAL


def strength_status(test: Mapping[str, Any],
                    analysis_clusters: int | None = None) -> str:
    """Mapping A.3 (Task 5 Amendment 3, 9.2, 9.10, D15), first row that
    applies. "n_clusters" counts clusters holding scored observations with
    strength_parse_ok = 1. A z at or below -2.24 is not_clear, reported with
    its sign.

    analysis_clusters: the reading's D. Task 5 Amendment 3 runs S1 and S2
    "under the same 60-cluster floor", which 9.2 keeps as the floor gating
    the analysis set as a whole, so D below K.FLOOR_ANALYSIS_CLUSTERS is
    abstain_floor too (HarnessCoder: EXPERIMENT.md applied where mapping
    A.3 lists only the 30-cluster row; reported to the lead)."""
    if analysis_clusters is not None \
            and int(analysis_clusters) < K.FLOOR_ANALYSIS_CLUSTERS:
        return ABSTAIN_FLOOR
    if int(test["n_clusters"]) < K.FLOOR_TEST_CLUSTERS:
        return ABSTAIN_FLOOR
    boot = test.get("bootstrap") or {}
    if boot.get("status") == ABSTAIN_EMPTY_POOL:
        return ABSTAIN_EMPTY_POOL
    tse = estimate(boot)
    if tse is None:
        return DEGENERATE
    t, se = tse
    if bar_met(t, se, K.BAR_STRENGTH_Z):
        return CLEAR
    return NOT_CLEAR


def status_words(status: str) -> str:
    """The words a status is reported in (9.3 "significant reversal", 9.10
    "net negative"); every other status is reported by its name."""
    return STATUS_WORDS.get(status, status)


# ------------------------------------------------------ the gross reading

def gross_reading(reading: Mapping[str, Any],
                  p_statuses: Mapping[str, str]) -> dict:
    """Mapping B (Task 5 floor, Task 6, Amendment 6 note, 9.2, 9.3, 9.5, D5,
    D19), first row that applies, for one reading.

    reading: the family reading dict ("D", "M", "tests"["P1"]).
    Returns the gross reading, P1's interval at K.BAR_PRIMARY_Z, and under
    row 1 or row 4 every reason that applies."""
    d, m = int(reading["D"]), int(reading["M"])
    tse = estimate(reading["tests"]["P1"].get("bootstrap"))
    lower = upper = None
    if tse is not None:
        lower, upper = interval(tse[0], tse[1], K.BAR_PRIMARY_Z)
    out = {"D": d, "M": m, "p1_lower": lower, "p1_upper": upper,
           "effect_bp": K.EFFECT_BP, "reasons": []}
    floor_reasons = []
    if d < K.FLOOR_ANALYSIS_CLUSTERS:
        floor_reasons.append(REASON_D_BELOW_FLOOR)
    if m < K.FLOOR_SCORABLE:
        floor_reasons.append(REASON_M_BELOW_FLOOR)
    if floor_reasons:
        return {**out, "gross_reading": GROSS_ABSTENTION_FLOOR,
                "reasons": floor_reasons}
    if any(p_statuses[t] == CLEAR for t in PRIMARY_TESTS):
        return {**out, "gross_reading": GROSS_CLEARS}
    any_bar_met = any(p_statuses[t] in BAR_MET_STATUSES for t in PRIMARY_TESTS)
    if (p_statuses["P1"] in (NOT_CLEAR, SIGNIFICANT_REVERSAL)
            and not any_bar_met and upper is not None
            and upper < K.EFFECT_BP):
        return {**out, "gross_reading": GROSS_POWERED_NEGATIVE}
    reasons = []
    if lower is not None and lower <= 0 and upper >= K.EFFECT_BP:
        reasons.append(REASON_INTERVAL_ZERO_AND_EFFECT)
    if any(p_statuses[t] in NULL_INTERCEPTED_STATUSES for t in PRIMARY_TESTS):
        reasons.append(REASON_NULL_INTERCEPTED)
    if p_statuses["P1"] == DEGENERATE:
        reasons.append(REASON_P1_DEGENERATE)
    if p_statuses["P1"] == ABSTAIN_FLOOR:
        reasons.append(REASON_P1_FLOOR)
    return {**out, "gross_reading": GROSS_ABSTENTION, "reasons": reasons}


# ------------------------------------------------------------ verdict rows

def _row(key: str, notes: list[str] | None = None, **extra: Any) -> dict:
    outcome, verdict_text = VERDICT_TABLE[key]
    return {"key": key, "outcome": outcome, "verdict": verdict_text,
            "notes": list(notes or []), **extra}


def judgment_distribution(reading: Mapping[str, Any]) -> dict:
    """The realised judgment distribution printed beside the UNINFORMATIVE
    row (Amendment 5 row 388, Amendment 6): pooled counts and shares, the
    minority share and the mixed clusters."""
    diag = reading.get("diagnostics") or {}
    null = reading.get("null") or {}
    return {"pooled": diag.get("pooled"),
            "minority_share": null.get("minority_share"),
            "n_mixed_clusters": null.get("n_mixed_clusters")}


def _e_note(e_pattern: Mapping[str, str]) -> str:
    """Every stratum's E-test status, in the words EXPERIMENT.md fixes."""
    return "E-test status per stratum: " + ", ".join(
        f"{t} ({K.E_TEST_STRATUM[t]}) {status_words(s)}"
        for t, s in e_pattern.items())


def net_abstention(selected: str | None,
                   e_statuses: Mapping[str, str]) -> dict | None:
    """S6 ruling: under CLEARS_GROSS_NET_ABSTAINS, the statement that no
    Amendment 5 net row applies, every stratum's status, the E-tests that
    abstained, and Amendment 5's sentence verbatim. None for any other
    selection."""
    if selected != CLEARS_GROSS_NET_ABSTAINS:
        return None
    e_pattern = {t: e_statuses[t] for t in E_TESTS}
    return {"statement": NET_ABSTAINS_WORDS[0].upper()
            + NET_ABSTAINS_WORDS[1:] + ".",
            "e_pattern": e_pattern,
            "e_note": _e_note(e_pattern),
            "abstained": [t for t in E_TESTS
                          if e_pattern[t] in E_ABSTAIN_STATUSES],
            "quote": A5_ABSTENTION_NOT_NEGATIVE}


def verdict_rows(gross: Mapping[str, Any], p_statuses: Mapping[str, str],
                 e_statuses: Mapping[str, str],
                 distribution: Mapping[str, Any] | None = None
                 ) -> tuple[list[dict], str | None, list[str]]:
    """Mapping C (Amendment 5's table, Task 6, D6, D7 as revised by the S6
    ruling): the rows reported for one reading, the selection (an Amendment
    5 outcome row key, CLEARS_GROSS_NET_ABSTAINS, or None under an
    abstention) and the statements in Task 6's words where they apply."""
    rows: list[dict] = []
    statements: list[str] = []
    selected: str | None = None
    g = gross["gross_reading"]
    e_pattern = {t: e_statuses[t] for t in E_TESTS}
    e_note = _e_note(e_pattern)
    if g == GROSS_CLEARS:
        n_clear = sum(1 for s in e_pattern.values() if s == CLEAR)
        if n_clear == 0 and all(s in E_FAILS_NET_STATUSES
                                for s in e_pattern.values()):
            # S6 (a): every E-test net_negative or below_econ_bar.
            selected = ROW_CLEARS_FAILS_NET
            rows.append(_row(selected, [e_note], e_pattern=e_pattern))
        elif n_clear == 0:
            # S6 (b): an E-test abstained; no Amendment 5 net row applies.
            selected = CLEARS_GROSS_NET_ABSTAINS
        elif n_clear < len(E_TESTS):
            selected = ROW_CLEARS_SOME
            notes = [e_note]
            thin_cleared = [t for t in E_TESTS
                            if K.E_TEST_STRATUM[t] in K.THIN_END
                            and e_pattern[t] == CLEAR]
            if thin_cleared:
                notes.append(
                    "The realised per-stratum pattern differs from the row's "
                    "description (\"fails in S3/S4\"): "
                    + ", ".join(f"{t} ({K.E_TEST_STRATUM[t]})"
                                for t in thin_cleared)
                    + " cleared. The row's sentence (\"tradeable where the "
                    "E-tests cleared\") is the one applied.")
            rows.append(_row(selected, notes, e_pattern=e_pattern))
        else:
            selected = ROW_CLEARS_BOTH
            rows.append(_row(selected, [e_note], e_pattern=e_pattern))
        rows.append(_row(ROW_ANY_GROSS_POSITIVE))
    elif g == GROSS_POWERED_NEGATIVE:
        selected = ROW_FAILS_GROSS
        rows.append(_row(selected, [e_note], e_pattern=e_pattern))
        statements.append(TASK6_POWERED_NEGATIVE)
    elif g == GROSS_ABSTENTION_FLOOR:
        statements.append(TASK5_FLOOR_ABSTENTION)
    else:
        if REASON_INTERVAL_ZERO_AND_EFFECT in gross["reasons"]:
            statements.append(TASK6_ABSTENTION)
        if REASON_NULL_INTERCEPTED in gross["reasons"]:
            statements.append(A6_ABSTAIN_RATHER_THAN_PROMOTE)
    affected = [t for t in PRIMARY_TESTS
                if p_statuses[t] == ABSTAIN_NULL_UNINFORMATIVE]
    if affected:
        rows.append(_row(ROW_NULL_UNINFORMATIVE,
                         ["Affected primaries: " + ", ".join(affected)],
                         affected=affected,
                         judgment_distribution=dict(distribution or {})))
    return rows, selected, statements


# --------------------------------------------------------------- readings

def decide_reading(reading: Mapping[str, Any]) -> dict:
    """Statuses (A.1, A.2, A.3), the gross reading (B) and the rows (C) for
    one reading (primary or 8.2 sensitivity; D19 applies the B floors to the
    reading's own D and M)."""
    null = reading.get("null") or {}
    informative = null_informative(null.get("minority_share"),
                                   null.get("n_mixed_clusters"))
    tests = reading["tests"]
    p = {t: primary_status(tests[t], informative) for t in PRIMARY_TESTS}
    e = {t: e_status(tests[t]) for t in E_TESTS}
    s = {t: strength_status(tests[t], reading["D"]) for t in STRENGTH_TESTS}
    gross = gross_reading(reading, p)
    rows, selected, statements = verdict_rows(
        gross, p, e, judgment_distribution(reading))
    statuses = {**p, **e, **s}
    return {
        "null_informative": informative,
        "statuses": statuses,
        "status_words": {t: status_words(v) for t, v in statuses.items()},
        "bootstrap_bar_met": {t: p[t] in BAR_MET_STATUSES
                              for t in PRIMARY_TESTS},
        "gross": gross,
        "rows": rows,
        "outcome_row": selected,
        "net_abstention": net_abstention(selected, e),
        "statements": statements,
        "strength_label": STRENGTH_LABEL,
    }


def _row_words(key: str | None) -> str:
    if key is None:
        return "no Amendment 5 outcome row"
    if key == CLEARS_GROSS_NET_ABSTAINS:
        return NET_ABSTAINS_WORDS
    return f"row \"{VERDICT_TABLE[key][0]}\""


def readings_disagreement(primary: Mapping[str, Any],
                          sensitivity: Mapping[str, Any]) -> dict:
    """Mapping C.1 (8.2 "When the two readings disagree"): the readings
    differ when their gross readings or their selected outcome rows differ.
    Both stay reported; the primary governs."""
    pg = primary["gross"]["gross_reading"]
    sg = sensitivity["gross"]["gross_reading"]
    pr, sr = primary["outcome_row"], sensitivity["outcome_row"]
    differs = pg != sg or pr != sr
    statement = None
    if differs:
        statement = (
            f"The 8.2 sensitivity reading disagrees with the primary reading: "
            f"the primary reading is {pg} ({_row_words(pr)}) and the "
            f"sensitivity reading is {sg} ({_row_words(sr)}); both are "
            f"reported side by side and the primary governs.")
    return {"differs": differs, "statement": statement,
            "quote": READINGS_DISAGREE_8_2}


def story_comparison(results: Mapping[str, Any],
                     decided: Mapping[str, Mapping[str, Any]]) -> dict:
    """Mapping C.2 (Task 5, 9.10, D11): when the story trigger fired, P1 to
    P4 of each reading are also given statuses on the story-group version,
    with the reading's own D2 determination. The scoring_session-clustered
    version governs; any primary whose status differs is named."""
    story = results.get("story") or {}
    if not story.get("fired"):
        return {"fired": False, "statuses": {}, "differences": [],
                "statement": None}
    statuses: dict[str, dict[str, str]] = {}
    differences: list[dict] = []
    for name in READINGS:
        story_name = STORY_READINGS[name]
        tests = story["readings"][story_name]["tests"]
        informative = decided[name]["null_informative"]
        st = {t: primary_status(tests[t], informative) for t in PRIMARY_TESTS}
        statuses[story_name] = st
        for t in PRIMARY_TESTS:
            base = decided[name]["statuses"][t]
            if st[t] != base:
                differences.append({"reading": name, "test": t,
                                    "scoring_session_version": base,
                                    "story_group_version": st[t]})
    statement = None
    if differences:
        statement = (
            "The story-group version differs from the scoring_session-"
            "clustered version: " + "; ".join(
                f"{d['test']} ({d['reading']} reading) "
                f"{status_words(d['scoring_session_version'])} against "
                f"{status_words(d['story_group_version'])}"
                for d in differences)
            + "; the scoring_session-clustered version governs.")
    return {"fired": True, "statuses": statuses, "differences": differences,
            "statement": statement}


def _reading_phrase(name: str, decided: Mapping[str, Any]) -> str:
    g = decided["gross"]["gross_reading"]
    row = decided["outcome_row"]
    phrase = f"{name}: {g}"
    if row == CLEARS_GROSS_NET_ABSTAINS:
        abstained = (decided.get("net_abstention") or {}).get("abstained")
        phrase += (f" ({NET_ABSTAINS_WORDS}"
                   + (f": {', '.join(abstained)}" if abstained else "") + ")")
    elif row is not None:
        phrase += f" ({VERDICT_TABLE[row][0]})"
    if g == GROSS_CLEARS:
        phrase += f"; {PIPELINE_PREDICTS}"
        if row == ROW_CLEARS_FAILS_NET:
            phrase += f", {FINDING_ABOUT_MARKETS}"
    affected = [t for t in PRIMARY_TESTS
                if decided["statuses"][t] == ABSTAIN_NULL_UNINFORMATIVE]
    if affected:
        phrase += ("; permutation null UNINFORMATIVE, abstention on "
                   + ", ".join(affected))
    return phrase


def summary_line(decided: Mapping[str, Mapping[str, Any]],
                 disagreement: Mapping[str, Any],
                 story: Mapping[str, Any]) -> str:
    """The one-line summary (C.1, C.2): the primary reading governs, the
    sensitivity reading beside it, and any disagreement stated in words."""
    parts = [_reading_phrase("Primary reading (governs)", decided["primary"]),
             _reading_phrase("8.2 sensitivity reading",
                             decided["sensitivity"])]
    if disagreement["differs"]:
        parts.append(disagreement["statement"])
    if story.get("statement"):
        parts.append(story["statement"])
    return ". ".join(p.rstrip(".") for p in parts) + "."


def decide(results: Mapping[str, Any]) -> dict:
    """The verdict for a family results dict (mapping A, B, C, C.1, C.2).

    Per reading: statuses, the gross reading, the rows and the statements.
    Then the 8.2 disagreement, the story-group comparison, the one-line
    summary (the primary governs), and the 8.1 and 8.2 statements Stage C
    reports with the verdict."""
    decided = {name: decide_reading(results["readings"][name])
               for name in READINGS}
    disagreement = readings_disagreement(decided["primary"],
                                         decided["sensitivity"])
    story = story_comparison(results, decided)
    sens = results.get("sensitivity_exclusion") or {}
    return {
        "governing_reading": GOVERNING_READING,
        "readings": decided,
        "sensitivity_disagreement": disagreement,
        "story": story,
        "summary": summary_line(decided, disagreement, story),
        "statements": {
            "model_cutoff_8_1": MODEL_CUTOFF_8_1,
            "closed_end_fund_defect_8_2": {
                "quote": CLOSED_END_FUND_DEFECT_8_2,
                "scale": sens.get("rule_b_scale")},
            "wording": {"gross_positive": PIPELINE_PREDICTS,
                        "gross_positive_net_negative": FINDING_ABOUT_MARKETS},
        },
    }
