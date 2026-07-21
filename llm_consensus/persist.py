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
)


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
            cur = conn.execute(
                "INSERT INTO council_eval (ts, symbol, mode, prompt_version, "
                "state_json, system_prompt, user_prompt, bias, confidence, "
                "edge, verdict, agreement_count, directional_count, "
                "abstentions, gate_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, str(state.get("symbol", "?")), prompt_mode(state),
                 PROMPT_VERSION, json.dumps(state, default=str),
                 system_prompt_for(state, cfg_path), render_user_prompt(state),
                 float(result.bias), float(result.confidence),
                 float(result.edge), str(result.verdict),
                 int(result.agreement_count),
                 int(getattr(result, "directional_count", 0)),
                 int(getattr(result, "abstentions", 0)),
                 json.dumps(getattr(result, "gate", None))))
            eval_id = int(cur.lastrowid)
            for v in per_model:
                bias = float(getattr(v, "bias", 0.0))
                conn.execute(
                    "INSERT INTO council_eval_provider (eval_id, slot, "
                    "model_id, source, direction, bias, confidence, edge, "
                    "abstained, rationale, extra_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (eval_id, str(getattr(v, "model", "")),
                     str(getattr(v, "model_id", "")),
                     str(getattr(v, "source", "")),
                     _direction_of(bias), bias,
                     float(getattr(v, "confidence", 0.0)),
                     float(getattr(v, "edge", 0.0)),
                     1 if abs(bias) <= 1e-9 else 0,
                     str(getattr(v, "rationale", ""))[:1000],
                     json.dumps(getattr(v, "extra", {}) or {})))
            conn.commit()
            return eval_id
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - record-keeping never breaks a verdict
        log.warning("council persistence failed: %s", type(e).__name__)
        return None


def load_evaluation(db_path: str, eval_id: int) -> dict | None:
    """The stored evaluation: state, prompts, composed result, provider rows."""
    try:
        from .evidence import _resolve_db
        conn = sqlite3.connect(f"file:{_resolve_db(db_path)}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT ts, symbol, mode, prompt_version, state_json, "
                "system_prompt, user_prompt, bias, confidence, edge, verdict, "
                "agreement_count, directional_count, abstentions "
                "FROM council_eval WHERE id=?", (eval_id,)).fetchone()
            if not row:
                return None
            providers = conn.execute(
                "SELECT slot, model_id, source, direction, bias, confidence, "
                "edge, abstained, rationale, extra_json "
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
        "providers": [{
            "slot": p[0], "model_id": p[1], "source": p[2], "direction": p[3],
            "bias": p[4], "confidence": p[5], "edge": p[6],
            "abstained": bool(p[7]), "rationale": p[8],
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
