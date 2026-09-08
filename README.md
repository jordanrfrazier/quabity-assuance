# qabot

A local CLI for reviewing application setup and recording QA journeys in Chrome.
It reads repository evidence and a change description, proposes an editable plan,
requires approval, then starts the application and records browser evidence.
The earlier CI, demo, and anonymous-scan prototypes remain available below.

## Reviewed Browser Journeys

Workspace: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli`, branch `feature/qabot-journeys-cli`.

Keep linked worktrees under the primary project's `.worktrees/` directory.
The former direct `/private/tmp/` CLI and combined Langflow worktrees were moved
there without discarding local changes. Historical evidence retains its original
paths; existing plans and approvals must be reviewed before reuse after relocation.
Requires macOS, installed Google Chrome, `uv`, and an authenticated `claude` CLI.
Journey commands use real Claude/Sonnet calls, not the legacy offline provider.

```sh
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv sync --extra dev --extra browser
uv run qabot journeys --help

uv run qabot journeys plan --repo /absolute/application/path --base BASE --head HEAD \
  --description /absolute/change-description.md --out /absolute/new-plan.json
uv run qabot journeys approve /absolute/new-plan.json --reviewer "Your name"
uv run qabot journeys run /absolute/new-plan.json --headed --channel chrome
```

Review the proposed command, environment, prerequisites, actions, and expected
observations before approving. Generated plans are not trusted test results. Put
credential references such as `${API_KEY}` in the plan, never values. An optional
`--env-file /absolute/private/.env` on `run` loads only required names; explicit
plan flags still win. Login actions must name their credential references.
Run preflight rejects nonempty literal values in recognized credential-named
environment entries and URLs with embedded credentials, before creating reports.
Use a complete `${NAME}` reference, not a reference mixed with a literal secret.
References resolve from the supplied host/dotenv environment before plan overrides;
their values remain redacted even when a source variable is later cleared.
Discovery preserves aliases and ordinary configuration, and rejects health URLs
with embedded credentials instead of producing an unusable URL reference.

The macOS pilot requires `lsof` on `PATH` to verify local listener ownership.
The target port must be free before setup and startup. Keep the reviewed app in
the foreground; daemonized or detached listeners cannot establish owned readiness.
Required setting strings must match exactly, including case and whitespace.

Each new run writes `report.html`, `report.md`, `results.json`, startup logs,
screenshots, and per-journey WebM video. Open the HTML directly in Chrome.
Executed setup commands retain redacted stdout/stderr in `setup-01.log`, etc.;
journey resets use `journey-01-reset.log`, etc. Failure diagnostics name the log.
Browser cleanup or missing required video can block a journey, but completed
steps and findings remain in the report with the cleanup diagnostic.
The default destination is a unique directory beneath the primary Git workspace's
`v1/reports/`, including when invoked from a linked worktree. Outside Git, the
invocation directory is used as the root. An explicit `--out` selects another new
directory. Reports use relative media links and include measured phase timing,
model call counts, and approximate video chapter links when timing is available.
Exit codes are `0` for all PASS, `1` for any FAIL, and `2` for BLOCKED without FAIL
or an invalid command/approval; Ctrl-C retains partial evidence and exits `130`.
A correctly observed expected rejection can PASS. A failed browser action blocks
the step before further model judgment; it cannot be retried into a PASS.
Changed plans, referenced scripts, target repositories, or resolved base/head
commits require renewed approval. Moving `HEAD` or a branch invalidates approval
even when the plan text is unchanged. Older approvals without Git bindings must
be reviewed again. An unchanged approved target and plan can be rerun to a fresh
output directory without another approval prompt.

Manual walkthrough: [examples/WALKTHROUGH.md](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/WALKTHROUGH.md).
Product requirements: [docs/PRD.md](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/docs/PRD.md).
This is a local pilot, not a production-release certification.

Design: `docs/superpowers/specs/2026-08-27-qa-bot-design.md`
Decisions and their rationale: `docs/DECISIONS.md`
Market position and competitive evidence: `docs/STRATEGY.md`

## Run it

    uv sync --extra dev --extra browser
    uv run playwright install chromium

    uv run pytest
    uv run pytest -m "not browser"           # skip the Chromium tier
    uv run qabot demo --source-root .        # the pipeline over HTTP
    uv run qabot demo-browser --source-root . --headed   # ...and through a real browser

`demo` stands the entire loop up in-process against `demo/app.py`, a small shop carrying
two deliberate, commented defects. The bot should report exactly one BUG (an expired card
is refused with a generic message) and two CHANGEs (the cart is cleared on that failure
path), block on one prose-only expectation it cannot check offline, and generate a
regression test for the workflow it did verify.

`demo-browser` drives the same defects through a real Chromium against a real server,
reaching the same verdicts by a different route, and adds a third: the cart's remove
button is an icon with no accessible name, so that workflow reports BLOCKED naming the
control. Screenshots land in `qa-artifacts/`. Add `--headed` to watch it work.

## The two rules everything else serves

**Provenance caps severity.** A violated expectation is reported at most as loudly as its
source allows: `human_confirmed` → BUG, `observed_in_run` → REGRESSION,
`inferred_from_test` → CHANGE, `inferred_from_code` → QUESTION only. A model decides
whether an expectation held; the data structure decides how much that is allowed to mean.

**PASS, FAIL, BLOCKED — never blurred.** BLOCKED means "I could not test this". It is not a
pass, not a failure, and never silence.

A third rule earns its place in the browser driver: **locators are a role and an accessible
name, never CSS or XPath.** That keeps the knowledge base valid across restyles, and it
means an unlabeled control is unreachable — so the bot reports BLOCKED and has, in passing,
found an accessibility bug.

## Offline by default

The default LLM provider is deterministic and needs no API key, so the suite and the demo
are fully reproducible. The real providers are explicit opt-in — `QABOT_LLM=anthropic` over
the SDK, or `QABOT_LLM=claude-cli` through a locally installed `claude` — and each raises
when what it needs is missing: a key for the first, the binary on PATH for the second. The
network is never a silent fallback.

## Two products

`seed`, `run` and `demo` are one product, a merge gate. It needs a knowledge base seeded
from an existing e2e suite and a diff to reason about, and it reports by passing or
failing a CI build. It is for a team that already has tests and wants to know which of
them a pull request put at risk.

`scan` is a different product for a different buyer: someone who built an app — often
with an AI — and has no test suite, no fixtures, and no CI to gate. It takes nothing but
a URL, crawls what it can reach anonymously, and writes a report to a file. It never
fails a build (`qabot scan` always exits 0); the report is the deliverable, not a
pass/fail signal.

    uv run qabot scan https://example.com

Flags: `--out` (default `qabot-scan-report.html`) is where the report is written,
`--max-pages` (default `25`) caps the crawl, `--delay` (default `1.0`) is the seconds
between page loads, and `--artifacts` (default `qa-artifacts`) is where screenshots land.

The two products share a repository for one reason: the intrinsic oracles — crashes,
console errors, failed requests, 5xxs — are the same code in both, and they are the half
of this codebase the evaluation vindicated. The merge gate drives an app over HTTP and
the scan drives it in a real browser, but both grade what comes back with
`qabot/intrinsics.py`.
