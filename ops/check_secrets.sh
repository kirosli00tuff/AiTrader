#!/usr/bin/env bash
# Pre-commit secrets scanner (Task 9 security hardening).
#
# Scans STAGED file content for credential-shaped strings and blocks the commit
# if any are found. Runs from the git pre-commit hook (see ops/install_git_hooks.sh)
# and can also be run by hand:
#
#   ops/check_secrets.sh            # scan currently-staged changes
#
# High-signal patterns only, so ordinary code does not trip it. Placeholder
# values in .env.example (empty / your_key_here / <...>) are ignored, and this
# scanner, the log-masking helper, and its tests are allow-listed because they
# legitimately contain example credential shapes.
set -euo pipefail

# Files allow-listed because they contain credential *shapes* on purpose.
ALLOWLIST_REGEX='^(ops/check_secrets\.sh|account_manager/log_safety\.py|tests/test_bridge_bind\.py|\.env\.example)$'

# Credential shapes that should never be committed as real values.
#   sk-...           OpenAI / Anthropic keys
#   sk-ant-...       (subset of sk-)
#   AKIA<16>         AWS access key id
#   github_pat_...   GitHub fine-grained token
#   ghp_/gho_/...    GitHub classic tokens
#   AIza...          Google API key
#   BEGIN ... PRIVATE KEY   PEM private key block
#   api_key=<value>  explicit assignment with a real-looking value
PATTERNS=(
  'sk-(ant-)?[A-Za-z0-9_-]{16,}'
  'AKIA[0-9A-Z]{16}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'gh[posru]_[A-Za-z0-9]{30,}'
  'AIza[0-9A-Za-z_-]{30,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
)
# Explicit secret assignment with a real-looking value (>=16 chars, not a
# placeholder). Kept separate so we can exclude obvious placeholders.
ASSIGN_PATTERN='(api[_-]?key|secret|token|password|passwd)["'"'"' ]*[:=]["'"'"' ]*[A-Za-z0-9/+_-]{16,}'
PLACEHOLDER_REGEX='your_|changeme|example|xxxx|placeholder|<[a-z_]+>|\$\{|_env|_ENV'

fail=0
report() {  # file, line-content
  echo "  BLOCKED: potential secret in $1"
  echo "    > $2"
  fail=1
}

# Staged, non-deleted files.
mapfile -t files < <(git diff --cached --name-only --diff-filter=ACM)

for f in "${files[@]}"; do
  [[ "$f" =~ $ALLOWLIST_REGEX ]] && continue
  # Skip binaries.
  git show ":$f" 2>/dev/null | grep -Iq . || continue
  content="$(git show ":$f" 2>/dev/null || true)"
  [[ -z "$content" ]] && continue

  for pat in "${PATTERNS[@]}"; do
    while IFS= read -r hit; do
      [[ -n "$hit" ]] && report "$f" "$hit"
    done < <(printf '%s\n' "$content" | grep -nE -e "$pat" || true)
  done

  # Assignment pattern, excluding placeholder values.
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    echo "$hit" | grep -Eiq -e "$PLACEHOLDER_REGEX" && continue
    report "$f" "$hit"
  done < <(printf '%s\n' "$content" | grep -niE -e "$ASSIGN_PATTERN" || true)
done

if [[ "$fail" -ne 0 ]]; then
  echo ""
  echo "Commit blocked: remove the secret(s) above (use .env / the keystore)."
  echo "If this is a false positive, add the path to ALLOWLIST_REGEX in"
  echo "ops/check_secrets.sh or commit with --no-verify (not recommended)."
  exit 1
fi

echo "check_secrets: no credential-shaped strings in staged changes."
exit 0
