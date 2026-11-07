#!/usr/bin/env bash
# build_archive.sh: deterministic build of the public research-archive repo (Stage P.1, D5).
#
# Usage:
#   build_archive.sh [--config-dir DIR] [--out DIR] [--report FILE] [--replace-text FILE] [--force]
#                    [--stub-missing] [--keep-work]
#
#   --config-dir DIR  folder with SOURCES.txt, EXCLUDE.txt, mailmap.txt, README.md and cards/
#                     (default: the folder that holds this script)
#   --out DIR         where the archive repo is written (default: ~/Documents/GitHub/research-archive)
#   --report FILE     build report (default: <AiTrader>/reports/p1_scratch/archive_build_report.md)
#   --replace-text FILE  git-filter-repo replace-text rules, applied to every blob and every commit message
#                     (default: ~/.config/p1-private/research-archive.replace-text). The build stops when
#                     the file is missing. It never builds without it. The file must not sit in a git repo.
#   --force           replace an existing --out, but only one that holds nothing except an earlier build
#   --stub-missing    write a stub for a missing card or README. For testing only, never for the real build.
#   --keep-work       keep the temporary work folder (filtered clones, path lists, stats) and print its path
#
# What it does:
#   1. Every source is read-only. It is cloned with `git clone --no-local` into a temporary folder, and any
#      other read of a source uses `git --no-optional-locks`. Nothing is ever written inside a source.
#   2. For each INCLUDE source, a pre-pass over every (path, blob) in the clone's full history finds
#      R1 hits (JSON that parses as a list of exactly 64 integers 0-255, whatever the file name) and
#      R2 hits (a blob over 1048576 bytes whose extension is not code or markdown). Each hit path is added,
#      as a literal, to that source's exclusion list after the lines of EXCLUDE.txt.
#   3. git-filter-repo then removes the excluded paths, applies the mailmap and the replace-text rules
#      (blobs and messages) and moves the tree under <group>/<name>/, in one run. The path rules come
#      before --to-subdirectory-filter on the command line, and git-filter-repo applies path changes in
#      command-line order, so the rules see the ORIGINAL paths. The helper checks it on every source: the paths that disappear must be exactly the paths
#      the rules match before the move, or the build stops.
#   4. The archive gets an empty root commit, one --no-ff merge per INCLUDE source in order of first
#      commit author date (ties broken by name), and a last commit with README.md, EXCLUDE.txt and every
#      card. A CARDONLY source gets its card and nothing else.
#   5. After filtering, every source and then the whole archive are scanned for each replace-text literal
#      (case-insensitive, also as UTF-16) in blobs, commit messages and identities. Any hit stops the build.
#      Literals are never printed: rules are named by number only.
#   6. A build report lists, per source, the paths each rule removed, commit counts before and after
#      filtering, and the replace-text hit counts before and after filtering, by rule number.
#
# Determinism: identities and dates are fixed through GIT_AUTHOR_* and GIT_COMMITTER_*, user and system
# git config are ignored, LC_ALL=C and TZ=UTC, inputs are sorted, and nothing random or timestamped goes
# into a commit. Two runs with the same inputs and tool versions give the same commit hashes.

set -euo pipefail

readonly IDENT_NAME='kirosli00tuff'
readonly IDENT_EMAIL='249804683+kirosli00tuff@users.noreply.github.com'
readonly ROOT_SUBJECT='start research archive'
readonly FINAL_SUBJECT='add experiment cards and index'
readonly FINAL_DATE_ISO='2026-11-07T00:00:00-07:00'
# `git-filter-repo --version` prints this for release 2.47.0. Another version could filter differently.
readonly FILTER_REPO_VERSION='a40bce548d2c'
readonly MIN_FREE_MB=2000
readonly NICE_LEVEL=10

script_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
script_dir="$(dirname -- "$script_path")"

# Run at low priority. Re-run this script under nice when the shell is not already niced enough.
current_nice="$(nice)"
if (( current_nice < NICE_LEVEL )); then
  exec nice -n "$(( NICE_LEVEL - current_nice ))" bash "$script_path" "$@"
fi

log() { printf '%s\n' "$*" >&2; }
die() { printf 'build_archive.sh: error: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,19p' "$script_path" | sed 's/^# \{0,1\}//'; }

# ---------------------------------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------------------------------
config_dir="$script_dir"
out_dir="$HOME/Documents/GitHub/research-archive"
report=""
force=0
stub_missing=0
keep_work=0
replace_text=""
readonly REPLACE_TEXT_DEFAULT="$HOME/.config/p1-private/research-archive.replace-text"

while (( $# )); do
  case "$1" in
    --config-dir) (( $# >= 2 )) || die "--config-dir needs a value"; config_dir="$2"; shift 2 ;;
    --config-dir=*) config_dir="${1#*=}"; shift ;;
    --out) (( $# >= 2 )) || die "--out needs a value"; out_dir="$2"; shift 2 ;;
    --out=*) out_dir="${1#*=}"; shift ;;
    --report) (( $# >= 2 )) || die "--report needs a value"; report="$2"; shift 2 ;;
    --report=*) report="${1#*=}"; shift ;;
    --replace-text) (( $# >= 2 )) || die "--replace-text needs a value"; replace_text="$2"; shift 2 ;;
    --replace-text=*) replace_text="${1#*=}"; shift ;;
    --force) force=1; shift ;;
    --stub-missing) stub_missing=1; shift ;;
    --keep-work) keep_work=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

# Only one build at a time: hold a lock on this script file for the whole run.
exec 9<"$script_path"
flock -n 9 || die "another build_archive.sh run holds the lock on $script_path"

# ---------------------------------------------------------------------------------------------------------
# A fixed environment for git: no user or system config, no hooks, no signing, no auto gc, fixed identity.
# ---------------------------------------------------------------------------------------------------------
export LC_ALL=C TZ=UTC
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES \
      GIT_NAMESPACE GIT_CONFIG GIT_CONFIG_PARAMETERS GIT_CEILING_DIRECTORIES GIT_REPLACE_REF_BASE \
      GIT_AUTHOR_DATE GIT_COMMITTER_DATE GIT_TRACE GIT_TRACE2 PYTHONPATH PYTHONHOME
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export GIT_TERMINAL_PROMPT=0 GIT_EDITOR=true GIT_MERGE_AUTOEDIT=no GIT_NO_REPLACE_OBJECTS=1
export GIT_AUTHOR_NAME="$IDENT_NAME" GIT_AUTHOR_EMAIL="$IDENT_EMAIL"
export GIT_COMMITTER_NAME="$IDENT_NAME" GIT_COMMITTER_EMAIL="$IDENT_EMAIL"

# Pass config to every git process, git-filter-repo's included, through GIT_CONFIG_COUNT.
set_git_config() {
  local i=0
  while (( $# >= 2 )); do
    export "GIT_CONFIG_KEY_$i=$1" "GIT_CONFIG_VALUE_$i=$2"
    i=$(( i + 1 ))
    shift 2
  done
  export GIT_CONFIG_COUNT="$i"
}
set_git_config \
  commit.gpgSign false \
  tag.gpgSign false \
  gc.auto 0 \
  maintenance.auto false \
  core.autocrlf false \
  core.hooksPath /dev/null \
  merge.log false \
  init.defaultBranch main \
  advice.detachedHead false

# ---------------------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------------------
FILTER_REPO="${FILTER_REPO:-$HOME/.local/bin/git-filter-repo}"
command -v git >/dev/null || die "git not found"
command -v python3 >/dev/null || die "python3 not found"
command -v flock >/dev/null || die "flock not found"
[[ -x "$FILTER_REPO" ]] || die "git-filter-repo not found at $FILTER_REPO (set FILTER_REPO)"
fr_version="$("$FILTER_REPO" --version)"
[[ "$fr_version" == "$FILTER_REPO_VERSION" ]] \
  || die "git-filter-repo --version is '$fr_version', expected '$FILTER_REPO_VERSION' (release 2.47.0)"
python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || die "python3 3.8 or newer needed"

check_mem() {
  local avail
  avail="$(free -m | awk '/^Mem:/ {print $7}')"
  [[ "$avail" =~ ^[0-9]+$ ]] || die "cannot read available memory from free -m"
  (( avail >= MIN_FREE_MB )) || die "only ${avail} MB of memory available, need ${MIN_FREE_MB}"
}
check_mem

# ---------------------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------------------
[[ -d "$config_dir" ]] || die "config dir not found: $config_dir"
config_dir="$(readlink -f -- "$config_dir")"
sources_file="$config_dir/SOURCES.txt"
exclude_file="$config_dir/EXCLUDE.txt"
mailmap_file="$config_dir/mailmap.txt"
readme_file="$config_dir/README.md"
for f in "$sources_file" "$exclude_file" "$mailmap_file"; do
  [[ -f "$f" ]] || die "missing input: $f"
done

aitrader_root="$(git --no-optional-locks -C "$script_dir" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$aitrader_root" ]] || aitrader_root="$(readlink -f -- "$script_dir/../..")"
[[ -n "$report" ]] || report="$aitrader_root/reports/p1_scratch/archive_build_report.md"

# The replace-text rules (R1, R4, R12). The build never runs without them. The file holds private
# literals, so it must sit outside every git repo, and no part of it is ever printed or recorded.
if [[ -z "$replace_text" ]]; then
  [[ -f "$REPLACE_TEXT_DEFAULT" ]] \
    || die "no replace-text file: the default $REPLACE_TEXT_DEFAULT is missing and --replace-text was not given. The build never runs without the replace-text rules."
  replace_text="$REPLACE_TEXT_DEFAULT"
fi
[[ -f "$replace_text" && -r "$replace_text" ]] || die "--replace-text $replace_text is not a readable file"
[[ -s "$replace_text" ]] || die "--replace-text $replace_text is empty"
replace_text="$(readlink -f -- "$replace_text")"
if git --no-optional-locks -C "$(dirname -- "$replace_text")" rev-parse --git-dir >/dev/null 2>&1; then
  die "--replace-text $replace_text lies inside a git repository. Keep it outside every repo (R12)."
fi

# SOURCES.txt: one TAB between six fields: group, name, path, branch, side, status.
S_GROUP=() S_NAME=() S_PATH=() S_BRANCH=() S_STATUS=()
lineno=0
while IFS= read -r line || [[ -n "$line" ]]; do
  lineno=$(( lineno + 1 ))
  line="${line%$'\r'}"
  [[ -z "$line" || "$line" == \#* ]] && continue
  tabs="${line//[^$'\t']/}"
  (( ${#tabs} == 5 )) || die "SOURCES.txt line $lineno: expected 6 TAB-separated fields"
  IFS=$'\t' read -r group name path branch side status <<<"$line"
  [[ "$group" =~ ^(experiments|solana)$ ]] || die "SOURCES.txt line $lineno: bad group '$group'"
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "SOURCES.txt line $lineno: bad name '$name'"
  [[ "$path" == /* ]] || die "SOURCES.txt line $lineno: path must be absolute"
  [[ "$branch" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "SOURCES.txt line $lineno: bad branch '$branch'"
  [[ "$side" == local ]] \
    || die "SOURCES.txt line $lineno: side '$side' is not supported, this build imports local history only"
  [[ "$status" =~ ^(INCLUDE|CARDONLY)$ ]] || die "SOURCES.txt line $lineno: bad status '$status'"
  for seen in "${S_NAME[@]}"; do
    [[ "$seen" != "$name" ]] || die "SOURCES.txt line $lineno: duplicate name '$name'"
  done
  if [[ "$status" == INCLUDE ]]; then
    [[ -d "$path" ]] || die "source not found: $path"
    git --no-optional-locks -C "$path" rev-parse --verify --quiet "refs/heads/$branch^{commit}" >/dev/null \
      || die "source $name has no branch $branch"
  fi
  S_GROUP+=("$group") S_NAME+=("$name") S_PATH+=("$path") S_BRANCH+=("$branch") S_STATUS+=("$status")
done <"$sources_file"
(( ${#S_NAME[@]} > 0 )) || die "SOURCES.txt lists no source"

# Cards and README: every one must exist unless --stub-missing. Fail now, before the long work.
missing=()
for i in "${!S_NAME[@]}"; do
  card="$config_dir/cards/${S_GROUP[$i]}/${S_NAME[$i]}/CARD.md"
  [[ -f "$card" ]] || missing+=("$card")
done
[[ -f "$readme_file" ]] || missing+=("$readme_file")
if (( ${#missing[@]} )) && (( ! stub_missing )); then
  printf 'missing: %s\n' "${missing[@]}" >&2
  die "${#missing[@]} card or README file(s) missing (--stub-missing writes stubs, for testing only)"
fi

# ---------------------------------------------------------------------------------------------------------
# Output location: never inside or around a source, AiTrader or the config dir
# ---------------------------------------------------------------------------------------------------------
# is_within A B: true when resolved path A is B or lies under B.
is_within() { [[ "$1" == "$2" || "$1" == "$2"/* ]]; }

out_abs="$(realpath -m -- "$out_dir")"
report_abs="$(realpath -m -- "$report")"
[[ "$out_abs" != / ]] || die "--out cannot be /"
[[ "$out_abs" != "$(realpath -m -- "$HOME")" ]] || die "--out cannot be your home folder"
guards=("$aitrader_root" "$config_dir")
[[ -d "$HOME/Documents/GitHub/AiTrader" ]] && guards+=("$(realpath -m -- "$HOME/Documents/GitHub/AiTrader")")
for p in "${S_PATH[@]}"; do guards+=("$(realpath -m -- "$p")"); done
for g in "${guards[@]}"; do
  if is_within "$out_abs" "$g" || is_within "$g" "$out_abs"; then
    die "--out $out_abs overlaps $g (a source, AiTrader or the config dir)"
  fi
done
is_within "$report_abs" "$out_abs" && die "--report cannot be inside --out"
for p in "${S_PATH[@]}"; do
  is_within "$report_abs" "$(realpath -m -- "$p")" && die "--report cannot be inside a source"
done

if [[ -e "$out_abs" ]]; then
  [[ -d "$out_abs" ]] || die "--out exists and is not a folder: $out_abs"
  if [[ -n "$(ls -A -- "$out_abs")" ]]; then
    (( force )) || die "--out is not empty: $out_abs (use --force to replace an earlier build)"
    # --force removes only a folder that looks like an earlier build: .git, the two groups, the two
    # root files, and nothing else at the top level.
    while IFS= read -r entry; do
      case "$entry" in
        .git|experiments|solana|README.md|EXCLUDE.txt) ;;
        *) die "--force refused: $out_abs holds '$entry', so it does not look like an earlier build" ;;
      esac
    done < <(ls -A -- "$out_abs")
    [[ -d "$out_abs/.git" ]] || die "--force refused: $out_abs has no .git, so it is not an earlier build"
    log "removing the earlier build at $out_abs (--force)"
    rm -rf -- "$out_abs"
  fi
fi

# ---------------------------------------------------------------------------------------------------------
# Work folder and helper
# ---------------------------------------------------------------------------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/build_archive.XXXXXX")"
LOG="$WORK/build.log"
cleanup() {
  local rc=$?
  # The private rules never stay behind, not even with --keep-work.
  rm -f -- "$WORK/replace-text"
  if (( rc != 0 )); then
    log "build failed (exit $rc). Last lines of $LOG:"
    tail -n 20 "$LOG" >&2 2>/dev/null || true
    [[ -d "$out_abs" ]] && log "the archive at $out_abs is incomplete; rerun with --force"
  fi
  if (( keep_work )); then
    log "work folder kept: $WORK"
  else
    rm -rf -- "$WORK"
  fi
}
trap cleanup EXIT
mkdir -p "$WORK/src" "$WORK/stats" "$WORK/paths" "$WORK/stubs"
: >"$LOG"
# One private copy of the rules for the whole run, so every step reads the same rules.
( umask 077 && cp -- "$replace_text" "$WORK/replace-text" )
RT="$WORK/replace-text"

cat >"$WORK/helper.py" <<'PYEOF'
"""Helper for build_archive.sh. It reads git data from the temporary clones and from the built
archive. It never opens a source repo."""
import collections
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
import threading

R2_LIMIT = 1048576
CODE_OR_MD = frozenset(b'py rs ts tsx js jsx mjs cjs sh c h cpp hpp go sql toml md rst'.split())
# A JSON list of 64 integers 0-255 holds only digits, '[', ']', ',', '-', JSON whitespace, and in
# UTF-16 or UTF-32 NUL and BOM bytes. Without whitespace, NUL and BOM bytes it is at most 257 bytes
# long, so a blob with more than 300 other bytes cannot be one and is not parsed.
R1_SKIP = b' \t\r\n\x00\xef\xbb\xbf\xfe\xff'
R1_MAX_CORE = 300
ZERO_SHA = '0' * 40


def die(msg):
    sys.stderr.write('build_archive.sh helper: error: ' + msg + '\n')
    raise SystemExit(1)


def s(raw):
    return raw.decode('utf-8', 'surrogateescape')


def b(text):
    return text.encode('utf-8', 'surrogateescape')


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], stdout=subprocess.PIPE, check=True).stdout


def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def dump(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.write('\n')


def commits_of(repo):
    return git(repo, 'rev-list', '--all').split()


def tree_pairs(repo, commits):
    """Every distinct (path, mode, type, object, size) in the trees of the given commits."""
    pairs = set()
    for commit in commits:
        for rec in git(repo, 'ls-tree', '-r', '-l', '-z', '--full-tree', commit).split(b'\0'):
            if not rec:
                continue
            meta, path = rec.split(b'\t', 1)
            mode, typ, obj, size = meta.split()
            pairs.add((path, mode, typ, obj, -1 if size == b'-' else int(size)))
    return pairs


def iter_blobs(repo, shas):
    """Yield (sha, content) for every blob sha, through one `git cat-file --batch`."""
    shas = sorted(shas)
    proc = subprocess.Popen(['git', '-C', repo, 'cat-file', '--batch'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def feed():
        try:
            for sha in shas:
                proc.stdin.write(sha + b'\n')
        finally:
            proc.stdin.close()

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    for sha in shas:
        header = proc.stdout.readline().split()
        if len(header) != 3 or header[0] != sha or header[1] != b'blob':
            die('git cat-file returned %r for %s' % (header, s(sha)))
        size = int(header[2])
        data = proc.stdout.read(size)
        if len(data) != size or proc.stdout.read(1) != b'\n':
            die('short read from git cat-file for %s' % s(sha))
        yield sha, data
    writer.join()
    proc.stdout.close()
    if proc.wait() != 0:
        die('git cat-file failed')


def is_keypair_json(data):
    """R1: the blob parses as JSON into a list of exactly 64 integers, each 0 to 255."""
    core = data.translate(None, R1_SKIP)
    if len(core) > R1_MAX_CORE or not core.startswith(b'['):
        return False
    try:
        value = json.loads(data.decode(json.detect_encoding(data)))
    except (ValueError, UnicodeError, LookupError, RecursionError):
        return False
    return (isinstance(value, list) and len(value) == 64
            and all(type(x) is int and 0 <= x <= 255 for x in value))


def ext_of(path):
    base = path.rsplit(b'/', 1)[-1]
    stem, dot, ext = base.rpartition(b'.')
    return ext.lower() if dot and stem else b''


def commit_rows(repo, *rev_args):
    """Hash, parent count, raw author date, identities and message of each commit."""
    fmt = '--format=%H%x01%P%x01%ad%x01%an <%ae>%x01%cn <%ce>%x01%B'
    out = git(repo, 'log', '-z', '--date=raw', fmt, *(rev_args or ('--all',)))
    rows = []
    for rec in out.split(b'\0'):
        if not rec:
            continue
        fields = rec.split(b'\x01', 5)
        if len(fields) != 6:
            die('cannot parse a git log record in ' + repo)
        sha, parents, adate, author, committer, msg = fields
        ts, off = adate.split()
        rows.append({'sha': s(sha), 'parents': len(parents.split()), 'ts': int(ts), 'off': s(off),
                     'author': s(author), 'committer': s(committer), 'msg': s(msg)})
    return rows


def date_info(row):
    off = row['off']
    secs = (-1 if off[0] == '-' else 1) * (int(off[1:3]) * 3600 + int(off[3:5]) * 60)
    when = datetime.datetime.fromtimestamp(row['ts'], datetime.timezone(datetime.timedelta(seconds=secs)))
    return {'sha': row['sha'], 'ts': row['ts'], 'raw': '%d %s' % (row['ts'], off),
            'date': when.date().isoformat(), 'iso': when.isoformat()}


def span(rows, tip):
    """First and last commit by author date (ties by hash), plus the root and tip commits."""
    first = min(rows, key=lambda r: (r['ts'], r['sha']))
    last = max(rows, key=lambda r: (r['ts'], r['sha']))
    roots = sorted((r for r in rows if r['parents'] == 0), key=lambda r: (r['ts'], r['sha']))
    tip_row = next(r for r in rows if r['sha'] == tip)
    return {'first': date_info(first), 'last': date_info(last),
            'roots': [date_info(r) for r in roots], 'tip': date_info(tip_row)}


# Path rules, parsed and matched exactly as git-filter-repo 2.47.0 does it
# (FilteringOptions.get_paths_from_file and RepoFilter._filter_files.filename_matches).
def parse_rules(path):
    rules = []
    with open(path, 'rb') as f:
        for raw in f:
            line = raw.rstrip(b'\r\n')
            if not line or line.startswith(b'#'):
                continue
            if b'==>' in line:
                die('rename lines are not allowed in an exclusion list: %s' % s(line))
            if line.startswith(b'regex:'):
                rules.append((s(line), 'regex', re.compile(line[6:])))
            elif line.startswith(b'glob:'):
                pat = line[5:]
                rules.append((s(line), 'glob', pat))
                if not pat.endswith(b'*'):
                    rules.append((s(line), 'glob', pat + (b'*' if pat.endswith(b'/') else b'/*')))
            else:
                rules.append((s(line), 'match', line[8:] if line.startswith(b'literal:') else line))
    return rules


def filename_matches(expr, path):
    if expr == b'':
        return True
    n = len(expr)
    return path.startswith(expr) and (expr[n - 1:n] == b'/' or len(path) == n or path[n:n + 1] == b'/')


def first_rule(rules, path):
    for label, kind, expr in rules:
        if kind == 'match' and filename_matches(expr, path):
            return label
        if kind == 'glob' and fnmatch.fnmatch(path, expr):
            return label
        if kind == 'regex' and expr.search(path):
            return label
    return None


# Replace-text literals, parsed as git-filter-repo 2.47.0 does it (FilteringOptions.get_replace_text).
# The literals are private. Nothing here prints one: rules are named by number only.
def load_literals(path):
    lits = []
    with open(path, 'rb') as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip(b'\r\n')
            if b'==>' in line:
                line = line.rsplit(b'==>', 1)[0]
            if line.startswith(b'regex:') or line.startswith(b'glob:'):
                die('replace-text line %d is a regex or glob rule; only literal rules can be checked' % lineno)
            if line.startswith(b'literal:'):
                line = line[8:]
            if not line:
                continue
            if not line.isascii():
                die('replace-text line %d is not ASCII; the case-insensitive check needs ASCII' % lineno)
            lits.append(line.lower())
    if not lits:
        die('the replace-text file holds no rule')
    return lits


def literal_counts(data, lits):
    """Per rule: case-insensitive occurrences in data, as bytes and as UTF-16 (LE and BE)."""
    low = data.lower()
    return [low.count(lit) + low.count(lit.decode('ascii').encode('utf-16-le'))
            + low.count(lit.decode('ascii').encode('utf-16-be')) for lit in lits]


def scan_literals(repo, lits, pairs, rows):
    """Hits of each literal in every blob of every commit, in every message and in every identity."""
    blob_paths = collections.defaultdict(set)
    for path, _mode, typ, obj, _size in pairs:
        if typ == b'blob':
            blob_paths[obj].add(path)
    found = [{'rule': i + 1, 'blobs': [], 'msgs': [], 'idents': []} for i in range(len(lits))]
    for sha, data in iter_blobs(repo, blob_paths):
        for i, n in enumerate(literal_counts(data, lits)):
            if n:
                found[i]['blobs'].append({'blob': s(sha), 'count': n,
                                          'paths': sorted(s(p) for p in blob_paths[sha])})
    for r in rows:
        for i, n in enumerate(literal_counts(b(r['msg']), lits)):
            if n:
                found[i]['msgs'].append({'sha': r['sha'], 'count': n})
        for i, n in enumerate(literal_counts(b(r['author'] + '\n' + r['committer']), lits)):
            if n:
                found[i]['idents'].append(r['sha'])
    return found


def literal_summary(found):
    return [{'rule': f['rule'], 'blobs': len(f['blobs']), 'blob_hits': sum(x['count'] for x in f['blobs']),
             'msgs': len(f['msgs']), 'msg_hits': sum(x['count'] for x in f['msgs']),
             'idents': len(f['idents'])} for f in found]


def die_on_literals(where, found):
    bad = []
    for f in found:
        if f['blobs'] or f['msgs'] or f['idents']:
            bad.append('rule %d: %d blob(s) %s, %d message(s) %s, %d identity hit(s)' % (
                f['rule'], len(f['blobs']), sorted({p for x in f['blobs'] for p in x['paths']})[:5],
                len(f['msgs']), [x['sha'][:12] for x in f['msgs']][:5], len(f['idents'])))
    if bad:
        die('%s: replace-text literals remain after filtering (git-filter-repo skips binary blobs and '
            'matches case-sensitively): %s' % (where, '; '.join(bad)))


def cmd_rules(replace_text):
    sys.stdout.write('%d\n' % len(load_literals(replace_text)))


def cmd_scan(repo, replace_text, out_json):
    """The whole built archive: every blob of every commit, every message and identity. Stops on a hit."""
    lits = load_literals(replace_text)
    commits = commits_of(repo)
    found = scan_literals(repo, lits, tree_pairs(repo, commits), commit_rows(repo))
    dump({'commits': len(commits), 'rules': len(lits), 'summary': literal_summary(found)}, out_json)
    die_on_literals('the archive', found)
    sys.stdout.write('replace-text scan of the archive: %d commits, %d rules, 0 hits in blobs, messages '
                     'and identities\n' % (len(commits), len(lits)))


def cmd_prepass(clone, out_json, hits_file, replace_text):
    lits = load_literals(replace_text)
    commits = commits_of(clone)
    pairs = tree_pairs(clone, commits)
    blob_shas = {p[3] for p in pairs if p[2] == b'blob'}
    keypair_blobs = {sha for sha, data in iter_blobs(clone, blob_shas) if is_keypair_json(data)}
    r1 = sorted({p[0] for p in pairs if p[3] in keypair_blobs})
    r2 = {}
    for path, _mode, typ, _obj, size in pairs:
        if typ == b'blob' and size > R2_LIMIT and ext_of(path) not in CODE_OR_MD:
            r2[path] = max(size, r2.get(path, 0))
    hits = sorted(set(r1) | set(r2))
    bad = [h for h in hits if b'\n' in h or b'\r' in h or b'==>' in h]
    if bad:
        die('hit paths that a paths file cannot hold literally: %r' % bad)
    with open(hits_file, 'wb') as f:
        for hit in hits:
            f.write(b'literal:' + hit + b'\n')
    tip = s(git(clone, 'rev-parse', 'HEAD').strip())
    rows = commit_rows(clone)
    lit_before = literal_summary(scan_literals(clone, lits, pairs, rows))
    dump({
        'lit_before': lit_before,
        'commits_before': len(commits),
        'span_before': span(rows, tip),
        'paths': sorted({s(q[0]) for q in pairs}),
        'pairs_before': len(pairs),
        'blobs_before': len(blob_shas),
        'r1': [s(p) for p in r1],
        'r2': {s(p): z for p, z in sorted(r2.items())},
        'gitlinks': sorted({s(p[0]) for p in pairs if p[2] == b'commit'}),
        'attributes': sorted({s(p[0]) for p in pairs
                              if p[0].rsplit(b'/', 1)[-1] in (b'.gitattributes', b'.gitmodules', b'.lfsconfig')}),
        'messages': {r['sha']: r['msg'] for r in rows},
        'idents_before': sorted({r['author'] for r in rows} | {r['committer'] for r in rows}),
    }, out_json)


def cmd_post(clone, name, prefix, exclude_file, hits_file, pre_json, out_json, replace_text):
    lits = load_literals(replace_text)
    pre = load(pre_json)
    commits = commits_of(clone)
    pairs = tree_pairs(clone, commits)
    pfx = b(prefix) + b'/'
    kept = set()
    for path, *_rest in pairs:
        if not path.startswith(pfx):
            die('%s: path outside %s after filtering: %s' % (name, prefix, s(path)))
        kept.add(path[len(pfx):])
    before = {b(p) for p in pre['paths']}
    ex_rules = parse_rules(exclude_file)
    hit_rules = parse_rules(hits_file)
    removed_by = {}
    for path in before:
        label = first_rule(ex_rules + hit_rules, path)
        if label is not None:
            removed_by[path] = label
    actual = before - kept
    new = kept - before
    if new or set(removed_by) != actual:
        die('%s: the removed paths differ from the paths the rules match on ORIGINAL paths. '
            'new: %s; removed but not matched: %s; matched but kept: %s' % (
                name, sorted(map(s, new))[:5], sorted(map(s, actual - set(removed_by)))[:5],
                sorted(map(s, set(removed_by) - actual))[:5]))
    by_rule = collections.OrderedDict((label, []) for label, _k, _e in ex_rules + hit_rules)
    for path, label in sorted(removed_by.items()):
        by_rule[label].append(s(path))
    hits = []
    for path in sorted(set(pre['r1']) | set(pre['r2'])):
        hits.append({'path': path, 'r1': path in pre['r1'], 'r2_size': pre['r2'].get(path),
                     'exclude_rule': first_rule(ex_rules, b(path))})

    tip = s(git(clone, 'rev-parse', 'HEAD').strip())
    rows = commit_rows(clone)
    span_after = span(rows, tip)
    found = scan_literals(clone, lits, pairs, rows)
    die_on_literals(name, found)
    changed, pruned = [], 0
    map_file = os.path.join(clone, 'filter-repo', 'commit-map')
    new_msgs = {r['sha']: r['msg'] for r in rows}
    with open(map_file, encoding='ascii') as f:
        for line in f.read().split('\n')[1:]:
            if not line.strip():
                continue
            old, new_sha = line.split()
            if new_sha == ZERO_SHA:
                pruned += 1
            elif pre['messages'].get(old) != new_msgs.get(new_sha):
                changed.append({'old': old, 'new': new_sha})
    dump({
        'name': name,
        'prefix': prefix,
        'tip': tip,
        'commits_after': len(commits),
        'span_after': span_after,
        'first': span_after['first'],
        'last': span_after['last'],
        'paths_before': len(before),
        'paths_kept': len(kept),
        'paths_removed': len(actual),
        'by_rule': by_rule,
        'exclude_labels': [label for label, _k, _e in ex_rules],
        'hits': hits,
        'lit_after': literal_summary(found),
        'idents_after': dict(collections.Counter(
            ['author ' + r['author'] for r in rows] + ['committer ' + r['committer'] for r in rows])),
        'messages_changed': changed,
        'pruned': pruned,
    }, out_json)


def cmd_plan(stats_dir, plan_file, *names):
    posts = sorted((load(os.path.join(stats_dir, n + '.post.json')) for n in names),
                   key=lambda p: (p['first']['ts'], p['name']))
    with open(plan_file, 'w', encoding='utf-8') as f:
        f.write('ROOT\t%s\n' % posts[0]['first']['raw'])
        for p in posts:
            n = p['commits_after']
            msg = 'import %s history (%s..%s, %d %s)' % (
                p['name'], p['first']['date'], p['last']['date'], n, 'commit' if n == 1 else 'commits')
            f.write('MERGE\t%s\t%s\t%s\n' % (p['name'], p['last']['raw'], msg))


def fence(lines):
    return ['```'] + list(lines) + ['```']


def cmd_report(work, out, report_path, meta_file):
    meta = collections.defaultdict(list)
    with open(meta_file, encoding='utf-8') as f:
        for line in f:
            key, _sep, value = line.rstrip('\n').partition('\t')
            meta[key].append(value)
    one = lambda key: meta[key][0] if meta[key] else ''
    sources = [v.split('\t') for v in meta['source']]   # group, name, status, branch, path
    order = []
    with open(os.path.join(work, 'plan.tsv'), encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if parts[0] == 'MERGE':
                order.append(parts[1])
    stats = os.path.join(work, 'stats')
    pre = {n: load(os.path.join(stats, n + '.pre.json')) for n in order}
    post = {n: load(os.path.join(stats, n + '.post.json')) for n in order}
    rows = commit_rows(out)
    head = s(git(out, 'rev-parse', 'HEAD').strip())
    first_parent = git(out, 'log', '--first-parent', '--reverse', '--format=%H%x01%P%x01%s', 'HEAD')
    chain = [line.split(b'\x01') for line in first_parent.splitlines()]
    merges = {}
    for sha, parents, subject in chain:
        if len(parents.split()) == 2:
            merges[s(subject).split(' ')[1]] = (s(sha), s(subject), s(parents.split()[1]))
    idents = collections.Counter(['author ' + r['author'] for r in rows] +
                                 ['committer ' + r['committer'] for r in rows])
    scan = load(os.path.join(work, 'stats', 'archive.scan.json'))

    L = []
    w = L.append
    w('# research-archive build report')
    w('')
    w('Written by build_archive.sh. The first four lines change between runs. Nothing in the archive does.')
    w('')
    w('- Run started (UTC): %s, finished: %s' % (one('started'), one('finished')))
    w('- Output: `%s`' % out)
    w('- Work folder: %s' % one('work'))
    w('- Flags: %s' % (one('flags') or 'none'))
    w('- Config dir: `%s`' % one('config_dir'))
    w('- Tools: %s; git-filter-repo 2.47.0 (`--version` %s); python %s' % (
        one('git_version'), one('filter_repo_version'), one('python_version')))
    w('- Inputs (sha256):')
    for value in meta['input']:
        name, digest = value.split('\t')
        w('  - `%s` %s' % (name, digest))
    stubs = meta['stub']
    if stubs:
        w('- STUBS WRITTEN (--stub-missing, testing only, %d): %s' % (len(stubs), ', '.join('`%s`' % x for x in stubs)))
    else:
        w('- Stubs written: none')
    w('- Archive: %d commits. Root `%s`. Head `%s`. Branches: %s.' % (
        len(rows), s(git(out, 'rev-list', '--first-parent', '--max-parents=0', 'HEAD').strip()), head, one('refs')))
    w('- Working tree after the last commit: %s' % (one('status') or 'clean'))
    w('- .git size after gc: %s bytes' % one('git_size'))
    w('')
    w('## Merge order')
    w('')
    w('Sources are merged in order of first commit author date, ties by name. First and last are the '
      'earliest and latest author dates after filtering, in each commit\'s own offset.')
    w('')
    w('| # | source | group | first | last | commits before | after | pruned | merge commit | subject |')
    w('|---|---|---|---|---|---|---|---|---|---|')
    for i, n in enumerate(order, 1):
        p = post[n]
        sha, subject, _tip = merges.get(n, ('MISSING', 'MISSING', ''))
        w('| %d | %s | %s | %s | %s | %d | %d | %d | `%s` | %s |' % (
            i, n, p['prefix'].split('/')[0], p['first']['iso'], p['last']['iso'],
            pre[n]['commits_before'], p['commits_after'], p['pruned'], sha[:12], subject))
    cardonly = [x for x in sources if x[2] == 'CARDONLY']
    w('')
    w('Card only (no history): %s' % (', '.join(x[1] for x in cardonly) if cardonly else 'none'))
    w('')
    w('## Removed paths, summary')
    w('')
    w('Paths are distinct paths over the full history. "R1 new" and "R2 new" count paths removed only '
      'because of a content hit. "Hits covered" counts R1 or R2 hits that EXCLUDE.txt removed anyway.')
    w('')
    w('| source | paths before | kept | removed | by EXCLUDE.txt | R1 new | R2 new | hits covered |')
    w('|---|---|---|---|---|---|---|---|')
    for n in order:
        p = post[n]
        ex = sum(len(v) for k, v in p['by_rule'].items() if k in p['exclude_labels'])
        r1n = sum(1 for h in p['hits'] if h['r1'] and h['exclude_rule'] is None)
        r2n = sum(1 for h in p['hits'] if h['r2_size'] and h['exclude_rule'] is None)
        cov = sum(1 for h in p['hits'] if h['exclude_rule'] is not None)
        w('| %s | %d | %d | %d | %d | %d | %d | %d |' % (
            n, p['paths_before'], p['paths_kept'], p['paths_removed'], ex, r1n, r2n, cov))
    w('')
    w('## Replace-text rules')
    w('')
    w('Rules: %s. git-filter-repo applied them to every blob (not binary ones) and every commit message. '
      'Rules are named by number only, and no literal is printed. Counts are case-insensitive and include '
      'UTF-16. "Before" is the clone before filtering, all paths. "After" is the filtered history; any '
      'hit there stops the build. Rows with no hit before are left out.' % one('replace_text'))
    w('')
    w('| source | rule | blobs before | hits in blobs before | messages before | identities before | blobs after | messages after | identities after |')
    w('|---|---|---|---|---|---|---|---|---|')
    for n in order:
        for bf, af in zip(pre[n]['lit_before'], post[n]['lit_after']):
            if not (bf['blobs'] or bf['msgs'] or bf['idents'] or af['blobs'] or af['msgs'] or af['idents']):
                continue
            w('| %s | %d | %d | %d | %d | %d | %d | %d | %d |' % (
                n, bf['rule'], bf['blobs'], bf['blob_hits'], bf['msgs'], bf['idents'],
                af['blobs'], af['msgs'], af['idents']))
    w('')
    w('Whole archive after the build (%d commits, every blob of every commit, every message and identity): %s' % (
        scan['commits'], '; '.join('rule %d: %d blobs, %d messages, %d identities' % (
            x['rule'], x['blobs'], x['msgs'], x['idents']) for x in scan['summary'])))
    w('')
    w('## Identities in the archive')
    w('')
    for ident, count in sorted(idents.items()):
        w('- %s: %d' % (ident, count))
    w('')
    w('## Notes per source')
    w('')
    for n in order:
        p, q = post[n], pre[n]
        notes = []
        if p['first']['raw'] != q['span_before']['first']['raw'] or p['last']['raw'] != q['span_before']['last']['raw']:
            notes.append('first or last date changed by filtering: before %s..%s, after %s..%s' % (
                q['span_before']['first']['iso'], q['span_before']['last']['iso'], p['first']['iso'], p['last']['iso']))
        sa = p['span_after']
        if [r['ts'] for r in sa['roots']] != [sa['first']['ts']]:
            notes.append('the earliest author date is not on the single root commit (roots: %s)' % (
                ', '.join('%s %s' % (r['sha'][:12], r['iso']) for r in sa['roots'])))
        if sa['tip']['ts'] != sa['last']['ts']:
            notes.append('the latest author date (%s) is not on the tip commit (%s %s)' % (
                sa['last']['iso'], sa['tip']['sha'][:12], sa['tip']['iso']))
        if p['messages_changed']:
            notes.append('%d commit message(s) differ from the source because git-filter-repo updated '
                         'abbreviated commit hashes or applied the replace-text rules in them'
                         % len(p['messages_changed']))
        if q['gitlinks']:
            notes.append('gitlinks (submodule entries): %s' % ', '.join(q['gitlinks']))
        if q['attributes']:
            notes.append('attribute or module files in history: %s' % ', '.join(q['attributes']))
        if q['idents_before']:
            notes.append('%d distinct identities before the mailmap' % len(q['idents_before']))
        w('- %s: %s' % (n, '; '.join(notes) if notes else 'nothing to note'))
    w('')
    w('## Removed paths, per source and rule')
    w('')
    w('Each removed path is listed once, under the first rule that matches it, in the order the rules '
      'appear in the paths file (EXCLUDE.txt first, then the R1 and R2 literals).')
    for n in order:
        p = post[n]
        w('')
        w('### %s (%s)' % (n, p['prefix']))
        w('')
        w('R1 and R2 hits:')
        if not p['hits']:
            w('- none')
        for h in p['hits']:
            kinds = []
            if h['r1']:
                kinds.append('R1 64-int JSON')
            if h['r2_size']:
                kinds.append('R2 %d bytes' % h['r2_size'])
            cover = ('also matched by EXCLUDE.txt rule `%s`' % h['exclude_rule']) if h['exclude_rule'] \
                else 'removed only because of this hit'
            w('- `%s`: %s; %s' % (h['path'], ', '.join(kinds), cover))
        w('')
        for label, paths in p['by_rule'].items():
            if not paths:
                continue
            src = 'EXCLUDE.txt' if label in p['exclude_labels'] else 'R1/R2 literal'
            w('`%s` (%s): %d path(s)' % (label, src, len(paths)))
            w('')
            L.extend(fence(paths))
            w('')
        unused = [label for label in p['exclude_labels'] if not p['by_rule'].get(label)]
        w('EXCLUDE.txt rules that removed nothing here: %d of %d' % (len(unused), len(p['exclude_labels'])))
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')


def main(argv):
    commands = {'prepass': cmd_prepass, 'post': cmd_post, 'plan': cmd_plan, 'report': cmd_report,
                'scan': cmd_scan, 'rules': cmd_rules}
    if len(argv) < 2 or argv[1] not in commands:
        die('usage: helper.py {%s} ...' % ','.join(sorted(commands)))
    commands[argv[1]](*argv[2:])


if __name__ == '__main__':
    main(sys.argv)
PYEOF

helper() { python3 -I "$WORK/helper.py" "$@"; }
rt_rules="$(helper rules "$RT")" || die "cannot read the replace-text rules"

meta() { printf '%s\t%s\n' "$1" "$2" >>"$WORK/meta.tsv"; }
: >"$WORK/meta.tsv"
meta started "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
meta config_dir "$config_dir"
meta git_version "$(git --version)"
meta filter_repo_version "$fr_version"
meta python_version "$(python3 -I -c 'import platform; print(platform.python_version())')"
# Path and rule count only. No content and no hash: a hash of a short private file would let anyone
# confirm a guessed literal.
meta replace_text "\`$replace_text\` ($rt_rules literal rules; content and hash not recorded)"
flags=()
(( force )) && flags+=(--force)
(( stub_missing )) && flags+=(--stub-missing)
(( keep_work )) && flags+=(--keep-work)
meta flags "${flags[*]:-}"
if (( keep_work )); then meta work "kept at $WORK"; else meta work "deleted at the end"; fi
for f in "$sources_file" "$exclude_file" "$mailmap_file"; do
  meta input "${f#"$config_dir"/}"$'\t'"$(sha256sum <"$f" | cut -d' ' -f1)"
done
for i in "${!S_NAME[@]}"; do
  meta source "${S_GROUP[$i]}"$'\t'"${S_NAME[$i]}"$'\t'"${S_STATUS[$i]}"$'\t'"${S_BRANCH[$i]}"$'\t'"${S_PATH[$i]}"
done

# ---------------------------------------------------------------------------------------------------------
# Clone, scan and filter each INCLUDE source
# ---------------------------------------------------------------------------------------------------------
include_names=()
while IFS=$'\t' read -r i name; do
  [[ "${S_STATUS[$i]}" == INCLUDE ]] || continue
  group="${S_GROUP[$i]}" src="${S_PATH[$i]}" branch="${S_BRANCH[$i]}"
  include_names+=("$name")
  check_mem
  clone="$WORK/src/$name"
  log "[$name] clone $src ($branch)"
  mkdir -p "$clone"
  git --no-optional-locks clone --quiet --no-local --bare --single-branch --no-tags --branch "$branch" \
    -- "$src" "$clone" >>"$LOG" 2>&1
  [[ "$(git -C "$clone" rev-parse --is-bare-repository)" == true ]] || die "$name: clone is not bare"

  log "[$name] pre-pass: R1 and R2 over every (path, blob) in history"
  helper prepass "$clone" "$WORK/stats/$name.pre.json" "$WORK/paths/$name.hits" "$RT"
  {
    cat "$exclude_file"
    printf '\n# R1 and R2 hits for %s, added by build_archive.sh\n' "$name"
    cat "$WORK/paths/$name.hits"
  } >"$WORK/paths/$name.paths"

  log "[$name] git-filter-repo"
  # The order of the options matters: path rules first, then the subdirectory move, so the rules are
  # matched against the original paths. The clone is a fresh clone under $WORK; git-filter-repo's own
  # fresh-clone check stays on (no --force).
  ( cd "$clone" && "$FILTER_REPO" --quiet \
      --paths-from-file "$WORK/paths/$name.paths" --invert-paths \
      --to-subdirectory-filter "$group/$name" \
      --mailmap "$mailmap_file" \
      --replace-text "$RT" --replace-message "$RT" \
      --replace-refs delete-no-add ) >>"$LOG" 2>&1

  log "[$name] check and count"
  helper post "$clone" "$name" "$group/$name" "$exclude_file" "$WORK/paths/$name.hits" \
    "$WORK/stats/$name.pre.json" "$WORK/stats/$name.post.json" "$RT"
done < <(for i in "${!S_NAME[@]}"; do printf '%s\t%s\n' "$i" "${S_NAME[$i]}"; done | sort -t $'\t' -k2,2)
(( ${#include_names[@]} > 0 )) || die "no INCLUDE source"

helper plan "$WORK/stats" "$WORK/plan.tsv" "${include_names[@]}"

# ---------------------------------------------------------------------------------------------------------
# Build the archive
# ---------------------------------------------------------------------------------------------------------
check_mem
log "building the archive at $out_abs"
mkdir -p "$out_abs"
git init --quiet --template= --initial-branch=main -- "$out_abs" >>"$LOG" 2>&1
# Every git call on the archive: no reflogs, so no reflog timestamps.
A() { git -C "$out_abs" -c core.logAllRefUpdates=false "$@"; }

branch_of() {
  local i
  for i in "${!S_NAME[@]}"; do
    [[ "${S_NAME[$i]}" == "$1" ]] && { printf '%s\n' "${S_BRANCH[$i]}"; return 0; }
  done
  die "unknown source $1"
}

root_date="$(awk -F '\t' '$1 == "ROOT" {print $2}' "$WORK/plan.tsv")"
[[ "$root_date" =~ ^[0-9]+\ [+-][0-9]{4}$ ]] || die "bad root date '$root_date'"
GIT_AUTHOR_DATE="$root_date" GIT_COMMITTER_DATE="$root_date" \
  A commit --quiet --allow-empty --no-verify -m "$ROOT_SUBJECT" >>"$LOG" 2>&1

while IFS=$'\t' read -r kind name date msg; do
  [[ "$kind" == MERGE ]] || continue
  [[ "$date" =~ ^[0-9]+\ [+-][0-9]{4}$ ]] || die "bad merge date '$date' for $name"
  log "[$name] merge: $msg"
  branch="$(branch_of "$name")"
  A fetch --quiet --no-tags --no-write-fetch-head -- "$WORK/src/$name" \
    "+refs/heads/$branch:refs/import/$name" >>"$LOG" 2>&1
  tip="$(A rev-parse "refs/import/$name")"
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" \
    A merge --quiet --no-ff --allow-unrelated-histories --no-edit --no-verify --no-log --no-gpg-sign \
      -m "$msg" "refs/import/$name" >>"$LOG" 2>&1
  [[ "$(A rev-parse HEAD^2)" == "$tip" ]] || die "$name: merge did not take the filtered history"
  [[ "$(A log -1 --format=%s HEAD)" == "$msg" ]] || die "$name: merge subject differs"
  A update-ref -d "refs/import/$name"
done <"$WORK/plan.tsv"

# Last commit: README.md and EXCLUDE.txt at the root, and each card in its source folder. Files are stored
# byte for byte (no filters) with mode 100644, and none may replace a path that came from a source.
add_file() {
  local from="$1" rel="$2" sha
  A cat-file -e "HEAD:$rel" 2>/dev/null && die "$rel already exists in the imported history"
  mkdir -p -- "$(dirname -- "$out_abs/$rel")"
  install -m 0644 -- "$from" "$out_abs/$rel"
  sha="$(A hash-object -w --no-filters -- "$out_abs/$rel")"
  A update-index --add --cacheinfo "100644,$sha,$rel"
}

stub() {
  local rel="$1" title="$2" what="$3"
  mkdir -p -- "$(dirname -- "$WORK/stubs/$rel")"
  printf '# %s\n\nSTUB. %s is not written yet. build_archive.sh --stub-missing wrote this file, for testing only.\n' \
    "$title" "$what" >"$WORK/stubs/$rel"
  meta stub "$rel"
  log "STUB written for $rel (--stub-missing, testing only)"
  printf '%s\n' "$WORK/stubs/$rel"
}

if [[ -f "$readme_file" ]]; then
  add_file "$readme_file" README.md
  meta input "README.md"$'\t'"$(sha256sum <"$readme_file" | cut -d' ' -f1)"
else
  add_file "$(stub README.md research-archive 'The index')" README.md
fi
add_file "$exclude_file" EXCLUDE.txt
while IFS=$'\t' read -r i name; do
  rel="${S_GROUP[$i]}/$name/CARD.md"
  card="$config_dir/cards/$rel"
  if [[ -f "$card" ]]; then
    add_file "$card" "$rel"
    meta input "cards/$rel"$'\t'"$(sha256sum <"$card" | cut -d' ' -f1)"
  else
    add_file "$(stub "$rel" "$name" 'The card for this source')" "$rel"
  fi
done < <(for i in "${!S_NAME[@]}"; do printf '%s\t%s\n' "$i" "${S_NAME[$i]}"; done | sort -t $'\t' -k2,2)
# Cards in the config dir for names that SOURCES.txt does not list are not imported. Name them.
if [[ -d "$config_dir/cards" ]]; then
  while IFS= read -r extra; do
    rel="${extra#"$config_dir/cards/"}"
    known=0
    for i in "${!S_NAME[@]}"; do
      [[ "$rel" == "${S_GROUP[$i]}/${S_NAME[$i]}/CARD.md" ]] && known=1
    done
    (( known )) || { meta unused_card "$rel"; log "warning: card not used (no such source): $rel"; }
  done < <(find "$config_dir/cards" -type f -name CARD.md | sort)
fi

final_raw="$(date -d "$FINAL_DATE_ISO" +%s) -0700"
GIT_AUTHOR_DATE="$final_raw" GIT_COMMITTER_DATE="$final_raw" \
  A commit --quiet --no-verify -m "$FINAL_SUBJECT" >>"$LOG" 2>&1
[[ "$(A log -1 --format=%aI HEAD)" == "$FINAL_DATE_ISO" ]] || die "last commit date is not $FINAL_DATE_ISO"

# ---------------------------------------------------------------------------------------------------------
# Clean up the archive repo and check it
# ---------------------------------------------------------------------------------------------------------
status="$(A status --porcelain --untracked-files=all)"
if [[ -n "$status" ]]; then
  printf '%s\n' "$status" >>"$LOG"
  meta status "$(grep -c '' <<<"$status") path(s) differ from the last commit (listed in the build log)"
fi
rm -f -- "$out_abs/.git/ORIG_HEAD" "$out_abs/.git/FETCH_HEAD" "$out_abs/.git/AUTO_MERGE" \
         "$out_abs/.git/MERGE_HEAD" "$out_abs/.git/MERGE_MSG" "$out_abs/.git/COMMIT_EDITMSG"
A reflog expire --expire=now --all
rm -rf -- "$out_abs/.git/logs"
A gc --quiet --prune=now >>"$LOG" 2>&1
A fsck --no-progress >>"$LOG" 2>&1 || die "git fsck failed on the archive"
refs="$(A for-each-ref --format='%(refname)')"
[[ "$refs" == refs/heads/main ]] || die "the archive should hold only refs/heads/main, it holds: $refs"
[[ "$(A symbolic-ref HEAD)" == refs/heads/main ]] || die "HEAD is not main"
[[ -z "$(A remote)" ]] || die "the archive has a remote"
[[ ! -e "$out_abs/.git/filter-repo" ]] || die "the archive has .git/filter-repo"
[[ ! -e "$out_abs/.git/refs/replace" ]] || [[ -z "$(ls -A "$out_abs/.git/refs/replace")" ]] \
  || die "the archive has replace refs"
log "replace-text scan of the whole archive"
helper scan "$out_abs" "$RT" "$WORK/stats/archive.scan.json" >>"$LOG" 2>&1 \
  || die "the archive still holds a replace-text literal (rule numbers in $LOG)"
meta refs "$refs"
meta git_size "$(du -sb "$out_abs/.git" | cut -f1)"
meta finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$(dirname -- "$report_abs")"
helper report "$WORK" "$out_abs" "$report_abs" "$WORK/meta.tsv"

log "done: $(A rev-list --count HEAD) commits, head $(A rev-parse HEAD)"
log "archive: $out_abs"
log "report:  $report_abs"
if (( stub_missing )) && grep -q '^stub' "$WORK/meta.tsv"; then
  log "WARNING: this build holds stub files (--stub-missing). It is for testing only."
fi
