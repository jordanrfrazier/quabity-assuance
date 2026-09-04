"""Orchestration for a single CI run.

The runner is deliberately stateless: it reads a frozen knowledge-base snapshot,
exercises the app, and returns a report. It never mutates the knowledge base --
a flaky run must not be able to corrupt the asset. Anything it learns leaves as
OpenQuestions for the async curator loop to apply.

Order matters. The staleness pass runs FIRST, because the knowledge base is hosted
and nothing else forces it to track the customer's refactors.
"""

from __future__ import annotations

from pathlib import Path

from qabot.anchors import staleness_pass
from qabot.drivers.base import Driver, DriverError
from qabot.impact import select_workflows
from qabot.llm import LLMProvider
from qabot.models import (
    KnowledgeBase,
    Outcome,
    RunReport,
    StepResult,
    Workflow,
    WorkflowResult,
)
from qabot.planner import PlanError, capture_variables, resolve_step
from qabot.routemap import RouteMap
from qabot.verifier import verify_workflow


def _execute_workflow(
    workflow: Workflow, driver: Driver, llm: LLMProvider
) -> tuple[list[StepResult], dict[int, object]]:
    """Run one workflow's steps, stopping at the first step that cannot proceed.

    A step's outcome here means "did the interaction happen", not "was the app
    correct" -- correctness is the verifier's job. Anything that prevents the
    interaction produces BLOCKED and halts this workflow, never a guessed result.
    """
    variables: dict[str, object] = {}
    step_results: list[StepResult] = []
    observations: dict[int, object] = {}

    for index, step in enumerate(workflow.steps):
        try:
            action = resolve_step(step, variables, llm)
        except PlanError as exc:
            step_results.append(
                StepResult(intent=step.intent, outcome=Outcome.BLOCKED, detail=str(exc))
            )
            break

        try:
            observation = driver.execute(action)
        except DriverError as exc:
            step_results.append(
                StepResult(intent=step.intent, outcome=Outcome.BLOCKED, detail=str(exc))
            )
            break

        if not observation.ok:
            # Prefer the driver's explanation over its summary. A summary says
            # "click -> TimeoutError", which tells a developer nothing; drivers put
            # the actionable reason ("no accessible control named 'Remove widget'")
            # under evidence["error"], and a BLOCKED nobody can act on is a BLOCKED
            # that gets ignored.
            explanation = observation.evidence.get("error")
            step_results.append(
                StepResult(
                    intent=step.intent,
                    outcome=Outcome.BLOCKED,
                    detail=str(explanation) if explanation else observation.summary,
                    evidence=observation.evidence,
                )
            )
            break

        observations[index] = observation
        step_results.append(
            StepResult(
                intent=step.intent,
                outcome=Outcome.PASS,
                detail=observation.summary,
                # Carry the pre-substitution hint alongside the concrete request.
                # The driver's evidence records the request as sent -- ids already
                # substituted -- so without this a generated test would hard-code a
                # server-generated id from the run that produced it and go red later
                # for the wrong reason. `hint` keeps the templated form and the
                # capture map so the test can re-derive ids at replay time.
                evidence={**observation.evidence, "hint": step.hint},
            )
        )

        try:
            capture_variables(step, observation, variables)
        except PlanError as exc:
            step_results.append(
                StepResult(
                    intent=f"capture after: {step.intent}",
                    outcome=Outcome.BLOCKED,
                    detail=str(exc),
                )
            )
            break

    return step_results, observations


def run(
    kb: KnowledgeBase,
    driver: Driver,
    source_root: Path,
    diff_text: str,
    llm: LLMProvider,
    budget: int = 10,
    base_ref: str = "main",
    head_ref: str = "HEAD",
    route_map: RouteMap | None = None,
) -> RunReport:
    """Execute a full QA run and return the report.

    Anything the driver could not guarantee about the run -- an app with no reset
    endpoint, say -- is read off the driver and carried into the report as a stated
    limitation. It is read with `getattr` rather than by widening the Driver protocol
    on purpose: a driver with nothing to declare should not have to say so, and a
    protocol change would strand every Driver implementation that is fine as it is.

    `route_map` is read the same way and for the same reason. A run whose route table
    could not be built still runs, but it selects on decorator inference alone, and a
    `RouteMap.unavailable(...)` says so in the report rather than letting an empty
    selection read as "nothing was at risk" -- which is the false-green failure this
    product's whole positioning is against.
    """
    stale_ids, stale_questions = staleness_pass(kb, source_root)
    selected, skipped = select_workflows(kb, diff_text, source_root, budget, route_map)

    results: list[WorkflowResult] = []
    for workflow in selected:
        driver.reset()
        step_results, observations = _execute_workflow(workflow, driver, llm)
        results.append(verify_workflow(workflow, step_results, observations, llm))

    return RunReport(
        repo=kb.repo,
        base_ref=base_ref,
        head_ref=head_ref,
        selected=[w.id for w in selected],
        skipped_for_budget=skipped,
        stale_workflows=stale_ids,
        results=results,
        open_questions=stale_questions,
        limitations=[
            *getattr(driver, "limitations", ()),
            *getattr(route_map, "limitations", ()),
        ],
    )
