# Design: `qabot scan` — checking an app you were only given the URL of

Status: proposed, 2026-09-03. Supersedes nothing; sits alongside
[the QA-bot design](2026-08-27-qa-bot-design.md), which describes a different product
for a different buyer.

Evidence behind every claim here is in [EVAL.md](../../EVAL.md) — the CI evaluation and
the 2026-09-03 spike against seven public Lovable-built apps.

---

## 1. What this is, and why it is not the other thing

The merge-gate product asks *"did this diff break a workflow someone wrote down?"* It
needs a knowledge base, a diff, fixtures, and an engineer to read the answer. Measured
against real repositories, the half of it that depends on seeded expectations produced
28 findings and **28 false positives**, because a seeded assertion is silently coupled
to the fixtures, configuration and identity of the test that produced it.

The half that worked needed none of that. Intrinsic oracles — findings that rest on the
application declaring its own failure — returned **zero false positives across 120 routes
of two applications** and found two real defects in released software.

`scan` is that half, pointed at a different buyer: somebody who built an app with an AI
and cannot read a stack trace. They have no test suite to seed from, no fixtures, no
`conftest`, and no engineer. Everything that made the expectation tier fail is absent by
construction, and everything the intrinsic tier needs is a URL.

**The question it answers, in the buyer's words: "is my app broken for the people I'm
about to show it to?"**

### Scope, decided

| | v1 |
|---|---|
| Access | **Anonymous only.** No credentials, ever. |
| Depth | **Load + safe interactions.** Click what does not obviously mutate; never submit a form. |
| Delivery | **One-shot scan → a shareable report at a permanent link.** No accounts, no scheduling, no diffing. |

Out of scope and deliberately so: authentication, form submission, account creation,
scheduled re-scans, run history, deploy hooks, CI integration. Each is a plausible v2;
none is needed to find out whether v1 is worth anything.

---

## 2. Boundary: what is reused, what is new, what changes

Roughly a third of the existing codebase carries over, and it is the third the evaluation
vindicated.

**Reused unchanged.** `qabot/intrinsics.py` (oracle tables, aggregation, the
`declares_failure` tier predicate) and `qabot/models.py`'s `Observation` and `Finding`.

**New, in a `qabot/scan/` package.** Discovery, sweep orchestration, a scan-specific
severity map, source-map resolution, and an HTML report.

**Not reused.** `routemap.py` needs an importable application and we will never have one
— its *idea* survives as bundle parsing (§3), none of its code does. `seeder`, `impact`,
`anchors`, `verifier`, `planner`, `testgen` and `llm` are all knowledge-base machinery
this product has no knowledge base for. `reporter.py` renders a PR comment, which is the
wrong artifact for a reader who does not use pull requests.

### Two changes to `BrowserDriver`, both of which fix latent bugs

I claimed in design discussion that `scan` would not touch the driver. That was wrong.

**(a) The origin filter must follow redirects.** `_is_noise` compares each event's host
against the host parsed from `base_url` at construction. Measured on a real app:
`snake-survival.lovable.app` redirects to `www.snakesurvival.com`, so every console error,
failed request and 5xx it produced was suppressed as third-party. Only its uncaught
exception survived, because `page_errors` are deliberately exempt from the rule. The
filter's stated purpose is "an analytics tag exploding inside a third-party script is not
a defect this team can fix" — a vanity domain the app itself redirected us to is not a
third party, and treating it as one turns the run silently empty.

Fix: the driver tracks the **effective** origin — the host actually serving the page after
navigation — and compares against that. Every host the app has redirected us to during the
run counts as the app. This is strictly more correct for the CI product too; it simply
could not arise there, because `base_url` is a server it controls.

**(b) `reset_path` becomes `str | None`.** It is currently a plain `str` defaulting to
`/reset`, so `reset()` would POST to a stranger's application. `HttpDriver` already takes
`str | None` for exactly this reason (see `NO_RESET_LIMITATION`); this brings the browser
driver into line. `scan` always passes `None`, and says so in its report.

---

## 3. Discovery — the component that decides whether any of this works

The spike's central measurement: **route discovery is bimodal, and it determines
everything.** Across seven apps the number of routes found ranged from 1 to 32, and the
findings tracked it exactly. Apps where discovery worked were checked; apps where it
returned one page were not checked at all, and a report saying "I found nothing" about an
app we never entered is the false-green failure this codebase exists to refuse.

Four sources, in descending order of trust:

1. **The JS bundle's own router configuration.** An SPA ships its route table to the
   browser; route literals (`path:"/x"`, `to:"/x"`) can be recovered from the minified
   bundle. This is `routemap.py`'s principle — *ask the application what it serves rather
   than inferring it* — moved to the client, and it is what separated the apps that
   crawled richly from the ones that did not: 51, 111 and 38 route literals recovered
   from three real bundles.
2. **`sitemap.xml`**, when present. Authoritative and cheap.
3. **`robots.txt`** — read for `Sitemap:` directives and honoured for exclusions.
4. **`a[href]` on the root page.** The fallback, and on an SPA landing page it finds almost
   nothing, which is why it cannot be the only source — but it is the *only* source for a
   server-rendered site, and one measured app in the spike yielded all four of its pages this
   way with zero bundle routes and no sitemap.

   **Scoped to one hop, deliberately.** Discovery is a pure, browser-free unit, which is what
   lets it be tested without Chromium; reading anchors from every page as it is visited would
   require a live browser and would move the paths list out of `Discovery`, taking the
   per-source counts with it. So links rendered by JavaScript are not seen, and a page two hops
   from the root is not reached. Both are real limitations of v1 and are stated in the report
   rather than papered over. One hop was empirically sufficient for every app measured in the
   spike.

Discovery is a distinct, separately testable unit: `discover(root_url) -> Discovery`,
where `Discovery` carries the paths **and the per-source counts**. The counts are not
telemetry — they are how the report tells the reader whether the scan saw their app or
just its front door, which is the difference between a trustworthy "all clear" and a
worthless one.

**Never followed:** off-origin URLs; paths matching `logout|signout|delete|remove|cancel|
checkout|pay|purchase|unsubscribe`; route *patterns* containing `:` or `*` (a template is
not a page); asset extensions.

---

## 4. Sweep

For each discovered path, in a single browser context:

1. Fetch the main document once over HTTP to record the status a plain client sees.
2. `goto` the path through `BrowserDriver`, then wait for network idle (bounded), then a
   `read` to collect events that settled after load. Merge both observations' event
   bundles — a late XHR failure belongs to the page that issued it.
3. Perform **safe interactions**: click elements whose accessible role is a tab, a
   disclosure, a menu item, or a button whose accessible name does not match the unsafe
   vocabulary above, then re-read. Never `fill`, never `select`, never submit.
4. Screenshot.

Budget: a page cap, a per-page timeout, a polite delay, and an immediate stop on HTTP 429.
The footprint is deliberately that of a search-engine crawler, and §8 says why that is the
line.

Safe interaction is where the design is most likely to be wrong, and it is scoped to be
cheaply reversible: the unsafe-name vocabulary and the allowed roles are two constants,
and the sweep records every control it clicked so a surprising finding can be traced to
the click that caused it.

---

## 5. Grading — re-cut for a reader who cannot read a stack trace

The existing severities (`BUG`, `REGRESSION`, `CHANGE`, `QUESTION`) are pull-request
words, and their ordering is epistemic: how much may we *claim*, given where the
expectation came from. That ordering was right for a merge gate and is wrong here.

The spike settled it empirically. The single most useful thing found across seven apps was
`challengebrew.com/account` throwing `Cannot read properties of null (reading 'tier')`
while redirecting a logged-out visitor — and under the CI severity map that is a
**console error at QUESTION**, "noticed, not called". For a builder asking whether their
app works, that is the headline, not a footnote.

So `scan` keeps the oracles and replaces the ordering. Its axis is **visitor impact**:

| Scan severity | Means | Sourced from |
|---|---|---|
| **Broken** | A visitor cannot use this page. | main document non-2xx; `blank_page`; 5xx from the page's own requests |
| **Glitchy** | It works, but something failed underneath. | uncaught exceptions that left the page rendered; console errors carrying a stack; failed requests including broken images; links to routes that 404 |
| **Noted** | Observed; may well be intentional. | everything else the oracles emit |

**Where the new severity lives.** `Finding.severity` is typed to the CI enum and cannot
hold `Broken`. Rather than fork `Finding` or widen that enum, grading is a *pure function
over findings* — `scan_severity(finding) -> ScanSeverity`, a lookup on `finding.oracle`
(plus the `blank_page` conjunction). Findings stay exactly as `intrinsics.py` produced
them; the scan severity is derived at report time and never stored on the model. This is
why the CI product is unaffected, and why the mapping can be re-cut later without
migrating anything.

Three properties this must keep from the CI product, because they are what makes a report
worth reading:

- **The mapping is mechanical**, from oracle name to scan severity — a lookup, never a
  judgement about prose. A rate that moves when someone rewords a sentence is not a
  measurement.
- **`intrinsics.py` is not modified.** The scan package owns its own map. The CI product's
  epistemic ordering stays intact for the CI product.
- **Nothing is silently dropped.** Suppressed-event counts and unvisited routes appear in
  the report.

### One new oracle: `blank_page`

For this reader, "an uncaught exception occurred" is jargon; "this page is blank" is the
finding. Conservative by construction, and it fires only on the conjunction: main document
2xx **and** an uncaught exception occurred **and** after network idle the body carries
less than a threshold of text. Each conjunct is mechanical, and the combination is close
to unarguable — a page that returned OK, crashed, and rendered nothing is broken by any
definition. It lives in the scan package, not in `intrinsics.py`, because it is the only
oracle here that reads a *combination* of signals rather than one.

### Source maps

The spike found the severity ceiling inverted: our highest-severity signal was our least
actionable. `snake-survival`'s uncaught exception arrived as the message `"Wl"` — a
mangled symbol. Meanwhile console errors carried real stacks with file and line.

Where an app ships `.map` files (many do), resolving a minified frame back to original
file, line and symbol is the difference between a finding a builder can act on and noise.
Fetch the map for the frame's bundle, resolve, and **fall back to the minified frame with
that fact stated** — never silently present an unresolved frame as if it were resolved.

**Status: built and tested, not yet wired into the report.** `qabot/scan/sourcemaps.py`
implements resolution and the honest fallback described above, against its own test
suite. Connecting it to `render_html` needs network access during rendering to fetch a
`.map` file, and `report.py` being a pure function of a `ScanResult` — no network, no
filesystem beyond an already-captured screenshot path — is a stated design property this
codebase is not breaking to land one feature. Where that fetch belongs (in `sweep`,
resolving frames as findings are produced, so `report.py` stays pure and receives
already-resolved text) is an open design question, not a bug in the module as it stands.
See `docs/DECISIONS.md` D52.

---

## 6. Report

A **single self-contained HTML file** — no external assets, screenshots inlined — written
for someone who does not use GitHub. `qabot scan` writes it to disk; the "shareable link"
half of the delivery model is hosting, and **hosting is out of scope for v1**. A file the
builder can open, send, or drop anywhere is enough to find out whether the report is worth
sharing at all, and it defers every question about accounts and storage. Structure follows from the severity axis: what is broken, what is glitchy, what
was noted, and then — carried directly from this codebase's founding rule — **what could
not be checked**.

That last section is not an apology, it is the product's integrity. Under an
anonymous-only scan there is a great deal we cannot see, and a report that quietly omits
it is the false green again in a new costume. It states plainly: pages behind a login were
not reached; forms were found but not submitted; *these* specific routes were discovered
but not visited because the budget ran out.

Each finding carries: a plain-language statement, the URL, a screenshot, the technical
detail underneath (collapsed), and — where we can say it — what to do about it.

The report is a pure function of the run's findings, so it is testable without a browser.

---

## 7. Module layout

```
qabot/scan/
  discovery.py   root URL -> paths, with per-source provenance and counts
  sweep.py       drive one app: budget, safe interactions, evidence collection
  grading.py     oracle -> scan severity; the blank_page oracle
  sourcemaps.py  minified frame -> original file/line/symbol, or an honest failure
                 (built, tested, not yet wired into the report -- see §5)
  report.py      findings -> a self-contained HTML page
  cli.py         `qabot scan <url> --out report.html`
```

Each is independently testable; only `sweep` needs a browser. Discovery, grading,
source-map resolution and reporting are all pure functions over data, which is deliberate
— it is what lets the expensive part be tested once and the cheap parts thoroughly.

---

## 8. Operating on applications we do not own

This is the design constraint with the least engineering in it and the most consequence.
Every scan drives somebody else's live production application, and the people who built
these apps did not ask us to.

- **Read-only in effect, not merely in intent.** No form submission, no account creation,
  no `POST` from the driver, and no request to `/reset`.
- **A crawler's footprint**: bounded page count, a delay between pages, an immediate stop
  on 429, `robots.txt` honoured, and an identifying User-Agent.
- **Never a security tool.** No probing for vulnerabilities, no fuzzing, no attempts at
  auth. It visits pages a visitor could visit and reports what the app said about itself.
- **The spike's own findings** are recorded in EVAL.md as evidence about the tool, and
  the affected apps have not been contacted; whether to report a defect upstream is the
  operator's decision, not the tool's.

---

## 9. Testing

- **Discovery, grading, source maps, report**: pure unit tests over fixture data, including
  real minified bundle excerpts captured from the spike, so the route-literal extraction is
  tested against what real bundles actually look like rather than what we imagine.
- **Sweep**: against a locally served fixture app built to break in specific ways — a page
  that throws, one that renders blank after throwing, one whose XHR 500s, one with a dead
  link and a broken image. Marked `browser`, following the existing marker precedent.
- **Driver changes**: the redirect-origin fix needs a test with two hosts, which the local
  fixture server can provide by binding two ports.
- **The honesty property, pinned**: a scan that discovered only one route must not render
  as a clean bill of health. This is the same regression `test_a_run_that_exercised_nothing
  _says_so_instead_of_reading_as_a_pass` pins for the CI product, and it is the single most
  important test in this design.

## 10. What would tell us this is wrong

- **If discovery stays bimodal**, the product only works on content-forward apps and the
  auth question (§1, deferred) becomes v1 rather than v2.
- **If safe interactions cause a single unintended mutation** on somebody's app, the
  interaction scope was wrong and reverts to load-only.
- **If reports are not shared**, the distribution thesis — that "it found 3 bugs on my app"
  is a screenshot people post — is false, and the wedge is not a wedge.
