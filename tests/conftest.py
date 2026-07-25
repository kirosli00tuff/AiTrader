"""Pytest config — make repo-root packages importable, and keep the suite
hermetic against the host credential keystore."""
import atexit
import os
import shutil
import sqlite3
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Point the credential keystore at an EMPTY temp dir before any test imports
# account_manager.credentials (its KEYSTORE_DIR is read once at import time).
# Keystore-first resolution then finds no real key, so the LLM providers and the
# base-check gate fall back to their labelled offline mocks unless a test sets an
# env var explicitly. Without this, a populated host keystore makes offline tests
# issue real API calls (non-deterministic, network-dependent). Tests that need
# their own keystore (e.g. test_credentials) override MAL_KEYSTORE_DIR per test.
os.environ["MAL_KEYSTORE_DIR"] = tempfile.mkdtemp(prefix="mal_test_keystore_")

# Point the operator control file at an EMPTY temp dir, for the same reason and
# with the same shape. controls.json is the runtime override that WINS over
# config, so a test resolving a flag through the runtime path (cfg_path=None)
# reads whatever THIS machine's operator last toggled. Tests asserting a SHIPPED
# default then go red the moment a real operator enables a layer, reporting a
# regression that never happened.
#
# That shipped three times before this line existed (test_discovery_funnel,
# test_discovery_whale, test_long_term_sleeve), and each was fixed by hand while
# the rest were missed. An empty control dir kills the CLASS: no test can read
# the host's live toggles, so the runtime path and the shipped path agree and a
# shipped-default assertion is right either way. Tests that need their own
# control file set MAL_CONTROL_DIR per test, exactly as the keystore tests do.
os.environ["MAL_CONTROL_DIR"] = tempfile.mkdtemp(prefix="mal_test_controls_")

# Pin the whale feed flags OFF for the suite. These resolve env > controls.json >
# config, and the SHIPPED config turns SEC EDGAR on, so without this a test that
# calls GET /health/integrations makes a REAL request to efts.sec.gov: slow,
# flaky, network-dependent, and rude to SEC's fair-use limit. The env is the
# highest-precedence override, so setting it here pins every feed off no matter
# what the host config or control file say.
#
# Same reasoning as the keystore and control dir above: a test must never depend
# on this machine's configuration. A test that wants a feed ON deletes the var it
# cares about and patches the config it wants, which keeps the intent local and
# visible in the test.
for _flag in ("SEC_EDGAR_ENABLED", "WHALE_LIVE_ENABLED", "WHALE_ALERT_ENABLED"):
    os.environ[_flag] = "false"

# Point the evidence records (ops/evidence.py) at a temp dir, same shape as the
# keystore and control dir above. Several code paths capture diagnostics as a
# side effect (a watchdog cycle, a layer toggle, a flag mismatch), and a test
# exercising them must not write records into the repo's diagnostics/ dir.
os.environ["MAL_DIAGNOSTICS_DIR"] = tempfile.mkdtemp(prefix="mal_test_diag_")

# Point the runtime dir (pid file, engine lock, watchdog loop-guard state) at a
# temp dir, same shape again. The watchdog persists its remediation state under
# run_dir, and a test cycle must never write it into the repo's .run or read a
# real run's restarts as its own. Tests needing a private run dir still set
# MAL_RUN_DIR per test, which overrides this.
os.environ["MAL_RUN_DIR"] = tempfile.mkdtemp(prefix="mal_test_run_")

# --- NO TEST READS OR WRITES THE PRODUCTION DATABASE (2026-07-25) ------------
#
# Two mechanisms, because the per-module fixture approach demonstrably leaks.
# The 2026-07-24 session added an autouse MAL_DB_PATH fixture to the three
# watchdog modules after four spurious watchdog_restart events reached
# production, and 108 of them are in the journal anyway: a fixture fixes the
# modules someone remembered, and the class re-opens the moment a new module
# calls a journaling path. So the isolation is now global and the guard is
# active rather than advisory.
#
# 1. MAL_DB_PATH points at a temp database for the WHOLE session. Every module
#    that resolves the operational database through the env (ops.watchdog,
#    api_server.store, rl_advisory.service, adaptive.run, ml_factor) lands
#    there instead of production, with no per-module fixture to remember.
#    Tests that need their own database still set MAL_DB_PATH per test, and
#    the several that delenv it to assert the repo-anchored DEFAULT still
#    resolve that default, because they only inspect the path.
#
# 2. sqlite3.connect REFUSES the production path outright. That is what makes
#    it a guard instead of a convention: a module with a hardcoded default, a
#    cwd-relative resolution, or a path the env never reached fails LOUDLY, in
#    the test that did it, naming the file. Reads are refused alongside writes:
#    a test reading the operator's live database is not hermetic either, and
#    its result silently depends on this machine.
_PRODUCTION_DB = os.path.join(_ROOT, "market_ai_lab.db")

os.environ["MAL_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="mal_test_db_"), "isolated.db")


class ProductionDatabaseAccess(BaseException):
    """A test opened the operator's production database.

    BaseException, NOT Exception, and the distinction is the whole guard. The
    call sites that leak are precisely the ones wrapped in ``except
    Exception: pass`` — the watchdog's journaling says so in a comment
    ("journaling must never break remediation"), and so do controls._audit and
    every advisory-layer writer. A guard raising Exception is caught by the
    swallow, the write is blocked, and the test passes green with nobody told.
    Measured: the first version of this guard raised RuntimeError, blocked
    every production write in the suite, and reported 917 passed.

    Violations are ALSO recorded below, so a handler catching BaseException
    still cannot hide one.
    """


def _resolves_to_production(database) -> bool:
    """Whether a sqlite3.connect target names the production database.

    Handles every shape the codebase passes: an absolute path, a cwd-relative
    path (which is how the leak happened, the bare default "market_ai_lab.db"
    resolved against a repo-root cwd), a pathlib.Path, and a file: URI with
    query parameters (the evidence renderer's read-only open). ":memory:" and
    an integer fd are not paths and pass through.
    """
    if isinstance(database, int):
        return False
    try:
        text = os.fspath(database)
    except TypeError:
        return False
    if isinstance(text, bytes):
        text = text.decode()
    if text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
    if not text or text == ":memory:":
        return False
    return (os.path.realpath(os.path.abspath(text))
            == os.path.realpath(_PRODUCTION_DB))


_real_sqlite_connect = sqlite3.connect

# Every refused open, with the test that made it. Written even when the raise
# is caught, so a swallowing handler still cannot hide a violation.
PRODUCTION_DB_VIOLATIONS: list[str] = []


def _guarded_connect(database=":memory:", *args, **kwargs):
    if _resolves_to_production(database):
        where = os.environ.get("PYTEST_CURRENT_TEST", "<outside a test>")
        PRODUCTION_DB_VIOLATIONS.append(where)
        raise ProductionDatabaseAccess(
            f"{where} opened the production database ({_PRODUCTION_DB}). "
            "Point the code under test at a tmp_path database, or set "
            "MAL_DB_PATH for this test. Production is the operator's live "
            "journal and no test may read or write it.")
    return _real_sqlite_connect(database, *args, **kwargs)


sqlite3.connect = _guarded_connect


# Belt and braces for what the connect guard cannot see: a subprocess with its
# own interpreter (the mal_engine tests) writes through its own sqlite. The
# file's size and mtime are recorded at session start and checked at the end,
# so a subprocess touching production fails the RUN even though it cannot fail
# an individual test.
def _production_fingerprint():
    try:
        st = os.stat(_PRODUCTION_DB)
        return (st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        return None


_PRODUCTION_FINGERPRINT_AT_START = _production_fingerprint()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook
    """Fail the RUN on any production access, however it was handled.

    Two independent conditions. The recorded violations catch an open a
    handler swallowed; the fingerprint catches a subprocess with its own
    interpreter, which the connect guard cannot see at all.
    """
    problems = []
    if PRODUCTION_DB_VIOLATIONS:
        seen = sorted(set(PRODUCTION_DB_VIOLATIONS))
        problems.append(
            f"{len(PRODUCTION_DB_VIOLATIONS)} refused open(s) of the "
            f"production database from {len(seen)} test(s):\n  "
            + "\n  ".join(seen))
    after = _production_fingerprint()
    if after != _PRODUCTION_FINGERPRINT_AT_START:
        problems.append(
            f"the production database file changed during the run: "
            f"{_PRODUCTION_FINGERPRINT_AT_START} -> {after}. A subprocess "
            "under test wrote to the operator's live journal.")
    if problems:
        session.exitstatus = 1
        raise ProductionDatabaseAccess(
            f"production database ({_PRODUCTION_DB}) was accessed by the "
            "test suite.\n" + "\n".join(problems))


# The temp dirs above are process-scoped, so remove them when the run ends
# rather than leaving one of each per invocation under /tmp forever.
@atexit.register
def _cleanup_test_dirs() -> None:
    for var in ("MAL_KEYSTORE_DIR", "MAL_CONTROL_DIR", "MAL_DIAGNOSTICS_DIR",
                "MAL_RUN_DIR"):
        path = os.environ.get(var, "")
        if "mal_test_" in path:
            shutil.rmtree(path, ignore_errors=True)
    shutil.rmtree(os.path.dirname(os.environ.get("MAL_DB_PATH", "")),
                  ignore_errors=True)
