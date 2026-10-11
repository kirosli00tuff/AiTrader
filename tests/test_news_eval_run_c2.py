"""Tests for news_eval/run_c2.py, the C.2 runner (STAGE C.1 Task 6; Amendment 9.7, 9.12, 9.15).

Everything runs in tmp_path on synthetic databases. A fake "live" database in
tmp_path stands in for news_experiment.db (data.REAL_DB_PATH points at it);
the unlock file, the run-once marker, the manifest, the gate log and the
relevance summary are all tmp_path files. The repository's real database is
never opened (sqlite3.connect is guarded) and reports/c2* is never created.

End to end: S-EFFECT on a synthetic snapshot (twice, in separate directories,
for the byte-identical results.json) and S-NULL on a NON-synthetic snapshot
(the C.2 shape: the VERDICT phase then needs the unlock file and the marker).

Test mode (NEWS_EVAL_TEST_MODE=1, C.1 ruling S5) is set by an autouse fixture
so the runner accepts its path overrides; the tests of the refusals unset it.
The MemAvailable reader (ruling S7) is replaced by a fixed 8,192 MB except in
the tests of the memory precondition. The unlock file is a valid c2_unlock/1
object naming the staged manifest (ruling B2).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from news_eval import constants as K
from news_eval import cutoff
from news_eval import data
from news_eval import envcheck
from news_eval import family
from news_eval import freeze
from news_eval import gate
from news_eval import marker
from news_eval import run_c2
from news_eval import synthetic

REPO = freeze.REPO_ROOT
REPO_REAL_DB = os.path.realpath(data.REAL_DB_PATH)  # never opened
C2_PATHS = (REPO / "reports" / "c2_UNLOCK.json",
            REPO / "reports" / "c2_RUN_ONCE.json", REPO / "reports" / "c2")
_UNPATCHED_CONNECT = sqlite3.connect
_ORIGINAL_MEM_READER = run_c2._mem_available_mb  # before any patch
EXPECTED_ORDER = ("numpy_sane", "manifest", "unlock", "marker_absent",
                  "snapshot", "s_star", "gate_pass", "relevance_summary",
                  "outputs_absent", "memory")
PLENTY_MB = 8192.0


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


def _guarded_connect(database, *args, **kwargs):
    if _touches_repo_real(database):
        raise ConnectCalled(f"test opened the real database: {database}")
    return _UNPATCHED_CONNECT(database, *args, **kwargs)


@pytest.fixture(autouse=True)
def _guards(monkeypatch, tmp_path):
    """Never the repository's real database; never reports/c2*. Test mode
    on; MemAvailable fixed (ruling S7)."""
    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)
    monkeypatch.setattr(data, "UNLOCK_PATH", str(tmp_path / "dflt_unlock"))
    monkeypatch.setattr(data, "RUN_ONCE_PATH", str(tmp_path / "dflt_marker"))
    monkeypatch.setenv(data.TEST_MODE_ENV, "1")
    monkeypatch.setattr(run_c2, "_mem_available_mb", lambda: PLENTY_MB)
    before = [p.exists() for p in C2_PATHS]
    yield
    assert [p.exists() for p in C2_PATHS] == before == [False] * 3


def write_unlock(path: Path, **overrides) -> Path:
    """A c2_unlock/1 file the loader accepts (ruling B2), with overrides."""
    body = {"schema": K.UNLOCK_SCHEMA, "stage": K.UNLOCK_STAGE,
            "approver": "test operator", "utc_time": "2026-10-20T06:00:00Z",
            "experiment_sha256": data.sha256_file(data.EXPERIMENT_MD_PATH),
            "manifest_sha256": "0" * 64, **overrides}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body) + "\n")
    return path


# ------------------------------------------------------------------ staging

@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    out = {}
    for name in ("S-EFFECT", "S-NULL"):
        out[name] = base / f"{name}.db"
        synthetic.build(name, out[name])
    return out


def _demark(path: Path) -> None:
    """Strip the synthetic marker: the copy classifies NON_SYNTHETIC, as the
    real C.2 snapshot does."""
    conn = _UNPATCHED_CONNECT(path)
    try:
        conn.execute("PRAGMA application_id = 0")
        conn.execute(f"DROP TABLE {marker.META_TABLE}")
        conn.commit()
    finally:
        conn.close()


RELEVANCE_FIXTURE = {
    "schema": run_c2.RELEVANCE_SCHEMA, "n_sample": 200, "grades_order": [],
    "agreement_opus_fable": {"raw_agreement": 0.9, "n_agree": 180,
                             "n_disagree": 20, "cohens_kappa": 0.81},
    "variants": {}, "rates": {}, "note": "fixture",
}


def stage(root: Path, live_src: Path, monkeypatch, *, demark: bool = False,
          gate_pass: bool = True) -> dict:
    """A complete pre-C.2 state under `root`: live db, unlock, snapshot,
    gate log, relevance summary, manifest. Returns the run argv and paths."""
    live = root / "live" / "live.db"
    live.parent.mkdir(parents=True)
    shutil.copyfile(live_src, live)
    if demark:
        _demark(live)
    monkeypatch.setattr(data, "REAL_DB_PATH", str(live))
    manifest = root / "manifest.json"
    manifest_sha = freeze.write_manifest(manifest, REPO, head="test")
    c2 = root / "c2"
    c2.mkdir()
    unlock = write_unlock(c2 / "UNLOCK.json", manifest_sha256=manifest_sha)
    snap_dir = root / "snap"
    rc = run_c2.main(["snapshot", "--source", str(live), "--out-dir",
                      str(snap_dir), "--unlock", str(unlock), "--real-db",
                      str(live)])
    assert rc == 0
    snapshot = snap_dir / run_c2.SNAPSHOT_NAME
    gate_log = root / "gate.jsonl"
    if gate_pass:
        assert gate.run(snapshot, gate_log, real_db_path=live,
                        unlock_path=unlock,
                        manifest_path=manifest) == gate.EXIT_PASS
    relevance_json = root / "relevance.json"
    relevance_json.write_text(json.dumps(RELEVANCE_FIXTURE))
    paths = {"root": root, "live": live, "unlock": unlock,
             "manifest_sha": manifest_sha,
             "marker": c2 / "RUN_ONCE.json", "snapshot": snapshot,
             "snap_dir": snap_dir, "gate_log": gate_log,
             "relevance": relevance_json, "manifest": manifest,
             "out": root / "out"}
    paths["argv"] = [
        "run", "--snapshot", str(snapshot), "--out-dir", str(paths["out"]),
        "--gate-log", str(gate_log), "--relevance-summary",
        str(relevance_json), "--manifest", str(manifest), "--unlock",
        str(unlock), "--marker", str(paths["marker"]), "--repo-root",
        str(REPO), "--real-db", str(live)]
    return paths


def tree(root: Path) -> dict[str, tuple[int, int, int]]:
    """Every path under root with (size, mtime_ns, mode): 'nothing written'."""
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns,
                                               st.st_mode)
    return out


def refuses(paths: dict, capsys, check: str) -> None:
    before = tree(paths["root"])
    rc = run_c2.main(paths["argv"])
    err = capsys.readouterr().err
    assert rc == run_c2.EXIT_REFUSED, err
    assert f"precondition {check}:" in err, err
    assert tree(paths["root"]) == before
    assert not paths["marker"].exists() or check == "marker_absent"


def config(paths: dict) -> run_c2.RunConfig:
    return run_c2._config(run_c2._parser().parse_args(paths["argv"]),
                          paths["argv"])


@pytest.fixture()
def staged(tmp_path, built, monkeypatch) -> dict:
    return stage(tmp_path, built["S-EFFECT"], monkeypatch)


# --------------------------------------------------------------- end to end

def _readings_match(decision: dict, scenario: str) -> None:
    expected = synthetic.SCENARIOS[scenario].expected["readings"]
    for reading in ("primary", "sensitivity"):
        got = decision["readings"][reading]
        exp = expected[reading]
        assert got["gross"]["gross_reading"] == exp["gross"]
        assert [r["outcome"] for r in got["rows"]] == list(exp["rows"])
        assert {t: got["statuses"][t] for t in ("P1", "P2", "P3", "P4")} \
            == dict(exp["statuses"])
        # Task 7: the null determination and the pinned E-test statuses too.
        assert got["null_informative"] is exp["null_informative"]
        assert {t: got["statuses"][t] for t in exp["e_statuses"]} \
            == dict(exp["e_statuses"])


@pytest.fixture(scope="module")
def effect_runs(tmp_path_factory, built) -> list[dict]:
    """S-EFFECT run end to end in two separate directories (real settings:
    10,000 draws and permutations)."""
    runs = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sqlite3, "connect", _guarded_connect)
        mp.setenv(data.TEST_MODE_ENV, "1")
        mp.setattr(run_c2, "_mem_available_mb", lambda: PLENTY_MB)
        for i in range(2):
            root = tmp_path_factory.mktemp(f"effect{i}")
            mp.setattr(data, "UNLOCK_PATH", str(root / "dflt_unlock"))
            mp.setattr(data, "RUN_ONCE_PATH", str(root / "dflt_marker"))
            paths = stage(root, built["S-EFFECT"], mp)
            paths["rc"] = run_c2.main(paths["argv"])
            runs.append(paths)
    return runs


def test_end_to_end_s_effect(effect_runs, capsys, monkeypatch):
    paths = effect_runs[0]
    assert paths["rc"] == run_c2.EXIT_OK
    out = paths["out"]
    assert sorted(p.name for p in out.iterdir()) == sorted(
        [run_c2.RESULTS_NAME, run_c2.RUN_META_NAME, run_c2.VERDICT_NAME])
    doc = json.loads((out / run_c2.RESULTS_NAME).read_text())
    _readings_match(doc["decision"], "S-EFFECT")
    assert doc["companion_horizons"] is None and not doc["companion_computed"]
    verdict_md = (out / run_c2.VERDICT_NAME).read_text()
    assert doc["decision"]["summary"] in verdict_md
    assert "the pipeline predicts" in verdict_md
    meta = json.loads((out / run_c2.RUN_META_NAME).read_text())
    snap_sha = run_c2.sha256_file(paths["snapshot"])
    assert meta["hashes"]["snapshot_sha256"] == snap_sha
    assert meta["hashes"]["manifest_sha256"] == run_c2.sha256_file(
        paths["manifest"])
    assert meta["outputs"][run_c2.RESULTS_NAME] == run_c2.sha256_file(
        out / run_c2.RESULTS_NAME)
    assert meta["successor_condition_9_12"]["holds"] is False
    mark = json.loads(paths["marker"].read_text())
    assert mark["schema"] == K.RUN_ONCE_SCHEMA == "c2_run_once/1"
    assert mark["snapshot_sha256"] == snap_sha
    # Rulings B1, S1, S4, S7, N3: the provenance run_meta now carries.
    assert meta["sidecars_absent"] is True
    assert meta["snapshot"]["sidecars_absent"] is True
    assert meta["snapshot"]["source_st_size"] == paths["live"].stat().st_size
    assert meta["snapshot"]["source_realpath"] == os.path.realpath(
        paths["live"])
    assert len(meta["snapshot_identity"]) == 4
    assert set(meta["thread_env"]) == set(run_c2.THREAD_ENV_VARS)
    assert meta["thread_env"]["OPENBLAS_NUM_THREADS"] == os.environ.get(
        "OPENBLAS_NUM_THREADS")
    assert meta["versions"]["sqlite"] == sqlite3.sqlite_version
    assert meta["versions"]["numpy_blas"] == freeze.blas_info()
    assert meta["mem_available_mb"] == PLENTY_MB
    assert meta["test_mode"] is True
    assert meta["unlock"]["manifest_sha256"] == paths["manifest_sha"]
    assert meta["gate_entry"]["manifest_sha256"] == paths["manifest_sha"]
    assert mark["manifest_sha256"] == meta["hashes"]["manifest_sha256"]
    assert mark["s_star"] == doc["results"]["analysis_set"]["cutoff"]["s_star"]
    assert stat.S_IMODE(paths["marker"].stat().st_mode) & 0o222 == 0


def test_second_invocation_refuses_on_marker(effect_runs, capsys,
                                             monkeypatch):
    paths = effect_runs[0]
    monkeypatch.setattr(data, "REAL_DB_PATH", str(paths["live"]))
    refuses(paths, capsys, "marker_absent")


def test_results_json_byte_identical_across_directories(effect_runs):
    a, b = (p["out"] / run_c2.RESULTS_NAME for p in effect_runs)
    assert effect_runs[0]["rc"] == effect_runs[1]["rc"] == run_c2.EXIT_OK
    assert a.read_bytes() == b.read_bytes()
    text = a.read_text()
    for p in effect_runs:
        assert str(p["root"]) not in text
    assert os.uname().nodename not in text


def test_end_to_end_s_null_on_non_synthetic_snapshot(tmp_path, built,
                                                     monkeypatch):
    paths = stage(tmp_path, built["S-NULL"], monkeypatch, demark=True)
    assert data.classify(paths["snapshot"], paths["live"]) \
        is data.DbClass.NON_SYNTHETIC
    assert run_c2.main(paths["argv"]) == run_c2.EXIT_OK
    out = paths["out"]
    doc = json.loads((out / run_c2.RESULTS_NAME).read_text())
    _readings_match(doc["decision"], "S-NULL")
    meta = json.loads((out / run_c2.RUN_META_NAME).read_text())
    assert meta["snapshot_db_class"] == "NON_SYNTHETIC"
    verdict_md = (out / run_c2.VERDICT_NAME).read_text()
    assert "Fails gross" in verdict_md
    assert "Gross positive in this reading" not in verdict_md


# ----------------------------------------------------------- preconditions

def test_precondition_order_is_fixed():
    assert tuple(n for n, _ in run_c2.PRECONDITIONS) == EXPECTED_ORDER


def test_preconditions_refuse_in_order(staged, monkeypatch):
    """Break every precondition, then repair them one at a time: each check
    must be the one that refuses next, in EXPECTED_ORDER."""
    p = staged
    cfg = config(p)
    snap_sha = run_c2.sha256_file(p["snapshot"])
    manifest_good = p["manifest"].read_bytes()
    gate_good = p["gate_log"].read_bytes()
    relevance_good = p["relevance"].read_bytes()
    real_s_star = cutoff.compute_s_star
    real_sane = envcheck.numpy_sane

    monkeypatch.setattr(envcheck, "numpy_sane", lambda: False)
    m = json.loads(manifest_good)
    m["files"][0]["sha256"] = "0" * 64
    p["manifest"].write_text(json.dumps(m))
    unlock_good = p["unlock"].read_bytes()
    p["unlock"].unlink()
    p["marker"].write_text("{}")
    os.chmod(p["snapshot"], 0o644)
    monkeypatch.setattr(cutoff, "compute_s_star", lambda status: cutoff.SStar(
        None, cutoff.CASE_NO_SESSIONS, (), None, None, (), 0, 0))
    p["gate_log"].write_text("")
    p["relevance"].unlink()
    p["out"].mkdir()
    (p["out"] / run_c2.VERDICT_NAME).write_text("old")
    monkeypatch.setattr(run_c2, "_mem_available_mb", lambda: 100.0)

    repairs = {
        "numpy_sane": lambda: monkeypatch.setattr(envcheck, "numpy_sane",
                                                  real_sane),
        "manifest": lambda: p["manifest"].write_bytes(manifest_good),
        "unlock": lambda: p["unlock"].write_bytes(unlock_good),
        "marker_absent": lambda: p["marker"].unlink(),
        "snapshot": lambda: os.chmod(p["snapshot"], 0o444),
        "s_star": lambda: monkeypatch.setattr(cutoff, "compute_s_star",
                                              real_s_star),
        "gate_pass": lambda: p["gate_log"].write_bytes(gate_good),
        "relevance_summary": lambda: p["relevance"].write_bytes(
            relevance_good),
        "outputs_absent": lambda: (p["out"] / run_c2.VERDICT_NAME).unlink(),
        "memory": lambda: monkeypatch.setattr(run_c2, "_mem_available_mb",
                                              lambda: PLENTY_MB),
    }
    seen = []
    for name in EXPECTED_ORDER:
        with pytest.raises(run_c2.Refused) as exc:
            run_c2.check_preconditions(cfg)
        seen.append(exc.value.check)
        repairs[name]()
    assert tuple(seen) == EXPECTED_ORDER
    facts = run_c2.check_preconditions(cfg)
    assert facts["snapshot_sha256"] == snap_sha
    assert not p["marker"].exists()


def test_refuses_numpy_canary(staged, capsys, monkeypatch):
    monkeypatch.setattr(envcheck, "numpy_sane", lambda: False)
    refuses(staged, capsys, "numpy_sane")


def test_refuses_tampered_manifest_hash(staged, capsys):
    m = json.loads(staged["manifest"].read_text())
    entry = next(e for e in m["files"] if e["path"] == "news_eval/run_c2.py")
    entry["sha256"] = "f" * 64
    staged["manifest"].write_text(json.dumps(m))
    refuses(staged, capsys, "manifest")


def test_refuses_missing_manifest(staged, capsys):
    staged["manifest"].unlink()
    refuses(staged, capsys, "manifest")


def test_refuses_missing_unlock(staged, capsys):
    staged["unlock"].unlink()
    refuses(staged, capsys, "unlock")


def test_refuses_present_marker(staged, capsys):
    staged["marker"].write_text("{}")
    before = tree(staged["root"])
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "precondition marker_absent:" in err
    # Ruling S7: a marker without results.json or results_STOPPED.json is a
    # killed run, whose verdict is STOPPED; no resume path exists.
    assert "killed" in err and "STOPPED" in err and "9.15" in err
    assert tree(staged["root"]) == before
    assert staged["marker"].read_text() == "{}"


def test_refuses_writable_snapshot(staged, capsys):
    os.chmod(staged["snapshot"], 0o644)
    refuses(staged, capsys, "snapshot")


def test_refuses_snapshot_hash_mismatch(staged, capsys):
    snap = staged["snapshot"]
    os.chmod(snap, 0o644)
    with open(snap, "ab") as fh:
        fh.write(b"\0")
    os.chmod(snap, 0o444)
    refuses(staged, capsys, "snapshot")


def test_refuses_snapshot_meta_not_backup(staged, capsys):
    meta_path = staged["snap_dir"] / run_c2.SNAPSHOT_META_NAME
    meta = json.loads(meta_path.read_text())
    meta["method"] = "shutil.copyfile"
    os.chmod(meta_path, 0o644)
    meta_path.write_text(json.dumps(meta))
    refuses(staged, capsys, "snapshot")


def test_refuses_snapshot_meta_without_time(staged, capsys):
    meta_path = staged["snap_dir"] / run_c2.SNAPSHOT_META_NAME
    meta = json.loads(meta_path.read_text())
    meta["utc_time"] = "2026-10-20 06:00:00"
    os.chmod(meta_path, 0o644)
    meta_path.write_text(json.dumps(meta))
    refuses(staged, capsys, "snapshot")


def test_refuses_the_live_database_path(staged, capsys):
    argv = list(staged["argv"])
    argv[argv.index("--snapshot") + 1] = str(staged["live"])
    refuses({**staged, "argv": argv}, capsys, "snapshot")


def test_refuses_symlink_to_the_live_database(staged, capsys):
    link = staged["root"] / "link.db"
    link.symlink_to(staged["live"])
    argv = list(staged["argv"])
    argv[argv.index("--snapshot") + 1] = str(link)
    refuses({**staged, "argv": argv}, capsys, "snapshot")


def test_refuses_when_s_star_is_none(staged, capsys, monkeypatch):
    monkeypatch.setattr(cutoff, "compute_s_star", lambda status: cutoff.SStar(
        None, cutoff.CASE_NO_RESOLVED, ("2026-08-03",), None, "2026-08-03",
        (), 0, 0))
    refuses(staged, capsys, "s_star")


def _append_gate(paths: dict, **fields) -> None:
    entry = {"inputs_sha256": run_c2.sha256_file(paths["snapshot"]),
             "pass": True, "status": "ok", "s_star": "2026-10-26",
             "manifest_sha256": paths["manifest_sha"], **fields}
    with open(paths["gate_log"], "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def test_refuses_gate_fail_for_this_hash(staged, capsys):
    _append_gate(staged, **{"pass": False})
    refuses(staged, capsys, "gate_pass")


def test_refuses_gate_degenerate_for_this_hash(staged, capsys):
    _append_gate(staged, **{"pass": False, "status": "degenerate"})
    refuses(staged, capsys, "gate_pass")


def test_refuses_gate_pass_only_for_other_bytes(staged, capsys):
    lines = staged["gate_log"].read_text().splitlines()
    entries = [json.loads(x) for x in lines]
    for e in entries:
        e["inputs_sha256"] = "0" * 64
    staged["gate_log"].write_text("".join(json.dumps(e) + "\n"
                                          for e in entries))
    refuses(staged, capsys, "gate_pass")


def test_refuses_missing_gate_log(staged, capsys):
    staged["gate_log"].unlink()
    refuses(staged, capsys, "gate_pass")


def test_refuses_gate_pass_with_other_s_star(staged, capsys):
    entries = [json.loads(x) for x in
               staged["gate_log"].read_text().splitlines()]
    for e in entries:
        e["s_star"] = "2026-01-02"
    staged["gate_log"].write_text("".join(json.dumps(e) + "\n"
                                          for e in entries))
    refuses(staged, capsys, "gate_pass")


def test_refuses_missing_relevance_summary(staged, capsys):
    staged["relevance"].unlink()
    refuses(staged, capsys, "relevance_summary")


def test_refuses_relevance_summary_wrong_schema(staged, capsys):
    staged["relevance"].write_text(json.dumps({"schema": "other"}))
    refuses(staged, capsys, "relevance_summary")


def test_refuses_existing_outputs(staged, capsys):
    staged["out"].mkdir()
    (staged["out"] / run_c2.STOPPED_NAME).write_text("{}")
    refuses(staged, capsys, "outputs_absent")


# ------------------------------------------------------ marker and STOPPED

def test_stopped_after_marker_then_never_rerun(staged, capsys, monkeypatch):
    real_compute = family.compute

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic failure inside family.compute")
    monkeypatch.setattr(family, "compute", boom)
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_STOPPED
    out = staged["out"]
    assert sorted(p.name for p in out.iterdir()) == [run_c2.STOPPED_NAME]
    stopped = json.loads((out / run_c2.STOPPED_NAME).read_text())
    assert stopped["status"] == "STOPPED"
    assert "synthetic failure inside family.compute" in stopped["reason"]
    assert stopped["step"] == "family.compute"
    assert staged["marker"].exists()
    monkeypatch.setattr(family, "compute", real_compute)
    refuses(staged, capsys, "marker_absent")


def test_concurrent_marker_loses_the_race(staged, capsys, monkeypatch):
    real_check = run_c2.check_preconditions

    def check_then_race(cfg):
        facts = real_check(cfg)
        cfg.marker.write_text("another run")
        return facts
    monkeypatch.setattr(run_c2, "check_preconditions", check_then_race)
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_REFUSED
    assert staged["marker"].read_text() == "another run"
    assert not staged["out"].exists()


def test_marker_written_before_any_outcome_read(staged, monkeypatch):
    seen = {}

    def spy(db_path, **kwargs):
        seen["marker_exists"] = Path(kwargs["marker_path"]).exists()
        seen["kwargs"] = kwargs
        raise RuntimeError("stop here")
    monkeypatch.setattr(family, "compute", spy)
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_STOPPED
    assert seen["marker_exists"] is True
    assert seen["kwargs"] == {"real_db_path": str(staged["live"]),
                              "unlock_path": staged["unlock"],
                              "marker_path": staged["marker"]}


def test_companion_only_when_9_12_holds(staged, effect_runs, monkeypatch):
    cached = json.loads((effect_runs[0]["out"] / run_c2.RESULTS_NAME)
                        .read_text())["results"]
    monkeypatch.setattr(family, "compute", lambda *a, **k: cached)
    calls = []
    real_companion = family.companion_horizons

    def companion(*a, **k):
        calls.append(k)
        return real_companion(*a, **k)
    monkeypatch.setattr(family, "companion_horizons", companion)
    monkeypatch.setattr(run_c2, "successor_condition",
                        lambda root, utc: {"holds": True, "tracked": True})
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_OK
    doc = json.loads((staged["out"] / run_c2.RESULTS_NAME).read_text())
    assert doc["companion_computed"] is True and len(calls) == 1
    assert doc["companion_horizons"]["label"] == "EXPLORATORY"
    assert "EXPLORATORY" in (staged["out"] / run_c2.VERDICT_NAME).read_text()


# ------------------------------------------------------------ 9.12 (git)

def _git(repo: Path, *args: str, date: str | None = None,
         committer_date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if date:
        env.update(GIT_AUTHOR_DATE=date,
                   GIT_COMMITTER_DATE=committer_date or date)
    subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null",
                    "-c", "commit.gpgsign=false", *args], check=True,
                   env=env, capture_output=True)


def _draft_repo(tmp_path: Path, commit_date: str | None,
                committer_date: str | None = None) -> Path:
    repo = tmp_path / "gitrepo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / run_c2.SUCCESSOR_DRAFT_REL).write_text("draft\n")
    if commit_date:
        _git(repo, "add", run_c2.SUCCESSOR_DRAFT_REL)
        _git(repo, "commit", "-q", "-m", "draft", date=commit_date,
             committer_date=committer_date)
    return repo


def test_successor_condition_holds_when_committed_before(tmp_path):
    repo = _draft_repo(tmp_path, "2026-10-01T12:00:00-07:00")
    got = run_c2.successor_condition(repo, "2026-10-20T06:00:00.000000Z")
    assert got["tracked"] and got["holds"]
    assert got["last_commit_time"].startswith("2026-10-01T12:00:00")
    # Ruling N6: the sha and both dates are recorded.
    assert len(got["commit_sha"]) == 40
    assert got["author_time"].startswith("2026-10-01T12:00:00")
    assert got["committer_time"] == got["last_commit_time"]


@pytest.mark.parametrize("author, committer", [
    ("2026-10-21T12:00:00-07:00", "2026-10-01T12:00:00-07:00"),
    ("2026-10-01T12:00:00-07:00", "2026-10-21T12:00:00-07:00"),
])
def test_successor_condition_needs_both_dates_before(tmp_path, author,
                                                     committer):
    """Ruling N6: a backdated committer date (or author date) alone does
    not make 9.12 hold."""
    repo = _draft_repo(tmp_path, author, committer)
    got = run_c2.successor_condition(repo, "2026-10-20T06:00:00.000000Z")
    assert got["tracked"] and not got["holds"]
    assert got["author_time"].startswith(author[:19])
    assert got["committer_time"].startswith(committer[:19])


def test_successor_condition_fails_when_committed_after(tmp_path):
    repo = _draft_repo(tmp_path, "2026-10-21T12:00:00-07:00")
    got = run_c2.successor_condition(repo, "2026-10-20T06:00:00.000000Z")
    assert got["tracked"] and not got["holds"]


def test_successor_condition_fails_when_untracked(tmp_path):
    repo = _draft_repo(tmp_path, None)
    got = run_c2.successor_condition(repo, "2026-10-20T06:00:00.000000Z")
    assert not got["tracked"] and not got["holds"]


def test_successor_condition_false_outside_git(tmp_path):
    got = run_c2.successor_condition(tmp_path, "2026-10-20T06:00:00Z")
    assert got["holds"] is False


# ---------------------------------------------------------------- snapshot

def test_snapshot_copy_is_read_only_hashed_and_counted(tmp_path, built,
                                                       monkeypatch):
    p = stage(tmp_path, built["S-EFFECT"], monkeypatch, gate_pass=False)
    snap = p["snapshot"]
    meta = json.loads((p["snap_dir"] / run_c2.SNAPSHOT_META_NAME).read_text())
    assert stat.S_IMODE(snap.stat().st_mode) == 0o444
    assert meta["method"] == "sqlite3.Connection.backup"
    assert meta["sha256"] == run_c2.sha256_file(snap)
    assert meta["bytes"] == snap.stat().st_size
    assert meta["source_realpath"] == os.path.realpath(p["live"])
    # Ruling S1: the source's size and mtime at the copy.
    live_st = p["live"].stat()
    assert meta["source_st_size"] == live_st.st_size
    assert meta["source_st_mtime"] == live_st.st_mtime
    # DELETE mode, as before. It is not the sidecar guarantee: SQLite applies
    # a planted -wal whatever the header says (audit B1). The guarantee is
    # the immutable open plus the planted-sidecar refusals below.
    assert meta["journal_mode_after_copy"] == "delete"
    assert snap.read_bytes()[18:20] == b"\x01\x01"
    assert meta["sidecars_absent"] is True
    conn = _UNPATCHED_CONNECT(p["live"])
    try:
        want = {}
        for qd, st, n in conn.execute(
                "SELECT query_date, state, COUNT(*) FROM news_observation "
                "WHERE run_kind = 'collection' GROUP BY query_date, state"):
            want.setdefault(qd, {})[st] = n
    finally:
        conn.close()
    assert meta["collection_rows_by_query_date_state"] == want
    assert meta["collection_rows_total"] == sum(
        sum(v.values()) for v in want.values())
    assert sorted(x.name for x in p["snap_dir"].iterdir()) == sorted(
        [run_c2.SNAPSHOT_NAME, run_c2.SNAPSHOT_META_NAME])


def test_snapshot_leaves_the_source_unchanged(tmp_path, built, monkeypatch):
    live = tmp_path / "live.db"
    shutil.copyfile(built["S-NULL"], live)
    monkeypatch.setattr(data, "REAL_DB_PATH", str(live))
    unlock = write_unlock(tmp_path / "unlock")
    before = (run_c2.sha256_file(live), live.stat().st_mtime_ns)
    assert run_c2.main(["snapshot", "--source", str(live), "--out-dir",
                        str(tmp_path / "s"), "--unlock", str(unlock)]) == 0
    assert (run_c2.sha256_file(live), live.stat().st_mtime_ns) == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["live.db", "s",
                                                          "unlock"]


def test_snapshot_refuses_without_unlock(tmp_path, built, capsys):
    out = tmp_path / "s"
    rc = run_c2.main(["snapshot", "--source", str(built["S-NULL"]),
                      "--out-dir", str(out), "--unlock",
                      str(tmp_path / "missing")])
    assert rc == run_c2.EXIT_REFUSED and not out.exists()


def test_snapshot_refuses_over_an_existing_snapshot(tmp_path, built,
                                                    monkeypatch):
    p = stage(tmp_path, built["S-NULL"], monkeypatch, gate_pass=False)
    before = tree(p["snap_dir"])
    rc = run_c2.main(["snapshot", "--source", str(p["live"]), "--out-dir",
                      str(p["snap_dir"]), "--unlock", str(p["unlock"])])
    assert rc == run_c2.EXIT_REFUSED and tree(p["snap_dir"]) == before


# --------------------------------------------------------------------- CLI

def test_defaults_resolve_from_the_loader_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "UNLOCK_PATH", str(tmp_path / "u"))
    monkeypatch.setattr(data, "RUN_ONCE_PATH", str(tmp_path / "m"))
    monkeypatch.setattr(data, "REAL_DB_PATH", str(tmp_path / "r"))
    argv = ["run", "--snapshot", "s", "--out-dir", "o", "--gate-log", "g",
            "--relevance-summary", "r"]
    cfg = run_c2._config(run_c2._parser().parse_args(argv), argv)
    assert (cfg.unlock, cfg.marker, cfg.real_db) == (
        tmp_path / "u", tmp_path / "m", str(tmp_path / "r"))
    assert cfg.manifest == REPO / freeze.MANIFEST_REL
    assert cfg.repo_root == REPO


def test_module_entry_point_refuses(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO), data.TEST_MODE_ENV: "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "news_eval.run_c2", "run", "--snapshot",
         str(tmp_path / "s.db"), "--out-dir", str(tmp_path / "o"),
         "--gate-log", str(tmp_path / "g"), "--relevance-summary",
         str(tmp_path / "r"), "--manifest", str(tmp_path / "m.json"),
         "--unlock", str(tmp_path / "u"), "--marker", str(tmp_path / "k"),
         "--real-db", str(tmp_path / "live.db")],
        capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == run_c2.EXIT_REFUSED, proc.stderr
    assert "precondition manifest" in proc.stderr
    assert sorted(x.name for x in tmp_path.iterdir()) == []



# ------------------------------------------------ C.1 rulings: the fix tests

@pytest.mark.parametrize("suffix", data.SIDECAR_SUFFIXES)
def test_refuses_planted_sidecar_beside_the_snapshot(staged, capsys, suffix):
    """Ruling B1: the guarantee is a refusal, not the header bytes."""
    Path(str(staged["snapshot"]) + suffix).write_bytes(b"planted")
    refuses(staged, capsys, "snapshot")


def test_snapshot_refuses_a_sidecar_already_beside_the_destination(
        tmp_path, built, monkeypatch, capsys):
    live = tmp_path / "live.db"
    shutil.copyfile(built["S-NULL"], live)
    monkeypatch.setattr(data, "REAL_DB_PATH", str(live))
    unlock = write_unlock(tmp_path / "unlock")
    out = tmp_path / "s"
    out.mkdir()
    (out / (run_c2.SNAPSHOT_NAME + "-wal")).write_bytes(b"planted")
    rc = run_c2.main(["snapshot", "--source", str(live), "--out-dir",
                      str(out), "--unlock", str(unlock)])
    assert rc == run_c2.EXIT_REFUSED
    assert "snapshot_absent" in capsys.readouterr().err
    assert sorted(x.name for x in out.iterdir()) == [
        run_c2.SNAPSHOT_NAME + "-wal"]


@pytest.mark.parametrize("text", ["{}", "README", "[]"])
def test_unlock_existence_alone_refused_everywhere(staged, capsys, tmp_path,
                                                   built, text):
    """Ruling B2: run and snapshot both read the unlock's content."""
    staged["unlock"].write_text(text)
    refuses(staged, capsys, "unlock")
    out = tmp_path / "s2"
    rc = run_c2.main(["snapshot", "--source", str(staged["live"]),
                      "--out-dir", str(out), "--unlock",
                      str(staged["unlock"])])
    assert rc == run_c2.EXIT_REFUSED and not out.exists()


def test_refuses_unlock_naming_another_manifest(staged, capsys):
    write_unlock(staged["unlock"], manifest_sha256="0" * 64)
    refuses(staged, capsys, "unlock")


def test_refuses_unlock_for_another_stage(staged, capsys):
    write_unlock(staged["unlock"], manifest_sha256=staged["manifest_sha"],
                 stage="C.1")
    refuses(staged, capsys, "unlock")


def test_refuses_a_snapshot_of_another_source(tmp_path, built, monkeypatch,
                                              capsys):
    """Ruling S1: a snapshot whose source is not the configured live
    database (here a synthetic fixture) is refused."""
    p = stage(tmp_path, built["S-EFFECT"], monkeypatch)
    other = tmp_path / "other_source.db"
    shutil.copyfile(built["S-NULL"], other)
    meta_path = p["snap_dir"] / run_c2.SNAPSHOT_META_NAME
    meta = json.loads(meta_path.read_text())
    meta["source_realpath"] = os.path.realpath(other)
    os.chmod(meta_path, 0o644)
    meta_path.write_text(json.dumps(meta))
    refuses(p, capsys, "snapshot")


def test_outside_test_mode_the_snapshot_must_be_non_synthetic(staged,
                                                              monkeypatch):
    cfg = config(staged)
    assert run_c2._check_snapshot(cfg, {})["snapshot_db_class"] == "SYNTHETIC"
    monkeypatch.delenv(data.TEST_MODE_ENV)
    with pytest.raises(run_c2.Refused, match="NON_SYNTHETIC"):
        run_c2._check_snapshot(cfg, {})


def test_test_mode_refuses_a_snapshot_of_the_repository_database(
        staged, tmp_path, capsys):
    """Ruling S5: in test mode a snapshot.json naming the repository's
    database as its source is refused (before any open of either file), and
    take_snapshot refuses that source before copying."""
    meta_path = staged["snap_dir"] / run_c2.SNAPSHOT_META_NAME
    meta = json.loads(meta_path.read_text())
    meta["source_realpath"] = os.path.realpath(data.COMPILED_REAL_DB_PATH)
    os.chmod(meta_path, 0o644)
    meta_path.write_text(json.dumps(meta))
    cfg = run_c2.RunConfig(**{**vars(config(staged)),
                              "real_db": data.COMPILED_REAL_DB_PATH})
    with pytest.raises(run_c2.Refused, match="S5"):
        run_c2._check_snapshot(cfg, {})
    with pytest.raises(run_c2.Refused) as exc:
        run_c2.take_snapshot(data.COMPILED_REAL_DB_PATH, tmp_path / "x",
                             unlock_path=staged["unlock"])
    assert exc.value.check == "source" and not (tmp_path / "x").exists()


def test_refuses_gate_pass_without_or_with_another_manifest(staged, capsys):
    """Ruling S2: a PASS counts only under the manifest this run verified."""
    good = staged["gate_log"].read_text()
    for value in (None, "0" * 64):
        entries = [json.loads(x) for x in good.splitlines()]
        for e in entries:
            if value is None:
                e.pop("manifest_sha256")
            else:
                e["manifest_sha256"] = value
        staged["gate_log"].write_text("".join(json.dumps(e) + "\n"
                                              for e in entries))
        refuses(staged, capsys, "gate_pass")


def test_refuses_a_loaded_module_outside_the_manifest(staged, capsys,
                                                      monkeypatch):
    """Ruling S3: the manifest precondition hashes the imported code."""
    stray = staged["root"] / "stray.py"
    stray.write_text("X = 1\n")
    mod = type(sys)("news_eval.zz_stray")
    mod.__file__ = str(stray)
    monkeypatch.setitem(sys.modules, "news_eval.zz_stray", mod)
    refuses(staged, capsys, "manifest")


def test_refuses_low_or_unreadable_memory(staged, capsys, monkeypatch):
    """Ruling S7: MemAvailable >= 2,048 MB before the marker, else nothing
    is written."""
    for value in (float(K.MIN_MEM_AVAILABLE_MB) - 1.0, None):
        monkeypatch.setattr(run_c2, "_mem_available_mb", lambda v=value: v)
        refuses(staged, capsys, "memory")
        assert not staged["marker"].exists()


def test_mem_available_reader(tmp_path, monkeypatch):
    fake = tmp_path / "meminfo"
    fake.write_text("MemTotal:       15480832 kB\n"
                    "MemFree:         3672064 kB\n"
                    "MemAvailable:    4194304 kB\n")
    monkeypatch.setattr(run_c2, "MEMINFO_PATH", str(fake))
    assert _ORIGINAL_MEM_READER() == 4096.0
    fake.write_text("MemTotal: 1 kB\n")
    assert _ORIGINAL_MEM_READER() is None
    monkeypatch.setattr(run_c2, "MEMINFO_PATH", str(tmp_path / "absent"))
    assert _ORIGINAL_MEM_READER() is None


def test_mem_available_reader_on_this_host():
    with open(run_c2.MEMINFO_PATH, encoding="ascii") as fh:
        line = next(x for x in fh if x.startswith("MemAvailable:"))
    want = int(line.split()[1]) / 1024.0
    got = _ORIGINAL_MEM_READER()
    assert got is not None and abs(got - want) < 512.0


def _swap_in(snapshot: Path, replacement: Path) -> None:
    """Replace the snapshot by another file (a new inode) of mode 0444."""
    tmp = snapshot.with_name("swap.tmp")
    shutil.copyfile(replacement, tmp)
    os.chmod(tmp, 0o444)
    os.replace(tmp, snapshot)


def test_snapshot_swapped_after_the_preconditions_is_stopped(
        staged, monkeypatch):
    """Ruling S4: the file is swapped (same bytes, new inode) between the
    preconditions and compute; the run is STOPPED and family.compute never
    runs."""
    real_marker = run_c2.write_marker
    copy = staged["root"] / "same_bytes.db"
    shutil.copyfile(staged["snapshot"], copy)

    def marker_then_swap(cfg, facts):
        body = real_marker(cfg, facts)
        _swap_in(cfg.snapshot, copy)
        return body
    monkeypatch.setattr(run_c2, "write_marker", marker_then_swap)
    calls = []
    monkeypatch.setattr(family, "compute",
                        lambda *a, **k: calls.append(1))
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_STOPPED
    out = staged["out"]
    assert sorted(x.name for x in out.iterdir()) == [run_c2.STOPPED_NAME]
    stopped = json.loads((out / run_c2.STOPPED_NAME).read_text())
    assert stopped["step"] == "snapshot re-check before compute"
    assert "before compute" in stopped["reason"]
    assert "st_ino" in stopped["reason"] and calls == []


def test_snapshot_changed_during_compute_is_stopped(staged, effect_runs,
                                                    built, monkeypatch):
    """Ruling S4: the bytes change while family.compute runs; the re-check
    after compute stops the run before results.json is written."""
    cached = json.loads((effect_runs[0]["out"] / run_c2.RESULTS_NAME)
                        .read_text())["results"]

    def compute_then_swap(db_path, **kwargs):
        _swap_in(Path(db_path), built["S-NULL"])
        return cached
    monkeypatch.setattr(family, "compute", compute_then_swap)
    assert run_c2.main(staged["argv"]) == run_c2.EXIT_STOPPED
    out = staged["out"]
    assert sorted(x.name for x in out.iterdir()) == [run_c2.STOPPED_NAME]
    stopped = json.loads((out / run_c2.STOPPED_NAME).read_text())
    assert stopped["step"] == "snapshot re-check after compute"
    assert "after compute" in stopped["reason"]
    assert stopped["files_written_before_stop"] == []


# ------------------------------------------------- ruling S5: test-only flags

RUN_FLAGS = ("--manifest", "--unlock", "--marker", "--repo-root", "--real-db")


@pytest.mark.parametrize("flag", RUN_FLAGS)
def test_run_flag_refused_outside_test_mode(staged, capsys, monkeypatch,
                                            flag):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    argv = ["run", "--snapshot", str(staged["snapshot"]), "--out-dir",
            str(staged["out"]), "--gate-log", str(staged["gate_log"]),
            "--relevance-summary", str(staged["relevance"]), flag,
            str(staged["argv"][staged["argv"].index(flag) + 1])]
    before = tree(staged["root"])
    assert run_c2.main(argv) == run_c2.EXIT_REFUSED
    err = capsys.readouterr().err
    assert flag in err and "test mode" in err
    assert tree(staged["root"]) == before


@pytest.mark.parametrize("flag", ["--unlock", "--real-db"])
def test_snapshot_flag_refused_outside_test_mode(tmp_path, built, capsys,
                                                 monkeypatch, flag):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    out = tmp_path / "s"
    rc = run_c2.main(["snapshot", "--source", str(built["S-NULL"]),
                      "--out-dir", str(out), flag, str(tmp_path / "x")])
    assert rc == run_c2.EXIT_REFUSED and not out.exists()
    assert flag in capsys.readouterr().err


def test_config_refuses_non_default_paths_outside_test_mode(staged,
                                                            monkeypatch,
                                                            capsys):
    """The Python API follows the CLI rule: RunConfig itself refuses."""
    monkeypatch.delenv(data.TEST_MODE_ENV)
    with pytest.raises(run_c2.Refused) as exc:
        config(staged)
    assert exc.value.check == "config"
    for field in ("manifest", "unlock", "marker", "real_db"):
        assert f"{field}=" in exc.value.reason
    assert "repo_root=" not in exc.value.reason   # staged with the default
    # The registered defaults are accepted (constructed, not run).
    for name, value in (("UNLOCK_PATH", data.COMPILED_UNLOCK_PATH),
                        ("RUN_ONCE_PATH", data.COMPILED_RUN_ONCE_PATH),
                        ("REAL_DB_PATH", data.COMPILED_REAL_DB_PATH)):
        monkeypatch.setattr(data, name, value)
    argv = ["run", "--snapshot", "s", "--out-dir", "o", "--gate-log", "g",
            "--relevance-summary", "r"]
    cfg = run_c2._config(run_c2._parser().parse_args(argv), argv)
    assert (str(cfg.unlock), str(cfg.marker), cfg.real_db) == (
        data.COMPILED_UNLOCK_PATH, data.COMPILED_RUN_ONCE_PATH,
        data.COMPILED_REAL_DB_PATH)
    assert cfg.repo_root == freeze.REPO_ROOT
    with pytest.raises(run_c2.Refused, match="repo_root="):
        run_c2.RunConfig(**{**vars(cfg), "repo_root": staged["root"]})


def test_module_entry_point_refuses_flags_without_test_mode(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != data.TEST_MODE_ENV}
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run(
        [sys.executable, "-m", "news_eval.run_c2", "run", "--snapshot",
         str(tmp_path / "s.db"), "--out-dir", str(tmp_path / "o"),
         "--gate-log", str(tmp_path / "g"), "--relevance-summary",
         str(tmp_path / "r"), "--marker", str(tmp_path / "k")],
        capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == run_c2.EXIT_REFUSED, proc.stderr
    assert "--marker" in proc.stderr and "test mode" in proc.stderr
    assert sorted(x.name for x in tmp_path.iterdir()) == []
