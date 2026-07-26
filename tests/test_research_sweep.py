"""The memory-sized sweep runner and the streaming harness (2026-07-25).

Pins the OOM-incident preventions:
  * worker width derives from measured RSS and available memory, never a
    constant (mutating the sizing to a hardcoded width fails here),
  * an oversized batch is refused with its numbers stated,
  * a running trading stack shrinks the width or refuses the batch,
  * a MemoryMax scope kills a runaway inside the scope and nothing else,
  * the streaming tape reproduces the held tape byte for byte.
"""
from __future__ import annotations

import datetime
import math
import os
import sqlite3
import subprocess

import pytest

from backtest import sweep

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(REPO, "build", "mal_backtest")
SCHEMA = os.path.join(REPO, "storage", "schema.sql")

MB = 1024  # kB per MB

INCIDENT_PER_RUN_KB = 1_159_080  # measured 2026-07-25


# ---- Task 1: width from measured memory, never a constant ----------------

def test_incident_numbers_compute_width_three() -> None:
    plan = sweep.plan_workers(INCIDENT_PER_RUN_KB, 4_710_400, 0,
                              margin=0.25, max_workers=18)
    assert not plan.refused
    assert plan.width == 3
    assert plan.width != 14  # the width the incident actually launched


@pytest.mark.parametrize("available_mb,expected", [
    (2_000, 1), (4_000, 3), (8_000, 6), (16_000, 12)])
def test_width_scales_with_available_memory(available_mb: int,
                                            expected: int) -> None:
    plan = sweep.plan_workers(1_000 * MB, available_mb * MB, 0,
                              margin=0.25, max_workers=64)
    assert plan.width == expected


@pytest.mark.parametrize("per_run_mb,expected", [
    (500, 6), (1_000, 3), (3_000, 1)])
def test_width_scales_with_per_run_rss(per_run_mb: int,
                                       expected: int) -> None:
    plan = sweep.plan_workers(per_run_mb * MB, 4_000 * MB, 0,
                              margin=0.25, max_workers=64)
    assert plan.width == expected


def test_width_capped_by_workers() -> None:
    plan = sweep.plan_workers(100 * MB, 64_000 * MB, 0, max_workers=5)
    assert plan.width == 5


def test_margin_reduces_width() -> None:
    loose = sweep.plan_workers(1_000 * MB, 8_000 * MB, 0, margin=0.0,
                               max_workers=64)
    tight = sweep.plan_workers(1_000 * MB, 8_000 * MB, 0, margin=0.5,
                               max_workers=64)
    assert tight.width < loose.width


# ---- Task 1: refusal with numbers stated ---------------------------------

def test_oversized_batch_refused_with_numbers() -> None:
    plan = sweep.plan_workers(2_048 * MB, 1_024 * MB, 0)
    assert plan.refused
    assert plan.width == 0
    assert "2048 MB" in plan.reason      # the measured per-run figure
    assert "1024 MB available" in plan.reason
    assert "REFUSED" in plan.reason


def test_cli_refuses_oversized(tmp_path) -> None:
    f = tmp_path / "cmds.txt"
    f.write_text("true\n")
    rc = sweep.main(["--commands", str(f), "--dry-run",
                     "--assume-run-rss-mb", "4000",
                     "--assume-available-mb", "3000",
                     "--assume-stack-rss-mb", "0"])
    assert rc == 3


# ---- Task 4: a running stack shrinks or refuses --------------------------

def test_stack_reserve_shrinks_width() -> None:
    without = sweep.plan_workers(1_000 * MB, 8_000 * MB, 0,
                                 margin=0.25, max_workers=64)
    with_stack = sweep.plan_workers(1_000 * MB, 8_000 * MB, 2_000 * MB,
                                    margin=0.25, max_workers=64)
    assert with_stack.width < without.width
    assert with_stack.stack_reserve_kb == 2_000 * MB


def test_stack_too_big_refuses_single_run() -> None:
    plan = sweep.plan_workers(2_000 * MB, 4_000 * MB, 3_000 * MB)
    assert plan.refused
    assert "stack reserve" in plan.reason


def test_cli_sizes_down_when_stack_up(tmp_path, capsys) -> None:
    f = tmp_path / "cmds.txt"
    f.write_text("true\ntrue\ntrue\n")
    rc = sweep.main(["--commands", str(f), "--dry-run", "--no-scope",
                     "--assume-run-rss-mb", "1000",
                     "--assume-available-mb", "8000",
                     "--assume-stack-rss-mb", "2000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "trading stack RUNNING" in out
    assert "width 4" in out  # (8000-2000)*0.75/1000, not 6000/1000


# ---- Task 2: the MemoryMax scope bounds a runaway ------------------------

HOG = "b = bytearray(300 * 1024 * 1024); print(len(b))"


@pytest.mark.skipif(not sweep.scope_available(),
                    reason="systemd-run --user scope unavailable")
def test_scope_kills_runaway_inside_bound() -> None:
    r = subprocess.run(
        sweep.scope_prefix(64 * 1024) + ["python3", "-c", HOG],
        capture_output=True)
    assert r.returncode != 0  # killed by the scope's own MemoryMax
    # the same allocation outside any scope succeeds untouched
    ctrl = subprocess.run(["python3", "-c", HOG], capture_output=True)
    assert ctrl.returncode == 0


def test_probe_measures_real_rss() -> None:
    kb = sweep.measure_run_rss_kb(
        "python3 -c 'b = bytearray(50 * 1024 * 1024)'")
    assert kb >= 50 * 1024  # at least the 50 MB it allocated


# ---- Task 3: streaming reproduces the held tape exactly ------------------

def _mk_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    with open(SCHEMA) as fh:
        conn.executescript(fh.read())
    for ddl in ("ALTER TABLE bars ADD COLUMN source TEXT DEFAULT 'unknown'",
                "ALTER TABLE bars ADD COLUMN volume_source TEXT"):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    return conn


def _seed(conn, symbol: str, n: int, base_epoch: int) -> None:
    # Equal timestamps across symbols on purpose: tie order is the case
    # streaming must reproduce. Spans a month boundary on purpose too.
    for i in range(n):
        ts = datetime.datetime.fromtimestamp(
            base_epoch + i * 300,
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        px = 100.0 + 5.0 * math.sin(i / 12.0) + (i % 7) * 0.2
        conn.execute(
            "INSERT OR REPLACE INTO bars(venue,symbol,timeframe,timestamp,"
            "open,high,low,close,volume,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("alpaca", symbol, "5min", ts, px, px + 0.8, px - 0.8,
             px + 0.3, 1000.0 + i, "backfill"))


@pytest.mark.skipif(not os.path.exists(BIN),
                    reason="mal_backtest not built")
def test_stream_and_hold_tape_byte_identical(tmp_path) -> None:
    db = str(tmp_path / "bars.db")
    conn = _mk_db(db)
    # 2026-01-30T00:00Z start: 600 bars cross the Jan/Feb window boundary.
    base = int(datetime.datetime(
        2026, 1, 30, tzinfo=datetime.timezone.utc).timestamp())
    _seed(conn, "BTC/USD", 600, base)
    _seed(conn, "ETH/USD", 600, base)
    conn.commit()
    conn.close()

    def run(*extra: str) -> str:
        return subprocess.run(
            [BIN, "--db", db, "--profile", "swing",
             "--symbols", "BTC/USD,ETH/USD", "--emit-rejections", *extra],
            capture_output=True, text=True, check=True).stdout

    held = run("--hold-tape")
    streamed = run()
    assert streamed == held
    assert '"t":"summary"' in streamed


# ---- CLI edges -----------------------------------------------------------

def test_cli_empty_commands_file(tmp_path) -> None:
    f = tmp_path / "cmds.txt"
    f.write_text("# only a comment\n")
    assert sweep.main(["--commands", str(f), "--dry-run"]) == 2
