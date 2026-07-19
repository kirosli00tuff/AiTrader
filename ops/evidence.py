"""Automatic evidence capture for the unexplained failure conditions.

Two conditions are unexplained and not reproduced (PROGRESS.md Open Flags): a
layer toggle whose on-disk value changed with no audit row (the layer.whale
True to False events of 2026-07-17), and the engine-reads-ON funnel-reads-OFF
discovery flag mismatch. Fixing either without a reproduction would be a
guess. This module makes the next occurrence self-documenting: at the moment
of detection the raw facts are written to a JSON record under diagnostics/.

What a record holds, and why each field settles a hypothesis:
  * the control file bytes exactly as read, with size, mtime, mode, and a
    sha256, so a torn or unexpected on-disk state is preserved, not described
  * the reading process pid, START TIME, and argv. Start time is the fact
    that settles the stale-process hypothesis: a reader started before a fix
    landed runs pre-fix code no matter what the file on disk says
  * the open fd count of the capturing process, because fd-class exhaustion
    is the leading hypothesis for the funnel case

Rules:
  * capture() NEVER raises and never blocks its caller. Evidence is worthless
    if collecting it takes down the process under diagnosis.
  * Every field is gathered independently. One unreadable source (fd
    exhaustion breaks open(), which is exactly the suspected state) records
    its error string instead of voiding the record.
  * Captures are rate limited per condition per process. The first record is
    the valuable one, and a 19-hour outage must not write thousands of files.
  * If the record file cannot be written, the record is logged as one line so
    the facts still land somewhere.

This module diagnoses. It never fixes, never writes a control file, never
touches an operational table, and never carries a credential.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

log = logging.getLogger("ops.evidence")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One capture per condition per process inside this window. Long enough that a
# stuck loop cannot flood the disk, short enough that a recurrence hours later
# is captured again.
_MIN_INTERVAL_SECONDS = 900

# Control files are a few KB. Anything larger than this is itself anomalous
# and the head of it is what matters.
_MAX_CONTROL_BYTES = 65536

_last_capture: dict[str, float] = {}


def evidence_dir() -> str:
    """Where records land. Repo-anchored, env-overridable, gitignored."""
    return os.environ.get("MAL_DIAGNOSTICS_DIR",
                          os.path.join(_REPO_ROOT, "diagnostics"))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def process_start_time(pid: int | None = None) -> str:
    """ISO start time of a process, from /proc/<pid>/stat plus the boot time.

    starttime is stat field 22, in clock ticks since boot. comm (field 2) may
    contain spaces, so parse after the closing paren. Returns an error string
    rather than raising: an unavailable start time is a recorded fact.
    """
    try:
        pid = pid or os.getpid()
        with open(f"/proc/{pid}/stat", "rb") as fh:
            stat = fh.read().decode("ascii", "replace")
        after = stat.rsplit(")", 1)[1].split()
        ticks = int(after[19])
        btime = 0
        with open("/proc/stat") as fh:
            for line in fh:
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    break
        if btime <= 0:
            return "unavailable (no btime in /proc/stat)"
        hz = float(os.sysconf("SC_CLK_TCK"))
        return _iso(btime + ticks / hz)
    except Exception as e:  # noqa: BLE001 - evidence must never raise
        return f"unavailable ({type(e).__name__})"


def fd_count(pid: int | None = None):
    """Open fd count via /proc. Returns an int, or a string saying why not.

    Listing /proc/<pid>/fd needs a descriptor itself, so under fd exhaustion
    this fails. That failure string is evidence, not a gap: it says the
    process could not even open a directory at the moment of capture.
    """
    try:
        return len(os.listdir(f"/proc/{pid or os.getpid()}/fd"))
    except Exception as e:  # noqa: BLE001 - evidence must never raise
        return f"unavailable ({type(e).__name__})"


def socket_count(pid: int | None = None):
    """Open sockets of a process, counted from /proc/<pid>/fd readlinks.
    Same error-string posture as fd_count."""
    fd_dir = f"/proc/{pid or os.getpid()}/fd"
    try:
        names = os.listdir(fd_dir)
    except Exception as e:  # noqa: BLE001 - evidence must never raise
        return f"unavailable ({type(e).__name__})"
    n = 0
    for name in names:
        try:
            if os.readlink(os.path.join(fd_dir, name)).startswith("socket:"):
                n += 1
        except OSError:
            continue  # the fd closed between listdir and readlink
    return n


def control_file_snapshot() -> dict:
    """The control file exactly as read, plus its stat facts.

    Bytes are decoded with backslashreplace so a torn or binary-corrupt file
    survives the JSON encoding byte for byte. controls.json carries operator
    toggles and never a credential (pinned by test_control_precedence), so
    recording it verbatim leaks nothing.
    """
    out: dict = {}
    try:
        from llm_consensus import control_file
        path = control_file.control_path()
    except Exception as e:  # noqa: BLE001 - evidence must never raise
        return {"error": f"path unresolved ({type(e).__name__})"}
    out["path"] = path
    try:
        st = os.stat(path)
        out["size"] = st.st_size
        out["mtime"] = _iso(st.st_mtime)
        out["mode"] = oct(st.st_mode & 0o777)
    except Exception as e:  # noqa: BLE001
        out["stat_error"] = f"{type(e).__name__}: {e}"
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_MAX_CONTROL_BYTES)
        import hashlib
        out["sha256"] = hashlib.sha256(raw).hexdigest()
        out["truncated"] = len(raw) >= _MAX_CONTROL_BYTES
        out["bytes"] = raw.decode("utf-8", "backslashreplace")
    except Exception as e:  # noqa: BLE001
        out["read_error"] = f"{type(e).__name__}: {e}"
    return out


def capture(condition: str, detail: dict | None = None, *,
            include_fd: bool = True,
            min_interval_seconds: int = _MIN_INTERVAL_SECONDS) -> str | None:
    """Write one diagnostic record for a detected condition.

    Returns the record path, None when rate limited or when even the fallback
    failed. Never raises. ``detail`` is caller context (the endpoint, the
    response, the mismatching values); it must never contain a credential.
    """
    record: dict = {"condition": condition}
    try:
        now = time.time()
        if now - _last_capture.get(condition, 0.0) < max(0, min_interval_seconds):
            return None
        _last_capture[condition] = now

        record["ts"] = _utcnow_iso()
        record["pid"] = os.getpid()
        record["process_start_time"] = process_start_time()
        try:
            record["argv"] = list(sys.argv)
        except Exception:  # noqa: BLE001
            record["argv"] = []
        if include_fd:
            record["fd_count"] = fd_count()
        record["control_file"] = control_file_snapshot()
        record["detail"] = dict(detail or {})

        d = evidence_dir()
        os.makedirs(d, exist_ok=True)
        name = (f"{condition}-{record['ts'].replace(':', '')}"
                f"-pid{record['pid']}.json")
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            json.dump(record, fh, indent=2)
        log.warning("evidence captured: %s -> %s", condition, path)
        return path
    except Exception:  # noqa: BLE001 - the last resort is one log line
        try:
            log.warning("evidence capture could not write a record for %s: %s",
                        condition, json.dumps(record, default=str)[:4000])
        except Exception:  # noqa: BLE001
            pass
        return None
