"""Replay feed refuses clearly when the bars table is empty (Task 6).

Historical replay must never silently produce zero bars: with no data in the
requested range it must fail loudly and tell the operator to run the Alpaca
backfill first. Replay lives in the C++ engine, so this drives the built
``mal_engine`` binary against an empty bars table. No network is used (the
"missing data" is the empty DB itself).
"""
import os
import subprocess

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE = os.path.join(_REPO, "build", "mal_engine")
_SCHEMA = os.path.join(_REPO, "storage", "schema.sql")
_CONFIG = os.path.join(_REPO, "config", "default_config.yaml")


@pytest.mark.skipif(not os.path.exists(_ENGINE),
                    reason="mal_engine not built (build/ absent)")
def test_replay_refuses_when_bars_table_empty(tmp_path):
    db = tmp_path / "empty.db"  # fresh DB => empty bars table
    proc = subprocess.run(
        [_ENGINE, "--config", _CONFIG, "--db", str(db), "--schema", _SCHEMA,
         "--feed-mode", "replay", "--clock-mode", "simulated", "--iterations", "1"],
        cwd=_REPO, capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"expected non-zero exit, got 0:\n{out}"
    # The refusal must be actionable: name the empty table and the backfill step.
    assert "backfill" in out.lower(), f"refusal not actionable:\n{out}"
    assert "no bars" in out.lower() or "replay" in out.lower()
