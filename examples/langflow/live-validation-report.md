# Langflow Browser Validation

Directory: `/private/tmp/qabot-cli-2026-09-06`  
Branch: `feature/qabot-journeys-cli`

## Target and Scope

Target: `/private/tmp/langflow-qabot-release-d14`, HEAD
`d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`, containing both requested fixes.
No tracked application source was patched to obtain an outcome. A later generated
`uv.lock` change is preserved and recorded as a target-identity limitation. The
prebuilt frontend is shared with the fixed PR14913 target; tracked frontend source
was compared and is identical. This is not general dependency/artifact attestation.

Reviewed startup disables custom components and automatic login, enables lazy
component loading and the Assistant, and disables Langflow and SDK tracing. Login
uses named environment references. Real inference uses IBM WatsonX
`ibm/granite-4-h-small`; the available OpenAI credential could authenticate but had
no inference quota. The browser actor/judge is real Claude CLI/Sonnet with no tools.

Supplied settings are recorded separately from effective application observations.
Supplementary checks observed the restricted/Assistant flags through application
configuration and lazy loading in the server process environment. A generic
effective-configuration attestation mechanism is not implemented.

Setup: `/private/tmp/langflow-qabot-release-d14-runtime/README.md`.
Walkthrough: `/private/tmp/qabot-cli-2026-09-06/examples/WALKTHROUGH.md`.

## PR14931: Valid Browser Failure

Report: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-diagnostic-run1/report.html`.
Video: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-diagnostic-run1/journey-01/page@c075a3b769855a4078ad7e50a8b5278b.webm`.

The customized Agent is deliberately rejected when custom components are disabled.
The expectation is rejection **with the new policy explanation**, not a successful
build. The recorded browser shows only `No model selected`; its required explanation
is missing. The CLI exits 1 with FAIL. Root and independent reviewer inspected the
actual screenshot; the WebM decodes in Chrome at 1440x1000, 104.48 seconds.

The legacy build SSE includes the enriched policy Note in its later vertex result.
Source investigation indicates the canvas AG-UI path emits a terminal error first,
and the frontend unsubscribes before the enriched result. This event-order diagnosis
is source-backed inference, distinct from the directly observed missing browser note.
Relevant source: `/private/tmp/langflow-qabot-release-d14/src/lfx/src/lfx/workflow/agui_translator.py`
and `/private/tmp/langflow-qabot-release-d14/src/frontend/src/controllers/API/agui/run-flow-bridge.ts`.
An API-only success claim would not satisfy this browser acceptance criterion.

## PR14913: Assistant Pass and Repeat

Plan: `/private/tmp/qabot-cli-2026-09-06/examples/langflow/assistant-plan.json`.
First PASS: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1343/report.html`.
Persistent-database repeat PASS: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1348-repeat/report.html`.

Both packaged CLI runs pass all seven steps: log in, create a fresh flow, select
IBM granite in the Assistant, request exactly Chat Input -> Agent -> Chat Output,
apply its result, open Playground, and receive a completed `WATSONX VERIFIED` reply.
The first video is 171.36 seconds; the repeat is 155.32 seconds, both 1440x1000 and
decoded in a real browser. Root inspected both final response screenshots. The
repeat uses dashboard New Flow rather than first-run onboarding and preserves the
first flow. Independent database inspection confirms distinct flows, each with
three nodes, two edges, the intended provider/model, and `Answer briefly.` prompt.

Preserved iterations:

- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1329`:
  BLOCKED because the reviewed plan demanded Add to canvas while the live Assistant
  offered Replace canvas/Dismiss after building the flow.
- `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1335`:
  BLOCKED because generation was still running after repeated read decisions used
  the action budget. A tested bounded wait operation corrected this executor gap.

The final plan accepts the application's actual proposal controls only on a new
disposable flow, checks for duplicates, and waits for observable generation
completion. It does not accept a submitted request or provider error as success.
The Assistant can leave its own validation messages in Playground; the explicit
final user prompt and reply remain distinct. Expected auto-login 403 and a completed
stream reported as aborted remain QUESTION evidence, not hidden as a clean trace.

## PR14913: Editor Route

Plan: `/private/tmp/qabot-cli-2026-09-06/examples/langflow/editor-plan.json`.
Report: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/report.html`.
Iterations: `/private/tmp/qabot-cli-2026-09-06/examples/langflow/editor-validation.md`.

The packaged run completes all 13 steps with independently supported HELD outcomes. Root decoded
the 249.88-second, 1440x1000 video in Chrome, inspected the connected canvas and final
Playground screenshot, and checked the mobile report without horizontal overflow.
Independent source/database inspection confirms three nodes and two correct edges:
ChatInput.message -> Agent.input_value; Agent.response -> ChatOutput.input_value.
The Agent is bound to IBM WatsonX `ibm/granite-4-h-small`. The exact submitted input
is `Reply with exactly: qabot editor flow works`; real inference completes with
`qabot editor flow works` in 3.8 seconds (932 tokens).

Earlier final2 qualification: the actor submitted `qabot editor flow works`, dropping the reviewed
`Reply with exactly:` prefix. The judge's claim that the date response answers the
prompt overstates semantic relevance. Independent adjudication accepts the **core
flow construction and inference proof**, not exact execution of every reviewed
instruction. A literal-input-is-data instruction, a failing-then-passing prompt
regression, and explicit submitted-input observation corrected this example in
final3. Root and independent reviewer verified agreement between actual action,
report, and screenshot. Generic action-fidelity enforcement remains a production
gap; neither the earlier action nor its verdict was rewritten to hide the discrepancy.

Earlier blocked/cancelled attempts remain preserved. Fixes included strict keyboard
targeting, bounded arrow repetition, explicit zoom-menu dismissal, removing optional
minimization, and replacing unsupported geometry/provider-label assertions with
observable checks. No target application source was patched. Target `uv.lock` is
dirty from an investigative launch's dependency resolution and remains preserved;
restoring that file would not attest the installed environment. Port 7865 is stopped.

## Evidence Boundaries

Example approvals are explicitly agent-reviewed, not human-confirmed. Inferred
expectations remain distinct from a human-established oracle. Videos and screenshots
do not have automatic pixel redaction; use disposable test data. No commits, remote
pushes, published reports, or ticket changes were made.
