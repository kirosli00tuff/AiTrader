"""The guarded loader's refusals, allow-lists and real-path detection
(STAGE C.1 Task 1; news_eval/data.py; Amendment 9.7, 9.8, 9.13, 9.15).

No test opens the repo's news_experiment.db: an autouse fixture points
data.REAL_DB_PATH at an unstamped fake "real" database under tmp_path, points
the unlock and run-once paths at absent tmp_path files, and makes any
sqlite3.connect to the repo's real file raise. The C.1 ruling tests (B1
sidecars and immutable opens, B2 unlock and marker content, B3 the compiled
live path) name the repository's database only through os.stat-based checks
or refusals that come before sqlite3.connect, under the same guard.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from news_eval import constants as K
from news_eval import data
from news_eval import marker

SCHEMA_SQL = Path(data.SCHEMA_SQL_PATH).read_text()
REPO_REAL_DB = os.path.realpath(data.REAL_DB_PATH)  # read at import, never opened
_UNPATCHED_CONNECT = sqlite3.connect


class ConnectCalled(BaseException):
    """Raised by a patched sqlite3.connect; BaseException so nothing swallows it."""


def _touches_repo_real(target: object) -> bool:
    text = os.fspath(target) if not isinstance(target, int) else ""
    if isinstance(text, bytes):
        text = text.decode()
    if text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
        while text.startswith("//"):
            text = text[1:]
    if not text or text == ":memory:":
        return False
    if os.path.realpath(text) == REPO_REAL_DB:
        return True
    try:
        a, b = os.stat(text), os.stat(REPO_REAL_DB)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


# ------------------------------------------------------------------ helpers

_BASE_ROW = {
    "rule_id": "r", "formation_date": "2026-07-01", "symbol": "AAA",
    "stratum": "S1", "sector": "Technology", "sector_source": "x",
    "query_date": "2026-08-03", "state": "judged", "exclusion_reason": "",
    "headline": "h", "spec_version": "v", "written_ts": "w",
    "run_kind": "collection", "outcome_state": "resolved",
    "scoring_session": "2026-08-03", "judgment": "POSITIVE", "strength": 3,
    "excess_1session": 0.001,
}

# (overrides) for each fixture row; ids are 1..N in this order.
_ROWS = [
    {},                                                         # 1 G, POS
    {"judgment": "NEGATIVE", "excess_1session": -0.002},        # 2 G, NEG
    {"judgment": "NEUTRAL", "excess_1session": 0.003},          # 3 G, NEU
    {"scoring_session": "2026-08-04", "query_date": "2026-08-04",
     "excess_1session": 0.004},                                 # 4 G, POS
    {"scoring_session": "2026-08-04", "query_date": "2026-08-04",
     "excess_1session": None},                                  # 5 NULL excess
    {"scoring_session": "2026-08-05", "query_date": "2026-08-05",
     "outcome_state": "pending", "excess_1session": None},      # 6 pending
    {"exclusion_reason": "duplicate_headline"},                 # 7 excluded
    {"scoring_session": ""},                                    # 8 empty session
    {"scoring_session": None},                                  # 9 null session
    {"run_kind": "demonstration"},                              # 10 demo
    {"state": "source_failed", "judgment": None,
     "scoring_session": None, "excess_1session": None,
     "outcome_state": "pending"},                               # 11 source_failed
    {"query_date": "2026-10-10", "scoring_session": "2026-10-12",
     "excess_1session": 0.005},                                 # 12 after 10-09
    {"scoring_session": "2026-08-06", "query_date": "2026-08-06",
     "judgment": "NEGATIVE", "excess_1session": 0.006},         # 13 G, NEG
]


def _insert(conn: sqlite3.Connection, overrides: dict) -> None:
    row = {**_BASE_ROW, **overrides}
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO news_observation ({cols}) VALUES "
                 f"({', '.join('?' * len(row))})", tuple(row.values()))


def make_db(path: Path, rows=_ROWS, stamp: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _UNPATCHED_CONNECT(path)
    try:
        conn.executescript(SCHEMA_SQL)
        for overrides in rows:
            _insert(conn, overrides)
        conn.commit()
        if stamp:
            marker.write_marker(conn, "loader-test", 1)
    finally:
        conn.close()
    return path


def valid_unlock(**overrides) -> dict:
    """A c2_unlock/1 body the loader accepts (ruling B2), with overrides."""
    body = {"schema": K.UNLOCK_SCHEMA, "stage": K.UNLOCK_STAGE,
            "approver": "test operator", "utc_time": "2026-10-20T06:00:00Z",
            "experiment_sha256": data.sha256_file(data.EXPERIMENT_MD_PATH),
            "manifest_sha256": "0" * 64}
    return {**body, **overrides}


def write_unlock(path: Path, **overrides) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(valid_unlock(**overrides)))
    return path


def write_marker(path: Path, db: Path | None = None, **overrides) -> Path:
    """A c2_run_once/1 marker bound to db's sha256 (ruling B2)."""
    body = {"schema": K.RUN_ONCE_SCHEMA,
            "snapshot_sha256": data.sha256_file(db) if db else "0" * 64}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**body, **overrides}))
    return path


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.real = make_db(tmp / "repo" / "news_experiment.db")
        self.synth = make_db(tmp / "fixtures" / "synth.db", stamp=True)
        self.unlock = tmp / "repo" / "reports" / "c2_UNLOCK.json"
        self.run_once = tmp / "repo" / "reports" / "c2_RUN_ONCE.json"

    def symlink(self) -> Path:
        link = self.tmp / "links" / "alias.db"
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(self.real, link)
        return link

    def hardlink(self) -> Path:
        link = self.tmp / "links" / "hard.db"
        link.parent.mkdir(parents=True, exist_ok=True)
        os.link(self.real, link)
        return link

    def copy(self) -> Path:
        dest = self.tmp / "snapshot" / "news_experiment.db"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.real, dest)
        return dest

    def write_unlock(self) -> None:
        write_unlock(self.unlock)

    def write_run_once(self, db: Path | None = None) -> None:
        write_marker(self.run_once, db)


@pytest.fixture(autouse=True)
def _never_the_repo_real_db(monkeypatch):
    def guarded(database, *args, **kwargs):
        if _touches_repo_real(database):
            raise ConnectCalled(f"test opened the repo's real database: "
                                f"{database}")
        return _UNPATCHED_CONNECT(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", guarded)


@pytest.fixture()
def env(tmp_path, monkeypatch) -> Env:
    e = Env(tmp_path)
    monkeypatch.setattr(data, "REAL_DB_PATH", str(e.real))
    monkeypatch.setattr(data, "UNLOCK_PATH", str(e.unlock))
    monkeypatch.setattr(data, "RUN_ONCE_PATH", str(e.run_once))
    return e


@pytest.fixture()
def no_connect(monkeypatch):
    """sqlite3.connect raises: proves a refusal came before any connect."""
    def refuse(*args, **kwargs):
        raise ConnectCalled("sqlite3.connect was called")
    monkeypatch.setattr(sqlite3, "connect", refuse)


@pytest.fixture()
def trace(monkeypatch) -> list[str]:
    """Every statement the loader executes, in order."""
    statements: list[str] = []
    inner = sqlite3.connect

    def traced(*args, **kwargs):
        conn = inner(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, "connect", traced)
    return statements


# ------------------------------------------------------------ the defaults

def test_default_real_path_is_the_repo_database():
    assert Path(REPO_REAL_DB).name == "news_experiment.db"
    assert Path(REPO_REAL_DB).parent == data.REPO_ROOT.resolve()
    assert Path(data.UNLOCK_PATH) == data.REPO_ROOT / "reports" / "c2_UNLOCK.json"
    assert Path(data.RUN_ONCE_PATH) \
        == data.REPO_ROOT / "reports" / "c2_RUN_ONCE.json"


def test_refusal_classes_share_the_base():
    for cls in (data.RealDatabaseRefused, data.NotSyntheticRefused,
                data.ColumnRefused, data.UnlockMissing,
                data.RunOnceMarkerMissing, data.PhaseRefused,
                data.FilterRefused):
        assert issubclass(cls, data.LoaderRefusal)


# ---------------------------------------------------------- classification

def test_classify_live_real_by_path_symlink_and_hardlink(env, no_connect):
    assert data.classify(env.real) is data.DbClass.LIVE_REAL
    assert data.classify(str(env.real)) is data.DbClass.LIVE_REAL
    assert data.classify(env.symlink()) is data.DbClass.LIVE_REAL
    assert data.classify(env.hardlink()) is data.DbClass.LIVE_REAL


def test_classify_live_real_by_relative_path(env, no_connect, monkeypatch):
    monkeypatch.chdir(env.real.parent)
    assert data.classify("news_experiment.db") is data.DbClass.LIVE_REAL
    assert data.classify("./../repo/news_experiment.db") \
        is data.DbClass.LIVE_REAL


def test_is_live_real_never_opens(env, no_connect):
    assert data.is_live_real(env.real)
    assert data.is_live_real(env.symlink())
    assert data.is_live_real(env.hardlink())
    assert not data.is_live_real(env.synth)
    assert not data.is_live_real(env.tmp / "missing.db")


def test_copy_named_news_experiment_db_is_non_synthetic(env):
    assert data.classify(env.copy()) is data.DbClass.NON_SYNTHETIC


def test_synthetic_renamed_news_experiment_db_stays_synthetic(env):
    dest = env.tmp / "elsewhere" / "news_experiment.db"
    dest.parent.mkdir()
    shutil.copy2(env.synth, dest)
    assert data.classify(env.synth) is data.DbClass.SYNTHETIC
    assert data.classify(dest) is data.DbClass.SYNTHETIC


def test_synthetic_with_row_added_after_stamp_is_non_synthetic(env):
    conn = _UNPATCHED_CONNECT(env.synth)
    _insert(conn, {"symbol": "ZZZ"})
    conn.commit()
    conn.close()
    assert data.classify(env.synth) is data.DbClass.NON_SYNTHETIC


def test_classify_missing_file_raises(env):
    with pytest.raises(FileNotFoundError):
        data.classify(env.tmp / "missing.db")


# ------------------------------------- real-path refusals precede connect

@pytest.mark.parametrize("phase_cls", [data.SyntheticPhase, data.GatePhase,
                                       data.VerdictPhase])
@pytest.mark.parametrize("how", ["path", "symlink", "hardlink"])
def test_live_real_refused_before_connect_even_with_unlock(
        env, phase_cls, how):
    env.write_unlock()
    env.write_run_once()
    target = {"path": lambda: env.real, "symlink": env.symlink,
              "hardlink": env.hardlink}[how]()

    def refuse(*args, **kwargs):
        raise ConnectCalled("connect before refusal")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sqlite3, "connect", refuse)
        phase = phase_cls(target)
        with pytest.raises(data.RealDatabaseRefused):
            phase.open()
        assert phase.db_class is None
        assert phase._conn is None


def test_live_real_refused_with_explicit_real_db_path(tmp_path, no_connect):
    real = make_db(tmp_path / "other" / "news_experiment.db")
    with pytest.raises(data.RealDatabaseRefused):
        with data.GatePhase(real, real_db_path=real):
            pass


@pytest.mark.parametrize("which", ["synth", "copy"])
def test_schema_refuses_non_real_before_connect(env, which):
    target = env.synth if which == "synth" else env.copy()

    def refuse(*args, **kwargs):
        raise ConnectCalled("connect before refusal")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sqlite3, "connect", refuse)
        with pytest.raises(data.PhaseRefused):
            with data.SchemaPhase(target):
                pass
        with pytest.raises(data.PhaseRefused):
            data.dump_schema(target)


# ----------------------------------------------------------- admission

def test_synthetic_phase_admits_only_synthetic(env):
    with data.SyntheticPhase(env.synth) as ph:
        assert ph.phase is data.Phase.SYNTHETIC
        assert ph.db_class is data.DbClass.SYNTHETIC
    with pytest.raises(data.NotSyntheticRefused):
        with data.SyntheticPhase(env.copy()):
            pass


def test_synthetic_phase_refuses_tampered_synthetic(env):
    conn = _UNPATCHED_CONNECT(env.synth)
    conn.execute("UPDATE news_observation SET symbol = 'X' WHERE id = 1")
    _insert(conn, {})
    conn.commit()
    conn.close()
    with pytest.raises(data.NotSyntheticRefused):
        with data.SyntheticPhase(env.synth):
            pass


def test_relevance_admits_live_real_and_synthetic_only(env):
    with data.RelevancePhase(env.real) as ph:
        assert ph.db_class is data.DbClass.LIVE_REAL
    with data.RelevancePhase(env.symlink()) as ph:
        assert ph.db_class is data.DbClass.LIVE_REAL
    with data.RelevancePhase(env.synth) as ph:
        assert ph.db_class is data.DbClass.SYNTHETIC
    env.write_unlock()
    with pytest.raises(data.NotSyntheticRefused):
        with data.RelevancePhase(env.copy()):
            pass


def test_gate_on_copy_needs_unlock(env):
    copy = env.copy()
    with pytest.raises(data.UnlockMissing):
        with data.GatePhase(copy):
            pass
    env.write_unlock()
    with data.GatePhase(copy) as ph:
        assert ph.db_class is data.DbClass.NON_SYNTHETIC
        assert ph.phase is data.Phase.GATE


def test_verdict_on_copy_needs_unlock_and_marker(env):
    copy = env.copy()
    with pytest.raises(data.UnlockMissing):
        with data.VerdictPhase(copy):
            pass
    env.write_run_once(copy)
    with pytest.raises(data.UnlockMissing):
        with data.VerdictPhase(copy):
            pass
    env.run_once.unlink()
    env.write_unlock()
    with pytest.raises(data.RunOnceMarkerMissing):
        with data.VerdictPhase(copy):
            pass
    env.write_run_once(copy)
    with data.VerdictPhase(copy) as ph:
        assert ph.db_class is data.DbClass.NON_SYNTHETIC
        assert ph.phase is data.Phase.VERDICT


def test_gate_and_verdict_on_synthetic_need_no_files(env):
    assert not env.unlock.exists() and not env.run_once.exists()
    with data.GatePhase(env.synth) as ph:
        assert ph.db_class is data.DbClass.SYNTHETIC
    with data.VerdictPhase(env.synth) as ph:
        assert ph.db_class is data.DbClass.SYNTHETIC


def test_explicit_unlock_and_marker_paths(env, tmp_path):
    copy = env.copy()
    unlock = write_unlock(tmp_path / "u.json")
    run_once = write_marker(tmp_path / "m.json", copy)
    with pytest.raises(data.UnlockMissing):
        with data.GatePhase(copy):
            pass
    with data.GatePhase(copy, unlock_path=unlock):
        pass
    with data.VerdictPhase(copy, unlock_path=unlock, run_once_path=run_once):
        pass


def test_phase_not_open_refuses(env):
    ph = data.GatePhase(env.synth)
    with pytest.raises(data.PhaseRefused):
        ph.state_counts_by_query_date()
    with pytest.raises(data.PhaseRefused):
        data.SchemaPhase(env.real).table_info()


def test_context_manager_closes_and_cannot_double_open(env):
    with data.SyntheticPhase(env.synth) as ph:
        assert ph._conn is not None
        with pytest.raises(data.PhaseRefused):
            ph.open()
    assert ph._conn is None


def test_connections_are_read_only(env):
    with data.SyntheticPhase(env.synth) as ph:
        ph._conn.set_authorizer(None)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ph._conn.execute("DELETE FROM news_observation")


def test_open_phase_factory(env):
    for phase, cls in data.PHASE_CLASSES.items():
        obj = data.open_phase(phase.value, env.synth)
        assert isinstance(obj, cls)
        assert obj.phase is phase


# ------------------------------------------------------------ allow-lists

def test_allow_lists_pinned():
    assert data.SYNTHETIC_ALLOW == K.SCHEMA_COLUMNS
    assert data.VERDICT_ALLOW == K.SCHEMA_COLUMNS
    assert data.RELEVANCE_SELECT_ALLOW == ("id", "symbol", "query_date",
                                           "headline", "sector", "stratum")
    assert data.RELEVANCE_FILTER_ALLOW == ("run_kind", "state", "query_date")
    assert data.GATE_ALLOW == ("id", "query_date", "scoring_session",
                               "state", "run_kind", "outcome_state",
                               "exclusion_reason", "excess_1session")
    assert data.GATE_DIRECTIONAL_FILTER_EXTRA == ("judgment",)


def test_allow_lists_against_guarded_columns():
    relevance = set(data.RELEVANCE_SELECT_ALLOW) | set(
        data.RELEVANCE_FILTER_ALLOW)
    assert not relevance & set(K.GUARDED_COLUMNS)
    gate = set(data.GATE_ALLOW)
    assert gate & set(K.BLIND_COLUMNS) == {"scoring_session"}
    assert gate & set(K.OUTCOME_COLUMNS) == {"outcome_state",
                                             "excess_1session"}
    assert not gate & set(K.JUDGMENT_DERIVED_COLUMNS)
    assert not gate & set(K.OUTCOME_ADJACENT_COLUMNS)


def test_only_some_phases_expose_free_column_methods():
    assert hasattr(data.SyntheticPhase, "select")
    assert hasattr(data.SyntheticPhase, "count_by")
    assert hasattr(data.VerdictPhase, "select")
    assert not hasattr(data.VerdictPhase, "count_by")
    for cls in (data.GatePhase, data.RelevancePhase, data.SchemaPhase):
        assert not hasattr(cls, "select")
        assert not hasattr(cls, "count_by")
    public = {n for n in dir(data.RelevancePhase)
              if not n.startswith("_") and callable(
                  getattr(data.RelevancePhase, n))}
    assert public == {"relevance_population", "open", "close"}
    public_gate = {n for n in dir(data.GatePhase)
                   if not n.startswith("_") and callable(
                       getattr(data.GatePhase, n))}
    assert public_gate == {"state_counts_by_query_date",
                           "judged_session_status", "gate_rows",
                           "directional_counts_by_cluster", "open", "close"}


GATE_REFUSED = ["judgment", "strength", "reason", "net_bp", "headline",
                "symbol", "raw_response", "ret_1session", "not_a_column"]
RELEVANCE_SELECT_REFUSED = ["judgment", "scoring_session", "excess_1session",
                            "outcome_state", "raw_response", "state"]
RELEVANCE_FILTER_REFUSED = ["symbol", "headline", "judgment",
                            "scoring_session", "id"]
ANY_PHASE_REFUSED = ["not_a_column", "id; DROP TABLE news_observation",
                     "ID", "news_observation.id", "*", 1, None]


def _assert_refused(trace, call, column, phase_name):
    before = len(trace)
    with pytest.raises(data.ColumnRefused) as info:
        call()
    assert info.value.column == column
    assert info.value.phase == phase_name
    assert len(trace) == before, "a query ran before the refusal"


@pytest.mark.parametrize("col", GATE_REFUSED)
def test_gate_allow_list_select_filter_group(env, trace, col):
    with data.GatePhase(env.synth) as ph:
        _assert_refused(trace, lambda: ph._select((col,)), col, "GATE")
        _assert_refused(trace, lambda: ph._select(
            ("excess_1session",), ((col, "=", "x"),)), col, "GATE")
        _assert_refused(trace, lambda: ph._count_by((col,)), col, "GATE")
        _assert_refused(trace, lambda: ph._select(
            ("id",), order_by=(col,)), col, "GATE")


@pytest.mark.parametrize("col", RELEVANCE_SELECT_REFUSED)
def test_relevance_allow_list_select(env, trace, col):
    with data.RelevancePhase(env.synth) as ph:
        _assert_refused(trace, lambda: ph._select((col,)), col, "RELEVANCE")


@pytest.mark.parametrize("col", RELEVANCE_FILTER_REFUSED)
def test_relevance_allow_list_filter(env, trace, col):
    with data.RelevancePhase(env.synth) as ph:
        _assert_refused(trace, lambda: ph._select(
            ("symbol",), ((col, "=", "x"),)), col, "RELEVANCE")


@pytest.mark.parametrize("col", ANY_PHASE_REFUSED)
@pytest.mark.parametrize("phase_cls", [data.SyntheticPhase,
                                       data.VerdictPhase, data.GatePhase,
                                       data.RelevancePhase])
def test_non_columns_refused_in_every_phase(env, trace, phase_cls, col):
    name = phase_cls.phase.value
    with phase_cls(env.synth) as ph:
        _assert_refused(trace, lambda: ph._select((col,)), col, name)
        _assert_refused(trace, lambda: ph._select(
            ("id",), ((col, "=", 1),)), col, name)


def test_schema_phase_has_no_columns(env):
    assert data.SchemaPhase._select_allow == ()
    assert data.SchemaPhase._filter_allow == ()


@pytest.mark.parametrize("bad", [
    ("id", "LIKE", "x"),
    ("id", "= 1 OR 1=1 --", 1),
    ("id", "=", None),
    ("id", "=", True),
    ("id", "=", b"x"),
    ("id", "IN", "abc"),
    ("id", "IN", 5),
    ("id", "IS NULL", 1),
    ("id", "!= ''", "x"),
    ("id", "="),
    "id = 1",
])
def test_malformed_filters_refused(env, trace, bad):
    with data.SyntheticPhase(env.synth) as ph:
        before = len(trace)
        with pytest.raises(data.FilterRefused):
            ph.select(("id",), (bad,))
        assert len(trace) == before


def test_filters_must_be_a_sequence_of_triples(env):
    with data.SyntheticPhase(env.synth) as ph:
        with pytest.raises(data.FilterRefused):
            ph.select(("id",), "id = 1")
        with pytest.raises(data.PhaseRefused):
            ph.select("id")
        with pytest.raises(data.PhaseRefused):
            ph.select(())


def test_values_are_bound_not_spliced(env):
    hostile = "x' OR '1'='1"
    q = data.build_select(("id",), (("symbol", "=", hostile),),
                          select_allow=K.SCHEMA_COLUMNS,
                          filter_allow=K.SCHEMA_COLUMNS,
                          phase=data.Phase.SYNTHETIC)
    assert hostile not in q.sql
    assert q.params == (hostile,)
    with data.SyntheticPhase(env.synth) as ph:
        assert len(ph.select(("id",), (("symbol", "=", hostile),))) == 0


def test_every_operator_runs(env):
    ops = [("id", "=", 1), ("id", "!=", 1), ("id", "<=", 2), ("id", ">=", 2),
           ("id", "<", 2), ("id", ">", 12), ("id", "IN", (1, 2)),
           ("id", "NOT IN", [1, 2]), ("id", "IN", {3, 4}),
           ("excess_1session", "IS NULL", None),
           ("excess_1session", "IS NOT NULL", None),
           ("scoring_session", "!= ''", None), ("id", "IN", ()),
           ("id", "NOT IN", ())]
    expected = [1, 12, 2, 12, 1, 1, 2, 11, 2, 3, 10, 10, 0, 13]
    with data.SyntheticPhase(env.synth) as ph:
        got = [len(ph.select(("id",), (f,))) for f in ops]
    assert got == expected


def test_engine_guard_denies_unlisted_reads(env):
    with data.GatePhase(env.synth) as ph:
        for sql in ("SELECT judgment FROM news_observation",
                    "SELECT COUNT(*) FROM news_observation "
                    "WHERE strength = 1",
                    "SELECT id FROM news_observation ORDER BY net_bp",
                    "SELECT value FROM news_eval_synthetic_meta",
                    "SELECT name FROM sqlite_master",
                    "SELECT max(id) FROM news_observation"):
            with pytest.raises(sqlite3.DatabaseError,
                               match="not authorized|prohibited"):
                ph._run(data.Query(sql, ()))
    with data.RelevancePhase(env.real) as ph:
        with pytest.raises(sqlite3.DatabaseError):
            ph._run(data.Query("SELECT scoring_session FROM "
                               "news_observation", ()))


def test_schema_phase_runs_only_pragma(env, trace):
    with data.SchemaPhase(env.real) as ph:
        assert ph.db_class is data.DbClass.LIVE_REAL
        info = ph.table_info()
        with pytest.raises(sqlite3.DatabaseError):
            ph._conn.execute("SELECT id FROM news_observation").fetchall()
        with pytest.raises(sqlite3.DatabaseError):
            ph._conn.execute("PRAGMA index_list(news_observation)")
        with pytest.raises(sqlite3.DatabaseError):
            ph._conn.execute("PRAGMA table_info(news_eval_synthetic_meta)")
    assert tuple(c.name for c in info) == K.SCHEMA_COLUMNS
    assert trace[0] == "PRAGMA table_info(news_observation)"
    assert all(s.startswith("PRAGMA") for s in trace)


# --------------------------------------------------------------- RELEVANCE

def _expanded(sql: str, params: tuple) -> str:
    for p in params:
        sql = sql.replace("?", f"'{p}'", 1)
    return sql


def test_relevance_population_six_columns_fixed_filter(env, trace):
    with data.RelevancePhase(env.real) as ph:
        rows = ph.relevance_population("2026-10-09")
    assert rows.columns == K.RELEVANCE_COLUMNS
    assert all(len(r) == 6 for r in rows.data)
    # collection, judged, query_date <= 2026-10-09: ids 1-9 and 13
    assert rows.column("id") == (1, 2, 3, 4, 5, 6, 7, 8, 9, 13)
    executed = [s for s in trace if s.startswith("SELECT")]
    assert executed == [_expanded(data.RELEVANCE_SQL,
                                  ("collection", "judged", "2026-10-09"))]


def test_relevance_sql_text_pinned():
    assert data.RELEVANCE_SQL == (
        "SELECT id, symbol, query_date, headline, sector, stratum FROM "
        "news_observation WHERE run_kind = ? AND state = ? AND "
        "query_date <= ? ORDER BY id")


def test_relevance_live_date_fixed_synthetic_free(env, trace):
    with data.RelevancePhase(env.real) as ph:
        before = len(trace)
        with pytest.raises(data.FilterRefused):
            ph.relevance_population("2026-10-10")
        assert len(trace) == before
    with data.RelevancePhase(env.synth) as ph:
        assert len(ph.relevance_population("2026-10-10")) == 11
        for bad in ("2026/10/09", "", None, 20261009):
            with pytest.raises(data.FilterRefused):
                ph.relevance_population(bad)


# -------------------------------------------------------------------- GATE

def test_state_counts_by_query_date(env):
    with data.GatePhase(env.synth) as ph:
        counts = ph.state_counts_by_query_date()
    assert counts == {
        "2026-08-03": {"judged": 6, "source_failed": 1},
        "2026-08-04": {"judged": 2},
        "2026-08-05": {"judged": 1},
        "2026-08-06": {"judged": 1},
        "2026-10-10": {"judged": 1},
    }


def test_judged_session_status_counts_only(env):
    with data.GatePhase(env.synth) as ph:
        status = ph.judged_session_status()
    assert status == {
        None: {"resolved": 1},
        "": {"resolved": 1},
        "2026-08-03": {"resolved": 4},
        "2026-08-04": {"resolved": 2},
        "2026-08-05": {"pending": 1},
        "2026-08-06": {"resolved": 1},
        "2026-10-12": {"resolved": 1},
    }


def test_gate_rows_conditions_and_null_count(env):
    with data.GatePhase(env.synth) as ph:
        g = ph.gate_rows(excluded_query_dates=(), s_star=None)
    # ids 1, 2, 3 (NEUTRAL included), 4, 13, 12; id 5 is NULL excess.
    assert g.scoring_session == ("2026-08-03", "2026-08-03", "2026-08-03",
                                 "2026-08-04", "2026-08-06", "2026-10-12")
    assert g.excess_1session == (0.001, -0.002, 0.003, 0.004, 0.006, 0.005)
    assert g.null_excess_count == 1
    assert all(isinstance(x, float) for x in g.excess_1session)


def test_gate_rows_s_star_and_day_exclusion(env):
    with data.GatePhase(env.synth) as ph:
        g = ph.gate_rows(excluded_query_dates={"2026-08-03"},
                         s_star="2026-08-04")
        g2 = ph.gate_rows(excluded_query_dates=["2026-08-04"],
                          s_star="2026-08-03")
    assert g.scoring_session == ("2026-08-04",)
    assert g.excess_1session == (0.004,)
    assert g.null_excess_count == 1
    assert g2.scoring_session == ("2026-08-03",) * 3
    assert g2.null_excess_count == 0


def test_gate_null_excess_never_zero(env):
    with data.GatePhase(env.synth) as ph:
        g = ph.gate_rows((), None)
    assert len(g.excess_1session) == len(g.scoring_session) == 6
    assert 0.0 not in g.excess_1session


def test_directional_counts_by_cluster_counts_only(env, trace):
    with data.GatePhase(env.synth) as ph:
        counts = ph.directional_counts_by_cluster((), None)
        cut = ph.directional_counts_by_cluster(("2026-08-06",), "2026-08-06")
    assert counts == {"2026-08-03": 2, "2026-08-04": 1, "2026-08-06": 1,
                      "2026-10-12": 1}
    assert cut == {"2026-08-03": 2, "2026-08-04": 1}
    assert all(type(k) is str and type(v) is int for k, v in counts.items())
    naming_judgment = [s for s in trace if "judgment" in s]
    assert len(naming_judgment) == 2
    for s in naming_judgment:
        assert s.startswith("SELECT scoring_session, COUNT(*) FROM")
        assert "GROUP BY scoring_session" in s
        assert "judgment IN ('POSITIVE', 'NEGATIVE')" in s


def test_directional_widening_does_not_leak(env):
    with data.GatePhase(env.synth) as ph:
        ph.directional_counts_by_cluster((), None)
        assert "judgment" not in ph._readable
        with pytest.raises(sqlite3.DatabaseError):
            ph._run(data.Query("SELECT judgment FROM news_observation", ()))


def test_gate_methods_on_unlocked_copy(env):
    env.write_unlock()
    with data.GatePhase(env.copy()) as ph:
        assert ph.directional_counts_by_cluster((), None) == {
            "2026-08-03": 2, "2026-08-04": 1, "2026-08-06": 1,
            "2026-10-12": 1}
        assert ph.gate_rows((), None).null_excess_count == 1


@pytest.mark.parametrize("excluded, s_star", [
    ("2026-08-03", None), (None, None), ((1,), None), ((), ""), ((), 5),
])
def test_gate_bad_arguments_refused(env, excluded, s_star):
    with data.GatePhase(env.synth) as ph:
        with pytest.raises(data.FilterRefused):
            ph.gate_rows(excluded, s_star)
        with pytest.raises(data.FilterRefused):
            ph.directional_counts_by_cluster(excluded, s_star)


# ----------------------------------------------------------------- VERDICT

def test_verdict_select_reads_any_column_on_synthetic(env):
    with data.VerdictPhase(env.synth) as ph:
        rows = ph.select(("id", "judgment", "net_bp", "excess_1session"),
                         (("judgment", "=", "NEGATIVE"),))
    assert rows.column("id") == (2, 13)
    assert rows.as_dicts()[0]["excess_1session"] == -0.002


def test_synthetic_count_by(env):
    with data.SyntheticPhase(env.synth) as ph:
        r = ph.count_by(("judgment",), (("run_kind", "=", "collection"),))
        total = ph.count_by((), ())
    assert r.columns == ("judgment", "count")
    assert dict(r.data) == {None: 1, "NEGATIVE": 2, "NEUTRAL": 1,
                            "POSITIVE": 8}
    assert total.data == ((13,),)


# ------------------------------------------------- schema reconstruction

def test_dump_schema_on_fake_real_round_trips(env, trace):
    text = data.dump_schema(env.real)
    assert trace == ["PRAGMA table_info(news_observation)"]
    a = _UNPATCHED_CONNECT(":memory:")
    b = _UNPATCHED_CONNECT(":memory:")
    a.executescript(text)
    b.executescript(SCHEMA_SQL)
    pragma = "PRAGMA table_info(news_observation)"
    assert a.execute(pragma).fetchall() == b.execute(pragma).fetchall()
    idx = "SELECT name, sql FROM sqlite_master WHERE type='index' ORDER BY name"
    assert a.execute(idx).fetchall() == b.execute(idx).fetchall()
    body = lambda t: t[t.index("CREATE TABLE"):]  # noqa: E731
    assert body(text) == body(SCHEMA_SQL)


def test_schema_sql_matches_store_ddl():
    store = data.store_columns(data._store_schema_text())
    conn = _UNPATCHED_CONNECT(":memory:")
    conn.executescript(SCHEMA_SQL)
    pragma = tuple(data.ColumnInfo(*r) for r in conn.execute(
        "PRAGMA table_info(news_observation)"))
    assert data.compare_with_store(pragma, store) == []
    assert "id INTEGER PRIMARY KEY AUTOINCREMENT" in SCHEMA_SQL
    for name in ("idx_obs_symbol_day", "idx_obs_state", "idx_obs_story"):
        assert name in SCHEMA_SQL


def test_compare_with_store_reports_differences():
    store = data.store_columns(data._store_schema_text())
    changed = list(store)
    changed[13] = data.ColumnInfo(13, "exclusion_reason", "TEXT", 0, None, 0)
    changed.append(data.ColumnInfo(61, "extra_col", "TEXT", 0, None, 0))
    diffs = data.compare_with_store(tuple(changed), store)
    assert "exclusion_reason.notnull: PRAGMA 0 vs store.py 1" in diffs
    assert "exclusion_reason.dflt_value: PRAGMA None vs store.py \"''\"" \
        in diffs
    assert "column extra_col in PRAGMA, not in store.py" in diffs


# ------------------------------------------ C.1 ruling B1: sidecars, immutable

@pytest.mark.parametrize("suffix", data.SIDECAR_SUFFIXES)
@pytest.mark.parametrize("which", ["synth", "copy"])
def test_planted_sidecar_refused_before_connect(env, no_connect, suffix,
                                                which):
    """The guarantee that replaced the header-bytes assertion: a -wal, -shm
    or -journal beside a non-live database refuses every phase and the
    classification, before sqlite3.connect."""
    target = env.synth if which == "synth" else env.copy()
    Path(str(target) + suffix).write_bytes(b"planted")
    env.write_unlock()
    env.write_run_once(target)
    with pytest.raises(data.SidecarPresent):
        data.classify(target)
    for phase_cls in (data.SyntheticPhase, data.RelevancePhase,
                      data.GatePhase, data.VerdictPhase):
        phase = phase_cls(target)
        with pytest.raises(data.SidecarPresent):
            phase.open()
        assert phase._conn is None and phase.db_class is None


def test_sidecar_beside_the_realpath_of_a_symlink_refused(env, no_connect):
    link = env.tmp / "links" / "snap_alias.db"
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(env.synth, link)
    Path(str(env.synth) + "-wal").write_bytes(b"planted")
    with pytest.raises(data.SidecarPresent):
        data.classify(link)


def test_non_live_opens_are_immutable_and_live_opens_are_not(env,
                                                             monkeypatch):
    uris: list[str] = []
    inner = sqlite3.connect

    def record(database, *args, **kwargs):
        uris.append(os.fspath(database))
        return inner(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", record)
    data.classify(env.synth)
    with data.GatePhase(env.synth):
        pass
    with data.RelevancePhase(env.real):
        pass
    assert uris[0].endswith("?mode=ro&immutable=1")
    assert uris[1].endswith("?mode=ro&immutable=1")
    assert uris[2].endswith("?mode=ro") and "immutable" not in uris[2]


def test_wal_mode_copy_is_read_without_creating_a_sidecar(env):
    """A WAL-header database with no sidecar: a plain mode=ro open would
    create -shm beside it; the immutable open reads it and creates none."""
    copy = env.copy()
    conn = _UNPATCHED_CONNECT(copy)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    conn.close()
    assert copy.read_bytes()[18:20] == b"\x02\x02"
    assert data.sidecars(copy) == []
    env.write_unlock()
    with data.GatePhase(copy) as ph:
        assert ph.db_class is data.DbClass.NON_SYNTHETIC
        assert sum(sum(v.values()) for v in
                   ph.state_counts_by_query_date().values()) == 12
    assert data.sidecars(copy) == []


# ------------------------------------- C.1 ruling B2: unlock and marker content

@pytest.mark.parametrize("field, bad", [
    ("schema", None), ("schema", "c2_unlock/2"),
    ("stage", "C.1"), ("stage", None),
    ("approver", ""), ("approver", "   "), ("approver", None), ("approver", 7),
    ("utc_time", "2026-10-20T06:00:00"), ("utc_time", "2026-10-20T06:00:00+00:00"),
    ("utc_time", "2026-10-20Z"), ("utc_time", "2026-13-45T06:00:00Z"),
    ("utc_time", None),
    ("experiment_sha256", "0" * 64), ("experiment_sha256", None),
    ("manifest_sha256", None), ("manifest_sha256", "A" * 64),
    ("manifest_sha256", "0" * 63),
])
def test_unlock_field_refused_and_named(env, field, bad):
    body = valid_unlock(**{field: bad})
    if bad is None:
        del body[field]
    env.unlock.parent.mkdir(parents=True, exist_ok=True)
    env.unlock.write_text(json.dumps(body))
    with pytest.raises(data.UnlockInvalid) as exc:
        data.load_unlock(env.unlock)
    assert exc.value.field == field
    assert repr(field) in str(exc.value)
    with pytest.raises(data.UnlockInvalid):
        with data.GatePhase(env.copy()):
            pass


@pytest.mark.parametrize("text", ["{}", "", "not json", "[1, 2]", "null"])
def test_unlock_existence_alone_is_not_enough(env, text):
    """B2: the file that merely exists (README.md in the audit) is refused."""
    env.unlock.parent.mkdir(parents=True, exist_ok=True)
    env.unlock.write_text(text)
    with pytest.raises(data.UnlockInvalid) as exc:
        with data.GatePhase(env.copy()):
            pass
    assert exc.value.field in ("schema", "json")
    with pytest.raises(data.UnlockInvalid):
        data.load_unlock(data.REPO_ROOT / "README.md")


def test_valid_unlock_loads_and_missing_is_unlock_missing(env):
    with pytest.raises(data.UnlockMissing):
        data.load_unlock(env.unlock)
    env.write_unlock()
    body = data.load_unlock(env.unlock)
    assert body["schema"] == K.UNLOCK_SCHEMA and body["stage"] == "C.2"
    write_unlock(env.unlock, utc_time="2026-10-20T06:00:00.123456Z")
    data.load_unlock(env.unlock)


@pytest.mark.parametrize("overrides, field", [
    ({"schema": "c2_run_once/0"}, "schema"),
    ({"schema": None}, "schema"),
    ({"snapshot_sha256": "0" * 64}, "snapshot_sha256"),
    ({"snapshot_sha256": None}, "snapshot_sha256"),
])
def test_marker_content_refused_and_named(env, overrides, field):
    copy = env.copy()
    env.write_unlock()
    write_marker(env.run_once, copy, **overrides)
    with pytest.raises(data.RunOnceMarkerInvalid) as exc:
        with data.VerdictPhase(copy):
            pass
    assert exc.value.field == field


@pytest.mark.parametrize("text", ["{}", "", "README"])
def test_marker_existence_alone_is_not_enough(env, text):
    copy = env.copy()
    env.write_unlock()
    env.run_once.write_text(text)
    with pytest.raises(data.RunOnceMarkerInvalid):
        with data.VerdictPhase(copy):
            pass


def test_marker_bound_to_the_bytes_opened(env):
    """A marker for one file does not admit another, and a file changed after
    the marker was written is refused."""
    copy = env.copy()
    other = make_db(env.tmp / "other" / "copy.db", _ROWS[:5])
    env.write_unlock()
    env.write_run_once(copy)
    with data.VerdictPhase(copy) as ph:
        assert ph.db_class is data.DbClass.NON_SYNTHETIC
    with pytest.raises(data.RunOnceMarkerInvalid):
        with data.VerdictPhase(other):
            pass
    conn = _UNPATCHED_CONNECT(copy)
    _insert(conn, {"symbol": "ZZZ"})
    conn.commit()
    conn.close()
    with pytest.raises(data.RunOnceMarkerInvalid):
        with data.VerdictPhase(copy):
            pass


def test_verdict_hashes_before_connect(env, monkeypatch):
    copy = env.copy()
    env.write_unlock()
    env.write_run_once(copy)
    order: list[str] = []
    inner_connect, inner_sha = sqlite3.connect, data.sha256_file

    def connect(database, *args, **kwargs):
        order.append("connect")
        return inner_connect(database, *args, **kwargs)

    def sha(path):
        order.append(f"sha256:{Path(path).name}")
        return inner_sha(path)
    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(data, "sha256_file", sha)
    with data.VerdictPhase(copy):
        pass
    assert order.index(f"sha256:{copy.name}") < order.index("connect")


def test_gate_does_not_need_the_marker_but_checks_the_unlock(env):
    copy = env.copy()
    env.unlock.parent.mkdir(parents=True, exist_ok=True)
    env.unlock.write_text("{}")
    with pytest.raises(data.UnlockInvalid):
        with data.GatePhase(copy):
            pass
    env.write_unlock()
    assert not env.run_once.exists()
    with data.GatePhase(copy) as ph:
        assert ph.db_class is data.DbClass.NON_SYNTHETIC


# ------------------------------------------ C.1 ruling B3: the compiled path

def test_compiled_real_path_is_the_repository_database():
    assert data.COMPILED_REAL_DB_PATH == str(data.REPO_ROOT
                                             / "news_experiment.db")
    assert os.path.realpath(data.COMPILED_REAL_DB_PATH) == REPO_REAL_DB
    assert data.COMPILED_UNLOCK_PATH == str(data.REPO_ROOT / "reports"
                                            / "c2_UNLOCK.json")
    assert data.COMPILED_RUN_ONCE_PATH == str(data.REPO_ROOT / "reports"
                                              / "c2_RUN_ONCE.json")


def test_override_adds_a_live_path_and_never_removes_the_compiled_one(
        env, tmp_path, no_connect):
    """The audit's attack: --real-db <nonexistent> made the real file
    NON_SYNTHETIC. Now it stays LIVE_REAL by stat, and every phase that
    never reads it refuses before sqlite3.connect (which raises here)."""
    nowhere = tmp_path / "nowhere" / "news_experiment.db"
    compiled = data.COMPILED_REAL_DB_PATH
    assert data.is_live_real(compiled, nowhere)
    assert data.is_live_real(compiled)            # REAL_DB_PATH patched
    assert data.is_compiled_real(compiled)
    assert data.classify(compiled, nowhere) is data.DbClass.LIVE_REAL
    assert data.is_live_real(env.real, nowhere) is False
    assert data.is_live_real(env.real)            # the fake is added
    env.write_unlock()
    for phase_cls in (data.SyntheticPhase, data.GatePhase,
                      data.VerdictPhase):
        phase = phase_cls(compiled, real_db_path=nowhere,
                          unlock_path=env.unlock, run_once_path=env.unlock)
        with pytest.raises(data.RealDatabaseRefused):
            phase.open()
        assert phase._conn is None


def test_symlink_to_the_compiled_path_stays_live(tmp_path, no_connect):
    link = tmp_path / "alias.db"
    os.symlink(data.COMPILED_REAL_DB_PATH, link)
    try:
        assert data.is_live_real(link, tmp_path / "x.db")
        with pytest.raises(data.RealDatabaseRefused):
            with data.GatePhase(link, real_db_path=tmp_path / "x.db"):
                pass
    finally:
        link.unlink()


# --------------------------------------------------- C.1 ruling S5: test mode

def test_test_mode_reads_the_environment(monkeypatch):
    monkeypatch.delenv(data.TEST_MODE_ENV, raising=False)
    assert not data.is_test_mode()
    assert "--real-db" in data.override_refusal({"--real-db": "x",
                                                 "--unlock": None})
    assert data.override_refusal({"--real-db": None}) is None
    monkeypatch.setenv(data.TEST_MODE_ENV, "0")
    assert not data.is_test_mode()
    monkeypatch.setenv(data.TEST_MODE_ENV, "1")
    assert data.is_test_mode()
    assert data.override_refusal({"--real-db": "x"}) is None
