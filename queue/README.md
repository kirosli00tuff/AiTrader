# queue

Inbound prompt queue. Chat Claude writes prompt files here. Claude Code executes them.

## How it works

1. Chat Claude writes a numbered prompt file: `NNN-short-name.md`
2. Each file names its model at the top and carries `Status: PENDING`
3. Claude Code reads the lowest-numbered PENDING file and executes it
4. On completion, Claude Code sets `Status: DONE` and moves the file to `queue/done/`
5. Results land in PROGRESS.md and RETURN.md as normal

## Rules

- Files here are prompts and notes only. Chat Claude does not edit code, config,
  or the four tracking files. Claude Code remains the only thing that changes those.
- Execute in numerical order unless a file says otherwise.
- A file whose Status is not PENDING is not picked up.
- Every prompt still logs itself to RETURN.md before work begins, as always.
