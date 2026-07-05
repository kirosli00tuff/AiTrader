# Follow-up requirement: Accounts page credential handling (in-app + .env fallback)

User confirmed: support BOTH in-app credential entry AND .env fallback.

- Accounts/Connections page (Dash ui/ + account_manager/) must let the user TYPE and SAVE
  API keys/secrets per venue (Alpaca, Coinbase, IBKR, Polymarket) and per data source
  (ClankApp — free, default; Apify; SEC EDGAR — free, no key; Whale Alert — optional,
  limited free tier). Keep paper and live key fields separate per venue.
- Persist entered credentials in an ENCRYPTED local store (e.g. `credentials` table in the
  SQLite DB, values encrypted via a locally-generated key file, or a small keystore file).
  NEVER store secrets in YAML/config; NEVER commit. .gitignore must exclude keystore/.env.
- Runtime resolution order: (1) in-app saved credential, else (2) env var / .env
  (the *_env names in default_config.yaml: CLANKAPP_API_KEY (optional), APIFY_TOKEN,
  WHALE_ALERT_API_KEY (optional), SEC_API_KEY (optional override; EDGAR needs none),
  ALPACA_API_KEY/SECRET, COINBASE_API_KEY/SECRET, IBKR host/port/account).
- Per-venue connection status + a "test/validate connection" action (mock validator OK offline).
- Wire live_requires_connected_credentials in the approval gate to check the RESOLVED
  credential (in-app OR env).
