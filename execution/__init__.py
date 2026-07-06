"""Execution package (Python side of the bridge).

The C++ core owns routing and the RiskGate. This package holds the Python
venue executors the bridge calls. Alpaca paper execution lives in
market_data/alpaca_source.py. IBKR live execution lives here in ibkr_adapter.py.
IBKR is the only real-money venue and stays disabled behind the approval gate.
"""
