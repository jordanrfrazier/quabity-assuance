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

## Correction: the 0-false-positive claim does not transfer to the scan (2026-09-04)

An adversarial review built twelve local fixture apps and ran the real `qabot scan` against
them. Four were **correct by construction**. It produced **three false positives across 14
routes on three distinct pages, two of them in the loudest tier** — plus four more when the
operator pastes a deep link rather than a bare origin.

1. `correct_app/inventory` — **`server_traceback` → BROKEN.** An ordinary status table.
   `page.inner_text("body")` synthesises `\t` between cells and `\n` between rows, so an
   inventory row reading "at capacity" produces `\n\tat `, the JVM stack-frame marker.
2. `correct_app/status` — **`browser_failed_request` → GLITCHY.** `AbortController` +
   `abort()`: the standard React/TanStack cleanup. Both `browser.py` and `intrinsics.py`
   document that `net::ERR_ABORTED` is the intended outcome; neither acts on it.
3. `hero_app/` — **`blank_page` → BROKEN.** An image-led landing page carrying 47 characters
   of text, whose embedded third-party chat widget throws. The report inlines its own
   screenshot of the fully rendered page directly beneath the claim that it rendered nothing.

**Why this was invisible to the earlier measurement, which is the part that matters.** The
0/120 was not wrong about what it measured; it is **not transferable**. Those 120 routes were
`HttpDriver` sweeps of datasette and CTFd — server-rendered Python apps, no browser, no client
JavaScript, no third-party embeds — and `evidence["text"]` there is the **raw HTTP response
body**. All three mechanisms above are structurally unreachable in that setting: `\n\tat `
cannot be a table artifact without rendered innerText, there is no `AbortController`, and
`blank_page` did not exist. The number was measured on the CI tier and then carried across a
driver change and a new oracle. That carry is the error.

**The honest form of the claim is one number per tier PER DRIVER**, and the browser tier has
no measurement at all. Until it does, no precision number should be published for the scan.

All three triggers are ordinary constructs — a table with an icon column, a cancelled fetch,
an image-led page with an embedded widget. None required reaching for anything strange.
Three-of-fourteen is not a rate (the fixtures were adversarial) and must not be published as
one; what it establishes is that the true number is not zero, and not zero in the BROKEN tier.

## The BROKEN tier is largely non-functional on this buyer's apps (2026-09-04)

Every source of the tier the product rests on is dead, unreachable, or false-positive-prone:

| Source (spec §5) | Reality |
|---|---|
| main document non-2xx | **never graded.** `status_of`'s result reaches only the 429 check, a display field, and `blank_page`'s guard |
| `server_error` (5xx) | **structurally dead.** `evidence["status"]` is set only by `HttpDriver`; the browser driver never sets it, so the oracle can never fire in the scan |
| `server_traceback` | fires on ordinary HTML tables (above) |
| `blank_page` | fires on correct rendered pages when a **third party's** script throws |
| `browser_server_error` | suppressed when the backend is a sibling hostname — see below |

It survived thirteen reviews because Chromium happens to log a console message for a failed
main-document load, so reports were never *empty* — only wrong about the tier and the wording.
A 404 renders as *"Glitchy — The page worked, but something on it misbehaved."*

Independently, a strategic review measured that on SPA hosting a nonexistent path commonly
returns the index shell with **200** (`podprime.ai` and `student-os.net` both do;
`challengebrew.com` 404s), so even a fixed non-2xx source would not fire on much of this
buyer's hosting.

## Three ways the scan acts on a stranger's application (2026-09-04)

All three proven against local fixtures with the real command.

**It suppresses the app's own backend and then reassures the reader about it.** A 500 from
`api.<host>` or a `*.supabase.co` endpoint — the default architecture of a Lovable app — is
dropped as third-party, because `_note_origin` learns only the **main frame's** host from
`page.url` and never a subresource's. The headline reads "No problems found" and the integrity
section states *"2 errors came from other companies' scripts on your pages (ads, analytics,
embedded widgets) and are not counted above — they are not yours to fix."* False about the
reader's own backend. Task 1 fixed this filter for the redirect case; the subresource case
survived the fix written for exactly this bug.

**It mutates state through GET links, which the form guard cannot see.** A WooCommerce-shaped
fixture with `<a href="/?add-to-cart=42">` had its cart mutated **twice** — once by
`cli.status_of`'s httpx pre-fetch, once by the browser load. Three failures compose:
`robots.txt` is honoured by plain prefix only, so `Disallow: /*add-to-cart=*` (WooCommerce's
own shipped default) is ignored, and wildcards are precisely how sites exclude mutating URLs;
`UNSAFE_WORDS` lacks "cart" and "add" while `UNSAFE_CLICK_WORDS` has "add", so the same action
is refused as a click and accepted as a URL; and the report then prints *"so those pages were
not opened"* four lines above listing that URL under Pages visited. **A rule the tool failed
to apply, reported back as evidence of compliance.**

**A scanned site can direct our traffic, and we forward whatever a bundle contains.** Every
`Sitemap:` value in `robots.txt` is fetched verbatim — unvalidated, off-origin, following
redirects. And route literals are requested with no shape check: a fixture bundle carrying
`/%2e%2e/%2e%2e/etc/passwd` and `/search?q=<script>alert(1)</script>` had both requested under
our identifying User-Agent. That is how a well-meaning scan becomes an abuse report.

## What held (2026-09-04)

Tested adversarially and did not break: form submission (the `el.form || el.closest('form')`
guard held across every run; the sentinel file was never created, and a safe button outside
the form was still clicked); 500 clickable controls on one page (whole scan 3.8s, all caps
held); HTML injected through an error message (correctly escaped everywhere); `Disallow: /`
(zero pages, NOTHING_CHECKED fired, no false green, on an app whose pages were all 500s);
HTTP 429 (stopped immediately, disclosed the stop and the unvisited paths); a title rewritten
after load (later-wins is correct). Two hypotheses were tested and **did not** reproduce:
cross-page event misattribution at the drain boundary, and third-party host taint via redirect.

**The honesty machinery works. The detection layer does not.** That is an unusual and
informative shape: the parts that say what we could not see are sound, and the parts that say
what is wrong are not.

## Field test of the shipped product: 8 real apps, 0 true positives (2026-09-04)

`qabot scan` at `abff550`, unmodified, `--max-pages 12`, default delay. Candidate list
frozen before the first run. Findings adjudicated with plain Playwright rather than qabot's
own oracles, because a finding adjudicated with the tool's own oracle is not adjudicated.

**8 apps · 62 pages visited · 2 findings · 0 true positives · 2 false positives.**

1. `challengebrew.com/.lovable/oauth/consent` — an OAuth consent route that exists only as a
   redirect target. Discovery pulled the literal from the bundle and the sweep opened it bare,
   which no visitor does; the app then rendered a deliberate "Authorization unavailable" state
   and said so on screen. Exactly the case `intrinsics.py`'s own docstring predicts — "real
   applications log expected conditions at error level constantly" — arriving as a finding.
2. `snakesurvival.com/` — `TagError`, Google AdSense's own error class, message `Il`. Blocking
   the four Google ad hosts removes it and changes nothing else. The driver suppressed six
   *other* Google events on that page as third-party; `page_errors` are deliberately exempt
   from the origin filter, and that exemption produced the finding.

n=2 is not a precision rate. What it is: on eight real applications the product made two
claims and neither survived contact with the page it was about.

**The spike's one true positive is unreachable by the shipped product — correctly.**
`challengebrew.com/account` sits under `Disallow: /account`. The throwaway crawler ignored
robots; the product honours it. **The evidence base for the entire pivot was produced by
doing something the product now rightly refuses to do.**

**One real defect, missed, and printed as evidence of coverage.** `kraflio.com/contact` —
linked three times from the home page and listed in its sitemap — renders a bare Sign In form.
The scan visited it, recorded `status 200 Sign In — Kraflio` in its own "Pages visited" table,
and said nothing. There is no oracle for *"this is the wrong page"*. That is worse than not
scanning, because the report's structure asserts these pages were checked and were fine.

**Why the oracles were never given anything to grade** — the gap is coverage, not grading:

- **Nested route fragments read as absolute paths.** challengebrew's bundle declares
  `path:"/packs"` under the `/admin` route; discovery emits `/packs`, which 404s. This is
  *verbatim* the failure logged for the CI product on 2026-08-29 (decorator fragments vs full
  paths), reincarnated in `qabot/scan/discovery.py`.
- **`_ROUTE_RE` accepts only double quotes.** Modern minifiers emit template literals, so
  ``to:`/privacy` `` is invisible. **Bundle extraction returned zero on 3 of 8 apps** — and the
  module docstring calls it "the highest-trust source available to a stranger". Nobody was told.
- **`$id` templates are visited literally** (`followable` rejects `:` and `*`, not `$`, and
  TanStack — which Lovable ships — writes `$id`). **3 of 24 sampled pages were placeholders.**
- **Alphabetical order plus a page cap starves the product.** challengebrew declared 170 paths;
  the 12 visited were `/`, the oauth route, four `/alchemy-*`, two `/ascent*`, a blog post and
  two `/community*`. Pricing, presets and the loadout builder were never opened. A site whose
  content sorts early gets scanned; one whose content sorts late does not.
- **`max_bundles=6` misses the router chunk** on code-split builds.

**C1 confirmed live on a real app.** kraflio's front end is `kraflio.com`, its API is
`kraflio-api.kraflio.workers.dev`; a 401 from `/api/brands` was counted under "errors came
from other companies' scripts … they are not yours to fix". `browser_server_error` — the only
event oracle graded BROKEN — **can never fire for an app whose API is on another host**
(Supabase, Cloudflare Workers, Firebase, an API subdomain). That is the standard architecture
of the exact buyer this product is for.

**`NOTHING_CHECKED` is miscalibrated at both ends.** It fires whenever the page budget is hit,
so podprime — which visited 12 of 13 discovered pages — was told "This scan reached almost none
of your app", and liquid-log-glow, covered **completely**, got the same sentence. Meanwhile
student-os, whose entire product is `robots.txt`-disallowed and whose application was never
touched, got **no warning at all**. The warning fires loudest on the runs that went best.

**A state-changing control was clicked on a stranger's app.** hydration-hero's
"+ Drunk 250 ml" is not in a `<form>`, so the structural guard did not apply and
`UNSAFE_CLICK_WORDS` does not contain "drunk". The scan logged 250 ml. Harmless
(localStorage), and it records that the only thing between the sweep and a write was a word
list, which is explicitly the *defence in depth* and not the guard — and it lost.

**Would the builder have found this useful?** No, for six of eight: "No problems found" is
accurate and worth approximately nothing, and for four of them it sits directly above a
warning that the scan barely looked. kraflio is worse than useless — the answer was in their
hands, formatted as evidence of coverage. The two findings would each have wasted an hour.

**What is genuinely good, stated fairly:** across the sample the tool excluded 56 third-party
events without one leaking into a finding; on 60 healthy pages it said nothing and was right;
and "What I could not check" always rendered, naming robots exclusions, unvisited paths and
the login boundary. The discipline is real. It is not yet pointed at anything a builder needs.

## Consequence, measured — and it inverts the evidence base (2026-09-04)

Precision was always the wrong question on its own. Scoring every finding a second time for
**would the builder act on it** — would fix / might fix / would ignore — produces the result
that decides this:

| Finding | Real? | Would the builder act? |
|---|---|---|
| challengebrew `/account` — `Cannot read properties of null (reading 'tier')` — **the finding that justified the entire pivot** | yes | **would ignore.** It redirects the visitor to `/login` exactly as it should; nothing on screen breaks |
| datasette `assert False` on an unknown format suffix | yes | **would ignore**, judged for a vibecoder rather than a maintainer |
| CTFd `/admin/export/csv` 500 on a missing param | yes | **would ignore**, same |
| challengebrew oauth-consent console error | no (FP) | would ignore |
| snakesurvival AdSense `TagError` | no (FP) | would ignore |
| **kraflio `/contact` renders a bare Sign In form** — linked 3× from its own home page | yes | **WOULD FIX — the only one in eight applications** |

**Every signal this design can emit is bottom-tier, and the one thing worth money is
invisible to it.** kraflio's `/contact` returns **200 OK with zero console output**. No
intrinsic oracle can see it, and not because of a bug: *an intrinsic oracle only reports what
the application declares about itself, and a page serving the wrong content declares nothing.*

That is an architectural verdict, not a defect list. The pivot rested on the finding that the
intrinsic tier was "the half that worked" — and it did work, in the sense of being *correct*.
Measured for **consequence** against the buyer it was aimed at, the whole tier is
approximately worthless: three genuine defects found across the entire evaluation programme,
and all three land in "would ignore" for this reader. The class that matters — the page that
loads fine and is wrong — has no intrinsic signal by construction.

## Safety audit of the field test (2026-09-04)

62 paths requested across 8 apps. **No traversal, injection, or over-length path. No
action-shaped URL** (`add-to-cart`, `action=`, `delete`, `vote`). One query string:
kraflio `/auth?mode=signup`, a view toggle between sign-in and sign-up forms, not a state
change. **No site published a wildcard robots rule**, so the prefix-only parser's blindness
was never exercised in the wild. Off-origin: podprime and challengebrew declared same-origin
sitemaps (files held); for the other six it is unprovable from the artefacts and was not
re-requested. **Correction to an earlier framing of mine:** a `sitemap` route count of 0 does
not mean no sitemap was fetched — only that it contributed no new paths — so more than three
of the eight had a sitemap request made against them. Bounded either way: ceiling six GETs,
floor zero, of a URL each site itself published; `followable` discards every off-origin
`<loc>` before the sweep sees it and `discover` breaks after the first sitemap returning a
body. Nobody is owed an explanation.

**The audit's own finding, which outranks its result: nothing in the tool records what it
fetched.** Questions 1 and 3 were answerable only because the report happens to list visited
paths, and question 2 only for the two apps whose `robots.txt` had been curled by hand for an
unrelated reason. A tool that drives strangers' servers and keeps no request log cannot be
audited after the fact — and the clicks audit could not be performed *at all*, because
`PageResult.clicked` is collected and never rendered. Operating on other people's
applications without a record of what you sent them is its own defect, independent of every
finding above.

**One state change did occur:** the sweep clicked "+ Drunk 250 ml" on liquid-log-glow and
logged 250 ml (client-side only). And because `report.py` never renders `PageResult.clicked`,
**there is no artefact from which to audit clicks on the other seven sites** — the traceability
the design promised exists in memory and not in the deliverable, which is exactly when it was
needed.

## The architectural verdict, tested: visitor-experience oracles on 88 apps (2026-09-05)

The 2026-09-04 verdict rested on one sentence: *"an intrinsic oracle only reports what the
application declares about itself, and a page serving the wrong content declares nothing."*
That is a claim about one oracle family. It was never tested whether *other* mechanical,
source-free signals exist for the class of defect this buyer would fix. This section tests it.

**Method.** A throwaway sweep (`scratchpad/vx/crawl.py`, not product code) with the field
test's footprint — robots honoured, same origin, ≤15 pages, 1 page/s, no forms, clicks only on
CTA-vocabulary buttons behind the product's own `_inside_form`/`_safe_to_click` guards —
recording everything a visitor could see. Seven oracles were then evaluated *offline* over the
crawl, each with its false-positive mechanism written down before the run (`PLAN.md`):

| oracle | signal | provenance |
|---|---|---|
| `dead_link` | a same-origin link whose destination renders identically to a random nonexistent path (rendered soft-404 baseline) or 404s | app-declared: the app rendered its own not-found page |
| `error_boundary` | page text is the app's own error screen ("The application encountered an unexpected error") | app-declared, in prose; invisible to `pageerror` because the boundary caught it |
| `placeholder_text` | lorem ipsum, `(123) 456-7890`, `123 Main Street`, `John Doe`, `TODO` in visible text | mechanical |
| `broken_image` | visible `<img>`, `complete`, `naturalWidth 0`, >2px wide; re-fetched with a browser UA to exclude our own identity | mechanical |
| `dead_button` | CTA-named button; after click: same URL, same DOM length, same dialogs, same scrollY, zero requests | inferred from absence |
| `mobile_overflow` | `scrollWidth > clientWidth + 8` at 390px | mechanical |
| `template_defaults` | Lovable scaffold `og:image` / description / title left in place | mechanical |
| `wrong_page` (LLM) | link label vs destination content, Sonnet, batched, "delivers / wrong_page / unclear" | **inferred** |

**Corpus** — two, because the first turned out to be mostly dead:

- **A**: GitHub code search for Lovable's build fingerprint (`lovable-tagger` in `package.json`,
  76,416 repos), first 499 → 125 live at `<slug>.lovable.app` → 40 selected. Only 8 of 40 pushed
  in the last 90 days: code search ranks old repos first.
- **B**: repository search for the Lovable README template, `created < 2026-08-01`,
  `pushed 2026-08-12..28` (8,532 repos pushed in the last two weeks alone) → 118 live → 40
  custom-titled selected. These are shipped *and* still being worked on: the buyer.
- **F**: the eight 2026-09-04 field-test apps, for continuity. kraflio's `/contact` is the
  positive control.

Every app in A and B has public source, so findings were adjudicated against the page, the
screenshot, and where useful the repository — never against the oracle.

### Results

**88 apps · 479 pages · 369 guarded clicks.** Per-oracle precision after adjudication
(A+B+F; screenshots for every dead-button pair, every dead-link destination, every error
screen and every broken image; source for the tontine routes):

| oracle | findings (deduped per site-wide element) | true | false | unverified |
|---|---|---|---|---|
| `dead_link` (rendered not-found) | 20 | **20** | 0 | 0 |
| `error_boundary` | 2 | **2** | 0 | 0 |
| `placeholder_text` | 6 | 5 | **1** (`TODO` matched Portuguese "todo", see the correction below) | 0 |
| `broken_image` | 23 | **22** | 0 | 1 (Wikimedia 403 with any UA) |
| `mobile_overflow` | 7 | 6 | 0 | 1 weak (17px) |
| `template_defaults` | 64 | 64 (literal scaffold strings) | 0 | 0 |
| `page_error` | 4 | 3 (all React #418 hydration; page renders) | 1 (AdSense, known) | 0 |
| **`dead_button`** | **24** | **11** | **13** | 0 |

The five mechanical, visitor-visible oracles — dead link, error boundary, placeholder,
broken image, overflow — produced **55 true findings and 1 false positive**
across 88 applications, with 2 unverified — and the one false positive was adjudicated *true*
by me, from the oracle's own label, until a later control exposed it (see the correction below). `dead_button` is the exception and is reported
separately: 46% precision, from five named mechanisms (the nav button for the page already
open ×4, buttons needing a microphone ×2, an already-active tab whose state is styled rather
than declared ×1, buttons that require a filled input beside them ×2, DOM-length signatures
blind to a class toggle or carousel reorder ×4). Each is mechanically excludable; none was
excluded here because the protocol was frozen before the run.

**What the "wrong content" class actually looks like in this population.** The verdict
imagined a page that "loads fine and is wrong" with no signal. In AI-built apps, wrong content
overwhelmingly *does* carry a mechanical signal, because the model that built the app
hallucinated the resource rather than mis-wiring it:

- **Links to routes the router never declared.** modern-tontine's footer links six pages
  (`/features`, `/pricing`, `/about`, `/terms`, `/privacy`, `/cookies`); `src/App.tsx` declares
  none of them and the catch-all renders `NotFound`. akeno-health links seven such pages from
  its header and nav. prompt-sculptor links six. The server says 200; the app's own not-found
  page says otherwise, and Lovable's scaffold even logs it: `console.error("404 Error: User
  attempted to access non-existent route:", location.pathname)`.
- **Images from URLs that never existed.** medicalbaise's doctor cards load five Unsplash
  photo ids that 404 — and the app's own `<meta>` CSP blocks Unsplash anyway. cottage-hero and
  saurav-nextgen the same. prompt-sculptor requests `/api/placeholder/600/400`, an image API
  the model invented; the static host returns the HTML shell. youly's partner strip shows the
  literal alt text "Logo" for Ikea and Casas Bahia.
- **Placeholders shipped as content.** `+1 (123) 456-7890` as the support number (tontine),
  `call (123) 456-7890` on an agency's About page (prompt-sculptor), `123 Main Street,
  Nairobi` as an NGO's address on five pages plus "John Doe, Executive Director" on its team
  page (yapd4africa), and `+1 (555) 123-4567` (smoke-shop).
- **Caught crashes.** prompt-sculptor `/brief` — linked as "Get Started", "AI Brief", "Start
  Your Project" — renders "Something went wrong"; learnathon's leaderboard renders "An
  unexpected error occurred" where the leaderboard should be. Neither raises `pageerror`; the
  shipped product's BROKEN tier cannot see either.
- **Dead primary CTAs.** "Explore Our Vision", "View Leaderboard", "Get Started", "Schedule a
  Visit", "Try Again" on the crashed page — buttons with nothing behind them.

**The semantic judge, measured.** On kraflio (positive control): 35 label→page pairs, 31
delivers, 1 unclear, 3 wrong_page — all three the `/contact`-renders-Sign-In defect, and no
false positive. Across corpus A: 28 wrong_page destinations, of which 20 are the 404 and crash
pages the mechanical oracles already caught; of the 8 residual, adjudicated: "Download
Portfolio PDF" → a process page with no PDF (real), "Read Full Article" → the same teaser
listing (real), two priced product links → "Coming Soon" placeholder pages (real), a map link
→ no map (real); false: "Schedule a Demo" → a generic contact form, "Free Power Infrastructure
Assessment" → an IT-health page, a 404 page's "Return to Dashboard" → the marketing home.
Provenance-capped, as it should be, it adds a small number of real findings at 5-of-8
residual precision. It is the only oracle here that could have found kraflio, and it did.
Across corpus B: 9 wrong_page destinations, none overlapping a mechanical oracle — 6
distinct defects on 5 apps, 5 real and 1 false. Real: a product category filter that returns
the same catalogue for Beverages, Cheese and everything else (the rendered text of three
category URLs is byte-identical to the unfiltered `/products`); "View All →" on three brand
cards leading to a single brand page; two "coming soon" pages behind nav links (i6-website,
roll-call); and "Explorar serviços" landing on a signup form — the kraflio pattern, on an
app pushed a week before the scan. False: "Back to Services" → the home page. 14 unclear.

**Consequence, per app, scored by the frozen protocol** (would fix = the owner of a live
product would change it this week):

| corpus | apps | ≥1 would-fix finding | might-fix only | template-only or nothing |
|---|---|---|---|---|
| A (mostly abandoned) | 40 | **10** (25%) | 7 | 23 |
| B (shipped, actively pushed) | 40 | **6** (15%) | 5 | 29 |
| B2 (same selection, pushed Jul 25–Aug 11; scanned after the protocol froze) | 60 | **6** (10%) | 5 | 49 |
| F (field test, polished) | 8 | 1 (kraflio, judge only) | 0 | 7 |

The would-fix findings in B are the ones that matter, because their owners pushed code within
the last three weeks: a school website whose "Schedule a Visit" does nothing; a creative
studio whose "Get Started" does nothing and whose merch and scripts pages fail CORS against
its own API; a doctor directory whose photos are all broken because of its own CSP and whose
layout is 475px wide on every phone; a furniture-assembly marketplace with blank partner logos; a cigar shop with a placeholder phone and address; a
food distributor whose category filter filters nothing.

### What this changes

**The 2026-09-04 architectural verdict is falsified as stated.** "Wrong content declares
nothing" is true of the intrinsic-oracle family and false of the product: in this population
wrong content is, most of the time, a hallucinated resource, and a hallucinated resource is
mechanically detectable with app-declared provenance — the app's own not-found page, its own
error screen, its own broken `<img>`. The scan was built on the wrong oracle family, not on
the wrong idea. Five source-free oracles reach 0 confirmed false positives over 88 apps, and
a quarter of a random sample and 12 of 100 actively-maintained apps carry something the owner would fix.

**What the verdict got right survives.** The consequence test with owners has still not been
run; "would fix" above is my judgement under a written protocol, not a builder's action. The
login boundary is real and bigger than the field test suggested: 24 of 40 active apps exposed
one page to a stranger — 12 login walls, 11 single-page sites whose nav is in-page anchors,
and one whose robots.txt disallows everything. And ArgosX's free tier lists broken links, so `dead_link` alone is
not a wedge; the combination — hallucinated images, shipped placeholders, caught crashes, dead
CTAs, each with a screenshot and a one-line "your visitors see this" — is the thing to
test against the competitor, which nothing here has done.

**Two defects in the tool this experiment exposed, for the record.** The browser driver
attributed the *baseline probe's* console error (`…non-existent route: /qabot-probe-…`) to a
product page loaded four navigations later on postlaneweb — an attribution failure the
2026-09-04 review tested for and could not reproduce; it reproduces. And `dead_button`'s
DOM-length signature is blind to any change that preserves length (class toggles, theme
switches, carousel reorder): a signature must hash content, not measure it.

**`dead_button`, re-measured after fixing what the adjudication named.** The probe was
changed in three ways — a content hash of the body instead of its length, a skip for buttons
named like the page already open, a skip for buttons beside an empty text input — and the 16
apps that had produced dead-button findings were re-crawled. All 11 true findings survived, 5
of the 13 false ones vanished, nothing new appeared: **46% → 58%**. Two of the remaining eight
are one-line fixes not made here (normalise "Sign Up" against `/signup`; hash the `<html>`
element so a theme toggle counts as a change). The other six — microphone buttons, an active
tab styled rather than declared, focus styling on a one-page nav — need a vocabulary or a
screenshot diff, and the honest ceiling for this oracle without those is about two-thirds.
It stays reported apart from the mechanical five.

**Safety audit of the experiment's own clicks.** 567 clicks across 104 crawls, every one
logged with name, page, before/after signature and request count — the record the 2026-09-04
audit said the product lacks. The form guard held on every click. But the experiment's CTA
vocabulary was wrong: it *admitted* "Join", "Sign Up", "Register", "Book", "Schedule",
"Download" and "Bookmark" as navigational, and the product's `UNSAFE_CLICK_WORDS` does not
contain them either, so 27 "Join" clicks, 13 "Sign Up" clicks and 12 "Bookmark verse N"
clicks went through. Effects, from the log: the four "Bookmark verse" clicks toggled
client-side state with zero requests; every "Join", "Schedule", "Book a Demo", "Download
Brochure" and "Start Your Free Trial" click produced zero requests (dead, or a modal); the
only clicks that produced requests were navigations loading their own page and one media
fetch after "Start test". No write was sent, and that is luck plus the form guard, not the
vocabulary. `UNSAFE_CLICK_WORDS` needs "signup", "register", "join", "bookmark", "book",
"schedule", "download" and "start" before the product clicks anything on a stranger's app
again.

**Control: the 2026-09-04 adversary apps, re-run under the visitor-experience oracles.**
Eleven local apps built to trip oracles (`scratchpad/adversary/`). `correct_app`: 0 findings,
judge 4/4 delivers. `shop_app`: 0 clicks — every control is inside a form, and the guard
held. `late_app`, `locked_app`, `split_origin_app`: 0 visitor-experience findings. Two
findings need a ruling. `hero_app` — described in its own docstring as "a correct, image-led
landing page" — carries a fixed `<img width="600">`, and `mobile_overflow` reports 608px on a
390px screen; the oracle is right about the pixels and the author would call the page
correct, so **`mobile_overflow` fires on any fixed-width element wider than a phone, deliberate
or not**, and that is its false-positive mechanism, now observed. `silent_app` — "broken for a
visitor in five ways, only one of which is a 5xx" — exposed a coverage gap instead: `/gone`
(404 behind the app's own link) and `/boom` (500) were found, but `/loop` (redirect loop),
`/hang` (never responds) and `/empty` (200 with a white screen) were *recorded* by the crawl
and reported by nothing. Two oracles were added offline, `load_failed` (the browser gave up:
loop, timeout) and `white_screen` (2xx, no text, no visible image, under 3KB), and re-run over
every crawl: they catch all three on `silent_app`, fire on nothing in the 88 real apps except
one link to a PDF ("Download is starting" — a file link working as intended, now excluded by
name), and cost nothing. The product's `blank_page` requires an uncaught error to fire; a
white screen with no error is exactly the case it misses.

**Corpus B2: 60 more active apps, scanned after everything above was written.** Same
selection as B from the preceding push window (created before Jul 15, pushed Jul 25–Aug 11),
crawled with the v2 probe, oracles and protocol frozen. 244 pages, 134 clicks, 29 apps with
more than one page. Mechanical findings, adjudicated from screenshots: `dead_link` 5/5 (two
product cards → rendered 404; three Hebrew nav links → rendered 404 that the exact-signature
soft-404 match *missed* and a 200-character prefix match catches, added and re-run: +3, no
new false positives anywhere), `broken_image` 2/2 (a header logo showing its alt text on
three pages; one hallucinated Unsplash id), `placeholder_text` 1/1, `error_boundary` 3/3
(a shop whose every page carries "Supabase connection failed — demo mode" and whose home is
a "Connection Failed" configuration screen; a dashboard that cannot reach
`localhost:3001` — the app was published pointing at its author's machine),
`mobile_overflow` 11 true + 1 weak (a lead table 4,168px wide on a phone), `dead_button` 6/7
(Enterprise "Contact Sales" on a pricing page; "Download CV" on a portfolio; all three
home-page CTAs of a furniture studio; one false: a scroll-to). Judge: 13 wrong_page
destinations, 2 already mechanical, and of the 11 residual 10 real — an empty blog behind
"View All Articles", "Read Article" → "Blog Post Not Found" ×2, three category filters that
return the laptop list for Desktop PCs, Monitors and Peripherals, a "Forecast Arena" that
redirects home — and 1 false ("Register for … Workshop" → a contact form, the same shape as
the two false calls in A). **Six of sixty apps carry a would-fix finding**, all of them the
kind a visitor hits on the first click.

**Across the two active corpora (100 apps): 12 would-fix, 10 might-fix, 78 nothing beyond
scaffold metadata.** That is the number to carry forward, and its error bar is wide; it is
also a floor, because 41 of the 100 showed a stranger one page.

**Correction: the Lovable host is not always the product (2026-09-05, from Jordan's
review).** The corpus was harvested at `<slug>.lovable.app`, Lovable's preview host. Four
of the twelve would-fix repos declare a different homepage, and one links to a custom
domain from its page. Crawling those five real deployments: `website-gga5.vercel.app` is a
dead 404, so the Lovable host *is* the live site and its finding stands; `medicalbaise
.vercel.app` is a larger, different build (the owner moved to Cursor in August) with none
of the Lovable host's broken images or overflow — **void**; `priyanka-portfolio-delta
.vercel.app` is a different portfolio with no "Download CV" button — **void**;
`smoke-shop-hub.vercel.app` is a different shop that ships its own placeholder address,
"123 Main Street, Suite 100, Anytown, USA" — same class, real site; `redvisionmusic.com`,
the studio's production domain, loads five merch images from Unsplash ids that do not exist
— same class, real site. So: the 12-of-100 consequence figure is overstated by the share of
owners who have moved on from the preview host, which in this check was 2 of 5; the defect
*classes* reproduce on production domains; and a corpus for the next round has to be built
from declared homepages and custom domains, not the builder's preview host. The
"actively maintained" label was also too strong: the search window selected repos with a
push on one of two days, and the commit histories show many were touched once after months
of silence. "Touched in the window" is what it guarantees.

**Correction, and what it says about adjudication.** Running the oracles over a third corpus
(B2, 60 more actively-pushed apps, below) produced five `TODO` findings in Portuguese and
Spanish copy — "todo o Brasil", "Todo mi trabajo": the pattern was case-insensitive and
*todo* means *all*. That also means the youly finding above, which I had scored "TP, would
fix: literal TODO in production copy", was false, and I scored it from the oracle's printed
label rather than from the page. The table and the counts above are corrected; the pattern
is now case-sensitive; and the lesson is the one this file keeps relearning: a finding
adjudicated from the tool's own output is not adjudicated.

**Artefacts.** `qa-artifacts/vx-2026-09-05/` (gitignored, local): `crawl.py`, `oracles.py`,
`judge.py`, `aggregate.py`, `tally.py`, `PLAN.md` (protocol), `judge_cache.json` (every
verdict), `runs/<app>/crawl.json` for all 88 apps (screenshots stayed in the session
scratchpad; the adjudicated contact sheets are in `runs/adjudicate/`),
`runs/adjudication_{A,B,B2}.json`, `corpus/meta.json` (repo, last push, corpus per app),
`runs/outreach_drafts.md` (twelve owner messages, drafted, not sent).

## User journeys on Langflow PR #14913 (2026-09-05)

Spec `docs/superpowers/specs/2026-09-05-user-journeys-design.md`, plan
`docs/superpowers/plans/2026-09-05-user-journeys.md`, code `spikes/journeys/` (28 tests),
artefacts `qa-artifacts/journeys-2026-09-05/`. Two local Langflow instances from one
checkout, same frontend build, both started with `LANGFLOW_LAZY_LOAD_COMPONENTS=true
LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false`: **fixed** at the merge commit `84a3649` on 7860,
**broken** at its parent on 7861. Ground truth from the server logs: the broken build skips
every starter project at startup ("unavailable components: ChatInput, ChatOutput, …") and
serves 0 flows; the fixed build serves 26 and skips one starter of its own, "Research
Translation Loop" (ArXivComponent unavailable) — a real, unrelated finding about 1.12.1.

**Authoring (the deliverable a human grades first).** One model call from the diff, the PR
text, the three settings names the diff touches, and five Playwright specs picked by token
overlap. Seven journeys came back. Journey 1 is the happy path the fix protects, names both
settings as preconditions, and uses the product's words — Starter Project, Basic Prompting,
Playground, the exact "Flow build blocked: custom components are not allowed" string. J2–J7
cover registry parity, the per-component merge, same-name override, lazy hydration, path
equivalence, and that the gate still blocks a genuine custom component — each traced to a
hunk or a sentence. Two defects in the authoring: the spec selector's token overlap chose
irrelevant specs (duplicate-DOM-id and MCP tests), so the author's picture of the UI came
from the diff alone; and it therefore described a first-run Langflow that does not exist —
"open the Starter Project folder from the projects sidebar" — when a fresh install shows a
"Welcome to Langflow / Create first flow" screen and reaches the starters through a template
picker. Jordan's read of the journeys is the grade that matters here and is still owed.

**Preconditions as contracts.** The first walk failed J3 and J4 on *both* instances because
neither has a custom components path: an unmet precondition read as a defect. The walker now
takes `--env KEY=VALUE` for what the instance was started with and blocks, before any
action, a journey whose `preconditions.settings` this instance does not satisfy, naming the
setting. Second walk: J2–J6 blocked with reasons like "LANGFLOW_ALLOW_CUSTOM_COMPONENTS must
be 'true' but this instance has 'false'; settings.components_path is required". That is the
honest shape: five of seven journeys need a differently configured server, and the report
says so instead of failing them.

**Walking.** Three walker defects found and fixed by looking at screenshots rather than
verdicts: the driver's `goto` returns on the SPA shell ("Loading…"), so the model was
deciding from a splash screen — the walker now waits for network idle and then for the
visible text to hold still, and screenshots after that; an API JSON page whose Python source
contains "Unable to connect to the Ollama API" was read as the app's error screen — the
error-text check now runs only on `text/html` documents; the aborted first run had created a
"New Flow" on both instances and contaminated the second — both were restarted from empty
state. One walker defect remains and is the finding of the run: **the walker stood on the
discriminating screen and walked past it.** After "Create first flow", the fixed instance
shows *"Or start from a template: Simple Agent · Vector Store RAG · Browse more…"*; the broken
one shows only *"Blank Flow"* (`fixed/shots/J1/settled_01_02.png` vs
`broken/shots/J1/settled_01_02.png`). Because the step said "folder", the walker clicked on
to the Starter Project folder, which on both instances holds only the flow it had just
created, and the judge failed step 1 on both for the same non-discriminating reason. The
regression was visible in one screenshot pair and was not reported as such.

**Scorecard against the spec's five questions.** Journeys sensible: yes, with one wrong UI
assumption, pending Jordan. Author understood the change: yes — both settings named, the
protected behaviour named, the exact error string named. Walker can walk: 3 of 3 actions
completed per attempt, 0 driver errors after the settle fix; it cannot yet judge purpose
over wording. Regression caught: **visible in evidence, not in verdicts** — both instances
FAIL step 1 by inference (QUESTION), so the tool did not discriminate. Quiet on the fixed
build: no — one false FAIL, the same one. Environment gaps the journeys did not state: no
model API key, so a build reaching the model node fails on the fixed build too; the
"Flow build blocked" gate the PR describes never had a flow to fire on, because the broken
build's symptom is upstream (no starters at all).

**What this says.** Journeys as the unit are right: seven pages of steps a person can read,
argue with and repeat, five of them correctly declared unwalkable on this server, and one
screenshot pair a human can settle in a glance. The two missing pieces are exactly the ones
the spec predicted: product knowledge for the author (the right specs, or a crawl of the
running UI before writing), and a walker that judges the step's purpose on the screen where
it was served rather than the screen its wording named. Neither is a research problem.

**Not done.** Jordan's grading of the journeys; a human-corrected step 1 re-walked to see
whether the verdicts then discriminate (the product's intended loop: a person edits the
journey, the tool re-walks it); J7 with a real hand-edited custom component; the
ArXivComponent starter skip reported upstream. Instances left running on 7860/7861.
