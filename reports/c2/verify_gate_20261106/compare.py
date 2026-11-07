#!/usr/bin/env python3
"""Compare own_gate.json (GateVerifier-FableXHigh) with the registered gate
log entry for the 20261106 snapshot. Exact for counts, dates, booleans and
strings; within 1e-9 relative for reals. Writes compare.out beside it."""
import hashlib
import json
import math

ROOT = "/home/kiros-li/Documents/GitHub/AiTrader"
OWN = f"{ROOT}/reports/c2/verify_gate_20261106/own_gate.json"
LOG = f"{ROOT}/reports/c2/gate_log.jsonl"
MANIFEST = f"{ROOT}/reports/c3_harness_freeze.json"
OUT = f"{ROOT}/reports/c2/verify_gate_20261106/compare.out"
REL_TOL = 1e-9


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_diff(a, b):
    if a == b:
        return 0.0
    den = max(abs(a), abs(b))
    return abs(a - b) / den if den else float("inf")


def main():
    own = json.load(open(OWN))
    snap_sha = own["integrity"]["sha256_computed"]
    entries = [json.loads(l) for l in open(LOG) if l.strip()]
    matches = [e for e in entries if e.get("inputs_sha256") == snap_sha]
    lines = []
    lines.append(f"own_gate.json: {OWN}")
    lines.append(f"gate_log.jsonl entries: {len(entries)}; entries with inputs_sha256 == snapshot sha256: {len(matches)}")
    if len(matches) != 1:
        lines.append("RESULT: MISMATCH (snapshot does not have exactly one log entry)")
        open(OUT, "w").write("\n".join(lines) + "\n")
        print("\n".join(lines))
        return
    log = matches[0]
    manifest_sha = sha256_of(MANIFEST)

    # three sides: (name, own value, log value, kind) kind in {exact, real}
    own_pass = own["pass_9_8"]
    own_failing = [name for cond, name in (
        (own_pass["C_at_least_60"], "CLUSTERS"),
        (own_pass["M_at_least_1000"], "SCORABLE"),
        (own_pass["M_at_least_Required"], "REQUIRED")) if not cond]
    rows = [
        ("inputs_sha256", snap_sha, log.get("inputs_sha256"), "exact"),
        ("db_path", own["integrity"]["snapshot_path"], log.get("db_path"), "exact"),
        ("manifest_sha256 vs sha256sum(c3_harness_freeze.json)", manifest_sha, log.get("manifest_sha256"), "exact"),
        ("excluded_query_dates", sorted(own["day_rule_9_1"]["excluded_query_dates"]),
         sorted(log.get("excluded_query_dates", {}).keys()) if isinstance(log.get("excluded_query_dates"), dict)
         else sorted(log.get("excluded_query_dates") or []), "exact"),
        ("latest_resolved_session", own["cutoff_9_7"]["latest_resolved_session"], log.get("latest_resolved_session"), "exact"),
        ("stale_pending_count", own["cutoff_9_7"]["stale_pending_rows"], log.get("stale_pending_count"), "exact"),
        ("stale_pending_sessions", [], log.get("stale_pending_sessions"), "exact"),
        ("earliest_nonstale_pending_session", own["cutoff_9_7"]["earliest_non_stale_pending_session"],
         log.get("earliest_nonstale_pending_session"), "exact"),
        ("empty_session_pending_count (own: judged collection rows with NULL/empty scoring_session, 0 of any outcome_state)",
         0 if own["vocab"]["scoring_session_class_judged_collection"].get("SET", 0)
         == sum(own["vocab"]["scoring_session_class_judged_collection"].values()) else None,
         log.get("empty_session_pending_count"), "exact"),
        ("s_star", own["cutoff_9_7"]["S_star"], log.get("s_star"), "exact"),
        ("N", own["gate_rows_G"]["N"], log.get("N"), "exact"),
        ("C_G", own["gate_rows_G"]["C_G"], log.get("C_G"), "exact"),
        ("null_excess_count", own["gate_rows_G"]["null_excess_1session_among_rows_meeting_other_conditions"],
         log.get("null_excess_count"), "exact"),
        ("sigma", own["sigma_rho"]["sigma_bp_ddof1"], log.get("sigma"), "real"),
        ("MSB", own["sigma_rho"]["MSB"], log.get("MSB"), "real"),
        ("MSW", own["sigma_rho"]["MSW"], log.get("MSW"), "real"),
        ("n0", own["sigma_rho"]["n0"], log.get("n0"), "real"),
        ("rho_raw", own["sigma_rho"]["rho_raw"], log.get("rho_raw"), "real"),
        ("rho", own["sigma_rho"]["rho"], log.get("rho"), "real"),
        ("M", own["directional_9_8"]["M"], log.get("M"), "exact"),
        ("C", own["directional_9_8"]["C"], log.get("C"), "exact"),
        ("k_eff", own["directional_9_8"]["k_eff"], log.get("k_eff"), "real"),
        ("required", own["required_9_8"]["required"], log.get("required"), "real"),
        ("pass", own_pass["gate_passes"], log.get("pass"), "exact"),
        ("failing (own: derived from the three conditions)", own_failing, log.get("failing"), "exact"),
        ("constants.REQUIRED_FACTOR", own["required_9_8"]["z_const_used"], log.get("constants", {}).get("REQUIRED_FACTOR"), "real"),
        ("constants.EFFECT_BP", own["required_9_8"]["delta_bp"], log.get("constants", {}).get("EFFECT_BP"), "real"),
        ("constants.FLOOR_ANALYSIS_CLUSTERS", 60, log.get("constants", {}).get("FLOOR_ANALYSIS_CLUSTERS"), "exact"),
        ("constants.FLOOR_SCORABLE", 1000, log.get("constants", {}).get("FLOOR_SCORABLE"), "exact"),
        ("constants.SOURCE_FAILED_DAY_EXCLUDE", own["day_rule_9_1"]["limit_strict_greater_than"],
         log.get("constants", {}).get("SOURCE_FAILED_DAY_EXCLUDE"), "real"),
        ("constants.STALE_PENDING_SESSIONS", 3, log.get("constants", {}).get("STALE_PENDING_SESSIONS"), "exact"),
    ]
    n_ok, n_bad, worst = 0, 0, 0.0
    lines.append("")
    lines.append(f"{'quantity':<70} {'own':>24} {'log':>24} {'rel_diff':>12} {'ok':>5}")
    for name, a, b, kind in rows:
        if kind == "real":
            if a is None or b is None:
                ok, rd = False, float("inf")
            else:
                rd = rel_diff(float(a), float(b))
                ok = rd <= REL_TOL and math.isfinite(rd)
            worst = max(worst, rd if math.isfinite(rd) else 1e300)
            lines.append(f"{name:<70} {a!r:>24} {b!r:>24} {rd:>12.3e} {str(ok):>5}")
        else:
            ok = (a == b)
            sa, sb = json.dumps(a), json.dumps(b)
            lines.append(f"{name:<70} {sa[-24:]:>24} {sb[-24:]:>24} {'exact':>12} {str(ok):>5}")
        n_ok += ok
        n_bad += (not ok)
    not_recomputed = sorted(k for k in log if k not in {
        "inputs_sha256", "db_path", "manifest_sha256", "excluded_query_dates", "latest_resolved_session",
        "stale_pending_count", "stale_pending_sessions", "earliest_nonstale_pending_session",
        "empty_session_pending_count", "s_star", "N", "C_G", "null_excess_count", "sigma", "MSB", "MSW",
        "n0", "rho_raw", "rho", "M", "C", "k_eff", "required", "pass", "failing", "constants"})
    own_only = ["hard_stop_session (2027-01-15; the log carries no hard-stop field)",
                "pending_judged_rows total (0)",
                "max_source_failed_share and its query_date (33/476 on 2026-10-07)",
                "design_effect 1 + (k_eff - 1) rho",
                "required_with_exact_const (2.50 + 0.84)^2 = 11.1556 sensitivity"]
    lines.append("")
    lines.append(f"compared: {len(rows)}  ok: {n_ok}  mismatched: {n_bad}  largest relative difference over reals: {worst:.3e}")
    lines.append(f"log fields not recomputed by this verifier: {not_recomputed}")
    lines.append(f"own quantities with no log counterpart: {own_only}")
    lines.append(f"log entries for this snapshot: {len(matches)} (required: exactly 1)")
    lines.append(f"manifest_sha256 matches sha256sum reports/c3_harness_freeze.json: {log.get('manifest_sha256') == manifest_sha}")
    verdict = "MATCH" if (n_bad == 0 and len(matches) == 1) else "MISMATCH"
    lines.append(f"RESULT: {verdict}; own pass decision: {own_pass['gate_passes']}; log pass: {log.get('pass')}")
    open(OUT, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines[-7:]))


if __name__ == "__main__":
    main()
