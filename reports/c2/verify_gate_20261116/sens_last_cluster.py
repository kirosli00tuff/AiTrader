"""Post-log sensitivity, NOT the registered gate: the same 9.8 arithmetic with the
last session (2026-11-16) left out, i.e. bound = 2026-11-13, the latest scoring_session
whose own query_date is in the snapshot. Reads scoring_session and excess_1session of
gate rows only; m_c is reused from own_gate.json (no new judgment query). SQL is logged."""
import sqlite3, datetime, os, sys, json, math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SNAP = os.path.join(ROOT, "reports", "c2", "snap_20261116", "news_experiment_snapshot.db")
LOG = os.path.join(HERE, "verify_gate.sql.log")
ALT_BOUND = "2026-11-13"


def q(con, sql, params=()):
    with open(LOG, "a") as fh:
        fh.write("%s\t%s\t%s\tparams=%r\n" % (
            datetime.datetime.now().isoformat(timespec="seconds"),
            os.path.basename(sys.argv[0]), " ".join(sql.split()), tuple(params)))
    return con.execute(sql, params).fetchall()


own = json.load(open(os.path.join(HERE, "own_gate.json")))
assert own["s9_1"]["primary_excluded_query_dates"] == []
con = sqlite3.connect("file:%s?mode=ro&immutable=1" % SNAP, uri=True)
rows = q(con, "SELECT scoring_session, excess_1session FROM news_observation WHERE run_kind='collection' "
              "AND state='judged' AND outcome_state='resolved' AND exclusion_reason='' "
              "AND excess_1session IS NOT NULL AND scoring_session IS NOT NULL AND scoring_session<>'' "
              "AND scoring_session<=?", (ALT_BOUND,))
cl = {}
for s, e in rows:
    cl.setdefault(s, []).append(10000.0 * e)
N = len(rows); CG = len(cl)
allx = [x for v in cl.values() for x in v]
gm = math.fsum(allx) / N
sigma = math.sqrt(math.fsum((x - gm) ** 2 for x in allx) / (N - 1))
cm = {s: math.fsum(v) / len(v) for s, v in cl.items()}
MSB = math.fsum(len(v) * (cm[s] - gm) ** 2 for s, v in cl.items()) / (CG - 1)
MSW = math.fsum((x - cm[s]) ** 2 for s, v in cl.items() for x in v) / (N - CG)
n0 = (N - sum(len(v) ** 2 for v in cl.values()) / N) / (CG - 1)
rho_raw = (MSB - MSW) / (MSB + (n0 - 1) * MSW); rho = max(0.0, rho_raw)
m_c = {s: n for s, n in own["s9_8"]["m_c"].items() if s <= ALT_BOUND}
M = sum(m_c.values()); C = len(m_c); k_eff = sum(v * v for v in m_c.values()) / M
req = 11.156 * (sigma / 30.0) ** 2 * (1 + (k_eff - 1) * rho)
out = {"note": "sensitivity only, not the registered gate", "bound": ALT_BOUND, "N": N, "C_G": CG, "M": M, "C": C,
       "sigma": sigma, "MSB": MSB, "MSW": MSW, "n0": n0, "rho_raw": rho_raw, "rho": rho, "k_eff": k_eff,
       "required": req, "cond_C_ge_60": C >= 60, "cond_M_ge_1000": M >= 1000, "cond_M_ge_required": M >= req,
       "pass": bool(C >= 60 and M >= 1000 and M >= req)}
json.dump(out, open(os.path.join(HERE, "sens_last_cluster.json"), "w"), indent=1)
print(json.dumps(out))
