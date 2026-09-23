# Orchestration and model tiering

Adopted 2026-09-23, ported from PropExperiment (adopted there 2026-09-21,
revised 2026-09-22). CLAUDE.md holds the operating rules. This file holds
the reasoning, the stage-prompt skeleton, the launch procedure and the
thresholds that would change the setup. docs/PROMPT_WRITING.md holds the
full rules the planning chat follows when it writes a prompt.

## The setup

- Lead session on Opus 5.5 (the `opus` alias). The lead plans, routes,
  verifies and synthesizes. It does not write bulk code, parse logs or run
  long jobs itself.
- Workers on haiku, sonnet, opus or fable, at effort medium, high, xhigh or
  max, chosen per subtask by the lead. Low effort is not used.
- Haiku does pure extraction only. Sonnet does complex extraction and
  mechanical work. Extraction quality does not depend much on model tier,
  while drawing conclusions from extracted data does, so every interpretive
  step goes to a higher tier.
- Four generic agent files (.claude/agents/worker-medium, worker-high,
  worker-xhigh, worker-max) pin the effort. The lead passes the model on
  each Agent call. The Agent tool takes a per-call `model` but no per-call
  `effort`, which is why effort lives in the files. Dynamic workflows take
  both per agent: `agent(prompt, { model, effort })`.
- .claude/settings.json caps concurrency at 4 subagents and spawn depth
  at 2.

## Why

- Opus 5.5 matches or beats Fable 5.1 on most benchmarks (Terminal-Bench
  4.0 66.4% vs 55.8%, GDPval-AA 1,846 vs 1,735, OSWorld 2.0 81.8% vs 80.7%,
  HLE 67.7% vs 65.6%) at lower cost, so Opus leads and does all high-level
  work. Figures as recorded in PropExperiment on 2026-09-22.
- Fable is kept for independent and adversarial verification. A check by a
  different model than the author catches errors two Opus passes would
  share. Fable has its own weekly cap (50% of the plan's weekly usage), so
  nothing else routes to it. Revisit when a new Fable model ships.
- Multi-agent work pays off on parallel, independent items (per-stratum
  audits, per-family checks, per-finding verification). It does not pay
  off on tightly coupled single judgments. The Stage C verdict synthesis
  is one of those, so it stays with the lead.
- Route by silent-failure risk. This repo has recorded seven fabrications,
  every one a plausible output built from absent input. A cheap model on a
  judgment produces output that looks right and is wrong. Sonnet gets only
  work whose correctness is checkable by inspection or by a test.

## What the PropExperiment D.1d blowout showed

The first D.1d run there spent about 744k tokens in 7 minutes across 6
parallel agents and hit the weekly limit. That was a fan-out problem more
than a model-tier problem: every subagent pays roughly 25k to 35k tokens of
setup, re-reads its own inputs, and draws from the same shared pool at the
same time. The fixes, in order of effect: the concurrency cap, doing small
tasks inline, passing file paths instead of long summaries, and only then
cheaper tiers.

## Usage notes

- The lead is Opus. Fable workers draw on Fable's own weekly slice, which
  PropExperiment also uses. Keep Fable spawns to verdict-number checks and
  the one hinge review per stage.
- Ultracode is available on Opus. Use it only when a stage has real
  parallel fan-out. Ultracode is not an --effort value, so a prompt that
  wants it is launched interactively.
- Check /usage mid-session. If a stage in PropExperiment is running at the
  same time, both draw from the same weekly pool.
- If a sonnet worker fails verification more than occasionally on a class
  of task, move that class to opus in CLAUDE.md's routing table.
- Keep CLAUDE.md stable. A stable prompt prefix keeps cache reads cheap for
  a long-running lead.
- Claude Code 2.1.234 and later continues automatically after a usage limit
  resets. Check it is on in /config.

## Stage-prompt skeleton

Every stage prompt follows this shape. docs/PROMPT_WRITING.md gives the
rules for each section.

    STAGE X.Y "SHORT TITLE"

    BEGIN PROMPT - SUMMARY OF PROMPT

    Summary: one paragraph. What this session does, why now, and where it
    stops.

    Lead: Opus 5.5, effort <xhigh|max>. Ultracode: <on|off>.
    Why this lead and effort: one paragraph.
    Usage: which Fable spawns, and why only those.

    SCOPE                does, and does NOT
    CONTEXT TO READ FIRST numbered, with section names
    GUARDRAILS           CLAUDE.md invariants plus stage-specific ones
    TASK 1..n            owner, inputs, output artifact, done-when
    DELEGATION PLAN      table plus the standard block
    VERIFICATION         what Fable checks, at which effort
    WHAT NOT TO DO
    DELIVERABLE          one return document plus index lines
    OPEN CHOICES         every call the lead made on its own

    END PROMPT

Standard delegation block, pasted into every prompt:

    DELEGATION PLAN (the lead executes this; it does not do worker tasks)
    1. Decompose each task into subtasks with one objective, inputs, output
       path and format, allowed tools, and boundaries.
    2. Route per CLAUDE.md. State model and effort for each subtask before
       spawning. Name each spawn <Role>-<Model><Effort>.
    3. At most 4 concurrent. Small tasks needing no isolation go inline.
    4. Collect results as files plus short summaries.
    5. Verify every number entering a verdict with an independent fable
       xhigh worker.
    6. Synthesize in the lead against this prompt, and write the synthesis
       to disk before ending.
    7. Unattended run: no pauses to ask. Checkpoint to
       reports/<stage>_STATE.md after each task.

## Launching a stage

The order is fixed:

1. The planning chat writes the prompt to docs/prompts/STAGE_<X.Y>.md,
   updates the index, commits, and sends the same text to the user in
   chat as one copy-paste block.
2. The user reviews it. Nothing launches without the user's go-ahead.
3. At the desk, the user opens the CLI session in the repo so they can
   watch it: `claude --dangerously-skip-permissions`, then /model and
   /effort to match the prompt, then paste. Every CLI session runs in auto
   or skip-permissions mode.
4. On mobile, and only when the user asks, the planning chat launches it
   headless through Desktop Commander and logs to reports/<stage>_cli.log:

       cd ~/Documents/GitHub/AiTrader && \
       setsid nohup claude -p "$(cat docs/prompts/STAGE_<X.Y>.md)" \
         --model opus --effort xhigh --permission-mode bypassPermissions \
         --name "Stage X.Y title" --output-format stream-json --verbose \
         > reports/<stage>_cli.log 2>&1 < /dev/null &

   The session shows up in `claude agents` and the /resume picker, so the
   user opens it with `claude --resume <id>`.
5. Never launch a stage into the collector window (about 15:30 to 16:30 PT
   on weekdays), and never run two heavy sessions at once. Check
   `ps -eo pid,etime,args | grep claude` first: a PropExperiment session
   running at the same time shares the 14 GB of RAM and the usage pool.

The laptop must stay awake: no auto-suspend, lid close set to ignore
(/etc/systemd/logind.conf.d/lid.conf).

## Returns

A stage session ends by writing one self-contained return document,
reports/<STAGE>_RETURN.md, in the structure docs/PROMPT_WRITING.md gives.
The planning chat reviews the session by reading that one file through
Desktop Commander. PROGRESS.md and RETURN.md each get a short dated entry
pointing to it, so the older tracking files stay continuous without
duplicating the content.
