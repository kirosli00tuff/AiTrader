# Configuration Schema

`config/default_config.yaml` is the canonical, safe-default config and the
**safety contract**. It is loaded by the C++ core (`config/config.cpp`) into
typed structs and validated strictly at load time (`validate_config`). Invalid
or unsafe values cause the engine to refuse to start.

The Python services and Dash UI read the same YAML for display/control defaults.

## Top-level blocks

| Block | Struct | Notes |
|-------|--------|-------|
| `system` | `SystemConfig` | balance, default mode, live default (must be false), kill switch. |
| `venues` | `vector<VenueConfig>` | per-venue mode/adapters; live disabled by default. |
| `risk` | `RiskConfig` | **Layer-1 HARD LIMITS** — never weakened by adaptive logic. |
| `sizing` | `SizingConfig` | sizing method + advisory caps (`dnn_position_scale_cap`, `whale_position_scale_cap`). |
| `adaptive` | `AdaptiveConfig` | Layer-2 tuning cadence + promotion/rollback policy. |
| `whale` | `WhaleConfig` | Layer-4 whale weighting + usefulness gating. |
| `live_approval` | `LiveApprovalConfig` | all conditions that must hold before live can be enabled. |
| `dashboard` | `DashboardConfig` | refresh seconds + default panels. |
| `model_weights` | `ModelWeights` | ensemble weights (auto-normalized in the engine). |
| `data_sources` | (read by Python) | Apify / Whale Alert / SEC 13F endpoints + key env vars. |

## Validation rules (enforced in C++)

- All `*_pct` values must be fractions in `[0, 1]`.
- `risk.max_daily_loss_per_venue_pct` ≤ `risk.max_daily_loss_total_pct`.
- Position/agreement counts must be non-negative; `max_consecutive_losses ≥ 1`.
- `sizing.dnn_position_scale_cap`, `sizing.whale_position_scale_cap` ∈ `[0,1]`.
- All `model_weights.*` ≥ 0 and their sum > 0 (so normalization is well-defined).
- **SAFETY:** `system.live_mode_default_enabled` must be `false`; no venue may
  default to `live` mode or have `live_enabled: true`.
- `dashboard.dashboard_refresh_seconds ≥ 1`.

## Value types

Scalars are parsed as: bool (`true/false/yes/no/1/0`), int, double, or string.
Keys are addressed by dotted path (e.g. `risk.max_daily_loss_total_pct`).
Secrets (API keys) are **never** stored in YAML — only the *env var name* is
referenced under `data_sources.*`. See `.env.example`.
