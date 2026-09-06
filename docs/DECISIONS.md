# Decision log

Every material decision, who made it, and what was rejected. Ordered by when it was
taken. "You" = Jordan; "Claude" = decided autonomously under the standing instruction
to use best judgement.

Date of record: 2026-08-27.

---

## Product shape

### D1 — Target is a general-purpose QA bot sold as a subscription
**Decided by:** you.
Not a bespoke tool for one repo. This raises the bar on environment handling, tenancy,
and trust, and it means we cannot hardcode anything about the customer's stack.

### D2 — The bot runs inside the customer's CI
**Decided by:** you, from four options.
Their pipeline already boots the app for their own tests, so we inherit a working
environment, secrets, and a seeded database for free.
**Rejected:** (a) pointing at a staging URL — too weak a link between diff and behavior;
(b) standing the app up ourselves — makes us a devops product before a QA product;
(c) API/CLI-only testing — sidesteps the demo everyone wants.
**Consequence:** CI is non-interactive, so human-in-the-loop cannot happen during a run.
This forced D7.

### D3 — A run leaves behind a report *and* generated regression tests
**Decided by:** you.
Prose is read once; tests are permanent and falsifiable. The customer never has to take
the bot's word for anything, and their suite compounds.
**Rejected:** report-only (value evaporates, every claim rests on narration);
tests-only (invisible subscription value).

### D4 — The knowledge base is hosted in your service, not committed to their repo
**Decided by:** you. Claude recommended repo-committed; you chose hosted to own the asset.
**Accepted downsides, and what we do about them:**
- *Drift.* Repo-committed state stays honest because refactors move it; hosted state goes
  stale silently. Mitigated by D16 (anchors + a staleness pass every run). This is now
  load-bearing: if the staleness pass is ever skipped, the product rots.
- *Lock-in objection.* Mitigated by one-click export of the full KB.
**Boundary:** generated tests live in their repo (artifacts they own); the KB lives in
yours (the asset you sell).

### D5 — Cold start: diff-driven, KB seeded from their existing test suite
**Decided by:** you, refining Claude's recommendation.
Their existing e2e tests are human-written, encode which flows matter, name them in domain
language, and are already in the repo. Seeding from them means day-one value at zero
customer effort, and makes HITL questions specific rather than a blank questionnaire.
**Rejected:** onboarding-first deep indexing as the *entry point* (time-to-first-value in
days, and long structured interviews get abandoned); record-and-generalize from telemetry
(needs data access no new vendor gets on day one — revisit later).

### D6 — Deep indexing is demand-driven and scoped, not an upfront ceremony
**Decided by:** Claude; you approved.
Runs emit open questions and per-workflow confidence. When a region of the app crosses an
uncertainty threshold, that schedules a targeted session for that region only. Same depth
as full onboarding, paid in installments, self-targeting at the areas that cost signal.

---

## Architecture

### D7 — Two loops, knowledge base as the interface
**Decided by:** Claude; you approved.
Async loop (hosted, human time): ingest, curate, answer questions. Sync loop (their CI,
machine time): read a frozen snapshot, execute, report, never ask. Forced by D2.

### D8 — Provenance caps finding severity
**Decided by:** Claude; you approved. **This is the most important rule in the system.**
`human_confirmed` → may report a BUG. `observed_in_run` → REGRESSION.
`inferred_from_test` → CHANGE ("your tests implied this; did you mean to change it?").
`inferred_from_code` → QUESTION only, never a finding.
An LLM cannot reliably tell "broken" from "different", so we do not ask it to: the model
decides whether an expectation held, the data structure decides how loud that may be.
This is what prevents cry-wolf structurally rather than by prompt-tuning. Every human
answer upgrades an expectation's provenance, which permanently raises the volume the bot
is allowed to speak at — that is the flywheel, made mechanical.

### D9 — Exactly three outcomes: PASS, FAIL, BLOCKED — never blurred
**Decided by:** Claude; you approved.
BLOCKED means "I could not test this". It is not a pass and not a failure, and it is never
silence. Matches your fail-loudly-over-silent-fallback rule.

### D10 — Only verified PASSes become generated tests, after a flake check
**Decided by:** Claude; you approved.
We never commit a test asserting behavior we could not confirm. New tests are run N times
in the same job; flaky ones are discarded, not committed. Poisoning a customer's suite
with flaky generated tests would be fatal and entirely self-inflicted.

### D11 — Generated tests land as a separate follow-up PR
**Decided by:** Claude; you approved. Never make a developer's merge wait on the bot.

### D12 — Advisory by default; blocking is opt-in per workflow
**Decided by:** Claude; you approved. Blocking by default gets you uninstalled in week two.

### D13 — Time-boxed run over a ranked queue
**Decided by:** Claude; you approved.
CI minutes are the customer's money. The run degrades by testing *less*, never by testing
*worse*, and everything skipped is reported — silent truncation reads as coverage.

### D14 — Split "knowledge" (hosted) from "wiring" (their repo)
**Decided by:** Claude; you approved.
A small committed `qa.yml` holds base URL, readiness check, reset command, and credential
sources. Plumbing moves with their infra; knowledge stays the asset.

### D15 — Steps are declarative intents, never selectors
**Decided by:** Claude; you approved.
"log in as a user whose subscription expired yesterday", not a CSS path. If plans contain
selectors the KB rots every time someone renames a div.

### D16 — Anchors are the drift sensor; staleness runs first, every run
**Decided by:** Claude; you approved.
Typed code references (route, symbol, file, component) per workflow, re-resolved each run.
Unresolvable → workflow marked STALE, confidence drops, open question emitted. This does
the job that repo-committed state would have done for free (see D4).

### D17 — Workflows stay small; one journey, one outcome, ≲8 steps
**Decided by:** Claude. Big workflows fail ambiguously and are unmaintainable.

### D18 — Knowledge base is append-only and versioned
**Decided by:** Claude. Human corrections are the most valuable data in the system and must
never be overwritten. Also supplies the audit trail and the export story from D4.

### D19 — Personas are first-class and fixture-backed
**Decided by:** Claude. A persona is a named entity with traits, permissions, and a recipe
for constructing that state in a fresh environment — not prose. One clarification about
audience then pays off across every workflow that uses it.

---

## Prototype implementation (Claude's judgement, this session)

### D20 — Prototype built in the scratchpad, then mirrored into the repo
**Forced by the environment.** `~/Documents` is TCC-locked for this process: exact-path
file reads/writes work, but directory enumeration, `git`, `uv`, and `pytest` all fail
(`PermissionError` on `os.listdir`; `git: Unable to read current working directory`).
Building in the scratchpad is the only way to actually *run* and verify the prototype.
**To fix permanently:** System Settings → Privacy & Security → Full Disk Access → enable
for your terminal app, then restart it.

### D21 — Python 3.11+, pydantic, FastAPI, httpx, pytest, uv
**Decided by:** Claude. Matches your stated `uv run` workflow. Pydantic gives the KB schema
validation for free, which matters because the KB is the product.

### D22 — Expectations carry an optional machine-checkable `check`
**Decided by:** Claude (contract amendment made before the team was dispatched).
An expectation derived from an existing test's assert gets a deterministic form
(`{"kind": "status", "value": 402}`). A prose-only expectation has none, and offline
evaluates to BLOCKED rather than a guess. This is what makes D8 and D9 testable without
a network, and it means the offline path degrades honestly instead of hallucinating.

### D23 — Deterministic LLM provider is the default; the network is never a silent fallback
**Decided by:** Claude. Both real providers are explicit opt-in and raise loudly when what
they need is absent: `AnthropicLLM` (`QABOT_LLM=anthropic`) without a key, `ClaudeCliLLM`
(`QABOT_LLM=claude-cli`) without the `claude` binary on PATH. The CLI provider exists
because no `ANTHROPIC_API_KEY` is present in this environment, and without it an evaluation
would quietly run against the rule-based stand-in and report its numbers as a model's. No
env var still means the deterministic path, which is what the prototype is verified on.

### D24 — Seeding is AST-based and uses no model at all
**Decided by:** Claude. Parsing a customer's existing pytest suite with the `ast` module is
deterministic, auditable, and free. Reserve model calls for genuinely ambiguous inference.

### D25 — HTTP driver first; browser driver deferred
**Decided by:** Claude. The Driver protocol is the seam; adding Playwright later means
adding a driver, not touching planner, verifier, or reporter. HTTP is what can be built and
honestly verified in a prototype. **This is the biggest gap between the prototype and the
product** — "impersonate a real user" ultimately means a browser.

### D26 — `Observation.ok` means the interaction completed, not that it succeeded
**Decided by:** Claude. A 402 is `ok=True`; a timeout is `ok=False`. This is precisely what
lets the verifier tell FAIL from BLOCKED (D9).

### D27 — KB persistence is a JSON file standing in for the hosted service
**Decided by:** Claude. `KBStore.snapshot()` returns a deep copy, enforcing D7's rule that
the runner never mutates the KB — a flaky run must not be able to corrupt the asset.

### D28 — The demo app contains two deliberate, commented defects
**Decided by:** Claude. An expired card returns a generic error (violating a
human-confirmed expectation → BUG) and clears the cart (violating a test-inferred
expectation → CHANGE), while a declined card preserves it. That asymmetry is exactly what
a QA engineer should catch, and it exercises the full severity ladder end to end.

### D29 — Nothing is committed to git
**Decided by:** Claude, following your CLAUDE.md over the brainstorming skill, which wanted
to commit the spec. Your instruction wins. (Git is also non-functional here — see D20.)

### D30 — Built by five parallel agents with non-overlapping file ownership
**Decided by:** Claude, on your instruction to spin up a team. Contracts (`models.py`,
`llm.py`, `drivers/base.py`, `store.py`) were frozen first so the agents could not fight
over interfaces.

### D31 — Expectations are bound to the step they describe
**Decided by:** Claude, after the first end-to-end run exposed the bug. **This was my
error, not an agent's** — I specified "evaluate against the final observation" in the
verifier's brief.

Grading every expectation against the last response produced findings whose evidence
pointed at the wrong thing: the report said "expected status 402, got 200" with the body
of a trailing `GET /cart`, when the app had correctly returned 402 at checkout. Three of
five findings in the first live run were false positives, and even the correct BUG finding
cited the wrong response body. For a product whose entire pitch is evidence quality, this
is the worst available bug.

Fix: `Expectation.step_index` binds an expectation to its step; an expectation whose step
was never reached is BLOCKED, never graded against a different step's response.
Additionally, observations are now keyed by step index rather than intent string — two
steps can share an intent, and a dict keyed by intent silently drops one.

### D32 — `capture` binds destination from source: `{var_name: response_field}`
**Decided by:** Claude, ruling on a conflict two agents raised independently.

The seeder emitted `{response_field: var_name}`; the planner read `{var_name: response_field}`.
Inverted. The planner's reading stands (it matches the contract I issued, reads like an
assignment, and matches both modules' docstrings); the seeder flipped.

**The important part is why it was invisible.** Every capture in the demo e2e suite was
`cart_id = resp.json()["cart_id"]`, where the variable and field names coincide and both
readings behave identically — so 203 tests passed over an inverted implementation. The
worked example in the design doc had the same defect and would have propagated it.
Both were changed to rename on capture. *A fixture that cannot distinguish two readings is
not a fixture*, and a degenerate example in a spec is worse than no example.

Credit where due: two agents found this by inspection and both stopped to ask rather than
silently converging on different answers. That was the right call and it is why the bug
was caught before the demo rather than after.

### D33 — Generated tests come from any non-FAILing workflow, not only PASSing ones
**Decided by:** Claude, after the end-to-end run showed the original rule disabling the
feature entirely. **Revises D10.**

The original rule — only `PASS` workflows emit tests — sounds conservative but fails badly
in a realistic case. In the live demo `wf_checkout_with_valid_card` has four expectations:
three verify deterministically and pass, and the fourth comes from `assert resp.json()["order_id"]`,
a truthiness assert the seeder honestly cannot translate into a machine check. That one
prose-only expectation evaluates to BLOCKED, which makes the whole workflow BLOCKED, which
emitted nothing — despite three behaviors having been genuinely confirmed.

New rule: a workflow contributes its verified expectations when its outcome is PASS **or
BLOCKED**; a FAILing workflow still contributes nothing.

The distinction is principled rather than convenient. An expectation that passed a
deterministic check is confirmed behavior, and BLOCKED means "we could not check
everything", not "something contradicted us". A FAILing workflow is genuinely different:
the app is misbehaving, so behavior observed alongside the failure may be an artifact of
it, and codifying that would be unsafe. Unchanged: only machine-checked expectations ever
become tests, never prose.

### D34 — Expectations added by the curator must carry a step binding
**Decided by:** Claude. A corollary of D31 worth stating separately, because it is a trap.

When a human answers an open question, the resulting `human_confirmed` expectation needs a
`step_index` like any other. Without one it is graded against the workflow's last response.
In the demo this produced the right verdict with the wrong evidence — the BUG finding cited
the body of a trailing `GET /cart` rather than the checkout response that actually
misbehaved. Right verdict, wrong evidence is still a credibility failure: it is the first
thing a skeptical developer checks. The curator UI must therefore capture *which step* an
answer is about, not just the answer.

---

## Browser driver (2026-08-28)

Built after you chose the browser driver over three alternatives (a first pass against a
real repo, CI packaging, or hardening what existed). It closes the gap flagged in D25.

### D35 — Browser locators are role + accessible name; CSS and XPath are unsupported
**Decided by:** Claude.

`get_by_role("button", name="Place order")` describes what a user *perceives*. A locator
encoding DOM structure (`div.sc-1x2y > button:nth-child(3)`) is knowledge invalidated by
every restyle, and the knowledge base is the asset — so this is D15 ("intents, not
selectors") applied to the browser. The driver raises rather than accepting a CSS escape
hatch, because one accepted escape hatch becomes the default within a month.

**The side effect is worth as much as the rule.** The driver can only reach controls that
are in the accessibility tree. A button with no accessible name is unreachable, so the
step reports BLOCKED naming the control — which is simultaneously a real accessibility
defect. The demo's cart has an icon-only remove button precisely to show this: the bot
finds an a11y bug as a by-product of not being able to do its job.

### D36 — Text checks are scoped to a page region, never matched page-wide
**Decided by:** Claude, after a smoke test caught a false pass.

The demo's checkout page renders a card `<select>` containing an option labelled
"expired". A page-wide search for "expired" therefore **passes on the exact page whose
error message fails to mention it** — a false pass on the defect being hunted. So
`text_visible`/`text_absent` take an optional `role` (currently `alert`) and grade only
that region. `tests/test_demo_ui.py::test_the_word_expired_appears_outside_the_alert`
exists solely to keep that trap in place; if it ever stops being true, the scoping is no
longer exercised and page-wide checks would start passing for the wrong reason.

This is the same class of error as D32's degenerate capture fixture: a check that cannot
distinguish right from wrong is not a check.

### D37 — The surface is inferred from the hint's shape, not configured
**Decided by:** Claude. A hint naming an `op` is a browser interaction; one naming
`method` + `path` is HTTP. No mode switch and no per-run driver setting, so one knowledge
base can hold both HTTP and browser workflows and a workflow can migrate between surfaces
without a config change.

### D38 — `DriverError` propagates; only interaction failures become BLOCKED
**Decided by:** Claude, after a test caught the driver swallowing it.

`execute` originally caught every exception and turned it into an `ok=False` observation.
That conflated two different things: a malformed action (an authoring bug in the knowledge
base) and a timeout (the app could not be interacted with). The first must be loud; only
the second is legitimately BLOCKED. A malformed plan quietly reported as "could not test"
is a bug that hides itself.

### D39 — Generated tests decline browser workflows by name, and never emit an empty module
**Decided by:** Claude. Revises D33's mechanics, not its rule.

The generator produces pytest + httpx replays, which browser steps have no equivalent for.
It now recognises a browser workflow and says so — "qabot verified it through a real
browser, but does not yet generate Playwright regression tests" — rather than falling
through to the generic "no recorded request" note, which misdiagnoses it. Separately,
`emit_tests` now plans before deciding: a run where every contributing workflow is
declined returns nothing at all, instead of writing a test file whose only content is an
explanation of why it is empty. Explaining absence is a report's job.

### D40 — A BLOCKED step reports the driver's explanation, not its summary
**Decided by:** Claude.

The summary said `click -> TimeoutError`. The actionable text — "no accessible control
matching button named 'Remove widget'... which is itself an accessibility defect worth
fixing" — sat unused in the evidence. A BLOCKED nobody can act on is a BLOCKED that gets
ignored, which would quietly undo D9.

### D41 — Browser tests drive real Chromium against a real server, behind a marker
**Decided by:** Claude.

A browser driver verified against a mock proves nothing about the thing it exists to do,
so these tests launch Chromium and hit a real uvicorn port (`demo/server.py` binds the
socket before handing it over, so nothing can claim the port in between). They carry a
`browser` marker: `-m "not browser"` for the fast tier, and the full suite by default.

Also removed `pytest-playwright`: it was unused, and its session-scoped `base_url` fixture
silently collided with the test module's own.

---

## Strategy (2026-08-28)

Full evidence and competitive map in [STRATEGY.md](STRATEGY.md). Recorded here because
each of these changes what gets built.

### D42 — Docs-vs-behavior contradiction detection is cut
**Decided by:** Claude, on research evidence, reversing a direction Claude had proposed
two turns earlier and Jordan had endorsed as the way to "bridge the gap."

Three independent kills. No buyer asks for it and no budget attaches to it — the only
advocacy traces to a founder who sells a documentation product. The nearest research
(Cascade, FSE 2026) achieves **0.39 precision at realistic class imbalance and 0.21
recall**, missing four of five real inconsistencies, and it operates on
method-docstrings-vs-code while ours would be prose-vs-UI — a regime nobody has measured.
Momentic already ingests docs, guides, tickets, Jira, Linear and Figma; they are one
product decision from it.

Worth stating plainly because it was *my* idea: the CONTRADICTION severity tier was a good
argument that did not survive contact with evidence.

### D43 — The pitch is the anti-false-negative guarantee, not the outcome enum
**Decided by:** Claude, on demand-side evidence.

We assumed buyers fear noisy findings. They do not — across the category leader's 73
long-form reviews, not one mentions false positives. What they fear is a **falsely green
build**: self-healing binds to a similar-looking button, the test passes, the bug ships.
BrowserStack documents this against their own product; Meticulous silently drops oversized
recording sessions with nothing surfacing it.

So D9's three outcomes stay exactly as built, but the *claim* changes from "an outcome
nobody reports" to **"green means we verified it, not that we couldn't check."** Ranger
already ships a `blocked` verdict, and *Blocked* has been a standard manual test status for
decades — the enum is not defensible, the guarantee is.

### D44 — Provenance grading is retained as mechanism, demoted as pitch
**Decided by:** Claude.

Zero counterexamples across twelve vendors, so the whitespace is real. But nobody asks for
it, a July 2026 SLR already publishes a (flat, unranked) authority taxonomy, and the slot
is occupied in buyers' heads by AI triage that buckets failures into Actual Bug / UI Change
/ Flaky / Environment.

The decisive reframe: **buyers do not want fewer findings, they want cheaper triage per
finding.** Provenance earns its place only if proven in triage-minutes saved. It stays
because it is the mechanism that makes D43's guarantee honest — you can only promise "green
means verified" if you track where every expectation came from.

### D45 — Implicit-intrinsic oracles are the first thing to build
**Decided by:** Claude, on the strongest evidence in the whole investigation.

Crashes, uncaught exceptions, console errors, 4xx/5xx, DOM validity, broken links, a11y
violations. **Zero of 54 studies** in the oracle literature cover them and no product
asserts them systematically. They have no provenance problem at all — nothing needs
deriving, so no severity cap applies and they cannot be a false positive in the "nothing is
wrong" sense.

Highest precision, lowest cost, and they serve the pain buyers actually voice (cheap
triage) rather than the pain we assumed. Ship first, earn the right to be believed, spend
that credibility on the hard problem.

### D46 — Target new-feature verification, not regression
**Decided by:** Claude, on competitive analysis; consistent with Jordan's original brief.

Meticulous dissolved the oracle problem by making the previous commit the expectation. That
is architecturally cleaner than our design and attacks flakiness structurally — do not
compete there. But it means they have **no oracle for behavior nobody has exercised yet**,
which is precisely the PR case.

The original brief was never regression testing: "Developer builds a feature... then the QA
bot." Ranger occupies this segment but its oracle is written by the coding agent that then
writes the code — the author grading the author, which their docs market as a feature and
never examine as a risk. **Oracle independence is the opening.**

Honest counterweight: Ranger's commercial signals are poor (no round in 19 months, npm
installs -72% from peak, 1 GitHub star, two self-submitted HN posts with zero comments, no
reviews anywhere). The segment may be untaken because nobody pays for it. That is the
weakest link in the strategy and is flagged as such in STRATEGY.md §4.

---

## Seeder correctness (2026-08-29)

Prompted by a read-only audit of the seeder against the shapes a foreign repository
actually contains. That audit's list is much longer; this is the item on it that was
already producing wrong answers rather than merely missing right ones.

### D47 — An assert binds to the response variable it names, not to the call before it
**Decided by:** Claude, after the audit reproduced a false positive end to end against an
application that was correct by construction. **This is D31's bug at the seeding layer.**

`_step_for_assert` bound an assert to a step by source position: `bisect_right` over the
call positions, take the last call written before the assert ends. That rule is right only
when every call is immediately followed by its own asserts. The ordinary "issue the
requests, then assert on them" shape —

```python
a = client.get("/a")
b = client.post("/b", json={"x": 1})
assert a.status_code == 200
assert b.status_code == 201
```

— puts both calls ahead of both asserts, so both bound to `b`. Against an app where `/a`
returns 200 and `/b` returns 201, exactly as the test says, qabot reported *"response
status is 200 — expected status 200, got 201."*

**Why this earns a decision and not a commit message.** The second expectation binds to
`b` as well and passes, so the report carries a single finding rather than two: it reads
as precise rather than as obviously broken. Every element of the evidence is individually
true — the request was sent, the response really was 201, the test really does assert 200
— and the one false thing is the binding between the claim and the response, which is the
part a reader cannot check without opening the source. The repro then reads "1. fetch /a,
2. submit /b", so a reader who follows it watches `/a` return 200 and cannot reconstruct
where the 201 came from. This is the failure `verifier.py`'s rule 3 calls worse than no
finding at all, fired on correct code.

Fix: the response variable the assert names decides. `a.status_code` is a claim about
whatever `a` was bound to *at that line*, so a rebound `resp` resolves to its latest
assignment rather than to one the name ever had. Position still settles the two cases that
name no variable — a call written inside the assert is its own subject, and an assert
reaching into no name at all falls back to the last call before it. An assert naming a
variable we never saw bound to a call, such as a fixture's response, binds to nothing:
BLOCKED is honest, and attaching it to the nearest step is the same lie in a tidier shape.
The variable-to-step map already existed inside `_thread_captures` and was being thrown
away; it now carries the position of each binding and is handed to `_expectations`, so
there is one answer to "what does `resp` mean here" instead of two that can drift apart.

**The pair is the point.** D31 fixed grading-against-the-last-response in the verifier and
stopped there. The same mistake was available one layer up, in the data that feeds the
verifier, and it survived the fix — because a fix aimed at a symptom asks "is this layer
right?" and never "who computed the input this layer now faithfully honours?". Every layer
below the seeder behaved correctly here; the lie was baked into the knowledge base at seed
time, where nothing downstream can see it.

It stayed invisible for the reason D32's inverted `capture` did. The demo suite interleaves
each call with its own asserts, so every positional binding was also the correct one, and
295 tests passed over the bug. *A fixture that cannot distinguish two readings is not a
fixture* — the second time that sentence has had to be written about this repository's one
e2e suite, which is now itself a finding about the fixture rather than about the code. The
regression tests for this decision use the trailing shape deliberately, and one asserts a
rebinding whose positional, ever-bound and correct answers are three different numbers.

### D48 — A call must earn the label "HTTP request"; what it cannot earn, it asks about
**Decided by:** Claude, after pointing the seeder at CTFd and langflow and measuring what
came out. **Continues D47:** the same failure, reached from the other end.

`_http_method` accepted any `<name>.<verb>(...)`. Python being what it is, `.get` belongs
to every dict, cache, ORM session, context variable, queue and mocking library alive, and
real suites call them constantly — CTFd reads `sess.get("nonce")` off a Flask session 93
times. Measured on CTFd's seeded knowledge base: **127 of 1018 steps (12.5%), across 63 of
473 workflows, were requests no test ever issued**, with **107 expectations bound to
them**. `GET nonce`. `GET content`. `GET success`. langflow was worse in proportion.

D47 was an expectation pointed at the wrong response. This is an expectation pointed at a
response that never existed — the bot issues the fabricated request itself, the app
answers it, and the assertion is graded against that answer. Every layer downstream
behaves correctly on input that was invented three commands earlier.

**The only thing standing between us and silently issuing them was a crash.** A run against
live CTFd died in `normalize_route` with `route path must start with '/', got 'GET status'`
— we were saved by the accident that a dict key rarely begins with a slash. And that crash
is its own indictment: **the seeder was writing knowledge bases its own run path refuses to
load.** `qabot seed` reported success, `qabot run` exploded, and the two commands had no
contract between them at all. So seeding now resolves every anchor it produces through
`resolve_against_index` — the run path's own function, against an empty index, checking
that resolution *runs* rather than what it finds — and fails at seed time, where the message
can name the test that caused it.

**The rule, and why it is this one.** A call earns REQUEST on evidence of the URL it names:
a keyword only an HTTP client takes (`json=`, `headers=`, `params=` …), or a first argument
with path structure — any literal fragment containing `/`. Two counts of evidence say the
opposite: a bare string literal with no `/` (that is a key), and any argument count other
than one, since httpx, Flask's test client and Starlette's all make everything after the
URL keyword-only, so `d.get(k, default)`, `session.get(Model, pk)` and `ctx.get()` are
shapes no request has.

A receiver-name allowlist was the obvious alternative and is wrong: CTFd's `sess` is a
session dict while langflow's `session` is a SQLModel session and half the world's `client`
is an HTTP client, so the name carries no information the argument does not carry better.
Requiring a leading slash was the other candidate and is also wrong — **langflow writes
`client.get("api/v1/all")` 1121 times**, and a rule that discarded those would have thrown
away most of the largest suite we tested. Path structure is what both cases actually have
in common, and it is one sentence a reader can hold in their head. Measured across both
suites: 355 slashless string-literal first arguments, not one of them a request.

Those 1121 slashless paths do get a leading slash written into the step, because httpx and
every test client resolve a relative URL against the base URL by stripping exactly that
slash — it changes no request, and without it the route anchor is one the run path will not
load.

**And the third answer, which is the part that matters.** `client.get(chal_uri)` may be a
request; `session.delete(project)` may not; `client.get("http://localhost/login")` names a
host we cannot show is the app under test rather than Stripe. Nothing in any of them
decides it. Including them fabricates requests, and dropping them is a silent hole in
coverage the customer believes is covered — the failure D43's guarantee is sold against. So
they are neither: each becomes an OpenQuestion on the knowledge base, grouped by receiver
(a human answers "is `session` a client?" once, not seventy times) with its call sites
attached, and `cmd_seed` now prints what it could not read alongside what it could. A seed
line reporting only successes reads as "we understood your suite", which is the same lie
`reporter.py` rule 2 forbids about a truncated run.

Result on the two real repositories: CTFd 127 phantom steps → **0**, 1018 steps → 893, the
same 473 workflows, 21 open questions naming 38 calls. langflow 27 fabricated steps gone,
112 slashless-but-real steps kept and made loadable, 3 open questions. Unloadable route
anchors: 72 and 118 → **0 and 0**.

**What this cost, stated plainly.** `client.get(carts[0].url)` used to abort the seed with
"cannot render"; now it is a question. The loud path survives only where we have positively
identified a request and still cannot read it — `client.get(carts[0].url, headers=auth)`
still raises. That is a deliberate narrowing: a loud failure is the right answer for a
request we cannot follow, and the wrong answer for a line that was never a request at all,
because one un-renderable expression anywhere under `--e2e-dir` still takes the whole seed
with it.

---

## Impact selection on real applications (2026-08-29)

Prompted by the headline finding in [EVAL.md](EVAL.md): impact selection could not fire on
any application except the bundled demo, which made "work out which workflows this diff put
at risk" — the tool's central job — a demo-only capability.

### D49 — Workflows anchor to application source through the running app's own route table
**Decided by:** Claude.

`anchors.route_decorators` reads routes out of source syntax, matching
`@<obj>.<http_method>("literal")`. That is one idiom of one framework, and it happens to be
the one `demo/app.py` uses. Measured: **zero** routes extracted from CTFd's
`api/v1/challenges.py`, which declares seventeen of them as `@challenges_namespace.route(...)`
on Flask-RESTX `Resource` classes. Flask's own `@app.route("/x", methods=["POST"])` is
unmatched too — the attribute is `route`, not a verb. And a matched decorator would still be
the wrong string: real frameworks compose paths from fragments, so the decorator says
`/types` where a test calls `/api/v1/challenges/types`.

The consequence was not a degraded selection, it was no selection: 410 clean CTFd workflows,
a diff rewriting the flag-submission handler, **0 selected** — and with the unfiltered 473,
`select_workflows` raised instead. Same on datasette: 82 workflows, 0 selected.

**The fix is to stop inferring.** A running application already holds the map from URL to
handler; it must, or it could not serve a request. Ask it. `qabot/routemap.py` walks Flask's
`url_map` (resolving `view_functions` through `view_class` to the method serving each verb)
or Starlette/FastAPI's `routes`, and turns each handler into a file and a line span with
`inspect`. A diff overlapping that span is then a *direct* hit on every workflow that calls
that path — exactly the signal `impact.score_workflow` already wanted, sourced from the
framework's routing table instead of from a guess about how the framework was spelled. On
CTFd the same knowledge base and the same diff now select 10 workflows out of 114 that
scored, with 104 reported as skipped-for-budget.

**Anchors are instances; route tables are patterns**, and reconciling them is where the real
design decision sits. The knowledge base holds `/api/v1/challenges/1` (an id some test
used) and `/api/v1/challenges/{chal_id}` (the seeder's placeholder, named after the test's
variable); Flask holds `/api/v1/challenges/<challenge_id>`. Three vocabularies, and the
parameter *name* is shared by none of them. So a parameter segment collapses to a nameless
slot and matching is segment-wise with literals beating slots — which is what a router does
to resolve a request, and the only way those three ever meet.

**Rejected:**
- *Teach `route_decorators` more idioms.* It cannot work in principle, not just in practice:
  the path is not in the decorator. Matching `@ns.route("/types")` correctly requires knowing
  which namespace `ns` is and where it was mounted, i.e. re-implementing each framework's
  registration semantics from syntax — and being wrong *silently*, which is the property that
  makes this class of bug expensive.
- *Read the app's OpenAPI schema* (the direction EVAL.md took for cold-start seeding). It has
  paths and methods but no handler-to-source mapping, so it cannot answer "did this diff touch
  the code that serves this route". Right tool for seeding, useless for impact.
- *Have the customer declare a route-to-file map in `qa.yml`.* Committed knowledge that goes
  stale on the first refactor, which is the thing D15 and D16 exist to avoid.

**The cost is operational and belongs in the open.** This needs the application *importable*,
which means its dependencies, which means running the probe under the target's own
interpreter: `build_route_map(root, "CTFd:create_app", python=<their venv>/bin/python)`.
Measured, that is 1.5s and a database connection for CTFd, 7.8s for langflow. In CI it is
noise beside standing the app up, which their pipeline already does (D2). It also means the
probe is a separate stdlib-only module, `qabot/_routeprobe.py`: qabot cannot import CTFd and
CTFd's virtualenv cannot import qabot, so the only place they meet is a bare script. That is
a two-file split where one file was suggested, and it is deliberate — the constraint "never
import qabot here" is checkable at a glance in a file with no qabot imports, and would be
invisible as a pair of deferred imports inside otherwise ordinary code.

**Failure is loud, and opting out costs a sentence.** `build_route_map` raises `RouteMapError`
for an app that will not import, a router we cannot read, or a route table that resolves
entirely outside the checkout. A caller who chooses to continue anyway constructs
`RouteMap.unavailable(reason)`, which is an empty map *carrying its own limitation*; the
runner reads it with `getattr` exactly as it reads `HttpDriver.limitations`, and the reason
lands in the report. This follows `reset_path=None` precisely: the opt-out is explicit, made
once, in the open, and it costs a stated caveat on the whole run rather than silence. An
unreadable route table and an application with no routes must never look alike, because both
produce an empty selection and one of them is a false green (D43).

**What this does not fix.**
- *datasette is still out.* Its router is a list of `(compiled regex, view)` pairs, so there
  is no path template to normalize — `^/(?P<database>[^/]+)/(?P<table>[^/]+)$` would have to
  be *reverse-engineered* into `/{}/{}`, which is inference again, on a per-application basis,
  and would silently produce plausible wrong paths. It fails loudly instead, naming the router
  it could not read. Reaching it needs a different mechanism (its regexes carry named groups,
  so a regex-to-template converter is possible) and should be its own decision with its own
  evidence.
- *The staleness pass still resolves routes by decorator inference*, so on CTFd it marks
  workflows STALE that are anchored to routes the application demonstrably serves.
  `RouteMap` is exactly what `anchors.resolve_against_index` would need, but wiring it there
  flips hundreds of workflows out of STALE and changes confidence caps and report content —
  a larger behavioural change than this one, and it deserves its own entry.
- ~~*Scoring rewards breadth over specificity.*~~ Fixed in D50, which this note prompted.


### D50 — The strongest anchor decides a score; weaker ones never add to it
**Decided by:** Jordan's call, on evidence from the CTFd selection; implemented against a
measurement, not a preference.

D49 made impact analysis fire on real applications for the first time, and the first thing
it revealed was that the scoring underneath it was backwards. Anchor hits accumulated across
strengths, so a workflow calling the rewritten handler *plus two bystander routes in the same
file* scored 5.0, while the four tests whose entire subject was that handler scored 3.0 and
ranked 16th-19th. Under a budget of ten they did not run. Ranking exists to spend a CI budget
on the tests most about a change, and the rule was ordering by how much of the application a
workflow happened to touch.

**The rule: dominance, not accumulation.** A workflow scores its strongest anchor. Further
hits *at that same strength* add a small capped corroboration term; hits at any weaker
strength add nothing. A symbol hit already implies its file was touched, so summing the two
scores one piece of evidence twice.

Corroboration counting only equal-strength hits is the part worth arguing, and it was
settled by measurement rather than taste. Counting every other hit is the same defect in
miniature, and on CTFd it does not even work: every workflow calling the rewritten endpoint
has exactly one direct hit, so the tiebreak is composed entirely of bystander routes and the
four target tests move only from 16-19 to 14-17 — still cut. Under dominance they tie at the
top, which is the honest answer: with respect to this diff those workflows *are* equally
implicated, and the order within the tie is `select_workflows`' id sort, not a claim about
risk.

Measured outcome on the real CTFd diff that rewrites `POST /api/v1/challenges/attempt`: all
four tests written against that endpoint, plus a fifth, now occupy ranks 2-6 of 10.

Criticality and staleness still apply afterwards and may reorder across tiers. They are
standing priorities about a workflow rather than evidence about this diff, and the dominance
rule is a statement about evidence.

Three tests in `tests/test_impact.py` pinned the old summing behaviour and were rewritten to
pin this one; `test_specificity_outranks_breadth` was added so the regression cannot return
quietly.

---

## The scan product (2026-09-04)

Design: [2026-09-03-scan-design.md](superpowers/specs/2026-09-03-scan-design.md). Evidence
in [EVAL.md](EVAL.md).

### D51 — The scan product reuses the oracles and abandons the knowledge base
**Decided by:** Claude, on the EVAL.md evidence; you approved building it as a second
product rather than a mode of the first.

The measurement that forced it. Run against real repositories, the expectation tier —
seeded workflows, graded by provenance-capped `Expectation`s — produced 28 findings across
CTFd and datasette, and **28 of them were false positives**. The pattern was always the
same: a seeded assertion is only valid inside the fixtures, configuration and identity of
the test that produced it, and the knowledge base captures the assertion while discarding
that context. The intrinsic tier — findings that rest on the application declaring its own
failure, needing no seeded expectation at all — returned **zero false positives across 120
routes of two applications** and found two real defects in released software: datasette's
`assert False` on an unrecognized output format, and CTFd's unguarded `table` query
parameter in `/admin/export/csv`. One half of this codebase works on code we did not write.
The other half is 0-for-28. `scan` is the working half, pointed at a buyer the other half
was never for: someone who built an app — often with an AI — and has no test suite to seed
from, no fixtures, no `conftest`, and no engineer to read a stack trace. Everything that
sank the expectation tier is absent by construction, and everything the intrinsic tier
needs is a URL.

The design consequence. `scan` reuses `qabot/drivers/browser.py`'s `BrowserDriver` and
`qabot/intrinsics.py` unchanged, and abandons the knowledge base entirely — no `Workflow`,
no `Expectation`, no seeding, no curator loop. Severity is *derived*, not stored:
`impact_of` in the new `qabot/scan/grading.py` is a pure lookup on `finding.oracle`, never
a field written onto a `Finding` and never a match on prose. That keeps `intrinsics.py` and
`models.py` untouched, so the CI product keeps the epistemic ordering D8 depends on
(`human_confirmed` → BUG, ..., `inferred_from_code` → QUESTION), and the visitor-impact axis
this buyer actually needs (BROKEN / GLITCHY / NOTED, ranking a console error above a
correctly-capped QUESTION) can be re-cut again later without migrating any stored data.

The two `BrowserDriver` changes, and the bug that forced them. I claimed in design
discussion that `scan` would not touch the driver; that was wrong, and both fixes were
found against real applications, not imagined.

**(a) The origin filter's noise rule compared every event's host against the host parsed
out of `base_url` at construction.** Measured on a real app: `snake-survival.lovable.app`
redirects to `www.snakesurvival.com`, so every console error, failed request and 5xx it
produced was suppressed as third-party — only its uncaught exception survived, because
`page_errors` are deliberately exempt from the rule. A vanity domain the app itself
redirected us to is not a third party, and treating it as one turned the run silently
empty. Fixed by tracking the *effective* origin: `_hosts` starts as the configured host and
`_note_origin` adds every host the app has redirected us to during the run, so `_is_noise`
compares against the set rather than the one name we started with. This makes the CI
product more correct too — it simply could not surface there, because `base_url` in that
product is always a server it controls and never redirects away from itself.

**(b) `reset_path` was a plain `str` defaulting to `/reset`, so a scan would have called
`reset()` and POSTed to a stranger's production server.** `HttpDriver` already took
`reset_path: str | None` for exactly this reason (`NO_RESET_LIMITATION`); this brought the
browser driver into line. `scan` always constructs it with `reset_path=None` and states the
limitation in its report, the same as an `HttpDriver` run against an app with no reset
endpoint.

The counter-case, honestly. This couples two products to one piece of shared code: a future
change to `BrowserDriver` for either product's sake must now satisfy both, and a bug fixed
for one is a bug that was silently live in the other. Both changes above happened to be
strict improvements with no tradeoff, but the next one may not be, and there is no
mechanism here beyond the test suite for both products to catch it.

---

### D52 — `sourcemaps.py` stays built and unwired; the report layer's purity is not
### traded for it in a fix wave
**Decided by:** the repo owner, on the final whole-branch review's recommendation
(review finding I7).

`qabot/scan/sourcemaps.py` resolves a minified stack frame back to original file, line
and symbol, with an honest fallback to the minified frame when it cannot — built exactly
as spec §5 describes, and tested against its own suite. Nothing calls it. `render_html`
never receives a resolved frame, so the severity-ceiling problem the spec's §5 opens with
(the highest-severity signal arriving as `"Wl"`, a mangled symbol) is unfixed in the
shipped report.

The reason is not an oversight, it is a conflict between two things this branch already
decided. `report.py`'s docstring states the report is "a pure function of the run" — no
network, no filesystem beyond an already-captured screenshot path — precisely so it stays
testable without a browser and without a fixture server. Resolving a source map needs to
fetch the `.map` file, which is a network call, and the only point in the pipeline that
already holds a live connection to the app is `sweep`, not `report`. Wiring resolution in
during a review fix wave would mean choosing, under time pressure, where that fetch
happens and what report.py's purity claim then means — exactly the kind of design
decision a fix wave should not make as a side effect of closing a review finding.

So: the module and its tests are left exactly as they are, and the two places that
claimed otherwise are corrected instead. Spec §5 now states plainly that source-map
resolution is built and tested but not yet wired into the report, and names the open
question (most likely home: inside `sweep`, resolving frames as findings are produced, so
`report.py` keeps receiving already-resolved text and never touches the network itself).
Spec §7's module table carries the same note next to `sourcemaps.py`. Wiring it is future
work, scoped as its own change with its own decision about where the fetch lives — not
retrofitted here.

---

## Open, deferred to you

- **O1 — Model access and billing.** Does the runner proxy through your API with a scoped
  per-run token, or does the customer supply a key? Changes the pricing story, and their CI
  needs egress to your API either way. *(You said you'd think about this.)*
- **O2 — Security posture.** You are running an LLM-driven agent inside their CI with their
  secrets in the environment. Recommendation: open-source runner, pinned by digest, with an
  explicit statement of what leaves the container. Retrofitting trust is expensive.
  *(You said you'd think about this.)*
- **O3 — Browser driver.** ~~See D25.~~ Built 2026-08-28; see D35-D41. What remains:
  seeding browser workflows from an existing Playwright suite (the demo's are
  hand-authored), generating Playwright regression tests, and richer check kinds
  (element counts, scoping to roles beyond `alert`).
- **O4 — Flake check.** D10 is specified but not implemented in the prototype.
- **O5 — Multi-tenancy, auth, and the hosted curator dashboard.** Entirely unbuilt; the
  prototype models the async loop only as open questions written to the run report.
