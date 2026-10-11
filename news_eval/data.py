"""The guarded loader for news_observation (STAGE C.1 Task 1; Amendment 9.7, 9.8, 9.13, 9.15).

Every read of a news_observation database in news_eval/ goes through one of
five named phases. Each phase holds a FIXED column allow-list and builds its
queries only from that list: no method takes free SQL, identifiers come only
from the allow-list, and every value is bound as a parameter. A column outside
the list raises ColumnRefused before any query runs. A second, engine-level
guard (sqlite3 set_authorizer) denies any read of a column outside the phase's
readable set and every non-SELECT action, so a builder bug cannot widen a read.

Database classification, in this order (STAGE C.1 GUARDRAILS, Task 1):
  1. LIVE_REAL: os.path.realpath of the path equals the realpath of a live
     path, or its (st_dev, st_ino) equals that file's. The live paths are
     COMPILED_REAL_DB_PATH (the repository's news_experiment.db) ALWAYS, plus
     the real_db_path override or REAL_DB_PATH when it names another file: an
     override or a monkeypatch adds a second live path and never removes the
     compiled one (C.1 lead ruling B3). Checked with os.stat only, never by
     opening the file, so symlinks and hard links are caught before
     sqlite3.connect is ever called.
  2. SYNTHETIC: no -wal, -shm or -journal file sits beside it (SidecarPresent
     otherwise, before any open; ruling B1), the file opens read-only and
     immutable (file:<path>?mode=ro&immutable=1, so SQLite neither reads nor
     creates a sidecar) and marker.is_synthetic(conn) is True
     (application_id, generator, and a DDL-plus-row-count fingerprint;
     Amendment 9.15).
  3. NON_SYNTHETIC: everything else. C.2's snapshot copy (9.7) and any copy of
     the real database under another name land here: no marker, so the
     fingerprint fails. Opened the same way as step 2.
The live file alone keeps plain file:<path>?mode=ro: the collector may hold
a legitimate WAL there.

Phase matrix (refusals raise a LoaderRefusal subclass; real-path refusals
happen before sqlite3.connect):

  phase      | LIVE_REAL            | SYNTHETIC      | NON_SYNTHETIC
  -----------+----------------------+----------------+-------------------------
  SYNTHETIC  | RealDatabaseRefused  | allowed        | NotSyntheticRefused
  SCHEMA     | PRAGMA table_info    | PhaseRefused   | PhaseRefused
  RELEVANCE  | six columns (9.13)   | six columns    | NotSyntheticRefused
  GATE       | RealDatabaseRefused  | allowed        | needs a valid unlock
  VERDICT    | RealDatabaseRefused  | allowed        | needs a valid unlock
             |                      |                | and the run-once marker
             |                      |                | for this file's sha256

A valid unlock (ruling B2; load_unlock) is reports/c2_UNLOCK.json parsed as
a JSON object with schema constants.UNLOCK_SCHEMA, stage "C.2", a non-empty
approver, utc_time in ISO 8601 ending Z, and experiment_sha256 equal to the
sha256 of EXPERIMENT.md on disk; a missing file is UnlockMissing, a bad field
UnlockInvalid naming it. (manifest_sha256 is bound by news_eval.gate and
news_eval.run_c2, which verify the manifest.) The run-once marker
(check_run_once) must parse with schema constants.RUN_ONCE_SCHEMA and a
snapshot_sha256 equal to the sha256 of the file VERDICT opens, hashed after
the sidecar check and before sqlite3.connect.

GATE and VERDICT never read the live database: C.2 reads only the snapshot
copy (9.7), so the live file is refused even when the unlock file exists. The
GATE allow-list is what 9.8 needs and nothing more; its single named
exception, directional_counts_by_cluster, returns counts by scoring_session
and never a row (9.8 k_eff). The SCHEMA phase is the C.1 guardrail read 2 and
the RELEVANCE phase is guardrail read 3 (9.13).

Test mode (ruling S5) is NEWS_EVAL_TEST_MODE=1 in the environment
(is_test_mode). Only test mode accepts the path override flags of the
gate, run_c2 and relevance CLIs; the keyword overrides of this module stay,
held by B2 and B3.
"""
from __future__ import annotations

import argparse
import enum
import hashlib
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from news_eval import constants as K
from news_eval import marker

REPO_ROOT = Path(__file__).resolve().parent.parent
# The registered locations (C.1 lead ruling B3). COMPILED_REAL_DB_PATH is the
# repository's live database and is ALWAYS live to is_live_real (through the
# private copy below, which no override replaces). The COMPILED_* paths are
# also the only values run_c2's config accepts outside test mode (ruling S5).
COMPILED_REAL_DB_PATH = str(REPO_ROOT / "news_experiment.db")
COMPILED_UNLOCK_PATH = str(REPO_ROOT / "reports" / "c2_UNLOCK.json")
COMPILED_RUN_ONCE_PATH = str(REPO_ROOT / "reports" / "c2_RUN_ONCE.json")
_ALWAYS_LIVE = COMPILED_REAL_DB_PATH
# The unlock file's experiment_sha256 is checked against this file (B2).
EXPERIMENT_MD_PATH = str(REPO_ROOT / "EXPERIMENT.md")
# Module-level settings, read at call time so tests can point them elsewhere.
# REAL_DB_PATH adds a live path; it never removes COMPILED_REAL_DB_PATH (B3).
REAL_DB_PATH = COMPILED_REAL_DB_PATH
UNLOCK_PATH = COMPILED_UNLOCK_PATH
RUN_ONCE_PATH = COMPILED_RUN_ONCE_PATH
STORE_PY_PATH = str(REPO_ROOT / "news_experiment" / "store.py")
SCHEMA_SQL_PATH = str(Path(__file__).resolve().parent / "schema.sql")

TABLE = "news_observation"
PRAGMA_TABLE_INFO = f"PRAGMA table_info({TABLE})"
# Ruling B1: files SQLite would read beside a database. A non-live database
# with any of them beside it is refused before any open.
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
# Ruling S5: the environment variable that turns test mode on (value "1").
TEST_MODE_ENV = "NEWS_EVAL_TEST_MODE"
_UTC_Z_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- refusals

class LoaderRefusal(Exception):
    """Base of every named refusal raised by the guarded loader."""


class RealDatabaseRefused(LoaderRefusal):
    """The live news_experiment.db (by path, symlink or inode) in a phase that never reads it."""


class NotSyntheticRefused(LoaderRefusal):
    """A database without a valid synthetic marker in a phase that needs one."""


class ColumnRefused(LoaderRefusal):
    """A column outside the phase allow-list, named with its phase and role."""

    def __init__(self, column: object, phase: str, role: str) -> None:
        self.column = column
        self.phase = phase
        self.role = role
        super().__init__(f"column {column!r} refused in phase {phase} ({role})")


class UnlockMissing(LoaderRefusal):
    """GATE or VERDICT on a non-synthetic database without reports/c2_UNLOCK.json."""


class UnlockInvalid(LoaderRefusal):
    """The unlock file exists but is not a valid c2_unlock/1 object (ruling
    B2). Names the first field that fails."""

    def __init__(self, path: str, field: str, reason: str) -> None:
        self.path = path
        self.field = field
        super().__init__(f"unlock file {path}: field {field!r} {reason}")


class RunOnceMarkerMissing(LoaderRefusal):
    """VERDICT on a non-synthetic database without the C.2 run-once marker."""


class RunOnceMarkerInvalid(LoaderRefusal):
    """The run-once marker exists but is not c2_run_once/1 for the file being
    opened (ruling B2). Names the field that fails."""

    def __init__(self, path: str, field: str, reason: str) -> None:
        self.path = path
        self.field = field
        super().__init__(f"run-once marker {path}: field {field!r} {reason}")


class SidecarPresent(LoaderRefusal):
    """A -wal, -shm or -journal file beside a non-live database (ruling B1):
    SQLite could read it, so the bytes hashed would not be the bytes read."""


class PhaseRefused(LoaderRefusal):
    """A phase used outside its contract (wrong database, not open, wrong call)."""


class FilterRefused(LoaderRefusal):
    """A malformed filter: unknown operator, wrong arity, or a value of the wrong kind."""


# ---------------------------------------------------------- classification

class DbClass(str, enum.Enum):
    LIVE_REAL = "LIVE_REAL"
    SYNTHETIC = "SYNTHETIC"
    NON_SYNTHETIC = "NON_SYNTHETIC"


class Phase(str, enum.Enum):
    SYNTHETIC = "SYNTHETIC"
    SCHEMA = "SCHEMA"
    RELEVANCE = "RELEVANCE"
    GATE = "GATE"
    VERDICT = "VERDICT"


def _setting(value: str | os.PathLike | None, name: str) -> str:
    """An explicit argument wins; otherwise the module attribute at call time."""
    return os.fspath(value) if value is not None else getattr(
        sys.modules[__name__], name)


def is_test_mode() -> bool:
    """Ruling S5: test mode is NEWS_EVAL_TEST_MODE=1 in the environment,
    read at call time. Only test mode accepts the CLI path overrides."""
    return os.environ.get(TEST_MODE_ENV) == "1"


def override_refusal(flags: Mapping[str, object]) -> str | None:
    """Ruling S5: the refusal message for CLI path overrides given outside
    test mode (flags maps each flag name to its parsed value, None when not
    given), or None when nothing is refused."""
    used = [name for name, value in flags.items() if value is not None]
    if not used or is_test_mode():
        return None
    return (f"{', '.join(used)}: test-only override(s), refused outside test "
            f"mode ({TEST_MODE_ENV}=1 is set by the test suite only; C.1 "
            "lead ruling S5). The registered run uses the default paths.")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _same_file(path: str, other: str) -> bool:
    """Same realpath, or same (st_dev, st_ino). os.stat only, never an open."""
    if os.path.realpath(path) == os.path.realpath(other):
        return True
    try:
        other_st = os.stat(other)
    except FileNotFoundError:
        return False
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False
    return (st.st_dev, st.st_ino) == (other_st.st_dev, other_st.st_ino)


def is_compiled_real(path: str | os.PathLike) -> bool:
    """True for the repository's news_experiment.db, a symlink to it or a
    hard link (ruling B3); no override can change the answer."""
    return _same_file(os.fspath(path), _ALWAYS_LIVE)


def is_live_real(path: str | os.PathLike,
                 real_db_path: str | os.PathLike | None = None) -> bool:
    """Classification step 1 (STAGE C.1 Task 1; 9.7, 9.15): stat only, never
    opens a file. True for a live path, a symlink to it, or a hard link. The
    live paths are the compiled repository database ALWAYS and the override
    (or REAL_DB_PATH) as well: an override adds, never replaces (ruling B3)."""
    path = os.fspath(path)
    if is_compiled_real(path):
        return True
    return _same_file(path, _setting(real_db_path, "REAL_DB_PATH"))


def sidecars(path: str | os.PathLike) -> list[str]:
    """The -wal, -shm and -journal files present beside `path`, by its
    absolute path and by its realpath (ruling B1)."""
    found: list[str] = []
    for base in dict.fromkeys((os.path.abspath(os.fspath(path)),
                               os.path.realpath(os.fspath(path)))):
        found += [base + s for s in SIDECAR_SUFFIXES
                  if os.path.lexists(base + s)]
    return found


def refuse_sidecars(path: str | os.PathLike) -> None:
    """Ruling B1: raise SidecarPresent when a sidecar sits beside a non-live
    database. Called before any open of such a file."""
    found = sidecars(path)
    if found:
        raise SidecarPresent(
            f"{os.fspath(path)}: {', '.join(found)} present beside a non-live "
            "database; a sidecar can change what SQLite reads, so the file is "
            "refused (C.1 ruling B1). Find out how it got there before "
            "removing it.")


def _connect_ro(path: str, *, immutable: bool) -> sqlite3.Connection:
    """Open read-only through a URI; the path is percent-encoded. A non-live
    file is opened immutable=1, so SQLite neither reads nor creates a -wal,
    -shm or -journal beside it (ruling B1); the live file keeps plain
    mode=ro, since the collector may hold a legitimate WAL there."""
    query = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    uri = Path(os.path.abspath(path)).as_uri() + query
    return sqlite3.connect(uri, uri=True)


def _classify_open(path: str, real: str
                   ) -> tuple[DbClass, sqlite3.Connection | None]:
    """Steps 2 and 3 for a path already known not to be LIVE_REAL: the
    sidecar refusal, then an immutable read-only open."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    refuse_sidecars(path)
    conn = _connect_ro(path, immutable=True)
    try:
        cls = DbClass.SYNTHETIC if marker.is_synthetic(conn) \
            else DbClass.NON_SYNTHETIC
        # The file could have been swapped for a link to the real one between
        # the stat and the open; recheck after the open.
        if is_live_real(path, real):
            raise RealDatabaseRefused(f"{path} became the live database")
    except BaseException:
        conn.close()
        raise
    return cls, conn


def classify(path: str | os.PathLike,
             real_db_path: str | os.PathLike | None = None) -> DbClass:
    """The three-step classification of the module docstring (9.7, 9.15).
    Reads no row of a non-synthetic file (marker.is_synthetic stops at the
    header)."""
    real = _setting(real_db_path, "REAL_DB_PATH")
    path = os.fspath(path)
    if is_live_real(path, real):
        return DbClass.LIVE_REAL
    cls, conn = _classify_open(path, real)
    conn.close()
    return cls


# ---------------------------------------------- the unlock and the marker

def _json_object(path: str, label: str, invalid: type) -> dict:
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise invalid(path, "json", f"is not readable JSON: {exc}") from None
    if not isinstance(body, dict):
        raise invalid(path, "json", f"{label} is not a JSON object")
    return body


def load_unlock(path: str | os.PathLike) -> dict:
    """The unlock file, parsed and checked (C.1 lead ruling B2). Raises
    UnlockMissing when it is absent and UnlockInvalid naming the first bad
    field of: schema (constants.UNLOCK_SCHEMA), stage (constants.UNLOCK_STAGE),
    approver (a non-empty string), utc_time (ISO 8601 ending Z) and
    experiment_sha256 (the sha256 of EXPERIMENT.md on disk), and
    manifest_sha256 (present and well formed, 64 lowercase hex; re-check
    note R1). Its EQUALITY with the verified manifest is checked by the
    callers that verify a manifest (gate, run_c2)."""
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise UnlockMissing(f"the non-synthetic database needs the unlock "
                            f"file {path}; it does not exist")
    body = _json_object(path, "the unlock", UnlockInvalid)
    if body.get("schema") != K.UNLOCK_SCHEMA:
        raise UnlockInvalid(path, "schema", f"is {body.get('schema')!r}, "
                            f"not {K.UNLOCK_SCHEMA!r}")
    if body.get("stage") != K.UNLOCK_STAGE:
        raise UnlockInvalid(path, "stage", f"is {body.get('stage')!r}, not "
                            f"{K.UNLOCK_STAGE!r}")
    approver = body.get("approver")
    if not isinstance(approver, str) or not approver.strip():
        raise UnlockInvalid(path, "approver", "must be a non-empty string")
    stamp = body.get("utc_time")
    if not isinstance(stamp, str) or not _UTC_Z_RE.match(stamp):
        raise UnlockInvalid(path, "utc_time", f"{stamp!r} is not ISO 8601 "
                            "UTC ending Z (YYYY-MM-DDTHH:MM[:SS[.ffffff]]Z)")
    try:
        datetime.fromisoformat(stamp[:-1] + "+00:00")
    except ValueError:
        raise UnlockInvalid(path, "utc_time", f"{stamp!r} is not a valid "
                            "time") from None
    try:
        want = sha256_file(EXPERIMENT_MD_PATH)
    except OSError as exc:
        raise UnlockInvalid(path, "experiment_sha256", "cannot be checked: "
                            f"{EXPERIMENT_MD_PATH} unreadable ({exc})") \
            from None
    if body.get("experiment_sha256") != want:
        raise UnlockInvalid(path, "experiment_sha256",
                            f"{body.get('experiment_sha256')!r} != the "
                            f"sha256 of {EXPERIMENT_MD_PATH} ({want})")
    manifest = body.get("manifest_sha256")
    if not isinstance(manifest, str) or not _SHA256_RE.match(manifest):
        raise UnlockInvalid(path, "manifest_sha256", f"{manifest!r} is not a "
                            "64-character lowercase hex sha256")
    return body


def check_run_once(path: str | os.PathLike, db_sha256: str | None) -> dict:
    """The run-once marker, parsed and bound to the database about to be
    opened (C.1 lead ruling B2). Raises RunOnceMarkerMissing when absent and
    RunOnceMarkerInvalid when its schema is not constants.RUN_ONCE_SCHEMA or
    its snapshot_sha256 is not db_sha256."""
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise RunOnceMarkerMissing(
            f"the non-synthetic database needs the run-once marker {path}; "
            "it does not exist")
    body = _json_object(path, "the marker", RunOnceMarkerInvalid)
    if body.get("schema") != K.RUN_ONCE_SCHEMA:
        raise RunOnceMarkerInvalid(path, "schema", f"is "
                                   f"{body.get('schema')!r}, not "
                                   f"{K.RUN_ONCE_SCHEMA!r}")
    got = body.get("snapshot_sha256")
    if not isinstance(got, str) or not _SHA256_RE.match(got) \
            or got != db_sha256:
        raise RunOnceMarkerInvalid(path, "snapshot_sha256", f"{got!r} is not "
                                   f"the sha256 of the file opened "
                                   f"({db_sha256})")
    return body


# ------------------------------------------------------------- allow-lists

# Every phase's FIXED column allow-list (STAGE C.1 Task 1). Identifiers in any
# query come only from these tuples.
SYNTHETIC_ALLOW = K.SCHEMA_COLUMNS
# 9.13 and C.1 GUARDRAILS read 3: exactly six columns, filtered on three.
RELEVANCE_SELECT_ALLOW = K.RELEVANCE_COLUMNS
RELEVANCE_FILTER_ALLOW = ("run_kind", "state", "query_date")
# 9.7 and 9.8: what the S* cutoff, the 9.1 day exclusion and the gate need.
GATE_ALLOW = ("id", "query_date", "scoring_session", "state", "run_kind",
              "outcome_state", "exclusion_reason", "excess_1session")
# 9.8 k_eff: judgment, as a filter inside one COUNT, in one method only.
GATE_DIRECTIONAL_FILTER_EXTRA = ("judgment",)
VERDICT_ALLOW = K.SCHEMA_COLUMNS

# The one statement the RELEVANCE phase runs (9.13), pinned as text.
RELEVANCE_SQL = ("SELECT id, symbol, query_date, headline, sector, stratum "
                 "FROM news_observation WHERE run_kind = ? AND state = ? "
                 "AND query_date <= ? ORDER BY id")


# ----------------------------------------------------------- query builder

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BINARY_OPS = ("=", "!=", "<=", ">=", "<", ">")
LIST_OPS = ("IN", "NOT IN")
NULLARY_OPS = ("IS NULL", "IS NOT NULL", "!= ''")
FILTER_OPS = BINARY_OPS + LIST_OPS + NULLARY_OPS


@dataclass(frozen=True)
class Query:
    """A statement assembled from allow-listed identifiers and bound values
    (STAGE C.1 Task 1: no free SQL)."""
    sql: str
    params: tuple


def _column(col: object, allow: tuple[str, ...], phase: Phase,
            role: str) -> str:
    if not isinstance(col, str) or not _IDENT_RE.match(col) \
            or col not in K.SCHEMA_COLUMNS or col not in allow:
        raise ColumnRefused(col, phase.value, role)
    return col


def _columns(cols: object, allow: tuple[str, ...], phase: Phase,
             role: str) -> tuple[str, ...]:
    if isinstance(cols, (str, bytes)) or not isinstance(cols, (tuple, list)):
        raise PhaseRefused(f"{role} columns must be a tuple or list of names")
    return tuple(_column(c, allow, phase, role) for c in cols)


def _scalar(value: object, col: str, op: str) -> str | int | float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise FilterRefused(f"{col} {op}: value must be str, int or float, "
                            f"got {type(value).__name__}")
    return value


def _where(filters: object, allow: tuple[str, ...],
           phase: Phase) -> tuple[str, tuple]:
    """WHERE clause from (column, op, value) triples; values always bound."""
    if isinstance(filters, (str, bytes)) \
            or not isinstance(filters, (tuple, list)):
        raise FilterRefused("filters must be a tuple or list of triples")
    conds: list[str] = []
    params: list[object] = []
    for item in filters:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise FilterRefused(f"filter must be (column, op, value): {item!r}")
        col, op, value = item
        col = _column(col, allow, phase, "filter")
        if op not in FILTER_OPS:
            raise FilterRefused(f"operator {op!r} not in {FILTER_OPS}")
        if op in BINARY_OPS:
            conds.append(f"{col} {op} ?")
            params.append(_scalar(value, col, op))
        elif op in LIST_OPS:
            if isinstance(value, (str, bytes)) or not isinstance(
                    value, (tuple, list, set, frozenset)):
                raise FilterRefused(f"{col} {op}: value must be a collection")
            try:
                values = tuple(sorted(value)) if isinstance(
                    value, (set, frozenset)) else tuple(value)
            except TypeError:
                raise FilterRefused(f"{col} {op}: mixed value types") from None
            params.extend(_scalar(v, col, op) for v in values)
            conds.append(f"{col} {op} ({', '.join('?' * len(values))})")
        else:
            if value is not None:
                raise FilterRefused(f"{col} {op} takes no value (pass None)")
            conds.append(f"{col} {op}")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return where, tuple(params)


def build_select(columns: object, filters: object, *,
                 select_allow: tuple[str, ...], filter_allow: tuple[str, ...],
                 phase: Phase, order_by: object = ("id",)) -> Query:
    """SELECT <allow-listed columns> FROM news_observation [WHERE ...]
    [ORDER BY ...] (STAGE C.1 Task 1; the phases of 9.7, 9.8, 9.13, 9.15)."""
    cols = _columns(columns, select_allow, phase, "select")
    if not cols:
        raise PhaseRefused("select needs at least one column")
    order = _columns(order_by, select_allow, phase, "order_by")
    where, params = _where(filters, filter_allow, phase)
    sql = f"SELECT {', '.join(cols)} FROM {TABLE}{where}"
    if order:
        sql += f" ORDER BY {', '.join(order)}"
    return Query(sql, params)


def build_count_by(group_columns: object, filters: object, *,
                   group_allow: tuple[str, ...], filter_allow: tuple[str, ...],
                   phase: Phase) -> Query:
    """SELECT <groups>, COUNT(*) ... GROUP BY <groups>; no groups gives one
    count (STAGE C.1 Task 1; the 9.8 counts)."""
    groups = _columns(group_columns, group_allow, phase, "group_by")
    where, params = _where(filters, filter_allow, phase)
    if not groups:
        return Query(f"SELECT COUNT(*) FROM {TABLE}{where}", params)
    g = ", ".join(groups)
    return Query(f"SELECT {g}, COUNT(*) FROM {TABLE}{where} "
                 f"GROUP BY {g} ORDER BY {g}", params)


# ------------------------------------------------------------ result types

@dataclass(frozen=True)
class Rows:
    """Immutable query result: column names and row tuples (9.15 phases)."""
    columns: tuple[str, ...]
    data: tuple[tuple, ...]

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def column(self, name: str) -> tuple:
        i = self.columns.index(name)
        return tuple(r[i] for r in self.data)

    def as_dicts(self) -> list[dict]:
        return [dict(zip(self.columns, r)) for r in self.data]


@dataclass(frozen=True)
class GateRows:
    """9.8 gate rows G with non-null excess, and the NULL-excess count
    (reported, never read as 0)."""
    scoring_session: tuple[str, ...]
    excess_1session: tuple[float, ...]
    null_excess_count: int


@dataclass(frozen=True)
class ColumnInfo:
    """One row of PRAGMA table_info: metadata, never row data (9.15;
    C.1 GUARDRAILS read 2)."""
    cid: int
    name: str
    type: str
    notnull: int
    dflt_value: str | None
    pk: int


# ------------------------------------------------------------------ phases

class _Phase:
    """A read-only, classified, allow-listed connection (context manager).

    Records `phase` and `db_class`. Refusals of the live database happen
    before sqlite3.connect; other refusals before any query."""

    phase: Phase
    _select_allow: tuple[str, ...] = ()
    _filter_allow: tuple[str, ...] = ()
    _allow_live_real = False
    _live_real_only = False
    _allow_synthetic = True
    _non_synthetic = "refuse"  # "refuse" | "unlock" | "unlock+marker"

    def __init__(self, db_path: str | os.PathLike, *,
                 real_db_path: str | os.PathLike | None = None,
                 unlock_path: str | os.PathLike | None = None,
                 run_once_path: str | os.PathLike | None = None) -> None:
        self.db_path = os.fspath(db_path)
        self._real = _setting(real_db_path, "REAL_DB_PATH")
        self._unlock = _setting(unlock_path, "UNLOCK_PATH")
        self._run_once = _setting(run_once_path, "RUN_ONCE_PATH")
        self.db_class: DbClass | None = None
        self._conn: sqlite3.Connection | None = None
        self._readable = frozenset(self._select_allow) \
            | frozenset(self._filter_allow)

    def __repr__(self) -> str:
        return (f"{type(self).__name__}(phase={self.phase.value}, "
                f"db_class={getattr(self.db_class, 'value', None)}, "
                f"path={self.db_path!r})")

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self._conn is not None:
            raise PhaseRefused(f"{self.phase.value} phase is already open")
        if is_live_real(self.db_path, self._real):
            self._admit(DbClass.LIVE_REAL)  # refuses before connect
            cls = DbClass.LIVE_REAL
            conn = _connect_ro(self.db_path, immutable=False)
        else:
            if self._live_real_only:
                raise PhaseRefused(
                    f"{self.phase.value} runs only against the real database "
                    f"({self._real}); refused {self.db_path}")
            db_sha256 = None
            if self._non_synthetic == "unlock+marker":
                # Ruling B2: the marker is bound to the bytes about to be
                # read, hashed after the sidecar check and before connect.
                if not os.path.isfile(self.db_path):
                    raise FileNotFoundError(self.db_path)
                refuse_sidecars(self.db_path)
                db_sha256 = sha256_file(self.db_path)
            cls, conn = _classify_open(self.db_path, self._real)
            try:
                self._admit(cls, db_sha256)
            except BaseException:
                conn.close()
                raise
        conn.set_authorizer(self._authorize)
        self._conn, self.db_class = conn, cls

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _admit(self, cls: DbClass, db_sha256: str | None = None) -> None:
        name = self.phase.value
        if cls is DbClass.LIVE_REAL:
            if not self._allow_live_real:
                raise RealDatabaseRefused(
                    f"{name} never reads the live database {self.db_path} "
                    "(9.7: C.2 reads only the snapshot copy)")
            return
        if cls is DbClass.SYNTHETIC:
            if not self._allow_synthetic:
                raise PhaseRefused(f"{name} does not run on synthetic data")
            return
        if self._non_synthetic == "refuse":
            raise NotSyntheticRefused(
                f"{name} needs a synthetic database; {self.db_path} "
                "carries no valid marker")
        # Ruling B2: content, not existence. UnlockMissing / UnlockInvalid.
        load_unlock(self._unlock)
        if self._non_synthetic == "unlock+marker":
            check_run_once(self._run_once, db_sha256)

    def _authorize(self, action: int, arg1: str | None, arg2: str | None,
                   db_name: str | None, trigger: str | None) -> int:
        """Engine guard: SELECT, COUNT and reads of readable columns only."""
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 == "count":
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and arg1 == TABLE \
                and (arg2 == "" or arg2 in self._readable):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def _run(self, query: Query) -> list[tuple]:
        if self._conn is None:
            raise PhaseRefused(f"{self.phase.value} phase is not open")
        return self._conn.execute(query.sql, query.params).fetchall()

    def _select(self, columns: object, filters: object = (),
                order_by: object = ("id",)) -> Rows:
        q = build_select(columns, filters, select_allow=self._select_allow,
                         filter_allow=self._filter_allow, phase=self.phase,
                         order_by=order_by)
        return Rows(tuple(columns), tuple(self._run(q)))

    def _count_by(self, group_columns: object, filters: object = ()) -> Rows:
        q = build_count_by(group_columns, filters,
                           group_allow=self._select_allow,
                           filter_allow=self._filter_allow, phase=self.phase)
        return Rows(tuple(group_columns) + ("count",), tuple(self._run(q)))


class SyntheticPhase(_Phase):
    """SYNTHETIC phase: a marker-verified synthetic database only (9.15).
    Any schema column, through select and count_by."""

    phase = Phase.SYNTHETIC
    _select_allow = SYNTHETIC_ALLOW
    _filter_allow = SYNTHETIC_ALLOW

    def select(self, columns: object, filters: object = (),
               order_by: object = ("id",)) -> Rows:
        return self._select(columns, filters, order_by)

    def count_by(self, group_columns: object, filters: object = ()) -> Rows:
        return self._count_by(group_columns, filters)


class SchemaPhase(_Phase):
    """SCHEMA phase (C.1 GUARDRAILS read 2): PRAGMA table_info only, on the
    live real database only. Any other path is refused before connect."""

    phase = Phase.SCHEMA
    _allow_live_real = True
    _live_real_only = True
    _allow_synthetic = False

    def _authorize(self, action: int, arg1: str | None, arg2: str | None,
                   db_name: str | None, trigger: str | None) -> int:
        if action == sqlite3.SQLITE_PRAGMA and arg1 == "table_info" \
                and arg2 == TABLE:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def table_info(self) -> tuple[ColumnInfo, ...]:
        if self._conn is None:
            raise PhaseRefused("SCHEMA phase is not open")
        rows = self._conn.execute(PRAGMA_TABLE_INFO).fetchall()
        return tuple(ColumnInfo(*r) for r in rows)


class RelevancePhase(_Phase):
    """RELEVANCE phase (9.13; C.1 GUARDRAILS read 3): the six columns, the
    fixed filter, one method. Live real or synthetic only."""

    phase = Phase.RELEVANCE
    _select_allow = RELEVANCE_SELECT_ALLOW
    _filter_allow = RELEVANCE_FILTER_ALLOW
    _allow_live_real = True

    def relevance_population(self, query_date_max: str) -> Rows:
        """Judged collection rows with query_date <= query_date_max, ordered by
        id, six columns (9.13). On the live database the date is fixed at
        RELEVANCE_QUERY_DATE_MAX."""
        if not isinstance(query_date_max, str) \
                or not _DATE_RE.match(query_date_max):
            raise FilterRefused(f"query_date_max must be YYYY-MM-DD: "
                                f"{query_date_max!r}")
        if self.db_class is DbClass.LIVE_REAL \
                and query_date_max != K.RELEVANCE_QUERY_DATE_MAX:
            raise FilterRefused(
                "the live-database relevance draw is fixed at query_date <= "
                f"{K.RELEVANCE_QUERY_DATE_MAX} (9.13)")
        q = build_select(
            K.RELEVANCE_COLUMNS,
            (("run_kind", "=", K.RUN_KIND_COLLECTION),
             ("state", "=", K.STATE_JUDGED),
             ("query_date", "<=", query_date_max)),
            select_allow=self._select_allow, filter_allow=self._filter_allow,
            phase=self.phase, order_by=("id",))
        if q.sql != RELEVANCE_SQL:
            raise PhaseRefused("RELEVANCE statement drifted from RELEVANCE_SQL")
        return Rows(K.RELEVANCE_COLUMNS, tuple(self._run(q)))


class GatePhase(_Phase):
    """GATE phase (9.7, 9.8): never the live database; a synthetic database,
    or a non-synthetic one (C.2's snapshot) with a valid
    reports/c2_UNLOCK.json (load_unlock, ruling B2). The allow-list is
    GATE_ALLOW; judgment appears only inside the COUNT of
    directional_counts_by_cluster."""

    phase = Phase.GATE
    _select_allow = GATE_ALLOW
    _filter_allow = GATE_ALLOW
    _non_synthetic = "unlock"

    def state_counts_by_query_date(self) -> dict[str, dict[str, int]]:
        """Collection rows counted by (query_date, state): the 9.1 / Task 7
        source_failed day rule's input."""
        rows = self._count_by(("query_date", "state"),
                              (("run_kind", "=", K.RUN_KIND_COLLECTION),))
        out: dict[str, dict[str, int]] = {}
        for qd, state, n in rows:
            out.setdefault(qd, {})[state] = n
        return out

    def judged_session_status(self) -> dict[str | None, dict[str, int]]:
        """Judged collection rows counted by (scoring_session, outcome_state):
        the 9.7 S* cutoff and stale-pending input. Counts only."""
        rows = self._count_by(("scoring_session", "outcome_state"),
                              (("run_kind", "=", K.RUN_KIND_COLLECTION),
                               ("state", "=", K.STATE_JUDGED)))
        out: dict[str | None, dict[str, int]] = {}
        for ss, ostate, n in rows:
            out.setdefault(ss, {})[ostate] = n
        return out

    @staticmethod
    def _gate_filters(excluded_query_dates: object,
                      s_star: object) -> tuple[tuple, ...]:
        """9.7's scorable conditions minus the judgment condition (9.8 G),
        plus the 9.1 day exclusion and the S* cutoff (lead decision)."""
        if isinstance(excluded_query_dates, (str, bytes)) or not isinstance(
                excluded_query_dates, (tuple, list, set, frozenset)):
            raise FilterRefused("excluded_query_dates must be a collection")
        if any(not isinstance(d, str) for d in excluded_query_dates):
            raise FilterRefused("excluded_query_dates must hold strings")
        excluded = tuple(sorted(set(excluded_query_dates)))
        filters: list[tuple] = [
            ("run_kind", "=", K.RUN_KIND_COLLECTION),
            ("state", "=", K.STATE_JUDGED),
            ("outcome_state", "=", K.OUTCOME_RESOLVED),
            ("exclusion_reason", "=", K.EXCLUSION_NONE),
            ("scoring_session", "IS NOT NULL", None),
            ("scoring_session", "!= ''", None),
            ("query_date", "NOT IN", excluded),
        ]
        if s_star is not None:
            if not isinstance(s_star, str) or not s_star:
                raise FilterRefused(f"s_star must be a non-empty string or "
                                    f"None: {s_star!r}")
            filters.append(("scoring_session", "<=", s_star))
        return tuple(filters)

    def gate_rows(self, excluded_query_dates: object,
                  s_star: str | None) -> GateRows:
        """9.8 G: scoring_session and excess_1session of every row meeting the
        gate conditions with non-null excess, ordered by (scoring_session,
        id), plus the count of rows meeting them with NULL excess."""
        base = self._gate_filters(excluded_query_dates, s_star)
        rows = self._select(
            ("scoring_session", "excess_1session"),
            base + (("excess_1session", "IS NOT NULL", None),),
            order_by=("scoring_session", "id"))
        null_count = self._count_by(
            (), base + (("excess_1session", "IS NULL", None),)).data[0][0]
        return GateRows(
            scoring_session=tuple(r[0] for r in rows),
            excess_1session=tuple(float(r[1]) for r in rows),
            null_excess_count=int(null_count))

    def directional_counts_by_cluster(self, excluded_query_dates: object,
                                      s_star: str | None) -> dict[str, int]:
        """9.8 k_eff and C: the count of directional scorable rows per
        scoring_session, from one COUNT ... GROUP BY. Returns counts only,
        never a row; the only GATE code that names judgment."""
        filters = self._gate_filters(excluded_query_dates, s_star) + (
            ("excess_1session", "IS NOT NULL", None),
            ("judgment", "IN", K.DIRECTIONAL),
        )
        q = build_count_by(
            ("scoring_session",), filters, group_allow=self._select_allow,
            filter_allow=self._filter_allow + GATE_DIRECTIONAL_FILTER_EXTRA,
            phase=self.phase)
        widened = self._readable
        self._readable = widened | frozenset(GATE_DIRECTIONAL_FILTER_EXTRA)
        try:
            rows = self._run(q)
        finally:
            self._readable = widened
        return {ss: int(n) for ss, n in rows}


class VerdictPhase(_Phase):
    """VERDICT phase (9.15): never the live database; a synthetic database,
    or a non-synthetic one with a valid reports/c2_UNLOCK.json AND the C.2
    run-once marker whose snapshot_sha256 is this file's sha256, hashed
    before connect (check_run_once, ruling B2). All schema columns, through
    select only."""

    phase = Phase.VERDICT
    _select_allow = VERDICT_ALLOW
    _filter_allow = VERDICT_ALLOW
    _non_synthetic = "unlock+marker"

    def select(self, columns: object, filters: object = (),
               order_by: object = ("id",)) -> Rows:
        return self._select(columns, filters, order_by)


PHASE_CLASSES = {
    Phase.SYNTHETIC: SyntheticPhase,
    Phase.SCHEMA: SchemaPhase,
    Phase.RELEVANCE: RelevancePhase,
    Phase.GATE: GatePhase,
    Phase.VERDICT: VerdictPhase,
}


def open_phase(phase: Phase | str, db_path: str | os.PathLike, **kwargs):
    """The phase object for `phase` (not yet open; use it in a with block).
    Phases per 9.7, 9.8, 9.13, 9.15."""
    return PHASE_CLASSES[Phase(phase)](db_path, **kwargs)


# ------------------------------------------------- schema.sql reconstruction

_STORE_SCHEMA_RE = re.compile(r'SCHEMA\s*=\s*"""(.*?)"""', re.S)
_STORE_TABLE_RE = re.compile(
    r"CREATE TABLE[^(]*\(\s*(.*?)\n\);", re.S)
_STORE_INDEX_RE = re.compile(r"CREATE INDEX[^;]*;", re.S)
_COLDEF_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s+([A-Za-z]+)(.*?),?\s*$")
_DEFAULT_RE = re.compile(r"DEFAULT\s+('(?:[^']|'')*'|[^\s,]+)")


def _store_schema_text(store_py_path: str | None = None) -> str:
    text = Path(_setting(store_py_path, "STORE_PY_PATH")).read_text()
    match = _STORE_SCHEMA_RE.search(text)
    if match is None:
        raise ValueError("no SCHEMA string in store.py")
    return match.group(1)


def store_columns(store_schema: str) -> tuple[ColumnInfo, ...]:
    """Parse store.py's CREATE TABLE text into ColumnInfo-shaped records
    (Task 8 columns; compared with PRAGMA for 9.15's schema copy)."""
    body = _STORE_TABLE_RE.search(store_schema)
    if body is None:
        raise ValueError("no CREATE TABLE in store.py SCHEMA")
    out = []
    for line in body.group(1).splitlines():
        line = line.split("--", 1)[0].rstrip()
        if not line.strip():
            continue
        m = _COLDEF_RE.match(line)
        if m is None:
            raise ValueError(f"unparsed store.py column line: {line!r}")
        name, ctype, rest = m.group(1), m.group(2), m.group(3)
        dflt = _DEFAULT_RE.search(rest)
        out.append(ColumnInfo(
            cid=len(out), name=name, type=ctype,
            notnull=int("NOT NULL" in rest.upper()),
            dflt_value=dflt.group(1) if dflt else None,
            pk=int("PRIMARY KEY" in rest.upper())))
    return tuple(out)


def store_indexes(store_schema: str) -> tuple[str, ...]:
    """The CREATE INDEX statements of store.py, verbatim (9.15 schema copy)."""
    return tuple(_STORE_INDEX_RE.findall(store_schema))


def compare_with_store(pragma: tuple[ColumnInfo, ...],
                       store: tuple[ColumnInfo, ...]) -> list[str]:
    """Differences between PRAGMA table_info and store.py's DDL, as text
    (9.15 schema copy; reported in schema.sql's header)."""
    diffs = []
    p_names = [c.name for c in pragma]
    s_names = [c.name for c in store]
    for name in p_names:
        if name not in s_names:
            diffs.append(f"column {name} in PRAGMA, not in store.py")
    for name in s_names:
        if name not in p_names:
            diffs.append(f"column {name} in store.py, not in PRAGMA")
    common_p = [n for n in p_names if n in s_names]
    common_s = [n for n in s_names if n in p_names]
    if common_p != common_s:
        diffs.append("column order differs between PRAGMA and store.py")
    s_by = {c.name: c for c in store}
    for c in pragma:
        s = s_by.get(c.name)
        if s is None:
            continue
        for field in ("type", "notnull", "dflt_value", "pk"):
            pv, sv = getattr(c, field), getattr(s, field)
            if field == "type":
                pv, sv = pv.upper(), sv.upper()
            if pv != sv:
                diffs.append(
                    f"{c.name}.{field}: PRAGMA {pv!r} vs store.py {sv!r}")
    return diffs


def _store_autoincrement(store_schema: str, column: str) -> bool:
    return re.search(rf"^\s*{re.escape(column)}\s+INTEGER\s+PRIMARY\s+KEY"
                     r"\s+AUTOINCREMENT\b", store_schema,
                     re.M | re.I) is not None


def render_schema(pragma: tuple[ColumnInfo, ...], store_schema: str,
                  read_utc: str) -> str:
    """Deterministic schema.sql text (9.15): the CREATE TABLE from PRAGMA,
    then the store.py indexes, marked as such. Only the header carries the
    read time."""
    if not pragma:
        raise ValueError("PRAGMA table_info returned no columns")
    pk_cols = sorted((c for c in pragma if c.pk), key=lambda c: c.pk)
    single_pk = pk_cols[0].name if len(pk_cols) == 1 else None
    autoinc = single_pk is not None and _store_autoincrement(
        store_schema, single_pk)
    diffs = compare_with_store(pragma, store_columns(store_schema))
    lines = [
        "-- news_eval/schema.sql: the news_observation table as the real",
        "-- database declares it (STAGE C.1 Task 1; GUARDRAILS read 2;",
        "-- Amendment 9.15). Written by the loader's SCHEMA phase:",
        "--   python -m news_eval.data schema --out news_eval/schema.sql",
        f"-- which ran `{PRAGMA_TABLE_INFO}` on",
        "--   file:news_experiment.db?mode=ro (read-only URI)",
        f"-- at {read_utc} and read nothing else.",
        "-- Column order, declared type, NOT NULL and DEFAULT text are exactly",
        "-- what PRAGMA returned.",
    ]
    if autoinc:
        lines.append(f"-- AUTOINCREMENT on {single_pk}: not visible to PRAGMA; "
                     "news_experiment/store.py declares it.")
    if diffs:
        lines.append("-- Differences between PRAGMA and news_experiment/store.py:")
        lines.extend(f"--   {d}" for d in diffs)
    else:
        lines.append("-- PRAGMA and news_experiment/store.py's DDL agree on "
                     "every column, type, NOT NULL, DEFAULT and key.")
    defs = []
    for c in pragma:
        parts = [c.name, c.type] if c.type else [c.name]
        if single_pk == c.name:
            parts.append("PRIMARY KEY AUTOINCREMENT" if autoinc
                         else "PRIMARY KEY")
        if c.notnull:
            parts.append("NOT NULL")
        if c.dflt_value is not None:
            parts.append(f"DEFAULT {c.dflt_value}")
        defs.append("    " + " ".join(parts))
    if len(pk_cols) > 1:
        defs.append("    PRIMARY KEY ("
                    + ", ".join(c.name for c in pk_cols) + ")")
    lines.append(f"CREATE TABLE {TABLE} (")
    lines.append(",\n".join(defs))
    lines.append(");")
    lines.append("-- Indexes: taken verbatim from news_experiment/store.py's "
                 "SCHEMA text, not read from the real database.")
    lines.extend(store_indexes(store_schema))
    return "\n".join(lines) + "\n"


def _dump(real_db_path: str | os.PathLike) -> tuple[str, int]:
    with SchemaPhase(real_db_path) as phase:
        info = phase.table_info()
    read_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return render_schema(info, _store_schema_text(), read_utc), len(info)


def dump_schema(real_db_path: str | os.PathLike) -> str:
    """The SCHEMA phase read (9.15; C.1 guardrail read 2): one PRAGMA table_info on
    the real database through a read-only URI, rendered as schema.sql text.
    Refuses (PhaseRefused, before connect) unless real_db_path is the real
    database as REAL_DB_PATH names it."""
    return _dump(real_db_path)[0]


# --------------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m news_eval.data")
    sub = parser.add_subparsers(dest="command", required=True)
    schema = sub.add_parser("schema", help="SCHEMA phase: write schema.sql")
    schema.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "schema":
        text, n_cols = _dump(REAL_DB_PATH)
        Path(args.out).write_text(text)
        diffs = "none" if "agree on every column" in text else "see header"
        print(f"wrote {args.out}: {n_cols} columns from PRAGMA; "
              f"store.py differences: {diffs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
