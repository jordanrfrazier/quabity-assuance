# User Journeys — design (2026-09-05)

## What this is

Given a code change on a product we can run, write the **user journeys** that change
affects — numbered plain-language steps a human tester could follow, each with what they
should see — then walk those journeys in a real browser and report, per journey,
PASS / FAIL / BLOCKED with evidence a human can check.

The journey is the product. It is readable before it is executed, and it is verifiable
after: every step names what a person would do and what they would see, so a maintainer
can repeat it by hand, disagree with it, or hand it to someone else.

## Why now

EVAL.md (2026-08-29) established that the CI product can map a diff to routes and execute
*given* steps in a browser, and that seeding journeys from an app's own pytest suite
produces expectations coupled to that suite's fixtures. It never had a way to *author*
journeys from a change, and its planner sees only a step's intent, never the page, so it
cannot walk an unfamiliar UI. This spike builds the two missing pieces and measures them
on one real change whose owner can grade the result.

## Scope: a spike, not product code

- Lives in `spikes/journeys/` in this repository. Imports `qabot.drivers.browser`,
  `qabot.intrinsics`, `qabot.impact`, `qabot.llm`; modifies none of them.
- Tracked in git so it survives the session; the user decides when and what to commit.
- Product code (`qabot/`) is untouched until the measurement below says what to keep.

## The one measurement it exists for

Target: Langflow, branch `release-1.12.1`, PR #14913 (merge `84a3649`), a fix for
"lazy component loading wipes the built-in registry, so with
`LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false` every flow is rejected."

Two local instances from one checkout: **fixed** at `84a3649` and **broken** at
`84a3649^` (a worktree). Same diff drives the journeys for both.

| question | how it is answered |
|---|---|
| Are the journeys sensible? | Jordan reads them. They are the deliverable a human grades first. |
| Did the author *understand* the change? | The journeys must name the precondition the diff implies (the two settings) and the user-visible behaviour it protects (a starter flow builds and runs). Scored by inspection. |
| Can the walker walk them? | Steps completed / steps attempted on the fixed instance. |
| Does it catch the regression? | On the broken instance, the run-flow journey must FAIL with the app's own error surfaced. |
| Does it stay quiet when nothing is wrong? | On the fixed instance, every FAIL is a false positive, adjudicated from screenshots. |

## Components

### `evidence.py` — what changed, in terms the author can use
Input: repo path, base ref, head ref, optional PR title/body text.
Output (`Evidence`, a pydantic model):
- `diff`: the unified diff text (capped at 60 KB; the cap is recorded).
- `changed_files`, `changed_symbols` (via `qabot.impact.parse_unified_diff` and
  `changed_symbols` for Python files).
- `settings_names`: every `LANGFLOW_[A-Z_]+` and `settings.<name>` token in the diff.
- `description`: PR title + body, if given.
- `related_specs`: up to 5 Playwright spec files (`**/*.spec.ts`) whose text shares the most
  identifier tokens with `changed_symbols`, each truncated to 4 KB. Product knowledge in the
  product's own words.

### `author.py` — journeys from evidence
`author(evidence, llm) -> list[Journey]`. One model call. Journey schema:

```
Journey:
  id: str                     # j1, j2, ...
  title: str                  # "A first-time user runs the Basic Prompting starter"
  persona: str                # who is doing this and why
  preconditions:
    settings: dict[str, str]  # env / settings the journey depends on, from the diff
    state: list[str]          # "at least one starter project exists"
  steps: list[Step]
  provenance: "inferred_from_diff"   # fixed; this is inference and is capped as such
Step:
  do: str                     # one action a person could perform, present tense
  see: str                    # what they should observe if the product is right
```

Rules the prompt enforces: 3–8 journeys; every journey traceable to a line of the diff or the
description (the model must cite which); the *happy path* the change protects is always
journey 1; at least one journey exercises the condition under which the change matters.
The output is validated; a journey missing `see` on any step is rejected and re-asked once.

### `walker.py` — walking a journey in the page
`walk(journey, driver, page, llm, artifacts) -> JourneyResult`.

Per step, the model receives: the step's `do` and `see`, the current URL, the trimmed
accessibility snapshot of the page (`page.locator("body").aria_snapshot()`, capped at
12 KB, interactive roles first), and the last three actions taken. It returns exactly one of:
- an action: `{"op": "goto"|"click"|"fill"|"select"|"read", "role": ..., "name": ..., "value": ...}`
  in the driver's own vocabulary (`qabot.drivers.browser.OPS`);
- `{"op": "done"}` — the step's `do` is complete and `see` is on screen;
- `{"op": "blocked", "reason": ...}` — it cannot find a way to do this step.

A step gets at most 6 actions before it is BLOCKED ("could not complete in 6 actions").
Every action goes through `BrowserDriver.execute`, so console, network and screenshots are
captured as they are for every other qabot run. After each action the intrinsic oracles run
on the observation, and two visitor-experience checks run on the page text: the app's own
error screen, and a white screen.

When the model says `done`, the step's `see` is judged: the model is given `see` and the
current snapshot + visible text and answers `held` / `failed` / `unclear` with a one-line
reason. `failed` marks the step and the journey FAIL; `unclear` marks the step BLOCKED.

Severity discipline, copied from the product: a `see` judged `failed` is an **inferred**
finding and is reported at QUESTION severity, never BUG. A 5xx, an uncaught error, or the
app's own error screen is app-declared and is reported at BUG. The report keeps the two
apart, with the same words the product uses.

### `report.py` — the human-readable deliverable
Markdown. For each journey: title, persona, preconditions, then the steps as a numbered
list, each with `do`, `see`, a mark (✓ held · ✗ failed · – blocked · ○ not reached), the
screenshot path after the step, and the app-declared findings met during it. Then the
journey's outcome and, if FAIL or BLOCKED, the sentence that says why. A summary table at
the top: journey → outcome. A "what this run could not check" section listing every
BLOCKED step with its reason.

### `run.py` — the command
```
uv run python -m spikes.journeys.run \
  --repo /path/to/langflow --base 84a3649^ --head 84a3649 \
  --pr-text pr.md --url http://127.0.0.1:7860 --out runs/journeys/fixed
```
Writes `journeys.json` (authored), `results.json`, `report.md`, screenshots. `--journeys
journeys.json` reuses authored journeys so the fixed and broken instances walk the same
steps. `--author-only` stops after authoring, so Jordan can read the journeys before any
browser opens.

## Constraints
- LLM through `qabot.llm.ClaudeCliLLM` (the machine has a logged-in CLI and no key). One
  process per call; a journey of six steps costs on the order of a minute. Fine for a spike.
- Local instances only. Nothing here touches a site we do not run.
- Snapshot cap 12 KB; diff cap 60 KB; both caps recorded in the output so a truncated input
  is never mistaken for a complete one.
- No product-code changes. No commits without Jordan's say-so.

## Non-goals
Regression-test emission, authentication flows, running journeys in parallel, anything
that touches the product's planner or verifier.
