#!/usr/bin/env bash
# go_public.sh: take the Stage P.1 repositories public. Kiros runs this by hand, after review.
#
# Usage:
#   publish/go_public.sh                      run every step. It asks once before the first change.
#   publish/go_public.sh --check-only         run steps 1 and 2 only. Changes nothing.
#   publish/go_public.sh --build-profile DIR  build the local profile repo in DIR (a new folder) and stop.
#                                             No check, no network. Stage P.1 part H2 uses it.
#
# Steps:
#   1. Stop if any KIROS confirm mark is left under publish/.
#   2. Stop unless gh has the user scope, and print the command that adds it.
#   3. Rebuild llm-news-drift with extract.sh and push it. This must be a fast-forward.
#   4. Rebuild research-archive and the profile repo and push them. A force-push happens only while
#      GitHub reports the repo as private. Once it is public, a rebuild that is not a fast-forward stops.
#   5. Set the GitHub bio from publish/profile/bio.txt.
#   6. Make llm-news-drift, research-archive and kirosli00tuff public.
#   7. Print the steps that only the GitHub website can do.
#
# research-archive is skipped in steps 4, 6 and 7 while `gh repo view kirosli00tuff/research-archive`
# fails, which means the archive has no GitHub repo yet. The script prints one line when it skips it.
# llm-news-drift and the profile repo run as usual.
#
# Stage P.1 wrote this script and tested steps 1 and 2 only. It never ran steps 3 to 6.
# Builds go to a new temporary folder. The local copies under ~/Documents/GitHub are not changed.
# Steps 3 to 5 read committed files, so commit your edits under publish/ before you run it.

set -euo pipefail

readonly OWNER=kirosli00tuff
readonly PROFILE_REPO=kirosli00tuff
readonly ARCHIVE_REPO=research-archive
readonly AUTHOR_NAME=kirosli00tuff
readonly AUTHOR_EMAIL=249804683+kirosli00tuff@users.noreply.github.com
readonly BIO_MAX=160
readonly MARK="[KIROS"": confirm"   # split in two so this file never matches its own check
readonly GH_HELPER='!gh auth git-credential'

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
aitrader="$(cd "$here/.." && pwd)"

die() { printf 'go_public.sh: %s\n' "$*" >&2; exit 1; }
say() { printf '== %s\n' "$*"; }

# gh reads its token from the keyring through the user session bus. Stage P.1 part 0.1 sets both
# variables for every gh command, because a shell outside the desktop session can carry a stale bus
# address (gh then gets 401 Unauthorized).
uid="$(id -u)"
XDG_RUNTIME_DIR="/run/user/$uid"
DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus"
export XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS

check_marks() {
  local hits
  hits="$(grep -rnF --exclude=go_public.sh -e "$MARK" "$here" || true)"
  if [[ -n "$hits" ]]; then
    printf '%s\n' "$hits" >&2
    die "step 1: $(printf '%s\n' "$hits" | wc -l) confirm marks remain under publish/. Resolve each one, then run again."
  fi
  say "step 1: no confirm marks under publish/"
}

check_scope() {
  command -v gh >/dev/null || die "step 2: gh is not installed"
  local scopes
  scopes="$(gh api -i /user 2>/dev/null | tr -d '\r' \
    | awk '!found && tolower($0) ~ /^x-oauth-scopes:/ { sub(/^[^:]*: */, ""); print; found = 1 }')" \
    || die "step 2: gh api /user failed. Run: gh auth status"
  if [[ ",${scopes// /}," != *",user,"* ]]; then
    printf 'step 2: gh does not have the user scope. Run this, then run go_public.sh again:\n' >&2
    printf '  gh auth refresh -h github.com -s user\n' >&2
    exit 1
  fi
  say "step 2: gh has the user scope"
}

require_committed() {
  [[ -z "$(git -C "$aitrader" status --porcelain -- publish/)" ]] \
    || die "publish/ has uncommitted changes. The builds read committed files: commit them first."
  if git -C "$aitrader" grep -qF -e "$MARK" HEAD -- publish/ ':!publish/go_public.sh'; then
    die "HEAD still holds confirm marks under publish/. Commit the resolved files first."
  fi
}

archive_on_github() {   # true when GitHub has the research-archive repo
  gh repo view "$OWNER/$ARCHIVE_REPO" --json name --jq .name >/dev/null 2>&1
}

confirm() {   # confirm <repo> ...: the repos that step 6 makes public
  local answer
  printf 'Steps 3 to 6 push to GitHub, set the bio and make these repos public: %s.\n' "$*"
  printf 'Type "go public" to continue: '
  read -r answer
  [[ "$answer" == "go public" ]] || die "stopped. Nothing was changed."
}

remote_head() {   # remote_head <repo>: GitHub's main commit id, empty for an empty repo
  git -c credential.helper= -c "credential.helper=$GH_HELPER" \
    ls-remote "https://github.com/$OWNER/$1.git" refs/heads/main | awk '{ print $1 }'
}

is_fast_forward() {   # is_fast_forward <build dir> <old commit id>
  local dir="$1" old="$2"
  [[ -z "$old" ]] && return 0
  git -C "$dir" cat-file -e "$old^{commit}" 2>/dev/null || return 1
  git -C "$dir" merge-base --is-ancestor "$old" main
}

push_build() {   # push_build <build dir> <repo> <may force: yes or no>
  local dir="$1" name="$2" may_force="$3" old new url
  url="https://github.com/$OWNER/$name.git"
  new="$(git -C "$dir" rev-parse main)"
  old="$(remote_head "$name")"
  if [[ "$old" == "$new" ]]; then
    say "$name: GitHub already has $new"
    return 0
  fi
  local git_gh=(git -C "$dir" -c credential.helper= -c "credential.helper=$GH_HELPER")
  if is_fast_forward "$dir" "$old"; then
    "${git_gh[@]}" push "$url" main:main
  elif [[ "$may_force" == yes && "$(gh repo view "$OWNER/$name" --json visibility --jq .visibility)" == PRIVATE ]]; then
    say "$name: the rebuild is not a fast-forward and the repo is private, so it is force-pushed"
    "${git_gh[@]}" push --force-with-lease="refs/heads/main:$old" "$url" main:main
  else
    die "$name: the rebuild ($new) is not a fast-forward of GitHub's main ($old). Stopped. Nothing after this step ran."
  fi
  say "$name: pushed $new"
}

build_profile() {   # build_profile <new dir>: one commit that holds the committed publish/profile/README.md
  local dir="$1" date
  [[ ! -e "$dir" ]] || die "$dir already exists"
  date="$(git -C "$aitrader" log -1 --format=%cI HEAD -- publish/profile/README.md)"
  [[ -n "$date" ]] || die "publish/profile/README.md is not committed"
  git init -q -b main "$dir"
  git -C "$aitrader" show HEAD:publish/profile/README.md > "$dir/README.md"
  git -C "$dir" add README.md
  GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" GIT_AUTHOR_DATE="$date" \
    GIT_COMMITTER_NAME="$AUTHOR_NAME" GIT_COMMITTER_EMAIL="$AUTHOR_EMAIL" GIT_COMMITTER_DATE="$date" \
    git -C "$dir" -c commit.gpgsign=false commit -q -m "Profile README"
  say "profile: built $(git -C "$dir" rev-parse main) in $dir"
}

set_bio() {
  local bio
  bio="$(git -C "$aitrader" show HEAD:publish/profile/bio.txt | tr -d '\n')"
  [[ -n "$bio" ]] || die "step 5: bio.txt is empty"
  (( ${#bio} <= BIO_MAX )) || die "step 5: bio.txt has ${#bio} characters. GitHub allows $BIO_MAX."
  gh api -X PATCH /user -f bio="$bio" --silent
  say "step 5: bio set (${#bio} characters)"
}

print_web_steps() {   # print_web_steps <with archive: yes or no>
  local pins="llm-news-drift and PropExperiment"
  [[ "$1" == yes ]] && pins="llm-news-drift, PropExperiment and $ARCHIVE_REPO"
  printf '== step 7: do these on github.com, they have no gh command:\n'
  printf '  1. Profile page, "Customize your pins": pin %s.\n' "$pins"
  printf '  2. Settings > Public profile > Contributions: turn on "Include private contributions on my profile".\n'
  printf '  3. Settings > Public profile: set the avatar.\n'
}

main() {
  case "${1:-}" in
    --check-only) check_marks; check_scope; say "check only: stopped before step 3"; exit 0 ;;
    --build-profile) [[ -n "${2:-}" ]] || die "--build-profile needs a folder"; build_profile "$2"; exit 0 ;;
    -h | --help) sed -n '2,/^$/{s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; exit 0 ;;
    "") ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
  check_marks
  check_scope
  require_committed
  local with_archive=yes
  if ! archive_on_github; then
    with_archive=no
    say "$ARCHIVE_REPO: skipped in steps 4, 6 and 7, because gh repo view $OWNER/$ARCHIVE_REPO fails (no GitHub repo yet)"
  fi
  local public=(llm-news-drift)
  if [[ "$with_archive" == yes ]]; then public+=("$ARCHIVE_REPO"); fi
  public+=("$PROFILE_REPO")
  confirm "${public[@]}"
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/go_public.XXXXXX")"
  say "builds go to $tmp (kept for inspection, delete it when done)"

  "$here/llm-news-drift/extract.sh" --out "$tmp/llm-news-drift"
  push_build "$tmp/llm-news-drift" llm-news-drift no
  say "step 3: llm-news-drift done"

  if [[ "$with_archive" == yes ]]; then
    "$here/research-archive/build_archive.sh" --out "$tmp/$ARCHIVE_REPO" --report "$tmp/archive_build_report.md"
    push_build "$tmp/$ARCHIVE_REPO" "$ARCHIVE_REPO" yes
    say "step 4: $ARCHIVE_REPO done"
  fi
  build_profile "$tmp/$PROFILE_REPO"
  push_build "$tmp/$PROFILE_REPO" "$PROFILE_REPO" yes
  say "step 4: the profile repo done"

  set_bio

  local name
  for name in "${public[@]}"; do
    gh repo edit "$OWNER/$name" --visibility public --accept-visibility-change-consequences
    say "step 6: $name is public"
  done

  print_web_steps "$with_archive"
}

main "$@"
