# Local CLI Walkthrough

Directory: `/private/tmp/qabot-cli-2026-09-06`  
Branch: `feature/qabot-journeys-cli`

All examples run locally. Model inference requires network access. No commit,
push, hosting, or external publication is part of this workflow.

## 1. Inspect a Recorded Run

Open `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-diagnostic-run1/report.html`.
Play its video and expand the steps. The fixed revision really fails the browser
expectation: the canvas shows only a missing-model error, without the new policy
diagnostic. The legacy build API contains that note; it is not equivalent to the
browser evidence requested here. The video was decoded in Chrome at 1440x1000,
104.48 seconds. Desktop and 390px mobile report layouts were checked.

Open `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-final/report.html`
for a smaller complete example: add-to-cart and valid checkout PASS; the expired
card FAILS because its message is generic and its cart is emptied. All three videos
were decoded in Chrome. Earlier invalid attempts remain separately documented in
`/private/tmp/qabot-cli-2026-09-06/examples/shop/live-validation-report.md`.

The successful Assistant browser run is
`/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1343/report.html`.
It creates Chat Input -> Agent -> Chat Output using IBM WatsonX, applies the flow,
and receives a completed real `WATSONX VERIFIED` reply in Playground. All seven
steps PASS. Its 171.36-second video was decoded in Chrome and the final screenshot
independently inspected.

The same-database repeat also passes:
`/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-assistant-20260906-1348-repeat/report.html`.
It uses the dashboard's New Flow button and leaves the earlier flow intact. The
repeat video is 155.32 seconds; the final response is independently visible in its
last screenshot. The target's `uv.lock` changed during validation and was preserved;
the report records tracked changes. No target application source differs from d14.

## 2. Run the Small Shop Example

For direct manual interaction, a separate prepared shop instance is running at
`http://127.0.0.1:7888/ui` (this session's PID 65419). It is independent of the CLI
test instance on port 7880. Its log is
`/private/tmp/qabot-cli-2026-09-06/qa-artifacts/manual-shop-server.log`.

```sh
cd /private/tmp/qabot-cli-2026-09-06
uv sync --extra dev --extra browser
uv run qabot journeys run /private/tmp/qabot-cli-2026-09-06/examples/shop/reviewed-plan.json \
  --headed --channel chrome --out /private/tmp/qabot-shop-manual-01
```

The plan is already labeled as agent-reviewed, not human-confirmed. Read it first;
to replace that review with your own, run `journeys approve` with your real name.
The server starts on port 7880 and is stopped after the run. A failure exit is
expected for this intentionally defective application. Use a new output directory
for every rerun. Model decisions are not deterministic: earlier iterations marked
a later contradiction BLOCKED, while the final run correctly marks both defective
observations FAILED. Inspect the action trace alongside the verdict.

## 3. Run the Langflow Diagnostic

The exact fixed checkout is `/private/tmp/langflow-qabot-release-d14`, detached at
`d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`. It includes both requested fixes.
Setup details and idempotent fixture seeding are documented in
`/private/tmp/langflow-qabot-release-d14-runtime/README.md`.

```sh
cd /private/tmp/qabot-cli-2026-09-06
uv run qabot journeys run /private/tmp/qabot-cli-2026-09-06/examples/langflow/diagnostic-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome --out /private/tmp/qabot-langflow-diagnostic-manual-01
```

Port 7862 must be free. The runner refuses to reuse an already-running application
because it cannot identify that process as the approved startup. It uses the
isolated existing database, a fresh browser context, and explicit restricted/lazy
flags. Persistent application state is not reset for this example; the exact
fixture identity and inspection expectation are in the plan.

## 4. Run the Assistant Example

```sh
cd /private/tmp/qabot-cli-2026-09-06
uv run qabot journeys run /private/tmp/qabot-cli-2026-09-06/examples/langflow/assistant-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome --out /private/tmp/qabot-langflow-assistant-manual-01
```

Port 7864 must be free. This starts and stops its own application instance using
the isolated existing database. Each run creates a new flow through the UI; it
does not reset or overwrite your prior proof flows. The plan supports both the
first-run workspace and an existing projects dashboard. Real Watsonx inference
requires network and available provider quota. Expect a few minutes, including
model-controlled browser steps.

`--env-file` above is qabot's selective credential input. Do not pass the main
environment file directly to Langflow's own `--env-file`, which could override the
restricted flags. The Assistant may leave its own validation messages in Playground;
the final explicit `WATSONX VERIFIED` user prompt and completed reply are the proof.
Reports retain expected auto-login 403 and completed-stream abort QUESTION evidence;
PASS does not mean there were zero network errors.

## 5. Run the Editor Example

```sh
cd /private/tmp/qabot-cli-2026-09-06
uv run qabot journeys run /private/tmp/qabot-cli-2026-09-06/examples/langflow/editor-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome --out /private/tmp/qabot-langflow-editor-manual-01
```

Port 7865 must be free. This creates a separate new flow, adds the three components
from the sidebar, selects the real Watsonx model, moves the nodes through ordinary
keyboard controls, connects both edges, and submits a Playground message. The
movement and zoom steps are setup; inspect the recorded fitted canvas yourself for
spatial readability. Functional checks require both named edges and a real response.
No prebuilt flow is injected to bypass browser construction.

Recorded build/inference proof:
`/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/report.html`.
All 13 steps PASS. The 249.88-second video decodes in Chrome. Independent inspection
confirms three nodes, both correct edges, the IBM model binding, exact submitted
message `Reply with exactly: qabot editor flow works`, and completed real response
`qabot editor flow works` (932 tokens, 3.8 seconds). An earlier input-fidelity failure
was corrected and rerun; its unchanged evidence remains documented in
`/private/tmp/qabot-cli-2026-09-06/examples/langflow/editor-validation.md`.

## 6. Generate and Review a New Plan

```sh
cd /private/tmp/qabot-cli-2026-09-06
uv run qabot journeys plan --repo /private/tmp/langflow-qabot-release-d14 \
  --base d7bd4b55a856216d1074d18e29fad38563158d10 \
  --head d14dec904fc55c5e79cfeb8dec2bdf449e638f9d \
  --description /private/tmp/qabot-cli-2026-09-06/examples/langflow/change-description.md \
  --out /private/tmp/qabot-langflow-draft-01.json
```

Open and edit the JSON in your normal editor. Resolve `unresolved` entries using
the actual local prerequisites. Check that startup environment matches every
selected journey's required settings. The recorded v3 discovery identifies both
the editor and Assistant routes, but needed correction: flags were missing from
startup, and provider errors were incorrectly offered as an acceptable alternative
to a successful model run. Those are review findings, not supported success claims.

```sh
uv run qabot journeys approve /private/tmp/qabot-langflow-draft-01.json --reviewer "Jordan"
uv run qabot journeys run /private/tmp/qabot-langflow-draft-01.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome --out /private/tmp/qabot-langflow-reviewed-01
```

Approval is the adjacent `.approval.json` file. Editing reviewed content or a
referenced script invalidates it; formatting-only changes do not. Current pilot
approval is whole-plan, so editing one journey invalidates that plan even when
running a different selected journey. Independent per-journey approval remains a
PRD requirement, not a completed pilot capability.

## 7. Interact with Langflow Yourself

When qabot is not running the diagnostic/editor examples, start the prepared target
directly in a terminal:

```sh
cd /private/tmp/langflow-qabot-release-d14
uv run --no-sync python /private/tmp/langflow-qabot-release-d14-runtime/start_d14.py --port 7862
```

Open `http://127.0.0.1:7862`, sign in with the credentials from your existing local
environment file, and inspect or create a flow. Select IBM WatsonX model
`ibm/granite-4-h-small`; the available OpenAI credential has exhausted inference
quota. Stop this server with Ctrl-C before
running the diagnostic CLI example; qabot intentionally refuses an occupied target
endpoint. This standalone helper is a prepared Langflow fixture, not the generic
qabot discovery implementation.

## Known Boundaries

- Model-generated navigation and judging can be incomplete; no PASS is a substitute
  for inspecting its actual video and expected observation.
- Literal-input guidance and an explicit observation corrected the editor example's
  shortened input. This is not generic action-fidelity enforcement; continue to
  inspect requested versus actual actions.
- The actor/judge receives page text and accessibility outlines, not screenshot
  pixels. Spatial visibility, overlap, and visual styling require human video review.
- Plans record supplied flags separately from observed readiness. They do not
  universally attest the application's effective configuration, role, or database
  state. The Langflow runtime/API observations are documented in its setup notes.
- Startup runs reviewed local shell commands with the operator's privileges and
  inherited environment. This is not a sandbox for untrusted repositories.
- Browser actions use accessible names and named scopes. Unreachable or ambiguous
  controls block rather than selecting arbitrary matches.
- Browser navigation stays on the reviewed local origin. Cross-origin SSO is not
  supported in this pilot. External model requests and assets still use network.
- Video is required; missing recordings block. Evidence stays locally until you
  remove its directory; there is no retention automation or hosted dashboard.
- Credential references are resolved only in the browser driver; credential-named
  values require masked inputs. Text evidence is redacted, but arbitrary reflected
  secrets in screenshot/video pixels are not. Use disposable test data, not
  sensitive production data. Ctrl-C retains partial evidence and exits 130.
- The prebuilt Langflow frontend is shared with the original fixed target and was
  checked against identical tracked frontend source. General dependency/artifact
  attestation and per-journey database reset are not implemented.
