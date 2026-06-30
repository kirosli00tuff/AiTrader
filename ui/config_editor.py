"""Comment-preserving editor for the engine's Level 1 (static safety) risk-gate.

The dashboard's Advanced tab exposes the ``risk:`` block of the engine config so
an operator can raise OR lower a hard limit. This module is the *only* writer of
that file. It performs a line-based edit so YAML comments / formatting survive,
and mirrors the C++ ``validate_config`` invariants (see ``config/config.cpp``)
so a written file always stays loadable by the engine.

This edits ONLY the static config that Layer 1 reads on its next reload. It does
not — and cannot — touch the running RiskGate or weaken the runtime safety
architecture; the deterministic gate remains the final authority.
"""
from __future__ import annotations

import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.environ.get(
    "MAL_CONFIG_PATH", os.path.join(_REPO_ROOT, "config", "default_config.yaml")
)

# Parameter kinds (mirrors the C++ Config.risk field types).
PCT_PARAMS = (
    "max_daily_loss_total_pct",
    "max_daily_loss_per_venue_pct",
    "max_trade_risk_pct_of_equity",
    "max_total_open_risk_pct",
    "max_exposure_per_symbol_pct",
    "max_exposure_per_market_pct",
    "max_exposure_per_category_pct",
    "min_confidence_default",
    "min_edge_default",
)
INT_PARAMS = (
    "max_open_positions_total",
    "max_open_positions_per_venue",
    "max_consecutive_losses",
    "cooldown_minutes_after_loss_breach",
    "required_model_agreement_count",
    "stale_signal_reject_minutes",
)
BOOL_PARAMS = (
    "kill_switch_enabled",
    "hard_stop_live_if_loss_breach",
    "manual_resume_required_after_kill_switch",
)

# Ordered, with human labels — drives the editor panel.
L1_PARAMS: list[tuple[str, str]] = [
    ("max_daily_loss_total_pct", "Max daily loss — total (fraction)"),
    ("max_daily_loss_per_venue_pct", "Max daily loss — per venue (fraction)"),
    ("max_trade_risk_pct_of_equity", "Max risk per trade (fraction of equity)"),
    ("max_total_open_risk_pct", "Max total open risk (fraction)"),
    ("max_open_positions_total", "Max open positions — total"),
    ("max_open_positions_per_venue", "Max open positions — per venue"),
    ("max_exposure_per_symbol_pct", "Max exposure per symbol (fraction)"),
    ("max_exposure_per_market_pct", "Max exposure per market (fraction)"),
    ("max_exposure_per_category_pct", "Max exposure per category (fraction)"),
    ("max_consecutive_losses", "Max consecutive losses"),
    ("cooldown_minutes_after_loss_breach", "Cooldown after loss breach (minutes)"),
    ("min_confidence_default", "Min confidence to trade (fraction)"),
    ("min_edge_default", "Min edge to trade (fraction)"),
    ("required_model_agreement_count", "Required model agreement count"),
    ("stale_signal_reject_minutes", "Stale signal reject (minutes)"),
    ("kill_switch_enabled", "Kill switch enabled"),
    ("hard_stop_live_if_loss_breach", "Hard-stop live on loss breach"),
    ("manual_resume_required_after_kill_switch", "Manual resume after kill switch"),
]
L1_KEYS = [k for k, _ in L1_PARAMS]


def kind_of(key: str) -> str:
    if key in PCT_PARAMS:
        return "pct"
    if key in INT_PARAMS:
        return "int"
    if key in BOOL_PARAMS:
        return "bool"
    raise KeyError(f"{key} is not a Level 1 risk parameter")


def _coerce(key: str, raw) -> object:
    """Coerce a raw input (str/number/bool) into the param's native type."""
    kind = kind_of(key)
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key}: expected a boolean, got {raw!r}")
    if kind == "int":
        f = float(raw)
        if f != int(f):
            raise ValueError(f"{key}: expected a whole number, got {raw!r}")
        return int(f)
    return float(raw)


def _fmt(key: str, value) -> str:
    kind = kind_of(key)
    if kind == "bool":
        return "true" if value else "false"
    if kind == "int":
        return str(int(value))
    # Float: compact, never scientific notation, drop trailing zeros.
    s = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return s if s else "0"


# --- Read -------------------------------------------------------------------

def _risk_block_lines(lines: list[str]) -> tuple[int, int]:
    """Return [start, end) line indices of the body of the top-level ``risk:``
    block (the indented lines under it)."""
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^risk:\s*(#.*)?$", ln):
            start = i + 1
            break
    if start is None:
        raise ValueError("config has no top-level `risk:` block")
    end = len(lines)
    for j in range(start, len(lines)):
        ln = lines[j]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        # A non-indented, non-blank line ends the block.
        if not ln.startswith((" ", "\t")):
            end = j
            break
    return start, end


def read_l1_values(path: str = DEFAULT_CONFIG_PATH) -> dict[str, object]:
    """Read the current Level 1 values from the config file (typed)."""
    with open(path) as fh:
        lines = fh.read().splitlines()
    start, end = _risk_block_lines(lines)
    out: dict[str, object] = {}
    for ln in lines[start:end]:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^#]*?)\s*(#.*)?$", ln)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        if key in L1_KEYS and raw != "":
            try:
                out[key] = _coerce(key, raw)
            except Exception:
                out[key] = raw
    return out


# --- Validate ---------------------------------------------------------------

def validate_l1_changes(current: dict, changes: dict) -> list[str]:
    """Return a list of problems for the merged result. Empty == valid.

    Mirrors config/config.cpp:validate_config for the risk block, including the
    cross-field invariant per_venue <= total.
    """
    merged = dict(current)
    problems: list[str] = []
    for key, raw in changes.items():
        if key not in L1_KEYS:
            problems.append(f"{key}: not a Level 1 risk parameter")
            continue
        try:
            merged[key] = _coerce(key, raw)
        except Exception as exc:  # noqa: BLE001
            problems.append(str(exc))
    for key in PCT_PARAMS:
        if key in merged and isinstance(merged[key], (int, float)):
            v = float(merged[key])
            if v < 0.0 or v > 1.0:
                problems.append(f"{key} must be a fraction in [0,1], got {v}")
    for key in ("max_open_positions_total", "max_open_positions_per_venue"):
        if key in merged and merged[key] < 0:
            problems.append(f"{key} must be >= 0")
    if "max_consecutive_losses" in merged and merged["max_consecutive_losses"] < 1:
        problems.append("max_consecutive_losses must be >= 1")
    if ("required_model_agreement_count" in merged
            and merged["required_model_agreement_count"] < 0):
        problems.append("required_model_agreement_count must be >= 0")
    for key in ("cooldown_minutes_after_loss_breach", "stale_signal_reject_minutes"):
        if key in merged and merged[key] < 0:
            problems.append(f"{key} must be >= 0")
    if ("max_daily_loss_per_venue_pct" in merged
            and "max_daily_loss_total_pct" in merged):
        try:
            if (float(merged["max_daily_loss_per_venue_pct"])
                    > float(merged["max_daily_loss_total_pct"])):
                problems.append(
                    "max_daily_loss_per_venue_pct must not exceed "
                    "max_daily_loss_total_pct")
        except Exception:  # noqa: BLE001
            pass
    return problems


# --- Write ------------------------------------------------------------------

def write_l1_values(changes: dict, path: str = DEFAULT_CONFIG_PATH) -> dict[str, object]:
    """Validate then write the given Level 1 changes back to ``path`` in place,
    preserving comments / formatting. Returns the typed values written.

    Raises ValueError (without touching the file) if any value is invalid.
    """
    current = read_l1_values(path)
    problems = validate_l1_changes(current, changes)
    if problems:
        raise ValueError("; ".join(problems))

    with open(path) as fh:
        lines = fh.read().splitlines(keepends=True)
    # Work on a newline-less copy for matching, remember line endings.
    body = [ln.rstrip("\n").rstrip("\r") for ln in lines]
    start, end = _risk_block_lines(body)

    written: dict[str, object] = {}
    remaining = dict(changes)
    for i in range(start, end):
        m = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:\s*)([^#]*?)(\s*)(#.*)?$",
                     body[i])
        if not m:
            continue
        indent, key, sep, _old, _ws, comment = m.groups()
        if key in remaining:
            typed = _coerce(key, remaining.pop(key))
            comment_part = f"  {comment}" if comment else ""
            newline = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"{indent}{key}{sep}{_fmt(key, typed)}{comment_part}{newline}"
            written[key] = typed
    if remaining:
        raise ValueError(
            "parameters not found in risk block: " + ", ".join(remaining))

    with open(path, "w") as fh:
        fh.writelines(lines)
    return written
