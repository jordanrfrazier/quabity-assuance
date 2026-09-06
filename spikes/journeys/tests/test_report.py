from qabot.models import Finding, Outcome, Severity
from spikes.journeys.models import (
    ActionRecord,
    Journey,
    JourneyResult,
    JourneyStep,
    StepOutcome,
    StepResult,
)
from spikes.journeys.report import render


def _result(outcome, step_outcomes, findings=()):
    j = Journey(
        id="j1",
        title="Run the starter flow",
        persona="a first-time user",
        preconditions={"settings": {"LANGFLOW_ALLOW_CUSTOM_COMPONENTS": "false"}, "state": []},
        steps=[
            JourneyStep(do="Open the Basic Prompting starter", see="the canvas"),
            JourneyStep(do="Click Run", see="a reply appears"),
        ],
    )
    steps = [
        StepResult(
            index=i,
            do=s.do,
            see=s.see,
            outcome=o,
            reason="r" if o != "held" else "",
            actions=[
                ActionRecord(
                    op="click", ok=True, summary="clicked", screenshot="shots/step_001.png"
                )
            ],
            findings=list(findings) if i == 1 else [],
            screenshot="shots/step_001.png",
        )
        for i, (s, o) in enumerate(zip(j.steps, step_outcomes, strict=True))
    ]
    return JourneyResult(
        journey=j, outcome=outcome, steps=steps, why="r" if outcome != "pass" else ""
    )


def test_render_has_summary_steps_and_marks():
    md = render([_result(Outcome.PASS, [StepOutcome.HELD, StepOutcome.HELD])])
    assert "| Run the starter flow | PASS |" in md
    assert "1. ✓ **Open the Basic Prompting starter** — see: the canvas" in md
    assert "shots/step_001.png" in md
    assert "LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false" in md


def test_render_keeps_declared_and_inferred_findings_apart():
    declared = Finding(
        workflow_id="j1",
        workflow_name="t",
        severity=Severity.BUG,
        outcome=Outcome.FAIL,
        statement="the page rendered an error state",
        detail="Flow build blocked",
        oracle="page_error_screen",
    )
    inferred = Finding(
        workflow_id="j1",
        workflow_name="t",
        severity=Severity.QUESTION,
        outcome=Outcome.FAIL,
        statement="expected to see: a reply",
        detail="no reply",
        oracle=None,
    )
    md = render(
        [
            _result(
                Outcome.FAIL, [StepOutcome.HELD, StepOutcome.FAILED], findings=[declared, inferred]
            )
        ]
    )
    assert md.index("The app said (BUG)") < md.index("We inferred (QUESTION)")
    assert "Flow build blocked" in md and "no reply" in md


def test_render_lists_what_it_could_not_check():
    md = render([_result(Outcome.BLOCKED, [StepOutcome.BLOCKED, StepOutcome.NOT_REACHED])])
    assert "## What this run could not check" in md
    assert "○" in md and "–" in md
