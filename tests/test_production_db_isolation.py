"""No test reads or writes the operator's production database.

THE HISTORY THIS CLOSES. On 2026-07-24 the watchdog gained event journaling,
and repeated pytest runs during that development wrote 108 watchdog_restart
rows into the production journal between 07:15:20Z and 07:28:20Z, in bursts of
13 to 18 within a single second. The session that noticed added an autouse
MAL_DB_PATH fixture to three modules and recorded "four spurious events"; the
true count was 108, and every one of them predates the fixture commit
(2026-07-24T07:50:13Z). Two days earlier the same class had hit
test_control_precedence, journaling control_change events into production on
every run.

Per-module fixtures fix the modules someone remembers. A guard kills the class.
The isolation is now global (conftest points MAL_DB_PATH at a session temp
database) and the guard is ACTIVE (sqlite3.connect refuses the production path
outright), so a module with a hardcoded default, a cwd-relative resolution, or
a path the env never reached fails loudly in the test that did it.

The 108 rows are LEFT IN PLACE. The events table is an append-only audit
journal, and deleting from it to tidy a record is the mistake the SOL/USD
postmortem documents. They are documented in PROGRESS.md instead.
"""
from __future__ import annotations

import os
import pathlib
import sqlite3

import pytest

import conftest


@pytest.fixture(autouse=True)
def _drop_deliberate_violations():
    """Every test in THIS module trips the guard on purpose. Clear what they
    record so the session-end hook only ever sees a real leak."""
    before = len(conftest.PRODUCTION_DB_VIOLATIONS)
    yield
    del conftest.PRODUCTION_DB_VIOLATIONS[before:]


def test_the_session_database_is_not_the_production_database():
    """Every module resolving the DB through the env lands in a temp file."""
    resolved = os.environ["MAL_DB_PATH"]
    assert resolved != conftest._PRODUCTION_DB
    assert "mal_test_db_" in resolved

    from ml_factor import factor
    from ops import watchdog
    from rl_advisory import service
    for path in (watchdog._db_path(), factor._default_db_path(),
                 service._db_path()):
        assert path != conftest._PRODUCTION_DB, path


@pytest.mark.parametrize("target", [
    conftest._PRODUCTION_DB,                      # absolute
    "market_ai_lab.db",                           # cwd-relative, the leak shape
    "./market_ai_lab.db",
    f"file:{conftest._PRODUCTION_DB}?mode=ro",    # the read-only URI form
    f"file:{conftest._PRODUCTION_DB}",
])
def test_the_guard_refuses_the_production_path_in_every_shape(target,
                                                              monkeypatch):
    """The bare relative default resolved against a repo-root cwd is exactly
    how ops.watchdog reached production, so it must be refused as such."""
    monkeypatch.chdir(conftest._ROOT)
    with pytest.raises(conftest.ProductionDatabaseAccess):
        sqlite3.connect(target)


def test_the_guard_refuses_a_pathlib_target(monkeypatch):
    monkeypatch.chdir(conftest._ROOT)
    with pytest.raises(conftest.ProductionDatabaseAccess):
        sqlite3.connect(pathlib.Path(conftest._PRODUCTION_DB))


def test_the_guard_allows_everything_that_is_not_production(tmp_path):
    """A guard that blocked ordinary test databases would be useless."""
    for target in (":memory:", str(tmp_path / "own.db"),
                   f"file:{tmp_path / 'uri.db'}?mode=rwc"):
        conn = sqlite3.connect(target, uri=str(target).startswith("file:"))
        conn.execute("CREATE TABLE IF NOT EXISTS t (a INTEGER)")
        conn.close()
    # A same-named database in another directory is a different file.
    other = tmp_path / "market_ai_lab.db"
    sqlite3.connect(str(other)).close()
    assert other.exists()


def test_a_relative_path_from_another_directory_is_not_production(tmp_path,
                                                                  monkeypatch):
    """The guard resolves against the cwd exactly as sqlite does, so a test
    that chdirs to tmp_path may use the same bare filename."""
    monkeypatch.chdir(tmp_path)
    sqlite3.connect("market_ai_lab.db").close()
    assert (tmp_path / "market_ai_lab.db").exists()


def test_the_guard_raises_baseexception_so_a_swallowing_caller_cannot_hide_it():
    """THE point of the guard, and it was measured the hard way.

    The leaking call sites are wrapped in ``except Exception: pass`` by
    design: the watchdog's journaling says so in a comment ("journaling must
    never break remediation"), and so does controls._audit. The first version
    of this guard raised RuntimeError. It blocked every production write in
    the suite and the suite reported 917 passed, because every leak was
    swallowed. BaseException propagates through those handlers.
    """
    assert issubclass(conftest.ProductionDatabaseAccess, BaseException)
    assert not issubclass(conftest.ProductionDatabaseAccess, Exception)

    swallowed = False
    try:
        try:
            sqlite3.connect(conftest._PRODUCTION_DB)
        except Exception:  # noqa: BLE001 - reproducing the real call sites
            swallowed = True
    except conftest.ProductionDatabaseAccess:
        pass
    assert not swallowed, "a plain `except Exception` caught the guard"


def test_every_refused_open_is_recorded_with_the_test_that_made_it(
        monkeypatch):
    """Belt and braces: even a handler catching BaseException cannot hide a
    violation, because the session-end hook reads the recorded list."""
    before = len(conftest.PRODUCTION_DB_VIOLATIONS)
    monkeypatch.chdir(conftest._ROOT)
    try:
        sqlite3.connect("market_ai_lab.db")
    except BaseException:  # noqa: BLE001 - the worst-case swallowing caller
        pass
    recorded = conftest.PRODUCTION_DB_VIOLATIONS[before:]
    assert len(recorded) == 1
    assert "test_every_refused_open_is_recorded" in recorded[0]
