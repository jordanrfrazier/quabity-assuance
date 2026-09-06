# qabot Current State

Last assessed: 2026-09-06.
Directory: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`.
Branch: `feature/qabot-scan`. Current HEAD: `df7d2d4`.
Initial code/test assessment was performed at `ccc3698` with the existing working tree.

## Authorized Implementation Worktree

Jordan subsequently authorized building the local CLI and iterating with a team
until real browser/video examples work. Implementation, the updated PRD, and full
current build status are at `/private/tmp/qabot-cli-2026-09-06`, branch
`feature/qabot-journeys-cli`. This original workspace's earlier code/docs edits are
preserved; this section is a handoff pointer, not a replacement of that history.

- Current implementation state: `/private/tmp/qabot-cli-2026-09-06/qabot_current_state.md`.
- Manual walkthrough: `/private/tmp/qabot-cli-2026-09-06/examples/WALKTHROUGH.md`.
- Updated PRD: `/private/tmp/qabot-cli-2026-09-06/docs/PRD.md`.
- Actual shop report: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-final/report.html`.
- Repeated Assistant PASS: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1348-repeat/report.html`.
- Editor PASS with exact submitted input and real response: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/report.html`.
- PR14931 browser FAIL (missing policy explanation): `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-diagnostic-run1/report.html`.

The packaged CLI discovers/reviews startup plans, starts local applications, records
real Chrome journeys, and writes local HTML/JSON/Markdown evidence. Headed Chrome
and recording permissions work. Final code suite: 649 passed, 1 legacy live-model
test deselected; both editor and Assistant videos were independently verified.
The walkthrough is ready; production acceptance remains separate. A direct
manual shop is running at `http://127.0.0.1:7888/ui` for this session. No commits,
pushes, publication, or ticket changes were made.

## Current Objective

Produce a production-grade product requirements document (PRD). Jordan confirmed
the following product scope on 2026-09-06:

For developers reviewing a code change, qabot generates understandable QA journeys,
lets a human correct their expected outcomes, executes them against a controlled
test environment, and reports evidence plus anything it could not verify.

Anonymous scanning and automatic merge blocking are outside the first release.
The PRD draft is at
[/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/PRD.md](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/PRD.md).
Product direction and local CLI delivery are confirmed. Jordan will evaluate CLI
usability before pursuing a local web interface. The PRD now proposes an end-to-end
CLI acceptance path: generate, review/edit, run a selected journey, inspect evidence,
and correct/rerun through documented commands, without source edits or custom runner
scripts. The web interface is later work, with no framework or web API required now.

Jordan clarified that each test must show its relevant system configuration/state
to the reviewer, for example custom components disabled, MCP allowed, and rate
limiting enabled. This is now FR-14 with acceptance case AC-10 in the PRD.

Jordan confirmed D-02: include repo-informed, human-reviewed local setup/startup
in v1, under explicit journey profiles, with readiness checks and per-test state
evidence. The developer supplies host tools and secret values; qabot can reuse
reviewed documented setup and seed/reset procedures. General infrastructure
provisioning and arbitrary generated executable fixtures are deferred. Unsupported
setup blocks the affected tests with a concrete missing requirement.

The PRD now includes startup discovery, reviewed execution, and setup lifecycle
requirements FR-15 through FR-17, with AC-11 and AC-12. AC-08 includes Jordan's
review of the startup plan and qabot-managed startup. D-02 is resolved; the set
of supported local setups remains D-04.

Jordan confirmed D-03: explicit approval once per startup-plan/journey version,
unchanged reruns without another prompt, and renewed review after execution-affecting
edits. The PRD specifies invalidation examples, separate plan/journey approvals,
fresh evidence on reruns, and recording the approved versions used. These details
are acceptance-review material under the approved policy. FR-18 and AC-13 cover
approval reuse and stale-approval rejection. Application revision and approved
procedure identity remain separate so the same journey can compare broken/fixed
builds; changed executable setup inputs still require renewed review.

The next question, D-04, is pending. Recommendation, not accepted: macOS and Chromium,
local Git repo with base/head revisions and optional change description, validated
on Langflow plus one unrelated web app. Alternatives are Langflow-only initially
or supporting macOS and Linux from the first release. Exact supported local setup
types must also be defined once the release scope is selected.

Supplied environment variables must be distinguished from effective runtime
configuration; source, verification status, and unknown values matter. A readiness
response does not prove the app honored every flag. State setup failure and a
defect in the flag behavior being tested must remain distinguishable. These
acceptance details, support boundaries, and quantitative release criteria are
still subject to review.

## Assessment

The repository has substantial prototype code and unusually candid evaluation
records. At the initial assessment it had no single current product contract.
Its three existing directions serve
different users, require different inputs, and make different promises:

| Direction | Current capability | Evidence and limit |
| --- | --- | --- |
| CI merge gate | Seeds workflows from tests, selects by diff, executes and grades, emits some regression tests | Recorded expectation-tier evaluation: 28 findings, all false positives, because fixture/configuration/identity context was lost. Runtime-error detection performed better in a separate experiment; that result does not validate the expectation tier. |
| URL scan | Anonymous discovery, browser sweep, intrinsic checks, HTML report | Shipped code is distinct from the newer visitor-experience experiments. Source-map resolution exists but is unwired. Evaluation records false positives, limited authenticated reach, and unintended mutations; read-only behavior cannot be treated as an established guarantee. |
| User journeys | Authors readable steps from a diff; walks in Chromium; records JSON, Markdown, screenshots and optional video; includes local instance launch and fixture preparation | Lives in a spike, with Langflow-specific assumptions. One real PR provides feasibility evidence, not general product validation. Saved v3 results contain no PASS journeys on either build. |

Decision: user journeys are now the PRD's primary unit, with human review central
to the workflow. This scope decision is not evidence of customer demand or reliable
automated verification. Existing scan and merge-gate code remains evaluation context;
the PRD work does not authorize changes to those implementations.

## Most Relevant Evidence

- [README](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/README.md)
  still describes two products and does not cover the journey spike.
- [Evaluation](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/EVAL.md:799)
  describes the first journey experiment: a wrong UI assumption, missing environment
  requirements, false failure on the fixed build, and a visible regression not
  distinguished by the verdicts.
- [Fixed v3 report](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qa-artifacts/journeys-2026-09-05/launch_fixed_v3/report.md)
  records 0 PASS, 1 FAIL, 6 BLOCKED. The main starter journey blocks on an authored
  expectation of eight templates when 26 are visible.
- [Broken v3 report](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/qa-artifacts/journeys-2026-09-05/launch_broken_v3/report.md)
  records 0 PASS, 2 FAIL, 5 BLOCKED. The main starter journey fails by inference.
  This is partial differentiation, not a demonstrated healthy-pass/broken-fail pair.
- The v3 reports are additional saved evidence beyond the written evaluation.
  Their screenshots were not independently adjudicated in this assessment. Some
  report evidence paths reference the earlier launch directories; immutable run
  identity and artifact integrity need explicit requirements.
- [Strategy](/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/docs/STRATEGY.md)
  contains successive positioning changes and acknowledges missing primary buyer
  evidence. Its 12-of-100 consequence figure is qualified by deployment-selection
  corrections in the evaluation. Owner willingness to fix or pay is unvalidated.
  External market assertions were not reverified in this local assessment.

## Gaps the PRD Must Resolve

1. **Release boundary.** Primary direction and user are confirmed: human-reviewed
   user journeys for developers reviewing code changes. Local CLI delivery and Jordan
   as the first usability evaluator are confirmed. Select supported applications and
   the broader release audience. Buyer and business model remain unvalidated.
2. **Authority for expected behavior.** Approval per plan/journey version and
   renewed review after execution-affecting edits are confirmed. Review the detailed
   invalidation cases and CLI interaction. Current spike journey provenance remains
   `inferred_from_diff`; code changes and model judgments alone do not establish
   intended behavior.
3. **Outcome and coverage semantics.** Define PASS, FAIL, BLOCKED, not reached,
   invalid setup, tool failure, and any CI exit behavior. Specify the evidence
   needed for each and how partial runs are summarized. Inferred QUESTION findings
   currently still yield journey FAIL, while the command returns zero after a run.
4. **Environment contracts.** Repo-informed reviewed local startup, developer-supplied
   host tools/secrets, and documented seed/reset reuse are confirmed. Specify the
   supported setup types, identity/state checks, mutation boundaries, and resets.
   Current spike preconditions are prose; unknown environment settings do not block
   its execution. A fresh browser context does not isolate server-side data.
5. **Execution boundaries.** Decide permitted targets/actions, handling of ambiguous
   controls, external navigation, and generated fixture code. The journey walker
   currently retries an ambiguous locator by clicking the first match; the launcher
   inherits the process environment and can load model-generated Python fixtures.
   These are prototype behaviors, not established production policies.
6. **Evidence and failure handling.** Define required artifacts, source revision,
   journey revision, environment identity, retention/deletion, redaction, cancellation,
   partial-result persistence, and behavior when recording or model calls fail.
7. **Measurable acceptance.** Agree on human-adjudicated paired healthy/broken cases,
   journey usefulness, execution completion, false failures, missed defects,
   blocked rate, repeatability, review time, latency, and cost. Set denominators and
   release thresholds before evaluating; do not invent targets from this one PR.
8. **Release ownership.** Identify who accepts requirements, adjudicates findings,
   approves launch, handles incidents/support, and evaluates rollout or rollback.

These are unresolved decisions and requirement categories, not authorization to
implement additional features. The existing design and implementation plans are
inputs to the PRD; they do not replace measurable product acceptance criteria.

## Verification This Session

Executed using the existing environment, with no dependency synchronization:

```sh
env UV_CACHE_DIR=/private/tmp/quabity-uv-cache uv run --offline --no-sync pytest -q tests spikes/journeys/tests -m 'not browser and not live_llm'
```

Result: **506 passed, 2 failed, 62 deselected** in 11.67 seconds. Both failures are
in the journey run tests and occur at Chromium launch: macOS sandbox permission
denied for MachPortRendezvousServer. Those two tests use a real browser but lack
the `browser` marker. This is not evidence of application assertion failure.
Browser behavior and live-model accuracy were not freshly verified in that run.

The initial `uv run --offline` attempt could not create its default cache directory;
the command above used a writable temporary cache and the installed environment.
No application code was changed and no external scans or model calls were run.

After Jordan changed the session to full access, reran only the two blocked tests:

```sh
uv run --offline --no-sync pytest -q spikes/journeys/tests/test_run.py::test_launch_mode_starts_app_per_settings_group spikes/journeys/tests/test_run.py::test_model_outage_blocks_the_journey_instead_of_crashing
```

Result: **2 passed in 13.87 seconds**. Chromium startup and these two local browser
test paths now work. The default uv cache no longer prevented the command from
running. The permission blocker is resolved; the full browser suite and live-model
accuracy remain unverified. No application code changes were required.

## Working Tree and Next Steps

Current HEAD is `df7d2d4` (`docs`), a commit made outside this agent's actions.
The PRD and state file have unstaged edits; Spec Kit and agent configuration are
untracked. Preserve that work. No staging or commits were performed by this agent.
Spec Kit's constitution remains an unfilled template; no feature spec/plan/tasks
set was found. The PRD draft was created after the scope confirmation. Local run
evidence is gitignored.

1. Resolve D-04: supported platforms, change inputs, target applications, and local
   setup types; the clarification is pending.
2. Resolve D-05: detailed outcome/partial-run semantics and CLI exit behavior.
3. Complete the PRD's requirement IDs, priorities, testable acceptance criteria,
   failure states, nonfunctional requirements, rollout gates, and evidence links
   as the corresponding decisions are made.
4. Resolve open decisions and review traceability and contradictions before calling
   the PRD production-grade. Keep prototype capabilities and release requirements
   explicitly distinguished.

Session changes: the PRD draft and this state file, renamed from
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/project_current_state.md`
to match Jordan's updated naming instruction. No application code changes, commits,
pushes, publishing, messages to others, or changes to external systems.
