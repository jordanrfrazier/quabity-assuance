# Workflow Learning and Reuse

Status: proposal for later product review; no implementation is authorized here.
Date: 2026-09-07.
Project directory: `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`.
Branch: `main`.

## Motivation and Evidence Limits

Repeated setup, such as reaching a login form or preparing a new flow, may spend
model time rediscovering a procedure that a previous run already verified. A
reviewed reusable procedure could reduce repeated decisions while still checking
the current application and gathering new evidence.

Jordan observed approximately 1 minute 45 seconds for a four-step diagnostic with
eight browser actions. With one actor and one judge request per action, that would
imply 16 serial model requests; it is an architectural estimate, not a measured
request count or latency breakdown for the historical run. Old reports do not
contain per-phase timing. Video length alone cannot establish model time, waiting
time, or a speedup. V1 timing evidence should inform whether reuse is worthwhile.

## Three Separate Proposals

| Mechanism | What could be reused | What must still be established |
| --- | --- | --- |
| Reviewed setup procedure replay | Approved browser actions and guards for a bounded setup task. | Current compatibility, action success, expected state, and fresh evidence. Login still runs if it is part of the procedure. |
| Authentication-state reuse | Explicitly permitted browser authentication state for a particular identity and target. | Session validity, identity/role, target/profile compatibility, and fresh application state. This does not exercise login. |
| Pattern mining after a run | Suggestions extracted from repeated verified setup behavior, potentially by a separate agent after execution. | Human approval before any candidate becomes executable; learning never changes the completed run's evidence or verdict. |

These mechanisms need separate acceptance and data-handling decisions. A successful
replay does not imply that storing authentication state is permitted, and running
a pattern miner does not approve its suggestions.

## Candidate Extraction and Review

The smallest candidate is a bounded setup procedure with a clear initial guard and
observable end condition. Candidate extraction would use verified setup actions
from retained runs, preserving the original step order and literal nonsecret input
values. It must not infer a working procedure from an attempted action, a missing
observation, or an overall verdict alone. A run that later fails could still supply
individually verified setup steps, but the later failure and source evidence must
remain attached for review. No automatic promotion follows from repetition.

A reviewable candidate would record:

- Source run, journey and step identities, their approved versions, evidence
  references, and the observed result for each included setup step.
- The task it prepares, exact actions and inputs, initial guards, intermediate
  checks, end conditions, action/time bounds, and any state mutations or reset needs.
- Application/target identity, relevant source and setup dependencies, compatible
  configuration profile, identity/role, and secret reference names.
- Whether a human or an agent proposed or reviewed it, the accepted content version,
  reviewer identity, approval time, and the scope of any explicit human approval.

The human can inspect and edit the candidate before approving a specific version.
An agent's favorable assessment is agent review, not human confirmation. Execution-
affecting edits require renewed approval. The procedure's approval also cannot
authorize a changed journey or startup plan that requires its own review.

## Bounded Replay and Fresh Evidence

Before replay, validate the approved version and evaluate current guards. Select a
procedure only when the target, configuration, identity/role, and state satisfy its
reviewed compatibility conditions. Unknown compatibility must be visible and block
automatic replay; matching a procedure name or URL is insufficient.

Replay would execute the approved actions within explicit action and time bounds,
check observable state along the way, and capture new screenshots, video, browser
errors, and judgment evidence. It must not skip the behavior under test: a journey
testing login must perform and verify login even if an authenticated session exists.
Setup reuse must not change the reviewed expectation or substitute a different input.

When a guard fails, a locator becomes ambiguous, an action diverges, or the expected
state does not appear, stop replay and record the failing operation with evidence.
Do not silently repair the procedure, click a different control, retry a submission,
switch identity, or grant a cached PASS. Whether to resume ordinary model-driven
execution after a visible stop is an open product decision; any future policy must
preserve the failed replay and stay inside the approved journey.

Every run evaluates the current application's behavior. Prior outcomes establish
candidate provenance only; verdicts and successful observations are never cached
as proof that the new run passed.

## Compatibility and Invalidation

The proposal needs explicit, inspectable invalidation rules before implementation:

| Change or condition | Proposed handling |
| --- | --- |
| Actions, literal input, guard, expected setup state, or reset procedure changes | Invalidate procedure approval and require review of the changed version. |
| Target/origin, profile, role, identity reference, or relevant setup dependency changes | Require a reviewed compatibility decision; do not assume a prior login/setup still applies. |
| Referenced executable instructions change at the same path | Treat them as changed content, consistent with startup approval. |
| UI structure or application revision changes | Reevaluate compatibility and fresh guards; the exact revision compatibility policy remains open. |
| Session expires, identity cannot be verified, or initial server data differs | Stop reuse and expose the unmet condition. Browser context reuse does not reset server state. |
| Replay diverges despite valid prior approval | Preserve the failure and mark the procedure for review; do not overwrite its provenance with a repaired procedure. |

Approval validity and runtime readiness are separate. Unchanged approved content
can still be unusable against the current application.

## Secrets and Authentication State

Procedures should retain secret reference names such as `${QA_PASSWORD}`, never
credential values captured from a run. Required secrets remain developer supplied.
Source evidence and candidate extraction must respect the existing credential
boundary; screenshots or videos that visibly contain a secret are not sanitized
merely by redacting report text.

Authentication state can contain session credentials even when no password is
present. Its storage, access, expiration, deletion, and allowed identity/target scope
need an explicit policy before reuse is built. It must not be embedded in recipes,
sent to a pattern-mining model, or bundled with reviewer-facing reports. A fresh
identity/role check is required after restore. Persistent server-side fixtures need
their own readiness/reset evidence.

## Optional Pattern Mining After a Run

A later experiment could inspect completed, eligible evidence and suggest recurring
setup procedures after the execution report is finalized. A separate learning agent
is one possible mechanism, not an accepted architecture or v1 requirement. It would
have proposal-only authority, bounded inputs/cost, and no ability to execute actions,
change approvals, revise completed verdicts, or replace source evidence.

Candidate discovery should report why steps appear reusable and where they differ
across runs. Frequency is not correctness: identity, configuration, literal inputs,
and server state can make superficially similar sequences incompatible. Candidate
promotion still requires explicit human review of the actual procedure.

## Decisions and Evaluation Before Building

- Use measured v1 phase timing and call counts to select a worthwhile setup task;
  do not commit a speed target based on the historical video.
- Decide candidate storage/format, manual versus mined extraction, matching rules,
  revision compatibility, and approval granularity before implementing them.
- Decide whether authentication-state reuse is wanted independently, including
  local credential storage/retention and the journeys where it is prohibited.
- Decide how visible replay divergence affects subsequent execution and whether a
  separate learning agent justifies its model cost and operational complexity.
- Compare equivalent fresh runs with and without replay, including latency, calls,
  evidence completeness, wrong-role/profile cases, changed UI, expired sessions,
  duplicate-submission risk, cancellation, and known application failures.

No benchmark result or general performance improvement is claimed by this proposal.
See the [v1 PRD](/private/tmp/qabot-cli-2026-09-06/docs/PRD.md) for release requirements
that remain in scope independently of workflow learning.
