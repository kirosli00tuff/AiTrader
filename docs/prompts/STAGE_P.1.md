
STAGE P.1 "PUBLIC REPOS AND GITHUB PROFILE (PRIVATE UNTIL KIROS FLIPS)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: Kiros is applying to schools with this experiment and
PropExperiment as his two main coding projects. This stage builds his
public GitHub profile in one pass (V7, which merges the old P.1 and P.2):
- llm-news-drift: a clean repository holding only the pre-registered
  news-drift experiment, with its git history from Stage A (commit
  74532e7, 2026-07-27) onward. Frozen files keep their exact paths, so
  `news_eval.freeze check` verifies in a fresh clone. It gets a
  first-person README, TIMELINE, HOW_TO_VERIFY and AI_USE.
- research-archive: one repository that groups the smaller research
  repos from July to September 2026, each in its own folder with its
  history kept, plus one CARD.md per experiment and an index README.
- the profile README repo kirosli00tuff/kirosli00tuff, plus description,
  topic and bio text.
- GitHub changes in the safe direction only. The stage creates the three
  new repos as PRIVATE and pushes them, sets descriptions, and makes five
  old repos private. It makes nothing public. Kiros does that himself
  with publish/go_public.sh after he resolves every `[KIROS: confirm]`.

It does not touch the collector, the experiment or any frozen file, reads
no outcome, spends nothing, and changes nothing in PropExperiment.

Decisions in force: docs/DECISIONS.md V1 to V7. V6 holds the
llm-news-drift decisions (name, README voice, mailmap, AI-use content).
V7 holds the profile layout and the archive.

Binding, in priority order:
1. CLAUDE.md invariants. The collector is untouched and blindness holds.
   This stage reads repository files and git history only, never
   news_experiment.db.
2. EXPERIMENT.md, sha256
   964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe. It is
   published unchanged.
3. The C.3 manifest reports/c3_harness_freeze.json, with the sha256
   recorded in reports/C.3_RETURN.md section 1. `freeze check` must print
   FROZEN: match against it, in AiTrader and in a fresh clone of
   llm-news-drift. reports/c1_harness_freeze.json is published as the
   record and is not expected to match the current EXPERIMENT.md.
4. docs/DECISIONS.md V6 and V7.
5. This prompt.

Read first:
- CLAUDE.md
- docs/PROMPT_WRITING.md sections 4 and 8
- docs/DECISIONS.md V1 to V7
- docs/STAGES.md
- EXPERIMENT.md, by search only (`grep -n '^## \|^### '`): the status
  block, then each amendment's opening paragraph
- reports/C.1_RETURN.md, C.2_RETURN.md and C.3_RETURN.md, section 1 of
  each
- docs/prompts/README.md
- .claude/agents/*.md and .claude/settings.json
- `git log --format='%h %ad %an %s' --date=short` since 2026-07-27
- PropExperiment's README.md, read-only, for the one-line profile entry.
  Never write anything in PropExperiment.

Lead: Opus 5.5, effort max. Ultracode: off.
- Reviewers: Fable xhigh, with the model confirmed from each reviewer's
  transcript. Opus max in a fresh context only if Fable is unavailable,
  and the return says so.
- Worker routing (V9, from PropExperiment V59): Sonnet high for counts,
  inventories, hash checks, test runs with a failure list, the
  mechanical redaction and table formatting. Opus xhigh for
  history-rewriting scripts and scan code. Opus high for the experiment
  cards. If unsure between Sonnet and Opus for code whose output is
  published, use Opus.
- Worker briefs give exact paths and line ranges. Workers return a path
  and at most 200 words.
- At most 4 workers at once, and at most 1 heavy job.

Why this lead and effort: these are public, permanent artifacts, read by
admissions reviewers. The silent failures are a leaked secret, wallet key
or personal datum anywhere in any history, a third-party dataset
published, a card or README claim the record does not support, a manifest
that no longer verifies, an AI-use account that overstates or understates
what was done, and a visibility change that takes something down. Each
one is costly and looks fine at a glance.

Usage and time:
- Launch at Kiros's go-ahead, after C.3 is committed, outside 23:00 to
  23:45 America/Vancouver on weekdays. No fixed end. Expect 6 to 9 hours.
- If a weekday 23:00 arrives mid-run: at 22:55 finish the current tool
  call, start no new worker, job or test run, checkpoint STATE, and
  resume at 23:45.
- Checkpoint to reports/P.1_STATE.md after every step, and resume from it
  after any usage limit or reboot.
- Self-wipe (V9, from PropExperiment V60): at about 150k tokens of lead
  context, at a quiet point (no worker or foreground job running, detached
  jobs may continue), and never between a gh call that changes something and its STATE line:
  1. write a RESUME HERE section of at most 60 lines in reports/P.1_STATE.md: what is
     done, what is next, the exact continuation commands, each unfinished
     worker with its brief path, and each detached job allowed to keep
     running
  2. append "READY FOR WIPE <time>" to the STATE file
  3. run this one command, then end the turn with no further tool call:
     setsid nohup bash -c 'sleep 30; tmux send-keys -t stage-p1 "/clear"; sleep 1; tmux send-keys -t stage-p1 Enter; sleep 8; tmux send-keys -t stage-p1 "Read the newest RESUME HERE section of reports/P.1_STATE.md and every STATE line after it, then the parts of docs/prompts/STAGE_P.1.md it points to, and continue Stage P.1 as a fresh lead after a planned self-wipe. First append a line Lead self-wipe done to the STATE file with the time. Earlier workers cannot be messaged: re-spawn any unfinished worker from its brief. A detached job still running is checked from disk and never started twice. Do not redo finished work. Run unattended."; sleep 1; tmux send-keys -t stage-p1 Enter' >/dev/null 2>&1 &
  The /clear keeps the same CLI process, model and effort.
- A usage-limit stop or a shutdown: write RESUME HERE if possible. The
  claude-auto-retry monitor resumes after a usage limit. The planner
  resumes anything else.
- Never cut a check to save usage.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue.

============================================================
PART 0: START GATES (FIXED HERE)
============================================================

0.1 Start checks, quoted verbatim in the return:
- the CLAUDE.md status command
- `git status --short` and `git log --oneline -5`. The log must contain
  "Stage C.3 hard-stop readout build and re-freeze", and
  reports/C.3_RETURN.md must exist. If not, stop.
- `tmux ls`. No stage-c3 or stage-c2b session may still be running a
  claude process.
- `sha256sum EXPERIMENT.md`, which must equal the Binding value
- `PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc .venv-eval/bin/python -m news_eval.freeze check`,
  which must print FROZEN: match on the C.3 manifest
- `free -m`
- `gh auth status`, with the scopes recorded. gh reads the GNOME keyring,
  so first run `export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.
  Without that export, gh wrongly reports the token as invalid. If the
  `repo` scope is missing, do every part except H, and say so.

0.2 Tools, installed outside the repo and never into .venv:
- git-filter-repo via `uv tool install git-filter-repo`
- gitleaks from its official GitHub release binary into ~/.local/bin,
  with the version recorded

If either install fails, stop and say why.

0.3 Write reports/P.1_STATE.md and the estimate ETA table.

Layout in AiTrader. All public source files this stage writes live under
publish/, which is committed in AiTrader:
- publish/llm-news-drift/: ALLOWLIST.txt, extract.sh, README.md, docs/,
  reports/ (redacted files). The extraction maps this folder to the root
  of llm-news-drift.
- publish/research-archive/: SOURCES.txt, build_archive.sh, README.md,
  the cards, and the exclusion list.
- publish/profile/: README.md, bio.txt, metadata.json.
- publish/go_public.sh: the one script Kiros runs to go public.

============================================================
PART A: LLM-NEWS-DRIFT ALLOWLIST AND SOURCE FOLDER (FIXED HERE)
============================================================

A1. The allowlist, written to publish/llm-news-drift/ALLOWLIST.txt.
Owner: the lead.
- **Experiment paths, history kept:**
  - EXPERIMENT.md
  - news_experiment/
  - news_eval/
  - tests/test_news_eval_*.py, tests/test_news_experiment_*.py,
    tests/test_collection_daily.py, plus any fixture or conftest those
    tests need (prove it by running them in the extracted repo)
  - docs/STAGES.md, docs/DECISIONS.md, docs/ORCHESTRATION.md,
    docs/PROMPT_WRITING.md and docs/prompts/
  - CLAUDE.md, .claude/agents/ and .claude/settings.json
  - reports/: the B.2, C.1, C.2, C.3 and later stage returns, STATE
    files, reviews, rulings, change records, verification folders, both
    freeze manifests, c2/gate_log.jsonl and c2/snap_*/snapshot.json
  - COLLECTION_LOG.md
  - ops/systemd/news-collect.timer and news-collect.service
  - scripts/blind_interim_20260928.py
- **Dependencies:** map the full import graph of news_experiment/ and
  news_eval/, including imports inside functions. Known so far:
  backtest/fees.py, backtest/universe.py, llm_consensus/provider_health.py,
  llm_consensus/http_json.py and ops/logpipe.py, plus anything they import.
  Dependencies carry their history only from 2026-07-27 onward. Simplest:
  include them as one commit, "import collector dependencies from AiTrader
  <sha>". Keep their paths identical, because the manifest hashes them.
- **Never included:**
  - every *.db and *.db-*
  - .env*, any keystore and any key or token file
  - docs/FOLLOWUP_CREDENTIALS.md and the engine docs
  - the C++ engine, ui/, electron-app/ and every other engine folder
  - reports/c1_scratch/
  - publish/research-archive/ and publish/profile/
  - the five headline-bearing relevance files in their original form:
    c1_relevance_sample.csv, c1_relevance_grader_input.csv,
    c1_relevance_grades_opus.csv, c1_relevance_grades_fable.csv and
    c1_relevance_final.csv. Also c1_relevance_adjudication.md if it
    quotes headlines.

A2. The redacted relevance files. Owner: Redactor-SonnetHigh
(worker-high on sonnet). Write publish/llm-news-drift/reports/<same
names>, keeping only id, symbol, query_date, sector, stratum, the grades
and the name source. Drop every headline and every reason or rationale
column. Write a headline-free adjudication summary. The extraction maps
these onto reports/ in place of the excluded originals. A test asserts
that no redacted file contains any string from the headline column of
its original.

A3. The headline scan. Owner: the lead, with a script. Scan every text
file in the allowlist, at every commit of the history, for any substring
of 40 or more characters that matches a headline in the original
relevance sample. Record and rule on every hit.
- Short illustrative quotes inside EXPERIMENT.md, such as Amendment 8's
  three example headlines, stay. EXPERIMENT.md is published unchanged and
  its hash binds the experiment. The return lists them.
- Any other bulk headline listing is excluded or redacted.

A4. The extraction script, publish/llm-news-drift/extract.sh. Owner:
ExtractionCoder-OpusXHigh (worker-xhigh on opus). It must:
- clone AiTrader into a temporary directory and never touch the working
  repo
- run git-filter-repo with the allowlist, the exclusions, and the path
  rename from publish/llm-news-drift/ to the root
- apply a mailmap: kiros1134@gmail.com and the
  "kirosli00tuff <kiros1134@gmail.com>" identity both become
  "kirosli00tuff <249804683+kirosli00tuff@users.noreply.github.com>".
  Leave every other author unchanged: the Claude co-author lines and the
  Perplexity-agent commits stay as recorded.
- write the result to ~/Documents/GitHub/llm-news-drift as a local repo

Determinism test: two runs produce identical commit hashes.

The first commit of the extracted history must be dated 2026-07-27 or
later. Report the first and last commit, the commit count, and every
non-Kiros author.

============================================================
PART B: LLM-NEWS-DRIFT PUBLIC DOCUMENTS (FIXED HERE)
============================================================

Owner: the lead drafts all four. DocWriter-OpusXHigh (worker-xhigh on
opus) may draft TIMELINE from the commit log.

Kiros's writing style applies to every public file in this stage: plain
words, active voice, short sentences, no em dashes, no semicolons, no
hype ("groundbreaking", "revolutionary" and the like), and data over
adjectives. Each statement Kiros must personally confirm is marked
`[KIROS: confirm]`.

B1. publish/llm-news-drift/README.md, about one page, first person, as
Kiros:
- the question, in one paragraph
- why it is pre-registered, in one paragraph
- how it works: collector, model call, five states, blindness, harness,
  freeze, independent verification, with one small diagram in text or
  mermaid
- status today, honestly:
  - collecting since 2026-07-28
  - the C.2 gate failed on 2026-10-28 because sigma was 442 bp against
    the 180 bp assumed
  - Amendment 10 reads the verdict at the 120-session hard stop (the date
    recorded in C.3), with the result expected in late January 2027
  - C.3 built that hard-stop path and re-froze the harness
  - the permanent gaps, and why each happened
  - no result yet, and no claim made
- the repository map
- links to TIMELINE, HOW_TO_VERIFY and AI_USE
- one line noting that the original working repo, AiTrader, stays public
  until the readout as the dated audit trail, with its link
No number goes in the README that cannot be traced to a file in the
repo.

B2. publish/llm-news-drift/docs/TIMELINE.md: every dated event from
Stage A to today. That covers the registration, each amendment, each
stage with its prompt and return, the freezes, the gate, the decisions
V1 onward, and the gaps. Each event has its date and the commit hash in
the extracted repo (take the hashes from a first extraction pass, which
is deterministic).

B3. publish/llm-news-drift/docs/HOW_TO_VERIFY.md:
- clone the repo
- `git log --follow EXPERIMENT.md` shows the dated amendments
- build the harness environment from news_eval/requirements-eval.lock
  with uv and Python 3.12
- run `python -m news_eval.freeze check`, which should print FROZEN:
  match on the C.3 manifest
- explain why the C.1 manifest reports EXPERIMENT.md as changed
  (Amendment 10 came after it), and how to check that every other entry
  still matches
- run the synthetic test suite, which needs no data
- what cannot be verified publicly and why: the headline database is
  third-party news and is never published, while its snapshot hash and
  row counts are in reports/c2/

B4. publish/llm-news-drift/docs/AI_USE.md, first person, the full
account Kiros asked for (V6):
- **Plain statement:** the code in this repository was generated and
  written with Claude Code, Anthropic's command-line agent, and its CLI
  options. The design, prompts and reviews came from a planning
  conversation with Claude on claude.ai.
- **Roles:** the planning chat (designs, writes the prompts, reviews the
  returns, keeps the decision log), the CLI lead session, the workers,
  and the independent reviewers. Name each model and effort as actually
  used, from the prompts and returns. Kiros approves every amendment,
  every launch and the unlock.
- **CLI options and setup actually used:**
  - `--model`, `--effort` (xhigh, max)
  - `--dangerously-skip-permissions` for unattended runs
  - the worker agent files in .claude/agents
  - concurrency and model pins in .claude/settings.json
  - tmux sessions with an auto-retry monitor for usage limits
  - the context-wipe and resume-from-STATE rule
- **How prompts are structured:** the full anatomy from PROMPT_WRITING.md
  section 8 and the PropExperiment Prompt Structure, part by part (header
  and markers, summary, decisions in force, read first, lead and why,
  usage and time, autonomy line, PART 0 gates, work parts, SCOPE does
  NOT, guardrails, delegation plan, deliverable). Include one short real
  excerpt from docs/prompts/.
- **Organization:** lettered stages, prompts committed before launch,
  V-numbered decisions, STATE checkpoints, eight-section return
  documents, sha256 freeze manifests, independent Fable verification and
  written rulings.
- **The markdown files, one line each on what each one does:**
  EXPERIMENT.md, CLAUDE.md, docs/ORCHESTRATION.md,
  docs/PROMPT_WRITING.md, docs/STAGES.md, docs/DECISIONS.md,
  docs/prompts/, reports/*_RETURN.md, reports/*_STATE.md and
  COLLECTION_LOG.md.
- **My review:** in Kiros's words, "I personally review every line of
  code written afterwards" `[KIROS: confirm]`.
- **Other agents in the history:** the Perplexity-agent commits, if any
  survive the extraction, are listed with what they touched.
- **What the AI got wrong and was caught:** a few real examples from the
  returns and rulings, such as the numpy defect C.1 found, the leakage
  findings Fable raised, or the C.3 start-gate defect in the planner's
  own prompt.

B5. A short LICENSE note. Recommend a licence under Decisions for the
user. Do not choose one. The same recommendation covers research-archive.

============================================================
PART C: LLM-NEWS-DRIFT BUILD AND VERIFY IN A FRESH CLONE (FIXED HERE)
============================================================

Owner: the lead, with scripts.

C1. Run extract.sh. Then run it again into a second directory and
confirm identical commit hashes.

C2. Clone the result into a new temporary directory. Then:
- build a venv with `uv venv --python 3.12` and
  `uv pip install -r news_eval/requirements-eval.lock`
- `freeze check` must print FROZEN: match on the C.3 manifest
- run every included test, using the full list from A1

Run the tests from a clone that omits reports/c2_UNLOCK.json and
reports/c2/, as C.3 did (reports/C.3_RETURN.md section 7 item 4): the
autouse guards in three test files error when those paths exist. Record
both the clean result and, for the record, the full-clone teardown
errors with their cause. Never reuse C.3's scratch path.

Record the counts. A test that needs an AiTrader-only file is a finding:
either add the file to the dependency set, or document the exclusion.

C3. Run `gitleaks detect --source <clone> --log-opts="--all"` over the
full history. It must report zero findings, or each finding is ruled on
in writing.

C4. History hygiene:
- no path from the A1 "never included" list appears in any commit
  (`git log --all --name-only`)
- no blob is larger than 5 MB
- the A3 headline scan, rerun on the extracted history, finds only the
  ruled EXPERIMENT.md quotes
- grep the extracted history for "kiros1134", phone-number patterns and
  street-address words. Expect zero hits after the mailmap, or rule on
  each hit.

============================================================
PART D: RESEARCH-ARCHIVE (FIXED HERE)
============================================================

Purpose (V7): one public repo that shows the smaller experiments Kiros
ran before the two main projects, with their real commit dates, without
crowding the profile with many small repos.

D1. Sources, written to publish/research-archive/SOURCES.txt. Every
source folder is read-only: clone it into a temporary directory and
never write inside it.
- /mnt/large-storage/Archive/GitHub/: ETFExperiment, HFExperiment,
  InsiderExperiment, MBTExperiment, MLCryptoEngine, NPDExperiment,
  NPLExperiment, ORBExperiment, PMExperiment, VRPExperiment,
  program-audit, retail-power-limits, solattn, solback, solceil,
  solclear, solcopy, soltool
- MBTExperiment, solback, solceil, solcopy and soltool have no GitHub
  remote. Use the local history.
- For each repo with a remote: in the temporary clone, fetch origin and
  compare the default branch. If one side contains the other, use the
  newer one. If they diverged, use the local history and record it.
- Never included: AiTrader, PropExperiment and its worktrees,
  kirosliforlio, dc-roofing-redesign-concept, and ~/OpenManus (a
  third-party clone, not Kiros's work).
- If any other Git repo turns up under ~/Documents, ~/Desktop or the
  archive drive, record it and leave it out.

D2. Inventory. Owner: Inventory-SonnetHigh (sonnet, high). For each source, record in STATE:
commit count, first and last commit date, authors, size, languages, the
top-level tree, and every doc that states a question, a pre-registration
or a result.

D3. Layout and classification. Two groups:
- experiments/<name>/ for the *Experiment repos, MLCryptoEngine,
  program-audit and retail-power-limits
- solana/<name>/ for solattn, solback, solceil, solclear, solcopy and
  soltool

Each source is INCLUDE by default: code, docs and history. It becomes
CARD ONLY (a card in the archive, no code, no history) if its scans in
D6 find something that path exclusion cannot remove, or if it is mostly
third-party data. The README table marks the solana/ group with
`[KIROS: confirm]`, because Kiros decides whether it stays in the public
archive.

D4. Path exclusions, applied to every source, written to
publish/research-archive/EXCLUDE.txt:
- *.db, *.sqlite*, *.parquet, *.feather, *.pkl, *.npy, *.npz, *.h5,
  *.arrow and any model weights
- data/, raw/, cache/, logs/ and any folder of market data
- .env*, keystores, and any file named like a key, wallet, secret or
  token
- any JSON file that parses as an array of 64 integers (a Solana
  keypair), wherever it sits
- saved third-party pages: *.html, *.mhtml and *.pdf not written in the
  repo
- vendor market data, such as price, quote, trade or option CSVs
- any blob over 1 MB that is not code or markdown written in the repo
Tiny fixtures that tests need may stay if they are proven synthetic.

D5. The build script, publish/research-archive/build_archive.sh. Owner:
ArchiveCoder-OpusXHigh (worker-xhigh on opus). It must:
- for each INCLUDE source, in order of first commit date: clone to a
  temporary directory, run git-filter-repo with EXCLUDE.txt, the
  A4 mailmap and `--to-subdirectory-filter <group>/<name>`, then merge it
  into the archive with `--allow-unrelated-histories`, one merge commit
  per source: "import <name> history (<first date>..<last date>, <n>
  commits)"
- give each merge commit a fixed author, committer and date (the source's
  last commit date), so the build is deterministic
- add the cards and README from publish/research-archive/ as the last
  commit, "add experiment cards and index"
- write the result to ~/Documents/GitHub/research-archive

Determinism test: two runs produce identical commit hashes.

D6. Archive scans, over the full built history. Owner: the lead, with
scripts. Each hit is recorded and ruled on in writing:
- `gitleaks detect --source <archive> --log-opts="--all"`
- Solana keypairs: JSON arrays of 64 integers, and base58 strings of 86
  to 88 characters
- EVM private keys: 64 hex characters, with or without 0x, outside
  known hash fields
- API keys and tokens by prefix (sk-, sk-ant-, ghp_, gho_, xox, AKIA and
  the like), and Bearer headers
- broker, exchange or prop-firm account IDs, and wallet addresses tied
  to Kiros
- "kiros1134", any email other than the noreply address and model
  co-author lines, phone-number patterns and street-address words
- any path from D4, and any blob over 5 MB
- third-party text in bulk: news, headlines, scraped pages or vendor
  data
A key found anywhere in history makes that source CARD ONLY, and the
return lists it under Decisions for the user with "rotate this key".

D7. The cards. Owner: CardWriter-OpusHigh workers (opus, high), at most
3 at once, each given a set of sources. One
publish/research-archive/cards/<group>/<name>/CARD.md per source, copied
into the source's folder by the build script. Every card has the same
fields:
- the question, in one or two sentences
- what was registered before testing, with the file path, or
  "not pre-registered"
- dates: first and last commit
- the data, by name and source, with a note that it is not included
- the method, in three to five lines
- the result, with every number traced to a file path in that folder
- why it stopped
- one thing learned, marked `[KIROS: confirm]`
Cards draw only on the source's own files and history. An unknown field
says "not recorded". A card never states a result stronger than its
source file does.

D8. publish/research-archive/README.md, about one page, first person:
- what this is: the smaller experiments from July to September 2026,
  before llm-news-drift and PropExperiment, with links to both
- one table: name, dates, question, result in a few words, link to the
  card
- an honest line on the results. If most were negative or stopped, say
  so and name what carried into the main projects (for example
  pre-registration, freezes and independent review), traced to files.
- how AI was used here, from the history: the tools and agents that
  appear in these commits, and a link to llm-news-drift's AI_USE for the
  current method. Do not claim the current method for earlier repos.
- the layout, and a note that data files are excluded

D9. Build and verify. Run build_archive.sh twice into two directories
and confirm identical hashes. Then rerun D6 on the final build. For any
source with tests, run them in a fresh clone if they need no excluded
data, and record the counts. A test that needs excluded data is
documented, not fixed.

============================================================
PART E: PROFILE AND METADATA (FIXED HERE)
============================================================

Owner: the lead.

E1. publish/profile/README.md, for the repo kirosli00tuff/kirosli00tuff:
- two lines on who Kiros is: UBC Mechanical Engineering, fourth year
  `[KIROS: confirm]`. No location, email, phone or birth date.
- the two main projects, one or two lines each: llm-news-drift, and
  PropExperiment drafted from its README `[KIROS: confirm]`
- research-archive, with the number of experiments
- one line on how he uses AI, linking AI_USE
- no stats widgets, badges or visitor counters

E2. publish/profile/metadata.json: description, topics and homepage for
llm-news-drift, research-archive and AiTrader. AiTrader's description
says it is the working repo behind llm-news-drift and stays public as
the dated audit trail until the 2027 readout. A suggested PropExperiment
description goes in the return only. This stage never edits
PropExperiment's metadata.

E3. publish/profile/bio.txt: one bio line of at most 160 characters,
marked `[KIROS: confirm]`.

============================================================
PART F: REVIEW (FIXED HERE)
============================================================

Three reviewers run in parallel after Parts C, D and E. Each has its
model confirmed from its transcript.

F1. LeakAuditor-FableXHigh (worker-xhigh on fable). The llm-news-drift
build and its full history only. Hunt for secrets, personal data,
third-party data (headline datasets, news text, vendor data whose terms
forbid redistribution), excluded paths, and anything that could
embarrass Kiros publicly. Output: reports/p1_review_leak.md.

F2. ArchiveAuditor-FableXHigh (worker-xhigh on fable). The
research-archive build and its full history only. The same hunt, with
extra weight on wallet keys, exchange and prop-firm account IDs, vendor
data, and source files that slipped past EXCLUDE.txt. Also check that
every INCLUDE or CARD ONLY call matches D3 and D6. Output:
reports/p1_review_archive.md.

F3. ClaimsReviewer-FableXHigh (worker-xhigh on fable).
- Trace every factual claim in the llm-news-drift docs, the archive
  README, every card and the profile README to a file or commit.
- Flag anything overstated, especially any implied result for
  llm-news-drift (there is none yet) and any card stronger than its
  source.
- Check that AI_USE covers every item in B4 and V6.
- Check that HOW_TO_VERIFY works step by step in a fresh clone.
Output: reports/p1_review_claims.md.

Each finding is marked BLOCKING, SHOULD FIX or NOTE. The lead rules on
every finding in reports/p1_rulings.md. BLOCKING and SHOULD FIX findings
are fixed, then the affected build and its checks rerun before Part G.

============================================================
PART G: SOURCE COMMIT AND FINAL LOCAL BUILDS (FIXED HERE)
============================================================

Both builds read committed history only. Until this part, every test
build runs on a temporary clone in which the working publish/ files are
added as a scratch commit. That scratch commit never reaches AiTrader.

G1. The source commit in AiTrader: publish/, reports/p1_review_*.md and
reports/p1_rulings.md, staged by explicit path, as "Stage P.1 publish
sources". This is the first of the stage's two commits. Two are needed
because the public builds must contain publish/, and the return must
record the GitHub results that come after the builds.

G2. Run extract.sh into ~/Documents/GitHub/llm-news-drift and
build_archive.sh into ~/Documents/GitHub/research-archive, from the G1
commit. Rerun on the final builds: freeze check in a fresh clone,
gitleaks on both, the D6 scans, and the determinism check. Record HEAD
hash, commit count, first and last commit dates and size for each.

============================================================
PART H: GITHUB, PRIVATE ONLY (FIXED HERE)
============================================================

Owner: the lead. Run only after Part G, if Parts C, D9, F and G are
clean and gh has the `repo` scope. Every gh command runs with the 0.1 DBUS export.

H1. The before record. Write reports/p1_github_before.json from
`gh repo list kirosli00tuff --limit 100 --json name,visibility,stargazerCount,forkCount,watchers,isArchived,description,homepageUrl`.

H2. Create and push, private:
- `gh repo create kirosli00tuff/llm-news-drift --private --source ~/Documents/GitHub/llm-news-drift --push`
- the same for research-archive
- the profile repo kirosli00tuff/kirosli00tuff, from a local repo built
  from publish/profile/README.md
If a name already exists on the account, skip that repo, record it, and
continue.

H3. Apply metadata.json to llm-news-drift, research-archive and AiTrader
with `gh repo edit` (description, homepage, topics). Change nothing else
on AiTrader.

H4. Make private: solattn, solclear, MLCryptoEngine,
dc-roofing-redesign-concept and kirosliforlio. For each one, first:
- check `gh api repos/kirosli00tuff/<name>/pages`. If GitHub Pages is
  live, skip that repo and list it under Decisions for the user, because
  a private repo on a free plan cannot serve Pages.
- record stars, forks and watchers from H1.
Then run `gh repo edit kirosli00tuff/<name> --visibility private --accept-visibility-change-consequences`.

H5. Write reports/p1_github_after.json the same way as H1, and a diff of
the two in the return.

H6. publish/go_public.sh, for Kiros to run later. Owner: the lead. Write
it before G1, so the source commit holds it. It must:
1. refuse to run if any `[KIROS: confirm]` remains under publish/
2. check that gh has the `user` scope, and if not, print
   `gh auth refresh -h github.com -s user` and stop
3. rerun extract.sh and push llm-news-drift. This must be a fast-forward.
4. rebuild research-archive and the profile repo. Force-push them only
   while GitHub reports them as private. Once public, a rebuild that is
   not a fast-forward stops with a message.
5. set the bio from bio.txt with `gh api -X PATCH /user -f bio=...`
6. flip llm-news-drift, research-archive and kirosli00tuff to public
   with `--accept-visibility-change-consequences`
7. print the web-only steps: pin llm-news-drift, PropExperiment and
   research-archive, turn on "Include private contributions" in the
   profile settings, and set the avatar
The stage writes and syntax-checks this script, and tests steps 1 and 2
only. It never runs steps 3 to 6.

============================================================
SCOPE
============================================================

This stage does NOT:
- open news_experiment.db or any snapshot, or read any outcome
- edit EXPERIMENT.md, news_experiment/, news_eval/, any test,
  backtest/, llm_consensus/, ops/, any report from an earlier stage, or
  any frozen file
- touch the collector, its timer or its units
- write inside any source repo in D1, or change AiTrader's history. Every
  rewrite works on a temporary clone.
- make any repo public, delete, archive or transfer any repo, force-push
  to any repo that was public before this stage, or change the
  visibility of AiTrader or PropExperiment
- write anything in PropExperiment or change its GitHub metadata
- set the GitHub bio. go_public.sh does that after Kiros confirms it.
- publish any database, key, .env, keystore, wallet file, headline
  dataset or vendor data
- push AiTrader. The planner pushes.
- run C.2b, the gate, or anything in PropExperiment
- install into .venv, call a paid API, or print a key

============================================================
GUARDRAILS
============================================================

- Start and end checks quoted verbatim, as in 0.1. At the end, also run
  `git -C ~/Documents/GitHub/llm-news-drift log --oneline | wc -l`,
  the same for research-archive, the fresh-clone freeze check output, and
  `gh repo list kirosli00tuff --limit 100 --json name,visibility`.
- In AiTrader, commits touch only publish/, reports/P.1_*, reports/p1_*,
  PROGRESS.md, RETURN.md, the docs/STAGES.md line and the
  docs/prompts/README.md row. Stage them by explicit path. There are two
  named commits (G1 and the final one) and no push of AiTrader.
  COLLECTION_LOG.md is never staged.
- Every gh command that changes something is logged to STATE with its
  output before the next one runs.
- Nothing runs between 23:00 and 23:45 America/Vancouver on weekdays.
- At most 1 heavy job. Stop it if free memory falls below 2 GB.
- Before ending, confirm no worker or shell is still running.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| Part 0, A1, A3, B, C, D1, D3, D4, D6, D8, D9, E, rulings, G, H, return | lead | opus | max | serial | public artifacts and account changes, so the lead keeps claims, inclusion, rulings and every gh call |
| A2 | Redactor-SonnetHigh | sonnet | high | parallel with A4 | well-specified column removal, checked by a test |
| A4 | ExtractionCoder-OpusXHigh | opus | xhigh | parallel with A2 | history rewriting, silent-failure risk |
| B2 (optional) | DocWriter-OpusXHigh | opus | xhigh | after a first extraction pass | long, factual and checkable |
| D5 | ArchiveCoder-OpusXHigh | opus | xhigh | after D4 | multi-repo history rewriting and merging |
| D2 | Inventory-SonnetHigh | sonnet | high | parallel with A2 and A4 | counts and listings only, no judgment |
| C2, D9 test runs | TestRunner-SonnetHigh | sonnet | high | after each build | runs suites and lists failures |
| D7 | CardWriter-OpusHigh (up to 3) | opus | high | parallel, after D2 | research reading, each card traced to its source files |
| F1 | LeakAuditor-FableXHigh | fable | xhigh | parallel with F2 and F3 | independent leak hunt on llm-news-drift |
| F2 | ArchiveAuditor-FableXHigh | fable | xhigh | parallel with F1 and F3 | independent leak and wallet-key hunt on the archive |
| F3 | ClaimsReviewer-FableXHigh | fable | xhigh | parallel with F1 and F2 | every public claim traced |

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each part into subtasks with one objective, inputs, output
       path and format, allowed tools, and boundaries.
    2. Route per CLAUDE.md. State model and effort for each subtask before
       spawning; confirm each reviewer's model from its transcript.
    3. Run independent workers at once, within the worker cap.
    4. Collect results as files plus short summaries.
    5. Verify with independent reviewers as listed.
    6. Synthesize in the lead against this prompt, and write the synthesis
       to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to
       reports/P.1_STATE.md after each step.

============================================================
DELIVERABLE
============================================================

Write reports/P.1_RETURN.md. Also write one dated entry at the top of
PROGRESS.md and of RETURN.md, one docs/STAGES.md line under a new
"Stage P: publication" heading, and the P.1 row's Run column in
docs/prompts/README.md. Then make the final commit, "Stage P.1 public
repos and GitHub profile". No push.

The return has these fixed sections:
1. Summary, at most 250 words: what each new repo contains, the checks
   each passed, what changed on GitHub, and what Kiros must do before
   anything goes public.
2. Guardrail evidence: start and end checks verbatim, and the order of
   events, including every gh call.
3. Results:
   - the llm-news-drift allowlist and dependency map
   - the redaction table and the headline-scan rulings
   - the archive source table: each source, INCLUDE or CARD ONLY and why,
     commits, dates, and what EXCLUDE.txt removed
   - the archive scan rulings
   - determinism for both builds
   - the fresh-clone checks and test counts
   - the gitleaks results
   - the repo stats
   - the GitHub before and after diff
4. Delegation record, with each reviewer's model confirmed from its
   transcript.
5. Verification: each finding, the ruling and the fix.
6. Open choices.
7. Decisions for the user, each with a recommendation:
   - every `[KIROS: confirm]` mark, with its file and line
   - whether the solana/ group stays in the public archive
   - the licence for both repos
   - any key to rotate, and any repo skipped in H2 or H4
   - the suggested PropExperiment description, for the PropExperiment
     chat
   - the go-public steps: `gh auth refresh -h github.com -s user`, fix
     each mark in publish/ and commit, run publish/go_public.sh, then the
     web-only steps it prints
   - how to refresh after the gate reruns and the readout: rerun
     go_public.sh steps 3 and 4, which must fast-forward once public
8. Session cost: the final ETA table and per-model token counts from the
   transcripts, never estimated.

The last thing before ending: list every open choice in section 6.

END PROMPT
