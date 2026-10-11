"""The 9.8 gate step (STAGE C.1 Task 5; EXPERIMENT.md Amendment 8.4 and 9.8).

    python -m news_eval.gate --db <path> --log <jsonl>
        [--real-db P] [--unlock P] [--manifest P]     (test mode only)

Reads only through the GATE loader phase (news_eval.data.GatePhase), which
never opens the live database, opens a non-live file immutable after refusing
any -wal/-shm/-journal beside it (C.1 ruling B1), and needs a valid
reports/c2_UNLOCK.json for a non-synthetic snapshot (ruling B2).

Manifest (C.1 ruling S2). On a NON_SYNTHETIC database, before any row is
read, news_eval.freeze.verify checks the frozen manifest (default
reports/c1_harness_freeze.json under freeze.REPO_ROOT): every frozen file on
disk, the version and constants pins, and the loaded news_eval modules
(ruling S3). Any difference refuses. The unlock file's manifest_sha256 must
then equal the verified manifest's sha256 (ruling B2). On a SYNTHETIC
database the check runs only when a manifest path is given. Every entry
carries manifest_sha256: the verified manifest's, or null for a synthetic
database checked against no manifest. news_eval.run_c2 accepts only a PASS
whose manifest_sha256 is the manifest it verified itself.

The --real-db, --unlock and --manifest flags are refused (exit 2) outside
test mode, NEWS_EVAL_TEST_MODE=1 (ruling S5). Flow:

1. state_counts_by_query_date -> cutoff.excluded_query_dates (9.1, D18)
2. judged_session_status -> cutoff.compute_s_star (9.7, D16)
3. gate_rows(excluded, S*): y = 10,000 x excess_1session over G, clustered by
   scoring_session (9.8, D1); NULL excess rows are counted, never read as 0
   (D25)
4. directional_counts_by_cluster(excluded, S*): m_c per scoring_session, one
   COUNT ... GROUP BY (9.8 k_eff); the only bridge to the label column, and it
   returns directional counts, never a row
5. stats.gate_quantities: sigma (ddof 1), one-way ANOVA rho floored at 0, n0,
   k_eff, Required = 11.156 x (sigma / 30)^2 x (1 + (k_eff - 1) x rho), and
   the pass: C (C_dir) >= 60, M >= 1,000, M >= Required. C_G (clusters among
   the gate rows, used in n0) is logged apart from C.

A None S* means the analysis set is empty (news_eval.cutoff); the loader is
then not asked for rows and the gate is degenerate.

Each run appends ONE JSON line (sort_keys, one trailing newline, append mode)
to the gate log and never rewrites an earlier line (9.8 "Cadence", 9.15).
Exit 0 on PASS, 1 on FAIL or degenerate, 2 when the run is refused (a loader
refusal, a missing database, a manifest difference, a test-only flag outside
test mode, malformed counts, or a log whose last line is unterminated);
nothing is appended on 2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from news_eval import constants as K
from news_eval import cutoff
from news_eval import data
from news_eval import envcheck
from news_eval import freeze
from news_eval import stats

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2

FAIL_C = "C"
FAIL_M = "M"
FAIL_REQUIRED = "REQUIRED"

STATUS_OK = "ok"
STATUS_DEGENERATE = "degenerate"


class GateRefused(Exception):
    """The gate run refused; nothing was appended to the log."""


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_inputs(phase: data.GatePhase) -> tuple[dict, cutoff.SStar, object,
                                                 dict[str, int]]:
    """Steps 1 to 4 of the module docstring, through the open GATE phase."""
    state_counts = phase.state_counts_by_query_date()
    excluded, shares = cutoff.excluded_query_dates(state_counts)
    cut = cutoff.compute_s_star(phase.judged_session_status())
    if cut.s_star is None:
        rows = data.GateRows(scoring_session=(), excess_1session=(),
                             null_excess_count=0)
        m_c: dict[str, int] = {}
    else:
        rows = phase.gate_rows(excluded, cut.s_star)
        m_c = phase.directional_counts_by_cluster(excluded, cut.s_star)
    excluded_shares = {d: shares[d] for d in excluded}
    return excluded_shares, cut, rows, m_c


def _failing(result: stats.GateResult) -> list[str]:
    """The failed 9.8 conditions among C, M and REQUIRED (REQUIRED only when
    Required is defined)."""
    out = []
    if result.n_clusters_directional < K.FLOOR_ANALYSIS_CLUSTERS:
        out.append(FAIL_C)
    if result.n_directional < K.FLOOR_SCORABLE:
        out.append(FAIL_M)
    if result.required is not None and result.n_directional < result.required:
        out.append(FAIL_REQUIRED)
    return out


def _degenerate_condition(result: stats.GateResult) -> str:
    """The stats module's degenerate condition text, or '' when status is ok."""
    try:
        result.require_ok()
    except stats.DegenerateRefusal as exc:
        return str(exc).partition(": ")[2] or str(exc)
    return ""


def verify_manifest(db_class: data.DbClass,
                    manifest_path: str | os.PathLike | None,
                    unlock_path: str | os.PathLike | None) -> str | None:
    """Rulings S2 and B2: the manifest check of the module docstring.
    Returns the verified manifest's sha256, or None for a synthetic database
    with no manifest path. Raises GateRefused on a manifest difference and
    data.UnlockInvalid when the unlock names another manifest."""
    non_synthetic = db_class is data.DbClass.NON_SYNTHETIC
    if not non_synthetic and manifest_path is None:
        return None
    path = Path(manifest_path) if manifest_path is not None \
        else freeze.REPO_ROOT / freeze.MANIFEST_REL
    diffs, digest = freeze.verify(path, freeze.REPO_ROOT)
    if diffs or digest is None:
        raise GateRefused(f"manifest {path}: {len(diffs)} difference(s): "
                          + "; ".join(diffs[:5]))
    if non_synthetic:
        unlock = os.fspath(unlock_path) if unlock_path is not None \
            else data.UNLOCK_PATH
        body = data.load_unlock(unlock)
        if body.get("manifest_sha256") != digest:
            raise data.UnlockInvalid(
                unlock, "manifest_sha256",
                f"{body.get('manifest_sha256')!r} != the sha256 of the "
                f"verified manifest {path} ({digest})")
    return digest


def evaluate(db_path: str | os.PathLike, *,
             real_db_path: str | os.PathLike | None = None,
             unlock_path: str | os.PathLike | None = None,
             manifest_path: str | os.PathLike | None = None) -> dict:
    """One gate evaluation; returns the log entry (nothing written).

    Raises envcheck.EnvironmentRefused, data.LoaderRefusal, GateRefused,
    FileNotFoundError or ValueError when refused.
    """
    envcheck.assert_numpy_sane()
    db_path = os.fspath(db_path)
    with data.open_phase(data.Phase.GATE, db_path, real_db_path=real_db_path,
                         unlock_path=unlock_path) as phase:
        # Rulings S2, B2: the manifest is verified before any row is read.
        manifest_sha256 = verify_manifest(phase.db_class, manifest_path,
                                          unlock_path)
        # Hashed only after the phase admitted the file: the live database is
        # refused before any byte of it is read.
        inputs_sha256 = sha256_file(db_path)
        db_class = phase.db_class.value
        excluded_shares, cut, rows, m_c = _read_inputs(phase)

    result = stats.gate_quantities(
        rows.excess_1session, rows.scoring_session, m_c,
        power_constant=K.REQUIRED_FACTOR, effect_bp=K.EFFECT_BP,
        min_clusters=K.FLOOR_ANALYSIS_CLUSTERS,
        min_directional=K.FLOOR_SCORABLE)
    status = STATUS_OK if result.ok else STATUS_DEGENERATE
    failing = _failing(result)
    if result.ok and result.passed != (not failing):
        raise ValueError("gate pass disagrees with the failed conditions")
    passed = bool(result.ok and result.passed)

    return {
        "utc_time": _utc_now(),
        "db_path": os.path.abspath(db_path),
        "db_class": db_class,
        "inputs_sha256": inputs_sha256,
        "manifest_sha256": manifest_sha256,
        "s_star": cut.s_star,
        "s_star_case": cut.case,
        "latest_resolved_session": cut.latest_resolved,
        "earliest_nonstale_pending_session": cut.earliest_nonstale_pending,
        "stale_pending_count": cut.stale_pending_rows,
        "stale_pending_sessions": [[s, n] for s, n in cut.stale_pending],
        "empty_session_pending_count": cut.empty_session_pending,
        "excluded_query_dates": excluded_shares,
        "C": result.n_clusters_directional,
        "C_G": result.n_clusters_gate,
        "N": result.n_rows,
        "M": result.n_directional,
        "sigma": result.sigma,
        "MSB": result.msb,
        "MSW": result.msw,
        "n0": result.n0,
        "rho_raw": result.rho_raw,
        "rho": result.rho,
        "k_eff": result.k_eff,
        "required": result.required,
        "pass": passed,
        "failing": failing,
        "failing_detail": list(result.failing),
        "null_excess_count": rows.null_excess_count,
        "test_mode": data.is_test_mode(),
        "status": status,
        "degenerate_condition": _degenerate_condition(result),
        "constants": {
            "FLOOR_ANALYSIS_CLUSTERS": K.FLOOR_ANALYSIS_CLUSTERS,
            "FLOOR_SCORABLE": K.FLOOR_SCORABLE,
            "REQUIRED_FACTOR": K.REQUIRED_FACTOR,
            "EFFECT_BP": K.EFFECT_BP,
            "SOURCE_FAILED_DAY_EXCLUDE": K.SOURCE_FAILED_DAY_EXCLUDE,
            "STALE_PENDING_SESSIONS": K.STALE_PENDING_SESSIONS,
        },
    }


def append_entry(log_path: str | os.PathLike, entry: dict) -> str:
    """Append one JSON line; never rewrites or truncates. Returns the line."""
    line = json.dumps(entry, sort_keys=True, allow_nan=False) + "\n"
    log = Path(log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > 0:
        with open(log, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                raise GateRefused(f"{log} does not end with a newline; "
                                  "refusing to append to it")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return line


def run(db_path: str | os.PathLike, log_path: str | os.PathLike, *,
        real_db_path: str | os.PathLike | None = None,
        unlock_path: str | os.PathLike | None = None,
        manifest_path: str | os.PathLike | None = None) -> int:
    """Evaluate, append, and return the exit code (0 PASS, 1 FAIL or
    degenerate, 2 refused with nothing appended)."""
    try:
        entry = evaluate(db_path, real_db_path=real_db_path,
                         unlock_path=unlock_path,
                         manifest_path=manifest_path)
        append_entry(log_path, entry)
    except (data.LoaderRefusal, FileNotFoundError, ValueError,
            GateRefused, envcheck.EnvironmentRefused) as exc:
        print(f"GATE REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    verdict = "PASS" if entry["pass"] else (
        "DEGENERATE" if entry["status"] == STATUS_DEGENERATE else "FAIL")
    print(f"gate {verdict}: C={entry['C']} C_G={entry['C_G']} "
          f"N={entry['N']} M={entry['M']} required={entry['required']} "
          f"failing={entry['failing']} -> {log_path}")
    return EXIT_PASS if entry["pass"] else EXIT_FAIL


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m news_eval.gate")
    ap.add_argument("--db", required=True, help="snapshot or synthetic db")
    ap.add_argument("--log", required=True, help="append-only JSONL gate log")
    ap.add_argument("--real-db", default=None,
                    help="adds a live database path (test mode only)")
    ap.add_argument("--unlock", default=None,
                    help="override of the unlock file path (test mode only)")
    ap.add_argument("--manifest", default=None,
                    help="override of the manifest path (test mode only)")
    args = ap.parse_args(argv)
    refusal = data.override_refusal({"--real-db": args.real_db,
                                     "--unlock": args.unlock,
                                     "--manifest": args.manifest})
    if refusal:
        print(f"GATE REFUSED: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    return run(args.db, args.log, real_db_path=args.real_db,
               unlock_path=args.unlock, manifest_path=args.manifest)


if __name__ == "__main__":
    sys.exit(_main())
