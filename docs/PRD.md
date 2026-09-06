# qabot: Human-Reviewed QA Journeys

Status: Working draft; product direction confirmed, release contract incomplete.
Date: 2026-09-06.
Decision maker for this drafting process: Jordan.
Project directory: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`.
Working branch: `feature/qabot-scan`.

## 1. Product Definition

For developers reviewing a code change, qabot generates understandable QA journeys,
lets a human correct their expected outcomes, executes them against a controlled
test environment, and reports evidence plus anything it could not verify.

Jordan confirmed this product direction on 2026-09-06. Human review is central to
the first release. Anonymous scanning and automatic merge blocking are excluded.

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

The initial release audience, frequency of use, buyer, and willingness to pay have
not been established. The project evidence supports investigating this workflow;
it does not establish commercial demand or general verification accuracy.

## 3. Goals and Boundaries

The first release should enable a developer to:

- Understand why each proposed journey is relevant to a code change.
- Review and correct actions, expectations, and necessary setup before execution.
- Execute the reviewed journeys against a controlled test environment.
- Inspect outcomes and supporting evidence, including incomplete coverage.
- Correct a journey and rerun it without confusing old and new results.

**Confirmed exclusions:** anonymous URL scanning and automatic merge blocking.

The delivery surface is not selected. No CLI, web interface, CI integration,
hosted service, authentication automation, automatic fixture generation, or
regression-test export is committed by this draft. These are scope decisions,
not features that enter the first release because related prototype code exists.

## 4. Core Workflow

1. **Provide the change.** The developer identifies the change and supplies the
   available explanation of intended behavior. Supported input formats are pending.
2. **Inspect proposed journeys.** qabot presents each journey's purpose, relationship
   to the change, preconditions, actions, and expected observations.
3. **Review and correct.** The developer can correct the journeys and decide which
   ones to run. The exact mechanism for recording review is pending.
4. **Establish readiness.** The required configuration, identity, data, and external
   dependencies are accounted for before the corresponding behavior is evaluated.
   Responsibility for preparing the environment is pending.
5. **Execute.** qabot attempts the selected journeys within the agreed environment
   and reports outcomes with evidence and reasons for incomplete work.
6. **Inspect and rerun.** The developer distinguishes an application issue from an
   incorrect journey or unmet setup, corrects the relevant input, and runs again.
   Each result remains associated with the journey and environment it evaluated.

## 5. Functional Requirements

All rows are candidate first-release requirements derived from the confirmed
workflow. Acceptance examples define observable behavior without prescribing an
implementation or selecting unresolved release details.

| ID | Requirement | Acceptance example |
| --- | --- | --- |
| FR-01 | Generate reviewable journeys relevant to the supplied change. | Each journey describes a user goal and identifies the supplied evidence that makes it relevant. An absent or unsupported connection is visible to the reviewer. |
| FR-02 | Each journey states preconditions, actions, and expected observations. | A reviewer can distinguish what to do from what should happen and identify the setup on which the expectation depends. Missing required information is exposed before execution. |
| FR-03 | Allow human correction before execution. | The developer changes an incorrect expected template count; the next execution evaluates the corrected expectation. The generated wording does not silently reappear. |
| FR-04 | Preserve the distinction between generated and human-reviewed expectations. | A model-generated expectation is not described as human-confirmed merely because the model executed or judged it. The precise approval and revision mechanism is decided under D-03. |
| FR-05 | Make required environment conditions explicit. | A journey requiring a feature flag or model credential does not report an application defect solely because that prerequisite was missing. Unknown prerequisites are visible. The readiness policy is decided under D-02. |
| FR-06 | Report a result for every selected journey, including incomplete journeys. | An unreachable application or unavailable model produces an explicit account of what could not be verified, with no missing journey that appears implicitly successful. |
| FR-07 | Associate verdicts with inspectable evidence and the evaluated expectation. | A developer can inspect the observed state and understand why the expectation was judged satisfied, contradicted, or uncheckable. Evidence format and minimum completeness are decided under D-06. |
| FR-08 | Make unverified work visible in the report. | A run with one completed journey and three blocked journeys displays both counts and the reasons; it does not represent the complete change as verified. |
| FR-09 | Support correction and rerun with unambiguous result identity. | Editing a journey and rerunning produces results tied to the new version; historical evidence is not presented as verification of the edited expectation. |
| FR-10 | Separate evidence about application behavior from tool and setup limitations. | A browser locator failure, an unmet prerequisite, and an observed application error are distinguishable, even if all prevent verification of the intended behavior. |

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

**Pending under D-05:** mixed failure/blockage precedence, treatment of unreviewed
execution, intrinsic error applicability, cancellation, command exit semantics,
and which failures stop a journey or the run. The prototype's choices are not
automatically adopted. Run completeness must remain visible regardless of the
summary outcome chosen.

## 7. Production Requirements to Specify

The following concerns must have concrete requirements and acceptance cases before
the PRD is complete. This list does not choose unapproved mechanisms or thresholds.

| Area | Required product decision | Evidence or reason |
| --- | --- | --- |
| Supported environments | Supported OS/browser/app classes; local versus remote test environments; required installation and dependencies. | Current journey evidence is one Langflow change in Chromium, with Langflow-specific fixture preparation. |
| Identity and data | Who supplies credentials and fixtures; how initial state is established; permitted mutations; cleanup and rerun isolation. | Earlier walks contaminated later runs by creating a flow. New browser contexts do not reset server data. |
| Execution boundaries | Allowed targets and actions; ambiguous control handling; responsibility for any generated executable fixture. | The spike clicks the first match after a strict locator error and can materialize model-generated Python. |
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

The existing 506 passing tests and the two successfully retried browser tests are
implementation evidence. They do not satisfy the release cases or define accuracy.

## 9. Open Decisions

Jordan is the decision maker for this PRD drafting process. No selection in this
table should be inferred from an existing implementation. Recommendations are
proposals for discussion.

| ID | Decision needed | Current status | Blocks |
| --- | --- | --- | --- |
| D-01 | First-release surface: local CLI, local web interface, or CI integration. | Asked. Recommendation: local CLI with editable journeys and HTML evidence, using existing capabilities. Not accepted yet. | Review interaction, packaging, distribution, command/UI acceptance. |
| D-02 | Environment responsibility: developer-prepared app versus tool-managed launch/setup; permitted targets, identity, state, and dependencies. | Not decided. | Readiness, mutation policy, reproducibility, support scope. |
| D-03 | Human-review contract: required approval, who can approve, version binding, and what edits invalidate it. | Human review is central; exact contract not decided. | Authority of expectations and execution eligibility. |
| D-04 | Supported inputs and targets: change formats, intent sources, app types, OS, browsers, and initial integration boundary. | Not decided. | Scope, authoring fidelity, installation and compatibility acceptance. |
| D-05 | Outcome and execution rules, including negative tests, tool failures, partial runs, cancellation, and any exit codes. | Section 6 is proposed for review. | Reliable reporting and acceptance tests. |
| D-06 | Model access and data handling; required evidence formats and retention. | Not decided. | Privacy, cost, installation, evidence completeness. |
| D-07 | Quantitative quality, time, and cost thresholds; independent adjudication method and evaluation corpus. | Metrics and candidate cases listed; no target numbers accepted. | A measurable release decision. |
| D-08 | Initial release audience, rollout stages, acceptance owner, and support/rollback responsibility. | Not decided. | Release plan and operational readiness. |

Next drafting step: resolve D-01, then specify the environment and review contracts.
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

## 11. Decision Log

| Date | Decision | Authority |
| --- | --- | --- |
| 2026-09-06 | Center the first release on developer-focused, human-reviewed QA journeys from code changes; execute in a controlled test environment and report evidence and unverified work. | Jordan's explicit confirmation in conversation. |
| 2026-09-06 | Exclude anonymous scanning and automatic merge blocking from the first release. | Included in the scope proposal Jordan confirmed. |
