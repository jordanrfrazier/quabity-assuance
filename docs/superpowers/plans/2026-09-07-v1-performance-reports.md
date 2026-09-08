# V1 Performance and Durable Reports

> Execute with test-driven development and independent review. No commits or remote writes are authorized for this task.

**Goal:** Measure execution latency, remove unnecessary readiness waits without losing failure evidence, retain reports in the user's durable project directory, and separate deferred workflow-learning design from v1.

**Spec:** Jordan's September 7 approval of v1 timing/readiness improvements and request for `v2/` follow-up details and durable `v1/reports/` artifacts.

**Architecture:** Extend the existing journey result models with optional timing data; old reports remain readable with unknown timing, not zero measurements. Keep browser decisions and judgment semantics unchanged. Resolve default run output beneath the invoking Git workspace's primary root, so the linked implementation worktree does not default to temporary storage. Reports use bundle-relative media references for portability.

**Workspace:** `/private/tmp/qabot-cli-2026-09-06`, branch `feature/qabot-journeys-cli`.
**Retained reports:** `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/`.

## Constraints

- No workflow cache, recipe replay, auth-state reuse, secondary learning agent, or model-provider change in v1.
- Do not weaken assertions, retry submissions, drop delayed runtime errors, or fabricate timings for historical reports.
- Preserve existing artifact bytes and source identities; migration copies are verified before links change. No deletion of old evidence.
- Keep reports local and ignored by Git. Do not copy credentials or runtime databases into report bundles.
- Run Python/pytest through `uv run`; manual edits use `apply_patch`.

## Task 1: Timing and Readiness

Files: `qabot/journeys/models.py`, `qabot/journeys/walker.py`, `tests/test_journey_walker.py`.

- [x] Add failing tests proving timing survives successful, failed and cancelled steps, form fills do not wait for network idle, and delayed browser failures remain failures.
- [x] Add optional `StepResult.timing` with numeric seconds: `actor_s`, `judge_s`, `action_s`, `wait_s`, `evidence_s`, `total_s`; integer `actor_calls`, `judge_calls`. Values are nonnegative and measured with a monotonic clock; do not claim they are provider-internal reasoning time.
- [x] Add optional `StepResult.started_offset_s` measured from journey execution start, explicitly approximate for video chapters. Preserve defaults of None for old/unexecuted results.
- [x] Remove generic network-idle dependence. Use existing locator actionability and explicit wait actions; skip full settling for local form edits/read operations. Retain bounded DOM readiness for navigation and bounded event observation before final judgment. Pending loading and delayed 300ms crash cases must stay covered.
- [x] Preserve partial timing in failures/cancellation; no new global mutable state or changes to the reviewed-plan schema.
- [x] Run covering pure/browser tests with retained output under the durable reports directory and review the changes independently.

## Task 2: Reports and Storage

Files: `qabot/journeys/report.py`, `qabot/journeys/cli.py`, `qabot/journeys/runner.py` only if needed, a small output-path helper, focused CLI/report tests, `.gitignore`, `README.md`, `examples/WALKTHROUGH.md`.

- [x] Add failing tests for portable report media, unknown legacy timing, HTML/Markdown timing summaries, and optional default `run --out` behavior.
- [x] Make `run --out` optional; choose a unique new directory under primary Git workspace `v1/reports/`, falling back to invocation directory outside Git. Keep explicit `--out` behavior and refusal to overwrite existing runs.
- [x] Display measured per-step timing and model call counts, including totals. Add approximate chapter links only for measured offsets, no synthetic offsets for historical videos.
- [x] Write bundle-relative screenshot/video references to new serialized reports without modifying execution's in-memory paths; ensure links work after copying a bundle.
- [x] Copy the full existing `qa-artifacts/` evidence archive to the durable reports root, verifying all original file hashes. Preserve historical originals and create a durable report index identifying authoritative and superseded runs. Update walkthrough report/output paths, never target fixture paths or approval contents unnecessarily.
- [x] Validate desktop/mobile report rendering, video decoding and chapter navigation in Chrome. Run one real Langflow diagnostic with the current CLI to retain measured evidence and preserve its real verdict.

## Task 3: V2 Follow-Up and Scope

Files: `v2/README.md`, `v2/workflow-learning.md`, `docs/PRD.md` (root owns current-state updates).

- [x] Move workflow-learning proposal details into `v2/`: candidate extraction from verified setup steps, reviewed promotion, bounded replay, secret references, role/profile compatibility, fresh guards/evidence, visible divergence, and no cached verdicts.
- [x] Distinguish procedure replay from auth-state reuse and background pattern mining. Keep these unimplemented and deferred. Do not relabel existing v1 release gaps as v2 solely to declare completion.
- [x] Keep concise v2 links in the PRD, add v1 timing/readiness/durable-evidence acceptance criteria, and retain historical pilot evidence and limitations.
- [x] Update project state with accepted scope, validation, storage path and next steps.

## Completion

- [x] Focused tests pass after observed RED failures; independent final review has no unresolved correctness findings.
- [x] Reports and evidence are readable at the durable path, originals preserved, no sensitive artifacts staged.
- [x] Report exact verification and live run outcome without promising a latency improvement unsupported by comparable measurements.
