"""THE one reader for the operator's runtime control file, controls.json.

THE PRECEDENCE RULE, for both halves of the system:

    controls.json (the operator's runtime override) WINS over
    config/default_config.yaml (the shipped default).

Config says what the system ships with. controls.json says what the operator
decided. Any flag the GUI can toggle MUST be read through this precedence on
BOTH sides, or one half acts on a value the other half never sees. The C++ side
does the same thing in core/layer_toggles.hpp, core/discovery_controls.hpp,
core/adaptive_controls.hpp, core/sleeve_controls.hpp, and
core/operator_controls.hpp: seed from config, then let controls.json override.

WHY THIS MODULE EXISTS. Three separate copies of this resolution had drifted
(api_server/controls.py, discovery/settings.py, adaptive/settings.py), and all
three shared one bug: a RELATIVE control_dir from config (it ships ".control")
was resolved against each process's CURRENT WORKING DIRECTORY. The engine, the
bridge, and the API backend are three processes. They agreed only by the accident
of all being launched from the repo root, and a launcher that started one of them
elsewhere made that half read a control file that was not there, fall back to
config, and silently act on the shipped default. Measured: the same call returns
discovery ON from the repo root and OFF from /tmp.

So a relative control_dir resolves against the REPO ROOT here, an absolute anchor
every process agrees on regardless of where it was started. MAL_CONTROL_DIR still
overrides, and an absolute control_dir is honored as given.

READ POSTURE. A missing, empty, or unreadable control file means NO OVERRIDE, so
the caller falls back to config, which ships every operator flag off. That is the
safe direction: an unreadable file must never start a spender. It is also why the
WRITER must be atomic (see api_server/controls._write_controls): a torn read is
indistinguishable from "no override" here, so a non-atomic write silently
reported the shipped default to whichever half read at the wrong moment.

NOT CACHED, deliberately. The funnel, the engine, and the GUI are separate
processes, so a cached value would keep a layer running after the operator turned
it off. Reading a small local JSON file per call is cheap. Being wrong about
whether a spender is enabled is not.
"""
from __future__ import annotations

import json
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def control_dir() -> str:
    """Where the operator control files live, as an ABSOLUTE path.

    Resolution order, matching the engine and the API backend:
      1. env MAL_CONTROL_DIR (explicit operator override, honored as given)
      2. config system.control_dir, resolved against the repo root when relative
      3. <repo root>/.control
    """
    env = os.environ.get("MAL_CONTROL_DIR")
    if env:
        return env
    configured = ""
    try:
        # Imported lazily so this module has no import-time dependency on the
        # config layer, which lets config_access import it without a cycle.
        from llm_consensus.config_access import config_block
        configured = str((config_block("system", None) or {}).get(
            "control_dir") or "")
    except Exception:  # noqa: BLE001 — config is not load-bearing for a path
        configured = ""
    d = configured or ".control"
    # THE FIX: anchor a relative dir to the repo root, not to os.getcwd(). Three
    # processes read this file, and only an absolute anchor makes them agree.
    return d if os.path.isabs(d) else os.path.join(_REPO_ROOT, d)


def control_path() -> str:
    return os.path.join(control_dir(), "controls.json")


def control_state() -> dict:
    """The whole control file, {} when absent, empty, or unreadable.

    {} means "no override": every caller then falls back to config. Never raises:
    a control file is not load-bearing, and a broken one must degrade to the
    shipped default rather than take a process down.
    """
    try:
        with open(control_path()) as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def control_block(name: str) -> dict:
    """One nested block of the control file ("discovery", "sleeves", ...), {} if
    absent. The block layout mirrors the config block of the same name, which is
    what lets a caller overlay one onto the other."""
    block = control_state().get(name)
    return block if isinstance(block, dict) else {}


def overlay(cfg: dict, block_name: str, cfg_path: str | None = None) -> dict:
    """Config with the operator's control block layered over it.

    THE precedence, in one place: controls.json wins where it carries a key, else
    config. An explicit cfg_path means the caller is PINNING a config (the tests
    do this), so the control file is ignored entirely. Without that, a
    developer's local controls.json would leak into a test that thought it had
    set every value it cared about.
    """
    if cfg_path is not None:
        return cfg
    return {**cfg, **control_block(block_name)}


def as_bool(v: object, default: bool) -> bool:
    """Coerce a control-file value to a bool the way the C++ reader does.

    THE TWO HALVES MUST AGREE ON WHAT A BOOLEAN IS, or this module's whole
    purpose fails at the last step. core/bridge_client.cpp json_get_bool accepts
    `true`/`false` AND the bare integers `1`/`0`:

        if (json[*p] == '1') return true;
        if (json[*p] == '0') return false;

    A strict isinstance(v, bool) here rejected `1`, fell back to config, and
    reproduced the exact mismatch this file exists to prevent: a hand-edited
    {"discovery_enabled": 1} read ON in the engine and OFF in the Python funnel.
    So 1 and 0 are accepted here too. isinstance(True, int) is True in Python, so
    the bool check must come first or every bool would take the int branch.

    Anything else (a string, a float, null, a typo) is NOT guessed at: it means
    "no override" and the caller falls back to config, which ships every operator
    flag off. Exact parity with the C++ char-sniffing is neither achievable nor
    desirable past this point (it reads "0.5" as false), and a malformed boolean
    must never be read as an intent to start a spender.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    return default


def flag(key: str, default: bool) -> bool:
    """A TOP-LEVEL control-file boolean (gate_enabled, rl_enabled, ...), falling
    back to `default`, which the caller reads from config. Distinct from
    control_block: these keys sit at the root of controls.json rather than in a
    block, because that is the shape the GUI writes and the C++ flat reader
    expects."""
    return as_bool(control_state().get(key), default)


def block_flag(block: str, key: str, default: bool) -> bool:
    """A boolean nested inside a control block, for the flags whose key NAME
    differs between config and the control file (config
    sleeves.research_satellite_enabled vs control sleeves.research_satellite),
    which is why they cannot be block-overlaid."""
    return as_bool(control_block(block).get(key), default)
