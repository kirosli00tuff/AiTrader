# queue

Inbound prompt queue. Chat Claude writes prompt files here. Claude Code executes them.

## How it works

1. Chat Claude writes a numbered prompt file: `NNN-short-name.md`
2. Each file names its model at the top and carries `Status: PENDING`
3. Claude Code reads the lowest-numbered PENDING file and executes it
4. On completion, Claude Code sets `Status: DONE` and moves the file to `queue/done/`
5. Results land in PROGRESS.md and RETURN.md as normal

## Rules

- The queue is OPT-IN, not a standing instruction. Do NOT read this directory at the
  start of a session. Read it only when the operator says so, in words like "run the
  queue" or "read the queue". A pasted prompt is the normal path and costs nothing here.
- When a prompt is pasted directly, ignore this directory entirely. Do not open, scan,
  or list it. If the pasted prompt is recognisably the same work as a file here, mark
  that file DONE and move it to `queue/done/` at the end, and do nothing else with it.
- Files here are prompts and notes only. Chat Claude does not edit code, config,
  or the four tracking files. Claude Code remains the only thing that changes those.
- Execute in numerical order unless a file says otherwise.
- A file whose Status is not PENDING is not picked up.
- Every prompt still logs itself to RETURN.md before work begins, as always.
- If a queue file conflicts with CLAUDE.md, CLAUDE.md wins. Report the conflict rather
  than resolving it silently.
