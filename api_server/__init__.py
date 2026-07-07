"""Thin read-only FastAPI backend for the React trading GUI.

The C++ core is the sole writer of the operational SQLite tables. This backend
reads those tables read-only and serves them to the React frontend in web/. It
never writes an operational table. The only write path is credential entry,
which goes through the existing encrypted keystore in account_manager, never a
YAML file and never a log line. It binds loopback only.

The existing Plotly Dash UI in ui/ stays in place as a fallback. This backend
and the React app are additive and read the same database.
"""

__all__ = ["store", "app"]
