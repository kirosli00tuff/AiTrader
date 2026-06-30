# Broker-Style Dashboard Redesign Brief

Redesign the Plotly Dash dashboard in `ui/app.py` into a clean, beginner-friendly
layout modeled on big online brokers (Robinhood / Schwab / Wealthsimple). The
goal: a novice trader should instantly understand their portfolio value and
performance, with advanced AI/safety detail tucked away separately.

## Hard constraints (do NOT break these)
- **Reuse the existing data layer `ui/db.py` as-is.** Do not change its function
  signatures. All numbers must come from the same SQLite tables/functions
  already used (equity_curve(venue), trades(), positions(), blocked_trades(),
  approval_state(), venue_state(), whale_*, model_*, weight/param history, events).
- **Preserve ALL existing functionality and data** — every panel/table/chart that
  exists today must still be reachable somewhere (most move to the Advanced page).
  Keep the model-weight control panel and the Accounts/Connections page fully
  working (same callback Input/Output ids where possible; if you rename ids,
  update both layout and callbacks so nothing breaks).
- **Keep the offline mock-data path working** (db may be empty -> show friendly
  empty states / zeros, never crash).
- **Safety posture unchanged**: live trading disabled by default; the Live page
  must clearly reflect the approval gate. Do not weaken any gate.
- Dark theme, consistent with current colors (panel #161b22-ish, green #3fb950
  for gains, red #f85149 for losses, accent on a near-black bg #0d1117).
- The app is hosted in a native desktop window (ui/desktop.py) — keep it a single
  Dash app served at one URL. Multi-page via `dcc.Tabs` or `dcc.Location` routing
  is fine (Tabs is simplest and already in use).

## Page structure (top nav: 4 tabs/pages)
1. **Paper** (default landing page) — the main broker-style view, paper account.
2. **Live** — same layout but a LOCKED state by default (see below).
3. **Advanced** — ALL the dense/technical panels live here (see list).
4. **Accounts / Connections** — keep the existing accounts page basically as-is.

## Paper page layout (top -> bottom, scrollable)
1. **Big portfolio header (hero):**
   - Very large total equity number (e.g. `$10,482.55`), the single most
     prominent thing on the page.
   - **Stacked beneath it:** today's change in `$` and `%` (green/red w/ up/down
     arrow), AND all-time P/L in `$` and `%` since the start of the equity curve.
   - Data: latest `equity_curve("AGGREGATE")` row for the value; today's change =
     latest equity minus first equity of the current day (or previous close);
     all-time = latest minus first equity row. Compute robustly; if <2 rows, show
     `$0.00 (0.00%)` not an error.
2. **Row of simple summary stat cards** (big readable numbers, label underneath):
   - Total P/L ($), Win rate (%), # Trades, Max drawdown (%). Optionally Open
     positions count. Derive from trades()/equity_curve()/positions(). Color P/L
     green/red.
3. **Equity curve chart** (clean line/area, green when up). This is the main chart.
4. **Open Positions** table (holdings) — simple columns: symbol, qty, avg price,
   market value/notional, unrealized P/L (color-coded).
5. **Recent Trades** table (activity feed) — time, symbol, side, qty, price, P/L,
   outcome. Filter to `mode == 'paper'` for this page.
6. (Optional, lower) a compact daily P/L bar and drawdown mini-chart.
Keep it breezy and spacious — generous spacing, large fonts, few words.

## Live page
- Same visual skeleton as Paper, BUT default state is **locked**: a clear banner
  / overlay card saying live (real-money) trading is **disabled by default** and
  this is paper-first software. Show the **approval gate** UI (reads
  approval_state(); the existing live-approval readiness logic) so the user can
  see what's required to enable live, and where live would be enabled.
- Pull live numbers from `mode == 'live'` trades and live venue balances; if none
  (the normal case), show zeros / "No live activity — live trading is disabled."
- Do not actually enable live trading from here beyond whatever the existing
  approval mechanism already does. Just surface state clearly.

## Advanced page (move existing dense panels here)
Put ALL of these here (they exist today on the Control Board): AI/model verdict
board, model-weight control panel (the sliders + status), DNN/RL advisory chart,
whale activity + whale-agreement charts, model registry (champion/challenger),
venue state table, blocked/rejected trades (RiskGate), weight-change history,
Layer-2 param-change history, the event/audit log, venue allocation & exposure,
learning curve, win/loss calendar heatmap. Group them with clear section
sub-headers. This page can stay dense — it's for power users.

## Implementation notes
- Refactor `_dashboard_tab` into `_paper_page()`, `_live_page()`,
  `_advanced_page()` builders; keep `_accounts_tab()`.
- Add reusable helpers: `_hero(value, today_chg, alltime_chg)` and
  `_stat_card(label, value, color)`.
- The auto-refresh `dcc.Interval(id="tick")` should keep driving updates. New
  hero/cards need their own callbacks (Output children, Input tick). Existing
  graph/table callbacks can be reused; just make sure their target ids exist on
  whichever page now hosts them. NOTE: Dash callbacks whose Output id is not
  present in the initial layout will error — since all pages' content is built
  into the Tabs children at load (current pattern), keep that pattern so every
  id exists. Do NOT lazy-render tab contents unless you also guard callbacks.
- Money formatting: helper `_fmt_money(x)` -> `$1,234.56`; `_fmt_pct(x)`; arrows
  ▲/▼ and green/red by sign.
- Verify: `cd ui && python -c "import app"` must succeed and report the callback
  count; the app must build its layout without exceptions. Run repo tests:
  ctest (3 expected) and pytest (34 expected) must stay green.
- Keep everything in `ui/app.py` (plus small additions to `ui/db.py` ONLY if a
  genuinely new query is needed — prefer composing existing functions).
