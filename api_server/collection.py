"""Collection monitoring for the running news-drift experiment. READ-ONLY.

WHY THIS MODULE REFUSES TO REPORT AN OUTCOME, WHICH IS ITS MOST IMPORTANT
PROPERTY. EXPERIMENT.md fixes that the holdout is evaluated ONCE, at stage 4,
against pre-registered tests. A dashboard that charts excess return turns a
once-only evaluation into something glanced at daily, and an operator who has
watched the effect accumulate cannot then run a pre-registered test on it: the
decisions the pre-registration exists to constrain (stop early, extend, restrict
the band) would already have been informed by the answer. Seven amendments went
into protecting that ordering. A convenient chart would undo all of them.

SO THE EXCLUSION IS STRUCTURAL, IN FOUR INDEPENDENT LAYERS:

  1. Every SELECT here names its columns as literals. There is no `SELECT *`
     anywhere in this file, so no outcome column can arrive by accident when
     the schema grows.
  2. `FORBIDDEN_COLUMNS` names every outcome quantity, and `_reject_outcomes`
     walks the assembled payload and RAISES if any of those names appears as a
     key. A future edit that adds one ships a 500 rather than a number.
  3. `tests/test_collection_monitor.py` scans THIS FILE'S SOURCE for every
     forbidden identifier, which is what catches the case the key check cannot:
     an aggregate like `AVG(excess_1session) AS mean_excess` whose result key
     looks innocent. That test is mutation-verified.
  4. The queries are aggregate-only over states and judgments. No row-level
     read of an observation exists in this module, so there is no path by
     which one row's outcome could be echoed.

WHAT IT DOES REPORT: progress against the registered floors, whether the
scheduler is alive, what the sample is composed of, and the two pre-registered
DIAGNOSTICS (judgment balance and strength) that Amendment 3 and Amendment 6
specifically require be reported BEFORE any result is interpreted. Those are
not outcomes. They describe the model's own answers and say whether the
registered tests will be able to say anything at all, which is exactly what an
operator needs while collecting and cannot learn from an outcome.

IT DOES NOT IMPORT `news_experiment`. `tests/test_news_experiment_spec.py`
pins that package as standalone and fails on any production import of it, so
the floors below are transcribed as literals with their source cited, and
`tests/test_collection_monitor.py` asserts each one still matches the
specification. Transcription plus a cross-check, rather than a dependency.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_REPO_ROOT, "news_experiment.db")
_DEFAULT_LOG = os.path.join(_REPO_ROOT, "COLLECTION_LOG.md")

TIMER_UNIT = "news-collect.timer"
SERVICE_UNIT = "news-collect.service"

# --- The registered floors, transcribed from EXPERIMENT.md -------------------
# Cross-checked against news_experiment.spec by the test suite, so a drift
# between this transcription and the specification fails rather than misleads.
CLUSTER_FLOOR = 60            # Amendment 5, "Cluster floor 60, unchanged"
CLUSTER_HARD_STOP = 120       # Task 5, the 120-trading-day hard stop
PER_STRATUM_CLUSTER_FLOOR = 30  # Amendment 5, the E-tests' per-stratum floor
JUDGED_TARGET = 1000          # Task 5, required sample size
MINORITY_SHARE_FLOOR = 0.10   # Amendment 6, below this the null is uninformative
MIXED_CLUSTER_FLOOR = 30      # Amendment 6, mixed day clusters needed
NEUTRAL_REPORTABLE_FAILURE = 0.80   # Task 5, a NEUTRAL rate above this fails
MEASURED_COST_PER_CALL = 0.000555   # measured 2026-07-28, 92 calls / 0.051 USD
STRENGTH_DEGENERATE_SHARE = 0.80    # Task 5's recorded reversal condition

# A run whose newest collected session falls this many completed sessions
# behind the calendar is treated as stalled. Two allows for the ordinary case
# where today's session is not collectable yet and yesterday's is in flight.
STALL_SESSIONS = 2

# --- The exclusion ----------------------------------------------------------

# EVERY outcome quantity, named. Nothing in this module may select, aggregate,
# derive from, or return any of these. Enumerated rather than pattern-matched
# so the list is auditable against EXPERIMENT.md Task 8 by eye.
FORBIDDEN_COLUMNS = frozenset({
    "ret_intraday", "ret_1session", "ret_2session", "ret_5session",
    "ret_10session", "bench_1session", "excess_1session", "net_bp",
    "cost_bp_round_trip", "anchor_price",
})

# The columns this module is permitted to read. An allow-list rather than a
# deny-list at the query layer, because a deny-list has to anticipate every
# future column and an allow-list does not.
ALLOWED_COLUMNS = frozenset({
    "query_date", "stratum", "state", "error_class", "judgment", "strength",
    "strength_parse_ok", "cost_usd", "run_kind", "exclusion_reason",
    "outcome_state", "neutral_strength_anomaly",
})


class OutcomeLeak(RuntimeError):
    """An outcome quantity reached the monitoring payload.

    Raised rather than filtered. Filtering would let a leak ship silently
    minus one field, and the operator would have no way to know the view had
    started answering a question it must not answer.
    """


def _reject_outcomes(node, path: str = "$") -> None:
    """Walk the payload and raise on any forbidden key. Called before return."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key) in FORBIDDEN_COLUMNS:
                raise OutcomeLeak(
                    f"outcome quantity '{key}' reached the monitoring payload "
                    f"at {path}. The holdout is evaluated once, at stage 4.")
            _reject_outcomes(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            _reject_outcomes(value, f"{path}[{i}]")


def _db_path() -> str:
    return os.environ.get("MAL_EXPERIMENT_DB", _DEFAULT_DB)


def _log_path() -> str:
    return os.environ.get("MAL_COLLECTION_LOG", _DEFAULT_LOG)


def _analysis_db() -> str:
    return os.environ.get("MAL_ANALYSIS_DB",
                          os.path.join(_REPO_ROOT, "analysis_bars.db"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Progress ---------------------------------------------------------------

def _progress(conn) -> dict:
    sessions = [r[0] for r in conn.execute(
        "SELECT DISTINCT query_date FROM news_observation "
        "WHERE run_kind='collection' ORDER BY query_date")]
    judged, = conn.execute(
        "SELECT COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' AND state='judged'").fetchone()
    scored, = conn.execute(
        "SELECT COUNT(*) FROM news_observation WHERE run_kind='collection' "
        "AND state='judged' AND judgment IN ('POSITIVE','NEGATIVE')").fetchone()

    per_stratum = []
    for stratum, clusters, n_judged in conn.execute(
            "SELECT stratum, COUNT(DISTINCT query_date), "
            "SUM(CASE WHEN state='judged' THEN 1 ELSE 0 END) "
            "FROM news_observation WHERE run_kind='collection' "
            "AND stratum IS NOT NULL AND stratum != '' "
            "GROUP BY stratum ORDER BY stratum"):
        per_stratum.append({
            "stratum": stratum,
            "day_clusters": clusters,
            "judged": n_judged or 0,
            "cluster_floor": PER_STRATUM_CLUSTER_FLOOR,
            "meets_floor": clusters >= PER_STRATUM_CLUSTER_FLOOR,
        })

    n = len(sessions)
    return {
        "day_clusters": n,
        "cluster_floor": CLUSTER_FLOOR,
        "hard_stop": CLUSTER_HARD_STOP,
        "clusters_to_floor": max(0, CLUSTER_FLOOR - n),
        "clusters_to_hard_stop": max(0, CLUSTER_HARD_STOP - n),
        "meets_cluster_floor": n >= CLUSTER_FLOOR,
        "at_hard_stop": n >= CLUSTER_HARD_STOP,
        "judged": judged,
        "judged_target": JUDGED_TARGET,
        "scored_directional": scored,
        "first_session": sessions[0] if sessions else None,
        "last_session": sessions[-1] if sessions else None,
        "per_stratum": per_stratum,
    }


# --- Composition ------------------------------------------------------------

def _composition(conn) -> dict:
    states = {state: n for state, n in conn.execute(
        "SELECT state, COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' GROUP BY state")}
    total = sum(states.values())

    def by_error_class(state: str) -> dict:
        return {(ec or "(none)"): n for ec, n in conn.execute(
            "SELECT error_class, COUNT(*) FROM news_observation "
            "WHERE run_kind='collection' AND state=? GROUP BY error_class",
            (state,))}

    failed = states.get("source_failed", 0)
    return {
        "total_rows": total,
        "states": states,
        # NEVER SUMMED, and kept apart here for the reason Amendment 4 gives:
        # model_failed is operational health (go and look at the provider),
        # excluded_pre_call is sample composition (the effective sample is
        # smaller than the raw headline count). One number answers neither.
        "excluded_pre_call_by_error_class": by_error_class("excluded_pre_call"),
        "model_failed_by_error_class": by_error_class("model_failed"),
        "source_failed_fraction": (failed / total) if total else 0.0,
        "source_failed_critical": bool(total) and failed / total > 0.05,
        "day_excluded_risk": bool(total) and failed / total > 0.20,
        "excluded_outcomes": {
            (reason or "(none)"): n for reason, n in conn.execute(
                "SELECT exclusion_reason, COUNT(*) FROM news_observation "
                "WHERE run_kind='collection' AND outcome_state='excluded' "
                "GROUP BY exclusion_reason")},
        # Rows collected under any other run kind can never count toward the
        # pre-registered sample, so their presence is worth stating.
        "non_collection_rows": {
            kind: n for kind, n in conn.execute(
                "SELECT run_kind, COUNT(*) FROM news_observation "
                "WHERE run_kind != 'collection' GROUP BY run_kind")},
    }


# --- The two pre-registered diagnostics ------------------------------------

def _judgment(conn) -> dict:
    counts = {j: n for j, n in conn.execute(
        "SELECT judgment, COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' AND state='judged' "
        "AND judgment IS NOT NULL GROUP BY judgment")}
    pos = counts.get("POSITIVE", 0)
    neg = counts.get("NEGATIVE", 0)
    neu = counts.get("NEUTRAL", 0)
    directional = pos + neg
    total = directional + neu
    minority = (min(pos, neg) / directional) if directional else 0.0

    mixed, = conn.execute(
        "SELECT COUNT(*) FROM (SELECT query_date FROM news_observation "
        "WHERE run_kind='collection' AND state='judged' "
        "AND judgment IN ('POSITIVE','NEGATIVE') GROUP BY query_date "
        "HAVING COUNT(DISTINCT judgment) > 1)").fetchone()

    per_stratum = []
    for stratum, p, ng, nu in conn.execute(
            "SELECT stratum, "
            "SUM(judgment='POSITIVE'), SUM(judgment='NEGATIVE'), "
            "SUM(judgment='NEUTRAL') FROM news_observation "
            "WHERE run_kind='collection' AND state='judged' "
            "AND stratum IS NOT NULL AND stratum != '' "
            "GROUP BY stratum ORDER BY stratum"):
        per_stratum.append({"stratum": stratum, "positive": p or 0,
                            "negative": ng or 0, "neutral": nu or 0})

    return {
        "positive": pos, "negative": neg, "neutral": neu,
        "directional": directional,
        "neutral_rate": (neu / total) if total else 0.0,
        "neutral_reportable_failure_bar": NEUTRAL_REPORTABLE_FAILURE,
        "neutral_rate_reportable_failure":
            bool(total) and neu / total > NEUTRAL_REPORTABLE_FAILURE,
        "minority_share": minority,
        "minority_share_floor": MINORITY_SHARE_FLOOR,
        "mixed_day_clusters": mixed,
        "mixed_cluster_floor": MIXED_CLUSTER_FLOOR,
        # Amendment 6: below either threshold the permutation null cannot
        # reassure and the affected primary reads as an ABSTENTION. Reported
        # while collecting because by stage 4 it is too late to influence.
        "null_informative": (minority >= MINORITY_SHARE_FLOOR
                             and mixed >= MIXED_CLUSTER_FLOOR),
        "per_stratum": per_stratum,
    }


def _strength(conn) -> dict:
    hist = {int(s): n for s, n in conn.execute(
        "SELECT strength, COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' AND state='judged' "
        "AND judgment IN ('POSITIVE','NEGATIVE') AND strength_parse_ok=1 "
        "AND strength IS NOT NULL GROUP BY strength ORDER BY strength")}
    total = sum(hist.values())
    top = max(hist.values()) if hist else 0
    unparseable, = conn.execute(
        "SELECT COUNT(*) FROM news_observation WHERE run_kind='collection' "
        "AND state='judged' AND strength_parse_ok=0").fetchone()
    anomalies, = conn.execute(
        "SELECT COUNT(*) FROM news_observation WHERE run_kind='collection' "
        "AND neutral_strength_anomaly=1").fetchone()
    return {
        "histogram": hist,
        "scored_directional": total,
        "distinct_values": len(hist),
        "unparseable": unparseable,
        "neutral_strength_anomalies": anomalies,
        # Task 5's recorded condition for revisiting the five-point scale.
        "degenerate": bool(total) and (top / total > STRENGTH_DEGENERATE_SHARE
                                       or len(hist) < 3),
    }


def _spend(conn) -> dict:
    total, calls = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0), COUNT(*) FROM news_observation "
        "WHERE run_kind='collection' AND cost_usd IS NOT NULL").fetchone()
    per_session = [
        {"session": day, "usd": round(usd or 0.0, 6), "calls": n}
        for day, usd, n in conn.execute(
            "SELECT query_date, SUM(cost_usd), COUNT(*) FROM news_observation "
            "WHERE run_kind='collection' AND cost_usd IS NOT NULL "
            "GROUP BY query_date ORDER BY query_date DESC LIMIT 30")]
    per_call = (total / calls) if calls else None
    return {
        "total_usd": round(total, 6),
        "calls": calls,
        "per_call": round(per_call, 8) if per_call is not None else None,
        "measured_per_call": MEASURED_COST_PER_CALL,
        "per_call_drift_pct": (round((per_call / MEASURED_COST_PER_CALL - 1)
                                     * 100, 1) if per_call else None),
        "per_session": per_session,
    }


# --- Run health -------------------------------------------------------------

_RUN_HEADER = re.compile(r"^=== DAILY RUN (\S+) ===$")


def parse_collection_log(text: str) -> list[dict]:
    """Every wrapper run recorded in COLLECTION_LOG.md, oldest first.

    Parsed rather than re-derived so the view reports what the wrapper
    actually wrote. A run the wrapper never logged is a run that did not
    happen, which is the signal this whole view exists to surface.
    """
    runs: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        header = _RUN_HEADER.match(line.strip())
        if header:
            current = {"started_utc": header.group(1), "gaps": []}
            runs.append(current)
            continue
        if current is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "action":
            current["action"] = value
        elif key == "target":
            current["target"] = value
        elif key == "formation":
            current["formation"] = value
        elif key == "exit":
            current["exit_code"] = int(value) if value.isdigit() else None
        elif key == "gap":
            # "N session(s) missing, UNRECOVERABLE by design: a, b"
            _, _, listed = value.partition(":")
            current["gaps"] = [s.strip() for s in listed.split(",")
                               if s.strip()]
        elif key == "detail":
            current["detail"] = value
        elif key == "maintain":
            current["maintenance"] = value
    return runs


def _stamp_to_iso(raw: str | None) -> str | None:
    """Parse a systemd timestamp property into ISO-8601 UTC, or None.

    Queried with `--timestamp=unix`, so systemd answers `@1785450605`. WITHOUT
    that flag it answers a localised human string ("Thu 2026-07-30 15:30:05
    PDT"), which is why the flag is passed rather than the string parsed: a
    locale-dependent format is not something to regex in a monitoring view.
    An empty value means never scheduled or never triggered, and reads as None
    rather than as an epoch-zero date in 1970.
    """
    if not raw:
        return None
    text = raw.strip().lstrip("@")
    if not text.isdigit():
        return None
    seconds = int(text)
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(
        seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _systemd(unit: str = TIMER_UNIT, service: str = SERVICE_UNIT) -> dict:
    """Timer state from systemd, or an explicit unknown.

    An unavailable systemd reports `known: false` rather than a healthy
    default. A monitoring view whose failure mode is "looks fine" is worse
    than no monitoring view at all.
    """
    out = {"known": False, "timer_active": None, "next_fire_utc": None,
           "unit_failed": None, "last_trigger_utc": None, "error": None}
    try:
        p = subprocess.run(
            ["systemctl", "--user", "show", unit, "--timestamp=unix",
             "--property=ActiveState,NextElapseUSecRealtime,LastTriggerUSec"],
            capture_output=True, text=True, timeout=5)
        if p.returncode != 0:
            out["error"] = (p.stderr or "systemctl show failed").strip()[:200]
            return out
        props = dict(line.split("=", 1) for line in p.stdout.splitlines()
                     if "=" in line)
        out["known"] = True
        out["timer_active"] = props.get("ActiveState") == "active"
        out["next_fire_utc"] = _stamp_to_iso(
            props.get("NextElapseUSecRealtime"))
        out["last_trigger_utc"] = _stamp_to_iso(props.get("LastTriggerUSec"))
        f = subprocess.run(["systemctl", "--user", "is-failed", service],
                           capture_output=True, text=True, timeout=5)
        out["unit_failed"] = f.stdout.strip() == "failed"
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _completed_sessions(last_collected: str | None) -> dict:
    """How many completed calendar sessions sit past the newest collected one.

    Read from the same `trading_calendar` the wrapper derives its target from,
    so the view and the scheduler cannot disagree about what a session is.
    """
    out = {"known": False, "sessions_behind": None, "next_expected": None}
    path = _analysis_db()
    if not last_collected or not os.path.exists(path):
        return out
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro",
                                     uri=True)) as conn:
            later = [r[0] for r in conn.execute(
                "SELECT date FROM trading_calendar WHERE date > ? "
                "ORDER BY date", (last_collected,))]
    except sqlite3.Error:
        return out
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out["known"] = True
    out["sessions_behind"] = len([d for d in later if d < today])
    out["next_expected"] = later[0] if later else None
    return out


def _run_health(progress: dict) -> dict:
    runs: list[dict] = []
    path = _log_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                runs = parse_collection_log(fh.read())
        except OSError:
            runs = []
    last = runs[-1] if runs else None
    # Every gap any run ever flagged. A gap is permanent, so it must not stop
    # being reported once a later run succeeds.
    gaps = sorted({g for r in runs for g in r.get("gaps", [])})
    return {
        "log_present": os.path.exists(path),
        "runs_recorded": len(runs),
        "last_run": last,
        "recent_runs": runs[-8:][::-1],
        "gaps": gaps,
        "gap_count": len(gaps),
        "timer": _systemd(),
        "calendar": _completed_sessions(progress.get("last_session")),
    }


# --- Alarms -----------------------------------------------------------------

def _alarms(progress: dict, health: dict, composition: dict, judgment: dict,
            strength: dict, spend: dict) -> list[dict]:
    """Everything that says collection has stopped or is banking rows that
    will not count. Most severe first."""
    out: list[dict] = []

    def add(level: str, code: str, message: str) -> None:
        out.append({"level": level, "code": code, "message": message})

    for session in health["gaps"]:
        add("critical", "gap_unrecoverable",
            f"Session {session} completed and was never collected. "
            f"UNRECOVERABLE: filling it would query historical news, which "
            f"the design forbids. One of the {CLUSTER_FLOOR} required day "
            f"clusters is permanently lost.")

    cal = health["calendar"]
    if cal.get("known") and (cal.get("sessions_behind") or 0) > STALL_SESSIONS:
        add("critical", "collection_stalled",
            f"{cal['sessions_behind']} completed sessions sit past the newest "
            f"collected session ({progress['last_session']}). Collection has "
            f"stopped, and every session lost is unrecoverable.")

    timer = health["timer"]
    if not timer.get("known"):
        add("warn", "timer_unknown",
            f"Cannot read the scheduler state: {timer.get('error')}. The view "
            f"cannot confirm the next run will happen.")
    else:
        if timer.get("unit_failed"):
            add("critical", "unit_failed",
                f"{SERVICE_UNIT} is in the failed state. The next timer fire "
                f"will not recover it on its own.")
        if timer.get("timer_active") is False:
            add("critical", "timer_inactive",
                f"{TIMER_UNIT} is not active. No further collection will run "
                f"until it is re-enabled.")
        if timer.get("next_fire_utc") is None:
            add("warn", "no_next_fire",
                f"{TIMER_UNIT} reports no next fire time.")

    last = health["last_run"]
    if last is None:
        add("warn", "no_run_recorded",
            "COLLECTION_LOG.md records no wrapper run. Either the scheduler "
            "has never fired or it cannot write its log.")
    elif last.get("exit_code") not in (0, None):
        add("warn", "last_run_nonzero",
            f"The last run ({last.get('started_utc')}) exited "
            f"{last['exit_code']} with action '{last.get('action')}'. "
            f"{last.get('detail', '')}".strip())

    if composition["day_excluded_risk"]:
        add("critical", "day_exclusion_risk",
            f"source_failed is "
            f"{composition['source_failed_fraction'] * 100:.1f} percent of "
            f"rows, past the 20 percent bar at which a day leaves the cluster "
            f"count. Those rows will not count.")
    elif composition["source_failed_critical"]:
        add("warn", "source_failed_critical",
            f"source_failed is "
            f"{composition['source_failed_fraction'] * 100:.1f} percent of "
            f"rows, past the 5 percent critical bar.")

    pre_call = sum(composition["excluded_pre_call_by_error_class"].values())
    if pre_call and composition["total_rows"]:
        share = pre_call / composition["total_rows"]
        if share > 0.10:
            add("warn", "sample_composition",
                f"{pre_call} rows ({share * 100:.1f} percent) were excluded "
                f"before any model call, so the effective sample is smaller "
                f"than the raw row count and the power arithmetic is "
                f"optimistic.")

    # Gated on having enough clusters for the check to mean anything. Before
    # MIXED_CLUSTER_FLOOR sessions exist the mixed-cluster count CANNOT reach
    # its floor, so an alarm here would fire every day of the first six weeks
    # and carry no information. An alarm that is always on is an alarm the
    # operator stops reading, which is how a real one gets missed.
    if (judgment["directional"] and not judgment["null_informative"]
            and progress["day_clusters"] >= MIXED_CLUSTER_FLOOR):
        add("warn", "null_uninformative",
            f"Judgment balance would make the permutation null UNINFORMATIVE: "
            f"minority share {judgment['minority_share'] * 100:.1f} percent "
            f"against a {MINORITY_SHARE_FLOOR * 100:.0f} percent floor, "
            f"{judgment['mixed_day_clusters']} mixed day clusters against "
            f"{MIXED_CLUSTER_FLOOR}. Every affected primary would read as an "
            f"abstention.")

    if judgment["neutral_rate_reportable_failure"]:
        add("warn", "neutral_rate",
            f"NEUTRAL rate {judgment['neutral_rate'] * 100:.1f} percent is "
            f"past the {NEUTRAL_REPORTABLE_FAILURE * 100:.0f} percent bar at "
            f"which the design is itself a reportable failure.")

    if strength["scored_directional"] and strength["degenerate"]:
        add("warn", "strength_degenerate",
            f"Strength is degenerate ({strength['distinct_values']} distinct "
            f"values). Both strength secondaries would be uninformative.")

    if strength["unparseable"]:
        add("warn", "strength_unparseable",
            f"{strength['unparseable']} judged rows carry an unparseable "
            f"strength.")

    drift = spend.get("per_call_drift_pct")
    if drift is not None and abs(drift) > 25:
        add("warn", "cost_drift",
            f"Cost per call is {spend['per_call']} against the measured "
            f"{MEASURED_COST_PER_CALL}, {drift:+.1f} percent. The projection "
            f"the budget rests on may no longer hold.")

    if progress["at_hard_stop"]:
        add("warn", "hard_stop",
            f"{progress['day_clusters']} day clusters reaches the "
            f"{CLUSTER_HARD_STOP}-session hard stop. Collection should end.")

    return out


# --- The one entry point ----------------------------------------------------

def monitor() -> dict:
    """The whole monitoring payload. Read-only, outcome-free by construction.

    Every value returned is a count, a floor, a state string, a timestamp or a
    spend figure. No return, benchmark, excess or net quantity is read,
    aggregated or derived anywhere in this module.
    """
    path = _db_path()
    payload: dict = {
        "generated_utc": _now(),
        "db_present": os.path.exists(path),
        "outcome_columns_excluded": sorted(FORBIDDEN_COLUMNS),
        "exclusion_note": (
            "The holdout is evaluated ONCE, at stage 4, against the "
            "pre-registered tests. This view reports progress and health and "
            "cannot report an outcome. See EXPERIMENT.md."),
    }
    if not os.path.exists(path):
        payload.update({
            "error": "the experiment database does not exist yet",
            "progress": None, "composition": None, "judgment": None,
            "strength": None, "spend": None,
            "run_health": _run_health({"last_session": None}),
            "alarms": [{"level": "warn", "code": "no_database",
                        "message": f"No experiment database at {path}."}],
        })
        _reject_outcomes(payload)
        return payload

    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        progress = _progress(conn)
        composition = _composition(conn)
        judgment = _judgment(conn)
        strength = _strength(conn)
        spend = _spend(conn)
    health = _run_health(progress)

    payload.update({
        "progress": progress,
        "run_health": health,
        "composition": composition,
        "judgment": judgment,
        "strength": strength,
        "spend": spend,
        "alarms": _alarms(progress, health, composition, judgment, strength,
                          spend),
    })
    # The last line of defence: an outcome that reached the payload raises
    # rather than rendering.
    _reject_outcomes(payload)
    return payload
