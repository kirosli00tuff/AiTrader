"""Compare own_gate.json (written first) with the frozen harness gate_log.jsonl."""
import json

OWN = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/verify_gate/own_gate.json"
LOG = "/home/kiros-li/Documents/GitHub/AiTrader/reports/c2/gate_log.jsonl"
REL_TOL = 1e-9

own = json.load(open(OWN))
lines = [l for l in open(LOG).read().splitlines() if l.strip()]
assert len(lines) == 1, f"expected one log line, got {len(lines)}"
log = json.loads(lines[0])

g = own["gate_9_8"]
d = own["day_exclusion_9_1"]
c = own["cutoff_9_7"]

# (name, own value, log value, kind)  kind: 'int' exact, 'real' rel 1e-9, 'bool' exact, 'str' exact, 'list' exact
pairs = [
    ("snapshot sha256", own["snapshot"]["sha256"], log["inputs_sha256"], "str"),
    ("excluded query_dates", sorted(d["excluded_dates"]), sorted(log["excluded_query_dates"].keys()), "list"),
    ("latest resolved session", c["latest_resolved_session"], log["latest_resolved_session"], "str"),
    ("pending judged rows (own) vs stale_pending_count+nonstale (log)", c["pending_judged_collection_rows"],
        log["stale_pending_count"] + (0 if log["earliest_nonstale_pending_session"] is None else -1), "int"),
    ("stale count", c["stale_count_reading_A_calendar_sessions"], log["stale_pending_count"], "int"),
    ("S*", c["s_star"], log["s_star"], "str"),
    ("N", g["N"], log["N"], "int"),
    ("C_G", g["C_G"], log["C_G"], "int"),
    ("null-excess count", g["null_excess_among_otherwise_G"], log["null_excess_count"], "int"),
    ("sigma (bp)", g["sigma_bp"], log["sigma"], "real"),
    ("MSB", g["MSB"], log["MSB"], "real"),
    ("MSW", g["MSW"], log["MSW"], "real"),
    ("n0", g["n0"], log["n0"], "real"),
    ("rho_raw", g["rho_raw"], log["rho_raw"], "real"),
    ("rho (floored)", g["rho"], log["rho"], "real"),
    ("C", g["C"], log["C"], "int"),
    ("M", g["M"], log["M"], "int"),
    ("k_eff", g["k_eff"], log["k_eff"], "real"),
    ("Required", g["Required"], log["required"], "real"),
    ("cond C>=60", g["cond_C_ge_60"], "C" not in [f.upper() for f in log["failing"]] and "CLUSTERS" not in log["failing"], "bool"),
    ("cond M>=1000", g["cond_M_ge_1000"], "SCORABLE" not in log["failing"] and "M" not in log["failing"], "bool"),
    ("cond M>=Required", g["cond_M_ge_Required"], "REQUIRED" not in log["failing"], "bool"),
    ("pass", g["pass"], log["pass"], "bool"),
    ("const 11.156", own["constants"]["const_11156_literal"], log["constants"]["REQUIRED_FACTOR"], "real"),
    ("delta 30 bp", own["constants"]["delta_bp"], log["constants"]["EFFECT_BP"], "real"),
    ("min clusters 60", own["constants"]["min_clusters"], log["constants"]["FLOOR_ANALYSIS_CLUSTERS"], "int"),
    ("min M 1000", own["constants"]["min_M"], log["constants"]["FLOOR_SCORABLE"], "int"),
    ("day-exclusion share 0.2", own["constants"]["day_exclusion_share_strict_gt"], log["constants"]["SOURCE_FAILED_DAY_EXCLUDE"], "real"),
    ("stale sessions 3", own["constants"]["stale_sessions"], log["constants"]["STALE_PENDING_SESSIONS"], "int"),
]

rows = []
all_ok = True
for name, a, b, kind in pairs:
    if kind == "real":
        denom = max(abs(a), abs(b))
        rel = abs(a - b) / denom if denom else 0.0
        ok = rel <= REL_TOL
        rows.append((name, repr(a), repr(b), f"{rel:.3e}", "MATCH" if ok else "MISMATCH"))
    else:
        ok = a == b
        rows.append((name, repr(a), repr(b), "exact", "MATCH" if ok else "MISMATCH"))
    all_ok &= ok

print("| Quantity | Own | Log | Rel diff | Result |")
print("|---|---|---|---|---|")
for r in rows:
    print("| " + " | ".join(str(x) for x in r) + " |")
print()
print("ALL MATCH" if all_ok else "SOME MISMATCH")
print("log failing:", log["failing"], "| failing_detail:", log["failing_detail"])
print("log s_star_case:", log["s_star_case"], "| degenerate:", repr(log["degenerate_condition"]), "| status:", log["status"], "| test_mode:", log["test_mode"], "| db_class:", log["db_class"])
print("log utc_time:", log["utc_time"], "| db_path:", log["db_path"])
print("log empty_session_pending_count:", log["empty_session_pending_count"], "| earliest_nonstale_pending_session:", log["earliest_nonstale_pending_session"])
print("own Required with (2.50+0.84)^2 = 11.1556:", own["gate_9_8"]["Required_with_z_sq_11_1556"])
