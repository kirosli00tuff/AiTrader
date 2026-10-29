"""Independent recomputation of the C.2 stop-rule gate (EXPERIMENT.md 8.4, 9.1, 9.7, 9.8, Task 5).

Stdlib only. Reads the read-only snapshot through a mode=ro&immutable=1 URI.
Permitted columns: query_date, scoring_session, state, run_kind, exclusion_reason,
outcome_state, excess_1session. The judgment column appears only inside one
COUNT ... GROUP BY scoring_session aggregate. No row-level excess value is
printed or saved; only aggregates reach stdout and own_gate.json.
"""
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
from fractions import Fraction

SNAP = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/snap_20261028/news_experiment_snapshot.db"
EXPECTED_SHA = "2b517c70ae61affec18a973952e02714240e8f9086fe3069f3bc1ff8e3ed6500"
OUT_DIR = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/verify_gate"
OUT_JSON = os.path.join(OUT_DIR, "own_gate.json")
SQL_LOG_PATH = os.path.join(OUT_DIR, "verify_gate.sql.log")

# Registered constants (9.8, Task 5)
CONST_11156 = 11.156            # literal from 9.8: "11.156 is (2.50 + 0.84)^2"
CONST_Z_SQ = (2.50 + 0.84) ** 2  # 11.1556, the arithmetic the literal rounds
DELTA_BP = 30.0
MIN_CLUSTERS = 60
MIN_M = 1000
DAY_EXCLUSION_SHARE = Fraction(20, 100)   # "exceeds 20 percent" -> strictly greater
STALE_SESSIONS = 3                         # 9.7: "more than 3 sessions before"

SQL_LOG = []


def shell_date():
    return subprocess.run(["date"], capture_output=True, text=True, check=True).stdout.strip()


def q(con, sql, params=()):
    SQL_LOG.append(sql.strip())
    return con.execute(sql, params).fetchall()


# ---------------------------------------------------------------- integrity
def check_snapshot():
    h = hashlib.sha256()
    with open(SNAP, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if digest != EXPECTED_SHA:
        sys.exit(f"SHA256 MISMATCH: {digest}")
    sidecars = [SNAP + s for s in ("-wal", "-shm", "-journal")]
    present = [p for p in sidecars if os.path.exists(p)]
    if present:
        sys.exit(f"SIDECAR FILES PRESENT: {present}")
    mode = oct(os.stat(SNAP).st_mode & 0o777)
    return {"sha256": digest, "sha256_matches": True, "sidecars_present": [], "mode": mode}


# ---------------------------------------------------------------- NYSE calendar
NYSE_HOLIDAYS = {
    # 2026
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Presidents' Day",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observed; Jul 4 is Saturday)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    # 2027
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King Jr. Day",
    "2027-02-15": "Presidents' Day",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth (observed; Jun 19 is Saturday)",
    "2027-07-05": "Independence Day (observed; Jul 4 is Sunday)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed; Dec 25 is Saturday)",
}


def is_trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def trading_days_from(start_iso, count):
    d = dt.date.fromisoformat(start_iso)
    out = []
    while len(out) < count:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def trading_days_between(a_iso, b_iso):
    """Inclusive list of NYSE sessions from a to b."""
    d = dt.date.fromisoformat(a_iso)
    b = dt.date.fromisoformat(b_iso)
    out = []
    while d <= b:
        if is_trading_day(d):
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------- 9.1 day exclusion
def day_exclusion(con):
    rows = q(con, """
        SELECT query_date,
               COUNT(*) AS n_total,
               SUM(state = 'source_failed') AS n_source_failed
        FROM news_observation
        WHERE run_kind = 'collection'
        GROUP BY query_date
        ORDER BY query_date
    """)
    per_day = []
    excluded = []
    for qd, n_total, n_sf in rows:
        share = Fraction(int(n_sf), int(n_total))
        is_excl = share > DAY_EXCLUSION_SHARE
        per_day.append({
            "query_date": qd,
            "n_collection_rows": int(n_total),
            "n_source_failed": int(n_sf),
            "source_failed_share": float(share),
            "excluded": is_excl,
        })
        if is_excl:
            excluded.append(qd)
    # Also report the collector's own marker, if any row carries it.
    marker = q(con, """
        SELECT COUNT(*), COUNT(DISTINCT query_date)
        FROM news_observation
        WHERE run_kind = 'collection' AND exclusion_reason = 'day_excluded_source_failures'
    """)[0]
    return per_day, excluded, {"rows_with_day_excluded_marker": int(marker[0]),
                               "dates_with_day_excluded_marker": int(marker[1])}


# ---------------------------------------------------------------- 9.7 cutoff S*
def cutoff_s_star(con):
    latest_resolved = q(con, """
        SELECT MAX(scoring_session)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged' AND outcome_state = 'resolved'
          AND scoring_session IS NOT NULL AND scoring_session <> ''
    """)[0][0]
    latest_judged_any = q(con, """
        SELECT MAX(scoring_session)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
          AND scoring_session IS NOT NULL AND scoring_session <> ''
    """)[0][0]
    pending = q(con, """
        SELECT scoring_session, COUNT(*)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged' AND outcome_state = 'pending'
        GROUP BY scoring_session
        ORDER BY scoring_session
    """)
    outcome_states = q(con, """
        SELECT outcome_state, COUNT(*)
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
        GROUP BY outcome_state
        ORDER BY outcome_state
    """)
    data_sessions = [r[0] for r in q(con, """
        SELECT DISTINCT scoring_session
        FROM news_observation
        WHERE run_kind = 'collection' AND state = 'judged'
          AND scoring_session IS NOT NULL AND scoring_session <> ''
        ORDER BY scoring_session
    """)]

    pending_total = sum(int(n) for _, n in pending)
    pending_sessions = [s for s, _ in pending]

    # Stale rule, reading A: "sessions" are NYSE calendar sessions.
    # Stale rule, reading B: "sessions" are distinct scoring_session values present in the data.
    def stale_A(sess):
        gap = len(trading_days_between(sess, latest_resolved)) - 1  # sessions strictly after sess up to latest
        return gap > STALE_SESSIONS

    def stale_B(sess):
        if sess not in data_sessions:
            return None
        gap = data_sessions.index(latest_resolved) - data_sessions.index(sess)
        return gap > STALE_SESSIONS

    stale_A_count = sum(int(n) for s, n in pending if stale_A(s))
    stale_B_count = sum(int(n) for s, n in pending if stale_B(s))
    live_pending_A = [s for s, _ in pending if not stale_A(s)]
    live_pending_B = [s for s, _ in pending if not stale_B(s)]

    def s_star_for(live):
        if not live:
            return latest_judged_any
        earliest_live = min(live)
        before = [s for s in data_sessions if s < earliest_live]
        return before[-1] if before else None

    s_star_A = s_star_for(live_pending_A)
    s_star_B = s_star_for(live_pending_B)

    return {
        "latest_resolved_session": latest_resolved,
        "latest_judged_session_any_outcome_state": latest_judged_any,
        "outcome_state_counts_judged_collection": {k: int(v) for k, v in outcome_states},
        "pending_judged_collection_rows": pending_total,
        "pending_sessions": pending_sessions,
        "stale_count_reading_A_calendar_sessions": stale_A_count,
        "stale_count_reading_B_data_sessions": stale_B_count,
        "s_star_reading_A": s_star_A,
        "s_star_reading_B": s_star_B,
        "s_star": s_star_A,
        "readings_agree": s_star_A == s_star_B,
        "how_set": ("no pending judged collection rows exist, so S* is the latest scoring_session "
                    "among judged collection rows" if pending_total == 0 else
                    "S* is the latest data session strictly before the earliest non-stale pending session"),
        "n_distinct_data_sessions_judged": len(data_sessions),
        "data_sessions_first": data_sessions[0] if data_sessions else None,
        "data_sessions_last": data_sessions[-1] if data_sessions else None,
    }, data_sessions


# ---------------------------------------------------------------- 9.8 gate rows and statistics
G_CONDITIONS = """
        run_kind = 'collection'
        AND state = 'judged'
        AND outcome_state = 'resolved'
        AND exclusion_reason = ''
        AND scoring_session IS NOT NULL AND scoring_session <> ''
"""


def gate_rows(con, excluded_dates, s_star):
    excl_sql = ""
    params = []
    if excluded_dates:
        excl_sql = " AND query_date NOT IN (%s)" % ",".join("?" * len(excluded_dates))
        params.extend(excluded_dates)
    cutoff_sql = " AND scoring_session <= ?"
    params_cut = params + [s_star]

    # G rows: cluster key and the scored quantity. Row-level values stay in memory only.
    g = q(con, f"""
        SELECT scoring_session, excess_1session
        FROM news_observation
        WHERE {G_CONDITIONS}
          AND excess_1session IS NOT NULL
          {excl_sql}
          {cutoff_sql}
        ORDER BY scoring_session
    """, params_cut)

    null_excess = q(con, f"""
        SELECT COUNT(*)
        FROM news_observation
        WHERE {G_CONDITIONS}
          AND excess_1session IS NULL
          {excl_sql}
          {cutoff_sql}
    """, params_cut)[0][0]

    # Same without the S* cutoff, to show whether the cutoff removes anything.
    g_no_cut = q(con, f"""
        SELECT COUNT(*), COUNT(DISTINCT scoring_session)
        FROM news_observation
        WHERE {G_CONDITIONS}
          AND excess_1session IS NOT NULL
          {excl_sql}
    """, params)[0]

    # Directional counts per cluster: the single permitted judgment aggregate.
    directional = q(con, f"""
        SELECT scoring_session, COUNT(*)
        FROM news_observation
        WHERE {G_CONDITIONS}
          AND excess_1session IS NOT NULL
          {excl_sql}
          {cutoff_sql}
          AND judgment IN ('POSITIVE', 'NEGATIVE')
        GROUP BY scoring_session
        ORDER BY scoring_session
    """, params_cut)

    return g, int(null_excess), {"N_no_cutoff": int(g_no_cut[0]), "C_G_no_cutoff": int(g_no_cut[1])}, directional


def anova_icc(g_rows):
    """One-way ANOVA ICC of 10,000 x excess over clusters. Returns float and exact-rational versions."""
    by_cluster = {}
    for sess, ex in g_rows:
        by_cluster.setdefault(sess, []).append(10000.0 * float(ex))
    clusters = sorted(by_cluster)
    N = sum(len(v) for v in by_cluster.values())
    C = len(clusters)
    all_y = [y for s in clusters for y in by_cluster[s]]

    # ---- float path (fsum)
    gmean = math.fsum(all_y) / N
    ss_tot = math.fsum((y - gmean) ** 2 for y in all_y)
    var1 = ss_tot / (N - 1)
    sigma = math.sqrt(var1)
    ssb = math.fsum(len(by_cluster[s]) * (math.fsum(by_cluster[s]) / len(by_cluster[s]) - gmean) ** 2 for s in clusters)
    ssw = math.fsum(math.fsum((y - math.fsum(by_cluster[s]) / len(by_cluster[s])) ** 2 for y in by_cluster[s]) for s in clusters)
    msb = ssb / (C - 1)
    msw = ssw / (N - C)
    sum_nc2 = sum(len(by_cluster[s]) ** 2 for s in clusters)
    n0 = (N - sum_nc2 / N) / (C - 1)
    rho_raw = (msb - msw) / (msb + (n0 - 1) * msw)
    rho = max(0.0, rho_raw)

    # ---- exact rational path (inputs converted exactly from their binary floats)
    FY = {s: [Fraction(y) for y in by_cluster[s]] for s in clusters}
    f_all = [y for s in clusters for y in FY[s]]
    f_gmean = sum(f_all) / N
    f_ss_tot = sum((y - f_gmean) ** 2 for y in f_all)
    f_var1 = f_ss_tot / (N - 1)
    f_ssb = sum(len(FY[s]) * (sum(FY[s]) / len(FY[s]) - f_gmean) ** 2 for s in clusters)
    f_ssw = sum(sum((y - sum(FY[s]) / len(FY[s])) ** 2 for y in FY[s]) for s in clusters)
    f_msb = f_ssb / (C - 1)
    f_msw = f_ssw / (N - C)
    f_n0 = (Fraction(N) - Fraction(sum_nc2, N)) / (C - 1)
    f_rho_raw = (f_msb - f_msw) / (f_msb + (f_n0 - 1) * f_msw)

    cluster_sizes = {s: len(by_cluster[s]) for s in clusters}
    return {
        "N": N, "C_G": C,
        "sigma_bp": sigma,
        "MSB": msb, "MSW": msw, "n0": n0,
        "rho_raw": rho_raw, "rho": rho,
        "SSB": ssb, "SSW": ssw, "SS_total": ss_tot,
        "sum_nc2": sum_nc2,
        "cluster_size_min": min(cluster_sizes.values()),
        "cluster_size_max": max(cluster_sizes.values()),
        "cluster_size_mean": N / C,
        "exact": {
            "sigma_bp": math.sqrt(float(f_var1)),
            "var_ddof1": float(f_var1),
            "MSB": float(f_msb), "MSW": float(f_msw), "n0": float(f_n0),
            "rho_raw": float(f_rho_raw),
        },
        "float_vs_exact_rel": {
            "MSB": abs(msb - float(f_msb)) / abs(float(f_msb)),
            "MSW": abs(msw - float(f_msw)) / abs(float(f_msw)),
            "rho_raw": abs(rho_raw - float(f_rho_raw)) / abs(float(f_rho_raw)) if f_rho_raw != 0 else 0.0,
        },
    }, cluster_sizes


def directional_stats(directional):
    m = {s: int(n) for s, n in directional}
    M = sum(m.values())
    C = len(m)
    sum_m2 = sum(v * v for v in m.values())
    k_eff = sum_m2 / M
    k_eff_exact = Fraction(sum_m2, M)
    return {"C": C, "M": M, "sum_mc2": sum_m2, "k_eff": k_eff, "k_eff_exact_num": sum_m2, "k_eff_exact_den": M,
            "m_c_min": min(m.values()), "m_c_max": max(m.values()), "m_c_mean": M / C}, m


def required_n(sigma, k_eff, rho, const):
    return const * (sigma / DELTA_BP) ** 2 * (1.0 + (k_eff - 1.0) * rho)


# ---------------------------------------------------------------- main
def main():
    t_start = shell_date()
    integ = check_snapshot()
    con = sqlite3.connect(f"file:{SNAP}?mode=ro&immutable=1", uri=True)

    per_day, excluded_dates, marker = day_exclusion(con)
    cut, data_sessions = cutoff_s_star(con)
    s_star = cut["s_star"]

    g, null_excess, no_cut, directional = gate_rows(con, excluded_dates, s_star)
    icc, cluster_sizes = anova_icc(g)
    dstats, m_by_cluster = directional_stats(directional)

    # rho with the alternative C (clusters holding a directional row) in n0, if it differs
    rho_alt = None
    if dstats["C"] != icc["C_G"]:
        N = icc["N"]
        n0_alt = (N - icc["sum_nc2"] / N) / (dstats["C"] - 1)
        rho_alt_raw = (icc["MSB"] - icc["MSW"]) / (icc["MSB"] + (n0_alt - 1) * icc["MSW"])
        rho_alt = {"n0": n0_alt, "rho_raw": rho_alt_raw, "rho": max(0.0, rho_alt_raw)}

    sigma = icc["sigma_bp"]
    rho = icc["rho"]
    k_eff = dstats["k_eff"]
    req = required_n(sigma, k_eff, rho, CONST_11156)
    req_zsq = required_n(sigma, k_eff, rho, CONST_Z_SQ)

    cond_C = dstats["C"] >= MIN_CLUSTERS
    cond_M = dstats["M"] >= MIN_M
    cond_req = dstats["M"] >= req
    cond_req_zsq = dstats["M"] >= req_zsq
    passes = cond_C and cond_M and cond_req

    # Clusters that have G rows but no directional row, and vice versa
    only_neutral_clusters = sorted(set(cluster_sizes) - set(m_by_cluster))
    dir_not_in_g = sorted(set(m_by_cluster) - set(cluster_sizes))

    # Calendar cross-check: data sessions vs NYSE calendar between first and last
    cal = trading_days_between(data_sessions[0], data_sessions[-1])
    cal_missing_in_data = sorted(set(cal) - set(data_sessions))
    data_not_in_cal = sorted(set(data_sessions) - set(cal))
    qdates = [d["query_date"] for d in per_day]
    cal_q = trading_days_between(qdates[0], qdates[-1])
    qdates_missing = sorted(set(cal_q) - set(qdates))
    qdates_not_in_cal = sorted(set(qdates) - set(cal_q))

    # ---- PROJECTION (arithmetic, not a finding)
    m_per_c = dstats["M"] / dstats["C"]
    clusters_to_required = math.ceil(req / m_per_c) if m_per_c > 0 else None
    clusters_to_required_zsq = math.ceil(req_zsq / m_per_c) if m_per_c > 0 else None
    sessions120 = trading_days_from("2026-07-28", 120)
    hard_stop_date = sessions120[-1]
    holidays_used = {d: NYSE_HOLIDAYS[d] for d in sorted(NYSE_HOLIDAYS) if sessions120[0] <= d <= hard_stop_date}
    # sessions between the latest data session and the hard stop
    remaining_after_s_star = len(trading_days_between(s_star, hard_stop_date)) - 1
    # session index of S*
    s_star_index = sessions120.index(s_star) + 1 if s_star in sessions120 else None

    con.close()
    t_written = shell_date()

    out = {
        "written_at_date_cmd": t_written,
        "started_at_date_cmd": t_start,
        "snapshot": {"path": SNAP, **integ},
        "constants": {"const_11156_literal": CONST_11156, "const_z_sq_arith": CONST_Z_SQ,
                      "delta_bp": DELTA_BP, "min_clusters": MIN_CLUSTERS, "min_M": MIN_M,
                      "day_exclusion_share_strict_gt": float(DAY_EXCLUSION_SHARE), "stale_sessions": STALE_SESSIONS},
        "day_exclusion_9_1": {
            "n_query_dates": len(per_day),
            "excluded_dates": excluded_dates,
            "n_excluded": len(excluded_dates),
            "max_share": max(d["source_failed_share"] for d in per_day),
            "dates_with_any_source_failed": [d["query_date"] for d in per_day if d["n_source_failed"] > 0],
            "collector_marker": marker,
            "per_day": per_day,
            "calendar_check": {"query_dates_missing_vs_nyse_calendar": qdates_missing,
                               "query_dates_not_trading_days": qdates_not_in_cal},
        },
        "cutoff_9_7": {**cut, "calendar_check": {"sessions_missing_vs_nyse_calendar": cal_missing_in_data,
                                                 "sessions_not_trading_days": data_not_in_cal}},
        "gate_9_8": {
            "N": icc["N"],
            "C_G": icc["C_G"],
            "null_excess_among_otherwise_G": null_excess,
            "without_cutoff": no_cut,
            "sigma_bp": sigma,
            "MSB": icc["MSB"], "MSW": icc["MSW"], "n0": icc["n0"],
            "SSB": icc["SSB"], "SSW": icc["SSW"], "SS_total": icc["SS_total"], "sum_nc2": icc["sum_nc2"],
            "rho_raw": icc["rho_raw"], "rho": rho,
            "exact_rational_check": icc["exact"], "float_vs_exact_rel": icc["float_vs_exact_rel"],
            "cluster_size_G": {k: icc[k] for k in ("cluster_size_min", "cluster_size_max", "cluster_size_mean")},
            "C": dstats["C"], "M": dstats["M"], "sum_mc2": dstats["sum_mc2"], "k_eff": k_eff,
            "k_eff_exact": f'{dstats["k_eff_exact_num"]}/{dstats["k_eff_exact_den"]}',
            "m_c": {k: dstats[k] for k in ("m_c_min", "m_c_max", "m_c_mean")},
            "clusters_in_G_without_directional_row": only_neutral_clusters,
            "directional_clusters_not_in_G": dir_not_in_g,
            "rho_with_C_directional_in_n0": rho_alt,
            "Required": req,
            "Required_with_z_sq_11_1556": req_zsq,
            "cond_C_ge_60": cond_C,
            "cond_M_ge_1000": cond_M,
            "cond_M_ge_Required": cond_req,
            "cond_M_ge_Required_z_sq": cond_req_zsq,
            "pass": passes,
            "directional_per_cluster": {k: int(v) for k, v in sorted(m_by_cluster.items())},
            "G_rows_per_cluster": {k: int(v) for k, v in sorted(cluster_sizes.items())},
        },
        "projection": {
            "M_over_C": m_per_c,
            "clusters_at_which_M_reaches_Required": clusters_to_required,
            "clusters_at_which_M_reaches_Required_z_sq": clusters_to_required_zsq,
            "hard_stop_session_120_date": hard_stop_date,
            "session_1": sessions120[0],
            "s_star_session_index": s_star_index,
            "sessions_remaining_after_s_star_to_hard_stop": remaining_after_s_star,
            "nyse_holidays_used": holidays_used,
        },
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, indent=2)
    with open(SQL_LOG_PATH, "w") as fh:
        for s in SQL_LOG:
            fh.write(s + ";\n\n")

    # Short stdout summary: aggregates only.
    print("started:", t_start)
    print("written:", t_written)
    print("sha256 ok:", integ["sha256_matches"], "mode:", integ["mode"])
    print("9.1 excluded dates:", excluded_dates, "max share: %.4f" % out["day_exclusion_9_1"]["max_share"])
    print("S*:", s_star, "| pending:", cut["pending_judged_collection_rows"], "| readings agree:", cut["readings_agree"])
    print("N=%d C_G=%d null_excess=%d" % (icc["N"], icc["C_G"], null_excess))
    print("sigma=%.12g MSB=%.12g MSW=%.12g n0=%.12g" % (sigma, icc["MSB"], icc["MSW"], icc["n0"]))
    print("rho_raw=%.12g rho=%.12g" % (icc["rho_raw"], rho))
    print("C=%d M=%d k_eff=%.12g" % (dstats["C"], dstats["M"], k_eff))
    print("Required=%.12g (z_sq: %.12g)" % (req, req_zsq))
    print("cond C>=60:", cond_C, "| M>=1000:", cond_M, "| M>=Required:", cond_req, "| PASS:", passes)
    print("only-neutral clusters:", only_neutral_clusters, "| rho_alt:", rho_alt)
    print("float vs exact rel:", icc["float_vs_exact_rel"])
    print("PROJECTION: M/C=%.6f clusters_to_required=%s hard_stop=%s remaining_after_S*=%d" % (
        m_per_c, clusters_to_required, hard_stop_date, remaining_after_s_star))
    print("calendar: sessions missing:", cal_missing_in_data, "| qdates missing:", qdates_missing,
          "| non-trading:", data_not_in_cal, qdates_not_in_cal)
    print("wrote", OUT_JSON)


if __name__ == "__main__":
    main()
