"""The strategy profile's runtime lever, Python half (2026-07-23).

The SHIPPED config carries the SHIPPED profile (swing). The runtime choice
lives in controls.json ("strategy_profile"), resolved by
market_data.universe.resolved_profile the same way core/profile_controls.hpp
resolves it for the engine, so both halves read the same value. An invalid or
unreadable control file means NO override, config decides.

The first test is the guard against the old mechanism returning: a session
that reintroduces a profile edit to config/default_config.yaml fails it,
committed or not, because it reads the working-tree file.
"""
from __future__ import annotations

import json
import os

SHIPPED = "config/default_config.yaml"


def _write_controls(tmp_path, payload: dict) -> None:
    with open(os.path.join(str(tmp_path), "controls.json"), "w") as fh:
        json.dump(payload, fh)


def test_shipped_config_carries_the_shipped_profile():
    from llm_consensus.config_access import config_block
    profile = str(config_block("strategy", SHIPPED).get("profile", "swing"))
    assert profile == "swing", (
        f"config/default_config.yaml ships profile '{profile}'. The shipped "
        "default is swing; select active_quant through the controls.json "
        "strategy_profile lever, never by editing the shipped file (that "
        "edit got swept into commit 440fda8)")


def test_control_file_overrides_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    _write_controls(tmp_path, {"strategy_profile": "active_quant"})
    from market_data import universe
    assert universe.resolved_profile(SHIPPED) == "active_quant"
    core = universe.declared_core(SHIPPED)
    assert "SOL/USD" in core and len(core) == 8, (
        "the active_quant override must resolve the eight-name core")


def test_invalid_or_absent_override_means_config_decides(tmp_path, monkeypatch):
    from market_data import universe
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    # Absent file: config decides.
    assert universe.resolved_profile(SHIPPED) == "swing"
    # Invalid value: refused, never guessed.
    _write_controls(tmp_path, {"strategy_profile": "yolo_mode"})
    assert universe.resolved_profile(SHIPPED) == "swing"
    core = universe.declared_core(SHIPPED)
    assert len(core) == 4, "an invalid override must leave the swing core"


def test_controls_writer_round_trips_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    from api_server import controls
    state = controls.read_controls()
    assert state.get("strategy_profile") in controls.STRATEGY_PROFILES
    state["strategy_profile"] = "active_quant"
    controls._write_controls(state)
    again = controls.read_controls()
    assert again["strategy_profile"] == "active_quant"
    # Flat and unique in the written file: the engine's reader is a flat
    # search, so a duplicate key would be read order-dependently.
    text = open(os.path.join(str(tmp_path), "controls.json")).read()
    assert text.count('"strategy_profile"') == 1
