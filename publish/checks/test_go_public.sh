#!/usr/bin/env bash
# test_go_public.sh: test publish/go_public.sh against local bare repos and a stub gh. It never reaches GitHub.
#
# Usage:
#   publish/checks/test_go_public.sh [--keep] [--verbose]
#
#   --keep     keep the sandbox when every check passes. It is always kept when a check fails.
#   --verbose  print the full output of every go_public.sh run.
#
# Everything runs in one new `mktemp -d` sandbox under ${XDG_CACHE_HOME:-$HOME/.cache}/p2-tmp. Each
# scenario gets its own folder there:
#   AiTrader/  a throwaway git repo standing in for AiTrader. It holds a copy of the go_public.sh under
#              test, publish/profile/ (README.md, bio.txt), and stub publish/llm-news-drift/extract.sh and
#              publish/research-archive/build_archive.sh. The stubs write small deterministic repos to
#              --out. The variant (v1, ff, nonff, nonff_same_tree) comes from state/variant.<news|archive>.
#   remotes/   bare repos llm-news-drift.git, research-archive.git and kirosli00tuff.git, standing in for
#              GitHub. An update hook logs every ref change to state/push.log as create, ff or NONFF.
#   state/     the stub gh's state: repo.<name> holds PUBLIC, PRIVATE, INTERNAL, FAIL or EMPTY (ABSENT or
#              no file: the repo does not exist), vis_seq.<name> optional answers served first, one per call,
#              scopes, bio. gh.log logs every gh call as READ, MUTATE, CREDENTIAL or UNEXPECTED.
# The stub gh is first on PATH, next to a git wrapper that logs the arguments of every git push to
# state/git_push.log and then runs the real git, so a force flag is caught even on a push that happens
# to be a fast-forward. The GitHub URLs reach remotes/ through the environment only:
# GIT_CONFIG_COUNT with url.file://<scenario>/remotes/.insteadOf = https://github.com/kirosli00tuff/.
# The script's own `-c credential.helper=` options do not touch url.*, so the redirect holds and the
# script is unchanged. GIT_ALLOW_PROTOCOL=file stops git from using any network transport,
# GIT_CONFIG_GLOBAL and GIT_CONFIG_NOSYSTEM keep the user's git config out, GH_CONFIG_DIR is an empty
# folder and GH_TOKEN and GITHUB_TOKEN are unset, so the real gh could not authenticate even if reached.
# The unchanged-mode checks (--check-only, --build-profile) compare against go_public.sh at commit
# $GO_PUBLIC_BASELINE (default cfcd878, Stage P.1), read from this repo with git show.
#
# Exit status: 0 when every check passes, 1 when one fails, 2 on a setup error.

set -euo pipefail

checks_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
publish_dir="$(cd "$checks_dir/.." && pwd)"
real_repo="$(cd "$publish_dir/.." && pwd)"
readonly SCRIPT_UNDER_TEST="$publish_dir/go_public.sh"
readonly BASELINE="${GO_PUBLIC_BASELINE:-cfcd878}"
readonly OWNER_URL=https://github.com/kirosli00tuff/
readonly MARK="[KIROS"": confirm"   # split in two so the mark check never matches this file
readonly CO_AUTHOR_LINE='Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'
readonly AUTHOR_NAME=kirosli00tuff
readonly AUTHOR_EMAIL=249804683+kirosli00tuff@users.noreply.github.com
readonly BIO_TEXT="Bio for the go_public.sh test."
readonly EDIT_ARCHIVE="repo edit kirosli00tuff/research-archive --visibility public --accept-visibility-change-consequences"
readonly PATCH_BIO="api -X PATCH /user -f bio=$BIO_TEXT --silent"

keep=no
verbose=no
for arg in "$@"; do
  case "$arg" in
    --keep) keep=yes ;;
    --verbose) verbose=yes ;;
    -h | --help) sed -n '2,/^$/{s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "test_go_public.sh: unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[[ -f "$SCRIPT_UNDER_TEST" ]] || { echo "test_go_public.sh: no $SCRIPT_UNDER_TEST" >&2; exit 2; }

parent="${XDG_CACHE_HOME:-$HOME/.cache}/p2-tmp"
mkdir -p "$parent"
SANDBOX="$(mktemp -d "$parent/go_public_test.XXXXXX")"
[[ -d "$SANDBOX" && "$SANDBOX" == "$parent"/go_public_test.* ]] || { echo "test_go_public.sh: bad sandbox" >&2; exit 2; }
readonly SANDBOX

# Isolation for this process and every child. Set once, before any git or gh call.
unset GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN GH_HOST GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
mkdir -p "$SANDBOX/bin" "$SANDBOX/ghconfig" "$SANDBOX/home"
export HOME="$SANDBOX/home"
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$SANDBOX/gitconfig" GIT_ALLOW_PROTOCOL=file GIT_TERMINAL_PROMPT=0
export GH_CONFIG_DIR="$SANDBOX/ghconfig" PATH="$SANDBOX/bin:$PATH" STUB_LIB="$SANDBOX/stublib.sh"
: > "$GIT_CONFIG_GLOBAL"
real_git="$(PATH="${PATH#"$SANDBOX/bin:"}" command -v git)"
[[ -x "$real_git" && "$real_git" != "$SANDBOX"/* ]] || { echo "test_go_public.sh: no real git" >&2; exit 2; }
cat > "$SANDBOX/bin/git" <<WRAP
#!/usr/bin/env bash
# git wrapper for test_go_public.sh: logs every push's arguments, then runs the real git.
for a in "\$@"; do
  if [[ "\$a" == push && -n "\${STUB_STATE:-}" ]]; then printf '%s\n' "\$*" >> "\$STUB_STATE/git_push.log"; break; fi
done
exec "$real_git" "\$@"
WRAP
chmod +x "$SANDBOX/bin/git"

# ---------------------------------------------------------------- sandbox files

cat > "$SANDBOX/stublib.sh" <<'LIB'
# stublib.sh: helpers shared by test_go_public.sh and its stub build scripts.
fixed_commit() {   # fixed_commit <repo dir> <day 1-28> <message>: commit every change, fixed identity and date
  local dir="$1" date
  date="2026-01-$(printf '%02d' "$2")T12:00:00+00:00"
  git -C "$dir" add -A
  GIT_AUTHOR_NAME="Stub Builder" GIT_AUTHOR_EMAIL="stub@example.invalid" GIT_AUTHOR_DATE="$date" \
    GIT_COMMITTER_NAME="Stub Builder" GIT_COMMITTER_EMAIL="stub@example.invalid" GIT_COMMITTER_DATE="$date" \
    git -C "$dir" -c commit.gpgsign=false commit -q -m "$3"
}
put() { mkdir -p "$(dirname "$1/$2")"; printf '%s\n' "$3" > "$1/$2"; }
news_base() {
  put "$1" README.md "news v1"; put "$1" data.txt 1; fixed_commit "$1" 1 "news first"
  put "$1" data.txt 2; fixed_commit "$1" 2 "news second"
}
archive_base() {
  put "$1" README.md "archive v1"; put "$1" a/x.txt 1; put "$1" a/drop.txt "dropped later"
  fixed_commit "$1" 1 "archive root"
  put "$1" b/y.txt 1; fixed_commit "$1" 2 "archive b"
}
make_variant() {   # make_variant <out dir> <news or archive> <variant>: a deterministic repo
  local out="$1"
  git init -q -b main "$out"
  case "$2:$3" in
    news:v1) news_base "$out" ;;
    news:ff) news_base "$out"; put "$out" data.txt 3; put "$out" notes/new.md new; fixed_commit "$out" 3 "news third" ;;
    news:nonff) put "$out" README.md "news rebuilt"; put "$out" data.txt 2; fixed_commit "$out" 4 "news rebuilt" ;;
    archive:v1) archive_base "$out" ;;
    archive:ff) archive_base "$out"; put "$out" c/z.txt 1; fixed_commit "$out" 3 "archive c" ;;
    archive:nonff)   # a new history that changes README.md and b/y.txt and drops a/drop.txt
      put "$out" README.md "archive v2"; put "$out" a/x.txt 1; put "$out" b/y.txt 2
      fixed_commit "$out" 5 "archive rebuilt" ;;
    archive:nonff_same_tree)   # a new history whose files equal v1's
      put "$out" README.md "archive v1"; put "$out" a/x.txt 1; put "$out" a/drop.txt "dropped later"
      put "$out" b/y.txt 1; fixed_commit "$out" 6 "archive rebuilt, same files" ;;
    *) echo "make_variant: unknown variant $2:$3" >&2; return 1 ;;
  esac
}
LIB
# shellcheck source=/dev/null
source "$STUB_LIB"

cat > "$SANDBOX/stub_extract.sh" <<'STUB'
#!/usr/bin/env bash
# Stub extract.sh for test_go_public.sh: writes a small deterministic llm-news-drift repo to --out.
set -euo pipefail
out=""
while (( $# )); do case "$1" in --out) out="$2"; shift 2 ;; *) shift ;; esac; done
[[ -n "$out" && ! -e "$out" ]] || { echo "stub extract.sh: --out is missing or exists" >&2; exit 2; }
# shellcheck source=/dev/null
source "$STUB_LIB"
variant="$(cat "$STUB_STATE/variant.news")"
echo "extract.sh $variant" >> "$STUB_STATE/builds.log"
make_variant "$out" news "$variant"
echo "stub extract.sh: built llm-news-drift ($variant) in $out"
STUB

cat > "$SANDBOX/stub_build_archive.sh" <<'STUB'
#!/usr/bin/env bash
# Stub build_archive.sh for test_go_public.sh: writes a small deterministic research-archive repo to --out.
set -euo pipefail
out="" report=""
while (( $# )); do
  case "$1" in --out) out="$2"; shift 2 ;; --report) report="$2"; shift 2 ;; *) shift ;; esac
done
[[ -n "$out" && ! -e "$out" ]] || { echo "stub build_archive.sh: --out is missing or exists" >&2; exit 2; }
# shellcheck source=/dev/null
source "$STUB_LIB"
variant="$(cat "$STUB_STATE/variant.archive")"
echo "build_archive.sh $variant" >> "$STUB_STATE/builds.log"
make_variant "$out" archive "$variant"
if [[ -n "$report" ]]; then echo "stub build report ($variant)" > "$report"; fi
echo "stub build_archive.sh: built research-archive ($variant) in $out"
STUB

cat > "$SANDBOX/bin/gh" <<'GH'
#!/usr/bin/env bash
# Stub gh for test_go_public.sh. Scenario state lives in $STUB_STATE. Every call is logged to gh.log.
set -u
st="${STUB_STATE:?stub gh: STUB_STATE is not set}"
owner=kirosli00tuff
log() { printf '%s\n' "$*" >> "$st/gh.log"; }
missing() { echo "GraphQL: Could not resolve to a Repository with the name '$owner/$1'. (repository)" >&2; exit 1; }
exists() { [[ -f "$st/repo.$1" && "$(cat "$st/repo.$1")" != ABSENT ]]; }
joined="$*"
case "$joined" in
  "repo view $owner/"*" --json name --jq .name")
    log "READ $joined"
    name="${3#"$owner"/}"
    exists "$name" || missing "$name"
    printf '%s\n' "$name" ;;
  "repo view $owner/"*" --json visibility --jq .visibility")
    log "READ $joined"
    name="${3#"$owner"/}"
    exists "$name" || missing "$name"
    if [[ -s "$st/vis_seq.$name" ]]; then
      answer="$(head -n 1 "$st/vis_seq.$name")"
      sed -i 1d "$st/vis_seq.$name"
    else
      answer="$(cat "$st/repo.$name")"
    fi
    case "$answer" in
      FAIL) echo "HTTP 502: Bad Gateway (https://api.github.com/graphql)" >&2; exit 1 ;;
      EMPTY) exit 0 ;;
      *) printf '%s\n' "$answer" ;;
    esac ;;
  "api -i /user")
    log "READ $joined"
    printf 'HTTP/2.0 200 OK\r\nX-Oauth-Scopes: %s\r\n\r\n{"login":"%s"}\n' "$(cat "$st/scopes")" "$owner" ;;
  "api /user --jq .bio")
    log "READ $joined"
    printf '%s\n' "$(cat "$st/bio")" ;;
  "api -X PATCH /user -f bio="*" --silent")
    log "MUTATE $joined"
    printf '%s' "${6#bio=}" > "$st/bio" ;;
  "repo edit $owner/"*" --visibility public --accept-visibility-change-consequences")
    log "MUTATE $joined"
    name="${3#"$owner"/}"
    echo PUBLIC > "$st/repo.$name" ;;
  "auth git-credential"*)
    log "CREDENTIAL $joined"
    exit 1 ;;
  *)
    log "UNEXPECTED $joined"
    echo "stub gh: unexpected call: $joined" >&2
    exit 1 ;;
esac
GH
chmod +x "$SANDBOX/bin/gh" "$SANDBOX/stub_extract.sh" "$SANDBOX/stub_build_archive.sh"

cat > "$SANDBOX/update_hook.template" <<'HOOK'
#!/bin/sh
# Logs every ref update this bare repo receives: create, delete, ff or NONFF.
zero=0000000000000000000000000000000000000000
if [ "$2" = "$zero" ]; then kind=create
elif [ "$3" = "$zero" ]; then kind=delete
elif git merge-base --is-ancestor "$2" "$3"; then kind=ff
else kind=NONFF
fi
printf '%s %s %s %s %s\n' "@NAME@" "$1" "$2" "$3" "$kind" >> "@LOG@"
exit 0
HOOK

git -C "$real_repo" show "$BASELINE:publish/go_public.sh" > "$SANDBOX/go_public_baseline.sh" 2>/dev/null \
  || : > "$SANDBOX/go_public_baseline.sh"
chmod +x "$SANDBOX/go_public_baseline.sh"

# ---------------------------------------------------------------- scenario plumbing

pass=0
fail=0
failures=()
scenario=""
S=""
out=""
rc=0
run_n=0
refs_before=""
old_news="" old_archive="" old_profile=""

make_standin() {   # make_standin <dir>: the throwaway AiTrader with the script under test and the stubs
  local dir="$1"
  git init -q -b main "$dir"
  mkdir -p "$dir/publish/profile" "$dir/publish/llm-news-drift" "$dir/publish/research-archive/cards"
  cp "$SCRIPT_UNDER_TEST" "$dir/publish/go_public.sh"
  cp "$SANDBOX/stub_extract.sh" "$dir/publish/llm-news-drift/extract.sh"
  cp "$SANDBOX/stub_build_archive.sh" "$dir/publish/research-archive/build_archive.sh"
  chmod +x "$dir/publish/go_public.sh" "$dir/publish/llm-news-drift/extract.sh" \
    "$dir/publish/research-archive/build_archive.sh"
  printf '# Profile v1\n' > "$dir/publish/profile/README.md"
  printf '%s\n' "$BIO_TEXT" > "$dir/publish/profile/bio.txt"
  printf '# llm-news-drift (stub)\n' > "$dir/publish/llm-news-drift/README.md"
  printf '# card (stub)\n' > "$dir/publish/research-archive/cards/card.md"
  printf 'Stand-in for AiTrader, made by test_go_public.sh.\n' > "$dir/README.md"
  fixed_commit "$dir" 10 "stand-in AiTrader"
}

make_bare() {   # make_bare <name> <seed repo, or empty for an empty remote>
  local name="$1" seed="$2" bare="$S/remotes/$1.git"
  git init -q --bare -b main "$bare"
  if [[ -n "$seed" ]]; then git -C "$seed" push -q "$bare" main:main; fi
  sed -e "s|@NAME@|$name|" -e "s|@LOG@|$S/state/push.log|" "$SANDBOX/update_hook.template" > "$bare/hooks/update"
  chmod +x "$bare/hooks/update"
}

go_env() {   # go_env <command...>: run with the scenario's stub state and the GitHub URL redirect
  env STUB_STATE="$S/state" TMPDIR="$S/tmp" GIT_CONFIG_COUNT=1 \
    "GIT_CONFIG_KEY_0=url.file://$S/remotes/.insteadOf" "GIT_CONFIG_VALUE_0=$OWNER_URL" "$@"
}

new_scenario() {   # new_scenario <id> <title> [no-archive]: the expected state, set up from scratch
  scenario="$1"
  S="$SANDBOX/$1"
  run_n=0
  printf '\n### %s: %s\n' "$1" "$2"
  mkdir -p "$S/state" "$S/remotes" "$S/tmp" "$S/seed" "$S/expect"
  : > "$S/state/gh.log"
  : > "$S/state/push.log"
  : > "$S/state/builds.log"
  : > "$S/state/git_push.log"
  echo PUBLIC > "$S/state/repo.llm-news-drift"
  echo PUBLIC > "$S/state/repo.kirosli00tuff"
  printf 'gist, read:org, repo, user, workflow\n' > "$S/state/scopes"
  printf '%s' "An older bio." > "$S/state/bio"
  echo ff > "$S/state/variant.news"
  echo nonff > "$S/state/variant.archive"
  make_standin "$S/AiTrader"
  make_variant "$S/seed/llm-news-drift" news v1
  go_env "$S/AiTrader/publish/go_public.sh" --build-profile "$S/seed/kirosli00tuff" >/dev/null
  make_bare llm-news-drift "$S/seed/llm-news-drift"
  make_bare kirosli00tuff "$S/seed/kirosli00tuff"
  if [[ "${3:-}" != no-archive ]]; then
    echo PRIVATE > "$S/state/repo.research-archive"
    make_variant "$S/seed/research-archive" archive v1
    make_bare research-archive "$S/seed/research-archive"
  fi
  old_news="$(remote_main llm-news-drift)"
  old_archive="$(remote_main research-archive)"
  old_profile="$(remote_main kirosli00tuff)"
  refs_before="$(snapshot)"
}

set_state() { printf '%s\n' "$2" > "$S/state/$1"; }   # set_state <file> <value>

standin_commit() {   # standin_commit <day> <message>: commit the stand-in's work tree
  fixed_commit "$S/AiTrader" "$1" "$2"
}

change_profile() {   # the profile README changes in the stand-in, so the profile repo has something to append
  printf '# Profile v2\n\nNow with a link to research-archive.\n' > "$S/AiTrader/publish/profile/README.md"
  standin_commit 11 "profile README v2"
}

expect_tip() {   # expect_tip <news or archive> <variant>: the commit id a stub build of that variant has
  local dir="$S/expect/$1-$2"
  [[ -d "$dir" ]] || make_variant "$dir" "$1" "$2"
  git -C "$dir" rev-parse main
}

expect_tree() {   # expect_tree <news or archive> <variant>
  expect_tip "$1" "$2" >/dev/null
  git -C "$S/expect/$1-$2" rev-parse 'main^{tree}'
}

run_gp() {   # run_gp <one line for stdin, or - for /dev/null> <go_public.sh arguments...>
  local input="$1"
  shift
  run_n=$((run_n + 1))
  out="$S/run$run_n.out"
  set +e
  if [[ "$input" == - ]]; then
    (cd "$S/AiTrader" && go_env "$S/AiTrader/publish/go_public.sh" "$@") < /dev/null > "$out" 2>&1
  else
    (cd "$S/AiTrader" && printf '%s\n' "$input" | go_env "$S/AiTrader/publish/go_public.sh" "$@") > "$out" 2>&1
  fi
  rc=$?
  set -e
  printf '  run %d: go_public.sh %s (stdin: %s) -> exit %d, output %s\n' \
    "$run_n" "${*:-(no arguments)}" "$input" "$rc" "${out#"$SANDBOX"/}"
  if [[ "$verbose" == yes ]]; then sed 's/^/    | /' "$out"; fi
}

check() {   # check <description> <command> [arguments...]: PASS when the command succeeds
  local what="$1"
  shift
  if "$@"; then
    pass=$((pass + 1))
    printf '    PASS %s\n' "$what"
  else
    fail=$((fail + 1))
    failures+=("$scenario run $run_n: $what")
    printf '    FAIL %s\n' "$what"
  fi
}

remote_main() {   # remote_main <name>: the bare repo's main, "empty" or "absent"
  local bare="$S/remotes/$1.git"
  if [[ ! -d "$bare" ]]; then echo absent; return 0; fi
  git -C "$bare" rev-parse -q --verify refs/heads/main || echo empty
}

snapshot() {
  printf 'llm-news-drift=%s research-archive=%s kirosli00tuff=%s\n' \
    "$(remote_main llm-news-drift)" "$(remote_main research-archive)" "$(remote_main kirosli00tuff)"
}

short_ids() { sed -E 's/\b([0-9a-f]{10})[0-9a-f]{30}\b/\1/g'; }

evidence() {   # the scenario's refs and logs, after its last run
  printf '    refs before: %s\n' "$(printf '%s\n' "$refs_before" | short_ids)"
  printf '    refs after:  %s\n' "$(snapshot | short_ids)"
  if grep -qvE '^READ ' "$S/state/gh.log"; then
    grep -vE '^READ ' "$S/state/gh.log" | sed 's/^/    gh: /'
  else
    echo "    gh: no mutating call ($(wc -l < "$S/state/gh.log") read-only calls)"
  fi
  if [[ -s "$S/state/push.log" ]]; then short_ids < "$S/state/push.log" | sed 's/^/    push hook: /'
  else echo "    push hook: no ref update"; fi
  if [[ -s "$S/state/git_push.log" ]]; then sed -e "s|$S/||g" -e 's/^/    git push args: /' "$S/state/git_push.log"
  else echo "    git push args: no git push"; fi
}

# predicates
rc_is() { [[ "$rc" -eq "$1" ]]; }
out_has() { grep -qF -- "$1" "$out"; }
out_lacks() { ! grep -qF -- "$1" "$out"; }
refs_unchanged() { [[ "$(snapshot)" == "$refs_before" ]]; }
no_ref_update() { [[ ! -s "$S/state/push.log" ]]; }
no_mutation() { ! grep -qE '^(MUTATE|CREDENTIAL|UNEXPECTED)' "$S/state/gh.log"; }
no_builds() { [[ ! -s "$S/state/builds.log" ]]; }
builds_lack() { ! grep -qF -- "$1" "$S/state/builds.log"; }
remote_is() { [[ "$(remote_main "$1")" == "$2" ]]; }
is_ancestor() { git -C "$S/remotes/$1.git" merge-base --is-ancestor "$2" main; }
no_nonff_update() { ! grep -q ' NONFF$' "$S/state/push.log"; }
gh_count() { grep -cF -- "$1" "$S/state/gh.log" || true; }
vis_is() { [[ "$(cat "$S/state/repo.$1")" == "$2" ]]; }
bio_is() { [[ "$(cat "$S/state/bio")" == "$1" ]]; }

mutations_are() {   # mutations_are <line> ...: the MUTATE lines of gh.log, exactly and in order
  diff <(grep -E '^(MUTATE|CREDENTIAL|UNEXPECTED)' "$S/state/gh.log" || true) \
    <(if (( $# )); then printf 'MUTATE %s\n' "$@"; fi) > /dev/null
}

updates_are() {   # updates_are "<name> <kind>" ...: the push hook's ref updates, exactly and in order
  diff <(awk '{ print $1, $5 }' "$S/state/push.log") <(if (( $# )); then printf '%s\n' "$@"; fi) > /dev/null
}

one_appended_commit() {   # one_appended_commit <name> <old id>: main is one commit whose only parent is old
  local bare="$S/remotes/$1.git"
  [[ "$(git -C "$bare" rev-list --count "$2..main")" == 1 ]] \
    && [[ "$(git -C "$bare" rev-list --parents -n 1 main)" == "$(git -C "$bare" rev-parse main) $2" ]]
}

message_exact() {   # message_exact <name>: main's message is the update line, a blank line, the trailer
  local sha
  sha="$(git -C "$S/AiTrader" rev-parse --short HEAD)"
  diff <(git -C "$S/remotes/$1.git" cat-file commit main | sed '1,/^$/d') \
    <(printf 'update from AiTrader %s\n\n%s\n' "$sha" "$CO_AUTHOR_LINE") > /dev/null
}

identity_exact() {   # identity_exact <name>: author and committer are the script's AUTHOR_NAME and AUTHOR_EMAIL
  [[ "$(git -C "$S/remotes/$1.git" log -1 --format='%an|%ae|%cn|%ce' main)" \
    == "$AUTHOR_NAME|$AUTHOR_EMAIL|$AUTHOR_NAME|$AUTHOR_EMAIL" ]]
}

tree_is() { [[ "$(git -C "$S/remotes/$1.git" rev-parse 'main^{tree}')" == "$2" ]]; }
file_is() { [[ "$(git -C "$S/remotes/$1.git" show "main:$2")" == "$3" ]]; }
file_absent() { ! git -C "$S/remotes/$1.git" cat-file -e "main:$2" 2>/dev/null; }
profile_has_standin_readme() {
  [[ "$(git -C "$S/remotes/kirosli00tuff.git" show main:README.md)" \
    == "$(git -C "$S/AiTrader" show HEAD:publish/profile/README.md)" ]]
}
no_force_flag() {   # no_force_flag <name>: no logged push to that repo carries any force flag or + refspec
  ! grep -F "/$1.git" "$S/state/git_push.log" | grep -qE -- '(^| )(-f|--force[^ ]*|\+[^ ]+)( |$)'
}
pushes_to() {   # pushes_to <name> <count>: the number of logged pushes to that repo
  [[ "$(grep -cF "/$1.git" "$S/state/git_push.log" || true)" == "$2" ]]
}
tmp_in_sandbox() { compgen -G "$S/tmp/go_public.*" > /dev/null; }

# ---------------------------------------------------------------- safety preflight

preflight() {
  new_scenario s00 "safety preflight: stub gh, no network transport, the redirect works under the script's -c options"
  check "gh on PATH is the stub" [ "$(command -v gh)" == "$SANDBOX/bin/gh" ]
  check "GH_TOKEN and GITHUB_TOKEN are unset" [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]
  check "GH_CONFIG_DIR is an empty sandbox folder" [ -z "$(ls -A "$GH_CONFIG_DIR")" ]
  local probe
  probe="$(git ls-remote https://example.invalid/none.git 2>&1 || true)"
  check "git refuses the https transport (GIT_ALLOW_PROTOCOL=file)" grep -qF "transport 'https' not allowed" <<< "$probe"
  probe="$(go_env git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
    ls-remote "${OWNER_URL}llm-news-drift.git" refs/heads/main | awk '{ print $1 }')"
  check "a GitHub URL under the script's -c options reaches the sandbox bare repo" [ "$probe" == "$old_news" ]
  check "git on PATH is the logging wrapper around $real_git" [ "$(command -v git)" == "$SANDBOX/bin/git" ]
  check "the baseline go_public.sh ($BASELINE) was read" [ -s "$SANDBOX/go_public_baseline.sh" ]
  evidence
}

# ---------------------------------------------------------------- scenarios

s01_dry_run_expected_state() {
  new_scenario s01 "dry run, expected state (llm-news-drift PUBLIC, profile PUBLIC, archive PRIVATE, all changed)"
  change_profile
  run_gp - --dry-run
  check "exit 0 (no gate would stop a real run)" rc_is 0
  check "no ref changed in any bare repo" refs_unchanged
  check "the bare repos received no update" no_ref_update
  check "no git push was even attempted" [ ! -s "$S/state/git_push.log" ]
  check "no mutating gh call" no_mutation
  check "no confirm prompt" out_lacks 'Type "go public"'
  check "plan: llm-news-drift fast-forward old -> new" \
    out_has "llm-news-drift (PUBLIC): push $old_news -> $(expect_tip news ff), a fast-forward"
  check "plan: research-archive force-push (private, not a fast-forward)" \
    out_has "research-archive (PRIVATE): force-push $old_archive -> $(expect_tip archive nonff) with --force-with-lease"
  check "plan: kirosli00tuff one appended commit" out_has "kirosli00tuff (PUBLIC): push $old_profile -> "
  check "plan: the appended commit's message" \
    out_has "appends one commit, \"update from AiTrader $(git -C "$S/AiTrader" rev-parse --short HEAD)\""
  check "plan: the diff --stat" out_has "README.md | "
  check "plan: the bio would change" out_has "bio: set to \"$BIO_TEXT\""
  check "plan: make public research-archive only" out_has "make public: research-archive"
  check "plan: the public repos are reported as already public" \
    out_has "already public, left alone: llm-news-drift kirosli00tuff"
  check "both builds ran" grep -qF "build_archive.sh nonff" "$S/state/builds.log"
  check "builds and clones went to mktemp -d under TMPDIR" tmp_in_sandbox
  evidence
}

s02_real_run_expected_state() {
  new_scenario s02 "real run, expected state"
  change_profile
  run_gp "go public"
  check "exit 0" rc_is 0
  check "llm-news-drift: GitHub main is the fast-forward build" remote_is llm-news-drift "$(expect_tip news ff)"
  check "llm-news-drift: the old main is an ancestor" is_ancestor llm-news-drift "$old_news"
  check "research-archive: force-pushed to the rebuild" remote_is research-archive "$(expect_tip archive nonff)"
  check "kirosli00tuff: exactly one new commit whose only parent is the old main" \
    one_appended_commit kirosli00tuff "$old_profile"
  check "kirosli00tuff: message, blank line, Co-Authored-By trailer, exactly" message_exact kirosli00tuff
  check "kirosli00tuff: author and committer are AUTHOR_NAME and AUTHOR_EMAIL" identity_exact kirosli00tuff
  check "kirosli00tuff: README.md is the stand-in's committed README" profile_has_standin_readme
  check "push hook: ff, NONFF (private archive), ff" \
    updates_are "llm-news-drift ff" "research-archive NONFF" "kirosli00tuff ff"
  check "gh: the bio PATCH and one repo edit, for research-archive only" mutations_are "$PATCH_BIO" "$EDIT_ARCHIVE"
  check "git push to llm-news-drift (public): one push, no force flag" pushes_to llm-news-drift 1
  check "git push to llm-news-drift carries no force flag" no_force_flag llm-news-drift
  check "git push to kirosli00tuff (public): one push, no force flag" pushes_to kirosli00tuff 1
  check "git push to kirosli00tuff carries no force flag" no_force_flag kirosli00tuff
  check "git push to research-archive (private) used --force-with-lease with the old id" \
    grep -qF -- "--force-with-lease=refs/heads/main:$old_archive" "$S/state/git_push.log"
  check "research-archive visibility re-read before the force-push" \
    [ "$(gh_count 'repo view kirosli00tuff/research-archive --json visibility')" == 2 ]
  check "research-archive is now public" vis_is research-archive PUBLIC
  check "the bio is bio.txt" bio_is "$BIO_TEXT"
  check "step 6 leaves llm-news-drift alone" out_has "step 6: llm-news-drift was already public, left alone"
  check "step 6 leaves kirosli00tuff alone" out_has "step 6: kirosli00tuff was already public, left alone"
  check "the confirm prompt lists the pushes" \
    out_has "push to: llm-news-drift (fast-forward), research-archive (force-push, private), kirosli00tuff (one appended commit, fast-forward)."
  check "the confirm prompt lists the flips" out_has "Step 6 makes these repos public: research-archive."
  evidence
}

s03_public_archive_not_ff() {
  new_scenario s03 "research-archive PUBLIC, its rebuild is not a fast-forward and drops a file"
  set_state repo.research-archive PUBLIC
  run_gp - --dry-run
  check "dry run: exit 0" rc_is 0
  check "dry run: no ref changed" refs_unchanged
  check "dry run: no mutating gh call" no_mutation
  check "dry run: plan appends one commit to research-archive" \
    out_has "research-archive (PUBLIC): push $old_archive -> "
  check "dry run: the stat shows the dropped file" out_has "a/drop.txt | 1 -"
  check "dry run: the profile has nothing to commit" \
    out_has "kirosli00tuff (PUBLIC): nothing to push: the build's files equal GitHub's main $old_profile, so no commit"
  check "dry run: nothing to make public" out_has "make public: none"
  run_gp "go public"
  check "exit 0" rc_is 0
  check "the old main is an ancestor of the new main" is_ancestor research-archive "$old_archive"
  check "exactly one appended commit whose only parent is the old main" \
    one_appended_commit research-archive "$old_archive"
  check "message and trailer exact" message_exact research-archive
  check "author and committer exact" identity_exact research-archive
  check "the new main's files are the rebuild's" tree_is research-archive "$(expect_tree archive nonff)"
  check "the file the build dropped is deleted" file_absent research-archive a/drop.txt
  check "README.md changed" file_is research-archive README.md "archive v2"
  check "push hook: only fast-forwards" updates_are "llm-news-drift ff" "research-archive ff"
  check "no NONFF ref update anywhere" no_nonff_update
  check "git push to research-archive (public) carries no force flag" no_force_flag research-archive
  check "kirosli00tuff not pushed at all (no diff)" pushes_to kirosli00tuff 0
  check "gh: only the bio PATCH, no repo edit" mutations_are "$PATCH_BIO"
  check "kirosli00tuff unchanged (no diff, no commit)" remote_is kirosli00tuff "$old_profile"
  evidence
}

s04_no_diff() {
  new_scenario s04 "nothing changed: llm-news-drift rebuild equals GitHub, archive PUBLIC with the same files, profile unchanged, bio equal"
  set_state variant.news v1
  set_state repo.research-archive PUBLIC
  set_state variant.archive nonff_same_tree
  printf '%s' "$BIO_TEXT" > "$S/state/bio"
  run_gp -
  check "exit 0, and no prompt was needed (stdin was /dev/null)" rc_is 0
  check "no ref changed" refs_unchanged
  check "the bare repos received no update" no_ref_update
  check "no mutating gh call" no_mutation
  check "llm-news-drift: nothing to push" \
    out_has "llm-news-drift (PUBLIC): nothing to push, GitHub's main already is the rebuild $old_news"
  check "research-archive: same files, so no commit" \
    out_has "research-archive (PUBLIC): nothing to push: the build's files equal GitHub's main $old_archive, so no commit"
  check "kirosli00tuff: same files, so no commit" \
    out_has "kirosli00tuff (PUBLIC): nothing to push: the build's files equal GitHub's main $old_profile, so no commit"
  check "the script says there is nothing to change" out_has "nothing to change on GitHub"
  check "no git push was attempted" [ ! -s "$S/state/git_push.log" ]
  evidence
}

s05_news_not_ff() {
  new_scenario s05 "llm-news-drift rebuild is not a fast-forward"
  set_state variant.news nonff
  change_profile
  run_gp "go public"
  check "exit 1" rc_is 1
  check "the stop names the rebuild that is not a fast-forward" \
    out_has "llm-news-drift: the rebuild ($(expect_tip news nonff)) is not a fast-forward of GitHub's main ($old_news)"
  check "no ref changed" refs_unchanged
  check "the bare repos received no update" no_ref_update
  check "no mutating gh call" no_mutation
  check "stopped before step 4: the archive was not built" builds_lack build_archive.sh
  check "stopped before step 4: no step 4 line" out_lacks "step 4"
  check "no git push was attempted" [ ! -s "$S/state/git_push.log" ]
  run_gp - --dry-run
  check "dry run: exit 1" rc_is 1
  check "dry run: reports where a real run stops" out_has "a real run would stop here: llm-news-drift: the rebuild"
  check "dry run: goes on and plans the archive" out_has "research-archive (PRIVATE): force-push"
  check "dry run: goes on and plans the profile" out_has "kirosli00tuff (PUBLIC): push $old_profile -> "
  check "dry run: no ref changed" refs_unchanged
  check "dry run: no mutating gh call" no_mutation
  set_state repo.llm-news-drift PRIVATE
  run_gp "go public"
  check "PRIVATE llm-news-drift that is not a fast-forward also stops (never the force path)" rc_is 1
  check "PRIVATE llm-news-drift: no ref changed" refs_unchanged
  check "PRIVATE llm-news-drift: no mutating gh call" no_mutation
  evidence
}

s06_visibility_lookup() {
  local what file answer
  for what in "kirosli00tuff FAIL failed, so its visibility is unknown" \
    "research-archive EMPTY gave an empty visibility" \
    "llm-news-drift INTERNAL reports the visibility 'INTERNAL'"; do
    read -r file answer _ <<< "$what"
    new_scenario "s06-$answer" "visibility lookup of $file answers $answer"
    change_profile
    set_state "repo.$file" "$answer"
    run_gp "go public"
    check "exit 1" rc_is 1
    check "the stop names the lookup" out_has "go_public.sh: $file: "
    check "the stop message" out_has "${what#"$file $answer "}"
    check "no ref changed" refs_unchanged
    check "the bare repos received no update" no_ref_update
    check "no mutating gh call" no_mutation
    check "stopped before any build" no_builds
    evidence
  done
  new_scenario s06-dry "dry run with the profile's visibility lookup failing"
  change_profile
  set_state repo.kirosli00tuff FAIL
  run_gp - --dry-run
  check "exit 1" rc_is 1
  check "reports where a real run stops" \
    out_has "a real run would stop here: kirosli00tuff: gh repo view kirosli00tuff/kirosli00tuff failed"
  check "the profile is not planned" out_has "kirosli00tuff: nothing planned, a real run stops before it"
  check "the profile is listed as unknown, not private" \
    out_has "visibility unknown, a real run stops before them: kirosli00tuff"
  check "the profile is not in the make-public list" out_has "make public: research-archive"
  check "goes on and plans llm-news-drift" out_has "llm-news-drift (PUBLIC): push"
  check "no ref changed" refs_unchanged
  check "no mutating gh call" no_mutation
  evidence
  new_scenario s06-race "research-archive PRIVATE when planned, PUBLIC at the second lookup before the force-push"
  change_profile
  printf 'PRIVATE\nPUBLIC\n' > "$S/state/vis_seq.research-archive"
  run_gp "go public"
  check "exit 1" rc_is 1
  check "the force-push is refused" out_has "research-archive: not force-pushed, because GitHub now reports 'PUBLIC'"
  check "research-archive unchanged" remote_is research-archive "$old_archive"
  check "no NONFF ref update anywhere" no_nonff_update
  check "kirosli00tuff (after the archive) was not pushed" remote_is kirosli00tuff "$old_profile"
  check "no repo edit and no bio PATCH" no_mutation
  evidence
}

s07_marks_left() {
  new_scenario s07 "a confirm mark is left (and committed) under publish/llm-news-drift/"
  change_profile
  printf '# llm-news-drift (stub)\n\n%s] a lesson to confirm\n' "$MARK" > "$S/AiTrader/publish/llm-news-drift/README.md"
  standin_commit 12 "a mark"
  run_gp "go public"
  check "real run: exit 1" rc_is 1
  check "real run: refuses at step 1" out_has "go_public.sh: step 1: 1 confirm marks remain under publish/."
  check "real run: no ref changed" refs_unchanged
  check "real run: no mutating gh call" no_mutation
  check "real run: stopped before any build" no_builds
  run_gp - --dry-run
  check "dry run: exit 1" rc_is 1
  check "dry run: reports step 1" out_has "a real run would stop here: step 1: 1 confirm marks remain under publish/."
  check "dry run: reports the HEAD check" \
    out_has "a real run would stop here: HEAD still holds confirm marks under publish/."
  check "dry run: goes on to the plan" out_has "llm-news-drift (PUBLIC): push $old_news -> "
  check "dry run: plans the profile commit" out_has "kirosli00tuff (PUBLIC): push $old_profile -> "
  check "dry run: lists the reasons at the end" out_has "dry run: a real run would have stopped (2):"
  check "dry run: no ref changed" refs_unchanged
  check "dry run: no mutating gh call" no_mutation
  evidence
}

s08_archive_absent() {
  new_scenario s08 "research-archive has no GitHub repo, and a mark is left under publish/research-archive/" no-archive
  change_profile
  printf '# card (stub)\n\n%s] a lesson\n' "$MARK" > "$S/AiTrader/publish/research-archive/cards/card.md"
  standin_commit 12 "a mark in the archive"
  run_gp - --check-only
  check "check-only: exit 0" rc_is 0
  check "check-only: step 1 leaves the archive out and counts its mark" \
    out_has "step 1: left publish/research-archive/ out of the check (1 confirm marks there)"
  run_gp "go public"
  check "real run: exit 0" rc_is 0
  check "real run: step 1 leaves the archive out" out_has "(1 confirm marks there)"
  check "real run: the archive is skipped" out_has "research-archive: skipped in steps 4, 6 and 7"
  check "real run: the archive was not built" no_builds_archive
  check "real run: llm-news-drift pushed as a fast-forward" remote_is llm-news-drift "$(expect_tip news ff)"
  check "real run: the profile got one appended commit" one_appended_commit kirosli00tuff "$old_profile"
  check "real run: gh calls only the bio PATCH" mutations_are "$PATCH_BIO"
  check "real run: step 7 does not pin the archive" out_has "pin llm-news-drift and PropExperiment."
  evidence
  new_scenario s08b "the same mark once research-archive exists: the exclusion ends"
  printf '# card (stub)\n\n%s] a lesson\n' "$MARK" > "$S/AiTrader/publish/research-archive/cards/card.md"
  standin_commit 12 "a mark in the archive"
  run_gp "go public"
  check "exit 1 at step 1" out_has "go_public.sh: step 1: 1 confirm marks remain under publish/."
  check "no ref changed" refs_unchanged
  check "no mutating gh call" no_mutation
  evidence
}
no_builds_archive() { builds_lack build_archive.sh; }

s09_unchanged_modes() {
  new_scenario s09 "--check-only and --build-profile behave as the baseline ($BASELINE)"
  if [[ ! -s "$SANDBOX/go_public_baseline.sh" ]]; then
    check "baseline go_public.sh at $BASELINE is readable" false
    return 0
  fi
  local new_copy="$S/go_public_new.sh" label prep
  cp "$S/AiTrader/publish/go_public.sh" "$new_copy"
  for label in clean no-scope mark archive-absent; do
    case "$label" in
      no-scope) set_state scopes "gist, repo" ;;
      mark) set_state scopes "gist, read:org, repo, user, workflow"
        printf '%s] x\n' "$MARK" > "$S/AiTrader/publish/profile/NOTE.md" ;;
      archive-absent) printf 'a note\n' > "$S/AiTrader/publish/profile/NOTE.md"
        set_state repo.research-archive ABSENT
        printf '%s] y\n' "$MARK" > "$S/AiTrader/publish/research-archive/cards/extra.md" ;;
    esac
    cp "$new_copy" "$S/AiTrader/publish/go_public.sh"
    run_gp - --check-only
    prep="$out"
    local new_rc="$rc"
    cp "$SANDBOX/go_public_baseline.sh" "$S/AiTrader/publish/go_public.sh"
    run_gp - --check-only
    check "--check-only ($label): same exit status as the baseline ($new_rc)" [ "$new_rc" == "$rc" ]
    check "--check-only ($label): same output as the baseline, byte for byte" cmp -s "$prep" "$out"
  done
  cp "$new_copy" "$S/AiTrader/publish/go_public.sh"
  check "--check-only changed nothing" refs_unchanged
  check "--check-only made no mutating gh call" no_mutation
  : > "$S/state/gh.log"
  run_gp - --build-profile "$S/bp-new"
  prep="$out"
  cp "$SANDBOX/go_public_baseline.sh" "$S/AiTrader/publish/go_public.sh"
  run_gp - --build-profile "$S/bp-base"
  cp "$new_copy" "$S/AiTrader/publish/go_public.sh"
  check "--build-profile: the same commit id as the baseline" \
    [ "$(git -C "$S/bp-new" rev-parse main)" == "$(git -C "$S/bp-base" rev-parse main)" ]
  check "--build-profile: the same output, folder name aside" \
    diff <(sed "s|$S/bp-new|DIR|" "$prep") <(sed "s|$S/bp-base|DIR|" "$out")
  run_gp - --build-profile "$S/bp-new"
  check "--build-profile into an existing folder still refuses" out_has "go_public.sh: $S/bp-new already exists"
  check "--build-profile made no gh call at all" [ ! -s "$S/state/gh.log" ]
  evidence
}

s10_bio_equal() {
  new_scenario s10 "the bio already equals bio.txt"
  change_profile
  printf '%s' "$BIO_TEXT" > "$S/state/bio"
  run_gp - --dry-run
  check "dry run: the bio is reported unchanged" out_has "bio: unchanged, GitHub already has the text of bio.txt"
  run_gp "go public"
  check "exit 0" rc_is 0
  check "no bio PATCH, only the archive's repo edit" mutations_are "$EDIT_ARCHIVE"
  check "step 5 says the bio is not changed" out_has "step 5: the bio already says the text of bio.txt, not changed"
  check "the confirm prompt says the bio is left" out_has "Step 5 leaves the bio."
  evidence
}

s11_scope_missing() {
  new_scenario s11 "gh lacks the user scope"
  change_profile
  set_state scopes "gist, read:org, repo, workflow"
  run_gp "go public"
  check "real run: exit 1" rc_is 1
  check "real run: prints the refresh command" out_has "gh auth refresh -h github.com -s user"
  check "real run: no ref changed" refs_unchanged
  check "real run: no mutating gh call" no_mutation
  check "real run: stopped before any build" no_builds
  run_gp - --dry-run
  check "dry run: exit 1" rc_is 1
  check "dry run: reports step 2" out_has "a real run would stop here: step 2: gh does not have the user scope"
  check "dry run: goes on to the plan" out_has "kirosli00tuff (PUBLIC): push $old_profile -> "
  check "dry run: no ref changed" refs_unchanged
  check "dry run: no mutating gh call" no_mutation
  evidence
}

s12_uncommitted() {
  new_scenario s12 "publish/ has an uncommitted change"
  change_profile
  printf 'An uncommitted bio.\n' > "$S/AiTrader/publish/profile/bio.txt"
  run_gp "go public"
  check "real run: exit 1" rc_is 1
  check "real run: refuses" out_has "go_public.sh: publish/ has uncommitted changes."
  check "real run: no ref changed" refs_unchanged
  check "real run: no mutating gh call" no_mutation
  check "real run: stopped before any build" no_builds
  run_gp - --dry-run
  check "dry run: exit 1" rc_is 1
  check "dry run: reports it" out_has "a real run would stop here: publish/ has uncommitted changes."
  check "dry run: the plan uses the committed bio.txt" out_has "bio: set to \"$BIO_TEXT\""
  check "dry run: no ref changed" refs_unchanged
  check "dry run: no mutating gh call" no_mutation
  evidence
}

s13_public_empty_remote() {
  new_scenario s13 "kirosli00tuff PUBLIC with an empty remote (no main)"
  change_profile
  git -C "$S/remotes/kirosli00tuff.git" update-ref -d refs/heads/main
  refs_before="$(snapshot)"
  run_gp "go public"
  check "exit 1" rc_is 1
  check "the stop names the empty main" out_has "kirosli00tuff: GitHub reports it PUBLIC, but its main is empty or missing"
  check "no ref changed (llm-news-drift and the archive were not pushed either)" refs_unchanged
  check "the bare repos received no update" no_ref_update
  check "no git push was attempted" [ ! -s "$S/state/git_push.log" ]
  check "no mutating gh call" no_mutation
  evidence
}

s14_private_archive_ff() {
  new_scenario s14 "research-archive PRIVATE, its rebuild is a fast-forward"
  set_state variant.archive ff
  run_gp "go public"
  check "exit 0" rc_is 0
  check "research-archive is the rebuild" remote_is research-archive "$(expect_tip archive ff)"
  check "push hook: research-archive updated as a fast-forward, no force" updates_are "llm-news-drift ff" "research-archive ff"
  check "the plan said fast-forward" out_has "research-archive (PRIVATE): push $old_archive -> $(expect_tip archive ff), a fast-forward"
  check "git push to research-archive carries no force flag" no_force_flag research-archive
  check "research-archive visibility read once (no force-push re-check)" \
    [ "$(gh_count 'repo view kirosli00tuff/research-archive --json visibility')" == 1 ]
  check "gh: bio PATCH and the archive's repo edit" mutations_are "$PATCH_BIO" "$EDIT_ARCHIVE"
  evidence
}

s15_confirm_declined() {
  new_scenario s15 "the confirm prompt is not answered with \"go public\""
  change_profile
  run_gp "no"
  check "answer 'no': exit 1" rc_is 1
  check "answer 'no': stopped, nothing changed" out_has "go_public.sh: stopped. Nothing was changed."
  run_gp -
  check "no answer (end of input): exit 1" rc_is 1
  check "no answer: stopped, nothing changed" out_has "go_public.sh: stopped. Nothing was changed."
  check "no git push was attempted" [ ! -s "$S/state/git_push.log" ]
  check "no ref changed" refs_unchanged
  check "no mutating gh call" no_mutation
  evidence
}

s16_help_and_arguments() {
  new_scenario s16 "--help and argument handling"
  run_gp - --help
  check "--help: exit 0" rc_is 0
  check "--help documents --dry-run" out_has "publish/go_public.sh --dry-run"
  check "--help documents the PUBLIC path" out_has "PUBLIC: history is never rebuilt and never force-pushed."
  check "--help ends before the code" out_lacks "set -euo pipefail"
  run_gp - --bogus
  check "unknown argument: exit 1" rc_is 1
  run_gp - --dry-run extra
  check "--dry-run with an extra argument: exit 1" out_has "unexpected argument: extra"
  check "no ref changed" refs_unchanged
  check "no mutating gh call" no_mutation
  evidence
}

# ---------------------------------------------------------------- run

printf 'test_go_public.sh: sandbox %s\n' "$SANDBOX"
printf 'script under test: %s (sha256 %s)\n' "$SCRIPT_UNDER_TEST" "$(sha256sum "$SCRIPT_UNDER_TEST" | cut -c1-16)"
preflight
s01_dry_run_expected_state
s02_real_run_expected_state
s03_public_archive_not_ff
s04_no_diff
s05_news_not_ff
s06_visibility_lookup
s07_marks_left
s08_archive_absent
s09_unchanged_modes
s10_bio_equal
s11_scope_missing
s12_uncommitted
s13_public_empty_remote
s14_private_archive_ff
s15_confirm_declined
s16_help_and_arguments

printf '\nRESULT: %d passed, %d failed\n' "$pass" "$fail"
if (( fail > 0 )); then
  printf '  FAILED %s\n' "${failures[@]}"
  printf 'sandbox kept: %s\n' "$SANDBOX"
  exit 1
fi
if [[ "$keep" == yes ]]; then
  printf 'sandbox kept: %s\n' "$SANDBOX"
else
  find "$SANDBOX" -mindepth 1 -delete
  rmdir "$SANDBOX"
  printf 'sandbox deleted\n'
fi
