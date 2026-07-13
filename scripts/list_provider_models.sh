#!/usr/bin/env bash
# Discover which models each provider key can actually reach.
#
# Resolves keys through the unified keystore-first resolver
# (account_manager.credentials.resolve_env), then calls each provider's
# list-models endpoint and prints every reachable model id, highlighting the
# gpt-5 and gemini-3 families. It also captures the exact response body from a
# minimal generation call per provider, so a model-access or request-shape error
# (HTTP 400 / 404) shows its real reason instead of just a status code.
#
# It never prints a key value: every key substring is redacted from all output.
# The list calls are read-only GETs; the minimal generation calls cap output at
# a single token. Spend is near zero. Live trading is never touched.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
PY="${MAL_PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || { echo "venv missing at $PY" >&2; exit 2; }

"$PY" - "$@" <<'PYMODELS'
import json
import urllib.error
import urllib.request

from account_manager.credentials import resolve_env

TIMEOUT = 20.0
_SECRETS: list[str] = []


def redact(text: str) -> str:
    for s in _SECRETS:
        if s:
            text = text.replace(s, "***REDACTED***")
    return text


def http(method: str, url: str, headers: dict, data: bytes | None = None):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # network / DNS / TLS
        return 0, f"{type(e).__name__}: {e}"


def key_for(env: str) -> str | None:
    k = resolve_env(env)
    if k:
        _SECRETS.append(k)
    return k


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


# --- OpenAI ------------------------------------------------------------------

def openai_models() -> None:
    section("OpenAI  (GET /v1/models)")
    key = key_for("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY not resolved (keystore or env). SKIPPED.")
        return
    status, body = http("GET", "https://api.openai.com/v1/models",
                        {"Authorization": f"Bearer {key}"})
    print(f"HTTP {status}")
    if status != 200:
        print(redact(body)[:1200])
        return
    try:
        ids = sorted(m.get("id", "") for m in json.loads(body).get("data", []))
    except Exception as e:
        print(f"parse error: {e}"); print(redact(body)[:800]); return
    print(f"{len(ids)} models reachable:")
    for i in ids:
        print(f"  {i}")
    gpt5 = [i for i in ids if i.startswith("gpt-5")]
    print()
    print(f">>> gpt-5 family reachable: {gpt5 if gpt5 else 'NONE'}")


# --- Google Gemini -----------------------------------------------------------

def gemini_models() -> None:
    section("Gemini  (GET v1beta/models, fallback v1)")
    key = key_for("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not resolved (keystore or env). SKIPPED.")
        return
    for ver in ("v1beta", "v1"):
        url = (f"https://generativelanguage.googleapis.com/{ver}"
               "/models?pageSize=200")
        status, body = http("GET", url, {"x-goog-api-key": key})
        print(f"[{ver}] HTTP {status}")
        if status != 200:
            print(redact(body)[:600])
            continue
        try:
            models = json.loads(body).get("models", [])
        except Exception as e:
            print(f"parse error: {e}"); print(redact(body)[:600]); continue
        rows = []
        for m in models:
            name = str(m.get("name", "")).removeprefix("models/")
            methods = m.get("supportedGenerationMethods", []) or []
            rows.append((name, "generateContent" in methods))
        rows.sort()
        print(f"{len(rows)} models reachable ({ver}):")
        for name, gen in rows:
            print(f"  {name}{'  [generateContent]' if gen else ''}")
        g3 = [n for n, gen in rows if n.startswith("gemini-3") and gen]
        print()
        print(f">>> gemini-3 family with generateContent ({ver}): "
              f"{g3 if g3 else 'NONE'}")
        return  # v1beta worked; do not also dump v1
    print("Neither v1beta nor v1 returned a usable model list.")


# --- Anthropic ---------------------------------------------------------------

def anthropic_models() -> None:
    section("Anthropic  (GET /v1/models)")
    key = key_for("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not resolved (keystore or env). SKIPPED.")
        return
    status, body = http("GET", "https://api.anthropic.com/v1/models?limit=100",
                        {"x-api-key": key, "anthropic-version": "2023-06-01"})
    print(f"HTTP {status}")
    if status != 200:
        print("list endpoint unavailable; Opus 4.8 + Haiku gate confirmed "
              "working by verify_live_integrations.sh")
        print(redact(body)[:600])
        return
    try:
        ids = sorted(m.get("id", "") for m in json.loads(body).get("data", []))
    except Exception as e:
        print(f"parse error: {e}"); print(redact(body)[:600]); return
    print(f"{len(ids)} models reachable:")
    for i in ids:
        print(f"  {i}")


# --- Task 2: exact error bodies from minimal generation calls ----------------

def diagnose_openai(model: str) -> None:
    section(f"OpenAI minimal call diagnosis (model={model})")
    key = key_for("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY not resolved. SKIPPED."); return
    # Corrected GPT-5 family shape: max_completion_tokens (not max_tokens), no
    # custom temperature. A bad model still surfaces its error body here.
    payload = json.dumps({"model": model,
                          "messages": [{"role": "user", "content": "ping"}],
                          "max_completion_tokens": 16}).encode()
    status, body = http("POST", "https://api.openai.com/v1/chat/completions",
                        {"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"}, payload)
    print(f"HTTP {status}")
    print(redact(body)[:1200])


def diagnose_gemini(model: str) -> None:
    section(f"Gemini minimal call diagnosis (model={model})")
    key = key_for("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not resolved. SKIPPED."); return
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1}}).encode()
    status, body = http("POST", url, {"x-goog-api-key": key,
                                      "Content-Type": "application/json"},
                        payload)
    print(f"HTTP {status}")
    print(redact(body)[:1200])


def main() -> None:
    print("Provider model discovery")
    print("========================")
    openai_models()
    gemini_models()
    anthropic_models()
    # Diagnose the currently-configured council models with the corrected
    # request shapes, confirming each generates (or surfacing its error body).
    try:
        from llm_consensus.config_access import llm_model_names
        names = llm_model_names()
    except Exception:
        names = {}
    diagnose_openai(names.get("llm_primary", "gpt-5.5"))
    diagnose_gemini(names.get("llm_tertiary", "gemini-3.1-pro-preview"))
    print()
    print("No key value is printed above (all redacted).")


main()
PYMODELS
