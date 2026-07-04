"""Market AI Lab — Plotly Dash dashboard (broker-style).

A clean, beginner-friendly layout modeled on big online brokers, with four
top-level tabs:

  Paper      (default)  big portfolio hero + simple stat cards + equity chart,
                        open positions and recent activity (paper account).
  Live                  same skeleton but LOCKED by default — surfaces the
                        approval gate; live trading stays disabled.
  Advanced              every dense/technical panel (AI verdicts, model-weight
                        control panel, DNN/RL, whale charts, registry, venue
                        state, blocked trades, weight/param history, event log,
                        allocation/exposure, learning curve, calendar heatmap).
  Accounts              the credentials / connections manager.

All numbers come from the existing read-only ``db`` helpers (single source of
truth). The model-weight control panel is fully adjustable (numeric input +
lock + reset); adjusting weights only re-blends ADVISORY factors and can never
weaken the deterministic Layer-1 RiskGate.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml
from dash import Input, Output, State, dash_table, dcc, html, ctx

import db
import config_editor as cfg_editor
import weight_tuner
from dash import ALL

# Make repo-root packages (account_manager) importable from the ui/ cwd.
_RR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RR not in sys.path:
    sys.path.insert(0, _RR)
from account_manager import credentials as creds  # noqa: E402

# --- Config -----------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG_PATH = os.environ.get(
    "MAL_CONFIG_PATH", os.path.join(_REPO_ROOT, "config", "default_config.yaml")
)


def _load_full_cfg() -> dict:
    try:
        with open(_CFG_PATH) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def _load_dashboard_cfg() -> dict:
    return _load_full_cfg().get("dashboard", {}) or {}


_DCFG = _load_dashboard_cfg()
REFRESH_MS = int(_DCFG.get("dashboard_refresh_seconds", 5)) * 1000
TRADE_PAGE = int(_DCFG.get("trade_feed_page_size", 50))
# Auto-tune on a slower multiple of the dashboard tick so weights visibly drift
# as the bot learns without thrashing the audit log every few seconds.
AUTO_TUNE_EVERY = max(1, int(_DCFG.get("auto_tune_every_ticks", 6)))

FACTOR_LABELS = {
    "llm_primary": "LLM Primary",
    "llm_secondary": "LLM Secondary",
    "llm_tertiary": "LLM Tertiary",
    "rule_based": "Rule-Based",
    "dnn_advisory": "DNN Advisory",
    "whale_signal": "Whale Signal",
}


def _llm_model_names() -> dict:
    """Concrete model id per LLM slot, read live from the config's llm_models
    block (single source of truth — never hardcoded)."""
    names = _load_full_cfg().get("llm_models", {}) or {}
    return {str(k): str(v) for k, v in names.items()}


def _factor_label(factor: str) -> str:
    """Label for an ensemble factor. For LLM slots, surface the exact configured
    model id (e.g. "gpt-5.5") instead of the generic slot name."""
    names = _llm_model_names()
    mid = names.get(factor, "")
    if mid:
        return mid
    return FACTOR_LABELS.get(factor, factor)

_PACIFIC = ZoneInfo("America/Los_Angeles")


def _fmt_ts_pst(value) -> str:
    """Shared user-facing timestamp formatter.

    Converts a stored UTC ISO string (e.g. "2026-06-30T01:32:02Z") to friendly
    US Pacific time with the correct PST/PDT label, e.g. "Jun 29, 6:32 PM PST".
    Reused everywhere user-facing timestamps appear (trades, whale activity,
    events). Returns the input unchanged if it cannot be parsed (raw value stays
    available for sorting upstream).
    """
    if not value or not isinstance(value, str):
        return value or ""
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(_PACIFIC)
        label = local.tzname() or "PST"  # PST or PDT depending on the date
        return local.strftime("%b %-d, %-I:%M %p ") + label
    except Exception:
        return value


def _fmt_ts_col(df: pd.DataFrame, col: str = "ts") -> pd.DataFrame:
    """Return a copy with the given UTC-ISO column reformatted to friendly PST."""
    if col in df.columns:
        df = df.copy()
        df[col] = [_fmt_ts_pst(v) for v in df[col]]
    return df


_MODAL_HIDDEN = {"display": "none"}
_MODAL_SHOWN = {"display": "flex", "alignItems": "center",
                "justifyContent": "center", "position": "fixed",
                "top": 0, "left": 0, "width": "100vw", "height": "100vh",
                "background": "rgba(0,0,0,0.78)", "zIndex": 1000}

_BG = "#0d1117"
_PANEL = "#161b22"
_FG = "#e6edf3"
_MUTED = "#8b949e"
_ACCENT = "#2f81f7"
_GREEN = "#3fb950"
_RED = "#f85149"
_AMBER = "#d29922"

app = dash.Dash(__name__, title="AiTrader — Dashboard",
                suppress_callback_exceptions=True)
server = app.server  # for gunicorn / WSGI / desktop wrapper


# --- Reusable layout helpers ------------------------------------------------

def _panel(title: str, *children) -> html.Div:
    return html.Div(
        [html.H3(title, style={"marginTop": 0, "color": _FG,
                               "borderBottom": f"1px solid {_ACCENT}",
                               "paddingBottom": "6px", "fontSize": "15px"}),
         *children],
        style={"background": _PANEL, "borderRadius": "10px", "padding": "14px",
               "margin": "8px", "flex": "1 1 480px", "minWidth": "420px",
               "boxShadow": "0 1px 3px rgba(0,0,0,0.4)"},
    )


def _table(df: pd.DataFrame, page_size: int = 10) -> dash_table.DataTable:
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        page_size=page_size,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": _PANEL, "color": _FG,
                    "border": "1px solid #30363d", "fontSize": "12px",
                    "padding": "4px", "fontFamily": "monospace",
                    "textAlign": "left", "maxWidth": "220px",
                    "overflow": "hidden", "textOverflow": "ellipsis"},
        style_header={"backgroundColor": "#21262d", "fontWeight": "bold",
                      "color": _FG, "border": "1px solid #30363d"},
        sort_action="native",
    )


_TRADE_CELL = {"backgroundColor": _PANEL, "color": _FG,
               "border": "1px solid #30363d", "fontSize": "12px",
               "padding": "4px", "fontFamily": "monospace", "textAlign": "left",
               "maxWidth": "220px", "overflow": "hidden",
               "textOverflow": "ellipsis"}
_TRADE_HEADER = {"backgroundColor": "#21262d", "fontWeight": "bold",
                 "color": _FG, "border": "1px solid #30363d"}


def _trade_table(df: pd.DataFrame, scope: str,
                 page_size: int = 12) -> dash_table.DataTable:
    """A clickable trade DataTable, sorted MOST RECENT FIRST.

    Rows are pre-sorted descending by the raw UTC timestamp so page 1 shows the
    newest trades; the raw ``id`` is carried in the row data so a row click can
    look the full trade up. The displayed ``time`` column uses the shared PST
    formatter. ``scope`` distinguishes the paper/live/all tables for the
    detail-modal callback's pattern-matching Input.
    """
    df = df.copy()
    if "ts" in df.columns:
        df = df.sort_values("ts", ascending=False, kind="stable")
    show = pd.DataFrame()
    if "id" in df.columns:
        show["id"] = df["id"].values
    if "ts" in df.columns:
        show["time"] = [_fmt_ts_pst(v) for v in df["ts"]]
    for c in ("symbol", "side", "qty", "price", "pnl", "outcome"):
        if c in df.columns:
            show[c] = df[c].values
    for c in ("qty", "price", "pnl"):
        if c in show.columns:
            show[c] = pd.to_numeric(show[c], errors="coerce").round(4)
    return dash_table.DataTable(
        id={"type": "trade-tbl", "scope": scope},
        data=show.to_dict("records"),
        columns=[{"name": c, "id": c} for c in show.columns],
        page_size=page_size,
        page_action="native",
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell=_TRADE_CELL,
        style_header=_TRADE_HEADER,
        style_data={"cursor": "pointer"},
    )


def _empty_fig(msg: str = "no data yet") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False,
                       font={"color": _MUTED, "size": 13})
    fig.update_layout(template="plotly_dark", paper_bgcolor=_PANEL,
                      plot_bgcolor=_PANEL, height=260,
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis={"visible": False}, yaxis={"visible": False})
    return fig


def _style(fig: go.Figure, height: int = 260) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor=_PANEL,
                      plot_bgcolor=_PANEL, height=height,
                      margin=dict(l=40, r=14, t=30, b=30),
                      legend=dict(font={"size": 10}))
    return fig


# Every chart id, registered as it is built, so the fullscreen modal callback
# can read the live figure of whichever chart the user expands. Populated while
# the layout is constructed (before any callback is registered).
GRAPH_IDS: list[str] = []


def _graph(graph_id: str, **graph_kwargs) -> html.Div:
    """A dcc.Graph plus a consistent "⤢ Expand" button that opens the same
    figure in the shared fullscreen modal. The button never alters the chart's
    own tick callback — it just mirrors the current figure into the overlay."""
    if graph_id not in GRAPH_IDS:
        GRAPH_IDS.append(graph_id)
    return html.Div([
        html.Div(
            html.Button("⤢ Expand",
                        id={"type": "expand", "graph": graph_id}, n_clicks=0,
                        title="Open this chart full screen",
                        style={"background": "transparent", "color": _MUTED,
                               "border": "1px solid #30363d",
                               "borderRadius": "6px", "fontSize": "11px",
                               "padding": "2px 8px", "cursor": "pointer"}),
            style={"textAlign": "right", "marginBottom": "-6px"}),
        dcc.Graph(id=graph_id, **graph_kwargs),
    ])


# --- Broker-style formatting + summary helpers ------------------------------

def _fmt_money(x) -> str:
    try:
        x = float(x)
    except Exception:
        x = 0.0
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _fmt_pct(x) -> str:
    try:
        x = float(x)
    except Exception:
        x = 0.0
    return f"{x:+.2f}%"


def _agg_equity() -> pd.DataFrame:
    """Aggregate equity curve (ts, equity[, drawdown_pct...]).

    Prefers the AGGREGATE balance rows; falls back to summing per-venue
    equity so the hero/chart still work on partially-seeded databases.
    """
    df = db.equity_curve("AGGREGATE")
    if not df.empty:
        return df
    venues = [v for v in db.venues_with_balances() if v != "AGGREGATE"]
    frames = []
    for v in venues:
        d = db.equity_curve(v)
        if not d.empty:
            frames.append(d[["ts", "equity"]].rename(
                columns={"equity": v}).set_index("ts"))
    if frames:
        merged = pd.concat(frames, axis=1).sort_index().ffill()
        merged["equity"] = merged.sum(axis=1)
        return merged.reset_index()[["ts", "equity"]]
    return pd.DataFrame()


def _equity_summary(df: pd.DataFrame):
    """Return (latest, today_chg, today_pct, alltime_chg, alltime_pct).

    Robust to empty / single-row frames -> zeros (never raises).
    """
    if df is None or df.empty or "equity" not in df:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    eq = pd.to_numeric(df["equity"], errors="coerce")
    valid = df.loc[eq.notna()].copy()
    eq = eq.dropna()
    if eq.empty:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    latest = float(eq.iloc[-1])
    if len(eq) < 2:
        return latest, 0.0, 0.0, 0.0, 0.0
    first = float(eq.iloc[0])
    all_chg = latest - first
    all_pct = (all_chg / first * 100.0) if first else 0.0
    # Today's change: latest minus the first equity recorded on the latest day.
    today_open = first
    try:
        ts = pd.to_datetime(valid["ts"], errors="coerce")
        days = ts.dt.date
        last_day = days.iloc[-1]
        same_day = valid.loc[days == last_day, "equity"]
        same_day = pd.to_numeric(same_day, errors="coerce").dropna()
        if not same_day.empty:
            today_open = float(same_day.iloc[0])
    except Exception:
        today_open = first
    today_chg = latest - today_open
    today_pct = (today_chg / today_open * 100.0) if today_open else 0.0
    return latest, today_chg, today_pct, all_chg, all_pct


def _trade_stats(tdf: pd.DataFrame):
    """Return (total_pl, win_rate_pct, n_trades) from a trades frame."""
    if tdf is None or tdf.empty:
        return 0.0, 0.0, 0
    pnl = pd.to_numeric(tdf.get("pnl"), errors="coerce").dropna()
    total_pl = float(pnl.sum()) if not pnl.empty else 0.0
    n_trades = int(len(tdf))
    if "outcome" in tdf:
        decided = tdf[tdf["outcome"].isin(["win", "loss"])]
        n_dec = len(decided)
        wins = int((decided["outcome"] == "win").sum()) if n_dec else 0
        win_rate = (wins / n_dec * 100.0) if n_dec else 0.0
    else:
        win_rate = 0.0
    return total_pl, win_rate, n_trades


def _max_drawdown(edf: pd.DataFrame) -> float:
    """Most-negative drawdown % from an equity frame (0.0 if unavailable)."""
    if edf is None or edf.empty:
        return 0.0
    if "drawdown_pct" in edf:
        dd = pd.to_numeric(edf["drawdown_pct"], errors="coerce").dropna()
        if not dd.empty:
            return float(dd.min())
    eq = pd.to_numeric(edf.get("equity"), errors="coerce").dropna()
    if eq.empty:
        return 0.0
    dd = (eq / eq.cummax() - 1.0) * 100.0
    return float(dd.min())


def _change_line(label: str, chg: float, pct: float, big: bool = False) -> html.Div:
    up = chg >= 0
    color = _GREEN if up else _RED
    arrow = "▲" if up else "▼"  # ▲ / ▼
    size = "20px" if big else "15px"
    return html.Div([
        html.Span(f"{arrow} {_fmt_money(chg)} ({_fmt_pct(pct)})",
                  style={"color": color, "fontSize": size, "fontWeight": "600"}),
        html.Span(label, style={"color": _MUTED, "fontSize": "13px",
                                "marginLeft": "10px"}),
    ], style={"margin": "3px 0"})


def _hero(value, today_chg, today_pct, all_chg, all_pct,
          label: str = "Total portfolio value") -> html.Div:
    return html.Div([
        html.Div(label, style={"color": _MUTED, "fontSize": "14px",
                               "letterSpacing": "0.5px",
                               "textTransform": "uppercase"}),
        html.Div(_fmt_money(value), style={"color": _FG, "fontSize": "54px",
                                           "fontWeight": "700",
                                           "lineHeight": "1.1",
                                           "margin": "6px 0"}),
        _change_line("today", today_chg, today_pct, big=True),
        _change_line("all-time", all_chg, all_pct),
    ], style={"padding": "26px 30px"})


def _stat_card(label: str, value: str, color: str | None = None) -> html.Div:
    return html.Div([
        html.Div(value, style={"color": color or _FG, "fontSize": "26px",
                               "fontWeight": "700"}),
        html.Div(label, style={"color": _MUTED, "fontSize": "12px",
                               "marginTop": "5px",
                               "textTransform": "uppercase",
                               "letterSpacing": "0.4px"}),
    ], style={"background": _PANEL, "borderRadius": "10px",
              "padding": "18px 20px", "margin": "8px", "flex": "1 1 160px",
              "minWidth": "150px", "border": "1px solid #30363d"})


def _stat_cards(tdf: pd.DataFrame, edf: pd.DataFrame,
                n_open: int) -> list[html.Div]:
    total_pl, win_rate, n_trades = _trade_stats(tdf)
    mdd = _max_drawdown(edf)
    return [
        _stat_card("Total P/L", _fmt_money(total_pl),
                   _GREEN if total_pl >= 0 else _RED),
        _stat_card("Win rate", f"{win_rate:.1f}%"),
        _stat_card("# Trades", str(n_trades)),
        _stat_card("Max drawdown", f"{mdd:.2f}%", _RED if mdd < 0 else _FG),
        _stat_card("Open positions", str(n_open)),
    ]


# --- Page: Paper (default) --------------------------------------------------

def _paper_page() -> html.Div:
    return html.Div([
        html.Div(id="hero-paper", style={"background": _PANEL,
                                         "borderRadius": "12px",
                                         "margin": "12px",
                                         "border": "1px solid #30363d"}),
        html.Div(id="stats-paper",
                 style={"display": "flex", "flexWrap": "wrap", "margin": "0 4px"}),
        html.Div([_panel("Portfolio value over time",
                         _graph("g-equity-paper"))],
                 style={"display": "flex"}),
        html.Div([_panel("Open positions", html.Div(id="t-positions-paper"))],
                 style={"display": "flex"}),
        html.Div([_panel("Recent activity", html.Div(id="t-trades-paper"))],
                 style={"display": "flex"}),
    ], style={"paddingBottom": "30px"})


# --- Page: Live (locked by default) -----------------------------------------

def _live_page() -> html.Div:
    return html.Div([
        html.Div(id="live-gate", style={"margin": "12px"}),
        html.Div(id="hero-live", style={"background": _PANEL,
                                        "borderRadius": "12px",
                                        "margin": "12px",
                                        "border": "1px solid #30363d"}),
        html.Div(id="stats-live",
                 style={"display": "flex", "flexWrap": "wrap", "margin": "0 4px"}),
        html.Div([_panel("Live open positions",
                         html.Div(id="t-positions-live"))],
                 style={"display": "flex"}),
        html.Div([_panel("Live activity", html.Div(id="t-trades-live"))],
                 style={"display": "flex"}),
    ], style={"paddingBottom": "30px"})


# --- Page: Advanced (all dense/technical panels) ----------------------------

def _weight_controls() -> html.Div:
    weights = db.load_weight_overrides()
    locks = db.load_locks()
    rows = []
    for factor in FACTOR_LABELS:
        label = _factor_label(factor)
        rows.append(html.Div([
            html.Span(label, style={"width": "150px", "display": "inline-block",
                                    "color": _FG, "fontSize": "13px"}),
            dcc.Input(id={"type": "w-input", "factor": factor}, type="number",
                      min=0, max=1, step=0.01, value=round(weights[factor], 3),
                      style={"width": "80px", "marginRight": "10px",
                             "background": "#0d1117", "color": _FG,
                             "border": "1px solid #30363d"}),
            dcc.Checklist(id={"type": "w-lock", "factor": factor},
                          options=[{"label": " lock", "value": "locked"}],
                          value=["locked"] if locks[factor] else [],
                          style={"display": "inline-block", "color": _MUTED,
                                 "fontSize": "12px"}),
        ], style={"marginBottom": "6px"}))
    return html.Div([
        html.P("These are the LIVE effective weights the bot auto-tunes toward "
               "the most-accurate advisors. Edit any value + Apply to override "
               "(your edit becomes the new effective value); tick the lock to "
               "freeze a factor and exclude it from auto-tuning. Advisory blend "
               "only — never affects the Layer-1/Layer-2 RiskGate.",
               style={"color": _MUTED, "fontSize": "11px"}),
        *rows,
        html.Div([
            html.Button("Apply", id="w-apply", n_clicks=0,
                        style={"background": _ACCENT, "color": "white",
                               "border": "none", "padding": "6px 16px",
                               "borderRadius": "6px", "marginRight": "8px",
                               "cursor": "pointer"}),
            html.Button("Reset to defaults", id="w-reset", n_clicks=0,
                        style={"background": "#30363d", "color": _FG,
                               "border": "none", "padding": "6px 16px",
                               "borderRadius": "6px", "cursor": "pointer"}),
        ], style={"marginTop": "8px"}),
        html.Div(id="w-status", style={"color": _GREEN, "fontSize": "12px",
                                       "marginTop": "6px"}),
        html.H4("Live effective weights (auto-tuned)",
                style={"color": _FG, "marginTop": "14px", "marginBottom": "4px",
                       "fontSize": "13px"}),
        html.P("Status shows auto vs locked/manual; recent accuracy is the "
               "trailing hit-rate driving each move.",
               style={"color": _MUTED, "fontSize": "11px", "marginTop": 0}),
        html.Div(id="w-live"),
    ])


def _l1_current_table() -> dash_table.DataTable:
    """Current on-disk Level 1 values (refreshed from the config file)."""
    try:
        vals = cfg_editor.read_l1_values(_CFG_PATH)
    except Exception:
        vals = {}
    rows = [{"parameter": k, "value": str(vals.get(k, "—"))}
            for k in cfg_editor.L1_KEYS]
    df = pd.DataFrame(rows, columns=["parameter", "value"])
    return _table(df, 18)


def _l1_editor() -> html.Div:
    """Editable Level 1 (static safety) risk-gate panel with a typed-confirm
    gate. Edits the engine config file on disk; the deterministic runtime
    RiskGate is never bypassed — Layer 1 reads the new values on next reload."""
    try:
        vals = cfg_editor.read_l1_values(_CFG_PATH)
    except Exception:
        vals = {}
    rows = []
    for key, label in cfg_editor.L1_PARAMS:
        cur = vals.get(key)
        kind = cfg_editor.kind_of(key)
        if kind == "bool":
            field = dcc.Dropdown(
                id={"type": "l1-input", "param": key},
                options=[{"label": "true", "value": "true"},
                         {"label": "false", "value": "false"}],
                value="true" if cur else "false", clearable=False,
                style={"width": "120px", "color": "#111", "fontSize": "12px"})
        else:
            step = 0.001 if kind == "pct" else 1
            field = dcc.Input(
                id={"type": "l1-input", "param": key}, type="number",
                value=cur, step=step,
                style={"width": "120px", "background": "#0d1117", "color": _FG,
                       "border": "1px solid #30363d", "padding": "3px"})
        rows.append(html.Div([
            html.Span(label, style={"width": "300px", "display": "inline-block",
                                    "color": _FG, "fontSize": "12px"}),
            field,
        ], style={"marginBottom": "5px", "display": "flex",
                  "alignItems": "center", "gap": "10px"}))
    return html.Div([
        html.P("Edit the engine's Level 1 (static safety) hard limits. Changes "
               "are written to the config file on disk and picked up by the C++ "
               "engine on its next config reload. This edits ONLY the static "
               "config Layer 1 reads — it cannot bypass or weaken the running "
               "RiskGate, which stays the final authority.",
               style={"color": _MUTED, "fontSize": "11px"}),
        html.P("Every applied change is recorded in the event log below. "
               "Raising OR lowering any value requires the typed confirmation.",
               style={"color": _AMBER, "fontSize": "11px"}),
        *rows,
        html.Div([
            html.Span("Type CONFIRM to apply:",
                      style={"color": _FG, "fontSize": "12px",
                             "marginRight": "8px"}),
            dcc.Input(id="l1-confirm", type="text", value="",
                      placeholder="CONFIRM",
                      style={"width": "140px", "background": "#0d1117",
                             "color": _FG, "border": "1px solid #30363d",
                             "padding": "4px"}),
            html.Button("Apply changes", id="l1-apply", n_clicks=0,
                        style={"background": _ACCENT, "color": "white",
                               "border": "none", "padding": "6px 16px",
                               "borderRadius": "6px", "marginLeft": "10px",
                               "cursor": "pointer"}),
        ], style={"marginTop": "10px"}),
        html.Div(id="l1-status", style={"fontSize": "12px", "marginTop": "8px"}),
        html.Div("Current values on disk", style={
            "color": _FG, "fontSize": "12px", "fontWeight": "600",
            "marginTop": "12px", "marginBottom": "4px"}),
        html.Div(_l1_current_table(), id="l1-current"),
    ])


def _section(title: str) -> html.H2:
    return html.H2(title, style={"color": _FG, "padding": "10px 18px 0",
                                 "fontSize": "17px",
                                 "borderTop": "1px solid #30363d",
                                 "marginTop": "10px"})


def _advanced_page() -> html.Div:
    return html.Div([
        html.P("Power-user view — every model, safety and audit panel. Nothing "
               "here can weaken the deterministic Layer-1 RiskGate.",
               style={"color": _MUTED, "fontSize": "12px", "padding": "0 18px"}),

        _section("Performance"),
        html.Div([
            _panel("Equity Curve (Aggregate)", _graph("g-equity")),
            _panel("Daily Realized PnL", _graph("g-daily-pnl")),
            _panel("Drawdown %", _graph("g-drawdown")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Trade-by-Trade PnL", _graph("g-trade-pnl")),
            _panel("Win / Loss Calendar", _graph("g-calendar")),
            _panel("Venue Allocation", _graph("g-venue-alloc")),
        ], style={"display": "flex", "flexWrap": "wrap"}),

        _section("Allocation & exposure"),
        html.Div([
            _panel("Exposure by Symbol / Market", _graph("g-exposure")),
            _panel("Factor-Weight Contribution", _graph("g-weights")),
            _panel("Learning: Param Before/After", _graph("g-learning")),
        ], style={"display": "flex", "flexWrap": "wrap"}),

        _section("Models & AI advisory"),
        html.Div([
            _panel("DNN / RL Performance", _graph("g-dnn")),
            _panel("Whale Signal History", _graph("g-whale-hist")),
            _panel("Whale Agreement vs Outcome", _graph("g-whale-agree")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Model Verdict Board (verdict / confidence / edge / weight)",
                   html.Div(id="t-verdicts")),
            _panel("Model-Weight Control Panel", _weight_controls()),
        ], style={"display": "flex", "flexWrap": "wrap"}),

        _section("Safety & state"),
        html.Div([
            _panel("Level 1 Risk-Gate Editor (static safety hard limits)",
                   _l1_editor()),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Live-Approval Readiness", html.Div(id="t-approval")),
            _panel("Venue State", html.Div(id="t-venues")),
            _panel("Model Registry (champion/challenger)",
                   html.Div(id="t-registry")),
        ], style={"display": "flex", "flexWrap": "wrap"}),

        _section("Trading & audit"),
        html.Div([
            _panel("Recent Trades", html.Div(id="t-trades")),
            _panel("Open Positions", html.Div(id="t-positions")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Blocked / Rejected Trades (RiskGate)",
                   html.Div(id="t-blocked")),
            _panel("Weight-Change History", html.Div(id="t-weighthist")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Layer-2 Param-Change History", html.Div(id="t-paramhist")),
            _panel("Recent Whale Activity", html.Div(id="t-whaleact")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
        html.Div([
            _panel("Event Log (append-only audit)", html.Div(id="t-events")),
        ], style={"display": "flex", "flexWrap": "wrap"}),
    ], style={"paddingBottom": "30px"})


# --- Page: Accounts / Connections -------------------------------------------

VENUE_GROUPS = [("alpaca", "Alpaca"), ("coinbase", "Coinbase"),
                ("ibkr", "IBKR"), ("polymarket", "Polymarket")]
SOURCE_GROUPS = [("clankapp", "ClankApp (free, default)"),
                 ("apify", "Apify"),
                 ("sec_api", "SEC EDGAR (free, no key needed)"),
                 ("whale_alert", "Whale Alert (optional, limited free tier)")]


def _cred_input(spec) -> html.Div:
    # Secrets are never pre-filled/echoed; non-secret values are shown so they
    # can be edited. Placeholder communicates whether something is already set.
    configured = creds.get_credential_source(spec.name) != "missing"
    prefill = ""
    if not spec.secret and creds.get_credential_source(spec.name) == "in-app":
        prefill = creds.get_credential(spec.name) or ""
    placeholder = "set — leave blank to keep" if (spec.secret and configured) \
        else ("from env" if creds.get_credential_source(spec.name) == "env"
              else "not set")
    return html.Div([
        html.Span(spec.label, style={"width": "90px", "display": "inline-block",
                                     "color": _MUTED, "fontSize": "12px"}),
        dcc.Input(id={"type": "cred-input", "name": spec.name},
                  type="password" if spec.secret else "text",
                  value=prefill, placeholder=placeholder, debounce=True,
                  style={"width": "230px", "background": "#0d1117",
                         "color": _FG, "border": "1px solid #30363d",
                         "padding": "4px"}),
    ], style={"marginBottom": "5px"})


def _group_card(group: str, glabel: str, kind: str) -> html.Div:
    children = [html.H4(glabel, style={"color": _FG, "margin": "4px 0",
                                       "fontSize": "14px"})]
    if kind == "venue":
        for mode in ("paper", "live"):
            specs = [s for s in creds.CREDENTIALS.values()
                     if s.group == group and s.mode == mode]
            tag = "PAPER" if mode == "paper" else "LIVE"
            tcolor = _GREEN if mode == "paper" else _RED
            children.append(html.Div(tag, style={
                "color": tcolor, "fontSize": "11px", "fontWeight": "bold",
                "marginTop": "6px"}))
            children += [_cred_input(s) for s in specs]
    else:
        specs = [s for s in creds.CREDENTIALS.values() if s.group == group]
        children += [_cred_input(s) for s in specs]
    return html.Div(children, style={
        "background": _PANEL, "borderRadius": "10px", "padding": "12px",
        "margin": "8px", "flex": "1 1 300px", "minWidth": "280px",
        "border": "1px solid #30363d"})


def _test_options() -> list[dict]:
    opts = []
    for g, gl in VENUE_GROUPS:
        opts.append({"label": f"{gl} — paper", "value": f"{g}:paper"})
        opts.append({"label": f"{gl} — live", "value": f"{g}:live"})
    for g, gl in SOURCE_GROUPS:
        opts.append({"label": gl, "value": f"{g}:"})
    return opts


def _accounts_tab() -> html.Div:
    return html.Div([
        html.Div([
            html.P("Enter API credentials per venue (separate paper / live) and "
                   "per data source. Values are encrypted at rest with a local "
                   "key (.keystore/) and NEVER written to YAML or logs. "
                   "Resolution order at runtime: in-app saved credential first, "
                   "then environment / .env.",
                   style={"color": _MUTED, "fontSize": "12px"}),
            html.P("Live trading stays DISABLED by default; saving live keys only "
                   "makes them resolvable for the approval gate — it does not "
                   "enable live.",
                   style={"color": _AMBER, "fontSize": "12px"}),
        ], style={"padding": "0 16px"}),

        html.H3("Venues", style={"color": _FG, "padding": "0 16px",
                                 "fontSize": "15px"}),
        html.Div([_group_card(g, gl, "venue") for g, gl in VENUE_GROUPS],
                 style={"display": "flex", "flexWrap": "wrap"}),

        html.H3("Data sources", style={"color": _FG, "padding": "0 16px",
                                       "fontSize": "15px"}),
        html.Div([_group_card(g, gl, "source") for g, gl in SOURCE_GROUPS],
                 style={"display": "flex", "flexWrap": "wrap"}),

        html.Div([
            html.Button("Save credentials", id="cred-save", n_clicks=0,
                        style={"background": _ACCENT, "color": "white",
                               "border": "none", "padding": "8px 18px",
                               "borderRadius": "6px", "cursor": "pointer",
                               "marginRight": "10px"}),
            html.Span(id="cred-save-status",
                      style={"color": _GREEN, "fontSize": "12px"}),
        ], style={"padding": "8px 16px"}),

        html.Div([
            _panel("Connection Status (configured-in-app / from-env / missing)",
                   html.Div(id="cred-status")),
            _panel("Test / Validate Connection", html.Div([
                html.P("Offline-safe validator: checks that the required "
                       "credentials for the selection resolve (no network call).",
                       style={"color": _MUTED, "fontSize": "11px"}),
                dcc.Dropdown(id="cred-test-target", options=_test_options(),
                             value="alpaca:paper", clearable=False,
                             style={"width": "320px", "color": "#111"}),
                html.Button("Test connection", id="cred-test", n_clicks=0,
                            style={"background": "#30363d", "color": _FG,
                                   "border": "none", "padding": "7px 16px",
                                   "borderRadius": "6px", "cursor": "pointer",
                                   "marginTop": "8px"}),
                html.Div(id="cred-test-status",
                         style={"marginTop": "8px", "fontSize": "13px"}),
            ])),
        ], style={"display": "flex", "flexWrap": "wrap"}),
    ], style={"paddingBottom": "30px"})


# --- App layout (all tab bodies built at load so every id exists) -----------

_TAB_STYLE = {"background": _BG, "color": _FG, "border": "none",
              "padding": "12px 18px", "fontSize": "15px"}
_TAB_SELECTED = {"background": _PANEL, "color": _ACCENT, "border": "none",
                 "borderBottom": f"2px solid {_ACCENT}", "padding": "12px 18px",
                 "fontSize": "15px", "fontWeight": "600"}

def _chart_modal() -> html.Div:
    """Shared fullscreen overlay reused by every chart's Expand button."""
    return html.Div(
        id="chart-modal", style={"display": "none"},
        children=html.Div([
            html.Div([
                html.Span(id="modal-title", style={"color": _FG,
                                                    "fontSize": "16px",
                                                    "fontWeight": "600"}),
                html.Button("✕ Close", id="modal-close", n_clicks=0,
                            style={"background": "#30363d", "color": _FG,
                                   "border": "none", "padding": "6px 16px",
                                   "borderRadius": "6px", "cursor": "pointer",
                                   "float": "right"}),
            ], style={"marginBottom": "8px", "overflow": "hidden"}),
            dcc.Graph(id="modal-graph",
                      style={"height": "82vh", "width": "100%"}),
        ], style={"background": _PANEL, "borderRadius": "12px",
                  "padding": "18px 22px", "width": "94vw", "height": "92vh",
                  "border": "1px solid #30363d", "boxSizing": "border-box"}),
    )


def _trade_modal() -> html.Div:
    """Shared trade-detail overlay opened by clicking any trade row.

    The container + body Output id live in the initial layout (no lazy render),
    mirroring the fullscreen-chart modal pattern.
    """
    return html.Div(
        id="trade-modal", style={"display": "none"},
        children=html.Div([
            html.Div([
                html.Span("Trade detail", style={"color": _FG,
                                                 "fontSize": "16px",
                                                 "fontWeight": "600"}),
                html.Button("✕ Close", id="trade-modal-close", n_clicks=0,
                            style={"background": "#30363d", "color": _FG,
                                   "border": "none", "padding": "6px 16px",
                                   "borderRadius": "6px", "cursor": "pointer",
                                   "float": "right"}),
            ], style={"marginBottom": "12px", "overflow": "hidden"}),
            html.Div(id="trade-modal-body"),
        ], style={"background": _PANEL, "borderRadius": "12px",
                  "padding": "18px 22px", "width": "min(680px, 92vw)",
                  "maxHeight": "88vh", "overflowY": "auto",
                  "border": "1px solid #30363d", "boxSizing": "border-box"}),
    )


def _trade_detail(trade_id) -> html.Div:
    """Build the full-detail view for one trade id from the DB."""
    df = db.query("SELECT * FROM trades WHERE id = ?", (trade_id,))
    if df.empty:
        return html.P("Trade not found.", style={"color": _MUTED})
    row = df.iloc[0].to_dict()

    def _line(label, value):
        return html.Div([
            html.Span(f"{label}: ", style={"color": _MUTED, "fontSize": "13px"}),
            html.Span(str(value), style={"color": _FG, "fontSize": "13px",
                                         "fontFamily": "monospace"}),
        ], style={"marginBottom": "4px"})

    order = ["id", "symbol", "venue", "market", "category", "side", "qty",
             "price", "notional", "fee", "pnl", "outcome", "mode",
             "combined_conf", "combined_edge", "decision_id"]
    lines = []
    if row.get("ts"):
        lines.append(_line("time", _fmt_ts_pst(row.get("ts"))))
        lines.append(_line("timestamp (UTC)", row.get("ts")))
    for k in order:
        if k in row and row[k] is not None:
            lines.append(_line(k, row[k]))

    # Associated model/advisor verdicts recorded at the same tick timestamp.
    detail = [html.Div(lines)]
    ts = row.get("ts")
    if ts:
        mo = db.query(
            "SELECT model, verdict, confidence, edge, weight FROM model_outputs "
            "WHERE ts = ? ORDER BY weight DESC", (ts,))
        if not mo.empty:
            for c in ("confidence", "edge", "weight"):
                if c in mo:
                    mo[c] = pd.to_numeric(mo[c], errors="coerce").round(4)
            detail.append(html.H4("Advisor verdicts",
                                   style={"color": _FG, "marginTop": "14px",
                                          "fontSize": "14px"}))
            detail.append(_table(mo, 8))
    return html.Div(detail)


app.layout = html.Div([
    dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0),
    dcc.Store(id="modal-current"),
    _chart_modal(),
    _trade_modal(),
    html.Div([
        html.H1("AiTrader",
                style={"color": _FG, "margin": "0", "fontSize": "22px"}),
        html.Span(id="header-status",
                  style={"color": _MUTED, "fontSize": "13px",
                         "marginLeft": "16px"}),
    ], style={"padding": "14px 22px", "background": _PANEL,
              "borderBottom": f"2px solid {_ACCENT}",
              "display": "flex", "alignItems": "baseline"}),
    dcc.Tabs(id="main-tabs", value="paper", children=[
        dcc.Tab(label="Paper", value="paper", children=_paper_page(),
                style=_TAB_STYLE, selected_style=_TAB_SELECTED),
        dcc.Tab(label="Live", value="live", children=_live_page(),
                style=_TAB_STYLE, selected_style=_TAB_SELECTED),
        dcc.Tab(label="Advanced", value="advanced", children=_advanced_page(),
                style=_TAB_STYLE, selected_style=_TAB_SELECTED),
        dcc.Tab(label="Accounts / Connections", value="accounts",
                children=_accounts_tab(),
                style=_TAB_STYLE, selected_style=_TAB_SELECTED),
    ]),
], style={"background": _BG, "minHeight": "100vh", "fontFamily":
          "system-ui, sans-serif", "paddingBottom": "30px"})


# --- Header -----------------------------------------------------------------

@app.callback(Output("header-status", "children"), Input("tick", "n_intervals"))
def _header(_n):
    if not db.db_exists():
        return "⚠ database not found — run ops/demo.py to seed it"
    ap = db.approval_state()
    live = "ENABLED" if (not ap.empty and int(ap.iloc[0]["live_enabled"]) == 1) else "DISABLED (safe default)"
    tr = db.trades(1)
    last = tr.iloc[0]["ts"] if not tr.empty else "—"
    return f"live trading: {live}  •  last trade: {last}"


# --- Paper page callbacks ---------------------------------------------------

@app.callback(Output("hero-paper", "children"), Input("tick", "n_intervals"))
def _hero_paper(_n):
    val, tc, tp, ac, ap = _equity_summary(_agg_equity())
    return _hero(val, tc, tp, ac, ap)


@app.callback(Output("stats-paper", "children"), Input("tick", "n_intervals"))
def _stats_paper(_n):
    td = db.trades(5000)
    if not td.empty and "mode" in td:
        td = td[td["mode"] == "paper"]
    pos = db.positions()
    n_open = 0 if pos.empty else int(len(pos))
    return _stat_cards(td, _agg_equity(), n_open)


@app.callback(Output("g-equity-paper", "figure"), Input("tick", "n_intervals"))
def _equity_paper(_n):
    df = _agg_equity()
    if df.empty:
        return _empty_fig("no portfolio history yet")
    _, _, _, all_chg, _ = _equity_summary(df)
    up = all_chg >= 0
    color = _GREEN if up else _RED
    fill = "rgba(63,185,80,0.12)" if up else "rgba(248,81,73,0.12)"
    fig = px.area(df, x="ts", y="equity")
    fig.update_traces(line_color=color, fillcolor=fill)
    return _style(fig, height=320)


@app.callback(Output("t-positions-paper", "children"), Input("tick", "n_intervals"))
def _positions_paper(_n):
    df = db.positions()
    if df.empty:
        return html.P("No open positions.", style={"color": _MUTED})
    cols = [c for c in ["symbol", "venue", "side", "qty", "avg_price",
                        "notional", "unrealized_pnl"] if c in df]
    d = df[cols].copy()
    for c in ("qty", "avg_price", "notional", "unrealized_pnl"):
        if c in d:
            d[c] = d[c].round(4)
    return _table(d, 10)


@app.callback(Output("t-trades-paper", "children"), Input("tick", "n_intervals"))
def _trades_paper(_n):
    df = db.trades(TRADE_PAGE * 4)
    if df.empty:
        return html.P("No trades yet.", style={"color": _MUTED})
    if "mode" in df:
        df = df[df["mode"] == "paper"]
    if df.empty:
        return html.P("No paper trades yet.", style={"color": _MUTED})
    return _trade_table(df, "paper", 12)


# --- Live page callbacks ----------------------------------------------------

def _live_venues() -> list[str]:
    vs = db.venue_state()
    if vs.empty or "live_enabled" not in vs:
        return []
    return vs[vs["live_enabled"] == 1]["venue"].tolist()


@app.callback(Output("live-gate", "children"), Input("tick", "n_intervals"))
def _live_gate(_n):
    ap = db.approval_state()
    enabled = (not ap.empty and int(ap.iloc[0]["live_enabled"]) == 1)
    if enabled:
        banner = html.Div([
            html.Div("● LIVE TRADING ENABLED", style={
                "color": "white", "background": _RED, "display": "inline-block",
                "padding": "8px 16px", "borderRadius": "8px",
                "fontWeight": "700"}),
            html.P("Real-money trading is currently enabled. Every order still "
                   "routes through the deterministic Layer-1 RiskGate.",
                   style={"color": _FG, "fontSize": "13px", "marginTop": "8px"}),
        ])
    else:
        banner = html.Div([
            html.Div("🔒 Live (real-money) trading is DISABLED by default",
                     style={"color": _FG, "fontSize": "20px",
                            "fontWeight": "700"}),
            html.P("AiTrader is paper-first. Live trading stays off until the "
                   "approval gate passes and you explicitly enable it. This page "
                   "only surfaces the gate — it cannot enable live on its own.",
                   style={"color": _MUTED, "fontSize": "13px",
                          "marginTop": "6px"}),
        ])

    details = []
    if not ap.empty:
        r = ap.iloc[0]
        details.append(html.P(
            f"manual_confirmation: {int(r['manual_confirmation'])}  •  "
            f"last_checked: {r['last_checked_ts']}",
            style={"color": _MUTED, "fontSize": "12px", "margin": "4px 0"}))
        readiness = str(r.get("readiness_json", "") or "")
        if readiness:
            details.append(html.Details([
                html.Summary("Approval gate readiness",
                             style={"color": _FG, "fontSize": "13px",
                                    "cursor": "pointer"}),
                html.Pre(readiness, style={"color": _MUTED, "fontSize": "11px",
                                           "whiteSpace": "pre-wrap"}),
            ]))
    else:
        details.append(html.P("No approval state recorded yet.",
                              style={"color": _MUTED, "fontSize": "12px"}))

    vs = db.venue_state()
    if not vs.empty:
        details.append(html.Div("Venue readiness", style={
            "color": _FG, "fontSize": "13px", "fontWeight": "600",
            "marginTop": "10px", "marginBottom": "4px"}))
        details.append(_table(vs, 8))

    return html.Div([banner, html.Div(details, style={"marginTop": "12px"})],
                    style={"background": _PANEL, "borderRadius": "12px",
                           "padding": "20px 24px", "border": "1px solid #30363d"})


@app.callback(Output("hero-live", "children"), Input("tick", "n_intervals"))
def _hero_live(_n):
    frames = []
    for v in _live_venues():
        d = db.equity_curve(v)
        if not d.empty:
            frames.append(d[["ts", "equity"]].set_index("ts"))
    if frames:
        merged = pd.concat(frames, axis=1).sort_index().ffill()
        merged.columns = [f"c{i}" for i in range(merged.shape[1])]
        merged["equity"] = merged.sum(axis=1)
        df = merged.reset_index()[["ts", "equity"]]
    else:
        df = pd.DataFrame()
    val, tc, tp, ac, ap = _equity_summary(df)
    return _hero(val, tc, tp, ac, ap, label="Live account value")


@app.callback(Output("stats-live", "children"), Input("tick", "n_intervals"))
def _stats_live(_n):
    td = db.trades(5000)
    if not td.empty and "mode" in td:
        td = td[td["mode"] == "live"]
    else:
        td = td.iloc[0:0] if not td.empty else td
    live_venues = set(_live_venues())
    pos = db.positions()
    n_open = 0
    if not pos.empty and live_venues and "venue" in pos:
        n_open = int(len(pos[pos["venue"].isin(live_venues)]))
    return _stat_cards(td, pd.DataFrame(), n_open)


@app.callback(Output("t-positions-live", "children"), Input("tick", "n_intervals"))
def _positions_live(_n):
    pos = db.positions()
    live_venues = set(_live_venues())
    if pos.empty or not live_venues or "venue" not in pos:
        return html.P("No live positions — live trading is disabled.",
                      style={"color": _MUTED})
    df = pos[pos["venue"].isin(live_venues)]
    if df.empty:
        return html.P("No live positions — live trading is disabled.",
                      style={"color": _MUTED})
    cols = [c for c in ["symbol", "venue", "side", "qty", "avg_price",
                        "notional", "unrealized_pnl"] if c in df]
    d = df[cols].copy()
    for c in ("qty", "avg_price", "notional", "unrealized_pnl"):
        if c in d:
            d[c] = d[c].round(4)
    return _table(d, 10)


@app.callback(Output("t-trades-live", "children"), Input("tick", "n_intervals"))
def _trades_live(_n):
    df = db.trades(TRADE_PAGE * 4)
    if df.empty or "mode" not in df:
        return html.P("No live activity — live trading is disabled.",
                      style={"color": _MUTED})
    df = df[df["mode"] == "live"]
    if df.empty:
        return html.P("No live activity — live trading is disabled.",
                      style={"color": _MUTED})
    return _trade_table(df, "live", 12)


# --- Advanced: chart callbacks ----------------------------------------------

@app.callback(Output("g-equity", "figure"), Input("tick", "n_intervals"))
def _equity(_n):
    df = db.equity_curve("AGGREGATE")
    if df.empty:
        # fall back to summing per-venue if no AGGREGATE rows
        venues = [v for v in db.venues_with_balances() if v != "AGGREGATE"]
        frames = []
        for v in venues:
            d = db.equity_curve(v)
            if not d.empty:
                d = d[["ts", "equity"]].rename(columns={"equity": v})
                frames.append(d.set_index("ts"))
        if frames:
            merged = pd.concat(frames, axis=1).sort_index().ffill()
            merged["equity"] = merged.sum(axis=1)
            df = merged.reset_index()[["ts", "equity"]]
    if df.empty:
        return _empty_fig()
    fig = px.line(df, x="ts", y="equity", markers=False)
    fig.update_traces(line_color=_ACCENT)
    return _style(fig)


@app.callback(Output("g-daily-pnl", "figure"), Input("tick", "n_intervals"))
def _daily_pnl(_n):
    df = db.trades(2000)
    if df.empty or df["pnl"].isna().all():
        return _empty_fig()
    df = df.dropna(subset=["pnl"]).copy()
    df["day"] = pd.to_datetime(df["ts"]).dt.date.astype(str)
    g = df.groupby("day", as_index=False)["pnl"].sum()
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in g["pnl"]]
    fig = go.Figure(go.Bar(x=g["day"], y=g["pnl"], marker_color=colors))
    return _style(fig)


@app.callback(Output("g-drawdown", "figure"), Input("tick", "n_intervals"))
def _drawdown(_n):
    df = db.equity_curve("AGGREGATE")
    if df.empty:
        # derive from per-venue aggregate equity
        venues = [v for v in db.venues_with_balances() if v != "AGGREGATE"]
        frames = []
        for v in venues:
            d = db.equity_curve(v)
            if not d.empty:
                frames.append(d[["ts", "equity"]].rename(columns={"equity": v}).set_index("ts"))
        if frames:
            merged = pd.concat(frames, axis=1).sort_index().ffill()
            eq = merged.sum(axis=1)
            dd = (eq / eq.cummax() - 1.0) * 100.0
            df = pd.DataFrame({"ts": eq.index, "drawdown_pct": dd.values})
    if df.empty:
        return _empty_fig()
    fig = px.area(df, x="ts", y="drawdown_pct")
    fig.update_traces(line_color="#f85149", fillcolor="rgba(248,81,73,0.2)")
    return _style(fig)


@app.callback(Output("g-trade-pnl", "figure"), Input("tick", "n_intervals"))
def _trade_pnl(_n):
    df = db.trades(2000)
    if df.empty or df["pnl"].isna().all():
        return _empty_fig()
    df = df.dropna(subset=["pnl"]).sort_values("id")
    df["cum"] = df["pnl"].cumsum()
    colors = ["#3fb950" if v >= 0 else "#f85149" for v in df["pnl"]]
    fig = go.Figure()
    fig.add_bar(x=df["id"], y=df["pnl"], marker_color=colors, name="trade pnl")
    fig.add_trace(go.Scatter(x=df["id"], y=df["cum"], mode="lines",
                             line_color=_ACCENT, name="cumulative", yaxis="y2"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return _style(fig)


@app.callback(Output("g-calendar", "figure"), Input("tick", "n_intervals"))
def _calendar(_n):
    df = db.trades(2000)
    if df.empty or "outcome" not in df:
        return _empty_fig()
    df = df.dropna(subset=["pnl"]).copy()
    if df.empty:
        return _empty_fig()
    df["dt"] = pd.to_datetime(df["ts"])
    df["dow"] = df["dt"].dt.day_name().str[:3]
    df["hour"] = df["dt"].dt.hour
    pivot = df.pivot_table(index="dow", columns="hour", values="pnl",
                           aggfunc="sum", fill_value=0)
    order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    pivot = pivot.reindex([d for d in order if d in pivot.index])
    fig = go.Figure(go.Heatmap(z=pivot.values, x=[str(c) for c in pivot.columns],
                               y=list(pivot.index), colorscale="RdYlGn",
                               zmid=0))
    return _style(fig)


@app.callback(Output("g-venue-alloc", "figure"), Input("tick", "n_intervals"))
def _venue_alloc(_n):
    df = db.trades(5000)
    if df.empty:
        return _empty_fig()
    g = df.groupby("venue", as_index=False)["notional"].sum()
    fig = px.pie(g, names="venue", values="notional", hole=0.45)
    return _style(fig)


@app.callback(Output("g-exposure", "figure"), Input("tick", "n_intervals"))
def _exposure(_n):
    df = db.positions()
    if df.empty:
        df = db.trades(5000)
        if df.empty:
            return _empty_fig()
        g = df.groupby("symbol", as_index=False)["notional"].sum()
    else:
        g = df.groupby("symbol", as_index=False)["notional"].sum()
    g = g.sort_values("notional", ascending=True)
    fig = go.Figure(go.Bar(x=g["notional"], y=g["symbol"], orientation="h",
                           marker_color=_ACCENT))
    return _style(fig)


@app.callback(Output("g-weights", "figure"), Input("tick", "n_intervals"))
def _weights_chart(_n):
    mo = db.latest_model_outputs()
    if not mo.empty:
        mo = mo.copy()
        mo["label"] = mo["model"].map(_factor_label)
        fig = px.bar(mo, x="label", y="weight", color="confidence",
                     color_continuous_scale="Blues")
        return _style(fig)
    w = db.load_weight_overrides()
    fig = go.Figure(go.Bar(x=[_factor_label(k) for k in w], y=list(w.values()),
                           marker_color=_ACCENT))
    return _style(fig)


@app.callback(Output("g-learning", "figure"), Input("tick", "n_intervals"))
def _learning(_n):
    df = db.param_history(2000)
    if df.empty:
        return _empty_fig()
    df = df.copy()
    for col in ("old_value", "new_value"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["old_value", "new_value"])
    if df.empty:
        return _empty_fig("param changes are non-numeric")
    g = df.groupby("param", as_index=False).agg(before=("old_value", "first"),
                                                after=("new_value", "last"))
    g = g.head(8)
    fig = go.Figure()
    fig.add_bar(x=g["param"], y=g["before"], name="before", marker_color="#8b949e")
    fig.add_bar(x=g["param"], y=g["after"], name="after", marker_color=_ACCENT)
    fig.update_layout(barmode="group")
    return _style(fig)


@app.callback(Output("g-dnn", "figure"), Input("tick", "n_intervals"))
def _dnn(_n):
    # Use model_outputs for the dnn_advisory factor to show advisory confidence/edge.
    df = db.query(
        "SELECT ts, confidence, edge FROM model_outputs WHERE model='dnn_advisory' "
        "ORDER BY id"
    )
    if df.empty:
        return _empty_fig()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["confidence"], mode="lines",
                             name="confidence", line_color=_ACCENT))
    fig.add_trace(go.Scatter(x=df.index, y=df["edge"], mode="lines",
                             name="expected edge", line_color="#3fb950",
                             yaxis="y2"))
    fig.update_layout(yaxis2=dict(overlaying="y", side="right", showgrid=False))
    return _style(fig)


@app.callback(Output("g-whale-hist", "figure"), Input("tick", "n_intervals"))
def _whale_hist(_n):
    df = db.whale_signal_history(1000)
    if df.empty:
        return _empty_fig("no whale signal history (run demo to populate)")
    df = df.sort_values("ts")
    fig = px.line(df, x="ts", y="whale_bias", color="symbol", markers=True)
    return _style(fig)


@app.callback(Output("g-whale-agree", "figure"), Input("tick", "n_intervals"))
def _whale_agree(_n):
    df = db.whale_signal_history(1000)
    if df.empty or "agreed_with_trade" not in df:
        return _empty_fig("no whale agreement data yet")
    df = df.dropna(subset=["agreed_with_trade", "trade_outcome"])
    if df.empty:
        return _empty_fig("no whale agreement data yet")
    df["agreed"] = df["agreed_with_trade"].map({1: "agreed", 0: "disagreed"})
    g = df.groupby(["agreed", "trade_outcome"], as_index=False).size()
    fig = px.bar(g, x="agreed", y="size", color="trade_outcome", barmode="group",
                 color_discrete_map={"win": "#3fb950", "loss": "#f85149",
                                     "open": "#8b949e"})
    return _style(fig)


# --- Advanced: table callbacks ----------------------------------------------

@app.callback(Output("t-verdicts", "children"), Input("tick", "n_intervals"))
def _verdicts(_n):
    df = db.latest_model_outputs()
    if df.empty:
        return html.P("no model outputs yet", style={"color": _MUTED})
    df = df.copy()
    df["model"] = df["model"].map(_factor_label)
    for c in ("confidence", "edge", "weight"):
        df[c] = df[c].round(4)
    return _table(df[["model", "verdict", "confidence", "edge", "weight"]], 8)


@app.callback(Output("t-approval", "children"), Input("tick", "n_intervals"))
def _approval(_n):
    df = db.approval_state()
    if df.empty:
        return html.P("no approval state", style={"color": _MUTED})
    r = df.iloc[0]
    live = int(r["live_enabled"]) == 1
    badge = ("LIVE ENABLED", "#f85149") if live else ("LIVE DISABLED (safe default)", "#3fb950")
    return html.Div([
        html.Div(badge[0], style={"background": badge[1], "color": "white",
                                  "padding": "6px 12px", "borderRadius": "6px",
                                  "display": "inline-block", "fontWeight": "bold",
                                  "marginBottom": "10px"}),
        html.P(f"manual_confirmation: {int(r['manual_confirmation'])}",
               style={"color": _FG, "fontSize": "13px", "margin": "2px"}),
        html.P(f"last_checked: {r['last_checked_ts']}",
               style={"color": _MUTED, "fontSize": "12px", "margin": "2px"}),
        html.Pre(str(r.get("readiness_json", "")),
                 style={"color": _MUTED, "fontSize": "11px",
                        "whiteSpace": "pre-wrap"}),
    ])


@app.callback(Output("t-venues", "children"), Input("tick", "n_intervals"))
def _venues(_n):
    df = db.venue_state()
    if df.empty:
        return html.P("no venue state", style={"color": _MUTED})
    return _table(df, 8)


@app.callback(Output("t-registry", "children"), Input("tick", "n_intervals"))
def _registry(_n):
    df = db.model_registry()
    if df.empty:
        return html.P("no registry entries (champion auto-trains on first run)",
                      style={"color": _MUTED})

    # Surface training provenance (synthetic | real-data) as its own column so a
    # real-data challenger is visibly distinct from the synthetic bootstrap
    # champion. Legacy rows with no provenance are shown as "synthetic".
    def _prov(mj):
        try:
            return json.loads(mj).get("provenance", "synthetic")
        except (TypeError, ValueError):
            return "synthetic"

    if "metrics_json" in df.columns:
        prov = df["metrics_json"].map(_prov)
        df.insert(df.columns.get_loc("metrics_json"), "provenance", prov)
    return _table(df, 6)


@app.callback(Output("t-trades", "children"), Input("tick", "n_intervals"))
def _trades(_n):
    df = db.trades(TRADE_PAGE * 4)
    if df.empty:
        return html.P("no trades yet", style={"color": _MUTED})
    return _trade_table(df, "all", 12)


@app.callback(Output("t-positions", "children"), Input("tick", "n_intervals"))
def _positions(_n):
    df = db.positions()
    if df.empty:
        return html.P("no open positions", style={"color": _MUTED})
    for c in ("qty", "avg_price", "notional", "unrealized_pnl"):
        df[c] = df[c].round(4)
    return _table(df, 10)


@app.callback(Output("t-blocked", "children"), Input("tick", "n_intervals"))
def _blocked(_n):
    df = db.blocked_trades(300)
    if df.empty:
        return html.P("no blocked trades", style={"color": _MUTED})
    if "qty" in df:
        df["qty"] = df["qty"].round(2)
    return _table(df, 12)


@app.callback(Output("t-weighthist", "children"), Input("tick", "n_intervals"))
def _weighthist(_n):
    df = db.weight_change_history(300)
    if df.empty:
        return html.P("no weight changes", style={"color": _MUTED})
    for c in ("old_weight", "new_weight"):
        df[c] = df[c].round(4)
    return _table(df, 12)


@app.callback(Output("t-paramhist", "children"), Input("tick", "n_intervals"))
def _paramhist(_n):
    df = db.param_history(300)
    if df.empty:
        return html.P("no param history", style={"color": _MUTED})
    return _table(df, 12)


@app.callback(Output("t-whaleact", "children"), Input("tick", "n_intervals"))
def _whaleact(_n):
    df = db.whale_activity(300)
    if df.empty:
        return html.P("no whale activity (run demo to populate)",
                      style={"color": _MUTED})
    if "value_usd" in df:
        df["value_usd"] = df["value_usd"].round(0)
    return _table(_fmt_ts_col(df), 12)


@app.callback(Output("t-events", "children"), Input("tick", "n_intervals"))
def _events(_n):
    df = db.events(300)
    if df.empty:
        return html.P("no events", style={"color": _MUTED})
    return _table(_fmt_ts_col(df), 15)


# --- Weight control panel (the UI's only writer) ----------------------------

@app.callback(
    Output("w-status", "children"),
    Input("w-apply", "n_clicks"),
    Input("w-reset", "n_clicks"),
    State({"type": "w-input", "factor": dash.ALL}, "value"),
    State({"type": "w-input", "factor": dash.ALL}, "id"),
    State({"type": "w-lock", "factor": dash.ALL}, "value"),
    State({"type": "w-lock", "factor": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def _apply_weights(_apply, _reset, values, value_ids, lock_vals, lock_ids):
    trigger = ctx.triggered_id
    if trigger == "w-reset":
        locks = {k: False for k in db.DEFAULT_WEIGHTS}
        db.save_weight_overrides(dict(db.DEFAULT_WEIGHTS), locks, source="reset")
        return "Reset to config defaults and normalized."

    weights = {}
    for val, ident in zip(values, value_ids):
        weights[ident["factor"]] = float(val) if val is not None else 0.0
    locks = {}
    for lv, ident in zip(lock_vals, lock_ids):
        locks[ident["factor"]] = "locked" in (lv or [])
    db.save_weight_overrides(weights, locks, source="manual")
    norm = db.normalize(weights)
    summary = ", ".join(f"{_factor_label(k)}={v:.2f}" for k, v in norm.items())
    return f"Applied (normalized): {summary}"


@app.callback(Output("w-live", "children"), Input("tick", "n_intervals"))
def _auto_tune(n):
    """Run the adaptive tuner on a slow tick multiple and render the live panel.

    Locked/manual factors always win — they are excluded from adjustment by the
    tuner. The displayed values are the effective weights (post-persist), so the
    panel visibly tracks what the bot learns.
    """
    try:
        if n and n % AUTO_TUNE_EVERY == 0:
            res = weight_tuner.run_auto_tune()
            weights, accs, locks = res["weights"], res["accuracies"], res["locks"]
        else:
            weights = db.load_weight_overrides()
            locks = db.load_locks()
            accs = weight_tuner.compute_factor_accuracy()
    except Exception:
        weights, locks, accs = db.load_weight_overrides(), db.load_locks(), {}

    rows = []
    for f in db.DEFAULT_WEIGHTS:
        a = accs.get(f)
        rows.append({
            "factor": _factor_label(f),
            "effective weight": round(float(weights.get(f, 0.0)), 3),
            "recent accuracy": (f"{a * 100:.0f}%" if a is not None else "—"),
            "status": "locked / manual" if locks.get(f) else "auto",
        })
    df = pd.DataFrame(rows, columns=["factor", "effective weight",
                                     "recent accuracy", "status"])
    return _table(df, 8)


# --- Accounts / Connections callbacks ---------------------------------------

def _status_table() -> dash_table.DataTable:
    rows = []
    for s in creds.list_status():
        scope = s["group_label"]
        if s["mode"]:
            scope += f" / {s['mode']}"
        rows.append({
            "connection": scope,
            "field": s["label"],
            "status": ("in-app" if s["source"] == "in-app"
                       else "from-env" if s["source"] == "env" else "missing"),
            "value": s["masked"] or "—",
        })
    df = pd.DataFrame(rows, columns=["connection", "field", "status", "value"])
    return _table(df, 14)


@app.callback(
    Output("cred-save-status", "children"),
    Output("cred-status", "children"),
    Input("cred-save", "n_clicks"),
    State({"type": "cred-input", "name": dash.ALL}, "value"),
    State({"type": "cred-input", "name": dash.ALL}, "id"),
    prevent_initial_call=True,
)
def _save_credentials(_n, values, ids):
    saved, cleared = 0, 0
    for val, ident in zip(values, ids):
        name = ident["name"]
        spec = creds.CREDENTIALS.get(name)
        if not spec:
            continue
        text = (val or "").strip()
        # Blank secret input means "keep existing"; blank non-secret clears it.
        if text == "":
            if not spec.secret and creds.get_credential_source(name) == "in-app":
                creds.set_credential(name, None)
                cleared += 1
            continue
        creds.set_credential(name, text)
        saved += 1
    msg = f"Saved {saved} credential(s)" + (f", cleared {cleared}" if cleared else "")
    return msg + " (encrypted at rest).", _status_table()


@app.callback(Output("cred-status", "children", allow_duplicate=True),
              Input("tick", "n_intervals"), prevent_initial_call="initial_duplicate")
def _refresh_status(_n):
    return _status_table()


@app.callback(
    Output("cred-test-status", "children"),
    Input("cred-test", "n_clicks"),
    State("cred-test-target", "value"),
    prevent_initial_call=True,
)
def _test_connection(_n, target):
    group, _, mode = (target or "").partition(":")
    mode = mode or None
    result = creds.validate_connection(group, mode)
    # For a venue LIVE test, reflect resolved readiness into venue_state so the
    # C++ approval gate (live_requires_connected_credentials) sees it. Never
    # enables live by itself.
    note = ""
    if mode == "live" and group in {"alpaca", "coinbase", "ibkr", "polymarket"}:
        db.set_venue_credentials_connected(group, result["ok"])
        note = "  •  venue_state.credentials_connected updated for approval gate"
    color = "#3fb950" if result["ok"] else "#f85149"
    icon = "✓" if result["ok"] else "✗"
    return html.Span(f"{icon} {result['message']}{note}", style={"color": color})


# --- Fullscreen chart modal (shared by every chart's Expand button) ---------

_GRAPH_TITLES = {
    "g-equity-paper": "Portfolio value over time",
    "g-equity": "Equity Curve (Aggregate)",
    "g-daily-pnl": "Daily Realized PnL",
    "g-drawdown": "Drawdown %",
    "g-trade-pnl": "Trade-by-Trade PnL",
    "g-calendar": "Win / Loss Calendar",
    "g-venue-alloc": "Venue Allocation",
    "g-exposure": "Exposure by Symbol / Market",
    "g-weights": "Factor-Weight Contribution",
    "g-learning": "Learning: Param Before/After",
    "g-dnn": "DNN / RL Performance",
    "g-whale-hist": "Whale Signal History",
    "g-whale-agree": "Whale Agreement vs Outcome",
}


@app.callback(
    Output("chart-modal", "style"),
    Output("modal-graph", "figure"),
    Output("modal-title", "children"),
    Output("modal-current", "data"),
    Input({"type": "expand", "graph": ALL}, "n_clicks"),
    Input("modal-close", "n_clicks"),
    Input("tick", "n_intervals"),
    State("modal-current", "data"),
    [State(gid, "figure") for gid in GRAPH_IDS],
    prevent_initial_call=True,
)
def _chart_modal_cb(_expands, _close, _tick, current, *graph_figs):
    figs = dict(zip(GRAPH_IDS, graph_figs))
    trigger = ctx.triggered_id

    if trigger == "modal-close":
        return _MODAL_HIDDEN, dash.no_update, dash.no_update, None

    if isinstance(trigger, dict) and trigger.get("type") == "expand":
        # Ignore the synthetic n_clicks=0 fired when the buttons first register.
        if not any(_expands or []):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update
        gid = trigger.get("graph")
        fig = figs.get(gid) or _empty_fig()
        return _MODAL_SHOWN, fig, _GRAPH_TITLES.get(gid, gid), gid

    # tick: keep the modal live while open; never auto-open it.
    if current:
        fig = figs.get(current) or _empty_fig()
        return _MODAL_SHOWN, fig, _GRAPH_TITLES.get(current, current), current
    return _MODAL_HIDDEN, dash.no_update, dash.no_update, dash.no_update


@app.callback(
    Output("trade-modal", "style"),
    Output("trade-modal-body", "children"),
    Input({"type": "trade-tbl", "scope": ALL}, "active_cell"),
    Input("trade-modal-close", "n_clicks"),
    State({"type": "trade-tbl", "scope": ALL}, "derived_viewport_data"),
    State({"type": "trade-tbl", "scope": ALL}, "id"),
    prevent_initial_call=True,
)
def _trade_modal_cb(active_cells, _close, viewports, ids):
    trigger = ctx.triggered_id
    if trigger == "trade-modal-close":
        return _MODAL_HIDDEN, dash.no_update

    if isinstance(trigger, dict) and trigger.get("type") == "trade-tbl":
        # Locate the table that fired among the pattern-matched group.
        idx = next((i for i, ident in enumerate(ids) if ident == trigger), None)
        if idx is None:
            return dash.no_update, dash.no_update
        cell = active_cells[idx] if idx < len(active_cells) else None
        vp = viewports[idx] if idx < len(viewports) else None
        if not cell or not vp:
            return dash.no_update, dash.no_update
        row = cell.get("row")
        if row is None or row >= len(vp):
            return dash.no_update, dash.no_update
        tid = vp[row].get("id")
        if tid is None:
            return dash.no_update, dash.no_update
        return _MODAL_SHOWN, _trade_detail(tid)

    return dash.no_update, dash.no_update


# --- Level 1 risk-gate editor (writes config + event log) -------------------

@app.callback(
    Output("l1-status", "children"),
    Output("l1-current", "children"),
    Output("l1-confirm", "value"),
    Input("l1-apply", "n_clicks"),
    State("l1-confirm", "value"),
    State({"type": "l1-input", "param": ALL}, "value"),
    State({"type": "l1-input", "param": ALL}, "id"),
    prevent_initial_call=True,
)
def _l1_apply(_n, confirm, values, ids):
    err = lambda m: (html.Span(f"✗ {m}", style={"color": _RED}),
                     _l1_current_table(), dash.no_update)
    try:
        current = cfg_editor.read_l1_values(_CFG_PATH)
    except Exception as exc:  # noqa: BLE001
        return err(f"could not read config: {exc}")

    # Collect only the params the user actually changed.
    changes = {}
    for val, ident in zip(values, ids):
        key = ident["param"]
        if val is None or val == "":
            continue
        try:
            new_typed = cfg_editor._coerce(key, val)
        except Exception as exc:  # noqa: BLE001
            return err(str(exc))
        if key not in current or current[key] != new_typed:
            changes[key] = new_typed

    if not changes:
        return (html.Span("No changes to apply.", style={"color": _MUTED}),
                _l1_current_table(), dash.no_update)

    if (confirm or "").strip() != "CONFIRM":
        return err('type "CONFIRM" in the confirmation box to apply changes')

    problems = cfg_editor.validate_l1_changes(current, changes)
    if problems:
        return err("; ".join(problems))

    try:
        written = cfg_editor.write_l1_values(changes, _CFG_PATH)
    except Exception as exc:  # noqa: BLE001
        return err(f"write failed: {exc}")

    # Audit every applied change to the event log (old -> new + timestamp).
    logged = 0
    for key, new_v in written.items():
        old_v = current.get(key, "—")
        msg = (f"Level 1 risk param '{key}' changed {old_v} -> {new_v} "
               f"via dashboard (typed-confirm)")
        if db.append_event("config_change", msg, severity="warn",
                           payload_json=None):
            logged += 1

    summary = ", ".join(f"{k}: {current.get(k, '—')}→{v}"
                        for k, v in written.items())
    note = "" if logged == len(written) else " (event log unavailable — DB read-only?)"
    return (html.Span(f"✓ Applied {len(written)} change(s) to config and logged "
                      f"to event log{note}: {summary}", style={"color": _GREEN}),
            _l1_current_table(), "")


@app.callback(Output("l1-current", "children", allow_duplicate=True),
              Input("tick", "n_intervals"),
              prevent_initial_call="initial_duplicate")
def _l1_refresh(_n):
    return _l1_current_table()


if __name__ == "__main__":
    host = os.environ.get("MAL_DASH_HOST", "127.0.0.1")
    port = int(os.environ.get("MAL_DASH_PORT", "8050"))
    app.run(host=host, port=port, debug=False)
