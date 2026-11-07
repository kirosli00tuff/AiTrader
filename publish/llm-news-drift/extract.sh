#!/usr/bin/env bash
# extract.sh: build the llm-news-drift repository from AiTrader's committed history.
#
# Usage:
#   extract.sh [--source <git repo path or URL>] [--ref <ref>] [--out <dir>] [--force]
#              [--replace-text <file>]
#
#   --source  the repository to read. Default: $HOME/Documents/GitHub/AiTrader.
#   --ref     the branch, tag or commit to extract. Default: HEAD of the source.
#   --out     where to write the new repository.
#             Default: $HOME/Documents/GitHub/llm-news-drift.
#   --force   replace --out when it already holds a repository. The script still
#             refuses when --out is, holds or sits inside the AiTrader repository.
#   --replace-text  a git-filter-repo --replace-text file applied to every blob of
#             every kept commit. Default: publish/checks/llm-news-drift.replace-text
#             read from --ref, when that path is committed there. When it is not,
#             the build runs with no text replacement and says so.
#
# What it does, in order:
#   1. Clones the source into a new temporary directory with
#      `git clone --bare --no-local`. The source is only read, never changed.
#   2. Keeps one branch, main, at --ref. Every other branch, tag and remote goes.
#   3. Cuts the history at AiTrader commit 74532e7 (2026-07-27). A replace ref
#      gives that commit no parents, so nothing older is exported.
#   4. Runs git-filter-repo three times:
#        a. keep the paths in ALLOWLIST.txt, apply the mailmap, and apply the
#           replace-text rules to file contents
#        b. drop the paths in EXCLUDE.txt, matched against the original paths
#        c. move publish/llm-news-drift/ to the repository root
#      ALLOWLIST.txt, EXCLUDE.txt, the mailmap and the default replace-text file
#      are read from --ref. Files in the working tree of the source are never
#      used. Only a file named with --replace-text is read from this machine.
#   5. Checks the result, then clones it into --out with no remote and one
#      branch, main.
#
# Two runs from the same --ref give the same commit hashes. The script adds no
# commit, no timestamp and no random name to the history. Commit messages stay
# exactly as recorded (--preserve-commit-hashes).
#
# Needs git and git-filter-repo (tested with git 2.53.0 and git-filter-repo
# 2.47.0). Set GIT_FILTER_REPO to use a git-filter-repo outside PATH.

set -euo pipefail

# ---------------------------------------------------------------- constants

# The first commit of the extracted history: AiTrader 74532e7, 2026-07-27.
readonly CUT_COMMIT=74532e7a98adae1f1ac383bdb36382557aecb785
readonly EARLIEST_DATE=2026-07-27
readonly LIST_DIR=publish/llm-news-drift
readonly MAILMAP_PATH=publish/checks/llm-news-drift.mailmap
readonly REPLACE_TEXT_PATH=publish/checks/llm-news-drift.replace-text
readonly BRANCH=main

# ---------------------------------------------------------------- helpers

die() {
    printf 'extract.sh: %s\n' "$*" >&2
    exit 1
}

say() {
    printf '%s\n' "$*"
}

usage() {
    sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'
}

# True when path $1 is $2, or sits inside $2.
is_same_or_inside() {
    [[ "$1" == "$2" || "$1" == "$2/"* ]]
}

# Git with no user or system config, so settings such as hooks or templates on
# this machine cannot change what is written.
git_clean() {
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git "$@"
}

# Run git-filter-repo inside the work repository and keep its output in a log.
run_filter() {
    local step=$1
    shift
    say "filter-repo: ${step}"
    if ! (cd "$work" && GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
            "$filter_repo" --force --preserve-commit-hashes \
            --replace-refs delete-no-add "$@") >>"$tmp/filter-repo.log" 2>&1; then
        tail -n 40 "$tmp/filter-repo.log" >&2
        die "git-filter-repo failed at step: ${step}"
    fi
}

# ---------------------------------------------------------------- arguments

source_repo="$HOME/Documents/GitHub/AiTrader"
ref=HEAD
out="$HOME/Documents/GitHub/llm-news-drift"
force=0
replace_text=

while (($# > 0)); do
    case $1 in
        --source) (($# >= 2)) || die "--source needs a value"; source_repo=$2; shift 2 ;;
        --source=*) source_repo=${1#*=}; shift ;;
        --ref) (($# >= 2)) || die "--ref needs a value"; ref=$2; shift 2 ;;
        --ref=*) ref=${1#*=}; shift ;;
        --out) (($# >= 2)) || die "--out needs a value"; out=$2; shift 2 ;;
        --out=*) out=${1#*=}; shift ;;
        --force) force=1; shift ;;
        --replace-text) (($# >= 2)) || die "--replace-text needs a value"; replace_text=$2; shift 2 ;;
        --replace-text=*) replace_text=${1#*=}; shift ;;
        -h | --help) usage; exit 0 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
done

[[ -n "$source_repo" && -n "$ref" && -n "$out" ]] || die "empty argument"
if [[ -n "$replace_text" ]]; then
    [[ -f "$replace_text" && -r "$replace_text" ]] ||
        die "--replace-text $replace_text is not a readable file"
fi

filter_repo=${GIT_FILTER_REPO:-$(command -v git-filter-repo || true)}
[[ -n "$filter_repo" && -x "$filter_repo" ]] ||
    die "git-filter-repo not found; install it or set GIT_FILTER_REPO"

# ---------------------------------------------------------------- refuse unsafe targets

# Paths that must never be written: the AiTrader repository and the source.
protected=()
protected+=("$(realpath -m -- "$HOME/Documents/GitHub/AiTrader")")
if [[ -d "$source_repo" ]]; then
    protected+=("$(realpath -- "$source_repo")")
    if top=$(git -C "$source_repo" rev-parse --show-toplevel 2>/dev/null); then
        protected+=("$(realpath -- "$top")")
    fi
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if top=$(git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null); then
    if git -C "$top" cat-file -e "${CUT_COMMIT}^{commit}" 2>/dev/null; then
        protected+=("$(realpath -- "$top")")
    fi
fi

out_abs=$(realpath -m -- "$out")
home_abs=$(realpath -m -- "$HOME")
[[ "$out_abs" != "/" && "$out_abs" != "$home_abs" ]] ||
    die "refusing to write to $out_abs"
for p in "${protected[@]}"; do
    if is_same_or_inside "$out_abs" "$p" || is_same_or_inside "$p" "$out_abs"; then
        die "refusing: --out $out_abs is, holds or sits inside $p"
    fi
done

replace_out=0
if [[ -e "$out_abs" || -L "$out_abs" ]]; then
    [[ -d "$out_abs" && ! -L "$out_abs" ]] || die "--out $out_abs exists and is not a directory"
    if [[ -n "$(ls -A -- "$out_abs")" ]]; then
        ((force == 1)) || die "--out $out_abs is not empty; pass --force to replace it"
        # Only replace something that looks like an earlier output: a git work
        # tree rooted at --out that does not hold the original AiTrader history.
        top=$(git -C "$out_abs" rev-parse --show-toplevel 2>/dev/null) ||
            die "refusing: --out $out_abs is not a git repository"
        [[ "$(realpath -- "$top")" == "$out_abs" ]] ||
            die "refusing: --out $out_abs sits inside the repository at $top"
        if git -C "$out_abs" cat-file -e "${CUT_COMMIT}^{commit}" 2>/dev/null; then
            die "refusing: --out $out_abs holds AiTrader history (commit ${CUT_COMMIT:0:7})"
        fi
        replace_out=1
    fi
fi

# ---------------------------------------------------------------- 1. clone

tmp=$(mktemp -d "${TMPDIR:-/tmp}/llm-news-drift-extract.XXXXXXXX")
trap 'rm -rf -- "$tmp"' EXIT
work="$tmp/work.git"
: >"$tmp/filter-repo.log"

say "source: $source_repo"
# The user's git config is kept for this one step so that a URL source can
# use its credentials. A bare clone checks nothing out and runs no hooks.
git clone --quiet --bare --no-local -- "$source_repo" "$work" ||
    die "cannot clone $source_repo"

ref_sha=$(git_clean -C "$work" rev-parse --verify --quiet "${ref}^{commit}") ||
    die "--ref $ref is not a commit in $source_repo"
say "ref: $ref = $ref_sha"

git_clean -C "$work" cat-file -e "${CUT_COMMIT}^{commit}" 2>/dev/null ||
    die "the cut commit ${CUT_COMMIT:0:7} is not in $source_repo"
git_clean -C "$work" merge-base --is-ancestor "$CUT_COMMIT" "$ref_sha" ||
    die "the cut commit ${CUT_COMMIT:0:7} is not an ancestor of $ref"

# The lists and the mailmap come from the commit being extracted.
for f in "$LIST_DIR/ALLOWLIST.txt" "$LIST_DIR/EXCLUDE.txt" "$MAILMAP_PATH"; do
    git_clean -C "$work" cat-file -e "${ref_sha}:${f}" 2>/dev/null ||
        die "$f is not committed at $ref"
done
git_clean -C "$work" cat-file blob "${ref_sha}:${LIST_DIR}/ALLOWLIST.txt" >"$tmp/allowlist.txt"
git_clean -C "$work" cat-file blob "${ref_sha}:${LIST_DIR}/EXCLUDE.txt" >"$tmp/exclude.txt"
git_clean -C "$work" cat-file blob "${ref_sha}:${MAILMAP_PATH}" >"$tmp/mailmap"

# The replace-text rules: the file named with --replace-text, else the one
# committed at --ref, else none.
replace_args=()
if [[ -n "$replace_text" ]]; then
    cp -- "$replace_text" "$tmp/replace-text"
    replace_args=(--replace-text "$tmp/replace-text")
    say "replace-text: $replace_text"
elif git_clean -C "$work" cat-file -e "${ref_sha}:${REPLACE_TEXT_PATH}" 2>/dev/null; then
    git_clean -C "$work" cat-file blob "${ref_sha}:${REPLACE_TEXT_PATH}" >"$tmp/replace-text"
    replace_args=(--replace-text "$tmp/replace-text")
    say "replace-text: $REPLACE_TEXT_PATH at $ref"
else
    say "replace-text: none ($REPLACE_TEXT_PATH is not committed at $ref), no text replaced"
fi

# ---------------------------------------------------------------- 2. one branch

git_clean -C "$work" remote remove origin 2>/dev/null || true
git_clean -C "$work" for-each-ref --format='delete %(refname)' |
    git_clean -C "$work" update-ref --no-deref --stdin
git_clean -C "$work" update-ref "refs/heads/$BRANCH" "$ref_sha"
git_clean -C "$work" symbolic-ref HEAD "refs/heads/$BRANCH"

# ---------------------------------------------------------------- 3. cut

git_clean -C "$work" replace --graft "$CUT_COMMIT"
# With the graft, every commit on the branch must descend from the cut commit.
# A merge that reached older history would break that, so check it.
n_all=$(git_clean -C "$work" rev-list --count "$BRANCH")
n_desc=$(git_clean -C "$work" rev-list --count --ancestry-path "${CUT_COMMIT}..${BRANCH}")
((n_all == n_desc + 1)) ||
    die "history before ${CUT_COMMIT:0:7} is still reachable ($n_all commits, $n_desc descendants)"
say "commits to filter: $n_all (the cut commit and $n_desc after it)"

# ---------------------------------------------------------------- 4. filter

run_filter "a. allowlist, mailmap and replace-text" \
    --paths-from-file "$tmp/allowlist.txt" --mailmap "$tmp/mailmap" "${replace_args[@]}"
run_filter "b. exclude list on original paths" \
    --paths-from-file "$tmp/exclude.txt" --invert-paths

# Before the move, make sure no file under publish/llm-news-drift/ lands on a
# path that some other kept file uses at any point in the history. The only
# intended overlaps are with excluded originals, which step b removed.
git_clean -C "$work" log --format= --name-only --no-renames "$BRANCH" |
    LC_ALL=C sort -u >"$tmp/paths.txt"
LC_ALL=C grep "^$LIST_DIR/" "$tmp/paths.txt" | sed "s#^$LIST_DIR/##" >"$tmp/moved.txt" || true
LC_ALL=C grep -v "^$LIST_DIR/" "$tmp/paths.txt" >"$tmp/kept.txt" || true
collisions=$(LC_ALL=C comm -12 "$tmp/moved.txt" "$tmp/kept.txt")
[[ -z "$collisions" ]] ||
    die "moving $LIST_DIR/ to the root would overwrite kept files: $collisions"

run_filter "c. move $LIST_DIR/ to the root" \
    --path-rename "$LIST_DIR/:"

# ---------------------------------------------------------------- 5. check

refs=$(git_clean -C "$work" for-each-ref --format='%(refname)')
[[ "$refs" == "refs/heads/$BRANCH" ]] || die "unexpected refs after filtering: $refs"

roots=$(git_clean -C "$work" rev-list --max-parents=0 "$BRANCH")
[[ -n "$roots" && "$roots" != *$'\n'* ]] || die "expected one root commit, found: ${roots:-none}"
cut_new=$(awk -v c="$CUT_COMMIT" '$1 == c { print $2 }' "$work/filter-repo/commit-map")
[[ -n "$cut_new" && "$cut_new" == "$roots" ]] ||
    die "the root commit is not the rewritten cut commit (root $roots, cut maps to ${cut_new:-nothing})"

earliest=$(git_clean -C "$work" log --format='%as%n%cs' "$BRANCH" | LC_ALL=C sort | head -n 1)
[[ ! "$earliest" < "$EARLIEST_DATE" ]] || die "a commit is dated $earliest, before $EARLIEST_DATE"

# ---------------------------------------------------------------- write --out

if ((replace_out == 1)); then
    say "replacing $out_abs"
    rm -rf -- "$out_abs"
fi
git_clean clone --quiet --no-local --single-branch --no-tags --branch "$BRANCH" -- "$work" "$out_abs"
git_clean -C "$out_abs" remote remove origin
git_clean -C "$out_abs" reflog expire --expire=now --all
[[ -z "$(git_clean -C "$out_abs" status --porcelain)" ]] || die "$out_abs is not clean"

count=$(git_clean -C "$out_abs" rev-list --count "$BRANCH")
say "cut: ${CUT_COMMIT:0:7} -> $roots"
say "first: $(git_clean -C "$out_abs" log -1 --format='%H %aI %s' "$roots")"
say "last:  $(git_clean -C "$out_abs" log -1 --format='%H %aI %s' "$BRANCH")"
say "commits: $count"
say "git: $(git --version | awk '{ print $3 }'), git-filter-repo: $("$filter_repo" --version)"
say "out: $out_abs"
