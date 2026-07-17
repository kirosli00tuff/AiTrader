"""THE precedence rule: controls.json overrides config, on BOTH sides.

The defect these exist to catch, confirmed from live logs: the C++ engine read
discovery_enabled from controls.json (where the GUI toggle writes it) and saw ON,
while the Python funnel read the config default and saw OFF. The engine logged
"engine reads discovery ON but the Python funnel reads it OFF" and refused every
pass. One flag, two sources, two answers.

Two root causes, both proven here rather than asserted:

  1. A TORN READ. api_server wrote controls.json with open(path, "w"), which
     TRUNCATES before writing. Every reader swallows a read error and falls back
     to config, so a read landing in that window did not fail loudly, it silently
     reported the SHIPPED default. Measured on the old writer: 88 percent of
     reads returned discovery OFF while the file on disk said ON.
  2. A CWD-RELATIVE PATH. config ships system.control_dir as the relative
     ".control", and each of the three processes resolved it against its OWN
     working directory. They agreed only by all happening to launch from the repo
     root.

The rule now has one implementation (llm_consensus/control_file.py) that every
Python reader shares, and the C++ side mirrors it in core/*_controls.hpp.
"""
from __future__ import annotations

import json
import os
import threading

import pytest

from llm_consensus import control_file


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path))
    return tmp_path


def _write(ctl, state: dict) -> None:
    (ctl / "controls.json").write_text(json.dumps(state, indent=2))


# --- The rule ---------------------------------------------------------------

def test_controls_json_overrides_config(ctl):
    from discovery import settings
    _write(ctl, {"discovery": {"discovery_enabled": True}})
    # Config ships discovery OFF. The operator's file says ON. The operator wins.
    assert settings.discovery_enabled(None) is True


def test_controls_json_overrides_config_in_both_directions(ctl):
    """A toggle that can only ever turn something ON is not a toggle."""
    from discovery import settings
    _write(ctl, {"discovery": {"discovery_enabled": False}})
    assert settings.discovery_enabled(None) is False


def test_absent_control_file_falls_back_to_the_shipped_default(ctl):
    from discovery import settings
    assert not (ctl / "controls.json").exists()
    assert settings.discovery_enabled(None) is False   # config ships it off


def test_an_unreadable_control_file_means_no_override_not_a_crash(ctl):
    from discovery import settings
    (ctl / "controls.json").write_text('{"discovery": {"discovery_enabled":')
    # No override, so config decides. A broken file must never START a spender.
    assert settings.discovery_enabled(None) is False
    assert control_file.control_state() == {}


def test_a_key_the_control_file_omits_falls_back_per_key(ctl):
    """Precedence is per KEY, not per file: a partial block overrides only what
    it carries, so an operator setting one field does not reset the rest."""
    from discovery import settings
    _write(ctl, {"discovery": {"discovery_enabled": True}})
    assert settings.discovery_enabled(None) is True
    # max_finalists is absent from the control file, so config's value stands.
    assert settings.max_finalists(None) == 12


# --- The same rule for every other GUI-toggleable flag ----------------------

def test_the_adaptive_flags_follow_the_rule(ctl):
    from adaptive import settings as a
    _write(ctl, {"adaptive_realtime": {"adaptive_news_feed_enabled": True}})
    assert a.news_feed_enabled() is True
    _write(ctl, {"adaptive_realtime": {"adaptive_news_feed_enabled": False}})
    assert a.news_feed_enabled() is False


def test_the_sleeve_flag_follows_the_rule(ctl):
    """config sleeves.research_satellite_enabled vs control sleeves.research_satellite.

    The key NAMES differ between the two files, which is exactly why this one is
    mapped explicitly: a generic block overlay would silently miss it.
    """
    from llm_consensus.config_access import research_satellite_enabled
    _write(ctl, {"sleeves": {"research_satellite": True}})
    assert research_satellite_enabled() is True
    _write(ctl, {"sleeves": {"research_satellite": False}})
    assert research_satellite_enabled() is False


def test_the_haiku_gate_flag_follows_the_rule(ctl):
    """The GUI's base-check toggle was cosmetic on the Python side.

    api_server.set_model("gate", ...) writes gate_enabled to controls.json and
    audits it, and llm_consensus read llm.gate_enabled from config, so the
    council ran the gate no matter what the operator chose.
    """
    from llm_consensus.config_access import gate_enabled
    _write(ctl, {"gate_enabled": False})
    assert gate_enabled() is False       # config defaults it True
    _write(ctl, {"gate_enabled": True})
    assert gate_enabled() is True


def test_the_long_term_flag_follows_the_rule(ctl):
    from discovery import settings
    _write(ctl, {"discovery": {"long_term_sleeve_enabled": True}})
    assert settings.long_term_sleeve_enabled(None) is True


def test_a_pinned_config_ignores_the_control_file(ctl, tmp_path):
    """Tests pin a config, and a local controls.json must not leak into them."""
    import yaml
    from discovery import settings
    _write(ctl, {"discovery": {"discovery_enabled": True}})
    cfg = tmp_path / "pinned.yaml"
    cfg.write_text(yaml.safe_dump({"discovery": {"discovery_enabled": False}}))
    # The control file says ON. The pinned config says OFF. The pin wins.
    assert settings.discovery_enabled(str(cfg)) is False


# --- Root cause 1: the write must be atomic ---------------------------------

def test_a_concurrent_write_never_shows_a_torn_file(ctl):
    """THE LIVE BUG. A reader during a GUI write must never see a partial file.

    With the old truncating writer this failed on ~88 percent of reads: the
    funnel read a half-written file, fell back to config, and reported discovery
    OFF while the file on disk said ON. That is precisely the mismatch the engine
    logged.
    """
    from api_server import controls
    from discovery import settings

    # _write_controls takes its state as an argument and never reads the
    # file, so the only isolation this test needs is the MAL_CONTROL_DIR
    # fixture. Patching read_controls here would be inert and would imply an
    # isolation that is not doing any work.
    state = {"discovery": {"discovery_enabled": True},
             "padding": ["x" * 200] * 200}      # big enough to tear mid-write
    controls._write_controls(dict(state))
    assert settings.discovery_enabled(None) is True

    stop = threading.Event()
    errors: list[str] = []

    def writer():
        while not stop.is_set():
            controls._write_controls(dict(state))

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(400):
            if settings.discovery_enabled(None) is not True:
                errors.append("read discovery OFF while the file said ON")
                break
    finally:
        stop.set()
        t.join(timeout=5)

    assert not errors, errors[0]
    # And the atomic write leaves no temp file behind.
    assert [f for f in os.listdir(ctl) if f.startswith(".controls.")] == []


# --- Root cause 2: the path must not depend on the process's cwd ------------

def test_the_control_dir_is_absolute_so_three_processes_agree(monkeypatch):
    """The engine, the bridge, and the API backend are three processes.

    config ships system.control_dir as the relative ".control". Resolved against
    each process's cwd, a launcher starting one of them elsewhere split them
    silently. An absolute anchor cannot.
    """
    monkeypatch.delenv("MAL_CONTROL_DIR", raising=False)
    # Absolute is the PROPERTY. The trailing name is whatever
    # system.control_dir happens to be set to, and asserting it would fail on
    # a correct system that configured the dir elsewhere.
    d = control_file.control_dir()
    assert os.path.isabs(d), f"control_dir must be absolute, got {d!r}"


def test_the_control_dir_is_the_same_from_any_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("MAL_CONTROL_DIR", raising=False)
    here = control_file.control_dir()
    monkeypatch.chdir(tmp_path)
    assert control_file.control_dir() == here


def test_every_python_reader_resolves_the_same_control_dir(monkeypatch):
    """One rule needs one path. Three copies of it had drifted."""
    monkeypatch.delenv("MAL_CONTROL_DIR", raising=False)
    from api_server import controls
    assert controls._control_dir() == control_file.control_dir()


def test_mal_control_dir_still_overrides(ctl):
    assert control_file.control_dir() == str(ctl)


def test_an_absolute_control_dir_is_honored_as_given(monkeypatch, tmp_path):
    monkeypatch.delenv("MAL_CONTROL_DIR", raising=False)
    from llm_consensus import config_access
    monkeypatch.setattr(config_access, "config_block",
                        lambda name, path=None: {"control_dir": str(tmp_path)}
                        if name == "system" else {})
    assert control_file.control_dir() == str(tmp_path)


# --- No key value, ever -----------------------------------------------------

def test_no_control_read_returns_or_logs_a_key_value(ctl):
    """controls.json holds toggles, never credentials. Assert it stays that way."""
    _write(ctl, {"discovery": {"discovery_enabled": True}})
    body = json.dumps(control_file.control_state())
    for shape in ("sk-", "sk-ant-", "AKIA", "token=", "api_key"):
        assert shape not in body


# --- Regressions found in review of the precedence commit itself -------------
#
# The atomic-write fix reintroduced the SAME silent-fallback bug through two
# different doors, and the strict bool check reintroduced it through a third.
# Every reader falls back to config on any read failure, which is the right
# posture but makes every one of these silent. They are pinned here because a
# silent revert to shipped defaults is exactly what this file exists to prevent.

def test_the_control_file_stays_readable_by_other_users(ctl):
    """tempfile.mkstemp creates 0600. The old open(path, "w") gave 0644.

    The engine, the bridge, and the API backend are three processes that may not
    share a uid. A reader that cannot open the file does not fail loudly, it
    falls back to config and silently acts on the shipped defaults.
    """
    import stat
    from api_server import controls
    controls._write_controls({"discovery": {"discovery_enabled": True}})
    mode = stat.S_IMODE(os.stat(ctl / "controls.json").st_mode)
    assert mode == 0o644, f"controls.json must stay group/world readable, got {oct(mode)}"
    assert mode & stat.S_IROTH, "a reader on another uid must be able to open it"


def test_the_write_leaves_no_temp_file_behind(ctl):
    from api_server import controls
    for _ in range(3):
        controls._write_controls({"discovery": {"discovery_enabled": True}})
    assert [f for f in os.listdir(ctl) if f.startswith(".controls.")] == []


def test_an_integer_boolean_agrees_with_the_cpp_reader(ctl):
    """core/bridge_client.cpp json_get_bool accepts 1/0. Python must too.

    A strict isinstance(v, bool) rejected `1`, fell back to config, and gave the
    engine ON while the funnel read OFF: the exact reported mismatch, through a
    hand-edit instead of a torn read.
    """
    from discovery import settings
    from llm_consensus.config_access import gate_enabled, research_satellite_enabled

    _write(ctl, {"discovery": {"discovery_enabled": 1}, "gate_enabled": 1,
                 "sleeves": {"research_satellite": 1}})
    assert settings.discovery_enabled(None) is True
    assert gate_enabled() is True
    assert research_satellite_enabled() is True

    _write(ctl, {"discovery": {"discovery_enabled": 0}, "gate_enabled": 0,
                 "sleeves": {"research_satellite": 0}})
    assert settings.discovery_enabled(None) is False
    # config ships gate_enabled True, so a control-file 0 has to win.
    assert gate_enabled() is False
    assert research_satellite_enabled() is False


def test_a_malformed_boolean_is_not_guessed_at(ctl):
    """1 and 0 are accepted. A string or a float is NOT.

    Exact parity with the C++ char-sniffing is not the goal past that point (it
    reads "0.5" as false). A value we cannot read means no override, so config
    decides, and config ships every operator flag off. A malformed boolean must
    never be read as an intent to start a spender.
    """
    from llm_consensus import control_file
    for bad in ("yes", "true", 0.5, 2, None, [], {}):
        assert control_file.as_bool(bad, False) is False
        assert control_file.as_bool(bad, True) is True   # falls back, not flips


def test_as_bool_does_not_take_the_int_branch_for_real_bools(ctl):
    """isinstance(True, int) is True in Python, so bool must be checked first."""
    from llm_consensus import control_file
    assert control_file.as_bool(True, False) is True
    assert control_file.as_bool(False, True) is False


def test_a_temp_file_from_a_killed_write_is_swept(ctl):
    """A SIGKILL between mkstemp and os.replace leaves a temp file forever.

    The write's except path only cleans up a FAILED write, not a killed one, and
    these accumulate in the same directory as controls.json and the kill-request
    file across a week-long unattended run.
    """
    from api_server import controls
    orphan = ctl / ".controls.abandoned.tmp"
    orphan.write_text("{}")
    os.utime(orphan, (0, 0))          # backdate it past the stale window
    controls._write_controls({"discovery": {"discovery_enabled": True}})
    assert not orphan.exists(), "a stale temp file should have been swept"


def test_the_sweep_never_touches_a_write_in_flight(ctl):
    """Only files past the stale window are removed.

    A temp file another thread is writing right now is seconds old at most.
    Deleting it would make that thread's os.replace fail and lose its write.
    """
    from api_server import controls
    live = ctl / ".controls.inflight.tmp"
    live.write_text("{}")             # fresh: another thread is mid-write
    controls._write_controls({"discovery": {"discovery_enabled": True}})
    assert live.exists(), "a fresh temp file must never be swept"


def test_the_suite_cannot_read_the_hosts_live_control_file():
    """Test isolation, asserted. The fix for the CLASS, not for three instances.

    controls.json is the runtime override that WINS over config, so any test
    resolving a flag through the runtime path reads whatever THIS machine's
    operator last toggled. Three tests asserting a SHIPPED default went red the
    moment a real operator enabled a layer, each was fixed by hand, and the rest
    were missed. conftest.py now points MAL_CONTROL_DIR at an empty temp dir for
    the whole suite, the same way it already isolates the credential keystore.

    This pins that isolation, so removing it fails here rather than surfacing as
    a mystery red suite on someone's machine months later.
    """
    import os
    d = os.environ.get("MAL_CONTROL_DIR")
    assert d, "conftest must isolate MAL_CONTROL_DIR for the whole suite"
    assert "mal_test_controls_" in d, f"not the suite's temp control dir: {d}"
    # And it is really empty, so every reader falls back to config.
    assert not os.path.exists(os.path.join(d, "controls.json"))
    assert control_file.control_state() == {}

    # Which means the runtime path and the shipped path AGREE, which is what
    # made the three hand-fixed tests fragile in the first place.
    from discovery import settings
    assert settings.discovery_enabled(None) is False
    assert settings.long_term_sleeve_enabled(None) is False
