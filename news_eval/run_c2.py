"""The C.2 runner: snapshot, preconditions, run-once marker, compute, outputs (STAGE C.1 Task 6).

EXPERIMENT.md Amendment 9.7 (snapshot), 9.11 (the compute order lives in
news_eval.family), 9.12 (companion horizons), 9.15 (run once, preconditions,
STOPPED). Two steps, so the 9.8 gate has run on the exact bytes analysed:

    python -m news_eval.run_c2 snapshot --source <db> --out-dir <dir>
    python -m news_eval.gate --db <dir>/news_experiment_snapshot.db --log <jsonl>
    python -m news_eval.run_c2 run --snapshot <dir>/news_experiment_snapshot.db \
        --out-dir <dir2> --gate-log <jsonl> --relevance-summary <json>

Test-only flags (C.1 lead ruling S5): --unlock and --real-db on `snapshot`;
--manifest, --unlock, --marker, --repo-root and --real-db on `run`. Outside
test mode (NEWS_EVAL_TEST_MODE=1, set by the test suite only) each is refused
with exit 2, and RunConfig refuses any value other than the registered
default (data.COMPILED_UNLOCK_PATH, data.COMPILED_RUN_ONCE_PATH,
data.COMPILED_REAL_DB_PATH, freeze.REPO_ROOT and its manifest), so the Python
API follows the same rule.

`snapshot` refuses (exit 2, nothing written) unless the unlock file is a
valid c2_unlock/1 object (data.load_unlock, ruling B2) and neither
<dir>/news_experiment_snapshot.db, its sidecars, nor <dir>/snapshot.json
exists. In test mode it also refuses the repository's live database as the
source. It records the source's st_size and st_mtime (ruling S1), copies the
source (opened read-only by URI) with sqlite3.Connection.backup, sets the copy
to rollback-journal (DELETE) mode, sets mode 0444, checks that no -wal, -shm
or -journal is left beside it (ruling B1), hashes it, and writes
snapshot.json with the method, the source realpath and stat, sha256, bytes,
UTC time, sidecars_absent, and collection row counts by (query_date, state)
read through the GATE loader phase. It reads no other column. The header
bytes do not keep SQLite from applying a planted -wal (the C.1 leakage
audit, B1); what does is that every later open of the snapshot is immutable
and refused outright when a sidecar sits beside it.

`run` checks PRECONDITIONS in their fixed order; each refuses with exit 2 and
nothing written:
  0 numpy_sane        envcheck.assert_numpy_sane: the temporary-elision
                      canaries pass (the harness runs only in .venv-eval)
  1 manifest          freeze.verify finds no difference: every frozen hash,
                      the Python, numpy and SQLite pins, the constants, and
                      the loaded news_eval modules (ruling S3)
  2 unlock            the unlock file is a valid c2_unlock/1 object
                      (data.load_unlock) whose manifest_sha256 is 1's sha256
                      (ruling B2)
  3 marker_absent     the run-once marker does not exist. A marker with
                      neither results.json nor results_STOPPED.json means
                      the registered run was killed: its verdict is STOPPED
                      (9.15, ruling S7), never a rerun
  4 snapshot          not the live database (stat), no -wal/-shm/-journal
                      beside it (ruling B1), a regular file with no write
                      bit, snapshot.json beside it names the backup API, its
                      source_realpath is the realpath of the configured live
                      database (ruling S1; in test mode never the
                      repository's own, ruling S5), its sha256 equals the
                      file's, data.classify agrees it is not the live
                      database, and outside test mode it is NON_SYNTHETIC.
                      (st_dev, st_ino, st_size, st_mtime_ns) and the sha256
                      are recorded for the re-checks (ruling S4)
  5 s_star            S* from the GATE phase's counts of the snapshot is not
                      None (news_eval.cutoff)
  6 gate_pass         the gate log has at least one entry for this snapshot's
                      sha256 with pass true and status ok, whose S* equals 5's
                      and whose manifest_sha256 equals 1's (ruling S2), and
                      no FAIL or degenerate entry for that sha256
  7 relevance_summary the relevance.summarize JSON exists and parses; its
                      sha256 is recorded (8.3: the rates go with the verdict)
  8 outputs_absent    none of the output files exists in --out-dir
  9 memory            /proc/meminfo MemAvailable is at least
                      constants.MIN_MEM_AVAILABLE_MB (ruling S7)
Then the marker (schema constants.RUN_ONCE_SCHEMA, bound to the snapshot's
sha256) is written with O_CREAT|O_EXCL (two concurrent runs cannot both
proceed), BEFORE any outcome column is read. After it, any exception or stop
writes <out-dir>/results_STOPPED.json (status "STOPPED", the reason) and
exits 3. Nothing is retried, resumed or recomputed with changed settings
(9.15). The snapshot's identity and sha256 are re-checked immediately before
compute and again after compute, before any output is written (ruling S4); a
mismatch is STOPPED with its reason and results.json is never written.

Compute: family.compute on the snapshot; verdict.decide; the 9.12 condition
(docs/SUCCESSOR_PREREG_DRAFT.md is tracked and its last commit's author date
AND committer date both precede snapshot.json's time; ruling N6);
family.companion_horizons only when it holds; report.write. Outputs:
results.json (numbers and decisions only, sort_keys, no time, path or
hostname), run_meta.json (times, paths, every input hash, the snapshot's
source stat and sidecar record, the Python, numpy, SQLite and BLAS versions,
the thread environment variables, the 9.12 evidence) and verdict.md. Exit 0.

Every path is a parameter. Defaults resolve at call time from news_eval.data
(UNLOCK_PATH, RUN_ONCE_PATH, REAL_DB_PATH) and news_eval.freeze (the
manifest), so tests run in temporary directories and never touch reports/c2*.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from news_eval import constants as K
from news_eval import cutoff
from news_eval import data
from news_eval import envcheck
from news_eval import family
from news_eval import freeze
from news_eval import report
from news_eval import verdict

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_STOPPED = 3

SNAPSHOT_NAME = "news_experiment_snapshot.db"
SNAPSHOT_META_NAME = "snapshot.json"
SNAPSHOT_METHOD = "sqlite3.Connection.backup"
SNAPSHOT_MODE = 0o444
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH

RESULTS_NAME = "results.json"
RUN_META_NAME = "run_meta.json"
VERDICT_NAME = "verdict.md"
STOPPED_NAME = "results_STOPPED.json"
OUTPUT_NAMES = (RESULTS_NAME, RUN_META_NAME, VERDICT_NAME, STOPPED_NAME)

SUCCESSOR_DRAFT_REL = "docs/SUCCESSOR_PREREG_DRAFT.md"
RELEVANCE_SCHEMA = "c1_relevance_summary/1"
GATE_STATUS_OK = "ok"
# Ruling S7: the thread settings run_meta records (value, or null if unset).
THREAD_ENV_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                   "MKL_NUM_THREADS")
MEMINFO_PATH = "/proc/meminfo"


class Refused(Exception):
    """A precondition refused; nothing was written. Carries the check name."""

    def __init__(self, check: str, reason: str) -> None:
        self.check = check
        self.reason = reason
        super().__init__(f"{check}: {reason}")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _default(value: str | os.PathLike | None, name: str) -> str:
    """An explicit path wins; else news_eval.data's setting at call time."""
    return os.fspath(value) if value is not None else getattr(data, name)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(stamp: str) -> datetime:
    """An ISO time with an offset or a trailing Z; naive times are refused."""
    if not isinstance(stamp, str):
        raise TypeError(f"time must be a string: {stamp!r}")
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{stamp!r} carries no offset")
    return parsed


def _write_exclusive(path: Path, text: str, mode: int = 0o644) -> None:
    """Create `path` with O_EXCL (never overwrite) and fsync it."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def _json_text(obj: object, *, indent: int | None = 2) -> str:
    return json.dumps(obj, sort_keys=True, indent=indent) + "\n"


# ----------------------------------------------------------------- snapshot

def take_snapshot(source: str | os.PathLike, out_dir: str | os.PathLike, *,
                  unlock_path: str | os.PathLike | None = None,
                  real_db_path: str | os.PathLike | None = None) -> dict:
    """The 9.7 snapshot. Raises Refused (nothing written) before any write.
    A failure after the copy started removes what this call created."""
    unlock = _default(unlock_path, "UNLOCK_PATH")
    out = Path(out_dir)
    dest, meta_path = out / SNAPSHOT_NAME, out / SNAPSHOT_META_NAME
    partial = dest.with_name(dest.name + ".partial")
    try:
        data.load_unlock(unlock)  # ruling B2: content, not existence
    except data.LoaderRefusal as exc:
        raise Refused("unlock", str(exc)) from None
    for p in (dest, meta_path, partial,
              *(Path(str(x) + sfx) for x in (dest, partial)
                for sfx in data.SIDECAR_SUFFIXES)):
        if os.path.lexists(p):
            raise Refused("snapshot_absent", f"{p} already exists")
    if not os.path.isfile(source):
        raise Refused("source", f"source database {source} does not exist")
    if data.is_test_mode() and data.is_compiled_real(source):
        raise Refused("source", "test mode never snapshots the repository's "
                      "live database (C.1 ruling S5)")
    source_st = os.stat(source)  # ruling S1: the source's size and mtime

    out.mkdir(parents=True, exist_ok=True)
    linked = False
    try:
        _backup(Path(source), partial)
        os.link(partial, dest)  # fails if dest appeared meanwhile
        linked = True
        partial.unlink()
        os.chmod(dest, SNAPSHOT_MODE)
        _no_sidecars_left(dest)
        digest = sha256_file(dest)
        counts = _snapshot_counts(dest, unlock, real_db_path)
        if sha256_file(dest) != digest:
            raise RuntimeError(f"{dest} changed while its counts were read")
        _no_sidecars_left(dest)
        meta = {
            "schema": "c2_snapshot/1",
            "method": SNAPSHOT_METHOD,
            "journal_mode_after_copy": "delete",
            "source_realpath": os.path.realpath(source),
            "source_st_size": source_st.st_size,
            "source_st_mtime": source_st.st_mtime,
            "snapshot_path": os.path.abspath(dest),
            "sha256": digest,
            "bytes": dest.stat().st_size,
            "file_mode": oct(stat.S_IMODE(dest.stat().st_mode)),
            "sidecars_absent": True,
            "utc_time": utc_now(),
            **counts,
        }
        _write_exclusive(meta_path, _json_text(meta))
    except BaseException:
        if partial.exists():
            partial.unlink()
        if linked and dest.exists():
            dest.unlink()
        raise
    return meta


def _no_sidecars_left(dest: Path) -> None:
    """Ruling B1: the DELETE-mode copy leaves no -wal, -shm or -journal."""
    left = data.sidecars(dest)
    if left:
        raise RuntimeError(f"sidecar(s) beside the snapshot: {left}")


def _backup(source: Path, dest: Path) -> None:
    """sqlite3 backup API from a read-only URI connection, then DELETE mode."""
    src = sqlite3.connect(Path(os.path.abspath(source)).as_uri() + "?mode=ro",
                          uri=True)
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            mode = dst.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(mode).lower() != "delete":
                raise RuntimeError(f"snapshot journal_mode is {mode}")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def _snapshot_counts(snapshot: Path, unlock: str,
                     real_db_path: str | os.PathLike | None) -> dict:
    """Collection rows by (query_date, state), GATE phase only (9.7)."""
    with data.open_phase(data.Phase.GATE, snapshot, real_db_path=real_db_path,
                         unlock_path=unlock) as phase:
        by_day = phase.state_counts_by_query_date()
        db_class = phase.db_class.value
    by_day = {qd: dict(sorted(states.items()))
              for qd, states in sorted(by_day.items())}
    by_state: dict[str, int] = {}
    for states in by_day.values():
        for st, n in states.items():
            by_state[st] = by_state.get(st, 0) + n
    return {
        "db_class": db_class,
        "collection_rows_total": sum(by_state.values()),
        "collection_rows_by_state": dict(sorted(by_state.items())),
        "collection_query_dates": len(by_day),
        "collection_rows_by_query_date_state": by_day,
    }


# ------------------------------------------------------------ preconditions

@dataclass(frozen=True)
class RunConfig:
    snapshot: Path
    out_dir: Path
    manifest: Path
    unlock: Path
    marker: Path
    gate_log: Path
    relevance_summary: Path
    repo_root: Path
    real_db: str
    argv: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Ruling S5 (and S3 for repo_root): outside test mode every path a
        test may override must be the registered default. Raises Refused
        (check "config")."""
        if data.is_test_mode():
            return
        registered = {
            "manifest": freeze.REPO_ROOT / freeze.MANIFEST_REL,
            "unlock": data.COMPILED_UNLOCK_PATH,
            "marker": data.COMPILED_RUN_ONCE_PATH,
            "repo_root": freeze.REPO_ROOT,
            "real_db": data.COMPILED_REAL_DB_PATH,
        }
        bad = [f"{name}={os.fspath(getattr(self, name))!r}"
               for name, want in registered.items()
               if os.path.realpath(getattr(self, name))
               != os.path.realpath(want)]
        if bad:
            raise Refused("config", f"{', '.join(bad)} differ(s) from the "
                          "registered default; path overrides are test-only "
                          f"({data.TEST_MODE_ENV}=1 is set by the test suite "
                          "only; C.1 ruling S5)")


def _check_numpy(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    try:
        envcheck.assert_numpy_sane()
    except envcheck.EnvironmentRefused as exc:
        raise Refused("numpy_sane", str(exc)) from None
    return {}


def _check_manifest(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    """The frozen manifest on disk under cfg.repo_root, and the news_eval
    modules this process imported (ruling S3)."""
    diffs, digest = freeze.verify(cfg.manifest, cfg.repo_root)
    if diffs or digest is None:
        shown = "; ".join(diffs[:5])
        raise Refused("manifest", f"{len(diffs)} difference(s): {shown}")
    return {"manifest_sha256": digest}


def _check_unlock(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    """Ruling B2: a valid c2_unlock/1 object naming the verified manifest."""
    try:
        body = data.load_unlock(cfg.unlock)
    except data.LoaderRefusal as exc:
        raise Refused("unlock", str(exc)) from None
    if body.get("manifest_sha256") != facts["manifest_sha256"]:
        raise Refused("unlock", f"unlock file {cfg.unlock}: field "
                      f"'manifest_sha256' {body.get('manifest_sha256')!r} != "
                      f"the verified manifest {facts['manifest_sha256']}")
    return {"unlock_sha256": sha256_file(cfg.unlock),
            "unlock": {k: body.get(k) for k in K.UNLOCK_FIELDS}}


def _check_marker_absent(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    if os.path.lexists(cfg.marker):
        raise Refused(
            "marker_absent",
            f"run-once marker {cfg.marker} exists: C.2 has run. If the run's "
            f"out-dir holds neither {RESULTS_NAME} nor {STOPPED_NAME}, the "
            "registered run was killed after the marker; its verdict is "
            "STOPPED with reason \"process killed\" (EXPERIMENT.md 9.15, C.1 "
            "ruling S7). It is never rerun or resumed.")
    return {}


def snapshot_identity(path: Path) -> list[int]:
    """(st_dev, st_ino, st_size, st_mtime_ns) by os.stat (ruling S4)."""
    st = os.stat(path)
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def _check_snapshot(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    snap = cfg.snapshot
    if data.is_live_real(snap, cfg.real_db):
        raise Refused("snapshot", f"{snap} is the live database")
    if not snap.is_file() or snap.is_symlink():
        raise Refused("snapshot", f"{snap} is not a regular file")
    try:
        data.refuse_sidecars(snap)  # ruling B1, before any open
    except data.SidecarPresent as exc:
        raise Refused("snapshot", str(exc)) from None
    mode = stat.S_IMODE(snap.stat().st_mode)
    if mode & WRITE_BITS:
        raise Refused("snapshot", f"{snap} is writable (mode {oct(mode)})")
    meta_path = snap.with_name(SNAPSHOT_META_NAME)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("snapshot", f"{meta_path} unreadable: {exc}") from None
    if not isinstance(meta, dict) or meta.get("method") != SNAPSHOT_METHOD:
        raise Refused("snapshot", f"{meta_path} method is not "
                      f"{SNAPSHOT_METHOD!r}")
    try:
        _parse_utc(meta.get("utc_time"))
    except (TypeError, ValueError):
        raise Refused("snapshot", f"{meta_path} utc_time "
                      f"{meta.get('utc_time')!r} is not an ISO time") from None
    source = meta.get("source_realpath")
    if not isinstance(source, str) \
            or source != os.path.realpath(cfg.real_db):  # ruling S1
        raise Refused("snapshot", f"{meta_path} source_realpath {source!r} "
                      f"is not the configured live database "
                      f"{os.path.realpath(cfg.real_db)}")
    if data.is_test_mode() and data.is_compiled_real(source):  # ruling S5
        raise Refused("snapshot", "test mode refuses a snapshot of the "
                      "repository's live database (C.1 ruling S5)")
    identity = snapshot_identity(snap)  # ruling S4
    digest = sha256_file(snap)
    if digest != meta.get("sha256"):
        raise Refused("snapshot", f"sha256 {digest} != snapshot.json "
                      f"{meta.get('sha256')}")
    try:
        cls = data.classify(snap, cfg.real_db)
    except (data.LoaderRefusal, OSError, sqlite3.Error) as exc:
        raise Refused("snapshot", f"classify failed: {exc}") from None
    if cls is data.DbClass.LIVE_REAL:
        raise Refused("snapshot", f"{snap} classifies as the live database")
    if cls is not data.DbClass.NON_SYNTHETIC and not data.is_test_mode():
        raise Refused("snapshot", f"{snap} classifies {cls.value}; the "
                      "registered run reads a NON_SYNTHETIC snapshot of the "
                      "live database (C.1 ruling S1)")
    if snapshot_identity(snap) != identity:
        raise Refused("snapshot", f"{snap} changed while it was checked")
    return {"snapshot_sha256": digest, "snapshot_meta": meta,
            "snapshot_meta_sha256": sha256_file(meta_path),
            "snapshot_db_class": cls.value,
            "snapshot_identity": identity, "sidecars_absent": True}


def _check_s_star(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    try:
        with data.open_phase(data.Phase.GATE, cfg.snapshot,
                             real_db_path=cfg.real_db,
                             unlock_path=cfg.unlock) as phase:
            state_counts = phase.state_counts_by_query_date()
            session_status = phase.judged_session_status()
        excluded, _ = cutoff.excluded_query_dates(state_counts)
        cut = cutoff.compute_s_star(session_status)
    except (data.LoaderRefusal, OSError, ValueError, sqlite3.Error) as exc:
        raise Refused("s_star", f"{type(exc).__name__}: {exc}") from None
    if cut.s_star is None:
        raise Refused("s_star", f"S* is None ({cut.case}): the analysis set "
                      "is empty")
    return {"s_star": cut.s_star, "s_star_case": cut.case,
            "excluded_query_dates": sorted(excluded)}


def _check_gate_pass(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    digest = facts["snapshot_sha256"]
    try:
        lines = cfg.gate_log.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Refused("gate_pass", f"gate log unreadable: {exc}") from None
    mine = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            raise Refused("gate_pass", f"gate log line {i} is not JSON") \
                from None
        if isinstance(entry, dict) and entry.get("inputs_sha256") == digest:
            mine.append((i, entry))
    bad = [i for i, e in mine
           if e.get("pass") is not True or e.get("status") != GATE_STATUS_OK]
    if bad:
        raise Refused("gate_pass", f"gate log has a FAIL or degenerate entry "
                      f"for {digest} (lines {bad})")
    # Ruling S2: only a PASS produced under the manifest this run verified;
    # an entry without manifest_sha256 never counts.
    passes = [(i, e) for i, e in mine if e.get("s_star") == facts["s_star"]
              and e.get("manifest_sha256") == facts["manifest_sha256"]]
    if not passes:
        raise Refused("gate_pass", f"no PASS entry for sha256 {digest} with "
                      f"S* {facts['s_star']} and manifest_sha256 "
                      f"{facts['manifest_sha256']}")
    line_no, entry = passes[-1]
    return {"gate_log_sha256": sha256_file(cfg.gate_log),
            "gate_entry_line": line_no, "gate_entry": entry}


def _check_relevance(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    try:
        summary = json.loads(cfg.relevance_summary.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused("relevance_summary",
                      f"{cfg.relevance_summary} unreadable: {exc}") from None
    if not isinstance(summary, dict) or summary.get("schema") \
            != RELEVANCE_SCHEMA:
        raise Refused("relevance_summary",
                      f"{cfg.relevance_summary} schema is not "
                      f"{RELEVANCE_SCHEMA!r}")
    return {"relevance_summary": summary,
            "relevance_summary_sha256": sha256_file(cfg.relevance_summary)}


def _check_outputs_absent(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    present = [n for n in OUTPUT_NAMES
               if os.path.lexists(cfg.out_dir / n)]
    if present:
        raise Refused("outputs_absent",
                      f"{cfg.out_dir} already holds {present}")
    return {}


def _mem_available_mb() -> float | None:
    """MemAvailable from /proc/meminfo in MB, or None when unreadable
    (ruling S7). Tests replace this function."""
    try:
        with open(MEMINFO_PATH, encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def _check_memory(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    """Ruling S7: enough free memory that the compute is not OOM-killed
    after the marker (the host has a recorded OOM incident)."""
    mb = _mem_available_mb()
    if mb is None:
        raise Refused("memory", f"MemAvailable unreadable from {MEMINFO_PATH}")
    if mb < K.MIN_MEM_AVAILABLE_MB:
        raise Refused("memory", f"MemAvailable {mb:.0f} MB < "
                      f"{K.MIN_MEM_AVAILABLE_MB} MB; free memory first "
                      "(nothing was written)")
    return {"mem_available_mb": round(mb, 1)}


PRECONDITIONS: tuple[tuple[str, Callable[[RunConfig, Mapping], dict]], ...] = (
    ("numpy_sane", _check_numpy),
    ("manifest", _check_manifest),
    ("unlock", _check_unlock),
    ("marker_absent", _check_marker_absent),
    ("snapshot", _check_snapshot),
    ("s_star", _check_s_star),
    ("gate_pass", _check_gate_pass),
    ("relevance_summary", _check_relevance),
    ("outputs_absent", _check_outputs_absent),
    ("memory", _check_memory),
)


def check_preconditions(cfg: RunConfig) -> dict:
    """Run PRECONDITIONS in order; the first failure raises Refused. Writes
    nothing. Returns the facts every check recorded."""
    facts: dict[str, Any] = {}
    for _name, check in PRECONDITIONS:
        facts = {**facts, **check(cfg, facts)}
    return facts


# ------------------------------------------------------------------- marker

def write_marker(cfg: RunConfig, facts: Mapping[str, Any]) -> dict:
    """The run-once marker, exclusive create (9.15). Raises Refused if it
    appeared after precondition 3 (a concurrent run)."""
    body = {
        "schema": K.RUN_ONCE_SCHEMA,
        "manifest_sha256": facts["manifest_sha256"],
        "snapshot_sha256": facts["snapshot_sha256"],
        "s_star": facts["s_star"],
        "relevance_summary_sha256": facts["relevance_summary_sha256"],
        "gate_log_sha256": facts["gate_log_sha256"],
        "utc_time": utc_now(),
        "argv": list(cfg.argv),
    }
    try:
        _write_exclusive(cfg.marker, _json_text(body), 0o444)
    except FileExistsError:
        raise Refused("marker_absent", f"run-once marker {cfg.marker} "
                      "appeared: another run holds it") from None
    return body


# -------------------------------------------------------------- 9.12 check

def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_root), *args],
                          capture_output=True, text=True, timeout=60)


def successor_condition(repo_root: Path, snapshot_utc: str) -> dict:
    """9.12: the draft is tracked and its last commit precedes the snapshot.
    Records the commit sha, author date and committer date; holds only when
    BOTH dates precede the snapshot time (ruling N6: a backdated committer
    date alone cannot make it hold). last_commit_time is the committer date.
    Any git failure leaves the condition false (C.2 then computes nothing)."""
    out: dict[str, Any] = {"path": SUCCESSOR_DRAFT_REL,
                           "snapshot_utc": snapshot_utc, "tracked": False,
                           "commit_sha": None, "author_time": None,
                           "committer_time": None, "last_commit_time": None,
                           "holds": False, "error": None}
    try:
        tracked = _git(repo_root, "ls-files", "--error-unmatch", "--",
                       SUCCESSOR_DRAFT_REL)
        out["tracked"] = tracked.returncode == 0
        if not out["tracked"]:
            return out
        log = _git(repo_root, "log", "-1", "--format=%H%n%aI%n%cI", "--",
                   SUCCESSOR_DRAFT_REL)
        fields = log.stdout.split()
        if log.returncode != 0 or len(fields) != 3:
            out["error"] = (f"git log rc {log.returncode}: "
                            f"{log.stderr.strip() or log.stdout.strip()!r}")
            return out
        sha, author, committer = fields
        out.update(commit_sha=sha, author_time=author,
                   committer_time=committer, last_commit_time=committer)
        snap = _parse_utc(snapshot_utc)
        out["holds"] = _parse_utc(author) < snap \
            and _parse_utc(committer) < snap
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["holds"] = False
    return out


# ------------------------------------------------------------------ compute

def _compute(cfg: RunConfig, facts: Mapping[str, Any],
             progress: dict) -> dict:
    """Everything after the marker, in memory; outputs written last."""
    kw = dict(real_db_path=cfg.real_db, unlock_path=cfg.unlock,
              marker_path=cfg.marker)
    progress["step"] = "family.compute"
    results = family.compute(cfg.snapshot, **kw)
    progress["step"] = "verdict.decide"
    decision = verdict.decide(results)
    progress["step"] = "successor_condition (9.12)"
    succ = successor_condition(cfg.repo_root,
                               facts["snapshot_meta"]["utc_time"])
    companion = None
    if succ["holds"]:
        progress["step"] = "family.companion_horizons (9.12)"
        companion = family.companion_horizons(cfg.snapshot, **kw)
    results_doc = {"schema": "c2_results/1", "results": results,
                   "decision": decision, "companion_horizons": companion,
                   "companion_computed": companion is not None}
    progress["step"] = "results.json serialisation"
    results_text = _json_text(results_doc)
    meta = _run_meta(cfg, facts, succ)
    progress["step"] = "report.write"
    verdict_text = report.write(results, decision,
                                relevance_summary=facts["relevance_summary"],
                                companion=companion, run_meta=meta)
    return {"results_text": results_text, "verdict_text": verdict_text,
            "meta": meta}


def environment_record() -> dict:
    """Ruling N3 / S7: the versions and thread settings run_meta records."""
    return {"versions": {"python": platform.python_version(),
                         "numpy": np.__version__,
                         "sqlite": sqlite3.sqlite_version,
                         "numpy_blas": freeze.blas_info()},
            "thread_env": {v: os.environ.get(v) for v in THREAD_ENV_VARS}}


def _run_meta(cfg: RunConfig, facts: Mapping[str, Any], succ: dict) -> dict:
    return {
        "schema": "c2_run_meta/1",
        "argv": list(cfg.argv),
        "utc_start": facts["utc_start"],
        "utc_marker": facts["marker"]["utc_time"],
        "paths": {k: str(getattr(cfg, k)) for k in (
            "snapshot", "out_dir", "manifest", "unlock", "marker", "gate_log",
            "relevance_summary", "repo_root", "real_db")},
        "hashes": {k: facts[k] for k in (
            "manifest_sha256", "unlock_sha256", "snapshot_sha256",
            "snapshot_meta_sha256", "gate_log_sha256",
            "relevance_summary_sha256")},
        "snapshot": {k: facts["snapshot_meta"].get(k) for k in (
            "method", "source_realpath", "source_st_size", "source_st_mtime",
            "sha256", "bytes", "utc_time", "sidecars_absent", "db_class",
            "collection_rows_total")},
        "snapshot_db_class": facts["snapshot_db_class"],
        "snapshot_identity": facts["snapshot_identity"],
        "sidecars_absent": facts["sidecars_absent"],
        "unlock": facts["unlock"],
        "test_mode": data.is_test_mode(),
        "mem_available_mb": facts["mem_available_mb"],
        "s_star": facts["s_star"],
        "s_star_case": facts["s_star_case"],
        "excluded_query_dates": facts["excluded_query_dates"],
        "gate_entry_line": facts["gate_entry_line"],
        "gate_entry": facts["gate_entry"],
        "successor_condition_9_12": succ,
        **environment_record(),
    }


def _write_outputs(cfg: RunConfig, computed: dict, progress: dict) -> dict:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    progress["step"] = "write results.json"
    _write_exclusive(cfg.out_dir / RESULTS_NAME, computed["results_text"])
    progress["written"].append(RESULTS_NAME)
    progress["step"] = "write verdict.md"
    _write_exclusive(cfg.out_dir / VERDICT_NAME, computed["verdict_text"])
    progress["written"].append(VERDICT_NAME)
    meta = {**computed["meta"], "utc_end": utc_now(), "outputs": {
        RESULTS_NAME: hashlib.sha256(
            computed["results_text"].encode()).hexdigest(),
        VERDICT_NAME: hashlib.sha256(
            computed["verdict_text"].encode()).hexdigest()}}
    progress["step"] = "write run_meta.json"
    _write_exclusive(cfg.out_dir / RUN_META_NAME, _json_text(meta))
    progress["written"].append(RUN_META_NAME)
    return meta


def _write_stopped(cfg: RunConfig, facts: Mapping[str, Any], progress: dict,
                   exc: BaseException) -> None:
    body = {
        "status": "STOPPED",
        "reason": f"{type(exc).__name__}: {exc}",
        "step": progress.get("step"),
        "files_written_before_stop": list(progress.get("written", [])),
        "utc_time": utc_now(),
        "marker": str(cfg.marker),
        "snapshot_sha256": facts.get("snapshot_sha256"),
        "manifest_sha256": facts.get("manifest_sha256"),
        "note": "A stop closes the registered attempt; it is never rerun "
                "with changed settings (EXPERIMENT.md 9.15).",
    }
    try:
        cfg.out_dir.mkdir(parents=True, exist_ok=True)
        _write_exclusive(cfg.out_dir / STOPPED_NAME, _json_text(body))
    except OSError as werr:
        print(f"STOPPED, and results_STOPPED.json could not be written "
              f"({werr}): {body['reason']}", file=sys.stderr)


class SnapshotChanged(RuntimeError):
    """The snapshot is not the file the preconditions checked (ruling S4)."""


def recheck_snapshot(cfg: RunConfig, facts: Mapping[str, Any],
                     when: str) -> None:
    """Ruling S4: the snapshot's identity, sidecars and sha256 against what
    precondition 4 recorded. Raises SnapshotChanged with the reason."""
    try:
        identity = snapshot_identity(cfg.snapshot)
    except OSError as exc:
        raise SnapshotChanged(f"snapshot {when}: {exc}") from None
    if identity != facts["snapshot_identity"]:
        raise SnapshotChanged(
            f"snapshot {when}: (st_dev, st_ino, st_size, st_mtime_ns) "
            f"{identity} != {facts['snapshot_identity']} recorded at the "
            "precondition")
    left = data.sidecars(cfg.snapshot)
    if left:
        raise SnapshotChanged(f"snapshot {when}: sidecar(s) {left}")
    digest = sha256_file(cfg.snapshot)
    if digest != facts["snapshot_sha256"]:
        raise SnapshotChanged(f"snapshot {when}: sha256 {digest} != "
                              f"{facts['snapshot_sha256']}")


def run(cfg: RunConfig) -> int:
    """Preconditions, marker, compute, outputs. Returns the exit code."""
    utc_start = utc_now()
    try:
        facts = check_preconditions(cfg)
        facts = {**facts, "utc_start": utc_start}
        facts = {**facts, "marker": write_marker(cfg, facts)}
    except Refused as exc:
        print(f"C.2 REFUSED at precondition {exc.check}: {exc.reason}",
              file=sys.stderr)
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - before the marker nothing is written
        print(f"C.2 REFUSED: unexpected {type(exc).__name__} before the "
              f"marker: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    progress: dict[str, Any] = {"step": "start", "written": []}
    try:
        progress["step"] = "snapshot re-check before compute"
        recheck_snapshot(cfg, facts, "before compute")
        computed = _compute(cfg, facts, progress)
        progress["step"] = "snapshot re-check after compute"
        recheck_snapshot(cfg, facts, "after compute")
        _write_outputs(cfg, computed, progress)
    except BaseException as exc:  # noqa: BLE001 - every stop is a STOPPED
        _write_stopped(cfg, facts, progress, exc)
        print(f"C.2 STOPPED at {progress.get('step')}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_STOPPED
    print(f"C.2 done -> {cfg.out_dir}")
    return EXIT_OK


# ---------------------------------------------------------------------- CLI

def _config(args: argparse.Namespace, argv: list[str]) -> RunConfig:
    """The run config from parsed arguments. RunConfig refuses non-default
    paths outside test mode (ruling S5)."""
    repo_root = Path(args.repo_root) if args.repo_root else freeze.REPO_ROOT
    manifest = Path(args.manifest) if args.manifest \
        else freeze.REPO_ROOT / freeze.MANIFEST_REL
    return RunConfig(
        snapshot=Path(args.snapshot), out_dir=Path(args.out_dir),
        manifest=manifest,
        unlock=Path(_default(args.unlock, "UNLOCK_PATH")),
        marker=Path(_default(args.marker, "RUN_ONCE_PATH")),
        gate_log=Path(args.gate_log),
        relevance_summary=Path(args.relevance_summary),
        repo_root=repo_root,
        real_db=_default(args.real_db, "REAL_DB_PATH"),
        argv=tuple(argv))


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m news_eval.run_c2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="9.7 snapshot with the backup API")
    s.add_argument("--source", required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("--unlock", default=None,
                   help="test mode only; default news_eval.data.UNLOCK_PATH")
    s.add_argument("--real-db", default=None,
                   help="test mode only; adds a live database path")
    r = sub.add_parser("run", help="the single C.2 verdict run")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--gate-log", required=True)
    r.add_argument("--relevance-summary", required=True)
    r.add_argument("--manifest", default=None,
                   help=f"test mode only; default {freeze.MANIFEST_REL}")
    r.add_argument("--unlock", default=None,
                   help="test mode only; default news_eval.data.UNLOCK_PATH")
    r.add_argument("--marker", default=None,
                   help="test mode only; default "
                   "news_eval.data.RUN_ONCE_PATH")
    r.add_argument("--repo-root", default=None,
                   help="test mode only; default the repository root")
    r.add_argument("--real-db", default=None,
                   help="test mode only; adds a live database path")
    return ap


TEST_ONLY_FLAGS = {"snapshot": ("unlock", "real_db"),
                   "run": ("manifest", "unlock", "marker", "repo_root",
                           "real_db")}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(argv)
    refusal = data.override_refusal(
        {"--" + name.replace("_", "-"): getattr(args, name)
         for name in TEST_ONLY_FLAGS[args.cmd]})
    if refusal:
        print(f"{args.cmd.upper()} REFUSED: {refusal}", file=sys.stderr)
        return EXIT_REFUSED
    if args.cmd == "snapshot":
        try:
            meta = take_snapshot(args.source, args.out_dir,
                                 unlock_path=args.unlock,
                                 real_db_path=args.real_db)
        except Refused as exc:
            print(f"SNAPSHOT REFUSED at {exc.check}: {exc.reason}",
                  file=sys.stderr)
            return EXIT_REFUSED
        except (OSError, sqlite3.Error, data.LoaderRefusal,
                RuntimeError) as exc:
            print(f"SNAPSHOT FAILED: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return EXIT_FAILED
        print(f"snapshot {meta['sha256']} {meta['bytes']} bytes -> "
              f"{meta['snapshot_path']}")
        return EXIT_OK
    try:
        cfg = _config(args, argv)
    except Refused as exc:
        print(f"C.2 REFUSED at precondition {exc.check}: {exc.reason}",
              file=sys.stderr)
        return EXIT_REFUSED
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
