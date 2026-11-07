"""Self-test for scan_history.py on a synthetic git repo with planted fake values.

Every planted value is generated at run time from a seeded RNG, so this file
holds no key-shaped literal. Run:
  PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc .venv-eval/bin/python -m pytest -q \
      -p no:cacheprovider publish/checks/test_scan_history.py
"""
from __future__ import annotations

import gzip
import io
import json
import os
import random
import string
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "scan_history.py"
sys.path.insert(0, str(HERE))
import scan_history as sh  # noqa: E402

RNG = random.Random(20261107)
ALNUM = string.ascii_letters + string.digits
UPPER_DIGITS = string.ascii_uppercase + string.digits
HEX = "0123456789abcdef"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DASH5 = "-" * 5


def rnd(alphabet: str, n: int) -> str:
    """Random string that holds an upper, a lower and a digit when the alphabet allows."""
    while True:
        v = "".join(RNG.choice(alphabet) for _ in range(n))
        need = [set(string.digits), set(string.ascii_uppercase), set(string.ascii_lowercase)]
        if all(not (s & set(alphabet)) or (s & set(v)) for s in need):
            return v


# ------------------------------------------------------------------ plants

SECRET_PLANTS = {
    "anthropic_key": "sk" + "-ant-" + "api03-" + rnd(ALNUM, 48),
    "openai_style_key": "sk" + "-proj-" + rnd(ALNUM, 40),
    "github_token": "gh" + "p_" + rnd(ALNUM, 36),
    "github_token_o": "gh" + "o_" + rnd(ALNUM, 36),
    "github_token_s": "gh" + "s_" + rnd(ALNUM, 36),
    "github_pat": "github" + "_pat_" + rnd(ALNUM, 22) + "_" + rnd(ALNUM, 59),
    "slack_token": "xo" + "xb-" + rnd(string.digits, 12) + "-" + rnd(ALNUM, 24),
    "aws_access_key": "AK" + "IA" + rnd(UPPER_DIGITS, 16),
    "google_api_key": "AI" + "za" + rnd(ALNUM, 35),
    "huggingface_token": "hf" + "_" + rnd(ALNUM, 34),
    "stripe_pk": "pk" + "_live_" + rnd(ALNUM, 24),
    "stripe_sk": "sk" + "_live_" + rnd(ALNUM, 24),
    "stripe_rk": "rk" + "_live_" + rnd(ALNUM, 24),
    "bearer_token": rnd(ALNUM, 40),
    "evm_private_key": "0x" + rnd(HEX, 64),
    "solana_keypair_base58": rnd(B58, 88),
    "base58_address": rnd(B58, 44),
    "evm_address": "0x" + rnd(HEX, 40),
    "account_id": "PA" + rnd(UPPER_DIGITS, 10),
    "email": "jane.doe" + "@" + "corp-mail" + ".io",
}
PEM_BODY = rnd(ALNUM, 64)
PEM = f"{DASH5}BEGIN RSA PRIVATE KEY{DASH5}\n{PEM_BODY}\n{DASH5}END RSA PRIVATE KEY{DASH5}\n"
KEYPAIR = [RNG.randrange(256) for _ in range(64)]
COMMIT_MSG_TOKEN = "gh" + "p_" + rnd(ALNUM, 36)
GZ_TOKEN = "hf" + "_" + rnd(ALNUM, 34)
ZIP_EMAIL = "john.roe" + "@" + "privmail" + ".net"
SIDE_EMAIL = "kiros1134" + "@" + "mailbox" + ".org"

PHONES = ["(415) 555-0134", "415-555-0172", "+1 415 555 0199", "+44 20 7946 0958"]
KEYWORD_PHONE = "4155550111"
ADDRESSES = ["1234 Maple Street", "Suite 400", "IL 62704", "ON M5V 2T6"]

HEADLINES = [
    "Acme Robotics shares jump after surprise quarterly profit beats every estimate",
    "Globex Energy cuts full-year outlook as refinery outage drags on margins",
    "Initech names new chief executive in sweeping leadership reshuffle this week",
]
SHA256 = rnd(HEX, 64)
GIT_ID_NO_ZERO = rnd("123456789abcdef", 40)


def secrets_file() -> str:
    p = SECRET_PLANTS
    return "\n".join([
        f'ANTHROPIC = "{p["anthropic_key"]}"',
        f'OPENAI = "{p["openai_style_key"]}"',
        f'GH = ["{p["github_token"]}", "{p["github_token_o"]}", "{p["github_token_s"]}"]',
        f'PAT = "{p["github_pat"]}"',
        f'SLACK = "{p["slack_token"]}"',
        f'AWS = "{p["aws_access_key"]}"',
        f'GOOGLE = "{p["google_api_key"]}"',
        f'HF = "{p["huggingface_token"]}"',
        f'STRIPE = ["{p["stripe_pk"]}", "{p["stripe_sk"]}", "{p["stripe_rk"]}"]',
        f'headers = {{"Authorization": "Bearer {p["bearer_token"]}"}}',
        f'PRIVATE_KEY = "{p["evm_private_key"]}"',
        f'SOL_SECRET = "{p["solana_keypair_base58"]}"',
        f'payout_to = "{p["base58_address"]}"',
        f'eth_dest = "{p["evm_address"]}"',
        f'account_id = "{p["account_id"]}"',
        f'owner = "{p["email"]}"',
        "",
    ])


def controls_hashes() -> str:
    """Hash and git-id lines that must not be flagged by secrets or hygiene."""
    return "\n".join([
        f"sha256: {SHA256}",
        f'"sha256": "{SHA256}",',
        f"{SHA256}  data/file.csv",
        f"commit {GIT_ID_NO_ZERO}",
        f"parent {GIT_ID_NO_ZERO}",
        GIT_ID_NO_ZERO,
        f"manifest entry digest {SHA256}",
        "Co-Authored-By: Claude Opus 5.5 <noreply" + "@anthropic.com>",
        "author: someone" + "@users.noreply.github.com",
        "uuid 123e4567-e89b-12d3-a456-426614174000",
        "blob data:image/png;base64," + "".join(RNG.choice(string.ascii_letters + string.digits + "+/")
                                                 for _ in range(600)),
        "",
    ])


def controls_numbers() -> str:
    """Timestamps, versions and digit runs that must not look like phones or addresses."""
    return "\n".join([
        "ts=1730000000 ms=1730000000123",
        "at 2026-11-07T12:34:56Z and +2026-11-07 10:00 and 2026/11/07",
        "version 10.200.300.4000 and v4.155.550.123 and 1.2.3.4",
        "id 41555501239876 and 4155550123987654",
        f"hash {SHA256} and {GIT_ID_NO_ZERO}",
        "matrix 250 300 1000 then 415 555 0123 without a keyword",
        "we ran 3 tests in 2 Main loops",
        "",
    ])


def pii_file() -> str:
    return "\n".join([
        f"Call the desk at {PHONES[0]} or {PHONES[1]}.",
        f"Mobile {PHONES[2]}, London office {PHONES[3]}.",
        f"phone: {KEYWORD_PHONE}",
        f"Office: {ADDRESSES[0]}, {ADDRESSES[1]}, Springfield, {ADDRESSES[2]}",
        f"Branch: 99 Bay Road, Toronto, {ADDRESSES[3]}",
        "contact kiros1134 for access",
        "",
    ])


def headlines_csv_text() -> str:
    rows = ["id,symbol,headline,source"]
    for i in range(12):
        h = HEADLINES[i % 3] + ("" if i < 3 else f" (update {i})")
        rows.append(f'{100 + i},SYM{i},"{h}",Reuters')
    return "\n".join(rows) + "\n"


def news_feed_text() -> str:
    lines = [f"2026-11-{(i % 28) + 1:02d} Reuters: market item number {i}" for i in range(60)]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------- repo build

def git_env(home: Path) -> dict:
    return {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "LANG": "C.UTF-8"}


def run_git(repo: Path, env: dict, *args: str, date: str = "2026-01-01T00:00:00+0000",
            name: str = "Test Author", email: str = "tester@users.noreply.github.com") -> str:
    e = {**env, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date,
         "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": date}
    r = subprocess.run(["git", "-C", str(repo), *args], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(repo: Path, rel: str, content) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("scan")
    repo, home = base / "repo", base / "home"
    repo.mkdir()
    home.mkdir()
    env = git_env(home)
    run_git(repo, env, "init", "-q", "-b", "main")

    write(repo, "README.md", "# Synthetic repo\n\nNothing to see.\n")
    write(repo, "data/prices.db", b"SQLite format 3\x00" + bytes(range(256)))
    write(repo, "keys/id.json", json.dumps(KEYPAIR))
    write(repo, "config.py", secrets_file())
    write(repo, "certs/server.pem", PEM)
    write(repo, "controls/hashes.txt", controls_hashes())
    write(repo, "controls/numbers.txt", controls_numbers())
    write(repo, "controls/words.txt", "Our Test Suite runs on Google Drive near Wall Street.\n")
    write(repo, "notes/pii.txt", pii_file())
    run_git(repo, env, "add", "-A")
    run_git(repo, env, "commit", "-qm", "c1 initial", date="2026-01-01T00:00:00+0000")
    c1 = run_git(repo, env, "rev-parse", "HEAD")

    write(repo, "assets/big.txt", "0123456789abcdef\n" * 330_000)
    write(repo, "README.md", "# Synthetic repo\n\nNow with assets.\n")
    run_git(repo, env, "add", "-A")
    run_git(repo, env, "commit", "-qm", "c2 assets", date="2026-01-02T00:00:00+0000")
    c2 = run_git(repo, env, "rev-parse", "HEAD")

    run_git(repo, env, "rm", "-q", "keys/id.json")
    write(repo, "news/headlines.csv", headlines_csv_text())
    write(repo, "data/items.jsonl", "\n".join(json.dumps({"title": f"Item {i} says markets moved a lot today",
                                                          "n": i}) for i in range(12)) + "\n")
    write(repo, "feed/news.txt", news_feed_text())
    write(repo, "pages/saved.html", "<!DOCTYPE html>\n<!-- saved from url=(0040)https://www.example.com/a -->\n"
                                    "<html><head><meta property=\"og:title\" content=\"x\"></head>"
                                    "<body><p>hello</p></body></html>\n")
    write(repo, "package.json", json.dumps({"name": "x", "description": "short"}))
    write(repo, "docs/quote.md", f"As reported: {HEADLINES[0][5:60]} (source).\n")
    write(repo, "docs/quote_ws.md", "Paraphrase:\n" + HEADLINES[1].upper().replace(" ", "  ", 6) + "\n")
    write(repo, "docs/short.md", f"Short quote: {HEADLINES[2][:30]}\n")
    write(repo, "grp/src/raw/dump.txt", "raw dump\n")
    write(repo, "archive/notes.txt.gz", gzip.compress(f"token {GZ_TOKEN}\n".encode(), mtime=0))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("inner.txt", (2026, 1, 1, 0, 0, 0)), f"mail {ZIP_EMAIL}\n" * 3,
                   compress_type=zipfile.ZIP_DEFLATED)
    write(repo, "archive/bundle.zip", buf.getvalue())
    run_git(repo, env, "add", "-A")
    run_git(repo, env, "commit", "-qm", "c3 news", date="2026-01-03T00:00:00+0000")
    c3 = run_git(repo, env, "rev-parse", "HEAD")

    run_git(repo, env, "checkout", "-q", "-b", "side", c2)
    write(repo, "side.txt", "side branch\n")
    run_git(repo, env, "add", "-A")
    run_git(repo, env, "commit", "-qm", f"side: oops {COMMIT_MSG_TOKEN}\n\nquoting {HEADLINES[2][:45]}",
            date="2026-01-04T00:00:00+0000", name="Kiros", email=SIDE_EMAIL)
    side = run_git(repo, env, "rev-parse", "HEAD")
    run_git(repo, env, "checkout", "-q", "main")
    run_git(repo, env, "merge", "-q", "--no-ff", "-m", "merge side", "side", date="2026-01-05T00:00:00+0000")
    merge = run_git(repo, env, "rev-parse", "HEAD")
    run_git(repo, env, "tag", "-a", "v1", "-m", "release notes by kiros1134", date="2026-01-06T00:00:00+0000")

    hl_csv = base / "headlines.csv"
    hl_csv.write_text("id,headline\n" + "".join(f'{i},"{h}"\n' for i, h in enumerate(HEADLINES, 1)),
                      encoding="utf-8")
    never = base / "never.txt"
    never.write_text("# never list\nregex:(^|.*/)[^/]*\\.db$\nkeys/\nglob:*.pem\nliteral:secrets/creds.txt\n\n",
                     encoding="utf-8")
    excl = base / "exclude.txt"
    excl.write_text("regex:(^|.*/)[^/]*\\.(db|sqlite[^/]*|parquet|pkl)$\nglob:*.html\nraw/\n", encoding="utf-8")
    return {"repo": repo, "base": base, "env": env, "c1": c1, "c2": c2, "c3": c3, "side": side,
            "merge": merge, "hl_csv": hl_csv, "never": never, "excl": excl}


def run_scan(world, sub: str, *extra: str) -> tuple[dict, str, str]:
    out = world["base"] / f"{sub}_{len(extra)}.json"
    cmd = [sys.executable, "-I", str(SCRIPT), sub, "--repo", str(world["repo"]), "--out", str(out),
           "--min-free-mb", "0", *extra]
    r = subprocess.run(cmd, env=world["env"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    raw = out.read_text(encoding="utf-8")
    report = json.loads(raw)
    assert report["status"] == "ok"
    return report, raw, r.stdout


def paths_of(f: dict) -> set[str]:
    return {loc["path"] for loc in f.get("locations", [])} | ({f["path"]} if f.get("path") else set())


def kinds_at(findings, path: str) -> set[str]:
    return {f["kind"] for f in findings if path in paths_of(f)}


# -------------------------------------------------------------------- tests

def test_headlines_exact_normalized_and_commit_message(world):
    rep, raw, stdout = run_scan(world, "headlines", "--headlines-csv", str(world["hl_csv"]))
    f = rep["findings"]
    assert "headline_exact" in kinds_at(f, "docs/quote.md")
    assert kinds_at(f, "docs/quote_ws.md") == {"headline_normalized"}
    assert "headline_exact" in kinds_at(f, "news/headlines.csv")
    assert not kinds_at(f, "docs/short.md"), "a 30-char quote is under --min-len 40"
    quote = next(x for x in f if x.get("path") == "docs/quote.md")
    assert quote["headline_rows"] == [1] and quote["line"] == 1 and quote["match_len"] >= 40
    assert quote["first_commit"] == world["c3"]
    assert {c for loc in quote["locations"] for c in loc["commits"]} == {world["c3"], world["merge"]}
    msg = [x for x in f if x.get("source") == "commit"]
    assert [x["commit"] for x in msg] == [world["side"]] and msg[0]["headline_rows"] == [3]
    for h in HEADLINES:
        assert h[:40] not in raw and h[:40] not in stdout, "headline text must stay out by default"


def test_hygiene_finds_plants(world):
    rep, raw, stdout = run_scan(world, "hygiene", "--never-list", str(world["never"]))
    f = rep["findings"]
    excluded = {x["path"]: x for x in f if x["kind"] == "excluded_path"}
    assert set(excluded) == {"data/prices.db", "keys/id.json", "certs/server.pem"}
    assert excluded["keys/id.json"]["commits"] == [world["c1"], world["c2"], world["side"]]
    assert excluded["keys/id.json"]["rule"] == "keys/"
    big = [x for x in f if x["kind"] == "large_blob"]
    assert len(big) == 1 and big[0]["path"] == "assets/big.txt" and big[0]["size"] > 5_000_000
    pii = [x for x in f if x.get("path") == "notes/pii.txt"]
    kinds = {x["kind"] for x in pii}
    assert {"phone_na", "phone_intl", "address_street", "address_unit", "address_zip_state",
            "address_postal_province", "term"} <= kinds
    assert sum(1 for x in pii if x["kind"].startswith("phone")) == 5
    assert any(x["kind"] == "phone_na" and x["tier"] == "keyword" for x in pii)
    for x in pii:
        assert x["line"] >= 1 and len(x["context"]) <= 60 and x["first_commit"] == world["c1"]
    ident = [x for x in f if x.get("source") == "commit" and x["kind"] == "term"]
    assert {x["field"] for x in ident} == {"author", "committer"} and ident[0]["commit"] == world["side"]
    assert not [x for x in f if x.get("path", "").startswith("controls/")], "false positives in controls"
    tag = [x for x in f if x.get("source") == "tag"]
    assert [(x["kind"], x["field"]) for x in tag] == [("term", "message")]
    words = [x for x in rep["low_tier"] if x.get("path") == "controls/words.txt"]
    assert {x["kind"] for x in words} == {"address_word"}
    for v in PHONES + [KEYWORD_PHONE]:
        assert v not in raw and v not in stdout


def test_secrets_finds_plants_and_masks_them(world):
    rep, raw, stdout = run_scan(world, "secrets")
    f = rep["findings"]
    cfg = kinds_at(f, "config.py")
    expected = {"anthropic_key", "openai_style_key", "github_token", "github_pat", "slack_token",
                "aws_access_key", "google_api_key", "huggingface_token", "stripe_key", "bearer_token",
                "evm_private_key", "solana_keypair_base58", "base58_address", "evm_address", "account_id", "email"}
    assert expected <= cfg, expected - cfg
    assert sum(1 for x in f if x.get("path") == "config.py" and x["kind"] == "github_token") == 3
    assert sum(1 for x in f if x.get("path") == "config.py" and x["kind"] == "stripe_key") == 3
    assert "private_key_block" in kinds_at(f, "certs/server.pem")
    kp = [x for x in f if x.get("path") == "keys/id.json"]
    assert [x["kind"] for x in kp] == ["solana_keypair_json"], "deleted file is still in history"
    assert {c for loc in kp[0]["locations"] for c in loc["commits"]} == {world["c1"], world["c2"], world["side"]}
    msg = {(x["kind"], x["field"]) for x in f if x.get("source") == "commit"}
    assert ("github_token", "message") in msg
    assert ("email", "author") in msg and ("email", "committer") in msg
    assert not [x for x in f if x.get("path", "").startswith("controls/")], "hash, git id or noreply flagged"
    gz = [x for x in f if x.get("path") == "archive/notes.txt.gz"]
    assert [(x["kind"], x["member"]) for x in gz] == [("huggingface_token", "<gunzip>")]
    zp = [x for x in f if x.get("path") == "archive/bundle.zip"]
    assert [(x["kind"], x.get("member"), x["line"]) for x in zp] == [("email", "inner.txt", n) for n in (1, 2, 3)]
    low = [x for x in rep["low_tier"] if x.get("path") == "controls/hashes.txt"]
    assert low and {x["kind"] for x in low} == {"evm_private_key"} and all(x["tier"] == "excluded" for x in low)
    values = [*SECRET_PLANTS.values(), COMMIT_MSG_TOKEN, PEM_BODY, SIDE_EMAIL, json.dumps(KEYPAIR), GZ_TOKEN, ZIP_EMAIL]
    for v in values:
        assert v not in raw and v not in stdout, "a planted value leaked unmasked"
    for x in f:
        assert len(x["context"]) <= 60 and "***[len=" in x["value_masked"]


def test_paths_rules_big_blob_and_keypair(world):
    rep, _, _ = run_scan(world, "paths", "--exclude-file", str(world["excl"]))
    f = rep["findings"]
    assert {x["path"] for x in f if x["kind"] == "excluded_path"} == {"data/prices.db", "pages/saved.html"}
    assert [x["path"] for x in f if x["kind"] == "large_blob"] == ["assets/big.txt"]
    assert [x["path"] for x in f if x["kind"].startswith("solana")] == ["keys/id.json"]
    rep2, _, _ = run_scan(world, "paths", "--exclude-file", str(world["excl"]), "--strip-depth", "2")
    stripped = [x for x in rep2["findings"] if x["kind"] == "excluded_path" and x["matched_on"] == "stripped"]
    assert [x["path"] for x in stripped] == ["grp/src/raw/dump.txt"]


def test_bulktext_kinds(world):
    rep, _, _ = run_scan(world, "bulktext")
    f = rep["findings"]
    assert "bulk_text_table" in kinds_at(f, "news/headlines.csv")
    table = next(x for x in f if x["kind"] == "bulk_text_table")
    assert table["rows"] == 12 and table["bulk"] and table["matched_keys"] == ["headline"]
    assert "bulk_text_json" in kinds_at(f, "data/items.jsonl")
    assert "news_like_text" in kinds_at(f, "feed/news.txt")
    html = next(x for x in f if x["kind"] == "html_page")
    assert html["path"] == "pages/saved.html" and "saved_from_url" in html["saved_markers"]
    assert not kinds_at(f, "README.md")
    minor = [x for x in rep["low_tier"] if x.get("path") == "package.json"]
    assert minor and minor[0]["bulk"] is False


def test_walker_paths_equal_git_log_name_only(world):
    out = subprocess.run(["git", "-C", str(world["repo"]), "log", "--all", "-m", "--no-renames", "--name-only",
                          "--format="], env=world["env"], capture_output=True, text=True, check=True).stdout
    expected = {ln for ln in out.splitlines() if ln}
    reader = sh.ObjectReader(str(world["repo"]))
    try:
        inv = sh.load_inventory(str(world["repo"]))
        commits = [sh.parse_header_object(o, reader.read(o)[1]) for o in inv.commit_oids]
        found = sh.TreeWalker(reader, inv.oid_hex_len).locate(commits, path_pred=lambda p: True)
    finally:
        reader.close()
    assert {p for p, _ in found} == expected


@pytest.mark.parametrize("line", controls_numbers().splitlines())
def test_phone_and_address_controls_unit(line):
    hits = [h for h in sh.detect_phones(line) + sh.detect_addresses(line, low_tier=False)]
    assert not hits, (line, [line[h.start:h.end] for h in hits])


@pytest.mark.parametrize("text", ["Acme  SHARES jump ’ now", "a\tb\n\nC  d", "Straße  X",
                                  "  lead and trail  ", "İstanbul ﬁnance"])
def test_norm_offset_map_agrees(text):
    norm = sh.normalize(text)
    idx = sh.map_norm_offsets(text, list(range(len(norm))))
    assert len(idx) == len(norm) and idx == sorted(idx)
    for i, j in enumerate(idx):
        src = text[j]
        assert norm[i] in (" " if src.isspace() else sh.normalize(src)), (i, j)


def test_mask_never_shows_more_than_six_chars():
    v = "x" * 3 + rnd(ALNUM, 60)
    m = sh.mask(v)
    assert m.startswith(v[:6]) and v[:7] not in m and m.endswith("[len=63]")


def test_paths_file_semantics():
    rules = [sh.PathRule("keys/", "literal", b"keys/"), sh.PathRule("docs/a.md", "literal", b"docs/a.md"),
             sh.PathRule("glob:*.pem", "glob", b"*.pem")]
    match = sh.path_matcher(rules, 0)
    assert match("keys/x/y.json")[0] == "keys/"
    assert match("docs/a.md") and match("docs/a.md/inner") and not match("docs/a.mdx")
    assert match("deep/dir/server.pem") and not match("pem.txt")


def test_token_rules_unit():
    tele = "1" + rnd(string.digits, 9) + ":AA" + rnd(ALNUM, 33)
    alp = "P" + "K" + rnd(UPPER_DIGITS, 18)
    aws = "AK" + "IA" + rnd(UPPER_DIGITS, 16)
    text = (f"url = 'https://api.telegram.org/bot{tele}/send'\nkey={alp}\naws={aws}\n"
            # Split literals: same runtime string, and the repo secret hook does not see an sk- run.
            "risk" "-adjusted-return-calculation-function-name\nsk" "-learn-is-a-python-library-name-here\n")
    found = sorted((h.kind, text[h.start:h.end]) for h in sh.dedupe(sh.detect_tokens(text)))
    assert found == sorted([("telegram_bot_token", tele), ("alpaca_key_id", alp), ("aws_access_key", aws)])
