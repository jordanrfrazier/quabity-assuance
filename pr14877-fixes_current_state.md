# PR14877 Findings Fixes

## Scope - 2026-09-09

- User requested fixing all findings from the lookup investigation.
- Implement confirmed Langflow defects: nested-event isolation, inappropriate
  generation-helper exposure/routing, and search path/payload noise.
- Qabot's recorded failure was valid; optional new reporting features are
  separate enhancements, not defects in this run. Do not change its verdicts.
- No commits, pushes, provider calls, or publishing authorized in this message.
  Use local offline tests and preserve all original source/evidence targets.

## Working Directory

- Implementation:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/.worktrees/langflow-pr14877-fixes`
  on branch `fix/pr14877-lookup-and-events`, based on PR head
  `b8f96d5ecd2c8a12222587197a7fa098f7519707`.
- Primary notes/artifacts:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`, branch `main`.
- Evidence:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-fixes-20260909`.
- New worktree reuses prepared dependencies by .venv symlink. Do not mutate the
  shared environment or assume imports without exact new-worktree PYTHONPATH.

## Delegation

- GPT-5.5 fix_nested_events: event handler plus scoped regression tests.
- GPT-5.5 lookup_investigation: helper routing/policy, shipped JSON and parity
  tests. Sole writer of shipped JSON to avoid conflicting regeneration.
- GPT-5.5 streaming_investigation: component search implementation and tests;
  coordinates compact lookup/full-source contract with the JSON owner.
- Root: source/architecture review, integration, independent offline verification
  and final status. No unrelated refactoring.

## Verification Plan

- Reproduce the fixed nested-agent behavior with real create_agent and fake
  models; preserve legitimate repeated parent output and tool records.
- Verify disabled generation cannot be reached via the shipped helper tool,
  while permissive generation and built-in search remain available.
- Verify package-relative matching, compact lookup metadata, explicit source
  retrieval, and saved/installed component parity.
- Run pytest only on tests edited/created in this task. Retain outputs locally.
- Live browser/provider confirmation remains pending fresh explicit permission.

## Progress

- Event implementation and focused regressions pass. Root independently ran
  the original real nested-create_agent probe against the fixed worktree:
  one parent answer, with two legitimate repeated parent answers retained.
- Review requested an automated real-orchestration regression, in addition
  to the synthetic event cases.
- Search changes must update only their cached registry entry and shipped
  node; verify real callable-tool defaults as well as direct component calls.
- Routing changes must specifically identify the shipped generation helper;
  unrelated Agent tools must remain connected.
- Root event regression run: 18 passed, including real nested-agent callbacks.
- Root initial backend integration run: 74 passed, 3 failed. Failures expose
  accidental extra columns in the default full-source output; preserve the
  original two-column schema, not weaken the compatibility assertions.
- Root review rejected unsupported hardcoded Message Input aliases. Search
  must report actual registry/source names rather than reinforce the wrong
  model-generated label.
- Root caught renamed helper tags dropping permissive tools. Preserve runtime
  tags and test actual toolkit exposure, defaults, and scheduler selection.

## Final Status

- All three confirmed implementation defects fixed in the isolated worktree.
- Root final verification: 87 backend tests and 18 event tests passed (105 total).
  All edited Python files pass Ruff; git diff --check passes.
- Actual graph-built search tool uses compact defaults; explicit source works.
  Generic component default and two-column source schema remain compatible.
- Permissive renamed helper tools remain available; disabled action metadata
  filters them correctly. Private-filter-only review concern was a false positive.
- Shipped JSON and registry source parity verified; only the search registry
  entry plus its enclosing checksum changed.
- No source changes in the original checkout; no commits or provider calls.
- Evidence and live-validation checklist:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-fixes-20260909/README.md`.
- Next: obtain fresh explicit authorization for live browser/model-provider
  replay. Do not present these offline checks as new browser evidence.
