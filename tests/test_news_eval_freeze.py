"""news_eval.freeze: the C.1 harness manifest writer and checker (Task 8c; 9.15).

Unit tests build a small tree in tmp_path. The last test verifies the REAL
manifest, reports/c1_harness_freeze.json, against disk once the C.1 lead has
written it, and skips before then.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from news_eval import constants as K
from news_eval import freeze

REPO = Path(__file__).resolve().parent.parent
REAL_MANIFEST = REPO / freeze.MANIFEST_REL
HEAD = "0123456789abcdef0123456789abcdef01234567"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture()
def tree(tmp_path) -> dict:
    root = tmp_path / "repo"
    _write(root / "news_eval" / "__init__.py", '"""pkg"""\n')
    _write(root / "news_eval" / "a.py", "X = 1\n")
    _write(root / "news_eval" / "schema.sql", "CREATE TABLE t (x);\n")
    _write(root / "news_eval" / "sub" / "b.txt", "nested\n")
    _write(root / "news_eval" / "__pycache__" / "note.txt", "skipped\n")
    _write(root / "tests" / "test_news_eval_a.py", "def test(): pass\n")
    _write(root / "tests" / "test_other.py", "not frozen\n")
    _write(root / "reports" / "c1_verdict_mapping.md", "# mapping\n")
    for rel in freeze.INPUT_PATHS:
        _write(root / rel, f"input {rel}\n")
    ext = tmp_path / "ext"
    for rel in freeze.EXTERNAL_RELS[:-1]:          # the last one is absent
        _write(ext / rel, f"external {rel}\n")
    manifest = root / "reports" / "c1_harness_freeze.json"
    digest = freeze.write_manifest(manifest, root, head=HEAD,
                                   external_root=ext)
    return {"root": root, "ext": ext, "manifest": manifest, "sha": digest}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _save(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


# -------------------------------------------------------------------- write

def test_write_then_check_passes(tree):
    assert freeze.check_manifest(tree["manifest"], tree["root"]) == []
    raw = tree["manifest"].read_bytes()
    assert tree["sha"] == hashlib.sha256(raw).hexdigest()
    assert raw.endswith(b"}\n")


def test_manifest_schema_and_pins(tree):
    m = _load(tree["manifest"])
    assert m["schema"] == "c1_harness_freeze/1"
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+$",
                    m["created_pdt"])
    pins = m["pins"]
    assert pins["seeds"] == {"BOOT_SEED": 20261010, "PERM_SEED": 20261011,
                             "RELEVANCE_SEED": 20261012}
    assert pins["git_head_before_freeze"] == HEAD
    assert pins["numpy_version"] == np.__version__
    assert re.match(r"^\d+\.\d+\.\d+", pins["python_version"])
    # C.1 ruling N3: SQLite compared, BLAS recorded.
    assert pins["sqlite_version"] == sqlite3.sqlite_version
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
    assert pins["numpy_blas"] == {"name": blas["name"],
                                  "version": blas["version"]}
    c = pins["constants"]
    assert list(c) == sorted(c)
    assert c["BOOT_SEED"] == K.BOOT_SEED and c["REQUIRED_FACTOR"] == 11.156
    assert c["STREAM_ORDER"][0] == ["P1", "primary"]
    assert c["OUTCOME_COLUMN_RE"]["regex"] == K.OUTCOME_COLUMN_RE.pattern
    assert c["E_TEST_STRATUM"] == {"E1": "S1", "E2": "S2", "E3": "S3",
                                   "E4": "S4"}
    assert "_REGISTERED_TESTS" not in c and "stream_index" not in c


def test_manifest_files_inputs_external(tree):
    m = _load(tree["manifest"])
    paths = [e["path"] for e in m["files"]]
    assert paths == sorted(paths)
    assert paths == ["news_eval/__init__.py", "news_eval/a.py",
                     "news_eval/schema.sql", "news_eval/sub/b.txt",
                     "reports/c1_verdict_mapping.md",
                     "tests/test_news_eval_a.py"]
    a = next(e for e in m["files"] if e["path"] == "news_eval/a.py")
    assert a["bytes"] == 6
    assert a["sha256"] == hashlib.sha256(b"X = 1\n").hexdigest()
    assert [e["path"] for e in m["inputs"]] == list(freeze.INPUT_PATHS)
    ext = m["external"]
    assert len(ext) == len(freeze.EXTERNAL_RELS)
    assert all(Path(e["path"]).is_absolute() for e in ext)
    assert ext[-1]["sha256"] is None and ext[0]["sha256"] is not None


def test_write_refuses_bytecode_under_news_eval(tree):
    _write(tree["root"] / "news_eval" / "__pycache__" / "a.cpython-314.pyc",
           "bytecode")
    with pytest.raises(freeze.FreezeError, match="PYTHONPYCACHEPREFIX"):
        freeze.write_manifest(tree["root"] / "m.json", tree["root"],
                              head=HEAD, external_root=tree["ext"])


def test_write_refuses_a_missing_input(tree):
    (tree["root"] / "backtest" / "fees.py").unlink()
    with pytest.raises(freeze.FreezeError, match="backtest/fees.py"):
        freeze.build_manifest(tree["root"], head=HEAD,
                              external_root=tree["ext"])


def test_write_needs_git_outside_a_repository(tree, capsys):
    out = tree["root"] / "m2.json"
    code = freeze._main(["write", "--out", str(out),
                         "--root", str(tree["root"])])
    assert code == 1 and not out.exists()
    assert "git rev-parse HEAD failed" in capsys.readouterr().err


# -------------------------------------------------------------------- check

def test_one_byte_change_fails(tree):
    (tree["root"] / "news_eval" / "a.py").write_text("X = 2\n")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert len(diffs) == 1 and diffs[0].startswith("files: news_eval/a.py: "
                                                   "sha256")


def test_input_change_fails(tree):
    (tree["root"] / "EXPERIMENT.md").write_text("input EXPERIMENT.mX\n")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == [d for d in diffs if d.startswith("inputs: EXPERIMENT.md")]
    assert len(diffs) == 1


def test_size_change_reported(tree):
    (tree["root"] / "news_eval" / "a.py").write_text("X = 10\n")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert any("bytes 7 != 6" in d for d in diffs)
    assert any("sha256" in d for d in diffs)


def test_deleted_file_fails(tree):
    (tree["root"] / "tests" / "test_news_eval_a.py").unlink()
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == ["files: tests/test_news_eval_a.py: missing"]


@pytest.mark.parametrize("extra", ["news_eval/extra.py",
                                   "news_eval/sub/deep/c.json",
                                   "tests/test_news_eval_new.py"])
def test_extra_file_fails(tree, extra):
    _write(tree["root"] / extra, "new\n")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == [f"files: {extra}: on disk, not in the manifest"]


def test_unrelated_new_files_do_not_fail(tree):
    _write(tree["root"] / "tests" / "test_something_else.py", "x\n")
    _write(tree["root"] / "reports" / "c1_relevance_sample.csv", "x\n")
    _write(tree["root"] / "news_eval" / "__pycache__" / "more.txt", "x\n")
    assert freeze.check_manifest(tree["manifest"], tree["root"]) == []


def test_bytecode_fails_check(tree):
    _write(tree["root"] / "news_eval" / "__pycache__" / "a.cpython-314.pyc",
           "bytecode")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert len(diffs) == 1 and "bytecode" in diffs[0]


@pytest.mark.parametrize("key", ["python_version", "numpy_version",
                                 "sqlite_version"])
def test_version_mismatch_fails(tree, key):
    m = _load(tree["manifest"])
    m["pins"][key] = "0.0.1"
    _save(tree["manifest"], m)
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert len(diffs) == 1 and diffs[0].startswith(f"pins: {key}")


def test_running_version_mismatch_fails(tree, monkeypatch):
    monkeypatch.setattr(freeze.platform, "python_version", lambda: "3.99.0")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == [f"pins: python_version 3.99.0 != pinned "
                     f"{_load(tree['manifest'])['pins']['python_version']}"]


def test_constants_pin_mismatch_fails(tree):
    m = _load(tree["manifest"])
    m["pins"]["constants"]["BAR_PRIMARY_Z"] = 2.0
    _save(tree["manifest"], m)
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == ["pins: constants differ: ['BAR_PRIMARY_Z']"]


def test_input_dropped_from_manifest_fails(tree):
    m = _load(tree["manifest"])
    m["inputs"] = [e for e in m["inputs"] if e["path"] != "EXPERIMENT.md"]
    _save(tree["manifest"], m)
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == ["inputs: EXPERIMENT.md: not in the manifest"]


def test_every_difference_listed(tree):
    (tree["root"] / "news_eval" / "a.py").write_text("X = 2\n")
    (tree["root"] / "news_eval" / "sub" / "b.txt").unlink()
    _write(tree["root"] / "news_eval" / "z.py", "z\n")
    (tree["root"] / "backtest" / "fees.py").write_text("changed\n")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert len(diffs) == 5  # a.py sha256, b.txt missing, z.py extra,
    # fees.py bytes and sha256


def test_external_drift_never_fails(tree):
    (tree["ext"] / freeze.EXTERNAL_RELS[0]).write_text("changed\n")
    assert freeze.check_manifest(tree["manifest"], tree["root"]) == []
    drift = freeze.external_drift(tree["manifest"])
    assert len(drift) == 1 and freeze.EXTERNAL_RELS[0] in drift[0]


def test_missing_or_malformed_manifest(tree, tmp_path):
    assert "is missing" in freeze.check_manifest(tmp_path / "none.json",
                                                 tree["root"])[0]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert "not JSON" in freeze.check_manifest(bad, tree["root"])[0]
    bad.write_text(json.dumps({"schema": "other/1"}))
    assert "schema" in freeze.check_manifest(bad, tree["root"])[0]


def test_cli_check_exit_codes_and_output(tree, capsys):
    args = ["check", "--manifest", str(tree["manifest"]),
            "--root", str(tree["root"])]
    assert freeze._main(args) == 0
    out = capsys.readouterr().out
    assert tree["sha"] in out and "FROZEN: match" in out
    (tree["root"] / "news_eval" / "a.py").write_text("X = 3\n")
    _write(tree["root"] / "news_eval" / "new.py", "n\n")
    assert freeze._main(args) == 1
    out = capsys.readouterr().out
    assert out.count("MISMATCH") == 2 and "NOT FROZEN: 2" in out


# ---------------------------------------------------------- the real tree

def test_constants_pins_cover_every_public_constant():
    pins = freeze.constants_pins()
    json.dumps(pins)
    public = {n for n in vars(K) if re.match(r"^[A-Z][A-Z0-9_]*$", n)}
    assert set(pins) == public


def test_unknown_constant_type_refused():
    class Box:
        WEIRD = object()
    with pytest.raises(freeze.FreezeError, match="WEIRD"):
        freeze.constants_pins(Box)


def test_real_tree_file_selection():
    files = freeze.harness_files(REPO)
    for rel in ("news_eval/freeze.py", "news_eval/schema.sql",
                "news_eval/gate.py", "news_eval/cutoff.py",
                "news_eval/relevance.py", "tests/test_news_eval_freeze.py",
                "reports/c1_verdict_mapping.md"):
        assert rel in files
    assert not [f for f in files if "__pycache__" in f or f.endswith(".pyc")]
    assert all((REPO / rel).is_file() for rel in freeze.INPUT_PATHS)


def test_git_head_reads_the_repository():
    assert re.match(r"^[0-9a-f]{40}$", freeze.git_head(REPO))


def test_real_manifest_matches_disk():
    if not REAL_MANIFEST.is_file():
        pytest.skip("manifest not yet written (pre-freeze)")
    assert freeze.check_manifest(REAL_MANIFEST, REPO) == []


def test_running_sqlite_version_mismatch_fails(tree, monkeypatch):
    monkeypatch.setattr(freeze.sqlite3, "sqlite_version", "3.0.0")
    diffs = freeze.check_manifest(tree["manifest"], tree["root"])
    assert diffs == [f"pins: sqlite_version 3.0.0 != pinned "
                     f"{_load(tree['manifest'])['pins']['sqlite_version']}"]


def test_blas_is_recorded_not_compared(tree):
    m = _load(tree["manifest"])
    m["pins"]["numpy_blas"] = {"name": "other", "version": "0"}
    _save(tree["manifest"], m)
    assert freeze.check_manifest(tree["manifest"], tree["root"]) == []


# ------------------------------------ C.1 ruling S3: the code Python imported

def _modules_from(root: Path, names=("a",)) -> dict:
    mods = {"news_eval": SimpleNamespace(
        __file__=str(root / "news_eval" / "__init__.py"))}
    for n in names:
        mods[f"news_eval.{n}"] = SimpleNamespace(
            __file__=str(root / "news_eval" / f"{n}.py"))
    return mods


def test_loaded_modules_of_the_frozen_tree_pass(tree):
    mods = _modules_from(tree["root"])
    assert freeze.loaded_module_differences(tree["manifest"], mods) == []


def test_clean_repo_root_cannot_vouch_for_modified_imported_code(tree,
                                                                 tmp_path):
    """The audit's S3 case: the manifest check passes on a clean --repo-root
    tree while the imported news_eval is a modified copy."""
    other = tmp_path / "modified"
    shutil.copytree(tree["root"], other)
    (other / "news_eval" / "a.py").write_text("X = 2\n")
    assert freeze.check_manifest(tree["manifest"], tree["root"]) == []
    diffs = freeze.loaded_module_differences(tree["manifest"],
                                             _modules_from(other))
    assert len(diffs) == 1 and diffs[0].startswith(
        "loaded: news_eval.a: news_eval/a.py sha256 ")


def test_loaded_module_not_in_manifest_or_outside_the_package(tree,
                                                              tmp_path):
    root = tree["root"]
    (root / "news_eval" / "late.py").write_text("Y = 1\n")
    mods = _modules_from(root, ("a", "late"))
    stray = tmp_path / "stray.py"
    stray.write_text("Z = 1\n")
    mods["news_eval.stray"] = SimpleNamespace(__file__=str(stray))
    mods["news_eval.nofile"] = SimpleNamespace()
    diffs = freeze.loaded_module_differences(tree["manifest"], mods)
    assert any("news_eval.late: news_eval/late.py is not in the manifest"
               in d for d in diffs)
    assert any(d.startswith("loaded: news_eval.stray:") and "outside" in d
               for d in diffs)
    assert "loaded: news_eval.nofile: no __file__" in diffs


def test_verify_combines_both_checks_and_returns_the_sha(tree, tmp_path):
    mods_ok = freeze.loaded_module_differences(tree["manifest"],
                                               _modules_from(tree["root"]))
    assert mods_ok == []
    diffs, digest = freeze.verify(tmp_path / "absent.json", tree["root"])
    assert digest is None and len(diffs) == 1 and "missing" in diffs[0]


def test_this_process_imports_the_frozen_repository_code(tmp_path):
    """A manifest of the repository matches every news_eval module this test
    process loaded, and verify() returns its sha256."""
    manifest = tmp_path / "manifest.json"
    digest = freeze.write_manifest(manifest, REPO, head="test")
    assert [n for n in sys.modules if n.startswith("news_eval.")]
    assert freeze.loaded_module_differences(manifest) == []
    assert freeze.verify(manifest, REPO) == ([], digest)
    m = _load(manifest)
    entry = next(e for e in m["files"] if e["path"] == "news_eval/freeze.py")
    entry["sha256"] = "f" * 64
    _save(manifest, m)
    diffs = freeze.loaded_module_differences(manifest)
    assert diffs == [f"loaded: news_eval.freeze: news_eval/freeze.py sha256 "
                     f"{freeze.sha256_file(REPO / 'news_eval' / 'freeze.py')} "
                     f"!= {'f' * 64}"]


def test_a_module_run_as_main_is_checked_under_its_name(tree, tmp_path):
    """python -m news_eval.run_c2 loads run_c2 as __main__ only."""
    other = tmp_path / "modified"
    shutil.copytree(tree["root"], other)
    (other / "news_eval" / "a.py").write_text("X = 3\n")
    mods = _modules_from(tree["root"], ())
    mods["__main__"] = SimpleNamespace(
        __file__=str(other / "news_eval" / "a.py"),
        __spec__=SimpleNamespace(name="news_eval.a"))
    diffs = freeze.loaded_module_differences(tree["manifest"], mods)
    assert len(diffs) == 1 and diffs[0].startswith("loaded: news_eval.a:")
    mods["__main__"].__file__ = str(tree["root"] / "news_eval" / "a.py")
    assert freeze.loaded_module_differences(tree["manifest"], mods) == []
