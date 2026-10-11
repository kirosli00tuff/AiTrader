"""Compare my recomputation (<S>_mine.json) with the harness (<S>_harness.json).

Usage: .venv-eval/bin/python reports/c1_verify/compare.py S-EFFECT S-PREMIUM S-HIGHRHO
Prints a markdown table per scenario and an overall verdict line. Exact quantities
must agree to float rounding (rel 1e-9); SE and p within stated Monte Carlo tolerance.
"""
from __future__ import annotations

import json
import math
import sys

N_BOOT = 10_000
N_PERM = 10_000
MC_SIGMAS = 4.0       # tolerance = 4 Monte Carlo standard errors
EXACT_REL = 1e-9


def rel(a, b):
    if a == b:
        return 0.0
    den = max(abs(a), abs(b), 1e-300)
    return abs(a - b) / den


def main(names):
    overall_ok = True
    for name in names:
        mine = json.load(open(f"reports/c1_verify/{name}_mine.json"))
        harn = json.load(open(f"reports/c1_verify/{name}_harness.json"))
        g_h = harn["gate"]
        fam = harn["family"]
        pr = fam["readings"]["primary"]
        p1 = pr["tests"]["P1"]
        nul = pr["null"]
        funnel = fam["analysis_set"]["funnel"]
        cutoff = fam["analysis_set"]["cutoff"]
        day = fam["analysis_set"]["day_rule"]
        m_a, m_p, m_g = mine["analysis_set"], mine["P1"], mine["gate"]

        rows = []  # (quantity, mine, harness, kind, tol, ok)

        def exact(q, a, b):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
                ok = rel(float(a), float(b)) <= EXACT_REL
            else:
                ok = a == b
            rows.append((q, a, b, "exact", "rel 1e-9" if isinstance(a, float) else "equal", ok))
            return ok

        # analysis set
        exact("excluded query_dates (9.1)", m_a["excluded_days"], day["excluded_query_dates"])
        exact("S* (9.7)", m_a["s_star"], cutoff["s_star"])
        exact("latest resolved session", m_a["latest_resolved"], cutoff["latest_resolved"])
        exact("stale pending rows", sum(m_a["stale_pending"].values()), cutoff["stale_pending_rows"])
        exact("rows dropped by day rule (resolved judged)", m_a["dropped_by_day_rule"],
              funnel["dropped_first_reason"]["day_rule"])
        exact("rows dropped beyond S*", m_a["dropped_after_s_star"],
              funnel["dropped_first_reason"]["beyond_s_star"])
        exact("NULL excess excluded (judged, all)", m_a["null_excess_excluded_all"],
              funnel["dropped_first_reason"]["excess_1session_null"])
        exact("gate rows G (NEUTRAL incl.)", mine["counts"]["G"], funnel["gate_rows"])
        exact("scored M", mine["counts"]["scored"], pr["M"])
        exact("clusters D", m_p["C"], pr["D"])
        exact("n POSITIVE", m_p["n_pos"], nul["n_positive"])
        exact("n NEGATIVE", m_p["n_neg"], nul["n_negative"])
        # P1
        exact("P1 T (bp)", m_p["T_bp"], p1["bootstrap"]["statistic"])
        exact("P1 permutation t_obs", m_p["T_bp"], p1["permutation"]["t_obs"])
        exact("P1 clusters", m_p["C"], p1["bootstrap"]["n_clusters"])
        exact("P1 n_obs", m_p["n"], p1["bootstrap"]["n_obs"])
        # SE tolerance: MC sd of a bootstrap SD estimate ~ SE / sqrt(2 (B-1)) for a
        # near-normal replicate distribution; use MC_SIGMAS of that.
        se_m, se_h = m_p["SE_bp"], p1["bootstrap"]["se"]
        se_tol = MC_SIGMAS * se_h / math.sqrt(2 * (N_BOOT - 1))
        ok = abs(se_m - se_h) <= se_tol
        rows.append(("P1 SE (bp)", se_m, se_h, "MC", f"abs {se_tol:.4f} (4 MC se)", ok))
        z_m, z_h = m_p["z"], p1["bootstrap"]["z"]
        z_tol = abs(z_h) * se_tol / se_h
        ok = abs(z_m - z_h) <= z_tol
        rows.append(("P1 z", z_m, z_h, "MC", f"abs {z_tol:.4f} (via SE)", ok))
        # permutation tail counts: binomial MC sd = sqrt(B q (1-q)), q = smaller tail share
        ge_m, le_m = m_p["perm_ge"], m_p["perm_le"]
        ge_h, le_h = p1["permutation"]["count_ge"], p1["permutation"]["count_le"]
        q = max(min(ge_h, le_h), 1) / N_PERM
        cnt_tol = max(MC_SIGMAS * math.sqrt(N_PERM * q * (1 - q)), 1.0)
        ok_ge = abs(ge_m - ge_h) <= cnt_tol
        ok_le = abs(le_m - le_h) <= cnt_tol
        rows.append(("P1 perm count(T_perm >= T_obs)", ge_m, ge_h, "MC", f"abs {cnt_tol:.1f} (4 binomial sd)", ok_ge))
        rows.append(("P1 perm count(T_perm <= T_obs)", le_m, le_h, "MC", f"abs {cnt_tol:.1f} (4 binomial sd)", ok_le))
        p_m, p_h = m_p["perm_p"], p1["permutation"]["p"]
        p_tol = 2 * cnt_tol / (N_PERM + 1)
        ok = abs(p_m - p_h) <= p_tol
        rows.append(("P1 perm p (doubled one-sided, add-one)", p_m, p_h, "MC", f"abs {p_tol:.4f}", ok))
        exact("P1 upper tail", m_p["upper_tail"], p1["permutation"]["upper_tail"])
        # Amendment 6 diagnostics
        exact("minority share", m_p["minority_share"], nul["minority_share"])
        exact("mixed clusters", m_p["mixed_clusters"], nul["n_mixed_clusters"])
        # gate
        exact("gate N_G", m_g["N_G"], g_h["N"])
        exact("gate C_G (n0 clusters)", m_g["C_G"], g_h["C_G"])
        exact("gate C (directional)", m_g["C_dir"], g_h["C"])
        exact("gate M", m_g["M"], g_h["M"])
        exact("sigma (bp)", m_g["sigma_bp"], g_h["sigma"])
        exact("MSB", m_g["MSB"], g_h["MSB"])
        exact("MSW", m_g["MSW"], g_h["MSW"])
        exact("n0", m_g["n0"], g_h["n0"])
        exact("rho raw", m_g["rho_raw"], g_h["rho_raw"])
        exact("rho floored", m_g["rho"], g_h["rho"])
        exact("k_eff", m_g["k_eff"], g_h["k_eff"])
        exact("Required", m_g["required"], g_h["required"])
        exact("gate pass", m_g["passed"], g_h["pass"])

        print(f"\n### {name}\n")
        print("| quantity | mine | harness | kind | tolerance | agree |")
        print("|---|---|---|---|---|---|")
        for q, a, b, kind, tol, ok in rows:
            fa = f"{a:.10g}" if isinstance(a, float) else str(a)
            fb = f"{b:.10g}" if isinstance(b, float) else str(b)
            print(f"| {q} | {fa} | {fb} | {kind} | {tol} | {'yes' if ok else 'NO'} |")
            overall_ok &= bool(ok)
        print(f"\nseeds: mine boot={m_p['boot_seed']} perm={m_p['perm_seed']}; "
              f"harness boot={fam['settings']['boot_seed']} perm={fam['settings']['perm_seed']} "
              f"(stream_index P1 primary = {p1['bootstrap']['stream_index']})")
    print("\nOVERALL:", "all rows agree" if overall_ok else "DISAGREEMENT present")


if __name__ == "__main__":
    main(sys.argv[1:])
