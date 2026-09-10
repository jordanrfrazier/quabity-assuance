# PR14877 Lookup Investigation

## Scope - 2026-09-09

- User requested a team of GPT-5.5 agents to investigate strange component-lookup
  behavior. Investigation only; no product fixes or commits requested.
- Working directory:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance`, branch `main`.
- Three GPT-5.5 agents independently cover lookup/search, response duplication,
  and qabot/evidence validity. Root reviews conclusions and reproduction claims.
- No new provider calls, server launches, publishing, or other external writes.
  Local source/evidence inspection and bounded offline probes are permitted.
- Original reports, plans, screenshots, recordings, and databases stay intact.
  Any database inspection must use read-only mode and not print credentials.

## Inputs

- Source: detached `.worktrees/langflow-pr14877-after`, head
  `b8f96d5ecd2c8a12222587197a7fa098f7519707`.
- Control: detached `.worktrees/langflow-pr14877-before`, head
  `fa4bd2ab73627f4b0163d2fc32b0e35d86ca5129`.
- Evidence:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-20260908`.
- New investigation artifacts:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-investigation-20260909`.
- Observed after-03 conversation: greeting completes; component recommendation
  says Message Input rather than Chat Input; both response texts appear twice.
- Existing conclusions do not establish actual search-tool invocation, a
  deterministic cross-model failure, or that PR14877 introduced the issue.

## Next

- Trace search and streaming paths; audit actual browser submissions/oracles.
- Review independent offline reproductions and distinguish fact from inference.
- Document impactful findings and smallest justified fixes or next experiments.

## Root Evidence Review

- Read-only SQLite inspection confirms duplication exists in persisted
  `message.text`, not only browser rendering. Lookup content blocks retain two
  identical 74-character text steps followed by a 148-character final output.
- Persisted tool steps establish that `component_code_search` actually ran with
  column=file_path and keywords chat, message, user, receive. Its ten candidates
  include `input_output/chat.py` with the registered ChatInput class.
- A subsequent `Call_Agent_message_response` tool call receives the original
  question alone and returns the wrong Message Input recommendation. The search
  result is not absent; reviewers are investigating grounding/delegation and
  streaming assembly rather than presuming failed retrieval.
- Stored search content is 213344 characters. Absolute /Users paths also match
  the keyword user, a possible relevance/noise issue; this did not exclude the
  correct ChatInput candidate in the recorded run.
- Empty trace/span tables do not mean no tool evidence: relevant tool results
  are retained in message.content_blocks. Original browser-only limitation is
  now supplemented by this read-only backend evidence.
- Independent evidence audit confirms one browser submission per prompt.
  Exact startup import probes resolve relevant modules to the after worktree;
  legacy Agent Steps groups have an explicit v1 serialization explanation.
- Root rejects a premature fix based on suppressing identical text or assuming
  duplicate event IDs. Distinct nested helper and parent model runs can produce
  the same answer. Streaming reviewer is constructing an offline nested-agent
  reproduction to distinguish ancestry leakage from repeated event identity.
- Routing/search recommendations must stay narrow: correct ChatInput was
  retrieved, so switching all searches to raw source text is not justified by
  this failure. Prioritize the inappropriate helper handoff and unavailable
  tool exposure; treat search payload/ranking cleanup as a separate concern.

## Complete

- All three GPT-5.5 investigations completed. Root independently reran the real
  create_agent nested-tool offline probe using exact after-source PYTHONPATH.
  Exit 0: distinct child/parent model run IDs yield duplicated parent text;
  tool-ancestor filtering yields one answer; legitimate parent repeats remain.
- Root accepts event-ancestry leakage as a demonstrated defect consistent with
  retained messages, not a claim of complete historical provider-stream replay.
  Do not use string dedup or claim original provider-call counts from logs.
- Correct component retrieval and wrong helper output are substantiated by
  persisted content_blocks; one browser submission per prompt is confirmed.
- No application code changes, new provider calls, server launches, commits, or
  publishing. Original evidence unchanged; target after worktree remains clean.
- Consolidated findings, accepted/rejected proposals, source references, and
  recommended fix order:
  `/Users/jordan.frazier/Documents/frazier_projects/quabity-assuance/v1/reports/verification/pr14877-investigation-20260909/findings.md`.
