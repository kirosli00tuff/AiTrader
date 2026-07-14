"""Security tests for the python bridge (Task 9 hardening).

Two guarantees:
  1. The advisory bridge binds to loopback by default and REFUSES a non-loopback
     host (e.g. 0.0.0.0) unless an operator explicitly opts in.
  2. Operational log output masks credential-shaped strings so a stray secret is
     never printed to stdout/stderr.
"""
import pytest

from account_manager.log_safety import mask_secrets, safe_print


# --- Bind-address safety ---------------------------------------------------- #

def _resolve():
    # Imported lazily so a missing optional dep surfaces as a clear skip rather
    # than a collection error. In the real test venv (requirements installed)
    # this import always succeeds.
    server = pytest.importorskip("python_bridge.server")
    return server.resolve_bind_host


def test_default_host_is_loopback():
    resolve = _resolve()
    assert resolve("127.0.0.1") == "127.0.0.1"


@pytest.mark.parametrize("host", ["::1", "localhost"])
def test_other_loopback_hosts_allowed(host):
    resolve = _resolve()
    assert resolve(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.5"])
def test_non_loopback_refused_by_default(host):
    resolve = _resolve()
    with pytest.raises(ValueError):
        resolve(host, allow_remote=False)


def test_non_loopback_requires_explicit_optin():
    resolve = _resolve()
    # Only an explicit opt-in permits a routable bind; nothing else does.
    assert resolve("0.0.0.0", allow_remote=True) == "0.0.0.0"


def test_serve_default_signature_is_loopback():
    server = pytest.importorskip("python_bridge.server")
    import inspect
    sig = inspect.signature(server.serve)
    assert sig.parameters["host"].default == "127.0.0.1"


# --- Log masking ------------------------------------------------------------ #

@pytest.mark.parametrize("secret", [
    "sk-abc123def456ghi789jkl",
    "sk-ant-api03-Zzzz1111Yyyy2222",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_1234567890abcdefghijABCDEFGHIJ12",
    "github_pat_11ABCDEFG0abcdefghijklmnop",
    "AIzaSyA1234567890abcdefghijklmnop_qrst",
])
def test_known_credential_shapes_are_redacted(secret):
    out = mask_secrets(f"error talking to provider with key {secret} oops")
    assert secret not in out
    assert "REDACTED" in out


def test_key_value_assignment_is_redacted():
    out = mask_secrets('config api_key="supersecretvalue123" loaded')
    assert "supersecretvalue123" not in out


def test_ordinary_text_is_unchanged():
    line = "python_bridge serving on http://127.0.0.1:8765 (mock council)"
    assert mask_secrets(line) == line


def test_safe_print_masks(capsys):
    safe_print("token is sk-abcdefghijklmnop1234 here")
    captured = capsys.readouterr().out
    assert "sk-abcdefghijklmnop1234" not in captured
    assert "REDACTED" in captured


# --- Client-disconnect handling (bridge-call timeout fix) ------------------- #
# A slow real council round trip used to outlast the engine's short timeout; the
# engine hung up mid-response and the bridge raised BrokenPipeError, then tried
# to write a 500 over the already-broken socket (a double traceback). The write
# path now catches the disconnect, logs one line, and never writes twice.

class _BrokenWFile:
    """A wfile whose write always fails, as if the client already hung up."""
    def __init__(self):
        self.writes = 0

    def write(self, b):
        self.writes += 1
        raise BrokenPipeError("client hung up")


def _make_handler(server, wfile, path="/score/llm"):
    """A Handler instance without the socket plumbing: HTTP header writes are
    stubbed, only the body write (via wfile) exercises the disconnect path."""
    h = server.Handler.__new__(server.Handler)
    h.wfile = wfile
    h.path = path
    h._responses = []
    h.send_response = lambda code, *a: h._responses.append(code)
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda: None
    return h


def test_send_swallows_client_disconnect():
    server = pytest.importorskip("python_bridge.server")
    h = _make_handler(server, _BrokenWFile())
    # _send must NOT raise on a broken socket, and must report the failure.
    ok = h._send(200, {"ok": True})
    assert ok is False


def test_do_post_no_second_write_after_disconnect(monkeypatch):
    import io
    server = pytest.importorskip("python_bridge.server")
    # Handler result is a plain dict, so no real council/network call is made.
    monkeypatch.setattr(server, "_handle", lambda path, payload: {"ok": True})
    h = _make_handler(server, _BrokenWFile(), path="/score/llm")
    h.headers = {"Content-Length": "2"}
    h.rfile = io.BytesIO(b"{}")
    # do_POST must not raise, and must attempt exactly ONE response (the 200),
    # never a second 500 write over the broken socket.
    h.do_POST()
    assert h._responses == [200]
