# Claude Code Prompt Returns

## Prompt: Real LLM Council

**Date finished:** 2026-07-02

**Summary of changes:**
Implemented the real Layer-2 LLM council, replacing the mock-only stub. The
monolithic `llm_consensus/consensus.py` was split into focused modules and three
real provider clients were added, plus a free base-check gate and prompt
caching. The RiskGate, the live-trading gate, and the adaptive
limit-weakening invariant were **not touched** (this is Layer 2 only). Live
trading remains disabled by default.

Files (12 changed, +1182 / -171):
- `config/default_config.yaml` — corrected `llm_models` strings, added `llm_gate`,
  added the `llm:` block (`use_real_council`, `gate_enabled`).
- `llm_consensus/verdicts.py` *(new)* — shared value types + verdict mapping.
- `llm_consensus/config_access.py` *(new)* — config readers (model names, flags, weights).
- `llm_consensus/http_json.py` *(new)* — single mockable HTTP seam + JSON extraction.
- `llm_consensus/providers.py` *(new)* — `MockLLMProvider` + real OpenAI / Anthropic /
  Gemini clients.
- `llm_consensus/gate.py` *(new)* — `GeminiFlashGate` + `AlwaysProceedGate`.
- `llm_consensus/consensus.py` — orchestration (gate → council), ensemble math
  unchanged, backward-compatible re-exports, `council_status_line()`.
- `llm_consensus/__init__.py` — export the new public surface.
- `python_bridge/server.py` — prints the authoritative real-vs-mock startup line.
- `core/main.cpp` — engine banner clarifies llm factors are C++ mock vs bridge.
- `.env.example` — documented `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`.
- `tests/test_llm_consensus.py` — expanded from 7 to 29 tests (HTTP fully mocked).

**Model strings (corrected):**
```yaml
llm_models:
  llm_primary:   gpt-5.5           # OpenAI
  llm_secondary: claude-opus-4-8   # Anthropic  (was: claude-opus-4.8)
  llm_tertiary:  gemini-3.1-pro    # Google     (was: gemini-2.5-pro)
  llm_gate:      gemini-3-flash    # free base-check gate (new)
```

**Provider implementation status:**
| Slot | Class | Model | Env var | API | Force-JSON | Prompt caching |
|------|-------|-------|---------|-----|------------|----------------|
| llm_primary | `OpenAIProvider` | `gpt-5.5` | `OPENAI_API_KEY` | Chat Completions | `response_format: json_object` | automatic (stable system prefix) |
| llm_secondary | `AnthropicProvider` | `claude-opus-4-8` | `ANTHROPIC_API_KEY` | Messages | strict-JSON instruction | explicit `cache_control: ephemeral` on system block |
| llm_tertiary | `GeminiProvider` | `gemini-3.1-pro` | `GEMINI_API_KEY` | generateContent | `response_mime_type: application/json` | implicit (stable `systemInstruction` prefix) |
| gate | `GeminiFlashGate` | `gemini-3-flash` | `GEMINI_API_KEY` | generateContent | `response_mime_type: application/json` | implicit (stable prefix) |

Behaviour contract (every provider):
- **Key present** → real API call, forced structured JSON, parsed into a signed
  `ModelVerdict` (`direction`+`confidence`→bias, `edge`, one-line `rationale`).
- **Key absent** → clearly-labelled deterministic **mock** verdict
  (`source="mock"`, rationale `MOCK (no <ENV>): …`) — never raises, so the system
  still runs fully offline. **No `NotImplementedError`.**
- **Call error / unparseable JSON** → neutral **flat** verdict (`source="error"`,
  bias/conf/edge = 0) + logged warning; one provider can never crash the council.
- Ensemble math (weighted bias/confidence/edge, agreement count, per-model
  verdicts) is **unchanged** — only per-provider scoring changed from mock to real.

**Config flag added:**
```yaml
llm:
  use_real_council: false   # real council only when TRUE *and* engine run with --bridge
  gate_enabled: true        # cheap Gemini-Flash base-check before the 3 providers
```
- `use_real_council` (default **false**): keeps the offline paper loop deterministic
  and key-free. When true **and** the engine runs with `--bridge`, the `/score/llm`
  factors are scored by the real council instead of the C++ mock.
- `gate_enabled` (default **true**): the base-check gate can be turned off. Without
  `GEMINI_API_KEY` the gate runs in permissive mock mode (always proceeds), so
  offline behaviour is unchanged. When the gate says "no", the three expensive
  providers are skipped and a flat/neutral council verdict is returned.

**Startup line example:**
Python bridge (`python_bridge/server.py`), mock (default):
```
python_bridge serving on http://127.0.0.1:8765 (mock council)
  LLM council: MOCK council (deterministic offline stand-ins); base-check gate ON (gemini-3-flash)
```
Python bridge, real council enabled (`llm.use_real_council: true`):
```
python_bridge serving on http://127.0.0.1:8765 (REAL council ACTIVE)
  LLM council: REAL council [gpt-5.5, claude-opus-4-8, gemini-3.1-pro]; base-check gate ON (gemini-3-flash)
```
C++ engine (`mal_engine`) banner, no bridge:
```
  llm:    in-process C++ mock (real council needs --bridge + llm.use_real_council=true)
```

**Test coverage added:**
`tests/test_llm_consensus.py` grew from 7 → **29 tests, all passing**, HTTP layer
fully mocked (no real network calls). Covers the required cases and more:
- JSON parse failure → flat verdict (`test_json_parse_failure_falls_back_to_flat`).
- Call error → flat verdict; provider exception never crashes the council.
- Missing key → clearly-labelled mock, per provider
  (`test_missing_key_returns_labeled_mock`, parametrized ×3).
- Gate says no → council skipped, providers not called
  (`test_gate_says_no_skips_council` with an exploding provider double).
- Ensemble math unchanged (`test_ensemble_math_unchanged`, locked to the exact
  weighted formula + agreement count).
- Real success path parses per-provider envelopes (OpenAI/Anthropic/Gemini).
- Gate: disabled→AlwaysProceed, enabled→FlashGate, no-key→permissive mock,
  model-declines→skip, error→fail-open.
- Real-vs-mock council selection by config flag; startup line reflects config.
- JSON extraction handles clean JSON, fenced/prose JSON, and garbage.

Full Python suite: **73 passed**. C++ `mal_engine` rebuilds cleanly and its
config parser tolerates the new keys.

**Commit message:**
```
Implement real LLM council (Opus 4.8, GPT-5.5, Gemini 3.1 Pro) with Flash gate and caching, add RETURN.md.
```

**Full output:**
```
$ pytest tests/test_llm_consensus.py -q
.............................                                            [100%]
29 passed in 0.12s

$ pytest tests/ -q
........................................................................ [ 98%]
.                                                                        [100%]
73 passed in 3.35s

$ cmake --build build --target mal_engine
[ 96%] Building CXX object CMakeFiles/mal_engine.dir/core/main.cpp.o
[100%] Linking CXX executable mal_engine
[100%] Built target mal_engine

$ ./build/mal_engine --iterations 1        # (throwaway db)
Market AI Lab engine starting (live DISABLED by default)
  ...
  bridge: off (mock)
  llm:    in-process C++ mock (real council needs --bridge + llm.use_real_council=true)
Paper loop complete. Trades=0 Blocked=4 Events=6

$ python -c "from llm_consensus import council_status_line; print(council_status_line())"
LLM council: MOCK council (deterministic offline stand-ins); base-check gate ON (gemini-3-flash)

# with llm.use_real_council: true
use_real_council: True
LLM council: REAL council [gpt-5.5, claude-opus-4-8, gemini-3.1-pro]; base-check gate ON (gemini-3-flash)
providers: ['OpenAIProvider', 'AnthropicProvider', 'GeminiProvider']

# bridge end-to-end (mock)
python_bridge serving on http://127.0.0.1:8799 (mock council)
  LLM council: MOCK council (deterministic offline stand-ins); base-check gate ON (gemini-3-flash)
HEALTH: {"status": "ok"}
LLM verdict: strong_buy | gate source: mock | per_model sources: ['mock', 'mock', 'mock']

$ git diff --cached --stat
 .env.example                   |  12 +-
 config/default_config.yaml     |  28 +++-
 core/main.cpp                  |   9 ++
 llm_consensus/__init__.py      |  18 ++-
 llm_consensus/config_access.py |  77 ++++++++++
 llm_consensus/consensus.py     | 290 +++++++++++++++++--------------------
 llm_consensus/gate.py          |  99 +++++++++++++
 llm_consensus/http_json.py     |  71 ++++++++++
 llm_consensus/providers.py     | 304 +++++++++++++++++++++++++++++++++++++++
 llm_consensus/verdicts.py      | 123 ++++++++++++++++
 python_bridge/server.py        |   7 +-
 tests/test_llm_consensus.py    | 315 ++++++++++++++++++++++++++++++++++++++++-
 12 files changed, 1182 insertions(+), 171 deletions(-)
```
