#!/usr/bin/env bash
# scratch_source.sh: make a throwaway AiTrader clone that holds the working
# publish/ tree as one commit, so extract.sh can be tested before anything is
# committed to AiTrader.
#
# Usage:
#   scratch_source.sh [<AiTrader repo path>]
#
# It clones AiTrader with `git clone --no-local` into a new directory under
# ${TMPDIR:-/tmp}, replaces publish/ in the clone with a copy of the working
# publish/ tree, and makes ONE commit with a fixed author, committer, date and
# message. Then it removes the clone's remote, so the commit cannot be pushed
# back by accident, and prints the clone's path on stdout.
#
# The AiTrader repository is only read. The scratch commit lives in the clone
# and never reaches AiTrader. Delete the printed directory when done.
#
# Then build from it:
#   publish/llm-news-drift/extract.sh --source "$(scratch_source.sh)" --out <dir>

set -euo pipefail

readonly NAME=kirosli00tuff
readonly EMAIL=249804683+kirosli00tuff@users.noreply.github.com
readonly DATE=2026-11-07T00:00:00-07:00
readonly MESSAGE="scratch: P.1 publish sources (never pushed)"

die() {
    printf 'scratch_source.sh: %s\n' "$*" >&2
    exit 1
}

src=${1:-$HOME/Documents/GitHub/AiTrader}
[[ -d "$src/publish" ]] || die "$src/publish is not a directory"
git -C "$src" rev-parse --git-dir >/dev/null 2>&1 || die "$src is not a git repository"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/p1-scratch-source.XXXXXXXX")
clone="$tmp/aitrader"

# Git with no user or system config: no hooks, no signing, no templates from
# this machine can change the commit.
git_clean() {
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git "$@"
}

git_clean clone --quiet --no-local -- "$src" "$clone" >&2
git_clean -C "$clone" remote remove origin

# Copy the working publish/ tree in, replacing any committed copy.
rm -rf -- "$clone/publish"
cp -a -- "$src/publish" "$clone/publish"
find "$clone/publish" -name __pycache__ -type d -prune -exec rm -rf -- {} + >&2

git_clean -C "$clone" add -A -- publish
# Files that .gitignore keeps out of the commit would also stay out of a real
# commit. List them so a missing file is noticed.
ignored=$(git_clean -C "$clone" status --porcelain --ignored -- publish | sed -n 's/^!! //p')
if [[ -n "$ignored" ]]; then
    printf 'scratch_source.sh: ignored under publish/, not committed:\n%s\n' "$ignored" >&2
fi

GIT_AUTHOR_NAME=$NAME GIT_AUTHOR_EMAIL=$EMAIL GIT_AUTHOR_DATE=$DATE \
    GIT_COMMITTER_NAME=$NAME GIT_COMMITTER_EMAIL=$EMAIL GIT_COMMITTER_DATE=$DATE \
    git_clean -C "$clone" commit --quiet --allow-empty --no-verify -m "$MESSAGE" >&2

printf 'scratch_source.sh: commit %s on %s\n' \
    "$(git_clean -C "$clone" rev-parse HEAD)" \
    "$(git_clean -C "$clone" rev-parse HEAD^)" >&2
printf '%s\n' "$clone"
