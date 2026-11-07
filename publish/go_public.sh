#!/usr/bin/env bash
# go_public.sh: take the Stage P.1 repositories public, and update them once they are. Kiros runs this
# by hand, after review.
#
# Usage:
#   publish/go_public.sh                      run every step. It prints the plan, then asks once before
#                                             the first change.
#   publish/go_public.sh --dry-run            run every step up to the push, print what a real run would
#                                             push, change and make public, and stop. Changes nothing on
#                                             GitHub and asks nothing.
#   publish/go_public.sh --check-only         run steps 1 and 2 only. Changes nothing.
#   publish/go_public.sh --build-profile DIR  build the local profile repo in DIR (a new folder) and stop.
#                                             No check, no network. Stage P.1 part H2 uses it.
#
# Steps:
#   1. Stop if any KIROS confirm mark is left under publish/. While research-archive has no GitHub
#      repo (see below), step 1 leaves publish/research-archive/ out and prints how many marks it left out.
#   2. Stop unless gh has the user scope, and print the command that adds it.
#      Then stop if publish/ has uncommitted changes or HEAD still holds marks, and read each repo's
#      visibility with `gh repo view`. Only the exact answers PUBLIC and PRIVATE go on. A failed lookup,
#      an empty answer or any other answer (INTERNAL) stops the script before any push.
#   3. Rebuild llm-news-drift with extract.sh. Public or private, its push must be a fast-forward of
#      GitHub's main. A rebuild that is not a fast-forward stops the script. It is never force-pushed.
#   4. Build research-archive and the profile repo (kirosli00tuff) as before, then by visibility:
#      PRIVATE: push the rebuild. When it is not a fast-forward it is force-pushed with
#        --force-with-lease, after a second visibility lookup that must still say PRIVATE.
#      PUBLIC: history is never rebuilt and never force-pushed. GitHub's main is cloned into a new
#        temporary folder, its tracked files are replaced by the build's (files the build dropped are
#        deleted), `git diff --cached --stat` is printed, and one commit "update from AiTrader <short
#        sha of HEAD>" with a Co-Authored-By line is appended and pushed as a fast-forward. No change
#        means no commit and no push. A public repo whose main is empty or missing stops the script.
#   5. Set the GitHub bio from publish/profile/bio.txt, unless the bio already says that.
#   6. Make llm-news-drift, research-archive and kirosli00tuff public. A repo already public is left alone.
#   7. Print the steps that only the GitHub website can do.
#
# Steps 3 and 4 build and prepare every repo first and push nothing. The script then prints the plan
# (per repo: GitHub's main, the new main and how it is pushed, then the bio and the repos to make
# public), asks once, and only then pushes (step 3, then step 4), sets the bio and flips visibility.
# --dry-run stops after the plan: no push, no gh repo edit, no bio change, no prompt. It still reads
# GitHub (gh repo view, gh api /user, git ls-remote, git clone). Where a real run would stop (marks
# left, scope missing, uncommitted publish/, a visibility lookup, a push that is not allowed), it
# prints "a real run would stop here: <reason>", goes on so the whole plan shows, and exits 1 at the end.
#
# research-archive is skipped in steps 4, 6 and 7 while `gh repo view kirosli00tuff/research-archive`
# fails, which means the archive has no GitHub repo yet. The script prints one line when it skips it.
# The same check runs before step 1, in a full run, in --dry-run and in --check-only, and step 1 then
# leaves out the marks under publish/research-archive/. The check that HEAD holds no marks (before
# step 3) leaves them out too. Once the archive repo exists, both check all of publish/.
# llm-news-drift and the profile repo run as usual.
#
# Stage P.2 changed steps 3 to 6 for repos that are already public. publish/checks/test_go_public.sh
# tests every path against local bare repos and a stub gh, never against GitHub.
# Builds and clones go to a new folder under ${TMPDIR:-/tmp}, kept for inspection. The local copies
# under ~/Documents/GitHub are not changed. Steps 3 to 5 read committed files, so commit your edits
# under publish/ before you run it.

set -euo pipefail
# An exported GIT_DIR, or one of the others, would point the git commands below at another repository or
# at other parts of one. Every call names its repository with -C or a path, so none is needed. GIT_CONFIG_*
# stays: publish/checks/test_go_public.sh reaches its local remotes through it.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES \
  GIT_COMMON_DIR GIT_NAMESPACE GIT_SHALLOW_FILE GIT_GRAFT_FILE

readonly OWNER=kirosli00tuff
readonly NEWS_REPO=llm-news-drift
readonly PROFILE_REPO=kirosli00tuff
readonly ARCHIVE_REPO=research-archive
readonly AUTHOR_NAME=kirosli00tuff
readonly AUTHOR_EMAIL=249804683+kirosli00tuff@users.noreply.github.com
readonly CO_AUTHOR_LINE='Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'
readonly BIO_MAX=160
readonly MARK="[KIROS"": confirm"   # split in two so this file never matches its own check
readonly GH_HELPER='!gh auth git-credential'

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
aitrader="$(cd "$here/.." && pwd)"

dry_run=no                # yes under --dry-run
stops=()                  # --dry-run: every reason a real run would have stopped
tmp=""                    # the build folder
aitrader_sha=""           # short id of AiTrader's HEAD, for the appended commit's message
declare -A visibility=()  # repo -> PUBLIC or PRIVATE. Nothing else is ever stored.
declare -A plan=()        # repo -> nothing, push, append or force
declare -A plan_dir=() plan_old=() plan_new=() plan_note=() plan_stat=()
bio_text=""
bio_plan=""               # change, keep, or empty when a real run stops before step 5

die() { printf 'go_public.sh: %s\n' "$*" >&2; exit 1; }
say() { printf '== %s\n' "$*"; }

stop() {   # stop <reason>: a real run dies here. A dry run prints the reason, keeps it and goes on.
  if [[ "$dry_run" == yes ]]; then
    printf 'a real run would stop here: %s\n' "$*"
    stops+=("$*")
    return 0
  fi
  die "$*"
}

# gh reads its token from the keyring through the user session bus. Stage P.1 part 0.1 sets both
# variables for every gh command, because a shell outside the desktop session can carry a stale bus
# address (gh then gets 401 Unauthorized).
uid="$(id -u)"
XDG_RUNTIME_DIR="/run/user/$uid"
DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus"
export XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS

check_marks() {   # check_marks <with archive: yes or no>
  local with_archive="$1" hits where="publish/"
  local skip=()
  if [[ "$with_archive" == no ]]; then
    local left_out
    left_out="$({ grep -rnF -e "$MARK" "$here/$ARCHIVE_REPO" 2>/dev/null || true; } | wc -l)"
    skip=(--exclude-dir="$ARCHIVE_REPO")   # by folder name: publish/ has one folder of that name
    where="publish/ outside publish/$ARCHIVE_REPO/"
    say "step 1: left publish/$ARCHIVE_REPO/ out of the check ($left_out confirm marks there), because gh repo view $OWNER/$ARCHIVE_REPO fails (no GitHub repo yet) and the archive is skipped in steps 4, 6 and 7"
  fi
  local grep_rc=0
  hits="$(grep -rnF --exclude=go_public.sh "${skip[@]}" -e "$MARK" "$here")" || grep_rc=$?
  if (( grep_rc > 1 )); then   # 1 is "no match". Anything above it is an error, never "no marks".
    stop "step 1: grep could not read everything under $where (exit $grep_rc), so the confirm marks are unchecked. Fix the error above, then run again."
    return 0
  fi
  if [[ -n "$hits" ]]; then
    printf '%s\n' "$hits" >&2
    stop "step 1: $(printf '%s\n' "$hits" | wc -l) confirm marks remain under $where. Resolve each one, then run again."
    return 0
  fi
  say "step 1: no confirm marks under $where"
}

check_scope() {
  if ! command -v gh >/dev/null; then
    stop "step 2: gh is not installed"
    return 0
  fi
  local scopes
  if ! scopes="$(gh api -i /user 2>/dev/null | tr -d '\r' \
    | awk '!found && tolower($0) ~ /^x-oauth-scopes:/ { sub(/^[^:]*: */, ""); print; found = 1 }')"; then
    stop "step 2: gh api /user failed. Run: gh auth status"
    return 0
  fi
  if [[ ",${scopes// /}," != *",user,"* ]]; then
    if [[ "$dry_run" == yes ]]; then
      stop "step 2: gh does not have the user scope. Add it with: gh auth refresh -h github.com -s user"
      return 0
    fi
    printf 'step 2: gh does not have the user scope. Run this, then run go_public.sh again:\n' >&2
    printf '  gh auth refresh -h github.com -s user\n' >&2
    exit 1
  fi
  say "step 2: gh has the user scope"
}

require_committed() {   # require_committed <with archive: yes or no>
  local with_archive="$1" where="publish/"
  local spec=(publish/ ':!publish/go_public.sh')
  local porcelain git_rc=0
  porcelain="$(git -C "$aitrader" status --porcelain -- publish/)" || git_rc=$?
  if (( git_rc != 0 )); then
    stop "git status of publish/ failed (exit $git_rc), so uncommitted changes are unchecked. Fix the error above, then run again."
  elif [[ -n "$porcelain" ]]; then
    stop "publish/ has uncommitted changes. The builds read committed files: commit them first."
  fi
  if [[ "$with_archive" == no ]]; then
    spec+=(":!publish/$ARCHIVE_REPO/")
    where="publish/ outside publish/$ARCHIVE_REPO/"
  fi
  git_rc=0
  git -C "$aitrader" grep -qF -e "$MARK" HEAD -- "${spec[@]}" || git_rc=$?
  case "$git_rc" in
    0) stop "HEAD still holds confirm marks under $where. Commit the resolved files first." ;;
    1) ;;   # no match
    *) stop "git grep of HEAD failed (exit $git_rc), so the confirm marks in HEAD under $where are unchecked. Fix the error above, then run again." ;;
  esac
}

archive_on_github() {   # true when GitHub has the research-archive repo
  gh repo view "$OWNER/$ARCHIVE_REPO" --json name --jq .name >/dev/null 2>&1
}

archive_state() {   # prints yes when GitHub has the research-archive repo, no when it does not
  if archive_on_github; then echo yes; else echo no; fi
}

read_visibility() {   # read_visibility <repo>: stores PUBLIC or PRIVATE, or stops. A failed lookup is never private.
  local name="$1" answer
  if ! answer="$(gh repo view "$OWNER/$name" --json visibility --jq .visibility)"; then
    stop "$name: gh repo view $OWNER/$name failed, so its visibility is unknown. Nothing is pushed to it."
    return 0
  fi
  case "$answer" in
    PUBLIC | PRIVATE)
      visibility[$name]="$answer"
      say "$name: GitHub reports it $answer" ;;
    "") stop "$name: gh repo view $OWNER/$name gave an empty visibility. Nothing is pushed to it." ;;
    *) stop "$name: GitHub reports the visibility '$answer', which is neither PUBLIC nor PRIVATE. Nothing is pushed to it." ;;
  esac
}

repo_url() { printf 'https://github.com/%s/%s.git\n' "$OWNER" "$1"; }

git_gh() {   # git with gh as the only credential helper
  git -c credential.helper= -c "credential.helper=$GH_HELPER" "$@"
}

remote_head() {   # remote_head <repo>: GitHub's main commit id, empty for an empty repo
  git_gh ls-remote "$(repo_url "$1")" refs/heads/main | awk '{ print $1 }'
}

is_fast_forward() {   # is_fast_forward <build dir> <old commit id>
  local dir="$1" old="$2"
  [[ -z "$old" ]] && return 0
  git -C "$dir" cat-file -e "$old^{commit}" 2>/dev/null || return 1
  git -C "$dir" merge-base --is-ancestor "$old" main
}

plan_rebuild() {   # plan_rebuild <build dir> <repo> <may force: yes or no>: push the rebuild itself
  local dir="$1" name="$2" may_force="$3" old new
  new="$(git -C "$dir" rev-parse main)"
  if ! old="$(remote_head "$name")"; then
    stop "$name: git ls-remote of GitHub's main failed. Nothing is pushed to it."
    return 0
  fi
  plan_dir[$name]="$dir"
  plan_old[$name]="$old"
  plan_new[$name]="$new"
  if [[ "$old" == "$new" ]]; then
    plan[$name]=nothing
    plan_note[$name]="nothing to push, GitHub's main already is the rebuild $new"
  elif is_fast_forward "$dir" "$old"; then
    plan[$name]=push
    plan_note[$name]="push ${old:-(empty)} -> $new, a fast-forward"
  elif [[ "$may_force" == yes && "${visibility[$name]:-}" == PRIVATE ]]; then
    plan[$name]=force
    plan_note[$name]="force-push $old -> $new with --force-with-lease: the rebuild is not a fast-forward and the repo is private"
  else
    stop "$name: the rebuild ($new) is not a fast-forward of GitHub's main ($old). Nothing was pushed."
  fi
}

plan_append() {   # plan_append <build dir> <repo>: one commit on top of GitHub's main, for a PUBLIC repo
  local build="$1" name="$2" old work new
  if ! old="$(remote_head "$name")"; then
    stop "$name: git ls-remote of GitHub's main failed. Nothing is pushed to it."
    return 0
  fi
  if [[ -z "$old" ]]; then
    stop "$name: GitHub reports it PUBLIC, but its main is empty or missing. A public repo is only appended to, so nothing is pushed to it."
    return 0
  fi
  work="$(mktemp -d "$tmp/$name-update.XXXXXX")"
  if ! git_gh clone -q --branch main --single-branch "$(repo_url "$name")" "$work"; then
    stop "$name: git clone of GitHub's main failed. Nothing is pushed to it."
    return 0
  fi
  if [[ "$(git -C "$work" rev-parse HEAD)" != "$old" ]]; then
    stop "$name: GitHub's main moved while the script ran (it was $old). Nothing is pushed to it. Run the script again."
    return 0
  fi
  # The build's tree replaces the clone's: read-tree --reset -u also deletes files the build dropped.
  git -C "$work" fetch -q "$build" main
  git -C "$work" read-tree -u --reset FETCH_HEAD
  plan_dir[$name]="$work"
  plan_old[$name]="$old"
  if git -C "$work" diff --cached --quiet; then
    plan[$name]=nothing
    plan_new[$name]="$old"
    plan_note[$name]="nothing to push: the build's files equal GitHub's main $old, so no commit"
    return 0
  fi
  plan_stat[$name]="$(git -C "$work" diff --cached --stat)"
  GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
    GIT_COMMITTER_NAME="$AUTHOR_NAME" GIT_COMMITTER_EMAIL="$AUTHOR_EMAIL" \
    git -C "$work" -c commit.gpgsign=false commit -q \
      -m "update from AiTrader $aitrader_sha" -m "$CO_AUTHOR_LINE"
  new="$(git -C "$work" rev-parse HEAD)"
  [[ "$(git -C "$work" rev-parse 'HEAD^')" == "$old" ]] \
    || die "$name: the appended commit's parent is not GitHub's main $old. Stopped before any push."
  [[ "$(git -C "$work" rev-parse 'HEAD^{tree}')" == "$(git -C "$work" rev-parse 'FETCH_HEAD^{tree}')" ]] \
    || die "$name: the appended commit's files differ from the build's. Stopped before any push."
  plan[$name]=append
  plan_new[$name]="$new"
  plan_note[$name]="push $old -> $new, a fast-forward that appends one commit, \"update from AiTrader $aitrader_sha\":"
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

prepare_news() {   # step 3: build llm-news-drift and plan a fast-forward push. Never a force-push.
  if [[ -z "${visibility[$NEWS_REPO]:-}" ]]; then
    say "step 3: $NEWS_REPO not built, its visibility is unknown"
    return 0
  fi
  if ! "$here/$NEWS_REPO/extract.sh" --out "$tmp/$NEWS_REPO"; then
    stop "step 3: extract.sh failed. Nothing was pushed."
    return 0
  fi
  plan_rebuild "$tmp/$NEWS_REPO" "$NEWS_REPO" no
}

prepare_step4() {   # prepare_step4 <repo>: build it, then rebuild-and-push (PRIVATE) or append (PUBLIC)
  local name="$1" dir="$tmp/$1"
  if [[ -z "${visibility[$name]:-}" ]]; then
    say "step 4: $name not built, its visibility is unknown"
    return 0
  fi
  if [[ "$name" == "$ARCHIVE_REPO" ]]; then
    if ! "$here/$ARCHIVE_REPO/build_archive.sh" --out "$dir" --report "$tmp/archive_build_report.md"; then
      stop "step 4: build_archive.sh failed. Nothing was pushed."
      return 0
    fi
  else
    build_profile "$dir"
  fi
  case "${visibility[$name]}" in
    PRIVATE) plan_rebuild "$dir" "$name" yes ;;
    PUBLIC) plan_append "$dir" "$name" ;;
    *) die "$name: no path for visibility '${visibility[$name]}'" ;;
  esac
}

plan_bio() {   # step 5, planned: bio_plan=change when GitHub's bio differs from bio.txt, keep when it matches
  local current
  if ! bio_text="$(git -C "$aitrader" show HEAD:publish/profile/bio.txt | tr -d '\n')"; then
    stop "step 5: publish/profile/bio.txt is not committed"
    return 0
  fi
  if [[ -z "$bio_text" ]]; then
    stop "step 5: bio.txt is empty"
    return 0
  fi
  if (( ${#bio_text} > BIO_MAX )); then
    stop "step 5: bio.txt has ${#bio_text} characters. GitHub allows $BIO_MAX."
    return 0
  fi
  if ! current="$(gh api /user --jq .bio)"; then
    say "step 5: could not read the current bio, so the bio is set"
    bio_plan=change
  elif [[ "$current" == "$bio_text" ]]; then
    bio_plan=keep
  else
    bio_plan=change
  fi
}

print_plan() {   # print_plan <repo> ...
  local name flip=() already=() unknown=()
  for name in "$@"; do
    if [[ -n "${plan[$name]:-}" ]]; then
      printf '  %s (%s): %s\n' "$name" "${visibility[$name]}" "${plan_note[$name]}"
      if [[ -n "${plan_stat[$name]:-}" ]]; then printf '%s\n' "${plan_stat[$name]}" | sed 's/^/      /'; fi
    else
      printf '  %s: nothing planned, a real run stops before it (see above)\n' "$name"
    fi
    case "${visibility[$name]:-}" in
      PUBLIC) already+=("$name") ;;
      PRIVATE) flip+=("$name") ;;
      *) unknown+=("$name") ;;
    esac
  done
  case "$bio_plan" in
    change) printf '  bio: set to "%s" (%s characters)\n' "$bio_text" "${#bio_text}" ;;
    keep) printf '  bio: unchanged, GitHub already has the text of bio.txt\n' ;;
    *) printf '  bio: nothing planned, a real run stops before it (see above)\n' ;;
  esac
  printf '  make public: %s\n' "${flip[*]:-none}"
  printf '  already public, left alone: %s\n' "${already[*]:-none}"
  if (( ${#unknown[@]} > 0 )); then
    printf '  visibility unknown, a real run stops before them: %s\n' "${unknown[*]}"
  fi
}

confirm() {   # confirm <repo> ...: lists what will be pushed and made public, then asks once
  local name answer pushes=() flips=()
  for name in "$@"; do
    case "${plan[$name]}" in
      push) pushes+=("$name (fast-forward)") ;;
      append) pushes+=("$name (one appended commit, fast-forward)") ;;
      force) pushes+=("$name (force-push, private)") ;;
    esac
    if [[ "${visibility[$name]}" == PRIVATE ]]; then flips+=("$name"); fi
  done
  local bio_word=leaves
  if [[ "$bio_plan" == change ]]; then bio_word=sets; fi
  printf 'Steps 3 and 4 push to: %s.\n' "$(join_list "${pushes[@]}")"
  printf 'Step 5 %s the bio. Step 6 makes these repos public: %s.\n' "$bio_word" "$(join_list "${flips[@]}")"
  printf 'Type "go public" to continue: '
  read -r answer || answer=""
  [[ "$answer" == "go public" ]] || die "stopped. Nothing was changed."
}

join_list() {   # join_list <item> ...: "a, b, c", or "nothing"
  local out="" item
  for item in "$@"; do out+="${out:+, }$item"; done
  printf '%s\n' "${out:-nothing}"
}

push_planned() {   # push_planned <repo>: carry out the plan made for it
  local name="$1" now url
  local dir="${plan_dir[$1]:-}" old="${plan_old[$1]:-}" new="${plan_new[$1]:-}"
  url="$(repo_url "$name")"
  case "${plan[$name]:-}" in
    nothing)
      say "$name: nothing to push"
      return 0 ;;
    push | append)
      git_gh -C "$dir" push "$url" main:main \
        || die "$name: the push failed. Repos listed before it in the plan were pushed." ;;
    force)
      now="$(gh repo view "$OWNER/$name" --json visibility --jq .visibility)" || now=""
      [[ "$now" == PRIVATE ]] \
        || die "$name: not force-pushed, because GitHub now reports '$now' instead of PRIVATE. Stopped."
      say "$name: the rebuild is not a fast-forward and the repo is private, so it is force-pushed"
      git_gh -C "$dir" push --force-with-lease="refs/heads/main:$old" "$url" main:main \
        || die "$name: the force-push failed. Repos listed before it in the plan were pushed." ;;
    *) die "$name: no plan. Stopped." ;;
  esac
  say "$name: pushed $new"
}

set_bio() {
  gh api -X PATCH /user -f bio="$bio_text" --silent
  say "step 5: bio set (${#bio_text} characters)"
}

print_web_steps() {   # print_web_steps <with archive: yes or no>
  local pins="llm-news-drift and PropExperiment"
  [[ "$1" == yes ]] && pins="llm-news-drift, PropExperiment and $ARCHIVE_REPO"
  printf '== step 7: do these on github.com, they have no gh command:\n'
  printf '  1. Profile page, "Customize your pins": pin %s.\n' "$pins"
  printf '  2. Settings > Public profile > Contributions: turn on "Include private contributions on my profile".\n'
  printf '  3. Settings > Public profile: set the avatar.\n'
}

finish_dry_run() {   # finish_dry_run <with archive>: report and exit, 1 when a real run would have stopped
  print_web_steps "$1"
  say "dry run: nothing was pushed, no bio was set and no repo was made public. Builds and clones: $tmp"
  if (( ${#stops[@]} > 0 )); then
    say "dry run: a real run would have stopped (${#stops[@]}):"
    printf '  - %s\n' "${stops[@]}"
    exit 1
  fi
  say "dry run: a real run would go ahead with the plan above"
  exit 0
}

main() {
  case "${1:-}" in
    --check-only) check_marks "$(archive_state)"; check_scope; say "check only: stopped before step 3"; exit 0 ;;
    --build-profile) [[ -n "${2:-}" ]] || die "--build-profile needs a folder"; build_profile "$2"; exit 0 ;;
    -h | --help) sed -n '2,/^$/{s/^# \{0,1\}//;p}' "${BASH_SOURCE[0]}"; exit 0 ;;
    --dry-run) dry_run=yes; say "dry run: nothing on GitHub is changed" ;;
    "") ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
  (( $# <= 1 )) || die "unexpected argument: $2 (see --help)"
  local with_archive
  with_archive="$(archive_state)"
  check_marks "$with_archive"
  check_scope
  require_committed "$with_archive"
  if [[ "$with_archive" == no ]]; then
    say "$ARCHIVE_REPO: skipped in steps 4, 6 and 7, because gh repo view $OWNER/$ARCHIVE_REPO fails (no GitHub repo yet)"
  fi
  local repos=("$NEWS_REPO") name
  if [[ "$with_archive" == yes ]]; then repos+=("$ARCHIVE_REPO"); fi
  repos+=("$PROFILE_REPO")
  for name in "${repos[@]}"; do read_visibility "$name"; done

  aitrader_sha="$(git -C "$aitrader" rev-parse --short HEAD)"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/go_public.XXXXXX")"
  say "builds go to $tmp (kept for inspection, delete it when done)"
  prepare_news
  say "step 3: $NEWS_REPO prepared, nothing pushed yet"
  if [[ "$with_archive" == yes ]]; then
    prepare_step4 "$ARCHIVE_REPO"
    say "step 4: $ARCHIVE_REPO prepared, nothing pushed yet"
  fi
  prepare_step4 "$PROFILE_REPO"
  say "step 4: the profile repo prepared, nothing pushed yet"
  plan_bio

  if [[ "$dry_run" == yes ]]; then say "dry run: a real run would do this:"; else say "plan:"; fi
  print_plan "${repos[@]}"
  if [[ "$dry_run" == yes ]]; then finish_dry_run "$with_archive"; fi

  local changes=no
  for name in "${repos[@]}"; do
    if [[ "${plan[$name]}" != nothing || "${visibility[$name]}" == PRIVATE ]]; then changes=yes; fi
  done
  if [[ "$bio_plan" == change ]]; then changes=yes; fi
  if [[ "$changes" == no ]]; then
    say "nothing to change on GitHub: no push, the bio already matches and every repo is public"
    print_web_steps "$with_archive"
    exit 0
  fi
  confirm "${repos[@]}"

  push_planned "$NEWS_REPO"
  say "step 3: $NEWS_REPO done"
  if [[ "$with_archive" == yes ]]; then
    push_planned "$ARCHIVE_REPO"
    say "step 4: $ARCHIVE_REPO done"
  fi
  push_planned "$PROFILE_REPO"
  say "step 4: the profile repo done"

  if [[ "$bio_plan" == change ]]; then
    set_bio
  else
    say "step 5: the bio already says the text of bio.txt, not changed"
  fi

  for name in "${repos[@]}"; do
    if [[ "${visibility[$name]}" == PUBLIC ]]; then
      say "step 6: $name was already public, left alone"
      continue
    fi
    gh repo edit "$OWNER/$name" --visibility public --accept-visibility-change-consequences
    say "step 6: $name is public"
  done

  print_web_steps "$with_archive"
}

main "$@"
