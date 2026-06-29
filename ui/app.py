"""Market AI Lab — Plotly Dash control board.

Reads the shared SQLite database (single source of truth) and renders every
panel/chart/table required by the build spec:

  Performance        equity curve, daily PnL, drawdown, trade-by-trade PnL,
                     win/loss calendar heatmap
  Allocation         venue allocation, exposure by symbol/market
  Models             verdict-comparison board, factor-weight contribution,
                     weight-change history, adjustable weight control panel
  Learning           Layer-2 param-change history, before/after chart,
                     DNN/RL performance chart, model registry
  Whale              recent whale activity, whale-signal history,
                     whale-agreement-vs-outcome
  Trading            recent trades, open positions, blocked/rejected trades
  Safety             live-approval readiness, venue state, event log

The model-weight control panel is fully adjustable (numeric input + lock +
reset). Adjusting weights only re-blends ADVISORY factors; it can never weaken
the deterministic Layer-1 RiskGate.
"""
from __future__ import annotations

import os
import sys

import dash
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml
from dash import Input, Output, State, dash_table, dcc, html, ctx

import db

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


def _load_dashboard_cfg() -> dict:
    try:
        with open(_CFG_PATH) as fh:
            cfg = yaml.safe_load(fh) or {}
        return cfg.get("dashboard", {}) or {}
    except Exception:
        return {}


_DCFG = _load_dashboard_cfg()
REFRESH_MS = int(_DCFG.get("dashboard_refresh_seconds", 5)) * 1000
TRADE_PAGE = int(_DCFG.get("trade_feed_page_size", 50))

FACTOR_LABELS = {
    "llm_primary": "LLM Primary",
    "llm_secondary": "LLM Secondary",
    "llm_tertiary": "LLM Tertiary",
    "rule_based": "Rule-Based",
    "dnn_rl": "DNN / RL",
    "whale_signal": "Whale Signal",
}

_BG = "#0e1117"
_PANEL = "#161b22"
_FG = "#e6edf3"
_ACCENT = "#2f81f7"

app = dash.Dash(__name__, title="Market AI Lab — Control Board",
                suppress_callback_exceptions=True)
server = app.server  # for gunicorn / WSGI if ever needed


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


def _empty_fig(msg: str = "no data yet") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False,
                       font={"color": "#8b949e", "size": 13})
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


# --- Static layout ----------------------------------------------------------

def _weight_controls() -> html.Div:
    weights = db.load_weight_overrides()
    locks = db.load_locks()
    rows = []
    for factor, label in FACTOR_LABELS.items():
        rows.append(html.Div([
            html.Span(label, style={"width": "120px", "display": "inline-block",
                                    "color": _FG, "fontSize": "13px"}),
            dcc.Input(id={"type": "w-input", "factor": factor}, type="number",
                      min=0, max=1, step=0.01, value=round(weights[factor], 3),
                      style={"width": "80px", "marginRight": "10px",
                             "background": "#0d1117", "color": _FG,
                             "border": "1px solid #30363d"}),
            dcc.Checklist(id={"type": "w-lock", "factor": factor},
                          options=[{"label": " lock", "value": "locked"}],
                          value=["locked"] if locks[factor] else [],
                          style={"display": "inline-block", "color": "#8b949e",
                                 "fontSize": "12px"}),
        ], style={"marginBottom": "6px"}))
    return html.Div([
        html.P("Adjust ensemble weights (auto-normalized). Advisory blend only — "
               "never affects the Layer-1 RiskGate.",
               style={"color": "#8b949e", "fontSize": "11px"}),
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
        html.Div(id="w-status", style={"color": "#3fb950", "fontSize": "12px",
                                       "marginTop": "6px"}),
    ])


_dashboard_tab = html.Div([
    # Row: performance
    html.Div([
        _panel("Equity Curve (Aggregate)", dcc.Graph(id="g-equity")),
        _panel("Daily Realized PnL", dcc.Graph(id="g-daily-pnl")),
        _panel("Drawdown %", dcc.Graph(id="g-drawdown")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("Trade-by-Trade PnL", dcc.Graph(id="g-trade-pnl")),
        _panel("Win / Loss Calendar", dcc.Graph(id="g-calendar")),
        _panel("Venue Allocation", dcc.Graph(id="g-venue-alloc")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("Exposure by Symbol / Market", dcc.Graph(id="g-exposure")),
        _panel("Factor-Weight Contribution", dcc.Graph(id="g-weights")),
        _panel("Learning: Param Before/After", dcc.Graph(id="g-learning")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("DNN / RL Performance", dcc.Graph(id="g-dnn")),
        _panel("Whale Signal History", dcc.Graph(id="g-whale-hist")),
        _panel("Whale Agreement vs Outcome", dcc.Graph(id="g-whale-agree")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    # Row: model verdict board + weight control
    html.Div([
        _panel("Model Verdict Board (verdict / confidence / edge / weight)",
               html.Div(id="t-verdicts")),
        _panel("Model-Weight Control Panel", _weight_controls()),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    # Row: safety / approval
    html.Div([
        _panel("Live-Approval Readiness", html.Div(id="t-approval")),
        _panel("Venue State", html.Div(id="t-venues")),
        _panel("Model Registry (champion/challenger)", html.Div(id="t-registry")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    # Row: tables
    html.Div([
        _panel("Recent Trades", html.Div(id="t-trades")),
        _panel("Open Positions", html.Div(id="t-positions")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("Blocked / Rejected Trades (RiskGate)", html.Div(id="t-blocked")),
        _panel("Weight-Change History", html.Div(id="t-weighthist")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("Layer-2 Param-Change History", html.Div(id="t-paramhist")),
        _panel("Recent Whale Activity", html.Div(id="t-whaleact")),
    ], style={"display": "flex", "flexWrap": "wrap"}),

    html.Div([
        _panel("Event Log (append-only audit)", html.Div(id="t-events")),
    ], style={"display": "flex", "flexWrap": "wrap"}),
])


# --- Accounts / Connections page --------------------------------------------

VENUE_GROUPS = [("alpaca", "Alpaca"), ("binance", "Binance"),
                ("ibkr", "IBKR"), ("polymarket", "Polymarket")]
SOURCE_GROUPS = [("apify", "Apify"), ("whale_alert", "Whale Alert"),
                 ("sec_api", "SEC API")]


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
                                     "color": "#8b949e", "fontSize": "12px"}),
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
            tcolor = "#3fb950" if mode == "paper" else "#f85149"
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
                   style={"color": "#8b949e", "fontSize": "12px"}),
            html.P("Live trading stays DISABLED by default; saving live keys only "
                   "makes them resolvable for the approval gate — it does not "
                   "enable live.",
                   style={"color": "#d29922", "fontSize": "12px"}),
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
                      style={"color": "#3fb950", "fontSize": "12px"}),
        ], style={"padding": "8px 16px"}),

        html.Div([
            _panel("Connection Status (configured-in-app / from-env / missing)",
                   html.Div(id="cred-status")),
            _panel("Test / Validate Connection", html.Div([
                html.P("Offline-safe validator: checks that the required "
                       "credentials for the selection resolve (no network call).",
                       style={"color": "#8b949e", "fontSize": "11px"}),
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


app.layout = html.Div([
    dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0),
    html.Div([
        html.H1("Market AI Lab — Control Board",
                style={"color": _FG, "margin": "0", "fontSize": "22px"}),
        html.Span(id="header-status",
                  style={"color": "#8b949e", "fontSize": "13px",
                         "marginLeft": "16px"}),
    ], style={"padding": "14px 22px", "background": _PANEL,
              "borderBottom": f"2px solid {_ACCENT}",
              "display": "flex", "alignItems": "baseline"}),
    dcc.Tabs(id="main-tabs", value="dash", children=[
        dcc.Tab(label="Control Board", value="dash", children=_dashboard_tab,
                style={"background": _BG, "color": _FG, "border": "none"},
                selected_style={"background": _PANEL, "color": _ACCENT,
                                "border": "none"}),
        dcc.Tab(label="Accounts / Connections", value="accounts",
                children=_accounts_tab(),
                style={"background": _BG, "color": _FG, "border": "none"},
                selected_style={"background": _PANEL, "color": _ACCENT,
                                "border": "none"}),
    ]),
], style={"background": _BG, "minHeight": "100vh", "fontFamily":
          "system-ui, sans-serif", "paddingBottom": "30px"})


# --- Chart callbacks --------------------------------------------------------

@app.callback(Output("header-status", "children"), Input("tick", "n_intervals"))
def _header(_n):
    if not db.db_exists():
        return "⚠ database not found — run ops/demo.py to seed it"
    ap = db.approval_state()
    live = "ENABLED" if (not ap.empty and int(ap.iloc[0]["live_enabled"]) == 1) else "DISABLED (safe default)"
    tr = db.trades(1)
    last = tr.iloc[0]["ts"] if not tr.empty else "—"
    return f"live trading: {live}  •  last trade: {last}"


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
        mo["label"] = mo["model"].map(lambda m: FACTOR_LABELS.get(m, m))
        fig = px.bar(mo, x="label", y="weight", color="confidence",
                     color_continuous_scale="Blues")
        return _style(fig)
    w = db.load_weight_overrides()
    fig = go.Figure(go.Bar(x=[FACTOR_LABELS[k] for k in w], y=list(w.values()),
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
    # Use model_outputs for the dnn_rl factor to show advisory confidence/edge.
    df = db.query(
        "SELECT ts, confidence, edge FROM model_outputs WHERE model='dnn_rl' "
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


# --- Table callbacks --------------------------------------------------------

@app.callback(Output("t-verdicts", "children"), Input("tick", "n_intervals"))
def _verdicts(_n):
    df = db.latest_model_outputs()
    if df.empty:
        return html.P("no model outputs yet", style={"color": "#8b949e"})
    df = df.copy()
    df["model"] = df["model"].map(lambda m: FACTOR_LABELS.get(m, m))
    for c in ("confidence", "edge", "weight"):
        df[c] = df[c].round(4)
    return _table(df[["model", "verdict", "confidence", "edge", "weight"]], 8)


@app.callback(Output("t-approval", "children"), Input("tick", "n_intervals"))
def _approval(_n):
    df = db.approval_state()
    if df.empty:
        return html.P("no approval state", style={"color": "#8b949e"})
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
               style={"color": "#8b949e", "fontSize": "12px", "margin": "2px"}),
        html.Pre(str(r.get("readiness_json", "")),
                 style={"color": "#8b949e", "fontSize": "11px",
                        "whiteSpace": "pre-wrap"}),
    ])


@app.callback(Output("t-venues", "children"), Input("tick", "n_intervals"))
def _venues(_n):
    df = db.venue_state()
    if df.empty:
        return html.P("no venue state", style={"color": "#8b949e"})
    return _table(df, 8)


@app.callback(Output("t-registry", "children"), Input("tick", "n_intervals"))
def _registry(_n):
    df = db.model_registry()
    if df.empty:
        return html.P("no registry entries (champion auto-trains on first run)",
                      style={"color": "#8b949e"})
    return _table(df, 6)


@app.callback(Output("t-trades", "children"), Input("tick", "n_intervals"))
def _trades(_n):
    df = db.trades(TRADE_PAGE * 4)
    if df.empty:
        return html.P("no trades yet", style={"color": "#8b949e"})
    for c in ("qty", "price", "notional", "pnl", "combined_conf", "combined_edge"):
        if c in df:
            df[c] = df[c].round(4)
    return _table(df.drop(columns=["market"], errors="ignore"), 12)


@app.callback(Output("t-positions", "children"), Input("tick", "n_intervals"))
def _positions(_n):
    df = db.positions()
    if df.empty:
        return html.P("no open positions", style={"color": "#8b949e"})
    for c in ("qty", "avg_price", "notional", "unrealized_pnl"):
        df[c] = df[c].round(4)
    return _table(df, 10)


@app.callback(Output("t-blocked", "children"), Input("tick", "n_intervals"))
def _blocked(_n):
    df = db.blocked_trades(300)
    if df.empty:
        return html.P("no blocked trades", style={"color": "#8b949e"})
    if "qty" in df:
        df["qty"] = df["qty"].round(2)
    return _table(df, 12)


@app.callback(Output("t-weighthist", "children"), Input("tick", "n_intervals"))
def _weighthist(_n):
    df = db.weight_change_history(300)
    if df.empty:
        return html.P("no weight changes", style={"color": "#8b949e"})
    for c in ("old_weight", "new_weight"):
        df[c] = df[c].round(4)
    return _table(df, 12)


@app.callback(Output("t-paramhist", "children"), Input("tick", "n_intervals"))
def _paramhist(_n):
    df = db.param_history(300)
    if df.empty:
        return html.P("no param history", style={"color": "#8b949e"})
    return _table(df, 12)


@app.callback(Output("t-whaleact", "children"), Input("tick", "n_intervals"))
def _whaleact(_n):
    df = db.whale_activity(300)
    if df.empty:
        return html.P("no whale activity (run demo to populate)",
                      style={"color": "#8b949e"})
    if "value_usd" in df:
        df["value_usd"] = df["value_usd"].round(0)
    return _table(df, 12)


@app.callback(Output("t-events", "children"), Input("tick", "n_intervals"))
def _events(_n):
    df = db.events(300)
    if df.empty:
        return html.P("no events", style={"color": "#8b949e"})
    return _table(df, 15)


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
    summary = ", ".join(f"{FACTOR_LABELS[k]}={v:.2f}" for k, v in norm.items())
    return f"Applied (normalized): {summary}"


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
    if mode == "live" and group in {"alpaca", "binance", "ibkr", "polymarket"}:
        db.set_venue_credentials_connected(group, result["ok"])
        note = "  •  venue_state.credentials_connected updated for approval gate"
    color = "#3fb950" if result["ok"] else "#f85149"
    icon = "✓" if result["ok"] else "✗"
    return html.Span(f"{icon} {result['message']}{note}", style={"color": color})


if __name__ == "__main__":
    host = os.environ.get("MAL_DASH_HOST", "127.0.0.1")
    port = int(os.environ.get("MAL_DASH_PORT", "8050"))
    app.run(host=host, port=port, debug=False)
