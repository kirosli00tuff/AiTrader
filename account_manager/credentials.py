"""Encrypted local credential store + single runtime resolver.

Credentials entered on the in-app Accounts/Connections page are encrypted at
rest with a locally-generated Fernet key and stored in a dedicated keystore
(``.keystore/credentials.sqlite``), kept separate from the operational DB so a
demo reseed never wipes saved keys. The Fernet key lives in
``.keystore/secret.key`` (gitignored, generated on first use, 0600).

Runtime resolution order for every secret:
  1. in-app saved encrypted credential, else
  2. environment variable / .env (the *_env names from default_config.yaml,
     plus paper/live-specific variants).

SECURITY: secrets are NEVER written to YAML/config and NEVER logged. Status
reporting masks secret values.
"""
from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cryptography.fernet import Fernet

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYSTORE_DIR = os.environ.get("MAL_KEYSTORE_DIR", os.path.join(_REPO_ROOT, ".keystore"))
_KEY_PATH = os.path.join(KEYSTORE_DIR, "secret.key")
_STORE_PATH = os.path.join(KEYSTORE_DIR, "credentials.sqlite")


# --- Credential registry ----------------------------------------------------

@dataclass(frozen=True)
class CredentialSpec:
    name: str               # stable storage key
    label: str              # field label in the UI
    group: str              # venue/source id (e.g. "alpaca", "clankapp")
    group_label: str        # human group name
    kind: str               # "venue" | "source"
    secret: bool            # mask in UI + never echo
    env_candidates: tuple[str, ...]  # env fallback names, in priority order
    mode: str | None = None  # "paper" | "live" | None (sources)


def _venue_keypair(group: str, glabel: str, mode: str,
                   base_env: tuple[str, str]) -> list[CredentialSpec]:
    m = mode.upper()
    key_env, sec_env = base_env
    return [
        CredentialSpec(f"{group}_{mode}_key", "API key", group, glabel, "venue",
                       True, (f"{group.upper()}_{m}_API_KEY", key_env), mode),
        CredentialSpec(f"{group}_{mode}_secret", "API secret", group, glabel,
                       "venue", True,
                       (f"{group.upper()}_{m}_API_SECRET", sec_env), mode),
    ]


def _build_registry() -> dict[str, CredentialSpec]:
    specs: list[CredentialSpec] = []
    # Venues with separate paper/live key+secret.
    for mode in ("paper", "live"):
        specs += _venue_keypair("alpaca", "Alpaca", mode,
                                ("ALPACA_API_KEY", "ALPACA_API_SECRET"))
        specs += _venue_keypair("coinbase", "Coinbase", mode,
                                ("COINBASE_API_KEY", "COINBASE_API_SECRET"))
        m = mode.upper()
        specs += [
            CredentialSpec(f"ibkr_{mode}_host", "Host", "ibkr", "IBKR", "venue",
                           False, (f"IBKR_{m}_HOST", "IBKR_HOST"), mode),
            CredentialSpec(f"ibkr_{mode}_port", "Port", "ibkr", "IBKR", "venue",
                           False, (f"IBKR_{m}_PORT", "IBKR_PORT"), mode),
            CredentialSpec(f"ibkr_{mode}_account", "Account", "ibkr", "IBKR",
                           "venue", False,
                           (f"IBKR_{m}_ACCOUNT", "IBKR_ACCOUNT"), mode),
        ]
    # Data sources (single credential each). Free-first: ClankApp (crypto) and
    # SEC EDGAR (institutional) are the defaults and need no paid key.
    specs += [
        CredentialSpec("clankapp_key", "API key (optional, free signup)",
                       "clankapp", "ClankApp (free, default)", "source", True,
                       ("CLANKAPP_API_KEY",)),
        CredentialSpec("whale_alert_key", "API key", "whale_alert",
                       "Whale Alert (optional, limited free tier)", "source",
                       True, ("WHALE_ALERT_API_KEY",)),
        CredentialSpec("sec_api_key", "API key (optional override only)",
                       "sec_api", "SEC EDGAR (free, no key needed)", "source",
                       True, ("SEC_API_KEY",)),
    ]
    return {s.name: s for s in specs}


CREDENTIALS: dict[str, CredentialSpec] = _build_registry()

# Required fields per group for a connection to count as "configured".
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "alpaca": ("key", "secret"),
    "coinbase": ("key", "secret"),
    "ibkr": ("host", "port", "account"),
    "clankapp": ("key",),
    "whale_alert": ("key",),
    "sec_api": ("key",),
}


# --- Keystore (encryption at rest) ------------------------------------------

def _ensure_keystore_dir() -> None:
    os.makedirs(KEYSTORE_DIR, exist_ok=True)
    try:
        os.chmod(KEYSTORE_DIR, stat.S_IRWXU)  # 0700
    except OSError:
        pass


def _load_key() -> bytes:
    _ensure_keystore_dir()
    if not os.path.exists(_KEY_PATH):
        key = Fernet.generate_key()
        # Write with restrictive perms before any secret is encrypted.
        fd = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key
    with open(_KEY_PATH, "rb") as fh:
        return fh.read()


def _fernet() -> Fernet:
    return Fernet(_load_key())


def _store() -> sqlite3.Connection:
    _ensure_keystore_dir()
    conn = sqlite3.connect(_STORE_PATH, timeout=5.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS credentials ("
        "name TEXT PRIMARY KEY, value_enc BLOB NOT NULL, updated_ts TEXT)"
    )
    return conn


# --- Read / write -----------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_credential(name: str, value: str | None) -> None:
    """Save (or clear, if value is empty/None) an in-app credential, encrypted."""
    if name not in CREDENTIALS:
        raise KeyError(f"unknown credential: {name}")
    if value is None or str(value).strip() == "":
        delete_credential(name)
        return
    token = _fernet().encrypt(str(value).encode())
    with _store() as conn:
        conn.execute(
            "INSERT INTO credentials(name, value_enc, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET value_enc=excluded.value_enc, "
            "updated_ts=excluded.updated_ts",
            (name, token, _now()),
        )
        conn.commit()


def delete_credential(name: str) -> None:
    try:
        with _store() as conn:
            conn.execute("DELETE FROM credentials WHERE name=?", (name,))
            conn.commit()
    except Exception:
        pass


def _stored_value(name: str) -> str | None:
    try:
        with _store() as conn:
            row = conn.execute(
                "SELECT value_enc FROM credentials WHERE name=?", (name,)
            ).fetchone()
        if not row:
            return None
        return _fernet().decrypt(row[0]).decode()
    except Exception:
        return None


def _env_value(name: str) -> str | None:
    spec = CREDENTIALS.get(name)
    if not spec:
        return None
    for env_name in spec.env_candidates:
        val = os.environ.get(env_name)
        if val:
            return val
    return None


def get_credential(name: str) -> str | None:
    """Resolve a credential: in-app saved value first, else env/.env fallback."""
    if name not in CREDENTIALS:
        raise KeyError(f"unknown credential: {name}")
    stored = _stored_value(name)
    if stored:
        return stored
    return _env_value(name)


def get_credential_source(name: str) -> str:
    """Where the resolved value comes from: 'in-app' | 'env' | 'missing'."""
    if _stored_value(name):
        return "in-app"
    if _env_value(name):
        return "env"
    return "missing"


def resolve_env(env_name: str) -> str | None:
    """Single resolver keyed by a config *_env name.

    Used by data-source adapters so the same in-app-then-env precedence applies
    everywhere a key is consumed. Falls back to a raw env lookup if the name is
    not part of the credential registry.
    """
    for name, spec in CREDENTIALS.items():
        if env_name in spec.env_candidates:
            return get_credential(name)
    return os.environ.get(env_name)


# --- Status / masking -------------------------------------------------------

def _mask(value: str, secret: bool) -> str:
    if not value:
        return ""
    if not secret:
        return value
    return "•" * 8


def list_status() -> list[dict]:
    """Per-credential status for the UI. Never includes secret plaintext."""
    out = []
    for name, spec in CREDENTIALS.items():
        source = get_credential_source(name)
        resolved = get_credential(name) if source != "missing" else None
        out.append({
            "name": name,
            "label": spec.label,
            "group": spec.group,
            "group_label": spec.group_label,
            "kind": spec.kind,
            "mode": spec.mode,
            "secret": spec.secret,
            "configured": source != "missing",
            "source": source,
            "masked": _mask(resolved or "", spec.secret),
        })
    return out


# --- Validation / approval-gate helpers -------------------------------------

def _group_field_names(group: str, mode: str | None) -> list[str]:
    fields = _REQUIRED_FIELDS.get(group, ())
    if mode:
        return [f"{group}_{mode}_{f}" for f in fields]
    return [f"{group}_{f}" for f in fields]


def credentials_present(group: str, mode: str | None = None) -> bool:
    """True if every required field for a group (+mode) resolves to a value."""
    names = _group_field_names(group, mode)
    if not names:
        return False
    return all(get_credential(n) for n in names)


def venue_live_credentials_ok(venue: str) -> bool:
    """Approval-gate check: resolved LIVE credentials present for the venue.

    This is what wires `live_requires_connected_credentials` to the RESOLVED
    credential (in-app OR env). Layer-1 safety and the live-disabled-by-default
    posture are unaffected — this only reports readiness.
    """
    return credentials_present(venue, "live")


def validate_connection(group: str, mode: str | None = None) -> dict:
    """Offline mock validator: ok when required creds resolve; never hits net.

    Returns {ok, message, source}. A real network probe would slot in here, but
    offline (or with no key) we deterministically report ok/fail by presence.
    """
    names = _group_field_names(group, mode)
    sources = {get_credential_source(n) for n in names}
    if not names:
        return {"ok": False, "message": "unknown group", "source": "missing"}
    missing = [n for n in names if not get_credential(n)]
    if missing:
        return {"ok": False,
                "message": f"missing: {', '.join(missing)}",
                "source": "missing"}
    source = "in-app" if "in-app" in sources else "env"
    scope = f"{group}/{mode}" if mode else group
    return {"ok": True, "message": f"{scope} credentials resolved ({source})",
            "source": source}
