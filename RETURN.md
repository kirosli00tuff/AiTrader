# Claude Code Prompt Returns

Every prompt gets logged here before work starts. Newest at top. Each entry records the prompt, the model, what changed, and the commit message.

Format:

## Prompt: [short title]

Date:
Model:
Prompt summary: one line.
Changes: what changed.
Commit message:

---

## Prompt: Close open flags, RL advisory module (shipped off), council cost cuts, doc sweep + AUDIT refresh

Date: 2026-07-05
Model: Opus 4.8
Prompt summary: Nine-task session. Constraints: do not touch RiskGate logic, the live-trading gate, or the adaptive limit-weakening invariant; live trading stays off. (1) VENV VERIFICATION: create a venv, install both pinned requirements files, run full pytest, fix minimal, run `python -m ml_factor.train_real` against demo db, confirm the trainer refuses (clear message) when closed trades too few; record counts + trainer output. (2) REAL WHALE FIXTURES: set `SEC_EDGAR_CONTACT_EMAIL` from env (never commit), make live read-only GETs to ClankApp + SEC EDGAR (efts/data.sec.gov), record real fixtures replacing synthetic, rerun parser tests, fix shape mismatches; if unreachable, keep synthetic + mark SYNTHETIC header + log blocker. (3) DOC SWEEP + AUDIT: docs/ARCHITECTURE/BUILD_SPEC/FOLLOWUP_CREDENTIALS Binance→Coinbase, DNN/RL→dnn_advisory; rename DNN_RL_DESIGN.md→DNN_ADVISORY_DESIGN.md + update ml_factor comments; refresh AUDIT.md to honest current state; clean PROGRESS.md (delete stale simulate_outcome caveat, rewrite Next Up). (4) RL ADVISORY MODULE (built now, shipped off): new `rl_advisory` module using Stable Baselines3 PPO; pin sb3/gymnasium/torch; gym env (reset/step) with rolling feature window obs (returns, ATR, RSI, volume z-score, regime one-hot, position), discrete flat/long/short actions, long-only flag for equities, reward = realized PnL − txn cost − drawdown penalty (txn cost mandatory); training gate `rl_min_real_fills` default 500, refuses below gate, NO synthetic path; toggle `rl_enabled` default false keeps factor out of ensemble; walk-forward eval matching dnn_advisory, challenger vs supervised champion on Sharpe + drawdown-no-worse, promotion off by default; advisory only, hard cap 0.5, `/score/rl` bridge endpoint with labeled mock fallback, artifacts with provenance in model_registry. (5) TWO COUNCIL COST CUTS: risk pre-check ordering (evaluate cheap RiskGate preconditions read-only before gate/council; skip + log `risk_precheck`); market-hours skip flag `equities_market_hours_only` default true (equities skip outside RTH, crypto 24/7, log `market_hours`). (6) CONFIG: add rl_enabled false, rl_min_real_fills 500, equities_market_hours_only true; loosen nothing. (7) STARTUP TRANSPARENCY: RL mode off / on-with-fill-count-vs-gate + market-hours flag. (8) TESTS: mocked HTTP, RL env contract, reward txn cost, trainer refuses below gate, /score/rl mock fallback, rl_enabled false keeps factor out, risk_precheck fires before provider call, market_hours fires for equities off-hours never crypto; run full suite. (9) DOCUMENT + COMMIT: CONTEXT.md GUI Plan + Key Decisions + RL/cost-cut entries, CLAUDE.md hard rule (RL ships off, trains only on real fills, gated at rl_min_real_fills), PROGRESS.md dated entry + clear fixed flags, RETURN.md entry, commit to main.
Changes: **(1) Venv verification.** Created a Python 3.14.4 venv, installed both pinned requirements files (reconciled the pandas pin to 2.2.3 so it builds against numpy 1.26.4). Full suite green: **124 pytest passed** (fixed one test-only config-cache artifact in `tests/test_rl_advisory.py` by giving each toggle state a distinct temp path — the loader lru_caches on path). `python -m ml_factor.train_real --db market_ai_lab.db` refuses cleanly: `insufficient_real_data`, 0 real samples < 200, synthetic champion retained, no real challenger recorded. C++ rebuilt clean, `ctest` **5/5**. **(2) Real whale fixtures.** Recorded a REAL SEC EDGAR 13F capture (`tests/fixtures/sec_edgar_13f_sample.json`, 5 hits from efts.sec.gov, delayed-disclosure, `_provenance` noted); updated `tests/test_whale_fixtures.py` to assert against it. ClankApp host was DNS-unreachable → kept synthetic, marked SYNTHETIC in the fixture header, blocker logged. SEC User-Agent contact read from `SEC_EDGAR_CONTACT_EMAIL` env (never committed). **(3) Doc sweep + AUDIT.** Binance→Coinbase and DNN/RL→`dnn_advisory` across `docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`; `git mv docs/DNN_RL_DESIGN.md docs/DNN_ADVISORY_DESIGN.md` + updated every referencing comment (`ml_factor/factor.py`, `model.py`, `registry.py`, `python_bridge/requirements.txt`, `README.md`) and the doc body (RL reframed as the separate `rl_advisory` module). Refreshed `AUDIT.md` to honest current state (tuner learns from real closed-trade PnL gated at 30; `dnn_advisory` real-data walk-forward + gated promotion; RL split to `rl_advisory` shipped off; whale live-OFF by default; model strings now correct; C++ 5/5, pytest 124; still blunt about what's unverified). Cleaned `PROGRESS.md` (removed the stale `simulate_outcome` caveat; rewrote Next Up to paper-loop stability → GUI overhaul; cleared resolved Open Flags). **(4) RL advisory module (built, shipped off).** New `rl_advisory/` (Stable-Baselines3 PPO, pinned in `rl_advisory/requirements.txt`): `env.py` gym `TradingEnv` (rolling-window obs = returns/ATR/RSI/vol-z/regime one-hot/position; discrete flat/long/short; equities long-only; reward = realized step PnL − mandatory txn cost − drawdown penalty), `dataset.py`, `train.py` (hard `rl_min_real_fills` gate default 500, refuses BEFORE importing any backend, NO synthetic path), `evaluate.py` (walk-forward windows + deterministic 5–20-episode eval + `challenger_beats_champion` via the shared promotion gate), `service.py` (`score_rl` → disabled-neutral / labelled mock / policy, cap 0.5; `rl_ensemble_factor_names`), `config.py`. `rl_enabled` default false → engine never calls it and the factor stays out of the ensemble (`rl_advisory_factor_weight = 0.0`). `/score/rl` wired in `python_bridge/server.py`. **(5) Two council cost cuts** in `llm_consensus/consensus.py`, before the Flash gate + providers: `_risk_precheck_skip` (skip + log `risk_precheck` when the engine's read-only RiskGate already blocks) and `_market_hours_skip` (SPY/QQQ skip outside US RTH, crypto 24/7, log `market_hours`, config `engine.equities_market_hours_only`). C++ engine (`core/engine.cpp`) short-circuits the same way before the bridge call, reusing `gate_->evaluate` read-only + `util::us_equity_market_open` — RiskGate logic untouched. **(6) Config.** `config/default_config.yaml` + typed C++ structs: `rl.rl_enabled: false`, `rl.rl_min_real_fills: 500`, `engine.equities_market_hours_only: true`, `model_weights.rl_advisory_factor_weight: 0.0`. No existing risk value loosened. **(7) Startup transparency** (`core/main.cpp`): prints the two cost cuts + RL mode (off, or on with live fill-count vs gate) + market-hours flag. **(8) Tests** (mocked HTTP, no network): `tests/test_rl_advisory.py` + `tests/test_council_cost_cuts.py` covering env contract, mandatory-txn-cost reward, long-only clamp, trainer refusal below gate, `/score/rl` disabled/mock, factor-out-when-disabled, walk-forward + challenger gate, and both skips firing before any provider/gate (never for crypto). **(9) Docs + commit.** CONTEXT.md GUI Plan section + Key Decisions (RL build, both cost cuts); CLAUDE.md hard rule ("RL ships toggled off, trains only on real fills, and activates only past the `rl_min_real_fills` gate"); PROGRESS.md dated entry + flags cleared; this RETURN.md entry; committed to `main`. **NOT touched:** RiskGate logic, live-trading gate, adaptive limit-weakening invariant; live trading stays OFF.
Commit message: `Close open flags, add RL advisory module shipped off, risk pre-check and market-hours council cuts, doc sweep and audit refresh`

---

## Prompt: Strategy Layer, Bars Storage, Real-Fill Learning, Council Cost Controls, Coinbase, Whale Feeds, Level 1 Defaults, Security Hardening

Date: 2026-07-02
Model: Opus 4.8
Prompt summary: 12-task master prompt. Add bars storage + Alpaca backfill; native strategy layer (trend/momentum + mean reversion + regime detector) evaluated on closed 5m bars only with native ATR exits; remove simulate_outcome from default path so tuner learns from real closed-trade PnL (min 30 trades/factor); council cost controls (entries-only, Flash gate, daily budget, per-symbol cooldown, token cap, neutral-regime skip, compressed context, skip logging); rename dnn_advisory + drop RL claim + walk-forward training pipeline + provenance; replace Binance with Coinbase adapter; wire ClankApp + SEC EDGAR free whale feeds with real fixtures and transparent heuristic; Level 1 config defaults; security hardening (pinned deps, bind-address test, credential masking, pre-commit secrets hook, .gitignore); startup transparency block; C++ ctest + pytest coverage; document and commit. Constraints: do not touch RiskGate logic, live-trading gate, or adaptive limit-weakening invariant; risk values change through config only; live trading stays off.
Changes: 12-task master prompt delivered on branch `feat/native-strategy-council-cost-controls`, fast-forwarded onto `origin/main`. **Task 1** bars OHLCV storage + Alpaca historical backfill. **Task 2** native strategy layer (`signal_engine/strategy.*`): trend/momentum + mean reversion + regime detector, evaluated on CLOSED bars only, native ATR stop/target/time-stop set at entry, exits run without the council. **Task 3** removed `simulate_outcome` from the default path; the adaptive tuner now learns from real closed-trade PnL, gated at ≥30 closed trades (`learning/adapt_gate.hpp` — extracted pure predicate). **Task 4** council cost controls (`signal_engine/council_gate.*` + `llm_consensus/config_access.py`): council only on candidate ENTRY, Flash base-check gate, daily budget, per-symbol cooldown, per-provider token cap, neutral-regime skip, every skip logged as `council_skip`. **Task 5** `dnn_advisory` factor rename + RL claim dropped; real-data walk-forward training pipeline + provenance + GATED promotion (`ml_factor/real_dataset.py`, `train_real.py`, `registry.meets_promotion_criteria`). **Task 6** `CoinbaseSimAdapter` replaces Binance (Canada). **Task 7** free-first whale feeds (ClankApp + SEC EDGAR), live OFF by default behind `WHALE_LIVE_ENABLED`/`SEC_EDGAR_ENABLED`, env-built SEC User-Agent, synthetic fixtures + parser tests. **Task 8** Level-1 config defaults. **Task 9** security hardening: loopback-only bridge bind (`resolve_bind_host`), credential masking (`account_manager/log_safety.py`), pre-commit secrets hook (`ops/check_secrets.sh` + `install_git_hooks.sh`), pinned deps, `.gitignore`. **Task 10** startup transparency block. **Task 11** C++ `ctest` (`test_tuner_minsample`, native-exit + council-gate in `test_strategy`) — 5/5 green; Python council cost-control + bridge-bind + whale-fixture pytest. **Task 12** docs: CLAUDE.md build-order/hard-rules, README.md + AUDIT.md Binance→Coinbase + `dnn_advisory` alignment, PROGRESS.md session entry, CONTEXT.md decisions. NOT touched: RiskGate logic, live-trading gate, adaptive limit-weakening invariant; risk changes via config only; live trading stays OFF by default.
Commit message: `docs: finalize Task 12 — align docs to native strategy, dnn_advisory, Coinbase; close 12-task master prompt`

Known flags / verification status (raised 2026-07-04, fix AFTER all 12 tasks per user):
- **py_compile-only verification for Python.** The in-session base `python3` has neither
  `pytest` nor `numpy`. So Python changes this session (Task 9 security, Task 5 dnn_advisory
  training pipeline, Task 7 whale wiring, Task 11 pytest additions) are verified by `py_compile`
  + isolated logic checks + direct execution only where deps allow (stdlib/`requests`); they are
  NOT validated by a full `pytest` run or an actual numpy training run. Before merge, in a venv:
  `pip install -r python_bridge/requirements.txt -r ui/requirements.txt && pytest tests/ -q`, and
  run the real-data trainer once. Mirrored in PROGRESS.md "Open Flags / Follow-ups".
- **Task 7 whale fixtures are SYNTHETIC, not recorded from live responses.** Per user decision
  (2026-07-04), the ClankApp + SEC EDGAR adapters were wired and tested against **synthetic**
  fixtures built from each API's documented response shape — NO live network calls were made from
  this session. Real-fixture recording + shape verification is deferred: it needs live read-only
  GETs to `api.clankapp.com` and `efts.sec.gov`, and the SEC request needs a real contact email in
  its `User-Agent` (SEC fair-access) supplied via `SEC_EDGAR_CONTACT_EMAIL` (never committed). TODO
  before trusting live whale data: set `SEC_EDGAR_CONTACT_EMAIL`, run the adapters live once,
  replace the synthetic fixtures with the real responses, and confirm the parsers still pass.
- **Residual doc-consistency sweep (Task 12 partial).** The code migration is complete
  (`CoinbaseSimAdapter`, `dnn_advisory_factor_weight`), and the two primary docs (README.md,
  AUDIT.md) plus CLAUDE.md were corrected. Still carrying pre-migration wording, deferred to the
  cleanup phase: `docs/ARCHITECTURE.md`, `docs/BUILD_SPEC.md`, `docs/FOLLOWUP_CREDENTIALS.md`, and
  `docs/DNN_RL_DESIGN.md` (Binance→Coinbase; "DNN/RL" concept vs the `dnn_advisory` factor name;
  design-doc filename still `DNN_RL_DESIGN.md`, referenced by code comments in `ml_factor/*.py`).
  AUDIT.md also still asserts pre-Task-3/5 claims ("DNN is a synthetic toy… no real retrain /
  champion-challenger pipeline", "adaptive layer learns from `simulate_outcome`") that Tasks 3+5
  superseded — a full honest-state AUDIT refresh is its own follow-up pass.
- Full flag list lives in PROGRESS.md "Open Flags / Follow-ups"; this note is the RETURN.md pointer.
- Policy (user, 2026-07-04): finish the whole master prompt first, then fix every flag/issue.

---

## Prompt: Add CONTEXT.md

Date: 2026-07-02
Model: Sonnet 5
Prompt summary: Owner provided CONTEXT.md content covering project rationale, key decisions, strategy rationale, whale tracking decisions, API notes, cost notes, working style, model selection guide.
Changes: Created CONTEXT.md at repo root with the provided content. No code changes.
Commit message: Add CONTEXT.md and log prompt in RETURN.md.

---

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
