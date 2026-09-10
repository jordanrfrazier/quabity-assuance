# Open-source and developer tools relevant to qabot

Checked: 2026-09-09. Scope: public primary documentation and repository pages only. No tools were installed, cloned, executed, or connected to accounts. Features below are documented capabilities, not hands-on validation. Repository license labels were checked; no legal interpretation is offered. Mutable documentation and default branches were observed, not a pinned release audit.

Comparison target: qabot's local CLI converts repository/PR/docs context into proposed startup/configuration and human-reviewed natural-language journeys, then runs an approved, version-bound plan in local Chrome with a model and reports PASS/FAIL/BLOCKED plus video, screenshots, and ZIP evidence. Workflow learning belongs to deferred v2 scope.

Already present versus proposed: the project review supplied for this comparison confirms stable journey IDs, JSON/HTML reports, required-video validation, per-step images/timings/call counts, secret references, executor completion separate from judge assessment, and approval-bound startup/reset configuration. Those are existing strengths to keep and benchmark, not new feature recommendations. Proposed deltas below are optional typed deterministic assertions, richer trace debugging, and enforced execution budgets. Reusable browser/auth profiles, learned replay, and test export remain deferred options, not accepted v1 work. This paragraph uses the supplied local project findings; external sources below establish competitor behavior only.

## Classification

| Tool | Relationship to qabot | Documented core | License |
| --- | --- | --- | --- |
| Playwright Test Agents + Test | Strong DIY substitute for developers; also a foundation | App exploration, Markdown planning, generated executable tests, repair loop | Apache-2.0 |
| Playwright CLI / MCP | Browser-control building blocks | Agent-facing browser commands/tools and session control | Apache-2.0 |
| Stagehand | Execution SDK/building block | Natural-language actions plus code, observation, caching | MIT |
| browser-use | Execution agent/building block | Python browser agent with local browser configuration and structured history | MIT |
| TestZeus Hercules | Close OSS QA runner competitor | Gherkin scenarios to agent execution, test reports, and proofs | AGPL-3.0 |

These classifications are analytical judgments about the documented workflows. They do not establish that any product lacks undocumented capabilities.

## Playwright Test Agents, CLI, and MCP

Observed workflow: the planner explores a running application using a seed test and optional PRD, and writes Markdown scenarios. The generator turns those scenarios into Playwright tests while verifying selectors and assertions live. The healer replays failures, proposes changes, and reruns; its documented output can also be a skipped test when it considers functionality broken. Agent definitions should be regenerated after Playwright updates. This overlaps strongly with qabot's plan-to-run path, although approval hashes and startup discovery were not established in this review. [Test Agents](https://playwright.dev/docs/test-agents)

The CLI is specifically positioned for coding agents needing concise commands and lower context overhead. MCP targets persistent exploratory loops with richer page state. This is a vendor architectural recommendation, not a measured cost comparison here. [Coding agents](https://playwright.dev/docs/getting-started-cli)

MCP documents persistent workspace profiles, isolated contexts initialized from storage state, and an extension for existing logged-in tabs. A persistent profile cannot serve concurrent browser instances. [MCP repository](https://github.com/microsoft/playwright-mcp)

Playwright supports reusable authentication state, including one account per worker for tests changing shared server state. Its trace viewer connects actions to DOM snapshots, source, logs, and errors. Auto-retrying assertions check observable UI conditions. [Authentication](https://playwright.dev/docs/auth), [Trace viewer](https://playwright.dev/docs/trace-viewer), [Assertions](https://playwright.dev/docs/test-assertions)

Ideas for qabot:

1. Proposed delta: add optional typed deterministic assertions alongside the existing judge, for example expected URL, visible role/name, exact field value, or element count. Preserve the approved expected outcome. Deferred test export could produce an inspectable regression artifact; generated code still cannot guarantee identical backend behavior.
2. Keep/benchmark the existing approval-bound startup/reset configuration and BLOCKED setup outcomes. A deferred v2 extension could reuse reviewed project/browser/auth profiles, with freshness checks and account isolation; auth reuse is not proposed as accepted v1 scope.
3. Proposed delta: enrich the existing images, timings, reports, and ZIP with action-to-DOM/network/console trace indexing. Video explains the visible sequence; richer trace data can explain why an action or assertion failed. Trace capture and export require explicit secret/personal-data handling because they can expose more than screenshots.

Risk: automatic healing or skipping must not silently redefine an approved acceptance condition. For qabot, a repair that changes the journey or expected outcome should create a new reviewable plan revision. CLI-versus-MCP selection should be measured on qabot workloads rather than chosen from promotional token-efficiency claims.

Confidence: high for documented workflow, assertions, auth, and traces; medium for substitution fit; unmeasured for accuracy, cost, and setup effort. Licenses checked in [Playwright](https://github.com/microsoft/playwright), [CLI](https://github.com/microsoft/playwright-cli), and [MCP](https://github.com/microsoft/playwright-mcp).

## Stagehand

Observed workflow: a developer combines ordinary browser code with model-directed actions. `observe()` returns candidate actions with description, method, arguments, and selector, allowing validation before `act()`. Variable placeholders can keep secret values out of the observed action arguments. [Observe](https://docs.stagehand.dev/v3/basics/observe)

The documented local cache persists actions and agent steps to a directory and replays cached actions without model calls; it works with both LOCAL and BROWSERBASE environments. Managed server caching is separate. Documentation describes cache input sensitivity and the need for stable page state. [Caching](https://docs.stagehand.dev/v3/best-practices/caching)

Ideas for qabot:

1. Proposed delta: expose resolved action candidates for validation before execution and include the chosen interpretation in richer debugging evidence. This extends existing approval and step evidence rather than introducing approval itself.
2. Deferred v2 replay idea: key cached resolutions to the approved plan, application revision, browser/tool version, and relevant page state; bound retries and rediscovery. Report cache hits, misses, and renewed inference explicitly. This is a proposed qabot design, not a claim about Stagehand's exact keys.
3. Keep/benchmark qabot's existing secret references and execution-time binding against Stagehand's placeholder approach; this is not new scope.

Risk: Stagehand enables self-healing by default according to its constructor reference. Silent rediscovery is unsuitable when it changes an approved test's meaning. A cache avoids repeated inference but does not prove that application behavior is correct. Local Chrome also does not imply a local model or that page data stays on-device. [Constructor reference](https://docs.stagehand.dev/v3/references/stagehand)

Confidence: high for documented APIs and cache behavior; medium for integration fit; no reliability or savings benchmark performed. MIT is listed in the [Stagehand repository](https://github.com/browserbase/stagehand). SDK licensing does not describe the terms or cost of Browserbase hosting or model providers.

## browser-use

Observed workflow: configure a Python agent with a task, model, and browser; run it and inspect history. The repository also documents a persistent CLI with navigation, state inspection, indexed clicks, typing, and screenshots. This is a general automation foundation, not by itself evidence of qabot-style acceptance-test governance. MIT is documented for the OSS library. [Repository](https://github.com/browser-use/browser-use), [official license statement](https://browser-use.com/legal/terms-of-service)

History provides action parameters, errors, screenshot paths, duration, and structured Pydantic output. `is_done()` means a done action occurred; `is_successful()` is the agent's own assessment. The documentation explicitly calls for independent outcome verification. [Output format](https://docs.browser-use.com/open-source/customize/agent/output-format)

Agent parameters include model-free initial actions, retry limits, per-step/model timeouts, and optional API-cost tracking. Browser parameters include storage state, profile paths, viewport, executable/channel selection, recordings, HAR, and traces. Video requires optional dependencies; documentation says missing dependencies can result in no saved video without an error. [Agent parameters](https://docs.browser-use.com/open-source/customize/agent/all-parameters), [Browser parameters](https://docs.browser-use.com/open-source/customize/browser/all-parameters)

Ideas for qabot:

1. Keep/benchmark qabot's existing separation of executor completion and judge verdict. The potential addition is optional typed assertions supplementing the judge, not merely a second assessment or a new BLOCKED status.
2. Keep/benchmark existing required-video validation and evidence checks against dependency failure cases. Their presence is a useful comparison advantage, not missing work.
3. Proposed delta: enforce run-level budgets for calls, time, and retries, with explicit budget-exhausted outcomes. Use existing phase/step timings and call counts to choose limits. Cost tracking alone is not a hard spend cap; currency enforcement also needs token/pricing accounting and a stated boundary for in-flight calls.

Risk: profile reuse and extensions can change the tested environment. Save the exact browser configuration in the run manifest. Do not treat hosted browser-use features as OSS-library features: the provider expressly distinguishes those APIs. Deterministic replay/test export was not verified for the OSS library in this review. [Documentation index](https://docs.browser-use.com/llms.txt)

Confidence: high for the cited configuration/output contracts; medium for integration fit; unmeasured for success rate and cost.

## TestZeus Hercules

Observed workflow: supply Gherkin feature files and test data, then execute with a Python/Playwright-based runner. The repository shows HTML/XML results and scenario-specific proof directories containing network logs, screenshots, and videos. It advertises UI assertions and adaptive execution. This is the closest dedicated OSS QA runner in this selection. [Repository and usage](https://github.com/test-zeus-ai/testzeus-hercules)

Ideas for qabot:

1. Keep/benchmark existing stable journey IDs, JSON/HTML reports, screenshots, video, and ZIP structure against Hercules's scenario proof directories. Richer network/trace indexing is the possible delta and carries additional privacy considerations.
2. Keep/benchmark atomic, reviewable scenarios with explicit preconditions and expected outcomes. This is a plan-quality criterion, not a claim that qabot lacks reviewable journeys.

Risk: its AGPL-3.0 license and open-core positioning require a separate reuse decision before borrowing implementation code. Default-on telemetry is documented. Claims such as production readiness, precision, and no maintenance are vendor claims, not validated findings here. Do not copy autonomous healing into approval-bound journeys without preserving original expectations.

Confidence: high for the repository's stated license and artifact structure; medium for workflow overlap; low for untested assertions of accuracy and maintenance savings. Approval/version binding, deterministic replay, and exported standalone tests were not established by this review. [Same primary repository](https://github.com/test-zeus-ai/testzeus-hercules)

## Priorities for qabot

The strongest proposed deltas are (1) optional typed deterministic assertions supplementing the existing judge, (2) richer trace/debug indexing over existing evidence, with explicit privacy handling, and (3) enforced execution budgets over existing timing/call telemetry. Approval, startup/reset binding, BLOCKED outcomes, secret references, required video, journey IDs, and JSON/HTML/ZIP reporting should be retained and benchmarked as existing capabilities. Reviewed project/browser/auth reuse, bounded replay, and test export remain deferred v2 options, not commitments for v1.

The supplied local Linkding03 measurement reports 100 calls, 253.45 seconds actor time, 92.19 seconds judge time, and 401.32 seconds of summed step time. This motivates testing bounded replay and inference reduction, but does not establish their speedup: cache misses, invalidation, application waits, and verification costs still need measurement. These figures are local project evidence supplied for comparison, not a competitor benchmark.

Evidence limits: this review cannot compare flake rates, false positives, model bills, installation friction, browser compatibility, or security guarantees. No absence claim is based solely on an omitted feature in a README. Subsequent hands-on evaluation would need the same bounded application scenarios, pinned tool versions, repeated runs, and separate accounting for model and browser costs.
