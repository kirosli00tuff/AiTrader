"""LLM council providers — one deterministic mock + three real API clients.

Real providers (OpenAI / Anthropic / Google) each read their key from an env var
via the shared credential resolver (``account_manager.credentials.resolve_env``),
never hardcoded. Behaviour contract for every real provider's ``score``:

  * key present  -> real API call, forced JSON, parsed into a ModelVerdict.
  * key ABSENT   -> clearly-labelled deterministic MOCK verdict (never raises),
                    so the whole system still runs fully offline.
  * call errors / unparseable JSON -> neutral FLAT verdict + logged warning,
                    so one provider can never crash the council.

ADVISORY ONLY — output is a weighted factor into the C++ engine and can never
bypass Layer-1 risk.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, replace
from typing import ClassVar, Protocol

from . import http_json, provider_health
from .verdicts import (
    EXHAUSTED_SOURCE, ModelVerdict, bias_to_verdict, clamp01, det_unit,
    flat_verdict, verdict_from_payload,
)

log = logging.getLogger("llm_consensus")

# ONE bounded retry for a transient provider failure (2026-07-25). Measured
# over the whole recorded history: gemini-3.1-pro-preview failed 17 of 57 calls
# (29.8 percent) while gpt-5.5 and claude-opus-4-8 each failed 0 of 57, and
# every observed cause was transient (HTTP 503 "high demand", and a read
# timeout). There was no retry anywhere, so roughly a third of council rounds
# silently ran two-handed.
#
# Two attempts, not more: a provider that fails twice inside its own budget is
# not having a blip, and a council round has a deadline to respect.
MAX_PROVIDER_ATTEMPTS = 2
PROVIDER_RETRY_BACKOFF_SECONDS = 1.5
# Do not start a second attempt that cannot plausibly finish. Retrying with two
# seconds left just burns the backoff and returns the same failure later.
MIN_PROVIDER_RETRY_BUDGET_SECONDS = 5.0

# Transient means "the same request might well succeed now". Rate limits,
# server-side overload, and transport timeouts qualify. An auth failure, a
# malformed request, and a model-not-found do not: retrying those is a second
# certain failure that costs a round its remaining budget.
# A BILLING 429 IS NOT TRANSIENT AND WAS TREATED AS ONE UNTIL 2026-07-27. The
# classification now lives in provider_health, which reads the response's typed
# fields rather than a truncated message, and separates a rate limit (retry
# once) from an account out of quota (never retry, latch the provider off).
_TRANSIENT_STATUS = provider_health.TRANSIENT_STATUS


def _is_transient(exc: Exception, label: str = "") -> bool:
    """Whether a provider failure is worth exactly one more attempt.

    Thin wrapper over ``provider_health.classify`` so the retry policy keeps
    one home. ``label`` is optional: without it a bare exception still
    classifies by status and body, which is what the existing call sites pass.
    """
    return provider_health.classify(exc, label=label) == provider_health.TRANSIENT


# --- Stable, cacheable instruction prefix (per mode) -------------------------
# Keeping the prefix constant is what makes prompt caching effective: the fixed
# prefix is cached by each provider (explicitly for Anthropic, implicitly for
# OpenAI and Gemini), so only the per-call evidence block is new. The prompts
# live in prompts.py: anchored confidence scale, disclosed threshold, flat as
# abstention, reasoning before verdict. SYSTEM_PROMPT stays exported as the
# short-term default for existing importers.
from .prompts import short_term_system, system_prompt_for  # noqa: E402


def _default_system_prompt() -> str:
    from .config_access import council_min_confidence
    return short_term_system(council_min_confidence(None))


SYSTEM_PROMPT = _default_system_prompt()


def build_user_prompt(state: dict) -> str:
    """The variable, per-call evidence block (kept out of the cached prefix).

    Delegates to the allowlist renderer (evidence.py): only fields with a real
    source render, absent fields are omitted, never zeroed. The fabricated
    engine fields (imbalance, catalyst) and the unlabelled tick-window numbers
    (ret_5, volatility) never render.
    """
    from .evidence import render_user_prompt
    return render_user_prompt(state)


def _debug_raw(name: str, model_id: str, text: str) -> None:
    """Log the raw provider text on a parse failure, ONLY when MAL_COUNCIL_DEBUG
    is set (off by default). Truncated and passed through the credential masker so
    no key value is ever logged. Diagnostic aid, off in normal running."""
    if not os.environ.get("MAL_COUNCIL_DEBUG"):
        return
    snippet = (text or "")[:800]
    try:
        from account_manager.log_safety import mask_secrets
        snippet = mask_secrets(snippet)
    except Exception:
        pass
    log.warning("council raw (unparseable) %s (%s): %r", name, model_id, snippet)


def _resolve_key(env_var: str) -> str | None:
    """Resolve an API key following the credentials.py precedence (in-app then
    env), degrading to a plain env lookup if the credential store is unavailable.
    Never logs or echoes the value."""
    if not env_var:
        return None
    try:
        from account_manager.credentials import resolve_env
        val = resolve_env(env_var)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(env_var) or None


# --- Protocol ----------------------------------------------------------------

class LLMProvider(Protocol):
    name: str
    weight: float

    def score(self, state: dict) -> ModelVerdict: ...


# --- Deterministic offline mock ---------------------------------------------

@dataclass
class MockLLMProvider:
    """Deterministic offline LLM stand-in.

    Derives a stable directional read from the market-state features plus a
    provider-specific perturbation, so different "models" mildly disagree —
    which is what makes the consensus + agreement count meaningful.
    """

    name: str
    weight: float = 0.2
    skew: float = 0.0     # provider personality (bull/bear lean)
    model_id: str = ""    # concrete model identity (e.g. "gpt-5.5"), from config

    def score(self, state: dict) -> ModelVerdict:
        sym = str(state.get("symbol", "?"))
        ret5 = float(state.get("ret_5", 0.0))
        imbalance = float(state.get("imbalance", 0.0))
        catalyst = float(state.get("catalyst", 0.0))
        vol = float(state.get("volatility", 0.0))
        noise = det_unit(self.name + sym) - 0.5
        raw = ret5 * 22.0 + imbalance * 0.3 + catalyst * 0.4 + self.skew + noise
        bias = math.tanh(raw)
        confidence = clamp01(0.55 + 0.4 * abs(bias) - vol * 0.8)
        edge = max(0.0, 0.03 * abs(bias) + 0.005)
        return ModelVerdict(
            model=self.name,
            bias=round(bias, 4),
            confidence=round(confidence, 4),
            edge=round(edge, 4),
            verdict=bias_to_verdict(bias),
            rationale=f"mock read on {sym}",
            source="mock",
            model_id=self.model_id,
        )


# --- Real provider base (template method) -----------------------------------

@dataclass
class _RealLLMProvider:
    name: str
    weight: float = 0.2
    model_id: str = ""
    skew: float = 0.0
    timeout: float = http_json.DEFAULT_TIMEOUT
    # Per-provider response token cap (Task 4 cost control). Default matches the
    # council config default; the builder passes the configured value.
    max_tokens: int = 400

    # Config path pin for tests. The system prompt embeds the mode's acting
    # threshold, read from this config.
    cfg_path: str | None = None

    ENV_VAR: ClassVar[str] = ""
    LABEL: ClassVar[str] = "provider"

    def _system_prompt(self, state: dict) -> str:
        return system_prompt_for(state, self.cfg_path)

    def __post_init__(self) -> None:
        self._fallback = MockLLMProvider(
            name=self.name, weight=self.weight, skew=self.skew,
            model_id=self.model_id)

    # --- subclass hooks ---
    def _request(self, state: dict, key: str) -> tuple[str, dict, dict]:
        raise RuntimeError("subclass must implement _request")

    def _text_from_response(self, resp: dict) -> str:
        raise RuntimeError("subclass must implement _text_from_response")

    # --- shared behaviour ---
    def _api_key(self) -> str | None:
        return _resolve_key(self.ENV_VAR)

    def _mock_verdict(self, state: dict, reason: str) -> ModelVerdict:
        v = self._fallback.score(state)
        return replace(v, source="mock", model_id=self.model_id,
                       rationale=f"MOCK ({reason}): {v.rationale}")

    def _call(self, state: dict, key: str, timeout: float | None = None) -> str:
        url, headers, payload = self._request(state, key)
        resp = http_json.post_json(
            url, headers, payload,
            timeout=self.timeout if timeout is None else timeout)
        return self._text_from_response(resp)

    def _call_with_retry(self, state: dict, key: str) -> tuple[str, int]:
        """One bounded retry for a TRANSIENT failure. Returns (text, attempts).

        Raises the LAST error when every attempt failed, so the caller's
        existing flat-verdict fallback is unchanged.

        THE RETRY SHARES THE PROVIDER'S EXISTING BUDGET, it does not add to it.
        Two full-length attempts plus a backoff would push a council round past
        the engine's /score/llm deadline and turn a provider problem into a
        transport problem, which is precisely the confusion the 2026-07-25
        session exists to remove. Each attempt gets only the time left on
        `self.timeout`, and a retry is skipped when too little remains to be
        worth making.
        """
        deadline = time.monotonic() + self.timeout
        last: Exception | None = None
        attempts = 0
        while attempts < MAX_PROVIDER_ATTEMPTS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempts += 1
            try:
                return self._call(state, key, timeout=remaining), attempts
            except Exception as e:  # noqa: BLE001 - classified below
                last = e
                kind = provider_health.classify(e, label=self.LABEL)
                if kind == provider_health.EXHAUSTED:
                    # OUT OF QUOTA OR CREDIT. A retry is a certain second
                    # failure, and every later call this session is too, so the
                    # provider is latched off rather than failed call by call.
                    provider_health.mark_exhausted(
                        self.LABEL, model_id=self.model_id,
                        detail=str(e)[:300])
                    log.error(
                        "council provider %s (%s) is EXHAUSTED (out of quota "
                        "or credit). Not retried, and not called again this "
                        "session: %s", self.name, self.model_id, str(e)[:200])
                    break
                if (attempts >= MAX_PROVIDER_ATTEMPTS
                        or kind != provider_health.TRANSIENT):
                    break
                left = (deadline - time.monotonic()
                        - PROVIDER_RETRY_BACKOFF_SECONDS)
                if left < MIN_PROVIDER_RETRY_BUDGET_SECONDS:
                    log.warning(
                        "council provider %s (%s) transient failure with too "
                        "little budget left to retry (%.1fs): %s",
                        self.name, self.model_id, max(0.0, left), e)
                    break
                log.warning(
                    "council provider %s (%s) transient failure, retrying once "
                    "in %.1fs: %s", self.name, self.model_id,
                    PROVIDER_RETRY_BACKOFF_SECONDS, e)
                time.sleep(PROVIDER_RETRY_BACKOFF_SECONDS)
        raise last if last is not None else http_json.LLMHTTPError(
            "no attempt was made within the provider budget")

    def score(self, state: dict) -> ModelVerdict:
        key = self._api_key()
        if not key:
            # The provider LABEL, never the env var name: rationales travel
            # into thesis output and the GUI, and credential identifiers do
            # not belong there (test_research_satellite pins this).
            return self._mock_verdict(state, f"no {self.LABEL} key")
        # LATCHED OFF: this account reported exhaustion earlier in the session,
        # so no call is made at all. Recorded distinctly from a transient error
        # and from a considered hold, because it is neither.
        if provider_health.is_exhausted(self.LABEL):
            latched = provider_health.exhausted_providers().get(
                self.LABEL.strip().lower(), {})
            return flat_verdict(
                self.name, f"flat: {self.LABEL} exhausted, not called",
                source=EXHAUSTED_SOURCE, model_id=self.model_id,
                extra={"attempts": 0, "exhausted_since": latched.get("since", ""),
                       "error": latched.get("detail", "")[:200]})
        attempts = 1
        try:
            text, attempts = self._call_with_retry(state, key)
        except Exception as e:  # network / status / decode errors
            kind = provider_health.classify(e, label=self.LABEL)
            if kind == provider_health.EXHAUSTED:
                return flat_verdict(
                    self.name, f"flat: {self.LABEL} out of quota or credit",
                    source=EXHAUSTED_SOURCE, model_id=self.model_id,
                    extra={"attempts": 1, "error": str(e)[:200]})
            tried = (MAX_PROVIDER_ATTEMPTS
                     if kind == provider_health.TRANSIENT else 1)
            log.warning("council provider %s (%s) call failed after %d "
                        "attempt(s): %s", self.name, self.model_id, tried, e)
            return flat_verdict(self.name, f"flat: {self.LABEL} call error",
                                source="error", model_id=self.model_id,
                                extra={"attempts": tried,
                                       "error": str(e)[:200]})
        obj = http_json.extract_json_object(text)
        if obj is None:
            log.warning("council provider %s (%s) returned unparseable output",
                        self.name, self.model_id)
            _debug_raw(self.name, self.model_id, text)
            return flat_verdict(self.name, f"flat: {self.LABEL} unparseable JSON",
                                source="error", model_id=self.model_id,
                                extra={"attempts": attempts})
        try:
            v = verdict_from_payload(self.name, obj, source="real",
                                     model_id=self.model_id)
            # Record the attempt count on every read, so "the retry fired" is a
            # measurable fact in the persisted row rather than a log line only.
            if attempts > 1:
                v.extra = {**v.extra, "attempts": attempts}
            return v
        except Exception as e:
            log.warning("council provider %s (%s) bad payload: %s",
                        self.name, self.model_id, e)
            return flat_verdict(self.name, f"flat: {self.LABEL} bad payload",
                                source="error", model_id=self.model_id,
                                extra={"attempts": attempts})


# --- Google Gemini transport (shared by the tertiary provider AND the gate) --

def gemini_request(model_id: str, key: str, system_prompt: str,
                   user_prompt: str, max_tokens: int = 400
                   ) -> tuple[str, dict, dict]:
    model = model_id or "gemini-3.1-pro-preview"
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    payload = {
        # Prompt caching: Gemini implicitly caches a stable leading prefix
        # (systemInstruction); keeping it constant maximizes cache hits.
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",  # force JSON output
            "temperature": 0.2,
            "maxOutputTokens": max_tokens,  # cost cap (Task 4)
        },
    }
    return url, headers, payload


def gemini_text(resp: dict) -> str:
    cands = resp.get("candidates") or []
    if not cands:
        return ""
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    return "".join(str(p.get("text", "")) for p in parts)


# --- Anthropic transport (shared by the secondary provider AND the gate) -----

def anthropic_request(model_id: str, key: str, system_prompt: str,
                      user_prompt: str, max_tokens: int = 400,
                      cache_system: bool = True) -> tuple[str, dict, dict]:
    model = model_id or "claude-opus-4-8"
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    system_block = {"type": "text", "text": system_prompt}
    if cache_system:
        # Prompt caching: explicit ephemeral cache_control on the fixed system
        # prefix caches it across calls.
        system_block["cache_control"] = {"type": "ephemeral"}
    # NOTE: claude-opus-4-8 does NOT support an assistant-message prefill ("The
    # conversation must end with a user message", HTTP 400), so the "{" prefill
    # trick is unavailable here. Anthropic's structured output relies on the
    # strict JSON instruction in the system prompt, and the robust parser
    # (http_json.extract_json_object) recovers the verdict from any noise.
    payload = {
        "model": model,
        "max_tokens": max_tokens,  # cost cap (Task 4)
        "system": [system_block],
        "messages": [{"role": "user", "content": user_prompt}],
    }
    return url, headers, payload


def anthropic_text(resp: dict) -> str:
    for block in resp.get("content") or []:
        if block.get("type") == "text":
            return str(block.get("text", ""))
    return ""


# --- Concrete real providers ------------------------------------------------

@dataclass
class OpenAIProvider(_RealLLMProvider):
    """GPT-5.5 via the OpenAI Chat Completions API (env OPENAI_API_KEY)."""

    ENV_VAR: ClassVar[str] = "OPENAI_API_KEY"
    LABEL: ClassVar[str] = "OpenAI"

    def _request(self, state: dict, key: str) -> tuple[str, dict, dict]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}
        payload = {
            "model": self.model_id or "gpt-5.5",
            "messages": [
                # Prompt caching: OpenAI automatically reuses the cached stable
                # prefix (this system message) across repeated calls; no param.
                {"role": "system", "content": self._system_prompt(state)},
                {"role": "user", "content": build_user_prompt(state)},
            ],
            "response_format": {"type": "json_object"},  # force JSON output
            # GPT-5 family request shape: the token cap must be
            # max_completion_tokens (these models reject the deprecated
            # max_tokens), and only the default temperature is allowed, so we
            # omit temperature rather than send an unsupported value.
            "max_completion_tokens": self.max_tokens,  # cost cap (Task 4)
        }
        return url, headers, payload

    def _text_from_response(self, resp: dict) -> str:
        choices = resp.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content", ""))


@dataclass
class AnthropicProvider(_RealLLMProvider):
    """Claude Opus 4.8 via the Anthropic Messages API (env ANTHROPIC_API_KEY)."""

    ENV_VAR: ClassVar[str] = "ANTHROPIC_API_KEY"
    LABEL: ClassVar[str] = "Anthropic"

    def _request(self, state: dict, key: str) -> tuple[str, dict, dict]:
        return anthropic_request(self.model_id or "claude-opus-4-8", key,
                                 self._system_prompt(state),
                                 build_user_prompt(state),
                                 max_tokens=self.max_tokens)

    def _text_from_response(self, resp: dict) -> str:
        return anthropic_text(resp)


@dataclass
class GeminiProvider(_RealLLMProvider):
    """Gemini 3.1 Pro via the Google Generative Language API (env GEMINI_API_KEY)."""

    ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    LABEL: ClassVar[str] = "Gemini"

    def _request(self, state: dict, key: str) -> tuple[str, dict, dict]:
        return gemini_request(self.model_id or "gemini-3.1-pro-preview", key,
                              self._system_prompt(state),
                              build_user_prompt(state),
                              max_tokens=self.max_tokens)

    def _text_from_response(self, resp: dict) -> str:
        return gemini_text(resp)
