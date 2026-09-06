# qabot Current State

Last assessed: 2026-09-06.
Directory: `/private/tmp/qabot-cli-2026-09-06`.
Branch: `feature/qabot-journeys-cli`. Current HEAD: `df7d2d4` (uncommitted implementation).
Original workspace: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`,
branch `feature/qabot-scan`; its earlier edits are preserved.
Initial code/test assessment was performed at `ccc3698` with the existing working tree.

## Current Objective

The overarching objective is a production-grade PRD. The authorized build is now
the active task: deliver a working local
CLI and real browser/video walkthrough, then use its findings to refine the PRD.

Jordan confirmed the following product scope on 2026-09-06:

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

### Active Build: 2026-09-06

Jordan authorized implementation and a team, with real browser/video validation of Langflow PRs 14931 and 14913, including the Assistant creation/build route. The implementation is isolated at `/private/tmp/qabot-cli-2026-09-06`, branch `feature/qabot-journeys-cli`; original workspace edits remain untouched. No commits or remote writes are authorized.

Plan: `/private/tmp/qabot-cli-2026-09-06/docs/superpowers/plans/2026-09-06-journeys-cli.md`.

- Accepted initial scope: local CLI, macOS/Chrome, local git base/head and optional change description; Langflow plus an unrelated local application.
- Real headed Google Chrome interaction and video recording passed. Full baseline: 569 passed, 1 live-model test deselected.
- Existing local Langflow `.env` provides required credentials. OpenAI authentication passed but inference later failed for exhausted quota; real Assistant tests use the existing funded Watsonx provider instead. Claude CLI JSON completion passed after the 12:40pm quota reset.
- Foundation agent owns plan discovery and approval. Root owns browser runner, reports, and CLI. Setup agent owns isolated Langflow prerequisites.
- PR14931 deliberately expects a rejected build with a policy diagnostic, not a successful restricted custom-component build. Added an explicit expected-error step flag.
- Proposed execution exit contract implemented for validation: 0 all PASS, 1 any FAIL, 2 BLOCKED without FAIL; invalid or stale approval prevents launch. These are implementation decisions, not yet release acceptance evidence.
- Five browser regressions pass: expected error, unexpected error, ambiguous controls, partial model-failure evidence, unknown required settings.
- Next: complete startup/report integration, validate both real PR routes and unrelated app, iterate on invalid results, update PRD with evidence and remaining release gaps.

### Live Validation and Corrections

- Packaged commands now exist: `qabot journeys plan`, `approve`, and `run`. Runs create new HTML/JSON/Markdown artifacts, real Chrome videos and screenshots, retain partial browser/model failures, and clean their owned application process group. `--env-file` imports only names explicitly required by the reviewed plan and cannot override its nonsecret feature flags.
- Independent review found and fixed stale script approval with adjacent shell punctuation, missing MDX/current product documentation, secret-bearing command arguments, secret precondition leakage, delayed browser errors, cross-origin navigation/input exposure, and discarded partial actions. Root added strict structured model responses, keyboard activation, and named-container locator scoping. Focused verification at this checkpoint: 33 tests passed, plus setup tests owned by the discovery reviewer.
- Live discovery first timed out and then omitted important routes; those artifacts were preserved. Relevance-selected semantic excerpts and explicit browser-only authoring produced `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-20260906/discovered-plan-v3.json`, which discovers both editor and Assistant routes. It still requires review: supplied startup flags and genuine model-success expectations needed correction. Human review remains a real boundary, not a cosmetic label.
- Real model provider is authenticated Claude CLI/Sonnet using structured JSON, no tools, no MCP configuration, no session persistence, and safe mode. OpenAI credential authentication succeeded but inference quota failed. The existing Watsonx credential successfully powered the exact fixed Langflow Assistant and a three-node Agent flow. Credential values remain outside plans/reports.
- Exact fixed target: `/private/tmp/langflow-qabot-release-d14`, detached `d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`, containing both PR fixes. Runtime scripts/seed data live at `/private/tmp/langflow-qabot-release-d14-runtime`; setup notes are in its `README.md`. No patches to this fixed target's tracked source.
- PR14931 has a real residual browser-path defect: the legacy build SSE includes the policy Note, but the canvas AG-UI route terminates on the early short error. The browser showed only No model selected and a disabled output inspector. Keep the original expectation and report a browser FAIL if the recorded CLI run confirms this; do not change Langflow or weaken the test to claim the PR works in the browser.
- Local Langflow tracing attempted requests that were rejected with 403. Subsequent reviewed startup explicitly sets `LANGFLOW_DEACTIVATE_TRACING=true`, the authoritative application switch, plus SDK tracing false flags and DO_NOT_TRACK. This behavior is not covered up as offline operation.
- Unrelated shop validation: real CLI Run2 passed widget/cart and valid checkout; Run5 correctly failed the expired-card case with a verified playable 46.72-second video. `/private/tmp/qabot-cli-2026-09-06/examples/shop/live-validation-report.md` records every iteration and remaining discovery/step-classification gaps.
- Recorded diagnostic run is complete: `qa-artifacts/langflow-diagnostic-run1/report.html` is a valid browser FAIL, with a decoded 104.48-second video. The expected policy explanation remains absent on the fixed revision.
- Final full regression after execution/security, bounded-keyboard and literal-input fixes: 649 passed, 1 live-model test deselected in 139.77 seconds. Independent review added reflected/encoded credential coverage in model inputs, reports and startup logs, masked credential inputs, shell working-directory approval bypasses, cancellation with partial evidence and exit 130, and owned-process-group cleanup. Ruff checks pass on edited Python files; `git diff --check` passes. Actual Claude/Watsonx runs are separate from the deselected legacy live-model test.
- Credential text is redacted before model evaluation and report serialization. Credential-named references are refused in non-password inputs. This is not general screenshot/video pixel redaction: an application that reflects secrets visibly can still expose them in visual evidence. Do not use sensitive production data in this pilot.
- Real Assistant generation exceeded the original six-action loop while still running. Added a bounded observable browser wait (visible, hidden, or enabled; default 30 seconds, maximum 60 seconds) with real Chrome tests; generation is not reported as successful merely because it was submitted.
- Editor `qa-artifacts/langflow-editor-20260906-final3` PASS: all 13 steps, three nodes, both correct edges, IBM model binding, exact full submitted input, and real `qabot editor flow works` response (932 tokens/3.8s). Root decoded its 249.88-second Chrome video and inspected canvas, final response and mobile report; independent review confirmed action/report/screenshot agreement. Earlier final2 omitted an input prefix; it is preserved as regression history, corrected by literal-input guidance and an explicit expected-input check. Port 7865 is stopped.
- Assistant CLI run `qa-artifacts/langflow-assistant-20260906-1343` passed all seven steps on d14. Root inspected the real Playground screenshot (WATSONX VERIFIED, 302 tokens, 2.7 seconds) and decoded its 171.36-second video in Chrome. Same-database run `qa-artifacts/langflow-assistant-20260906-1348-repeat` also passes: dashboard New Flow creates a distinct flow, final response 387 tokens/3.1 seconds. Root independently inspected its final screenshot; agent decoded its 155.32-second video. Original flow remains unchanged. Port 7864 is stopped.
- Target `uv.lock` became dirty during validation; it is preserved, not reverted. Root confirms it is the only tracked target diff, with no application source changes. Repeat evidence records the dirty-state limitation; the HEAD alone does not attest installed dependencies. Assistant PASS retains expected auto-login403/completed-stream-abort QUESTION evidence, not an error-free-network claim.
- Real shop discovery v3 finds UI routes but incorrectly makes known defects expected success. A focused intended-behavior instruction and prompt regression (15 setup tests passed) corrected live v4's expired-card oracle. Startup remains unresolved in scoped evidence and requires review; discovery is not autonomously release-ready.
- Fresh complete shop run `qa-artifacts/shop-20260906-final`: PASS/PASS/FAIL, exit 1. Both expired-card observations FAILED correctly. Root decoded all three videos (29.24/35.56/50.76 seconds), inspected the action trace and mobile report; independent evidence review found no material false verdict. The judge's incidental mention of declined describes the reset response form, not the actually submitted expired card.
- Prepared a separate direct-interaction shop at `http://127.0.0.1:7888/ui`, PID 65419 for this session, isolated from CLI test port 7880. Log: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/manual-shop-server.log`. This local demo is intentionally left running for Jordan's walkthrough; test-owned Langflow processes are stopped after their runs.
- Editor investigation proved two issues with the reviewed navigation: Fit view leaves its menu open and hides canvas roles until Escape; sidebar additions overlap at 10px offsets. Manual UI verification proves select Enter then twenty Shift+Arrow presses moves a node exactly 400px and Enter on the two handle pairs creates two edges. Bounded repeated arrow-key support is implemented and tested (maximum 30, never repeated submission keys); final recorded replay verifies the complete flow.
- Qabot lockfile normalization is from the installed uv version dropping upload-time metadata. Structured comparison confirms the only added package version is python-dotenv 1.2.3 and no existing package versions were removed/upgraded.
- The worktree's untracked `.venv` is a symlink to the original environment, synchronized with dev/browser/llm extras; the editable install points here. Run walkthrough commands from this worktree. Do not stage the `.venv` symlink in any later commit. Original source edits remain preserved; only its state-file handoff pointer was added by this build.
- Build handoff is ready: `/private/tmp/qabot-cli-2026-09-06/examples/WALKTHROUGH.md` includes exact commands, videos, repeat instructions and known boundaries. All four example approvals validate; all test-owned app ports are stopped. Only the separate manual shop on 7888 remains running intentionally. Next: Jordan performs the walkthrough and adjudicates the PR14931 browser failure; resolve PRD release gates, including generic action fidelity, configuration/dependency attestation, independent approvals, and accuracy/cost/retention ownership. Do not call the pilot production-certified.

Current HEAD is `df7d2d4` (`docs`), a commit made outside this agent's actions.
The PRD and state file have unstaged edits; Spec Kit and agent configuration are
untracked. Preserve that work. No staging or commits were performed by this agent.
Spec Kit's constitution remains an unfilled template; no feature spec/plan/tasks
set was found. The PRD draft was created after the scope confirmation. Local run
evidence is gitignored.

1. D-04 initial pilot scope is accepted; validate its local CLI, Chrome, repository,
   and reviewed startup boundaries against the walkthrough.
2. Resolve D-05: detailed outcome/partial-run semantics and CLI exit behavior.
3. Complete the PRD's requirement IDs, priorities, testable acceptance criteria,
   failure states, nonfunctional requirements, rollout gates, and evidence links
   as the corresponding decisions are made.
4. Resolve open decisions and review traceability and contradictions before calling
   the PRD production-grade. Keep prototype capabilities and release requirements
   explicitly distinguished.

Earlier discovery-session changes: the PRD draft and this state file, renamed from
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/project_current_state.md`
to match Jordan's updated naming instruction. The subsequent authorized build adds
application code and tests only in the isolated worktree above. No commits, pushes,
publishing, messages to others, or ticket changes were performed.
