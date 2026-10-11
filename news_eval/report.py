"""The C.2 verdict report: a fixed markdown template filled from computed numbers (STAGE C.1 Task 6).

EXPERIMENT.md 9.15 ("diagnostics first, each primary beside its 8.2
sensitivity reading, verdict rows quoted from Amendment 5's table, and the
wording 'the pipeline predicts'"), Amendment 5, Amendment 6, 8.1, 8.2, 8.3,
9.10, 9.12, 9.13; reports/c1_verdict_mapping.md C, C.1, C.2.

    write(results, decision, *, relevance_summary, companion=None,
          run_meta=None) -> str

`results` is news_eval.family.compute's dict, `decision` is
news_eval.verdict.decide's, `relevance_summary` is news_eval.relevance's
summarize JSON, `companion` is family.companion_horizons's dict (passed only
when the 9.12 condition holds), `run_meta` is the runner's provenance. Every
sentence is template text or a verbatim EXPERIMENT.md quote held in
news_eval.verdict; data contributes numbers, status keys and the categorical
labels symbol and sector only (escaped). Section order is SECTIONS. The same
inputs give the same text (no clock, no dict-order dependence).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from news_eval import constants as K
from news_eval import family
from news_eval import relevance
from news_eval import verdict as V

TITLE = "# Stage C.2 verdict report: the news-drift experiment"
H_DIAGNOSTICS = "## 1. Diagnostics (Amendment 6)"
H_ANALYSIS = "## 2. The analysis set (9.1, 9.7)"
H_PRIMARIES = "## 3. Primary tests P1 to P4, each beside its 8.2 sensitivity reading"
H_VERDICT = "## 4. Gross reading and verdict rows (Amendment 5, Task 6)"
H_CUTOFF = "## 5. Model cutoff (8.1)"
H_DEFECT = "## 6. The closed-end-fund defect and the 8.2 exclusion scale"
H_SECONDARIES = ("## 7. Weaker secondaries: E-tests and strength tests "
                 "(cannot confirm the hypothesis)")
H_RELEVANCE = "## 8. Relevance rates (8.3, 9.13)"
H_ROBUSTNESS = "## 9. Robustness figures: sector and story groups (9.10)"
H_COMPANION = "## 10. Companion horizons (9.12): EXPLORATORY"
H_PROVENANCE = "## Provenance"
SECTIONS = (H_DIAGNOSTICS, H_ANALYSIS, H_PRIMARIES, H_VERDICT, H_CUTOFF,
            H_DEFECT, H_SECONDARIES, H_RELEVANCE, H_ROBUSTNESS, H_COMPANION,
            H_PROVENANCE)

READINGS = V.READINGS
JUDGMENT_KEYS = (K.POSITIVE, K.NEGATIVE, K.NEUTRAL, "other")
RELEVANCE_VARIANTS = (relevance.VARIANT_ALL, relevance.VARIANT_A,
                      relevance.VARIANT_A_B1, relevance.VARIANT_A_B2)
GRADE_SETS = ("opus", "fable", "final")
NA = "n/a"


# ------------------------------------------------------------- formatting

def _num(x: Any, nd: int = 2) -> str:
    if x is None:
        return NA
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int):
        return str(x)
    return f"{float(x):.{nd}f}"


def _pct(x: Any, nd: int = 1) -> str:
    return NA if x is None else f"{100.0 * float(x):.{nd}f} percent"


def _yes(x: Any) -> str:
    return NA if x is None else ("yes" if x else "no")


def _label(x: Any) -> str:
    """A categorical label from data (symbol, sector), table-safe."""
    text = NA if x is None else str(x)
    return " ".join(text.split()).replace("|", "\\|").replace("`", "'")


def _interval(lo: Any, hi: Any, nd: int = 2) -> str:
    return NA if lo is None or hi is None else f"[{_num(lo, nd)}, {_num(hi, nd)}]"


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _quote(source: str, text: str) -> list[str]:
    """A verbatim EXPERIMENT.md quote, bytes unchanged (D24)."""
    return [f"Quoted verbatim from EXPERIMENT.md, {source}:", "", text, ""]


def _status(decision: Mapping, reading: str, test: str) -> str:
    return decision["readings"][reading]["status_words"][test]


def _keys(mapping: Mapping, first: Sequence[str]) -> list[str]:
    """`first` in order, then any other keys sorted (deterministic)."""
    return [k for k in first if k in mapping] + sorted(
        k for k in mapping if k not in first)


# ------------------------------------------------------------ 1 diagnostics

def _dist_row(name: str, block: Mapping | None) -> list[str]:
    block = block or {}
    counts, shares = block.get("counts") or {}, block.get("shares") or {}
    cells = [f"{_num(counts.get(k))} ({_pct(shares.get(k))})"
             for k in JUDGMENT_KEYS]
    return [name, *cells, _num(block.get("total"))]


def _diagnostics(results: Mapping, decision: Mapping) -> list[str]:
    out = [H_DIAGNOSTICS, "",
           "Judgment counts and shares are over rows meeting every scorable "
           "condition except the judgment condition (D20). The minority share "
           "and mixed clusters are over scored observations and decide whether "
           "the permutation null is informative (Amendment 6, D2).", ""]
    header = ("Population", *JUDGMENT_KEYS, "Total")
    for name in READINGS:
        r = results["readings"][name]
        d, null = r["diagnostics"], r["null"]
        rows = [_dist_row("pooled", d.get("pooled"))]
        per_stratum = d.get("per_stratum") or {}
        rows += [_dist_row(f"stratum {_label(s)}", per_stratum[s])
                 for s in _keys(per_stratum, K.STRATA)]
        per_half = d.get("per_half") or {}
        rows += [_dist_row(f"{_label(h)} half", per_half[h])
                 for h in _keys(per_half, ("first", "second"))]
        bar = d.get("neutral_rate_bar")
        out += [f"### {name.capitalize()} reading", "",
                *_table(header, rows), "",
                f"- NEUTRAL rate {_pct(d.get('neutral_rate'))} against the "
                f"{_pct(bar, 0)} bar: "
                f"{'above the bar' if d.get('neutral_rate_exceeds_bar') else 'not above the bar'}.",
                f"- Minority directional share {_pct(null.get('minority_share'))} "
                f"(threshold {_pct(null.get('min_minority_share'), 0)}); "
                f"mixed clusters {_num(null.get('n_mixed_clusters'))} of "
                f"{_num(null.get('n_clusters'))} (threshold "
                f"{_num(null.get('min_mixed_clusters'))}); POSITIVE "
                f"{_num(null.get('n_positive'))}, NEGATIVE "
                f"{_num(null.get('n_negative'))}.",
                f"- Permutation null informative: "
                f"{_yes(decision['readings'][name]['null_informative'])}.",
                ""]
    return out


# --------------------------------------------------------- 2 analysis set

def _analysis(results: Mapping) -> list[str]:
    a = results["analysis_set"]
    cut, day, funnel = a["cutoff"], a["day_rule"], a["funnel"]
    shares = day.get("source_failed_share") or {}
    out = [H_ANALYSIS, "",
           f"- S* (9.7): {_label(cut.get('s_star'))} (case "
           f"{_label(cut.get('case'))}); latest resolved session "
           f"{_label(cut.get('latest_resolved'))}; earliest non-stale pending "
           f"session {_label(cut.get('earliest_nonstale_pending'))}; "
           f"{len(cut.get('sessions') or [])} sessions on the order.",
           f"- Stale pending rows (more than {K.STALE_PENDING_SESSIONS} "
           f"sessions before the latest resolved): "
           f"{_num(cut.get('stale_pending_rows'))}, in sessions "
           + (", ".join(f"{_label(s)} ({_num(n)})"
                        for s, n in cut.get("stale_pending") or []) or "none")
           + f". Pending rows with an empty scoring_session: "
           f"{_num(cut.get('empty_session_pending'))}.",
           f"- Day exclusions (9.1, source_failed share above "
           f"{_pct(day.get('threshold'), 0)}): "
           + (", ".join(f"{_label(q)} ({_pct(shares.get(q))})"
                        for q in sorted(day.get("excluded_query_dates") or []))
              or "none")
           + f"; {_num(day.get('collection_rows_on_excluded_days'))} "
           "collection rows on excluded days.", ""]
    dropped = funnel.get("dropped_first_reason") or {}
    pending = funnel.get("pending") or {}
    out += ["Funnel over judged collection rows: each dropped row is counted "
            "once, under the first condition it fails, in the order tested. A "
            "NULL excess_1session is excluded and counted, never read as 0 "
            "(D25).", ""]
    out += _table(("Funnel quantity", "Count"), [
        ("judged collection rows", _num(funnel.get("judged_collection_rows"))),
        *((f"dropped first by {_label(k)}", _num(dropped[k]))
          for k in _keys(dropped, family.DROP_ORDER)),
        ("gate rows G (D1)", _num(funnel.get("gate_rows"))),
        ("scored observations", _num(funnel.get("scored"))),
        ("pending, not stale", _num(pending.get("not_stale"))),
        ("pending, stale", _num(pending.get("stale"))),
        ("pending, empty session", _num(pending.get("empty_session"))),
        ("scored with NULL net_bp", _num(funnel.get("scored_net_bp_null"))),
        ("scored with strength_parse_ok = 0",
         _num(funnel.get("scored_strength_not_parse_ok"))),
        ("scored with parse_ok = 1 and NULL strength",
         _num(funnel.get("scored_parse_ok_strength_null"))),
    ])
    h = results.get("halves") or {}
    out += ["",
            f"- Chronological halves (9.6): D = {_num(h.get('D'))}; first half "
            f"{_num(h.get('first_half_clusters'))} clusters "
            f"({_label(h.get('first_half_first'))} to "
            f"{_label(h.get('first_half_last'))}); second half "
            f"{_num(h.get('second_half_clusters'))} clusters "
            f"({_label(h.get('second_half_first'))} to "
            f"{_label(h.get('second_half_last'))})."]
    for name in READINGS:
        r = results["readings"][name]
        out.append(f"- {name.capitalize()} reading: D = {_num(r.get('D'))} "
                   f"clusters, M = {_num(r.get('M'))} scored observations.")
    rows = []
    for name in READINGS:
        pss = results["readings"][name]["diagnostics"].get(
            "per_stratum_scored") or {}
        for s in _keys(pss, K.STRATA):
            b = pss[s]
            rows.append((name, _label(s), _num(b.get("scored")),
                         _num(b.get("scored_clusters")),
                         _num(b.get("net_bp_non_null")),
                         _num(b.get("net_bp_null")),
                         _num(b.get("net_bp_clusters"))))
    out += ["", *_table(("Reading", "Stratum", "Scored", "Clusters",
                         "net_bp non-null", "net_bp NULL",
                         "net_bp clusters"), rows), ""]
    return out


# ------------------------------------------------------------ 3 primaries

def _boot_cells(b: Mapping | None, nd: int = 2) -> list[str]:
    b = b or {}
    return [_num(b.get("statistic"), nd), _num(b.get("se"), nd + 1),
            _num(b.get("z"), 2), _interval(b.get("lower"), b.get("upper"), nd),
            _interval(b.get("percentile_lower"), b.get("percentile_upper"), nd)]


def _status_cell(decision: Mapping, reading: str, test: str,
                 boot: Mapping | None) -> str:
    word = _status(decision, reading, test)
    reason = (boot or {}).get("reason")
    return f"{word} ({_label(reason)})" if reason else word


def _primary_row(results: Mapping, decision: Mapping, reading: str,
                 test: str, tests: Mapping | None = None,
                 status: str | None = None) -> list[str]:
    t = (tests or results["readings"][reading]["tests"])[test]
    b, p = t.get("bootstrap") or {}, t.get("permutation") or {}
    return [test, _label(t.get("subset")), reading, _num(t.get("n_obs")),
            _num(t.get("n_clusters")), *_boot_cells(b), _num(p.get("p"), 6),
            f"{_num(p.get('count_ge'))} / {_num(p.get('count_le'))}",
            _yes(p.get("upper_tail")),
            status or _status_cell(decision, reading, test, b)]


PRIMARY_HEADER = ("Test", "Subset", "Reading", "n", "Clusters", "T (bp)",
                  "SE", "z", "T +/- 2.50 SE", "Percentile interval "
                  "(descriptive)", "Permutation p", "count >= / <= T_obs",
                  "Upper tail", "Status")


def _primaries(results: Mapping, decision: Mapping) -> list[str]:
    rows = [_primary_row(results, decision, name, t)
            for t in V.PRIMARY_TESTS for name in READINGS]
    return [H_PRIMARIES, "",
            "T is the observation-weighted mean signed_bp (9.4); SE is the "
            "ddof-1 standard deviation of 10,000 cluster-bootstrap replicates "
            "clustered by scoring_session (9.5); z = T / SE. A clear needs "
            "z >= +2.50 with the lower bound above zero, an informative null, "
            "p <= 0.0125 and the upper tail (9.3). A z at or below -2.50 is a "
            "significant reversal and never a clear. Percentile intervals are "
            "descriptive and decide nothing.", "",
            *_table(PRIMARY_HEADER, rows), ""]


# -------------------------------------------------------------- 4 verdict

REASON_WORDS = {
    V.REASON_D_BELOW_FLOOR: "fewer than 60 clusters hold scored observations",
    V.REASON_M_BELOW_FLOOR: "fewer than 1,000 scored observations",
    V.REASON_INTERVAL_ZERO_AND_EFFECT:
        "P1's interval includes both zero and 30 bp",
    V.REASON_NULL_INTERCEPTED:
        "a positive was intercepted by the permutation null",
    V.REASON_P1_DEGENERATE: "P1 is degenerate",
    V.REASON_P1_FLOOR: "P1 is below its 30-cluster floor",
}


def _net_abstention(na: Mapping | None) -> list[str]:
    """S6 ruling: under clears_gross_net_abstains, no Amendment 5 net row is
    quoted; the report says so, lists every stratum's status and quotes
    Amendment 5's abstention sentence verbatim."""
    if not na:
        return []
    abstained = na.get("abstained") or []
    return [na["statement"], "",
            f"- {na['e_note']}.",
            "- E-tests that abstained: "
            + (", ".join(abstained) if abstained else NA) + ".",
            "- No E-test cleared, so no Amendment 5 row permits trading on "
            "this result.", "",
            *_quote("Amendment 5, the economic secondary family",
                    na["quote"])]


def _reading_verdict(name: str, d: Mapping) -> list[str]:
    g = d["gross"]
    reasons = [REASON_WORDS.get(r, _label(r)) for r in g.get("reasons") or []]
    out = [f"### {name.capitalize()} reading"
           + (" (governs)" if name == V.GOVERNING_READING else ""), "",
           f"- Gross reading: {_label(g['gross_reading'])}. D = "
           f"{_num(g.get('D'))}, M = {_num(g.get('M'))}. P1 interval "
           f"{_interval(g.get('p1_lower'), g.get('p1_upper'))} bp against the "
           f"{_num(g.get('effect_bp'), 0)} bp working effect.",
           "- Abstention reasons: " + ("; ".join(reasons) if reasons
                                       else "none") + ".", ""]
    if g["gross_reading"] == V.GROSS_CLEARS:
        out += [f"Gross positive in this reading: {V.PIPELINE_PREDICTS} "
                "next-session drift on the names its news source covers.", ""]
        if d.get("outcome_row") == V.ROW_CLEARS_FAILS_NET:
            out += [f"This result is {V.FINDING_ABOUT_MARKETS}. It licenses "
                    "no trade.", ""]
    out += _net_abstention(d.get("net_abstention"))
    if not d["rows"]:
        out += ["No Amendment 5 outcome row applies to this reading.", ""]
    for row in d["rows"]:
        outcome, text = V.VERDICT_TABLE[row["key"]]
        out += [f"Verdict row (Amendment 5 table), outcome cell: {outcome}",
                "", "Verdict cell:", "", text, ""]
        out += [f"- Note: {n}" for n in row.get("notes") or []]
        dist = row.get("judgment_distribution")
        if dist:
            pooled = dist.get("pooled") or {}
            counts = pooled.get("counts") or {}
            out.append("- Realised judgment distribution: " + ", ".join(
                f"{k} {_num(counts.get(k))}" for k in JUDGMENT_KEYS)
                + f"; minority share {_pct(dist.get('minority_share'))}; "
                f"mixed clusters {_num(dist.get('n_mixed_clusters'))}.")
        out.append("")
    for s in d.get("statements") or []:
        out += _quote("Task 5 and Task 6 (the words that apply)", s)
    return out


def _verdict(results: Mapping, decision: Mapping) -> list[str]:
    out = [H_VERDICT, "", f"One-line summary: {decision['summary']}", ""]
    for name in READINGS:
        out += _reading_verdict(name, decision["readings"][name])
    dis = decision["sensitivity_disagreement"]
    out += ["### Primary against the 8.2 sensitivity reading", ""]
    out += [dis["statement"] if dis.get("differs") else
            "The two readings agree in gross reading and outcome row.", ""]
    out += _quote("8.2", V.READINGS_DISAGREE_8_2)
    story = decision.get("story") or {}
    if story.get("fired"):
        out += ["### Story-group version against the scoring_session version",
                "", story.get("statement") or "The story-group version gives "
                "the same primary statuses; the scoring_session-clustered "
                "version governs.", ""]
    return out


# ------------------------------------------------------- 5 and 6 statements

def _cutoff_statement() -> list[str]:
    return [H_CUTOFF, "", *_quote("8.1", V.MODEL_CUTOFF_8_1)]


def _scale_line(label: str, s: Mapping | None) -> str:
    s = s or {}
    return (f"- {label}: {_num(s.get('pairs'))} (symbol, formation) pairs, "
            f"{len(s.get('symbols') or [])} symbols; "
            f"{_num(s.get('judged_rows'))} judged rows "
            f"({_pct(s.get('judged_share'))} of judged); "
            f"{_num(s.get('scored_rows'))} scored observations "
            f"({_pct(s.get('scored_share'))} of scored).")


def _defect(results: Mapping, decision: Mapping) -> list[str]:
    sens = results.get("sensitivity_exclusion") or {}
    out = [H_DEFECT, "", *_quote("8.2", V.CLOSED_END_FUND_DEFECT_8_2),
           "Measured scale in this snapshot:", "",
           _scale_line("Rule (b), closed-end funds and unclassified vehicles "
                       "(the defect)",
                       decision["statements"]["closed_end_fund_defect_8_2"]
                       .get("scale")),
           _scale_line("Rule (a), preferred shares and share classes",
                       sens.get("rule_a_scale")),
           _scale_line("Both rules together", sens.get("all_scale")), ""]
    rows = [(rule, _label(m.get("symbol")), _label(m.get("formation_date")),
             _num(m.get("judged_rows")), _num(m.get("scored_rows")))
            for rule, key in (("a", "rule_a"), ("b", "rule_b"))
            for m in sens.get(key) or []]
    out += [*_table(("Rule", "Symbol", "Formation", "Judged rows",
                     "Scored observations"), rows), "",
            "The sensitivity result is in sections 3, 4 and 7 beside the "
            "primary reading.", ""]
    return out


# ------------------------------------------------------------ 7 secondaries

def _e_rows(results: Mapping, decision: Mapping) -> list[list[str]]:
    rows = []
    for t in V.E_TESTS:
        for name in READINGS:
            e = results["readings"][name]["tests"][t]
            b = e.get("bootstrap") or {}
            rows.append([t, _label(e.get("stratum")), name,
                         _num(e.get("n_scored")), _num(e.get("n_obs")),
                         _num(e.get("n_net_bp_null")),
                         _num(e.get("n_clusters")), *_boot_cells(b),
                         _status_cell(decision, name, t, b)])
    return rows


def _s_rows(results: Mapping, decision: Mapping) -> list[list[str]]:
    rows = []
    for t in V.STRENGTH_TESTS:
        for name in READINGS:
            s = results["readings"][name]["tests"][t]
            b = s.get("bootstrap") or {}
            nd = 4 if t == "S1" else 2
            extra = (f"top {_num(s.get('n_top'))} / bottom "
                     f"{_num(s.get('n_bottom'))}" if t == "S2" else NA)
            rows.append([t, name, _num(s.get("n_obs")),
                         _num(s.get("n_clusters")), *_boot_cells(b, nd),
                         _num(b.get("n_undefined")), extra,
                         _status_cell(decision, name, t, b)])
    return rows


def _histogram_rows(results: Mapping) -> list[list[str]]:
    rows = []
    for name in READINGS:
        h = results["readings"][name]["diagnostics"].get(
            "strength_histogram") or {}
        buckets = h.get("buckets") or {}
        rows.append([name] + [
            f"{_num((buckets.get(str(k)) or {}).get('n'))} / "
            f"{_num((buckets.get(str(k)) or {}).get('mean_signed_bp'))}"
            for k in (1, 2, 3, 4, 5)]
            + [_num(h.get("n_parse_ok")), _num(h.get("n_not_parse_ok"))])
    return rows


def _secondaries(results: Mapping, decision: Mapping) -> list[str]:
    return [H_SECONDARIES, "",
            "These are weaker secondaries. No secondary confirms the "
            "hypothesis (Amendment 5, Task 5); the primaries in section 3 "
            "decide the gross reading.", "",
            "### E1 to E4: net of round-trip cost (9.4, 9.10)", "",
            "T is the mean net_bp over the stratum's scored observations with "
            f"non-null net_bp. A clear needs z >= +2.50 and T >= "
            f"{_num(K.ECON_BAR_BP)} bp. An interval spanning zero is an "
            "abstention, not a measured failure; a z at or below -2.50 is "
            f"\"{V.NET_NEGATIVE_WORDS}\".", "",
            *_table(("Test", "Stratum", "Reading", "Scored", "n (net_bp)",
                     "net_bp NULL", "Clusters", "T (bp)", "SE", "z",
                     "T +/- 2.50 SE", "Percentile interval (descriptive)",
                     "Status"), _e_rows(results, decision)), "",
            "### S1 and S2: strength (9.10)", "",
            f"Label: {V.STRENGTH_LABEL}.", "",
            *_table(("Test", "Reading", "n", "Clusters", "Statistic", "SE",
                     "z", "Statistic +/- 2.24 SE",
                     "Percentile interval (descriptive)",
                     "Undefined replicates", "S2 pools", "Status"),
                    _s_rows(results, decision)), "",
            "Strength buckets, n / mean signed_bp (descriptive):", "",
            *_table(("Reading", "1", "2", "3", "4", "5", "parse_ok = 1",
                     "parse_ok = 0"), _histogram_rows(results)), ""]


# ------------------------------------------------------------- 8 relevance

def _relevance(summary: Mapping) -> list[str]:
    agr = summary.get("agreement_opus_fable") or {}
    variants = summary.get("variants") or {}
    rates = summary.get("rates") or {}
    rows = []
    for grade_set in GRADE_SETS:
        for v in RELEVANCE_VARIANTS:
            block = (rates.get(grade_set) or {}).get(v) or {}
            counts, rr = block.get("counts") or {}, block.get("rates") or {}
            rows.append([grade_set, v, _yes((variants.get(v) or {})
                                            .get("approximate")),
                         _num(block.get("n"))] + [
                f"{_num(counts.get(g))} ({_pct(rr.get(g))})"
                for g in relevance.GRADES])
    notes = [f"- {v}: {relevance.VARIANT_NOTES[v]}." for v in
             RELEVANCE_VARIANTS]
    return [H_RELEVANCE, "",
            f"Sample of {_num(summary.get('n_sample'))} judged collection "
            "rows graded blind to outcomes by two independent graders (opus, "
            "fable), disagreements adjudicated by the C.1 lead. Nothing is "
            "filtered on these grades (8.3).", "",
            f"- Raw agreement {_pct(agr.get('raw_agreement'))} "
            f"({_num(agr.get('n_agree'))} agree, "
            f"{_num(agr.get('n_disagree'))} disagree); Cohen's kappa "
            f"{_num(agr.get('cohens_kappa'), 3)}.", "",
            *_table(("Grade set", "Variant", "Approximate", "n",
                     *relevance.GRADES), rows), "", *notes, ""]


# ------------------------------------------------------------ 9 robustness

def _robustness(results: Mapping, decision: Mapping) -> list[str]:
    sec = results.get("sector_robustness") or {}
    per = sec.get("observations_per_sector") or {}
    trig = (results.get("story") or {}).get("trigger") or {}
    out = [H_ROBUSTNESS, "", "### Sector (descriptive, no bar)", "",
           f"- P1 primary reading: T {_num(sec.get('statistic'))} bp, CR1 SE "
           f"over sectors {_num(sec.get('se'), 3)}, z {_num(sec.get('z'))}, "
           f"{_num(sec.get('n_clusters'))} sector clusters, "
           f"{_num(sec.get('n_obs'))} observations, status "
           f"{_label(sec.get('status'))}"
           + (f" ({_label(sec.get('reason'))})" if sec.get("reason") else "")
           + ".", "",
           *_table(("Sector", "Scored observations"),
                   [(_label(s), _num(per[s])) for s in sorted(per)]), "",
           "### Story groups", "",
           f"- Share of scored observations whose story group appears on at "
           f"least 2 scored observations: {_pct(trig.get('share'), 2)} "
           f"({_num(trig.get('n_shared'))} of {_num(trig.get('n_scored'))}, "
           f"{_num(trig.get('n_shared_groups'))} shared groups); trigger "
           f"above {_pct(trig.get('threshold'), 0)}: "
           f"{'fired' if trig.get('fired') else 'not fired'}"
           + (f" ({trig['reason']})" if trig.get("reason") else "") + ".",
           ""]
    story = results.get("story") or {}
    if story.get("fired"):
        statuses = (decision.get("story") or {}).get("statuses") or {}
        rows = []
        for t in V.PRIMARY_TESTS:
            for name in READINGS:
                sname = V.STORY_READINGS[name]
                tests = story["readings"][sname]["tests"]
                st = (statuses.get(sname) or {}).get(t)
                rows.append(_primary_row(results, decision, sname, t, tests,
                                         V.status_words(st) if st else NA))
        out += ["Story-group version (bootstrap clustered on story_group_id, "
                "block null within scoring_session). The scoring_session-"
                "clustered version governs.", "",
                *_table(PRIMARY_HEADER, rows), ""]
    return out


# ------------------------------------------------------------- 10 companion

def _companion(companion: Mapping) -> list[str]:
    horizons = companion.get("horizons") or {}
    order = sorted(horizons, key=lambda c: (horizons[c].get("k") or 0, c))
    rows = [(_label(c), _num(horizons[c].get("k")),
             _num(horizons[c].get("n_obs")), _num(horizons[c].get("n_null")),
             _num(horizons[c].get("mean_signed_bp")))
            for c in order]
    return [H_COMPANION, "",
            "EXPLORATORY. Not a registered test: no interval, no bar, and it "
            "decides nothing. Reported because a successor pre-registration "
            "draft was committed before the snapshot (9.12). Primary reading "
            "only; the observation-weighted mean of the judgment-signed raw "
            "return.", "",
            *_table(("Column", "k (sessions)", "n", "NULL (excluded)",
                     "Mean signed (bp), EXPLORATORY"), rows), ""]


# ------------------------------------------------------------ provenance

def _provenance(meta: Mapping) -> list[str]:
    hashes = meta.get("hashes") or {}
    succ = meta.get("successor_condition_9_12") or {}
    snap = meta.get("snapshot") or {}
    return [H_PROVENANCE, "",
            *(f"- {_label(k)}: {_label(hashes[k])}" for k in sorted(hashes)),
            f"- Snapshot time (UTC): {_label(snap.get('utc_time'))}; "
            f"method {_label(snap.get('method'))}; S* "
            f"{_label(meta.get('s_star'))}.",
            f"- Run start {_label(meta.get('utc_start'))}; marker written "
            f"{_label(meta.get('utc_marker'))}.",
            f"- 9.12 condition: draft tracked {_yes(succ.get('tracked'))}, "
            f"last commit {_label(succ.get('last_commit_time'))}, holds "
            f"{_yes(succ.get('holds'))}.", ""]


# ------------------------------------------------------------------ write

def write(results: Mapping[str, Any], decision: Mapping[str, Any], *,
          relevance_summary: Mapping[str, Any],
          companion: Mapping[str, Any] | None = None,
          run_meta: Mapping[str, Any] | None = None) -> str:
    """The fixed-template verdict report (9.15) as markdown text."""
    lines = [TITLE, "",
             "Fixed template (news_eval/report.py). Numbers come from "
             "news_eval.family, decisions from news_eval.verdict, quotes from "
             "EXPERIMENT.md byte for byte. The primary reading governs.", ""]
    lines += _diagnostics(results, decision)
    lines += _analysis(results)
    lines += _primaries(results, decision)
    lines += _verdict(results, decision)
    lines += _cutoff_statement()
    lines += _defect(results, decision)
    lines += _secondaries(results, decision)
    lines += _relevance(relevance_summary)
    lines += _robustness(results, decision)
    if companion is not None:
        lines += _companion(companion)
    if run_meta is not None:
        lines += _provenance(run_meta)
    return "\n".join(lines).rstrip("\n") + "\n"
