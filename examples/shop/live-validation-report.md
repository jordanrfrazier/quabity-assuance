# Packaged Journeys CLI: Live Shop Validation

## Scope and Identity

- Worktree: `/private/tmp/qabot-cli-2026-09-06`
- Branch: `feature/qabot-journeys-cli`
- Target repository scope: `/private/tmp/qabot-cli-2026-09-06/demo`
- Reviewed head and actual head: `df7d2d4b558ac61bed677eb715da313591b8c29c`
- Reviewer: `Codex agent-reviewed, not human-confirmed`
- Model: real Claude CLI, final result metadata `claude-cli/sonnet`
- Browser: installed Chrome channel, headless, 1440x1000 recording
- No environment variables or `.env` values were required or supplied.

The target was intentionally scoped to the bundled `demo` subtree. It remains a valid
Git working directory for `rev-parse`, while excluding unrelated qabot application files
from direct repository-document collection.

## Final Reviewed Inputs

- `change-description.md`: change intent supplied to real-model discovery.
- `generated-plan.json`: untouched initial real-model plan; unapproved because it
  describes a nonexistent application.
- `generated-plan-v2.json`: untouched post-fix real-model plan; unapproved because
  startup and browser UI evidence remain unresolved.
- `generated-plan-v3.json`: UI/import discovery works, but the model incorrectly
  expects the documented expired-card defects as successful observations. Unapproved.
- `generated-plan-v4.json`: after an intended-correct-behavior authoring instruction,
  the expired-card expectation correctly requires an expiration-specific message and
  retained cart. Startup remains unresolved in the scoped evidence; this is still an
  unapproved draft, not an automatically runnable plan.
- `reviewed-plan.json`: manually corrected against `demo/app.py`, `demo/ui.py`,
  `demo/e2e/test_shop_flows.py`, and the repository README.
- `reviewed-plan.json.approval.json`: current approval bound to the final reviewed JSON,
  reviewer identity, timestamp, and referenced local script identities.
- `review-notes.md`: the plan audit and every material edit/reapproval reason.

The final plan starts the actual application with:

```text
uv run --offline --no-sync python -m uvicorn demo.app:app --host 127.0.0.1 --port 7880
```

It checks `http://127.0.0.1:7880/health`, opens the user UI at `/ui`, and resets state
between journeys with `POST /reset`.

## Packaged Commands

Initial real-model planning from repository root timed out after 120 seconds and wrote no
file. The scoped planning command then succeeded but produced the invalid preserved v1:

```text
uv run --offline --no-sync python -m qabot.cli journeys plan --repo /private/tmp/qabot-cli-2026-09-06/demo --base HEAD~1 --head HEAD --description /private/tmp/qabot-cli-2026-09-06/examples/shop/change-description.md --out /private/tmp/qabot-cli-2026-09-06/examples/shop/generated-plan.json
```

After manual review, each plan edit was approved with:

```text
uv run --offline --no-sync python -m qabot.cli journeys approve /private/tmp/qabot-cli-2026-09-06/examples/shop/reviewed-plan.json --reviewer "Codex agent-reviewed, not human-confirmed"
```

The complete three-journey run was invoked with:

```text
uv run --offline --no-sync python -m qabot.cli journeys run /private/tmp/qabot-cli-2026-09-06/examples/shop/reviewed-plan.json --out /private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run2 --channel chrome
```

The final selected expired-card run was:

```text
uv run --offline --no-sync python -m qabot.cli journeys run /private/tmp/qabot-cli-2026-09-06/examples/shop/reviewed-plan.json --out /private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5 --channel chrome --journey shop-expired-card
```

Post-fix discovery was measured separately with the first planning command targeting
`generated-plan-v2.json`.

## Results

The fresh complete run `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-final`
returns PASS / PASS / FAIL, exit 1. Unlike earlier Run5, the expired-card journey now
correctly marks both its generic error and lost cart as FAILED. Root inspected the
action trace: `select expired` succeeds once, then `Place order` succeeds once.
The judge's extra remark that the displayed select is now `declined` describes the
reset response form, not the submitted card; it is not additional defect evidence.

Final report: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-final/report.html`.
All three WebMs decoded in installed Chrome at 1440x1000, readyState 4: 29.24,
35.56, and 50.76 seconds. Root checked the mobile report at 390px with no horizontal
overflow. The artifacts below preserve the earlier validation history.

Run 2 provided the successful control paths:

- `shop-add-widget`: PASS. Chrome selected Widget, added it, and verified `1 x widget`
  and `Total: 1000 cents`.
- `shop-valid-checkout`: PASS. Chrome selected the valid card, placed the order, and
  verified `Order confirmed` plus `Order reference: order_1`.
- `shop-expired-card`: BLOCKED after the model repeated an already completed expired
  checkout until the six-action limit. The first attempt had already exposed the defect.

Run 5 is the final known-defect result:

- Overall: FAIL, CLI exit 1.
- Step 1: HELD after opening `/ui` and adding one Widget.
- Step 2: FAILED after one expired-card checkout. The actual alert says only
  `Payment failed`, not that the card expired.
- Step 3: BLOCKED with a direct contradictory observation: `Your cart is empty` and
  `Total: 0 cents`, rather than the retained Widget and 1000-cent total.
- Finding severity: `question`, oracle `null`, preserving agent-inferred authority.
  The expected payment rejection was not mislabeled as an intrinsic BUG.

Run 5 browser evidence:

- HTML: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5/report.html`
- JSON: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5/results.json`
- Video: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5/journey-01/page@b807feb693d5253e5a02c94f47320e13.webm`
- Defect screenshot: `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5/journey-01/settled_02_02.png`
- Report inspection screenshot:
  `/private/tmp/qabot-cli-2026-09-06/qa-artifacts/shop-20260906-run5/report-inspection.png`

The Run 5 WebM is 379,874 bytes. Loading the HTML report in real Chrome produced
`readyState=4`, 1440x1000 video dimensions, and duration 46.72 seconds. The report
heading is `Expired card explains the rejection and preserves the cart FAIL`, and the
rendered report includes the `Payment failed` diagnosis. Port 7880 had no listener after
each run; startup logs show uvicorn shutdown completed.

## Failures Found During Validation

The following package defects were reported to root with their preserved artifacts:

1. Repository-subdirectory discovery did not scope `git diff`, contaminating the prompt
   with an unrelated historical design and generating a fictional shop. Root fixed diff
   scoping; v1 remains the before artifact.
2. The walker repeated a successful, irreversible payment submission while chasing a
   missing expected observation. Root added no-repeat guidance; Run 2 is the before
   artifact.
3. The safe-mode Claude invocation returned bare `done` rather than JSON. Root replaced
   loose parsing with structured output; Run 3 is the before artifact.
4. The first structured schema allowed an intended JSON action inside the `op` string.
   Root added an operation enum and explicit action fields; Run 4 is the before artifact.
5. UI/import evidence omission was corrected after v2. Live v3 now finds the browser
   routes, but encoded known bugs as expected success. Root added an explicit intended
   behavior oracle instruction, with a failing-then-passing prompt regression. Live v4
   correctly expects an expiration explanation and a retained cart. It still needs
   substantive startup review; a scoped subtree does not contain the root README's
   launch instructions, and the model also overstates health/reset uncertainty.
6. Remaining: the lost-cart contradiction is retained in Run 5's overall FAIL reason but
   Step 3 is BLOCKED rather than FAILED and carries no inferred finding. The report is not
   a false pass, but per-step classification understates a plainly observed contradiction.

The reports also record that the target has tracked local changes, so revision identity
alone does not fully identify the development checkout used for this validation.
