"""Stamp a process's output and append it to a rotated per-process log.

NO FAILURE MAY LEAVE NO TRACE (2026-07-25). The validation run ended when the
watchdog observed `backend_down` and stopped the stack, and why the backend died
could not be established, because not one supervised process had its stderr
captured anywhere. `scripts/start_paper_trading.sh` launched the bridge, the
engine, the api, the watchdog, and vite with a bare `&` and no redirection, and
`ops/start.sh` wrote two files with a truncating `>` and no timestamps. The only
`.run/*.log` files on disk were five days stale.

Each supervised process writes through one of these, so:
  * every line carries the time it was written, not the time someone read it,
  * a chatty process cannot fill the disk (size-based rotation, fixed
    generations),
  * output survives the process that produced it, which is the whole point.

Usage: `some-process 2>&1 | python -m ops.logpipe <name>`, or through
`api_server.stack.spawn(..., log_name="<name>")`. The shell launchers use
process substitution so `$!` stays the CHILD's pid rather than this logger's.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# 16 MiB per generation, 3 old generations kept: 64 MiB per process worst case.
# Sized against the observed 19 MiB start.log, so a normal run never rotates and
# a pathological one is still bounded.
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
DEFAULT_GENERATIONS = 3


def run_dir() -> str:
    """The .run directory, resolved the way api_server.stack resolves it.

    Repo-anchored, never cwd-relative: a launcher started from another directory
    must not scatter logs (the 2026-07-18 cwd lesson).
    """
    override = os.environ.get("MAL_RUN_DIR")
    if override:
        return override
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".run")


def log_path(name: str) -> str:
    safe = "".join(c for c in str(name) if c.isalnum() or c in "-_") or "process"
    return os.path.join(run_dir(), f"{safe}.log")


def rotate(path: str, max_bytes: int = DEFAULT_MAX_BYTES,
           generations: int = DEFAULT_GENERATIONS) -> bool:
    """Roll `path` to `path.1` when it exceeds max_bytes. Returns True if rolled.

    Best-effort: a rotation that cannot happen must never stop the logging,
    because losing the ability to log is worse than an oversized file.
    """
    try:
        if max_bytes <= 0 or not os.path.exists(path):
            return False
        if os.path.getsize(path) < max_bytes:
            return False
        oldest = f"{path}.{generations}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(generations - 1, 0, -1):
            src, dst = f"{path}.{i}", f"{path}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, f"{path}.1")
        return True
    except Exception:  # noqa: BLE001 - never break the pipe
        return False


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pump(name: str, stream=None, max_bytes: int = DEFAULT_MAX_BYTES,
         generations: int = DEFAULT_GENERATIONS) -> int:
    """Read lines from `stream` (stdin by default) into the rotated log.

    Returns the number of lines written. Unbuffered on purpose: a process that
    dies must have its last line already on disk, and a 4 KiB buffer is exactly
    how a crash message gets lost.
    """
    src = stream if stream is not None else sys.stdin.buffer
    path = log_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    written = 0
    fh = open(path, "ab", buffering=0)
    try:
        # Mark the boundary, so "which run wrote this" is answerable from the
        # file alone rather than by correlating mtimes.
        fh.write(f"{_stamp()} --- {name} log opened (pid {os.getpid()}) ---\n"
                 .encode())
        for raw in iter(src.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\n")
            fh.write(f"{_stamp()} {line}\n".encode())
            written += 1
            if rotate(path, max_bytes, generations):
                fh.close()
                fh = open(path, "ab", buffering=0)
        fh.write(f"{_stamp()} --- {name} stream closed ---\n".encode())
    except Exception as e:  # noqa: BLE001 - a logger must not raise at teardown
        try:
            fh.write(f"{_stamp()} --- logpipe error: {type(e).__name__} ---\n"
                     .encode())
        except Exception:
            pass
    finally:
        try:
            fh.close()
        except Exception:
            pass
    return written


def tail(name: str, nbytes: int = 4000) -> str:
    """The last nbytes of a process log, for evidence capture. Never raises."""
    try:
        path = log_path(name)
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - nbytes))
            return fh.read().decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: python -m ops.logpipe <name>", file=sys.stderr)
        return 2
    pump(args[0])
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
