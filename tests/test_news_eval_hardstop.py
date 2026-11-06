"""Tests for the hard-stop readout (STAGE C.3 Part B; EXPERIMENT.md Amendment
10.1 and 10.2).

Synthetic databases and tmp paths only. A snapshot straddling the hard stop is
a scenario built by news_eval.synthetic with SHIFT_DAYS added to scoring_session
and query_date, then stripped of the synthetic marker, so it classifies
NON_SYNTHETIC as the real run does. The real constant K.HARD_STOP_SESSION is
never patched in the happy path. With the 84 day shift, session 2026-10-23 lands
exactly on 2027-01-15 and one full resolved session (2026-10-26) lands after it,
as 2027-01-18, which is S*. S-HIGHRHO then gives a gate FAIL on REQUIRED alone,
and S-EFFECT gives a PASS and a clear (C stays at 63, above the floor of 60).

Expected counts come from sql_counts: raw SQL on the shifted copy, written here
and sharing no code with the harness.

family.compute is expensive, so three full runs happen, module scoped:
fail_run (S-HIGHRHO --hard-stop), pass_hs_run (S-EFFECT --hard-stop) and
pass_normal_run (S-EFFECT in normal mode). Refusals and mutants work through
check_preconditions, gate.evaluate, family.build_analysis on loaded inputs and
report.write on the cached results.

Mutants (STAGE C.3 B5) are applied at source level to one function: the exact old
text must be present, is replaced, and the result is compiled with the module's
globals and monkeypatched in. Kill checks pass on the unmutated harness first.
PRECONDITIONS holds function objects, so a mutant of a precondition also rebuilds
that tuple; patching the module attribute alone would change nothing.

The guard compares (exists, size, mtime_ns) of reports/c2_UNLOCK.json,
reports/c2_RUN_ONCE.json and reports/c2: they legitimately exist in the repo root
and are absent in a clean clone, and these tests pass in both.
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import re
import shutil
import sqlite3
import textwrap
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pytest

import test_news_eval_run_c2 as RC
from news_eval import constants as K
from news_eval import cutoff
from news_eval import data
from news_eval import family
from news_eval import freeze
from news_eval import gate
from news_eval import report
from news_eval import run_c2
from news_eval import stats
from news_eval import synthetic
from news_eval import verdict

HARD_STOP = "2027-01-15"
SHIFT_DAYS = 84
S_STAR_SHIFTED = "2027-01-18"
SENTINEL_CUTOFF = "2026-12-31"
OTHER_SHA = "b" * 64
GATE_LINE_QUANTITIES = ("C", "M", "required", "sigma", "rho")
LABEL_LINE = f"Label (Amendment 10.2): {K.HARD_STOP_LABEL}."
RUN_MODE_LINE = (f"- Run mode: {K.MODE_HARD_STOP} (run_c2 run --hard-stop, "
                 "Amendment 10.1).")
PASS_SENTENCE = ("The gate passed on this snapshot, so the registered power rule "
                 "is met and the Amendment 10.2 label does not apply.")
GATE_LINE_RE = re.compile(
    r"Hard-stop gate line \(Amendment 10\.2\): C = (?P<C>\d+), M = (?P<M>\d+), "
    r"Required = (?P<required>[\d.]+), sigma = (?P<sigma>[\d.]+) bp, "
    r"rho = (?P<rho>[\d.]+)\.")
C2_PATHS = tuple(freeze.REPO_ROOT / "reports" / name
                 for name in ("c2_UNLOCK.json", "c2_RUN_ONCE.json", "c2"))
_RAW_CONNECT = sqlite3.connect
_REPO_REAL_DB = os.path.realpath(data.COMPILED_REAL_DB_PATH)
_FORBIDDEN_DB_NAMES = ("news_experiment.db", "analysis_bars.db")


# -------------------------------------------------------------------- guards

class RealDatabaseOpened(BaseException):
    """Raised by the patched sqlite3.connect; nothing swallows it."""


def _is_forbidden_db(database: object) -> bool:
    if isinstance(database, int):
        return False
    text = os.fsdecode(database)
    if text.startswith("file:"):
        text = text[5:].split("?", 1)[0]
    if not text or text == ":memory:":
        return False
    real = os.path.realpath(text)
    if real == _REPO_REAL_DB or os.path.basename(real) in _FORBIDDEN_DB_NAMES:
        return True
    try:
        a, b = os.stat(text), os.stat(_REPO_REAL_DB)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _guarded_connect(database, *args, **kwargs):
    if _is_forbidden_db(database):
        raise RealDatabaseOpened(f"test opened a real database: {database}")
    return _RAW_CONNECT(database, *args, **kwargs)


def _c2_state() -> dict[str, tuple]:
    """(exists, size, mtime_ns) of each reports/c2* path; stat only."""
    out: dict[str, tuple] = {}
    for path in C2_PATHS:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            out[path.name] = (False, None, None)
        else:
            out[path.name] = (True, st.st_size, st.st_mtime_ns)
    return out


@pytest.fixture(scope="module", autouse=True)
def module_patch(tmp_path_factory):
    """Module scope because the staged snapshots and the three full runs are:
    no real database, test mode on, MemAvailable fixed, reports/c2* unchanged."""
    before = _c2_state()
    defaults = tmp_path_factory.mktemp("guard_defaults")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sqlite3, "connect", _guarded_connect)
        mp.setattr(data, "UNLOCK_PATH", str(defaults / "dflt_unlock"))
        mp.setattr(data, "RUN_ONCE_PATH", str(defaults / "dflt_marker"))
        mp.setenv(data.TEST_MODE_ENV, "1")
        mp.setattr(run_c2, "_mem_available_mb", lambda: RC.PLENTY_MB)
        yield mp
    assert _c2_state() == before


@pytest.fixture(autouse=True)
def _hardstop_guards():
    before = _c2_state()
    yield
    assert _c2_state() == before


def test_guard_refuses_the_real_databases_before_opening():
    for path in (data.COMPILED_REAL_DB_PATH,
                 str(freeze.REPO_ROOT / "analysis_bars.db")):
        with pytest.raises(RealDatabaseOpened):
            sqlite3.connect(path)


# ------------------------------------------------------- independent SQL

def shift_dates(path: Path, days: int = SHIFT_DAYS) -> None:
    conn = _RAW_CONNECT(path)
    try:
        for column in ("scoring_session", "query_date"):
            conn.execute(
                f"UPDATE news_observation SET {column} = date({column}, ?) "
                f"WHERE {column} IS NOT NULL AND {column} != ''",
                (f"+{days} days",))
        conn.commit()
    finally:
        conn.close()


def sql_counts(db: Path, limit: str) -> dict[str, int | str]:
    """The expected counts at scoring_session <= limit: EXPERIMENT.md 9.1, 9.7
    and 9.8 written as raw SQL here, sharing no code with the harness."""
    conn = _RAW_CONNECT(f"file:{db}?mode=ro", uri=True)
    try:
        excluded = [r[0] for r in conn.execute(
            "SELECT query_date FROM news_observation "
            "WHERE run_kind = 'collection' GROUP BY query_date "
            "HAVING 1.0 * SUM(state = 'source_failed') / COUNT(*) > 0.20")]
        marks = ",".join("?" * len(excluded))
        scorable = (
            "run_kind = 'collection' AND state = 'judged' "
            "AND outcome_state = 'resolved' AND exclusion_reason = '' "
            "AND scoring_session IS NOT NULL AND scoring_session != '' "
            f"AND query_date NOT IN ({marks})")
        gate_where = f"{scorable} AND excess_1session IS NOT NULL"
        directional = f"{gate_where} AND judgment IN ('POSITIVE', 'NEGATIVE')"

        def one(select: str, where: str, *args: str) -> int | str:
            return conn.execute(
                f"SELECT {select} FROM news_observation WHERE {where}",
                (*excluded, *args)).fetchone()[0]

        def judged_beyond() -> int:
            return conn.execute(
                "SELECT COUNT(*) FROM news_observation "
                "WHERE run_kind = 'collection' AND state = 'judged' "
                "AND scoring_session IS NOT NULL AND scoring_session != '' "
                "AND scoring_session > ?", (limit,)).fetchone()[0]

        within, beyond = "scoring_session <= ?", "scoring_session > ?"
        return {
            "N": one("COUNT(*)", f"{gate_where} AND {within}", limit),
            "M": one("COUNT(*)", f"{directional} AND {within}", limit),
            "C": one("COUNT(DISTINCT scoring_session)",
                     f"{directional} AND {within}", limit),
            "C_G": one("COUNT(DISTINCT scoring_session)",
                       f"{gate_where} AND {within}", limit),
            "last_session": one("MAX(scoring_session)",
                                f"{gate_where} AND {within}", limit),
            "N_at_limit": one("COUNT(*)", f"{gate_where} AND scoring_session = ?",
                              limit),
            "N_beyond": one("COUNT(*)", f"{gate_where} AND {beyond}", limit),
            "M_beyond": one("COUNT(*)", f"{directional} AND {beyond}", limit),
            "dropped_beyond": one("COUNT(*)", f"{scorable} AND {beyond}", limit),
            "judged_beyond": judged_beyond(),
            "latest_resolved": one("MAX(scoring_session)", gate_where),
        }
    finally:
        conn.close()


def sql_gate_rows(db: Path, limit: str) -> tuple[list[float], list[str],
                                                 dict[str, int]]:
    """(excess, session, directional per session), ordered by session and id."""
    conn = _RAW_CONNECT(f"file:{db}?mode=ro", uri=True)
    try:
        excluded = [r[0] for r in conn.execute(
            "SELECT query_date FROM news_observation "
            "WHERE run_kind = 'collection' GROUP BY query_date "
            "HAVING 1.0 * SUM(state = 'source_failed') / COUNT(*) > 0.20")]
        marks = ",".join("?" * len(excluded))
        where = (
            "run_kind = 'collection' AND state = 'judged' "
            "AND outcome_state = 'resolved' AND exclusion_reason = '' "
            "AND scoring_session IS NOT NULL AND scoring_session != '' "
            f"AND query_date NOT IN ({marks}) AND excess_1session IS NOT NULL "
            "AND scoring_session <= ?")
        rows = conn.execute(
            f"SELECT excess_1session, scoring_session FROM news_observation "
            f"WHERE {where} ORDER BY scoring_session, id",
            (*excluded, limit)).fetchall()
        per = dict(conn.execute(
            f"SELECT scoring_session, COUNT(*) FROM news_observation "
            f"WHERE {where} AND judgment IN ('POSITIVE', 'NEGATIVE') "
            "GROUP BY scoring_session", (*excluded, limit)).fetchall())
    finally:
        conn.close()
    return [r[0] for r in rows], [r[1] for r in rows], per


# -------------------------------------------------------------- staging

def staged_with_entry(root: Path, source: Path, mp: pytest.MonkeyPatch,
                      expect_rc: int) -> dict:
    """RC.stage on a NON_SYNTHETIC copy, then the real gate on its snapshot."""
    paths = RC.stage(root, source, mp, demark=True, gate_pass=False)
    rc = gate.run(paths["snapshot"], paths["gate_log"],
                  real_db_path=paths["live"], unlock_path=paths["unlock"],
                  manifest_path=paths["manifest"])
    assert rc == expect_rc
    lines = paths["gate_log"].read_text().splitlines()
    assert len(lines) == 1
    return {**paths, "source": source, "entry": json.loads(lines[0])}


def completed_run(paths: dict, *flags: str) -> dict:
    """run_c2.main end to end. Records each phase opened and whether the marker
    existed at that moment."""
    phases: list[tuple[data.Phase, bool]] = []
    real_open = data.open_phase

    def recording(phase, *args, **kwargs):
        phases.append((data.Phase(phase), paths["marker"].exists()))
        return real_open(phase, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(data, "open_phase", recording)
        rc = run_c2.main([*paths["argv"], *flags])
    out = paths["out"]
    stopped = out / run_c2.STOPPED_NAME
    assert rc == run_c2.EXIT_OK, stopped.read_text() if stopped.exists() else rc
    results_text = (out / run_c2.RESULTS_NAME).read_text()
    doc = json.loads(results_text)
    return {**paths, "rc": rc, "phases": phases, "results_text": results_text,
            "results": doc["results"], "decision": doc["decision"],
            "companion": doc["companion_horizons"],
            "text": (out / run_c2.VERDICT_NAME).read_text(),
            "meta": json.loads((out / run_c2.RUN_META_NAME).read_text()),
            "marker_body": json.loads(paths["marker"].read_text())}


@pytest.fixture(scope="module")
def sources(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("sources")
    out = {}
    for name in ("S-HIGHRHO", "S-EFFECT"):
        raw = base / f"{name}.db"
        synthetic.build(name, raw)
        shifted = base / f"{name}.shifted.db"
        shutil.copyfile(raw, shifted)
        shift_dates(shifted)
        out[name], out[f"{name}+shift"] = raw, shifted
    return out


@pytest.fixture(scope="module")
def fail_stage(tmp_path_factory, sources, module_patch) -> dict:
    """Post-hard-stop S-HIGHRHO with its real FAIL entry. Never run: refusals."""
    return staged_with_entry(tmp_path_factory.mktemp("fail_stage"),
                             sources["S-HIGHRHO+shift"], module_patch,
                             gate.EXIT_FAIL)


@pytest.fixture(scope="module")
def early_stage(tmp_path_factory, sources, module_patch) -> dict:
    """Unshifted S-HIGHRHO: S* before the hard stop, a real status ok entry."""
    return staged_with_entry(tmp_path_factory.mktemp("early_stage"),
                             sources["S-HIGHRHO"], module_patch, gate.EXIT_FAIL)


def _shifted_stage(root: Path, source: Path, days: int,
                   mp: pytest.MonkeyPatch) -> dict:
    copied = root.parent / f"{root.name}.source.db"
    shutil.copyfile(source, copied)
    shift_dates(copied, days)
    return staged_with_entry(root, copied, mp, gate.EXIT_FAIL)


@pytest.fixture(scope="module")
def on_stop_stage(tmp_path_factory, sources, module_patch) -> dict:
    """S-HIGHRHO shifted so that S* is exactly the hard stop."""
    return _shifted_stage(tmp_path_factory.mktemp("on_stop_stage"),
                          sources["S-HIGHRHO"], 81, module_patch)


@pytest.fixture(scope="module")
def day_before_stage(tmp_path_factory, sources, module_patch) -> dict:
    """S-HIGHRHO shifted so that S* is the day before the hard stop."""
    return _shifted_stage(tmp_path_factory.mktemp("day_before_stage"),
                          sources["S-HIGHRHO"], 80, module_patch)


@pytest.fixture(scope="module")
def fail_run(tmp_path_factory, sources, module_patch) -> dict:
    paths = staged_with_entry(tmp_path_factory.mktemp("fail_run"),
                              sources["S-HIGHRHO+shift"], module_patch,
                              gate.EXIT_FAIL)
    return completed_run(paths, "--hard-stop")


@pytest.fixture(scope="module")
def pass_hs_run(tmp_path_factory, sources, module_patch) -> dict:
    paths = staged_with_entry(tmp_path_factory.mktemp("pass_hs_run"),
                              sources["S-EFFECT+shift"], module_patch,
                              gate.EXIT_PASS)
    return completed_run(paths, "--hard-stop")


@pytest.fixture(scope="module")
def pass_normal_run(tmp_path_factory, sources, module_patch) -> dict:
    paths = staged_with_entry(tmp_path_factory.mktemp("pass_normal_run"),
                              sources["S-EFFECT+shift"], module_patch,
                              gate.EXIT_PASS)
    return completed_run(paths)


@pytest.fixture(scope="module")
def expected(sources) -> dict[str, int | str]:
    """Independent counts on shifted S-HIGHRHO at the hard stop."""
    return sql_counts(sources["S-HIGHRHO+shift"], HARD_STOP)


@pytest.fixture(scope="module")
def fail_inputs(fail_run) -> family.Inputs:
    """Loaded after the run: the VERDICT phase needs its marker."""
    return family.load_inputs(fail_run["snapshot"],
                              real_db_path=fail_run["live"],
                              unlock_path=fail_run["unlock"],
                              marker_path=fail_run["marker"])


def hard_stop_flag(paths: dict) -> dict:
    return {**paths, "argv": [*paths["argv"], "--hard-stop"]}


def with_arg(paths: dict, flag: str, value: Path) -> dict:
    argv = list(paths["argv"])
    argv[argv.index(flag) + 1] = str(value)
    return {**paths, "argv": argv}


def with_log(paths: dict, directory: Path, *entries: dict) -> dict:
    """The stage with its gate log replaced by one holding these entries."""
    log = directory / "custom_gate.jsonl"
    log.write_text("".join(json.dumps(e, sort_keys=True) + "\n"
                           for e in entries))
    return {**with_arg(paths, "--gate-log", log), "gate_log": log}


def with_marker(paths: dict, directory: Path) -> dict:
    marker_path = directory / "custom_marker.json"
    marker_path.write_text("{}\n")
    return {**with_arg(paths, "--marker", marker_path), "marker": marker_path}


def refuses(paths: dict, capsys, check: str, directory: Path,
            contains: str = "") -> None:
    """Exit 2 at this precondition with nothing written under the stage root or
    the test's own directory, and no marker unless the test placed one."""
    placed_marker = paths["marker"].exists()
    before = (RC.tree(paths["root"]), RC.tree(directory))
    rc = run_c2.main(paths["argv"])
    err = capsys.readouterr().err
    assert rc == run_c2.EXIT_REFUSED, err
    assert f"precondition {check}:" in err, err
    assert contains in err, err
    assert (RC.tree(paths["root"]), RC.tree(directory)) == before
    assert paths["marker"].exists() is placed_marker
    assert not paths["out"].exists()


def section_4(text: str) -> str:
    return text[text.index(report.H_VERDICT):text.index(report.H_CUTOFF)]


def before_readings(section: str) -> str:
    return section[:section.index("### Primary reading")]


def reading_chunks(section: str) -> dict[str, str]:
    start = section.index("### Primary reading")
    middle = section.index("### Sensitivity reading")
    end = section.index("### Primary against the 8.2 sensitivity reading")
    return {"primary": section[start:middle], "sensitivity": section[middle:end]}


def hard_stop_report(run: dict, *, passed: bool) -> str:
    """report.write on cached results with this gate outcome in run_meta."""
    meta = {**run["meta"], "mode": K.MODE_HARD_STOP,
            "gate_entry": {**run["meta"]["gate_entry"], "pass": passed}}
    return report.write(run["results"], run["decision"],
                        relevance_summary=RC.RELEVANCE_FIXTURE,
                        companion=run["companion"], run_meta=meta)


def refusal_of(paths: dict) -> run_c2.Refused:
    """The Refused from check_preconditions, or an AssertionError if accepted."""
    try:
        run_c2.check_preconditions(RC.config(paths))
    except run_c2.Refused as exc:
        return exc
    raise AssertionError("check_preconditions accepted")


# ------------------------------------------------- B1 normal mode, in pytest
# The byte identity against C.1 is reports/c3_evidence/normal_mode_identity.txt.

def test_entry_before_the_hard_stop_gains_no_hard_stop_key(early_stage):
    entry = early_stage["entry"]
    assert entry["status"] == gate.STATUS_OK
    assert entry["s_star"] < HARD_STOP
    assert "hard_stop_session" not in entry
    assert "analysis_cutoff" not in entry


def test_gate_counts_before_the_hard_stop_are_the_unrestricted_counts(
        early_stage, sources):
    exp = sql_counts(sources["S-HIGHRHO"], early_stage["entry"]["s_star"])
    entry = early_stage["entry"]
    assert exp["N_beyond"] == 0
    assert (entry["N"], entry["M"], entry["C"]) == (exp["N"], exp["M"], exp["C"])


# ------------------------------------------------------- B2 the happy path

def test_shifted_fixture_straddles_the_hard_stop(expected, fail_run):
    assert expected["latest_resolved"] == S_STAR_SHIFTED
    assert expected["last_session"] == HARD_STOP
    assert expected["N_at_limit"] > 0
    assert expected["N_beyond"] > 0
    assert expected["M_beyond"] > 0
    assert fail_run["entry"]["s_star"] == S_STAR_SHIFTED > HARD_STOP


def test_hard_stop_run_exits_zero_on_a_real_required_fail(fail_run):
    entry = fail_run["entry"]
    assert fail_run["rc"] == run_c2.EXIT_OK
    assert entry["pass"] is False
    assert entry["status"] == gate.STATUS_OK
    assert entry["failing"] == [gate.FAIL_REQUIRED]
    non_synthetic = data.DbClass.NON_SYNTHETIC.value
    assert entry["db_class"] == non_synthetic
    assert fail_run["meta"]["snapshot_db_class"] == non_synthetic
    assert not (fail_run["out"] / run_c2.STOPPED_NAME).exists()


def test_gate_line_and_label_sit_beside_the_verdict_in_section_4(fail_run):
    head = before_readings(section_4(fail_run["text"]))
    assert "One-line summary:" in head
    assert GATE_LINE_RE.search(head)
    assert LABEL_LINE in head
    assert head.index("One-line summary:") < GATE_LINE_RE.search(head).start() \
        < head.index(LABEL_LINE)
    # S-HIGHRHO does not clear, so the only label is the gate line's.
    assert fail_run["text"].count(K.HARD_STOP_LABEL) == 1


def test_gate_line_numbers_are_the_gate_entrys(fail_run):
    entry = fail_run["entry"]
    line = GATE_LINE_RE.search(section_4(fail_run["text"]))
    assert int(line["C"]) == entry["C"]
    assert int(line["M"]) == entry["M"]
    assert line["required"] == f"{entry['required']:.1f}"
    assert line["sigma"] == f"{entry['sigma']:.1f}"
    assert line["rho"] == f"{entry['rho']:.3f}"
    assert entry["M"] < entry["required"]


def test_marker_and_run_meta_record_the_hard_stop_mode(fail_run):
    assert fail_run["marker_body"]["mode"] == "hard_stop"
    assert fail_run["meta"]["mode"] == "hard_stop"
    assert fail_run["meta"]["gate_entry"] == fail_run["entry"]
    assert RUN_MODE_LINE in fail_run["text"]


def test_results_record_the_hard_stop_session_and_cutoff(fail_run):
    analysis_set = fail_run["results"]["analysis_set"]
    assert analysis_set["hard_stop_session"] == HARD_STOP
    assert analysis_set["analysis_cutoff"] == HARD_STOP
    assert analysis_set["cutoff"]["s_star"] == S_STAR_SHIFTED
    assert "- Hard stop (10.1):" in fail_run["text"]


def test_gate_counts_match_independent_restricted_sql(fail_run, expected):
    entry = fail_run["entry"]
    assert entry["hard_stop_session"] == HARD_STOP
    assert entry["analysis_cutoff"] == HARD_STOP
    assert (entry["N"], entry["M"], entry["C"], entry["C_G"]) == (
        expected["N"], expected["M"], expected["C"], expected["C_G"])


def test_funnel_counts_match_independent_restricted_sql(fail_run, expected):
    funnel = fail_run["results"]["analysis_set"]["funnel"]
    assert funnel["gate_rows"] == expected["N"]
    assert funnel["scored"] == expected["M"]
    assert funnel["judged_beyond_s_star_any_outcome"] \
        == expected["judged_beyond"]
    assert funnel["dropped_first_reason"][family.DROP_BEYOND_S_STAR] \
        == expected["dropped_beyond"]


def test_no_row_after_the_hard_stop_is_in_the_gate_rows_or_analysis_set(
        fail_run, fail_inputs, expected):
    with data.open_phase(data.Phase.GATE, fail_run["snapshot"],
                         real_db_path=fail_run["live"],
                         unlock_path=fail_run["unlock"]) as phase:
        _, cut, rows, directional = gate._read_inputs(phase)
    analysis = family.build_analysis(fail_inputs)
    assert cut.s_star == S_STAR_SHIFTED
    assert len(rows.scoring_session) == expected["N"]
    assert max(rows.scoring_session) == HARD_STOP
    assert max(directional) == HARD_STOP
    assert sum(directional.values()) == expected["M"]
    for row_set in (analysis.gate_rows, analysis.scored):
        assert max(r["scoring_session"] for r in row_set) == HARD_STOP
    assert fail_run["results"]["halves"]["second_half_last"] == HARD_STOP


def test_gate_sigma_and_rho_are_computed_on_the_restricted_rows(fail_run,
                                                                sources):
    db = sources["S-HIGHRHO+shift"]

    def quantities(limit: str) -> stats.GateResult:
        excess, sessions, per = sql_gate_rows(db, limit)
        return stats.gate_quantities(
            excess, sessions, per, power_constant=K.REQUIRED_FACTOR,
            effect_bp=K.EFFECT_BP, min_clusters=K.FLOOR_ANALYSIS_CLUSTERS,
            min_directional=K.FLOOR_SCORABLE)

    restricted, raw = quantities(HARD_STOP), quantities(S_STAR_SHIFTED)
    entry = fail_run["entry"]
    assert (entry["sigma"], entry["rho"], entry["required"]) == (
        restricted.sigma, restricted.rho, restricted.required)
    assert raw.n_rows > restricted.n_rows
    assert raw.required != restricted.required


def test_verdict_phase_opens_only_after_the_marker_exists(fail_run):
    verdict_opens = [has_marker for phase, has_marker in fail_run["phases"]
                     if phase is data.Phase.VERDICT]
    assert verdict_opens
    assert all(verdict_opens)


def test_clear_with_a_fail_entry_puts_the_label_after_the_registered_row(
        pass_hs_run):
    decision = pass_hs_run["decision"]
    text = hard_stop_report(pass_hs_run, passed=False)
    section = section_4(text)
    assert LABEL_LINE in before_readings(section)
    for name, chunk in reading_chunks(section).items():
        reading = decision["readings"][name]
        assert reading["gross"]["gross_reading"] == verdict.GROSS_CLEARS
        assert reading["rows"]
        for row in reading["rows"]:
            cell = verdict.VERDICT_TABLE[row["key"]][1]
            assert chunk.index(cell) < chunk.index(LABEL_LINE)
        assert chunk.count(K.HARD_STOP_LABEL) == 1
    assert text.count(K.HARD_STOP_LABEL) == 3


def test_report_write_does_not_change_verdict_decides_output(pass_hs_run):
    decision = pass_hs_run["decision"]
    before = copy.deepcopy(decision)
    hard_stop_report(pass_hs_run, passed=False)
    assert decision == before
    decided = verdict.decide(pass_hs_run["results"])
    assert json.loads(json.dumps(decided)) == before


def test_hard_stop_report_only_adds_lines_to_the_normal_report(pass_hs_run):
    meta = {k: v for k, v in pass_hs_run["meta"].items() if k != "mode"}
    normal = report.write(pass_hs_run["results"], pass_hs_run["decision"],
                          relevance_summary=RC.RELEVANCE_FIXTURE,
                          companion=pass_hs_run["companion"], run_meta=meta)
    text = hard_stop_report(pass_hs_run, passed=False)
    gate_line = GATE_LINE_RE.search(text).group(0)
    stripped = (text.replace(gate_line + "\n\n", "")
                .replace(LABEL_LINE + "\n\n", "")
                .replace(RUN_MODE_LINE + "\n", ""))
    assert stripped == normal


def test_the_normal_mode_key_changes_no_report_byte(pass_normal_run):
    """A3 adds "mode" to run_meta unconditionally. The byte identity against
    C.1 used a run_meta with no such key (diff review N-6), and this closes it."""
    meta = pass_normal_run["meta"]
    assert meta["mode"] == K.MODE_NORMAL
    without = {k: v for k, v in meta.items() if k != "mode"}
    with_key, no_key = (
        report.write(pass_normal_run["results"], pass_normal_run["decision"],
                     relevance_summary=RC.RELEVANCE_FIXTURE,
                     companion=pass_normal_run["companion"], run_meta=m)
        for m in (meta, without))
    assert with_key == no_key


def test_a_powered_negative_on_a_fail_run_meets_the_10_2_interval_rule(fail_run):
    """10.2, third bullet, on a real hard-stop run (test record observation 4).
    S-HIGHRHO reads as a powered negative beside the FAIL label. The rule is
    written out from the amendment rather than read from verdict.py: P1's upper
    bound below 30 bp and no primary clearing."""
    chunks = reading_chunks(section_4(fail_run["text"]))
    readings = fail_run["decision"]["readings"]
    assert set(readings) == {"primary", "sensitivity"}
    for name, reading in readings.items():
        gross = reading["gross"]
        assert gross["gross_reading"] == "powered_negative"
        assert gross["p1_upper"] < 30.0
        assert not [t for t, status in reading["statuses"].items()
                    if t.startswith("P") and status == verdict.CLEAR]
        assert "- Gross reading: powered_negative." in chunks[name]
        assert "**A powered negative:**" in chunks[name]


def test_an_abstention_is_reported_in_those_words(fail_run):
    """10.2, fourth bullet. The selection rule stays with the verdict tests;
    this is the wording the report prints for it."""
    reading = fail_run["decision"]["readings"]["primary"]
    abstention = {**reading, "statements": [], "gross": {
        **reading["gross"], "gross_reading": verdict.GROSS_ABSTENTION}}
    assert verdict.GROSS_ABSTENTION == "abstention"
    assert ("- Gross reading: abstention. "
            in "\n".join(report._reading_verdict("primary", abstention)))


def test_hard_stop_with_a_pass_entry_runs_without_the_label(pass_hs_run):
    assert pass_hs_run["rc"] == run_c2.EXIT_OK
    assert pass_hs_run["entry"]["pass"] is True
    assert pass_hs_run["marker_body"]["mode"] == "hard_stop"
    assert pass_hs_run["meta"]["mode"] == "hard_stop"
    assert K.HARD_STOP_LABEL not in pass_hs_run["text"]
    head = before_readings(section_4(pass_hs_run["text"]))
    assert GATE_LINE_RE.search(head)
    assert PASS_SENTENCE in head


def test_s_effect_stays_a_pass_and_a_clear_after_the_restriction(pass_hs_run,
                                                                 sources):
    exp = sql_counts(sources["S-EFFECT+shift"], HARD_STOP)
    entry = pass_hs_run["entry"]
    assert exp["N_beyond"] > 0
    assert (entry["N"], entry["M"], entry["C"]) == (exp["N"], exp["M"], exp["C"])
    assert entry["C"] >= K.FLOOR_ANALYSIS_CLUSTERS
    primary = pass_hs_run["decision"]["readings"]["primary"]
    assert primary["gross"]["gross_reading"] == verdict.GROSS_CLEARS


def test_normal_mode_after_the_hard_stop_is_restricted_with_no_gate_line(
        pass_normal_run, sources):
    exp = sql_counts(sources["S-EFFECT+shift"], HARD_STOP)
    analysis_set = pass_normal_run["results"]["analysis_set"]
    text = pass_normal_run["text"]
    assert pass_normal_run["rc"] == run_c2.EXIT_OK
    assert pass_normal_run["marker_body"]["mode"] == "normal"
    assert pass_normal_run["meta"]["mode"] == "normal"
    assert analysis_set["hard_stop_session"] == HARD_STOP
    assert analysis_set["analysis_cutoff"] == HARD_STOP
    assert analysis_set["funnel"]["gate_rows"] == exp["N"]
    assert analysis_set["funnel"]["scored"] == exp["M"]
    assert pass_normal_run["entry"]["N"] == exp["N"]
    assert "- Hard stop (10.1):" in text
    assert "Hard-stop gate line" not in text
    assert K.HARD_STOP_LABEL not in text
    assert PASS_SENTENCE not in text
    assert "Run mode" not in text


def test_the_mode_does_not_change_a_result(pass_hs_run, pass_normal_run):
    assert pass_hs_run["results_text"] == pass_normal_run["results_text"]


# --------------------------------------------------------- B3 the refusals

def test_hard_stop_refuses_s_star_before_the_hard_stop(early_stage, capsys,
                                                       tmp_path):
    refuses(hard_stop_flag(early_stage), capsys, "gate_pass", tmp_path,
            "is earlier than")


@pytest.mark.parametrize("passed", [True, False])
def test_s_star_guard_refuses_alone_even_with_an_otherwise_usable_entry(
        early_stage, capsys, tmp_path, passed):
    entry = {**early_stage["entry"], "pass": passed,
             "analysis_cutoff": early_stage["entry"]["s_star"]}
    paths = with_log(hard_stop_flag(early_stage), tmp_path, entry)
    refuses(paths, capsys, "gate_pass", tmp_path, "is earlier than")


def test_hard_stop_refuses_s_star_the_day_before_the_hard_stop(
        day_before_stage, capsys, tmp_path):
    assert day_before_stage["entry"]["s_star"] == "2027-01-14"
    assert "analysis_cutoff" not in day_before_stage["entry"]
    refuses(hard_stop_flag(day_before_stage), capsys, "gate_pass", tmp_path,
            "is earlier than")


def test_hard_stop_accepts_s_star_exactly_on_the_hard_stop(on_stop_stage,
                                                           sources):
    entry = on_stop_stage["entry"]
    before = RC.tree(on_stop_stage["root"])
    facts = run_c2.check_preconditions(RC.config(hard_stop_flag(on_stop_stage)))
    exp = sql_counts(on_stop_stage["source"], HARD_STOP)
    assert facts["s_star"] == HARD_STOP
    assert facts["gate_entry"] == entry
    assert entry["analysis_cutoff"] == entry["hard_stop_session"] == HARD_STOP
    assert exp["N_beyond"] == 0
    assert (entry["N"], entry["M"], entry["C"]) == (exp["N"], exp["M"], exp["C"])
    assert RC.tree(on_stop_stage["root"]) == before


def test_hard_stop_refuses_an_empty_gate_log(fail_stage, capsys, tmp_path):
    paths = with_log(hard_stop_flag(fail_stage), tmp_path)
    refuses(paths, capsys, "gate_pass", tmp_path, "no usable gate entry")


def test_hard_stop_refuses_a_log_holding_only_another_snapshot(
        fail_stage, capsys, tmp_path):
    other = {**fail_stage["entry"], "inputs_sha256": OTHER_SHA}
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, other)
    refuses(paths, capsys, "gate_pass", tmp_path, "no usable gate entry")


def test_hard_stop_refuses_a_missing_gate_log_file(fail_stage, capsys, tmp_path):
    paths = with_arg(hard_stop_flag(fail_stage), "--gate-log",
                     tmp_path / "absent.jsonl")
    refuses(paths, capsys, "gate_pass", tmp_path, "gate log unreadable")


def test_hard_stop_refuses_a_log_line_that_is_not_json(fail_stage, capsys,
                                                       tmp_path):
    log = tmp_path / "broken.jsonl"
    log.write_text("not json\n")
    paths = with_arg(hard_stop_flag(fail_stage), "--gate-log", log)
    refuses(paths, capsys, "gate_pass", tmp_path, "is not JSON")


def test_hard_stop_refuses_a_degenerate_entry(fail_stage, capsys, tmp_path):
    entry = {**fail_stage["entry"], "status": gate.STATUS_DEGENERATE}
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, entry)
    refuses(paths, capsys, "gate_pass", tmp_path, "degenerate entry")


def test_hard_stop_refuses_a_degenerate_entry_beside_an_ok_entry(
        fail_stage, capsys, tmp_path):
    entry = fail_stage["entry"]
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, entry,
                     {**entry, "status": gate.STATUS_DEGENERATE})
    refuses(paths, capsys, "gate_pass", tmp_path, "degenerate entry")


def test_hard_stop_refuses_an_entry_with_no_status(fail_stage, capsys, tmp_path):
    entry = {k: v for k, v in fail_stage["entry"].items() if k != "status"}
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, entry)
    refuses(paths, capsys, "gate_pass", tmp_path, "degenerate entry")


def test_hard_stop_refuses_when_a_marker_is_present(fail_stage, capsys, tmp_path):
    paths = with_marker(hard_stop_flag(fail_stage), tmp_path)
    refuses(paths, capsys, "marker_absent", tmp_path, "exists: C.2 has run")


def _without(key: str) -> Callable[[dict], dict]:
    return lambda e: {k: v for k, v in e.items() if k != key}


def _setting(key: str, value: object) -> Callable[[dict], dict]:
    return lambda e: {**e, key: value}


UNUSABLE_ENTRIES: dict[str, Callable[[dict], dict]] = {
    "another_manifest": _setting("manifest_sha256", "a" * 64),
    "no_manifest": _without("manifest_sha256"),
    "another_s_star": _setting("s_star", "2027-01-20"),
    "no_s_star": _without("s_star"),
    "no_analysis_cutoff": _without("analysis_cutoff"),
    "raw_s_star_as_cutoff": _setting("analysis_cutoff", S_STAR_SHIFTED),
    "pass_int": _setting("pass", 1),
    "pass_string": _setting("pass", "false"),
    "pass_null": _setting("pass", None),
    "pass_missing": _without("pass"),
    **{f"no_{q}": _without(q) for q in GATE_LINE_QUANTITIES},
    **{f"string_{q}": _setting(q, "63") for q in GATE_LINE_QUANTITIES},
    **{f"null_{q}": _setting(q, None) for q in GATE_LINE_QUANTITIES},
    **{f"bool_{q}": _setting(q, True) for q in GATE_LINE_QUANTITIES},
}


@pytest.mark.parametrize("name", UNUSABLE_ENTRIES)
def test_hard_stop_refuses_an_unusable_entry(fail_stage, capsys, tmp_path, name):
    entry = UNUSABLE_ENTRIES[name](fail_stage["entry"])
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, entry)
    refuses(paths, capsys, "gate_pass", tmp_path, "no usable gate entry")


def test_the_quantities_tested_are_the_ones_the_runner_requires():
    assert run_c2.GATE_LINE_FIELDS == GATE_LINE_QUANTITIES


EARLIER_OTHER_REFUSED = {
    "passed": {"pass": True, "s_star": "2026-12-01"},
    "reached_the_hard_stop_after_it": {"pass": False, "s_star": S_STAR_SHIFTED},
    "reached_the_hard_stop_exactly": {"pass": False, "s_star": HARD_STOP},
}


@pytest.mark.parametrize("name", EARLIER_OTHER_REFUSED)
def test_hard_stop_refuses_an_earlier_entry_for_another_snapshot(
        fail_stage, capsys, tmp_path, name):
    other = {**fail_stage["entry"], "inputs_sha256": OTHER_SHA,
             **EARLIER_OTHER_REFUSED[name]}
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, other,
                     fail_stage["entry"])
    refuses(paths, capsys, "gate_pass", tmp_path, "an earlier gate log entry")


def test_normal_mode_refuses_a_fail_entry_after_the_hard_stop(fail_stage, capsys,
                                                              tmp_path):
    refuses(fail_stage, capsys, "gate_pass", tmp_path, "FAIL or degenerate")


@pytest.mark.parametrize("flags", [("--hard-stop",), ()],
                         ids=["second_hard_stop", "normal"])
@pytest.mark.parametrize("run_name", ["fail_run", "pass_normal_run"])
def test_a_completed_run_refuses_every_later_run(request, capsys, tmp_path,
                                                 run_name, flags):
    run = request.getfixturevalue(run_name)
    before = RC.tree(run["root"])
    rc = run_c2.main([*run["argv"], *flags])
    err = capsys.readouterr().err
    assert rc == run_c2.EXIT_REFUSED, err
    assert "precondition marker_absent:" in err, err
    assert RC.tree(run["root"]) == before


ACCEPTED_LOGS = {
    "later_other_reached_the_hard_stop": (
        ("mine", {"pass": False, "s_star": S_STAR_SHIFTED}), 1),
    "later_other_passed": (("mine", {"pass": True, "s_star": S_STAR_SHIFTED}), 1),
    "earlier_other_failed_before_the_hard_stop": (
        ({"pass": False, "s_star": "2027-01-08"}, "mine"), 2),
    "earlier_other_failed_with_no_s_star": (
        ({"pass": False, "s_star": None}, "mine"), 2),
}


@pytest.mark.parametrize("name", ACCEPTED_LOGS)
def test_other_snapshot_entries_that_do_not_bar_the_run_are_accepted(
        fail_stage, tmp_path, name):
    layout, line_no = ACCEPTED_LOGS[name]
    entry = fail_stage["entry"]
    entries = [entry if item == "mine"
               else {**entry, "inputs_sha256": OTHER_SHA, **item}
               for item in layout]
    paths = with_log(hard_stop_flag(fail_stage), tmp_path, *entries)
    before = (RC.tree(fail_stage["root"]), RC.tree(tmp_path))
    facts = run_c2.check_preconditions(RC.config(paths))
    assert facts["gate_entry_line"] == line_no
    assert facts["gate_entry"] == entry
    assert (RC.tree(fail_stage["root"]), RC.tree(tmp_path)) == before


def test_hard_stop_flag_defaults_off_and_is_not_a_test_only_flag(fail_stage):
    assert RC.config(fail_stage).hard_stop is False
    assert RC.config(hard_stop_flag(fail_stage)).hard_stop is True
    assert "hard_stop" not in run_c2.TEST_ONLY_FLAGS["run"]


# ------------------------------- the gate log pin (C.3 review, run-once SF-1)

def registered_config(gate_log: Path | str, hard_stop: bool) -> run_c2.RunConfig:
    """Every other path is the registered default. Constructed, never run."""
    return run_c2.RunConfig(
        snapshot=Path("s"), out_dir=Path("o"),
        manifest=freeze.REPO_ROOT / freeze.MANIFEST_REL,
        unlock=Path(data.COMPILED_UNLOCK_PATH),
        marker=Path(data.COMPILED_RUN_ONCE_PATH),
        gate_log=Path(gate_log), relevance_summary=Path("r"),
        repo_root=freeze.REPO_ROOT, real_db=data.COMPILED_REAL_DB_PATH,
        hard_stop=hard_stop)


def test_hard_stop_refuses_another_gate_log_outside_test_mode(tmp_path,
                                                              monkeypatch):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    with pytest.raises(run_c2.Refused) as exc:
        registered_config(tmp_path / "own_log.jsonl", hard_stop=True)
    assert exc.value.check == "config"
    assert "gate_log=" in exc.value.reason


def test_hard_stop_accepts_the_registered_gate_log_outside_test_mode(monkeypatch):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    monkeypatch.chdir(freeze.REPO_ROOT)
    assert run_c2.GATE_LOG_REL == "reports/c2/gate_log.jsonl"
    assert registered_config(run_c2.GATE_LOG_REL, hard_stop=True).hard_stop
    assert registered_config(freeze.REPO_ROOT / run_c2.GATE_LOG_REL,
                             hard_stop=True).hard_stop


def test_normal_mode_leaves_the_gate_log_free_as_in_c1(tmp_path, monkeypatch):
    monkeypatch.delenv(data.TEST_MODE_ENV)
    assert not registered_config(tmp_path / "own_log.jsonl",
                                 hard_stop=False).hard_stop


def test_the_cli_refuses_hard_stop_with_another_gate_log(tmp_path, monkeypatch,
                                                         capsys):
    """Run-once SF-1's demonstration: a later snapshot with a log of its own."""
    monkeypatch.delenv(data.TEST_MODE_ENV)
    for name, value in (("UNLOCK_PATH", data.COMPILED_UNLOCK_PATH),
                        ("RUN_ONCE_PATH", data.COMPILED_RUN_ONCE_PATH),
                        ("REAL_DB_PATH", data.COMPILED_REAL_DB_PATH)):
        monkeypatch.setattr(data, name, value)
    out = tmp_path / "out"
    rc = run_c2.main(["run", "--hard-stop", "--snapshot", "s", "--out-dir",
                      str(out), "--gate-log", str(tmp_path / "own_log.jsonl"),
                      "--relevance-summary", "r"])
    err = capsys.readouterr().err
    assert rc == run_c2.EXIT_REFUSED, err
    assert "precondition config" in err and "gate_log=" in err
    assert not out.exists()


def test_the_last_usable_entry_is_the_one_read(fail_stage, tmp_path):
    """As in normal mode. Test record observation 3: only a hand-edited log can
    hold two different entries for one snapshot and manifest, and the C.2b
    verifier compares every entry for the snapshot with a rerun of the gate."""
    entry = fail_stage["entry"]
    paths = with_log(hard_stop_flag(fail_stage), tmp_path,
                     {**entry, "pass": True}, entry)
    facts = run_c2.check_preconditions(RC.config(paths))
    assert facts["gate_entry_line"] == 2
    assert facts["gate_entry"]["pass"] is False


# --------------------------------------------- B4 the restriction is shared

def test_gate_and_results_agree_on_the_cutoff_and_counts(fail_run):
    entry = fail_run["entry"]
    analysis_set = fail_run["results"]["analysis_set"]
    assert entry["analysis_cutoff"] == analysis_set["analysis_cutoff"] == HARD_STOP
    assert entry["N"] == analysis_set["funnel"]["gate_rows"]
    assert entry["M"] == analysis_set["funnel"]["scored"]


def test_patching_the_one_function_moves_gate_rows_and_analysis_set(
        fail_run, fail_inputs, sources, monkeypatch):
    kw = {"real_db_path": fail_run["live"], "unlock_path": fail_run["unlock"],
          "manifest_path": fail_run["manifest"]}
    base_entry = gate.evaluate(fail_run["snapshot"], **kw)
    base_funnel = family.build_analysis(fail_inputs).funnel
    assert base_entry["N"] == base_funnel["gate_rows"] == fail_run["entry"]["N"]

    monkeypatch.setattr(cutoff, "analysis_cutoff",
                        lambda s_star: SENTINEL_CUTOFF)
    entry = gate.evaluate(fail_run["snapshot"], **kw)
    analysis = family.build_analysis(fail_inputs)

    exp = sql_counts(sources["S-HIGHRHO+shift"], SENTINEL_CUTOFF)
    assert exp["N"] < base_entry["N"]
    assert entry["analysis_cutoff"] == SENTINEL_CUTOFF
    assert (entry["N"], entry["M"], entry["C"]) == (exp["N"], exp["M"], exp["C"])
    assert analysis.funnel["gate_rows"] == exp["N"]
    assert analysis.funnel["scored"] == exp["M"]
    assert analysis.funnel["judged_beyond_s_star_any_outcome"] \
        == exp["judged_beyond"]
    assert max(r["scoring_session"] for r in analysis.gate_rows) \
        == exp["last_session"]


@pytest.mark.parametrize("s_star, want", [
    (None, None),
    ("2027-01-14", "2027-01-14"),
    ("2026-08-03", "2026-08-03"),
    (HARD_STOP, HARD_STOP),
    ("2027-01-18", HARD_STOP),
    ("2028-03-01", HARD_STOP),
])
def test_analysis_cutoff_is_the_minimum_of_s_star_and_the_hard_stop(s_star, want):
    assert cutoff.analysis_cutoff(s_star) == want


@pytest.mark.parametrize("s_star, want", [
    (None, {}),
    ("2027-01-14", {}),
    (HARD_STOP, {"hard_stop_session": HARD_STOP, "analysis_cutoff": HARD_STOP}),
    ("2027-01-18", {"hard_stop_session": HARD_STOP,
                    "analysis_cutoff": HARD_STOP}),
])
def test_hard_stop_record_is_empty_before_the_hard_stop(s_star, want):
    assert cutoff.hard_stop_record(s_star) == want


def _scorable_row(session: str) -> dict:
    return {"run_kind": K.RUN_KIND_COLLECTION, "state": K.STATE_JUDGED,
            "outcome_state": K.OUTCOME_RESOLVED,
            "exclusion_reason": K.EXCLUSION_NONE, "scoring_session": session,
            "query_date": "2027-01-14", "excess_1session": 0.001}


def test_a_row_scoring_exactly_on_the_hard_stop_is_included():
    limit = cutoff.analysis_cutoff(S_STAR_SHIFTED)
    reason = family.scorable_filter((), limit)
    assert reason(_scorable_row(HARD_STOP)) is None
    assert reason(_scorable_row("2027-01-14")) is None
    assert reason(_scorable_row("2027-01-18")) == family.DROP_BEYOND_S_STAR


def test_the_hard_stop_session_row_count_enters_on_the_snapshot(fail_inputs,
                                                                expected):
    analysis = family.build_analysis(fail_inputs)
    on_it = sum(1 for r in analysis.gate_rows
                if r["scoring_session"] == HARD_STOP)
    assert on_it == expected["N_at_limit"] > 0


def test_companion_horizons_read_only_the_restricted_scored_rows(fail_run,
                                                                 expected):
    companion = family.companion_horizons(fail_run["snapshot"],
                                          real_db_path=fail_run["live"],
                                          unlock_path=fail_run["unlock"],
                                          marker_path=fail_run["marker"])
    horizons = companion["horizons"]
    assert horizons
    for horizon in horizons.values():
        assert horizon["n_obs"] + horizon["n_null"] == expected["M"]


def test_hard_stop_session_is_session_120_from_the_weekday_calendar():
    holidays = {date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
                date(2027, 1, 1)}
    day, session = date(2026, 7, 28), 0
    while True:
        if day.weekday() < 5 and day not in holidays:
            session += 1
            if session == 120:
                break
        day += timedelta(days=1)
    assert day.isoformat() == HARD_STOP == K.HARD_STOP_SESSION


def test_hard_stop_label_is_quoted_verbatim_from_experiment_md():
    text = Path(data.EXPERIMENT_MD_PATH).read_text(encoding="utf-8")
    assert K.HARD_STOP_LABEL == "registered power rule NOT met"
    assert f'"{K.HARD_STOP_LABEL}"' in text


def test_preconditions_under_hard_stop_open_only_the_gate_phase(fail_stage,
                                                                monkeypatch):
    phases: list[data.Phase] = []
    real_open = data.open_phase

    def recording(phase, *args, **kwargs):
        phases.append(data.Phase(phase))
        return real_open(phase, *args, **kwargs)

    monkeypatch.setattr(data, "open_phase", recording)
    run_c2.check_preconditions(RC.config(hard_stop_flag(fail_stage)))
    assert phases
    assert set(phases) == {data.Phase.GATE}


# ------------------------------------------------------------ B5 the mutants

@dataclass(frozen=True)
class Env:
    """What the kill checks read. Fetched before any mutant is applied."""
    fail_stage: dict
    early_stage: dict
    on_stop_stage: dict
    fail_run: dict
    clear_run: dict
    inputs: family.Inputs
    expected: dict


@pytest.fixture(scope="module")
def env(fail_stage, early_stage, on_stop_stage, fail_run, pass_hs_run,
        fail_inputs, expected) -> Env:
    return Env(fail_stage=fail_stage, early_stage=early_stage,
               on_stop_stage=on_stop_stage, fail_run=fail_run,
               clear_run=pass_hs_run, inputs=fail_inputs, expected=expected)


def kill_gate_counts(env: Env, work: Path) -> None:
    stage = env.fail_stage
    entry = gate.evaluate(stage["snapshot"], real_db_path=stage["live"],
                          unlock_path=stage["unlock"],
                          manifest_path=stage["manifest"])
    assert (entry["N"], entry["M"], entry["C"]) == (
        env.expected["N"], env.expected["M"], env.expected["C"])


def kill_analysis_counts(env: Env, work: Path) -> None:
    funnel = family.build_analysis(env.inputs).funnel
    assert funnel["gate_rows"] == env.expected["N"]
    assert funnel["scored"] == env.expected["M"]


def kill_funnel_beyond(env: Env, work: Path) -> None:
    funnel = family.build_analysis(env.inputs).funnel
    assert funnel["judged_beyond_s_star_any_outcome"] \
        == env.expected["judged_beyond"]


def kill_s_star_guard(env: Env, work: Path) -> None:
    """An entry otherwise usable, so only the S* guard can refuse it. A real
    entry before the hard stop has no analysis_cutoff and the usable filter
    refuses it too, under another message."""
    entry = {**env.early_stage["entry"],
             "analysis_cutoff": env.early_stage["entry"]["s_star"]}
    exc = refusal_of(with_log(hard_stop_flag(env.early_stage), work, entry))
    assert exc.check == "gate_pass"
    assert "is earlier than" in exc.reason


def kill_s_star_on_the_hard_stop_accepted(env: Env, work: Path) -> None:
    facts = run_c2.check_preconditions(
        RC.config(hard_stop_flag(env.on_stop_stage)))
    assert facts["s_star"] == HARD_STOP


def kill_label_on_fail_entry(env: Env, work: Path) -> None:
    text = hard_stop_report(env.fail_run, passed=False)
    assert LABEL_LINE in before_readings(section_4(text))
    assert text.count(K.HARD_STOP_LABEL) == 1


def kill_label_after_clear(env: Env, work: Path) -> None:
    text = hard_stop_report(env.clear_run, passed=False)
    for chunk in reading_chunks(section_4(text)).values():
        assert chunk.count(K.HARD_STOP_LABEL) == 1
    assert text.count(K.HARD_STOP_LABEL) == 3


def kill_marker_precondition(env: Env, work: Path) -> None:
    """Directly on check_preconditions: through run_c2.main the O_EXCL create in
    write_marker refuses under the same check name, so main cannot see M4."""
    paths = with_marker(hard_stop_flag(env.fail_stage), work)
    assert refusal_of(paths).check == "marker_absent"


def kill_normal_refuses_fail(env: Env, work: Path) -> None:
    exc = refusal_of(env.fail_stage)
    assert exc.check == "gate_pass"
    assert "FAIL or degenerate" in exc.reason


def kill_no_label_after_pass(env: Env, work: Path) -> None:
    text = hard_stop_report(env.clear_run, passed=True)
    assert K.HARD_STOP_LABEL not in text
    assert PASS_SENTENCE in text


def kill_earlier_pass_refused(env: Env, work: Path) -> None:
    other = {**env.fail_stage["entry"], "inputs_sha256": OTHER_SHA, "pass": True,
             "s_star": "2026-12-01"}
    exc = refusal_of(with_log(hard_stop_flag(env.fail_stage), work, other,
                              env.fail_stage["entry"]))
    assert exc.check == "gate_pass"
    assert "an earlier gate log entry" in exc.reason


def kill_gate_log_pin(env: Env, work: Path) -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv(data.TEST_MODE_ENV)
        try:
            registered_config(work / "other.jsonl", hard_stop=True)
        except run_c2.Refused as exc:
            assert "gate_log=" in exc.reason
            return
    raise AssertionError("another gate log was accepted under --hard-stop")


def kill_earlier_reached_refused(env: Env, work: Path) -> None:
    other = {**env.fail_stage["entry"], "inputs_sha256": OTHER_SHA,
             "pass": False, "s_star": S_STAR_SHIFTED}
    exc = refusal_of(with_log(hard_stop_flag(env.fail_stage), work, other,
                              env.fail_stage["entry"]))
    assert exc.check == "gate_pass"
    assert "an earlier gate log entry" in exc.reason


KILL_CHECKS: dict[str, Callable[[Env, Path], None]] = {
    f.__name__: f for f in (
        kill_gate_counts, kill_analysis_counts, kill_funnel_beyond,
        kill_s_star_guard, kill_s_star_on_the_hard_stop_accepted,
        kill_label_on_fail_entry, kill_label_after_clear,
        kill_marker_precondition, kill_normal_refuses_fail,
        kill_no_label_after_pass, kill_earlier_pass_refused,
        kill_earlier_reached_refused, kill_gate_log_pin)}


@dataclass(frozen=True)
class Edit:
    module: object
    function: str
    old: str
    new: str


@dataclass(frozen=True)
class Mutant:
    name: str
    edits: tuple[Edit, ...]
    kills: tuple[str, ...]  # exactly the checks that must fail under it


LABEL_OUT = '        out += [f"Label (Amendment 10.2): {K.HARD_STOP_LABEL}.", ""]'
EDIT_LABEL_LINES = Edit(report, "_hard_stop_lines", LABEL_OUT, "        pass")
EDIT_LABEL_CLEAR = Edit(report, "_reading_verdict", LABEL_OUT, "        pass")
MUTANTS = (
    Mutant("M1_restriction_on_the_analysis_set_only",
           (Edit(gate, "_read_inputs",
                 "limit = cutoff.analysis_cutoff(cut.s_star)",
                 "limit = cut.s_star"),),
           ("kill_gate_counts",)),
    Mutant("M2_hard_stop_allows_s_star_before_it",
           (Edit(run_c2, "_hard_stop_gate",
                 "    if s_star < K.HARD_STOP_SESSION:", "    if False:"),),
           ("kill_s_star_guard",)),
    Mutant("M2b_hard_stop_refuses_s_star_on_the_hard_stop",
           (Edit(run_c2, "_hard_stop_gate",
                 "    if s_star < K.HARD_STOP_SESSION:",
                 "    if s_star <= K.HARD_STOP_SESSION:"),),
           ("kill_s_star_on_the_hard_stop_accepted",)),
    Mutant("M3_label_dropped_in_both_places",
           (EDIT_LABEL_LINES, EDIT_LABEL_CLEAR),
           ("kill_label_on_fail_entry", "kill_label_after_clear")),
    Mutant("M3a_label_dropped_from_the_gate_line",
           (EDIT_LABEL_LINES,),
           ("kill_label_on_fail_entry", "kill_label_after_clear")),
    Mutant("M3b_label_dropped_after_a_clear",
           (EDIT_LABEL_CLEAR,),
           ("kill_label_after_clear",)),
    Mutant("M4_hard_stop_skips_marker_absent",
           (Edit(run_c2, "_check_marker_absent",
                 "    if os.path.lexists(cfg.marker):",
                 "    if not cfg.hard_stop and os.path.lexists(cfg.marker):"),),
           ("kill_marker_precondition",)),
    Mutant("M5_restriction_on_the_gate_only",
           (Edit(family, "build_analysis",
                 "scorable_filter(excluded, cutoff.analysis_cutoff(sstar.s_star))",
                 "scorable_filter(excluded, sstar.s_star)"),),
           ("kill_analysis_counts",)),
    Mutant("M6_normal_mode_accepts_a_fail_entry",
           (Edit(run_c2, "_check_gate_pass",
                 'if e.get("pass") is not True or e.get("status") '
                 '!= GATE_STATUS_OK]',
                 'if e.get("status") != GATE_STATUS_OK]'),),
           ("kill_normal_refuses_fail",)),
    Mutant("M7_label_on_the_gate_line_after_a_pass_entry",
           (Edit(report, "_hard_stop_lines", '    if entry["pass"] is False:',
                 "    if True:"),),
           ("kill_no_label_after_pass",)),
    Mutant("M7b_label_after_a_clear_on_a_pass_entry",
           (Edit(report, "_verdict",
                 'clear_label = hard_stop is not None and '
                 'hard_stop["pass"] is False',
                 "clear_label = hard_stop is not None"),),
           ("kill_no_label_after_pass",)),
    Mutant("M8_earlier_pass_and_first_snapshot_check_dropped",
           (Edit(run_c2, "_hard_stop_gate", "    if earlier:", "    if False:"),),
           ("kill_earlier_pass_refused", "kill_earlier_reached_refused")),
    Mutant("M8a_earlier_pass_check_dropped",
           (Edit(run_c2, "_hard_stop_gate",
                 'e.get("pass") is True\n        or (isinstance',
                 "(isinstance"),),
           ("kill_earlier_pass_refused",)),
    Mutant("M8b_first_snapshot_check_dropped",
           (Edit(run_c2, "_hard_stop_gate",
                 '\n        or (isinstance(e.get("s_star"), str)\n'
                 '            and e["s_star"] >= K.HARD_STOP_SESSION))]',
                 ")]"),),
           ("kill_earlier_reached_refused",)),
    Mutant("M9_funnel_keeps_the_raw_s_star",
           (Edit(family, "_funnel",
                 "s_star = cutoff.analysis_cutoff(sstar.s_star)",
                 "s_star = sstar.s_star"),),
           ("kill_funnel_beyond",)),
    Mutant("M10_hard_stop_leaves_the_gate_log_unpinned",
           (Edit(run_c2.RunConfig, "__post_init__", "    if self.hard_stop:",
                 "    if False:"),),
           ("kill_gate_log_pin",)),
)


def apply_edit(mp: pytest.MonkeyPatch, edit: Edit) -> None:
    """Source level: the exact old text once, replaced, compiled with the
    module's globals, monkeypatched in. A precondition is also swapped inside
    the PRECONDITIONS tuple, which holds the function objects. edit.module may
    be a class, for a method: its globals are its module's."""
    original = getattr(edit.module, edit.function)
    source = textwrap.dedent(inspect.getsource(original))
    assert source.count(edit.old) == 1, \
        f"old text not found once in {edit.function}: {edit.old!r}"
    namespace: dict = {}
    scope = vars(edit.module if inspect.ismodule(edit.module)
                 else inspect.getmodule(edit.module))
    exec(compile(source.replace(edit.old, edit.new),  # noqa: S102
                 f"<mutant {edit.function}>", "exec"),
         scope, namespace)
    mutated = namespace[edit.function]
    mp.setattr(edit.module, edit.function, mutated)
    if edit.module is run_c2:
        registry = tuple((name, mutated if check is original else check)
                         for name, check in run_c2.PRECONDITIONS)
        mp.setattr(run_c2, "PRECONDITIONS", registry)


def failing_checks(names: tuple[str, ...], env: Env, base: Path) -> list[str]:
    out = []
    for name in names:
        work = base / name
        work.mkdir(exist_ok=True)
        try:
            KILL_CHECKS[name](env, work)
        except Exception:  # noqa: BLE001 - a crash under a mutant is a kill too
            out.append(name)
    return out


def mutant_named(prefix: str) -> Mutant:
    return next(m for m in MUTANTS if m.name.startswith(prefix + "_"))


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.name)
def test_mutant_is_killed(mutant, env, tmp_path):
    assert failing_checks(mutant.kills, env, tmp_path) == []
    with pytest.MonkeyPatch.context() as mp:
        for edit in mutant.edits:
            apply_edit(mp, edit)
        failed = failing_checks(mutant.kills, env, tmp_path)
    assert failed, f"SURVIVED: {mutant.name}"
    assert tuple(failed) == mutant.kills
    assert failing_checks(mutant.kills, env, tmp_path) == []


def test_under_m2_a_real_early_entry_still_refuses_at_the_usable_filter(
        early_stage):
    """Why M2's kill check needs a crafted entry: a real entry before the hard
    stop has no analysis_cutoff, so a second guard refuses it."""
    with pytest.MonkeyPatch.context() as mp:
        for edit in mutant_named("M2").edits:
            apply_edit(mp, edit)
        exc = refusal_of(hard_stop_flag(early_stage))
    assert exc.check == "gate_pass"
    assert "no usable gate entry" in exc.reason


def test_under_m4_main_still_refuses_at_the_exclusive_create(fail_stage, capsys,
                                                             tmp_path):
    """Why M4's kill check calls check_preconditions: through main the O_EXCL
    create in write_marker refuses under the same check name."""
    paths = with_marker(hard_stop_flag(fail_stage), tmp_path)
    before = (RC.tree(fail_stage["root"]), RC.tree(tmp_path))
    with pytest.MonkeyPatch.context() as mp:
        for edit in mutant_named("M4").edits:
            apply_edit(mp, edit)
        rc = run_c2.main(paths["argv"])
    err = capsys.readouterr().err
    assert rc == run_c2.EXIT_REFUSED, err
    assert "precondition marker_absent:" in err, err
    assert "appeared" in err, err
    assert (RC.tree(fail_stage["root"]), RC.tree(tmp_path)) == before
