# qabot

A local CLI for reviewing application setup and recording QA journeys in Chrome.
It reads repository evidence and a change description, proposes an editable plan,
requires approval, starts the application with reviewed local commands, records
browser evidence, supports reruns, and can package completed evidence for local
offline review. The earlier demo and scan prototypes remain available below, but
the reviewed journey workflow is the main product path.

## Reviewed Browser Journeys

Requires macOS, installed Google Chrome, `uv`, and an authenticated `claude` CLI.
Journey planning, browser acting, and judging use real Claude/Sonnet calls through
the local CLI; they are not the legacy deterministic demo provider. Run from the
qabot repository root.

```sh
git clone https://github.com/jordanrfrazier/quabity-assuance.git qabot
cd qabot

export TARGET_REPO=/path/to/application-repo
export BASE_REF=main
export HEAD_REF=my-change
export CHANGE_DESCRIPTION=/path/to/change-description.md
export REVIEWER_NAME="Your name"
export PLAN_PATH=v1/reports/manual-first-use-01/plan.json
export RUN_DIR=v1/reports/manual-first-use-01/run-01

uv sync --extra dev --extra browser
uv run qabot journeys doctor --repo "$TARGET_REPO"
uv run qabot journeys --help

uv run qabot journeys plan --repo "$TARGET_REPO" --base "$BASE_REF" --head "$HEAD_REF" \
  --description "$CHANGE_DESCRIPTION" --out "$PLAN_PATH"

# Edit the JSON before approval: commands, settings, credentials, state, actions,
# and expected observations are proposed evidence, not trusted results.
uv run qabot journeys approve "$PLAN_PATH" --reviewer "$REVIEWER_NAME"

uv run qabot journeys run "$PLAN_PATH" --out "$RUN_DIR" --headed --channel chrome

uv run qabot journeys run "$PLAN_PATH" --out "${RUN_DIR}-rerun" --headed --channel chrome
```

Review the proposed command, environment, prerequisites, actions, and expected
observations before approving. Generated plans are not trusted test results. Put
credential references such as `${API_KEY}` in the plan, never values. An optional
`--env-file "$PRIVATE_ENV_FILE"` on `run` loads only required names; omit it when
the approved plan has no credential references. Explicit plan flags still win.
Login actions must name their credential references.
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
Any nonempty `preconditions.state` list blocks the journey in V1 before browser
actions or model calls. A startup or reset command alone does not satisfy arbitrary
prose state. Keep the requirement, or explicitly review its replacement with
verifiable fixture checks and browser observations; never remove a prerequisite
only to obtain PASS.

Each new run writes `report.html`, `report.md`, `results.json`, startup logs,
screenshots, and per-journey WebM video. Open the HTML directly in Chrome.
Executed setup commands retain redacted stdout/stderr in `setup-01.log`, etc.;
journey resets use `journey-01-reset.log`, etc. Failure diagnostics name the log.
Step screenshots link to the final observed state used for judgment; action
records keep their own per-action screenshots. If qabot cannot capture that final
judged-state screenshot, the step is BLOCKED with a capture diagnostic.
Application/browser cleanup or missing required video can block a journey, but
completed steps and findings remain in the report with the cleanup diagnostic.
Application cleanup and log-finalization errors retain final report metadata;
they block otherwise passing results without replacing an existing FAIL.
The default destination is a unique directory beneath the primary Git workspace's
`v1/reports/`, including when invoked from a linked worktree. Outside Git, the
invocation directory is used as the root. An explicit `--out` selects another new
directory. Reports use relative media links and include measured phase timing,
model call counts, and approximate video chapter links when timing is available.

Package a completed run for offline review with:

```sh
uv run qabot journeys bundle "$RUN_DIR"
```

This creates `"$RUN_DIR.zip"` next to the run, without overwriting an existing
archive or changing original evidence. The ZIP contains `report.html`, `report.md`,
`results.json`, and referenced screenshots/videos with relative media links intact.
Standalone logs, runtime configuration files, databases, credential files, and
unreferenced files are excluded. Missing, unsafe, absolute, or symlink evidence
references fail clearly. Extract the ZIP before opening `report.html`. Review
metadata and media for sensitive information before sharing; bundling is not
sanitization and performs no upload, hosting, model call, or application rerun.

Exit codes are `0` for all PASS, `1` for any FAIL, and `2` for BLOCKED without FAIL
or an invalid command/approval; Ctrl-C retains partial evidence and exits `130`.
A correctly observed expected rejection can PASS. A failed browser action blocks
the step before further model judgment; it cannot be retried into a PASS.
Changed plans, referenced scripts, target repositories, or resolved base/head
commits require renewed approval. Moving `HEAD` or a branch invalidates approval
even when the plan text is unchanged. Older approvals without Git bindings must
be reviewed again. An unchanged approved target and plan can be rerun to a fresh
output directory without another approval prompt.

Manual walkthrough: [examples/WALKTHROUGH.md](examples/WALKTHROUGH.md).
Product requirements: [docs/PRD.md](docs/PRD.md).
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
means a control the actor cannot reach is BLOCKED until a human reviews whether the
problem is an actor mistake, missing accessibility metadata, or some other UI mismatch.

## Legacy Demo Offline By Default

The legacy demo and scan prototype provider is deterministic and needs no API
key, so those prototype paths are reproducible. The reviewed journey workflow
above is live: planning, browser acting, and judging use real Claude/Sonnet calls
through the local `claude` CLI. Other real providers remain explicit opt-in:
`QABOT_LLM=anthropic` over the SDK, or `QABOT_LLM=claude-cli` through a locally
installed `claude`. Each raises when what it needs is missing, and the network is
never a silent fallback.

## Legacy Prototypes

`seed`, `run`, `demo`, `demo-browser`, and `scan` are earlier prototype surfaces.
They remain useful for local experiments and regression coverage, but they are not
the reviewed Chrome journey workflow described above.

`scan` takes a URL, crawls what it can reach anonymously, and writes a report to a
file. It never fails a build (`qabot scan` always exits 0); the report is the
deliverable, not a pass/fail signal.

    uv run qabot scan https://example.com

Flags: `--out` (default `qabot-scan-report.html`) is where the report is written,
`--max-pages` (default `25`) caps the crawl, `--delay` (default `1.0`) is the seconds
between page loads, and `--artifacts` (default `qa-artifacts`) is where screenshots land.
