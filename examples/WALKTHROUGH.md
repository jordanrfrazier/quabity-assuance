# Local CLI Walkthrough

Directory: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli`

Branch: `feature/qabot-journeys-cli`

All examples run locally. Model inference requires network access. No commit,
push, hosting, or external publication is part of this workflow.

Historical example plans and approvals retain their original paths and source
identities. Relocation and stronger revision binding require a fresh review:
check the target repository, commands, environment, state requirements, and
resolved commits before approving again. Do not bypass a stale-approval error or
rewrite historical report bundles. Section 6 creates a fresh plan and approval
and is the recommended first-use evaluation. The old shop plan's repository path
must be corrected before reuse because the CLI worktree moved.

## First-Use Validation

Start with section 6, not an already-reviewed example. This tests discovery and
your review experience, rather than just replaying a prepared plan. The current
Langflow checkout and runtime are pre-provisioned, so this is not yet a clean-machine
installation or generic provisioning test.

Prerequisites for the commands below: installed Chrome, `uv`, `lsof` on `PATH`, and an authenticated
`claude` CLI. In the implementation directory, run
`uv sync --extra dev --extra browser`, then `uv run qabot journeys --help`.
Journey authoring and execution use Claude/Sonnet; GPT-5.5's validation role does
not change the product's model provider. Langflow model-building journeys also
need working provider credentials and quota.

1. Generate a new draft using section 6. Note elapsed time and any unclear command,
   missing prerequisite, or failure. Do not copy a prepared plan over the draft.
2. Review the draft's startup command, required credential names, configuration,
   fixture/reset behavior, and unresolved questions. Check the configuration
   against the runtime README, including custom-component restrictions and lazy
   loading. Record absent or unverified settings as gaps, not as disabled settings.
3. Check journey coverage: login, component-list access, editor construction and
   completed execution, and the Assistant path to constructing and executing a
   flow. Provider errors or merely submitting a build are not successful execution.
4. Make necessary corrections in the draft and record each correction before
   approving. Stop if a startup command or required state is unclear or unsafe.
5. Approve and run using section 6. Open the report path printed by the CLI. Inspect
   the actual inputs, resulting component connections, completed response, step
   screenshots, video chapters, timing breakdown, and configuration limitations.
   Judge the evidence independently of the reported PASS/FAIL labels.
6. Rerun the unchanged plan without approving it again. It should get a different
   retained report directory. Check fixture behavior and whether the same expected
   outcomes hold; record any intervention required.

Keep your notes beside the draft in
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/manual-first-use-01/`.
Useful notes: generation time, number of substantive plan corrections, unclear
steps, manual setup interventions, verdicts you disagree with, and whether the
video gives enough evidence to decide. This is an evaluation, not a requirement
to repair qabot source yourself.

## 1. Inspect a Recorded Run

The fresh September 7 timing validation is
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/20260907T160319Z-diagnostic-plan-dcd7ab11/report.html`.
Its four steps correctly end in FAIL for the same missing browser diagnostic.
The 87.32-second video has approximate step chapters. Measured steps total 81.41s,
including 44.52s actor time, 24.61s judge time, 8.65s waits, 1.22s browser actions,
and 2.40s evidence/overhead. These timings exclude application provisioning and
final teardown and do not establish a repeatable speedup from a single run.

Open `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/langflow-diagnostic-run1/report.html`.
Play its video and expand the steps. The fixed revision really fails the browser
expectation: the canvas shows only a missing-model error, without the new policy
diagnostic. The legacy build API contains that note; it is not equivalent to the
browser evidence requested here. The video was decoded in Chrome at 1440x1000,
104.48 seconds. Desktop and 390px mobile report layouts were checked.

Open `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/shop-20260906-final/report.html`
for a smaller complete example: add-to-cart and valid checkout PASS; the expired
card FAILS because its message is generic and its cart is emptied. All three videos
were decoded in Chrome. Earlier invalid attempts remain separately documented in
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/shop/live-validation-report.md`.

The successful Assistant browser run is
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/langflow-assistant-20260906-1343/report.html`.
It creates Chat Input -> Agent -> Chat Output using IBM WatsonX, applies the flow,
and receives a completed real `WATSONX VERIFIED` reply in Playground. All seven
steps PASS. Its 171.36-second video was decoded in Chrome and the final screenshot
independently inspected.

The same-database repeat also passes:
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/langflow-assistant-20260906-1348-repeat/report.html`.
It uses the dashboard's New Flow button and leaves the earlier flow intact. The
repeat video is 155.32 seconds; the final response is independently visible in its
last screenshot. The target's `uv.lock` changed during validation and was preserved;
the report records tracked changes. No target application source differs from d14.

## 2. Run the Small Shop Example

The CLI starts its own shop instance on port 7880. A previously prepared manual
instance used port 7888; its historical availability is not a prerequisite.

```sh
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv sync --extra dev --extra browser
uv run qabot journeys run /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/shop/reviewed-plan.json \
  --headed --channel chrome
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
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv run qabot journeys run /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/langflow/diagnostic-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome
```

Port 7862 must be free. The runner refuses to reuse an already-running application
because it cannot identify that process as the approved startup. It uses the
isolated existing database, a fresh browser context, and explicit restricted/lazy
flags. Persistent application state is not reset for this example; the exact
fixture identity and inspection expectation are in the plan.

## 4. Run the Assistant Example

```sh
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv run qabot journeys run /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/langflow/assistant-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome
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
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv run qabot journeys run /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/langflow/editor-plan.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome
```

Port 7865 must be free. This creates a separate new flow, adds the three components
from the sidebar, selects the real Watsonx model, moves the nodes through ordinary
keyboard controls, connects both edges, and submits a Playground message. The
movement and zoom steps are setup; inspect the recorded fitted canvas yourself for
spatial readability. Functional checks require both named edges and a real response.
No prebuilt flow is injected to bypass browser construction.

Recorded build/inference proof:
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/langflow-editor-20260906-final3/report.html`.
All 13 steps PASS. The 249.88-second video decodes in Chrome. Independent inspection
confirms three nodes, both correct edges, the IBM model binding, exact submitted
message `Reply with exactly: qabot editor flow works`, and completed real response
`qabot editor flow works` (932 tokens, 3.8 seconds). An earlier input-fidelity failure
was corrected and rerun; its unchanged evidence remains documented in
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/langflow/editor-validation.md`.

## 6. Generate and Review a New Plan

```sh
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli
uv run qabot journeys plan --repo /private/tmp/langflow-qabot-release-d14 \
  --base d7bd4b55a856216d1074d18e29fad38563158d10 \
  --head d14dec904fc55c5e79cfeb8dec2bdf449e638f9d \
  --description /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-journeys-cli/examples/langflow/change-description.md \
  --out /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/manual-first-use-01/draft.json
```

Open and edit the JSON in your normal editor. Resolve `unresolved` entries using
the actual local prerequisites. Check that startup environment matches every
selected journey's required settings. The recorded v3 discovery identifies both
the editor and Assistant routes, but needed correction: flags were missing from
startup, and provider errors were incorrectly offered as an acceptable alternative
to a successful model run. Those are review findings, not supported success claims.

```sh
uv run qabot journeys approve /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/manual-first-use-01/draft.json --reviewer "Jordan"
uv run qabot journeys run /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/manual-first-use-01/draft.json \
  --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env \
  --headed --channel chrome
```

Approval is the adjacent `.approval.json` file. Editing reviewed content or a
referenced script invalidates it; formatting-only changes do not. Approval also
binds the canonical target repository and resolved base/head commits. Moving a
branch or `HEAD`, retargeting the repository, or reusing an older approval without
Git bindings requires renewed review. Current pilot
approval is whole-plan, so editing one journey invalidates that plan even when
running a different selected journey. Independent per-journey approval remains a
PRD requirement, not a completed pilot capability.

Run commands above intentionally omit `--out`: from this linked worktree, new
reports are stored in unique directories under the primary checkout at
`/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/`.
Keep the CLI's printed report path. If `manual-first-use-01/draft.json` already
exists, choose a new numbered directory for discovery; do not overwrite evidence.

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
- The target port must be unused before setup and startup, including by unhealthy
  services. The app must stay in the foreground and its listeners must remain in
  the reviewed process group. Missing `lsof` or unverifiable ownership blocks;
  qabot rechecks before each journey and does not stop an unrelated app to make
  room for the run.
- Setup and reset stdout/stderr are retained in redacted `setup-01.log` and
  `journey-01-reset.log` files, numbered by execution order. Their paths appear in
  report configuration and failure diagnostics, including timeouts.
- Required setting strings are compared exactly, including case and whitespace.
- Browser actions use accessible names and named scopes. Unreachable or ambiguous
  controls block rather than selecting arbitrary matches. Failed actions retain
  evidence and block before another model decision; there is no automatic retry.
- Browser navigation stays on the reviewed local origin. Cross-origin SSO is not
  supported in this pilot. External model requests and assets still use network.
- Video is required; missing recordings block. Evidence stays locally until you
  remove its directory; there is no retention automation or hosted dashboard.
- Login credential references are resolved in the browser driver; credential-named
  values require masked inputs. Text evidence is redacted, but arbitrary reflected
  secrets in screenshot/video pixels are not. Use disposable test data, not
  sensitive production data. Ctrl-C retains partial evidence and exits 130.
- Recognized credential-named startup environment entries and URLs with embedded
  credentials must use a complete `${NAME}` reference. Invalid literal values are
  rejected before report creation, without rewriting the approved plan. This is
  not a general secret scanner; do not put credentials in commands, descriptions,
  or other literal plan fields. Plain SQLite and credential-file paths are allowed.
- The prebuilt Langflow frontend is shared with the original fixed target and was
  checked against identical tracked frontend source. General dependency/artifact
  attestation and per-journey database reset are not implemented.
