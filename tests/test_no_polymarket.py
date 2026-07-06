"""Guard test: Polymarket and its Apify whale source are fully removed.

Polymarket was removed for region reasons. This test fails if a reference sneaks
back into the runtime code or config. It scans code and config only (not docs or
tests), and it also checks the two Python surfaces that used to list Polymarket:
the credential registry and the dashboard group lists.
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Runtime code and config only. Docs keep historical context and the test files
# themselves name the token in removal assertions, so both are out of scope.
_SCAN_DIRS = ("account_manager", "ui", "whale_signal", "python_bridge",
              "execution", "market_data", "ops")
_SCAN_FILES = ("config/default_config.yaml", "config/example_live_disabled.yaml",
               "config/schema.md", "storage/schema.sql", ".env.example")
_TOKENS = ("polymarket", "apify")


def _iter_files():
    for d in _SCAN_DIRS:
        base = os.path.join(_ROOT, d)
        for root, _dirs, names in os.walk(base):
            if "__pycache__" in root:
                continue
            for n in names:
                if n.endswith((".py", ".yaml", ".yml", ".sql", ".md")):
                    yield os.path.join(root, n)
    for f in _SCAN_FILES:
        yield os.path.join(_ROOT, f)


def test_no_polymarket_or_apify_in_runtime_code_or_config():
    offenders = []
    for path in _iter_files():
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read().lower()
        except FileNotFoundError:
            continue
        for token in _TOKENS:
            if token in text:
                offenders.append(f"{os.path.relpath(path, _ROOT)}: {token}")
    assert offenders == [], "stale Polymarket/Apify references: " + "; ".join(offenders)


def test_credential_registry_has_no_polymarket_or_apify():
    from account_manager import credentials
    assert "polymarket" not in credentials._REQUIRED_FIELDS
    assert "apify" not in credentials._REQUIRED_FIELDS
    groups = {spec.group for spec in credentials.CREDENTIALS.values()}
    assert "polymarket" not in groups
    assert "apify" not in groups
    # The dashboard group lists (ui/app.py VENUE_GROUPS / SOURCE_GROUPS) are
    # covered by the source scan above; ui/app.py is not importable from the repo
    # root because it expects to run from the ui/ directory.
