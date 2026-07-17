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

# Point the operator control file at an EMPTY temp dir, for the same reason and
# with the same shape. controls.json is the runtime override that WINS over
# config, so a test resolving a flag through the runtime path (cfg_path=None)
# reads whatever THIS machine's operator last toggled. Tests asserting a SHIPPED
# default then go red the moment a real operator enables a layer, reporting a
# regression that never happened.
#
# That shipped three times before this line existed (test_discovery_funnel,
# test_discovery_whale, test_long_term_sleeve), and each was fixed by hand while
# the rest were missed. An empty control dir kills the CLASS: no test can read
# the host's live toggles, so the runtime path and the shipped path agree and a
# shipped-default assertion is right either way. Tests that need their own
# control file set MAL_CONTROL_DIR per test, exactly as the keystore tests do.
os.environ["MAL_CONTROL_DIR"] = tempfile.mkdtemp(prefix="mal_test_controls_")
