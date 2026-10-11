"""Independent recomputation of the Stage C.1 key statistics (KnownAnswerVerifier, Task 8a).

Written from EXPERIMENT.md Amendments 5, 6, 8.4 and 9 (9.1, 9.4, 9.5, 9.7, 9.8, 9.9)
and Task 7's day rule ONLY. news_eval/stats.py, family.py, gate.py, cutoff.py and
verdict.py were not opened before this file was written and run.

Usage: .venv-eval/bin/python reports/c1_verify/verify.py <db> <out.json> [--boot-seed N] [--perm-seed N]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict

import numpy as np

N_BOOT = 10_000
N_PERM = 10_000
BAR = 2.50
DAY_EXCLUDE_SHARE = 0.20      # Task 7: "exceeds 20 percent" -> strictly greater
STALE_SESSIONS = 3            # 9.7: more than 3 sessions before the latest resolved
REQUIRED_FACTOR = 11.156      # 9.8: (2.50 + 0.84)^2
EFFECT_BP = 30.0
BP = 10_000.0


def fetch(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return cur.fetchall()


def analysis_set(db_path: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # ---- 9.1 / Task 7 day exclusion, by collection query_date over ALL collection rows
    day_rows = fetch(conn, """
        SELECT query_date, COUNT(*) AS n, SUM(state='source_failed') AS sf
        FROM news_observation WHERE run_kind='collection' GROUP BY query_date""")
    excluded_days = sorted(r["query_date"] for r in day_rows
                           if r["sf"] / r["n"] > DAY_EXCLUDE_SHARE)
    excluded_day_shares = {r["query_date"]: r["sf"] / r["n"] for r in day_rows
                           if r["query_date"] in excluded_days}

    # ---- 9.7 S*: latest scoring_session at or before which no judged collection row is
    # still pending; a pending row > 3 sessions before the latest resolved session is stale.
    sessions = sorted(r[0] for r in fetch(conn, """
        SELECT DISTINCT scoring_session FROM news_observation
        WHERE run_kind='collection' AND state='judged'
          AND scoring_session IS NOT NULL AND scoring_session<>''"""))
    sidx = {s: i for i, s in enumerate(sessions)}
    latest_resolved = fetch(conn, """
        SELECT MAX(scoring_session) FROM news_observation
        WHERE run_kind='collection' AND state='judged' AND outcome_state='resolved'
          AND scoring_session IS NOT NULL AND scoring_session<>''""")[0][0]
    pend = fetch(conn, """
        SELECT scoring_session, COUNT(*) FROM news_observation
        WHERE run_kind='collection' AND state='judged' AND outcome_state='pending'
        GROUP BY scoring_session""")
    pending_empty_session = sum(c for s, c in pend if s is None or s == "")
    pending_placed = {s: c for s, c in pend if s is not None and s != ""}
    stale = {s: c for s, c in pending_placed.items()
             if sidx[latest_resolved] - sidx[s] > STALE_SESSIONS}
    live_pending = sorted(s for s in pending_placed if s not in stale)
    if live_pending:
        first_live = live_pending[0]
        i = sidx[first_live]
        s_star = sessions[i - 1] if i > 0 else None
    else:
        s_star = sessions[-1]

    # ---- 9.7 scorable rows (judgment condition applied) and 9.8 gate rows G (without it)
    base_where = """
        run_kind='collection' AND state='judged' AND outcome_state='resolved'
        AND exclusion_reason='' AND scoring_session IS NOT NULL AND scoring_session<>''
    """
    rows = fetch(conn, f"""
        SELECT id, symbol, query_date, scoring_session, stratum, judgment,
               excess_1session, net_bp
        FROM news_observation WHERE {base_where}""")
    conn.close()

    ex_days = set(excluded_days)
    g_rows, scored, null_excess_dir, null_excess_all = [], [], 0, 0
    dropped_day, dropped_after_sstar = 0, 0
    for r in rows:
        if r["query_date"] in ex_days:
            dropped_day += 1
            continue
        if s_star is None or r["scoring_session"] > s_star:
            dropped_after_sstar += 1
            continue
        if r["excess_1session"] is None:
            null_excess_all += 1
            if r["judgment"] in ("POSITIVE", "NEGATIVE"):
                null_excess_dir += 1
            continue   # excluded and counted, never read as 0
        g_rows.append(r)
        if r["judgment"] in ("POSITIVE", "NEGATIVE"):
            scored.append(r)

    return dict(
        excluded_days=excluded_days, excluded_day_shares=excluded_day_shares,
        sessions_n=len(sessions), latest_resolved=latest_resolved, s_star=s_star,
        pending_placed=pending_placed, stale_pending=stale,
        pending_empty_session=pending_empty_session,
        dropped_by_day_rule=dropped_day, dropped_after_s_star=dropped_after_sstar,
        null_excess_excluded_all=null_excess_all,
        null_excess_excluded_directional=null_excess_dir,
        g_rows=g_rows, scored=scored,
    )


def p1_statistics(scored, boot_seed: int, perm_seed: int) -> dict:
    sess = np.array([r["scoring_session"] for r in scored])
    sign = np.array([1.0 if r["judgment"] == "POSITIVE" else -1.0 for r in scored])
    excess_bp = np.array([BP * r["excess_1session"] for r in scored], dtype=float)
    signed = sign * excess_bp
    n = len(scored)
    T = signed.sum() / n                                  # 9.4 observation-weighted

    clusters = sorted(set(sess.tolist()))
    C = len(clusters)
    cidx = {c: i for i, c in enumerate(clusters)}
    ci = np.array([cidx[s] for s in sess])
    S = np.bincount(ci, weights=signed, minlength=C)      # per-cluster sums
    Nc = np.bincount(ci, minlength=C).astype(float)       # per-cluster counts

    # 9.5 cluster bootstrap: C clusters with replacement, ratio over all drawn obs
    rng = np.random.default_rng(boot_seed)
    counts = rng.multinomial(C, np.full(C, 1.0 / C), size=N_BOOT)
    T_b = (counts @ S) / (counts @ Nc)
    SE = float(np.std(T_b, ddof=1))
    z = T / SE
    lo, hi = T - BAR * SE, T + BAR * SE
    pct = np.quantile(T_b, [0.00621, 0.99379])            # descriptive only

    # Amendment 6 / 9.9: within-cluster label permutation, 10,000 draws
    rng_p = np.random.default_rng(perm_seed)
    perm_sum = np.zeros(N_PERM)
    for c in range(C):
        idx = np.where(ci == c)[0]
        x = excess_bp[idx]
        k_pos = int((sign[idx] > 0).sum())
        nc = len(idx)
        tot = x.sum()
        if k_pos == 0 or k_pos == nc:
            perm_sum += (tot if k_pos == nc else -tot)    # unanimous: constant
            continue
        # a uniform random permutation of the labels == choose k_pos positions uniformly
        order = np.argsort(rng_p.random((N_PERM, nc)), axis=1)[:, :k_pos]
        pos_sum = np.take_along_axis(np.broadcast_to(x, (N_PERM, nc)), order, axis=1).sum(axis=1)
        perm_sum += 2.0 * pos_sum - tot
    T_perm = perm_sum / n
    ge = int((T_perm >= T).sum())
    le = int((T_perm <= T).sum())
    p = min(1.0, 2.0 * min(1 + ge, 1 + le) / (N_PERM + 1))
    upper_tail = ge < le

    # Amendment 6 skew diagnostic
    n_pos = int((sign > 0).sum())
    n_neg = n - n_pos
    minority_share = min(n_pos, n_neg) / n
    mixed = 0
    for c in range(C):
        s_c = sign[ci == c]
        if (s_c > 0).any() and (s_c < 0).any():
            mixed += 1

    return dict(n=n, n_pos=n_pos, n_neg=n_neg, C=C, T_bp=T, SE_bp=SE, z=z,
                lo_bp=lo, hi_bp=hi, pct_lo_bp=float(pct[0]), pct_hi_bp=float(pct[1]),
                perm_p=p, perm_ge=ge, perm_le=le, upper_tail=upper_tail,
                perm_null_mean_bp=float(T_perm.mean()), perm_null_sd_bp=float(T_perm.std(ddof=1)),
                minority_share=minority_share, mixed_clusters=mixed,
                boot_seed=boot_seed, perm_seed=perm_seed)


def gate(g_rows, scored) -> dict:
    y = np.array([BP * r["excess_1session"] for r in g_rows], dtype=float)
    g_sess = np.array([r["scoring_session"] for r in g_rows])
    N = len(y)
    sigma = float(np.std(y, ddof=1))

    clusters = sorted(set(g_sess.tolist()))
    C_G = len(clusters)
    cidx = {c: i for i, c in enumerate(clusters)}
    ci = np.array([cidx[s] for s in g_sess])
    n_c = np.bincount(ci, minlength=C_G).astype(float)
    sum_c = np.bincount(ci, weights=y, minlength=C_G)
    mean_c = sum_c / n_c
    grand = y.mean()
    SSB = float((n_c * (mean_c - grand) ** 2).sum())
    SSW = float(((y - mean_c[ci]) ** 2).sum())
    MSB = SSB / (C_G - 1)
    MSW = SSW / (N - C_G)
    n0 = (N - (n_c ** 2).sum() / N) / (C_G - 1)
    rho_raw = (MSB - MSW) / (MSB + (n0 - 1) * MSW)
    rho = max(0.0, rho_raw)

    m = defaultdict(int)
    for r in scored:
        m[r["scoring_session"]] += 1
    m_c = np.array(list(m.values()), dtype=float)
    M = int(m_c.sum())
    C_dir = len(m_c)
    k_eff = float((m_c ** 2).sum() / M)
    required = REQUIRED_FACTOR * (sigma / EFFECT_BP) ** 2 * (1 + (k_eff - 1) * rho)
    passed = (C_dir >= 60) and (M >= 1000) and (M >= required)
    return dict(N_G=N, C_G=C_G, sigma_bp=sigma, MSB=MSB, MSW=MSW, n0=n0,
                rho_raw=rho_raw, rho=rho, C_dir=C_dir, M=M, k_eff=k_eff,
                required=required, passed=bool(passed))


def main(argv):
    db, out = argv[1], argv[2]
    boot_seed = 7_001
    perm_seed = 7_002
    if "--boot-seed" in argv:
        boot_seed = int(argv[argv.index("--boot-seed") + 1])
    if "--perm-seed" in argv:
        perm_seed = int(argv[argv.index("--perm-seed") + 1])
    a = analysis_set(db)
    res = {
        "db": db,
        "analysis_set": {k: v for k, v in a.items() if k not in ("g_rows", "scored")},
        "counts": {"G": len(a["g_rows"]), "scored": len(a["scored"])},
        "P1": p1_statistics(a["scored"], boot_seed, perm_seed),
        "gate": gate(a["g_rows"], a["scored"]),
    }
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    s = res["analysis_set"]; p = res["P1"]; g = res["gate"]
    print(f"{db}: excluded_days={s['excluded_days']} S*={s['s_star']} stale={s['stale_pending']} "
          f"pending_empty={s['pending_empty_session']} drop_day={s['dropped_by_day_rule']} "
          f"drop_after_S*={s['dropped_after_s_star']} null_excess(all/dir)="
          f"{s['null_excess_excluded_all']}/{s['null_excess_excluded_directional']}")
    print(f"  G={res['counts']['G']} scored={res['counts']['scored']} C={p['C']} "
          f"pos/neg={p['n_pos']}/{p['n_neg']} minority={p['minority_share']:.4f} mixed={p['mixed_clusters']}")
    print(f"  P1 T={p['T_bp']:.4f} SE={p['SE_bp']:.4f} z={p['z']:.4f} [{p['lo_bp']:.3f},{p['hi_bp']:.3f}] "
          f"p={p['perm_p']:.5f} ge={p['perm_ge']} le={p['perm_le']} upper={p['upper_tail']} "
          f"null_mean={p['perm_null_mean_bp']:.3f} null_sd={p['perm_null_sd_bp']:.3f}")
    print(f"  gate sigma={g['sigma_bp']:.4f} rho_raw={g['rho_raw']:.6f} rho={g['rho']:.6f} n0={g['n0']:.4f} "
          f"k_eff={g['k_eff']:.4f} Required={g['required']:.2f} C_dir={g['C_dir']} C_G={g['C_G']} "
          f"M={g['M']} N_G={g['N_G']} pass={g['passed']}")


if __name__ == "__main__":
    main(sys.argv)
