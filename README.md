# qabot

An exploratory QA agent that runs in CI. It reads a pull request's diff, works out which
user-facing workflows are at risk, exercises them against the running app, reports what it
found, and leaves behind regression tests for whatever it verified.

Design: `docs/superpowers/specs/2026-08-27-qa-bot-design.md`
Decisions and their rationale: `docs/DECISIONS.md`
Market position and competitive evidence: `docs/STRATEGY.md`

## Run it

    uv sync --extra dev --extra browser
    uv run playwright install chromium

    uv run pytest                            # 278 tests
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
