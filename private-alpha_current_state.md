# Private Alpha Readiness

## Assessment - 2026-09-09

- Working directory: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`.
- Branch: `main`, HEAD `629e143`.
- User asked for the best next product step, not implementation or publication.
- Recommendation: prepare one reproducible CLI candidate and observe first use
  by someone outside the implementation team before broader release.

## Observed Gaps

- State-prerequisite enforcement remains uncommitted in the local
  `fix/state-prerequisites` worktree.
- Report ZIP support remains uncommitted in the local `feature/report-bundle`
  worktree. Both are based on the current main revision.
- Main README and walkthrough contain machine-specific paths, historical worktree
  instructions, and prepared Langflow runtime assumptions.
- Existing live evidence proves useful findings under assisted setup, not
  clean-machine onboarding or successful independent use on another repository.
- The latest Langflow fixes have offline verification, not a fresh browser pass.

## Proposed Sequence

1. Integrate reviewed product changes into one candidate, verify it, and make the
   supported CLI quickstart portable. Keep historical evidence intact. Integration
   and commits require a separate explicit request.
2. Close the Langflow fix loop with a focused browser run against the corrected
   revision and unchanged expectations. Provider calls need fresh authorization.
3. Have one external tester use a fresh environment and their own supported
   non-Langflow repository. Observe setup, plan review, execution, evidence review,
   unchanged rerun, and local ZIP extraction; record every intervention.
4. Fix first-use blockers, then expand to three private testers. No public launch,
   hosted service, billing, or V2 workflow learning needed for this experiment.

## Proposed Pilot Boundaries And Measures

- Supported audience: macOS developers with Chrome, uv, authenticated Claude CLI,
  a local browser application, and their own non-production credentials.
- Explain what goes to model providers and what is retained locally. Reports can
  contain sensitive pixels; require review before any external sharing.
- Suggested usability target, not yet accepted: first useful report within
  30 minutes once the target app's documented prerequisites are available.
- Measure plan corrections, undocumented setup interventions, actor-caused
  blocks, human verdict disagreements, elapsed time, and reported model usage.
- Success means no qabot source edits or author-written rescue scripts, evidence
  the tester understands, an unchanged rerun, and willingness to use a second PR.
- A known-broken control must not become PASS through relaxed expectations.

## Status

- Recommendation only. No product edits, tests, commits, provider calls, invites,
  uploads, or publication performed for this assessment.
