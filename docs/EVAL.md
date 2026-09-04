# Evaluation: does this thing actually work on code we didn't write?

Living log. Started 2026-08-29. Purpose: replace "the demo passes" with a number
nobody in this category publishes — a measured false-positive rate on real
open-source applications, plus a detection rate against real historical bugs.

STRATEGY.md §7 sets the bar: **<10% false positives** (Google Tricorder, CACM 2018).
Above that, developers disable the tool. That is the pass/fail line for this work.

## Why this experiment and not another

The load-bearing unknown in STRATEGY.md §8 is a demand question and cannot be settled
by desk research. What *can* be settled is the precision question underneath it — and
§6 already says nobody in the category publishes accuracy numbers, so being the one who
does is differentiation before a novel line of code is written.

## Two paths, run in parallel

**Path A — the existing machinery, seeded.** `qabot seed` reads a Python e2e suite with
`ast` and emits Workflows capped at INFERRED_FROM_TEST. So a candidate repo must be a
Python web app with pytest API tests. Stand the app up, seed from its own suite, feed it
a real diff, measure.

**Path B — intrinsic oracles.** STRATEGY.md §6.1 says ship these first: crashes, uncaught
exceptions, console errors, 4xx/5xx, DOM validity, broken links, a11y violations. Zero of
54 studies cover them; no product asserts them systematically. **They do not exist in the
codebase today** — every Finding currently flows through a seeded Expectation. This path
needs building, and it is the one that runs against a repo with no knowledge base at all.

## Ground truth

- **False positives** — run against unmodified HEAD of a healthy release tag. Any BUG or
  REGRESSION is a candidate FP, adjudicated blind.
- **Detection** — reverse a real historical bug-fix commit to reintroduce a known defect.
  The fix commit and its issue are the ground truth.
- **Adjudication** — an independent agent sees the claim and the evidence, never the
  bot's reasoning, and rules on it against a written rubric.

## Threats to validity, written down before any numbers exist

So that we cannot quietly define them away later.

1. **Circular seeding — the big one.** Path A seeds the knowledge base from the repo's own
   test suite. Historical bug-fix commits usually ship *with* a regression test. If we
   revert such a commit and seed from the post-fix suite, we have handed the bot the exact
   assertion that catches the bug and then congratulated it for catching the bug. Any
   detection measured that way is worth zero. **Rule: seed from the tree as it existed
   immediately BEFORE the fix commit, and never let the fix's own test into the KB.**
2. **Vacuous precision.** A bot that reports nothing has a 0% false-positive rate. The
   FP number is only meaningful published alongside a detection number on the same apps.
3. **Adjudicator capture.** An adjudicator that sees the bot's reasoning will be led by it.
   It sees the claim and the raw evidence only, and rules against a written rubric.
4. **Target cherry-picking.** Apps get chosen for whether they RUN, before anyone sees how
   the bot scores on them. Candidate list frozen before the first measured run; any app
   dropped afterwards gets logged here with the reason.
5. **Intrinsic-oracle noise.** a11y scanners emit hundreds of violations on real apps and
   4xx is frequently correct behavior (401 unauthenticated, 404 missing). Reported
   unfiltered, these would wreck precision. Filters must be fixed in advance, not tuned
   until the number looks good.

## Log

- 2026-08-29 — started. Confirmed `claude -p` works headless as a real-model provider
  (~3s, clean JSON) since no ANTHROPIC_API_KEY is present. Confirmed no intrinsic oracles.
- 2026-08-29 — **the seeder does not survive real repositories.** Verified by hand, not
  by reading: a class-based suite (`class TestRecipes:`) seeds to *zero workflows and
  exits 0* — silent, and a direct violation of seeder.py's own docstring promise that a
  dropped flow is never downgraded to a skip. And `f"/api/recipes/{recipe['id']}"` raises
  SeedError and aborts the entire seed, which is the most ordinary idiom in an API test
  suite: create a thing, fetch it by the id you got back. Django/Flask suites using
  `reverse()` are out too. Seeding is the day-one value story in DECISIONS.md; on
  third-party code it mostly yields nothing.
- 2026-08-29 — **decision: cold-start from the app's OpenAPI schema, not from its tests.**
  Every FastAPI/DRF/Flask-smorest app publishes one; it is deterministic, needs no `ast`
  heroics, and carries methods, paths and parameter schemas. It replaces the fragile part
  of the seeder for evaluation purposes and pairs with intrinsic oracles, which need no
  expectations at all. Seeding from tests stays for the case it genuinely serves —
  recovering *assertions a human wrote down* — but it is no longer the only way in.
- 2026-08-29 — decision: **Path B is the critical path.** Intrinsic oracles need no
  knowledge base, run against any app, and can produce both numbers (precision on healthy
  code, detection on reverted bug-fixes) because a large share of real bug-fix commits are
  "stopped it crashing on X". Path A stays, but behind this.
- 2026-08-29 — first contact with a live third-party app (CTFd, 473 seeded workflows) found
  three seeder defects, two of them of the exact class this product exists to prevent:
  **(i)** asserts bound to steps by source position, so the ordinary "issue the requests,
  then assert" shape graded every assertion against the last call — reproduced as a CHANGE
  finding against an app correct by construction; **(ii)** *phantom steps* — any `.get()`
  read as an HTTP GET, so CTFd's `sess.get("nonce")` on a Flask session dict became a
  request the bot would actually issue: 127 of 1018 steps (12.5%), 107 expectations bound
  to requests no test ever made; **(iii)** `qabot seed` writes a knowledge base that
  `qabot run` then refuses to load (`AnchorError` on a route with no leading slash) — the
  crash is the only thing that kept (ii) from being silent.
- 2026-08-29 — fixed: `runner.py` dropped the `llm` at its only call site, so the entire
  model-verification path had never executed in production. Proven live: the demo goes from
  "1 could not be tested" to "0". Unit tests missed it because they call `verify_workflow`
  directly, passing the provider the caller forgot.
- 2026-08-29 — **open: unbound is not the same as unbindable.** The assert-binding fix
  rebound 330 of 2043 CTFd expectations (16.2%), but *all 330 became unbound and none moved
  to a different correct step* — on real code the seeder usually cannot tell, because
  responses arrive through helper functions. `step_index is None` is graded against the
  **last observation** (verifier.py:322), a fallback its own docstring says is "only
  meaningful for expectations that genuinely describe the workflow's end state". So a
  binding the seeder could not determine is still being graded against a guess. These two
  cases must be distinguished, and the second one is BLOCKED.
- 2026-08-29 — **fixed, and the most important fix so far: a run that exercised nothing
  reported as a clean bill of health.** Against live datasette, zero workflows matched the
  diff and the report read "0 findings ... None. Every expectation that could be checked
  held." That is a false green — the one failure this product's entire positioning is
  against. Reports now lead with "This run verified nothing" whenever no workflow produced
  a result. One existing test had encoded the old behavior and was rewritten to pin the
  new one.
- 2026-08-29 — **headline: impact selection cannot fire on real applications.**
  `anchors.route_decorators` matches only `@app.get("/x")` / `@router.post("/x")` — the
  FastAPI idiom `demo/app.py` happens to use. It extracts **zero** routes from CTFd's
  `challenges.py` despite its `@challenges_namespace.route(...)` decorators, and datasette
  routes via `add_route(regex)` with no decorators at all. Flask's own `@app.route("/x",
  methods=[...])` is not matched either (the attribute is `route`, not a method name), nor
  Django `urls.py`. Compounding it: real frameworks compose paths from blueprint/namespace/
  `APIRouter(prefix=...)` fragments, so even a matched decorator yields `/types`, never the
  `/api/v1/challenges/types` a test calls. And every FILE anchor the seeder emits points at
  a **test file**, while diffs touch source. Selection is therefore structurally empty on
  CTFd (300 clean workflows, 0 selected) and datasette (82 clean, 0 selected).
  The tool cannot currently do its central job — "work out which workflows a diff put at
  risk" — on any code except the bundled demo.
- 2026-08-29 — **fixed for Flask and FastAPI: workflows now anchor to application source
  through the running app's own route table** (D49). `qabot/routemap.py` asks the app which
  handler serves each URL and `inspect`s it into a file and a line span, so a diff
  overlapping that span is a direct hit on every workflow calling that path. Live numbers:
  248 CTFd routes read in 1.5s under CTFd's own interpreter, spans landing on the right
  handlers (`POST /api/v1/challenges/attempt` → `CTFd/api/v1/challenges.py:664-1068`); the
  real `ctfd_attempts.diff`, which rewrites that handler, takes the same 410-workflow
  knowledge base from **0 selected to 114 scored, 10 selected, 104 reported as
  skipped-for-budget**, and nine of the ten call the rewritten endpoint. langflow reads too
  (257 routes, 7.8s) once FastAPI's lazily-included routers are expanded — a modern FastAPI
  app keeps `include_router` routes out of `app.routes` until requested, so a naive walk
  finds only its four documentation routes.
  **Still open on this:** the tests whose whole subject is the rewritten handler rank 16th–19th,
  because direct and file hits accumulate and so breadth beats specificity; the staleness
  pass still resolves routes by decorator inference and marks CTFd workflows STALE that the
  app demonstrably serves; and datasette is still out — its `(regex, view)` router has no path
  template to read, and it fails loudly rather than guessing one.

## First measured results — datasette 1.0a38 (2026-08-29)

82 seeded workflows exercised directly against a live server (impact selection bypassed;
it is broken, see above, and "does it pick the right workflows" is a separate question
from "is what it reports real").

**Run A — server pointed at an unrelated database.** 16 CHANGE findings, and **16 of 16
were false positives**: every one a 404 on `/fixtures...`, because datasette's suite
assumes a `fixtures.db` the server did not have.

**Run B — same knowledge base, server given the fixture database its tests expect.**
CHANGE findings fell 16 → 4. All 4 remaining are *also* environment mismatch, now
configuration rather than data: two need the `sleep()` SQL function a test plugin
registers, one needs auth configured, one needs `max_returned_rows=100` (default 1000).

**The generalizable finding: seeding records assertions but not the preconditions that
make them true.** A test's assertion is only valid inside the conftest that set up its
plugins, settings, auth and data. The knowledge base captures the assertion and discards
the setup, so every derived expectation is silently environment-coupled — and a 404 where
200 was expected is indistinguishable from a real regression. `Workflow.preconditions` and
`Persona.fixture` exist in the model and the seeder populates neither.

**The intrinsic tier, which needs none of that setup, found a real bug.**

> `GET /fixtures/-/query.nonsense?sql=select+1` → **500**
> `datasette/views/database.py:1140` — `assert False, f"Invalid format: {format_}"`
> and the same at `datasette/views/table.py:1922`, so `/fixtures/facetable.nonsense` too.

Any client can trigger it with an arbitrary URL suffix; an unrecognized output format
should be 404 or 400, never a 500 `AssertionError`. Under `python -O` the assert is
stripped and control falls through to an unbound local — still a 500, less legible.
Reproduced at HEAD `1.0a38-1-g0337fba`. Found with no seeded expectation about formats,
no configuration, and no human in the loop. *(Not checked against datasette's issue
tracker; the claim is that the tool found it unaided, not that it is undiscovered.)*

**Uncapped-oracle tier so far: 1 finding, 1 true positive, 0 false positives.** n=1 is not
a rate. It needs volume across apps before it is worth publishing, and detection needs the
reverted-bug-fix experiment.

## Detection and precision — the intrinsic tier, measured

**Precision.** The 30-route sweep against unmodified datasette 1.0a38: **0 findings, so 0
false positives.** Not a vacuous zero — the same oracle, same sweep, reports a true
positive on the `assert False` format bug and catches every injected fault below.

**Detection.** Ten crash-class faults (attribute-on-None, index error, zero division,
missing key, type error) injected one at a time into request handlers across four
datasette view modules, each run against a freshly restarted server, judged by qabot's
own `RESPONSE_ORACLES` rather than a reimplementation:

| Sweep | Detection |
|---|---|
| 11 hand-picked URLs | 4/10 (40%) |
| widened to 25 URLs | 5/10 (50%) |
| every injected handler's own route (30 URLs) | **10/10 (100%)** |

**What that decomposition establishes.** Every miss was a handler the traffic never
invoked — `TableFragmentView`, `TableAutocompleteView`, `AutocompleteDebugView`,
`AuthTokenView`, `LogoutView`, all reachable only at URLs the sweep did not contain.
Once each fault's own route was in the sweep, detection was total. So:

> **The oracle detects 100% of the crash-class faults it is exposed to. Recall is bounded
> entirely by route coverage, not by the oracle.**

That is the finding with a product consequence. Effort spent making the oracles cleverer
buys nothing; effort spent enumerating and exercising routes buys everything — and
`qabot/routemap.py`, built for impact analysis, already reads the complete route table out
of the running application. The two halves compose: enumerate every route the app declares,
sweep them, and crash-class recall goes to the ceiling with a measured zero false positives.

**Caveat, stated plainly.** Injected faults are unconditional — they fire on any request
reaching the handler. Real defects are usually conditional on state or input, so 100% is
the ceiling for this fault class, not a forecast for real bugs. The one real bug found so
far (datasette's `assert False`) was also unconditional. Conditional-fault detection is
unmeasured and is the honest next experiment.
- 2026-08-30 — impact selection fixed end to end. `qabot/routemap.py` reads the route table
  from the running application (244 routes from CTFd in 1.4s, 257 from langflow), and D50
  replaced accumulate-hits scoring with dominance. Against the real commit that rewrites
  `POST /api/v1/challenges/attempt`: selection **0 → 10 workflows**, and the four tests
  written against that endpoint went from ranks 16-19 (below a budget of ten) to ranks 2-6.
  A full `qabot run` now completes against live CTFd, authenticated, with route-map selection.
- 2026-08-30 — the CTFd run's 8 findings were **8/8 false positives**, same root cause as
  datasette: an empty instance, and a workflow titled "Can a user interact with challenges
  without having joined a team?" graded while authenticated as an administrator.
  `Workflow.persona` and `KnowledgeBase.personas` are defined in models.py and referenced
  nowhere else — identity-dependent workflows run as whoever logged in. Across all three
  configurations the expectation tier is **28 findings, 28 false positives, 0 real defects**.
- 2026-08-30 — the CTFd volume run was killed before finishing; CTFd is slow enough per
  request that 349 workflows did not complete in 30 minutes, which is why it never reported.
  Replaced with the better experiment: an intrinsic sweep of the routes CTFd itself declares.
  **90 GET routes with no path parameters, swept authenticated: 1 finding, and it is real.**

> `GET /admin/export/csv` → **500**, and `?table=nonsense` likewise; `?table=users` → 200.
> `CTFd/admin/__init__.py:171` — `table = request.args.get("table")` then
> `dump_csv(name=table)`, an unguarded lookup on a user-controlled query parameter. Absent or
> unrecognized input raises `KeyError` and returns 500 where a 400 belongs.
> Reproduced at CTFd 3.8.7 (`91ced62`, the current release tag).

**Intrinsic tier across two applications: 120 routes swept, 0 false positives, 2 real
defects in released software** — datasette's `assert False` on an unknown format suffix and
CTFd's unvalidated export parameter. Neither needed a knowledge base, a fixture, a seeded
expectation, or a human. Both are the same shape: user-controlled input reaching an
unguarded operation, returning 500 where a 4xx belongs.

## Spike — the working tier against apps we do not own (2026-09-03)

Question: can browser signal capture + intrinsic oracles find real defects in AI-built
apps with **no source access**, from nothing but a root URL? Throwaway crawler in the
scratchpad (`spike/crawl.py`), footprint of a search engine: page loads only, same origin,
no forms/auth/POST, ~1 req/s, stop on 429. Route discovery in order of trust: the JS
bundle's own router config (`path:"/x"` strings — the client-side analogue of what
`routemap.py` reads from a server), then `sitemap.xml`, then `a[href]`.

Seven public Lovable-built apps:

| App | Routes found (bundle/sitemap) | Pages crawled | Findings |
|---|---|---|---|
| podprime.ai | 14 (51 / 4) | 14 | clean |
| student-os.net | 20 (38 / 0) | 20 | clean |
| challengebrew.com | 32 (111 / 18) | 20 (cap) | **3 console errors** |
| snake-survival | 4 (a[href] only) | 4 | 1 uncaught JS error |
| blueprintbuddy | 1 | 1 | — (auth-walled) |
| liquid-log-glow | 1 | 1 | — (auth-walled) |
| showcase-my-stars | 1 | 1 | — (single page) |

**Four findings that matter.**

1. **The tier works on strangers' apps. Zero false positives across ~55 healthy pages**
   (podprime 14 + student-os 20 + the clean pages elsewhere). It reproduced a real defect
   independently: `challengebrew.com/account` throws `TypeError: Cannot read properties of
   null (reading 'tier')` (at `account-xkTSMTZg.js:6:4543`) three times while redirecting a
   logged-out visitor to `/login` — the account view renders before the auth guard fires
   and assumes `user.tier`. Confirmed by loading the page directly, not just via the crawler.

2. **Route discovery is the entire game, exactly as flagged — and it is bimodal.** Range 1
   to 32 routes. Content/marketing apps expose their whole surface (podprime, student-os,
   challengebrew) and crawl richly; **auth-walled SPAs show a logged-out stranger one
   landing page and nothing else** (blueprintbuddy, liquid-log-glow → 1 page). Pulling
   route strings out of the minified bundle is what unlocked the rich ones — 51/111/38
   route literals recovered from JS. That extraction is the highest-leverage thing to build,
   and it is `routemap.py`'s idea moved to the client.

3. **Minification blunts the BUG tier.** snake-survival's uncaught error arrived as the
   message `"Wl"` — a mangled symbol, useless to a builder. The QUESTION tier fared better
   because a console error carries a stack with file:line. Source maps (which many Lovable
   apps do ship) would restore the BUG tier; without them, the highest-severity signal is
   the least actionable.

4. **For THIS buyer, the useful finding was QUESTION-tier, not BUG-tier.** The severity
   ruling I made for a merge-gate — console errors are "noticed, not called" — is wrong for
   "does my app work, explained to a non-engineer." A reproducible `TypeError` on the
   account page is precisely what this buyer needs surfaced, fatal or not. The severity
   model has to be re-cut for the vibecoder, not inherited from the CI product.

**The elephant:** the two apps that showed nothing were auth-walled, and the valuable
surface of most vibecoded apps is behind login. Reaching it means the user hands over a
test account — a real onboarding step, and the product's central UX problem.

Verdict: the pivot's technical premise holds — the working tier finds real bugs in real
strangers' apps with zero setup and zero false positives on healthy pages. The two things
that decide whether it is a product are **route discovery on auth-walled SPAs** and
**re-cutting severity for a non-engineer buyer**, and both are now concrete rather than
hypothetical. Crawler code is throwaway; the findings inform the design.
