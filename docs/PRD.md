# qabot: Human-Reviewed QA Journeys

Status: Working draft; local CLI and reviewed local startup confirmed, release contract incomplete.
Date: 2026-09-06.
Decision maker for this drafting process: Jordan.
Implementation directory: `/private/tmp/qabot-cli-2026-09-06`.
Working branch: `feature/qabot-journeys-cli`.
Original project: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`,
branch `feature/qabot-scan`; its earlier draft is preserved.

## 1. Product Definition

For developers reviewing a code change, qabot generates understandable QA journeys,
lets a human correct their expected outcomes, executes them against a controlled
test environment, and reports evidence plus anything it could not verify.

Jordan confirmed this product direction on 2026-09-06. Human review is central to
the first release. Anonymous scanning and automatic merge blocking are excluded.
The first release is a local CLI. Jordan will first assess whether its workflow
is seamless to use; a local web interface is a later direction contingent on that
experience. No web interface is included in the first release.
qabot will inspect repository documentation and configuration to propose a local
startup plan, execute the reviewed plan under the selected test profiles, and
attach configuration/state evidence to each journey. General infrastructure
provisioning is deferred.
The developer approves each startup-plan and journey version once. Unchanged
versions can be rerun without another approval prompt; execution-affecting edits
require renewed review.

This document defines the intended product. Prototype behavior is evidence for
requirements, not an implicit requirement to preserve that behavior. Requirements
below translate the confirmed direction into a reviewable draft; detailed acceptance
rules remain subject to product review. Open decisions in section 9 prevent this
document from being treated as an implementation-ready or production-grade PRD.

## 2. User and Problem

**Primary user:** a developer reviewing a code change who needs to understand which
user-facing behaviors to exercise and what the observed results establish.

**Job:** turn a change into a reviewable QA procedure, correct the procedure using
product knowledge, execute it, and decide what needs attention from inspectable
evidence.

The current prototype demonstrates a concrete problem: an agent can execute browser
actions successfully while checking an incorrect expectation. For example, an
authored journey expected eight starter templates on a Langflow instance showing
26. The fixed build's main journey was BLOCKED, while the broken build's journey
was FAIL. Correct browser operation alone did not establish that the fixed change
worked. A developer needs to inspect and correct the expectation before relying
on a subsequent execution.

Jordan is the first evaluator of CLI usability. The broader release audience,
frequency of use, buyer, and willingness to pay have not been established. The
project evidence supports investigating this workflow; it does not establish
commercial demand or general verification accuracy.

## 3. Goals and Boundaries

The first release should enable a developer to:

- Understand why each proposed journey is relevant to a code change.
- Review and correct actions, expectations, and necessary setup before execution.
- Execute the reviewed journeys against a controlled test environment.
- Inspect outcomes and supporting evidence, including incomplete coverage.
- Correct a journey and rerun it without confusing old and new results.
- See the system configuration relevant to each test, including conditions such as
  custom components disabled, MCP allowed, and rate limiting enabled. Jordan
  explicitly identified this visibility as necessary for scoping and reviewing tests.

**Confirmed delivery:** local CLI first, with Jordan evaluating the complete
workflow before pursuing a local web interface.

**Confirmed first-release exclusions:** anonymous URL scanning, automatic merge
blocking, a local web interface, cloud infrastructure/account provisioning,
automatic secret acquisition, host-level service installation, invented
undocumented infrastructure, arbitrary generated executable fixtures, and unbounded
repair of a failing setup.

CI integration, hosted service, authentication automation, automatic fixture
generation, and regression-test export are not committed by this draft. Local CLI
delivery does not imply offline model execution; model access remains D-06.

The future web interface is a product direction, not a requirement to build a web
API, background service, or extensibility framework in this release. Its scope and
implementation effort will be assessed after the CLI workflow is validated.

## 4. Core Workflow

1. **Provide the repository and change.** The developer identifies the change and
   supplies the available explanation of intended behavior. qabot inspects the
   repository and documentation for startup, configuration, and setup information.
   Supported change formats and local application setups remain D-04.
2. **Inspect proposed journeys and startup plan.** qabot presents the proposed
   startup/setup commands and their sources, plus each journey's purpose,
   relationship to the change, preconditions, actions, and expected observations.
   Missing or conflicting setup information is explicit.
3. **Review and correct.** The developer corrects the startup plan, configuration
   profiles, and journeys, supplies required host tools and secrets, and selects
   the journeys to run. The developer explicitly approves each version once.
   Unchanged versions can be rerun without another prompt. Execution-affecting edits
   invalidate approval for the changed content before it executes.
4. **Establish readiness.** qabot runs the reviewed local setup/startup commands
   and readiness checks under the required profiles, using documented seed/reset
   procedures where available. It records the configuration, identity, data, and
   dependency evidence needed to interpret each test. Unsupported setup blocks
   affected journeys with a concrete missing requirement.
5. **Execute.** qabot attempts the selected journeys within the agreed environment
   and reports outcomes with evidence and reasons for incomplete work.
6. **Inspect and rerun.** The developer distinguishes an application issue from an
   incorrect journey or unmet setup, corrects the relevant input, and runs again.
   Each result remains associated with the journey and environment it evaluated.

### CLI Usability Contract for Review

"Seamless" needs an observable acceptance path. The following criteria are proposed
for Jordan's first-use evaluation; numeric time and cost targets remain D-07.
Command names, flags, and the journey file format are not selected here.

| Stage | Proposed first-release behavior |
| --- | --- |
| Start | Documented installation and command help are enough to begin; using the product does not require importing spike modules or editing qabot source. |
| Generate | The CLI identifies the supplied change, exposes missing inputs, and writes journeys that can be inspected and corrected before browser actions begin. |
| Review | A developer can edit the journey artifact with a normal editor. Malformed edits produce actionable validation errors before execution. The developer approves a startup-plan or journey version once; unchanged reruns reuse that approval. |
| Run | The developer can execute a selected journey from the reviewed artifact without generating a new set. The CLI exposes progress and the current journey. |
| Inspect | The terminal gives outcome counts, incomplete-work reasons, and the location of the evidence report. HTML remains the proposed report format, to be finalized under D-06. |
| Correct and rerun | The developer can fix a journey or the declared setup and rerun the selected journey without modifying qabot or manually assembling a new runner script. Old results remain identifiable. |
| Recover | Missing dependencies, invalid inputs, unavailable models, and unreachable applications identify the failing prerequisite and a concrete next step; no successful-run message masks the problem. |

Environment setup in this workflow follows the confirmed D-02 boundary below.
The CLI usability evaluation includes review and execution of the startup plan.

### Application Setup Contract

Jordan confirmed repo-informed, human-reviewed local startup for v1. Configuration
before startup is part of the test's meaning. The scope boundary is:

1. Inspect startup documentation, configuration definitions, dependency manifests,
   and existing startup/test scripts. Produce a proposed setup plan that cites
   where its commands, settings, and prerequisites came from. Conflicting or missing
   instructions remain explicit questions.
2. Let the developer review and correct the startup plan and the configuration
   profiles needed by the selected journeys before executing setup commands.
   The required host tools and secret values come from the developer. The plan may
   reuse documented local dependency/setup commands; the supported range of such
   commands must be settled under D-04.
3. Start the application under the reviewed profile, use an explicit readiness
   check, and establish the conditions needed for each journey. Reuse documented
   seed/reset procedures where available; unsupported state setup blocks affected
   journeys with a reason. Sharing a settings profile does not establish data
   isolation between journeys.
4. Attach each journey to its configuration and state evidence. Record required
   values, values supplied at startup, and effective values observed from the
   running app where verifiable. Include source revision, relevant settings and
   defaults, identity/role, and fixture/reset status. Secret values must not be
   exposed in reviewer-facing output; record their references or presence instead.
5. Use only the profiles required by the selected journeys. Automatic exploration
   of every configuration combination is outside this release.

Confirmed deferrals: cloud infrastructure/account provisioning, automatic secret
acquisition, installing host-level services, inventing undocumented infrastructure,
arbitrary generated executable fixtures, and unbounded repair of a failing setup.
Unsupported setup ends with a concrete missing requirement, not a claim that the
journey passed or that the application is defective.

**Evidence limit:** supplying an environment variable does not prove the app used
it; configuration files, persisted settings, and defaults may affect the result.
A health check proves readiness only to the extent of that check. Required values
must be distinguished from supplied and observed values, with unknown effective
state shown explicitly. Conditions essential to interpreting a test cannot be
silently treated as verified. The readiness policy must also distinguish an unmet
setup condition from a defect in the configuration behavior being tested: a test
of whether a flag is honored must not hide a demonstrated violation as mere setup
failure. Detailed outcome rules require acceptance review under D-05.

The first release supports a controlled set of documented local setups. It does not
promise that repository inspection can reconstruct every application's complete
runtime state or bootstrap an arbitrary repository without human input.

### Approval and Revision Contract

Jordan confirmed approval once per version, with no repeated prompt for unchanged
reruns and renewed review after execution-affecting edits. Approval belongs to the
startup plan and the individual journeys it covers. It does not claim that an
application is correct or that its current runtime state matches the test's needs.
Every run must still perform its readiness/state checks and capture fresh evidence.

The following rules make that decision concrete for acceptance review:

- Generated or manually edited content is not approved by its creation, a successful
  execution, or a model judgment. The developer must explicitly approve its current
  version before the dependent setup commands or test actions execute.
- Approval records identify the approved content version, the local reviewer, and
  when approval occurred. Runs identify the plan/journey versions and approvals
  they used. No hosted account or multi-user approval service is required by this
  local CLI contract.
- Changing execution-affecting content requires review of the changed plan or
  journey. Unchanged journeys retain their own approval, but cannot execute through
  an unapproved changed startup plan or profile. The CLI explains what changed and
  what needs review before executing the affected content.
- An unchanged selected subset can be rerun without reauthoring the journeys or
  approving them again. Previous results remain historical evidence for their own
  versions and runs; approval reuse never reuses an old PASS as a fresh result.

| Change | Approval behavior |
| --- | --- |
| Setup/startup command, arguments, working directory, readiness/cleanup procedure, or referenced executable setup script | Review the changed startup-plan version before executing it. A script at the same path is not unchanged content if its executable instructions changed. |
| Execution target, configuration values, identity/secret references, fixture definition, or reset procedure | Review the affected plan/profile or journey version. Do not reveal secret values in the change summary. |
| Journey actions, expected observations, required preconditions, or supporting intent that establishes the expectation | Review the changed journey version. |
| Output artifacts, timestamps, previous outcomes, or formatting that leaves reviewed content unchanged | No new approval of the plan or journey is required. |
| Another application revision evaluated using the same reviewed procedure and profile | Record the new source identity and check setup compatibility/readiness again. Reuse approval only when the reviewed plan, executable setup inputs, profiles, and journeys are unchanged. |

The application revision and the approved procedure have separate identities so
the same reviewed journey can evaluate a known broken and fixed build. Changes to
setup inputs or the reviewed procedure still invalidate the corresponding approval.
The exact local approval command and artifact encoding are implementation details
to specify after the supported CLI inputs are selected under D-04.

## 5. Functional Requirements

All rows are candidate first-release requirements derived from the confirmed
workflow. Acceptance examples define observable behavior without prescribing an
implementation or selecting unresolved release details.

| ID | Requirement | Acceptance example |
| --- | --- | --- |
| FR-01 | Generate reviewable journeys relevant to the supplied change. | Each journey describes a user goal and identifies the supplied evidence that makes it relevant. An absent or unsupported connection is visible to the reviewer. |
| FR-02 | Each journey states preconditions, actions, and expected observations. | A reviewer can distinguish what to do from what should happen and identify the setup on which the expectation depends. Missing required information is exposed before execution. |
| FR-03 | Allow human correction before execution. | The developer changes an incorrect expected template count; the next execution evaluates the corrected expectation. The generated wording does not silently reappear. |
| FR-04 | Preserve the distinction between generated and human-reviewed expectations. | A model-generated expectation is not described as human-confirmed merely because the model executed or judged it. Explicit human approval identifies the accepted journey version; editing its actions, expectations, preconditions, or supporting intent requires renewed review. |
| FR-05 | Make required environment conditions explicit. | A journey requiring a feature flag or model credential does not report an application defect solely because that prerequisite was missing. Unknown prerequisites are visible. The readiness policy follows the application setup contract; detailed outcome rules remain D-05. |
| FR-06 | Report a result for every selected journey, including incomplete journeys. | An unreachable application or unavailable model produces an explicit account of what could not be verified, with no missing journey that appears implicitly successful. |
| FR-07 | Associate verdicts with inspectable evidence and the evaluated expectation. | A developer can inspect the observed state and understand why the expectation was judged satisfied, contradicted, or uncheckable. Evidence format and minimum completeness are decided under D-06. |
| FR-08 | Make unverified work visible in the report. | A run with one completed journey and three blocked journeys displays both counts and the reasons; it does not represent the complete change as verified. |
| FR-09 | Support correction and rerun with unambiguous result identity. | Editing a journey and rerunning produces results tied to the new version; historical evidence is not presented as verification of the edited expectation. |
| FR-10 | Separate evidence about application behavior from tool and setup limitations. | A browser locator failure, an unmet prerequisite, and an observed application error are distinguishable, even if all prevent verification of the intended behavior. |
| FR-11 | Expose the complete first-release workflow through documented local CLI commands. | Jordan can generate, review, execute, inspect, and rerun journeys using the documented commands and an editor, without editing qabot source or invoking internal spike modules. Environment preparation follows the supported D-02 contract. |
| FR-12 | Validate CLI inputs and edited journey artifacts before the dependent operation. | A malformed journey identifies the field or step that needs correction and prevents its execution. A missing required input identifies what must be supplied. Validation does not silently replace the developer's edited expectation. |
| FR-13 | Provide useful terminal feedback during and after execution. | The CLI identifies the current journey, reports final outcome and incomplete-work counts, and gives the report location. A failed prerequisite has an actionable explanation and cannot be mistaken for a successful run. Exit values remain D-05. |
| FR-14 | Show the test-relevant system configuration and initial state for each journey. | A reviewer can see whether custom components are disabled, MCP is allowed, and rate limiting is enabled for the particular execution, including the source and verification status of those values. Required, supplied, and observed state are distinguishable; unknown state and unmet prerequisites are explicit. A global list of requested flags alone does not satisfy this requirement. Secret values are not displayed. |
| FR-15 | Discover and present a local startup plan from repository evidence. | Given a supported repository, qabot identifies the startup/setup commands, relevant configuration, required dependencies, readiness check, and documented seed/reset procedures, citing their sources. Missing or conflicting instructions require developer resolution before the dependent setup operation. Repository inspection alone executes no setup commands. |
| FR-16 | Execute the reviewed startup plan under the profiles required by selected journeys. | The developer corrects a proposed startup command or setting, reviews the plan, and qabot uses that reviewed content. Each journey is associated with the profile actually used; changing the profile requires the applicable startup/configuration procedure. The run does not enumerate unrelated configuration combinations or acquire missing secrets automatically. |
| FR-17 | Enforce and report local setup readiness and lifecycle. | A missing prerequisite or failed startup prevents dependent tests from being treated as executed. The report identifies the failing setup operation and affected journeys. On completion, cancellation, or failure, qabot attempts the reviewed cleanup, stops processes it owns, preserves diagnostics, and reports cleanup failure. It does not terminate unrelated processes. Initial-data reset is recorded separately from browser and process readiness. |
| FR-18 | Reuse valid approval for unchanged reruns and reject stale approval before affected actions. | An unchanged approved plan and journey rerun without another prompt while capturing fresh results. Changing a startup command, its referenced executable setup content, a profile, or a journey expectation requires review of the affected version before it executes. The CLI identifies what changed; each run retains the exact approved versions it used. |

## 6. Outcome Contract for Review

The product must distinguish journey outcomes from finding authority and run
completion. A completed command does not necessarily mean an application passed;
a runtime error does not by itself prove the reviewed code change caused it.

Proposed interpretation of the existing outcome vocabulary:

| Outcome | Meaning | Required distinction |
| --- | --- | --- |
| PASS | Required observations for this journey were verified under the stated conditions. | It does not mean the application, entire change, or unexecuted behavior is correct. |
| FAIL | Observed behavior contradicts the accepted expectation or an applicable failure rule. | Explain the evidence and authority. An expected rejection in a negative test must not fail solely because its message contains the word "error." |
| BLOCKED | The run could not establish whether the required behavior held. | Name the unmet prerequisite, ambiguous interaction, tool failure, missing evidence, or other limitation. |
| Not reached | An individual step was not attempted. | Preserve why it was not reached; it is not a successful step. |

**Pending under D-05:** mixed failure/blockage precedence, reporting of content
awaiting review, intrinsic error applicability, cancellation, command exit semantics,
and which failures stop a journey or the run. The prototype's choices are not
automatically adopted. Run completeness must remain visible regardless of the
summary outcome chosen.

## 7. Production Requirements to Specify

The following concerns must have concrete requirements and acceptance cases before
the PRD is complete. This list does not choose unapproved mechanisms or thresholds.

| Area | Required product decision | Evidence or reason |
| --- | --- | --- |
| Supported environments | Local startup is confirmed; select supported OS/browser/app classes, setup commands, dependencies, and whether attachment to an already-running app is also supported. | Current journey evidence is one Langflow change in Chromium, with Langflow-specific fixture preparation. |
| Identity and data | Developer supplies secrets; qabot uses reviewed documented seed/reset procedures. Specify identity verification, permitted mutations, missing reset behavior, and rerun isolation. | Earlier walks contaminated later runs by creating a flow. New browser contexts do not reset server data. |
| Execution boundaries | Setup uses the reviewed local plan; arbitrary generated executable fixtures are deferred. Specify allowed runtime targets/actions and ambiguous control handling. | The spike clicks the first match after a strict locator error and can materialize model-generated Python. |
| Data handling | What source, page content, credentials, and artifacts may reach model providers; storage, redaction, retention, and deletion rules. | Inputs and observations can contain private project or application data. |
| Failure recovery | Cancellation, model outage, browser crash, startup failure, budget exhaustion, partial-result retention, and cleanup behavior. | These can interrupt execution before a final report exists. |
| Evidence integrity | Required artifacts, run and journey identity, source/environment identity, and behavior when capture fails. | Saved v3 reports reference some earlier launch artifact paths. |
| Performance and cost | Acceptable setup time, run latency, review time, usage budget, and how limits are surfaced. | No accepted production thresholds or representative measurements exist. |
| Operability | Installation/update expectations, diagnostic information, support responsibility, and rollout/rollback criteria. | Passing prototype tests does not establish a supported product release. |

## 8. Validation and Release Criteria

Release acceptance needs both engineering evidence and human assessment of the
workflow. Thresholds, corpus size, supported target diversity, and the release
audience remain pending under D-07 and D-08. They must be agreed before a release
evaluation is scored. Historical small samples must not be converted into a
general accuracy claim.

### Required Validation Cases for Review

| ID | Case | Evidence needed |
| --- | --- | --- |
| AC-01 | Human correction changes what is evaluated. | Correct the inaccurate template expectation; show the reviewed journey version and that version's subsequent execution. Maps to FR-02, FR-03, FR-04, FR-09. |
| AC-02 | The same reviewed journey distinguishes a known healthy and known broken implementation. | A human-adjudicated healthy PASS and broken FAIL with comparable setup, attributable evidence, and no rewrite of the expected behavior between runs. Maps to FR-05, FR-07, FR-10. |
| AC-03 | Missing setup is reported as unverified behavior. | Remove a required flag, credential, or fixture; show the unmet prerequisite and prevented checks. Maps to FR-05, FR-06, FR-08, FR-10. |
| AC-04 | Partial execution remains visible. | Interrupt execution or exhaust its agreed budget; account for completed, blocked, and unattempted work. Maps to FR-06, FR-08, FR-09, FR-10. |
| AC-05 | An expected error is handled correctly. | A reviewed negative journey passes when the application rejects an invalid action as specified; unrelated failures remain separately visible. Maps to FR-07, FR-10. |
| AC-06 | Evidence belongs to the result being reviewed. | Edit and rerun a journey; inspect artifact references and confirm that each verdict retains the correct journey, source, and environment identity. Maps to FR-07, FR-09. |
| AC-07 | Journey relevance and readability survive independent review. | A developer checks the journeys against the supplied change and product behavior, recording unsupported expectations, missing important paths, and edits needed. Maps to FR-01, FR-02, FR-03. |
| AC-08 | Jordan completes the CLI workflow. | On a supported repository and change, Jordan follows documented installation and commands to inspect and correct the discovered startup plan, review it, generate journeys, edit one expectation, run a selected journey through qabot-managed startup, inspect the evidence, and rerun after correction without changing qabot source or writing a runner script. Record every undocumented intervention and usability blocker. Maps to FR-03, FR-09, FR-11, FR-13, FR-15, FR-16. |
| AC-09 | Invalid CLI input fails actionably before dependent execution. | Supply a malformed edited journey and omit a required input in separate attempts. Each error identifies the correction needed; no browser action executes the invalid journey and no edited content is silently regenerated. Maps to FR-03, FR-11, FR-12, FR-13. |
| AC-10 | Per-test configuration evidence reflects the actual execution. | Execute journeys under two different profiles and inspect each result's settings, identity, fixture state, and evidence sources. Introduce a configuration override in a control case; a requested flag must not be reported as observed merely because it was supplied. Unknown effective values are explicit. When flag behavior is itself the subject of the test, evidence that the flag is ignored remains available as a possible application failure. Maps to FR-05, FR-07, FR-10, FR-14. |
| AC-11 | Startup discovery is reviewable and uncertainty is explicit. | Use a supported repository with documented startup/configuration and a control variant containing conflicting instructions or a missing prerequisite. Inspect the cited plan before commands execute. Correct a command and verify that only reviewed content is executed; unresolved required setup prevents its dependent operation. Maps to FR-12, FR-15, FR-16. |
| AC-12 | Setup failure and cleanup remain visible. | Separately exercise startup failure, missing fixture/reset capability, cancellation after startup, and cleanup failure. Check that affected journeys and unverified state are accounted for, diagnostics survive, and unrelated processes are untouched. A stale healthy instance must not be accepted as proof that this run started the requested revision/profile. Maps to FR-05, FR-06, FR-10, FR-14, FR-16, FR-17. |
| AC-13 | Approval is reusable, version-specific, and checked before execution. | Approve a startup plan and two journeys. Rerun one unchanged journey without another prompt and confirm fresh evidence. In separate cases change its expectation, its profile, a startup command, and a referenced setup script while keeping its path; the affected content must await renewed review before executing. The other journey retains its own approval. Prior results retain their original identities. Maps to FR-03, FR-04, FR-09, FR-12, FR-16, FR-18. |

### Metrics to Define Before Scoring

- Journey usefulness: proposed journeys accepted, edited, or rejected by a human,
  with reasons and review time. Acceptance is not proof that coverage is complete.
- Verification completion: selected eligible journeys whose required observations
  were verified, with blocked and excluded journeys reported separately.
- False failures: healthy evaluated cases receiving FAIL, plus the fraction of
  reported failures adjudicated incorrect. These have different denominators.
- Missed defects: known broken cases incorrectly receiving PASS. BLOCKED broken
  cases must also be reported so inability to execute cannot inflate detection.
- Repeatability: agreement and evidence stability across equivalent independent
  runs, including the state-reset procedure.
- Time and cost: journey authoring, human review, environment preparation, execution,
  and rerun costs measured separately on the agreed representative workload.
- CLI usability: Jordan's completion of AC-08, undocumented interventions, manual
  runner work, and blockers encountered. Resolve usability blockers before treating
  the CLI workflow as validated for the later web-interface discussion.

The existing 506 passing tests and the two successfully retried browser tests are
implementation evidence. They do not satisfy the release cases or define accuracy.

## 9. Decision Register

Jordan is the decision maker for this PRD drafting process. No selection in this
table should be inferred from an existing implementation. Recommendations are
proposals for discussion.

| ID | Decision needed | Current status | Blocks |
| --- | --- | --- | --- |
| D-01 | First-release surface. | Resolved: local CLI. Jordan evaluates usability first; a local web interface is a later direction. Exact command grammar remains to be specified. | Delivery choice resolved; detailed CLI acceptance is proposed in section 4. |
| D-02 | Environment responsibility and provisioning boundary. | Resolved: repo/documentation-based discovery, reviewed local startup/setup, explicit journey profiles, readiness checks, and per-test configuration/state evidence. Developer supplies host tools and secrets. General infrastructure provisioning is deferred. | Scope resolved; supported setup types remain D-04 and detailed outcome rules D-05. |
| D-03 | Human-review contract and approval reuse. | Resolved: explicit approval once per startup-plan/journey version; unchanged reruns need no further prompt; execution-affecting edits require renewed review. Detailed change cases are specified in section 4 for acceptance review. | Policy resolved; CLI syntax and artifact encoding remain to be specified. |
| D-04 | Supported inputs and targets: change formats, intent sources, app types, OS, browsers, and initial integration boundary. | Accepted by the subsequent build instruction: macOS and Chrome/Chromium, local Git repository with base/head and optional description; validate Langflow plus the unrelated bundled shop. Initial setup is reviewed local commands, existing host tools, supplied secrets, and readiness checks. | Implementation and walkthrough validation underway; not a cross-platform support promise. |
| D-05 | Outcome and execution rules, including negative tests, tool failures, partial runs, cancellation, and any exit codes. | Section 6 is proposed for review. | Reliable reporting and acceptance tests. |
| D-06 | Model access and data handling; required evidence formats and retention. | Not decided. | Privacy, cost, installation, evidence completeness. |
| D-07 | Quantitative quality, time, and cost thresholds; independent adjudication method and evaluation corpus. | Metrics and candidate cases listed; no target numbers accepted. | A measurable release decision. |
| D-08 | Initial release audience, rollout stages, acceptance owner, and support/rollback responsibility. | Jordan is the first CLI usability evaluator. Broader release audience and operating responsibilities remain undecided. | Release plan and operational readiness. |

Next drafting step: select the supported inputs and local application setups under
D-05 through D-08. The local pilot below supplies implementation evidence; it does
not silently settle release ownership, quality thresholds, or privacy policy.
Once these are agreed, complete the production requirements and validation thresholds,
check requirement-to-acceptance traceability, and submit the complete PRD for review.

## 10. Evidence Register

Local evidence was inspected on 2026-09-06. Saved browser reports were read, but their
screenshots were not independently re-adjudicated during this PRD assessment.
Gitignored artifacts are available in this checkout; they are not a durable release
evaluation package yet. External market assertions have not been reverified.

- [Project assessment and test history](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qabot_current_state.md).
- [Journey spike design](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/superpowers/specs/2026-09-05-user-journeys-design.md).
- [Written Langflow evaluation](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/EVAL.md:799).
- [Fixed v3 report: zero PASS, one FAIL, six BLOCKED](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qa-artifacts/journeys-2026-09-05/launch_fixed_v3/report.md).
- [Broken v3 report: zero PASS, two FAIL, five BLOCKED](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qa-artifacts/journeys-2026-09-05/launch_broken_v3/report.md).
- [Recorded experimental ground truth](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qa-artifacts/journeys-2026-09-05/GROUND_TRUTH.md).
- [Strategy and acknowledged demand gaps](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/STRATEGY.md).
- [Existing settings-group launcher](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/spikes/journeys/launcher.py): accepts a supplied command, applies environment settings, and checks a health URL; discovery is not implemented here.
- [Current evidence gathering](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/spikes/journeys/evidence.py): collects diff context and related tests; it does not discover a repository's startup plan.
- [Current precondition checks](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/spikes/journeys/walker.py:305): compare supplied settings, with no check when the environment is unknown; they do not establish effective runtime configuration.

## 11. Decision Log

| Date | Decision | Authority |
| --- | --- | --- |
| 2026-09-06 | Center the first release on developer-focused, human-reviewed QA journeys from code changes; execute in a controlled test environment and report evidence and unverified work. | Jordan's explicit confirmation in conversation. |
| 2026-09-06 | Exclude anonymous scanning and automatic merge blocking from the first release. | Included in the scope proposal Jordan confirmed. |
| 2026-09-06 | Start with a local CLI and validate Jordan's ability to use it seamlessly before pursuing a local web interface. | Jordan: "Start with local CLI. If I can use it seamlessly, we can easily transition that to a local web interface." |
| 2026-09-06 | Each test must expose the relevant system configuration/state to its reviewer; configuration before startup matters to test scope. Repo/documentation-based application setup is desired, with v1 versus later provisioning scope still under discussion. | Jordan's explicit state-visibility requirement and provisioning question. |
| 2026-09-06 | Include repo-informed, human-reviewed local startup in v1, with readiness checks, explicit per-test configuration/state evidence, and actionable unsupported-setup handling. Defer general infrastructure provisioning. | Jordan's explicit confirmation of the reviewed local-startup boundary. Resolves D-02 and the provisioning scope left open in the preceding entry. |
| 2026-09-06 | Approve each startup-plan and journey version once; rerun unchanged versions without another approval prompt; review execution-affecting edits before they execute. | Jordan's explicit confirmation of approval once per version. Resolves D-03. |

## 12. Implementation-Informed Pilot

Jordan subsequently requested implementation, a manual walkthrough, and iterative
real-browser validation of PRs 14931 and 14913. The isolated implementation lives
at `/private/tmp/qabot-cli-2026-09-06`, branch `feature/qabot-journeys-cli`. This
section distinguishes observed pilot behavior from production requirements above.

### Implemented CLI Contract

```text
qabot journeys plan --repo PATH --base REF --head REF [--description FILE] --out PLAN.json
qabot journeys approve PLAN.json --reviewer NAME
qabot journeys run PLAN.json --out NEW_RUN_DIR [--headed] [--channel chrome|chromium]
                   [--env-file PRIVATE_DOTENV] [--journey ID]
```

- Discovery is non-executing and bounded. It collects scoped Git changes, current
  documentation, manifests, configuration definitions, related tests, and local
  UI/import entry points. Real environment files are excluded from model evidence.
- Plans are editable JSON. Approval is adjacent JSON recording reviewer identity,
  semantic plan identity, timestamp, and referenced local executable script hashes.
  Automated example reviews remain explicitly agent-reviewed, never human-confirmed.
- Run checks approval before launching, checks the actual checkout revision, refuses
  an already-serving health endpoint, starts the approved local command, and checks
  readiness. Unknown or mismatched required settings block execution.
- `--env-file` loads only credential names required by the plan. Explicit nonsecret
  plan values take precedence. The model acts using `${NAME}` references rather
  than receiving credential values. Startup is not an untrusted-code sandbox.
- A fresh browser context is used per journey. Optional reviewed reset commands
  support applications that expose a reset mechanism; lack of persistent-state
  reset is reported rather than concealed.
- Every executed journey requires video. HTML, JSON, Markdown, screenshots, startup
  logs, and partial-result explanations are retained under a new run directory.
- The pilot exit contract is 0 for all PASS, 1 for any FAIL, 2 for BLOCKED
  without FAIL or invalid input/approval, and 130 for user cancellation with partial
  evidence retained. This is the implementation baseline for
  D-05 review, not an assertion that all release-policy cases were accepted.
- Intentional application rejection is evaluated against its expected diagnostic;
  it is not automatically a defect. Unrelated browser crashes cannot become PASS
  solely because a step is marked `expected_error`.
- Bounded browser waits use observable visible/hidden/enabled conditions, up to
  60 seconds per action. A submitted asynchronous build is not proof of completion.
- Credential text is redacted from model inputs and reports, and credential-named
  references require masked browser inputs. General pixel redaction is absent;
  an application reflecting a secret visibly can expose it in recorded evidence.

### Evidence and Findings

1. Installed headed Google Chrome interaction and recording passed. A local runner
   integration test decoded its WebM in Chrome and confirmed owned-process cleanup.
2. Real discovery initially timed out, hallucinated a fictional shop from unrelated
   planning-document diffs, omitted the Assistant route, and lacked startup details.
   Those attempts were retained. Scoped diffs and semantic excerpts corrected the
   evidence collection. Langflow v3 discovery finds a documented startup command
   and the Assistant flow-build route, but still needed substantive review of flags,
   fixtures, and successful-run expectations. Discovery quality is not release-proven.
3. The independent shop's fresh complete run passes widget/cart and valid checkout.
   Its expired-card journey fails both the generic message and lost-cart assertions;
   all three videos are playable (29.24, 35.56, 50.76 seconds). Earlier BLOCKED
   observations and invalid discovery attempts remain retained. Live shop discovery
   v4 corrects a known-defect-as-success oracle seen in v3; startup review remains
   necessary, and one success does not establish general authoring accuracy.
4. Exact fixed Langflow revision `d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`
   contains both PR fixes. Real Watsonx inference created and successfully executed
   Chat Input -> Agent -> Chat Output through the API with restricted/lazy flags.
   API proof is not substituted for the separately required editor/Assistant videos.
   The packaged Assistant run now passes all seven browser steps, including actual
   three-node/two-edge generation, canvas application, and a completed Watsonx
   Playground reply. Root inspected its final screenshot and decoded its 171.36-second
   video in Chrome. A second same-database run also passes using dashboard New Flow,
   preserving the first flow and producing a new completed reply (155.32-second video).
   The repeat records a changed target lockfile; no application source changed.
   Expected auto-login 403 and completed-stream abort QUESTION evidence remain
   visible in results, so this is not a claim of an error-free network trace.
5. The PR14931 recorded CLI browser run correctly FAILS the requested expectation.
   The canvas shows only the missing-model complaint, not the policy explanation.
   Source investigation identifies an early terminal AG-UI error before the enriched
   vertex error arrives. The legacy build SSE does contain the note. This is a
   residual user-facing defect, not a reason to weaken the browser acceptance test.
6. The editor route completes browser login, fresh-flow creation, sidebar additions,
   exact model selection, both named connections, and real Playground inference.
   Root decoded its final 249.88-second video and independently reviewed canvas/response
   screenshots; database inspection confirms three nodes and two correct edges.
   An earlier run shortened the reviewed prompt and overstated a date response's
   relevance. Literal-input guidance plus an explicit submitted-input check corrected
   that case: final3 preserves the full user message and receives the intended real
   reply. All 13 steps are independently supported. Generic action-fidelity enforcement
   remains a release requirement, not a guarantee established by this example.

Final code verification: 649 tests passed, 1 legacy live-model test deselected;
Ruff and whitespace checks passed. The real Claude/Watsonx browser runs above are
separate product evidence, not substituted by mocked model tests.

Pilot walkthrough and evidence locations:

- `/private/tmp/qabot-cli-2026-09-06/examples/WALKTHROUGH.md`
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-diagnostic-run1/report.html`
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1343/report.html`
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-final/report.html`
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/report.html`
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-20260906/discovered-plan-v3.json`
- `/private/tmp/qabot-cli-2026-09-06/examples/shop/live-validation-report.md`

### Remaining Release Gaps

The following requirements are not silently marked complete by the pilot:

- Independently reusable startup/journey approvals: current implementation binds
  the entire plan, so unrelated journey edits also invalidate it.
- Universal effective-configuration, role, and fixture attestation: supplied
  environment and health readiness are distinguished, but arbitrary application
  state cannot yet be verified automatically. Langflow-specific API/process
  observations are supplementary evidence, not a generic attestation capability.
- Dependency and prebuilt-asset identity, setup-script indirection, supported
  provisioning recipes, and complete cancellation/failure-lifecycle guarantees
  require explicit production acceptance coverage.
- Cross-origin SSO, credential lifecycle, retention policy, model cost budgets,
  independent accuracy thresholds, release owner, rollout, and rollback remain
  D-05 through D-08 decisions.
- The current model reads text/accessibility outlines, not visual pixels. Actual
  screenshot/video review is required to adjudicate spatial visibility and overlap;
  text-based PASS is not a visual-correctness guarantee.
- Exact reviewed-action fidelity needs enforcement and acceptance coverage. A changed
  submitted value must be surfaced as a tool deviation and must not receive an
  unqualified reviewed-journey PASS. Preserve separately verified application
  behavior, such as successful inference, without claiming exact-input compliance.

Production acceptance must include both known-broken and known-fixed applications,
independent adjudication of the actual videos, no missed known defects labeled PASS,
and a first-use walkthrough by Jordan. Passing unit tests alone does not satisfy it.
