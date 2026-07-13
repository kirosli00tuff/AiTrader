"""Python bridge RPC server (JSON over HTTP, stdlib only).

Exposes advisory scoring to the C++ core:
  POST /score/llm        -> multi-LLM consensus verdict
  POST /score/dnn        -> supervised dnn_advisory factor
  POST /score/rl         -> RL advisory factor (deferred; disabled/mock fallback)
  POST /score/whale      -> whale / smart-money signal
  POST /marketdata/alpaca -> latest prices for requested symbols (real-time)
  POST /execute/alpaca_paper -> submit an Alpaca PAPER trading order
  POST /execute/ibkr_live -> submit an IBKR LIVE order via local IB Gateway
                             (live-only venue, gated off; reached only when the
                             operator enables live and the C++ gate allows it)
  GET  /health           -> liveness
  GET  /health/ibkr      -> whether the local IB Gateway socket is reachable

Each handler returns a flat JSON object that includes bridge-compatible
{bias, confidence, edge} aliases so the C++ engine's minimal JSON reader can
consume them directly. Runs fully offline (all services have mock fallbacks).
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Make repo-root packages importable when run as a script.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from llm_consensus import consensus, council_status_line, use_real_council  # noqa: E402
from ml_factor import score_state             # noqa: E402
from rl_advisory import rl_enabled, rl_min_real_fills, score_rl  # noqa: E402  (light: no torch/gym)
from whale_signal import whale_signal_for     # noqa: E402
from market_data import alpaca_source         # noqa: E402
from execution import ibkr_adapter             # noqa: E402  (lazy ib_insync inside)
from account_manager.log_safety import safe_print  # noqa: E402

# Loopback addresses are the only bind targets allowed by default. The bridge
# carries advisory scoring for a LOCAL C++ engine and must never be exposed on a
# routable interface unless an operator explicitly opts in (BRIDGE_ALLOW_REMOTE).
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _bridge_status() -> dict:
    """Report which real advisory services are actually available.

    Feeds the engine's strict-mode startup check (a layer set on-real refuses to
    start if its real service is not available) and the startup proof block.
    Cheap by design: no paid provider call and no live SEC fetch. Never raises
    and never returns a key value.
    """
    out: dict = {"status": "ok"}
    # Council: real only when use_real_council is true AND all three provider
    # keys resolve (else the providers silently degrade to labelled mocks).
    try:
        from account_manager.credentials import resolve_env
        from llm_consensus.config_access import llm_model_names
        names = llm_model_names()

        def _has(env: str) -> bool:
            try:
                return bool(resolve_env(env))
            except Exception:
                return False

        keys_ok = (_has("OPENAI_API_KEY") and _has("ANTHROPIC_API_KEY")
                   and _has("GEMINI_API_KEY"))
        real_council = bool(use_real_council())
        out["council_real"] = real_council and keys_ok
        out["council_models"] = ",".join(
            names.get(s, "") for s in
            ("llm_primary", "llm_secondary", "llm_tertiary"))
        out["council_gate"] = names.get("llm_gate", "")
        if not real_council:
            out["council_detail"] = "llm.use_real_council is false (config)"
        elif not keys_ok:
            out["council_detail"] = "a provider key does not resolve (keystore/env)"
        else:
            out["council_detail"] = "real council, all provider keys resolve"
    except Exception as e:  # noqa: BLE001
        out["council_real"] = False
        out["council_detail"] = f"council status error: {type(e).__name__}"
    # dnn_advisory: the bridge always runs real inference on the champion model.
    try:
        from ml_factor.factor import load_champion
        mid = str(load_champion().model_id)
        out["dnn_real"] = True
        out["dnn_champion"] = mid
        out["dnn_detail"] = ("champion " + mid + (" (synthetic Stage-A)"
                             if mid.startswith("dnn-0") else " (promoted real-data)"))
    except Exception as e:  # noqa: BLE001
        out["dnn_real"] = False
        out["dnn_detail"] = f"dnn unavailable: {type(e).__name__}"
    # whale: a real fetch happens only when the active SEC EDGAR feed is enabled.
    try:
        from whale_signal.adapters import (SEC_EDGAR_ENABLED_ENV,
                                           WHALE_LIVE_ENABLED_ENV, _flag)
        sec = _flag(SEC_EDGAR_ENABLED_ENV)
        out["sec_edgar"] = sec
        out["whale_live"] = _flag(WHALE_LIVE_ENABLED_ENV)
        out["whale_real"] = sec
        out["whale_detail"] = ("SEC EDGAR enabled (active whale feed)" if sec
                               else "SEC_EDGAR_ENABLED off, whale would be offline mock")
    except Exception as e:  # noqa: BLE001
        out["whale_real"] = False
        out["whale_detail"] = f"whale status error: {type(e).__name__}"
    return out


def _handle(path: str, payload: dict) -> dict:
    if path == "/status":
        return _bridge_status()
    if path == "/score/llm":
        return consensus(payload).to_dict()
    if path == "/score/dnn":
        return score_state(payload)
    if path == "/score/rl":
        # Deferred RL factor: neutral when disabled, labelled mock when enabled
        # with no artifact, real policy when a trained artifact exists. Never
        # raises, so offline runs are unaffected.
        return score_rl(payload)
    if path == "/score/whale":
        symbol = str(payload.get("symbol", "?"))
        market_bias = float(payload.get("bias", payload.get("catalyst", 0.0)))
        sig, _ = whale_signal_for(symbol, market_bias=market_bias)
        return sig.to_dict()
    if path == "/marketdata/alpaca":
        raw = str(payload.get("symbols", ""))
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
        return alpaca_source.fetch_prices(symbols)
    if path == "/execute/alpaca_paper":
        return alpaca_source.submit_paper_order(
            symbol=str(payload.get("symbol", "")),
            side=str(payload.get("side", "buy")),
            qty=float(payload.get("qty", 0.0)),
            price=float(payload.get("price", 0.0)),
        )
    if path == "/execute/ibkr_live":
        # IBKR live order via the local IB Gateway. This runs only when the C++
        # gate and mode router have already allowed a live order (gated off this
        # session). A missing Gateway returns an unavailable marker, never a fill.
        return ibkr_adapter.place_order(
            symbol=str(payload.get("symbol", "")),
            side=str(payload.get("side", "buy")),
            qty=float(payload.get("qty", 0.0)),
            price=float(payload.get("price", 0.0)),
        )
    raise KeyError(path)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default logging
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/status":
            # Which real advisory services are available (for the start script's
            # health check and the strict-mode readiness view). No paid call.
            self._send(200, _bridge_status())
        elif self.path == "/health/ibkr":
            # Raw socket probe of the local IB Gateway. Reports reachability only.
            # It never places an order and never enables live.
            reachable = ibkr_adapter.gateway_reachable()
            self._send(200, {"status": "ok", "reachable": reachable,
                             "host": ibkr_adapter._env_host(),
                             "port": ibkr_adapter._env_port()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
            result = _handle(self.path, payload)
            self._send(200, result)
        except KeyError:
            self._send(404, {"error": f"unknown endpoint {self.path}"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})


def resolve_bind_host(host: str, allow_remote: bool | None = None) -> str:
    """Return the host to bind, refusing non-loopback unless explicitly allowed.

    Defence-in-depth: the advisory bridge is loopback-only. A non-loopback host
    (e.g. 0.0.0.0) is rejected with a clear error unless BRIDGE_ALLOW_REMOTE=1
    (or an explicit ``allow_remote=True``) is set by an operator who accepts the
    exposure.
    """
    if host in _LOOPBACK_HOSTS:
        return host
    if allow_remote is None:
        allow_remote = os.environ.get("BRIDGE_ALLOW_REMOTE", "0") == "1"
    if allow_remote:
        return host
    raise ValueError(
        f"refusing to bind python_bridge to non-loopback host {host!r}; "
        f"set BRIDGE_ALLOW_REMOTE=1 to override (not recommended)"
    )


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    host = resolve_bind_host(host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    mode = "REAL council ACTIVE" if use_real_council() else "mock council"
    safe_print(f"python_bridge serving on http://{host}:{port} ({mode})")
    # Unambiguous, single source of truth for which council + gate are running.
    safe_print(f"  {council_status_line()}")
    # Non-fatal startup check: warn if a configured council model is not
    # reachable with the current key. Only when the real council is active (the
    # mock council makes no provider call, so a bad model string cannot 404
    # mid-trade). Never blocks serve() on a provider outage.
    if use_real_council():
        try:
            from llm_consensus.model_check import warn_unreachable_models
            if not warn_unreachable_models(printer=safe_print):
                safe_print("  model check: all configured council models "
                           "reachable (or unchecked)")
        except Exception as e:  # pragma: no cover - must never block startup
            safe_print(f"  model check skipped: {e}")
    safe_print(
        f"  RL advisory: {'ON' if rl_enabled() else 'OFF (ships off)'} "
        f"(real-fills gate {rl_min_real_fills()}, advisory cap 0.5)")
    httpd.serve_forever()


if __name__ == "__main__":
    p = int(os.environ.get("BRIDGE_PORT", "8765"))
    serve(port=p)
