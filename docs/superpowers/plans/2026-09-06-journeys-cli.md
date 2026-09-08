# Journeys CLI Implementation Plan

> Execution: subagent-driven-development for bounded tasks, with independent prerequisite investigation and browser validation in parallel. No commits or remote writes.

Goal: deliver a local CLI walkthrough that discovers a reviewed application startup plan, authors and approves journeys, executes them in Chrome with video and configuration evidence, and distinguishes correct outcomes for Langflow PRs 14931 and 14913, including the Assistant path.

Architecture: promote the existing journey spike into `qabot/journeys` using its Pydantic and Playwright patterns. Add a persisted plan and approval boundary, improve authoring with repository/documentation context, and repair browser execution based on real fixed/broken evidence. Keep scan and legacy merge-gate behavior unchanged.

Spec: `/private/tmp/qabot-cli-2026-09-06/docs/PRD.md`, supplemented by Jordan's 2026-09-06 build instruction naming both PRs and requiring videos and a manual walkthrough.

## Constraints

- Worktree: `/private/tmp/qabot-cli-2026-09-06`, branch `feature/qabot-journeys-cli`.
- No commits, pushes, external messages, or modifications to the user's Langflow checkout.
- Use `uv run python` and `uv run pytest`; reuse installed dependencies with `--no-sync` where appropriate.
- Run real Chrome and inspect its videos/screenshots. Model mocks establish unit behavior only, never product accuracy.
- PR14931 expects a build rejection with a visible policy diagnosis. Rejection alone is not a defect; an absent required diagnosis is a valid failure even on the fixed revision.
- PR14913 requires browser login, component-list interaction, flow construction/build, and the Langflow Assistant creation/build path.
- Missing real model/auth/setup requirements stay explicit. Do not substitute fake success for real Assistant or flow behavior.
- Changes to reviewed setup/expectations invalidate approval; unchanged reruns capture fresh evidence.
- Only run reviewed local setup plans; no general cloud provisioning or arbitrary generated fixture code.

## Tasks and Ownership

### Task 1: Plan Discovery and Approval

Owner: foundation implementer. Files: `qabot/journeys/models.py`, `setup.py`, `approval.py`, `tests/test_journey_setup.py`, `tests/test_journey_approval.py`.

Interfaces:

```python
# models.py promotes the spike's Journey/Step/Result models without removing fields.
class StartupPlan(BaseModel):
    command: str
    cwd: str
    health_url: str
    env: dict[str, str] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    reset_command: str | None = None
    sources: list[str] = Field(default_factory=list)

class ReviewPlan(BaseModel):
    repo: str
    base: str
    head: str
    description: str
    startup: StartupPlan
    journeys: list[Journey]
    unresolved: list[str] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)

def discover_plan(repo: Path, base: str, head: str, description: str, llm) -> ReviewPlan: ...
def approve_plan(plan_path: Path, reviewer: str) -> Path: ...
def require_approval(plan_path: Path) -> dict: ...
```

The JSON plan is the editable artifact. Approval is a separate adjacent JSON artifact with content identity, reviewer, timestamp, and identities of local executable setup scripts. Changed plans or referenced setup scripts must fail before execution. Hash parsed semantic JSON so formatting-only edits do not require approval. No secret values in discovery output: use required environment variable names and `${NAME}` references. Read only relevant repository documentation/manifests/config definitions; never ingest real `.env` secret values. Startup discovery calls the existing `complete_json` provider with bounded collected evidence and must expose missing/conflicting instructions. No hardcoded Langflow command in general discovery. Journey authoring must use repository knowledge as well as diff/description, distinguish expected errors, and discover alternate flow-building entry points such as the Assistant from the supplied repo evidence.

- [x] Write failing tests for discovery from documentation, unresolved required setup, referenced-script approval invalidation, and unchanged approval reuse.
- [x] Implement the minimal interfaces above, retaining spike model compatibility.
- [x] Run focused tests and return code-quality/spec self-review notes.

### Task 2: Browser Execution and Evidence

Owner: root implementer. Files: `qabot/journeys/walker.py`, `snapshot.py`, `report.py`, `runner.py`, `tests/test_journey_runner.py`, `tests/test_journey_walker.py`.

Interfaces: consume `ReviewPlan` and its `Journey` models; expose `run_plan(plan_path: Path, out: Path, *, headed: bool, channel: str, selected: list[str] | None) -> int`. Use exact reviewed startup/configuration, per-run output directories, per-journey video, initial state record, and process cleanup. Missing prerequisite => BLOCKED, expected application rejection => evaluate expected observation rather than automatic BUG. Browser operations remain validated and use Playwright; no blind first-match fallback. Preserve partial results after failures and make failed required recording explicit. Add richer browser operations only when real Langflow interactions require them.

- [x] Promote existing spike code mechanically with package-local imports.
- [x] Write failing tests for negative-journey error handling, stale approval preventing launch, environment/secret resolution, partial artifacts, and actual local Chrome recording.
- [x] Implement execution and local HTML/JSON/Markdown results, with terminal progress and clear exit behavior.
- [x] Verify video files are playable and reference the correct run; inspect screenshots on local reference app.

### Task 3: CLI Integration and Manual Example

Owner: root after task interfaces exist. Files: `qabot/cli.py`, `qabot/journeys/cli.py`, `README.md`, `examples/`, `tests/test_journey_cli.py`.

CLI:

```text
qabot journeys plan --repo PATH --base REF --head REF --description FILE --out PLAN.json
qabot journeys approve PLAN.json --reviewer NAME
qabot journeys run PLAN.json --out RUN_DIR [--headed] [--channel chrome] [--journey ID]
```

- [x] Add parser and command tests before wiring commands.
- [x] Document the exact editable plan, approval, run, report, and rerun procedure with absolute example paths.
- [x] Validate on the bundled independent local web app as well as Langflow; keep fake model use confined to tests.

### Task 4: Langflow Reproductions and Iteration

Owner: root with target investigation/validation agents. Only change Langflow files in isolated disposable target worktrees when setup explicitly needs it; do not patch away the defects under evaluation.

- [x] Establish isolated target builds containing each fix and baseline comparisons, with independent state and recorded flags.
- [x] Generate startup/journey plans from repo evidence and PR text; inspect whether they include login, components, editor build, and Assistant.
- [x] Have actual review/approval provenance; do not label an agent's generated expectation as human-confirmed without review.
- [x] Execute PR14931 expected-error diagnostic and PR14913 editor and Assistant paths; record video and screenshots.
- [x] Inspect actual browser evidence, fix qabot when verdicts are invalid, and repeat affected cases.
- [x] Run focused tests then full local regression suite; get independent code/evidence review and fix material findings.
- [x] Deliver the runnable walkthrough, correct videos/results, remaining evidence limits, final PRD/state, and worktree path. Keep the usable demo service available for Jordan.

## Final Verification

649 tests passed, 1 legacy live-model test deselected; Ruff and whitespace checks pass.
Real Claude/Watsonx runs independently establish editor PASS (including exact submitted
input), Assistant PASS twice against persistent state, and shop PASS/PASS/FAIL.
PR14931 is a valid browser FAIL: the required policy note is missing. Videos decode
in Chrome; reports were checked on desktop/mobile. Earlier failed/cancelled evidence
is preserved. The manual shop remains at `http://127.0.0.1:7888/ui`; test-owned app
processes are stopped. `/private/tmp/qabot-cli-2026-09-06/examples/WALKTHROUGH.md`
is the handoff. PRD production gates remain explicit and are not certified by this pilot.

## Preflight

Chrome channel `chrome`, headed interaction and video succeeded in the original workspace. Full local baseline in this worktree: 569 passed, 1 live-model test deselected. There are no active Langflow servers on the previously used ports. Real Assistant/model credentials and setup are being investigated before dependent execution.

## Interface Review

| Tasks | Shared interface | Ruling |
| --- | --- | --- |
| 1 / 2 | ReviewPlan, StartupPlan, Journey models | Task 1 owns schemas; task 2 consumes fields above. Additive browser-check fields require coordination. |
| 1 / 3 | discover_plan, approve_plan, require_approval | Task 3 handles argparse; task 1 has no CLI ownership. |
| 2 / 3 | run_plan | Root owns both; JSON outcomes remain distinct from process completion. |
| 2 / 4 | Runner and browser evidence | Validation may change runner logic only with focused regression coverage; never weaken expectations to force a pass. |
| 1 | Discovery and approval tests | No setup executes during discovery; approval checks cover local scripts and semantic plan changes. |
| 2 | Execution and evidence tests | Test real local browser and process lifecycle; no fake product-success claim. |
| 3 | CLI and walkthrough | All example commands call packaged CLI, not spike imports. |
| 4 | Actual PR validation | PR14931 is expected rejection with diagnostic; PR14913 includes two creation/build paths and real prerequisites. |
