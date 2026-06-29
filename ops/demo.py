#!/usr/bin/env python3
"""Market AI Lab — end-to-end offline demo orchestrator.

Runs entirely offline with NO API keys and live trading DISABLED:

  1. (Re)seed the shared SQLite DB by running the compiled C++ engine
     (Polymarket-paper + Alpaca-paper instruments, mock market/news data).
     The engine produces multi-LLM consensus + DNN advisory + rule-based
     factors, blends them, and routes each proposal through the deterministic
     Layer-1 RiskGate before paper execution.
  2. Populate the whale advisory tables (whale_activity + whale_signal_history)
     from the Python whale service so the dashboard's whale panels have data.
     (These adapters are offline mocks unless APIFY_TOKEN / WHALE_ALERT_API_KEY
     / SEC_API_KEY are set; 13F rows are flagged DELAYED.)
  3. Seed a model_registry champion row for the DNN factor.
  4. Launch the Plotly Dash control board (unless --no-dash).

Usage:
  python ops/demo.py [--iterations N] [--no-dash] [--rebuild] [--bridge host:port]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DB_PATH = os.path.join(REPO_ROOT, "market_ai_lab.db")
SCHEMA = os.path.join(REPO_ROOT, "storage", "schema.sql")
CONFIG = os.path.join(REPO_ROOT, "config", "default_config.yaml")
ENGINE = os.path.join(REPO_ROOT, "build", "mal_engine")

# Symbols mirror the engine's paper universe.
WHALE_SYMBOLS = ["BTC-USD", "AAPL", "PRES-2028-YES", "FED-CUT-Q3"]


def _now_iso(offset_min: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_min)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def build_engine(rebuild: bool) -> None:
    build_dir = os.path.join(REPO_ROOT, "build")
    if os.path.exists(ENGINE) and not rebuild:
        return
    print("[demo] building C++ engine ...")
    os.makedirs(build_dir, exist_ok=True)
    subprocess.run(["cmake", "-S", REPO_ROOT, "-B", build_dir],
                   check=True)
    subprocess.run(["cmake", "--build", build_dir, "-j"], check=True)


def run_engine(iterations: int, bridge: str | None) -> None:
    if not os.path.exists(ENGINE):
        print(f"[demo] engine binary not found at {ENGINE}; run with --rebuild")
        sys.exit(1)
    # Fresh DB each demo run so the dashboard shows a clean, coherent story.
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            os.remove(p)
    cmd = [ENGINE, "--config", CONFIG, "--db", DB_PATH, "--schema", SCHEMA,
           "--iterations", str(iterations)]
    if bridge:
        cmd += ["--bridge", bridge]
    print(f"[demo] running paper loop: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def populate_whale_tables() -> None:
    """Fill whale_activity + whale_signal_history via the offline whale service."""
    from whale_signal.service import whale_signal_for

    rows_activity = []
    rows_signal = []
    # A handful of evaluation snapshots so the history charts have a line.
    snapshots = 8
    for snap in range(snapshots):
        ts = _now_iso(offset_min=-(snapshots - snap) * 5)
        for sym in WHALE_SYMBOLS:
            # Bias drifts slightly per snapshot to make the chart non-flat.
            market_bias = 0.15 if "BTC" in sym or "PRES" in sym else -0.05
            sig, acts = whale_signal_for(sym, market_bias=market_bias)
            d = sig.to_dict()
            # agreement vs a synthetic taken-trade direction + outcome
            agreed = 1 if (d["whale_bias"] >= 0) == (market_bias >= 0) else 0
            outcome = "win" if (agreed and d["whale_follow_signal"]) else (
                "loss" if d["whale_contradiction_flag"] else "open")
            rows_signal.append((
                ts, sym, d["whale_bias"], d["whale_confidence"],
                d["whale_flow_direction"], d["whale_activity_score"],
                d["whale_follow_signal"], d["whale_contradiction_flag"],
                d["whale_regime_label"], agreed, outcome,
            ))
            if snap == snapshots - 1:  # only persist latest raw activity rows
                for a in acts:
                    rows_activity.append((
                        a.ts, a.source, int(a.delayed), a.entity, a.symbol,
                        a.direction, a.value_usd,
                    ))

    with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
        conn.executemany(
            "INSERT INTO whale_activity(ts, source, delayed, entity, symbol, "
            "direction, value_usd) VALUES(?,?,?,?,?,?,?)", rows_activity)
        conn.executemany(
            "INSERT INTO whale_signal_history(ts, symbol, whale_bias, "
            "whale_confidence, whale_flow_direction, whale_activity_score, "
            "whale_follow_signal, whale_contradiction_flag, whale_regime_label, "
            "agreed_with_trade, trade_outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            rows_signal)
        conn.commit()
    print(f"[demo] whale tables: {len(rows_activity)} activity, "
          f"{len(rows_signal)} signal-history rows")


def seed_model_registry() -> None:
    """Record the shipped DNN champion in the registry."""
    from ml_factor.factor import load_champion

    model = load_champion()
    model_id = getattr(model, "model_id", "dnn-stageA-numpy")
    metrics = '{"trainer":"numpy_mlp","hidden":16,"sizing_cap":0.5,' \
              '"note":"shipped Stage-A advisory model"}'
    with sqlite3.connect(DB_PATH, timeout=5.0) as conn:
        conn.execute(
            "INSERT INTO model_registry(ts, model_id, role, metrics_json, notes) "
            "VALUES(?,?,?,?,?)",
            (_now_iso(), model_id, "champion", metrics,
             "auto-registered by ops/demo.py"))
        conn.commit()
    print(f"[demo] model_registry: champion {model_id} registered")


def launch_dash() -> None:
    ui_dir = os.path.join(REPO_ROOT, "ui")
    env = dict(os.environ)
    env["MAL_DB_PATH"] = DB_PATH
    env["MAL_CONFIG_PATH"] = CONFIG
    host = env.get("MAL_DASH_HOST", "127.0.0.1")
    port = env.get("MAL_DASH_PORT", "8050")
    print(f"\n[demo] launching Dash control board at http://{host}:{port}")
    print("[demo] press Ctrl-C to stop.\n")
    subprocess.run([sys.executable, "app.py"], cwd=ui_dir, env=env)


def main() -> None:
    ap = argparse.ArgumentParser(description="Market AI Lab offline demo")
    ap.add_argument("--iterations", type=int, default=25)
    ap.add_argument("--no-dash", action="store_true",
                    help="seed only; do not launch the dashboard")
    ap.add_argument("--rebuild", action="store_true",
                    help="force a cmake rebuild of the engine")
    ap.add_argument("--bridge", default=None,
                    help="host:port of a running python_bridge (optional)")
    args = ap.parse_args()

    build_engine(args.rebuild)
    run_engine(args.iterations, args.bridge)
    populate_whale_tables()
    seed_model_registry()

    print("\n[demo] seeding complete — SQLite is the single source of truth.")
    print(f"[demo] db: {DB_PATH}")
    if args.no_dash:
        print("[demo] --no-dash set; skipping dashboard launch.")
        return
    launch_dash()


if __name__ == "__main__":
    main()
