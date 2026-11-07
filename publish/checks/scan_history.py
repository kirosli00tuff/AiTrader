#!/usr/bin/env python3
"""Stage P.1 history scanners (A3, C4, D6) for a built git repository.

Stdlib only, Python 3.12. Every subcommand reads every object reachable from
all refs (`git rev-list --objects --all`, then `git cat-file`), writes a JSON
report to --out and prints a short count summary. Secret-like values are
masked everywhere: at most the first 6 characters, plus the length.

    .venv-eval/bin/python -I publish/checks/scan_history.py SUB --repo R --out O.json

Subcommands: headlines, hygiene, secrets, paths, bulktext (see README.md).
Exit codes: 0 scan done, 1 findings with --fail-on-findings, 2 error,
3 stopped because free memory fell under --min-free-mb.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import fnmatch
import functools
import gzip
import io
import json
import os
import re
import string
import subprocess
import sys
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field

TOOL = "scan_history.py"
VERSION = 1
CTX_LEN = 60
MB = 1_000_000
TREE_MODE = "40000"
GITLINK_MODE = "160000"
GIT_CFG = ("-c", "core.quotePath=false")
csv.field_size_limit(2**31 - 1)


class ScanError(RuntimeError):
    """The scan could not run. The report is written with status=error."""


class LowMemory(RuntimeError):
    """Available memory fell under --min-free-mb."""


# ----------------------------------------------------------------- git layer

def git_cmd(repo: str) -> list[str]:
    return ["git", "-C", repo, *GIT_CFG]


def git_out(repo: str, *args: str, check: bool = True) -> str | None:
    r = subprocess.run([*git_cmd(repo), *args], capture_output=True)
    if r.returncode != 0:
        if not check:
            return None
        msg = r.stderr.decode("utf-8", "replace").strip()[:300]
        raise ScanError(f"git {args[0]} failed: {msg}")
    return r.stdout.decode("utf-8", "replace").strip()


class ObjectReader:
    """One persistent `git cat-file --batch` process."""

    def __init__(self, repo: str):
        self.proc = subprocess.Popen([*git_cmd(repo), "cat-file", "--batch"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, oid: str) -> tuple[str, bytes]:
        self.proc.stdin.write(oid.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) != 3:
            raise ScanError(f"cat-file cannot read {oid}: {b' '.join(header).decode('utf-8', 'replace')}")
        size = int(header[2])
        data = self.proc.stdout.read(size)
        self.proc.stdout.read(1)
        if len(data) != size:
            raise ScanError(f"short read for {oid}")
        return header[1].decode(), data

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)


@dataclass(frozen=True)
class Blob:
    oid: str
    size: int
    name: str  # first path rev-list saw for this blob


@dataclass
class Inventory:
    blobs: list[Blob]
    commit_oids: list[str]
    tag_oids: list[str]
    n_trees: int
    oid_hex_len: int


def load_inventory(repo: str) -> Inventory:
    blobs, commits, tags, n_trees, hexlen = [], [], [], 0, 0
    fmt = "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)"
    with tempfile.TemporaryFile() as err1, tempfile.TemporaryFile() as err2:
        rl = subprocess.Popen([*git_cmd(repo), "rev-list", "--objects", "--all"],
                              stdout=subprocess.PIPE, stderr=err1)
        cf = subprocess.Popen([*git_cmd(repo), "cat-file", fmt], stdin=rl.stdout,
                              stdout=subprocess.PIPE, stderr=err2)
        rl.stdout.close()
        for raw in cf.stdout:
            parts = raw.rstrip(b"\n").decode("utf-8", "surrogateescape").split(" ", 3)
            if len(parts) >= 2 and parts[1] == "missing":
                raise ScanError(f"missing object {parts[0]}")
            if len(parts) < 3:
                continue
            oid, typ = parts[0], parts[1]
            hexlen = hexlen or len(oid)
            if typ == "blob":
                blobs.append(Blob(oid, int(parts[2]), parts[3] if len(parts) > 3 else ""))
            elif typ == "commit":
                commits.append(oid)
            elif typ == "tag":
                tags.append(oid)
            elif typ == "tree":
                n_trees += 1
        rc_cf, rc_rl = cf.wait(), rl.wait()
        if rc_rl or rc_cf:
            err1.seek(0)
            err2.seek(0)
            msg = (err1.read() + err2.read()).decode("utf-8", "replace").strip()[:300]
            raise ScanError(f"rev-list/cat-file failed: {msg}")
    return Inventory(blobs, commits, tags, n_trees, hexlen or 40)


IDENT_RE = re.compile(r"^(?P<name>.*?) <(?P<email>[^>]*)> (?P<ts>-?\d+)")


@dataclass(frozen=True)
class HeaderObject:
    """A commit or an annotated tag, read raw (no mailmap)."""
    oid: str
    tree: str
    time: int
    idents: tuple[tuple[str, str], ...]
    message: str


def parse_header_object(oid: str, data: bytes) -> HeaderObject:
    head, _, body = data.partition(b"\n\n")
    tree, idents, ts = "", [], 0
    for ln in head.split(b"\n"):
        if not ln or ln[:1] == b" ":
            continue
        key, _, val = ln.partition(b" ")
        k = key.decode("ascii", "replace")
        if k == "tree":
            tree = val.decode("ascii", "replace")
        elif k in ("author", "committer", "tagger"):
            s = val.decode("utf-8", "replace")
            idents.append((k, s))
            m = IDENT_RE.match(s)
            if m and (k != "author" or ts == 0):
                ts = int(m["ts"])
    return HeaderObject(oid, tree, ts, tuple(idents), body.decode("utf-8", "replace"))


class TreeWalker:
    """Maps blobs or paths to every commit whose tree holds them."""

    def __init__(self, reader: ObjectReader, oid_hex_len: int):
        self.reader = reader
        self.raw_len = oid_hex_len // 2
        self.entries = functools.lru_cache(maxsize=8192)(self._entries)

    def _entries(self, tree_oid: str) -> tuple[tuple[str, str, str], ...]:
        typ, data = self.reader.read(tree_oid)
        if typ != "tree":
            raise ScanError(f"{tree_oid} is a {typ}, not a tree")
        out, i, n, rl = [], 0, len(data), self.raw_len
        while i < n:
            sp = data.index(b" ", i)
            nul = data.index(b"\0", sp)
            out.append((data[i:sp].decode("ascii"),
                        data[sp + 1:nul].decode("utf-8", "surrogateescape"),
                        data[nul + 1:nul + 1 + rl].hex()))
            i = nul + 1 + rl
        return tuple(out)

    def locate(self, commits, targets=None, path_pred=None) -> dict[tuple[str, str], list[str]]:
        """{(path, oid): [commit oids]} for target blobs or paths the predicate accepts."""
        memo: dict = {}
        contains: dict = {}
        pred_memo: dict = {}

        def has_target(tree):
            hit = contains.get(tree)
            if hit is None:
                hit = any(has_target(oid) if mode == TREE_MODE else oid in targets
                          for mode, _, oid in self.entries(tree) if mode != GITLINK_MODE)
                contains[tree] = hit
            return hit

        def wanted(path, oid, mode):
            if targets is not None and mode != GITLINK_MODE and oid in targets:
                return True
            if path_pred is None:
                return False
            v = pred_memo.get(path)
            if v is None:
                v = pred_memo[path] = bool(path_pred(path))
            return v

        def walk(tree, prefix):
            key = (tree, prefix)
            got = memo.get(key)
            if got is None:
                if path_pred is None and not has_target(tree):
                    got = ()
                else:
                    acc = []
                    for mode, name, oid in self.entries(tree):
                        path = prefix + name
                        if mode == TREE_MODE:
                            acc.extend(walk(oid, path + "/"))
                        elif wanted(path, oid, mode):
                            acc.append((path, oid))
                    got = tuple(acc)
                memo[key] = got
            return got

        out: dict[tuple[str, str], list[str]] = {}
        for c in commits:
            if c.tree:
                for path, oid in walk(c.tree, ""):
                    out.setdefault((path, oid), []).append(c.oid)
        return out


# -------------------------------------------------------- text and masking

def mask(value: str) -> str:
    keep = min(6, max(1, len(value) // 4))
    return f"{value[:keep]}***[len={len(value)}]"


def printable(s: str) -> str:
    return "".join(ch if ch.isprintable() else " " for ch in s)


def decode_blob(data: bytes) -> tuple[str, bool]:
    """(text, is_binary). Binary data is decoded as latin-1 so every byte survives."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16"), False
        except UnicodeDecodeError:
            pass
    if b"\0" in data[:8000]:
        return data.decode("latin-1"), True
    return data.decode("utf-8", "replace"), False


def line_at(text: str, start: int, end: int, radius: int = 300) -> str:
    lo = max(text.rfind("\n", max(0, start - radius), start) + 1, start - radius, 0)
    hi = text.find("\n", end, end + radius)
    hi = min(len(text), end + radius) if hi < 0 else hi
    return text[lo:hi]


def merge_spans(spans):
    out = []
    for s, e in sorted(spans):
        if out and s < out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


class SpanIndex:
    """Spans sorted by start, for window lookups in O(log n)."""

    def __init__(self, spans):
        self.spans = sorted(spans)
        self.starts = [s for s, _ in self.spans]
        self.max_len = max((e - s for s, e in self.spans), default=0)

    def window(self, lo: int, hi: int):
        i0 = bisect.bisect_left(self.starts, lo - self.max_len)
        i1 = bisect.bisect_left(self.starts, hi)
        return [(s, e) for s, e in self.spans[i0:i1] if e > lo]

    def overlaps(self, s: int, e: int) -> bool:
        return bool(self.window(s, e))


def masked_context(text: str, start: int, end: int, index: SpanIndex) -> str:
    """CTX_LEN chars around text[start:end] on its line, with every span masked."""
    lo, hi = max(0, start - 200), min(len(text), end + 200)
    nl = text.rfind("\n", lo, start)
    lo = nl + 1 if nl >= 0 else lo
    nl = text.find("\n", end, hi)
    hi = nl if nl >= 0 else hi
    pieces, pos, focus = [], lo, 0
    for s, e in merge_spans((max(s, lo), min(e, hi)) for s, e in index.window(lo, hi)):
        pieces.append(printable(text[pos:s]))
        if s <= start < e:
            focus = sum(map(len, pieces))
        pieces.append(mask(text[s:e]))
        pos = e
    pieces.append(printable(text[pos:hi]))
    line = "".join(pieces)
    begin = max(0, focus - 20)
    return line[begin:begin + CTX_LEN]


@dataclass
class Hit:
    kind: str
    start: int
    end: int
    tier: str = "high"
    family: str = ""
    extra: dict = field(default_factory=dict)
    line: int = 0


def dedupe(hits: list[Hit]) -> list[Hit]:
    """Within a family, overlapping hits collapse to one; the earlier detector wins."""
    by_fam: dict[str, list[tuple[int, int, Hit]]] = {}
    for order, h in enumerate(hits):
        by_fam.setdefault(h.family or h.kind, []).append((h.start, order, h))
    kept: list[Hit] = []
    for items in by_fam.values():
        items.sort(key=lambda t: (t[0], t[1]))
        cur: list[tuple[int, Hit]] = []
        for _, order, h in items:
            if cur and h.start < cur[-1][1].end:
                if order < cur[-1][0]:
                    cur[-1] = (order, h)
                continue
            cur.append((order, h))
        kept += [h for _, h in cur]
    return kept


def render_hits(text: str, hits: list[Hit], where: dict) -> list[dict]:
    hits = dedupe(hits)
    hits.sort(key=lambda h: h.start)
    line, pos = 1, 0
    for h in hits:
        line += text.count("\n", pos, h.start)
        pos = h.start
        h.line = line
    index = SpanIndex((h.start, h.end) for h in hits)
    out = []
    for h in hits:
        rec = {"kind": h.kind, "tier": h.tier, **where, "line": h.line,
               "value_masked": mask(text[h.start:h.end]),
               "context": masked_context(text, h.start, h.end, index)}
        rec.update(h.extra)
        out.append(rec)
    return out


# ------------------------------------------------------------ path rules

@dataclass(frozen=True)
class PathRule:
    raw: str
    kind: str  # literal | glob | regex
    pattern: object


def parse_paths_file(path: str) -> tuple[list[PathRule], list[str]]:
    """git-filter-repo --paths-from-file semantics. Returns (rules, warnings)."""
    rules, warnings = [], []
    with open(path, "rb") as f:
        for n, raw in enumerate(f, 1):
            line = raw.rstrip(b"\r\n")
            if not line or line.startswith(b"#"):
                continue
            if b"==>" in line:
                warnings.append(f"line {n}: rename rule ignored")
                continue
            if line != line.rstrip():
                warnings.append(f"line {n}: trailing whitespace is part of the pattern")
            text = line.decode("utf-8", "surrogateescape")
            if line.startswith(b"regex:"):
                rules.append(PathRule(text, "regex", re.compile(line[6:])))
            elif line.startswith(b"glob:"):
                rules.append(PathRule(text, "glob", line[5:]))
            else:
                lit = line[8:] if line.startswith(b"literal:") else line
                rules.append(PathRule(text, "literal", lit))
    return rules, warnings


def literal_matches(expr: bytes, path: bytes) -> bool:
    if expr == b"":
        return True
    n = len(expr)
    return path.startswith(expr) and (expr[n - 1:n] == b"/" or len(path) == n or path[n:n + 1] == b"/")


def rule_matches(rule: PathRule, path: bytes) -> bool:
    if rule.kind == "regex":
        return rule.pattern.search(path) is not None
    if rule.kind == "glob":
        return fnmatch.fnmatch(path, rule.pattern)
    return literal_matches(rule.pattern, path)


def path_matcher(rules: list[PathRule], strip_depth: int):
    """path -> (rule, matched_on) or None. With strip_depth N the path is also
    tested with its first N components removed (archive group/name prefix)."""
    def match(path: str):
        b = path.encode("utf-8", "surrogateescape")
        cands = [("full", b)]
        if strip_depth:
            parts = b.split(b"/", strip_depth)
            if len(parts) > strip_depth:
                cands.append(("stripped", parts[-1]))
        for on, cand in cands:
            for r in rules:
                if rule_matches(r, cand):
                    return r.raw, on
        return None
    return match


# ----------------------------------------------------------- secrets rules

B58_SET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
HEX_SET = frozenset(string.hexdigits)
B64_SET = frozenset(string.ascii_letters + string.digits + "+/=")
_WORDISH = frozenset(string.ascii_letters + string.digits + "_-")
_DIGITS = frozenset(string.digits)
TOKEN_RULES = [  # (kind, pattern, chars that may not precede it, needs a digit and a letter)
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_\-]{20,}", _WORDISH, False),
    ("openai_style_key", r"sk-(?!ant-)[A-Za-z0-9_\-]{20,}", _WORDISH, True),
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{30,}", _WORDISH, False),
    ("github_pat", r"github_pat_[A-Za-z0-9_]{22,}", _WORDISH, False),
    ("slack_token", r"xox[abprs]-[A-Za-z0-9\-]{10,}", _WORDISH, False),
    ("aws_access_key", r"(?:AKIA|ASIA)[0-9A-Z]{16}", _WORDISH, False),
    ("google_api_key", r"AIza[0-9A-Za-z_\-]{35}", _WORDISH, False),
    ("huggingface_token", r"hf_[A-Za-z0-9]{30,}", _WORDISH, False),
    ("stripe_key", r"[psr]k_(?:live|test)_[A-Za-z0-9]{10,}", _WORDISH, False),
    ("gitlab_token", r"glpat-[A-Za-z0-9_\-]{20,}", _WORDISH, False),
    ("google_oauth_token", r"ya29\.[0-9A-Za-z_\-]{20,}", _WORDISH, False),
    ("npm_token", r"npm_[A-Za-z0-9]{36}", _WORDISH, False),
    ("pypi_token", r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,}", _WORDISH, False),
    ("telegram_bot_token", r":AA[A-Za-z0-9_\-]{33}", frozenset(), False),  # digits before are checked below
    ("alpaca_key_id", r"[PA]K[A-Z0-9]{18}", _WORDISH, True),
    ("slack_webhook", r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}", frozenset(), False),
]
# each rule starts with a literal so re can scan for it fast; the char before is checked in Python
TOKEN_RES = [(k, re.compile(p + r"(?![A-Za-z0-9])"), before, digit) for k, p, before, digit in TOKEN_RULES]
RE_TELEGRAM_ID = re.compile(r"(?<!\d)\d{8,10}$")
RE_BEARER = re.compile(r"(?i)(?<![A-Za-z0-9])bearer\s+([A-Za-z0-9._~+/\-]{16,}=*)")
RE_PEM = re.compile(r"-{5}BEGIN ([A-Z0-9 ]*)PRIVATE KEY( BLOCK)?-{5}|PuTTY-User-Key-File-\d+:")
RE_INT_ARRAY64 = re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")
RE_HEX64 = re.compile(r"(?<![0-9A-Za-z])(?:0[xX])?[0-9a-fA-F]{64}(?![0-9A-Za-z])")
RE_HASH_CTX = re.compile(
    r"(?i)(?<![a-z])sha(?![a-z])|sha-?\d|hash|digest|commit|manifest|checksum|integrity|fingerprint"
    r"|etag|md5|merkle|keccak|(?<![a-z])(?:txid|tx|tree|parent|object|oid|blob|rev|revision|refs?|head)(?![a-z])")
RE_SECRET_CTX = re.compile(r"(?i)priv|secret|mnemonic|seed|signing|keypair|wallet")
RE_SHASUM_LINE = re.compile(r"^\s*[0-9a-fA-F]{64}\s+\*?[\w./\-]+\s*$")
RE_ALNUM_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{32,88}(?![A-Za-z0-9])")
RE_EVM_ADDR = re.compile(r"(?<![0-9A-Za-z])0[xX][0-9a-fA-F]{40}(?![0-9A-Za-z])")
RE_ACCOUNT = re.compile(
    r"(?i)(?<![a-z0-9])(?:account(?:[_ \-]?(?:id|no|num|number))?|acct(?:[_ \-]?(?:id|no|num))?"
    r"|wallet(?:[_ \-]?(?:address|addr|id))?|address|pubkey|public[_ \-]?key)(?![a-z0-9])"
    r"[\"']?\s*[:=#]?\s*[\"']?([A-Za-z0-9]{8,})(?![A-Za-z0-9])")
RE_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?)*\.[A-Za-z]{2,24}(?![A-Za-z0-9\-])")
RE_COAUTHOR_MODEL = re.compile(
    r"(?i)^\s*co-authored-by:[^<\n]*\b(?:claude|anthropic|openai|chatgpt|gpt|codex|copilot|gemini|cursor|devin|aider)\b")
FILE_TLDS = frozenset("png jpg jpeg gif svg webp ico bmp css js mjs ts tsx jsx py md txt json csv html htm "
                      "pdf zip gz tar xml yaml yml toml lock map so dll exe whl".split())
GENERIC_DOMAINS = ("example.com", "example.org", "example.net", "localhost")
GENERIC_SUFFIXES = (".example", ".test", ".invalid", ".localhost", ".local")
GIT_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")


def _digit_and_letter(v: str) -> bool:
    return any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


def _mixed_case_digit(v: str) -> bool:
    return any(c.isdigit() for c in v) and any(c.isupper() for c in v) and any(c.islower() for c in v)


def _b64_run_len(text: str, s: int, e: int) -> int:
    lo, hi = s, e
    while lo > 0 and text[lo - 1] in B64_SET and s - lo < 400:
        lo -= 1
    while hi < len(text) and text[hi] in B64_SET and hi - e < 400:
        hi += 1
    return hi - lo


def whole_json_64ints(text: str) -> bool:
    t = text.strip()
    if len(t) > 4096 or not (t.startswith("[") and t.endswith("]")):
        return False
    try:
        v = json.loads(t)
    except ValueError:
        return False
    return isinstance(v, list) and len(v) == 64 and all(type(x) is int and 0 <= x <= 255 for x in v)


def detect_int_arrays(text: str) -> list[Hit]:
    out = []
    for m in RE_INT_ARRAY64.finditer(text):
        nums = [int(x) for x in re.findall(r"\d+", m.group())]
        if len(nums) == 64 and all(x <= 255 for x in nums):
            out.append(Hit("solana_keypair_array", m.start(), m.end()))
    return out


def detect_tokens(text: str) -> list[Hit]:
    out = []
    for kind, rx, before, needs_digit in TOKEN_RES:
        for m in rx.finditer(text):
            s, v = m.start(), m.group()
            if s > 0 and text[s - 1] in before:
                continue
            if kind == "telegram_bot_token":
                ident = RE_TELEGRAM_ID.search(text, max(0, s - 11), s)
                if ident is None:
                    continue
                s, v = ident.start(), text[ident.start():m.end()]
            if needs_digit and not _digit_and_letter(v[2:] if kind == "alpaca_key_id" else v.split("-", 1)[-1]):
                continue
            extra = {"placeholder_like": True} if len(set(v)) < 8 else {}
            out.append(Hit(kind, s, m.end(), family="token", extra=extra))
    for m in RE_BEARER.finditer(text):
        if _digit_and_letter(m.group(1)):
            out.append(Hit("bearer_token", m.start(1), m.end(1), family="token"))
    for m in RE_PEM.finditer(text):
        out.append(Hit("private_key_block", m.start(), m.end()))
    return out


def detect_evm_keys(text: str) -> list[Hit]:
    out = []
    for m in RE_HEX64.finditer(text):
        line = line_at(text, m.start(), m.end())
        if RE_SECRET_CTX.search(line) is None and (RE_HASH_CTX.search(line) or RE_SHASUM_LINE.match(line)):
            out.append(Hit("evm_private_key", m.start(), m.end(), tier="excluded", family="hex64",
                           extra={"excluded_reason": "hash or git-id context on the line"}))
        else:
            out.append(Hit("evm_private_key", m.start(), m.end(), family="hex64"))
    return out


def detect_base58(text: str) -> list[Hit]:
    out = []
    for m in RE_ALNUM_TOKEN.finditer(text):
        v, n = m.group(), m.end() - m.start()
        if not (32 <= n <= 44 or 86 <= n <= 88):
            continue
        if not B58_SET.issuperset(v) or HEX_SET.issuperset(v) or not _mixed_case_digit(v):
            continue
        if _b64_run_len(text, m.start(), m.end()) > 200:
            continue
        if n >= 86:
            out.append(Hit("solana_keypair_base58", m.start(), m.end()))
        else:
            out.append(Hit("base58_address", m.start(), m.end(), family="account"))
    return out


def detect_accounts(text: str) -> list[Hit]:
    out = [Hit("evm_address", m.start(), m.end(), family="account") for m in RE_EVM_ADDR.finditer(text)]
    for m in RE_ACCOUNT.finditer(text):
        if any(c.isdigit() for c in m.group(1)):
            out.append(Hit("account_id", m.start(1), m.end(1), family="account"))
    return out


def classify_email(addr: str, allow: list[str]) -> dict | None:
    """None when the address is allowed or is not an email; else extra fields."""
    low = addr.lower()
    local, _, domain = low.rpartition("@")
    if domain.rsplit(".", 1)[-1] in FILE_TLDS:
        return None
    if low.endswith("@users.noreply.github.com") or low == "noreply@anthropic.com":
        return None
    for a in allow:
        a = a.lower()
        if low == a or (a.startswith("@") and low.endswith(a)):
            return None
    generic = (domain in GENERIC_DOMAINS or domain.endswith(GENERIC_SUFFIXES)
               or any(domain.endswith("." + g) for g in GENERIC_DOMAINS)
               or (local == "git" and domain in GIT_HOSTS))
    return {"email_domain": domain, "generic": generic}


def detect_emails(text: str, allow: list[str]) -> list[Hit]:
    out = []
    for m in RE_EMAIL.finditer(text):
        extra = classify_email(m.group(), allow)
        if extra is None or RE_COAUTHOR_MODEL.search(line_at(text, m.start(), m.end())):
            continue
        out.append(Hit("email", m.start(), m.end(), extra=extra))
    return out


def detect_secrets(text: str, allow_emails: list[str]) -> list[Hit]:
    strong = detect_tokens(text) + detect_int_arrays(text) + detect_evm_keys(text)
    index = SpanIndex((h.start, h.end) for h in strong)
    # an address-like hit inside a token or key already reported is the same value
    weak = [h for h in detect_base58(text) + detect_accounts(text) if not index.overlaps(h.start, h.end)]
    return strong + weak + detect_emails(text, allow_emails)


# ----------------------------------------------------------- hygiene rules

_PH_START = r"(?<![0-9A-Za-z_.\-+])"
_PH_END = r"(?![0-9A-Za-z_]|[.\-]\d)"
PHONE_RULES = [  # (kind, tier, regex); keyword tier only counts on lines naming a phone
    ("phone_na", "structured", re.compile(_PH_START + r"\([2-9]\d{2}\)[ \t]?[2-9]\d{2}[ \t.\-]\d{4}" + _PH_END)),
    ("phone_na", "structured", re.compile(_PH_START + r"[2-9]\d{2}([.\-])[2-9]\d{2}\1\d{4}" + _PH_END)),
    ("phone_na", "structured", re.compile(
        _PH_START + r"\+1[ \t.\-]?\(?[2-9]\d{2}\)?[ \t.\-]?[2-9]\d{2}[ \t.\-]?\d{4}" + _PH_END)),
    ("phone_intl", "structured", re.compile(
        r"(?<![0-9A-Za-z_.\-+)\]])\+(?!1(?![0-9]))[1-9]\d{0,2}(?:[ \t.\-]?\(?\d{1,4}+\)?){2,6}" + _PH_END)),
    ("phone_na", "keyword", re.compile(
        _PH_START + r"(?:1[ \t.\-]?)?[2-9]\d{2}[ \t]?[2-9]\d{2}[ \t]?\d{4}" + _PH_END)),
]
RE_PHONE_WORD = re.compile(r"(?i)(?<![a-z])(?:phone|tel|telephone|mobile|cell|cellphone|fax|sms|whatsapp|contact)(?![a-z])")
RE_DATEISH = re.compile(r"(?:19|20)\d{2}[.\-/ ](?:0?[1-9]|1[0-2])[.\-/ ](?:0?[1-9]|[12]\d|3[01])"
                        r"|(?:0?[1-9]|[12]\d|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/](?:19|20)\d{2}")


def _intl_ok(v: str, line: str) -> bool:
    if not 8 <= sum(c.isdigit() for c in v) <= 15 or RE_DATEISH.search(v):
        return False
    seps = set(re.findall(r"[ \t.\-]", v))
    return not (seps == {"."} and RE_PHONE_WORD.search(line) is None)


def detect_phones(text: str) -> list[Hit]:
    out = []
    for kind, tier, rx in PHONE_RULES:
        for m in rx.finditer(text):
            line = line_at(text, m.start(), m.end())
            if tier == "keyword" and RE_PHONE_WORD.search(line) is None:
                continue
            if kind == "phone_intl" and not _intl_ok(m.group(), line):
                continue
            out.append(Hit(kind, m.start(), m.end(), tier=tier, family="phone"))
    return out


_STREET_WORDS = ["Street", "Avenue", "Road", "Drive", "Boulevard", "Lane", "Way", "Court", "Place",
                 "Crescent", "Terrace", "Highway", "Parkway", "Circle", "Square", "Trail"]
_STREET_ABBR = ["St", "Ave", "Rd", "Dr", "Blvd", "Ln", "Ct", "Pl", "Cres", "Hwy", "Pkwy"]
_SUFFIX = "|".join([*_STREET_WORDS, *(w.upper() for w in _STREET_WORDS),
                    *(a + r"\.?" for a in _STREET_ABBR), *(a.upper() + r"\.?" for a in _STREET_ABBR)])
_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ"
           "|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|PR")
_PROVINCES = ("AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT|Alberta|British Columbia|Manitoba|New Brunswick"
              "|Newfoundland(?: and Labrador)?|Nova Scotia|Ontario|Quebec|Québec|Saskatchewan|Yukon|Nunavut"
              "|Prince Edward Island|Northwest Territories")
ADDRESS_RULES = [
    ("address_street", re.compile(
        r"(?<![\w.\-])\d{1,6}[A-Za-z]?[ \t]+(?:(?:[NSEW]|North|South|East|West)\.?[ \t]+)?"
        r"(?:[A-Z][A-Za-z'\-]*\.?[ \t]+){1,4}(?:" + _SUFFIX + r")(?!\w)")),
    ("address_unit", re.compile(r"(?<!\w)(?:Suite|SUITE|Ste\.|STE\.|Apt\.?|APT\.?|Apartment)[ \t]*#?[ \t]*\d{1,5}[A-Za-z]?(?!\w)")),
    ("address_zip_state", re.compile(r"(?<=[A-Za-z.])[ \t]*,[ \t]*(?P<v>(?:" + _STATES + r")[ \t]+\d{5}(?:-\d{4})?)(?![\w\-])")),
    ("address_postal_province", re.compile(
        r"(?<!\w)(?:" + _PROVINCES + r")\.?,?[ \t]+[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ \t\-]?\d[ABCEGHJ-NPRSTV-Z]\d(?!\w)")),
]
RE_ADDRESS_WORD = re.compile(r"(?<!\w)(?:Street|St\.|Avenue|Ave\.?|Road|Rd\.?|Drive|Blvd\.?|Lane|Suite|Apt\.?"
                             r"|STREET|AVENUE|ROAD|DRIVE|BLVD\.?|LANE|SUITE|APT\.?)(?!\w)")


def detect_addresses(text: str, low_tier: bool) -> list[Hit]:
    out = []
    for kind, rx in ADDRESS_RULES:
        for m in rx.finditer(text):
            s, e = (m.start("v"), m.end("v")) if "v" in rx.groupindex else (m.start(), m.end())
            out.append(Hit(kind, s, e, tier="structured", family="address"))
    if low_tier:
        out += [Hit("address_word", m.start(), m.end(), tier="word", family="address")
                for m in RE_ADDRESS_WORD.finditer(text)]
    return out


def term_regex(terms: list[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)


def detect_hygiene(text: str, terms: re.Pattern, low_tier: bool = True) -> list[Hit]:
    hits = [Hit("term", m.start(), m.end()) for m in terms.finditer(text)]
    return hits + detect_phones(text) + detect_addresses(text, low_tier)


# ---------------------------------------------------------- headline index

_NORM_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                             "–": "-", "—": "-", " ": " "})
_WS = re.compile(r"\s+")


def normalize(s: str) -> str:
    """Case-fold, collapse whitespace, fold smart quotes and dashes."""
    return _WS.sub(" ", s.translate(_NORM_TRANS).casefold())


_TOKEN = re.compile(r"\s+|\S+")


def map_norm_offsets(s: str, offsets: list[int]) -> list[int]:
    """Original index of each offset into normalize(s). Offsets must be sorted.
    Walks whitespace runs and words, so memory stays flat on large blobs."""
    out: list[int] = []
    qi, npos = 0, 0
    for m in _TOKEN.finditer(s):
        if qi >= len(offsets):
            break
        tok, st = m.group(), m.start()
        if tok[0].isspace():
            while qi < len(offsets) and offsets[qi] == npos:
                out.append(st)
                qi += 1
            npos += 1
            continue
        folded = tok.translate(_NORM_TRANS).casefold()
        end = npos + len(folded)
        if qi < len(offsets) and offsets[qi] < end:
            if len(folded) == len(tok):
                while qi < len(offsets) and offsets[qi] < end:
                    out.append(st + offsets[qi] - npos)
                    qi += 1
            else:
                p = npos
                for i, ch in enumerate(tok):
                    p += len(ch.translate(_NORM_TRANS).casefold())
                    while qi < len(offsets) and offsets[qi] < p:
                        out.append(st + i)
                        qi += 1
        npos = end
    if qi < len(offsets):
        raise ScanError("normalized offset out of range")
    return out


class HeadlineIndex:
    """All L-char windows of every headline, exact and normalized. Text is
    probed at stride k=L//2 against k-char windows, then verified."""

    def __init__(self, headlines: list[str], min_len: int):
        self.L = min_len
        self.k = max(1, min_len // 2)
        self.exact = self._build(headlines)
        self.norm = self._build([normalize(h) for h in headlines])

    def _build(self, texts):
        win: dict[str, list[int]] = {}
        kset: set[str] = set()
        for idx, t in enumerate(texts):
            for i in range(len(t) - self.L + 1):
                win.setdefault(t[i:i + self.L], []).append(idx)
            for i in range(len(t) - self.k + 1):
                kset.add(t[i:i + self.k])
        return win, kset

    def regions(self, text: str, normalized: bool) -> list[tuple[int, int, set[int]]]:
        win, kset = self.norm if normalized else self.exact
        L, k, n = self.L, self.k, len(text)
        starts = set()
        for p in range(0, n - k + 1, k):
            if text[p:p + k] in kset:
                for s in range(max(0, p + k - L), min(p, n - L) + 1):
                    if text[s:s + L] in win:
                        starts.add(s)
        regs: list[list] = []
        for s in sorted(starts):
            ids = win[text[s:s + L]]
            if regs and s <= regs[-1][1]:
                regs[-1][1] = max(regs[-1][1], s + L)
                regs[-1][2].update(ids)
            else:
                regs.append([s, s + L, set(ids)])
        return [(a, b, c) for a, b, c in regs]


def load_headlines(path: str, column: str, id_column: str, min_len: int):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        if column not in cols:
            raise ScanError(f"column {column!r} not in {path} (columns: {cols})")
        rows = list(reader)
    texts: dict[str, list[int]] = {}
    ids: dict[str, list[str]] = {}
    short = 0
    for n, row in enumerate(rows, 1):
        h = (row.get(column) or "").strip()
        if len(h) < min_len:
            short += 1
            continue
        texts.setdefault(h, []).append(n)
        if id_column in cols:
            ids.setdefault(h, []).append(row.get(id_column) or "")
    uniq = list(texts)
    return uniq, [texts[h] for h in uniq], [ids.get(h, []) for h in uniq], {"rows": len(rows), "short_skipped": short}


# ------------------------------------------------------------ bulk text

BULK_KEYS = frozenset("headline headlines title summary body text snippet article content description".split())
MARKET_KEYS = frozenset("open high low close volume vwap bid ask price last strike expiry expiration iv oi "
                        "adj_close adjclose bid_size ask_size".split())
_OUTLETS = ("Reuters|Bloomberg|CNBC|MarketWatch|Yahoo Finance|Seeking Alpha|Benzinga|Business Wire|PR Newswire"
            "|GlobeNewswire|Globe Newswire|Motley Fool|Barron's|Barrons|WSJ|Wall Street Journal|Financial Times"
            "|Forbes|Associated Press|Zacks|Investing\\.com|TheStreet|Dow Jones|Morningstar|Insider Monkey"
            "|Simply Wall St|Accesswire|Investor's Business Daily|Fox Business|CNN Business|Globe and Mail"
            "|Business Insider|Fortune|Axios|TechCrunch|The Verge|New York Times")
_NEWS_DOMAINS = ("reuters|bloomberg|cnbc|wsj|ft|marketwatch|finance\\.yahoo|seekingalpha|benzinga|businesswire"
                 "|prnewswire|globenewswire|fool|barrons|nytimes|apnews|investing|thestreet|nasdaq|forbes|cnn"
                 "|foxbusiness|zacks|morningstar|insidermonkey|simplywall|accesswire|investors|theglobeandmail"
                 "|businessinsider|fortune|axios|techcrunch|theverge")
RE_NEWS_SOURCE = re.compile(r"(?<![A-Za-z])(?:" + _OUTLETS + r")(?![A-Za-z])"
                            r"|(?i:https?://(?:www\.)?(?:" + _NEWS_DOMAINS + r")\.)")
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
RE_NEWS_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)|" + _MON + r"\s+\d{1,2},?\s+(?:19|20)\d{2}"
                          r"|\d{1,2}\s+" + _MON + r"\s+(?:19|20)\d{2}|(?<!\d)\d{1,2}/\d{1,2}/(?:19|20)\d{2}(?!\d)")
SAVED_MARKERS = [
    ("saved_from_url", re.compile(r"<!--\s*saved from url=", re.I)),
    ("singlefile", re.compile(r"page saved with singlefile", re.I)),
    ("content_location", re.compile(r"^content-location:\s*https?://", re.I | re.M)),
    ("canonical_external", re.compile(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']https?://", re.I)),
    ("og_meta", re.compile(r"<meta[^>]+property=[\"']og:", re.I)),
    ("base_href_external", re.compile(r"<base[^>]+href=[\"']https?://", re.I)),
    ("mhtml_multipart", re.compile(r"content-type:\s*multipart/related", re.I)),
]
HTML_EXT = (".html", ".htm", ".xhtml", ".mhtml", ".mht")


def key_match(key: str) -> str | None:
    k = key.strip().strip("\"'").strip()
    if k.lower() in BULK_KEYS:
        return "exact"
    tokens = re.split(r"[^a-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", k).lower())
    return "token" if any(t in BULK_KEYS for t in tokens) else None


def prose_stats(values) -> dict:
    vals = [v for v in values if isinstance(v, str)]
    if not vals:
        return {"n_values": 0}
    prose = sum(1 for v in vals if len(v) >= 25 and len(v.split()) >= 5)
    return {"n_values": len(vals), "avg_len": round(sum(map(len, vals)) / len(vals), 1),
            "prose_fraction": round(prose / len(vals), 3)}


def _guess_delim(lines: list[str], strict: bool) -> str | None:
    best, best_n = None, 0
    for d in (",", "\t", ";", "|"):
        c0 = lines[0].count(d)
        if strict:
            if c0 < 2 or len(lines) < 3 or any(ln.count(d) != c0 for ln in lines[1:3]):
                continue
            cells = [c.strip().strip("\"'") for c in lines[0].split(d)]
            if not all(re.fullmatch(r"[\w .\-]{1,40}", c) for c in cells):
                continue
        if c0 > best_n:
            best, best_n = d, c0
    return best if (best or not strict) else None


def table_findings(text: str, name: str, min_items: int) -> list[dict]:
    lower = name.lower()
    head = text[:65536].splitlines()[:6]
    if not head:
        return []
    if lower.endswith(".tsv"):
        delim = "\t"
    elif lower.endswith((".csv", ".psv")):
        delim = _guess_delim(head, strict=False) or ","
    else:
        delim = _guess_delim(head, strict=True)
        if delim is None:
            return []
    try:
        header = next(csv.reader([head[0]], delimiter=delim))
    except (csv.Error, StopIteration):
        return []
    matched = {i: h for i, h in enumerate(header) if key_match(h)}
    market = [h for h in header if h.strip().lower() in MARKET_KEYS]
    if not matched and len(market) < 3:
        return []
    rows, samples, err = 0, [], None
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
            if i == 0:
                continue
            rows += 1
            if rows <= 2000:
                samples += [row[j] for j in matched if j < len(row)]
    except csv.Error as e:
        err = str(e)[:120]
    out = []
    base = {"format": "csv", "rows": rows, "bulk": rows >= min_items}
    if err:
        base["parse_error"] = err
    if matched:
        out.append({"kind": "bulk_text_table", **base, "matched_keys": sorted(set(matched.values())),
                    **prose_stats(samples)})
    if len(market) >= 3:
        out.append({"kind": "market_data_table", **base, "matched_keys": sorted(market)})
    return out


def _walk_json(docs, node_cap: int = 2_000_000):
    items, market_items, keys, samples, nodes = 0, 0, set(), [], 0
    stack = list(docs)
    while stack and nodes < node_cap:
        v = stack.pop()
        nodes += 1
        if isinstance(v, dict):
            hit = [k for k, x in v.items() if isinstance(x, str) and key_match(str(k))]
            if hit:
                items += 1
                keys.update(hit)
                if len(samples) < 2000:
                    samples += [v[k] for k in hit]
            if sum(1 for k in v if str(k).strip().lower() in MARKET_KEYS) >= 3:
                market_items += 1
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
    return items, market_items, keys, samples, nodes >= node_cap


def json_findings(text: str, name: str, min_items: int) -> list[dict]:
    lower = name.lower()
    t = text.lstrip("﻿ \t\r\n")
    if not t:
        return []
    jsonl_ext = lower.endswith((".jsonl", ".ndjson"))
    docs, fmt, bad = None, "json", 0
    if not jsonl_ext and (lower.endswith((".json", ".geojson", ".ipynb", ".har")) or t[0] in "{["):
        try:
            docs = [json.loads(t)]
        except ValueError:
            docs = None
    if docs is None and (jsonl_ext or t[0] == "{"):
        docs, fmt = [], "jsonl"
        for ln in t.splitlines():
            if ln.strip():
                try:
                    docs.append(json.loads(ln))
                except ValueError:
                    bad += 1
        if len(docs) < 2 and not (jsonl_ext and docs):
            return []
    if not docs:
        return []
    items, market_items, keys, samples, truncated = _walk_json(docs)
    out = []
    base = {"format": fmt}
    if bad:
        base["bad_lines"] = bad
    if truncated:
        base["truncated"] = True
    if items:
        out.append({"kind": "bulk_text_json", **base, "items": items, "bulk": items >= min_items,
                    "matched_keys": sorted(map(str, keys))[:50], **prose_stats(samples)})
    if market_items:
        out.append({"kind": "market_data_json", **base, "items": market_items, "bulk": market_items >= min_items})
    return out


def html_finding(text: str, name: str) -> dict | None:
    head = text[:2048].lower()
    if not (name.lower().endswith(HTML_EXT) or "<!doctype html" in head or "<html" in head
            or ("mime-version:" in head and "multipart/related" in head)):
        return None
    markers = [k for k, rx in SAVED_MARKERS if rx.search(text)]
    return {"kind": "html_page", "saved_markers": markers, "bulk": bool(markers),
            "paragraphs": len(re.findall(r"<p[\s>]", text, re.I))}


def news_finding(text: str, min_file_lines: int, min_hit_lines: int) -> dict | None:
    if RE_NEWS_SOURCE.search(text) is None:
        return None
    lines = text.splitlines()
    n = len(lines)
    if n <= min_file_lines:
        return None
    src = [RE_NEWS_SOURCE.search(ln) is not None for ln in lines]
    hits = [i for i, ln in enumerate(lines) if RE_NEWS_DATE.search(ln)
            and (src[i] or (i > 0 and src[i - 1]) or (i + 1 < n and src[i + 1]))]
    if len(hits) < min_hit_lines:
        return None
    return {"kind": "news_like_text", "n_lines": n, "news_lines": len(hits),
            "ratio": round(len(hits) / n, 3), "example_lines": [h + 1 for h in hits[:5]], "bulk": True}


# ------------------------------------------------------------ scan session

def mem_available_mb() -> int | None:
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) // 1024
    except OSError:
        return None
    return None


def lower_priority() -> None:
    try:
        cur = os.nice(0)
        if cur < 10:
            os.nice(10 - cur)
    except OSError:
        pass


class Scan:
    def __init__(self, args):
        self.args = args
        self.repo = os.path.abspath(args.repo)
        if not os.path.isdir(self.repo):
            raise ScanError(f"repo not found: {self.repo}")
        self.check_memory()
        self.inv = load_inventory(self.repo)
        self.reader = ObjectReader(self.repo)
        self.commits = [parse_header_object(o, self.reader.read(o)[1]) for o in self.inv.commit_oids]
        self.tags = [parse_header_object(o, self.reader.read(o)[1]) for o in self.inv.tag_oids]
        self.commit_time = {c.oid: c.time for c in self.commits}
        self.walker = TreeWalker(self.reader, self.inv.oid_hex_len)
        self.incomplete: list[dict] = []
        self.stats = {"commits": len(self.commits), "tags": len(self.tags), "trees": self.inv.n_trees,
                      "blobs": len(self.inv.blobs), "text_blobs": 0, "binary_blobs": 0,
                      "container_members": 0, "bytes_scanned": 0, "skipped_large": 0}

    def check_memory(self) -> None:
        free = mem_available_mb()
        if free is not None and free < self.args.min_free_mb:
            raise LowMemory(f"MemAvailable {free} MB < {self.args.min_free_mb} MB")

    def expand(self, blob: Blob, data: bytes, cap: int):
        yield "", data
        try:
            if data[:2] == b"\x1f\x8b":
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                    yield "<gunzip>", g.read(cap)
            elif data[:4] == b"PK\x03\x04":
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist():
                        if not info.is_dir():
                            with z.open(info) as f:
                                yield info.filename, f.read(cap)
        except (OSError, EOFError, zlib.error, zipfile.BadZipFile, RuntimeError, NotImplementedError) as e:
            self.incomplete.append({"blob": blob.oid, "name": blob.name, "reason": f"container: {e}"[:160]})

    def iter_texts(self, text_only: bool = False):
        """Yield (blob, member, text, is_binary) for every blob under --max-scan-mb."""
        cap = int(self.args.max_scan_mb * MB)
        for i, b in enumerate(self.inv.blobs):
            if i % 500 == 0:
                self.check_memory()
            if b.size > cap:
                self.stats["skipped_large"] += 1
                self.incomplete.append({"blob": b.oid, "name": b.name, "size": b.size,
                                        "reason": "over --max-scan-mb, content not scanned"})
                continue
            _, data = self.reader.read(b.oid)
            for member, payload in self.expand(b, data, cap):
                if member and len(payload) >= cap:
                    self.incomplete.append({"blob": b.oid, "name": b.name, "member": member,
                                            "reason": "member truncated at --max-scan-mb"})
                text, is_bin = decode_blob(payload)
                self.stats["binary_blobs" if is_bin else "text_blobs"] += 0 if member else 1
                self.stats["container_members"] += 1 if member else 0
                self.stats["bytes_scanned"] += len(payload)
                if is_bin and text_only:
                    continue
                yield b, member, text, is_bin

    def header_texts(self):
        """Yield (source, oid, field, text) for commit and tag messages and identities."""
        for kind, objs in (("commit", self.commits), ("tag", self.tags)):
            for o in objs:
                yield kind, o.oid, "message", o.message
                for fld, ident in o.idents:
                    yield kind, o.oid, fld, ident

    def attach_locations(self, findings: list[dict]) -> None:
        targets = {f["blob"] for f in findings if "blob" in f}
        if not targets:
            return
        names = {b.oid: b.name for b in self.inv.blobs if b.oid in targets}
        per = location_records(self.walker.locate(self.commits, targets=targets), self.commit_time,
                               self.args.max_commits_per_location)
        for f in findings:
            if "blob" not in f:
                continue
            locs = per.get(f["blob"], [])
            f["locations"] = locs
            f["path"] = locs[0]["path"] if locs else names.get(f["blob"], "")
            if locs:
                first = min((loc["first_commit"] for loc in locs), key=lambda c: self.commit_time.get(c, 0))
                f["first_commit"] = first
            else:
                f["note"] = "blob is not in any commit tree (reachable through a tag or note only)"

    def close(self) -> None:
        self.reader.close()


def location_records(loc_map, commit_time, cap: int) -> dict[str, list[dict]]:
    per: dict[str, list[dict]] = {}
    for (path, oid), cs in loc_map.items():
        cs = sorted(set(cs), key=lambda c: (commit_time.get(c, 0), c))
        per.setdefault(oid, []).append({"path": path, "n_commits": len(cs), "first_commit": cs[0],
                                        "last_commit": cs[-1], "commits": cs[:cap] if cap else cs})
    for recs in per.values():
        recs.sort(key=lambda r: r["path"])
    return per


def where_blob(b: Blob, member: str, is_bin: bool) -> dict:
    w = {"source": "blob", "blob": b.oid}
    if member:
        w["member"] = member
    if is_bin:
        w["binary"] = True
    return w


# -------------------------------------------------------------- subcommands

def path_findings(scan: Scan, rules_file: str, strip_depth: int, report: dict) -> list[dict]:
    rules, warnings = parse_paths_file(rules_file)
    report["params"]["rules"] = [r.raw for r in rules]
    if warnings:
        report["warnings"] = warnings
    match = path_matcher(rules, strip_depth)
    found = scan.walker.locate(scan.commits, path_pred=lambda p: match(p) is not None)
    by_path: dict[str, dict] = {}
    for (path, oid), cs in found.items():
        rec = by_path.setdefault(path, {"blobs": set(), "commits": set()})
        rec["blobs"].add(oid)
        rec["commits"].update(cs)
    out = []
    for path in sorted(by_path):
        rule, on = match(path)
        cs = sorted(by_path[path]["commits"], key=lambda c: (scan.commit_time.get(c, 0), c))
        cap = scan.args.max_commits_per_location
        out.append({"kind": "excluded_path", "tier": "high", "source": "path", "path": path, "rule": rule,
                    "matched_on": on, "blobs": sorted(by_path[path]["blobs"]), "n_commits": len(cs),
                    "first_commit": cs[0], "last_commit": cs[-1], "commits": cs[:cap] if cap else cs})
    return out


def large_blob_findings(scan: Scan, max_mb: float) -> list[dict]:
    limit = int(max_mb * MB)
    return [{"kind": "large_blob", "tier": "high", "source": "blob", "blob": b.oid, "size": b.size,
             "limit_bytes": limit} for b in scan.inv.blobs if b.size > limit]


def run_headlines(scan: Scan, args, report: dict) -> list[dict]:
    uniq, rows, ids, hstats = load_headlines(args.headlines_csv, args.column, args.id_column, args.min_len)
    report["params"].update({"headlines_csv": os.path.abspath(args.headlines_csv), "column": args.column,
                             "min_len": args.min_len, "headlines": {**hstats, "unique_used": len(uniq)}})
    index = HeadlineIndex(uniq, args.min_len)

    def scan_text(text: str, where: dict) -> list[dict]:
        out: list[dict] = []
        seen: dict[int, list[set[int]]] = {}
        for normalized in (False, True):
            regs = index.regions(normalize(text) if normalized else text, normalized)
            if not regs:
                continue
            if normalized:
                qs = sorted({q for s, e, _ in regs for q in (s, e - 1)})
                mp = dict(zip(qs, map_norm_offsets(text, qs)))
                spans = [(mp[s], mp[e - 1] + 1, e - s, hids) for s, e, hids in regs]
            else:
                spans = [(s, e, e - s, hids) for s, e, hids in regs]
            line, pos = 1, 0
            for o_s, o_e, mlen, hids in sorted(spans, key=lambda t: t[0]):
                line += text.count("\n", pos, o_s)
                pos = o_s
                if normalized and any(hids & h for h in seen.get(line, ())):
                    continue
                seen.setdefault(line, []).append(hids)
                rec = {"kind": "headline_normalized" if normalized else "headline_exact", "tier": "high",
                       **where, "line": line, "match_len": mlen,
                       "headline_rows": sorted(r for h in hids for r in rows[h])[:50],
                       "headline_ids": sorted({i for h in hids for i in ids[h]})[:50]}
                if args.include_text:
                    rec["text"] = printable(text[o_s:o_e])[:CTX_LEN]
                out.append(rec)
        return out

    findings = []
    for b, member, text, _ in scan.iter_texts(text_only=True):
        findings += scan_text(text, where_blob(b, member, False))
    for src, oid, fld, text in scan.header_texts():
        if fld == "message":
            findings += scan_text(text, {"source": src, src: oid, "field": fld})
    return findings


def run_hygiene(scan: Scan, args, report: dict) -> list[dict]:
    terms = ["kiros1134", *args.extra_term]
    report["params"].update({"never_list": os.path.abspath(args.never_list), "max_blob_mb": args.max_blob_mb,
                             "terms": terms, "strip_depth": args.strip_depth})
    rx = term_regex(terms)
    findings = path_findings(scan, args.never_list, args.strip_depth, report)
    findings += large_blob_findings(scan, args.max_blob_mb)
    for b, member, text, is_bin in scan.iter_texts():
        hits = detect_hygiene(text, rx, low_tier=not is_bin)
        if is_bin:
            hits = [h for h in hits if h.tier != "keyword"]
        if hits:
            findings += render_hits(text, hits, where_blob(b, member, is_bin))
    for src, oid, fld, text in scan.header_texts():
        hits = detect_hygiene(text, rx) if fld == "message" else [
            Hit("term", m.start(), m.end()) for m in rx.finditer(text)]
        if hits:
            findings += render_hits(text, hits, {"source": src, src: oid, "field": fld})
    return findings


def run_secrets(scan: Scan, args, report: dict) -> list[dict]:
    report["params"]["allow_email"] = args.allow_email
    findings = []
    for b, member, text, is_bin in scan.iter_texts():
        hits = detect_secrets(text, args.allow_email)
        if not is_bin and whole_json_64ints(text):
            hits.insert(0, Hit("solana_keypair_json", 0, len(text), family="solana_keypair_array"))
        if hits:
            findings += render_hits(text, hits, where_blob(b, member, is_bin))
    for src, oid, fld, text in scan.header_texts():
        hits = detect_secrets(text, args.allow_email)
        if hits:
            findings += render_hits(text, hits, {"source": src, src: oid, "field": fld})
    return findings


def run_paths(scan: Scan, args, report: dict) -> list[dict]:
    report["params"].update({"exclude_file": os.path.abspath(args.exclude_file), "max_blob_mb": args.max_blob_mb,
                             "strip_depth": args.strip_depth})
    findings = path_findings(scan, args.exclude_file, args.strip_depth, report)
    findings += large_blob_findings(scan, args.max_blob_mb)
    for b, member, text, is_bin in scan.iter_texts():
        hits = [] if is_bin else detect_int_arrays(text)
        if not is_bin and whole_json_64ints(text):
            hits.insert(0, Hit("solana_keypair_json", 0, len(text), family="solana_keypair_array"))
        if hits:
            findings += render_hits(text, hits, where_blob(b, member, is_bin))
    return findings


def run_bulktext(scan: Scan, args, report: dict) -> list[dict]:
    report["params"].update({"bulk_min_items": args.bulk_min_items, "news_min_file_lines": args.news_min_file_lines,
                             "news_min_hit_lines": args.news_min_hit_lines})
    findings = []
    for b, member, text, is_bin in scan.iter_texts():
        name = member or b.name
        where = where_blob(b, member, False)
        if is_bin:
            if text.startswith("%PDF-"):
                findings.append({"kind": "pdf_document", "tier": "high", **where, "binary": True, "bulk": True})
            continue
        if text.startswith("%PDF-"):
            findings.append({"kind": "pdf_document", "tier": "high", **where, "bulk": True})
            continue
        recs = table_findings(text, name, args.bulk_min_items) + json_findings(text, name, args.bulk_min_items)
        for rec in (html_finding(text, name),
                    news_finding(text, args.news_min_file_lines, args.news_min_hit_lines)):
            if rec:
                recs.append(rec)
        findings += [{"tier": "high" if r.get("bulk") else "minor", **where, **r} for r in recs]
    return findings


# ------------------------------------------------------------------- report

LOW_TIERS = ("excluded", "word", "minor")


def summarize(findings: list[dict]) -> dict:
    main = [f for f in findings if f.get("tier") not in LOW_TIERS]
    low = [f for f in findings if f.get("tier") in LOW_TIERS]

    def count(items, key):
        out: dict[str, int] = {}
        for f in items:
            k = str(key(f))
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    return {"n_findings": len(main), "n_low_tier": len(low),
            "by_kind": count(main, lambda f: f["kind"]),
            "by_tier": count(main, lambda f: f.get("tier", "")),
            "by_path": count(main, lambda f: f.get("path") or f"{f.get('source')}:{f.get(f.get('source'), '')}"),
            "low_tier_by_kind": count(low, lambda f: f"{f['kind']}/{f.get('tier')}")}


def print_summary(report: dict) -> None:
    st, sm = report.get("stats", {}), report.get("summary", {})
    print(f"[{report['subcommand']}] status={report['status']} repo={report['repo']}")
    if st:
        print(f"  commits={st['commits']} tags={st['tags']} blobs={st['blobs']} text={st['text_blobs']} "
              f"binary={st['binary_blobs']} members={st['container_members']} "
              f"scanned_mb={st['bytes_scanned'] / MB:.1f} skipped_large={st['skipped_large']}")
    if sm:
        print(f"  findings={sm['n_findings']} low_tier={sm['n_low_tier']} incomplete={len(report['incomplete'])}")
        for title, key in (("by kind", "by_kind"), ("by path", "by_path"), ("low tier", "low_tier_by_kind")):
            items = list(sm[key].items())
            if items:
                shown = ", ".join(f"{k}={v}" for k, v in items[:12])
                more = f" (+{len(items) - 12} more)" if len(items) > 12 else ""
                print(f"  {title}: {shown}{more}")
    if report.get("error"):
        print(f"  error: {report['error']}")
    print(f"  report: {report['out']}")


RUNNERS = {"headlines": run_headlines, "hygiene": run_hygiene, "secrets": run_secrets,
           "paths": run_paths, "bulktext": run_bulktext}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="subcommand", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="git repository to scan (all refs)")
    common.add_argument("--out", required=True, help="JSON report path")
    common.add_argument("--max-scan-mb", type=float, default=64.0, help="blobs larger than this are not content-scanned")
    common.add_argument("--min-free-mb", type=int, default=2000, help="stop when MemAvailable falls under this")
    common.add_argument("--max-commits-per-location", type=int, default=0, help="cap commit lists (0 = all)")
    common.add_argument("--fail-on-findings", action="store_true", help="exit 1 when there are findings")
    h = sub.add_parser("headlines", parents=[common], help="40+ char headline substrings in history (A3)")
    h.add_argument("--headlines-csv", required=True)
    h.add_argument("--column", default="headline")
    h.add_argument("--id-column", default="id")
    h.add_argument("--min-len", type=int, default=40)
    h.add_argument("--include-text", action="store_true", help="put up to 60 chars of matched text in the report")
    g = sub.add_parser("hygiene", parents=[common], help="never-list paths, big blobs, PII (C4)")
    g.add_argument("--never-list", required=True)
    g.add_argument("--max-blob-mb", type=float, default=5.0)
    g.add_argument("--strip-depth", type=int, default=0)
    g.add_argument("--extra-term", action="append", default=[], help="another term to find (repeatable)")
    s = sub.add_parser("secrets", parents=[common], help="keys, tokens, emails, account ids (D6)")
    s.add_argument("--allow-email", action="append", default=[], help="allowed address or @domain (repeatable)")
    a = sub.add_parser("paths", parents=[common], help="archive exclusions, big blobs, 64-int JSON (D6)")
    a.add_argument("--exclude-file", required=True)
    a.add_argument("--max-blob-mb", type=float, default=5.0)
    a.add_argument("--strip-depth", type=int, default=0, help="also match with N leading path parts removed")
    b = sub.add_parser("bulktext", parents=[common], help="third-party text in bulk (D6)")
    b.add_argument("--bulk-min-items", type=int, default=10)
    b.add_argument("--news-min-file-lines", type=int, default=50)
    b.add_argument("--news-min-hit-lines", type=int, default=10)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    lower_priority()
    out = os.path.abspath(args.out)
    report = {"tool": TOOL, "version": VERSION, "subcommand": args.subcommand, "status": "ok",
              "repo": os.path.abspath(args.repo), "out": out,
              "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "params": {}, "incomplete": []}
    code, scan = 0, None
    try:
        scan = Scan(args)
        report["head"] = git_out(scan.repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
        refs = git_out(scan.repo, "for-each-ref", "--format=%(refname)") or ""
        report["n_refs"] = len(refs.splitlines())
        findings = RUNNERS[args.subcommand](scan, args, report)
        scan.attach_locations(findings)
        findings.sort(key=lambda f: (f.get("tier") in LOW_TIERS, f["kind"], f.get("path", ""), f.get("line", 0)))
        report["stats"] = scan.stats
        report["summary"] = summarize(findings)
        report["findings"] = [f for f in findings if f.get("tier") not in LOW_TIERS]
        report["low_tier"] = [f for f in findings if f.get("tier") in LOW_TIERS]
        report["incomplete"] = scan.incomplete
        if args.fail_on_findings and report["findings"]:
            code = 1
    except LowMemory as e:
        report.update(status="aborted_low_memory", error=str(e))
        code = 3
    except (ScanError, OSError, subprocess.SubprocessError) as e:
        report.update(status="error", error=str(e)[:500])
        code = 2
    finally:
        if scan is not None:
            if "stats" not in report:
                report["stats"] = scan.stats
            scan.close()
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
        f.write("\n")
    print_summary(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
