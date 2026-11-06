"""STAGE C.3 B1: normal-mode byte identity, one tree at a time.

One-off evidence, not a pytest test. Run once per tree, as separate processes:

    PYTHONPYCACHEPREFIX=... nice -n 10 python normal_mode_identity.py <tree root> <out json>

The tree goes first on sys.path and the script asserts news_eval loaded from
it. For EVERY scenario in synthetic.SCENARIOS it builds the database in a temp
directory and records the sha256 of four quantities:

    gate      gate.evaluate's entry, sorted JSON, without utc_time and db_path
    family    family.compute, sorted JSON
    verdict   verdict.decide, sorted JSON
    report    report.write with the fixed relevance summary and run_meta below
              (no "mode" key)

Then compare the two outputs:

    python normal_mode_identity.py --compare <c1 json> <current json> <out txt>

Synthetic databases and temp paths only: sqlite3.connect refuses anything
outside the temp directory. Progress is written after each scenario and a rerun
skips finished ones. Exit 75 means stopped for memory or the collector window,
with the finished scenarios saved.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

EXIT_STOPPED = 75
MIN_MEM_AVAILABLE_KB = 2048 * 1024
WINDOW_START, WINDOW_END = 2255, 2345  # weekdays, local time
QUANTITIES = ("gate", "family", "verdict", "report")
ENTRY_VOLATILE = ("utc_time", "db_path")

FIXED_RELEVANCE = {
    "schema": "c1_relevance_summary/1", "n_sample": 200, "grades_order": [],
    "agreement_opus_fable": {"raw_agreement": 0.9, "n_agree": 180,
                             "n_disagree": 20, "cohens_kappa": 0.81},
    "variants": {}, "rates": {}, "note": "fixture",
}
FIXED_RUN_META = {
    "schema": "c2_run_meta/1",
    "hashes": {"manifest_sha256": "0" * 64, "snapshot_sha256": "1" * 64},
    "snapshot": {"utc_time": "2026-10-20T06:00:00Z",
                 "method": "sqlite3.Connection.backup"},
    "s_star": "2026-10-26",
    "utc_start": "2026-10-20T06:01:00Z",
    "utc_marker": "2026-10-20T06:01:01Z",
    "successor_condition_9_12": {"tracked": False, "last_commit_time": None,
                                 "holds": False},
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sorted_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True)


def mem_available_kb() -> int:
    with open("/proc/meminfo", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    raise RuntimeError("MemAvailable not in /proc/meminfo")


def stop_reason() -> str | None:
    kb = mem_available_kb()
    if kb < MIN_MEM_AVAILABLE_KB:
        return f"MemAvailable {kb // 1024} MB under 2048 MB"
    now = time.localtime()
    hhmm = now.tm_hour * 100 + now.tm_min
    if now.tm_wday < 5 and WINDOW_START <= hhmm < WINDOW_END:
        return f"collector window, local time {hhmm:04d}"
    return None


def guard_connect(allowed_root: str) -> None:
    """Only databases under the temp directory can open."""
    real_connect = sqlite3.connect
    root = os.path.realpath(allowed_root) + os.sep

    def guarded(database, *args, **kwargs):
        text = os.fspath(database)
        if text.startswith("file:"):
            text = text[5:].split("?", 1)[0]
        if text != ":memory:" and not os.path.realpath(text).startswith(root):
            raise RuntimeError(f"refused to open {database}")
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = guarded


def load_tree(root: Path) -> dict:
    sys.path.insert(0, str(root))
    from news_eval import family, gate, report, synthetic, verdict
    import news_eval
    loaded = Path(news_eval.__file__).resolve().parent
    if loaded != (root / "news_eval").resolve():
        raise RuntimeError(f"news_eval loaded from {loaded}, not {root}")
    return {"family": family, "gate": gate, "report": report,
            "synthetic": synthetic, "verdict": verdict}


def scenario_hashes(mods: dict, name: str, directory: str) -> dict:
    db_path = os.path.join(directory, f"{name}.db")
    mods["synthetic"].build(name, db_path)
    entry = mods["gate"].evaluate(db_path)
    stable = {k: v for k, v in entry.items() if k not in ENTRY_VOLATILE}
    results = mods["family"].compute(db_path)
    decision = mods["verdict"].decide(results)
    text = mods["report"].write(results, decision,
                                relevance_summary=FIXED_RELEVANCE,
                                companion=None, run_meta=FIXED_RUN_META)
    return {"gate": sha(sorted_json(stable)),
            "family": sha(sorted_json(results)),
            "verdict": sha(sorted_json(decision)),
            "report": sha(text)}


def write_atomic(path: Path, body: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def measure(root: Path, out: Path) -> int:
    if not sys.pycache_prefix:
        print("REFUSED: set PYTHONPYCACHEPREFIX", file=sys.stderr)
        return 2
    done = json.loads(out.read_text()) if out.exists() \
        else {"tree": str(root), "scenarios": {}}
    with tempfile.TemporaryDirectory(prefix="c3_identity_") as directory:
        guard_connect(directory)
        mods = load_tree(root)
        names = list(mods["synthetic"].SCENARIOS)
        done["scenario_order"] = names
        for name in names:
            if name in done["scenarios"]:
                continue
            why = stop_reason()
            if why:
                write_atomic(out, done)
                print(f"STOPPED before {name}: {why}", file=sys.stderr)
                return EXIT_STOPPED
            start = time.time()
            done["scenarios"][name] = scenario_hashes(mods, name, directory)
            write_atomic(out, done)
            print(f"{name} done in {time.time() - start:.1f} s", flush=True)
    return 0


def compare(left: Path, right: Path, out: Path) -> int:
    a, b = json.loads(left.read_text()), json.loads(right.read_text())
    lines = [f"C.1 tree:     {a['tree']}", f"current tree: {b['tree']}", ""]
    diffs = 0
    names = list(a["scenario_order"])
    if names != list(b["scenario_order"]):
        lines.append(f"SCENARIO LIST DIFF: {names} != {b['scenario_order']}")
        diffs += 1
    for name in names:
        for q in QUANTITIES:
            left_hash = a["scenarios"].get(name, {}).get(q)
            right_hash = b["scenarios"].get(name, {}).get(q)
            same = left_hash is not None and left_hash == right_hash
            diffs += 0 if same else 1
            lines.append(f"{name:12} {q:8} {'MATCH' if same else 'DIFF':5} "
                         f"{left_hash} {right_hash}")
    total = len(names) * len(QUANTITIES)
    lines += ["", f"{total - diffs} MATCH, {diffs} DIFF, of {total}"]
    out.write_text("\n".join(lines) + "\n")
    print(lines[-1])
    return 1 if diffs else 0


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "--compare":
        return compare(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    if len(argv) == 2:
        return measure(Path(argv[0]).resolve(), Path(argv[1]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
