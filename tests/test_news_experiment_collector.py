"""The collector's behaviour, against a hermetic fixture database.

EVERY STATE IS PRODUCED, NEVER ASSERTED. The absent-input rule is the reason
this package has the shape it does, and five fabrications are recorded in this
project where absent input rendered as a plausible number. So these tests drive
the real collector down its real branches and read what it wrote.

THE ABSENT-INPUT RULE IS MUTATION-TESTED. `test_mutation_*` applies the exact
defect the rule exists to prevent, a failed source answering as an empty one,
and asserts the state check catches it. A test that cannot fail is not a test.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from news_experiment import collect, spec, store, universe
from news_experiment.dedup import Deduplicator
from news_experiment.horizon import Calendar, resolve_anchor
from news_experiment.scoring import (ScoreResult, SpendCeiling,
                                     SpendCeilingReached, parse_verdict)

SESSIONS = ([f"2026-01-{d:02d}" for d in range(1, 29)]
            + [f"2026-02-{d:02d}" for d in range(1, 29)]
            + [f"2026-03-{d:02d}" for d in range(1, 21)])
FORMATION = SESSIONS[65]

# One symbol per stratum plus two rejects, with volumes chosen so median
# dollar volume lands squarely inside each band.
SYMBOLS = {
    "AAA": (40.0, 1_200_000),   # 48.0M -> S1
    "BBB": (40.0, 400_000),     # 16.0M -> S2
    "CCC": (40.0, 200_000),     # 8.0M  -> S3
    "DDD": (40.0, 75_000),      # 3.0M  -> S4
    "EEE": (40.0, 5_000),       # 0.2M  -> below the band
    "FFF": (5.0, 1_000_000),    # below the 10.00 price floor
}


@pytest.fixture()
def analysis_db(tmp_path):
    path = str(tmp_path / "analysis.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trading_calendar (date TEXT PRIMARY KEY, "
                 "open TEXT, close TEXT)")
    conn.executemany("INSERT INTO trading_calendar VALUES (?,?,?)",
                     [(d, "09:30", "16:00") for d in SESSIONS])
    conn.execute("CREATE TABLE bars (symbol TEXT, timeframe TEXT, "
                 "timestamp TEXT, open REAL, high REAL, low REAL, close REAL, "
                 "volume REAL, source TEXT)")
    rows = []
    for sym, (close, vol) in SYMBOLS.items():
        for i, day in enumerate(SESSIONS):
            drift = 1.0 + (i % 5) * 0.001
            rows.append((sym, "1day", f"{day}T05:00:00Z", close * 0.99 * drift,
                         close * 1.01, close * 0.98, close * drift, vol,
                         "backfill"))
    conn.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE TABLE universe_asset (symbol TEXT PRIMARY KEY, "
                 "name TEXT, exchange TEXT)")
    conn.executemany("INSERT INTO universe_asset VALUES (?,?,?)",
                     [(s, f"{s} Industries Inc", "NASDAQ") for s in SYMBOLS])
    conn.execute("CREATE TABLE listing_segment (symbol TEXT, seg INTEGER, "
                 "start_date TEXT, end_date TEXT)")
    conn.commit()
    conn.close()
    return path


class FakeFinnhub:
    """A news source whose answer per symbol-day is dictated by the test.

    `None` means the query FAILED. `[]` means it SUCCEEDED and there was no
    news. Keeping those apart is the whole point of the absent-input rule, and
    the real `FinnhubClient.company_news` uses exactly this convention.
    """

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def company_news(self, symbol, frm, to):
        self.calls.append((symbol, frm))
        return self.answers.get((symbol, frm), [])

    def _get(self, path, params):
        return {"finnhubIndustry": "Technology"}


class FakeScorer:
    """Returns a scripted verdict per headline."""

    def __init__(self, script: dict, default: ScoreResult | None = None):
        self.script = script
        self.default = default or ScoreResult(
            state=spec.STATE_JUDGED,
            raw_response='{"judgment":"NEUTRAL","strength":1,'
                         '"reason":"routine"}',
            judgment="NEUTRAL", strength=1, reason="routine", parse_ok=True,
            strength_parse_ok=True, input_tokens=290, output_tokens=35,
            cost_usd=0.000465)
        self.seen: list[str] = []

    def score(self, ticker, headline):
        self.seen.append(headline)
        return self.script.get(headline, self.default)


def _article(aid, headline, when: datetime, source="Reuters"):
    return {"id": aid, "headline": headline, "source": source,
            "datetime": int(when.timestamp())}


def _cfg(analysis_db, tmp_path, **kw):
    defaults = dict(formation=FORMATION, day_from=SESSIONS[70],
                    day_to=SESSIONS[70], symbols=0, ceiling=1.0,
                    db_path=str(tmp_path / "obs.db"), run_kind="demonstration",
                    analysis_db=analysis_db)
    defaults.update(kw)
    return collect.RunConfig(**defaults)


@pytest.fixture(autouse=True)
def _experiment_key(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_ANTHROPIC_API_KEY", "test-key-not-a-secret")


# --- The universe rule -------------------------------------------------------

def test_band_admits_only_symbols_inside_the_adv_band(analysis_db):
    members, rejects = universe.resolve_band(analysis_db, FORMATION)
    by_symbol = {m.symbol: m for m in members}
    assert set(by_symbol) == {"AAA", "BBB", "CCC", "DDD"}
    assert by_symbol["AAA"].stratum == "S1"
    assert by_symbol["BBB"].stratum == "S2"
    assert by_symbol["CCC"].stratum == "S3"
    assert by_symbol["DDD"].stratum == "S4"
    assert rejects.get("below_price_floor") == 1      # FFF at 5.00
    assert rejects.get("outside_adv_band") == 1       # EEE below the band


def test_liquidity_rank_is_recorded_over_the_eligible_pool(analysis_db):
    """Rank is recorded, never used as the band variable, so the superseded
    rank rule stays scoreable as a pre-registered robustness check."""
    members, _ = universe.resolve_band(analysis_db, FORMATION)
    ranks = {m.symbol: m.liquidity_rank for m in members}
    assert ranks["AAA"] < ranks["BBB"] < ranks["CCC"] < ranks["DDD"]
    assert max(ranks.values()) <= 5


def test_the_sample_is_reproducible_from_its_seed(analysis_db):
    members, _ = universe.resolve_band(analysis_db, FORMATION)
    a = universe.stratified_sample(members, rule_id=spec.RULE_ID,
                                   formation_date=FORMATION, per_stratum=1)
    b = universe.stratified_sample(members, rule_id=spec.RULE_ID,
                                   formation_date=FORMATION, per_stratum=1)
    assert [m.symbol for m in a] == [m.symbol for m in b]
    assert universe.draw_seed(spec.RULE_ID, FORMATION) != \
        universe.draw_seed(spec.RULE_ID, SESSIONS[64])


def test_the_window_ends_before_the_formation_date():
    start, end = universe.window_for(SESSIONS, FORMATION)
    assert end < FORMATION
    assert SESSIONS.index(end) == SESSIONS.index(FORMATION) - 1
    assert (SESSIONS.index(FORMATION) - SESSIONS.index(start)
            == spec.WINDOW_SESSIONS)


# --- The four states, each produced ------------------------------------------

def _states(db_path) -> dict:
    conn = sqlite3.connect(db_path)
    out = dict(conn.execute(
        "SELECT state, COUNT(*) FROM news_observation GROUP BY state"))
    conn.close()
    return out


def test_every_recorded_state_is_produced(analysis_db, tmp_path):
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {
        ("AAA", day): [_article(1, "AAA wins a large contract", when)],
        ("BBB", day): [],                       # no_news, absence PROVEN
        ("CCC", day): None,                     # source_failed, UNPROVEN
        ("DDD", day): [_article(2, "DDD files an 8-K", when)],
    }
    scorer = FakeScorer({
        "DDD files an 8-K": ScoreResult(state=spec.STATE_MODEL_FAILED,
                                        raw_response="upstream 500",
                                        error_class="http_status"),
    })
    cfg = _cfg(analysis_db, tmp_path)
    report = collect.run(cfg, finnhub_client=FakeFinnhub(answers),
                         scorer=scorer)
    states = _states(cfg.db_path)
    assert states.get(spec.STATE_JUDGED) == 1
    assert states.get(spec.STATE_NO_NEWS) == 1
    assert states.get(spec.STATE_SOURCE_FAILED) == 1
    assert states.get(spec.STATE_MODEL_FAILED) == 1
    assert report["coverage"]["symbols_queried"] == 4


def test_no_news_and_source_failed_never_merge(analysis_db, tmp_path):
    """The first is evidence of absence. The second is absence of evidence.
    Collapsing them would let an outage read as a quiet news day."""
    day = SESSIONS[70]
    answers = {("AAA", day): [], ("BBB", day): None, ("CCC", day): [],
               ("DDD", day): None}
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers),
                scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    rows = dict(conn.execute("SELECT symbol, state FROM news_observation"))
    conn.close()
    assert rows["AAA"] == spec.STATE_NO_NEWS
    assert rows["BBB"] == spec.STATE_SOURCE_FAILED
    assert rows["CCC"] == spec.STATE_NO_NEWS
    assert rows["DDD"] == spec.STATE_SOURCE_FAILED


def test_a_no_news_row_carries_no_judgment_and_no_strength(analysis_db,
                                                           tmp_path):
    """A `no_news` row emits no order, no signal and no factor value of any
    kind. Nothing may be inferred from it."""
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub({}), scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    rows = conn.execute(
        "SELECT judgment, strength, raw_response, cost_usd FROM "
        "news_observation WHERE state='no_news'").fetchall()
    conn.close()
    assert rows
    for judgment, strength, raw, cost in rows:
        assert judgment is None and strength is None
        assert raw is None and cost is None


def test_mutation_a_failed_source_answering_as_empty_is_caught(analysis_db,
                                                              tmp_path):
    """MUTATION TEST of the absent-input rule.

    The exact defect the rule prevents: a source failure rendering as an empty
    result, so an outage reads as a quiet news day. The mutant maps None to []
    on the way out of the client, which is what a careless `or []` in a caller
    would do. The state check must catch it.
    """
    day = SESSIONS[70]
    answers = {("AAA", day): None, ("BBB", day): None, ("CCC", day): None,
               ("DDD", day): None}

    class MutantFinnhub(FakeFinnhub):
        def company_news(self, symbol, frm, to):
            return super().company_news(symbol, frm, to) or []

    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=MutantFinnhub(answers),
                scorer=FakeScorer({}))
    states = _states(cfg.db_path)
    # Under the mutation every row reads no_news, so the assertion the real
    # test makes would fail. That is what proves the assertion works.
    assert states.get(spec.STATE_NO_NEWS) == 4
    assert states.get(spec.STATE_SOURCE_FAILED) is None
    with pytest.raises(AssertionError):
        assert states.get(spec.STATE_SOURCE_FAILED) == 4


# --- Strength ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expect_strength,expect_ok", [
    ('{"judgment":"POSITIVE","strength":4,"reason":"beat"}', 4, True),
    ('{"judgment":"POSITIVE","strength":"4","reason":"beat"}', 4, True),
    ('{"judgment":"POSITIVE","strength":9,"reason":"beat"}', None, False),
    ('{"judgment":"POSITIVE","strength":0,"reason":"beat"}', None, False),
    ('{"judgment":"POSITIVE","strength":"high","reason":"beat"}', None, False),
    ('{"judgment":"POSITIVE","reason":"beat"}', None, False),
    ('{"judgment":"POSITIVE","strength":true,"reason":"beat"}', None, False),
    ('{"judgment":"POSITIVE","strength":3.5,"reason":"beat"}', None, False),
])
def test_a_malformed_strength_never_discards_a_valid_judgment(
        raw, expect_strength, expect_ok):
    """Strength gates nothing, so letting it invalidate the primary field
    would trade the measurement for the diagnostic."""
    parsed = parse_verdict(raw)
    assert parsed.parse_ok is True
    assert parsed.judgment == "POSITIVE"
    assert parsed.strength == expect_strength
    assert parsed.strength_parse_ok is expect_ok


def test_an_unparseable_judgment_is_model_failed():
    for raw in ("", "I cannot answer that", '{"judgment":"MAYBE"}', "{}"):
        parsed = parse_verdict(raw)
        assert parsed.parse_ok is False
        assert parsed.judgment is None


def test_a_neutral_strength_other_than_one_is_recorded_and_flagged():
    """Recorded as returned and counted as a format diagnostic, never
    discarded and never model_failed."""
    parsed = parse_verdict('{"judgment":"NEUTRAL","strength":4,"reason":"x"}')
    assert parsed.parse_ok is True
    assert parsed.judgment == "NEUTRAL"
    assert parsed.strength == 4
    assert parsed.neutral_strength_anomaly is True
    ok = parse_verdict('{"judgment":"NEUTRAL","strength":1,"reason":"x"}')
    assert ok.neutral_strength_anomaly is False


def test_case_is_normalised_because_the_model_plainly_considered_it():
    parsed = parse_verdict('{"judgment":"Positive","strength":2,"reason":"x"}')
    assert parsed.judgment == "POSITIVE"


# --- De-duplication ----------------------------------------------------------

def test_near_identical_headlines_collapse_within_the_window():
    dd = Deduplicator()
    base = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    first, _ = dd.consider(ticker="AAA", headline="Acme wins big contract!",
                           article_id="1", published=base)
    second, _ = dd.consider(ticker="AAA", headline="ACME  wins big contract",
                            article_id="2",
                            published=base + timedelta(hours=3))
    assert first is False and second is True


def test_the_same_article_id_collapses_even_when_reworded():
    dd = Deduplicator()
    base = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    dd.consider(ticker="AAA", headline="One wording", article_id="42",
                published=base)
    dup, _ = dd.consider(ticker="AAA", headline="A different wording entirely",
                         article_id="42", published=base + timedelta(hours=1))
    assert dup is True


def test_outside_the_window_is_not_a_duplicate():
    dd = Deduplicator()
    base = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    dd.consider(ticker="AAA", headline="Acme wins", article_id="1",
                published=base)
    dup, _ = dd.consider(ticker="AAA", headline="Acme wins", article_id="9",
                         published=base + timedelta(hours=25))
    assert dup is False


def test_one_story_across_tickers_shares_a_story_group():
    dd = Deduplicator()
    base = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    dup_a, group_a = dd.consider(ticker="AAA", headline="Sector-wide recall",
                                 article_id="1", published=base)
    dup_b, group_b = dd.consider(ticker="BBB", headline="Sector-wide recall",
                                 article_id="2",
                                 published=base + timedelta(minutes=5))
    assert dup_a is False and dup_b is False, "different tickers, both scored"
    assert group_a == group_b, "one story, one group"


# --- The minimum delay -------------------------------------------------------

@pytest.fixture()
def cal():
    return Calendar.from_rows([(d, "09:30", "16:00") for d in SESSIONS])


def test_a_headline_inside_the_session_anchors_on_that_close(cal):
    published = datetime(2026, 3, 10, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
    res = resolve_anchor(published, cal)
    assert res.anchor_kind == spec.ANCHOR_SAME_SESSION_CLOSE
    assert res.anchor_session == "2026-03-10"
    assert res.scoring_session == "2026-03-11"
    assert res.delay_rolled is False


def test_a_late_headline_rolls_to_the_next_session(cal):
    """Published 15:50 ET, ten minutes before the close, so the 20-minute
    delay makes that close unactionable."""
    published = datetime(2026, 3, 10, 19, 50, tzinfo=timezone.utc)
    res = resolve_anchor(published, cal)
    assert res.delay_rolled is True
    assert res.anchor_kind == spec.ANCHOR_NEXT_SESSION_OPEN
    assert res.anchor_session == "2026-03-11"
    assert res.scoring_session == "2026-03-11"


def test_exactly_twenty_minutes_before_the_close_still_acts(cal):
    """The boundary is inclusive: 20 minutes IS the minimum delay, so a
    headline exactly 20 minutes out is actionable."""
    published = datetime(2026, 3, 10, 19, 40, tzinfo=timezone.utc)
    res = resolve_anchor(published, cal)
    assert res.delay_rolled is False
    assert res.anchor_kind == spec.ANCHOR_SAME_SESSION_CLOSE


def test_an_overnight_headline_anchors_on_the_next_open(cal):
    published = datetime(2026, 3, 10, 23, 0, tzinfo=timezone.utc)  # 19:00 ET
    res = resolve_anchor(published, cal)
    assert res.anchor_kind == spec.ANCHOR_NEXT_SESSION_OPEN
    assert res.anchor_session == "2026-03-11"
    assert res.scoring_session == "2026-03-11"
    assert res.delay_rolled is False


def test_a_headline_just_before_the_open_rolls_too(cal):
    """The delay is stated about the FIRST ACTIONABLE MOMENT, not about closes
    specifically. Eight minutes before the bell is as unactionable at that
    bell as eight minutes before the close is at that close."""
    published = datetime(2026, 3, 11, 13, 22, tzinfo=timezone.utc)  # 09:22 ET
    res = resolve_anchor(published, cal)
    assert res.delay_rolled is True
    assert res.anchor_session == "2026-03-12"


# --- The spend ceiling -------------------------------------------------------

def test_the_ceiling_refuses_before_the_call_that_would_cross_it():
    ceiling = SpendCeiling(limit_usd=0.001)
    ceiling.check()
    ceiling.record(0.0006)
    with pytest.raises(SpendCeilingReached):
        ceiling.check()


def test_the_ceiling_is_enforced_from_zero_spend():
    """A ceiling below one projected call refuses the FIRST call, not the
    second. Enforced before the first call, never after the first overrun."""
    with pytest.raises(SpendCeilingReached):
        SpendCeiling(limit_usd=0.0001).check()


# --- Recording ---------------------------------------------------------------

def test_every_task_8_field_exists_in_the_schema(tmp_path):
    conn = store.open_store(str(tmp_path / "s.db"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news_observation)")}
    conn.close()
    required = {
        "rule_id", "formation_date", "symbol", "adv_usd_at_formation",
        "liquidity_rank", "stratum", "median_close_at_formation", "sector",
        "query_date", "state", "exclusion_reason", "headline", "source_name",
        "source_article_id", "published_ts", "fetched_ts", "story_group_id",
        "model_id", "prompt_sha256", "temperature", "called_ts", "latency_ms",
        "raw_response", "judgment", "reason", "parse_ok", "error_class",
        "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd",
        "anchor_kind", "anchor_ts", "anchor_price", "ret_intraday",
        "ret_1session", "ret_2session", "ret_5session", "ret_10session",
        "bench_1session", "excess_1session", "bar_source",
        "cost_bp_round_trip", "net_bp", "spec_version", "collector_git_sha",
        "strength", "strength_parse_ok",
    }
    assert required <= cols, f"missing Task 8 fields: {sorted(required - cols)}"


def test_an_unknown_column_raises_rather_than_being_dropped(tmp_path):
    conn = store.open_store(str(tmp_path / "s.db"))
    with pytest.raises(KeyError):
        store.insert_observation(conn, {
            "rule_id": "r", "formation_date": "2026-01-02", "symbol": "AAA",
            "query_date": "2026-01-02", "state": spec.STATE_NO_NEWS,
            "spec_version": "v", "typo_field": 1})
    conn.close()


def test_the_raw_response_is_stored_not_only_the_parsed_verdict(analysis_db,
                                                               tmp_path):
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    raw = ('Here you go: {"judgment":"POSITIVE","strength":4,'
           '"reason":"contract win"}')
    answers = {("AAA", day): [_article(1, "AAA wins", when)]}
    scorer = FakeScorer({"AAA wins": ScoreResult(
        state=spec.STATE_JUDGED, raw_response=raw, judgment="POSITIVE",
        strength=4, reason="contract win", parse_ok=True,
        strength_parse_ok=True, input_tokens=290, output_tokens=35,
        cost_usd=0.000465)})
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers), scorer=scorer)
    conn = sqlite3.connect(cfg.db_path)
    stored = conn.execute("SELECT raw_response, judgment, strength FROM "
                          "news_observation WHERE state='judged'").fetchone()
    conn.close()
    assert stored[0] == raw, "the full response text, not only the verdict"
    assert stored[1] == "POSITIVE" and stored[2] == 4


def test_outcome_state_starts_pending_never_zero(analysis_db, tmp_path):
    """A freshly collected row HAS no outcome. A NULL return must never be
    read as a zero return, so the state says which it is."""
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {("AAA", day): [_article(1, "AAA wins", when)]}
    cfg = _cfg(analysis_db, tmp_path, day_from=day, day_to=day)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers),
                scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    rows = conn.execute("SELECT outcome_state, ret_1session FROM "
                        "news_observation WHERE state='judged'").fetchall()
    conn.close()
    assert rows
    for state, ret in rows:
        assert state in ("pending", "resolved", "excluded")
        if state != "resolved":
            assert ret is None, "an unresolved outcome is NULL, never 0.0"


def test_a_judged_row_always_carries_a_judgment(analysis_db, tmp_path):
    """`judged` means the model returned a parseable verdict. A row that never
    reached the model must not wear it. The first demonstration run recorded a
    collapsed duplicate as `judged` with a NULL judgment, which is exactly the
    kind of plausible-looking record this project keeps correcting."""
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {("AAA", day): [
        _article(1, "AAA wins a contract", when),
        _article(2, "AAA  wins a contract!", when + timedelta(hours=1)),
    ]}
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers),
                scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    orphans = conn.execute(
        "SELECT COUNT(*) FROM news_observation "
        "WHERE state='judged' AND judgment IS NULL").fetchone()[0]
    dup = conn.execute(
        "SELECT state, error_class, exclusion_reason FROM news_observation "
        "WHERE exclusion_reason='duplicate_headline'").fetchone()
    conn.close()
    assert orphans == 0, "a judged row with no judgment is a fabrication"
    assert dup == (spec.STATE_EXCLUDED_PRE_CALL, "duplicate_headline",
                   "duplicate_headline")


# --- AMENDMENT 4: the fifth state --------------------------------------------

@pytest.mark.parametrize("article,error_class,exclusion", [
    ({"id": 7, "headline": "No timestamp here", "source": "X", "datetime": 0},
     "no_publication_time", spec.EXCLUSION_NO_PUBLICATION_TIME),
    ({"id": 8, "headline": "From the future", "source": "X",
      "datetime": int(datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp())},
     "clock_inconsistent", spec.EXCLUSION_CLOCK_INCONSISTENT),
], ids=["no-publication-time", "clock-inconsistent"])
def test_each_pre_call_condition_produces_excluded_pre_call(
        analysis_db, tmp_path, article, error_class, exclusion):
    """The rule is one question: was a request sent to the provider? These were
    never eligible for one, so none of them is a provider failure."""
    day = SESSIONS[70]
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub({("AAA", day): [article]}),
                scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    row = conn.execute(
        "SELECT state, error_class, exclusion_reason FROM news_observation "
        "WHERE headline=?", (article["headline"],)).fetchone()
    conn.close()
    assert row == (spec.STATE_EXCLUDED_PRE_CALL, error_class, exclusion)


def test_a_duplicate_produces_excluded_pre_call(analysis_db, tmp_path):
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {("AAA", day): [
        _article(1, "AAA wins a contract", when),
        _article(2, "AAA  wins a contract!", when + timedelta(hours=1)),
    ]}
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers),
                scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    state, ec = conn.execute(
        "SELECT state, error_class FROM news_observation "
        "WHERE exclusion_reason='duplicate_headline'").fetchone()
    conn.close()
    assert state == spec.STATE_EXCLUDED_PRE_CALL
    assert ec == "duplicate_headline"


def test_excluded_pre_call_and_model_failed_never_merge(analysis_db, tmp_path):
    """Both appear in one run and stay separate. `model_failed` is provider
    health, `excluded_pre_call` is sample composition, and a combined rate
    answers neither question."""
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {
        ("AAA", day): [{"id": 7, "headline": "No stamp", "source": "X",
                        "datetime": 0}],
        ("BBB", day): [_article(2, "BBB files", when)],
    }
    scorer = FakeScorer({"BBB files": ScoreResult(
        state=spec.STATE_MODEL_FAILED, raw_response="upstream 500",
        error_class="http_status")})
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers), scorer=scorer)
    conn = sqlite3.connect(cfg.db_path)
    states = dict(conn.execute(
        "SELECT state, COUNT(*) FROM news_observation GROUP BY state"))
    conn.close()
    assert states.get(spec.STATE_EXCLUDED_PRE_CALL) == 1
    assert states.get(spec.STATE_MODEL_FAILED) == 1
    assert spec.STATE_EXCLUDED_PRE_CALL != spec.STATE_MODEL_FAILED


def test_an_excluded_pre_call_row_carries_no_model_output_and_no_cost(
        analysis_db, tmp_path):
    """No call was attempted, so there is nothing the provider produced and
    nothing it charged. A cost on such a row would be a fabrication."""
    day = SESSIONS[70]
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub({("AAA", day): [
        {"id": 7, "headline": "No stamp", "source": "X", "datetime": 0}]}),
        scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    row = conn.execute(
        "SELECT judgment, strength, raw_response, cost_usd, called_ts, "
        "latency_ms, input_tokens, output_tokens FROM news_observation "
        "WHERE state=?", (spec.STATE_EXCLUDED_PRE_CALL,)).fetchone()
    conn.close()
    assert row is not None
    assert all(v is None for v in row), f"pre-call row carries model output: {row}"


def test_mutation_collapsing_the_two_failure_states_is_caught(analysis_db,
                                                             tmp_path,
                                                             monkeypatch):
    """MUTATION TEST of the state separation.

    The mutant is the pre-Amendment-4 behaviour: route a pre-call exclusion to
    `model_failed`. Under it the two conditions share one representation, the
    shape behind all six recorded fabrications in this project. The separation
    check must catch it.
    """
    monkeypatch.setattr(spec, "STATE_EXCLUDED_PRE_CALL",
                        spec.STATE_MODEL_FAILED)
    day = SESSIONS[70]
    when = datetime(2026, 3, 11, 14, 0, tzinfo=timezone.utc)
    answers = {
        ("AAA", day): [{"id": 7, "headline": "No stamp", "source": "X",
                        "datetime": 0}],
        ("BBB", day): [_article(2, "BBB files", when)],
    }
    scorer = FakeScorer({"BBB files": ScoreResult(
        state=spec.STATE_MODEL_FAILED, raw_response="upstream 500",
        error_class="http_status")})
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub(answers), scorer=scorer)
    conn = sqlite3.connect(cfg.db_path)
    states = dict(conn.execute(
        "SELECT state, COUNT(*) FROM news_observation GROUP BY state"))
    conn.close()
    # Under the mutation both land on model_failed and the pre-call state
    # vanishes, so the real test's assertion fails. That is what proves it works.
    assert states.get("excluded_pre_call") is None
    assert states.get(spec.STATE_MODEL_FAILED) == 2
    with pytest.raises(AssertionError):
        assert states.get("excluded_pre_call") == 1


def test_a_delay_rolled_headline_is_scored_not_excluded(analysis_db, tmp_path):
    """AMENDMENT 4 confirms Task 4. The 20-minute delay moves a headline to a
    tradeable moment, it does not discard it, and excluding late headlines
    would systematically remove those arriving near the close."""
    assert not hasattr(spec, "EXCLUSION_DELAY_ROLLED")
    assert "delay_rolled" not in spec.EXCLUSION_REASONS
    day = SESSIONS[70]
    # 15:50 ET, ten minutes before the close.
    late = datetime(2026, 3, 11, 19, 50, tzinfo=timezone.utc)
    cfg = _cfg(analysis_db, tmp_path, day_from=day, day_to=day)
    collect.run(cfg, finnhub_client=FakeFinnhub(
        {("AAA", day): [_article(1, "AAA late headline", late)]}),
        scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    row = conn.execute(
        "SELECT state, delay_rolled, exclusion_reason, anchor_kind, "
        "scoring_session, judgment FROM news_observation "
        "WHERE headline='AAA late headline'").fetchone()
    conn.close()
    assert row[0] == spec.STATE_JUDGED, "a rolled headline is scored"
    assert row[1] == 1, "the roll is recorded on its own boolean"
    assert row[2] == "", "and it is NOT an exclusion"
    assert row[3] == spec.ANCHOR_NEXT_SESSION_OPEN
    assert row[4] == "2026-03-12", "scored at the session it rolled to"
    assert row[5] is not None


# --- Credential and latch separation (Open Question 9) -----------------------

def test_the_experiment_key_never_silently_falls_back_to_the_council(
        monkeypatch):
    """A silent fallback would restore the exact coupling this exists to
    remove, invisibly. Refusing is the safe direction."""
    from news_experiment import credentials as expcred
    monkeypatch.delenv("EXPERIMENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "council-key-not-a-secret")
    monkeypatch.setattr(expcred, "_from_keystore", lambda name: None)
    res = expcred.resolve_experiment_key()
    assert res.key is None and res.source == "missing" and res.shared is False


def test_the_shared_key_is_opt_in_and_is_labelled_shared(monkeypatch):
    from news_experiment import credentials as expcred
    monkeypatch.delenv("EXPERIMENT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "council-key-not-a-secret")
    monkeypatch.setattr(expcred, "_from_keystore", lambda name: None)
    res = expcred.resolve_experiment_key(allow_shared=True)
    assert res.key == "council-key-not-a-secret"
    assert res.shared is True and res.source == "shared_council"
    assert "SHARED KEY IN USE" in res.describe()
    assert res.key not in res.describe(), "a description never carries a key"


def test_its_own_key_wins_and_is_not_shared(monkeypatch):
    from news_experiment import credentials as expcred
    monkeypatch.setenv("EXPERIMENT_ANTHROPIC_API_KEY", "own-key-not-a-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "council-key-not-a-secret")
    monkeypatch.setattr(expcred, "_from_keystore", lambda name: None)
    res = expcred.resolve_experiment_key(allow_shared=True)
    assert res.key == "own-key-not-a-secret" and res.shared is False
    assert res.label == expcred.EXPERIMENT_PROVIDER_LABEL


def test_the_exhaustion_latch_treats_them_as_two_providers():
    """The latch is keyed by provider LABEL. Two labels are two entries, so an
    exhaustion on one leaves the other callable. This is the half that works
    even before the operator creates a second key."""
    from llm_consensus import provider_health
    from news_experiment import credentials as expcred
    provider_health.reset_exhaustion()
    try:
        provider_health.mark_exhausted(expcred.COUNCIL_PROVIDER_LABEL,
                                       model_id="claude-opus-4-8")
        assert provider_health.is_exhausted(expcred.COUNCIL_PROVIDER_LABEL)
        assert not provider_health.is_exhausted(
            expcred.EXPERIMENT_PROVIDER_LABEL), (
            "a council exhaustion must not stop the collector")
        provider_health.mark_exhausted(expcred.EXPERIMENT_PROVIDER_LABEL,
                                       model_id=spec.MODEL_ID)
        assert len(provider_health.exhausted_providers()) == 2
    finally:
        provider_health.reset_exhaustion()
    assert expcred.latch_is_separate() is True


def test_the_separation_probe_leaves_the_latch_as_it_found_it():
    """The latch is process state, so a probe that clobbered it would drop a
    genuinely exhausted provider back into rotation."""
    from llm_consensus import provider_health
    from news_experiment import credentials as expcred
    provider_health.reset_exhaustion()
    try:
        provider_health.mark_exhausted("openai", model_id="gpt-5.5",
                                       detail="quota")
        expcred.latch_is_separate()
        assert provider_health.is_exhausted("openai")
        assert provider_health.exhausted_providers()["openai"]["model_id"] \
            == "gpt-5.5"
    finally:
        provider_health.reset_exhaustion()


def test_a_scorer_on_a_latched_label_refuses_without_calling():
    from llm_consensus import provider_health
    from news_experiment import credentials as expcred
    from news_experiment.scoring import Scorer

    def exploding_poster(url, headers, payload):
        raise AssertionError("a latched provider must never be called")

    provider_health.reset_exhaustion()
    try:
        provider_health.mark_exhausted(expcred.EXPERIMENT_PROVIDER_LABEL)
        scorer = Scorer(key="k", label=expcred.EXPERIMENT_PROVIDER_LABEL,
                        ceiling=SpendCeiling(limit_usd=1.0),
                        poster=exploding_poster)
        result = scorer.score("AAA", "anything")
        assert result.state == spec.STATE_MODEL_FAILED
        assert result.error_class == "exhausted"
    finally:
        provider_health.reset_exhaustion()


def test_the_stale_rule_id_and_the_real_floor_are_both_recorded(analysis_db,
                                                                tmp_path):
    cfg = _cfg(analysis_db, tmp_path)
    collect.run(cfg, finnhub_client=FakeFinnhub({}), scorer=FakeScorer({}))
    conn = sqlite3.connect(cfg.db_path)
    rule_id, floor = conn.execute(
        "SELECT rule_id, price_floor_at_formation FROM news_observation "
        "LIMIT 1").fetchone()
    conn.close()
    assert rule_id == spec.RULE_ID and "p5" in rule_id
    assert floor == 10.00, "the row is self-describing whatever the label says"
