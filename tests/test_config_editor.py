"""Tests for the Level 1 risk-gate config editor (ui/config_editor.py).

Covers the round-trip read/edit/write contract, comment/format preservation,
and that invalid values are rejected without mutating the file on disk.
"""
import os
import shutil
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UI = os.path.join(_ROOT, "ui")
if _UI not in sys.path:
    sys.path.insert(0, _UI)

import config_editor as ce  # noqa: E402

_SRC = os.path.join(_ROOT, "config", "default_config.yaml")


@pytest.fixture()
def cfg(tmp_path):
    dst = tmp_path / "config.yaml"
    shutil.copy(_SRC, dst)
    return str(dst)


def test_read_l1_values_typed(cfg):
    vals = ce.read_l1_values(cfg)
    assert isinstance(vals["max_daily_loss_total_pct"], float)
    assert isinstance(vals["max_open_positions_total"], int)
    assert isinstance(vals["kill_switch_enabled"], bool)
    assert vals["max_consecutive_losses"] == 3


def test_round_trip_read_edit_write(cfg):
    written = ce.write_l1_values(
        {"max_daily_loss_total_pct": 0.05,
         "max_open_positions_total": 8,
         "kill_switch_enabled": False}, cfg)
    assert written["max_daily_loss_total_pct"] == 0.05
    reread = ce.read_l1_values(cfg)
    assert reread["max_daily_loss_total_pct"] == 0.05
    assert reread["max_open_positions_total"] == 8
    assert reread["kill_switch_enabled"] is False
    # Untouched params are unchanged.
    assert reread["max_consecutive_losses"] == 3


def test_write_preserves_other_blocks_and_comments(cfg):
    before = open(cfg).read()
    assert "# sum = 1.00" in before
    ce.write_l1_values({"min_confidence_default": 0.7}, cfg)
    after = open(cfg).read()
    # Comments / unrelated blocks survive the edit.
    assert "# sum = 1.00" in after
    assert "STATIC SAFETY (HARD LIMITS)" in after
    assert "model_weights:" in after
    assert ce.read_l1_values(cfg)["min_confidence_default"] == 0.7


def test_invalid_pct_rejected_without_mutating(cfg):
    original = open(cfg).read()
    with pytest.raises(ValueError):
        ce.write_l1_values({"max_daily_loss_total_pct": 1.5}, cfg)
    assert open(cfg).read() == original  # file untouched on rejection


def test_invalid_cross_field_rejected(cfg):
    with pytest.raises(ValueError):
        # per-venue must not exceed total (default total is 0.03)
        ce.write_l1_values({"max_daily_loss_per_venue_pct": 0.9}, cfg)


def test_invalid_int_and_bounds_rejected(cfg):
    with pytest.raises(ValueError):
        ce.write_l1_values({"max_open_positions_total": -1}, cfg)
    with pytest.raises(ValueError):
        ce.write_l1_values({"max_consecutive_losses": 0}, cfg)
    with pytest.raises(ValueError):
        # non-integer for an int param
        ce.write_l1_values({"max_open_positions_total": 2.5}, cfg)


def test_validate_only_does_not_write(cfg):
    current = ce.read_l1_values(cfg)
    problems = ce.validate_l1_changes(current, {"min_edge_default": 2.0})
    assert problems
    # validation alone never writes
    assert ce.read_l1_values(cfg)["min_edge_default"] == current["min_edge_default"]


def test_unknown_param_rejected(cfg):
    with pytest.raises(ValueError):
        ce.write_l1_values({"not_a_real_param": 1}, cfg)
