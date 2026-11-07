# D1r. Archive recheck after the S1 rebuild (Stage P.2, rulings P2-R1 and P2-R4)

Reviewer: ArchiveRecheck-FableXHigh (Claude Fable 5.1, worker-xhigh). Finished 2026-11-07 11:59 MST (`date`).
Brief: section D1r of reports/p2_scratch/briefs/R2_reruns.md. Independent: I wrote neither the exclusion nor the
edits, and every number below is recomputed from the builds and the source repos, not taken from the exclusion
report or the build report (those are quoted only for comparison).

Builds judged: final `~/Documents/GitHub/research-archive`, HEAD d4f2b756a5f209b5b1defdc8e1025fcd98720f6e, 420
commits (`rev-list --count HEAD` and `--all`), refs/heads/main only, 0 tags, 0 remotes, 0 stash, 0 reflog entries,
working tree clean. Pre-S1 `/home/kiros-li/.cache/p2-tmp/c2a.CwINlb/archive`, HEAD 2bc0033bbd1f, 421 commits.
The two scratch rebuilds r2s1b.mHaaPY and r2s1c.kQBjHp have the same HEAD d4f2b756 and the same 5,556 objects as
the final, so the rebuild is deterministic and judging the final covers them.

Sandbox: /home/kiros-li/.cache/p2-tmp/ArchiveRecheck/ (scripts `derive_addrs.py`, `scan_build.py`, outputs
`scan_final.txt`, `scan_pre.txt`, `*_blobs.tsv`, path lists; `addrs.private` and `ids_*.private` hold the
addresses and solana commit ids, mode 600, never printed). Writes: this file and the sandbox only. No git add,
commit, stash or gh. Nothing written in a source repo or in any build. Sources read with read-only `git log`.

Verdict: **no BLOCKING and no SHOULD FIX finding.** S1 is fixed and the rebuild changed only what P2-R1 and the
traced edits intended. Five NOTEs follow, two of them for the lead's mention-class ruling.

## 1. S1 fixed

| check | final build | command |
|---|---|---|
| history paths under experiments/program-audit/ with solattn or solclear in them, case-insensitive | **0** (pre-S1: 46) | `git log --all --format= --name-only --no-renames \| sort -u \| grep -ciE 'solattn\|solclear'` |
| same, any folder, and in the HEAD tree (`ls-files`) | 0 and 0 | same grep over all 1,469 history paths; `git ls-files \| grep -ciE` |
| blobs holding any of the 8 on-chain addresses, exact bytes, every blob of `rev-list --objects --all` | **0** of 2,642 (pre-S1: 10 of 2,703) | `scan_build.py` |
| commit messages holding an address | 0 (pre-S1: 0) | same |
| blobs quoting a full (40-hex, token-bounded) solattn commit id / distinct paths | **38 / 6** (pre-S1: 65 / 27) | same |
| blobs quoting a full solclear commit id / distinct paths | **40 / 8** (pre-S1: 70 / 29) | same |
| union: blobs quoting either, distinct paths, paths present at HEAD | 40, 8, 8 | same |
| distinct solana ids quoted anywhere in the final | 1 of 20 solattn ids, 1 of 28 solclear ids | same |
| commit messages quoting a solana id | 0 (pre-S1: 0) | same |

Addresses. I derived them myself from the 46 excluded files at the pre-S1 HEAD: base58 tokens of 32 to 44
characters with a digit, a lowercase and an uppercase letter, not all-hex. That gives **9** tokens (lengths 43 and
44), not 8. The S1 worker's list (`s1/addrs.private`, 8 entries) is a strict subset of mine; the prefixes agree
(36gm, 7CSW, Azgh, CP1K, HEsT, Hp4X, UutV, gYgU). The ninth, prefix **AMBh**, sits only in
findings/agentC/solattn.json, in the sentence "its mint AMBh… has ZERO mentions anywhere in the 180-file store", so
it is a token mint address tied to the HEsT pool. It is in no blob of either solana repo's full history (0 and 0),
so it was not copied from their data; it is still an on-chain identifier. All 9 are at 0 blobs and 0 messages in
the final build. The S1 worker's note that agentA/solattn.json holds one full address, not two, is correct (a7
only; Azgh appears there truncated).

Solana commit ids come from `git rev-list --all --reflog` on /mnt/large-storage/Archive/GitHub/solattn (20 ids,
refs main and origin/main) and solclear (28 ids), read-only; my sets equal the S1 worker's and D1's lists. Matching
is token-bounded 40-hex; a plain-substring match gives the same blobs and paths, so no quote is hidden inside a
longer hex run. The 8 remaining paths, all program-audit: findings/ANCHOR.md, findings/protocol/COMMON_RULES.md,
findings/agentA/NPLExperiment.reopen.md, findings/agentA/CROSS_REPO.md and CROSS_REPO.json (solclear only),
provenance/git-baseline-BEFORE.txt, provenance/git-status-checks.log, provenance/launch-args/agentA-leads.json.
Each repo contributes exactly one distinct id to the archive, so these are anchor pointers, not history.

**NOTE 1 (for the lead's mention-class ruling).** The "before" figures in reports/p2_review_archive.md S1 (84 and 89
blobs) do not reproduce. My exact recount of the pre-S1 build is 65 and 70 blobs, the same as the S1 worker's.
I tested two other countings: blob-path pairs (65 and 70, since every hit blob has one path) and blobs holding a
full id or an abbreviated prefix of 7 to 39 hex (91 and 85). Neither gives 84 and 89. D1's path counts (27, 29) do
agree. The "after" figures to rule on are 38 / 6 and 40 / 8, union 40 blobs on 8 paths, one id per repo.

## 2. The rebuild changed only what was intended

| check | result | evidence |
|---|---|---|
| history paths removed (pre-S1 minus final) | **46**, exactly the paths matching `^experiments/program-audit/findings/(.*/)?[^/]*(solattn\|solclear)`; 0 removed outside the rule; **0 paths added** | `comm` over the two sorted `git log --all --name-only` lists (1,515 vs 1,469) |
| rule applied to every source's full history (read-only `git log --all --name-only` on the 12 SOURCES.txt folders) | program-audit 46 matches, the other 11 sources 0; every source's path count equals the build report's "paths before"; the 238 other solattn/solclear-named program-audit paths are all under work/ (0 elsewhere) | sandbox loop |
| per-source commits | only program-audit changed, 83 to 82, 1 pruned; `rev-list --count HEAD -- experiments/<name>/` identical for 11 sources, program-audit 84 to 83 | both builds |
| pruned commit | one: c7c537a4116e, 2026-09-05T16:19:31-07:00, "findings: agentB solclear p1-findings positives ledger (recovered from the draft and snapshot; draft unchanged)", which added only findings/agentB/_drafts/solclear/p1-findings.positives.md; matches the exclusion report | `(author date, subject)` matching pre-S1 vs final: 2 in pre not final (this one and the old program-audit merge "83 commits"), 1 in final not pre (the merge re-titled "82 commits") |
| commit ids | 363 shared; 57 rewritten = 28 program-audit commits from the first commit that touched an excluded path (2e0b375aa181, 2026-09-03) onward, 26 program-audit commits after the pruned one, the program-audit and MBTExperiment merges and the cards commit; the 28 program-audit commits before 2e0b375 keep their ids; 335 commits outside program-audit's chain all shared | `rev-list` ancestry sets |
| blobs new in the final | **4**: README.md, EXCLUDE.txt, experiments/ORBExperiment/CARD.md, experiments/program-audit/CARD.md | blob-set difference with paths from `log --all --raw --no-abbrev -m --root` (0 unmapped blobs) |
| blobs gone from the final | 65 = 61 blobs that lived only under the 46 paths + the 4 previous versions of those four files | same |
| identities | author and committer `kirosli00tuff <249804683+kirosli00tuff@users.noreply.github.com>` on all 420 and 420 | `git log --all --format` |
| `git fsck --strict --no-progress` | rc 0, no output | run on the final |
| branches | refs/heads/main only; no tags, remotes, stash, reflog | `for-each-ref`, `reflog --all` |
| largest blob | 667,208 bytes; 0 blobs over 1,000,000 | `cat-file --batch-check` over all 2,642 blobs |
| HEAD~1 | b86f2399fedc, the same MBTExperiment merge as in the S1 worker's scratch builds A and B | `rev-parse` |

**NOTE 2.** The brief expects the new blobs to be "only README.md and card blobs". EXCLUDE.txt is new too, because
it is published at the archive root and carries the P2-R1 rule (lines 48 to 52). That is the ruling's mechanism,
not a stray change. The four new blobs are byte-identical to the working copies in publish/research-archive/, and
the working copies differ from 73aa37a only by the diff in section 3, so the new blobs carry exactly that diff.

## 3. README and card statements changed since 73aa37a

`git diff 73aa37a -- publish/research-archive/` touches 4 files, 15 insertions, 10 deletions. At the final HEAD,
README.md, EXCLUDE.txt and all 12 cards (`experiments/<name>/CARD.md`) are byte-identical to the working copies
(`cmp`). Each changed statement, traced:

| edit | statement at final HEAD | recomputed on the final build |
|---|---|---|
| program-audit CARD.md line 2 | "`git log -- experiments/program-audit/` shows 83: one commit added only a removed file and is gone, and the extra one adds this card" | `git rev-list --count HEAD -- experiments/program-audit/` = 83 (pre-S1 84); 82 history commits + the cards commit; the pruned commit added one file only, now excluded |
| program-audit CARD.md line 14 | "The snapshots, work/ and the findings files on two of the thirteen repositories are not included in this archive (EXCLUDE.txt)." | findings/ANCHOR.md at HEAD lists 13 repositories, solattn and solclear among them; 46 findings paths on exactly those two removed by the rule; EXCLUDE.txt is in the HEAD commit at the root |
| README.md line 37 | "121 commits name Claude in a Co-Authored-By line and carry a Claude-Session line" | 121 commits with a Claude Co-Authored-By, 121 with Claude-Session, the same 121 (pre-S1 122) |
| README.md line 39 | "Claude Opus 5 (1M context) on 39, Claude Fable 5.1 on 81, all in program-audit, and Claude Fable 5 on 1" | by trailer name 39 / 81 / 1; Fable 5.1 commits touching any path outside experiments/program-audit/: 0 |
| README.md lines 52 to 56 | "program-audit's work/ folder and its findings on two of the repos it audited" added to the EXCLUDE list sentence; paragraph rewrapped, no other word changed | rule present in EXCLUDE.txt at HEAD; wording matches what the rule removes |
| ORBExperiment CARD.md line 8 (P2-R4) | "Sections 1 to 14 followed within about two minutes." | REGISTRATION.md commits in the final: 19:10:01 (Section 0), 19:11:30 (Sections 1-12), 19:12:08 (Sections 13 and 14): 127 s |

Unchanged statements re-checked: "8 of the 12 repos have a CLAUDE.md" (8 `experiments/*/CLAUDE.md` at HEAD);
program-audit card dates (history commits 2026-08-29T23:18:13 to 2026-09-13T01:55:58, the pruned commit was
2026-09-05); no README or card line names a solattn or solclear file.

Commit messages (name-mention class, unchanged by P2-R1): commits whose message names solattn 7 (pre-S1 7),
solclear 7 (pre-S1 8), message lines 18 (pre-S1 19).

## 4. Public-term blob counts on the final build

Method as C3's grep_scan.py: every blob of `rev-list --objects --all` once, `re.findall` case-insensitive, "files" =
distinct rev-list paths of blobs with a hit. My recount of the pre-S1 build reproduces scan_report.md lines 80 to
89 exactly (7415/158, 6864/132, 20/8, 328/43; messages 7/8/1/0; paths 25/25/0/0), so the method matches.

| term | blob occurrences | files | blobs with a hit | commits whose message hits | paths | pre-S1 (occ / files / msgs / paths) |
|---|---|---|---|---|---|---|
| solattn | **3496** | 134 | 454 | 7 | 0 | 7415 / 158 / 7 / 25 |
| solclear | **2761** | 92 | 300 | 7 | 0 | 6864 / 132 / 8 / 25 |
| solcopy | 20 | 8 | 20 | 1 | 0 | 20 / 8 / 1 / 0 |
| solana | **283** | 25 | 133 | 0 | 0 | 328 / 43 / 0 / 0 |
| solback, solceil, soltool, the email handle | 0 | 0 | 0 | 0 | 0 | 0 |

Identities: 0 hits for every term (one noreply identity). The C3r rerun's table should match these numbers.

## 5. Notes

- **NOTE 1** (section 1): D1's 84 / 89 "before" blob counts do not reproduce; 65 / 70 do. After: 40 blobs, 8 paths,
  one id per repo. For the lead's ruling.
- **NOTE 2** (section 2): EXCLUDE.txt is a fourth new blob, by design.
- **NOTE 3**: the excluded files held a ninth on-chain identifier (mint, prefix AMBh) that D1's list of 8 did not
  name. Gone with the file (0 blobs in the final). No action; recorded so the "8 addresses" count is not repeated
  as complete.
- **NOTE 4** (my own slip): while checking D1's counting method I ran `head -5` on D1's sandbox file
  `ArchiveReviewer/sol_commits.txt`, which holds the solana commit ids in plain text, so five solattn commit ids
  appear in my transcript. They are commit ids of a private repo, not p1-private literals, and the file already
  sat in plain text in D1's sandbox; nothing was written to the AiTrader tree or this report. Recorded for the
  audit trail.
- **NOTE 5**: the program-audit card's Result still cites findings/agentA/CROSS_REPO.md, whose first finding is on
  solclear and which quotes one solclear commit id; the S1 worker flagged the same (item 2). Mention class under
  the current ruling; not re-argued here.

## Not checked

- The C4r test rerun and the C3r tool reruns (scan_history.py bulktext and headlines, the private-term rules):
  other workers' briefs. The replace-text file under ~/.config/p1-private was never opened; private-term counts
  rely on the build report's whole-archive line (0 for all 5 rules) and C3r.
- go_public.sh, test_go_public.sh and SOURCES.txt confirm-mark behaviour (D2's domain).
- Whether the one quoted solattn and solclear id is each repo's anchored HEAD (not needed for the count).
- The README "## Tests" table and any README or card statement not changed since 73aa37a beyond those listed
  under "Unchanged statements re-checked".
- Whether the AMBh mint address is otherwise public; irrelevant once the file is gone.
- D1's findings other than S1 and N1, and the GitHub side.
