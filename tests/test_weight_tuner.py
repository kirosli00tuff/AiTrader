"""Tests for the adaptive advisory weight tuner (ui/weight_tuner.py).

Targets the PURE ``tune_weights`` contract: it moves weight toward the
more-accurate factor, never touches locked factors, preserves total mass
(renormalization holds), and respects the min/max floors.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UI = os.path.join(_ROOT, "ui")
if _UI not in sys.path:
    sys.path.insert(0, _UI)

import weight_tuner as wt  # noqa: E402


def _sum(d):
    return sum(d.values())


def test_moves_toward_more_accurate_factor():
    current = {"a": 0.5, "b": 0.5}
    locks = {"a": False, "b": False}
    # b is more accurate than a -> b should gain, a should lose.
    new = wt.tune_weights(current, {"a": 0.2, "b": 0.9}, locks, lr=0.25)
    assert new["b"] > current["b"]
    assert new["a"] < current["a"]
    assert abs(_sum(new) - 1.0) < 1e-9


def test_locked_factor_untouched():
    current = {"a": 0.5, "b": 0.3, "c": 0.2}
    locks = {"a": False, "b": True, "c": False}
    new = wt.tune_weights(current, {"a": 0.9, "b": 0.1, "c": 0.2}, locks, lr=0.3)
    # b is locked -> frozen at its exact current value, excluded from tuning.
    assert new["b"] == current["b"]
    # the unlocked pool still moves toward the more-accurate factor (a).
    assert new["a"] > current["a"]
    assert new["c"] < current["c"]


def test_renormalization_holds():
    current = {"a": 0.27, "b": 0.18, "c": 0.55}
    locks = {k: False for k in current}
    new = wt.tune_weights(current, {"a": 0.6, "b": 0.4, "c": 0.5}, locks)
    assert abs(_sum(new) - 1.0) < 1e-9


def test_renormalization_holds_with_lock():
    current = {"a": 0.4, "b": 0.4, "c": 0.2}
    locks = {"a": False, "b": False, "c": True}
    new = wt.tune_weights(current, {"a": 0.8, "b": 0.2, "c": 0.5}, locks)
    assert new["c"] == current["c"]            # locked mass preserved
    assert abs(_sum(new) - 1.0) < 1e-9          # whole vector still sums to 1


def test_min_max_floors_respected():
    current = {"a": 0.5, "b": 0.5}
    locks = {"a": False, "b": False}
    # Extreme accuracy gap with a high LR would otherwise push past the floors.
    new = wt.tune_weights(current, {"a": 0.0, "b": 1.0}, locks,
                          lr=5.0, w_min=0.1, w_max=0.7)
    for v in new.values():
        assert 0.1 - 1e-9 <= v <= 0.7 + 1e-9
    assert abs(_sum(new) - 1.0) < 1e-9


def test_no_accuracy_leaves_weights_unchanged():
    current = {"a": 0.3, "b": 0.3, "c": 0.4}
    locks = {k: False for k in current}
    new = wt.tune_weights(current, {"a": None, "b": None, "c": None}, locks)
    for k in current:
        assert abs(new[k] - current[k]) < 1e-9


def test_unscored_factor_holds_while_others_tune():
    current = {"a": 0.4, "b": 0.4, "c": 0.2}
    locks = {k: False for k in current}
    # Only a and b have signals; c has none and should stay ~flat in raw terms
    # while a/b redistribute. Total mass preserved.
    new = wt.tune_weights(current, {"a": 0.9, "b": 0.1, "c": None}, locks, lr=0.2)
    assert new["a"] > new["b"]
    assert abs(_sum(new) - 1.0) < 1e-9
