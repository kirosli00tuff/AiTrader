"""The synthetic-database marker (STAGE C.1 Task 1; Amendment 9.15).

A database counts as SYNTHETIC only when it proves it: the SQLite header's
application_id carries SYNTHETIC_APPLICATION_ID, the meta table names this
package as the generator, and the stored fingerprint equals the one
recomputed from the news_observation DDL and its row count. A copy of the
real database carries none of these, so no file name, link or copy can pass
it off as a fixture. A synthetic database edited after it was built fails the
fingerprint and stops counting as synthetic.

`is_synthetic` reads the header first and touches no table unless the
application_id already matches, so calling it on a copy of the real database
reads no row.
"""
from __future__ import annotations

import hashlib
import sqlite3

SYNTHETIC_APPLICATION_ID = 0x4E455653  # ASCII "NEVS"
META_TABLE = "news_eval_synthetic_meta"
GENERATOR = "news_eval.synthetic"


def fingerprint(conn: sqlite3.Connection) -> str:
    """sha256 of the stored news_observation DDL, a newline, and its row count."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='news_observation'").fetchone()
    if row is None or row[0] is None:
        raise ValueError("no news_observation table")
    count = conn.execute("SELECT COUNT(*) FROM news_observation").fetchone()[0]
    return hashlib.sha256(f"{row[0]}\n{count}".encode()).hexdigest()


def write_marker(conn: sqlite3.Connection, scenario: str, seed: int) -> None:
    """Stamp a freshly built synthetic database. Call after the last row."""
    stamp = fingerprint(conn)
    conn.execute(f"PRAGMA application_id = {SYNTHETIC_APPLICATION_ID}")
    conn.execute(f"CREATE TABLE {META_TABLE} "
                 "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.executemany(
        f"INSERT INTO {META_TABLE} (key, value) VALUES (?, ?)",
        [("generator", GENERATOR), ("scenario", scenario),
         ("seed", str(seed)), ("fingerprint", stamp)])
    conn.commit()


def is_synthetic(conn: sqlite3.Connection) -> bool:
    """True only for an unmodified database built by news_eval.synthetic."""
    if conn.execute("PRAGMA application_id").fetchone()[0] \
            != SYNTHETIC_APPLICATION_ID:
        return False
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name=?", (META_TABLE,)).fetchone() is None:
        return False
    meta = dict(conn.execute(f"SELECT key, value FROM {META_TABLE}"))
    if meta.get("generator") != GENERATOR:
        return False
    try:
        return meta.get("fingerprint") == fingerprint(conn)
    except ValueError:
        return False
