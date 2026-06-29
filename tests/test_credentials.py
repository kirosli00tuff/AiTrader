"""Tests for the encrypted credential store + runtime resolver.

Each test gets an isolated keystore dir (via MAL_KEYSTORE_DIR) and a clean
environment so encryption round-trips and resolution precedence are verified
in isolation. We import the module fresh per test so its module-level keystore
paths pick up the temp dir.
"""
import importlib
import os
import sys

import pytest


@pytest.fixture
def creds(tmp_path, monkeypatch):
    monkeypatch.setenv("MAL_KEYSTORE_DIR", str(tmp_path / "keystore"))
    # Clear any env that could leak into resolution.
    for var in ("APIFY_TOKEN", "WHALE_ALERT_API_KEY", "SEC_API_KEY",
                "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_LIVE_API_KEY",
                "ALPACA_LIVE_API_SECRET", "BINANCE_API_KEY", "BINANCE_API_SECRET",
                "IBKR_HOST", "IBKR_PORT", "IBKR_ACCOUNT"):
        monkeypatch.delenv(var, raising=False)
    sys.modules.pop("account_manager.credentials", None)
    mod = importlib.import_module("account_manager.credentials")
    return importlib.reload(mod)


def test_keyfile_generated_on_first_use(creds, tmp_path):
    creds.set_credential("apify_token", "secret-token-123")
    keyfile = os.path.join(str(tmp_path / "keystore"), "secret.key")
    assert os.path.exists(keyfile)
    # restrictive perms (owner-only)
    mode = os.stat(keyfile).st_mode & 0o777
    assert mode == 0o600


def test_encryption_roundtrip_and_at_rest(creds, tmp_path):
    creds.set_credential("apify_token", "plaintext-value")
    assert creds.get_credential("apify_token") == "plaintext-value"
    # The on-disk store must NOT contain the plaintext.
    store = os.path.join(str(tmp_path / "keystore"), "credentials.sqlite")
    with open(store, "rb") as fh:
        blob = fh.read()
    assert b"plaintext-value" not in blob


def test_in_app_overrides_env(creds, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "from-env")
    assert creds.get_credential("apify_token") == "from-env"
    assert creds.get_credential_source("apify_token") == "env"
    creds.set_credential("apify_token", "from-app")
    assert creds.get_credential("apify_token") == "from-app"
    assert creds.get_credential_source("apify_token") == "in-app"


def test_env_fallback_when_not_saved(creds, monkeypatch):
    assert creds.get_credential_source("sec_api_key") == "missing"
    monkeypatch.setenv("SEC_API_KEY", "env-sec")
    assert creds.get_credential("sec_api_key") == "env-sec"
    assert creds.get_credential_source("sec_api_key") == "env"


def test_paper_live_specific_env_variants(creds, monkeypatch):
    # generic env serves both paper and live as fallback
    monkeypatch.setenv("ALPACA_API_KEY", "generic")
    assert creds.get_credential("alpaca_paper_key") == "generic"
    assert creds.get_credential("alpaca_live_key") == "generic"
    # a live-specific env var takes priority for the live credential
    monkeypatch.setenv("ALPACA_LIVE_API_KEY", "live-only")
    assert creds.get_credential("alpaca_live_key") == "live-only"
    assert creds.get_credential("alpaca_paper_key") == "generic"


def test_resolve_env_uses_precedence(creds, monkeypatch):
    monkeypatch.setenv("WHALE_ALERT_API_KEY", "env-key")
    assert creds.resolve_env("WHALE_ALERT_API_KEY") == "env-key"
    creds.set_credential("whale_alert_key", "app-key")
    assert creds.resolve_env("WHALE_ALERT_API_KEY") == "app-key"
    # unknown env name falls back to raw os.environ
    monkeypatch.setenv("SOME_RANDOM_VAR", "raw")
    assert creds.resolve_env("SOME_RANDOM_VAR") == "raw"


def test_clearing_credential_restores_env(creds, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "env-val")
    creds.set_credential("apify_token", "app-val")
    assert creds.get_credential("apify_token") == "app-val"
    creds.set_credential("apify_token", "")  # blank clears in-app
    assert creds.get_credential("apify_token") == "env-val"


def test_list_status_masks_secrets(creds):
    creds.set_credential("apify_token", "supersecret")
    status = {s["name"]: s for s in creds.list_status()}
    s = status["apify_token"]
    assert s["configured"] is True
    assert s["source"] == "in-app"
    assert "supersecret" not in s["masked"]
    # non-secret values are shown
    creds.set_credential("ibkr_paper_host", "127.0.0.1")
    status = {s["name"]: s for s in creds.list_status()}
    assert status["ibkr_paper_host"]["masked"] == "127.0.0.1"


def test_validate_connection_offline(creds):
    res = creds.validate_connection("alpaca", "paper")
    assert res["ok"] is False  # nothing set
    creds.set_credential("alpaca_paper_key", "k")
    creds.set_credential("alpaca_paper_secret", "s")
    res = creds.validate_connection("alpaca", "paper")
    assert res["ok"] is True
    assert res["source"] == "in-app"


def test_venue_live_credentials_ok(creds, monkeypatch):
    assert creds.venue_live_credentials_ok("binance") is False
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")
    assert creds.venue_live_credentials_ok("binance") is True


def test_unknown_credential_raises(creds):
    with pytest.raises(KeyError):
        creds.get_credential("does_not_exist")
    with pytest.raises(KeyError):
        creds.set_credential("nope", "x")
