# OLD — archived, unreferenced files (2026-07-27)

Files here were moved out of the working tree because **nothing in the
repository references them**. They are kept rather than deleted so the decision
is reversible and the history stays readable.

## The rule that was applied

A file moved here had to survive all of these, checked per file with a
whole-tree grep for its exact basename plus, for Python, its import forms
(`import X`, `from X import`, `python -m ...X`):

- no import and no include,
- no config key naming it,
- no script or launcher invoking it,
- no test referencing it,
- no documentation instruction to run it.

**A file that merely looks old was not enough.** The 2026-07-27 audit found
several subsystems that looked like excess and were load-bearing, so anything
that could not be PROVEN unreferenced stayed where it was and is listed in the
uncertain section of the RETURN.md entry for this session instead.

Nothing under `.run`, no database, no tracking file (CLAUDE.md, PROGRESS.md,
CONTEXT.md, RETURN.md), no active config, and no test was moved.

## What was moved, and the evidence

| file | from | references found | why it is dead |
|---|---|---|---|
| `web_desktop.py` | repo root | **0** | An earlier pywebview desktop launcher carrying a hardcoded absolute path (`/home/kiros-li/Documents/GitHub/AiTrader`). Superseded by `ui/desktop.py`, which is what `ops/run_desktop.sh:42` execs and what `ui/MarketAILab.spec:5` packages. Was untracked, so moving it into `OLD/` puts it under version control for the first time. |
| `check.sh` | repo root | **0** | An ad-hoc operator diagnostic (`ps`, `sudo ss`, fd counts) with hardcoded `$HOME` paths. Superseded by `ops/watchdog.py`, the `/health/integrations` endpoint, and the GUI diagnostics view, all of which are wired and tested. Was untracked. |
| `news_ingestion/fetchers.py` | `news_ingestion/` | **0** | The Python half of the news mock. Its own docstring pairs it with `news_ingestion/news_ingestion.cpp`, removed this session as a fabricated input, and it still carried an unfulfilled `TODO: wire real providers`. Every fetcher was a deterministic mock. Its C++ half is gone, so it has no counterpart left. |
| `REDESIGN_BRIEF.md` | repo root | **0** | A completed one-off brief for redesigning the Plotly Dash UI (`e09c12c`). The work it specified was done and then superseded by the React GUI rebuild. It is a finished work order, not a tracking document. |

`news_ingestion/` no longer exists: both C++ files were removed in the same
session and `fetchers.py` was its last remaining member.

## Verification after the moves

Rebuilt clean with no warnings, **ctest 33 of 33**, **pytest 1,108 passed**, and
the engine starts and completes a paper loop writing bars, events and entry
decisions. Every service module (`api_server`, `ops`, `ui`, `discovery`,
`adaptive`, `llm_consensus`, `ml_factor`, `rl_advisory`) imports clean.

## Restoring one

```bash
git mv OLD/<path> <original path>
```

Nothing was rewritten on the way in, so a restore is a move back and nothing
else.
