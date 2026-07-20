"""The keystore handle leak that exhausted the bridge's file descriptors.

2026-07-19 root cause: every credential resolution opened a NEW sqlite3
connection to .keystore/credentials.sqlite and never closed it. `with conn:`
is a transaction scope, not a close, and on Python 3.14 each connection ends
up in cycle garbage that refcounting never frees, so a mostly idle bridge
accumulated 1018 open keystore handles in 20 hours (1023 of 1024 fds) and
lost the ability to open any new file or socket: the silent feed
substitutions and the engine-reads-ON funnel-reads-OFF condition.

These tests hold the fix by MEASURING fds, not by inspecting code: resolving
a credential a thousand times must not grow the process fd count. Against
the pre-fix resolver the plain loop grew 397 fds and the source loop 1000,
so every one of these failed before the fix. A lexical guard test pins the
`with sqlite3.connect(` idiom out of runtime code so the class cannot return
quietly elsewhere.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(
    not os.path.isdir("/proc/self/fd"),
    reason="fd counting needs /proc (Linux)")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fds() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.fixture
def creds(tmp_path, monkeypatch):
    """A fresh credentials module against an isolated keystore, same pattern
    as test_credentials: reimport so module-level paths pick up the dir."""
    monkeypatch.setenv("MAL_KEYSTORE_DIR", str(tmp_path / "keystore"))
    sys.modules.pop("account_manager.credentials", None)
    mod = importlib.import_module("account_manager.credentials")
    mod = importlib.reload(mod)
    yield mod
    mod.close_store()


# --- Task 2: the leak is closed, measured in fds -----------------------------

def test_resolving_a_credential_1000_times_does_not_grow_fds(creds):
    creds.set_credential("finnhub_key", "fd-leak-probe")
    creds.get_credential("finnhub_key")  # warm lazy imports and the store
    before = _fds()
    for _ in range(1000):
        assert creds.get_credential("finnhub_key") == "fd-leak-probe"
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 1000 resolutions"


def test_resolve_env_1000_times_does_not_grow_fds(creds):
    creds.set_credential("anthropic_key", "fd-leak-probe")
    creds.resolve_env("ANTHROPIC_API_KEY")
    before = _fds()
    for _ in range(1000):
        assert creds.resolve_env("ANTHROPIC_API_KEY") == "fd-leak-probe"
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 1000 resolutions"


def test_credential_source_1000_times_does_not_grow_fds(creds):
    # The worst pre-fix path: get_credential_source leaked exactly one fd per
    # call (1000 of 1000 in the pre-fix measurement).
    creds.set_credential("finnhub_key", "fd-leak-probe")
    creds.get_credential_source("finnhub_key")
    before = _fds()
    for _ in range(1000):
        assert creds.get_credential_source("finnhub_key") == "in-app"
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 1000 source lookups"


def test_missing_credential_resolution_does_not_grow_fds(creds):
    # The bridge's real cadence resolves keys that are often ABSENT (env-only
    # deployments), and the absent path also opened the store per call.
    creds.get_credential("openai_key")
    before = _fds()
    for _ in range(1000):
        assert creds.get_credential("openai_key") is None
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 1000 misses"


def test_write_paths_do_not_grow_fds(creds):
    creds.set_credential("whale_alert_key", "seed")
    before = _fds()
    for i in range(200):
        creds.set_credential("whale_alert_key", f"v{i}")
        creds.delete_credential("whale_alert_key")
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 200 write cycles"


# --- The long-lived connection behaves ---------------------------------------

def test_store_reconnects_when_the_path_is_repointed(creds, tmp_path,
                                                     monkeypatch):
    # test_api_server repoints _STORE_PATH per test; the cached connection
    # must follow the path, not pin the first store it opened.
    creds.set_credential("finnhub_key", "store-a")
    other = tmp_path / "keystore-b"
    monkeypatch.setattr(creds, "KEYSTORE_DIR", str(other))
    monkeypatch.setattr(creds, "_KEY_PATH", str(other / "secret.key"))
    monkeypatch.setattr(creds, "_STORE_PATH", str(other / "credentials.sqlite"))
    assert creds.get_credential("finnhub_key") is None  # empty store B
    creds.set_credential("finnhub_key", "store-b")
    assert creds.get_credential("finnhub_key") == "store-b"


def test_close_store_reopens_on_next_use(creds):
    creds.set_credential("finnhub_key", "still-there")
    creds.close_store()
    assert creds.get_credential("finnhub_key") == "still-there"


def test_concurrent_resolution_is_safe_and_leak_free(creds):
    # The bridge is a ThreadingHTTPServer: resolutions race across request
    # threads. The shared connection is serialized under the store lock, so
    # concurrent use must neither raise nor leak.
    creds.set_credential("finnhub_key", "fd-leak-probe")
    creds.get_credential("finnhub_key")
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(200):
                assert creds.get_credential("finnhub_key") == "fd-leak-probe"
        except BaseException as e:  # noqa: BLE001 - collected for the assert
            errors.append(e)

    before = _fds()
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    grown = _fds() - before
    assert not errors
    assert grown <= 2, f"fd count grew by {grown} under concurrent resolution"


def test_a_broken_connection_is_dropped_and_reopened(creds):
    # A sqlite error must not leave a permanently broken cached handle. The
    # call that hits the broken connection fails closed (None, the missing
    # direction), the store drops the handle, and the NEXT call reconnects.
    creds.set_credential("finnhub_key", "survives")
    creds.close_store()
    with creds._store() as conn:
        pass
    conn.close()  # sabotage: close the cached connection behind the store
    creds.get_credential("finnhub_key")  # hits the broken handle, drops it
    assert creds.get_credential("finnhub_key") == "survives"


# --- The other audited leak sites, measured ----------------------------------

def _seed_events_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE events (ts TEXT, kind TEXT, venue TEXT, symbol TEXT,"
            " severity TEXT, message TEXT, payload_json TEXT)")
        conn.execute(
            "INSERT INTO events VALUES('2026-07-19T00:00:00Z','unit','x','y',"
            "'info','seed',NULL)")
        conn.commit()


def test_api_server_store_query_does_not_grow_fds(tmp_path, monkeypatch):
    db = str(tmp_path / "ops.db")
    _seed_events_db(db)
    monkeypatch.setenv("MAL_DB_PATH", db)
    from api_server import store
    store.query("SELECT COUNT(*) AS n FROM events")
    before = _fds()
    for _ in range(300):
        assert store.query("SELECT COUNT(*) AS n FROM events")
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 300 backend queries"


def test_api_server_append_event_does_not_grow_fds(tmp_path, monkeypatch):
    db = str(tmp_path / "ops.db")
    _seed_events_db(db)
    monkeypatch.setenv("MAL_DB_PATH", db)
    from api_server import store
    store.append_event("unit", "warm")
    before = _fds()
    for i in range(300):
        assert store.append_event("unit", f"m{i}")
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 300 event appends"


def test_ui_db_query_does_not_grow_fds(tmp_path, monkeypatch):
    db = str(tmp_path / "ops.db")
    _seed_events_db(db)
    from ui import db as ui_db
    monkeypatch.setattr(ui_db, "DB_PATH", db)
    ui_db.query("SELECT COUNT(*) AS n FROM events")
    before = _fds()
    for _ in range(300):
        assert not ui_db.query("SELECT COUNT(*) AS n FROM events").empty
    grown = _fds() - before
    assert grown <= 2, f"fd count grew by {grown} over 300 dashboard queries"


# --- Reintroduction guard ----------------------------------------------------

def test_no_runtime_code_uses_with_sqlite_connect(tmp_path):
    """`with sqlite3.connect(...)` commits but never closes: it is the exact
    idiom behind the 2026-07-19 exhaustion. Runtime code must close every
    connection (contextlib.closing, an explicit finally, or the keystore's
    managed long-lived connection), so the bare idiom is pinned out of every
    non-test module."""
    offenders = []
    for root, dirs, files in os.walk(_REPO_ROOT):
        dirs[:] = [d for d in dirs
                   if d not in (".git", ".venv", "node_modules", "tests",
                                "__pycache__", "web", "electron-app")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "with sqlite3.connect(" in line \
                            and "closing(" not in line:
                        rel = os.path.relpath(path, _REPO_ROOT)
                        offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "unclosed `with sqlite3.connect(` idiom in runtime code: "
        + ", ".join(offenders))
