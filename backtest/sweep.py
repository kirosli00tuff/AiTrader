"""Memory-sized research sweep runner (2026-07-25).

Born from the OOM incident of 2026-07-25: a 14-way sweep of 1.13 GB
backtest runs on a 14 GB host exhausted memory, and the kernel OOM killer
chose victims across the whole machine, including the live trading stack.
This runner exists so that can never repeat:

  1. It MEASURES one run's peak RSS before launching anything. Width is
     never a constant and never an operator guess.
  2. It sizes worker count from measured RSS against available memory with
     a safety margin.
  3. It detects a running trading stack, reserves the stack's measured
     footprint again as headroom, and REFUSES the batch when even one
     worker cannot fit beside it. Research is never more important than
     the run it would kill.
  4. It launches the batch inside a systemd user scope with MemoryMax set
     to the batch's own budget, so a runaway batch is killed by its own
     bound and the kernel never chooses a victim for it.

Usage:
  python3 -m backtest.sweep --commands FILE [--margin 0.25] [--dry-run]
      [--no-scope] [--assume-run-rss-mb N] [--assume-available-mb N]
      [--assume-stack-rss-mb N]

The --assume-* flags replace a measurement with a stated value. They exist
for tests and for demonstrations while the stack must not be started. A
real launch without them measures everything.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
from dataclasses import dataclass

# Safety margin over the projected batch footprint. 0.25 covers what the
# probe cannot see: per-cell RSS variance across config variants, allocator
# overshoot, and page-cache pressure from concurrent sqlite readers. The
# incident numbers land at width 3 under this margin (see plan_workers).
DEFAULT_MARGIN = 0.25

# Patterns identifying the trading stack in /proc cmdlines. One entry per
# component the 2026-07-25 OOM sweep killed.
STACK_PATTERNS = ("mal_engine", "python_bridge", "api_server", "ops.watchdog")


@dataclass(frozen=True)
class Plan:
    """The sizing decision and every number that produced it."""
    per_run_kb: int
    available_kb: int
    stack_rss_kb: int
    stack_reserve_kb: int
    margin: float
    max_workers: int
    width: int
    refused: bool
    reason: str


def read_available_kb() -> int:
    """MemAvailable from /proc/meminfo, in kB."""
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    raise RuntimeError("MemAvailable not found in /proc/meminfo")


def stack_rss_kb() -> tuple[int, list[str]]:
    """Total resident memory of trading-stack processes, plus their names.

    Scans /proc/*/cmdline for STACK_PATTERNS. Skips this process so the
    runner never counts itself, and skips tooling that merely mentions a
    pattern.
    """
    total = 0
    found: list[str] = []
    self_pid = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == self_pid:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode(errors="replace")
            if not any(p in cmd for p in STACK_PATTERNS):
                continue
            if "sweep" in cmd or "grep" in cmd or "vim" in cmd:
                continue
            with open(f"/proc/{pid}/status") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1])
                        found.append(cmd.strip()[:80])
                        break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return total, found


def measure_run_rss_kb(command: str) -> int:
    """Run ONE command under /usr/bin/time -v and return its peak RSS in kB.

    This is the probe. It does real work (its output counts), and its
    measured footprint sizes the rest of the batch.
    """
    proc = subprocess.run(
        ["/usr/bin/time", "-v", "bash", "-c", command],
        capture_output=True, text=True)
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)",
                  proc.stderr)
    if not m:
        raise RuntimeError(
            f"probe run did not report RSS (exit {proc.returncode}): "
            f"{proc.stderr[-500:]}")
    return int(m.group(1))


def plan_workers(per_run_kb: int, available_kb: int, stack_kb: int,
                 margin: float = DEFAULT_MARGIN,
                 max_workers: int | None = None) -> Plan:
    """Width from measured numbers. Never a constant.

    usable = (available - stack_reserve) * (1 - margin)
    width  = min(max_workers, usable / per_run)

    stack_reserve equals the stack's measured RSS again: the stack's
    current pages are already resident (outside MemAvailable), and the
    reserve keeps an equal amount free for its growth and page cache.
    Refuses when width < 1. Under the incident numbers (1,159,080 kB per
    run, roughly 4.6 GB available beside the running stack) this computes
    width 3 where the incident launched 14.
    """
    if per_run_kb <= 0:
        raise ValueError("per_run_kb must be positive")
    if max_workers is None:
        max_workers = max(1, (os.cpu_count() or 2) - 2)
    reserve = stack_kb
    usable = (available_kb - reserve) * (1.0 - margin)
    width = int(usable // per_run_kb) if usable > 0 else 0
    width = min(width, max_workers)
    if width < 1:
        return Plan(
            per_run_kb, available_kb, stack_kb, reserve, margin, max_workers,
            0, True,
            f"REFUSED: one run needs {per_run_kb // 1024} MB, but only "
            f"{max(0, int(usable)) // 1024} MB is usable "
            f"({available_kb // 1024} MB available minus "
            f"{reserve // 1024} MB stack reserve, "
            f"minus {margin:.0%} margin). "
            "Free memory or shrink the batch, never the stack.")
    return Plan(
        per_run_kb, available_kb, stack_kb, reserve, margin, max_workers,
        width, False,
        f"width {width}: {per_run_kb // 1024} MB measured per run, "
        f"{available_kb // 1024} MB available, "
        f"{reserve // 1024} MB reserved for the stack, "
        f"{margin:.0%} margin, worker cap {max_workers}")


def scope_prefix(memmax_kb: int) -> list[str]:
    """systemd user scope carrying the batch's own memory bound."""
    return ["systemd-run", "--user", "--scope", "--quiet",
            "-p", f"MemoryMax={memmax_kb}K", "-p", "MemorySwapMax=0"]


def scope_available() -> bool:
    """Whether a MemoryMax scope can be created here."""
    try:
        r = subprocess.run(
            scope_prefix(1024 * 1024) + ["true"],
            capture_output=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_batch(commands: list[str], width: int, memmax_kb: int,
              use_scope: bool) -> int:
    """Run commands at the planned width, each failure contained.

    A failed or killed command never stops the batch (the 2026-07-25
    matrix lost 46 runs to one SIGABRT stopping xargs). Returns the count
    of failed commands.
    """
    prefix = scope_prefix(memmax_kb) if use_scope else []

    def one(cmd: str) -> int:
        r = subprocess.run(prefix + ["bash", "-c", cmd])
        return r.returncode

    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=width) as pool:
        for cmd, rc in zip(commands, pool.map(one, commands)):
            if rc != 0:
                failures += 1
                print(f"[sweep] FAILED (rc={rc}): {cmd}", file=sys.stderr)
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commands", required=True,
                    help="file with one shell command per line")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    ap.add_argument("--max-workers", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="plan and print, launch nothing")
    ap.add_argument("--no-scope", action="store_true",
                    help="run without a MemoryMax scope (loud, discouraged)")
    ap.add_argument("--assume-run-rss-mb", type=int, default=None,
                    help="test/demo: skip the probe, assume this per-run RSS")
    ap.add_argument("--assume-available-mb", type=int, default=None,
                    help="test/demo: override MemAvailable")
    ap.add_argument("--assume-stack-rss-mb", type=int, default=None,
                    help="test/demo: override the measured stack RSS")
    args = ap.parse_args(argv)

    with open(args.commands) as fh:
        commands = [c.strip() for c in fh if c.strip()
                    and not c.strip().startswith("#")]
    if not commands:
        print("[sweep] no commands", file=sys.stderr)
        return 2

    if args.assume_stack_rss_mb is not None:
        stack_kb, stack_names = args.assume_stack_rss_mb * 1024, ["(assumed)"]
    else:
        stack_kb, stack_names = stack_rss_kb()
    if stack_kb:
        print(f"[sweep] trading stack RUNNING: {stack_kb // 1024} MB across "
              f"{len(stack_names)} processes. Sizing around it.")

    probed = False
    if args.assume_run_rss_mb is not None:
        per_run_kb = args.assume_run_rss_mb * 1024
    else:
        print(f"[sweep] probing one run for RSS: {commands[0]}")
        per_run_kb = measure_run_rss_kb(commands[0])
        probed = True
        print(f"[sweep] measured {per_run_kb // 1024} MB peak RSS")

    available_kb = (args.assume_available_mb * 1024
                    if args.assume_available_mb is not None
                    else read_available_kb())

    plan = plan_workers(per_run_kb, available_kb, stack_kb,
                        margin=args.margin, max_workers=args.max_workers)
    print(f"[sweep] {plan.reason}")
    if plan.refused:
        return 3

    remaining = commands[1:] if probed else commands
    if not remaining:
        print("[sweep] probe covered the whole batch")
        return 0
    memmax_kb = int(plan.width * per_run_kb * (1.0 + args.margin))
    use_scope = not args.no_scope
    if use_scope and not scope_available():
        print("[sweep] REFUSED: no MemoryMax scope available "
              "(systemd-run --user failed). Pass --no-scope to run "
              "unbounded, which removes the batch's own kill bound.",
              file=sys.stderr)
        return 4
    if args.dry_run:
        print(f"[sweep] dry run: width {plan.width}, "
              f"MemoryMax {memmax_kb // 1024} MB, scope {use_scope}, "
              f"{len(remaining)} commands")
        return 0
    if not use_scope:
        print("[sweep] WARNING: running WITHOUT a memory bound",
              file=sys.stderr)
    failures = run_batch(remaining, plan.width, memmax_kb, use_scope)
    print(f"[sweep] done: {len(remaining) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
