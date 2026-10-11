"""The numerical-environment guard (news_eval/envcheck.py; Stage C.1).

numpy 1.26.4 on Python 3.14 corrupts in-function arithmetic on arrays of
256 KiB or more. The harness must run in .venv-eval and refuse elsewhere.
"""
import numpy as np
import pytest

from news_eval import envcheck, gate


def test_canaries_pass_in_this_environment():
    assert envcheck.numpy_sane()
    envcheck.assert_numpy_sane()


def test_canary_arrays_exceed_the_elision_floor():
    assert envcheck.CANARY_N * np.dtype(np.float64).itemsize > 256 * 1024


@pytest.mark.parametrize("name", ["_canary_reuse", "_canary_alias"])
def test_a_wrong_canary_refuses(monkeypatch, name):
    monkeypatch.setattr(envcheck, name, lambda *a: -1.0)
    assert not envcheck.numpy_sane()
    with pytest.raises(envcheck.EnvironmentRefused):
        envcheck.assert_numpy_sane()


def test_gate_refuses_before_reading_when_the_canary_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(envcheck, "numpy_sane", lambda: False)
    log = tmp_path / "gate.jsonl"
    code = gate.run(tmp_path / "absent.db", log)
    assert code == gate.EXIT_REFUSED
    assert not log.exists()
