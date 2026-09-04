# QA bot — design

**Date:** 2026-08-27 · **Status:** design approved through §3; §4–5 written after the
standing "use your best judgement" instruction. Decisions and their owners: `docs/DECISIONS.md`.

## 1. What this is

A QA agent that runs in a customer's CI on every pull request. It reads the diff, works out
which user-facing workflows are at risk, exercises them against the running app, reports
what it found in human terms, and leaves behind regression tests for whatever it verified.

Sold as a subscription across many repos. The thing being sold is not the agent run — that
is a commodity — but the **accumulated, human-corrected model of what the application is
supposed to do**. Month three must be measurably better than week one, and the mechanism
for that has to be structural rather than aspirational.

### The three problems that decide whether this works

1. **The oracle problem.** A QA engineer knows what *correct* looks like. A bot reading a
   diff only knows what *changed*. Nothing in a branch says an expired invite link should
   404 rather than redirect. Human-in-the-loop is not a nicety in the pipeline; it is the
   load-bearing wall. Addressed by §4's provenance ladder.
2. **The execution substrate.** "Pretend to be a real user" means actually driving the
   thing. This is the unglamorous majority of the work and where the product either
   verifies something or merely narrates plausibly. Addressed by running in CI (§2) and by
   the Driver seam (§3).
3. **Trust decay.** A bot that cries wolf is muted within a week. Addressed by capping
   finding severity by provenance (§4) and by making every claim ship with a re-runnable
   test (§6).

## 2. Deployment model

The bot ships as a CI job. The customer's pipeline already builds, migrates, seeds, and
boots their app for their own tests; we run as a step after the app is up and never own
bring-up. That single choice buys a working environment, secrets, and a seeded database.

It also makes the run **non-interactive**, which splits the system in two:

```
  ASYNC (hosted, human time)          SYNC (their CI, machine time)
  ┌──────────────────────────┐        ┌────────────────────────────┐
  │  Ingestor                │        │  Runner                    │
  │  repo → code map,        │        │   diff + booted app        │
  │  seeds KB from their     │        │     ↓                      │
  │  existing tests/routes   │        │   Planner  → what to try   │
  │            ↓             │        │     ↓                      │
  │  ┌────────────────────┐  │        │   Driver   → do it         │
  │  │  KNOWLEDGE BASE    │◄─┼────────┼── Verifier → did it work?  │
  │  │  (hosted)          │──┼───────►│     ↓                      │
  │  └────────────────────┘  │snapshot│   Reporter → comment,      │
  │            ↑             │        │              tests, run log│
  │  Curator (dashboard)     │        └────────────────────────────┘
  │  open questions → human  │◄─── open questions, low confidence
  └──────────────────────────┘
```

The knowledge base is the interface between the loops. The runner is **stateless**: it
pulls a frozen snapshot at start and pushes results at the end, and never mutates the KB.
A flaky run must not be able to corrupt the asset.

**Knowledge vs. wiring.** The KB is hosted. A small `qa.yml` in the customer's repo holds
base URL, readiness check, state-reset command, and credential sources — plumbing that
should move with their infrastructure.

## 3. Components

| Component | Where | Responsibility |
|---|---|---|
| **Ingestor** | hosted | Clone, build a code map, seed the KB from existing tests, routes, OpenAPI, README. |
| **Knowledge base** | hosted | Workflows, expectations, personas, anchors, confidence, open questions. The asset. |
| **Planner** | CI | Diff → affected workflows → ordered concrete steps. |
| **Driver** | CI | The execution substrate. Pluggable per surface: HTTP, browser, CLI. |
| **Verifier** | CI | PASS / FAIL / BLOCKED per expectation; applies the provenance cap. |
| **Reporter** | CI | PR comment, generated tests, run record. |
| **Curator** | hosted | The HITL surface: serves open questions, writes answers back to the KB. |

**Boundary rule:** anything needing the running app or the source lives in CI; anything
durable lives in the service. **Driver is the seam** — adding a browser means adding a
driver, not touching planner, verifier, or reporter.

## 4. The knowledge base schema

```yaml
id: wf_checkout_expired_card
name: "Checkout fails cleanly when the saved card is expired"
persona: returning_customer
criticality: high
status: active                    # active | stale | retired
preconditions: ["persona has exactly one saved payment method", "that method is expired"]
steps:                            # intents, never selectors
  - intent: "add sku 'widget' to the cart"
    hint: {method: POST, path: /cart/items, json: {sku: widget, qty: 1},
           capture: {cart: cart_id}}      # variable `cart` <- response field `cart_id`
  - intent: "submit checkout with the expired saved card"
    hint: {method: POST, path: /checkout/submit,
           json: {cart_id: "{cart}", card_token: expired}}
expectations:
  - id: exp_1
    statement: "an inline error identifies the card as expired"
    provenance: human_confirmed
    confidence: 0.95
    check: {kind: json_contains, path: message, value: expired}
  - id: exp_2
    statement: "the cart is preserved, not emptied"
    provenance: inferred_from_test
    confidence: 0.60
    check: {kind: json_len_gt, path: items, value: 0}
anchors:
  - {kind: route,     locator: "POST /checkout/submit"}
  - {kind: symbol,    locator: "billing/charge.py::charge_saved_method"}
  - {kind: component, locator: "web/src/checkout/PaymentError.tsx"}
```

### 4.1 Provenance caps severity — the central rule

| Provenance | A violation is reported as | Meaning |
|---|---|---|
| `human_confirmed` | **BUG** | A human said this must hold, and it doesn't. |
| `observed_in_run` | **REGRESSION** | This held before; it doesn't now. |
| `inferred_from_test` | **CHANGE** | Their test implied this. Did you mean to change it? |
| `inferred_from_code` | **QUESTION** | Never a finding — only an open question. |

A model cannot reliably distinguish "broken" from "different", so it is never asked to.
The model decides whether an expectation held; the **data structure** decides how loudly
that may be reported. Answering an open question upgrades an expectation's provenance,
which permanently raises the volume the bot may speak at. That is the flywheel, mechanised.

### 4.2 Supporting rules

- **Anchors are the drift sensor.** The KB is hosted, so nothing forces it to track
  refactors. Every run re-resolves every anchor first; unresolvable → `STALE`, confidence
  drops, open question emitted. Skipping this pass is how the product rots.
- **`check` is the machine-checkable form** of an expectation, derived from an existing
  test's assert where possible. Prose-only expectations have none and can only be judged by
  a model — offline they evaluate to BLOCKED, never to a guess.
- **Workflows stay small.** One journey, one outcome, ≲8 steps.
- **Append-only.** Human corrections are the most valuable data in the system.
- **`capture` binds destination from source**, like an assignment:
  `{var_name: response_field}`. Worked examples must never use a variable whose name
  equals the field's -- a degenerate example cannot distinguish the two readings, and
  one in an earlier draft of this document hid an inverted implementation from 203
  passing tests.
- **Personas are fixture-backed**, not prose — traits, permissions, and a recipe for
  constructing that state in a fresh environment.

## 5. A run, end to end

1. **Boot** — their CI stands the app up. We run after.
2. **Fetch snapshot** — frozen KB, pinned for the run.
3. **Staleness pass** — resolve every anchor; mark drift; emit open questions.
4. **Impact analysis** — diff → changed symbols → scored workflows.
   `score = Σ(direct 2.0 | file-level 1.0) × criticality × staleness bonus`.
5. **Plan** — intents resolved to concrete actions; captures thread state between steps.
6. **Execute** — Driver runs steps, resetting state between workflows, recording evidence.
7. **Verify** — PASS / FAIL / BLOCKED per expectation; severity capped by provenance.
8. **Emit** — PR comment; generated tests **from verified passes only**; run record and
   open questions pushed to the service.
9. **Exit** — advisory by default. Blocking is opt-in, per workflow, once trusted.

## 6. Failure modes

The governing principle: **every failure resolves to BLOCKED with a named reason.** Never a
silent pass, never an invented failure.

| Failure | Behavior |
|---|---|
| App never becomes ready | Everything BLOCKED, reported prominently. Advisory exit. |
| `reset()` fails | Abort the run. Testing from an unknown state is worse than not testing. |
| Step unresolvable (no hint, no model) | That workflow BLOCKED; others continue. |
| Connection error mid-workflow | Step BLOCKED, rest of that workflow skipped, workflow BLOCKED. |
| Prose-only expectation, no model | BLOCKED — "couldn't check", never a guess. |
| Anchor unresolvable | Workflow STALE + open question. Still tested, at lower confidence. |
| Budget exhausted | Remaining workflows listed under "not tested". Truncation is never silent. |
| KB snapshot unavailable | Hard fail. No stale-cache fallback — silent wrongness is the worst outcome. |
| Model returns unparseable output | `LLMError` → BLOCKED. Never a guessed verdict. |
| Generated test proves flaky | Discarded, not committed. |

## 7. Testing strategy

Testing a QA bot is unusually tractable, because you can plant the bugs.

- **The golden buggy app.** `demo/app.py` is a small shop with two *deliberate, commented*
  defects: an expired card returns a generic error (violating a `human_confirmed`
  expectation → BUG) and clears the cart (violating an `inferred_from_test` expectation →
  CHANGE), while a *declined* card correctly preserves it. The end-to-end test asserts the
  bot returns exactly those findings at exactly those severities. "Does the bot correctly
  grade an app whose bugs I planted?" is the only integration test that matters.
- **Determinism.** The default LLM provider is rule-based and offline, so the entire suite
  is reproducible and needs no API key. The real provider is explicit opt-in and raises
  without a key; the network is never a silent fallback.
- **The cap table is tested exhaustively** — all four provenance values.
- **Invariant under test:** BLOCKED never becomes PASS or FAIL.
- **Generated tests are compiled and executed** in the suite, not just string-matched.

## 8. Deliberately not built in the prototype

~~Browser driver~~ — built 2026-08-28 (see `docs/DECISIONS.md` D35-D41): role+name
locators, screenshot evidence, and region-scoped text checks, driving real Chromium.

Still unbuilt: seeding browser workflows from an existing Playwright suite (the demo's are
hand-authored); generating Playwright regression tests (the generator is HTTP-only and
declines browser workflows by name); the hosted service, multi-tenancy, auth, and curator
dashboard; the flake check before committing a generated test; GitHub App / PR-comment
plumbing; telemetry-driven workflow discovery.
