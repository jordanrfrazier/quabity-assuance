"""Tests for report rendering.

Most of these are really tests of one claim: that "I could not test this" survives
rendering as its own thing, and is never quietly rounded into a pass or a failure.
"""

from __future__ import annotations

from qabot.models import (
    Finding,
    OpenQuestion,
    Outcome,
    Provenance,
    RunReport,
    Severity,
    StepResult,
    WorkflowResult,
)
from qabot.reporter import exit_code, render_markdown, summary_line


def _finding(
    severity: Severity,
    *,
    workflow_id: str = "wf_checkout",
    workflow_name: str = "Checkout",
    outcome: Outcome = Outcome.FAIL,
    statement: str = "the thing holds",
    detail: str = "expected 402, got 500",
    provenance: Provenance | None = Provenance.HUMAN_CONFIRMED,
    oracle: str | None = None,
    repro: list[str] | None = None,
) -> Finding:
    return Finding(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        severity=severity,
        outcome=outcome,
        statement=statement,
        detail=detail,
        provenance=provenance,
        oracle=oracle,
        repro=repro if repro is not None else ["POST /cart", "POST /checkout"],
    )


def _result(
    outcome: Outcome,
    findings: list[Finding],
    *,
    workflow_id: str = "wf_checkout",
    workflow_name: str = "Checkout",
    steps: list[StepResult] | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        outcome=outcome,
        steps=steps or [],
        findings=findings,
    )


def _report(**kwargs: object) -> RunReport:
    base: dict[str, object] = {"repo": "acme/shop", "base_ref": "main", "head_ref": "pr-482"}
    base.update(kwargs)
    return RunReport(**base)  # type: ignore[arg-type]


def _section(markdown: str, heading: str) -> str:
    """The slice of the report under one `###` heading, exclusive of the next one."""
    lines = markdown.splitlines()
    start = lines.index(heading)
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if line.startswith("### "):
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def test_findings_grouped_by_severity_in_descending_order() -> None:
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [
                    _finding(Severity.QUESTION, provenance=Provenance.INFERRED_FROM_CODE),
                    _finding(Severity.CHANGE, provenance=Provenance.INFERRED_FROM_TEST),
                    _finding(Severity.REGRESSION, provenance=Provenance.OBSERVED_IN_RUN),
                    _finding(Severity.BUG),
                ],
            )
        ]
    )
    markdown = render_markdown(report)

    positions = [
        markdown.index("#### Bugs (1)"),
        markdown.index("#### Regressions (1)"),
        markdown.index("#### Changes (1)"),
        markdown.index("#### Questions (1)"),
    ]
    assert positions == sorted(positions)


def test_each_severity_is_explained_in_terms_of_provenance() -> None:
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [
                    _finding(Severity.BUG),
                    _finding(Severity.CHANGE, provenance=Provenance.INFERRED_FROM_TEST),
                ],
            )
        ]
    )
    markdown = render_markdown(report)

    assert "_BUG = a human confirmed this behavior; it is broken._" in markdown
    assert "did you mean to change it?" in markdown


def test_finding_renders_workflow_statement_detail_provenance_and_numbered_repro() -> None:
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [
                    _finding(
                        Severity.BUG,
                        statement="declined cards return 402",
                        detail="expected status 402, got 500",
                        repro=["POST /cart/items", "POST /checkout"],
                    )
                ],
            )
        ]
    )
    markdown = render_markdown(report)

    assert "**Checkout** (`wf_checkout`)" in markdown
    assert "> declined cards return 402" in markdown
    assert "- Detail: expected status 402, got 500" in markdown
    assert "`human_confirmed`" in markdown
    assert "  1. POST /cart/items" in markdown
    assert "  2. POST /checkout" in markdown


def _app_declared(**kwargs: object) -> Finding:
    """A finding from an intrinsic oracle: no expectation behind it, so no provenance."""
    fields: dict[str, object] = {
        "provenance": None,
        "oracle": "server_error",
        "statement": "the application returned a server error",
        "detail": "POST /checkout -> 500 (status 500)",
    }
    fields.update(kwargs)
    return _finding(Severity.BUG, **fields)  # type: ignore[arg-type]


def test_app_declared_findings_are_rendered_apart_from_graded_ones() -> None:
    """The load-bearing rendering test: a reader must see at a glance which findings
    rest on the app's own error and which rest on an expectation of ours. Grouping an
    uncapped finding under a heading that explains itself in terms of provenance
    would misdescribe the only findings in the report that cannot be a misreading."""
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [_finding(Severity.BUG, statement="declined cards return 402"), _app_declared()],
            )
        ]
    )
    markdown = render_markdown(report)
    findings = _section(markdown, "### Findings")

    assert "#### Errors the application reported about itself (1)" in findings
    assert "- Oracle: `server_error` -- the application reported this itself" in findings
    assert "no provenance cap" in findings

    # The graded group holds the expectation-derived bug and only that one.
    assert "#### Bugs (1)" in findings
    assert markdown.index("#### Errors the application") < markdown.index("#### Bugs (1)")
    assert "server_error" not in markdown[markdown.index("#### Bugs (1)") :]

    # Still a bug for counting purposes -- it is the most certain one in the report.
    assert summary_line(report).startswith("2 findings (2 bugs,")


def test_an_app_declared_finding_prints_no_provenance_line() -> None:
    report = _report(results=[_result(Outcome.FAIL, [_app_declared()])])
    markdown = render_markdown(report)
    assert "- Provenance:" not in markdown
    assert "- Detail: POST /checkout -> 500 (status 500)" in markdown


def _noticed(**kwargs: object) -> Finding:
    """A finding from the other intrinsic tier: the app logged it, we will not call it."""
    fields: dict[str, object] = {
        "provenance": None,
        "oracle": "browser_console_error",
        "statement": "the page logged an error to its console",
        "detail": "render loop warning (40 occurrences, first during: open the cart)",
    }
    fields.update(kwargs)
    return _finding(Severity.QUESTION, **fields)  # type: ignore[arg-type]


def test_the_two_intrinsic_tiers_render_apart_and_in_order_of_certainty() -> None:
    """The report reads loudest first: what the app declared opens it, what the app
    merely logged closes it, below even the graded questions. A reader must never meet
    a console error under a sentence promising it cannot be a misreading."""
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [
                    _app_declared(),
                    _noticed(),
                    _finding(Severity.QUESTION, provenance=Provenance.INFERRED_FROM_CODE),
                ],
            )
        ]
    )
    markdown = render_markdown(report)

    positions = [
        markdown.index("#### Errors the application reported about itself (1)"),
        markdown.index("#### Questions (1)"),
        markdown.index("#### Noticed, but not called a defect (1)"),
    ]
    assert positions == sorted(positions)

    declared_blurb = markdown.index("no provenance cap applies")
    assert declared_blurb < markdown.index("#### Noticed, but not called a defect (1)")
    assert "whether they are defects is a reading we will not make" in markdown
    assert "- Oracle: `browser_console_error` -- the application logged this itself" in markdown
    assert "render loop warning (40 occurrences" in markdown


def test_a_noticed_finding_is_not_counted_as_a_declared_one() -> None:
    report = _report(results=[_result(Outcome.FAIL, [_app_declared(), _noticed()])])
    assert summary_line(report).startswith(
        "2 findings (1 bug, 0 regressions, 0 changes, 1 question)"
    )


def test_a_noticed_finding_never_blocks_the_build() -> None:
    """QUESTION is the severity for "noticed, cannot call it", and the gate has never
    fired on one. That must stay true now that an oracle can produce them."""
    report = _report(results=[_result(Outcome.PASS, [_noticed()])])
    assert exit_code(report, blocking=True) == 0


def test_an_app_declared_error_can_block_the_build() -> None:
    """Uncapped means uncapped all the way to the gate."""
    report = _report(results=[_result(Outcome.FAIL, [_app_declared()])])
    assert exit_code(report, blocking=True) == 1


def test_run_limitations_are_surfaced() -> None:
    report = _report(limitations=["the app has no reset endpoint, so workflows ran in sequence"])
    section = _section(render_markdown(report), "### Limitations of this run")

    assert "- the app has no reset endpoint" in section
    assert "qualify every result above" in section


def test_no_limitations_no_section() -> None:
    assert "### Limitations of this run" not in render_markdown(_report())


def test_blocked_is_not_rendered_as_a_finding() -> None:
    """The load-bearing test: a BLOCKED expectation carrying BUG severity must not
    appear in the findings sections, must appear under "Could not test", and must
    not be counted as a bug anywhere."""
    blocked = _finding(
        Severity.BUG,
        outcome=Outcome.BLOCKED,
        statement="declined cards return 402",
        detail="payment sandbox unreachable",
    )
    report = _report(
        results=[
            _result(
                Outcome.BLOCKED,
                [blocked],
                steps=[
                    StepResult(
                        intent="submit payment",
                        outcome=Outcome.BLOCKED,
                        detail="no sandbox credentials in CI",
                    )
                ],
            )
        ]
    )
    markdown = render_markdown(report)

    findings_section = _section(markdown, "### Findings")
    blocked_section = _section(markdown, "### Could not test")

    assert "None. Every expectation that could be checked held." in findings_section
    assert "declined cards return 402" not in findings_section
    assert "declined cards return 402" in blocked_section
    assert "payment sandbox unreachable" in blocked_section
    assert "no sandbox credentials in CI" in blocked_section
    assert "0 bugs" in summary_line(report)
    assert "1 could not be tested" in summary_line(report)
    assert exit_code(report, blocking=True) == 0


def test_blocked_section_is_separate_from_a_real_failure_in_the_same_run() -> None:
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [_finding(Severity.BUG, statement="checkout succeeds")],
                workflow_id="wf_checkout",
                workflow_name="Checkout",
            ),
            _result(
                Outcome.BLOCKED,
                [],
                workflow_id="wf_refund",
                workflow_name="Refund",
                steps=[
                    StepResult(
                        intent="issue refund",
                        outcome=Outcome.BLOCKED,
                        detail="refund API needs a live merchant account",
                    )
                ],
            ),
        ]
    )
    markdown = render_markdown(report)

    findings_section = _section(markdown, "### Findings")
    blocked_section = _section(markdown, "### Could not test")

    assert "checkout succeeds" in findings_section
    assert "Refund" not in findings_section
    assert "Refund" in blocked_section
    assert "refund API needs a live merchant account" in blocked_section
    assert summary_line(report).startswith("1 finding (1 bug, 0 regressions,")
    assert "1 could not be tested" in summary_line(report)


def test_blocked_section_is_rendered_even_when_nothing_was_blocked() -> None:
    markdown = render_markdown(_report(results=[_result(Outcome.PASS, [])]))
    assert "### Could not test" in markdown
    assert "None. Every selected workflow was exercised." in markdown


def test_blocked_workflow_without_a_recorded_reason_says_so() -> None:
    report = _report(results=[_result(Outcome.BLOCKED, [])])
    assert "reason not recorded" in _section(render_markdown(report), "### Could not test")


def test_a_failing_workflow_still_reports_the_step_it_never_reached() -> None:
    """A workflow can both fail and be incomplete: an app that 500s usually drops the
    connection, and the steps after it never happen. The failure must not swallow the
    gap it caused."""
    report = _report(
        results=[
            _result(
                Outcome.FAIL,
                [_app_declared()],
                steps=[
                    StepResult(intent="submit payment", outcome=Outcome.PASS),
                    StepResult(
                        intent="read the receipt",
                        outcome=Outcome.BLOCKED,
                        detail="RemoteProtocolError: server disconnected",
                    ),
                ],
            )
        ]
    )
    section = _section(render_markdown(report), "### Could not test")

    assert "read the receipt" in section
    assert "server disconnected" in section
    assert "1 could not be tested" in summary_line(report)


def test_skipped_for_budget_is_surfaced() -> None:
    report = _report(skipped_for_budget=["wf_signup", "wf_search"])
    markdown = render_markdown(report)

    section = _section(markdown, "### Not tested (budget)")
    assert "- `wf_signup`" in section
    assert "- `wf_search`" in section
    assert "not a clean bill of health" in section
    assert "2 not tested (budget)" in summary_line(report)


def test_stale_workflows_are_surfaced_with_the_anchor_explanation() -> None:
    report = _report(stale_workflows=["wf_legacy_import"])
    section = _section(render_markdown(report), "### Stale knowledge")

    assert "- `wf_legacy_import`" in section
    assert "anchors no longer resolve" in section


def test_open_questions_render_question_and_candidates() -> None:
    report = _report(
        open_questions=[
            OpenQuestion(
                id="q1",
                question="Should an expired card return 402 or 400?",
                trigger="checkout returned 400 where the test implied 402",
                candidates=["402", "400"],
                blocking=True,
                workflow_id="wf_checkout",
            )
        ]
    )
    section = _section(render_markdown(report), "### Open questions")

    assert "Should an expired card return 402 or 400?" in section
    assert "**[blocking]**" in section
    assert "candidates: `402`, `400`" in section
    assert "workflow: `wf_checkout`" in section
    assert "checkout returned 400 where the test implied 402" in section


def test_a_run_that_exercised_nothing_says_so_instead_of_reading_as_a_pass() -> None:
    """A report with no findings reads as a clean bill of health. When nothing ran,
    that reading is false, and it is the one false reading that gets believed."""
    report = _report(
        results=[],
        skipped_for_budget=["wf_search"],
        stale_workflows=["wf_legacy"],
        open_questions=[OpenQuestion(id="q1", question="Is search still a workflow?", trigger="x")],
    )
    markdown = render_markdown(report)

    assert "This run verified nothing." in markdown
    assert "None. Every expectation that could be checked held." not in markdown
    assert "### Could not test" in markdown
    assert "### Not tested (budget)" in markdown
    assert "### Stale knowledge" in markdown
    assert "### Open questions" in markdown
    assert summary_line(report).startswith("0 findings (0 bugs, 0 regressions, 0 changes, 0 quest")


def test_report_header_names_the_repo_and_refs() -> None:
    markdown = render_markdown(_report())
    assert markdown.startswith("## qabot -- acme/shop")
    assert "`main` -> `pr-482`" in markdown


def test_exit_code_is_advisory_by_default() -> None:
    report = _report(results=[_result(Outcome.FAIL, [_finding(Severity.BUG)])])
    assert exit_code(report) == 0
    assert exit_code(report, blocking=False) == 0


def test_exit_code_blocks_on_bug_and_regression_only() -> None:
    for severity, expected in [
        (Severity.BUG, 1),
        (Severity.REGRESSION, 1),
        (Severity.CHANGE, 0),
        (Severity.QUESTION, 0),
    ]:
        report = _report(results=[_result(Outcome.FAIL, [_finding(severity)])])
        assert exit_code(report, blocking=True) == expected, severity


def test_exit_code_is_zero_for_a_clean_run_in_blocking_mode() -> None:
    report = _report(results=[_result(Outcome.PASS, [])], skipped_for_budget=["wf_search"])
    assert exit_code(report, blocking=True) == 0
