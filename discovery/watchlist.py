"""The dynamic watchlist: a living candidate list both sleeves draw from.

Discovery adds an instrument when it survives to Stage C. The list prunes itself
when a signal goes stale (no pass re-confirmed it inside ``watchlist_stale_hours``)
or when a thesis breaks. It is deliberately small: the universe is the outer edge
of the funnel, the watchlist is the narrow end.

EVENT-SOURCED ON PURPOSE. Every mutation goes through ``apply_event`` with an
explicit source, and each one is journalled to ``watchlist_event``. That was the
bridge the deferred react layer was promised, and the react layer has now taken
it: ``adaptive_react`` adds a producer, not a rewrite.

THREE STATUSES, and the third one carries the safety argument.

  active    tradeable. The engine merges these into its whitelist, so the native
            strategy may evaluate them. Only ``discovery`` can create one, and it
            only does so for a Stage-C survivor.
  referred  NOT tradeable. Invisible to the engine. A candidate the adaptive
            layer noticed and offered to the funnel. It becomes active only if a
            later discovery pass ranks it through Stage A, gates it through Stage
            B, and evaluates it through the four levels.
  removed   soft-deleted, kept for history.

That split is what makes "aggressive entry always goes through the funnel" true
rather than aspirational. The adaptive layer CANNOT create an active entry: the
status is derived from the SOURCE (see ``_entry_status_for``), never requested by
the caller, so there is no argument a react-layer bug could pass to promote a
symbol straight onto the traded universe. A misread headline buys a screening
slot at most.

Sources are gated, not hardcoded: ``adaptive_react`` is accepted only while
``adaptive_watchlist_shaping_enabled`` is on, which ships FALSE. The flag is read
here rather than accepted as a parameter, so no caller can pass an override that
unlocks the source. See CONTEXT.md.

Writer note: this module owns the discovery tables, following the precedent of
market_data/alpaca_source.py writing ``bars`` and ml_factor/registry.py writing
``model_registry``. The C++ engine remains the sole writer of the OPERATIONAL
trading tables (trades, positions, events). It only READS the watchlist, and only
when discovery is enabled.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Sources always allowed to mutate the watchlist.
ACTIVE_SOURCES = ("discovery", "prune")

# Sources allowed only while their own flag is on. Unlike ACTIVE_SOURCES, these
# are checked against live settings on every event, so turning the flag off stops
# them at once rather than at the next restart.
GATED_SOURCES = ("adaptive_react",)

# Still reserved: parses, journalled, refused. The seam for a later build.
RESERVED_SOURCES = ("manual",)

# Sources whose adds are REFERRALS, never promotions. A referral is not
# tradeable; only a discovery pass can make an entry active. Deriving this from
# the source (not from a parameter) is what makes the rule unbypassable.
REFERRAL_SOURCES = ("adaptive_react",)

VALID_ACTIONS = ("add", "remove")
VALID_SLEEVES = ("quant_core", "research_satellite")

STATUS_ACTIVE = "active"
STATUS_REFERRED = "referred"
STATUS_REMOVED = "removed"


def _shaping_enabled() -> bool:
    """Whether the adaptive layer may shape the watchlist right now.

    Imported lazily to keep discovery independent of the adaptive package at
    import time (adaptive imports discovery for its Finnhub client, so a
    module-level import here would be circular). Any failure reads as DISABLED:
    if we cannot prove the operator turned it on, it is off.
    """
    try:
        from adaptive import settings as adaptive_settings
        return adaptive_settings.watchlist_shaping_enabled()
    except Exception:  # noqa: BLE001 - unprovable means off
        return False


def _source_allowed(source: str) -> bool:
    """Whether `source` may mutate the watchlist. The single authority.

    Takes no override parameter on purpose. A caller cannot pass an allowlist
    that unlocks a gated source; only the operator's flag can.
    """
    if source in ACTIVE_SOURCES:
        return True
    if source in GATED_SOURCES:
        return _shaping_enabled()
    return False


def _entry_status_for(source: str) -> str:
    """The status an ADD from `source` creates. Derived, never requested."""
    return STATUS_REFERRED if source in REFERRAL_SOURCES else STATUS_ACTIVE

SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol         TEXT NOT NULL UNIQUE,
        asset_class    TEXT,
        added_ts       TEXT NOT NULL,
        updated_ts     TEXT NOT NULL,
        source         TEXT NOT NULL,
        reason         TEXT,
        sleeve_target  TEXT DEFAULT 'quant_core',
        score          REAL DEFAULT 0,
        status         TEXT DEFAULT 'active',
        removed_ts     TEXT,
        removed_reason TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status, symbol)",
    """
    CREATE TABLE IF NOT EXISTS watchlist_event (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        action  TEXT NOT NULL,
        symbol  TEXT NOT NULL,
        source  TEXT NOT NULL,
        reason  TEXT,
        applied INTEGER DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_watchlist_event_ts ON watchlist_event(ts)",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the watchlist tables if absent. Idempotent."""
    for ddl in SCHEMA_DDL:
        conn.execute(ddl)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class WatchlistEvent:
    """One requested mutation. The only way the list ever changes."""
    action: str
    symbol: str
    source: str
    reason: str = ""
    sleeve_target: str = "quant_core"
    score: float = 0.0
    asset_class: str = ""
    ts: str = ""


def _journal(conn: sqlite3.Connection, ev: WatchlistEvent, ts: str,
             applied: bool) -> None:
    conn.execute(
        "INSERT INTO watchlist_event(ts,action,symbol,source,reason,applied) "
        "VALUES(?,?,?,?,?,?)",
        (ts, ev.action, ev.symbol, ev.source, ev.reason, 1 if applied else 0))


def apply_event(conn: sqlite3.Connection, ev: WatchlistEvent) -> dict:
    """Apply one watchlist event. The single mutation path.

    Returns {"applied": bool, "reason": str}. Every event is journalled whether
    or not it applied, so a refused event from a not-yet-enabled source is
    visible rather than silent.
    """
    ensure_schema(conn)
    ts = ev.ts or _utcnow_iso()

    if ev.action not in VALID_ACTIONS:
        _journal(conn, ev, ts, False)
        return {"applied": False, "reason": "invalid_action"}
    if not ev.symbol:
        _journal(conn, ev, ts, False)
        return {"applied": False, "reason": "no_symbol"}
    if not _source_allowed(ev.source):
        # Refused, but still parsed and still journalled, so a refusal is
        # visible in the audit trail rather than silent.
        _journal(conn, ev, ts, False)
        reason = ("source_not_enabled"
                  if ev.source in RESERVED_SOURCES + GATED_SOURCES
                  else "unknown_source")
        return {"applied": False, "reason": reason}

    if ev.action == "add":
        sleeve = (ev.sleeve_target if ev.sleeve_target in VALID_SLEEVES
                  else "quant_core")
        status = _entry_status_for(ev.source)

        if status == STATUS_REFERRED:
            # A REFERRAL. Insert as not-tradeable if the symbol is new, and if it
            # already exists do NOT touch its status, source, or sleeve. Two
            # reasons: referring a symbol discovery already promoted must not
            # demote it back out of the traded universe, and a referral must
            # never be able to overwrite what the funnel concluded. It refreshes
            # the timestamp and the reason so the entry stays visibly alive.
            conn.execute(
                "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,"
                "source,reason,sleeve_target,score,status,removed_ts,"
                "removed_reason) VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL) "
                "ON CONFLICT(symbol) DO UPDATE SET "
                "updated_ts=excluded.updated_ts, reason=excluded.reason",
                (ev.symbol, ev.asset_class, ts, ts, ev.source, ev.reason,
                 sleeve, float(ev.score or 0.0), STATUS_REFERRED))
            _journal(conn, ev, ts, True)
            return {"applied": True, "reason": "referred"}

        # Re-adding an existing symbol REFRESHES it (updated_ts, reason, score),
        # which is exactly what keeps a live candidate from being pruned as
        # stale. added_ts is preserved, so "when did this first appear" survives.
        # A discovery add also PROMOTES a referred entry to active: that is the
        # funnel confirming a candidate the adaptive layer only offered.
        conn.execute(
            "INSERT INTO watchlist(symbol,asset_class,added_ts,updated_ts,source,"
            "reason,sleeve_target,score,status,removed_ts,removed_reason) "
            "VALUES(?,?,?,?,?,?,?,?,'active',NULL,NULL) "
            "ON CONFLICT(symbol) DO UPDATE SET "
            "updated_ts=excluded.updated_ts, source=excluded.source, "
            "reason=excluded.reason, sleeve_target=excluded.sleeve_target, "
            "score=excluded.score, status='active', removed_ts=NULL, "
            "removed_reason=NULL, asset_class=excluded.asset_class",
            (ev.symbol, ev.asset_class, ts, ts, ev.source, ev.reason, sleeve,
             float(ev.score or 0.0)))
        _journal(conn, ev, ts, True)
        return {"applied": True, "reason": "added"}

    # remove: soft delete. The row stays so the operator can see what left and
    # why, and so a re-add restores it rather than losing its history. Removing
    # covers referred entries too: dropping a candidate nobody promoted is the
    # cheapest possible action and must not need a promotion first.
    cur = conn.execute(
        "UPDATE watchlist SET status='removed', removed_ts=?, removed_reason=?, "
        "updated_ts=? WHERE symbol=? AND status IN (?,?)",
        (ts, ev.reason or "removed", ts, ev.symbol, STATUS_ACTIVE,
         STATUS_REFERRED))
    applied = cur.rowcount > 0
    _journal(conn, ev, ts, applied)
    return {"applied": applied,
            "reason": "removed" if applied else "not_on_watchlist"}


def recent_onboarding_refusals(conn: sqlite3.Connection,
                               within_hours: int = 168) -> set[str]:
    """Symbols whose onboarding was journalled REFUSED within the window.

    Read-only over the event journal (2026-07-23). The funnel spends a full
    Stage-C round BEFORE serviceability is verified, so a venue-unserviceable
    symbol (the ZEC/USD and APT/USD shape) re-surfaced and re-spent on every
    pass after its refusal. Filtering the recently refused OUT of the pass
    input spends nothing on a symbol the venue already proved it cannot
    serve; the window (default 7 days) lets a venue that later lists the
    symbol be retried rather than banned forever. Tolerant: a missing journal
    reads as no refusals.
    """
    ensure_schema(conn)
    try:
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(hours=within_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM watchlist_event "
            "WHERE action='add' AND applied=0 AND ts >= ? "
            "AND reason LIKE 'onboarding refused%'", (cutoff,)).fetchall()
        return {str(r[0]) for r in rows if r and r[0]}
    except sqlite3.Error:
        return set()


def journal_onboarding_refusal(conn: sqlite3.Connection, symbol: str, *,
                               reason: str, ts: str | None = None) -> dict:
    """Journal a REFUSED onboarding without touching the watchlist table.

    Serviceability verification (2026-07-20): a Stage-C survivor whose
    backfill returned nothing is NOT added, because the venue serves no data
    for it and it could only ever sit unavailable (the MANA/USD and RUNE/USD
    shape). The refusal still lands in the event journal, applied=0, so the
    audit trail shows discovery looked, the venue could not serve the symbol,
    and the symbol was not added.
    """
    ensure_schema(conn)
    ev = WatchlistEvent(action="add", symbol=symbol, source="discovery",
                        reason=reason)
    _journal(conn, ev, ts or _utcnow_iso(), False)
    return {"applied": False, "reason": "venue_unserviceable"}


def add_from_discovery(conn: sqlite3.Connection, symbol: str, *, reason: str,
                       sleeve_target: str = "quant_core", score: float = 0.0,
                       asset_class: str = "", ts: str | None = None) -> dict:
    """Add a Stage-C survivor. The only path that makes an entry TRADEABLE.

    A survivor reached here by clearing Stage A, Stage B, and the four levels, so
    this is the funnel's confirmation. It also PROMOTES a symbol the adaptive
    layer merely referred: the referral asked the funnel to look, and this is the
    funnel having looked and agreed.
    """
    return apply_event(conn, WatchlistEvent(
        action="add", symbol=symbol, source="discovery", reason=reason,
        sleeve_target=sleeve_target, score=score, asset_class=asset_class,
        ts=ts or _utcnow_iso()))


def refer_from_adaptive(conn: sqlite3.Connection, symbol: str, *, reason: str,
                        asset_class: str = "",
                        ts: str | None = None) -> dict:
    """Offer a symbol to the funnel. NOT an add to the traded universe.

    This is the strongest thing a live event can do toward BUYING something, and
    it is deliberately weak: the entry lands as ``referred``, the engine never
    sees it, and it becomes tradeable only if a later discovery pass ranks it,
    gates it, and evaluates it. Refused entirely unless the shaping flag is on.
    """
    return apply_event(conn, WatchlistEvent(
        action="add", symbol=symbol, source="adaptive_react", reason=reason,
        asset_class=asset_class, ts=ts or _utcnow_iso()))


def remove_from_adaptive(conn: sqlite3.Connection, symbol: str, *,
                         reason: str, ts: str | None = None) -> dict:
    """Prune one entry on a live event. A safe action: it can only ever shrink
    what the engine looks at, never grow it, and it closes no position."""
    return apply_event(conn, WatchlistEvent(
        action="remove", symbol=symbol, source="adaptive_react", reason=reason,
        ts=ts or _utcnow_iso()))


def referred_symbols(conn: sqlite3.Connection) -> list[str]:
    """Symbols the adaptive layer offered but the funnel has not confirmed.

    discovery/run.py folds these into the next pass's Stage-A input, which is
    what closes the loop: a referral is a request to be screened, and this is
    where the screening picks it up. They are NOT tradeable while they sit here.
    """
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT symbol FROM watchlist WHERE status=? ORDER BY symbol",
        (STATUS_REFERRED,)).fetchall()
    return [r[0] for r in rows if r and r[0]]


def active(conn: sqlite3.Connection) -> list[dict]:
    """Current active watchlist, most recently confirmed first. Read-only."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT symbol, asset_class, added_ts, updated_ts, source, reason, "
        "sleeve_target, score, status FROM watchlist WHERE status='active' "
        "ORDER BY updated_ts DESC, symbol ASC").fetchall()
    return [{"symbol": r[0], "asset_class": r[1], "added_ts": r[2],
             "updated_ts": r[3], "source": r[4], "reason": r[5],
             "sleeve_target": r[6], "score": r[7], "status": r[8]} for r in rows]


def active_symbols(conn: sqlite3.Connection,
                   sleeve_target: str | None = None) -> list[str]:
    """Active symbols, optionally for one sleeve. What the engine reads."""
    ensure_schema(conn)
    if sleeve_target:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' AND "
            "sleeve_target=? ORDER BY symbol", (sleeve_target,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE status='active' "
            "ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Recent adds and prunes, so the operator sees the list living."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT ts, action, symbol, source, reason, applied FROM watchlist_event "
        "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"ts": r[0], "action": r[1], "symbol": r[2], "source": r[3],
             "reason": r[4], "applied": bool(r[5])} for r in rows]


def stale_symbols(conn: sqlite3.Connection, stale_hours: int,
                  now: datetime | None = None) -> list[str]:
    """Live symbols no pass re-confirmed within ``stale_hours``. Pure read.

    Covers REFERRED entries as well as active ones. A referral the funnel never
    confirms (a symbol outside the configured universe, say) would otherwise sit
    in the table forever: nothing promotes it, so nothing refreshes it, so a
    staleness rule that only looked at active entries would never collect it.
    Referrals expire the same way candidates do.
    """
    ensure_schema(conn)
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max(0, stale_hours))).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT symbol FROM watchlist WHERE status IN (?,?) AND updated_ts < ? "
        "ORDER BY symbol", (STATUS_ACTIVE, STATUS_REFERRED, cutoff)).fetchall()
    return [r[0] for r in rows]


def prune_stale(conn: sqlite3.Connection, stale_hours: int,
                now: datetime | None = None) -> dict:
    """Remove entries whose signal went stale."""
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    pruned = []
    for symbol in stale_symbols(conn, stale_hours, now):
        r = apply_event(conn, WatchlistEvent(
            action="remove", symbol=symbol, source="prune",
            reason=f"signal stale, no pass in {stale_hours}h", ts=ts))
        if r["applied"]:
            pruned.append(symbol)
    return {"pruned": pruned, "count": len(pruned)}


def prune_broken_thesis(conn: sqlite3.Connection, symbol: str,
                        reason: str = "thesis invalidated",
                        ts: str | None = None) -> dict:
    """Remove one entry whose thesis broke."""
    return apply_event(conn, WatchlistEvent(
        action="remove", symbol=symbol, source="prune", reason=reason,
        ts=ts or _utcnow_iso()))


def enforce_max_size(conn: sqlite3.Connection, max_size: int,
                     ts: str | None = None) -> dict:
    """Keep the watchlist bounded: drop the lowest-scoring entries past the cap.

    The watchlist is the NARROW end of the funnel. An unbounded list would defeat
    the point, so the cap is enforced on score, keeping the strongest candidates.
    """
    ensure_schema(conn)
    ts = ts or _utcnow_iso()
    rows = conn.execute(
        "SELECT symbol FROM watchlist WHERE status='active' "
        "ORDER BY score DESC, updated_ts DESC, symbol ASC").fetchall()
    overflow = [r[0] for r in rows[max(0, max_size):]]
    dropped = []
    for symbol in overflow:
        r = apply_event(conn, WatchlistEvent(
            action="remove", symbol=symbol, source="prune",
            reason=f"watchlist full (max {max_size}), lower score", ts=ts))
        if r["applied"]:
            dropped.append(symbol)
    return {"dropped": dropped, "count": len(dropped)}
