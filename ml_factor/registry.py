"""Champion/Challenger model registry + promotion/rollback bookkeeping.

Writes to the shared SQLite `model_registry` table. Promotion is GATED by
default (`dnn_auto_promote_if_better=false`): a better challenger is recorded
but only promoted on an explicit call, matching DNN_RL_DESIGN.md. Rollback
reverts to the prior champion on metric degradation.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def register(conn: sqlite3.Connection, model_id: str, role: str,
             metrics: dict, notes: str = "") -> None:
    conn.execute(
        "INSERT INTO model_registry(ts,model_id,role,metrics_json,notes)"
        " VALUES(?,?,?,?,?)",
        (_now(), model_id, role, json.dumps(metrics), notes),
    )
    conn.commit()


def current_champion(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT model_id FROM model_registry WHERE role='champion'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def evaluate_and_maybe_promote(conn: sqlite3.Connection, champion_metric: float,
                               challenger_id: str, challenger_metric: float,
                               auto_promote: bool) -> dict:
    """Compare challenger vs champion. Promote only if better AND auto_promote.

    Returns a decision dict for the audit log / UI.
    """
    better = challenger_metric > champion_metric
    promoted = bool(better and auto_promote)
    if promoted:
        # Retire old champion, install challenger.
        conn.execute(
            "UPDATE model_registry SET role='retired' WHERE role='champion'"
        )
        register(conn, challenger_id, "champion",
                 {"metric": challenger_metric}, "auto-promoted: better metric")
    else:
        register(conn, challenger_id, "challenger",
                 {"metric": challenger_metric},
                 "evaluated; promotion gated" if better else "not better")
    return {
        "challenger": challenger_id,
        "challenger_metric": challenger_metric,
        "champion_metric": champion_metric,
        "better": better,
        "promoted": promoted,
    }


def rollback(conn: sqlite3.Connection, reason: str) -> str | None:
    """Roll back to the most recent retired model (previous champion)."""
    row = conn.execute(
        "SELECT model_id FROM model_registry WHERE role='retired'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    conn.execute("UPDATE model_registry SET role='retired' WHERE role='champion'")
    register(conn, row[0], "champion", {}, f"rollback: {reason}")
    return row[0]
