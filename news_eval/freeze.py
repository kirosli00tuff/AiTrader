"""The C.1 harness freeze: manifest writer and checker (STAGE C.1 Task 8c; Amendment 9.15).

    python -m news_eval.freeze write [--out reports/c1_harness_freeze.json]
    python -m news_eval.freeze check [--manifest reports/c1_harness_freeze.json]

`write` records schema "c1_harness_freeze/1":
- created_pdt: the `date "+%Y-%m-%d %H:%M:%S %Z"` command's output.
- pins: the three 9.11 seeds, every public UPPER_CASE value of
  news_eval.constants (JSON form, sorted), git HEAD before the freeze commit,
  the Python, numpy and SQLite (sqlite3.sqlite_version) versions, and
  numpy's BLAS name and version from np.show_config(mode="dicts") (C.1
  ruling N3; recorded, not compared).
- files: path, sha256 and bytes of every file under news_eval/ (recursive,
  sorted, __pycache__ directories skipped), every tests/test_news_eval_*.py,
  and reports/c1_verdict_mapping.md.
- inputs: the same for EXPERIMENT.md and the collector and cost files the
  harness definitions rest on (INPUT_PATHS).
- external: path and sha256 of the PropExperiment files read for patterns,
  for the record only; they never fail a check.

`check` (and check_manifest, which news_eval.run_c2 calls as its first
precondition, 9.15) recomputes every files and inputs entry and fails on: a
missing file, a changed sha256 or size, a file under news_eval/ or a
tests/test_news_eval_*.py on disk but absent from the manifest (an unlisted
file could change a verdict), any .pyc file under news_eval/ (bytecode in a
hashed folder; run with PYTHONPYCACHEPREFIX), a Python, numpy or SQLite
version of the running process other than the pinned one (ruling N3), or a
constants value other than the pinned one.

loaded_module_differences (C.1 ruling S3) checks the code Python actually
imported: it hashes the __file__ of every loaded news_eval.* module and
compares it with the manifest's files entry of the same repository-relative
path, so a clean --repo-root tree cannot vouch for modified imported code.
verify runs both checks and returns the manifest's sha256; news_eval.run_c2
(precondition 1) and news_eval.gate (ruling S2, on a non-synthetic database)
call it.

Every path is a parameter so the tests run on a tree in tmp_path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

from news_eval import constants as K

SCHEMA = "c1_harness_freeze/1"
REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_REL = "reports/c1_harness_freeze.json"
HARNESS_DIR = "news_eval"
TESTS_DIR = "tests"
TESTS_GLOB = "test_news_eval_*.py"
MAPPING_REL = "reports/c1_verdict_mapping.md"
PYCACHE_DIR = "__pycache__"
BYTECODE_SUFFIX = ".pyc"
INPUT_PATHS = (
    "EXPERIMENT.md",
    "news_experiment/outcomes.py",
    "news_experiment/scoring.py",
    "news_experiment/spec.py",
    "news_experiment/horizon.py",
    "news_experiment/store.py",
    "news_experiment/collect.py",
    "news_experiment/maintain.py",
    "news_experiment/daily.py",
    "backtest/fees.py",
    "scripts/blind_interim_20260928.py",
)
EXTERNAL_ROOT = Path.home() / "Documents" / "GitHub" / "PropExperiment"
EXTERNAL_RELS = (
    "c1_replication/evaluate.py",
    "reports/stage_e18_freeze.json",
    "tests/test_harness_freeze.py",
    "docs/prompts/STAGE_E.18.md",
    "reports/E.18_RETURN.md",
)
DATE_FORMAT = "+%Y-%m-%d %H:%M:%S %Z"
_UPPER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class FreezeError(Exception):
    """The manifest cannot be written or read."""


# ------------------------------------------------------------------ hashing

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def file_entry(root: Path, rel: str) -> dict:
    """{"path", "sha256", "bytes"} of root/rel."""
    p = root / rel
    return {"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size}


# ----------------------------------------------------------- what is frozen

def bytecode_files(root: Path) -> list[str]:
    """Every .pyc under news_eval/, __pycache__ included (relative paths)."""
    base = root / HARNESS_DIR
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("*")
                  if p.is_file() and p.suffix == BYTECODE_SUFFIX)


def harness_files(root: Path) -> list[str]:
    """news_eval/** (no __pycache__), tests/test_news_eval_*.py, the mapping.

    Raises FreezeError when news_eval/ is missing."""
    base = root / HARNESS_DIR
    if not base.is_dir():
        raise FreezeError(f"{base} is not a directory")
    found = [p.relative_to(root).as_posix() for p in base.rglob("*")
             if p.is_file() and PYCACHE_DIR not in p.relative_to(base).parts]
    found += [p.relative_to(root).as_posix()
              for p in (root / TESTS_DIR).glob(TESTS_GLOB) if p.is_file()]
    found.append(MAPPING_REL)
    return sorted(set(found))


def _jsonable(value: object, name: str) -> object:
    """A JSON form of a constants value; refuses a type it does not know."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_jsonable(v, name) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v, name) for v in value)
    if isinstance(value, dict):
        return {str(k): _jsonable(value[k], name)
                for k in sorted(value, key=str)}
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": int(value.flags)}
    raise FreezeError(f"constants.{name}: no JSON form for "
                      f"{type(value).__name__}")


def constants_pins(module: object = K) -> dict:
    """Every public UPPER_CASE attribute of the constants module, sorted."""
    names = sorted(n for n in vars(module) if _UPPER_RE.match(n))
    return {n: _jsonable(getattr(module, n), n) for n in names}


def git_head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FreezeError(f"git rev-parse HEAD failed in {root}: {exc}") \
            from None
    return out.stdout.strip()


def created_pdt() -> str:
    try:
        out = subprocess.run(["date", DATE_FORMAT], capture_output=True,
                             text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FreezeError(f"date failed: {exc}") from None
    return out.stdout.strip()


def versions() -> dict:
    """The versions check_manifest compares with the pins (ruling N3)."""
    return {"python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "sqlite_version": sqlite3.sqlite_version}


def blas_info() -> dict:
    """numpy's BLAS name and version from np.show_config(mode="dicts")
    (ruling N3). Recorded in the pins and in run_meta, not compared."""
    try:
        blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
        return {"name": blas.get("name"), "version": blas.get("version")}
    except Exception as exc:  # noqa: BLE001 - a record, never a refusal
        return {"name": None, "version": None,
                "error": f"{type(exc).__name__}: {exc}"}


# -------------------------------------------------------------------- write

def build_manifest(root: Path | str = REPO_ROOT, *,
                   head: str | None = None,
                   external_root: Path | str = EXTERNAL_ROOT) -> dict:
    """The manifest dict. Raises FreezeError on bytecode under news_eval/ or
    a missing frozen file or input."""
    root = Path(root)
    pyc = bytecode_files(root)
    if pyc:
        raise FreezeError(f"bytecode under {HARNESS_DIR}/: {pyc[:5]} "
                          f"({len(pyc)}); set PYTHONPYCACHEPREFIX and remove "
                          "it before freezing")
    missing = [r for r in harness_files(root) + list(INPUT_PATHS)
               if not (root / r).is_file()]
    if missing:
        raise FreezeError(f"missing files: {missing}")
    external = []
    for rel in EXTERNAL_RELS:
        p = Path(external_root) / rel
        external.append({"path": str(p.resolve()) if p.exists() else str(p),
                         "sha256": sha256_file(p) if p.is_file() else None})
    return {
        "schema": SCHEMA,
        "created_pdt": created_pdt(),
        "pins": {
            "seeds": {"BOOT_SEED": K.BOOT_SEED, "PERM_SEED": K.PERM_SEED,
                      "RELEVANCE_SEED": K.RELEVANCE_SEED},
            "constants": constants_pins(),
            "git_head_before_freeze": head if head is not None
            else git_head(root),
            **versions(),
            "numpy_blas": blas_info(),
        },
        "files": [file_entry(root, r) for r in harness_files(root)],
        "inputs": [file_entry(root, r) for r in INPUT_PATHS],
        "external": external,
    }


def write_manifest(out: Path | str, root: Path | str = REPO_ROOT, *,
                   head: str | None = None,
                   external_root: Path | str = EXTERNAL_ROOT) -> str:
    """Write the manifest (sorted keys, indent 2, trailing newline); return
    its sha256."""
    manifest = build_manifest(root, head=head, external_root=external_root)
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return sha256_bytes(raw)


# -------------------------------------------------------------------- check

def load_manifest(path: Path | str) -> tuple[dict, str]:
    """(manifest, sha256 of its bytes). Raises FreezeError when unusable."""
    p = Path(path)
    if not p.is_file():
        raise FreezeError(f"manifest {p} is missing")
    raw = p.read_bytes()
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise FreezeError(f"manifest {p} is not JSON: {exc}") from None
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise FreezeError(f"manifest {p} schema is not {SCHEMA!r}")
    for key in ("pins", "files", "inputs"):
        if key not in manifest:
            raise FreezeError(f"manifest {p} lacks {key!r}")
    return manifest, sha256_bytes(raw)


def _entry_differences(root: Path, entries: list, section: str) -> list[str]:
    out: list[str] = []
    for e in entries:
        rel = e.get("path") if isinstance(e, dict) else None
        if not isinstance(rel, str):
            out.append(f"{section}: malformed entry {e!r}")
            continue
        p = root / rel
        if not p.is_file():
            out.append(f"{section}: {rel}: missing")
            continue
        size = p.stat().st_size
        if size != e.get("bytes"):
            out.append(f"{section}: {rel}: bytes {size} != {e.get('bytes')}")
        digest = sha256_file(p)
        if digest != e.get("sha256"):
            out.append(f"{section}: {rel}: sha256 {digest} != "
                       f"{e.get('sha256')}")
    return out


def check_manifest(manifest_path: Path | str,
                   repo_root: Path | str = REPO_ROOT) -> list[str]:
    """Every difference between the manifest and disk; [] means frozen.

    A missing or unreadable manifest is one difference. External entries
    never produce a difference (see external_drift)."""
    root = Path(repo_root)
    try:
        manifest, _ = load_manifest(manifest_path)
    except FreezeError as exc:
        return [str(exc)]
    diffs: list[str] = []
    diffs += _entry_differences(root, manifest["files"], "files")
    diffs += _entry_differences(root, manifest["inputs"], "inputs")
    listed = {e.get("path") for e in manifest["files"] if isinstance(e, dict)}
    try:
        on_disk = harness_files(root)
    except FreezeError as exc:
        on_disk = []
        diffs.append(str(exc))
    for rel in on_disk:
        if rel not in listed and (root / rel).is_file():
            diffs.append(f"files: {rel}: on disk, not in the manifest")
    listed_inputs = {e.get("path") for e in manifest["inputs"]
                     if isinstance(e, dict)}
    for rel in INPUT_PATHS:
        if rel not in listed_inputs:
            diffs.append(f"inputs: {rel}: not in the manifest")
    if (root / HARNESS_DIR).is_dir():
        for rel in bytecode_files(root):
            diffs.append(f"files: {rel}: bytecode under {HARNESS_DIR}/ "
                         "(set PYTHONPYCACHEPREFIX and remove it)")
    pins = manifest["pins"]
    for key, now in versions().items():
        if pins.get(key) != now:
            diffs.append(f"pins: {key} {now} != pinned {pins.get(key)}")
    pinned_constants = pins.get("constants")
    try:
        live = constants_pins()
    except FreezeError as exc:
        diffs.append(f"pins: constants: {exc}")
    else:
        if pinned_constants != live:
            names = sorted(set(live) | set(pinned_constants or {}))
            changed = [n for n in names
                       if (pinned_constants or {}).get(n) != live.get(n)]
            diffs.append(f"pins: constants differ: {changed}")
    return diffs


def loaded_module_differences(manifest_path: Path | str,
                              modules: dict | None = None) -> list[str]:
    """Ruling S3: every loaded news_eval.* module (sys.modules, or `modules`;
    a news_eval module run as __main__ counts under its own name) whose
    __file__ differs from the manifest's files entry of the same
    repository-relative path (relative to the parent of the loaded news_eval
    package), is missing from the manifest, or lies outside that package.
    [] means the imported code is the frozen code."""
    try:
        manifest, _ = load_manifest(manifest_path)
    except FreezeError as exc:
        return [str(exc)]
    listed = {e["path"]: e for e in manifest["files"]
              if isinstance(e, dict) and isinstance(e.get("path"), str)}
    mods = dict(sys.modules if modules is None else modules)
    # `python -m news_eval.run_c2` runs the module as __main__: check it
    # under its own name too.
    main = mods.get("__main__")
    spec_name = getattr(getattr(main, "__spec__", None), "name", None)
    if isinstance(spec_name, str) and spec_name.startswith(HARNESS_DIR + "."):
        mods.setdefault(spec_name, main)
    names = sorted(n for n in mods
                   if n == HARNESS_DIR or n.startswith(HARNESS_DIR + "."))
    pkg = mods.get(HARNESS_DIR)
    pkg_file = getattr(pkg, "__file__", None)
    if not pkg_file:
        return [f"loaded: {HARNESS_DIR} package has no __file__"]
    pkg_dir = Path(pkg_file).resolve().parent
    diffs: list[str] = []
    for name in names:
        file = getattr(mods[name], "__file__", None)
        if not file:
            diffs.append(f"loaded: {name}: no __file__")
            continue
        path = Path(file).resolve()
        if pkg_dir not in path.parents:
            diffs.append(f"loaded: {name}: {path} is outside {pkg_dir}")
            continue
        rel = path.relative_to(pkg_dir.parent).as_posix()
        entry = listed.get(rel)
        if entry is None:
            diffs.append(f"loaded: {name}: {rel} is not in the manifest")
            continue
        digest = sha256_file(path) if path.is_file() else None
        if digest != entry.get("sha256"):
            diffs.append(f"loaded: {name}: {rel} sha256 {digest} != "
                         f"{entry.get('sha256')}")
    return diffs


def verify(manifest_path: Path | str,
           repo_root: Path | str = REPO_ROOT) -> tuple[list[str], str | None]:
    """check_manifest plus loaded_module_differences (rulings S2, S3), and
    the manifest's sha256 (None when it cannot be read)."""
    try:
        _, digest = load_manifest(manifest_path)
    except FreezeError as exc:
        return [str(exc)], None
    diffs = check_manifest(manifest_path, repo_root)
    diffs += loaded_module_differences(manifest_path)
    return diffs, digest


def external_drift(manifest_path: Path | str) -> list[str]:
    """External files whose sha256 changed since the freeze (record only)."""
    manifest, _ = load_manifest(manifest_path)
    out = []
    for e in manifest.get("external", []):
        p = Path(e["path"])
        now = sha256_file(p) if p.is_file() else None
        if now != e.get("sha256"):
            out.append(f"external: {e['path']}: {now} != {e.get('sha256')}")
    return out


# ---------------------------------------------------------------------- CLI

def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m news_eval.freeze")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--out", default=str(REPO_ROOT / MANIFEST_REL))
    w.add_argument("--root", default=str(REPO_ROOT))
    c = sub.add_parser("check")
    c.add_argument("--manifest", default=str(REPO_ROOT / MANIFEST_REL))
    c.add_argument("--root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    if args.cmd == "write":
        try:
            digest = write_manifest(args.out, args.root)
        except FreezeError as exc:
            print(f"FREEZE REFUSED: {exc}", file=sys.stderr)
            return 1
        print(f"wrote {args.out} sha256 {digest}")
        return 0
    diffs = check_manifest(args.manifest, args.root)
    try:
        _, digest = load_manifest(args.manifest)
        print(f"manifest {args.manifest} sha256 {digest}")
        for note in external_drift(args.manifest):
            print(f"note (record only): {note}")
    except FreezeError:
        pass
    for d in diffs:
        print(f"MISMATCH {d}")
    print("FROZEN: match" if not diffs else f"NOT FROZEN: {len(diffs)} "
          "difference(s)")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(_main())
