# Runner Cleanup Current State

Working directory: /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance
Branch: main

## Status

- Fixed `qabot/journeys/runner.py` so application cleanup failures cannot prevent final `finished_at`/`cancelled` metadata and report persistence.
- Refined SIGKILL `PermissionError` handling so an EPERM after process exit is only treated as unresolved cleanup when process-group inspection still finds surviving members or cannot verify the group.
- Added focused regression coverage in `tests/test_journey_runner.py`.
- No commits.

## Decisions

- `_stop(process)` now returns unresolved cleanup diagnostics instead of raising for expected process-group cleanup failures.
- SIGTERM timeout or SIGTERM permission issues are treated as escalation if final SIGKILL/wait succeeds; only unresolved final cleanup failures are reported.
- SIGKILL `PermissionError` triggers a bounded `ps` process-group inspection. Empty group means cleanup is verified; surviving members or failed inspection remains a BLOCKED cleanup diagnostic.
- Process-group inspection uses only `pid`, `pgid`, and `stat`; it does not collect command-line text. Empty or malformed `ps` output is treated as unverifiable and remains a cleanup diagnostic.
- Final `run_plan` cleanup is protected against unexpected `_stop` and startup log-thread finalization exceptions.
- Cleanup diagnostics are recorded in `metadata["cleanup"]` and `limitations`.
- Passing journey results are downgraded to `BLOCKED` when application teardown cannot be verified.
- Existing `FAIL` results remain `FAIL` while still retaining cleanup diagnostics.
- Linkding02 posthoc evidence: `results.json` had final metadata and 24 held steps, port `7891` was free, and later `ps` showed no members of group `88136`; this supports a false unresolved-cleanup diagnostic, not an application behavior failure.

## Verification

- Passed: `uv run pytest tests/test_journey_runner.py` (52 tests).
- Passed: `uv run ruff check qabot/journeys/runner.py tests/test_journey_runner.py`.
- Bounded real-process repro: started a disposable Python process group with a child that ignores SIGTERM under `Popen(start_new_session=True)`, observed 2 process-group members before `_stop`, `_stop` returned `[]`, and post-stop process-group inspection returned `[]`.
- Port check: `lsof -nP -iTCP:7891 -sTCP:LISTEN || true` returned no listener after the repro.
