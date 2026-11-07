# Stage P.1 review F2: research-archive build

Reviewer: ArchiveAuditor-FableXHigh (Fable 5.1, worker-xhigh). Written 2026-11-07 04:55 MST.
Scope: the build at /tmp/claude-1000/p1/ArchiveBuild/real1 (HEAD 682adb42, 496 commits, 3455 blobs,
85,762,544 bytes), its full history, publish/research-archive/EXCLUDE.txt, and the D3 and D6 calls.
Read only. Nothing was fixed. This file is committed to public AiTrader, so it names no secret, key,
account ID, email address, wallet address or removed literal. It gives file and line instead.

Rulings read: reports/p1_rulings.md (R1 to R30, OC1 to OC12). Prior reports read:
reports/p1_scratch/archive_d9_d6_report.md and scans/archive_*. Every number below was recomputed from
the raw archive, not copied from those reports. Scripts and intermediate files are under
/tmp/claude-1000/p1/ArchiveAuditor/ (blob dump, blob_paths.json, scan_patterns.py, b58_analysis.py).
They print masked values only.

## Verdict

BLOCKING: 0. SHOULD FIX: 4. NOTE: 14.

No key, token, keypair, seed phrase, private literal or personal contact detail is in the archive's
blobs, commit messages or identities. Every INCLUDE call matches D3 and D6. The four SHOULD FIX items
are a wrong number on one card, two files that D4 or D6 describe but the path rules missed, and two
AiTrader report files that carry the rule literals R12 says reports must not print.

## Method

1. Dumped all 3455 blobs with a blob-to-path map (`git rev-list --all --objects`, `git cat-file --batch`).
2. gitleaks 8.30.1 in `--no-git` mode over the blob dump, so coverage does not depend on commit structure.
3. My own pattern scan over every blob and every commit message: base58 of 86 to 88 characters, 128 hex,
   base64 of 88 characters, 64-integer arrays, PEM headers, key-bearing URL parameters, UUIDs, Telegram,
   Discord, Slack, AWS, GCP, Google, GitHub, OpenAI and Anthropic prefixes, Bearer headers, Alpaca and
   IBKR id shapes, EVM addresses, emails, NANP phone numbers, private IP ranges, personal-data words, name
   variants, and a seed-phrase heuristic (12 or 24 words, no stop words, no repeats).
4. The three private rule literals (email, handle, paper account ID) read in a script from
   ~/.config/p1-private/research-archive.replace-text and counted in blobs, messages, identities,
   publish/ and reports/, in exact, upper, lower, URL-encoded, base64, local-part and digits-only forms.
5. Every history path checked against every EXCLUDE.txt rule after stripping the group and name prefix.
6. Every valid 32-byte base58 string classified by file type, nearby label and known-program table.
7. All nine soltool screenshots viewed. All 18 cards and the README compared with publish/ copies.

## Named items from the brief

### R23. The 19 commits gitleaks did not scan

gitleaks reported 477 of 496 commits. The archive has 18 merge commits and 478 non-merge commits, so one
non-merge commit is unscanned. It is `51a625cd` "start research archive" (2026-07-30), the archive's root
commit. Its tree is `4b825dc6`, the empty tree, and `git diff-tree --root -r 51a625cd` prints nothing.
It is the only non-merge commit with an empty diff. The 18 merges each produce no diff under `git log -p`.

The 19 commits add no content the scanned commits lack:
- For each merge M with parents P1 and P2, every (blob, path) pair in M's tree is in P1's tree or P2's
  tree. Extra pairs: 0 for all 18. Command:
  `comm -23 <(git ls-tree -r M | awk '{print $3" "$4}' | sort) <(cat <(git ls-tree -r P1 ...) <(git ls-tree -r P2 ...) | sort -u)`.
  Each merge's diff against P1 equals P2's full tree (file counts match row by row), as a plain
  unrelated-history merge should.
- The root commit has no blob.
- Independent cover: gitleaks `--no-git` over all 3455 blobs (every blob in the object store, 85.76 MB)
  gave 15 findings, all `generic-api-key`: the same 13 the git-mode scan found, plus 2 that are earlier
  blob versions of the same lines (tests/core/test_http.py:28 and sources/rugcheck_models.py:27 against
  :35). All are fixture constants, a token address, an error string and a path constant. None is a key.
  Report: /tmp/claude-1000/p1/ArchiveAuditor/gitleaks_nogit.json (redacted).
Status: answered. No fix needed.

### R22. Is any base58 address in the archive Kiros's own wallet

Recount: 1651 base58 strings of 32 to 44 characters decode to exactly 32 bytes (the author's 1665 counts
some strings that are not 32 bytes). They are 680 distinct addresses in 83 paths. Of these:
- 478 end in `pump` (pump.fun vanity mints). They sit in solana/solback/artifacts/relaunch-sample.jsonl
  and relaunch-sample-mints.json. Mints, not wallets.
- 13 are well-known programs or mints (system program, SPL Token, Token-2022, WSOL, USDC, USDT, BONK,
  PYUSD, pump.fun, pumpswap, Raydium v4 and CPMM, Orca whirlpool, the incinerator).
- 8 appear only in non-test code: all in solana/soltool/soltool/watch/denylist.py, a list of liquid
  staking and stablecoin mints.
- 32 distinct addresses have an owner, wallet, deployer, delegate, watched, signer, payer, authority or
  holder word on the same or a nearby line (51 lines). 19 of them also occur in soltool docs/vendors/*.md,
  which record real vendor replies about third-party test tokens (BONK, USDC, PYUSD, one fresh memecoin
  picked from a public boost feed). Those are mint authorities, freeze authorities, update authorities,
  pool accounts and top holders of those tokens. The "my own" lines in program-audit
  findings/agentC/solattn.md:311 and solattn.json:166 are pool addresses in a citation check. The
  "watched" lines in solback relaunch-sample.jsonl:293 to 294 are token names. soltool
  tests/watch/conftest.py:41 assigns the BONK mint to the name WALLET and :43 USDC, so the watch tests use
  known mints as stand-in wallets.
- After removing known, vendor-documented and vanity addresses, 5 labelled addresses remain, all in
  soltool test files only. Two are structurally synthetic (one character makes up 84 percent of
  tests/verdict_builders.py:54 and :60, and 56 percent of tests/sources/test_helius_holders.py:96, which
  is a loader program name). Three are random-looking test constants with no documented origin:
  - solana/soltool/tests/watch/conftest.py:42 (DEPLOYER)
  - solana/soltool/tests/sources/test_bundle_parse.py:178 (a buyer's user_account in a bundle fixture)
  - solana/soltool/tests/sources/test_bundle_parse.py:377 (a buyer wallet in the same fixture)

Structural evidence that no source ever held Kiros's wallet:
- The build's R1 pre-pass found 0 keypair JSON files in the full history of all 18 sources
  (`grep -c ": R1 " real1_build_report.md` = 0).
- The only secret-named paths ever removed from any source history are 15 `.env.example` templates and
  vendor fixture JSONs (build report, paths listed under the secrets rules). No wallet, keypair, id.json
  or seed file ever existed in any history.
- The source working trees hold no untracked file named like a wallet, keypair, seed or key either
  (read-only `find` by name over the eight repos, depth 4: only .env.example files and test files).
- All six solana repos declare no wallet. soltool README.md:41 and :55 and watch/__init__.py:11 say it
  never reads, stores or transmits a private key, seed phrase or wallet session, and the UI footer in every
  screenshot reads "read-only: no trading, no wallets". solcopy README.md:20 and :75 to 76 say no wallet
  was defined and there is no wallet, signer, order or venue connection. solattn, solclear, solback and
  solceil have no signing code (grep for wallet, keypair, signer, private key: only feature names and
  policy text).
- No line in the archive pairs an address with a wallet app name, "my wallet", "my address", "personal",
  "funded", "airdrop", "devnet" or "faucet" (0 hits).
Conclusion: I find no evidence that any address is Kiros's own wallet, and no mechanism by which one
would have entered the record. The three test constants above are the residue that only Kiros can confirm
by eye. Status: answered, with that residue listed for `[KIROS: confirm]`.

### R21. The address in VRPExperiment

experiments/VRPExperiment/reports/task3/venue_table.md:40 (first in `3eea1fe`) and progress.md:363 both
quote the page footer of Interactive Brokers Canada Inc. The venue_table line is labelled "Footer,
verbatim" and the text itself reads "Registered Office:" followed by the company's Montreal office. The
progress.md line calls it "a CIRO member with a registered office at". It is a vendor's published business
address, quoted for venue evidence. Nothing personal. Over the whole archive the hygiene patterns found no
phone number and no other street address. Status: confirmed, as R21 ruled.

### soltool card: 7 commits or 6

Both numbers are right for different objects. The source repo main branch has 7 commits. The archive's
solana/soltool folder has 6 import commits plus the cards commit. The dropped commit is source `b778e1b`
"Fix .env.example: heredoc quoting broke on prior commit", which changed only `.env.example` (18
deletions). EXCLUDE.txt removes `.env*`, so the commit became empty and git-filter-repo pruned it. The
merge subject already says "6 commits" and the build table (real1_build_report.md line 61) says 7 source,
6 kept, 1 dropped. The card describes the archive folder, so it should say 6, or say "7 in the source, 6
kept, one touched only .env.example". Every other card's count equals its source count and its kept
count (17 of 17 match, verified card by card against the build table).

## Findings

### SHOULD FIX

F2-S1. soltool card commit count. publish/research-archive/cards/solana/soltool/CARD.md line 2 says "7
commits". The archive holds 6. See the named item above. Evidence:
`git -C /mnt/large-storage/Archive/GitHub/soltool log --oneline main | wc -l` (7),
`git -C real1 log --oneline --no-merges -- solana/soltool | wc -l` (7, including the cards commit),
`git -C /mnt/large-storage/Archive/GitHub/soltool show --stat b778e1b`. Already pending for the fix wave.

F2-S2. Bulk vendor reference data kept by path. experiments/ORBExperiment/reports/stage_a1r/
task6_delisted.json (584,119 bytes, one blob version, one commit) holds `enumerated_names`, a list of
6421 delisted tickers with delisting dates, pulled from the vendor endpoint named in its
`enumeration_source` field (a `/v3/reference/tickers?active=false` listing). The 140 `checks` entries are
redacted and fine. D6 names "vendor data" in bulk, and R2 excluded an exchange export on the ground that
nothing shows a right to redistribute. This file is the same kind of question for the lead: exclude it by
path in EXCLUDE.txt as R2 did, or accept it as a list of facts. No ruling covers it yet. Evidence, run
from the archive root in Python: load `experiments/ORBExperiment/reports/stage_a1r/task6_delisted.json`
with `json.load`, then print `len(d['enumerated_names'])` (6421) and `d['enumeration_source']` (the
vendor endpoint).

F2-S3. A model dump kept because of its extension. solana/solclear/solclear/artifacts/
hard_rug_clearance.txt (80,150 bytes, 3944 lines, one version) is a LightGBM model file in text form
(first lines `tree`, `version=v4`, `num_class=1`). D4 excludes "any model weights", and the EXCLUDE.txt
extension list has no `.txt` model case. It is the repo's own trained model, not vendor data, so the lead
may accept it. If not, one literal path line in EXCLUDE.txt removes it. Evidence: `head -3` of the file.

F2-S4. Rule literals in two AiTrader report files that G1 commits. The private email (rule 1) occurs 2
times and the handle (rule 2) 6 times in reports/P.1_STATE.md, and the handle 2 times in
reports/p1_rulings.md (inside the OC11 and OC12 text). Both files are untracked now and are named in
GUARDRAILS as G1 commit paths. R12 says "No report, review or reply prints a removed literal". The
exposure is not new: the same email is the author or committer email on 408 commits in AiTrader's own
history and R16 accepts the handle's machine-path form, so the lead may rule it accepted under R12's own
reasoning for llm-news-drift.replace-text. Fixing it is two edits. Evidence: counts only, from the
rule-literal script in the Method section (publish/ and reports/ pass). The archive itself is clean: 0
hits for all three literals and all variants in blobs, messages and identities, and the digits of the
account ID alone are 0 hits too.

### NOTE

F2-N1. Mailmap files carry the private email. publish/research-archive/mailmap.txt and
publish/checks/llm-news-drift.mailmap hold it 2 times each (3 lines, 2 distinct emails: the private one
and the GitHub noreply). A mailmap needs the literal to work. OC10 keeps mailmap.txt public with AiTrader
and R12 accepted llm-news-drift.replace-text on the ground that its literals already occur throughout
AiTrader's history, which holds here too (408 author or committer fields). If the lead wants the archive
mailmap out of AiTrader for consistency with the replace-text file, it can live beside it in
~/.config/p1-private and build_archive.sh can default to that path. The archive's identities are clean: one
identity on all 992 author and committer fields, the GitHub noreply address.

F2-N2. Leftover work folder with rule literals. /tmp/claude-1000/p1/ArchiveBuild/tmp/build_archive.Mey87e
(mode 700, 653 files) still exists at 04:55 and holds the email 18 times, the handle 18 times and the
account ID once (pre-filter stats). It is on tmpfs, in no repo. The author left it for the lead to delete.
Delete it before the session ends.

F2-N3. Full legal name in two LICENSE files. experiments/MBTExperiment/LICENSE:3 and
solana/solcopy/LICENSE:3 read "Copyright (c) 2026" followed by the first name and surname. E1 gives the
profile only the first name. The surname is already implied by the machine path R16 accepts and by the
private repo name in F2-N4. Not a secret. For `[KIROS: confirm]`.

F2-N4. A never-included private repo's name appears in 13 files: the portfolio repo named in D1's
never-included list is cited as "excluded" or "out of scope" in program-audit (README.md:16,
RESUME.md:49, findings/METHOD.md:12, findings/ANCHOR.md:105, findings/protocol/COMMON_RULES.md:13) and in
ORBExperiment docs/DUPLICATION.md:21 and VRPExperiment docs/DUPLICATION.md:25. It names the repo, nothing
in it. Its name is built from the full name in F2-N3. Evidence: `grep -rl <name> real1 | wc -l`.

F2-N5. Local session identifiers and paths. 25 distinct UUIDs: 112 are run ids in
experiments/MLCryptoEngine/research/experiments.jsonl, the rest are Claude Code session folder names
inside /tmp/claude-1000/... paths in program-audit findings/protocol/*.workflow.js, COMMON_RULES.md,
provenance/launch-args/SESSIONS.txt and findings files, plus fixture ids of all ones or zeros in soltool
tests. They identify local transcript folders, not credentials. /home/kiros-li appears 2047 times in
blobs (R16). Session folder names already appear in public AiTrader reports of the same kind.

F2-N6. On-chain and venue samples kept under artifacts/ and reports/. solana/solback/artifacts/
relaunch-sample.jsonl (300 rows: mint, name, symbol, timestamps, arm) and relaunch-sample-mints.json (591
mints) are produced by solback/scripts/sample_relaunch.py from public chain data. experiments/
NPLExperiment/reports/h5/census.rows.json holds 273 rows of venue market metrics at one instant. Each has
one blob version. They are not price series and are small. The lead may rule them as it rules F2-S2.

F2-N7. Docs tell the reader to copy .env.example, which the archive excludes. 52 markdown files mention
it. Five READMEs give the copy command: solana/soltool/README.md:82, solana/solclear/README.md:208,
experiments/MLCryptoEngine/README.md:46, and PMExperiment and ETFExperiment READMEs say theirs is empty
on purpose. D4 excludes `.env*` including templates, so the build is as specified. The archive README's
"data files are excluded" line could add that env templates are excluded too, so a reader is not sent to
a missing file. F3's area, listed here because the exclusion caused it.

F2-N8. Archive README length. real1's README.md is 1259 words against D8's "about one page". R30 says the
README changes after final1 and G2 rebuilds. F3 checks the text. Listed so the G2 rebuild is not missed.

F2-N9. gitleaks false positives, for the record. 15 `generic-api-key` findings in no-git mode (13 in git
mode). Files: solback/artifacts/relaunch-sample-mints.json:97 (a mint), soltool docs/vendors/goplus.md:280
and rugcheck.md:392 (token account fields in recorded replies), soltool/sources/bundle_helius.py:319 (an
error string), rugcheck_models.py:27 and :35 (a path constant), tests/core/test_http.py:28 (two blob
versions), tests/core/test_redact.py:9, tests/sources/test_jupiter.py:37, tests/sources/
test_bundle_fetch.py:68, tests/test_diagnostics.py:52, tests/discovery/test_feeds.py:142 to 143 (token
addresses), solclear/tests/test_rpc.py:26. The fixture values start with words like "fixt", "insi" or
"test". No real key. Matches the author's 3.1.

F2-N10. The three `sk-` strings are test fakes: soltool tests/test_ledger.py:54, tests/test_scan.py:256,
tests/test_scan_layers.py:210 (19 to 30 characters, named FAKE_SECRET or secret in a redaction test).

F2-N11. The one 86-to-88 character base58 string is a transaction signature in a vendor note:
solana/soltool/docs/vendors/helius.md:391, on a line that starts with the word signature. It is 88
characters because a signature is 64 bytes, the same length as a keypair. No 64-integer array and no
128-hex string exists anywhere in the blobs or messages.

F2-N12. Synthetic broker ids. 83 IBKR-shaped ids, 5 distinct, with digit shapes all-same-digit (6 and 7
digits), ascending (6 and 7 digits) and descending (7 digits), in HFExperiment demo and test files,
MBTExperiment tests marked SYNTHETIC-FIXTURE, and program-audit quotes of them. The real paper account ID
is 0 hits, and its placeholder "[paper account ID removed]" appears 160 times in blobs and once in a commit
message, so the rule also caught a message. The handle rule made 0 replacements because the handle only
ever occurred inside the email, which rule 1 replaced first.

F2-N13. Small test constants that trip scanners: a private-range IP in
solana/soltool/tests/api/test_main.py:18 (ALT_HOST), key-bearing URL parameters in 37 lines that are all
f-strings with a variable, hosts like api.example.invalid, or a bogus value labelled as such
(docs/vendors/helius.md:45). solclear/solclear/rpc.py:82 and enhanced.py:78 build the path from an
`api_key` variable.

F2-N14. Screenshots. All nine solana/soltool/docs/screenshots/*.png show the BONK mint, the system program
placeholder, provider states (working, failing, keyed or keyless, a quota count), and the local ledger
path under /home/kiros-li (R16). No key value, no wallet, no desktop. The three MLCryptoEngine Tauri icons
are icons. Third-party pages: the three kept .html files are the named exceptions (checked for saved-page
markers: none). soltool docs/vendors/*.md are the author's probe notes with OBSERVED and DOCUMENTED labels,
not copies. VRPExperiment task3 verbatim files are short quotes with URL, hash and retrieval time.

## D3 and D6 compliance

| Check | Result |
|---|---|
| Group placement | 12 sources under experiments/, 6 under solana/, as D3 lists. Top level holds only EXCLUDE.txt, README.md, experiments/, solana/. |
| INCLUDE for all 18 | Correct. D6 makes a source CARD ONLY when a key is found in its history. Keys found: 0 (gitleaks git and no-git, my patterns, the build's R1 pre-pass over every source blob, and only `.env.example` templates among secret-named paths ever removed). "Mostly third-party data": no source. solback's two sample files are 2 of 36 files. |
| README marks the solana group | Yes, README.md:33 `[KIROS: confirm]`. The table has 18 rows and 19 card links (one per row plus the header text). |
| Cards present and equal | 18 CARD.md files in the archive, byte-equal to publish/research-archive/cards/. EXCLUDE.txt in the archive equals the publish/ copy. |
| EXCLUDE.txt against history | 1977 distinct blob paths, 0 match any of the 14 rules after prefix strip. 0 blobs over 1 MB (largest 667,208 bytes, a uv.lock). The CME export path: 0. |
| Three private literals | 0 in blobs, messages, identities, in every variant tested. |
| Determinism | real1 and real2 share HEAD 682adb42 and tree e8bb883e (author's table, confirmed by `git rev-parse` on both). |
| Object store | 6926 objects in one pack, 0 loose, 0 unreachable (`git fsck --unreachable --no-reflogs` empty), 0 reflogs, 1 ref, 0 replace or original refs, 0 stashes. Nothing pre-filter survives in the repo. |
| R3 (MLCryptoEngine card figures) | The card's Result gives the corrected H6 figures only (two negative per-fill numbers) and says the positive did not survive the fill model. Both figures are in HYPOTHESES.md at HEAD (lines 196 to 197), which the archive commit `ee0087a` (source `d2a0f05`) wrote. The H1 numbers (AUC, gross capture, round trip) are at HYPOTHESES.md:50 and the 100 ms numbers in docs/notes/h1-predictability-without-capturability.md. No withdrawn mechanism is claimed. |

## Coverage numbers

Blobs 3455, bytes 85,762,544, text blobs scanned by pattern: all that decode as UTF-8 (binary blobs are the
12 PNGs and icons). Commit messages scanned: 496 (141 model co-author trailers at the Anthropic noreply
address, 1 sha256, 1 placeholder, no email, address, key or path). Identities: 1 distinct. Valid 32-byte
base58 addresses: 1651 occurrences, 680 distinct. Emails in blobs: 116 occurrences, 11 distinct, all vendor
support addresses, the NPLExperiment remote URL at the public account, a synthetic SEC user-agent string
in InsiderExperiment/tests/test_edgar.py:41, and the model trailer in program-audit/tools/resume.py:326.
Seed-phrase heuristic: 0 candidates. Phone numbers: 0. Private IPs: 1 (test constant).

## Not done or outside this review

- No network or on-chain lookup was made, so the three residual test addresses in R22 are confirmed by
  context only. No list of Kiros's wallets exists in the repos to compare against, which is itself the
  evidence.
- Card wording and README claims beyond the items above are F3's review.
- I did not read any .env file, key file or the content of the rule file beyond loading it in a script
  that printed counts.
