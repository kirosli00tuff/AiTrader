"""The collection monitoring view (api_server/collection.py).

THE TEST THAT MATTERS MOST is the one asserting no outcome quantity can reach
the response. EXPERIMENT.md fixes the holdout as evaluated ONCE, at stage 4,
against pre-registered tests. A dashboard that shows excess return turns that
into a daily glance and destroys the pre-registration, so the exclusion is
enforced in four layers and checked here three ways:

  by KEY, walking the assembled payload,
  by VALUE, against a sentinel written into every outcome column, and
  by SOURCE, scanning the module for every forbidden identifier.

The source scan is the one that catches what the key walk cannot: an aggregate
like `AVG(excess_1session) AS mean_excess` produces an innocent-looking key.
Both the source scan and the gap surfacing are mutation-verified below.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from api_server import collection  # noqa: E402

# Every outcome quantity, restated INDEPENDENTLY of the module so this test is
# a second opinion rather than a mirror. A module that quietly shrank its own
# forbidden set would still fail here.
OUTCOME_COLUMNS = (
    "ret_intraday", "ret_1session", "ret_2session", "ret_5session",
    "ret_10session", "bench_1session", "excess_1session", "net_bp",
    "cost_bp_round_trip", "anchor_price",
)
# Written into every outcome column so a leak through an aggregate shows up as
# a value even when its key looks innocent.
SENTINEL = 0.4242

SESSIONS = ("2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05")


def build_db(path: str, rows: list[dict]) -> None:
    """A news_observation table carrying POPULATED outcome columns.

    Populated on purpose: a monitoring module tested against a database whose
    outcome columns happen to be NULL would pass while leaking.
    """
    cols = [
        "query_date TEXT", "stratum TEXT", "state TEXT", "error_class TEXT",
        "judgment TEXT", "strength INTEGER", "strength_parse_ok INTEGER",
        "neutral_strength_anomaly INTEGER", "cost_usd REAL", "run_kind TEXT",
        "exclusion_reason TEXT", "outcome_state TEXT",
    ] + [f"{c} REAL" for c in OUTCOME_COLUMNS]
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE news_observation "
                     f"(id INTEGER PRIMARY KEY, {', '.join(cols)})")
        for r in rows:
            full = {c: SENTINEL for c in OUTCOME_COLUMNS}
            full.update({"strength_parse_ok": 1, "neutral_strength_anomaly": 0,
                         "exclusion_reason": "", "outcome_state": "resolved",
                         "run_kind": "collection", "error_class": None})
            full.update(r)
            keys = ", ".join(full)
            marks = ", ".join("?" for _ in full)
            conn.execute(f"INSERT INTO news_observation ({keys}) "
                         f"VALUES ({marks})", list(full.values()))
    conn.close()


def judged(session: str, stratum: str, judgment: str, strength: int = 3,
           **over) -> dict:
    row = {"query_date": session, "stratum": stratum, "state": "judged",
           "judgment": judgment, "strength": strength, "cost_usd": 0.000555}
    row.update(over)
    return row


SAMPLE = [
    judged(SESSIONS[0], "S1", "POSITIVE"),
    judged(SESSIONS[0], "S1", "NEGATIVE", 2),
    judged(SESSIONS[0], "S2", "NEUTRAL", 1),
    judged(SESSIONS[1], "S1", "POSITIVE", 4),
    judged(SESSIONS[1], "S3", "NEGATIVE"),
    {"query_date": SESSIONS[1], "stratum": "S2", "state": "no_news",
     "judgment": None, "strength": None},
    {"query_date": SESSIONS[1], "stratum": "S2", "state": "excluded_pre_call",
     "judgment": None, "strength": None, "error_class": "duplicate_headline",
     "exclusion_reason": "duplicate_headline", "outcome_state": "excluded"},
    {"query_date": SESSIONS[1], "stratum": "S4", "state": "model_failed",
     "judgment": None, "strength": None, "error_class": "timeout"},
    # A demonstration row: it can never count toward the registered sample.
    judged(SESSIONS[2], "S1", "POSITIVE", 5, run_kind="demonstration"),
]


def read_module_source() -> str:
    with open(os.path.join(REPO, "api_server", "collection.py"),
              encoding="utf-8") as fh:
        return fh.read()


def strip_exclusion_machinery(src: str) -> str:
    """Remove the FORBIDDEN_COLUMNS declaration and the module docstring.

    Both must NAME the columns to do their job: the set IS the enforcement and
    the docstring is the reasoning. Scanning them would make the guard
    impossible to write. Everything else in the file is fair game.
    """
    start = src.index("FORBIDDEN_COLUMNS = frozenset({")
    end = src.index("})", start) + 2
    without_set = src[:start] + src[end:]
    first = without_set.index('"""')
    second = without_set.index('"""', first + 3) + 3
    return without_set[second:]


def walk_keys(node, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            walk_keys(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            walk_keys(v, out)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "news.db")
    build_db(db, SAMPLE)
    log = tmp_path / "COLLECTION_LOG.md"
    log.write_text(
        "=== DAILY RUN 2026-03-03T22:30:00Z ===\n"
        "action:     collected\n"
        "target:     2026-03-02\n"
        "formation:  2026-01-02\n"
        "gaps:       none\n"
        "exit:       0\n")
    monkeypatch.setenv("MAL_EXPERIMENT_DB", db)
    monkeypatch.setenv("MAL_COLLECTION_LOG", str(log))
    monkeypatch.setenv("MAL_ANALYSIS_DB", str(tmp_path / "absent.db"))
    # systemd is not what these tests assert, so it is stubbed healthy except
    # where a test overrides it.
    monkeypatch.setattr(collection, "_systemd", lambda *a, **k: {
        "known": True, "timer_active": True, "unit_failed": False,
        "next_fire_utc": "2026-03-04T22:30:00Z", "last_trigger_utc": None,
        "error": None})
    return {"db": db, "log": log, "tmp": tmp_path}


# --- The constraint that matters most --------------------------------------

class TestNoOutcomeEscapes:
    def test_no_outcome_column_appears_as_a_key(self, env):
        keys: list[str] = []
        walk_keys(collection.monitor(), keys)
        for column in OUTCOME_COLUMNS:
            # `outcome_columns_excluded` lists them as VALUES, deliberately, so
            # the view can state what it refuses to show. Keys are what matter.
            assert column not in keys, f"{column} reached the payload as a key"

    def test_no_outcome_value_reaches_the_serialised_response(self, env):
        body = json.dumps(collection.monitor())
        assert str(SENTINEL) not in body
        assert "0.42" not in body

    def test_the_module_source_names_no_outcome_column(self):
        """MUTATION-CHECKED below. This is the layer that catches an aggregate
        whose result key looks innocent, which the key walk cannot see."""
        body = strip_exclusion_machinery(read_module_source())
        for column in OUTCOME_COLUMNS:
            assert column not in body, (
                f"{column} is named in api_server/collection.py outside its "
                f"forbidden-list declaration. An aggregate over it would reach "
                f"the response under a different key.")

    def test_mutation_an_outcome_aggregate_is_caught(self, monkeypatch):
        """MUTATION: put `AVG(excess_1session)` into a query. The source scan
        must fail. Performed, not asserted."""
        mutated = read_module_source().replace(
            "SELECT COUNT(*) FROM news_observation ",
            "SELECT AVG(excess_1session) FROM news_observation ", 1)
        assert "excess_1session" in strip_exclusion_machinery(mutated)
        monkeypatch.setitem(globals(), "read_module_source", lambda: mutated)
        with pytest.raises(AssertionError):
            TestNoOutcomeEscapes(
            ).test_the_module_source_names_no_outcome_column()

    def test_no_select_star_anywhere(self):
        """The docstring is stripped first: it EXPLAINS that there is no
        `SELECT *`, and a check that tripped on its own explanation would push
        the reasoning out of the file."""
        body = strip_exclusion_machinery(read_module_source())
        assert "SELECT *" not in body.upper()

    def test_the_payload_guard_raises_rather_than_filtering(self):
        """A leak must be loud. Filtering would ship the view minus one field
        and the operator would never know it had started answering."""
        with pytest.raises(collection.OutcomeLeak):
            collection._reject_outcomes({"progress": {"net_bp": 1.0}})
        with pytest.raises(collection.OutcomeLeak):
            collection._reject_outcomes({"rows": [{"ret_1session": 0.1}]})
        # And it passes a clean payload through untouched.
        collection._reject_outcomes({"progress": {"day_clusters": 3}})

    def test_the_forbidden_set_covers_every_named_quantity(self):
        assert set(OUTCOME_COLUMNS) <= collection.FORBIDDEN_COLUMNS

    def test_the_allow_list_and_the_forbidden_set_are_disjoint(self):
        assert not (collection.ALLOWED_COLUMNS & collection.FORBIDDEN_COLUMNS)


# --- What the view shows ---------------------------------------------------

class TestProgress:
    def test_cluster_and_stratum_counts_match_a_direct_query(self, env):
        got = collection.monitor()["progress"]
        conn = sqlite3.connect(f"file:{env['db']}?mode=ro", uri=True)
        clusters, = conn.execute(
            "SELECT COUNT(DISTINCT query_date) FROM news_observation "
            "WHERE run_kind='collection'").fetchone()
        n_judged, = conn.execute(
            "SELECT COUNT(*) FROM news_observation "
            "WHERE run_kind='collection' AND state='judged'").fetchone()
        per = dict(conn.execute(
            "SELECT stratum, COUNT(DISTINCT query_date) FROM news_observation "
            "WHERE run_kind='collection' AND stratum IS NOT NULL "
            "GROUP BY stratum"))
        conn.close()
        assert got["day_clusters"] == clusters == 2
        assert got["judged"] == n_judged == 5     # the demonstration row is out
        assert {s["stratum"]: s["day_clusters"]
                for s in got["per_stratum"]} == per

    def test_the_registered_floors_are_reported(self, env):
        got = collection.monitor()["progress"]
        assert got["cluster_floor"] == 60
        assert got["hard_stop"] == 120
        assert got["judged_target"] == 1000
        assert got["clusters_to_floor"] == 58
        assert got["meets_cluster_floor"] is False
        assert all(s["cluster_floor"] == 30 for s in got["per_stratum"])

    def test_the_transcribed_floors_match_the_specification(self):
        """The module transcribes these rather than importing the experiment,
        which must stay standalone, so a drift must fail rather than mislead."""
        from news_experiment import spec
        assert collection.NEUTRAL_REPORTABLE_FAILURE == \
            spec.NEUTRAL_RATE_REPORTABLE_FAILURE
        assert collection.PER_STRATUM_CLUSTER_FLOOR == 30
        assert collection.JUDGED_TARGET == 1000
        assert len(spec.STRATA) == 4

    def test_a_demonstration_row_is_reported_as_unable_to_count(self, env):
        comp = collection.monitor()["composition"]
        assert comp["non_collection_rows"] == {"demonstration": 1}


class TestComposition:
    def test_states_and_error_classes_are_reported(self, env):
        comp = collection.monitor()["composition"]
        assert comp["states"] == {"judged": 5, "no_news": 1,
                                  "excluded_pre_call": 1, "model_failed": 1}
        assert comp["excluded_pre_call_by_error_class"] == \
            {"duplicate_headline": 1}
        assert comp["model_failed_by_error_class"] == {"timeout": 1}

    def test_the_two_failure_states_are_never_summed(self, env):
        """Amendment 4: one is operational health, the other is sample
        composition. A combined number answers neither."""
        comp = collection.monitor()["composition"]
        assert "excluded_pre_call_by_error_class" in comp
        assert "model_failed_by_error_class" in comp
        assert not any(k.startswith("failures_total") for k in comp)


class TestDiagnostics:
    def test_judgment_split_and_minority_share(self, env):
        j = collection.monitor()["judgment"]
        assert (j["positive"], j["negative"], j["neutral"]) == (2, 2, 1)
        assert j["directional"] == 4
        assert j["minority_share"] == pytest.approx(0.5)
        assert j["minority_share_floor"] == 0.10
        assert j["mixed_day_clusters"] == 2
        assert j["mixed_cluster_floor"] == 30

    def test_the_null_reads_uninformative_below_the_mixed_cluster_floor(self,
                                                                       env):
        assert collection.monitor()["judgment"]["null_informative"] is False

    def test_strength_histogram_excludes_neutral(self, env):
        s = collection.monitor()["strength"]
        # Four directional rows at strengths 3, 2, 4, 3. The NEUTRAL row's
        # strength is fixed at 1 by the prompt and carries no information.
        assert s["histogram"] == {2: 1, 3: 2, 4: 1}
        assert s["scored_directional"] == 4
        assert 1 not in s["histogram"]

    def test_spend_is_reported_against_the_measured_rate(self, env):
        sp = collection.monitor()["spend"]
        assert sp["calls"] == 5
        assert sp["measured_per_call"] == 0.000555
        assert sp["per_call"] == pytest.approx(0.000555)


# --- Run health -------------------------------------------------------------

class TestRunHealth:
    def test_the_last_run_is_parsed_from_the_log(self, env):
        last = collection.monitor()["run_health"]["last_run"]
        assert last["started_utc"] == "2026-03-03T22:30:00Z"
        assert last["action"] == "collected"
        assert last["target"] == "2026-03-02"
        assert last["exit_code"] == 0

    def check_gap_surfaces(self, env) -> None:
        """A flagged gap must reach both the payload and the alarms."""
        payload = collection.monitor()
        assert payload["run_health"]["gaps"] == ["2026-03-04"]
        assert payload["run_health"]["gap_count"] == 1
        alarms = {a["code"]: a for a in payload["alarms"]}
        assert "gap_unrecoverable" in alarms
        assert alarms["gap_unrecoverable"]["level"] == "critical"
        assert "UNRECOVERABLE" in alarms["gap_unrecoverable"]["message"]

    def test_a_flagged_gap_surfaces(self, env):
        env["log"].write_text(
            "=== DAILY RUN 2026-03-05T22:30:00Z ===\n"
            "action:     collected\n"
            "GAP:        1 session(s) missing, UNRECOVERABLE by design: "
            "2026-03-04\n"
            "exit:       4\n")
        self.check_gap_surfaces(env)

    def test_mutation_dropping_the_gap_parse_is_caught(self, env, monkeypatch):
        """MUTATION: stop carrying the parsed GAP line through, the way a
        refactor that only handled lowercase keys would. The check must fail."""
        env["log"].write_text(
            "=== DAILY RUN 2026-03-05T22:30:00Z ===\n"
            "action:     collected\n"
            "GAP:        1 session(s) missing, UNRECOVERABLE by design: "
            "2026-03-04\n"
            "exit:       4\n")
        real = collection.parse_collection_log

        def blind(text: str):
            runs = real(text)
            for r in runs:
                r["gaps"] = []
            return runs

        monkeypatch.setattr(collection, "parse_collection_log", blind)
        with pytest.raises(AssertionError):
            self.check_gap_surfaces(env)

    def test_a_gap_keeps_being_reported_after_a_later_clean_run(self, env):
        """A gap is permanent. A later success must not bury it."""
        env["log"].write_text(
            "=== DAILY RUN 2026-03-05T22:30:00Z ===\n"
            "GAP:        1 session(s) missing, UNRECOVERABLE by design: "
            "2026-03-04\n"
            "exit:       4\n"
            "\n=== DAILY RUN 2026-03-06T22:30:00Z ===\n"
            "action:     collected\n"
            "gaps:       none\n"
            "exit:       0\n")
        payload = collection.monitor()
        assert payload["run_health"]["gaps"] == ["2026-03-04"]
        assert payload["run_health"]["last_run"]["exit_code"] == 0

    def test_a_failed_service_unit_surfaces(self, env, monkeypatch):
        monkeypatch.setattr(collection, "_systemd", lambda *a, **k: {
            "known": True, "timer_active": True, "unit_failed": True,
            "next_fire_utc": "2026-03-04T22:30:00Z",
            "last_trigger_utc": None, "error": None})
        alarms = {a["code"]: a for a in collection.monitor()["alarms"]}
        assert alarms["unit_failed"]["level"] == "critical"

    def test_an_inactive_timer_surfaces(self, env, monkeypatch):
        monkeypatch.setattr(collection, "_systemd", lambda *a, **k: {
            "known": True, "timer_active": False, "unit_failed": False,
            "next_fire_utc": None, "last_trigger_utc": None, "error": None})
        alarms = {a["code"]: a for a in collection.monitor()["alarms"]}
        assert alarms["timer_inactive"]["level"] == "critical"

    def test_unreadable_systemd_reports_unknown_not_healthy(self, env,
                                                            monkeypatch):
        """A monitoring view whose failure mode is 'looks fine' is worse than
        no monitoring view."""
        monkeypatch.setattr(collection, "_systemd", lambda *a, **k: {
            "known": False, "timer_active": None, "unit_failed": None,
            "next_fire_utc": None, "last_trigger_utc": None,
            "error": "systemctl: not found"})
        codes = [a["code"] for a in collection.monitor()["alarms"]]
        assert "timer_unknown" in codes

    def test_a_stalled_collection_surfaces(self, env, monkeypatch):
        monkeypatch.setattr(collection, "_completed_sessions", lambda last: {
            "known": True, "sessions_behind": 5,
            "next_expected": "2026-03-05"})
        alarms = {a["code"]: a for a in collection.monitor()["alarms"]}
        assert alarms["collection_stalled"]["level"] == "critical"
        assert "unrecoverable" in alarms["collection_stalled"]["message"]

    def test_a_missing_database_is_reported_not_crashed(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setenv("MAL_EXPERIMENT_DB", str(tmp_path / "nope.db"))
        monkeypatch.setenv("MAL_COLLECTION_LOG", str(tmp_path / "nolog.md"))
        payload = collection.monitor()
        assert payload["db_present"] is False
        assert [a["code"] for a in payload["alarms"]] == ["no_database"]

    def test_the_timestamp_parser_handles_the_systemd_forms(self):
        assert collection._stamp_to_iso("@1785450605") == \
            "2026-07-30T22:30:05Z"
        assert collection._stamp_to_iso("") is None
        assert collection._stamp_to_iso("@0") is None
        # The localised human form systemd emits WITHOUT --timestamp=unix must
        # read as unknown rather than as a wrong date.
        assert collection._stamp_to_iso("Thu 2026-07-30 15:30:05 PDT") is None


class TestEndpoint:
    def test_the_route_returns_the_payload_without_an_outcome(self, env):
        from fastapi.testclient import TestClient

        from api_server.app import app
        r = TestClient(app).get("/collection/monitor")
        assert r.status_code == 200
        keys: list[str] = []
        walk_keys(r.json(), keys)
        for column in OUTCOME_COLUMNS:
            assert column not in keys
        assert str(SENTINEL) not in r.text


# --- Retained controls ------------------------------------------------------

class TestRetainedControlsStillWrite:
    """Removing panels must not have removed a control the engine reads.

    Each writes the same controls.json key it wrote before, checked by reading
    the file back rather than by trusting a return value.
    """

    @pytest.fixture()
    def ctl(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAL_CONTROL_DIR", str(tmp_path / "control"))
        from api_server import controls
        return controls

    def test_the_per_level_source_selectors_still_write(self, ctl):
        """KEPT deliberately: raising a weight and setting a source is how a
        deactivated factor would be reactivated if a measurement justified it.
        """
        for layer in ("council", "dnn_advisory", "whale"):
            assert ctl.set_source(layer, "mock")["ok"] is True
            assert ctl.read_controls()["layer_sources"][layer] == "mock"
            assert ctl.set_source(layer, "real")["ok"] is True
            assert ctl.read_controls()["layer_sources"][layer] == "real"

    def test_the_layer_toggles_still_write(self, ctl):
        for layer in ("council", "dnn_advisory", "whale", "adaptive"):
            ctl.set_layer(layer, False)
            assert ctl.read_controls()["layers"][layer] is False
            ctl.set_layer(layer, True)
            assert ctl.read_controls()["layers"][layer] is True

    def test_the_weight_sliders_still_write(self, ctl):
        """The dnn_advisory and whale_signal sliders were KEPT even though both
        read 0.00, because CLAUDE.md records that restoring a weight is what
        reactivates a layer, with no other change."""
        # Weights persist to the model_weights table rather than to
        # controls.json, so the normalized result is what proves the path.
        flat = ctl.set_weights({"rule_based": 1.0, "dnn_advisory": 0.0,
                                "whale_signal": 0.0})
        assert flat["ok"] is True
        assert flat["weights"]["dnn_advisory"] == 0.0
        assert flat["weights"]["whale_signal"] == 0.0
        # THE REACTIVATION PATH: raising a deactivated factor's weight gives it
        # a real normalized share. This is the capability the sliders were kept
        # for, so it is asserted rather than assumed.
        raised = ctl.set_weights({"rule_based": 1.0, "dnn_advisory": 0.5,
                                  "whale_signal": 0.25})
        assert raised["ok"] is True
        assert raised["weights"]["dnn_advisory"] > 0.0
        assert raised["weights"]["whale_signal"] > 0.0

    def test_the_sleeve_toggles_still_write(self, ctl):
        """The rebalance BUTTON was removed. The sleeve toggles were not: a C++
        test proves the engine reads them from this file."""
        ctl.set_sleeve("research_satellite", True)
        assert ctl.read_controls()["sleeves"]["research_satellite"] is True
        ctl.set_sleeve("research_satellite", False)
        assert ctl.read_controls()["sleeves"]["research_satellite"] is False

    def test_the_kill_switch_route_is_still_mounted(self):
        """The kill switch is a latching safety control and the status strip is
        its interface on every page. No removal may touch it."""
        from api_server.app import app
        assert "/kill" in {r.path for r in app.routes}

    def test_the_removed_panels_endpoints_survive(self):
        """Removing a PANEL must not remove a capability. Promote, rollback,
        RL-enable and rebalance all remain reachable, so what was removed is an
        always-visible surface rather than an ability."""
        from api_server.app import app
        paths = {r.path for r in app.routes}
        for path in ("/controls/promote", "/controls/rollback",
                     "/controls/rl", "/controls/rebalance"):
            assert path in paths, path
