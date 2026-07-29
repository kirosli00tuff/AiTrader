"""The daily collection wrapper (news_experiment/daily.py).

What is pinned and why:

  target derivation      the wrapper asks the calendar, never date arithmetic.
                         Monday resolves Friday. The day after a Monday
                         holiday still resolves Friday. A Saturday run
                         resolves Thursday, because Friday's scoring session
                         (Monday) has not closed and collecting Friday early
                         would let the collector's resolve pass mis-exclude
                         its judged rows. A calendar that has been outrun
                         refuses rather than guessing.
  formation derivation   first session of the quarter, from the calendar, so
                         2026-10-01 re-draws the universe without an operator.
  gap detection          completed sessions with no collection rows are named
                         and never filled.
  idempotence            the collector appends, so the wrapper refuses a
                         session already present. Row counts prove it.
  the run always logs    every path appends to COLLECTION_LOG.md.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from news_experiment import daily, store
from news_experiment.horizon import Calendar


def make_cal(sessions: list[str], open_="09:30", close="16:00") -> Calendar:
    return Calendar.from_rows([(s, open_, close) for s in sessions])


def utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


# 2026-07-24 is a Friday, 2026-07-27 a Monday. July 2026 has no US holiday
# in this span, so the holiday cases below drop sessions deliberately.
WEEK = ["2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27",
        "2026-07-28", "2026-07-29", "2026-07-30"]


class TestTargetSession:
    def test_weekday_evening_resolves_the_prior_session(self):
        # Wednesday 22:30 UTC. Wednesday closed 20:00 UTC, so Tuesday's
        # scoring session has closed and Tuesday is the target.
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-07-29 22:30"))
        assert (t, why) == ("2026-07-28", "")

    def test_monday_run_resolves_friday_not_a_calendar_yesterday(self):
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-07-27 22:30"))
        assert (t, why) == ("2026-07-24", "")

    def test_day_after_monday_holiday_resolves_friday(self):
        no_monday = [s for s in WEEK if s != "2026-07-27"]
        t, why = daily.target_session(make_cal(no_monday),
                                      utc("2026-07-28 22:30"))
        assert (t, why) == ("2026-07-24", "")

    def test_monday_holiday_run_finds_friday_not_yet_collectable(self):
        # On the holiday itself Friday's scoring session (Tuesday) is still
        # open, so the target is Thursday. Thursday is normally already
        # collected and the run becomes an idempotent no-op.
        no_monday = [s for s in WEEK if s != "2026-07-27"]
        t, why = daily.target_session(make_cal(no_monday),
                                      utc("2026-07-27 22:30"))
        assert (t, why) == ("2026-07-23", "")

    def test_saturday_run_does_not_collect_friday_early(self):
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-07-25 12:00"))
        assert (t, why) == ("2026-07-23", "")

    def test_settle_margin_holds_the_target_back(self):
        # 20:30 UTC is after Wednesday's 20:00 close but inside the margin,
        # so Tuesday is not yet collectable and Monday is the target.
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-07-29 20:30"),
                                      settle_minutes=60)
        assert (t, why) == ("2026-07-27", "")

    def test_calendar_outrun_refuses(self):
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-08-03 12:00"))
        assert t is None
        assert "calendar exhausted" in why

    def test_before_any_close_refuses(self):
        t, why = daily.target_session(make_cal(WEEK),
                                      utc("2026-07-22 12:00"))
        assert t is None
        assert "too early" in why

    def test_empty_calendar_refuses(self):
        t, why = daily.target_session(make_cal([]), utc("2026-07-29 22:30"))
        assert t is None
        assert "empty" in why


def weekday_sessions(start: str, end: str) -> list[str]:
    d = datetime.strptime(start, "%Y-%m-%d")
    stop = datetime.strptime(end, "%Y-%m-%d")
    out = []
    while d <= stop:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


class TestFormationDerivation:
    SESSIONS = weekday_sessions("2026-01-02", "2026-10-05")

    def test_july_session_derives_the_q3_formation(self):
        assert daily.formation_for(self.SESSIONS, "2026-07-28") == "2026-07-01"

    def test_last_q3_session_still_uses_q3(self):
        assert daily.formation_for(self.SESSIONS, "2026-09-30") == "2026-07-01"

    def test_first_q4_session_re_draws_at_the_boundary(self):
        assert daily.formation_for(self.SESSIONS, "2026-10-01") == "2026-10-01"

    def test_no_window_yields_none(self):
        assert daily.formation_for(weekday_sessions("2026-07-01",
                                                    "2026-07-28"),
                                   "2026-07-28") is None


class TestGaps:
    def test_missing_session_is_named(self):
        gaps = daily.find_gaps(WEEK, ["2026-07-28"], "2026-07-30")
        assert gaps == ["2026-07-29"]

    def test_contiguous_collection_has_no_gap(self):
        gaps = daily.find_gaps(WEEK, ["2026-07-28", "2026-07-29"],
                               "2026-07-30")
        assert gaps == []

    def test_target_itself_is_not_a_gap(self):
        assert daily.find_gaps(WEEK, ["2026-07-28"], "2026-07-29") == []

    def test_before_collection_begins_nothing_is_a_gap(self):
        assert daily.find_gaps(WEEK, [], "2026-07-30") == []


def seed_analysis_db(path: str, sessions: list[str]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trading_calendar"
                     "(date TEXT PRIMARY KEY, open TEXT, close TEXT)")
        conn.executemany("INSERT INTO trading_calendar VALUES (?,?,?)",
                         [(s, "09:30", "16:00") for s in sessions])
        conn.execute(
            "CREATE TABLE bars (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "venue TEXT NOT NULL, symbol TEXT NOT NULL,"
            "timeframe TEXT NOT NULL, timestamp TEXT NOT NULL,"
            "open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,"
            "close REAL NOT NULL, volume REAL NOT NULL,"
            "source TEXT DEFAULT 'unknown', volume_source TEXT,"
            "adjustment TEXT,"
            "UNIQUE(venue, symbol, timeframe, timestamp))")
    conn.close()


def seed_collection_row(db: str, session: str, n: int = 1) -> None:
    conn = store.open_store(db)
    for i in range(n):
        store.insert_observation(conn, {
            "rule_id": "test", "formation_date": "2026-07-01",
            "symbol": f"TST{i}", "query_date": session,
            "state": "no_news", "run_kind": "collection",
        })
    conn.commit()
    conn.close()


def recent_calendar_around_now() -> tuple[list[str], str]:
    """Weekday sessions bracketing the real now, and the session the wrapper
    must resolve: the latest whose successor closed 60+ minutes ago."""
    now = datetime.now(timezone.utc)
    days = []
    # Far enough back that a first-of-quarter session carries the full
    # 60-session trailing window the formation derivation requires.
    d = now - timedelta(days=300)
    while d <= now + timedelta(days=10):
        if d.weekday() < 5:
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    cal = make_cal(days)
    target, why = daily.target_session(cal, now)
    assert target, f"synthetic calendar could not resolve a target: {why}"
    return days, target


class TestWrapperEndToEnd:
    @pytest.fixture()
    def env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAL_RUN_DIR", str(tmp_path / "run"))
        clog = tmp_path / "COLLECTION_LOG.md"
        monkeypatch.setattr(daily, "COLLECTION_LOG", str(clog))
        sessions, target = recent_calendar_around_now()
        adb = str(tmp_path / "analysis.db")
        seed_analysis_db(adb, sessions)
        edb = str(tmp_path / "news.db")
        return {"adb": adb, "edb": edb, "clog": clog, "target": target}

    def test_second_run_for_a_present_session_refuses_and_counts_match(
            self, env, capsys):
        seed_collection_row(env["edb"], env["target"], n=3)
        before = daily.session_rows(env["edb"], env["target"])

        code = daily.main(["--db", env["edb"], "--analysis-db", env["adb"]])

        after = daily.session_rows(env["edb"], env["target"])
        assert code == daily.EXIT_OK
        assert (before, after) == (3, 3)
        out = capsys.readouterr().out
        assert "IDEMPOTENT REFUSAL" in out
        assert env["clog"].read_text().count("refused_already_present") == 1

    def test_gap_is_reported_loudly_and_exit_code_says_so(self, env, capsys):
        sessions = list(daily.load_calendar(env["adb"]).sessions)
        t_idx = sessions.index(env["target"])
        # Collection began three sessions back, the middle two are missing,
        # and the target itself is already present so no collector runs.
        seed_collection_row(env["edb"], sessions[t_idx - 3])
        seed_collection_row(env["edb"], env["target"])

        code = daily.main(["--db", env["edb"], "--analysis-db", env["adb"]])

        assert code == daily.EXIT_GAP
        out = capsys.readouterr().out
        assert out.count("GAP: session") == 2
        text = env["clog"].read_text()
        assert "UNRECOVERABLE" in text
        assert sessions[t_idx - 2] in text and sessions[t_idx - 1] in text

    def test_every_run_leaves_a_collection_log_entry(self, env):
        # Even a failed run writes its entry (priority zero: no process may
        # fail without leaving output). Empty exp db, so the run proceeds
        # toward collection and dies inside band resolution against the
        # unseeded analysis db, before any network call.
        code = daily.main(["--db", env["edb"], "--analysis-db", env["adb"]])
        assert code != daily.EXIT_OK
        assert "=== DAILY RUN" in env["clog"].read_text()


class TestTopUp:
    def test_upsert_matches_the_breadth_load_provenance(self, tmp_path):
        adb = str(tmp_path / "analysis.db")
        seed_analysis_db(adb, WEEK)

        def fake_get(url, timeout=60.0):
            return 200, {"bars": {"TSTA": [
                {"t": "2026-07-29T04:00:00Z", "o": 10.0, "h": 11.0,
                 "l": 9.5, "c": 10.5, "v": 1000},
                {"t": "2026-07-30T04:00:00Z", "o": 10.5, "h": 12.0,
                 "l": 10.0, "c": 11.0, "v": None},   # volume absent
                {"t": "2026-07-31T04:00:00Z", "o": None, "h": 1.0,
                 "l": 1.0, "c": 1.0, "v": 1},        # incomplete, skipped
            ]}, "next_page_token": None}

        tee = daily.Tee.__new__(daily.Tee)
        tee.path = str(tmp_path / "tee.log")
        written, failed = daily.topup_bars(
            adb, ["TSTA"], "2026-07-22",
            utc("2026-07-30 22:30"), tee, http_get=fake_get)

        assert (written, failed) == (2, 0)
        with sqlite3.connect(adb) as conn:
            rows = list(conn.execute(
                "SELECT venue, timeframe, source, volume_source, adjustment,"
                " volume FROM bars ORDER BY timestamp"))
        conn.close()
        assert rows[0] == ("alpaca", "1day", "backfill", "venue_backfill",
                           "all", 1000.0)
        assert rows[1][3] == "unknown"      # absent volume is not invented
        assert len(rows) == 2               # the incomplete bar is skipped

    def test_failed_batch_is_counted_not_fatal(self, tmp_path, monkeypatch):
        adb = str(tmp_path / "analysis.db")
        seed_analysis_db(adb, WEEK)
        monkeypatch.setattr(daily.time, "sleep", lambda s: None)

        def fake_get(url, timeout=60.0):
            return 500, {"error": "boom"}

        tee = daily.Tee.__new__(daily.Tee)
        tee.path = str(tmp_path / "tee.log")
        written, failed = daily.topup_bars(
            adb, ["TSTA"], "2026-07-22",
            utc("2026-07-30 22:30"), tee, http_get=fake_get)
        assert (written, failed) == (0, 1)

    def test_bars_present_fraction(self, tmp_path):
        adb = str(tmp_path / "analysis.db")
        seed_analysis_db(adb, WEEK)
        with sqlite3.connect(adb) as conn:
            conn.execute(
                "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,"
                "low,close,volume) VALUES('alpaca','A','1day',"
                "'2026-07-29T04:00:00Z',1,1,1,1,0)")
        conn.close()
        frac = daily.bars_present_fraction(adb, ["A", "B"], "2026-07-29")
        assert frac == 0.5
        assert daily.bars_present_fraction(adb, [], "2026-07-29") == 0.0


class TestCollectionLogEntry:
    def test_ceiling_hit_is_loud(self, tmp_path):
        log = daily.RunLog(started_utc="2026-07-29T22:30:00Z",
                           target="2026-07-28", formation="2026-07-01",
                           action="collected", rows_before=0, rows_after=10,
                           spend_usd=1.0, calls=1800, ceiling_hit=True,
                           exit_code=daily.EXIT_CEILING)
        path = tmp_path / "clog.md"
        daily.append_collection_log(log, str(path))
        text = path.read_text()
        assert "CEILING HIT" in text
        assert "PARTIAL" in text
        assert "exit:       6" in text
