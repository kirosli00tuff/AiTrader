"""news_eval.gate: the 9.8 gate step (STAGE C.1 Task 5).

Every database here is built in tmp_path from news_eval/schema.sql and
stamped with news_eval.marker; data.REAL_DB_PATH points at a fake "real"
database in tmp_path, and sqlite3.connect refuses the repository's real file.
Test mode (NEWS_EVAL_TEST_MODE=1, C.1 ruling S5) is set by an autouse fixture
so the CLI accepts its test-only flags; the tests of the refusal unset it. A
non-synthetic database needs a manifest of the repository (ruling S2), written
once per module into tmp, and a valid unlock naming its sha256 (ruling B2).
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from news_eval import constants as K
from news_eval import data
from news_eval import freeze
from news_eval import gate
from news_eval import marker

REPO = Path(__file__).resolve().parent.parent
GATE_PY = REPO / "news_eval" / "gate.py"
SCHEMA_SQL = Path(data.SCHEMA_SQL_PATH).read_text()
REPO_REAL_DB = os.path.realpath(data.REAL_DB_PATH)  # never opened
_UNPATCHED_CONNECT = sqlite3.connect
DENY = ("judgment", "strength", "reason", "positive", "negative", "neutral",
        "net_bp", "ret_")
POS, NEG, NEU = K.POSITIVE, K.NEGATIVE, K.NEUTRAL


class ConnectCalled(BaseException):
    """Raised by the patched sqlite3.connect; nothing swallows it."""


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


@pytest.fixture(autouse=True)
def _never_the_repo_real_db(monkeypatch):
    def guarded(database, *args, **kwargs):
        if _touches_repo_real(database):
            raise ConnectCalled(f"test opened the real database: {database}")
        return _UNPATCHED_CONNECT(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", guarded)


@pytest.fixture(autouse=True)
def _test_mode(monkeypatch):
    monkeypatch.setenv(data.TEST_MODE_ENV, "1")


@pytest.fixture(scope="module")
def repo_manifest(tmp_path_factory) -> tuple[Path, str]:
    """A manifest of the repository as it is now (ruling S2): its files and
    the news_eval modules this process imported match it."""
    path = tmp_path_factory.mktemp("manifest") / "manifest.json"
    return path, freeze.write_manifest(path, REPO, head="test")


def write_unlock(path: Path, **overrides) -> Path:
    """A c2_unlock/1 file the loader accepts (ruling B2), with overrides."""
    body = {"schema": K.UNLOCK_SCHEMA, "stage": K.UNLOCK_STAGE,
            "approver": "test operator", "utc_time": "2026-10-20T06:00:00Z",
            "experiment_sha256": data.sha256_file(data.EXPERIMENT_MD_PATH),
            "manifest_sha256": "0" * 64, **overrides}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    fake_real = make_db(tmp_path / "repo" / "news_experiment.db",
                        [row("2026-08-03", 0.001)], stamp=False)
    unlock = tmp_path / "repo" / "reports" / "c2_UNLOCK.json"
    monkeypatch.setattr(data, "REAL_DB_PATH", str(fake_real))
    monkeypatch.setattr(data, "UNLOCK_PATH", str(unlock))
    monkeypatch.setattr(data, "RUN_ONCE_PATH",
                        str(tmp_path / "repo" / "reports" / "c2_RUN_ONCE.json"))
    return {"tmp": tmp_path, "real": fake_real, "unlock": unlock}


# ------------------------------------------------------------------ builders

_BASE = {
    "rule_id": "r", "formation_date": "2026-07-01", "symbol": "AAA",
    "stratum": "S1", "sector": "Technology", "sector_source": "x",
    "state": K.STATE_JUDGED, "exclusion_reason": "", "headline": "h",
    "spec_version": "v", "written_ts": "w",
    "run_kind": K.RUN_KIND_COLLECTION, "outcome_state": K.OUTCOME_RESOLVED,
}


def row(session: str | None, excess: float | None, label: str = POS,
        **overrides) -> dict:
    """A judged, resolved collection row scored at `session`; the
    query_date defaults to the session."""
    out = {**_BASE, "scoring_session": session,
           "query_date": overrides.pop("query_date", session or "2026-08-01"),
           "excess_1session": excess, "judgment": label}
    out.update(overrides)
    return out


def make_db(path: Path, rows: list[dict], stamp: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _UNPATCHED_CONNECT(path)
    try:
        conn.executescript(SCHEMA_SQL)
        for r in rows:
            cols = ", ".join(r)
            conn.execute(f"INSERT INTO news_observation ({cols}) VALUES "
                         f"({', '.join('?' * len(r))})", tuple(r.values()))
        conn.commit()
        if stamp:
            marker.write_marker(conn, "gate-test", 1)
    finally:
        conn.close()
    return path


def sessions(n: int) -> list[str]:
    """n distinct ISO dates (consecutive calendar days from 2026-07-01)."""
    from datetime import date, timedelta
    d0 = date(2026, 7, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def grid_rows(n_sessions: int, per_session: int, spread_bp: float,
              n_neutral: int = 0) -> list[dict]:
    """Every session holds the same values (-spread..+spread bp), so the
    cluster means are equal, MSB is 0 and rho is floored to 0."""
    out = []
    for s in sessions(n_sessions):
        for i in range(per_session):
            y = spread_bp * (2 * i / (per_session - 1) - 1)
            out.append(row(s, y / K.BP_PER_UNIT, POS if i % 2 else NEG))
        for i in range(n_neutral):
            out.append(row(s, 0.0, NEU))
    return out


def read_log(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------- the deny list

def _strings_and_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield "Name", node.id
        elif isinstance(node, ast.Attribute):
            yield "Attribute", node.attr
        elif isinstance(node, ast.arg):
            yield "arg", node.arg
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield "keyword", node.arg
        elif isinstance(node, ast.alias):
            yield "alias", node.name
            if node.asname:
                yield "alias", node.asname
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            yield "def", node.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield "module", node.module
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield "str", node.value  # docstrings and JoinedStr parts too


def test_gate_source_carries_no_deny_list_word():
    tree = ast.parse(GATE_PY.read_text())
    seen = list(_strings_and_names(tree))
    assert len(seen) > 100  # the walk reached the module
    hits = [(kind, text) for kind, text in seen
            for word in DENY if word in text.lower()]
    assert hits == []
    # Comments are outside the AST: check the raw text as well.
    raw = GATE_PY.read_text().lower()
    assert [w for w in DENY if w in raw] == []


def test_deny_walk_catches_each_kind_of_node():
    planted = (
        'import judgment_mod as reason_alias\n'
        'from x import strength\n'
        'def f(positive_arg, *, kw=1):\n'
        '    """negative docstring"""\n'
        '    g(neutral=1)\n'
        '    return obj.net_bp + f"{a}secret_part"\n'
        'class Interpret_Me: pass\n')
    kinds = {kind for kind, text in _strings_and_names(ast.parse(planted))
             for word in DENY if word in text.lower()}
    assert kinds == {"alias", "arg", "str", "keyword", "Attribute", "def"}


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_gate_import_closure_excludes_family_verdict_report():
    seen, todo = set(), ["news_eval.gate"]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = REPO / (mod.replace(".", "/") + ".py")
        if not path.is_file():
            continue
        todo += [m for m in _imports(path) if m.startswith("news_eval")]
    modules = {m for m in seen if (REPO / (m.replace(".", "/") + ".py"))
               .is_file()}
    assert {"news_eval.data", "news_eval.cutoff", "news_eval.stats"} <= modules
    for banned in ("family", "verdict", "report"):
        assert not [m for m in seen if banned in m.split(".")[-1]], seen


# ------------------------------------------------------ known answer by hand

def known_rows() -> list[dict]:
    a, b, c, d = "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"
    return [
        # G: A = 10, 20, 30 bp; B = 40, 60; C = 5, 15, 25, 35.
        row(a, 0.0010, POS), row(a, 0.0020, NEG), row(a, 0.0030, NEU),
        row(b, 0.0040, POS), row(b, 0.0060, NEU),
        row(c, 0.0005, POS), row(c, 0.0015, NEG), row(c, 0.0025, NEG),
        row(c, 0.0035, NEU),
        # A resolved row with NULL excess in B: counted, never read as 0.
        row(b, None, POS),
        # 2026-08-02 has 1 source_failed of 2 rows (0.5): excluded day.
        row(a, 0.0500, POS, query_date="2026-08-02"),
        row(None, None, None, query_date="2026-08-02",
            state=K.STATE_SOURCE_FAILED, outcome_state=K.OUTCOME_PENDING),
        # Session D holds a pending row: S* = C, so D's resolved row is out.
        row(d, 0.0900, POS), row(d, None, NEG,
                                 outcome_state=K.OUTCOME_PENDING),
        # Rows the 9.7 conditions drop.
        row(a, 0.0700, POS, exclusion_reason="duplicate_headline"),
        row(a, 0.0700, POS, run_kind="demonstration"),
        row(a, 0.0700, None, state=K.STATE_MODEL_FAILED),
        row(c, 0.0700, POS, outcome_state=K.OUTCOME_EXCLUDED),
        row("", 0.0700, POS),
    ]


def test_known_answer_by_hand(env):
    db = make_db(env["tmp"] / "known.db", known_rows())
    log = env["tmp"] / "gate.jsonl"
    assert gate.run(db, log) == gate.EXIT_FAIL
    (e,) = read_log(log)
    # N = 9 in C_G = 3 clusters of sizes 3, 2, 4; means 20, 50, 20 bp,
    # grand mean 240/9. Between SS = 1400, within SS = 200 + 200 + 500 = 900.
    msb, msw = 1400 / 2, 900 / 6
    n0 = (9 - (9 + 4 + 16) / 9) / 2                       # 26/9
    rho = (msb - msw) / (msb + (n0 - 1) * msw)            # 4950/8850
    sigma = math.sqrt((1400 + 900) / 8)
    k_eff = (2 ** 2 + 1 ** 2 + 3 ** 2) / 6                # m_c = 2, 1, 3
    required = 11.156 * (sigma / 30) ** 2 * (1 + (k_eff - 1) * rho)
    assert rho == pytest.approx(4950 / 8850, rel=1e-12)
    assert (e["N"], e["C_G"], e["C"], e["M"]) == (9, 3, 3, 6)
    for key, want in (("MSB", msb), ("MSW", msw), ("n0", n0),
                      ("rho_raw", rho), ("rho", rho), ("sigma", sigma),
                      ("k_eff", k_eff), ("required", required)):
        assert e[key] == pytest.approx(want, rel=1e-9), key
    # 11.156 x (287.5 / 900) x (1 + (4/3) x 4950/8850) = 6.2214
    assert e["required"] == pytest.approx(6.2214, abs=1e-4)
    assert e["null_excess_count"] == 1
    assert e["s_star"] == "2026-08-05"
    assert e["s_star_case"] == "before_earliest_nonstale_pending"
    assert e["excluded_query_dates"] == {"2026-08-02": 0.5}
    assert e["status"] == "ok" and e["degenerate_condition"] == ""
    assert e["pass"] is False and e["failing"] == ["C", "M", "REQUIRED"]
    assert e["inputs_sha256"] == sha256(db)
    assert e["db_class"] == "SYNTHETIC"
    assert e["db_path"] == os.path.abspath(db)


def test_rho_floored_at_zero_and_raw_kept(env):
    # Equal cluster means: MSB = 0, rho_raw < 0, rho = 0.
    db = make_db(env["tmp"] / "flat.db", grid_rows(3, 4, 30.0))
    e = gate.evaluate(db)
    assert e["rho_raw"] < 0 and e["rho"] == 0.0
    assert e["MSB"] == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------- pass and each failure

def test_pass(env):
    db = make_db(env["tmp"] / "pass.db", grid_rows(60, 20, 50.0, n_neutral=2))
    log = env["tmp"] / "g.jsonl"
    assert gate.run(db, log) == gate.EXIT_PASS
    (e,) = read_log(log)
    assert e["pass"] is True and e["failing"] == []
    assert (e["C"], e["C_G"], e["M"], e["N"]) == (60, 60, 1200, 1320)
    assert e["k_eff"] == pytest.approx(20.0)
    assert e["rho"] == 0.0
    assert e["required"] == pytest.approx(
        11.156 * (e["sigma"] / 30) ** 2, rel=1e-12)


def test_fail_c_only(env):
    db = make_db(env["tmp"] / "c.db", grid_rows(59, 20, 50.0))
    log = env["tmp"] / "g.jsonl"
    assert gate.run(db, log) == gate.EXIT_FAIL
    (e,) = read_log(log)
    assert e["C"] == 59 and e["M"] == 1180 and e["failing"] == ["C"]


def test_fail_m_only(env):
    db = make_db(env["tmp"] / "m.db", grid_rows(60, 16, 50.0))
    e = gate.evaluate(db)
    assert e["M"] == 960 and e["failing"] == ["M"] and e["pass"] is False


def test_fail_required_only(env):
    db = make_db(env["tmp"] / "req.db", grid_rows(60, 20, 700.0))
    e = gate.evaluate(db)
    assert e["M"] == 1200 and e["required"] > 1200
    assert e["failing"] == ["REQUIRED"] and e["pass"] is False


def test_c_counts_directional_clusters_not_gate_clusters(env):
    # 60 gate clusters, but one of them holds only labelled-NEUTRAL rows.
    rows = grid_rows(59, 20, 50.0)
    rows += [row("2026-12-30", 0.001, NEU), row("2026-12-30", -0.001, NEU)]
    e = gate.evaluate(make_db(env["tmp"] / "cdir.db", rows))
    assert e["C_G"] == 60 and e["C"] == 59 and e["failing"] == ["C"]


def test_degenerate_single_cluster(env):
    db = make_db(env["tmp"] / "one.db",
                 [row("2026-08-03", 0.001), row("2026-08-03", 0.002, NEG)])
    log = env["tmp"] / "g.jsonl"
    assert gate.run(db, log) == gate.EXIT_FAIL
    (e,) = read_log(log)
    assert e["status"] == "degenerate"
    assert e["degenerate_condition"] == "fewer than 2 gate clusters"
    assert e["pass"] is False and e["sigma"] is None and e["rho"] is None


def test_empty_analysis_set_never_asks_for_unfiltered_rows(env, monkeypatch):
    # The first session holds a pending row: S* is None, the set is empty.
    def boom(*args, **kwargs):
        raise AssertionError("loader asked for rows without a cutoff")
    monkeypatch.setattr(data.GatePhase, "gate_rows", boom)
    monkeypatch.setattr(data.GatePhase, "directional_counts_by_cluster", boom)
    db = make_db(env["tmp"] / "none.db", [
        row("2026-08-03", None, POS, outcome_state=K.OUTCOME_PENDING),
        row("2026-08-04", 0.001), row("2026-08-05", 0.002)])
    e = gate.evaluate(db)
    assert e["s_star"] is None
    assert e["s_star_case"] == "earliest_nonstale_pending_is_first_session"
    assert e["N"] == 0 and e["status"] == "degenerate"


# ------------------------------------------ day rule, S*, NULL excess (D25)

def test_source_failed_day_excluded_from_g(env):
    base = grid_rows(3, 4, 30.0)
    extra = [row("2026-07-02", 0.09, POS, query_date="2026-06-30"),
             row(None, None, None, query_date="2026-06-30",
                 state=K.STATE_SOURCE_FAILED,
                 outcome_state=K.OUTCOME_PENDING)]
    with_day = gate.evaluate(make_db(env["tmp"] / "a.db", base + extra))
    without = gate.evaluate(make_db(env["tmp"] / "b.db", base))
    assert with_day["excluded_query_dates"] == {"2026-06-30": 0.5}
    assert with_day["N"] == without["N"] == 12
    assert with_day["sigma"] == without["sigma"]


def test_day_at_exactly_twenty_percent_is_kept(env):
    rows = grid_rows(3, 4, 30.0)
    # 2026-07-01: 4 judged + 1 source_failed = 0.20 exactly: kept.
    rows.append(row(None, None, None, query_date="2026-07-01",
                    state=K.STATE_SOURCE_FAILED,
                    outcome_state=K.OUTCOME_PENDING))
    e = gate.evaluate(make_db(env["tmp"] / "edge.db", rows))
    assert e["excluded_query_dates"] == {} and e["N"] == 12


def test_s_star_applied_and_stale_pending_reported(env):
    rows = grid_rows(8, 4, 30.0)
    s = sessions(10)
    rows.append(row(s[1], None, POS, outcome_state=K.OUTCOME_PENDING))  # stale
    rows.append(row(s[8], None, POS, outcome_state=K.OUTCOME_PENDING))
    rows.append(row(s[9], 0.5, POS))   # resolved after S*: outside G
    e = gate.evaluate(make_db(env["tmp"] / "s.db", rows))
    assert e["s_star"] == s[7]
    assert e["stale_pending_count"] == 1
    assert e["stale_pending_sessions"] == [[s[1], 1]]
    assert e["latest_resolved_session"] == s[9]
    assert e["N"] == 32 and e["C_G"] == 8


def test_null_excess_counted_not_zeroed(env):
    base = grid_rows(3, 4, 30.0)
    nulls = [row("2026-07-01", None, POS), row("2026-07-02", None, NEU)]
    e = gate.evaluate(make_db(env["tmp"] / "n.db", base + nulls))
    ref = gate.evaluate(make_db(env["tmp"] / "r.db", base))
    assert e["null_excess_count"] == 2 and ref["null_excess_count"] == 0
    assert e["N"] == ref["N"] == 12 and e["M"] == ref["M"]
    for key in ("sigma", "MSB", "MSW", "rho_raw", "k_eff", "required"):
        assert e[key] == ref[key], key


# ---------------------------------------------------------- append-only

def test_append_only_two_runs(env):
    db = make_db(env["tmp"] / "k.db", known_rows())
    log = env["tmp"] / "logs" / "gate.jsonl"
    gate.run(db, log)
    first = log.read_bytes()
    assert first.endswith(b"\n") and first.count(b"\n") == 1
    gate.run(db, log)
    both = log.read_bytes()
    assert both.startswith(first) and both.count(b"\n") == 2
    lines = both.decode().splitlines()
    for line in lines:
        assert line == json.dumps(json.loads(line), sort_keys=True,
                                  allow_nan=False)
    a, b = (json.loads(x) for x in lines)
    a.pop("utc_time"), b.pop("utc_time")
    assert a == b


def test_unterminated_log_refused_and_left_alone(env):
    db = make_db(env["tmp"] / "k.db", known_rows())
    log = env["tmp"] / "gate.jsonl"
    log.write_bytes(b'{"partial": 1}')
    assert gate.run(db, log) == gate.EXIT_REFUSED
    assert log.read_bytes() == b'{"partial": 1}'


def test_log_entry_fields(env):
    e = gate.evaluate(make_db(env["tmp"] / "k.db", known_rows()))
    for key in ("utc_time", "db_path", "inputs_sha256", "s_star",
                "excluded_query_dates", "stale_pending_count", "C", "C_G",
                "N", "M", "sigma", "MSB", "MSW", "n0", "rho_raw", "rho",
                "k_eff", "required", "pass", "failing", "null_excess_count",
                "status", "manifest_sha256", "test_mode"):
        assert key in e, key
    assert e["test_mode"] is (os.environ.get(data.TEST_MODE_ENV) == "1")
    assert set(e["failing"]) <= {"C", "M", "REQUIRED"}


# ------------------------------------------------------------- refusals

def test_refuses_the_live_database_and_appends_nothing(env):
    log = env["tmp"] / "gate.jsonl"
    assert gate.run(env["real"], log) == gate.EXIT_REFUSED
    assert not log.exists()
    write_unlock(env["unlock"])             # D21: unlock does not admit it
    assert gate.run(env["real"], log) == gate.EXIT_REFUSED
    assert not log.exists()


def test_refuses_a_symlink_to_the_live_database(env):
    link = env["tmp"] / "alias.db"
    os.symlink(env["real"], link)
    log = env["tmp"] / "gate.jsonl"
    assert gate.run(link, log) == gate.EXIT_REFUSED and not log.exists()


def test_non_synthetic_copy_needs_unlock(env, repo_manifest):
    manifest, digest = repo_manifest
    src = make_db(env["tmp"] / "k.db", known_rows(), stamp=False)
    snap = env["tmp"] / "snapshot" / "copy.db"
    snap.parent.mkdir()
    shutil.copy2(src, snap)
    log = env["tmp"] / "gate.jsonl"
    assert gate.run(snap, log, manifest_path=manifest) == gate.EXIT_REFUSED
    assert not log.exists()
    env["unlock"].parent.mkdir(parents=True, exist_ok=True)
    env["unlock"].write_text("{}")         # existence alone (ruling B2)
    assert gate.run(snap, log, manifest_path=manifest) == gate.EXIT_REFUSED
    assert not log.exists()
    write_unlock(env["unlock"], manifest_sha256=digest)
    assert gate.run(snap, log, manifest_path=manifest) == gate.EXIT_FAIL
    (e,) = read_log(log)
    assert e["db_class"] == "NON_SYNTHETIC" and e["N"] == 9
    assert e["inputs_sha256"] == sha256(snap)
    assert e["manifest_sha256"] == digest


def test_explicit_real_db_and_unlock_overrides(env, tmp_path, repo_manifest):
    manifest, digest = repo_manifest
    db = make_db(tmp_path / "other_real.db", known_rows(), stamp=False)
    log = tmp_path / "gate.jsonl"
    assert gate.run(db, log, real_db_path=db) == gate.EXIT_REFUSED
    unlock = write_unlock(tmp_path / "my_unlock.json",
                          manifest_sha256=digest)
    assert gate.run(db, log, unlock_path=unlock,
                    manifest_path=manifest) == gate.EXIT_FAIL


def test_missing_database_refused(env):
    log = env["tmp"] / "gate.jsonl"
    assert gate.run(env["tmp"] / "absent.db", log) == gate.EXIT_REFUSED
    assert not log.exists()


def test_inputs_sha256_is_the_file_hash(env):
    db = make_db(env["tmp"] / "k.db", known_rows())
    assert gate.evaluate(db)["inputs_sha256"] == sha256(db)


# ------------------------------------------------------------------ CLI

def test_cli_main_in_process(env):
    db = make_db(env["tmp"] / "pass.db", grid_rows(60, 20, 50.0))
    log = env["tmp"] / "g.jsonl"
    code = gate._main(["--db", str(db), "--log", str(log),
                       "--real-db", str(env["real"]),
                       "--unlock", str(env["unlock"])])
    assert code == 0 and read_log(log)[0]["pass"] is True


def test_cli_module_entry_point(env):
    db = make_db(env["tmp"] / "k.db", known_rows())
    log = env["tmp"] / "g.jsonl"
    environ = {**os.environ, data.TEST_MODE_ENV: "1",
               "PYTHONPYCACHEPREFIX": os.path.expanduser(
                   "~/.cache/news_eval_pyc")}
    proc = subprocess.run(
        [sys.executable, "-m", "news_eval.gate", "--db", str(db),
         "--log", str(log), "--real-db", str(env["real"]),
         "--unlock", str(env["unlock"])],
        cwd=REPO, env=environ, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1, proc.stderr
    assert read_log(log)[0]["N"] == 9
    proc = subprocess.run(
        [sys.executable, "-m", "news_eval.gate", "--db", str(env["real"]),
         "--log", str(log), "--real-db", str(env["real"])],
        cwd=REPO, env=environ, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2 and "REFUSED" in proc.stderr
    assert len(read_log(log)) == 1


# ------------------------------- C.1 rulings S2, B2, S5: manifest and flags

def _copy_non_synthetic(env) -> Path:
    src = make_db(env["tmp"] / "src.db", known_rows(), stamp=False)
    snap = env["tmp"] / "snapshot" / "copy.db"
    snap.parent.mkdir(exist_ok=True)
    shutil.copy2(src, snap)
    return snap


def _tampered(manifest: Path, tmp: Path, rel: str) -> Path:
    m = json.loads(manifest.read_text())
    next(e for e in m["files"] if e["path"] == rel)["sha256"] = "f" * 64
    out = tmp / "tampered_manifest.json"
    out.write_text(json.dumps(m))
    return out


def test_synthetic_entry_without_manifest_has_null_sha(env):
    e = gate.evaluate(make_db(env["tmp"] / "k.db", known_rows()))
    assert e["db_class"] == "SYNTHETIC" and e["manifest_sha256"] is None


def test_synthetic_with_a_manifest_runs_the_check(env, repo_manifest):
    manifest, digest = repo_manifest
    db = make_db(env["tmp"] / "k.db", known_rows())
    assert gate.evaluate(db, manifest_path=manifest)["manifest_sha256"] \
        == digest
    bad = _tampered(manifest, env["tmp"], "news_eval/stats.py")
    log = env["tmp"] / "g.jsonl"
    assert gate.run(db, log, manifest_path=bad) == gate.EXIT_REFUSED
    assert not log.exists()


@pytest.mark.parametrize("rel", ["news_eval/gate.py", "news_eval/cutoff.py",
                                 "EXPERIMENT.md"])
def test_non_synthetic_refused_on_any_manifest_difference_before_reading(
        env, repo_manifest, monkeypatch, rel, capsys):
    manifest, digest = repo_manifest
    snap = _copy_non_synthetic(env)
    write_unlock(env["unlock"], manifest_sha256=digest)
    bad = _tampered(manifest, env["tmp"], rel) if rel != "EXPERIMENT.md" \
        else None
    if bad is None:  # an input entry, not a files entry
        m = json.loads(manifest.read_text())
        next(e for e in m["inputs"] if e["path"] == rel)["bytes"] = 1
        bad = env["tmp"] / "tampered_inputs.json"
        bad.write_text(json.dumps(m))
    reads = []
    monkeypatch.setattr(data.GatePhase, "state_counts_by_query_date",
                        lambda self: reads.append(1) or {})
    log = env["tmp"] / "g.jsonl"
    assert gate.run(snap, log, manifest_path=bad) == gate.EXIT_REFUSED
    assert "manifest" in capsys.readouterr().err
    assert reads == [] and not log.exists()


def test_non_synthetic_default_manifest_is_the_registered_one(env,
                                                              monkeypatch):
    """Without a manifest path the gate checks reports/c1_harness_freeze.json
    under freeze.REPO_ROOT; the unlock here names no manifest, so the run is
    refused before and after the freeze alike."""
    snap = _copy_non_synthetic(env)
    write_unlock(env["unlock"])
    seen = []
    real_verify = freeze.verify

    def spy(path, root):
        seen.append((Path(path), Path(root)))
        return real_verify(path, root)
    monkeypatch.setattr(freeze, "verify", spy)
    log = env["tmp"] / "g.jsonl"
    assert gate.run(snap, log) == gate.EXIT_REFUSED and not log.exists()
    assert seen == [(freeze.REPO_ROOT / freeze.MANIFEST_REL,
                     freeze.REPO_ROOT)]


def test_unlock_naming_another_manifest_refused(env, repo_manifest):
    manifest, digest = repo_manifest
    snap = _copy_non_synthetic(env)
    write_unlock(env["unlock"], manifest_sha256="0" * 64)
    with pytest.raises(data.UnlockInvalid) as exc:
        gate.evaluate(snap, manifest_path=manifest)
    assert exc.value.field == "manifest_sha256"
    write_unlock(env["unlock"], manifest_sha256=digest)
    assert gate.evaluate(snap, manifest_path=manifest)["manifest_sha256"] \
        == digest


def test_loaded_module_mismatch_refuses_a_non_synthetic_gate(
        env, repo_manifest, monkeypatch):
    """Ruling S3 through S2: a news_eval module loaded from outside the
    frozen tree fails the gate's manifest check."""
    manifest, digest = repo_manifest
    snap = _copy_non_synthetic(env)
    write_unlock(env["unlock"], manifest_sha256=digest)
    stray = env["tmp"] / "stray_module.py"
    stray.write_text("X = 1\n")
    monkeypatch.setitem(sys.modules, "news_eval.zz_stray",
                        type(sys)("news_eval.zz_stray"))
    sys.modules["news_eval.zz_stray"].__file__ = str(stray)
    with pytest.raises(gate.GateRefused, match="zz_stray"):
        gate.evaluate(snap, manifest_path=manifest)


def test_planted_wal_refuses_the_gate(env, repo_manifest):
    """Ruling B1 through the GATE phase: a -wal beside the snapshot."""
    manifest, digest = repo_manifest
    snap = _copy_non_synthetic(env)
    write_unlock(env["unlock"], manifest_sha256=digest)
    Path(str(snap) + "-wal").write_bytes(b"planted")
    log = env["tmp"] / "g.jsonl"
    assert gate.run(snap, log, manifest_path=manifest) == gate.EXIT_REFUSED
    assert not log.exists()


@pytest.mark.parametrize("flag", ["--real-db", "--unlock", "--manifest"])
def test_cli_test_only_flags_refused_outside_test_mode(env, monkeypatch,
                                                       capsys, flag):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    db = make_db(env["tmp"] / "pass.db", grid_rows(60, 20, 50.0))
    log = env["tmp"] / "g.jsonl"
    assert gate._main(["--db", str(db), "--log", str(log), flag,
                       str(env["tmp"] / "x")]) == gate.EXIT_REFUSED
    err = capsys.readouterr().err
    assert flag in err and "test mode" in err and not log.exists()
    assert gate._main(["--db", str(db), "--log", str(log)]) == gate.EXIT_PASS


def test_cli_module_refuses_flags_without_test_mode(env):
    db = make_db(env["tmp"] / "k.db", known_rows())
    log = env["tmp"] / "g.jsonl"
    environ = {k: v for k, v in os.environ.items()
               if k != data.TEST_MODE_ENV}
    environ["PYTHONPYCACHEPREFIX"] = os.path.expanduser(
        "~/.cache/news_eval_pyc")
    proc = subprocess.run(
        [sys.executable, "-m", "news_eval.gate", "--db", str(db),
         "--log", str(log), "--real-db", str(env["real"])],
        cwd=REPO, env=environ, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2 and "--real-db" in proc.stderr
    assert not log.exists()


# ----------------------------------- news_eval.synthetic scenarios (Task 2)

try:
    from news_eval import synthetic as _synthetic
    _SCENARIOS = tuple(_synthetic.SCENARIOS)
except Exception:  # the generator is optional for this file
    _synthetic, _SCENARIOS = None, ()


def _independent_gate(db: Path, s_star: str, excluded: set[str]) -> dict:
    """9.8 recomputed from every row through the SYNTHETIC phase, with its
    own filter and its own ANOVA, sharing no code with gate or stats."""
    cols = ("run_kind", "state", "outcome_state", "exclusion_reason",
            "excess_1session", "scoring_session", "query_date", "judgment")
    with data.open_phase("SYNTHETIC", db) as ph:
        rows = ph.select(cols).as_dicts()
    g = [r for r in rows if r["run_kind"] == "collection"
         and r["state"] == "judged" and r["outcome_state"] == "resolved"
         and r["exclusion_reason"] == "" and r["scoring_session"]
         and r["query_date"] not in excluded
         and r["scoring_session"] <= s_star]
    nulls = sum(1 for r in g if r["excess_1session"] is None)
    g = [r for r in g if r["excess_1session"] is not None]
    by: dict[str, list[float]] = {}
    m_c: dict[str, int] = {}
    for r in g:
        by.setdefault(r["scoring_session"], []).append(
            10_000.0 * r["excess_1session"])
        if r["judgment"] in (POS, NEG):
            m_c[r["scoring_session"]] = m_c.get(r["scoring_session"], 0) + 1
    y = [v for vs in by.values() for v in vs]
    n, c = len(y), len(by)
    grand = sum(y) / n
    msb = sum(len(v) * (sum(v) / len(v) - grand) ** 2
              for v in by.values()) / (c - 1)
    msw = sum((x - sum(v) / len(v)) ** 2
              for v in by.values() for x in v) / (n - c)
    n0 = (n - sum(len(v) ** 2 for v in by.values()) / n) / (c - 1)
    rho = max(0.0, (msb - msw) / (msb + (n0 - 1) * msw))
    sigma = math.sqrt(sum((x - grand) ** 2 for x in y) / (n - 1))
    m = sum(m_c.values())
    k_eff = sum(v * v for v in m_c.values()) / m
    return {"N": n, "C_G": c, "C": len(m_c), "M": m, "MSB": msb, "MSW": msw,
            "n0": n0, "rho": rho, "sigma": sigma, "k_eff": k_eff,
            "required": 11.156 * (sigma / 30) ** 2 * (1 + (k_eff - 1) * rho),
            "null_excess_count": nulls}


@pytest.mark.skipif(not _SCENARIOS, reason="news_eval.synthetic unavailable")
@pytest.mark.parametrize("name", _SCENARIOS)
def test_synthetic_scenario_gate(env, name):
    db = env["tmp"] / f"{name}.db"
    summary = _synthetic.build(name, db)
    log = env["tmp"] / "g.jsonl"
    code = gate.run(db, log)
    (e,) = read_log(log)
    want = _synthetic.SCENARIOS[name].expected["gate"]
    assert e["pass"] is (want["status"] == "PASS")
    assert code == (gate.EXIT_PASS if e["pass"] else gate.EXIT_FAIL)
    assert e["failing"] == list(want["failing"])
    assert e["s_star"] == summary["s_star"]
    assert sorted(e["excluded_query_dates"]) == summary["excluded_query_dates"]
    assert [s for s, _ in e["stale_pending_sessions"]] == \
        summary["stale_pending_sessions"]
    assert e["N"] == summary["gate_rows"]
    assert e["M"] == summary["analysis_scored"]
    assert e["C"] == summary["analysis_clusters"]
    ref = _independent_gate(db, e["s_star"], set(e["excluded_query_dates"]))
    for key in ("N", "C_G", "C", "M", "null_excess_count"):
        assert e[key] == ref[key], key
    for key in ("MSB", "MSW", "n0", "rho", "sigma", "k_eff", "required"):
        assert e[key] == pytest.approx(ref[key], rel=1e-9), key
