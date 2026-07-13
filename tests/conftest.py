"""Pytest config — make repo-root packages importable, and keep the suite
hermetic against the host credential keystore."""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Point the credential keystore at an EMPTY temp dir before any test imports
# account_manager.credentials (its KEYSTORE_DIR is read once at import time).
# Keystore-first resolution then finds no real key, so the LLM providers and the
# base-check gate fall back to their labelled offline mocks unless a test sets an
# env var explicitly. Without this, a populated host keystore makes offline tests
# issue real API calls (non-deterministic, network-dependent). Tests that need
# their own keystore (e.g. test_credentials) override MAL_KEYSTORE_DIR per test.
os.environ["MAL_KEYSTORE_DIR"] = tempfile.mkdtemp(prefix="mal_test_keystore_")
