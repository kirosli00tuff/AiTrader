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
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("python_bridge")

# Make repo-root packages importable when run as a script.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from llm_consensus import consensus, council_status_line, use_real_council  # noqa: E402
from research_satellite import research_thesis  # noqa: E402  (deep-research sleeve)
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


# --- Capability health (2026-07-18, after the silent bridge outage) ----------
# On 2026-07-17 this process answered /health 200 for 19 hours while its
# fresh-socket and fresh-file paths were dead: market data fell to the walk
# fallback and controls.json reads returned nothing, while pooled provider
# connections kept working. Liveness proved nothing. /health now exercises the
# exact capabilities that died: a brand-new file descriptor for a file read, a
# brand-new loopback socket, and the ability to fetch a real market quote.
# Reported as "ok" or "degraded", always HTTP 200, so an unreachable bridge
# stays distinguishable from a sick one.

_BOUND_PORT: int | None = None  # set by serve(); the fresh-socket probe target
_QUOTE_PROBE_TTL_SECONDS = 60.0
_quote_probe_cache: tuple[float, str] | None = None


# --- fd telemetry (2026-07-18, after the suspected fd-class exhaustion) ------
# The 2026-07-17 outage is CONSISTENT with fd exhaustion (fresh sockets and
# fresh file reads died together while pooled connections lived) but unproven,
# because no fd count was ever recorded. Now the count is in /health, logged
# periodically, and crossing the threshold reads as degraded, so the next
# occurrence carries its own diagnosis instead of only being survived.

def _fd_count():
    """Open fd count of this process, or an error string. The error string is
    itself evidence: under exhaustion even listing /proc/self/fd fails."""
    from ops.evidence import fd_count
    return fd_count()


def _bridge_cfg() -> dict:
    try:
        from llm_consensus.config_access import config_block
        return config_block("bridge") or {}
    except Exception:  # noqa: BLE001 - telemetry must never break health
        return {}


def _fd_warn_threshold() -> int:
    """The fd count at which the bridge reports itself degraded.

    config bridge.fd_warn_threshold when positive. 0 or absent means auto: 80
    percent of the process RLIMIT_NOFILE soft limit, the headroom at which
    exhaustion is close enough to act on and early enough to diagnose.
    """
    try:
        v = int(_bridge_cfg().get("fd_warn_threshold", 0) or 0)
    except (TypeError, ValueError):
        v = 0
    if v > 0:
        return v
    try:
        import resource
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft and soft > 0:
            return max(64, int(soft * 0.8))
    except Exception:  # noqa: BLE001
        pass
    return 800


def _fd_check() -> str:
    """fd headroom as a health capability: ok below the threshold, fail at or
    above it (which flips /health to degraded), fail when unreadable on a
    /proc system (unreadable IS the suspect state)."""
    n = _fd_count()
    threshold = _fd_warn_threshold()
    if isinstance(n, int):
        return ("ok" if n < threshold
                else f"fail ({n} open fds >= threshold {threshold})")
    if not os.path.isdir("/proc/self/fd"):
        return "skipped (no /proc)"
    return f"fail (fd count unreadable: {n})"


def _fd_log_loop(interval_seconds: float) -> None:
    """Periodic one-line fd log, so a slow leak is visible in the bridge log
    long before the threshold. Daemon thread, never raises."""
    import time as _time
    while True:
        _time.sleep(max(30.0, interval_seconds))
        try:
            safe_print(f"bridge fd telemetry: {_fd_count()} open "
                       f"(degraded threshold {_fd_warn_threshold()})")
        except Exception:  # noqa: BLE001 - telemetry must never crash serve
            pass


def _fresh_file_check() -> str:
    """Read a file through a brand-new descriptor. Uses the control file path,
    the exact read that silently returned nothing during the outage."""
    try:
        from llm_consensus import control_file
        with open(control_file.control_path(), "rb") as fh:
            fh.read(64)
        return "ok"
    except FileNotFoundError:
        return "ok_absent"  # no control file is a valid state (config fallback)
    except Exception as e:  # noqa: BLE001
        return f"fail ({type(e).__name__})"


def _fresh_socket_check() -> str:
    """Open a brand-new loopback socket to our own listener. Pooled connections
    survived the outage while fresh sockets died, so reusing a pool here would
    prove nothing."""
    if not _BOUND_PORT:
        return "skipped (port unknown)"
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", _BOUND_PORT), timeout=1.0):
            pass
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"fail ({type(e).__name__})"


def _quote_probe() -> str:
    """One real market-quote fetch through the same path the feed uses.
    Keyless is 'skipped', not degraded: the offline paper loop has no
    credentials by design and must not read as sick."""
    try:
        if not all(alpaca_source._data_keys()):
            return "skipped (no data key)"
        out = alpaca_source.fetch_prices(["BTC/USD"])
        src = str(out.get("source", ""))
        return "ok" if src == "alpaca" else f"fail (source={src or 'none'})"
    except Exception as e:  # noqa: BLE001
        return f"fail ({type(e).__name__})"


def _quote_capability() -> str:
    """The quote probe, cached so frequent health polls do not hammer Alpaca."""
    global _quote_probe_cache
    import time as _time
    now = _time.time()
    if (_quote_probe_cache
            and now - _quote_probe_cache[0] < _QUOTE_PROBE_TTL_SECONDS):
        return _quote_probe_cache[1]
    result = _quote_probe()
    _quote_probe_cache = (now, result)
    return result


def health_payload() -> dict:
    """Capability health: up means every exercised capability works right now.
    degraded means the process is alive but a capability is failing, which is
    exactly the state the old liveness check could not see. fd_headroom joins
    the capability set: a bridge burning toward fd exhaustion is degraded
    BEFORE the fresh-socket and fresh-file paths die."""
    checks = {
        "fresh_file": _fresh_file_check(),
        "fresh_socket": _fresh_socket_check(),
        "market_quote": _quote_capability(),
        "fd_headroom": _fd_check(),
    }
    failing = sorted(k for k, v in checks.items() if v.startswith("fail"))
    return {"status": "degraded" if failing else "ok",
            "checks": checks, "degraded": failing,
            "fd_count": _fd_count(),
            "fd_warn_threshold": _fd_warn_threshold()}


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
    # dnn_real stays REACHABILITY (strict mode reads it): a benched champion is
    # reachable and inferring, it just contributes zero until it trains on real
    # fills. Benched is a THIRD state, distinct from off and from unreachable.
    try:
        from ml_factor.factor import bench_state, load_champion
        mid = str(load_champion().model_id)
        out["dnn_real"] = True
        out["dnn_champion"] = mid
        benched, bench_detail = bench_state()
        out["dnn_benched"] = benched
        if benched:
            out["dnn_detail"] = ("BENCHED pending real training: champion " +
                                 mid + " contributes zero (" + bench_detail +
                                 ")")
        else:
            out["dnn_detail"] = "champion " + mid + " (promoted real-data)"
    except Exception as e:  # noqa: BLE001
        out["dnn_real"] = False
        out["dnn_detail"] = f"dnn unavailable: {type(e).__name__}"
    # whale: a real fetch happens only when the active SEC EDGAR feed is enabled.
    try:
        from whale_signal.adapters import (SEC_EDGAR_ENABLED_ENV,
                                           WHALE_ALERT_ENABLED_ENV,
                                           WHALE_LIVE_ENABLED_ENV, _flag,
                                           _resolve)
        sec = _flag(SEC_EDGAR_ENABLED_ENV)
        # Whale Alert crypto trial: live only when enabled AND the key resolves.
        wa_on = _flag(WHALE_ALERT_ENABLED_ENV)
        wa_keyed = bool(_resolve("WHALE_ALERT_API_KEY"))
        wa_live = wa_on and wa_keyed
        out["sec_edgar"] = sec
        out["whale_alert"] = wa_live
        out["whale_live"] = _flag(WHALE_LIVE_ENABLED_ENV)
        out["whale_real"] = sec or wa_live
        wa_note = ("Whale Alert trial ON (crypto)" if wa_live
                   else "Whale Alert trial ON but no key" if wa_on
                   else "Whale Alert trial off")
        sec_note = ("SEC EDGAR enabled (active whale feed)" if sec
                    else "SEC_EDGAR_ENABLED off")
        out["whale_detail"] = f"{sec_note}, {wa_note}"
    except Exception as e:  # noqa: BLE001
        out["whale_real"] = False
        out["whale_detail"] = f"whale status error: {type(e).__name__}"
    return out


def _capture_flag_mismatch(path: str, payload: dict, out: dict) -> None:
    """Evidence capture for the unexplained engine-ON funnel-OFF condition.

    The engine only calls the discovery endpoints when ITS parse of
    controls.json reads discovery ON, and it says so with
    engine_reads_enabled in the request. When this process simultaneously
    reads the flag OFF, that is the exact 2026-07-17 mismatch (19 hours, 228
    polls, never explained). Record the control file bytes as read, this
    process's pid and start time, and this process's fd count (the exhaustion
    hypothesis) at the moment it happens. Diagnosis only: the response is
    returned unchanged and the root cause is NOT guessed at.
    """
    try:
        if not payload.get("engine_reads_enabled"):
            return
        mismatch = (out.get("enabled") is False
                    or out.get("status") == "disabled")
        if not mismatch:
            return
        from ops.evidence import capture
        capture("discovery_flag_mismatch",
                {"endpoint": path,
                 "request": {k: payload.get(k)
                             for k in ("asset_class", "engine_reads_enabled")},
                 "response": out})
    except Exception:  # noqa: BLE001 - evidence must never break the endpoint
        pass


def _handle(path: str, payload: dict) -> dict:
    if path == "/status":
        return _bridge_status()
    if path == "/score/llm":
        return consensus(payload).to_dict()
    if path == "/research/thesis":
        # Deep-research thesis for the research_satellite sleeve. The Haiku gate
        # screens the candidate inside consensus before the full council runs.
        # Returns direction/conviction/horizon/rationale; the engine enforces the
        # hard cap, the conviction threshold, and the RiskGate on any order.
        return research_thesis(payload)
    if path == "/discovery/due":
        # Cadence question only: one indexed SQLite read, no Finnhub or LLM call.
        # The engine asks before every trigger, so this must stay cheap.
        from discovery import run as discovery_run
        out = discovery_run.due_status(
            str(payload.get("asset_class", "crypto")),
            db_path=str(payload.get("db", "market_ai_lab.db")))
        _capture_flag_mismatch(path, payload, out)
        return out
    if path == "/discovery/run_once":
        # Runs the funnel: Finnhub pre-screen, Haiku gate, council on survivors.
        # SLOW (tens of seconds once council calls run), which is why the engine
        # calls it off its loop thread and never waits on it inline. The bridge
        # is a ThreadingHTTPServer, so a pass in flight does not block the
        # engine's market-data or council calls on other connections.
        #
        # force=true because the ENGINE already asked /discovery/due and decided.
        # run_once re-checks discovery_enabled regardless, so the flag is still
        # honored on every path and force can only skip the cadence, never the
        # flag.
        from discovery import run as discovery_run
        out = discovery_run.run_once(
            str(payload.get("asset_class", "crypto")),
            db_path=str(payload.get("db", "market_ai_lab.db")),
            force=bool(payload.get("force", False)))
        _capture_flag_mismatch(path, payload, out)
        return out
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

    def _send(self, code: int, obj: dict) -> bool:
        """Write a JSON response. Returns False (and logs one line) if the client
        already hung up, so the caller never writes a second time (the 500) over
        an already-broken socket. This stops the double traceback that a slow
        council round trip used to cause when the engine timed out mid-response."""
        try:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except (BrokenPipeError, ConnectionResetError) as e:
            log.warning("bridge client disconnected before response on %s: %s",
                        self.path, e)
            return False

    def do_GET(self):
        if self.path == "/health":
            # Capability, not liveness: exercises a fresh file read, a fresh
            # socket, and the market-quote path. Always HTTP 200 so degraded
            # stays distinguishable from unreachable.
            self._send(200, health_payload())
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
        # Read the request body first. If the client already hung up, log one
        # line and return, never touch the socket again.
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
        except (BrokenPipeError, ConnectionResetError) as e:
            log.warning("bridge client disconnected before request body on %s: %s",
                        self.path, e)
            return
        # Compute the result, then send ONCE. A handler error sends a 500; a
        # broken socket during any send is swallowed by _send (no second write).
        try:
            payload = json.loads(raw or b"{}")
            result = _handle(self.path, payload)
        except KeyError:
            self._send(404, {"error": f"unknown endpoint {self.path}"})
            return
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})
            return
        self._send(200, result)


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
    global _BOUND_PORT
    host = resolve_bind_host(host)
    httpd = ThreadingHTTPServer((host, port), Handler)
    _BOUND_PORT = port  # the fresh-socket health probe connects back here
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
        f"(real-fills gate {rl_min_real_fills()}, factor weight 0.0 until "
        f"an operator enables it past the gate)")
    # fd telemetry: one line now (the baseline the leak is measured against),
    # then a periodic daemon-thread log. See the fd telemetry block above.
    safe_print(f"  fd telemetry: {_fd_count()} open at startup "
               f"(degraded threshold {_fd_warn_threshold()})")
    try:
        import threading
        interval = float(_bridge_cfg().get("fd_log_interval_seconds", 300) or 300)
        threading.Thread(target=_fd_log_loop, args=(interval,),
                         daemon=True, name="fd-telemetry").start()
    except Exception:  # noqa: BLE001 - telemetry must never block serving
        pass
    httpd.serve_forever()


if __name__ == "__main__":
    p = int(os.environ.get("BRIDGE_PORT", "8765"))
    serve(port=p)
