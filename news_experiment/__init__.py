"""The stage 2 news-drift collector.

STANDALONE BY CONSTRUCTION. Nothing in the engine, the RiskGate, the execution
path, the sleeves, the bridge or the GUI imports this package, and
`tests/test_news_experiment_isolation.py` fails if that changes. It resolves a
universe, watches for news, scores headlines, and records observations.
Nothing it produces reaches a trading decision.

It implements EXPERIMENT.md, accepted by the operator on 2026-07-28 before any
collection. The specification is closed: this package transcribes it in
`spec.py` and reports disagreements rather than resolving them.
"""
