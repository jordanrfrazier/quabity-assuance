# PR14877 Validation Current State

## Request And Authorization - 2026-09-08

- User requested running qabot on open Langflow PR14877, using the existing
  fix/assistant-flow-policy-compliance branch after the report ZIP task finishes.
- User explicitly confirmed "Yes, run PR14877 including model-provider calls".
  Live discovery, browser actor/judge, and Watsonx application inference are now
  authorized for this validation. Qabot model-backed discovery completed;
  application/browser execution has now started for both reviewed plans.
- No commits, pushes, PR comments, or changes to Langflow code are authorized.

## Verified Source

- Requested checkout: `/Users/jordan.frazier/Documents/Langflow/langflow`, branch
  `fix/assistant-flow-policy-compliance`.
- Local HEAD and origin branch match current GitHub PR head:
  `b8f96d5ecd2c8a12222587197a7fa098f7519707`.
- PR is OPEN and targets `release-1.12.1`; current GitHub base is
  `bd716bd9ea1b10b286a88d85cd341c5db60c124f`, available locally. The local
  origin/release-1.12.1 tracking ref is older; do not silently substitute it.
- No tracked changes in the requested checkout. Many pre-existing untracked
  files exist and must be preserved. Test worktrees/runtime/evidence should stay
  under `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/`.

## Test Scope To Prepare

- The shipped Assistant must remain usable with
  LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false,
  LANGFLOW_RESTRICT_LOCAL_FILE_ACCESS=true, and
  LANGFLOW_BLOCK_CODE_INTERPRETER_COMPONENTS=true (the hardened source-test setup).
- Browser coverage should include authenticated Assistant conversation, component
  library search, creation of an ordinary built-in flow, and real flow execution.
- A request to generate a custom component should receive a user-facing policy
  refusal without repeated generation attempts or a model-blaming failure card.
  The new source tests explicitly require this refusal NOT to expose operator
  setting names. Do not reuse PR14931's diagnostic-message oracle for this PR.
- Read the actual current diff and shipped-flow tests; earlier automated PR
  comments describe superseded approaches and are not current requirements.
- ZIP feature is complete and verified independently in feature/report-bundle.
- Important pair decision: current release tip bd716bd has unrelated frontend
  changes that this PR head has not absorbed. Use merge-base
  fa4bd2ab73627f4b0163d2fc32b0e35d86ca5129 as before control and head b8f96d5 as
  after. Their frontend source is identical to the prepared retained build's
  source revision 84a3649. This tests the PR delta, not merged-tip compatibility.
- New isolated target worktrees: primary project's
  `.worktrees/langflow-pr14877-before` and `.worktrees/langflow-pr14877-after`.
  Runtime ports 7881/7882; fresh separate config/SQLite directories under
  `v1/reports/verification/pr14877-20260908/harness/runtimes`.
- GPT-5.5 is preparing the scoped harness/config checks; root will run actual
  qabot discovery, review the generated plan, approve as agent review, and execute.
  CLI: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/qabot-state-prerequisites`,
  branch fix/state-prerequisites (enforces unverified state blocking).
- Evidence root:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-20260908`.

## Discovery And Review

- Qabot successfully generated `discovered-plan.json` in the evidence root from
  the actual source pair and retained `change-description.md`.
- Original discovery is preserved. It identified three relevant journeys but
  flagged inferred startup, UI/model controls, exact policy wording, and library
  behavior as unresolved. Source/test review and the previously proven UI
  harness are supplying explicit reviewed corrections; this is not evidence of
  unattended provisioning.
- Runtime imports for the after target resolve to the new PR worktree,
  including the registered ComponentLibrarySearch. Frontend copied into this
  evidence root passes its retained SHA-256 manifest.
- Review requires six policy/setup flags in each journey, mandatory API checks
  for known exposed configuration fields, and explicit reporting of flags the
  API does not expose. Fresh context/flow state becomes actual browser actions,
  not unchecked prose prerequisites.
- A correct component answer is browser evidence of user-visible behavior, not
  independent proof that a particular internal search tool was invoked.

## Live Pair Started

- Harness and product schema validation pass. Normalized before/after journey
  SHA-256: `ab6c766b4fac4a8d32b9328848633c75e7e4c5c121cfef885db139c2704d3c5d`.
- Root reviewed and approved both final plans as
  `Codex agent review - PR14877 validation`, not as user review.
- Actual qabot runs started with `--headed --channel chrome` and selective
  `--env-file` credential loading. Outputs are retained in the evidence root at
  `runs/pr14877-before-01` and `runs/pr14877-after-01`.
- No source fixes or acceptance-criteria relaxation have been made. Final
  outcomes and media verification are still pending.

## Initial Setup Block And Harness Correction

- Both `*-01` runs finished BLOCKED before any browser journey, because root
  incorrectly required `config.auto_login` in `/api/v1/config`. Neither target
  exposes this field there. This is a harness defect, not a PR failure.
- Correct source contract: unauthenticated `GET /api/v1/auto_login` returns 403
  with JSON `detail.auto_login=false` when disabled. That route is identical
  across the source pair. Require this response separately; retain mandatory
  config checks for the two fields that actually exist.
- GPT-5.5 is preparing a new retry checker and new paired plan files. Original
  checker, approved plans, and blocked reports remain unchanged. No acceptance
  text or target source changes are permitted in this correction.
- Correction completed: focused checker tests 5 passed; root retry validation
  passes, preserving the same normalized journey hash. Root reviewed/approved
  both retry plans and started outputs `runs/pr14877-before-02` and
  `runs/pr14877-after-02`. Existing isolated databases contain only setup/auth
  metadata from the first attempts; browser flow creation was never reached.

## Browser Evidence In Progress

- Both corrected runs pass setup. API confirms allow_custom_components=false,
  agentic_experience=true, and disabled auto-login via the dedicated endpoint.
  The other three supplied flags are explicitly reported as not exposed.
- Before greeting FAIL is a real rendered app error: custom components are not
  allowed for Keyword Search (DataFrameKeywordSearch-b8MUN).
- After greeting BLOCKED is a qabot actor error: it invented a nonexistent
  `Close welcome overlay` button. The visible welcome prompt is valid input;
  this does not establish a Langflow accessibility defect. Preserve the result
  and retry both targets with only an explicit control instruction correction.
- Both before and after build journeys PASS. Root inspected screenshots showing
  completed real Playground responses `PR14877 VERIFIED`, following the actual
  user request. This is non-regression coverage, not a newly fixed path.
- Policy-refusal journey and focused greeting rerun are still pending.

## Completed Result

- Full suite `before-02`: greeting FAIL, flow build/execution PASS, policy refusal
  FAIL (Generation failed, Attempt 4 of 4).
- Full suite `after-02`: greeting BLOCKED by invented actor control, flow
  build/execution PASS, policy refusal PASS with the exact intended message.
- Root reviewed/approved paired greeting-controls plans. Only the greeting
  action instruction changed; all expected observations and settings stayed
  fixed. Focused `before-03` reproduces the same Keyword Search error.
- Focused `after-03`: greeting succeeds, but component answer FAILs by naming
  Message Input instead of the registered Chat Input/ChatInput. Both answers
  visibly repeat their text. No causal attribution to this PR or claim of
  deterministic reproduction across models is made.
- This is a mixed result, not an all-pass sign-off. Do not rerun until green or
  weaken the component-name assertion to hide the recorded failure.
- All eight videos decode and play in Chrome; all 37 displayed screenshots
  load. Four local ZIPs match original bytes and exclude runtime data/logs.
  Literal API-key/password scans of archived text have zero matches. Pixel
  sanitization is not guaranteed; review before external sharing.
- Root independently reran focused checker tests: 5 passed in 0.06s. Source
  target worktrees are clean; user's Langflow checkout has no tracked changes.
  Servers stopped, ports 7881/7882 free, all exec sessions completed. No commits,
  pushes, PR comments, uploads, or Langflow source fixes were made.
- Final assessment with reports, video chapters, ZIPs, exact configuration,
  source revisions, correction history, limitations, and next manual check:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-20260908/verification.md`.
