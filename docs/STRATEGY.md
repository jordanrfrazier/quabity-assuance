# Market position

Living document. Where this product can win, what the evidence says, and what would
change the answer. Design decisions live in [DECISIONS.md](DECISIONS.md); this is the
case for *why* to build it at all.

Last substantive update: 2026-08-28.

---

## How this was produced, and what it cannot tell you

Five parallel research lanes, each briefed to **falsify** the hypothesis rather than
support it: buyer demand, incumbent vendor audit, emerging agentic entrants, technical
frontier and oracle literature, and a deep dive on Ranger. Every lane was told that
disconfirming evidence was the most valuable thing it could return, and to report gaps
rather than fill them.

**Hard limits on the demand evidence — read before trusting anything in §4:**

- **Reddit was completely inaccessible** (blocked to the fetch agent; mirrors 403). Zero
  primary r/QualityAssurance, r/softwaretesting or r/devops data. That is where the
  harshest voice lives, so the demand picture is missing its angriest quartile.
- **G2 review *text* was 403 on every fetch.** Aggregate counts and ratings only.
- **No findable user voice at all** for Functionize, Autonoma, Ranger, Bug0, or Momentic.
  Marketing only. An empty section is reported as empty.

What we did get at depth: four Hacker News launch threads comment-by-comment, ~145
long-form Capterra/SoftwareAdvice reviews across mabl / QA Wolf / testRigor, two large
vendor-neutral surveys (Capgemini WQR 2025-26 n=2,000+ execs; Ranorex Pulse 2026 n≈4,000),
vendor documentation sites, and primary research literature.

---

## 1. The original hypothesis, and how it fared

We believed the unmet need was: **(a)** findings graded by the *provenance* of the
expectation they violate, **(b)** "BLOCKED / could not test" as a first-class outcome,
**(c)** generated regression tests only from verified passes, and **(d)** detecting where
documentation and behavior disagree.

| Bet | Verdict |
|---|---|
| (a) Provenance-graded severity | Technically unoccupied, commercially unasked-for |
| (b) BLOCKED as first-class | **Survives — strongest pillar, once repositioned** |
| (c) Tests only from verified passes | Ranger shipped it — but buyers want it most |
| (d) Docs-vs-behavior contradictions | **Cut** |

---

## 2. What survived

### The anti-false-negative guarantee

**The voiced trust fear runs opposite to our assumption.** Teams do not fear noisy red
builds; they fear falsely green ones. The canonical scenario recurs across sources: a
"Pay now" button disappears due to a regression, self-healing binds to a visually similar
button, the test passes, the bug ships. The field's converged rule is that healing may
touch *element discovery* but must **never heal a broken assertion**.

This is the category's named, acknowledged failure mode — not our inference. BrowserStack
documents it against their own product:

> "Sometimes, self-heal might adjust a step and let the test pass even though there's an
> underlying issue in your app. Always review test execution results and the healing
> thoughts with logs to make sure the application itself is working as expected."

And the best-funded competitor has the flaw structurally: **Meticulous silently abandons
oversized recording sessions** to protect UX, so coverage goes quietly lossy in heavy
stateful flows — exactly the valuable ones — with nothing surfacing it.

**Position: "green means we verified it, not that we couldn't check."** Buyers already
have the vocabulary and the fear. Do not sell it as a novel outcome enum — *Blocked* has
been a standard manual test status for decades and reads as table stakes restored. Sell
the guarantee, not the enum.

### Oracle independence — the Ranger gap

Ranger targets our exact job (verifying a feature that has never executed) and its oracle
is **written by the coding agent, before it writes the code**. From their docs:
*"scenarios are generally written by the coding agent."* The agent authors the rubric,
implements against it, a second agent grades it, and the loop terminates on the agent's
own criteria. Human review is downstream and advisory.

They have not recognized this as a problem. A grep of their full 432KB documentation
corpus for *independent, bias, optimis, overfit, false positive, hallucin, grading*
returned **zero conceptual hits**. They market it as the feature. Their verification
separation exists for **context economy**, not independence — the verifier never sees the
diff, codebase, or ticket, making it *less* able to catch a wrong-but-self-consistent
interpretation.

The failure mode is invisible and self-reinforcing: a misunderstood requirement yields a
scenario encoding the misunderstanding, code satisfying it, and a green verdict with
persuasive screenshots. **The evidence bundle makes a wrong verdict more convincing.**

This is corroborated by research: *"Building to the Test: Coding Agents Deliver What You
Check, Not What You Requested"* (arXiv, June 2026) finds agent self-assessment
substantially more optimistic than independent external evaluation.

**This is the clearest technical opening we found.** It is also exactly what the original
brief's step (c) — clarifying intent *before* implementation — was for, and what the
provenance ladder's top tier encodes: a human said this must hold, independent of what
got built.

### Provenance grading — as mechanism, not pitch

Zero counterexamples across twelve vendors. Confidence scoring is ubiquitous but always on
**element identity** ("did I find the right button?"), never on **finding validity** ("is
this actually a bug?").

But nobody asks for it, and the slot is occupied in the buyer's head: Ranger, Virtuoso and
CloudBees already sell AI triage bucketing failures into *Actual Bug / UI Change / Flaky /
Environment*. That is cause-classification, not expectation-provenance — but it is what we
will be compared to.

**The reframe that matters: buyers do not want fewer findings, they want cheaper triage
per finding.** A six-month Meticulous user describes "occasional false positives that are
easy to review" — tolerated, because triage is cheap. Provenance earns its place only if
proven in triage-minutes saved. As a taxonomy it is worth zero.

Keep it internal. It is the mechanism that makes the anti-false-negative guarantee
honest — you can only promise "green means verified" if you track where every expectation
came from.

*Partial prior art:* a July 2026 systematic literature review (arXiv 2607.05031, 54
studies) proposes a seven-source "authority taxonomy" on our exact premise. It is
explicitly **flat** — it never ranks sources by trustworthiness, and never connects
authority to reporting severity. Claim the ranking and the cap, not the taxonomy.

---

## 3. What got falsified

- **Docs-vs-behavior (d) — cut entirely.** Three independent kills. No buyer asking and no
  budget attached (the only advocacy traces to a founder selling a documentation product).
  The Cascade paper (arXiv 2604.19400, FSE 2026) gets **0.39 precision at realistic class
  imbalance and 0.21 recall** — it misses four of five real inconsistencies. And it is
  *method-docstrings-vs-code*, while ours would be *prose-vs-UI*, a regime **nobody has
  measured**. Momentic already ingests docs, guides, tickets, Jira, Linear and Figma; they
  are one product decision away.
- **Documentation ingestion is not whitespace.** Autify Genesis, BrowserStack's Test Case
  Generator and Testsigma's Generator Agent all ingest PRDs/Confluence/Figma and
  auto-populate expected results. All emit test cases as artifacts for human review,
  decoupled from any code diff — none ties ingested docs to a specific PR.
- **Diff-triggered is not novel.** Meticulous is PR-native; Tricentis LiveCompare does
  change-impact test selection for SAP.
- **Tests from verified passes (c) — Ranger shipped it.** Agent builds, Ranger verifies in
  a real browser, successful verifications become permanent E2E tests on approval. Drop
  the novelty claim — but note two lanes independently identified *the conversion rate
  from generated test to stable long-lived regression test* as the real moat. Buyers pay
  for durable coverage. This moves from by-product to headline.
- **BLOCKED is partially occupied.** Applitools has a genuine `Unresolved` state; mabl
  treats visual changes as non-failing warnings; **Ranger already ships `blocked` as a
  first-class verdict** with free-text rationale. The rest are orchestration states
  ("runner didn't get there"), not epistemic ones ("I reached it and still can't tell
  you"). The claim needs that precision to stand.

---

## 4. Demand — the weakest link in the case

**Ranked buyer pains** (strongest evidence first):

1. **Test maintenance and flakiness** — dominant, decade-consistent. ~50% of QA leaders
   cite it; 30-40% of testing effort goes to maintenance rather than new tests.
2. **Cost, and pricing nobody can budget against.** Of twelve vendors, exactly one
   (Katalon) publishes a real rate card.
3. **"It failed and I can't tell why."** The most underrated pain found. The highest-signal
   HN comment from someone running thousands of E2E tests: writing tests is *not* the
   pain — Playwright handles that — the pain is failures that are hard to debug.
4. **Setup effort and infrastructure.** HN says repeatedly this *is* the moat: browser
   fleets, ephemeral environments, seeded data, real auth, email/OTP/CAPTCHA, device farms.
5. Slow runs / no parallelism. 6. Coverage gaps (mobile, desktop, API). 7. Lock-in.
   8. Data privacy — letting a vendor drive your app is Capgemini's #1 GenAI-QA concern (67%).

**Evidence against our hypothesis, stated plainly:**

- **The category leader's customers never mention false positives.** Across QA Wolf's 73
  long-form reviews, *not one* mentions false positives, noisy findings, hallucinated bugs,
  or not trusting the tool. And note *why*: QA Wolf puts humans in the loop to supply the
  oracle. **The market's biggest winner sells the absence of an oracle problem, not a
  better-graded one.**
- **Nobody in any launch thread asked for provenance, or for "I could not test this."**
  They asked for infrastructure and for tests that don't go flaky.
- **The DIY substitute is free and in the building.** Claude Code + Playwright MCP,
  reported as "working amazing" given data-testid discipline. The recurring objection to
  products in this space is literally "why not Claude Code + GitHub integrations."
- **A meaningful slice doesn't believe in E2E at all** — argued as ~30% of development cost
  for ~5% occasional benefit. That is a TAM problem, not a positioning problem.
- **The category is smaller than the noise.** Only **17%** say AI-driven testing tools have
  had significant impact (n≈4,000). Enterprise-scale GenAI-QA adoption is **15%**, and
  non-adopters **rose from 4% to 11%**.

**The one strong point in favor:** 2,000+ executives rank hallucination and reliability
concerns at **60%**, a top-three blocker. And the adjacent AI-code-review market previews
the noise problem at scale — teams "begging to disable CodeRabbit," a reviewer disabling it
because 1 in 10-20 comments was useful. A QA agent that decides from a diff what counts as
a bug inherits exactly that shape.

**But that is a pain of the AI-code-review market, not yet a voiced pain of AI-QA buyers.
We would be selling a cure for a disease our buyer has not caught yet.** Whether that
backlash transfers as deployment volume grows is the load-bearing assumption under this
entire strategy, and the research could neither confirm nor refute it.

---

## 5. Competitive map

**The squeeze.** QA Wolf sits above — 182 G2 reviews at 4.8 versus mabl's 38 and
testRigor's 20 — winning by putting humans in the loop. Claude Code + Playwright MCP sits
below, free.

| Player | Oracle | Threat |
|---|---|---|
| **Meticulous** | The previous commit. Deterministic replay of recorded sessions, backends mocked. $15M Jul 2026, 5x ARR, Notion/Dropbox/Wiz | **High.** Dissolved the oracle problem rather than solving it. Attacks flakiness (pain #1) structurally |
| **Momentic** | Session recordings + docs + tickets + Figma → user-flow graph. $19.2M | **High.** Our asset thesis, funded, in our words |
| **Ranger** | Agent-written scenarios | **Medium.** Right segment, unsolved oracle, alarming commercial silence |
| **QA Wolf** | Humans | **High, indirectly.** Proves buyers will pay to make the oracle problem someone else's |
| **Antithesis** | Human-written invariants. $212M | Low — different layer (infra/distributed systems) |
| **Testsigma** | — | Low. Its "release confidence score" is **marketing-only**: absent from docs and from the five agents in its own open-source repo |
| **Octomind** | — | **Dead.** Discontinued May 2026, pivoted to agent infrastructure |

**Meticulous's structural limits** (its oracle choice, not its implementation): no oracle
for new behavior — replay needs prior traffic, and a PR introducing a feature has none;
every difference is a *change*, not a defect, so it relocates the human rather than
removing them; screenshot diffs cannot see wrong logic; environment parity is a hard
requirement with a real integration tax.

**Platform absorption.** Assume browser-driving is worth zero — Copilot has had a default
Playwright browser since July 2025, Claude Code since July 2026. Three of the strongest
entrants now position as *accessories* to the coding agent (Checksum ships slash commands
inside Claude Code, Momentic an MCP server, Ranger's whole pitch is "give your coding agent
the tools to check itself").

**The counter-case is real:** Meticulous raised $15M in July 2026 — *after* both browsers
shipped — at 5x ARR, with angels from OpenAI and Cursor. The people building coding agents
are personally funding the independent verification layer. What is not absorbable is
(i) independence from the author's context and (ii) a durable, cross-PR, human-approved
model of intended behavior. Both are knowledge-base properties, not execution properties.

---

## 6. Recommended position

**A merge gate whose green is trustworthy.**

1. **Implicit-intrinsic oracles on every run.** Crashes, uncaught exceptions, console
   errors, 4xx/5xx, DOM validity, broken links, a11y violations. **Zero of 54 studies**
   cover them; no product asserts them systematically. They have no provenance problem —
   nothing needs deriving, so no severity cap applies and they can never be a false
   positive in the "nothing is wrong" sense. Highest precision, lowest cost, and it serves
   the pain buyers actually voice. Ship this first and earn the right to be believed.
2. **Replay plus adjudication.** The other empty cell — 0 of 54 studies use an LLM to
   supply a prior-version oracle. Meta's TestGen proves observation-derived oracles work at
   scale (5,702 faults). Meticulous proves replay works but dumps every diff on a human.
   The unoccupied move: use the model not to judge *correctness* but to judge **whether an
   observed difference is the one the diff intended**. That is a triage-cost play.
3. **Verified passes promoted into a durable suite** — the conversion rate to stable
   long-lived tests is what buyers pay for.
4. **An explicit, never-suppressed account of what could not be tested.**

**Provenance grading is the mechanism, not the pitch.**

**Pricing: per repo per month.** Per-seat is wrong — this product has no authors. Per-run
is wrong — it penalizes exactly the behavior we want. Per-repo aligns with the asset, which
is per-application anyway. A real self-serve band exists at $300-900/mo. **Publishing a
rate card is itself differentiation**: eleven of twelve vendors hide numbers, and matching
us would reprice their enterprise book.

**Nobody in this category publishes accuracy numbers** — two vendors were asked directly on
HN and both declined. Being the one who does would differentiate before a novel line of
code is written.

---

## 7. Numbers to hold onto

| Figure | Source | Why it matters |
|---|---|---|
| **<10% false positives** | Google Tricorder, CACM 2018 | Above this, developers disable the tool. The hard design constraint |
| ~70% precision | AgentRewardBench, 1,302 trajectories | Best LLM judges on web-agent tasks. 3x outside the threshold |
| +16.7 points | same | LLM judges over-estimate success vs expert assessment |
| ~20% of real failures missed | production multi-turn study | Judge-only verdicts are not viable |
| 31.9-37.0% | arXiv 2410.21136 | LLM accuracy classifying a correct assertion against **buggy** code — worst exactly where it matters |
| 0.39 / 0.21 | Cascade, FSE 2026 | Docs-as-oracle precision/recall at realistic imbalance |
| ~30% valid | Daikon | Raw inferred invariants. Never report one you haven't tried to falsify |
| 55.9% recall | rule-based eval, WebArena | **Conservative oracles fail loudly too** — rejected ~44% of genuinely successful runs |

---

## 8. What would change this strategy

**Resolved 2026-08-29 — Ranger's weak commercial signals are evidence against, not for.**
They are the closest thing this space offers to a controlled experiment: same segment,
real product, 432KB of docs, and two of our four bets already shipped (`blocked` as a
first-class verdict, tests promoted from verified passes). They still show no round in 19
months, npm installs -72% from peak, 1 GitHub star, and two self-submitted HN posts with
zero comments. Read it correctly: nobody complained about their oracle-independence flaw,
because there were no users to encounter it. A flaw customers never reached cannot be the
thing that killed them, so their fate says nothing about whether independence *sells* — it
says the segment did not buy at all. The available counter-reading is that 1 star and two
self-posted threads is barely a GTM attempt, so absence of traction may be absence of a
swing; but §4 found zero voiced demand for these features independently, which is a second
piece of nothing pointing the same way. Ranger's condition changes neither the
load-bearing unknown below nor the three real threats in §5.

- **If the AI-code-review noise backlash does not transfer to AI-QA**, the trust story has
  no buyer. This is the load-bearing unknown.
- **If Testsigma's release-confidence score actually ships**, the "nobody delivers graded
  confidence" opening closes.
- **If Momentic adds contradiction detection**, they have the pipeline and the customers
  already.
- **If coding agents ship native verification with durable artifact capture**, the
  execution half commoditizes entirely and only the knowledge base remains.
- **The risk our design under-weights:** provenance capping trades recall for precision,
  and **nothing in the literature measures the cost of suppressed true findings.** A bot
  that caps everything into silence is indistinguishable from one that finds nothing.

## 9. Unresolved

Whether a dedicated QA-tooling budget line exists (all pricing is quote-only with
mutually incompatible units). Real ACVs for any incumbent. Any published false-positive
rate for any agentic QA tool — none exists. Why Octomind actually discontinued. Whether
Ranger's named customers are paying or design partners. Any measurement at all of
prose-docs-vs-UI-behavior as an oracle.

---

# The scan pivot, re-examined after building it (2026-09-04)

The intrinsic tier of the merge gate was rebuilt as `qabot scan` and aimed at a different
buyer: someone who shipped an AI-built app, has no test suite, and cannot read a stack
trace. This section is the falsification review of that pivot, run against the working
product. It supersedes nothing above; the CI analysis stands as written.

## Verdict

**The buyer is real. The wedge is not.** That is a genuine improvement over §4 — where the
CI buyer never voiced the pain at all — and it still does not add up to a business as
scoped.

## What killed the wedge

**Our v1 is somebody else's lead magnet.** ArgosX ("Independent verification for AI-built
apps", targeting Lovable/Bolt/Cursor/v0/Replit users) gives away, free and without signup,
a superset of everything `qabot scan` does: anonymous crawl, broken links, accessibility,
page-level checks. What they charge $49/mo for is the authenticated tier — which their own
page says is "where most real problems are found". That is the boundary we drew between v1
and v2, drawn by a competitor, with the paid side on the half we deferred. VibeEval and
Rixel occupy adjacent positions; TestSprite ($6.7M seed) does "URL to 50-100 e2e tests in
ten minutes" at scale for developers.

**Platform absorption is no longer a prediction.** Lovable shipped Project Monitoring in
**June 2026** — scheduled app checking, code review, and *recent visitor errors* — two
months before the scan spec was written, and a security scan that runs automatically in the
publish dialog. Replit's Agent browser-tests the apps it builds and hits the same login wall
we do, from the inside. §5's platform-absorption section missed all of this because the
five-lane research audited QA *vendors*; the app builders were only ever assessed as
distribution, never as competitors. That is a scoping error in our own research method.

**Real visitor telemetry beats a stranger's crawl at our own signal.** "Recent visitor
errors" sees logged-in traffic, real routes and real state. One script tag, shipped free
inside the builder, is strictly better at crash-class detection than an anonymous synthetic
sweep. This is the single most damaging fact in the section.

**The long-term half has no buyer either.** "Shape 1 aimed at shape 2" assumed we would
eventually sell verification to the platforms. No partnerships found in either direction;
both large platforms built verification in-house (Replit published its own REPL-based
self-testing engine, claimed 3x faster and 10x cheaper). Reported as absence of evidence,
but it points the same way as everything else: platforms treat verification as core.

## What survives

- **The logged-out stranger's viewpoint.** Real, narrow, and the one thing a platform's own
  agent structurally cannot do, because it runs inside the build session. The owner is
  always logged in and never sees it. `challengebrew.com/account` throwing
  `Cannot read properties of null (reading 'tier')` while redirecting a logged-out visitor
  is the proof case.
- **The honesty properties.** "This run verified nothing", per-source discovery counts, the
  always-rendered could-not-check section, and a false-positive rate measured under an
  adjudication protocol written before the numbers existed. No competitor reports the shape
  of what it could not see. It is the intellectual core of this codebase — and it is a
  subtle good sold to a non-expert, while VibeEval already headlines "0 false positives"
  without doing any of the work.
- **The authenticated half we deferred** — defensible precisely because it is hard
  (credentials, session state, not mutating a stranger's production data). We deferred it to
  find out whether v1 was worth anything; the answer that came back is that v1 is what other
  people give away.

None is a company alone. The authenticated half plus the honesty properties might be:
**authenticated verification with an honest account of coverage** is a trustworthiness claim
a platform's self-marking agent cannot credibly make about its own output.

## The riskiest assumption, and the thing we never measured

**That "found" is separable from "fixed" for this buyer.** Every observed dollar pays for
removal: $25 Fiverr gigs, $70/hr rescue agencies, $249 human-verified scans — and the one
that matters, Lovable's free fix, applied by the same agent that wrote the bug, in the same
window, ten included in the account. *A report is the first half of a job whose second half
is already free and adjacent.* We occupy the cheapest link in our own value chain.

**And we measured precision without ever measuring consequence.** The 0%-false-positive
result answers "is this finding real". It does not answer "does anyone care". From the HN
launch thread of a company that shipped this exact wedge: *"I worked with exploratory
testing companies that would report hundreds of bugs that nobody ever cared about."* Our
measurement programme was built against Google Tricorder's <10% bar — the right constraint
for a merge gate a developer can switch off, the wrong one for a report a non-engineer
decides whether to buy.

## A measured limitation nobody had written down

On SPA hosting a nonexistent path commonly returns the index shell with **200**:
`podprime.ai/definitely-not-a-real-page-xyz` → 200, `student-os.net/...` → 200,
`challengebrew.com/...` → 404. Two of three soft-404. On those apps BROKEN's "main document
non-2xx" source cannot fire at all, and GLITCHY's "links to routes that 404" cannot either —
so BROKEN collapses to `blank_page` plus 5xx from the page's own XHRs. **`blank_page` is
carrying far more weight than the spec implies**, and it is the one oracle with a tunable
threshold. The severity distribution was validated against server-rendered apps (datasette,
CTFd) and this buyer's hosting behaves differently. Three apps is a flag, not a rate.

## What would change the answer, cheapest first

1. **The consequence test.** Scan 20 real AI-built apps, contact the owners, record what they
   *do*. If a material fraction fix something they did not know was broken, the objection
   above is answered. If they shrug, 0% false positives is confirmed as necessary and
   insufficient. Days, not months — and wire the source maps first, or it runs with one hand
   tied: an unresolved minified frame (`"Wl"`) is not a degraded finding to this buyer, it is
   a non-finding.
2. **The differential test.** Run ArgosX's free scan and `qabot scan` against the same ten
   apps and diff the findings. One afternoon.
3. **Reddit.** Every demand claim here is inferred from agencies, SEO content and vendor
   pricing — third parties reasoning about the buyer. r/lovable and r/vibecoding were
   inaccessible three ways, exactly as in the 2026-08-28 research, and that is where this
   buyer actually talks.
4. **A credible auth path** that does not turn this into a security product.
5. **Evidence any of the three live competitors has revenue.** None could be established.
   If all three are zero, "three competitors" collapses to "three people had the same idea
   and none of them sold anything" — a different and worse signal about the category.

## Evidence limits

No Reddit, no Discord, no Lovable forum — no primary buyer voice at all. No reviews, funding
or usage data for ArgosX, VibeEval or Rixel; treat them as three live *commercial attempts*,
not three businesses. `docs.lovable.dev/features/monitoring` 404s, so what Project Monitoring
actually detects is unconfirmed. Ghostship (YC S25, "find bugs in your web app by entering in
your URL") pivoted to Bidflow with the same two founders and its DNS torn down, but a trade
blog reports ~$200K ARR in nine months, uncited, and no founder post-mortem exists — so it is
evidence about pace and ceiling, not about whether anyone buys.

## Addendum (2026-09-05): the detection layer was the problem, not the wedge

EVAL.md's visitor-experience experiment (88 AI-built apps with public source, two corpora,
frozen protocol) falsifies the sentence this section's verdict leaned on. Wrong content in
AI-built apps is mostly a *hallucinated resource* — a route the router never declared, an
image URL that never existed, a placeholder shipped as content, a crash the error boundary
swallowed — and each of those is mechanically detectable with app-declared provenance. Five
source-free oracles: 0 confirmed false positives across 148 apps once a `todo`-in-Portuguese
bug in one pattern was corrected (see EVAL.md). 25% of a random sample and 12 of 100
actively-maintained apps carried something its owner would fix, by our protocol; the
consequence test with owners remains unrun.

What changes in the analysis above: "our v1 is somebody else's lead magnet" was written
about crash-class and broken-link signals. It has not been checked against the combination
found here — hallucinated images, shipped placeholders, caught crashes, dead CTAs, filter
that filters nothing — each with a screenshot and a one-line visitor consequence. Item 2 of
"what would change the answer" (the ArgosX differential) is now the cheapest decisive test,
and it should be run on corpus B, where the owners are alive. The login boundary is worse than
§"What survives" assumed: 24 of 40 active apps show a stranger exactly one page.

## The differential, as far as it can honestly be taken (2026-09-05)

**The empirical version cannot be run on other people's apps.** ArgosX's terms: *"You may
not use ArgosX to test systems you do not control or are not authorized to test."* Its form
adds *"By scanning you confirm you're authorized to test this app"*, and its report goes only
to an email address. VibeScan gates on a checkbox, *"I own this app or have permission to
security test it."* ShipSafe requires an account and a URL *"you tell us you own."* Running any
of them against the 100-app corpus would mean making that attestation falsely, in Jordan's
name, on a dozen strangers' apps. Not done. The version that *can* be run — our scan and
theirs against an app we own — needs an app we own on a public host, and is queued behind
that.

**The documentary version, from each vendor's own page (fetched 2026-09-05):**

| | ArgosX (free Deep) | VibeScan (free) | VibeEval ($49/mo) | ShipSafe ($9+) | `qabot scan` + the visitor-experience oracles |
|---|---|---|---|---|---|
| leaked keys / secrets | yes | yes | yes | — | no |
| security headers, TLS, cookies | yes | yes | — | — | no |
| Supabase RLS / open database | yes | yes | yes | — | no |
| broken links | **yes** | — | — | — | yes (rendered soft-404 too) |
| accessibility / SEO | yes | — | — | — | no |
| "unfinished content (placeholder text, formatting errors)" | **yes** | — | — | — | yes |
| images that never load, hallucinated image URLs | — | — | — | — | yes |
| caught crashes rendered as an error screen | — | — | — | — | yes |
| buttons that do nothing | — | — | — | — | yes (58%, reported apart) |
| horizontal scroll on a phone | — | — | — | — | yes |
| link label vs destination (wrong page, dead filter) | — | — | — | — | yes (inferred, capped) |
| a page that never loads / a white screen | — | — | — | — | yes |
| results on-page without an email | no (email) | yes | ? | yes (account) | yes |
| requires ownership attestation | yes | yes | ? | yes | no (read-only, robots, no forms) |

**What this says.** The category that looked like "three competitors" in August is now at
least eight free-or-cheap scanners aimed at Lovable/Bolt/v0 users, and *every one of them is
a security scanner*: keys, headers, RLS, CVEs. Two of our mechanical oracles — broken links
and placeholder text — sit inside ArgosX's free tier, exactly as §"What killed the wedge"
feared. The other five, and the judge, sit inside nobody's: the field checks whether the app
can be *broken into*, and nobody checks whether it *works for a visitor*. The 12-of-100
would-fix findings in EVAL.md are, with two exceptions (a placeholder phone number, footer
404s), of the kind no listed product claims to look for.

That is a narrower and more defensible statement than August's "our v1 is somebody else's
lead magnet": the *crash-and-broken-link* v1 was; the *visitor-experience* set is not, yet.
Whether it is worth money is still the unrun owner test — twelve drafted, unsent messages
sit in `qa-artifacts/vx-2026-09-05/runs/outreach_drafts.md` for Jordan to approve verbatim.

**Evidence limits.** Vendor pages, read once, on one day; "—" means *not claimed on the
page*, not *absent from the product*. No scanner was run. VibeEval's comparison page names
no non-security check at all, which is itself the signal.
