#!/usr/bin/env python3
"""verify_extract.py: check an llm-news-drift build made by extract.sh.

Usage:
  verify_extract.py --run1 DIR --run2 DIR --source REPO [--aitrader REPO]
                    [--replace-text FILE]

--source is the repository extract.sh read for run1 (a scratch clone from
scratch_source.sh, or AiTrader itself). --aitrader is the AiTrader repository,
used for HEAD and for the blob ids of the original relevance files. Every git
call here only reads. The report is Markdown on stdout. The exit code is 0
when every check passes and 1 otherwise.

The path rules are re-implemented here from the git-filter-repo 2.47.0
semantics (literal paths match a file or a leading directory, glob uses
fnmatch with a "/*" extension, regex uses re.search), so the checks do not
reuse the extraction's own code.

Text replacement: extract.sh applies a git-filter-repo --replace-text file to
every blob. The expected trees here apply the same rules (literal and regex
lines, binary blobs with a zero byte in the first 8 KB left alone), read from
--replace-text when given, else from publish/checks/llm-news-drift.replace-text
at the source HEAD when it is committed there, else none. The mailmap is read
from publish/checks/llm-news-drift.mailmap at the source HEAD.

--replace-text FILE also adds section 10: every object reachable from any ref,
and every object in the store, of run1 and run2 is searched for each left-hand
side of FILE (literals case-insensitively). Any hit in a blob, a tree, a commit
message, or an author or committer field fails the check. The literals are
read from FILE and are never printed.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

CUT = "74532e7a98adae1f1ac383bdb36382557aecb785"
EARLIEST = "2026-07-27"
LIST_DIR = b"publish/llm-news-drift/"
MAILMAP_PATH = "publish/checks/llm-news-drift.mailmap"
REPLACE_TEXT_PATH = "publish/checks/llm-news-drift.replace-text"
KIROS = "kirosli00tuff <249804683+kirosli00tuff@users.noreply.github.com>"
ORIGINALS = [f"reports/c1_relevance_{n}" for n in (
    "sample.csv", "grader_input.csv", "grades_opus.csv", "grades_fable.csv",
    "final.csv", "adjudication.md")]
MAX_BLOB = 5 * 1024 * 1024

failures: list[str] = []


def git(repo: str | Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True).stdout


def check(ok: bool, what: str) -> str:
    if not ok:
        failures.append(what)
    return "PASS" if ok else "FAIL"


# ------------------------------------------------------------ path rules

def parse_list(raw: bytes) -> list[tuple[str, object]]:
    rules: list[tuple[str, object]] = []
    for line in raw.split(b"\n"):
        line = line.rstrip(b"\r")
        if not line or line.startswith(b"#"):
            continue
        if b"==>" in line:
            raise SystemExit("renames inside a list are not expected")
        if line.startswith(b"regex:"):
            rules.append(("regex", re.compile(line[6:])))
        elif line.startswith(b"glob:"):
            g = line[5:]
            rules.append(("glob", g))
            if not g.endswith(b"*"):
                rules.append(("glob", g + (b"*" if g.endswith(b"/") else b"/*")))
        else:
            rules.append(("match", line[8:] if line.startswith(b"literal:") else line))
    return rules


def literal_matches(exp: bytes, p: bytes) -> bool:
    n = len(exp)
    return exp == b"" or (p.startswith(exp) and (
        exp.endswith(b"/") or len(p) == n or p[n:n + 1] == b"/"))


def matches(rules: list[tuple[str, object]], p: bytes) -> bool:
    for kind, exp in rules:
        if kind == "match" and literal_matches(exp, p):
            return True
        if kind == "glob" and fnmatch.fnmatchcase(p, exp):
            return True
        if kind == "regex" and exp.search(p):
            return True
    return False


def expected_path(allow, exclude, p: bytes) -> bytes | None:
    """Where extract.sh should put original path p, or None if dropped."""
    if not matches(allow, p) or matches(exclude, p):
        return None
    return p[len(LIST_DIR):] if p.startswith(LIST_DIR) else p


# ------------------------------------------------------------ replace-text and mailmap

def parse_replace_text(raw: bytes) -> list[tuple[str, object, bytes]]:
    """(kind, pattern, replacement) per line, as git-filter-repo 2.47.0 reads it."""
    rules: list[tuple[str, object, bytes]] = []
    for line in raw.splitlines():
        line = line.rstrip(b"\r\n")
        replacement = b"***REMOVED***"
        if b"==>" in line:
            line, replacement = line.rsplit(b"==>", 1)
        if line.startswith(b"glob:"):
            raise SystemExit("glob: lines in a replace-text file are not supported by this check")
        if line.startswith(b"regex:"):
            rules.append(("regex", re.compile(line[6:]), replacement))
            continue
        if line.startswith(b"literal:"):
            line = line[8:]
        if line:
            rules.append(("literal", line, replacement))
    return rules


def apply_replace_text(rules, data: bytes) -> bytes:
    if b"\0" in data[:8192]:
        return data
    for kind, pat, new in rules:
        if kind == "literal":
            data = data.replace(pat, new)
    for kind, pat, new in rules:
        if kind == "regex":
            data = pat.sub(new, data)
    return data


def rule_hits(rules, data: bytes) -> bool:
    low = data.lower()
    for kind, pat, _new in rules:
        if kind == "literal" and pat.lower() in low:
            return True
        if kind == "regex" and pat.search(data):
            return True
    return False


class BlobMap:
    """Blob id in a repository -> blob id after the replace-text rules."""

    def __init__(self, rules):
        self.rules = rules
        self.cache: dict[tuple[str, bytes], bytes] = {}
        self.changed: set[bytes] = set()

    def __call__(self, repo, oid: bytes) -> bytes:
        if not self.rules:
            return oid
        key = (str(repo), oid)
        if key not in self.cache:
            data = git(repo, "cat-file", "blob", oid.decode())
            new = apply_replace_text(self.rules, data)
            if new == data:
                self.cache[key] = oid
            else:
                head = b"blob %d\0" % len(new)
                self.cache[key] = hashlib.sha1(head + new).hexdigest().encode()
                self.changed.add(oid)
        return self.cache[key]

    def entry(self, repo, val: tuple[bytes, bytes]) -> tuple[bytes, bytes]:
        mode, oid = val
        return (mode, oid) if mode == b"160000" else (mode, self(repo, oid))


def parse_mailmap(raw: bytes) -> list[tuple[str | None, str | None, str | None, str]]:
    """(proper name, proper email, commit name, commit email) per mailmap line."""
    out = []
    for line in raw.decode().splitlines():
        line = line.split("#", 1)[0].strip()
        parts = re.findall(r"([^<>]*)<([^<>]*)>", line)
        if not parts:
            continue
        names = [n.strip() or None for n, _e in parts]
        emails = [e.strip() for _n, e in parts]
        if len(parts) == 1:
            out.append((names[0], None, None, emails[0]))
        else:
            out.append((names[0], emails[0] or None, names[1], emails[1]))
    return out


def apply_mailmap(entries, ident: str) -> str:
    m = re.fullmatch(r"(.*) <(.*)>", ident)
    if not m:
        return ident
    name, email = m.group(1), m.group(2)
    for pname, pemail, cname, cemail in entries:
        if cemail.lower() != email.lower():
            continue
        if cname is not None and cname.lower() != name.lower():
            continue
        return f"{pname or name} <{pemail or email}>"
    return ident


def scan_objects(repo, rules, oids: list[str]) -> Counter:
    """Count objects whose raw content hits a rule, by where the hit is."""
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                         input=("\n".join(oids) + "\n").encode(), check=True,
                         capture_output=True).stdout
    hits: Counter = Counter()
    pos = 0
    while pos < len(raw):
        nl = raw.index(b"\n", pos)
        _oid, typ, size = raw[pos:nl].split()
        size = int(size)
        body = raw[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1
        hits[f"{typ.decode()} objects searched"] += 1
        if typ == b"commit":
            header, _sep, msg = body.partition(b"\n\n")
            idents = b"\n".join(x for x in header.split(b"\n")
                                if x.startswith((b"author ", b"committer ")))
            hits["commit messages"] += rule_hits(rules, msg)
            hits["author or committer fields"] += rule_hits(rules, idents)
            hits["other commit headers"] += rule_hits(rules, header) and not rule_hits(rules, idents)
        else:
            hits[f"{typ.decode()}s"] += rule_hits(rules, body)
    return hits


# ------------------------------------------------------------ git readers

def tree(repo, rev: str) -> dict[bytes, tuple[bytes, bytes]]:
    """{path: (mode, blob id)} for every file in rev."""
    out = {}
    for rec in git(repo, "ls-tree", "-r", "-z", "--full-tree", rev).split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            mode, _type, oid = meta.split(b" ")
            out[path] = (mode, oid)
    return out


def commits(repo, rev_range: list[str]) -> list[dict]:
    fmt = "%H%x00%P%x00%an <%ae>%x00%cn <%ce>%x00%ad%x00%cd%x00%aI%x00%as%x00%cs%x00%B%x1e"
    raw = git(repo, "log", "--date=raw", f"--format={fmt}", *rev_range).decode()
    out = []
    for rec in raw.split("\x1e"):
        rec = rec.lstrip("\n")
        if not rec:
            continue
        f = rec.split("\x00")
        out.append(dict(sha=f[0], parents=f[1].split(), author=f[2], committer=f[3],
                        ad=f[4], cd=f[5], aiso=f[6], ashort=f[7], cshort=f[8],
                        msg=f[9], subject=f[9].split("\n", 1)[0]))
    return out


def all_objects(repo) -> dict[str, tuple[str, int]]:
    raw = git(repo, "cat-file", "--batch-all-objects",
              "--batch-check=%(objectname) %(objecttype) %(objectsize)").decode()
    out = {}
    for line in raw.splitlines():
        oid, typ, size = line.split()
        out[oid] = (typ, int(size))
    return out


def history_paths(repo) -> set[bytes]:
    raw = git(repo, "log", "--all", "--format=", "--name-only", "--no-renames", "-z")
    return {p.strip(b"\n") for p in raw.split(b"\0") if p.strip(b"\n")}


def blobs_of_path(repo, path: str, *revs: str) -> set[str]:
    raw = git(repo, "log", *revs, "--format=", "--raw", "--no-abbrev",
              "--no-renames", "--", path).decode()
    out = set()
    for line in raw.splitlines():
        if line.startswith(":"):
            parts = line.split()
            out.update(x for x in parts[2:4] if set(x) != {"0"})
    return out


# ------------------------------------------------------------ report

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run1", required=True)
    ap.add_argument("--run2", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--aitrader", default=str(Path.home() / "Documents/GitHub/AiTrader"))
    ap.add_argument("--replace-text", default=None,
                    help="replace-text file: use its rules and fail on any left-hand side left in the runs")
    a = ap.parse_args()
    r1, r2, src, ait = a.run1, a.run2, a.source, a.aitrader
    p = print

    if a.replace_text:
        rt_raw, rt_from = Path(a.replace_text).read_bytes(), f"--replace-text `{a.replace_text}`"
    elif subprocess.run(["git", "-C", src, "cat-file", "-e", f"HEAD:{REPLACE_TEXT_PATH}"],
                        capture_output=True).returncode == 0:
        rt_raw, rt_from = git(src, "cat-file", "blob", f"HEAD:{REPLACE_TEXT_PATH}"), \
            f"`{REPLACE_TEXT_PATH}` at the source HEAD"
    else:
        rt_raw, rt_from = b"", "none"
    rt_rules = parse_replace_text(rt_raw)
    bmap = BlobMap(rt_rules)
    mailmap = parse_mailmap(git(src, "cat-file", "blob", f"HEAD:{MAILMAP_PATH}"))
    # Private strings for section 4: the literal rules of the replace-text file
    # and the commit addresses the mailmap maps away. Read, never printed.
    private = sorted({pat.decode().lower() for kind, pat, _n in rt_rules if kind == "literal"}
                     | {cemail.lower() for *_rest, cemail in mailmap})

    def has_private(text: str) -> bool:
        low = text.lower()
        return any(t in low for t in private)

    allow_raw = git(src, "cat-file", "blob", "HEAD:publish/llm-news-drift/ALLOWLIST.txt")
    excl_raw = git(src, "cat-file", "blob", "HEAD:publish/llm-news-drift/EXCLUDE.txt")
    allow, excl = parse_list(allow_raw), parse_list(excl_raw)
    src_head = git(src, "rev-parse", "HEAD").decode().strip()
    ait_head = git(ait, "rev-parse", "HEAD").decode().strip()
    p("## Inputs\n")
    p(f"- run1: `{r1}`, run2: `{r2}`")
    p(f"- source of run1: `{src}` at `{src_head}`, parent `{git(src, 'rev-parse', 'HEAD^').decode().strip()}`")
    p(f"- AiTrader HEAD: `{ait_head}`")
    p(f"- ALLOWLIST.txt blob `{git(src, 'rev-parse', 'HEAD:publish/llm-news-drift/ALLOWLIST.txt').decode().strip()}`, "
      f"EXCLUDE.txt blob `{git(src, 'rev-parse', 'HEAD:publish/llm-news-drift/EXCLUDE.txt').decode().strip()}` (read from the source HEAD)")
    p(f"- mailmap: `{MAILMAP_PATH}` at the source HEAD, {len(mailmap)} line(s)")
    p(f"- replace-text rules for the expected trees: {len(rt_rules)}, from {rt_from}\n")

    # 1. determinism
    h1 = git(r1, "rev-list", "--all").decode().split()
    h2 = git(r2, "rev-list", "--all").decode().split()
    l1 = git(r1, "log", "--all", "--format=%H %T %P")
    l2 = git(r2, "log", "--all", "--format=%H %T %P")
    p("## 1. Determinism\n")
    p(f"- `git rev-list --all`: run1 {len(h1)} hashes, run2 {len(h2)} hashes, identical: "
      f"{check(h1 == h2, 'rev-list differs')}")
    p(f"- commit, tree and parent ids identical: {check(l1 == l2, 'log differs')}\n")

    # 2. first, last, count
    c1 = commits(r1, ["--all"])
    first, last = c1[-1], c1[0]
    p("## 2. First commit, last commit, count\n")
    p(f"- first: `{first['sha']}` {first['aiso']} \"{first['subject']}\"")
    p(f"- last: `{last['sha']}` {last['aiso']} \"{last['subject']}\"")
    p(f"- commits: {len(c1)}; root commits: {sum(1 for c in c1 if not c['parents'])}; "
      f"merges: {sum(1 for c in c1 if len(c['parents']) > 1)}\n")

    # 3. refs and cleanliness
    refs = git(r1, "for-each-ref", "--format=%(refname)").decode().split()
    remotes = git(r1, "remote").decode().split()
    status = git(r1, "status", "--porcelain").decode()
    gitdir = Path(r1) / ".git"
    leftovers = [str(x) for x in gitdir.rglob("*") if x.is_file() and (
        b"p1-scratch-source" in x.read_bytes() or b"llm-news-drift-extract" in x.read_bytes())]
    p("## 3. Refs and state\n")
    p(f"- refs: {refs} {check(refs == ['refs/heads/main'], 'refs')}")
    p(f"- remotes: {remotes or 'none'} {check(not remotes, 'remotes')}")
    p(f"- work tree clean: {check(status == '', 'status')}")
    p(f"- `.git/filter-repo` absent: {check(not (gitdir / 'filter-repo').exists(), 'filter-repo dir')}")
    p(f"- temp directory names inside `.git`: {leftovers or 'none'} {check(not leftovers, 'temp names')}\n")

    # 4. identities
    p("## 4. Identities\n")
    p("| role | identity | commits | Kiros? |\n|---|---|---|---|")
    for role in ("author", "committer"):
        for ident, n in sorted(Counter(c[role] for c in c1).items()):
            p(f"| {role} | `{ident}` | {n} | {'yes' if ident == KIROS else 'NO'} |")
    leaked_ident = [c["sha"] for c in c1 if has_private(c["author"] + c["committer"])]
    p(f"\n- private address in any author or committer: {len(leaked_ident)} "
      f"{check(not leaked_ident, 'private address in identity')}")
    p("\nCommits by a non-Kiros author or committer, and what each touched:\n")
    for c in reversed(c1):
        if c["author"] != KIROS or c["committer"] != KIROS:
            p(f"- `{c['sha'][:12]}` {c['ashort']} author `{c['author']}`, committer `{c['committer']}`: \"{c['subject']}\"")
            ns = git(r1, "show", "--format=", "--name-status", "--no-renames", c["sha"]).decode().split("\n")
            for line in ns:
                if line.strip():
                    p(f"    - {line.replace(chr(9), ' ')}")
    p(f"\n- private strings searched in this section: {len(private)} (replace-text literals and "
      f"mailmapped commit addresses, case-insensitive, not printed)")
    msg_hits = [c for c in c1 if has_private(c["msg"])]
    p(f"- commit messages containing a private string: {len(msg_hits)}")
    for c in msg_hits:
        p(f"    - `{c['sha'][:12]}` \"{c['subject']}\"")
    file_hits: dict[str, list[str]] = defaultdict(list)
    for c in c1:
        pats = [x for t in private for x in ("-e", t)]
        if not pats:
            break
        out = subprocess.run(["git", "-C", r1, "grep", "-l", "-i", "-F", *pats, c["sha"]],
                             capture_output=True).stdout.decode()
        for line in out.splitlines():
            file_hits[line.split(":", 1)[1]].append(c["sha"][:7])
    p(f"- files containing a private string (informational, part C4 rules on these): "
      f"{len(file_hits)} path(s)")
    for path, shas in sorted(file_hits.items()):
        at_head = shas[0] == last["sha"][:7]
        p(f"    - `{path}` in {len(shas)} commit(s), first {shas[-1]}, at HEAD: {'yes' if at_head else 'no'}")
    p("")

    # 5. dates
    early = [c for c in c1 if c["ashort"] < EARLIEST or c["cshort"] < EARLIEST]
    p("## 5. Dates\n")
    p(f"- earliest author date {min(c['ashort'] for c in c1)}, earliest committer date "
      f"{min(c['cshort'] for c in c1)}; commits before {EARLIEST}: {len(early)} "
      f"{check(not early, 'early commit')}\n")

    # 6. every commit equals the rule applied to its source commit
    srcc = commits(src, [f"{CUT}^..HEAD"])
    by_key = defaultdict(list)
    for s in srcc:
        by_key[(s["ad"], s["cd"], s["msg"])].append(s)
    pairs, unmatched = [], []
    for c in c1:
        hit = by_key.get((c["ad"], c["cd"], c["msg"]), [])
        (pairs.append((c, hit[0])) if len(hit) == 1 else unmatched.append(c))
    bad_trees = []
    for c, s in pairs:
        want = {}
        for path, val in tree(src, s["sha"]).items():
            new = expected_path(allow, excl, path)
            if new is not None:
                val = bmap.entry(src, val)
                if new in want and want[new] != val:
                    bad_trees.append((c["sha"], f"collision at {new!r}"))
                want[new] = val
        if tree(r1, c["sha"]) != want:
            bad_trees.append((c["sha"], "tree differs"))
    # identities: the mailmap is the only change allowed
    def mapped(ident: str) -> str:
        return apply_mailmap(mailmap, ident)
    bad_ident = [c["sha"] for c, s in pairs
                 if c["author"] != mapped(s["author"]) or c["committer"] != mapped(s["committer"])]
    kept = {s["sha"] for _, s in pairs}
    dropped = [s for s in srcc if s["sha"] not in kept]
    dropped_bad = []
    for s in dropped:
        parent = s["parents"][0] if s["parents"] else None
        names = git(src, "diff-tree", "-r", "--no-renames", "--name-only", "-z", "--root",
                    *( [parent, s["sha"]] if parent else [s["sha"]] )).split(b"\0")
        if any(n and expected_path(allow, excl, n) is not None for n in names):
            dropped_bad.append(s["sha"])
    p("## 6. Every commit against the rules\n")
    p(f"- source commits from {CUT[:7]} to the source HEAD: {len(srcc)}; extracted: {len(c1)}; "
      f"matched one to one by message and dates: {len(pairs)} "
      f"{check(not unmatched, 'unmatched extracted commits')}")
    p(f"- messages and dates byte-identical to the source: {len(pairs)} of {len(c1)}")
    p(f"- each extracted tree equals allowlist, then exclude on the original paths, then the move "
      f"of publish/llm-news-drift/, applied to its source commit (paths, modes, blob ids): "
      f"{len(pairs) - len(bad_trees)} of {len(pairs)} {check(not bad_trees, 'tree mismatch')}")
    for sha, why in bad_trees:
        p(f"    - `{sha[:12]}` {why}")
    p(f"- identities equal to the source after the mailmap: {len(pairs) - len(bad_ident)} of {len(pairs)} "
      f"{check(not bad_ident, 'identity mismatch')}")
    p(f"- source blobs changed by the replace-text rules: {len(bmap.changed)}")
    cut_new = [c["sha"] for c, s in pairs if s["sha"] == CUT]
    root_ok = (cut_new == [first["sha"]] and not first["parents"]
               and first["sha"] not in {sha for sha, _ in bad_trees})
    p(f"- the root commit is the rewritten {CUT[:7]}, with no parents and the full filtered tree "
      f"of {CUT[:7]} ({len(tree(r1, first['sha']))} files): {check(root_ok, 'root')}")
    p(f"- source commits dropped as empty after filtering: {len(dropped)}; dropped commits that "
      f"touched a kept path: {len(dropped_bad)} {check(not dropped_bad, 'dropped commit touched kept path')}")
    for s in reversed(dropped):
        p(f"    - `{s['sha'][:7]}` {s['ashort']} \"{s['subject'][:90]}\"")
    p("\nCommit map (extracted, source, date, author, subject):\n")
    p("| extracted | source | date | author | subject |\n|---|---|---|---|---|")
    for c, s in reversed(pairs):
        who = "Kiros" if c["author"] == KIROS else c["author"]
        p(f"| `{c['sha'][:12]}` | `{s['sha'][:7]}` | {c['ashort']} | {who} | {c['subject'][:80].replace('|', '/')} |")
    p("")

    # 7. no excluded path anywhere in history
    hp = history_paths(r1)
    src_moved = {path[len(LIST_DIR):] for path in history_paths(src) if path.startswith(LIST_DIR)}
    hits = sorted(x for x in hp if matches(excl, x))
    hits_moved = [x for x in hits if x in src_moved]
    hits_other = [x for x in hits if x not in src_moved]
    p("## 7. Excluded paths in `git log --all --name-only`\n")
    p(f"- paths in the extracted history: {len(hp)}")
    p(f"- paths matching EXCLUDE.txt that are not a moved publish/llm-news-drift/ file: "
      f"{len(hits_other)} {check(not hits_other, 'excluded path in history')}")
    for x in hits_other:
        p(f"    - `{x.decode()}`")
    p(f"- paths matching EXCLUDE.txt that are the moved redacted files (expected, same names): {len(hits_moved)}")
    for x in hits_moved:
        b_out = blobs_of_path(r1, x.decode(), "--all")
        b_src = {bmap(src, o.encode()).decode()
                 for o in blobs_of_path(src, (LIST_DIR + x).decode(), "--all")}
        ok = b_out <= b_src
        p(f"    - `{x.decode()}`: blobs {sorted(o[:12] for o in b_out)} all come from "
          f"publish/llm-news-drift/{x.decode()}: {check(ok, f'blob origin {x!r}')}")
    tops = Counter(x.split(b"/")[0].decode() if b"/" in x else "(root file)" for x in hp)
    p(f"- top-level entries in the history: {dict(sorted(tops.items()))}\n")

    # 8. HEAD has every allowlisted AiTrader HEAD path
    ait_tree = tree(ait, "HEAD")
    head_tree = tree(r1, "HEAD")
    want = {expected_path(allow, excl, path): bmap.entry(ait, val) for path, val in ait_tree.items()
            if expected_path(allow, excl, path) is not None}
    missing = sorted(x for x in want if x not in head_tree)
    differ = sorted(x for x in want if x in head_tree and head_tree[x] != want[x])
    extra = sorted(x for x in head_tree if x not in want)
    src_tree = tree(src, "HEAD")
    extra_bad = [x for x in extra if LIST_DIR + x not in src_tree
                 or bmap.entry(src, src_tree[LIST_DIR + x]) != head_tree[x]]
    p("## 8. HEAD against AiTrader HEAD\n")
    p(f"- AiTrader HEAD files kept by the rules: {len(want)}; present in the extracted HEAD: "
      f"{len(want) - len(missing)} {check(not missing, 'missing at HEAD')}")
    for x in missing:
        p(f"    - missing `{x.decode()}`")
    p(f"- of those, same mode and blob id: {len(want) - len(missing) - len(differ)} "
      f"{check(not differ, 'differs at HEAD')}")
    for x in differ:
        p(f"    - differs `{x.decode()}`")
    p(f"- extracted HEAD files not from AiTrader HEAD: {len(extra)}, all equal to "
      f"publish/llm-news-drift/<path> at the source HEAD: {check(not extra_bad, 'extra at HEAD')}")
    for x in extra:
        p(f"    - `{x.decode()}`")
    p("")

    # 9. redacted files and original blobs
    p("## 9. Relevance files\n")
    pub = Path(ait) / "publish/llm-news-drift/reports"
    for rel in ORIGINALS:
        name = rel.split("/", 1)[1]
        w = pub / name
        at_head = head_tree.get(rel.encode(), (None, None))[1]
        if w.is_file():
            wid = subprocess.run(["git", "hash-object", "--", str(w)], check=True,
                                 capture_output=True).stdout.decode().strip()
            p(f"- `{rel}` at HEAD `{(at_head or b'absent').decode()[:12]}`, working "
              f"publish/llm-news-drift/{rel} `{wid[:12]}`: "
              f"{check(at_head is not None and at_head.decode() == wid, f'redacted {rel}')}")
        else:
            p(f"- `{rel}`: no redacted file in the working publish/ tree; at HEAD: "
              f"{(at_head or b'absent').decode()[:12]}")
    orig_blobs = set()
    for rel in ORIGINALS:
        orig_blobs |= blobs_of_path(ait, rel, "--all")
    for run in (r1, r2):
        objs = all_objects(run)
        found = sorted(orig_blobs & set(objs))
        p(f"- original relevance blobs from all AiTrader history: {len(orig_blobs)}; present in "
          f"the object store of `{run}`: {len(found)} {check(not found, f'original blob in {run}')}")
        big = max((s for t, s in objs.values() if t == "blob"), default=0)
        p(f"- largest blob in `{run}`: {big} bytes {check(big <= MAX_BLOB, 'blob over 5 MB')}")
    p("")

    # 10. no left-hand side of the replace-text file anywhere in the runs
    if a.replace_text:
        p("## 10. Replace-text literals in the runs\n")
        p(f"- rules read from `{a.replace_text}`: {len(rt_rules)} "
          f"(literals matched case-insensitively; the literals are not printed)")
        check(bool(rt_rules), "replace-text file has no rules")
        where = ("blobs", "trees", "commit messages", "author or committer fields",
                 "other commit headers", "tags")
        for run in (r1, r2):
            reach = sorted({line.split()[0] for line in
                            git(run, "rev-list", "--objects", "--all").decode().splitlines()})
            store = sorted(all_objects(run))
            for label, oids in (("reachable from any ref", reach), ("in the object store", store)):
                h = scan_objects(run, rt_rules, oids)
                searched = ", ".join(f"{h[k]} {k.split()[0]}" for k in sorted(h) if k.endswith("searched"))
                p(f"- `{run}`, {len(oids)} objects {label} ({searched}):")
                for w in where:
                    p(f"    - {w} with a hit: {h[w]} {check(h[w] == 0, f'replace-text hit: {run} {label} {w}')}")
        repl = sorted({new for _k, _pat, new in rt_rules})
        at_head = Counter()
        for path, (mode, oid) in tree(r1, "HEAD").items():
            if mode != b"160000":
                data = git(r1, "cat-file", "blob", oid.decode())
                for new in repl:
                    if new in data:
                        at_head[(new, path)] += data.count(new)
        p("- replacement text at the run1 HEAD (informational):")
        for (new, path), n in sorted(at_head.items()):
            p(f"    - `{new.decode()}` in `{path.decode()}`: {n} time(s)")
        p("")

    p("## Result\n")
    p("ALL CHECKS PASS" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
