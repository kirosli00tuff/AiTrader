"""Numerical-environment guard (STAGE C.1; Amendment 9.15, execution).

Measured 2026-10-10 in Stage C.1: numpy 1.26.4 built for Python 3.14 (the
collector's .venv) silently corrupts arithmetic inside functions once an
array reaches 256 KiB. numpy's temporary elision writes a result into an
operand it believes is a dead temporary, and Python 3.14 lends a local
variable to the stack without taking a reference, so a live local looks
dead. `d = x - 1.0; wd = w * d; (wd * d).sum()` returned 640,000 where the
answer is 320,000 at n = 40,000, and the S1 bootstrap SE came out about 750
times too small. No error is raised; the numbers are simply wrong.

The harness therefore runs only in .venv-eval (Python 3.12.13, numpy 2.5.3,
news_eval/requirements-eval.lock), and every entry point that computes on
data calls assert_numpy_sane() first. The canaries use arrays above the
elision floor and check results that are exact in float64.
"""
from __future__ import annotations

import numpy as np

CANARY_N = 100_000  # 800,000 bytes per float64 array, above the 256 KiB floor


class EnvironmentRefused(RuntimeError):
    """The running numpy computes wrong answers; nothing may be computed."""


def _canary_reuse(w: np.ndarray, x: np.ndarray) -> float:
    d = x - 1.0
    wd = w * d
    return float((wd * d).sum())


def _canary_alias(x: np.ndarray) -> float:
    y = x + 1.0
    z = y * 2.0
    return float((z - y).sum())


def numpy_sane() -> bool:
    """True when both elision canaries return their exact answers."""
    x = np.full(CANARY_N, 3.0)
    w = np.full(CANARY_N, 2.0)
    return (_canary_reuse(w, x) == 8.0 * CANARY_N
            and _canary_alias(x) == 4.0 * CANARY_N)


def assert_numpy_sane() -> None:
    """Refuse before any computation when the elision canaries fail."""
    if not numpy_sane():
        raise EnvironmentRefused(
            f"numpy {np.__version__} on this interpreter fails the temporary-"
            "elision canary; run the harness with .venv-eval/bin/python "
            "(news_eval/requirements-eval.lock)")
