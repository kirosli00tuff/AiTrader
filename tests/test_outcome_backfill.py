"""Reopening, the unscored horizons, and the formation-correct benchmark.

Three defects the scheduler session reported, fixed with operator approval:

  1. A row excluded because its bar was not loaded yet is terminal, so it
     cannot self-heal once the bar arrives. It may be reopened, and ONLY when
     the bar genuinely exists.
  2. `ret_2session`, `ret_5session` and `ret_10session` were NULL forever on
     every promptly resolved row, because a row resolves once at T+1 when
     those sessions have not happened. They now fill as their bars appear,
     and filling them can never move a scored quantity.
  3. A pending row was benchmarked against the CURRENT run's band, which is
     wrong across a formation boundary. It is now benchmarked against the
     band of its own formation.

The two mutation tests carry the mutation in their docstring AND perform it,
because a mutation nobody executed is a claim rather than a check.
"""
from __future__ import annotations

import inspect
import re
import sqlite3

import pytest

from news_experiment import collect, maintain, outcomes, spec, store
from news_experiment.horizon import Calendar
from scripts import reopen_absent_bar_exclusions_20260729 as reopen

# 15 consecutive sessions: enough for a 10-session companion horizon past a
# scoring session at index 1.
SESSIONS = tuple(f"2026-03-{d:02d}" for d in
                 (2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20))
ANCHOR = SESSIONS[0]
SCORING = SESSIONS[1]
DRIFT = {"AAA": 0.01, "BBB": 0.02, "CCC": -0.01}


def cal() -> Calendar:
    return Calendar.from_rows([(s, "09:30", "16:00") for s in SESSIONS])


def _bar_rows(symbols: dict[str, float], through: str) -> list[tuple]:
    rows = []
    for sym, drift in symbols.items():
        for i, s in enumerate(SESSIONS):
            if s > through:
                break
            price = 50.0 * (1.0 + drift) ** i
            rows.append(("alpaca", sym, "1day", f"{s}T04:00:00Z",
                         price, price, price, price, 1e6, "backfill",
                         "venue_backfill", "all"))
    return rows


def seed_analysis_db(path: str, *, symbols: dict[str, float],
                     through: str = SESSIONS[-1]) -> None:
    """A calendar plus a compounding daily series per symbol.

    Each name has its own drift, so a benchmark over one set of names differs
    from a benchmark over another. That difference is what identifies which
    band priced a row.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trading_calendar"
                     "(date TEXT PRIMARY KEY, open TEXT, close TEXT)")
        conn.executemany("INSERT INTO trading_calendar VALUES (?,?,?)",
                         [(s, "09:30", "16:00") for s in SESSIONS])
        conn.execute(
            "CREATE TABLE bars (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "venue TEXT NOT NULL, symbol TEXT NOT NULL,"
            "timeframe TEXT NOT NULL, timestamp TEXT NOT NULL,"
            "open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,"
            "close REAL NOT NULL, volume REAL NOT NULL,"
            "source TEXT DEFAULT 'unknown', volume_source TEXT,"
            "adjustment TEXT, UNIQUE(venue,symbol,timeframe,timestamp))")
        conn.executemany(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source,volume_source,adjustment) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", _bar_rows(symbols, through))
    conn.close()


def extend_bars(path: str, symbols: dict[str, float]) -> None:
    """Add the sessions a first seed deliberately withheld."""
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO bars(venue,symbol,timeframe,timestamp,open,high,low,"
            "close,volume,source,volume_source,adjustment) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(venue,symbol,timeframe,timestamp) DO UPDATE SET "
            "open=excluded.open, close=excluded.close",
            _bar_rows(symbols, SESSIONS[-1]))
    conn.close()


def insert_row(conn, **over) -> int:
    row = {
        "rule_id": spec.RULE_ID, "formation_date": "2026-01-02",
        "symbol": "AAA", "adv_usd_at_formation": 5_000_000.0,
        "stratum": "S3", "query_date": ANCHOR, "state": spec.STATE_JUDGED,
        "judgment": spec.JUDGMENT_POSITIVE, "strength": 3,
        "reason": "a recorded verdict nothing here may touch",
        "anchor_kind": spec.ANCHOR_SAME_SESSION_CLOSE,
        "anchor_ts": f"{ANCHOR}T20:00:00Z", "scoring_session": SCORING,
        "outcome_state": "pending", "run_kind": "collection",
        "spec_version": spec.SPEC_VERSION,
    }
    row.update(over)
    return store.insert_observation(conn, row)


def cfg_for(db: str, adb: str, formation: str = "") -> collect.RunConfig:
    return collect.RunConfig(formation=formation, day_from="", day_to="",
                             symbols=0, ceiling=0.0, db_path=db,
                             run_kind="maintenance", analysis_db=adb)


def row_dict(conn, rid: int) -> dict:
    conn.row_factory = sqlite3.Row
    out = dict(conn.execute("SELECT * FROM news_observation WHERE id=?",
                            (rid,)).fetchone())
    conn.row_factory = None
    return out


@pytest.fixture()
def env(tmp_path):
    adb = str(tmp_path / "analysis.db")
    seed_analysis_db(adb, symbols=DRIFT)
    return {"adb": adb, "edb": str(tmp_path / "news.db")}


class TestReopen:
    """A row excluded for an absent bar, and what may be done about it."""

    def test_absent_bar_excludes_then_reopening_lets_it_price(self, tmp_path):
        # Bars stop BEFORE the scoring session: the 2026-07-28 shape exactly.
        adb = str(tmp_path / "a.db")
        seed_analysis_db(adb, symbols={"AAA": 0.01}, through=ANCHOR)
        edb = str(tmp_path / "n.db")
        conn = store.open_store(edb)
        rid = insert_row(conn)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                band_for=lambda f: ["AAA"])
        conn.commit()
        before = row_dict(conn, rid)
        conn.close()
        assert before["outcome_state"] == "excluded"
        assert before["exclusion_reason"] == \
            spec.EXCLUSION_SYMBOL_DID_NOT_TRADE
        assert before["ret_1session"] is None

        # The bars arrive. The row is TERMINAL, so a resolve pass alone does
        # nothing. This is why reopening is needed at all.
        extend_bars(adb, {"AAA": 0.01})
        conn = store.open_store(edb)
        assert collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                       band_for=lambda f: ["AAA"]) == 0
        assert row_dict(conn, rid)["outcome_state"] == "excluded"

        # Reopened, it prices, and the judgment is untouched throughout.
        plan = reopen.plan(conn, adb, ANCHOR)
        assert [r["id"] for r in plan["reopen"]] == [rid]
        assert plan["leave"] == []
        reopen.apply(conn, [rid])
        # The band comes from a stub because this fixture's analysis db carries
        # no `universe_asset`. `maintain.run_maintenance` over the same db
        # correctly leaves the row pending instead of substituting a band, and
        # that refusal is pinned by
        # TestFormationCorrectBenchmark::test_the_real_resolver_refuses_rather_than_substituting.
        assert collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                       band_for=lambda f: ["AAA"]) == 1
        conn.commit()
        after = row_dict(conn, rid)
        conn.close()
        assert after["outcome_state"] == "resolved"
        assert after["exclusion_reason"] == ""
        assert after["ret_1session"] == pytest.approx(0.01)
        assert after["judgment"] == before["judgment"]
        assert after["strength"] == before["strength"]
        assert after["reason"] == before["reason"]

    def test_a_row_whose_bar_is_still_absent_is_not_reopened(self, tmp_path):
        adb = str(tmp_path / "a.db")
        seed_analysis_db(adb, symbols={"AAA": 0.01}, through=ANCHOR)
        edb = str(tmp_path / "n.db")
        conn = store.open_store(edb)
        rid = insert_row(conn)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                band_for=lambda f: ["AAA"])
        conn.commit()

        plan = reopen.plan(conn, adb, ANCHOR)
        assert plan["reopen"] == []
        assert len(plan["leave"]) == 1
        assert "bar still absent" in plan["leave"][0]["reason"]
        assert row_dict(conn, rid)["outcome_state"] == "excluded"
        conn.close()

    def test_scope_excludes_other_reasons_sessions_and_run_kinds(self, env):
        conn = store.open_store(env["edb"])
        other_reason = insert_row(
            conn, outcome_state="excluded",
            exclusion_reason=spec.EXCLUSION_ADV_UNAVAILABLE)
        other_kind = insert_row(
            conn, outcome_state="excluded", run_kind="demonstration",
            exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
        other_session = insert_row(
            conn, outcome_state="excluded", query_date=SESSIONS[5],
            exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
        already_resolved = insert_row(
            conn, outcome_state="resolved",
            exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
        in_scope = insert_row(
            conn, outcome_state="excluded",
            exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
        conn.commit()

        got = [r[0] for r in reopen.candidates(conn, ANCHOR)]
        conn.close()
        assert got == [in_scope]
        for out_of_scope in (other_reason, other_kind, other_session,
                             already_resolved):
            assert out_of_scope not in got


class TestLongerHorizons:
    def test_a_prompt_resolution_leaves_companions_null_then_fills(self,
                                                                  tmp_path):
        # Bars end at the scoring session: the real T+1 situation.
        adb = str(tmp_path / "a.db")
        seed_analysis_db(adb, symbols={"AAA": 0.01}, through=SCORING)
        edb = str(tmp_path / "n.db")
        conn = store.open_store(edb)
        rid = insert_row(conn)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                band_for=lambda f: ["AAA"])
        conn.commit()
        first = row_dict(conn, rid)
        conn.close()

        assert first["outcome_state"] == "resolved"
        assert first["ret_1session"] == pytest.approx(0.01)
        assert (first["ret_2session"], first["ret_5session"],
                first["ret_10session"]) == (None, None, None)

        extend_bars(adb, {"AAA": 0.01})
        conn = store.open_store(edb)
        rep = collect.backfill_horizons(conn, cfg_for(edb, adb), cal())
        conn.commit()
        after = row_dict(conn, rid)
        conn.close()

        assert rep["rows_updated"] == 1
        assert rep["filled"] == {2: 1, 5: 1, 10: 1}
        # The anchor is the close of SESSIONS[0], so ret_Nsession runs N
        # sessions of compounding from it.
        for k in (2, 5, 10):
            assert after[f"ret_{k}session"] == pytest.approx(1.01 ** k - 1.0)

    def check_scored_outcome_immutable(self, tmp_path):
        """Resolve at T+1, then backfill against a DIFFERENT price series.

        The re-seeded series is the shape a dividend re-baseline produces. If
        any column but the three companions were writable here, it would move.
        """
        adb = str(tmp_path / "a.db")
        seed_analysis_db(adb, symbols={"AAA": 0.01}, through=SCORING)
        edb = str(tmp_path / "n.db")
        conn = store.open_store(edb)
        rid = insert_row(conn)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                band_for=lambda f: ["AAA"])
        conn.commit()
        before = row_dict(conn, rid)
        conn.close()

        extend_bars(adb, {"AAA": 0.05})
        conn = store.open_store(edb)
        collect.backfill_horizons(conn, cfg_for(edb, adb), cal())
        conn.commit()
        after = row_dict(conn, rid)
        conn.close()

        companions = {f"ret_{k}session" for k in outcomes.COMPANION_HORIZONS}
        changed = {k for k in before if before[k] != after[k]}
        assert changed <= companions, f"non-companion columns moved: {changed}"
        for col in ("ret_1session", "excess_1session", "bench_1session",
                    "net_bp", "anchor_price", "cost_bp_round_trip",
                    "outcome_state", "judgment", "strength"):
            assert after[col] == before[col], col

    def test_a_scored_outcome_is_immutable_across_a_backfill(self, tmp_path):
        self.check_scored_outcome_immutable(tmp_path)

    def test_mutation_writing_the_scored_horizon_is_caught(self, tmp_path,
                                                          monkeypatch):
        """MUTATION: append `ret_1session = 0.999` to HORIZON_UPDATE_SQL, so
        the pass writes the scored horizon. The immutability check must fail.
        """
        monkeypatch.setattr(collect, "HORIZON_UPDATE_SQL", (
            "UPDATE news_observation SET "
            "ret_2session = COALESCE(ret_2session, ?), "
            "ret_5session = COALESCE(ret_5session, ?), "
            "ret_10session = COALESCE(ret_10session, ?), "
            "ret_1session = 0.999 WHERE id=?"))
        with pytest.raises(AssertionError):
            self.check_scored_outcome_immutable(tmp_path)

    def test_an_already_filled_companion_is_never_overwritten(self, env):
        conn = store.open_store(env["edb"])
        rid = insert_row(conn, outcome_state="resolved", ret_1session=0.01,
                         anchor_price=50.0, ret_2session=0.99)
        conn.commit()
        collect.backfill_horizons(conn, cfg_for(env["edb"], env["adb"]), cal())
        conn.commit()
        after = row_dict(conn, rid)
        conn.close()
        assert after["ret_2session"] == 0.99       # COALESCE keeps it
        assert after["ret_5session"] is not None   # the NULL ones do fill

    def test_mutation_dropping_coalesce_is_caught(self, env):
        """MUTATION: replace COALESCE with a bare assignment, so a recomputed
        value overwrites a reported one. The no-overwrite check must fail."""
        import unittest.mock as mock
        mutated = ("UPDATE news_observation SET ret_2session = ?, "
                   "ret_5session = ?, ret_10session = ? WHERE id=?")
        with mock.patch.object(collect, "HORIZON_UPDATE_SQL", mutated):
            with pytest.raises(AssertionError):
                self.test_an_already_filled_companion_is_never_overwritten(env)

    def test_a_pending_or_excluded_row_is_not_touched(self, env):
        conn = store.open_store(env["edb"])
        pending = insert_row(conn)
        excluded = insert_row(
            conn, outcome_state="excluded",
            exclusion_reason=spec.EXCLUSION_SYMBOL_DID_NOT_TRADE)
        conn.commit()
        rep = collect.backfill_horizons(conn, cfg_for(env["edb"], env["adb"]),
                                        cal())
        conn.commit()
        assert rep["rows_examined"] == 0
        for rid in (pending, excluded):
            assert row_dict(conn, rid)["ret_2session"] is None
        conn.close()

    def test_a_companion_whose_bar_is_absent_stays_null_and_is_counted(self,
                                                                      tmp_path):
        """A partially reachable row: only the horizon that cannot be seen
        stays NULL, and the pass reports it as still incomplete rather than
        going quiet about it."""
        adb = str(tmp_path / "a.db")
        # Bars reach the 5-session target but not the 10-session one.
        seed_analysis_db(adb, symbols={"AAA": 0.01}, through=SESSIONS[6])
        edb = str(tmp_path / "n.db")
        conn = store.open_store(edb)
        rid = insert_row(conn)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(edb, adb), cal(), [],
                                band_for=lambda f: ["AAA"])
        conn.commit()
        resolved = row_dict(conn, rid)
        # The resolver already fills whatever exists AT RESOLVE TIME, so 2 and
        # 5 land immediately here and only 10 is out of reach.
        assert resolved["ret_2session"] is not None
        assert resolved["ret_5session"] is not None
        assert resolved["ret_10session"] is None

        rep = collect.backfill_horizons(conn, cfg_for(edb, adb), cal())
        conn.commit()
        assert rep["filled"] == {2: 0, 5: 0, 10: 0}
        assert rep["rows_still_incomplete"] == 1
        assert row_dict(conn, rid)["ret_10session"] is None
        conn.close()

        extend_bars(adb, {"AAA": 0.01})
        conn = store.open_store(edb)
        rep = collect.backfill_horizons(conn, cfg_for(edb, adb), cal())
        conn.commit()
        after = row_dict(conn, rid)
        conn.close()
        assert rep["filled"] == {2: 0, 5: 0, 10: 1}
        assert rep["rows_still_incomplete"] == 0
        assert after["ret_10session"] == pytest.approx(1.01 ** 10 - 1.0)
        # The reachable horizons the resolver had already written are unmoved.
        assert after["ret_2session"] == resolved["ret_2session"]
        assert after["ret_5session"] == resolved["ret_5session"]


class TestFormationCorrectBenchmark:
    """A row is benchmarked against the band of its OWN formation."""

    BANDS = {"2026-01-02": ["AAA", "BBB"], "2026-04-01": ["AAA", "CCC"]}

    def expected_bench(self, members: list[str]) -> float:
        # Equal-weighted close-to-close over the scored window, per Task 5.
        return sum(DRIFT[m] for m in members) / len(members)

    def resolve_one_row(self, env, row_formation: str, run_formation: str,
                        band_for) -> dict:
        conn = store.open_store(env["edb"])
        rid = insert_row(conn, formation_date=row_formation)
        conn.commit()
        collect.resolve_pending(conn, cfg_for(env["edb"], env["adb"],
                                             run_formation), cal(),
                                self.BANDS[run_formation], band_for=band_for)
        conn.commit()
        out = row_dict(conn, rid)
        conn.close()
        return out

    def check_cross_formation(self, env, band_for) -> None:
        """A July row resolved during an October run must read July's band."""
        out = self.resolve_one_row(env, "2026-01-02", "2026-04-01", band_for)
        assert out["outcome_state"] == "resolved"
        assert out["bench_1session"] == pytest.approx(
            self.expected_bench(["AAA", "BBB"]))

    def test_row_from_an_earlier_formation_uses_its_own_band(self, env):
        self.check_cross_formation(env, self.BANDS.get)

    def test_mutation_using_the_run_band_for_every_row_is_caught(self, env):
        """MUTATION: ignore the row's formation and use the RUN's band, the
        behaviour before this fix. The cross-formation check must fail."""
        with pytest.raises(AssertionError):
            self.check_cross_formation(
                env, lambda f: self.BANDS["2026-04-01"])

    def test_the_two_bands_really_do_price_differently(self, env):
        """Without this the mutation test could pass on an accident."""
        assert self.expected_bench(["AAA", "BBB"]) != \
            self.expected_bench(["AAA", "CCC"])

    def test_row_from_the_running_formation_uses_the_running_band(self, env):
        out = self.resolve_one_row(env, "2026-04-01", "2026-04-01",
                                   self.BANDS.get)
        assert out["bench_1session"] == pytest.approx(
            self.expected_bench(["AAA", "CCC"]))

    def test_an_unresolvable_formation_leaves_the_row_pending(self, env):
        conn = store.open_store(env["edb"])
        rid = insert_row(conn, formation_date="2026-01-02")
        conn.commit()
        assert collect.resolve_pending(conn, cfg_for(env["edb"], env["adb"]),
                                       cal(), [],
                                       band_for=lambda f: None) == 0
        out = row_dict(conn, rid)
        conn.close()
        assert out["outcome_state"] == "pending"
        assert out["bench_1session"] is None

    def test_the_real_resolver_refuses_rather_than_substituting(self, env):
        """No stub. The seeded analysis db carries no `universe_asset`, so
        every formation is unresolvable and each must return None rather than
        fall back to another formation's band."""
        band_for = collect.band_resolver(cfg_for(env["edb"], env["adb"]),
                                         cal())
        assert band_for("2026-01-02") is None
        assert band_for("2026-04-01") is None

    def test_the_seed_is_used_for_the_running_formation_only(self, env):
        """The running band seeds the cache so the common case costs no extra
        resolution, and it must NOT answer for any other formation."""
        band_for = collect.band_resolver(
            cfg_for(env["edb"], env["adb"], "2026-04-01"), cal(),
            {"2026-04-01": ["AAA", "CCC"]})
        assert band_for("2026-04-01") == ["AAA", "CCC"]
        assert band_for("2026-01-02") is None


def assigned_columns(sql: str) -> set[str]:
    body = sql.split(" SET ", 1)[1].split(" WHERE ")[0]
    return {m.group(1) for m in re.finditer(r"(\w+)\s*=", body)}


class TestNoJudgmentCanChange:
    FORBIDDEN = {"judgment", "strength", "reason", "raw_response", "headline",
                 "prompt_sha256", "model_id", "temperature", "called_ts",
                 "cost_usd", "state", "symbol", "formation_date",
                 "query_date", "run_kind", "spec_version"}

    def test_no_outcome_statement_can_write_a_judgment_column(self):
        for sql in (collect.RESOLVE_UPDATE_SQL, collect.HORIZON_UPDATE_SQL):
            assert not assigned_columns(sql) & self.FORBIDDEN, sql

    def test_the_horizon_statement_writes_only_the_companions(self):
        assert assigned_columns(collect.HORIZON_UPDATE_SQL) == {
            f"ret_{k}session" for k in outcomes.COMPANION_HORIZONS}

    def test_both_passes_execute_only_their_own_statements(self):
        src = (inspect.getsource(collect.resolve_pending)
               + inspect.getsource(collect.backfill_horizons))
        assert src.count("UPDATE news_observation") == 0, \
            "an inline UPDATE would bypass the audited constants"

    def test_maintenance_over_a_whole_db_moves_no_judgment(self, env):
        conn = store.open_store(env["edb"])
        ids = [insert_row(conn, symbol=s) for s in DRIFT]
        conn.commit()
        before = {i: row_dict(conn, i) for i in ids}
        conn.close()

        maintain.run_maintenance(env["edb"], env["adb"])

        conn = store.open_store(env["edb"])
        after = {i: row_dict(conn, i) for i in ids}
        conn.close()
        for i in ids:
            for col in sorted(self.FORBIDDEN):
                assert before[i][col] == after[i][col], (i, col)

    def test_the_companion_horizons_exclude_the_scored_one(self):
        assert 1 not in outcomes.COMPANION_HORIZONS
        assert set(outcomes.COMPANION_HORIZONS) | {1} == set(
            spec.RETURN_HORIZONS)
