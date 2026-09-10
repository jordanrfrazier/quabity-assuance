# Competitor Ideas For Qabot

Research date: 2026-09-09. Status: proposals for Jordan's review, not an implementation plan.
Workspace: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`, branch `main`.
Code baseline reviewed: `33553a004a4b259a35582a0e05c0c0ee2cf7756f`.

## Recommendation

Review **R1 coverage ledger**, **R2 evidence comparison and adjudication**, and
**R3 staged setup review** first. They address what made our Langflow/Linkding
validation labor-intensive: understanding the tested scope, comparing attempts,
and turning discovered setup into a trustworthy executable plan.

**R6 reviewed setup replay** is the strongest later efficiency experiment. It
remains v2, not a reason to introduce autonomous workflow learning now. No idea in
this document has been approved for implementation.

Three research agents covered direct competitors, OSS/developer substitutes, and
established/adjacent platforms. The coordinator reviewed their notes against the
current implementation, checked key sources independently, removed duplicate
recommendations, and separated existing features from actual additions.

## Competitive Reality

- The closest documented workflows include Ranger Feature Review and Momentic;
  QA Wolf also has local tooling, and Meticulous Agent review is an opt-in beta.
  They should not be dismissed as only hosted suites or outsourced manual QA.
  [Ranger](https://docs.ranger.net/), [Momentic local runs](https://momentic.ai/docs/running-tests/running-locally),
  [QA Wolf local projects](https://docs.qawolf.com/qawolf/local-execution/set-up-a-project),
  [Meticulous Agent review](https://app.meticulous.ai/docs/agents/agent-review).
- BLOCKED outcomes, browser evidence, CLI use and separate agents are not unique.
  Mo explicitly records coverage gaps. An independent execution context does not
  establish an independently sourced requirements oracle; missing documentation
  does not establish that a competitor lacks approval safeguards.
  [Ranger architecture](https://docs.ranger.net/concepts/how-it-works/),
  [Mo reports](https://momentic.ai/docs/mo/reports).
- Our defensible hypothesis is the quality of the complete local, reviewed,
  version-bound verification workflow. This research establishes neither a unique
  market position nor willingness to pay.

## Best Idea From Each Product

These are adaptations we would consider, not claims that we should reproduce each
vendor's architecture. Supporting lane notes contain more sources and caveats.

| Product | Relationship | Best idea to adapt | Proposal |
| --- | --- | --- | --- |
| [Ranger](https://docs.ranger.net/) | Direct feature-review competitor | Make the journey and its evidence a unit of human review, with an explicit disposition. | R2 |
| [Momentic / Mo](https://momentic.ai/docs/mo/reports) | Direct suite; Mo is private beta | Put verified criteria and remaining gaps beside the verdict. | R1 |
| [Bug0 / Passmark](https://github.com/bug0inc/passmark) | Managed QA plus testing library | State whether an expectation needs text, a screenshot, or temporal video evidence. | R4 |
| [Autonoma](https://docs.autonoma.app/test-planner/) | PR/environment-oriented competitor | Expose discovery and readiness as inspectable stages instead of one opaque setup operation. | R3 |
| [Playwright Test Agents](https://playwright.dev/docs/test-agents) | Strong DIY substitute | Keep reviewed specifications, existing seed setup and executable assertions linked. | R3, R4, R8 |
| [Playwright CLI / MCP](https://playwright.dev/docs/getting-started-cli) | Execution building blocks | Measure concise command-based versus state-rich browser control on the same work. | Later benchmark, not an engine rewrite |
| [Stagehand](https://docs.stagehand.dev/v3/best-practices/caching) | Execution SDK | Reuse resolved actions to avoid rediscovery, with visible cache behavior. | R6 |
| [browser-use](https://docs.browser-use.com/open-source/customize/agent/all-parameters) | Execution agent | Explicit run limits and usage accounting, distinct from successful completion. | R5 |
| [Hercules](https://github.com/test-zeus-ai/testzeus-hercules) | Dedicated OSS QA runner | Scenario-centered proofs and readable, atomic test specifications. | Benchmark existing report/scenario organization |
| [QA Wolf](https://docs.qawolf.com/qawolf/Diagnose-the-cause-of-a-failing-flow.md) | Behavioral QA platform and service | Distinguish product defects, test mistakes and infrastructure trouble using attempt evidence. | R2 |
| [mabl](https://help.mabl.com/hc/en-us/articles/19078188344980-Flows) | Broader automation platform | Parameterized shared setup, with dependency versions visible to consumers. | R6 |
| [Meticulous](https://app.meticulous.ai/docs/agents/agent-review) | Replay platform; agent-review beta | Deliberately promote exploration into persistent regression material. | R8 |
| [Argos](https://argos-ci.com/docs/learn/platform-fundamentals/baseline-build) | Adjacent visual review platform | Explain whether two runs are suitable for comparison before showing a diff. | R2 |

## Ranked Review Queue

Priority and effort are qualitative engineering judgments, not estimates derived
from vendor benchmarks. "Candidate" does not expand the accepted v1 contract.

| ID | Candidate addition | Value / relative effort | Suggested timing |
| --- | --- | --- | --- |
| R1 | Acceptance-criterion coverage ledger | High / small-medium | Consider for the next local pilot |
| R2 | Compatible-run comparison and separate human adjudication | High / medium | Consider for the next local pilot |
| R3 | Staged, source-backed setup review with actionable gaps | High / medium | Consider before broader first-use trials |
| R4 | Typed assertions and explicit evidence modality | High / medium-high | Bounded experiment after contract review |
| R5 | Enforced run time/model-call budgets | Medium-high / medium | Before larger unattended runs |
| R6 | Approved setup replay, separate from session reuse | Potentially high / high | Existing v2 proposal |
| R7 | Fresh-state reproduction of suspected defects | Medium-high / high | Later opt-in validation mode |
| R8 | Export reviewed journeys as regression tests | Potentially high / high | Later, after assertion/replay semantics |

### R1: Acceptance-Criterion Coverage Ledger

**Delta:** qabot already shows steps, outcomes and limitations. Add explicit links
from a reviewed criterion to the journeys and evidence that cover it, including
criteria deliberately omitted or never reached. Keep distinct roles and profiles
distinct. Do not call route visits or a passing selected subset "full coverage."
The concrete precedent is [Mo's case and gap reporting](https://momentic.ai/docs/mo/reports).

**Smallest useful trial:** review one Langflow PR with both editor and Assistant
paths. A reader should immediately see which path was verified, blocked or excluded.
**Success check:** reviewers identify every intentionally omitted criterion and
never interpret a partial run as complete. No fabricated overall coverage percentage.

### R2: Compatible-Run Comparison And Human Adjudication

**Delta:** preserve the current immutable reports, but show an explicitly selected
pair of runs together: expectation changes, revision/profile differences, first
divergent step, relevant screenshots, video positions and original failure reason.
Store a human diagnosis separately from the observed execution outcome. A reviewer
calling something expected behavior must not rewrite the original FAIL as PASS.
Inspired by [QA Wolf diagnosis](https://docs.qawolf.com/qawolf/Diagnose-the-cause-of-a-failing-flow.md)
and [Argos baseline eligibility](https://argos-ci.com/docs/learn/platform-fundamentals/baseline-build).

**Boundary:** a deliberate broken-before/fixed-after comparison is valid evidence,
even though the broken run must not become a passing regression baseline. Explain
changed expectations and incompatible environments rather than implying causality.
**Success check:** compare Linkding-01/02/03 and have a reviewer distinguish actor
error, cleanup blockage and verified application behavior without reading raw JSON.

Optional later depth: a private Playwright trace can expose action/DOM/network
context. Do not automatically add traces or HAR to shared ZIPs: these can expose
credentials, response bodies and source. Existing video chapters already help;
the goal is faster review, not another video container.
[Trace Viewer](https://playwright.dev/docs/trace-viewer).

### R3: Staged Setup Review

**Delta:** reuse the existing startup-plan schema, approval and doctor checks. Make
discovered prerequisites, required operator input, prepared dependencies, fixture
reset and effective-state checks separately visible before a full browser run.
Retain source references and distinguish supplied configuration from observations.
An inspectable project profile could later avoid repeating the same manual setup
explanation across plans; this is not permission to execute cached browser actions.
Inspiration: [Autonoma planner](https://docs.autonoma.app/test-planner/) and
[Playwright seed setup](https://playwright.dev/docs/test-agents).

**Boundary:** no invented fixtures, automatic backend edits, credential acquisition
or resumed execution against stale approvals. Begin with reviewed existing commands.
**Success check:** a new operator discovers missing dependencies, authentication or
reset support before paying for a full journey. Measure interventions and time to
first valid run; our prepared local harnesses do not establish clean-machine usability.

### R4: Typed Assertions And Evidence Modality

**Delta:** qabot already separates actor completion from model judgment. Add a small
human-reviewed vocabulary for objectively checkable conditions, such as exact text,
visibility, count or ordering, while retaining a clearly labeled semantic judge
for expectations that need it. Record what evidence modality was actually assessed.
Current actor/judge input is text/accessibility, not screenshot pixels.
Precedents: [Playwright assertions](https://playwright.dev/docs/test-assertions)
and [Passmark's assertion options](https://github.com/bug0inc/passmark).

**Boundary:** a generated assertion is a proposal, not the authoritative meaning of
the requirement. Unsupported or missing evidence must not become success. Video
model analysis would require its own provider, cost and privacy decisions.
**Success check:** the same reviewed assertion catches a deliberate defect and
passes the fix without being rewritten between runs. Start with one assertion type.

### R5: Enforced Budgets

**Delta:** existing phase timing and call counts describe usage after the fact.
Add explicit enforceable time/call limits, remaining allowance and stop reasons.
An alert is not a hard limit, and a call cap is not a dollar cap. Provider billing
cannot be inferred precisely from elapsed time.
[browser-use parameters](https://docs.browser-use.com/open-source/customize/agent/all-parameters),
[Momentic run timeout](https://momentic.ai/docs/cli-reference/momentic/commands/run).

**Success check:** exhaust a deliberately small limit, retain partial evidence,
stop owned processes, and report unverified work without PASS. Define whether
discovery, setup, judging and any rerun share the same budget before implementation.

### R6: Reviewed Setup Replay (V2)

**Delta:** replay approved setup actions with current guards instead of asking the
actor to rediscover every interaction. Keep learning suggestions, procedure replay
and authentication-state reuse as separate decisions, as already documented in
[our v2 proposal](../../../v2/workflow-learning.md).
Precedents: [Stagehand caching](https://docs.stagehand.dev/v3/best-practices/caching),
[Momentic step cache](https://momentic.ai/docs/get-started/how-momentic-works),
[mabl flows](https://help.mabl.com/hc/en-us/articles/19078188344980-Flows).

Our retained Linkding-03 audit recorded 100 model calls and 401.32 seconds summed
step time: 253.45 seconds actor requests and 92.19 seconds judge requests. About
86% was those request phases, not browser clicks. This is one run, not a benchmark
or proof of provider-internal reasoning time. Only some actions are reusable setup;
these numbers do not predict a cache speedup.
[Local measurements](../../../v1/reports/verification/private-alpha-20260909/audit/linkding-03/manifest.json).

**Success check:** compare repeated equivalent fresh runs, plus changed UI, wrong
role/profile, expired session and broken-behavior cases. Stop visibly on divergence;
never cache verdicts, skip the behavior under test or silently heal the expectation.

### R7: Independent Fresh-State Reproduction

**Delta:** a second bounded execution, not another model vote on the same evidence.
Retain the original observation and indicate whether reproduction succeeded, failed
to reproduce or was blocked. Mo documents a clean-start reproducer; its policy of
excluding unreproduced suspicions should not be copied into qabot's evidence record.
[Mo agent roles](https://momentic.ai/docs/mo).

**Boundary:** a fresh browser is not a fresh database. Reproduction needs an approved
fixture/reset contract and should not invent setup. A passing rerun cannot erase an
intermittent failure. **Success check:** distinguish a reproducible defect, a transient
defect and unavailable setup while preserving all attempts and their extra cost.

### R8: Export Reviewed Regression Tests

**Delta:** export a reviewable test from an approved journey with explicit assertions,
not a recording of clicks labeled as a complete test. Preserve requirement/source
links and unsupported assertions. Ranger's promotion path and Playwright generation
are precedents. Meticulous exports session data; that is not necessarily standalone
Playwright assertion code.
[Ranger feature reviews](https://docs.ranger.net/),
[Playwright generation](https://playwright.dev/docs/test-agents),
[Meticulous export](https://app.meticulous.ai/docs/export/exporting-generated-tests.md).

**Success check:** exported tests run repeatedly and still detect the intentional
defect. Do not automatically add them to a user's CI suite or rewrite expectations
to make generation succeed. Runtime/model dependencies and ownership remain explicit.

## Keep, Do Not Rebuild

The current CLI already has approval/version binding, startup/reset commands,
credential references, actor/judge separation, PASS/FAIL/BLOCKED, per-step results,
screenshots, required video checks, timing/call counts, durable reports and ZIPs.
Those competitor parallels validate useful mechanics; they are not a fresh backlog.
The coordinator's R1-R8 priorities supersede broader suggestions in individual lanes.

## Do Not Copy By Default

- Silent locator/flow healing, automatic quarantine or skipped broken tests that
  obscure the original outcome. Repair proposals can be reviewed separately.
- Automatic code fixes, pushes, cloud provisioning or shared session uploads.
- Mocked backend replay presented as proof of real backend behavior.
- More judges treated as proof of independent truth, or more agents as free speed.
- Unsupported novelty, accuracy, savings or self-hosting claims.

Lifecycle correction: mabl's current documentation says runtime recovery was
disabled in all workspaces on August 3, 2026. It is not evidence of an active
capability; element auto-heal is a distinct feature.
[mabl retirement notice](https://help.mabl.com/hc/en-us/articles/47421809580948-Agentic-runtime-recovery).

## Evidence And Next Decision

Read-only documentary research, not a hands-on bake-off or customer-demand study.
Vendor claims are labeled, mutable docs were checked on the date above, and public
prices are not comparable across software, hosting and managed-service offerings.
No account was created, application uploaded, competitor run, sales team contacted
or implementation copied. License labels in lane notes are not reuse clearance.
Some pages failed to fetch: notably the coordinator's Autonoma planner recheck
returned HTTP 402 although the research lane retrieved it. That limits independent
corroboration; it is not evidence of pricing or product availability.

- [Direct competitors: Ranger, Momentic/Mo, Bug0/Passmark, Autonoma](direct-competitors.md)
- [OSS and developer tools: Playwright, Stagehand, browser-use, Hercules](oss-and-developer-tools.md)
- [Established and adjacent: QA Wolf, mabl, Meticulous, Argos](established-and-adjacent.md)

Jordan can select proposal IDs to investigate or implement next. A sensible small
first selection is R1 plus the local report-comparison portion of R2, while deciding
R3's setup contract separately. Keep R6 in v2 unless explicitly reprioritized.
Any later competitor execution needs separate authorization and an owned test target.
