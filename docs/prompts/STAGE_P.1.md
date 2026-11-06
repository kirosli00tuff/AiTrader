STAGE P.1 "PUBLIC REPO EXTRACTION (LOCAL BUILD, NO PUSH)"

BEGIN PROMPT - SUMMARY OF PROMPT

Summary: Kiros is applying to schools with this experiment and
PropExperiment as his main coding projects, and wants this one shown
publicly. This stage builds a clean public repository, llm-news-drift. It
holds only the pre-registered news-drift experiment, with its git history
from Stage A (commit 74532e7, 2026-07-27, EXPERIMENT.md) onward.
- Frozen files keep their exact paths, so `news_eval.freeze check`
  verifies in a fresh clone.
- The repo gets a first-person README for Kiros to edit, plus TIMELINE,
  HOW_TO_VERIFY and AI_USE documents.
- Every verbatim third-party headline dataset is removed or redacted.
- It is built locally with a re-runnable, deterministic extraction script.

What the stage does NOT do:
- It does not push or create anything on GitHub. `gh` is logged out on
  this laptop, and Kiros flips the repo public himself after reading the
  README.
- It does not touch the collector, the experiment or any frozen file.
- It reads no outcome.
- It spends nothing.

Decisions in force: docs/DECISIONS.md V1 to V6. V6 holds this stage's
decisions: the name, the README voice, the mailmap and the AI-use content.

Binding, in priority order:
1. CLAUDE.md invariants. The collector is untouched and blindness holds.
   This stage reads repository files and git history only, never
   news_experiment.db.
2. EXPERIMENT.md, sha256
   964996723df6b1d6778461bad664e1599fdac9ca21dbe5e924f5214c3da78ebe. It is
   published unchanged.
3. The C.1 manifest, reports/c1_harness_freeze.json, sha256
   77c9bd73f0a98e9e3c909ef2e3d57defe4ee4375e85e89cad2992e8c8840b2a9. It
   must verify in a fresh clone of the extracted repo.
4. This prompt.

Read first:
- CLAUDE.md
- docs/PROMPT_WRITING.md sections 4 and 8
- docs/DECISIONS.md V1 to V6
- docs/STAGES.md
- EXPERIMENT.md, by search only (`grep -n '^## \|^### '`): the status
  block, then each amendment's opening paragraph
- reports/C.1_RETURN.md section 1
- reports/C.2_RETURN.md section 1
- docs/prompts/README.md
- .claude/agents/*.md and .claude/settings.json
- `git log --format='%h %ad %an %s' --date=short` since 2026-07-27
- the PropExperiment Prompt Structure summary in PROMPT_WRITING.md
  section 8

Lead: Opus 5.5, effort max. Ultracode: off.
- Reviewers: Fable xhigh, with the model confirmed from each reviewer's
  transcript. Opus in a fresh context only if Fable is unavailable, and
  the return says so.
- Mechanical redaction: Sonnet high. Script and verification code: Opus
  xhigh.
- At most 4 workers at once, and at most 1 heavy job.

Why this lead and effort: this is a public, permanent artifact. The
silent failures here are a leaked secret or personal datum anywhere in
history, a third-party headline dataset published, a README claim that
the record does not support, a manifest that no longer verifies, and an
AI-use account that overstates or understates what was done. Each one is
costly and looks fine at a glance.

Usage and time:
- Launch at Kiros's go-ahead, outside 23:00 to 23:45 America/Vancouver on
  weekdays. No fixed end. Expect 3 to 5 hours.
- Checkpoint to reports/P.1_STATE.md after every step, and resume from it
  after any usage limit or reboot.
- Context wipe at about 300k tokens with nothing running: write a RESUME
  HERE block and "READY FOR WIPE <time>" to STATE, then stop.
- Never cut a check to save usage.

Do not stop to ask, and do not use AskUserQuestion. Decide, log the
choice under Open choices in the return document, and continue.

============================================================
PART 0: START GATES (FIXED HERE)
============================================================

0.1 Start checks, quoted verbatim in the return:
- the CLAUDE.md status command
- `git status --short` and `git log --oneline -3`
- `sha256sum EXPERIMENT.md`, which must equal the Binding value
- `PYTHONPYCACHEPREFIX=$HOME/.cache/news_eval_pyc .venv-eval/bin/python -m news_eval.freeze check`,
  which must print FROZEN: match
- `free -m`
- `gh auth status`, recorded only. gh reads the GNOME keyring, so first
  run `export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.
  Without that export, gh wrongly reports the token as invalid.

0.2 Tools, installed outside the repo and never into .venv:
- git-filter-repo via `uv tool install git-filter-repo`
- gitleaks from its official GitHub release binary into ~/.local/bin,
  with the version recorded

If either install fails, stop and say why.

0.3 Write reports/P.1_STATE.md and the estimate ETA table.

============================================================
PART A: THE ALLOWLIST AND THE SOURCE FOLDER (FIXED HERE)
============================================================

A1. The allowlist, written to public/ALLOWLIST.txt in AiTrader. Owner:
the lead.
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
  - reports/: the B.2, C.1, C.2 and later stage returns, STATE files,
    reviews, rulings, verification folders, the freeze manifest(s),
    c2/gate_log.jsonl and c2/snap_*/snapshot.json
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
  - the five headline-bearing relevance files in their original form:
    c1_relevance_sample.csv, c1_relevance_grader_input.csv,
    c1_relevance_grades_opus.csv, c1_relevance_grades_fable.csv and
    c1_relevance_final.csv. Also c1_relevance_adjudication.md if it
    quotes headlines.

A2. The redacted relevance files. Owner: Redactor-SonnetHigh
(worker-high on sonnet). Write public/reports/<same names>, keeping only
id, symbol, query_date, sector, stratum, the grades and the name source.
Drop every headline and every reason or rationale column. Write a
headline-free adjudication summary. The extraction maps public/reports/
onto reports/ in place of the excluded originals. A test asserts that no
redacted file contains any string from the headline column of its
original.

A3. The headline scan. Owner: the lead, with a script. Scan every text
file in the allowlist, at every commit of the history, for any substring
of 40 or more characters that matches a headline in the original
relevance sample. Record and rule on every hit.
- Short illustrative quotes inside EXPERIMENT.md, such as Amendment 8's
  three example headlines, stay. EXPERIMENT.md is published unchanged and
  its hash binds the experiment. The return lists them.
- Any other bulk headline listing is excluded or redacted.

A4. The extraction script, public/extract.sh. Owner:
ExtractionCoder-OpusXHigh (worker-xhigh on opus). It must:
- clone AiTrader into a temporary directory and never touch the working
  repo
- run git-filter-repo with the allowlist, the exclusions, and path renames
  from public/ to the root (public/README.md to README.md, public/docs/*
  to docs/*, public/reports/* to reports/*)
- apply a mailmap: kiros1134@gmail.com and the
  "kirosli00tuff <kiros1134@gmail.com>" identity both become
  "kirosli00tuff <249804683+kirosli00tuff@users.noreply.github.com>".
  Leave every other author unchanged: the Claude co-author lines and the
  Perplexity-agent commits stay as recorded.
- write the result to ~/Documents/GitHub/llm-news-drift as a local repo
  with no remote

Determinism test: two runs produce identical commit hashes.

The first commit of the extracted history must be dated 2026-07-27 or
later. Report the first and last commit, the commit count, and every
non-Kiros author.

============================================================
PART B: THE PUBLIC DOCUMENTS (FIXED HERE)
============================================================

Owner: the lead drafts all four. DocWriter-OpusXHigh (worker-xhigh on
opus) may draft TIMELINE from the commit log.

Every file goes in AiTrader's public/ folder and is mapped to the root or
to docs/ by the script. Kiros's writing style applies throughout: plain
words, active voice, short sentences, no em dashes, no semicolons, no
hype ("groundbreaking", "revolutionary" and the like), and data over
adjectives. Each statement Kiros must personally confirm is marked
`[KIROS: confirm]`.

B1. public/README.md, about one page, first person, as Kiros:
- the question, in one paragraph
- why it is pre-registered, in one paragraph
- how it works: collector, model call, five states, blindness, harness,
  freeze, independent verification, with one small diagram in text or
  mermaid
- status today, honestly:
  - collecting since 2026-07-28
  - the C.2 gate failed on 2026-10-28 because sigma was 442 bp against
    the 180 bp assumed
  - Amendment 10 reads the verdict at the 120-session hard stop
    (2027-01-15), with the result expected in late January 2027
  - three permanent gaps, and why each happened
  - no result yet, and no claim made
- the repository map
- links to TIMELINE, HOW_TO_VERIFY and AI_USE
No number goes in the README that cannot be traced to a file in the
repo.

B2. public/docs/TIMELINE.md: every dated event from Stage A to today.
That covers the registration, each amendment, each stage with its prompt
and return, the freezes, the gate, the decisions V1 onward, and the
gaps. Each event has its date and the commit hash in the extracted repo
(take the hashes from a first extraction pass, which is deterministic).

B3. public/docs/HOW_TO_VERIFY.md:
- clone the repo
- `git log --follow EXPERIMENT.md` shows the dated amendments
- build the harness environment from news_eval/requirements-eval.lock
  with uv and Python 3.12
- run `python -m news_eval.freeze check`, which should print FROZEN:
  match
- run the synthetic test suite, which needs no data
- what cannot be verified publicly and why: the headline database is
  third-party news and is never published, while its snapshot hash and
  row counts are in reports/c2/

B4. public/docs/AI_USE.md, first person, the full account Kiros asked
for (V6):
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
  returns and rulings, such as the numpy defect C.1 found or the leakage
  findings Fable raised.

B5. A short LICENSE note. Recommend a licence under Decisions for the
user. Do not choose one.

============================================================
PART C: BUILD AND VERIFY IN A FRESH CLONE (FIXED HERE)
============================================================

Owner: the lead, with scripts.

C1. Run public/extract.sh. Then run it again into a second directory and
confirm identical commit hashes.

C2. Clone the result into a new temporary directory. Then:
- build a venv with `uv venv --python 3.12` and
  `uv pip install -r news_eval/requirements-eval.lock`
- `freeze check` must print FROZEN: match on the C.1 manifest
- run every included test, using the full list from A1

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
PART D: REVIEW (FIXED HERE)
============================================================

Two reviewers run in parallel. Each has its model confirmed from its
transcript.

D1. LeakAuditor-FableXHigh (worker-xhigh on fable). Use the extracted
repo and its full history only. Hunt for:
- secrets
- personal data
- third-party data: headline datasets, news text, or any vendor data
  whose terms forbid redistribution
- excluded paths
- anything that could embarrass Kiros publicly

Output: reports/p1_review_leak.md, with each finding marked BLOCKING,
SHOULD FIX or NOTE.

D2. ClaimsReviewer-FableXHigh (worker-xhigh on fable).
- Trace every factual claim in README, TIMELINE, HOW_TO_VERIFY and
  AI_USE to a file or commit in the extracted repo.
- Flag anything overstated, especially any implied result: there is
  none yet.
- Check that AI_USE covers every item in B4 and V6.
- Check that HOW_TO_VERIFY works step by step in a fresh clone.

Output: reports/p1_review_claims.md.

The lead rules on every finding in reports/p1_rulings.md. BLOCKING and
SHOULD FIX findings are fixed, then extraction and Part C rerun before
Part E.

============================================================
PART E: FINAL LOCAL BUILD (FIXED HERE)
============================================================

E1. Commit the public/ folder and this stage's files in AiTrader. That
is the one final commit, below.

E2. Run public/extract.sh into ~/Documents/GitHub/llm-news-drift. Record:
- HEAD hash, commit count, first and last commit dates
- repo size
- freeze check output
- test count
- gitleaks result

Do NOT add a remote and do NOT push.

E3. Write, in section 7 of the return, the exact steps for Kiros:
1. `gh auth login`
2. `gh repo create kirosli00tuff/llm-news-drift --private --source ~/Documents/GitHub/llm-news-drift --push`
3. read README.md and fix each `[KIROS: confirm]` mark in AiTrader
   public/
4. rerun extract.sh
5. `git push`
6. flip the repo public in the GitHub settings

Also write how to refresh the public repo after C.3, the gate reruns and
the readout: rerun extract.sh, then a fast-forward push.

============================================================
SCOPE
============================================================

This stage does NOT:
- open news_experiment.db or any snapshot, or read any outcome
- edit EXPERIMENT.md, news_experiment/, news_eval/, any test,
  backtest/, llm_consensus/, ops/, any report from an earlier stage, or
  any frozen file
- touch the collector, its timer or its units
- add a git remote, push, create a GitHub repo, or change any repo's
  visibility
- change AiTrader's history. The extraction works on a temporary clone.
- publish any database, key, .env, keystore or headline dataset
- run C.3, the gate, or anything in PropExperiment
- install into .venv, call a paid API, or print a key

============================================================
GUARDRAILS
============================================================

- Start and end checks quoted verbatim, as in 0.1. At the end, also run
  `git -C ~/Documents/GitHub/llm-news-drift log --oneline | wc -l` and
  the fresh-clone freeze check output.
- In AiTrader, commits touch only public/, reports/P.1_*, reports/p1_*,
  PROGRESS.md, RETURN.md, the docs/STAGES.md line and the
  docs/prompts/README.md row. Stage them by explicit path. There is one
  named final commit and no push. COLLECTION_LOG.md is never staged.
- Nothing runs between 23:00 and 23:45 America/Vancouver on weekdays.
- At most 1 heavy job. Stop it if free memory falls below 2 GB.
- Before ending, confirm no worker or shell is still running.

============================================================
DELEGATION PLAN
============================================================

| Step | Owner | Model | Effort | Parallel or serial | Why this tier |
|---|---|---|---|---|---|
| Part 0, A1, A3, B1 to B5, C, rulings, E, return | lead | opus | max | serial | public artifact, so the lead keeps claims, inclusion and rulings |
| A2 | Redactor-SonnetHigh | sonnet | high | parallel with A4 | well-specified column removal, checked by a test |
| A4 | ExtractionCoder-OpusXHigh | opus | xhigh | parallel with A2 | history rewriting, silent-failure risk |
| B2 (optional) | DocWriter-OpusXHigh | opus | xhigh | after a first extraction pass | long, factual and checkable |
| D1 | LeakAuditor-FableXHigh | fable | xhigh | parallel with D2 | independent leak hunt on the final history |
| D2 | ClaimsReviewer-FableXHigh | fable | xhigh | parallel with D1 | every public claim traced |

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
docs/prompts/README.md. Then make one final commit, "Stage P.1 public
repo extraction (local)". No push.

The return has these fixed sections:
1. Summary, at most 250 words: what the public repo contains, the
   checks it passed, what Kiros must do before it goes public.
2. Guardrail evidence: start and end checks verbatim, and the order of
   events.
3. Results:
   - the allowlist and the dependency map
   - the redaction table
   - the headline-scan rulings
   - extraction determinism
   - the fresh-clone checks
   - the gitleaks result
   - the repo stats
4. Delegation record, with each reviewer's model confirmed from its
   transcript.
5. Verification: each finding, the ruling and the fix.
6. Open choices.
7. Decisions for the user, each with a recommendation: the E3 steps,
   every `[KIROS: confirm]` mark, the licence, and anything left
   unresolved.
8. Session cost: the final ETA table and per-model token counts from the
   transcripts, never estimated.

The last thing before ending: list every open choice in section 6.

END PROMPT
