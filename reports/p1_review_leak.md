# Stage P.1 review F1: leak audit of the llm-news-drift build

Reviewer: LeakAuditor-FableXHigh (worker-xhigh, Fable 5.1). Recorded 2026-11-07 04:52 MST.
Subject: /tmp/claude-1000/p1/RebuildTest/final1, HEAD e93542e, 50 commits from f99fe72 (2026-07-27) to e93542e
(2026-11-07), 498 objects, 304 unique blobs, 191 paths. Read only. Nothing fixed. The lead rules.

This file is committed to AiTrader, which is public. It holds no secret, key, account ID, address, handle, quoted
headline or other removed literal. Each one is described and located instead (R12).

## Verdict

No BLOCKING finding. Three SHOULD FIX findings, all about words in public documents, none a secret. Ten NOTE
items, including two corrections to the scan record. The build holds no key, token, private email, phone number,
street address, database, binary, vendor payload or market-data table. Both private identity literals are absent
from every object in the store.

| id | severity | where | what |
|---|---|---|---|
| S1 | SHOULD FIX | docs/DECISIONS.md:210, docs/prompts/STAGE_P.1.md:391 and 603-604 | names the repos being made private, two of them personal and not in the archive |
| S2 | SHOULD FIX | docs/DECISIONS.md:172-173, docs/prompts/STAGE_P.1.md:6-7 | states the personal reason for the showcase |
| S3 | SHOULD FIX | EXCLUDE.txt lines 8-13 at the root | declares six paths never included while the tree holds redacted copies at those paths |
| N1 | NOTE | EXPERIMENT.md:769-772, three latest versions | two real headlines quoted verbatim, disclosed by LICENSE_NOTE.md, document locked |
| N2 | NOTE | scan record (R14) | the "0 hits, including EXPERIMENT.md" statement covers the 200-row sample only |
| N3 | NOTE | publish/checks/llm-news-drift.mailmap lines 3-4 (AiTrader, not the build) | comment says the folder never goes public, but G1 commits it to public AiTrader |
| N4 | NOTE | 38 commit-message trailer lines, 6 report files | session links and scratchpad ids, not secrets |
| N5 | NOTE | 93 blobs, ops/systemd, C.2b and C.3 reports | home path, machine model, Mountain-time clock. R16 covers the path |
| N6 | NOTE | 15 confirm marks under publish/, 12 references elsewhere | go_public.sh gates the 15. A tree-wide check would trip on the 12 references |
| N7 | NOTE | reports/c1_relevance_sample.csv (history copy), universe lists | derived vendor fields only, no text, no bars |
| N8 | NOTE | whole build | headline text outside the 200-row sample could not be tested against the database |
| N9 | NOTE | config/default_config.yaml | my own check agrees with config_check.md and R11 |
| N10 | NOTE | R25 class F | both digests recomputed as matching their snapshot.json |

## SHOULD FIX

### S1. The list of repos being made private is itself public

docs/DECISIONS.md line 210 ("Made private: ...") and docs/prompts/STAGE_P.1.md lines 391 ("Never included: ...")
and 603-604 (step H4) name five repositories that the stage makes private. Three of them (solattn, solclear,
MLCryptoEngine) go into research-archive, so their names are public by design. The other two are not in the
archive at all. One reads as a personal portfolio site and one reads as a redesign concept for a named roofing
business, which looks like client work. Naming a repo in a public document while hiding the repo defeats the
hiding, and a reader can search the handle for them. The archive's SOURCES.txt line 30 repeats the two names, and
OC10 keeps that file in AiTrader, so it is public too.

Evidence: `sed -n 210p docs/DECISIONS.md` and `sed -n '391p;603,604p' docs/prompts/STAGE_P.1.md` in final1. The two
names appear in those three places and nowhere else in the build (grep over all 304 blobs and all commit messages).
Already public: both files are in AiTrader main (f4e2f3a), so nothing new leaks today. The showcase repo still
should not carry them. Suggested fix: in DECISIONS.md replace the two names with "two personal repos". The prompt
file is kept as sent by convention, so the lead decides whether to redact it with a bracketed note or accept it.
No ruling covers this. R16 covers only the handle and the home path.

### S2. The personal reason for the showcase

docs/DECISIONS.md lines 172-173 (V6) and docs/prompts/STAGE_P.1.md lines 6-7 (the summary) state why the public
repos are being built, in terms of a personal application. A reader of the showcase, including the audience it is
built for, will find that sentence in the repo's own decision log. It is personal circumstance, not a secret, and it
reads badly in the artifact it describes. Already public in AiTrader (f4e2f3a). Suggested fix: "public showcase of
the experiment" with the purpose left out. No ruling covers this.

Evidence: `git -C final1 grep -n -i 'applying' HEAD`: 2 hits, both listed above. 0 in commit messages.

### S3. EXCLUDE.txt contradicts the tree it ships in

The root EXCLUDE.txt, lines 8-13, lists reports/c1_relevance_adjudication.md and the five c1_relevance CSVs under
"NEVER-INCLUDED". The HEAD tree holds files at exactly those six paths: the A2 redacted copies mapped from
publish/llm-news-drift/reports/ after the invert-paths filter (R14 accepted their presence as designed). README.md
line 156 says the relevance files have the headlines removed, but EXCLUDE.txt itself says they are never included.
A reader who checks the exclusion list against the tree finds six apparent violations. Suggested fix: one comment
line in EXCLUDE.txt stating that redacted copies from publish/llm-news-drift/reports/ take these six paths after the
filter. A comment does not change the filter, and EXCLUDE.txt is not in the freeze manifest (34 entries, none under
docs/ or at the root).

Evidence: my own matcher over all 191 paths against the 15 EXCLUDE rules: 6 hits, these six, each in commit e93542e
only. `git -C final1 log --all --name-only --format=''` gives the same 6.

## NOTE

### N1. Two real headlines quoted in EXPERIMENT.md

EXPERIMENT.md lines 769-772 (Amendment 8, the fund-exclusion sensitivity passage) quote two third-party headlines
verbatim inside parentheses and paraphrase a third. One is a bank research note on a retailer's price target. One
quotes a well-known investor on AI companies. The passage is in the three latest EXPERIMENT.md versions (blobs
5341661e, d359ed74, ad21aca4, commits 9105182 onward). Lines 1918 and 2846 mention "21 real headlines" from Stage 1
and give aggregates only, with no text, in all 17 versions.

LICENSE_NOTE.md already says EXPERIMENT.md quotes a few short headlines and that they belong to their publishers.
EXPERIMENT.md is locked by Amendment 10 and bound by hash (c2_UNLOCK.json experiment_sha256), so it cannot change.
Two short quotes with commentary is the normal scale of fair quotation. No action. The lead may want LICENSE_NOTE.md
to say "two" rather than "a few".

Evidence: `grep -n -E 'Bank of America|Sample headlines' EXPERIMENT.md` (lines 769-770). Across all 304 blobs the
pattern hits only the three EXPERIMENT.md versions.

### N2. Record correction: what the headline scans established

R14 says the headline scan "found 0 hits in every file and commit, including EXPERIMENT.md". That scan, and the
rebuild rerun, tested 40-character windows of the 195 sample headlines of 40 or more characters. It could not see
the N1 quotes, which are not in the sample. The accurate statement is LICENSE_NOTE's. My own checks extend the
record:
- every one of the 200 sample headlines, whole, normalized (case, whitespace, curly quotes), against every blob and
  every commit message: 0 hits. This includes the 5 headlines shorter than 40 characters that both prior scans
  skipped.
- 25-character windows of those 5 short headlines: 0 hits.
- quoted strings of 25 or more characters starting with a capital, in every markdown file: all are commit subjects,
  SQL, verdict-table phrases, or test strings. The only news-like text is N1.
- news-vendor payload field names outside code: 0. Market-data column triples: 0 (bulktext agreed).

### N3. The mailmap comment is wrong about where it ends up

publish/checks/llm-news-drift.mailmap lines 3-4 say the folder never reaches the public repository, so the private
address is not published by that file. R12 commits publish/checks/ to AiTrader at G1, and AiTrader is public. The
exposure is not new: the address is the author or committer email on 408 identity lines in AiTrader's own history,
and the handle sits in 2 tracked files at AiTrader HEAD (counts only, values unprinted). R12 already accepted this.
Suggested: fix the comment so it does not claim privacy it does not have. Outside the build.

Evidence: `git -C AiTrader log --all --format='%ae%n%ce' | grep -ci <address>`: 408.

### N4. Session identifiers in commit messages and reports

38 "Claude-Session:" trailer lines name 9 distinct claude.ai session links. Six session scratchpad UUIDs and
transcript paths under ~/.claude/projects/... appear in reports/C.2_STATE.md, C.2b_STATE_20261106.md,
C.2b_RETURN_20261106.md, C.3_STATE.md, C.3_RETURN.md, c3_tests_record.md, c3_change_record.md, c3_review_runonce.md
and c3_review_diff.md. They are not credentials and open nothing without the owner's account. No action.

### N5. Machine and region details

The home path appears in 93 of the 304 blobs (R16 accepted it, and the four new public docs README, LICENSE_NOTE,
HOW_TO_VERIFY, TIMELINE, AI_USE carry 0). ops/systemd/news-collect.service hard-codes the working directory and
venv path. CLAUDE.md names the laptop model and memory. C.2b and C.3 reports stamp 83 times in MST while the timer
runs on America/Vancouver, so the machine clock is on Mountain time. Region-level only. No action beyond R16.

### N6. The confirm marks and the go_public.sh gate

15 resolvable "[KIROS: confirm]" marks sit under publish/: README.md 3 (lines 27, 123, 128), LICENSE_NOTE.md 2,
docs/AI_USE.md 5, docs/TIMELINE.md 5. publish/go_public.sh step 1 refuses while any remains under publish/, so they
cannot ship by that path. docs/DECISIONS.md lines 185 and 218 and docs/prompts/STAGE_P.1.md (10 lines) mention the
mark by name as part of the process text. They are not marks to resolve, and a check widened to the whole built tree
would trip on them. G2 must rebuild after the 15 are resolved, or the built repo carries them.

### N7. Derived vendor fields

The history copy of reports/c1_relevance_sample.csv carries id, symbol, query_date, sector and stratum for 200 rows.
The sector label comes from the Finnhub profile endpoint. The grader-input copy's third column holds a database
and table name, not issuer names. The universe lists 400 symbols with strata derived from Alpaca bars. These are
per-symbol labels and aggregates, not text, bars or payloads. The snapshot.json files hold counts by state and
query_date, hashes, sizes and local paths, and no outcome column. reports/c2/verify_gate/explore_schema.out prints
table names, a column list and counts only. No action.

### N8. What could not be tested

The headline database holds 12,614 judged headlines. The COMMON rules close every database to me, so the only
headline text I could test against the build is the 200-row sample in AiTrader's reports/c1_relevance_sample.csv.
Headlines outside that sample could reach the build only as quoted prose. I hunted for those by quoted strings,
news-vendor field names, news phrasings and company-name contexts, and found only N1. That hunt is not exhaustive.

### N9. config/default_config.yaml, my own check (R11 asked F1)

No value of 20 or more alphanumeric characters. No key, token, secret or password line with a non-environment-name
value. No email, no home path, loopback host only. Agrees with reports/p1_scratch/scans/config_check.md.

### N10. R25 class F digests, rechecked

The sha256 in reports/c2/snap_20261028/snapshot.json appears on 3 lines of reports/C.2_RETURN.md, and the one in
snap_20261106/snapshot.json on 5 lines of reports/C.2b_RETURN_20261106.md. Both are snapshot digests, as R25 says.

## Checks that passed, with the evidence command

All run on 2026-11-07 between 04:40 and 04:52 MST from the AiTrader root or from final1. Blobs were dumped once to
/tmp/claude-1000/p1/LeakAuditor/blobs (304 files, 6.0 MB), commit messages to out/commit_messages.txt (1,041 lines),
paths to out/all_paths_ever.txt (191).

| check | command (abridged) | result |
|---|---|---|
| gitleaks, full history, my own run | `nice -n 10 ~/.local/bin/gitleaks git --redact=100 --report-format json .` in final1 | exit 0, 50 commits, 2.82 MB, 0 findings. Agrees with R13 |
| key and token shapes | grep over all blobs for Anthropic, OpenAI, Google, AWS, GitHub, Slack, Alpaca key id, PEM, Bearer, JWT, org and workspace ids, `?token=` style query strings, `password=` | 0 for every pattern. APCA hits (20) are environment variable names only |
| emails in blobs | regex for any address | only the GitHub noreply address (5) and noreply@anthropic.com (3) |
| emails in commit messages | same regex on out/commit_messages.txt | noreply address 94, noreply@anthropic.com 44, nothing else |
| author and committer identities | `git log --all --format='%an <%ae> %cn <%ce>'` | 94 kirosli00tuff noreply, 6 Claude noreply, no other ident |
| the two replace-text literals (read from publish/checks, never printed) | case-insensitive grep over blobs, over messages, and `git cat-file --batch-all-objects --batch` over the raw store | 0, 0, 0 |
| phone numbers, structured street addresses | North American and +international shapes | 0 |
| IPv4 | any dotted quad | 127.0.0.1 only. The other match is a package version string in c1_harness_freeze.json |
| host names | thinkpad, laptop, .local, .lan | prose words only, no host name |
| home paths | `/(home|Users)/...` | one user path only (R16) |
| UUIDs | 6 distinct | all session scratchpad ids in reports (N4), no account ids |
| long non-hex tokens 32+ | all | universe ids, config key names, test names, the UUIDs above |
| binary blobs and SQLite | `grep -I` per blob, "SQLite format 3" | one empty blob (backtest/__init__.py), 0 SQLite |
| largest blobs | `git cat-file --batch-check` | EXPERIMENT.md 186,222 bytes, nothing over 5 MB |
| paths against EXCLUDE.txt | my own matcher, 15 rules, 191 paths | 6 hits, the S3 paths, all in e93542e only. No .db, .env, key, keystore, token, secret, docs/FOLLOWUP_CREDENTIALS.md, reports/c1_scratch/, publish/checks/, publish/research-archive/, publish/profile/ or go_public.sh path in any commit |
| paths against ALLOWLIST.txt | every path, directly or via the publish/llm-news-drift/ mapping | 191 of 191 matched |
| paths deleted before HEAD | `git ls-tree -r HEAD` against all paths ever | none. Nothing was added and later removed |
| URL domains | all blobs | paper-api and data alpaca, finnhub, ntfy.sh, whale-alert, sec-api, anthropic, openai, googleapis, claude.ai session trailer, github.com, docs.astral.sh. No private host |
| vendor payload fields | Finnhub news keys, Alpaca bar keys | in discovery/finnhub_source.py and llm_consensus/evidence.py code only |
| tests/fixtures/finnhub_SYNTHETIC.json | read the README key and item shapes | labelled synthetic, no live response, sources "X" |
| test headline strings | all headline literals in tests and news_eval/synthetic.py | made-up names (Acme, AAA, "From the future"), none real |
| news_experiment/spec.py prompt | quoted strings 25+ | rule ids and labels, no example headline |
| COLLECTION_LOG.md | key, account, spend, balance probes | spend in USD per run and a credential label name. No value |
| .claude/settings.json, agents | read | four env limits and a model alias. Nothing personal |
| tests/conftest.py, account_manager/credentials.py | env and path probes | temp dirs and environment variable names only |
| unlock file | reports/c2_UNLOCK.json approver value | a sentence naming Kiros and a timestamp, no email |
| embarrassment words | profanity, family, health, money, employment, messaging handles | all hits technical (provider_health, test family, HTTP client, resume, "whatever") except S2 |
| 64-hex values | R15 and R25 | not redone beyond N10 |
| street words | R26 | not redone |

## Rulings already covering findings here

R11 (config, N9), R12 (replace-text and mailmap in AiTrader, N3), R13 (gitleaks), R14 (the six redacted copies, S3
adds the documentation mismatch), R15 and R25 (64-hex, N10), R16 (home path and handle, N5), R26 (street words).
S1, S2, N1, N2, N4 and N6 have no ruling yet.

## Not done

- No scan of the research-archive build. That is F2.
- No claim tracing. That is F3.
- shellcheck not installed (R7). extract.sh was not run or linted by me.
- Headline text beyond the 200-row sample could not be tested (N8).
