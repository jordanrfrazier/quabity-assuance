# Langflow PR14913 editor validation

## Scope

- Target: `/private/tmp/langflow-qabot-release-d14`
- Revision: `d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`
- Browser: headed Google Chrome
- Model: real `claude-cli/sonnet` journey actor and judge
- Approval: `Codex automated review; not human-confirmed`
- Credentials: loaded by name from the designated local env file; no values were read into this document or plan

The reviewed journey validates PR14913's lazy built-in component discovery with custom components disabled. It signs in, creates a fresh flow, adds Chat Input, Agent, and Chat Output from the component sidebar, selects the WatsonX-backed `ibm/granite-4-h-small` model, arranges and connects the nodes, opens Playground, and sends one real message.

## Discovery review

The supplied discovery artifact `qa-artifacts/langflow-20260906/discovered-plan-v3.json` identified the relevant editor and Assistant routes but was not executable as-is. It assumed OpenAI configuration and allowed provider/quota errors to satisfy success. The final reviewed plan instead uses the available IBM WatsonX configuration and requires a real assistant response with no provider, quota, model, build, or restricted-component error.

Live review also corrected these assumptions:

- Login actions must carry `${LANGFLOW_SUPERUSER}` and `${LANGFLOW_SUPERUSER_PASSWORD}` references so the driver can substitute and redact them.
- A new flow opens a welcome surface; its `Components` rail button is the accessible route to the blank component canvas.
- Sidebar rows and plus buttons share accessible names. Keyboard activation selects the unique focusable row.
- Newly added nodes overlap. Selecting named node applications and repeating `Shift+ArrowLeft` or `Shift+ArrowRight` separates them without pointer dragging.
- `Zoom To Fit` leaves its Radix menu open and aria-hides the canvas until Escape closes it.
- Connections are verifiable through the accessible buttons `Edge from Chat Input to Agent` and `Edge from Agent to Chat Output`.
- The Agent UI exposes the selected IBM model, not a separate literal `IBM WatsonX` provider label.

## Iteration evidence

- `run1`: blocked before startup because the wrong nonsecret metadata env file did not contain required credentials.
- `run2`: blocked after generic login wording caused guessed credentials; fixed with explicit environment references.
- `run3`: blocked on a nonexistent welcome-close action; corrected to the observed `Components` rail button.
- `run4`: exposed duplicate accessible sidebar controls and the missing focusable-row disambiguation.
- `run5`: proved keyboard component insertion, then exposed an invalid invented container scope.
- `run6`: added all nodes and selected the IBM model, then exposed off-screen/overlapped connection handles.
- `run7` and `run8`: proved fit-view leaves the menu open and aria-hides handle controls.
- Manual inspection on the run-created flow proved Escape restores all four exact handle roles and Enter creates both edges (`0 -> 1 -> 2`).
- Manual inspection also proved twenty `Shift+Arrow` events move a selected named node exactly 400 pixels.
- `run9`: rejected an unobservable separate-provider label.
- `run10`: executed movement but rejected an unobservable numeric geometry oracle.
- `run11` and `run12`: intentionally cancelled while the final text/ARIA-only plan review was applied.
- `final`: optional minimization succeeded, but the actor reopened its menu until the action budget expired; minimization was removed because node movement made it unnecessary.
- `final2`: qualified PASS for build/inference; the actor dropped the `Reply with exactly:` prefix from the submitted data.
- `final3`: PASS, all 13 expected observations held with the entire quoted input submitted exactly.

All failed and cancelled run directories remain under `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-*`.

## Final evidence

- Report: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/report.html`
- Results: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/results.json`
- Video: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/journey-01/page@c2b649b551e9598d0f0753575cb7c914.webm`
- Separated canvas: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/journey-01/settled_09_03.png`
- Connected canvas: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/journey-01/settled_11_02.png`
- Playground response: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/langflow-editor-20260906-final3/journey-01/settled_13_02.png`

The submitted message was exactly `Reply with exactly: qabot editor flow works`. The real Agent response completed in 3.8 seconds and displayed exactly: `qabot editor flow works`.

The persisted fresh flow independently confirms the browser evidence:

- Flow `5fe84681c1284031865b9ab1cec90ed0` (`New Flow (11)`) contains exactly three nodes and two edges.
- Agent model metadata records provider `IBM WatsonX` and name `ibm/granite-4-h-small`.
- Positions record Chat Input at x=-12, Agent at x=398, and Chat Output at x=808.
- The first edge binds Chat Input output `message` to Agent input `input_value`.
- The second edge binds Agent output `response` to Chat Output input `input_value`.

## Limitation

The final results correctly record target worktree status ` M uv.lock`. A manual direct Langflow inspection invoked dependency resolution and rewrote the lockfile. Per release-owner direction, that generated diff is preserved and disclosed rather than restored; the tested Git revision remained `d14dec904fc55c5e79cfeb8dec2bdf449e638f9d`.

## Exact final commands

```sh
uv run --offline --no-sync python -m qabot.cli journeys approve examples/langflow/editor-plan.json --reviewer "Codex automated review; not human-confirmed"
uv run --offline --no-sync python -m qabot.cli journeys run examples/langflow/editor-plan.json --out qa-artifacts/langflow-editor-20260906-final3 --headed --channel chrome --env-file /Users/jordan.frazier/Documents/langflow/langflow/.env
```
