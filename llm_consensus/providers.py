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

import json
import logging
import math
import os
from dataclasses import dataclass, replace
from typing import ClassVar, Protocol

from . import http_json
from .verdicts import (
    ModelVerdict, bias_to_verdict, clamp01, det_unit, flat_verdict,
    verdict_from_payload,
)

log = logging.getLogger("llm_consensus")


# --- Stable, cacheable instruction prefix (shared by every provider) ---------
# Keeping this constant is what makes prompt caching effective: the fixed prefix
# is cached by each provider (explicitly for Anthropic, implicitly/automatically
# for OpenAI and Gemini), so only the small per-tick user message is new.
SYSTEM_PROMPT = (
    "You are one member of a multi-model trading advisory council for a "
    "paper-trading research system. You receive a compact market/signal "
    "snapshot and output a single directional read. You are ADVISORY ONLY: a "
    "deterministic risk layer has final authority and may veto or ignore you. "
    "Judge only the edge in the setup described.\n\n"
    "Respond with a SINGLE JSON object and nothing else, with exactly these keys:\n"
    '  "direction":  one of "long", "short", "flat"\n'
    '  "confidence": number in [0,1] — confidence in that direction\n'
    '  "edge":       number in [0,1] — estimated expected fractional edge per trade\n'
    '  "rationale":  one short sentence (<= 140 chars)\n'
    "Do not include markdown, code fences, or any text outside the JSON object."
)


def build_user_prompt(state: dict) -> str:
    """The variable, per-tick portion of the prompt (kept out of the cached prefix)."""
    snapshot = {
        "symbol": state.get("symbol", "?"),
        "venue": state.get("venue", ""),
        "price": state.get("price", 0.0),
        "return_5": state.get("ret_5", 0.0),
        "order_book_imbalance": state.get("imbalance", 0.0),
        "catalyst_score": state.get("catalyst", 0.0),
        "volatility": state.get("volatility", 0.0),
    }
    return ("Market snapshot:\n" + json.dumps(snapshot, sort_keys=True) +
            "\nReturn your directional read as the required JSON object.")


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

    ENV_VAR: ClassVar[str] = ""
    LABEL: ClassVar[str] = "provider"

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

    def _call(self, state: dict, key: str) -> str:
        url, headers, payload = self._request(state, key)
        resp = http_json.post_json(url, headers, payload, timeout=self.timeout)
        return self._text_from_response(resp)

    def score(self, state: dict) -> ModelVerdict:
        key = self._api_key()
        if not key:
            return self._mock_verdict(state, f"no {self.ENV_VAR}")
        try:
            text = self._call(state, key)
        except Exception as e:  # network / status / decode errors
            log.warning("council provider %s (%s) call failed: %s",
                        self.name, self.model_id, e)
            return flat_verdict(self.name, f"flat: {self.LABEL} call error",
                                source="error", model_id=self.model_id)
        obj = http_json.extract_json_object(text)
        if obj is None:
            log.warning("council provider %s (%s) returned unparseable output",
                        self.name, self.model_id)
            _debug_raw(self.name, self.model_id, text)
            return flat_verdict(self.name, f"flat: {self.LABEL} unparseable JSON",
                                source="error", model_id=self.model_id)
        try:
            return verdict_from_payload(self.name, obj, source="real",
                                        model_id=self.model_id)
        except Exception as e:
            log.warning("council provider %s (%s) bad payload: %s",
                        self.name, self.model_id, e)
            return flat_verdict(self.name, f"flat: {self.LABEL} bad payload",
                                source="error", model_id=self.model_id)


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
                {"role": "system", "content": SYSTEM_PROMPT},
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
                                 SYSTEM_PROMPT, build_user_prompt(state),
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
                              SYSTEM_PROMPT, build_user_prompt(state),
                              max_tokens=self.max_tokens)

    def _text_from_response(self, resp: dict) -> str:
        return gemini_text(resp)
