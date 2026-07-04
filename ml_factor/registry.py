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


def meets_promotion_criteria(champion_metrics: dict, challenger_metrics: dict,
                             min_real_samples: int = 200) -> tuple[bool, str]:
    """Return (ok, reason) for promoting a REAL-data challenger over the champion.

    Task 5 gate — a real-data challenger may only be promoted when ALL hold:
      1. it was trained on real data (provenance == "real-data"),
      2. it has >= `min_real_samples` real samples,
      3. it beats the champion on walk-forward validation Sharpe, and
      4. its max drawdown is no worse than the champion's.
    Promotion still requires an explicit operator action even when this is True;
    nothing here auto-promotes. Advisory-only layer; the 0.5 sizing cap is
    unchanged regardless of which model serves.
    """
    if challenger_metrics.get("provenance") != "real-data":
        return False, "challenger is not real-data provenance"
    n = int(challenger_metrics.get("n_samples", 0))
    if n < min_real_samples:
        return False, f"only {n} real samples (< {min_real_samples})"
    ch_sharpe = float(challenger_metrics.get("validation_sharpe", 0.0))
    champ_sharpe = float(champion_metrics.get("validation_sharpe", 0.0))
    if ch_sharpe <= champ_sharpe:
        return False, f"sharpe {ch_sharpe} not better than champion {champ_sharpe}"
    ch_dd = float(challenger_metrics.get("max_drawdown", float("inf")))
    champ_dd = float(champion_metrics.get("max_drawdown", float("inf")))
    if ch_dd > champ_dd:
        return False, f"max drawdown {ch_dd} worse than champion {champ_dd}"
    return True, "meets all promotion criteria (still requires explicit promotion)"


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
