"""Intrinsic oracle tests.

Five claims are worth breaking the build over: a 5xx and a rendered stack trace are
reported, a 4xx is not, an error the workflow deliberately expects is not, a
declared-failure finding is a BUG regardless of the provenance of anything else in
the workflow, and the two tiers stay separable by typed fields alone. The last two
are the whole point -- if the cap ever reaches the top tier the layer has silently
become another inference, and if the tiers blur, the false-positive number this is
all for stops meaning anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from qabot.drivers.base import Observation
from qabot.drivers.http import NO_RESET_LIMITATION, HttpDriver
from qabot.intrinsics import (
    TRACEBACK_MARKERS,
    declares_failure,
    intrinsic_findings,
    server_error,
    server_traceback,
)
from qabot.llm import DeterministicLLM
from qabot.models import (
    Anchor,
    AnchorKind,
    Expectation,
    Finding,
    KnowledgeBase,
    Outcome,
    Provenance,
    Severity,
    Step,
    StepResult,
    Workflow,
)
from qabot.reporter import render_markdown
from qabot.runner import run
from qabot.verifier import verify_workflow

PYTHON_TRACEBACK = (
    'Traceback (most recent call last):\n  File "app.py", line 12, in checkout\n'
    "    total = price / qty\nZeroDivisionError: division by zero\n"
)


def observation(
    status: int | None = 200, text: str = "", summary: str | None = None
) -> Observation:
    evidence: dict[str, object] = {"text": text}
    if status is not None:
        evidence["status"] = status
    return Observation(
        ok=True,
        summary=summary if summary is not None else f"GET /widgets -> {status}",
        evidence=evidence,
    )


def workflow(*expectations: Expectation, steps: int = 2) -> Workflow:
    return Workflow(
        id="wf_widgets",
        name="Widgets",
        steps=[Step(intent=f"step {i}") for i in range(steps)],
        expectations=list(expectations),
    )


def status_expectation(value: int, step_index: int | None = 0) -> Expectation:
    return Expectation(
        id="e1",
        statement=f"the call answers {value}",
        provenance=Provenance.INFERRED_FROM_TEST,
        check={"kind": "status", "value": value},
        step_index=step_index,
    )


EVENT_CATEGORIES = ("page_errors", "console_errors", "failed_requests", "server_errors")


def browser_observation(summary: str = "goto /cart -> ok", **categories: object) -> Observation:
    """A browser Observation carrying the driver's drained event bundle."""
    events: dict[str, object] = {category: [] for category in EVENT_CATEGORIES}
    events |= {"suppressed": 0, "truncated": {}, "capture_errors": 0}
    events |= categories
    return Observation(
        ok=True,
        summary=summary,
        evidence={"url": "http://app/cart", "text": "", "browser_events": events},
    )


def logged(text: str, line: int | None = 12) -> dict:
    return {"text": text, "url": "http://app/bundle.js", "line": line}


# --- server_error: the app's own failure signal, and nothing else ------------------


@pytest.mark.parametrize("status", [500, 502, 503, 599])
def test_server_error_fires_on_5xx(status: int) -> None:
    assert server_error(observation(status=status)) is not None


@pytest.mark.parametrize("status", [200, 201, 204, 302, 304])
def test_server_error_silent_on_success_and_redirects(status: int) -> None:
    assert server_error(observation(status=status)) is None


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_4xx_is_not_an_oracle(status: int) -> None:
    """A 401 unauthenticated and a 404 for a resource that never existed are the app
    behaving correctly. Firing on them would wreck the precision this layer sells."""
    assert server_error(observation(status=status)) is None
    assert intrinsic_findings(workflow(), {0: observation(status=status)}) == []


def test_server_error_silent_without_a_recorded_status() -> None:
    """No status is not evidence of anything, in either direction."""
    assert server_error(observation(status=None)) is None


def test_server_error_detail_names_the_call_and_the_status() -> None:
    detail = server_error(observation(status=500, summary="POST /checkout -> 500"))
    assert detail == "POST /checkout -> 500 (status 500)"


# --- server_traceback: the 200 that carries a stack trace --------------------------


def test_traceback_fires_on_a_200() -> None:
    """The case status alone cannot see: the app broke and rendered an error page."""
    detail = server_traceback(observation(status=200, text=PYTHON_TRACEBACK))
    assert detail is not None
    assert "Traceback (most recent call last)" in detail


@pytest.mark.parametrize("marker", TRACEBACK_MARKERS)
def test_every_marker_is_detected(marker: str) -> None:
    assert server_traceback(observation(text=f"<html>{marker} ...</html>")) is not None


def test_traceback_silent_on_an_ordinary_body() -> None:
    assert server_traceback(observation(text='{"items": [], "total": 0}')) is None


def test_traceback_silent_without_a_body() -> None:
    assert server_traceback(observation(text="")) is None
    assert server_traceback(Observation(ok=True, summary="clicked", evidence={})) is None


def test_traceback_fires_regardless_of_status() -> None:
    findings = intrinsic_findings(workflow(), {0: observation(status=200, text=PYTHON_TRACEBACK)})
    assert [f.oracle for f in findings] == ["server_traceback"]
    assert findings[0].severity is Severity.BUG


def test_both_oracles_fire_on_one_response() -> None:
    """Two separate defects on one response: the request failed, and the failure was
    rendered into a body the user can read."""
    findings = intrinsic_findings(workflow(), {0: observation(status=500, text=PYTHON_TRACEBACK)})
    assert [f.oracle for f in findings] == ["server_error", "server_traceback"]


# --- the shape of an intrinsic finding ---------------------------------------------


def test_intrinsic_finding_carries_no_provenance() -> None:
    finding = intrinsic_findings(workflow(), {0: observation(status=500)})[0]
    assert finding.provenance is None
    assert finding.oracle == "server_error"
    assert finding.severity is Severity.BUG
    assert finding.outcome is Outcome.FAIL
    assert finding.workflow_id == "wf_widgets"
    assert finding.repro == ["step 0", "step 1"]
    assert finding.evidence["status"] == 500


def test_findings_come_out_in_step_order() -> None:
    observations = {1: observation(status=503), 0: observation(status=500)}
    details = [f.detail for f in intrinsic_findings(workflow(), observations)]
    assert details == ["GET /widgets -> 500 (status 500)", "GET /widgets -> 503 (status 503)"]


def test_no_observations_no_findings() -> None:
    assert intrinsic_findings(workflow(), {}) == []


# --- the suppression guard ----------------------------------------------------------


def test_expected_server_error_is_not_a_finding() -> None:
    """The app answering 503 where the knowledge base says 503 is behaving as
    specified, and calling that a bug is the false positive this layer cannot afford."""
    wf = workflow(status_expectation(503, step_index=0))
    assert intrinsic_findings(wf, {0: observation(status=503)}) == []


def test_suppression_covers_the_trace_from_the_expected_error() -> None:
    wf = workflow(status_expectation(500, step_index=0))
    assert intrinsic_findings(wf, {0: observation(status=500, text=PYTHON_TRACEBACK)}) == []


def test_suppression_is_per_step() -> None:
    """An expectation about step 0 says nothing about what step 1 was allowed to do."""
    wf = workflow(status_expectation(500, step_index=0))
    findings = intrinsic_findings(wf, {0: observation(status=500), 1: observation(status=500)})
    assert [f.detail for f in findings] == ["GET /widgets -> 500 (status 500)"]


def test_unbound_expectation_suppresses_at_the_final_observation() -> None:
    """Binding mirrors the verifier: an expectation naming no step is graded against
    the last observation, so that is the only one it may suppress."""
    wf = workflow(status_expectation(500, step_index=None))
    findings = intrinsic_findings(wf, {0: observation(status=500), 1: observation(status=500)})
    assert len(findings) == 1
    assert findings[0].evidence["status"] == 500
    assert intrinsic_findings(wf, {1: observation(status=500)}) == []


def test_a_non_error_expectation_does_not_suppress() -> None:
    wf = workflow(status_expectation(200, step_index=0))
    assert len(intrinsic_findings(wf, {0: observation(status=500)})) == 1


def test_a_prose_expectation_does_not_suppress() -> None:
    """Only a machine-checkable 5xx assertion counts. Prose might mean anything, and
    the guard may not suppress the app's own error signal on a guess about intent."""
    wf = workflow(
        Expectation(
            id="e1",
            statement="the server should fail here",
            provenance=Provenance.HUMAN_CONFIRMED,
            step_index=0,
        )
    )
    assert len(intrinsic_findings(wf, {0: observation(status=500)})) == 1


# --- browser events: which tier each signal earns ----------------------------------


def test_uncaught_js_error_is_a_declared_failure() -> None:
    """The JavaScript runtime reported its own failure. Nothing was read into it."""
    obs = browser_observation(page_errors=[logged("TypeError: cart is undefined")])
    finding = intrinsic_findings(workflow(), {0: obs})[0]

    assert finding.oracle == "browser_page_error"
    assert finding.severity is Severity.BUG
    assert declares_failure(finding) is True
    assert "TypeError: cart is undefined" in finding.detail
    assert "[http://app/bundle.js:12]" in finding.detail


def test_browser_side_5xx_is_a_declared_failure() -> None:
    obs = browser_observation(
        server_errors=[{"url": "http://app/api/cart", "method": "POST", "status": 502}]
    )
    finding = intrinsic_findings(workflow(), {0: obs})[0]

    assert finding.oracle == "browser_server_error"
    assert declares_failure(finding) is True
    assert "POST http://app/api/cart -> 502" in finding.detail


def test_console_error_is_noticed_not_declared() -> None:
    """An app-authored log line. Calling it a defect would be a reading, and a reading
    is exactly what the uncapped tier is not allowed to contain."""
    obs = browser_observation(console_errors=[logged("failed to load optional widget")])
    finding = intrinsic_findings(workflow(), {0: obs})[0]

    assert finding.oracle == "browser_console_error"
    assert finding.severity is Severity.QUESTION
    assert declares_failure(finding) is False
    assert finding.provenance is None


def test_failed_request_is_noticed_not_declared() -> None:
    obs = browser_observation(
        failed_requests=[
            {"url": "http://app/api/poll", "method": "GET", "failure": "net::ERR_ABORTED"}
        ]
    )
    finding = intrinsic_findings(workflow(), {0: obs})[0]

    assert finding.oracle == "browser_failed_request"
    assert finding.severity is Severity.QUESTION
    assert "GET http://app/api/poll -- net::ERR_ABORTED" in finding.detail


def test_a_clean_bundle_produces_nothing() -> None:
    assert intrinsic_findings(workflow(), {0: browser_observation()}) == []


def test_an_http_observation_has_no_browser_findings() -> None:
    """The oracles run over every observation the run produced, whatever drove it."""
    findings = intrinsic_findings(workflow(), {0: observation(status=200)})
    assert findings == []


def test_a_malformed_bundle_does_not_take_down_the_valid_events() -> None:
    """This reads a structure another driver produced. One bad entry must not cost us
    the twenty good ones beside it."""
    obs = browser_observation(page_errors=["not an event", logged("TypeError: real")])
    details = [f.detail for f in intrinsic_findings(workflow(), {0: obs})]
    assert len(details) == 1
    assert "TypeError: real" in details[0]


# --- browser events: forty copies of one defect are one finding --------------------


def test_repeats_within_one_step_aggregate_with_a_count() -> None:
    """The requirement that keeps a chatty page from destroying the report."""
    obs = browser_observation(console_errors=[logged("render loop warning")] * 40)
    findings = intrinsic_findings(workflow(), {0: obs})

    assert len(findings) == 1
    assert "40 occurrences, first during: step 0" in findings[0].detail


def test_repeats_across_steps_aggregate_too() -> None:
    """A page that logs the same error on every step has one problem, not one per step."""
    findings = intrinsic_findings(
        workflow(),
        {
            0: browser_observation(console_errors=[logged("render loop warning")]),
            1: browser_observation(console_errors=[logged("render loop warning")] * 2),
        },
    )

    assert len(findings) == 1
    assert "3 occurrences, first during: step 0" in findings[0].detail


def test_distinct_messages_stay_distinct() -> None:
    obs = browser_observation(console_errors=[logged("first problem"), logged("second problem")])
    details = [f.detail for f in intrinsic_findings(workflow(), {0: obs})]

    assert len(details) == 2
    assert "first problem" in details[0]
    assert "second problem" in details[1]
    assert "occurrences" not in details[0]


def test_one_message_from_two_call_sites_names_both() -> None:
    """Found on the first real browser run: the same TypeError thrown from two lines.
    Aggregating by message keeps it one finding; naming only the first place would send
    a developer to fix one of them and believe they were done."""
    obs = browser_observation(
        page_errors=[logged("TypeError: boom", line=19), logged("TypeError: boom", line=25)]
    )
    detail = intrinsic_findings(workflow(), {0: obs})[0].detail

    assert "2 occurrences" in detail
    assert "bundle.js:19" in detail
    assert "bundle.js:25" in detail


def test_a_message_from_many_places_lists_a_few_and_counts_the_rest() -> None:
    obs = browser_observation(console_errors=[logged("everywhere", line=n) for n in range(1, 8)])
    detail = intrinsic_findings(workflow(), {0: obs})[0].detail

    assert "7 occurrences" in detail
    assert "and 4 more]" in detail


def test_a_single_occurrence_reads_as_one() -> None:
    obs = browser_observation(console_errors=[logged("one off")])
    assert "(during: step 0)" in intrinsic_findings(workflow(), {0: obs})[0].detail


def test_truncation_is_reported_as_a_floor() -> None:
    """The driver caps what it keeps. A count presented as exact would be a lie about
    a number this report exists to make honest."""
    obs = browser_observation(
        console_errors=[logged("noisy")] * 20, truncated={"console_errors": 57}
    )
    detail = intrinsic_findings(workflow(), {0: obs})[0].detail

    assert "20 occurrences" in detail
    assert "the browser recorded 57 of these" in detail
    assert "this count is a floor" in detail


def test_suppressed_events_stay_out_of_the_detail_but_not_out_of_the_evidence() -> None:
    """A suppressed event came from another origin by the driver's own rule, so
    attributing it to a finding about this app would misattribute it."""
    obs = browser_observation(console_errors=[logged("ours")], suppressed=9)
    finding = intrinsic_findings(workflow(), {0: obs})[0]

    assert "suppressed" not in finding.detail
    assert "9" not in finding.detail
    assert finding.evidence["browser_events"]["suppressed"] == 9  # type: ignore[index]


def test_an_expected_server_error_silences_the_browser_record_of_it_too() -> None:
    """One expected error seen from another angle is not a second defect."""
    wf = workflow(status_expectation(503, step_index=0))
    obs = browser_observation(
        server_errors=[{"url": "http://app/admin", "method": "GET", "status": 503}],
        console_errors=[logged("maintenance")],
    )
    assert intrinsic_findings(wf, {0: obs}) == []


def test_findings_are_grouped_by_oracle_in_declaration_order() -> None:
    """Report order is oracle order, so a reader meets the declared failures first."""
    obs = browser_observation(
        page_errors=[logged("TypeError: boom")],
        console_errors=[logged("a log line")],
        failed_requests=[{"url": "http://app/x", "method": "GET", "failure": "aborted"}],
        server_errors=[{"url": "http://app/y", "method": "GET", "status": 500}],
    )
    oracles = [f.oracle for f in intrinsic_findings(workflow(), {0: obs})]

    assert oracles == [
        "browser_page_error",
        "browser_server_error",
        "browser_console_error",
        "browser_failed_request",
    ]


# --- the tier split ----------------------------------------------------------------


def test_declares_failure_reads_typed_fields_only() -> None:
    """Requirement from the eval side: the tiers must partition on `oracle` plus
    severity, never on prose, or the published number moves when someone rewords a
    sentence."""
    declared = intrinsic_findings(
        workflow(), {0: browser_observation(page_errors=[logged("boom")])}
    )[0]
    noticed = intrinsic_findings(
        workflow(), {0: browser_observation(console_errors=[logged("logged")])}
    )[0]

    assert declares_failure(declared) is True
    assert declares_failure(noticed) is False
    assert declared.oracle is not None and noticed.oracle is not None
    assert (declared.severity, noticed.severity) == (Severity.BUG, Severity.QUESTION)


def test_a_graded_finding_is_never_in_either_intrinsic_tier() -> None:
    wf = workflow(status_expectation(200, step_index=0))
    result = verify_workflow(
        wf, [StepResult(intent="step 0", outcome=Outcome.PASS)], {0: observation(status=404)}
    )
    graded = result.findings[0]

    assert graded.oracle is None
    assert declares_failure(graded) is False


# --- through verify_workflow: not capped, not lost to a BLOCKED workflow -----------


def intrinsic(result_findings: list[Finding]) -> list[Finding]:
    return [f for f in result_findings if f.oracle is not None]


def test_intrinsic_finding_is_not_provenance_capped() -> None:
    """Both findings come out of one workflow. The violated expectation was inferred
    from code, so it is capped at QUESTION however wrong it looks; the crash at the
    step before it is a BUG, because no cap applies to a finding no inference made."""
    wf = workflow(
        Expectation(
            id="e1",
            statement="the widget is fetched",
            provenance=Provenance.INFERRED_FROM_CODE,
            check={"kind": "status", "value": 200},
            step_index=1,
        )
    )
    result = verify_workflow(
        wf,
        [StepResult(intent="step 0", outcome=Outcome.PASS)],
        {0: observation(status=500), 1: observation(status=404)},
    )

    graded = [(f.provenance, f.severity) for f in result.findings if f.oracle is None]
    assert graded == [(Provenance.INFERRED_FROM_CODE, Severity.QUESTION)]
    assert [(f.oracle, f.severity) for f in intrinsic(result.findings)] == [
        ("server_error", Severity.BUG)
    ]


def test_an_app_declared_error_fails_the_workflow() -> None:
    result = verify_workflow(
        workflow(),
        [StepResult(intent="step 0", outcome=Outcome.PASS)],
        {0: observation(status=500)},
    )
    assert result.outcome is Outcome.FAIL


def test_observations_from_a_blocked_workflow_are_still_checked() -> None:
    """The 500 at step 0 is usually *why* step 1 could not run. Reporting only
    "could not test" would bury the most actionable thing the run found."""
    result = verify_workflow(
        workflow(),
        [
            StepResult(intent="step 0", outcome=Outcome.PASS),
            StepResult(intent="step 1", outcome=Outcome.BLOCKED, detail="cannot capture 'id'"),
        ],
        {0: observation(status=500)},
    )
    assert [f.oracle for f in intrinsic(result.findings)] == ["server_error"]


def test_a_clean_workflow_gains_nothing() -> None:
    result = verify_workflow(
        workflow(),
        [StepResult(intent="step 0", outcome=Outcome.PASS)],
        {0: observation(status=200)},
    )
    assert result.findings == []
    assert result.outcome is Outcome.PASS


def test_a_noticed_finding_does_not_fail_the_workflow() -> None:
    """We said we could not call it a defect. It must not act like one behind the
    reader's back -- a FAIL here would also stop testgen promoting what did pass."""
    result = verify_workflow(
        workflow(),
        [StepResult(intent="step 0", outcome=Outcome.PASS)],
        {0: browser_observation(console_errors=[logged("noisy but maybe fine")])},
    )

    assert [f.severity for f in result.findings] == [Severity.QUESTION]
    assert result.outcome is Outcome.PASS


def test_a_declared_failure_does_fail_the_workflow() -> None:
    result = verify_workflow(
        workflow(),
        [StepResult(intent="step 0", outcome=Outcome.PASS)],
        {0: browser_observation(page_errors=[logged("TypeError: boom")])},
    )
    assert result.outcome is Outcome.FAIL


# --- through the runner: a foreign app, no /reset, no knowledge base ----------------


def foreign_app() -> FastAPI:
    """An app of the kind this layer exists for: no /reset, and two ways of failing."""
    app = FastAPI()

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    @app.get("/trace")
    def trace() -> PlainTextResponse:
        return PlainTextResponse(PYTHON_TRACEBACK, status_code=200)

    return app


def foreign_kb(tmp_path: Path) -> KnowledgeBase:
    (tmp_path / "app.py").write_text("def boom():\n    raise RuntimeError('kaboom')\n")
    return KnowledgeBase(
        repo="acme/foreign",
        workflows=[
            Workflow(
                id="wf_foreign",
                name="Foreign app",
                steps=[
                    Step(intent="fetch /boom", hint={"method": "GET", "path": "/boom"}),
                    Step(intent="fetch /trace", hint={"method": "GET", "path": "/trace"}),
                ],
                anchors=[Anchor(kind=AnchorKind.FILE, locator="app.py")],
            )
        ],
    )


FOREIGN_DIFF = (
    "diff --git a/app.py b/app.py\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def boom():\n"
    "+    # (pretend this PR changed it)\n"
    "     raise RuntimeError('kaboom')\n"
)


def test_a_run_against_an_app_with_no_reset(tmp_path: Path) -> None:
    """The whole point of this layer, end to end: an app with no /reset and no
    expectations about it still yields findings, and the missing reset is stated
    rather than swallowed."""
    client = TestClient(foreign_app(), base_url="http://test", raise_server_exceptions=False)
    driver = HttpDriver(base_url="http://test", client=client, reset_path=None)
    try:
        report = run(
            kb=foreign_kb(tmp_path),
            driver=driver,
            source_root=tmp_path,
            diff_text=FOREIGN_DIFF,
            llm=DeterministicLLM(),
        )
    finally:
        driver.close()
        client.close()

    assert [(f.oracle, f.severity) for f in report.findings] == [
        ("server_error", Severity.BUG),
        ("server_traceback", Severity.BUG),
    ]
    assert report.limitations == [NO_RESET_LIMITATION]

    markdown = render_markdown(report)
    assert "#### Errors the application reported about itself (2)" in markdown
    assert "- Oracle: `server_error`" in markdown
    assert "### Limitations of this run" in markdown
    assert "no reset endpoint" in markdown
