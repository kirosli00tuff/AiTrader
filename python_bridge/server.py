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


def _handle(path: str, payload: dict) -> dict:
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
    safe_print(
        f"  RL advisory: {'ON' if rl_enabled() else 'OFF (ships off)'} "
        f"(real-fills gate {rl_min_real_fills()}, advisory cap 0.5)")
    httpd.serve_forever()


if __name__ == "__main__":
    p = int(os.environ.get("BRIDGE_PORT", "8765"))
    serve(port=p)
