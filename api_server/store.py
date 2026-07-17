"""Read-only data access for the API backend.

Every operational read goes through here. The connection is opened read-only
(``mode=ro``) so a bug can never write an operational table. Config values come
from the same YAML the engine loads. The bridge probe is a short-timeout local
HTTP call that reports reachability only.
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone

import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_REPO_ROOT, "market_ai_lab.db")
_DEFAULT_CFG = os.path.join(_REPO_ROOT, "config", "default_config.yaml")
_DEFAULT_BRIDGE = "http://127.0.0.1:8765"


def _db_path() -> str:
    """Resolve the operational DB path fresh each call (env-overridable)."""
    return os.environ.get("MAL_DB_PATH", _DEFAULT_DB)


def _cfg_path() -> str:
    return os.environ.get("MAL_CONFIG_PATH", _DEFAULT_CFG)


def _bridge_url() -> str:
    return os.environ.get("MAL_BRIDGE_URL", _DEFAULT_BRIDGE)

PAPER = "paper"
LIVE = "live"
MODES = (PAPER, LIVE)


def valid_mode(mode: str) -> str:
    return mode if mode in MODES else PAPER


# --- Category filtering (Paper/Live Stocks + Crypto subpages) ---------------
# The subpages filter server-side to a fixed symbol allow-list. Symbols match
# case-insensitively with "/" and "-" treated as equal, so both BTC/USD and the
# legacy BTC-USD land in the crypto bucket. Category is never trusted blindly:
# an unknown value falls back to no filter (all symbols).
STOCKS = "stocks"
CRYPTO = "crypto"
_CATEGORY_SYMBOLS: dict[str, set[str]] = {
    STOCKS: {"SPY", "QQQ"},
    CRYPTO: {"BTCUSD", "ETHUSD"},
}


def _norm_symbol(sym: str | None) -> str:
    return (sym or "").upper().replace("/", "").replace("-", "")


def valid_category(cat: str | None) -> str | None:
    return cat if cat in _CATEGORY_SYMBOLS else None


def _in_category(symbol: str | None, category: str | None) -> bool:
    if not category:
        return True
    return _norm_symbol(symbol) in _CATEGORY_SYMBOLS[category]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Connection -------------------------------------------------------------

def db_exists() -> bool:
    return os.path.exists(_db_path())


def _connect() -> sqlite3.Connection:
    uri = f"file:{_db_path()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query. Returns [] if the DB or table is absent."""
    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


# --- Config -----------------------------------------------------------------

def load_config() -> dict:
    try:
        with open(_cfg_path()) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def llm_models() -> dict:
    return {str(k): str(v)
            for k, v in (load_config().get("llm_models", {}) or {}).items()}


# --- Venue / mode helpers ---------------------------------------------------

def venue_state() -> list[dict]:
    return query(
        "SELECT venue, mode, live_enabled, credentials_connected, "
        "kill_switch_tripped, consecutive_losses, cooldown_until_ts, "
        "updated_ts FROM venue_state ORDER BY venue")


def _live_venues() -> set[str]:
    return {r["venue"] for r in venue_state() if r.get("live_enabled")}


def _mode_of(venue: str, live: set[str]) -> str:
    return LIVE if venue in live else PAPER


# --- Account / balances -----------------------------------------------------

def _latest_balances() -> list[dict]:
    return query(
        "SELECT venue, equity, cash, realized_pnl, unrealized_pnl, "
        "drawdown_pct, ts FROM account_balances b WHERE id = "
        "(SELECT MAX(id) FROM account_balances WHERE venue = b.venue) "
        "ORDER BY venue")


def account(mode: str) -> dict:
    mode = valid_mode(mode)
    live = _live_venues()
    latest = _latest_balances()
    venues = []
    totals = {"equity": 0.0, "cash": 0.0, "realized_pnl": 0.0,
              "unrealized_pnl": 0.0}
    worst_dd = 0.0
    for r in latest:
        v = r["venue"]
        if v == "AGGREGATE":
            continue
        if _mode_of(v, live) != mode:
            continue
        venues.append(r)
        for k in totals:
            totals[k] += float(r.get(k) or 0.0)
        worst_dd = min(worst_dd, float(r.get("drawdown_pct") or 0.0))
    if not venues and mode == PAPER:
        agg = next((r for r in latest if r["venue"] == "AGGREGATE"), None)
        if agg:
            for k in totals:
                totals[k] = float(agg.get(k) or 0.0)
            worst_dd = float(agg.get("drawdown_pct") or 0.0)
    return {"mode": mode, **{k: round(v, 2) for k, v in totals.items()},
            "drawdown_pct": round(worst_dd, 2), "venues": venues}


# --- Positions / orders / trades --------------------------------------------

def positions(mode: str, category: str | None = None) -> list[dict]:
    mode = valid_mode(mode)
    category = valid_category(category)
    live = _live_venues()
    rows = query(
        "SELECT venue, symbol, market, category, side, qty, avg_price, notional, "
        "opened_ts, unrealized_pnl FROM positions ORDER BY venue, symbol")
    return [r for r in rows
            if _mode_of(r["venue"], live) == mode
            and _in_category(r["symbol"], category)]


def sleeve_allocation() -> dict:
    """Current capital per sleeve (open-position notional), read-only. Powers the
    sleeve allocation panel. Never returns a key value."""
    rows = query(
        "SELECT COALESCE(sleeve,'quant_core') AS sleeve, "
        "SUM(notional) AS allocation, COUNT(*) AS open_positions "
        "FROM positions WHERE qty != 0 GROUP BY COALESCE(sleeve,'quant_core')")
    out = {"quant_core": {"allocation": 0.0, "open_positions": 0},
           "research_satellite": {"allocation": 0.0, "open_positions": 0}}
    total = 0.0
    for r in rows:
        s = r["sleeve"] if r["sleeve"] in out else "quant_core"
        out[s] = {"allocation": float(r["allocation"] or 0.0),
                  "open_positions": int(r["open_positions"] or 0)}
        total += float(r["allocation"] or 0.0)
    out["invested_total"] = total
    return out


def sleeve_history(sleeve: str | None = None, limit: int = 200) -> list[dict]:
    """Per-sleeve accounting snapshots over time, read-only."""
    limit = max(1, min(int(limit), 1000))
    if sleeve in ("quant_core", "research_satellite"):
        return query(
            "SELECT ts, sleeve, allocation, realized_pnl, unrealized_pnl, "
            "open_positions, wins, losses FROM sleeve_history WHERE sleeve=? "
            "ORDER BY id DESC LIMIT ?", (sleeve, limit))
    return query(
        "SELECT ts, sleeve, allocation, realized_pnl, unrealized_pnl, "
        "open_positions, wins, losses FROM sleeve_history ORDER BY id DESC LIMIT ?",
        (limit,))


def research_theses(limit: int = 100) -> list[dict]:
    """LLM deep-research theses (research feed + satellite positions), read-only.
    rationale is council prose, never a key value."""
    limit = max(1, min(int(limit), 500))
    return query(
        "SELECT ts, symbol, direction, conviction, horizon, rationale, status "
        "FROM research_thesis ORDER BY id DESC LIMIT ?", (limit,))


# --- Discovery (read-only) ---------------------------------------------------
# The Python discovery package writes these tables; this module only reads them,
# through the same mode=ro connection as everything else here. A DB predating
# discovery has no such tables, and `query` returns [] rather than raising, so
# these degrade to an empty view instead of a broken page.

def discovery_latest(asset_class: str | None = None) -> list[dict]:
    """The most recent funnel pass per asset class, with per-stage counts and
    every instrument dropped at each stage with its reason. Read-only."""
    classes = ([asset_class] if asset_class in ("crypto", "equity")
               else ["crypto", "equity"])
    out: list[dict] = []
    for ac in classes:
        # Most recent means most recent BY TIMESTAMP. Ordering by id would only
        # agree while rows are inserted in time order, which is true today but
        # is an assumption the view should not rest on. id breaks a tie.
        row = query_one(
            "SELECT id, ts, asset_class, universe_count, finalists_count, "
            "survivors_count, evaluated_count, council_calls, gate_calls, "
            "est_cost_usd, budget_remaining, status, reason, "
            "COALESCE(whale_surfaced_count, 0) AS whale_surfaced_count "
            "FROM discovery_pass WHERE asset_class = ? "
            "ORDER BY ts DESC, id DESC LIMIT 1", (ac,))
        if not row:
            continue
        row["drops"] = query(
            "SELECT symbol, stage, reason, score FROM discovery_drop "
            "WHERE pass_id = ? ORDER BY stage, score DESC, symbol",
            (row["id"],))
        out.append(row)
    return out


def discovery_candidates(limit: int = 50) -> list[dict]:
    """Stage-C survivors from the latest pass per asset class, with their
    four-level verdicts and ADVISORY sizing. Read-only.

    ``size_pct`` is a suggestion only: the engine's hard sleeve cap and the
    RiskGate both still apply and can only reduce it.
    """
    limit = max(1, min(int(limit), 200))
    # The latest pass per asset class, by TIMESTAMP (see discovery_latest).
    ids = [p["id"] for p in discovery_latest(None)]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return query(
        f"SELECT c.ts, c.symbol, c.verdict, c.direction, c.conviction, c.edge, "
        f"c.agreement, c.size_pct, c.horizon, c.sleeve_target, c.rationale, "
        f"COALESCE(c.whale_surfaced, 0) AS whale_surfaced, "
        f"c.whale_reason, p.asset_class FROM discovery_candidate c "
        f"JOIN discovery_pass p ON p.id = c.pass_id "
        f"WHERE c.pass_id IN ({placeholders}) "
        f"ORDER BY c.conviction DESC LIMIT ?", (*ids, limit))


def watchlist(limit: int = 100) -> list[dict]:
    """The current dynamic watchlist: why each instrument is on it, when it was
    added, its sleeve target, and its status. Read-only.

    Includes REFERRED entries alongside active ones, tagged by status. A referral
    is a name the adaptive layer offered to the funnel: it is genuinely on the
    watchlist, it is genuinely NOT tradeable, and the engine ignores it until a
    discovery pass promotes it. Hiding referrals would make the adaptive layer's
    main visible effect invisible on the page named after the list; showing them
    untagged would imply they trade. So: shown, and labelled.

    Active first, since that is the list that can actually take a position.
    """
    limit = max(1, min(int(limit), 500))
    return query(
        "SELECT symbol, asset_class, added_ts, updated_ts, source, reason, "
        "sleeve_target, score, status FROM watchlist "
        "WHERE status IN ('active', 'referred') "
        "ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, "
        "score DESC, updated_ts DESC, symbol LIMIT ?", (limit,))


def adaptive_events(limit: int = 100) -> list[dict]:
    """The live event feed, newest first, INCLUDING everything dropped for free.

    The dropped rows are the point, not noise: this layer's whole cost argument
    is that a free filter throws away the vast majority, and that claim is only
    checkable if what was thrown away is visible.
    """
    limit = max(1, min(int(limit), 500))
    return query(
        "SELECT id, ts, published_ts, symbol, headline, source, category, "
        "sentiment, event_type, held, material, material_reason, escalated "
        "FROM adaptive_event ORDER BY ts DESC, id DESC LIMIT ?", (limit,))


def adaptive_interpretations(limit: int = 50) -> list[dict]:
    """The escalated few: what a model actually said, and what came of it.

    Joined to the event so the operator reads the headline next to the verdict
    rather than an event id.
    """
    limit = max(1, min(int(limit), 200))
    return query(
        "SELECT i.id, i.event_id, i.ts, i.symbol, i.relevance, i.direction, "
        "i.severity, i.action, i.action_class, i.rationale, i.model, "
        "i.est_cost_usd, i.outcome, i.outcome_reason, e.headline "
        "FROM adaptive_interpretation i "
        "LEFT JOIN adaptive_event e ON e.id = i.event_id "
        "ORDER BY i.ts DESC, i.id DESC LIMIT ?", (limit,))


def adaptive_actions(limit: int = 50) -> list[dict]:
    """Defensive actions QUEUED for the engine. Only ever trim, exit, or flag."""
    limit = max(1, min(int(limit), 200))
    return query(
        "SELECT id, ts, event_id, symbol, action, reason, severity, source "
        "FROM adaptive_action ORDER BY ts DESC, id DESC LIMIT ?", (limit,))


def adaptive_engine_log(limit: int = 50) -> list[dict]:
    """What the ENGINE did with those actions, from its own event log.

    Queued is not applied: the engine still has to be running, still checks the
    flag, still re-checks the defensive allowlist, and still checks the action's
    age. Reading the outcome from the engine's own log, rather than trusting the
    request row, is what makes that difference visible.
    """
    limit = max(1, min(int(limit), 200))
    # The engine's event columns are `kind` and `payload_json`. Aliased to the
    # `type`/`payload` the GUI reads, so the naming lives in one place instead of
    # leaking the engine's column names into the frontend types.
    return query(
        "SELECT ts, kind AS type, symbol, severity, message, "
        "payload_json AS payload FROM events "
        "WHERE kind IN ('adaptive_defensive', 'adaptive_action_refused', "
        "'adaptive_action_noop', 'adaptive_flag_for_review') "
        "ORDER BY ts DESC, id DESC LIMIT ?", (limit,))


def watchlist_events(limit: int = 30) -> list[dict]:
    """Recent adds and prunes, so the operator sees the list living and changing.
    Includes REFUSED events (applied = 0), so an event from a not-yet-enabled
    source is visible rather than silent."""
    limit = max(1, min(int(limit), 200))
    return query(
        "SELECT ts, action, symbol, source, reason, applied FROM watchlist_event "
        "ORDER BY id DESC LIMIT ?", (limit,))


def _thesis_status(row: dict) -> str:
    """Where the position sits against its thesis, from stored numbers only.

    Reports what the DB says. It never decides an exit: the engine owns exits
    through its native stop/target and the RiskGate.
    """
    if not row.get("direction"):
        return "no thesis"
    # unrealized_pnl plus entry gives the mark without needing a live quote.
    try:
        qty = float(row.get("qty") or 0)
        entry = float(row.get("avg_price") or 0)
        pnl = float(row.get("unrealized_pnl") or 0)
        mark = entry + pnl / qty if qty else entry
    except (TypeError, ValueError, ZeroDivisionError):
        return "unknown"
    target = row.get("target")
    invalid = row.get("invalidation_price")
    if target and mark >= float(target):
        return "target reached"
    if invalid and mark <= float(invalid):
        return "invalidated"
    return "on thesis"


def longterm_positions() -> list[dict]:
    """Open research_satellite positions joined to their persisted thesis.

    Each row carries the position (entry date, current PnL) plus the thesis the
    engine holds it on: direction, conviction, target, horizon, and the
    invalidation condition. A position whose thesis predates the long-term
    strategy has NULL target/invalidation, which the GUI shows as absent rather
    than inventing a value.
    """
    rows = query(
        "SELECT p.venue, p.symbol, p.category, p.side, p.qty, p.avg_price, "
        "p.notional, p.opened_ts, p.unrealized_pnl, "
        "t.ts AS thesis_ts, t.direction, t.conviction, t.horizon, t.rationale, "
        "t.status AS thesis_status, t.target, t.invalidation_price, "
        "t.invalidation, t.entry_price "
        "FROM positions p LEFT JOIN research_thesis t "
        "  ON t.symbol = p.symbol AND t.status = 'open' "
        "WHERE COALESCE(p.sleeve,'quant_core') = 'research_satellite' "
        "ORDER BY p.symbol")
    for r in rows:
        r["status_vs_thesis"] = _thesis_status(r)
    return rows


def orders(mode: str, limit: int = 50,
           category: str | None = None) -> list[dict]:
    mode = valid_mode(mode)
    category = valid_category(category)
    fetch = limit if category is None else max(limit, 1000)
    rows = query(
        "SELECT id, ts, venue, symbol, side, qty, price, notional, mode, "
        "outcome, pnl FROM trades WHERE mode = ? ORDER BY id DESC LIMIT ?",
        (mode, fetch))
    rows = [r for r in rows if _in_category(r["symbol"], category)]
    return rows[:limit]


def closed_trades(mode: str, limit: int = 200,
                  category: str | None = None) -> list[dict]:
    mode = valid_mode(mode)
    category = valid_category(category)
    fetch = limit if category is None else max(limit, 1000)
    rows = query(
        "SELECT id, ts, venue, symbol, side, qty, price, notional, pnl, "
        "outcome, combined_conf, combined_edge FROM trades "
        "WHERE mode = ? AND outcome IN ('win','loss') "
        "ORDER BY id DESC LIMIT ?", (mode, fetch))
    rows = [r for r in rows if _in_category(r["symbol"], category)]
    return rows[:limit]


# --- PnL / equity -----------------------------------------------------------

def _balance_venues() -> list[str]:
    return [r["venue"]
            for r in query("SELECT DISTINCT venue FROM account_balances")]


def _equity_curve(mode: str) -> list[dict]:
    live = _live_venues()
    if mode == PAPER:
        agg = query("SELECT ts, equity FROM account_balances "
                    "WHERE venue = 'AGGREGATE' ORDER BY ts")
        if agg:
            return agg
    venues = [v for v in _balance_venues()
              if v != "AGGREGATE" and (v in live) == (mode == LIVE)]
    if not venues:
        return []
    series: dict[str, float] = {}
    for v in venues:
        for r in query("SELECT ts, equity FROM account_balances "
                       "WHERE venue = ? ORDER BY ts", (v,)):
            series[r["ts"]] = series.get(r["ts"], 0.0) + float(r.get("equity") or 0.0)
    return [{"ts": ts, "equity": round(e, 4)}
            for ts, e in sorted(series.items())]


def pnl(mode: str) -> dict:
    mode = valid_mode(mode)
    curve = _equity_curve(mode)
    closed = closed_trades(mode, 5000)
    daily: dict[str, float] = {}
    for t in closed:
        day = (t.get("ts") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + float(t.get("pnl") or 0.0)
    daily_list = [{"day": d, "pnl": round(v, 4)}
                  for d, v in sorted(daily.items())]
    wins = sum(1 for t in closed if t.get("outcome") == "win")
    losses = sum(1 for t in closed if t.get("outcome") == "loss")
    decided = wins + losses
    win_rate = round(wins / decided * 100.0, 2) if decided else 0.0
    total_pl = round(sum(float(t.get("pnl") or 0.0) for t in closed), 4)
    eq = [float(r["equity"]) for r in curve if r.get("equity") is not None]
    latest = eq[-1] if eq else 0.0
    first = eq[0] if eq else 0.0
    change = round(latest - first, 4)
    change_pct = round(change / first * 100.0, 4) if first else 0.0
    mdd, peak = 0.0, None
    for v in eq:
        peak = v if peak is None else max(peak, v)
        if peak:
            mdd = min(mdd, (v / peak - 1.0) * 100.0)
    return {"mode": mode, "equity_curve": curve, "daily_pnl": daily_list,
            "win_rate": win_rate, "wins": wins, "losses": losses,
            "n_trades": len(closed), "total_pnl": total_pl,
            "equity": round(latest, 2), "equity_change": change,
            "equity_change_pct": change_pct,
            "max_drawdown_pct": round(mdd, 2)}


# --- Signals / regime -------------------------------------------------------

def regimes() -> list[dict]:
    return query("SELECT symbol, regime, adx, rvol, updated_ts "
                 "FROM regime_state ORDER BY symbol")


def signals(limit: int = 100, category: str | None = None) -> dict:
    category = valid_category(category)
    fetch = limit if category is None else max(limit, 1000)
    rows = query(
        "SELECT ts, venue, symbol, factor, bias, confidence, edge "
        "FROM signals ORDER BY id DESC LIMIT ?", (fetch,))
    rows = [r for r in rows if _in_category(r["symbol"], category)][:limit]
    reg = {r["symbol"]: r for r in regimes()
           if _in_category(r["symbol"], category)}
    for r in rows:
        rr = reg.get(r.get("symbol"))
        r["regime"] = rr["regime"] if rr else None
    return {"signals": rows, "regimes": list(reg.values())}


# --- Council ----------------------------------------------------------------

def council() -> dict:
    latest = query(
        "SELECT m.model, m.verdict, m.confidence, m.edge, m.weight, m.ts "
        "FROM model_outputs m JOIN (SELECT model, MAX(id) AS mid "
        "FROM model_outputs GROUP BY model) l ON m.id = l.mid "
        "ORDER BY m.weight DESC")
    recent = query(
        "SELECT ts, model, verdict, confidence, edge, weight "
        "FROM model_outputs ORDER BY id DESC LIMIT 40")
    return {"models": llm_models(), "latest": latest, "recent": recent}


# --- Whale ------------------------------------------------------------------

def whale_feeds() -> dict:
    """Read-only state of BOTH whale sources for the Ops section.

    SEC EDGAR (equities, free, keyless, delayed) and Whale Alert (crypto, keyed,
    opt-in trial) are the two feeds that can be live, so they are reported side
    by side: which is on, which is off on purpose, and which one a signal could
    have come from.

    HONEST ABOUT THE ACTIVITY COUNT. `whale_activity` holds RAW per-fetch rows
    and is empty in practice (0 rows), because the engine asks the bridge for a
    SCORED signal and never persists the underlying activity. So the count here
    is whale FACTOR signals from the `signals` table. That is real data, but it
    means something narrower than "Whale Alert fetches":

      * it counts SIGNALS, not fetches, and
      * it is not attributed to a source, because the whale layer combines SEC
        EDGAR and Whale Alert into one 0.35-capped factor and records one score,
      * so a signal here may have come from either feed, or from the offline C++
        mock when the engine runs without the bridge.

    Reporting it as "last successful Whale Alert fetch" would be a fabrication.
    The question "does Whale Alert actually work" is answered by the health check
    (GET /health/integrations), which makes one real call and times it. This
    panel answers "is it on, and is the whale layer producing anything".

    Never returns a key value: it reports whether one RESOLVES, never what it is.
    """
    cfg = load_config().get("whale", {}) or {}
    from api_server.health import whale_alert_enabled  # lazy: health imports store

    try:
        from account_manager.credentials import resolve_env
        keyed = bool(resolve_env("WHALE_ALERT_API_KEY"))
    except Exception:  # noqa: BLE001
        keyed = False

    row = query_one(
        "SELECT ts FROM signals WHERE factor='whale_signal' "
        "ORDER BY id DESC LIMIT 1")
    recent = query_one(
        "SELECT COUNT(*) AS n FROM signals WHERE factor='whale_signal' "
        "AND ts >= datetime('now','-1 day')")
    total = query_one(
        "SELECT COUNT(*) AS n FROM signals WHERE factor='whale_signal'")

    return {
        "sec_edgar": {
            "enabled": bool(cfg.get("sec_edgar_enabled", False)),
            "label": "SEC EDGAR 13F + Form 4",
            "detail": ("equities, free, keyless, delayed (13F about 45 days, "
                       "Form 4 about 2 business days)"),
            "needs_key": False,
        },
        "whale_alert": {
            "enabled": whale_alert_enabled(),
            "keyed": keyed,
            "label": "Whale Alert (crypto trial)",
            "detail": ("crypto on-chain, keyed, opt-in trial, developer plan "
                       "10 calls/minute"),
            "needs_key": True,
        },
        # The whale FACTOR's output, across both feeds. See the docstring: this is
        # not a per-source fetch count and must not be labelled as one.
        "signal_activity": {
            "last_ts": (row or {}).get("ts"),
            "last_24h": int((recent or {}).get("n") or 0),
            "total": int((total or {}).get("n") or 0),
            "note": ("whale factor signals, combined across both feeds and the "
                     "offline mock. Raw per-fetch rows are not persisted."),
        },
    }


def whale() -> dict:
    activity = query(
        "SELECT ts, source, delayed, entity, symbol, direction, value_usd "
        "FROM whale_activity ORDER BY id DESC LIMIT 100")
    history = query(
        "SELECT ts, symbol, whale_bias, whale_confidence, "
        "whale_flow_direction, whale_activity_score, whale_follow_signal, "
        "whale_contradiction_flag, whale_regime_label, agreed_with_trade, "
        "trade_outcome FROM whale_signal_history ORDER BY id DESC LIMIT 100")
    return {"activity": activity, "history": history}


# --- Risk / venues / approval -----------------------------------------------

def risk_state() -> dict:
    risk = load_config().get("risk", {}) or {}
    vs = venue_state()
    tripped = any(r.get("kill_switch_tripped") for r in vs)
    return {"level1": risk,
            "kill_switch_enabled": bool(risk.get("kill_switch_enabled", True)),
            "kill_switch_tripped": tripped, "venues": vs}


def venues_status() -> list[dict]:
    cfg = load_config().get("venues", {}) or {}
    vs = {r["venue"]: r for r in venue_state()}
    configured: dict[str, bool] = {}
    try:
        from account_manager import credentials as creds
        for c in creds.list_status():
            if c.get("kind") == "venue":
                configured[c["group"]] = configured.get(c["group"], False) or c["configured"]
    except Exception:
        pass
    out = []
    for name, vcfg in cfg.items():
        st = vs.get(name, {})
        out.append({
            "venue": name,
            "mode": vcfg.get("mode"),
            "live_enabled": bool(vcfg.get("live_enabled")),
            "live_adapter": vcfg.get("live_adapter"),
            "runtime_mode": st.get("mode"),
            "credentials_connected": bool(st.get("credentials_connected")),
            "kill_switch_tripped": bool(st.get("kill_switch_tripped")),
            "configured": configured.get(name, False),
        })
    return out


def approval() -> dict:
    ap = query_one("SELECT live_enabled, manual_confirmation, "
                   "last_checked_ts, readiness_json FROM approval_state "
                   "WHERE id = 1") or {}
    vs = venue_state()
    live_venue = next((r for r in vs if r["venue"] == "ibkr"),
                      vs[0] if vs else {})
    creds_ok = bool(live_venue.get("credentials_connected"))
    kill = bool(live_venue.get("kill_switch_tripped"))
    live_enabled = bool(ap.get("live_enabled"))
    manual = bool(ap.get("manual_confirmation"))
    mechanisms = [
        {"name": "Live approval gate passed", "key": "approval_gate",
         "passed": manual,
         "detail": "operator recorded a manual approval confirmation"},
        {"name": "Live credentials connected", "key": "credentials_connected",
         "passed": creds_ok,
         "detail": "live credentials resolve for the live venue"},
        {"name": "Kill switch clear", "key": "kill_switch",
         "passed": (not kill), "detail": "kill switch is not tripped"},
        {"name": "Live-enabled flag set", "key": "live_enabled",
         "passed": live_enabled,
         "detail": "the mode router refuses live orders unless this is set"},
    ]
    readiness = ap.get("readiness_json")
    try:
        readiness = json.loads(readiness) if readiness else None
    except Exception:
        pass
    return {"live_enabled": live_enabled, "manual_confirmation": manual,
            "last_checked_ts": ap.get("last_checked_ts"),
            "mechanisms": mechanisms, "readiness": readiness,
            "all_passed": all(m["passed"] for m in mechanisms),
            "live_venue": live_venue.get("venue")}


# --- Events / health --------------------------------------------------------

def events(limit: int = 50) -> list[dict]:
    return query(
        "SELECT ts, kind, venue, symbol, severity, message "
        "FROM events ORDER BY id DESC LIMIT ?", (limit,))


def bridge_health() -> dict:
    url = _bridge_url().rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=0.8) as resp:  # noqa: S310
            ok = resp.status == 200
            body = json.loads(resp.read() or b"{}")
        return {"reachable": ok, "url": _bridge_url(),
                "status": body.get("status")}
    except Exception:
        return {"reachable": False, "url": _bridge_url(), "status": None}


def health() -> dict:
    present = db_exists()
    last = query_one("SELECT ts FROM events ORDER BY id DESC LIMIT 1")
    vs = venue_state()
    kill = any(r.get("kill_switch_tripped") for r in vs)
    return {"status": "ok", "db_present": present,
            "engine": {"db_present": present,
                       "last_event_ts": last["ts"] if last else None,
                       "kill_switch_tripped": kill,
                       "running": present and last is not None},
            "bridge": bridge_health()}


def stream_snapshot(mode: str) -> dict:
    mode = valid_mode(mode)
    return {"mode": mode, "ts": _now(),
            "positions": positions(mode), "orders": orders(mode, 20),
            "pnl": pnl(mode), "events": events(15)}


# --- Kill switch: operator halt request (control file, not an op table) -----
# The engine trips its own kill switch on risk breaches and reflects that in
# venue_state.kill_switch_tripped (read below). The operator can also record a
# durable HALT REQUEST here. This writes a control file next to the keystore,
# never an operational table and never the RiskGate. The C++ engine consumes
# this file at the top of every loop iteration and trips the same latching kill
# switch (see core/engine.cpp consume_operator_kill_request), then archives it
# to kill_request.processed.json so a stale request cannot re-trip on restart.

_DEFAULT_CONTROL = os.path.join(_REPO_ROOT, ".control")


def _control_dir() -> str:
    return os.environ.get("MAL_CONTROL_DIR", _DEFAULT_CONTROL)


def _kill_request_path() -> str:
    return os.path.join(_control_dir(), "kill_request.json")


def read_kill_request() -> dict:
    try:
        with open(_kill_request_path()) as fh:
            return json.load(fh)
    except Exception:
        return {"requested": False, "reason": None, "ts": None}


def write_kill_request(requested: bool, reason: str | None) -> dict:
    os.makedirs(_control_dir(), exist_ok=True)
    rec = {"requested": bool(requested), "reason": reason, "ts": _now()}
    with open(_kill_request_path(), "w") as fh:
        json.dump(rec, fh, indent=2)
    return rec


def kill_state() -> dict:
    vs = venue_state()
    tripped = any(r.get("kill_switch_tripped") for r in vs)
    return {"engine_kill_switch_tripped": tripped,
            "request": read_kill_request()}


# --- Audit write (append-only events log) -----------------------------------
# The ONLY additional write path beyond the credential keystore and the control
# files: an append to the append-only `events` audit table, used by the Controls
# endpoints to record each operator change with old/new values. This mirrors
# ui/db.append_event. It NEVER writes an operational STATE table, a Level-1 risk
# value, or the RiskGate. The DB path is resolved fresh from env each call.

def append_event(kind: str, message: str, severity: str = "info",
                 venue: str | None = None, symbol: str | None = None,
                 payload_json: str | None = None) -> bool:
    try:
        with sqlite3.connect(_db_path(), timeout=2.0) as conn:
            conn.execute(
                "INSERT INTO events(ts, kind, venue, symbol, severity, message, "
                "payload_json) VALUES(?,?,?,?,?,?,?)",
                (_now(), kind, venue, symbol, severity, message, payload_json))
            conn.commit()
        return True
    except Exception:
        return False


# --- Operational GUI reads (skip feed, run state, day summary, trade detail) -

_SKIP_KINDS = ("council_skip", "risk_precheck", "market_hours")


def skip_feed(limit: int = 50) -> list[dict]:
    """Recent council skips from the append-only event log. Read-only."""
    rows = query(
        "SELECT ts, kind, venue, symbol, message, payload_json FROM events "
        "WHERE kind IN ('council_skip','risk_precheck','market_hours') "
        "ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        reason = None
        try:
            reason = (json.loads(r.get("payload_json") or "{}") or {}).get("reason")
        except Exception:
            reason = None
        out.append({"ts": r["ts"], "kind": r["kind"], "symbol": r.get("symbol"),
                    "reason": reason or r["kind"], "message": r.get("message")})
    return out


def runstate() -> dict:
    """Current loop mode and posture, from config plus health. Read-only."""
    cfg = load_config()
    sim = cfg.get("simulation", {}) or {}
    llm = cfg.get("llm", {}) or {}
    md = cfg.get("market_data", {}) or {}
    ap = approval()
    bridge = bridge_health()
    use_real = bool(llm.get("use_real_council", False))
    # Prefer the runtime feed/clock from controls.json (the operator toggle the
    # engine reads each iteration) over the static config, so the banner reflects
    # the live loop state. Falls back to config when the control file is absent.
    _feed = sim.get("feed_mode", "flat_random_walk")
    _clock = sim.get("clock_mode", "real")
    try:
        from api_server import controls
        _ctl = controls.read_controls()
        _layers = _ctl.get("layers", {})
        _layer_sources = _ctl.get("layer_sources", {})
        _feed = _ctl.get("feed_mode", _feed)
        _clock = _ctl.get("clock_mode", _clock)
    except Exception:
        _layers = {}
        _layer_sources = {}
    council_mode = "real" if (use_real and bridge.get("reachable")) else "mock"
    return {"feed_mode": _feed,
            "clock_mode": _clock,
            "market_data_source": md.get("source", "mock"),
            "use_real_council": use_real,
            "gate_enabled": bool(llm.get("gate_enabled", True)),
            "council_mode": council_mode,
            "bridge": bridge,
            "live_enabled": bool(ap.get("live_enabled")),
            "layers": _layers,
            "layer_sources": _layer_sources,
            "ts": _now()}


def day_summary() -> dict:
    """Trades today, win rate today, and council calls today vs the budget.
    Estimated spend today is added by the /day_summary route. Read-only."""
    day = _now()[:10]
    closed = query("SELECT outcome FROM trades WHERE substr(ts,1,10)=? "
                   "AND outcome IN ('win','loss')", (day,))
    wins = sum(1 for r in closed if r.get("outcome") == "win")
    losses = sum(1 for r in closed if r.get("outcome") == "loss")
    dec = wins + losses
    total = query_one("SELECT COUNT(*) AS n FROM trades WHERE substr(ts,1,10)=?", (day,))
    calls = query_one("SELECT COUNT(*) AS n FROM model_outputs WHERE model IN "
                      "('llm_primary','llm_secondary','llm_tertiary') "
                      "AND substr(ts,1,10)=?", (day,))
    slot_rows = int(calls["n"]) if calls and calls.get("n") is not None else 0
    cfg = load_config().get("council", {}) or {}
    return {"day": day,
            "trades_today": int(total["n"]) if total and total.get("n") is not None else 0,
            "wins_today": wins, "losses_today": losses,
            "win_rate_today": round(wins / dec * 100.0, 2) if dec else 0.0,
            "council_calls_today": slot_rows // 3,  # three slots per decision
            "council_daily_budget": int(cfg.get("council_daily_budget", 30))}


def trade_detail(trade_id: int) -> dict:
    """Assemble a trade debugging view from trades, signals, model_outputs,
    regime_state, and events. Read-only."""
    t = query_one(
        "SELECT id, ts, venue, symbol, market, category, side, qty, price, "
        "notional, fee, mode, pnl, outcome, combined_conf, combined_edge, "
        "decision_id FROM trades WHERE id = ?", (trade_id,))
    if not t:
        return {"trade": None}
    sym, ts = t.get("symbol"), t.get("ts")
    signals = query(
        "SELECT ts, factor, bias, confidence, edge FROM signals "
        "WHERE symbol = ? AND ts <= ? ORDER BY id DESC LIMIT 12", (sym, ts))
    council = query(
        "SELECT ts, model, verdict, confidence, edge, weight FROM model_outputs "
        "WHERE ts <= ? ORDER BY id DESC LIMIT 10", (ts,))
    reg = query_one("SELECT regime, adx, rvol, updated_ts FROM regime_state "
                    "WHERE symbol = ?", (sym,))
    events_rows = query(
        "SELECT ts, kind, severity, message, payload_json FROM events "
        "WHERE symbol = ? ORDER BY id DESC LIMIT 20", (sym,))
    return {"trade": t, "signals": signals, "council": council,
            "regime": reg, "events": events_rows}
