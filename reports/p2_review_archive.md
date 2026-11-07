# Stage P.2 D1: independent review of the research-archive build (ArchiveReviewer-FableXHigh)

Model: Claude Fable 5.1, id claude-fable-5-1, effort xhigh. Run 2026-11-07 11:00 to 11:28 MST.

Target confirmed by me: /home/kiros-li/Documents/GitHub/research-archive, HEAD
2bc0033bbd1f605388d98b35b89a8095e9c79ede, branch main, `git rev-list --count HEAD` = 421, working tree clean, one
ref (refs/heads/main), no stash, no remote, empty reflog. All checks ran on a `git clone --no-local` copy at
/home/kiros-li/.cache/p2-tmp/ArchiveReviewer/archive (same HEAD, same count). Source repos and the six solana
originals under /mnt/large-storage/Archive/GitHub/ were read with `git --no-optional-locks` only. Nothing under
~/.config/p1-private/ was opened; no literal from it, from the mailmap, or from a replaced string was printed.
Every number below is my own recount from the raw inputs; the builders' and the C3/C4 workers' numbers were used
only as a cross-check after my own run.

Verdict: 0 BLOCKING, 1 SHOULD FIX (a class the lead reserved for its own ruling), 9 NOTE. Everything else passed.

## Summary of what passed

| Check | Result | Evidence (command, cwd = the clone unless stated) |
|---|---|---|
| HEAD, branch, count | 2bc0033…, main, 421 | `git rev-parse HEAD; git branch --show-current; git rev-list --count HEAD` |
| Commit structure | 1 empty root (51a625c "start research archive") + 12 import merges + 407 source commits (12 roots) + 1 cards commit = 421 | `git rev-list --merges --count HEAD` = 12; `--max-parents=0` = 13; `--first-parent --count` = 14 |
| Identities | one identity on all 842 author+committer slots: kirosli00tuff <249804683+kirosli00tuff@users.noreply.github.com> | `git log --format='%an <%ae>%n%cn <%ce>' \| sort \| uniq -c` |
| fsck | `git fsck --strict --full` exit 0, no output | item 5 |
| Blob sizes | 2,703 unique blobs, largest 667,208 B (experiments/MLCryptoEngine/uv.lock); 0 over 1,048,576 | `git rev-list --objects --all \| git cat-file --batch-check` |
| EXCLUDE.txt paths | 1,515 distinct paths across all 421 commits; 15 rules; 0 matches after stripping experiments/<name>/ | exclude_check.py (sandbox), union of `git ls-tree -r --name-only` over every commit |
| No solana folder, path, blob or commit | top-level ever: EXCLUDE.txt, README.md, experiments/{12 names}; archive blob ids ∩ six-repo blob ids = 4, all boilerplate also in the 12 sources' own histories; archive commit ids ∩ all 18 source repos (incl. reflogs) = 0 | item 1 |
| Secrets, keys, account ids, contacts | 0 hits for key patterns; all 5 distinct account-like tokens are sequential or repeated-digit placeholders; emails are vendor addresses only; gitleaks git and dir modes 0 | item 2 |
| README and 12 cards identical to publish/research-archive at AiTrader 73aa37a | 13 of 13 identical, EXCLUDE.txt identical | `diff <(git show 73aa37a:publish/research-archive/…) …` |
| Card header facts (first/last date, N and N+1) | 12 of 12 match | item 3 |
| Card timestamps and cited ids | all match; f0e5bc7, 3a26c5e, 4ec20ee exist in the build and in none of the 18 source repos | item 3 |
| Card figures vs cited files | 158 of 158 traced (7 differ only by Unicode minus or wording, listed) | item 3 |
| README AI-use figures | 122 commits with both a Claude Co-Authored-By and a Claude-Session line: Fable 5.1 = 82 (all program-audit), Opus 5 (1M context) = 39, Fable 5 = 1; 8 of 12 have CLAUDE.md | item 3 |
| README Tests rows | 12 of 12 match my recount from the C4 junit XML files and the C4 table | item 3 |
| A2 items | all 12 done | item 4 |
| No confirm mark | 0 "[KIROS" / "confirm" marks in README.md or any CARD.md | `grep -n -i -E 'KIROS\|confirm' README.md experiments/*/CARD.md` (only the handle in URLs matches) |

## Item 1. No solana source in the archive

Passed, with one class that goes beyond a mention (S1 below).

- Folders and paths: union of paths across all 421 commits = 1,515; top level is only EXCLUDE.txt, README.md and
  experiments/ with exactly the 12 names (ETF 108, HF 98, Insider 73, MBT 93, MLC 296, NPD 75, NPL 166, ORB 156, PM 31,
  VRP 47, program-audit 348, retail-power-limits 22 paths ever). No `cards/solana`, no `solana/`.
- Blobs: 2,703 unique archive blobs vs 863 unique blobs in the six originals (`rev-list --objects --all --reflog`).
  Intersection = 4, every one also in the 12 kept sources' own histories: e4fba21 (.python-version, 5 B),
  e69de29 (empty file), e7e951c (MLCryptoEngine .pre-commit-config.yaml, 594 B, identical in solclear), fe51488
  (3-byte JSON). Zero archive blobs come only from a solana repo.
- Commits: 0 archive commit ids exist in any of the 18 repos (so no pre-rewrite id survives anywhere).
- Copied content test: every line of 40+ chars in the six repos (77,238 distinct) searched in every archive blob:
  5,553 shared line occurrences in 284 blobs, dominated by uv.lock entries (7 files, 3,939 lines), house-template
  text (REGISTRATION.md headers, tests/test_guards.py) and MLCryptoEngine's research/detection/{history,labels}.py
  and tests/test_detection_c21.py (50, 45, 13 lines shared with solclear). Direction: history.py was added to
  MLCryptoEngine in 9535c66 on 2026-08-06 19:50; solclear's first commit is 2026-08-11 07:54 and solattn's 2026-08-16.
  So MLCryptoEngine is the origin, not the copy. program-audit shares only 17 such lines in total.
- Addresses and keys: base58 tokens of 32-44 chars from the six repos (47,078 distinct) intersected with archive blobs:
  331 hits, 323 of them lowercase hex (uv.lock hash fragments) and 8 base58-plausible on-chain pool/mint ids, all in
  program-audit findings about solattn and solclear (see S1). No keypair (64-int JSON array), no private key block,
  no wallet file.
- Mentions, recounted over the 2,703 unique blobs with Python (ugrep undercounts in binary-looking blobs; my first
  pass was wrong and is superseded): solattn 7,413 occurrences in 158 paths; solclear 6,853 in 132; solcopy 20 in 8;
  solback, solceil, soltool 0. 550 unique blobs carry at least one name, spread over 9 of the 12 sources
  (program-audit 287, ORB 102, NPL 79, ETF 32, PM 18, MBT 9, VRP 9, RPL 9, Insider 5; HF, MLC, NPD 0). Paths
  containing a name: 46, all under experiments/program-audit/findings/{agentA,agentB,agentC}/… named solattn.* or
  solclear.*. Commit messages: 8 subjects and 20 message lines, all program-audit provenance commits. This agrees with
  C3's p2_grep_scan.md (7,415 / 6,864 / 20 case-insensitive; 158 / 132 / 8 files).
- Mention kinds: (a) sibling lists in duplication screens, progress logs and audit scope statements (ORB and VRP
  docs/DUPLICATION.md and progress.md; program-audit README.md, RESUME.md, findings/METHOD.md, ANCHOR.md,
  protocol/COMMON_RULES.md; NPL, ETF, PM, Insider, MBT, RPL cross-references); (b) program-audit's dedicated audit
  files on solattn and solclear; (c) program-audit provenance commit messages.

**S1. SHOULD FIX (lead ruling; the brief reserves this class).** Kind (b) goes beyond a mention. At HEAD the 46
solattn/solclear-named files under experiments/program-audit/findings/ total 2,520,593 bytes (largest:
agentB/solclear.md 116,628; agentC/verification/solattn.claims.json 103,078; agentA/solattn.md 97,332). They hold
the two private repos' full commit ids (84 archive blobs quote a full solattn id, 89 a full solclear id; 27 and 29
distinct paths, e.g. findings/ANCHOR.md, agentA/CROSS_REPO.md, agentA/NPLExperiment.reopen.md), their anchored HEAD
(solattn.inventory.md line 4 quotes b3f5062bd87c…, which is the private solattn HEAD), file inventories with line
counts (verification/solattn.inventory.{json,md}, solclear.inventory.{json,md}), quoted per-pool figures, and 8
on-chain pool/mint addresses copied from solattn and solclear data: 6 in agentC/provenance/solclear.json, 2
(HEsTf2…, Azgh9c…) in agentA/solattn.{json,md}, agentA/_drafts/solattn/p1-register.md, agentC/solattn.{json,md},
agentC/verification/solattn.claims.json and solattn.verification.md. These are public chain identifiers and
figures, not secrets, but they are solana research content, so "No solana" is not literally true of program-audit.
Evidence: `git ls-files | grep -E 'program-audit/.*(solattn|solclear)' | xargs -I{} git cat-file -s HEAD:{}`;
base58 intersection script and commit-id intersection in the sandbox. Options are the lead's: keep as-is with a
README sentence, drop findings/*/solattn* and solclear* (46 paths) from the build, or ask Kiros.

## Item 2. No secret, keypair, account id, personal contact or vendor bulk data

Passed. My scan over all 2,703 blobs and all 421 messages (Python regexes, sandbox):

- 0 hits: AWS AKIA, sk-/sk-ant-, GitHub ghp_/github_pat_, Slack xox, PEM private-key blocks, JWTs, 64-int keypair
  arrays, Alpaca/Databento/Helius/Polygon key shapes, North-American phone numbers.
- Account ids: pattern `\b[DU]U?\d{5,9}\b` gives 5 distinct tokens in 14 files, digit shapes: DU+7 ascending,
  DU+7 descending, DU+6 repeated, DU+7 repeated, U+7 ascending. All placeholders; 0 in messages. The real id is
  gone: "[paper account ID removed]" sits in 44 blobs and 1 commit message (README line 48-49 claim verified).
- Emails: 12 distinct; all vendor or generic (polymarket.com x7, cmegroup.com, theice.com, git@github.com,
  noreply@anthropic.com, a@b.com). The mailmap's old address (19 chars) occurs 0 times in blobs, identities or
  messages. "[private email removed]" replaced a contact address in 7 VRPExperiment blobs (UA strings and
  reports/task4/deribit_probe.json line 1581).
- Full name (R43): see item 4. Exact-case occurrences in blobs and log: 0.
- Personal repo names: replaced by "[personal repo, name removed]" in ORB/VRP DUPLICATION.md and program-audit
  README/RESUME/METHOD/ANCHOR/COMMON_RULES (the masked diff of the 52 rewritten blobs shows only these four
  replacement kinds plus the LICENSE holder).
- Vendor bulk data: 0 EXCLUDE.txt matches over all 1,515 historical paths (the R2 CME csv and the R36
  task6_delisted.json included); 3 binary blobs only (MLCryptoEngine desktop/src-tauri icons, 698 to 6,803 B).
- Cross-check with C3 (reports/p2_scratch/scan_report.md, scans/): gitleaks git (408 commits) and dir: 0 findings,
  agrees. scan_history secrets 3,273 "findings" = 2,757 sha256 hashes in MBTExperiment
  reports/boundary/vrp_manifest_b1_close.txt classed evm_private_key, 111 vendor emails, 34 base58 (the 8 S1
  addresses plus package-lock integrity fragments), 28 account ids (the placeholders above), 6 evm addresses
  (Hyperliquid HIP-3 deployer/feeRecipient quoted from a public API reply in NPL docs/ACCESS.md). hygiene: 14
  "phone_intl" are +4.xx/+33.xx numeric values in program-audit solattn findings; 13 "address_*" are IBKR Canada's
  registered office in VRPExperiment progress.md:363 and reports/task3/venue_table.md:40 (a public corporate
  address). Nothing personal. NEW vs P.1 = 0 in every tool, agrees with my reading.

## Item 3. Every claim in README.md and the 12 cards

Header facts (recomputed in the clone with `git log --reverse --format='%h %ai'` and `git rev-list --count HEAD --
experiments/<name>/`): first/last commit dates and "N commits in the original repo … shows N+1" match for all 12
(ETF 28/29, HF 13/14, Insider 7/8, MBT 23/24, MLC 91/92, NPD 11/12, NPL 41/42, ORB 59/60, PM 36/37, VRP 12/13,
program-audit 83/84, RPL 3/4; originals' `rev-list --count` give the same N). README table dates match the cards
and the clone. "July to September 2026" (07-30 to 09-21), "PropExperiment began on 2026-09-17" (its first commit
c2d2c44 2026-09-17 16:32:54 -0700) and "llm-news-drift's pre-registration (2026-07-27)" (EXPERIMENT.md first
committed 74532e7 2026-07-27, date from `git log --diff-filter=A`, file not read) verified.

Timeline claims, all verified from commit timestamps: ETF REGISTRATION 01:07:59 / HYPOTHESES 01:11:17 / first
measurement 13:04:41; HF first commit 15:23:16, sections 1-12 at 21:40:25; Insider 18:34:56 / 18:38:50 / 18:47:16;
MBT 23:48:40 / 23:51:07 / 23:54:33 (206 s) / probe 23:27:35; MLC HYPOTHESES.md added 2026-08-04, f0e5bc7
2026-08-06 07:02 (progress.md), 3a26c5e 2026-08-06 12:18 (progress.md), 4ec20ee 2026-08-11 22:46 (report.md); NPD
09:39:00 / data layer 10:06:55; NPL 17:54:38, sealed read 640137d 2026-08-27 20:03, HYPOTHESES.md 20:53 after it;
ORB 19:10:01 / 19:11:30 / 19:12:08 / ACCESS 19:18:07 / Amendment 24 fbd8185 20:13:26 / slippage f9db307 20:41:12;
PM 00:09:55 / 00:37:33 / 00:53:10; VRP 21:47:08 / 23:22:23; program-audit COMMON_RULES 17:38:57 / first findings
21:48:43. Cited ids: only three 7+ hex strings appear in README+cards (f0e5bc7, 3a26c5e, 4ec20ee); each is a commit
in the build; none exists in any of the 18 source repos (F3-S1).

Figures: 158 (card, file, figure) items checked against the cited file at HEAD (claims_check.py, sandbox): 151 exact;
7 present with a different rendering (MLC HYPOTHESES.md "PUMP −4.81, MERL −4.35" with a Unicode minus; NPD
REGISTRATION.md "minus 0.0161"; ORB README.md "−0.426679"; HF a1b_report.md "Five orders of the ten-order cap used.
No order filled."; HF progress.md "zero capital was deployed"; PM README.md "Not disproven, not unlikely,
unmeasurable." quoted in lower case); 0 missing. The hedges in each Result section are the source's own (ETF "nothing
here is evidence", Insider "not a null", NPD "underpowered unresolved", ORB "finding about this design", PM "cost
finding", NPL "scope decision, not a verdict", RPL "not a survey"). No card states a result stronger than its file.
ORB's 6,421 figure traces to EXCLUDE.txt line 45 as cited.

README AI-use (lines 37-39): recomputed from the 421 messages: 122 commits have both a Claude Co-Authored-By and a
Claude-Session line (122 with either); by model Claude Fable 5.1 = 82, all touching experiments/program-audit/;
Claude Opus 5 (1M context) = 39 (MBT 19, PM 8, NPL 6, Insider 6); Claude Fable 5 = 1 (NPL). CLAUDE.md at HEAD and
ever: 8 repos (ETF, Insider, MBT, MLC, NPD, NPL, ORB, PM). No other AI tool is named in any message (the 3 hits for
"gpt-"/"OpenAI"/"cursor" are NPD's model under test and the word cursor). docs/AI_USE.md exists in llm-news-drift.

README removals (lines 46-56): mailmap.txt has 1 non-comment line (3 tokens: handle, noreply address, one old
address) so "one mailmap line sets one author name and address" holds; the replacement kinds found are exactly
"full name became my handle" (LICENSE), "personal contact details" (private email, 7 blobs) and "one broker paper
account ID" (44 blobs, 1 message). EXCLUDE.txt lists every class named, including bulk vendor reference data (R36)
and the two removals the cards name. `.env.example` matches rule `\.env[^/]*$` and appears in no historical path;
MLCryptoEngine README.md:46 still says `cp .env.example .env`, so line 54 is accurate.

README "What came of it" (line 31-33): PropExperiment docs/DECISIONS.md:15 (HFExperiment's intent/gate pattern),
docs/prompts/STAGE_D.1.md:236-240 (ORBExperiment's 11.27x slippage result), docs/ACCESS.md:12 and
docs/STAGE_E_DESIGN.md:767 (MLCryptoEngine's shared vendor account and spend ledger), docs/prompts/STAGE_A.1.md:14-16
("multiple independent agents cross-checking … reserved for program-audit-style work"). All four named.

README Tests (lines 65-76) vs C4 (reports/p2_scratch/tests_report.md, complete at 11:03:24) and my recount from
/home/kiros-li/.cache/p2-tmp/TestRunner/*/logs/*.xml (passed = tests − failures − errors − skipped): ETF 241/0/1,
HF 149/9/0, Insider 101/0/4, MBT 180/1/0, MLC 494/21/2, NPD 114/0/1, NPL 446/0/1, ORB 418/0/1, PM 110/1/0, VRP
50/0/0, RPL 112/0/0, program-audit "Ran 6 tests … OK". 12 of 12 rows match. Causes verified in the logs: HF's 9 fail
on `account_mode_mismatch` ("lacks the paper prefix DU", the placeholder), MLC's 21 are FileNotFoundError on
tests/fixtures, MBT and PM fail on the absent .env.example. The "no keys, no network, lock files where present"
wording matches C4's method (env -i, unshare -rn, uv sync --frozen where a lock exists).

## Item 4. The A2 items

| Item | Status | Evidence |
|---|---|---|
| R36 | done | ORB CARD.md line 15 names reports/stage_a1r/task6_delisted.json, 6,421 names, "bulk vendor data, and nothing shows a right to redistribute it (EXCLUDE.txt)"; EXCLUDE.txt lines 43-47 |
| F3-S1 | done | the 3 ids in MLC CARD.md line 8 exist in the build, in no source repo |
| F3-S2 | done | MBT CARD.md line 8 "206 seconds"; 23:51:07 to 23:54:33 = 206 s |
| F3-S3 | done | README Tests section is self-consistent: 12 projects in 12 rows, program-audit's command named once, failure causes match the rows |
| F3-S4 | done | 12 of 12 rows match the junit recount and C4 |
| F3-S6 | done | no README line claims where llm-news-drift names these repos; the only pointer is to docs/AI_USE.md, which exists |
| F3-N4 | done | every card line 2 says what it counts ("in the original repo" and "`git log -- experiments/X/` shows N+1: the extra one adds this card") |
| F3-N7 | done | README line 52-53 lists "bulk vendor reference data" |
| F2-N7 | done | README line 53-54 |
| F2-N8 | done | README 76 lines, 842 words (518 outside the table) |
| Licence line | done | README line 60 is exactly "I have not chosen a licence yet. Until I do, the default applies: all rights reserved." with no mark |
| R43 | done | 3 LICENSE files ever (MBT, PM, RPL). MBT and PM: "Copyright (c) 2026 kirosli00tuff". RPL: holder is two lowercase words of 19 and 12 chars (a project-name placeholder, not a person), unchanged from its source. The MBT source holder (two capitalised words, 5+2 letters) occurs 0 times exact-case in archive blobs and log; case-insensitive hits are the handle itself and the /home path |
| Confirm marks | none | 0 in README.md and the 12 cards |

## Item 5. Build facts

- `nice -n 10 git fsck --strict --full` on the clone: exit 0, no output.
- Blobs over 1 MB: 0 of 2,703 (top: uv.lock 667,208; MBT reports/boundary/vrp_manifest_b1_close.txt 412,057; NPL
  reports/h5/census.rows.json 330,621).
- EXCLUDE.txt paths in any commit: 0 of 1,515 (15 rules parsed; literal rules tested as path or directory prefix,
  regex rules with Python re, after stripping experiments/<name>/ as the build does). EXCLUDE.txt itself is tracked
  at the root by design (README line 51).
- No symlink or submodule mode in any tree; no .gitmodules or .gitattributes ever.

## Notes

- N1 (NOTE) ORB CARD.md line 8: "Sections 1 to 14 followed within two minutes": 19:10:01 to 19:12:08 is 127 s.
  "Within three minutes" or "within about two minutes" would be exact.
- N2 (NOTE) PM CARD.md line 22 quotes "not disproven, not unlikely" in lower case; README.md has "Not disproven,
  not unlikely, unmeasurable." Same words, case changed inside quotation marks.
- N3 (NOTE) C3's paths and hygiene scans report 2 "excluded_path" findings (MLCryptoEngine/desktop/index.html,
  NPDExperiment/reports/session_record.html). Those are the two files EXCLUDE.txt line 33-34 deliberately keeps;
  the scan matched the rule against the prefixed archive path, where the `^(?!desktop/index\.html$…)` lookahead
  cannot fire. Against the original paths the rule gives 0 hits. Scan artefact, not an archive defect.
- N4 (NOTE) /home/kiros-li appears in 425 blobs (OS username in logged paths), plus /home/u in 1. Same letters as the
  public handle; not contact data. Informational only.
- N5 (NOTE) Public third-party contacts remain by design: Polymarket, CME and ICE addresses, IBKR Canada's registered
  office. Not personal.
- N6 (NOTE) Public on-chain identifiers remain outside S1: Hyperliquid HIP-3 deployer and feeRecipient 0x addresses
  quoted from a public API reply in NPL docs/ACCESS.md and docs/H5_ACCESS.md.
- N7 (NOTE) The 4 byte-identical archive/solana blobs and the shared detection code are boilerplate or
  MLCryptoEngine-origin (dates in item 1). No action.
- N8 (NOTE) gitleaks reports 408 commits scanned against 421: the 12 import merges and the empty root carry no
  diff. Consistent.
- N9 (NOTE) C3 and my counts agree once the same definition is used (occurrences per unique blob, case-insensitive).
  My first substring count with ugrep over the blob dump undercounted (2,494 / 2,013 / 8) because ugrep collapses
  matches in binary-looking blobs; the Python recount (7,413 / 6,853 / 20) is the figure to use.

## Not checked

- The C3 bulktext and headlines scans (the lead ran them after the C3 brief; not in my brief).
- MLCryptoEngine/desktop (Tauri) has no test command; C4 did not run it and neither did I.
- The content of ~/.config/p1-private/ (never opened); the replace-text rule count there is taken from
  reports/P.2_STATE.md and not verified.
- Whether the public llm-news-drift README names any of these repos (not required once the README line was cut).

## Sandbox artefacts (read-only inputs for the lead, no literals inside)

/home/kiros-li/.cache/p2-tmp/ArchiveReviewer/: archive/ (clone), archive_objects.txt, archive_blobs.txt,
archive_paths_all.txt, solana_blobs.txt, source12_blobs.txt, new_blob_ids.txt, rewritten_paths.txt, blobs/,
solblobs/, exclude_check.py, mailmap_grep.py (prints counts only), masked_diff.py, claims_check.py.
