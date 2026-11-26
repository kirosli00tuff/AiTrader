#!/usr/bin/env python
"""Compare own_gate.json (my recomputation) with the registered gate log entry.

Written after own_gate.json was on disk. Exact for counts, dates, strings and
booleans; within 1e-9 relative for reals. Writes compare.out.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

REPO = "/home/kiros-li/Documents/GitHub/AiTrader"
OUT_DIR = REPO + "/reports/c2/verify_gate_20261125"
OWN = OUT_DIR + "/own_gate.json"
LOG = REPO + "/reports/c2/gate_log.jsonl"
MANIFEST = REPO + "/reports/c3_harness_freeze.json"
OUT = OUT_DIR + "/compare.out"
REL_TOL = 1e-9

sys.path.insert(0, OUT_DIR)
import verify_gate as vg  # my own module, for the constants taken from the registered text  # noqa: E402


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(a: float, b: float) -> float:
    if a == b:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b))


def main() -> int:
    own = json.load(open(OWN, encoding="utf-8"))
    entries = [json.loads(line) for line in open(LOG, encoding="utf-8") if line.strip()]
    sha = own["integrity"]["sha256_computed"]
    matching = [e for e in entries if e.get("inputs_sha256") == sha]
    lines: list[str] = []
    lines.append(f"own_gate.json sha256: {sha256_file(OWN)}")
    lines.append(f"gate_log.jsonl sha256: {sha256_file(LOG)}  entries: {len(entries)}")
    lines.append(f"entries with inputs_sha256 == snapshot sha256: {len(matching)}")
    if len(matching) != 1:
        lines.append("RESULT: MISMATCH (the snapshot does not have exactly one log entry)")
        open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print("\n".join(lines))
        return 1
    e = matching[0]
    g, s97 = own["gate"], own["s97"]

    only_required_fails = bool(g["pass_C_ge_60"] and g["pass_M_ge_1000"] and not g["pass_M_ge_Required"])
    own_failing = ([] if g["pass_C_ge_60"] else ["<C>"]) + ([] if g["pass_M_ge_1000"] else ["<M>"]) \
        + ([] if g["pass_M_ge_Required"] else ["REQUIRED"])
    own_detail = [f"M {g['M']} < Required {g['Required']:.3f}"] if only_required_fails else ["<not derivable>"]

    # (label, kind, own value, log value); kind: exact | real
    pairs: list[tuple[str, str, Any, Any]] = [
        ("N", "exact", g["N"], e["N"]),
        ("C_G", "exact", g["C_G"], e["C_G"]),
        ("C", "exact", g["C"], e["C"]),
        ("M", "exact", g["M"], e["M"]),
        ("null_excess_count", "exact", g["null_excess_among_rows_meeting_other_conditions"], e["null_excess_count"]),
        ("sigma", "real", g["sigma"], e["sigma"]),
        ("MSB", "real", g["MSB"], e["MSB"]),
        ("MSW", "real", g["MSW"], e["MSW"]),
        ("n0", "real", g["n0"], e["n0"]),
        ("rho_raw", "real", g["rho_raw"], e["rho_raw"]),
        ("rho", "real", g["rho"], e["rho"]),
        ("k_eff", "real", g["k_eff"], e["k_eff"]),
        ("required", "real", g["Required"], e["required"]),
        ("pass", "exact", g["passes"], e["pass"]),
        ("failing (derived from my three pass conditions)", "exact", own_failing, e["failing"]),
        ("failing_detail (derived: M and Required to 3 decimals)", "exact", own_detail, e["failing_detail"]),
        ("s_star", "exact", s97["S_star"], e["s_star"]),
        ("latest_resolved_session", "exact", s97["latest_resolved_session"], e["latest_resolved_session"]),
        ("earliest_nonstale_pending_session", "exact", s97["earliest_nonstale_pending_session"],
         e["earliest_nonstale_pending_session"]),
        ("stale_pending_count", "exact", s97["stale_pending_rows"], e["stale_pending_count"]),
        ("stale_pending_sessions (derived: empty because my stale count is 0)", "exact",
         [] if s97["stale_pending_rows"] == 0 else ["<not derivable>"], e["stale_pending_sessions"]),
        ("empty_session_pending_count (derived: 0 because my pending judged count is 0)", "exact",
         0 if s97["pending_judged_rows"] == 0 else "<not derivable>", e["empty_session_pending_count"]),
        ("excluded_query_dates (9.1; log is a mapping, its keys compared)", "exact",
         sorted(own["s91_excluded_query_dates"]), sorted(e["excluded_query_dates"])),
        ("inputs_sha256", "exact", sha, e["inputs_sha256"]),
        ("db_path", "exact", own["integrity"]["snapshot_path"], e["db_path"]),
        ("constants.REQUIRED_FACTOR (9.8 text)", "real", vg.FACTOR, e["constants"]["REQUIRED_FACTOR"]),
        ("constants.EFFECT_BP (9.8 text)", "real", vg.DELTA_BP, e["constants"]["EFFECT_BP"]),
        ("constants.FLOOR_ANALYSIS_CLUSTERS (9.8 text)", "exact", vg.MIN_CLUSTERS, e["constants"]["FLOOR_ANALYSIS_CLUSTERS"]),
        ("constants.FLOOR_SCORABLE (9.8 text)", "exact", vg.MIN_M, e["constants"]["FLOOR_SCORABLE"]),
        ("constants.SOURCE_FAILED_DAY_EXCLUDE (9.1 text)", "real", vg.SOURCE_FAILED_LIMIT,
         e["constants"]["SOURCE_FAILED_DAY_EXCLUDE"]),
        ("constants.STALE_PENDING_SESSIONS (9.7 text)", "exact", vg.STALE_SESSIONS, e["constants"]["STALE_PENDING_SESSIONS"]),
    ]
    compared_log_keys = {"N", "C_G", "C", "M", "null_excess_count", "sigma", "MSB", "MSW", "n0", "rho_raw", "rho",
                         "k_eff", "required", "pass", "failing", "failing_detail", "s_star",
                         "latest_resolved_session", "earliest_nonstale_pending_session", "stale_pending_count",
                         "stale_pending_sessions", "empty_session_pending_count", "inputs_sha256", "db_path",
                         "excluded_query_dates",
                         "constants", "manifest_sha256"}

    n_bad = 0
    max_rel = 0.0
    max_rel_label = ""
    lines.append("")
    lines.append(f"{'quantity':<78} | {'own':<24} | {'log':<24} | rel diff | verdict")
    for label, kind, a, b in pairs:
        if kind == "real":
            d = rel(float(a), float(b))
            ok = d <= REL_TOL
            if d > max_rel:
                max_rel, max_rel_label = d, label
            ds = f"{d:.3e}"
        else:
            ok = (a == b) and (type(a) is type(b) or a is None or b is None or
                               {type(a), type(b)} <= {int, float})
            ds = "exact" if ok else "DIFF"
        n_bad += 0 if ok else 1
        lines.append(f"{label:<78} | {a!r:<24} | {b!r:<24} | {ds:<8} | {'ok' if ok else 'MISMATCH'}")

    man = sha256_file(MANIFEST)
    man_ok = man == e["manifest_sha256"]
    n_bad += 0 if man_ok else 1
    lines.append(f"{'manifest_sha256 vs sha256(reports/c3_harness_freeze.json)':<78} | {man[:22]+'..':<24} | "
                 f"{str(e['manifest_sha256'])[:22]+'..':<24} | {'exact' if man_ok else 'DIFF':<8} | "
                 f"{'ok' if man_ok else 'MISMATCH'}")
    n_compared = len(pairs) + 1

    not_recomputed = sorted(k for k in e if k not in compared_log_keys)
    own_only = [
        "the largest source_failed share and its date (both denominators)",
        "pending judged row count (the log carries stale and empty-session pending counts only)",
        "hard-stop session, the bound min(S*, hard stop), rows dropped by the restriction",
        "n_c and m_c per cluster, sum n_c^2, sum m_c^2",
        "the pass conditions C >= 60 and M >= 1000 as separate booleans (the log carries pass and failing)",
    ]
    lines.append("")
    lines.append(f"quantities compared: {n_compared}  mismatches: {n_bad}")
    lines.append(f"largest relative difference among reals: {max_rel:.3e} ({max_rel_label})")
    lines.append("log fields not recomputed: " + ", ".join(f"{k}={e[k]!r}" for k in not_recomputed))
    lines.append("own quantities with no log field: " + "; ".join(own_only))
    lines.append(f"snapshot entries in log: {len(matching)} (must be exactly 1)")
    lines.append("RESULT: " + ("MATCH" if n_bad == 0 else "MISMATCH")
                 + f"  | pass decision own={g['passes']} log={e['pass']}")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines[-6:]))
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
