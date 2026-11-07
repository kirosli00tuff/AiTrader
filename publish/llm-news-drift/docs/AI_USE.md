# How I used AI in this project

## Plain statement

The code in this repository was generated and written with Claude Code,
Anthropic's command-line agent, and its CLI options. The design, the stage
prompts and the reviews came from a planning conversation with Claude on
claude.ai.

Claude Haiku 4.5 has a different role. It is the model under test. It reads
headlines inside the collector, on its own key, and writes no code.

## Roles

| Role | What it does | Models and effort, as used |
|---|---|---|
| Planning chat | Claude on claude.ai, working with me. It designs each stage, recommends decisions, writes each stage prompt and commits it before launch, reviews each return document, and keeps the decision log in [DECISIONS.md](DECISIONS.md). It reaches the laptop through Desktop Commander, a file and shell connector. Stages B.1 to B.3 ran here, with no CLI session. On my written instruction it wrote both unlock files (V3, V8). | The docs name it only as "Claude on claude.ai". |
| CLI lead | One Claude Code session per stage, in this repository. It reads [CLAUDE.md](../CLAUDE.md) and its prompt, splits the work, spawns workers, checks what they return, rules on every reviewer finding and writes the return document. It does not write bulk code itself. | July 2026 (Stage A, the collector build, collection start): single sessions, mostly on Claude Opus 5 (`claude-opus-5`, 1M context). Claude Fable 5 (`claude-fable-5`) ran Amendments 5 to 7, a tick-multiple measurement, an independent audit, the session that scheduled the daily collection from the trading calendar and the commit that closed three cost and usage fallbacks. Efforts were not recorded. From Stage C.1 on: Claude Opus 5.5 (`claude-opus-5-5`), effort xhigh for C.1 and max for C.2, C.3, C.2b and P.1. |
| Workers | Subagents with one objective each. Each gets a brief with exact paths and returns a file plus at most 200 words. Judgments on results and any amendment text stay with the lead. | C.1: ten Opus 5.5 workers, nine at xhigh (HarnessCoder, StatsCoder, GateCoder, FamilyCoder, RunnerCoder, TestDesigner, HarnessFixer, VerdictFixer, RelevanceGrader) and FixtureCoder at high. C.3: HarnessCoder and TestCoder, Opus 5.5 xhigh. C.2 and C.2b: no worker besides the verifier. P.1, as its prompt routes them: Sonnet high (`claude-sonnet-5-5`) for counts, inventories and test runs, Opus xhigh or high for scripts, cards and these documents. |
| Independent reviewers | Workers that did not produce what they check. They recompute from raw inputs with their own code and grade findings BLOCKING, SHOULD FIX or NOTE. | Claude Fable 5.1 (`claude-fable-5-1`), confirmed from the transcripts. C.1: KnownAnswerVerifier and a second relevance grader at xhigh, LeakageAuditor at max. C.2 and C.2b: GateVerifier at xhigh. C.3: DiffReviewer, RunOnceAuditor and FixChecker at xhigh. P.1: LeakAuditor, ArchiveAuditor and ClaimsReviewer at xhigh, on Fable 5.1 as the first lines of each report name it. If Fable is unavailable, Opus in a fresh context stands in, and the return says so. |
| Me | I approve every amendment, every launch and each unlock. | |

The July sessions predate the prompt archive. Their summaries are in
AiTrader's RETURN.md, which is not in this repository. The stage prompts from
2026-09-23 on are in [prompts/](prompts/), which starts at STAGE_C.1.md
(2026-10-10) because B.1 to B.3 ran in the planning chat with no CLI prompt, and each
return document names its lead, workers and reviewers with measured token counts.

The unlock files show the one place the planning chat acted for me. V2 said I
would write the unlock by hand. Twice I gave the instruction in writing
instead, "Write the unlock" on 2026-10-28 and "I unlock it. Run tonight" on
2026-11-05, and the planning chat wrote the file. V3 records the departure
from V2.

## CLI options and setup actually used

- **Launch at the desk.** `claude --dangerously-skip-permissions`, then
  `/model` and `/effort` to match the prompt, then paste the prompt. Every CLI
  session runs in auto or skip-permissions mode, so it runs unattended without
  stopping for approvals ([ORCHESTRATION.md](ORCHESTRATION.md)).
- **`--model` and `--effort`.** The lead runs on `opus` (Opus 5.5) at `xhigh`
  or `max`. Ultracode is not an `--effort` value, so a prompt that wants it
  launches interactively. Every prompt so far says "Ultracode: off".
- **tmux.** A prompt launches only on my go-ahead, in its own tmux session,
  and the planner gives me the attach command. Stage P.1 runs in `stage-p1`.
  AiTrader's docs say only "in tmux". My PropExperiment notes give the form
  `tmux new-session -d -s stage-<name>`, then
  `claude --dangerously-skip-permissions --model opus --effort max` inside it.
- **Headless launch, mobile only.** When I ask, the planning chat starts a
  stage through Desktop Commander with
  `setsid nohup claude -p "$(cat docs/prompts/STAGE_<X.Y>.md)" --model opus --effort xhigh --permission-mode bypassPermissions --name "Stage X.Y title" --output-format stream-json --verbose`,
  logged to reports/<stage>_cli.log.
- **Worker agent files** in .claude/agents/: worker-medium (default model
  haiku, effort medium), worker-high (sonnet, high), worker-xhigh (opus,
  xhigh) and worker-max (fable, max). The file fixes the effort, and the lead
  sets the model on each call. Each spawn is named `<Role>-<Model><Effort>`,
  for example `GateVerifier-FableXHigh`.
- **.claude/settings.json.** At most 4 subagents at once, a spawn depth of 2,
  a cap of 1,000 web searches per session, and the `sonnet` alias pinned to
  `claude-sonnet-5-5`.
- **Usage limits.** The claude-auto-retry monitor resumes a session after a
  usage limit. Its setup is not in this repository. Claude
  Code 2.1.234 and later also continues on its own once a limit resets. The
  planner resumes anything else. C.2b attempt 2 shows that case: its lead
  stopped on the 5-hour limit, the laptop rebooted, and the planner restarted
  the lead the next night with nothing lost.
- **Context wipe.** At about 150k tokens of context, at a quiet point, the
  lead writes a RESUME HERE section of at most 60 lines and the line
  "READY FOR WIPE <time>" to its STATE file. Then one detached
  `tmux send-keys` command sends `/clear` and a resume prompt to its own pane.
  The fresh context reads RESUME HERE and carries on in the same process,
  model and effort. C.3 did this twice without loss. Until 2026-11-05 the rule
  was to stop at about 300k tokens.
- **Resume from STATE.** After every task the lead appends what is done,
  running and next, with artifact paths and times, to
  reports/<stage>_STATE.md. A resumed lead reads it first and skips finished
  work.

## How prompts are structured

Each stage prompt follows a fixed order. [PROMPT_WRITING.md](PROMPT_WRITING.md)
section 8 sets it, taken from my PropExperiment Prompt Structure
(2026-10-28). Part by part:

1. **Header and markers.** `STAGE X.Y "SHORT TITLE"`, then
   `BEGIN PROMPT - SUMMARY OF PROMPT`. The prompt closes with `END PROMPT`.
2. **Summary.** One paragraph: what the last stage left, what this one does,
   why now, and exactly where it stops.
3. **Decisions in force.** The V-entries that apply, then the binding
   documents in priority order, with the sha256 of each frozen one.
4. **Read first.** The files and sections the lead reads before acting, often
   with line ranges.
5. **Lead and why.** `Lead: Opus 5.5, effort <xhigh|max>. Ultracode: <on|off>.`,
   the reviewer and worker routing, and one paragraph naming the silent
   failures that justify the effort.
6. **Usage and time.** When the stage may launch, how long to expect, the
   collector window to avoid, the checkpoints and the exact self-wipe command.
7. **Autonomy line.** "Do not stop to ask, and do not use AskUserQuestion.
   Decide, log the choice under Open choices in the return document, and
   continue."
8. **PART 0 gates.** Seals, freeze checks and start gates. If one fails, the
   stage stops.
9. **Work parts.** PART A onward, each marked FIXED HERE, with owner, inputs,
   outputs and when it is done.
10. **SCOPE.** "This stage does NOT:", one line per forbidden action.
11. **Guardrails.** The CLAUDE.md invariants plus the stage's own.
12. **Delegation plan.** Which worker does what, on which model and effort.
13. **Deliverable.** One return document in eight sections, then the last
    instruction and `END PROMPT`.

A real excerpt, the SCOPE part of [prompts/STAGE_C.3.md](prompts/STAGE_C.3.md)
(lines 237 to 248):

```
This stage does NOT:
- read any outcome, judgment, strength or reason value, or any
  scoring_session value, from news_experiment.db. The only database reads
  are the CLAUDE.md status counts and the 0.2 trading_calendar query.
- take a snapshot, run the gate or `run_c2` on real data, or create,
  edit or delete reports/c2_UNLOCK.json, reports/c2_RUN_ONCE.json or
  anything under reports/c2/
- edit EXPERIMENT.md (locked by 10.3), news_experiment/, backtest/, the
  collector units, COLLECTION_LOG.md, reports/c1_harness_freeze.json or
  any C.1 or C.2 report
- change any bar, test, seed, null, floor, verdict row or mapping
  definition, or anything outside 10.1, 10.2 and A5
```

## Organization

- **Lettered stages** ([STAGES.md](STAGES.md)). A is the pre-registration, B
  the collection and C the evaluation, with numbered sub-sessions such as
  C.1. D, paper trading, starts only on a green C, and E, live trading, only
  on a passed D. P.1, the stage that built this repository, sits outside
  that plan.
- **Prompts committed before launch.** From 2026-09-23 each prompt goes into
  docs/prompts/ before it is sent, so any session can be checked against its
  instructions.
- **V-numbered decisions.** The planning chat records each of my decisions in
  docs/DECISIONS.md as V1, V2 and onward, in the same commit as the prompt
  that relies on it.
- **STATE checkpoints.** reports/<stage>_STATE.md, after every task.
- **Eight-section return documents.** 1 summary in at most 200 words, 2
  guardrail evidence, 3 results per task, 4 delegation record, 5
  verification, 6 open choices, 7 decisions for me, 8 session cost in
  measured tokens.
- **sha256 freeze manifests.** reports/c1_harness_freeze.json from C.1 and
  reports/c3_harness_freeze.json from C.3, written and checked by
  news_eval/freeze.py.
- **Independent Fable verification.** Every number that enters a verdict gets
  an independent Fable xhigh check by a worker that did not produce it,
  recomputed from raw inputs.
- **Written rulings.** The lead rules on every reviewer finding in writing,
  with a fix or a reason: reports/c1_rulings.md, c2_rulings.md and
  c3_rulings.md.

## The markdown files

- [EXPERIMENT.md](../EXPERIMENT.md): the pre-registration, binding since
  2026-07-28, with Amendments 1 to 10.
- [CLAUDE.md](../CLAUDE.md): the rules every Claude Code session here reads
  first, covering invariants, roles, model routing, checkpoints, compute
  limits and context hygiene. Its later sections describe the AiTrader
  trading engine, which is not in this repository.
- [ORCHESTRATION.md](ORCHESTRATION.md): the reasons for the setup, the prompt
  skeleton, the launch procedure and the thresholds that would change it.
- [PROMPT_WRITING.md](PROMPT_WRITING.md): the planning chat's own rulebook for
  writing prompts, including the return-document format.
- [STAGES.md](STAGES.md): the stage plan, with one line per session.
  EXPERIMENT.md is the contract and this file is the index.
- [DECISIONS.md](DECISIONS.md): the locked decisions and the V-numbered
  decisions.
- [prompts/](prompts/): every stage prompt from 2026-09-23 on, exactly as
  sent, with an index. The first is STAGE_C.1.md (2026-10-10).
- reports/*_RETURN.md: one self-contained return document per session. The
  planning chat reviews a session by reading that one file.
- reports/*_STATE.md: the per-task checkpoints a resumed lead reads first.
- [COLLECTION_LOG.md](../COLLECTION_LOG.md): one entry per collector run,
  appended by the collector. No session edits it.
- .claude/agents/*.md: the four worker definitions.

## My review

In my words: "I personally review every line of code written afterwards."

## Other agents in the history

- No Perplexity commit is in this history. AiTrader has 12 commits by
  Perplexity agents ("Market AI Lab Agent" and "Perplexity Computer"), dated
  2026-06-29 to 2026-06-30. They predate Stage A, and this history starts at
  Stage A, so none survive the extraction.
- Three commits here have Claude as their git author instead of me:

  | Commit | AiTrader | Date | What it did | Files |
  |---|---|---|---|---|
  | `cfe7228` | `8a3bc4b` | 2026-07-29 | Amendment 6, the within-day permutation null | EXPERIMENT.md |
  | `7e62dca` | `d1769c3` | 2026-07-29 | Closed three latent cost and usage fallbacks | CLAUDE.md, backtest/fees.py, news_experiment/collect.py, outcomes.py, scoring.py, spec.py |
  | `be028b6` | `c173b53` | 2026-07-29 | Amendment 7, stale Level 1 figures and the collection start preconditions | EXPERIMENT.md |

- Many other commits carry Co-Authored-By trailers naming Claude Opus 5.5,
  Claude Opus 5 (1M context) or Claude Fable 5.
  `git log --format='%h %(trailers:key=Co-Authored-By,valueonly)'` lists them.

## What the AI got wrong, and how it was caught

- **A request bug reported as a bug.** In the July feasibility work the
  session sent `temperature` to Claude Opus 4.8, which rejects it. Every Opus
  call returned HTTP 400. The session titled its result "INCONCLUSIVE, and one
  reason is my own error" and wrote that Opus 4.8 was never tested
  (EXPERIMENT.md, Stage 1 Task 6).
- **A broken numpy.** The first C.1 tests ran under the repository's .venv
  (Python 3.14, numpy 1.26.4), which silently miscomputed large-array
  arithmetic. RunnerCoder, an Opus 5.5 worker, found it. The harness moved to
  .venv-eval (Python 3.12.13, numpy 2.5.3), the manifest pins those versions,
  and news_eval/envcheck.py refuses to compute under a bad build
  (reports/C.1_RETURN.md).
- **Leaks in the first harness.** LeakageAuditor (Fable, max) raised 3
  BLOCKING findings in code the Opus workers wrote. A planted `-wal` file
  beside the read-only snapshot changed the gate's counts under an unchanged
  hash. The unlock file and the run-once marker were checked for existence
  only, so `--unlock README.md` let a real snapshot into the gate. `--real-db`
  replaced the compiled live database path. All three were fixed and
  re-checked before the freeze (reports/C.1_RETURN.md section 5).
- **The planner's own start gate.** The C.3 prompt required `FROZEN: match`
  on the C.1 manifest. Amendment 10 had already changed EXPERIMENT.md, so that
  could not pass. The C.3 start checks showed the conflict before any code
  changed, and three minutes later the planner ruled that only the two
  EXPERIMENT.md differences were allowed. V7 records it as a planner defect
  (reports/C.3_RETURN.md section 2).
- **Tests that broke quietly.** C.1 tests hard-coded EXPERIMENT.md line
  numbers, so they had failed since the Amendment 10 commit, and nobody saw it
  until the C.3 lead ran the suite. Guards in three test files assert that
  reports/c2/ does not exist, so 157 tests error at teardown in any tree that
  holds the C.2 records, this repository included. Suite decisions use a clone
  without those paths ([HOW_TO_VERIFY.md](HOW_TO_VERIFY.md)).
- **A run-once hole.** RunOnceAuditor (Fable, xhigh) found that the hard-stop
  checks held only inside the gate log named on the command line, which the
  caller chooses. It was fixed in code: under `--hard-stop`, outside test
  mode, the runner refuses any other log (reports/C.3_RETURN.md).
- **A claim with no tool behind it.** During Stage P.1 a worker reported its
  scripts "shellcheck clean". shellcheck is not installed on the laptop. The
  lead withdrew the claim, and the scripts were checked with `bash -n` only
  (AiTrader reports/p1_rulings.md, R7).
