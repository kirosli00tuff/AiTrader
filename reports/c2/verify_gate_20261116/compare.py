"""Compare own_gate.json with the registered gate log entry for the same snapshot.
Exact for counts, dates, booleans and strings; 1e-9 relative for reals. No SQL here."""
import hashlib
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOGF = os.path.join(ROOT, "reports", "c2", "gate_log.jsonl")
FREEZE = os.path.join(ROOT, "reports", "c3_harness_freeze.json")
SNAP = os.path.join(ROOT, "reports", "c2", "snap_20261116", "news_experiment_snapshot.db")
TOL = 1e-9

own = json.load(open(os.path.join(HERE, "own_gate.json")))
src = open(os.path.join(HERE, "verify_gate.py")).read()
sha = own["integrity"]["snapshot_sha256"]

entries = [json.loads(l) for l in open(LOGF) if l.strip()]
match = [e for e in entries if e.get("inputs_sha256") == sha]
lines = []
lines.append("gate_log entries: %d; entries for this snapshot sha256: %d" % (len(entries), len(match)))
if len(match) != 1:
    open(os.path.join(HERE, "compare.out"), "w").write("\n".join(lines) + "\nRESULT: MISMATCH (entry count)\n")
    raise SystemExit("expected exactly one entry, found %d" % len(match))
log = match[0]


def const(name):
    m = re.search(r"^%s\s*=\s*([0-9.]+)" % name, src, re.M)
    return float(m.group(1))


def rel(a, b):
    a, b = float(a), float(b)
    return 0.0 if a == b else abs(a - b) / max(abs(a), abs(b))


g, s7, s1 = own["s9_8"], own["s9_7"], own["s9_1"]
own_failing = sorted(n for n, ok in (("CLUSTERS_FLOOR", g["cond_C_ge_60"]), ("M_FLOOR", g["cond_M_ge_1000"]),
                                     ("REQUIRED", g["cond_M_ge_required"])) if not ok)
own_stale_sessions = [] if (s7["pending_judged_collection_rows"] == 0 and s7["stale_pending_rows"] == 0) else None
h = hashlib.sha256(open(FREEZE, "rb").read()).hexdigest()
fd = re.fullmatch(r"M (\d+) < Required ([0-9.]+)", log["failing_detail"][0]) if len(log.get("failing_detail", [])) == 1 else None

rows = []   # (group, log field, own, log, kind)
EX = "exact"
RE = "real"
rows += [("gate", k, g[o], log[k], EX) for k, o in (
    ("N", "N"), ("C_G", "C_G"), ("C", "C"), ("M", "M"),
    ("null_excess_count", "null_excess_among_rows_meeting_other_conditions"), ("pass", "gate_pass"))]
rows += [("gate", "excluded_query_dates", sorted(s1["primary_excluded_query_dates"]), sorted(list(log["excluded_query_dates"])), EX),
         ("gate", "latest_resolved_session", s7["latest_resolved_session"], log["latest_resolved_session"], EX),
         ("gate", "s_star", s7["s_star"], log["s_star"], EX),
         ("gate", "earliest_nonstale_pending_session", s7["earliest_non_stale_pending_session"], log["earliest_nonstale_pending_session"], EX),
         ("gate", "stale_pending_count", s7["stale_pending_rows"], log["stale_pending_count"], EX),
         ("gate", "stale_pending_sessions", own_stale_sessions, log["stale_pending_sessions"], EX),
         ("gate", "empty_session_pending_count", s7["pending_with_empty_scoring_session"], log["empty_session_pending_count"], EX),
         ("gate", "failing", own_failing, sorted(log["failing"]), EX)]
rows += [("gate", k, g[k], log[k], RE) for k in ("sigma", "MSB", "MSW", "n0", "rho_raw", "rho", "k_eff", "required")]
rows += [("string", "failing_detail", "M %d < Required %.3f" % (g["M"], g["required"]),
          log["failing_detail"][0] if fd else repr(log.get("failing_detail")), EX)]
rows += [("constant", "constants." + k, const(o), log["constants"][k], RE) for k, o in (
    ("REQUIRED_FACTOR", "FACTOR_LITERAL"), ("EFFECT_BP", "DELTA_BP"), ("FLOOR_ANALYSIS_CLUSTERS", "MIN_CLUSTERS"),
    ("FLOOR_SCORABLE", "MIN_M"), ("SOURCE_FAILED_DAY_EXCLUDE", "SOURCE_FAILED_LIMIT"),
    ("STALE_PENDING_SESSIONS", "STALE_SESSIONS"))]
rows += [("identity", "inputs_sha256", sha, log["inputs_sha256"], EX),
         ("identity", "manifest_sha256", h, log["manifest_sha256"], EX),
         ("identity", "db_path", os.path.realpath(SNAP), os.path.realpath(log["db_path"]), EX)]

compared = {r[1].split(".")[0] for r in rows}
not_recomputed = ["db_class", "degenerate_condition", "s_star_case", "status", "test_mode", "utc_time"]
unaccounted = sorted(set(log) - compared - set(not_recomputed))

bad = 0
worst = (0.0, None)
lines.append("%-9s %-36s %-28s %-28s %-6s %-10s %s" % ("group", "log field", "own", "log", "rule", "rel diff", "ok"))
for grp, name, o, l, kind in rows:
    if kind == RE:
        d = rel(o, l)
        ok = d <= TOL
        if d > worst[0]:
            worst = (d, name)
        ds = "%.3e" % d
    else:
        ok = (o == l) and type(o) is type(l)
        ds = "0" if ok else "DIFF"
    bad += (not ok)
    lines.append("%-9s %-36s %-28s %-28s %-6s %-10s %s" % (grp, name, repr(o)[:28], repr(l)[:28], kind, ds, "OK" if ok else "MISMATCH"))
lines.append("")
lines.append("compared: %d (gate %d, string %d, constant %d, identity %d); mismatches: %d" % (
    len(rows), sum(r[0] == "gate" for r in rows), sum(r[0] == "string" for r in rows),
    sum(r[0] == "constant" for r in rows), sum(r[0] == "identity" for r in rows), bad))
lines.append("largest relative difference on reals: %.3e (%s); tolerance %.0e" % (worst[0], worst[1], TOL))
lines.append("log fields not recomputed: " + ", ".join("%s=%r" % (k, log.get(k)) for k in not_recomputed))
lines.append("log fields unaccounted for: %r" % unaccounted)
lines.append("own quantities with no log field: hard_stop_session=%s, bound=%s, rows_dropped_by_bound=%d, "
             "pending_judged_collection_rows=%d, largest source_failed shares, m_c and n_c per cluster, "
             "the three pass conditions as separate booleans" % (
                 own["s10_1_bound"]["hard_stop_session"], own["s10_1_bound"]["bound_min_s_star_hard_stop"],
                 g["rows_dropped_by_bound"], s7["pending_judged_collection_rows"]))
lines.append("sha256(reports/c3_harness_freeze.json) = %s; equals log manifest_sha256: %s" % (h, h == log["manifest_sha256"]))
result = "MATCH" if (bad == 0 and not unaccounted) else "MISMATCH"
lines.append("RESULT: %s; own pass decision: %s; log pass: %s" % (result, g["gate_pass"], log["pass"]))
open(os.path.join(HERE, "compare.out"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines[-7:]))
