"""Per-provider council persistence, keyed for replay.

Before 2026-07-20 only composed aggregates survived an evaluation, so no
historical read could ever be replayed against a changed prompt. This module
records, per evaluation: the full input state (including the gathered evidence
block), the exact system and user prompts sent, the template version, the
composed result, and one row per provider with direction, conviction,
abstention, and the written rationale.

Replay: load_evaluation returns the stored state, replay_prompt re-renders it
under the CURRENT templates. Comparing the stored prompts against the re-render
is the A/B harness: same state, two templates, no live trading required.

Ownership: these are Python-owned tables like the discovery_* set. The C++
engine never reads or writes them. Writes are fail-safe: any error is swallowed
and the council result is returned regardless, because record-keeping must
never break a verdict. Writes happen only when the caller passed an explicit
db path, so unit tests stay hermetic.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from .verdicts import is_error, is_exhausted
from datetime import datetime, timezone

log = logging.getLogger("llm_consensus")

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS council_eval (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        mode TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        state_json TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        user_prompt TEXT NOT NULL,
        bias REAL, confidence REAL, edge REAL, verdict TEXT,
        agreement_count INTEGER, directional_count INTEGER,
        abstentions INTEGER, gate_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS council_eval_provider (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        eval_id INTEGER NOT NULL,
        slot TEXT, model_id TEXT, source TEXT,
        direction TEXT, bias REAL, confidence REAL, edge REAL,
        abstained INTEGER, rationale TEXT, extra_json TEXT)""",
    # Every round the pre-call evidence check REFUSED (2026-07-25). A separate
    # table rather than a council_eval row, because the two records answer two
    # questions: council_eval is "what did the council say", this is "what did
    # we decline to ask, and why". No prompt was rendered and no provider was
    # contacted, so there is nothing to replay and no verdict to store.
    """CREATE TABLE IF NOT EXISTS council_refusal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        symbol TEXT NOT NULL,
        mode TEXT NOT NULL,
        reason TEXT NOT NULL,
        detail TEXT,
        state_json TEXT NOT NULL)""",
)

# Added after the tables shipped, so an existing database keeps every row.
# NO DEFAULT on either column: NULL keeps its only honest meaning, which is
# "written before this distinction existed". A historical row must not start
# claiming its abstentions were verified reads (2026-07-25).
_MIGRATIONS = (
    ("council_eval", "errors",
     "ALTER TABLE council_eval ADD COLUMN errors INTEGER"),
    ("council_eval_provider", "errored",
     "ALTER TABLE council_eval_provider ADD COLUMN errored INTEGER"),
    # Provider exhaustion (2026-07-27), same no-default rule for the same
    # reason: a row written before the distinction existed cannot know whether
    # its failures were a dry account, and NULL says exactly that.
    ("council_eval", "exhausted",
     "ALTER TABLE council_eval ADD COLUMN exhausted INTEGER"),
    ("council_eval_provider", "exhausted",
     "ALTER TABLE council_eval_provider ADD COLUMN exhausted INTEGER"),
)


def _migrate(conn) -> None:
    """Add the columns an older database is missing. Idempotent and silent."""
    for table, column, ddl in _MIGRATIONS:
        try:
            cols = {r[1] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(ddl)
        except Exception:  # noqa: BLE001 - record-keeping never breaks a verdict
            pass


def _direction_of(bias: float) -> str:
    if bias > 1e-9:
        return "long"
    if bias < -1e-9:
        return "short"
    return "flat"


def record_evaluation(db_path: str, state: dict, result,
                      cfg_path: str | None = None) -> int | None:
    """Persist one scored council evaluation. Returns the eval id or None.

    Never raises. Records only rounds that actually scored providers
    (result.per_model non-empty), because a short-circuit has nothing to
    replay.
    """
    per_model = list(getattr(result, "per_model", None) or [])
    if not per_model:
        return None
    try:
        from .evidence import _resolve_db, render_user_prompt
        from .prompts import PROMPT_VERSION, prompt_mode, system_prompt_for
        path = _resolve_db(db_path)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(path, timeout=5.0)
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            _migrate(conn)
            cur = conn.execute(
                "INSERT INTO council_eval (ts, symbol, mode, prompt_version, "
                "state_json, system_prompt, user_prompt, bias, confidence, "
                "edge, verdict, agreement_count, directional_count, "
                "abstentions, errors, exhausted, gate_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, str(state.get("symbol", "?")), prompt_mode(state),
                 PROMPT_VERSION, json.dumps(state, default=str),
                 system_prompt_for(state, cfg_path), render_user_prompt(state),
                 float(result.bias), float(result.confidence),
                 float(result.edge), str(result.verdict),
                 int(result.agreement_count),
                 int(getattr(result, "directional_count", 0)),
                 int(getattr(result, "abstentions", 0)),
                 int(getattr(result, "errors", 0)),
                 int(getattr(result, "exhausted", 0)),
                 json.dumps(getattr(result, "gate", None))))
            eval_id = int(cur.lastrowid)
            for v in per_model:
                bias = float(getattr(v, "bias", 0.0))
                # A FAILED CALL IS NOT AN ABSTENTION (2026-07-25). `abstained`
                # used to be derived from the bias alone, so an errored row and
                # a considered hold read identically and only `source` told
                # them apart. It now means "answered, and held".
                #
                # AND AN EXHAUSTED ACCOUNT IS NOT A FAILED CALL (2026-07-27).
                # The three flags are DISJOINT: a row is at most one of
                # abstained, errored, exhausted, so counting any one of them
                # never double-counts another.
                exhausted = is_exhausted(v)
                errored = is_error(v) and not exhausted
                abstained = (not errored) and (not exhausted) and abs(bias) <= 1e-9
                conn.execute(
                    "INSERT INTO council_eval_provider (eval_id, slot, "
                    "model_id, source, direction, bias, confidence, edge, "
                    "abstained, errored, exhausted, rationale, extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eval_id, str(getattr(v, "model", "")),
                     str(getattr(v, "model_id", "")),
                     str(getattr(v, "source", "")),
                     _direction_of(bias), bias,
                     float(getattr(v, "confidence", 0.0)),
                     float(getattr(v, "edge", 0.0)),
                     1 if abstained else 0,
                     1 if errored else 0,
                     1 if exhausted else 0,
                     str(getattr(v, "rationale", ""))[:1000],
                     json.dumps(getattr(v, "extra", {}) or {})))
            conn.commit()
            return eval_id
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - record-keeping never breaks a verdict
        log.warning("council persistence failed: %s", type(e).__name__)
        return None


def record_refusal(db_path: str, state: dict, refusal,
                   cfg_path: str | None = None) -> int | None:
    """Persist one round the evidence check refused. Returns the id or None.

    Never raises, same posture as record_evaluation: record-keeping must never
    break a verdict, and here it must never break a REFUSAL either, or a
    failing writer would turn a saved call back into a spent one.
    """
    try:
        from .evidence import _resolve_db
        from .prompts import prompt_mode
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(_resolve_db(db_path), timeout=5.0)
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            cur = conn.execute(
                "INSERT INTO council_refusal (ts, symbol, mode, reason, "
                "detail, state_json) VALUES (?,?,?,?,?,?)",
                (ts, str(state.get("symbol", "?")), prompt_mode(state),
                 str(getattr(refusal, "reason", "")),
                 str(getattr(refusal, "detail", "")),
                 json.dumps(state, default=str)))
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - record-keeping never breaks a refusal
        log.warning("council refusal persistence failed: %s", type(e).__name__)
        return None


def recent_refusals(db_path: str, limit: int = 50) -> list[dict]:
    """The most recent refusals, newest first, for the operator surfaces."""
    try:
        from .evidence import _resolve_db
        conn = sqlite3.connect(f"file:{_resolve_db(db_path)}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, ts, symbol, mode, reason, detail FROM "
                "council_refusal ORDER BY id DESC LIMIT ?",
                (int(limit),)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - a missing table reads as no refusals
        return []
    return [{"id": r[0], "ts": r[1], "symbol": r[2], "mode": r[3],
             "reason": r[4], "detail": r[5]} for r in rows]


def load_evaluation(db_path: str, eval_id: int) -> dict | None:
    """The stored evaluation: state, prompts, composed result, provider rows."""
    try:
        from .evidence import _resolve_db
        conn = sqlite3.connect(f"file:{_resolve_db(db_path)}?mode=ro", uri=True)
        try:
            # The read is opened READ-ONLY, so it cannot migrate. A database
            # written before the split simply lacks the columns, and the query
            # is built to match what is actually there rather than assuming.
            def has(table: str, column: str) -> bool:
                return any(r[1] == column for r in conn.execute(
                    f"PRAGMA table_info({table})").fetchall())

            # COALESCE, not a DEFAULT on the column: a row written before the
            # split genuinely does not know how many of its "abstentions" were
            # failed calls, and 0 reads as "none recorded", the honest answer.
            errors_expr = ("COALESCE(errors, 0)" if has("council_eval", "errors")
                           else "0")
            # Fall back to the source string for a pre-migration provider row,
            # which is exactly how the 17 historical errors stayed identifiable.
            errored_expr = (
                "COALESCE(errored, CASE WHEN source='error' THEN 1 ELSE 0 END)"
                if has("council_eval_provider", "errored")
                else "CASE WHEN source='error' THEN 1 ELSE 0 END")
            # A pre-2026-07-27 row has no exhaustion column and no way to know
            # it, so it reads 0 rather than guessing from the source string.
            eval_exh_expr = ("COALESCE(exhausted, 0)"
                             if has("council_eval", "exhausted") else "0")
            prov_exh_expr = (
                "COALESCE(exhausted, CASE WHEN source='exhausted' THEN 1 "
                "ELSE 0 END)" if has("council_eval_provider", "exhausted")
                else "CASE WHEN source='exhausted' THEN 1 ELSE 0 END")
            row = conn.execute(
                "SELECT ts, symbol, mode, prompt_version, state_json, "
                "system_prompt, user_prompt, bias, confidence, edge, verdict, "
                "agreement_count, directional_count, abstentions, "
                f"{errors_expr}, {eval_exh_expr} FROM council_eval WHERE id=?",
                (eval_id,)).fetchone()
            if not row:
                return None
            providers = conn.execute(
                "SELECT slot, model_id, source, direction, bias, confidence, "
                f"edge, abstained, rationale, extra_json, {errored_expr}, "
                f"{prov_exh_expr} "
                "FROM council_eval_provider WHERE eval_id=? ORDER BY id",
                (eval_id,)).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None
    return {
        "id": eval_id, "ts": row[0], "symbol": row[1], "mode": row[2],
        "prompt_version": row[3], "state": json.loads(row[4]),
        "system_prompt": row[5], "user_prompt": row[6],
        "bias": row[7], "confidence": row[8], "edge": row[9],
        "verdict": row[10], "agreement_count": row[11],
        "directional_count": row[12], "abstentions": row[13],
        "errors": row[14],
        "exhausted": row[15],
        # How many providers actually answered, so a two-handed round reads as
        # one without the caller doing arithmetic.
        "responded_count": (row[12] or 0) + (row[13] or 0),
        "providers": [{
            "slot": p[0], "model_id": p[1], "source": p[2], "direction": p[3],
            "bias": p[4], "confidence": p[5], "edge": p[6],
            # abstained means ANSWERED AND HELD. errored means the call failed.
            # exhausted means the account is out of quota, so no call was made
            # or the one made could never have succeeded. The three are
            # DISJOINT. A pre-migration row derives them from source rather
            # than claiming a failed call was a considered read.
            "abstained": bool(p[7]) and not bool(p[10]) and not bool(p[11]),
            "errored": bool(p[10]) and not bool(p[11]),
            "exhausted": bool(p[11]),
            "rationale": p[8],
            "extra": json.loads(p[9] or "{}"),
        } for p in providers],
    }


def replay_prompt(stored: dict, cfg_path: str | None = None) -> tuple[str, str]:
    """Re-render a stored evaluation's state under the CURRENT templates.

    Returns (system_prompt, user_prompt). Comparing these against the stored
    prompts measures exactly what a template change would have sent for that
    historical evaluation, with no provider call and no trading.
    """
    from .evidence import render_user_prompt
    from .prompts import system_prompt_for
    state = dict(stored.get("state") or {})
    return system_prompt_for(state, cfg_path), render_user_prompt(state)
