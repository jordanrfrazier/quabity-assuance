"""The report is a pure function of the run, so it is testable without a browser."""

from __future__ import annotations

from qabot.models import Finding, Outcome, Severity
from qabot.scan.discovery import Discovery
from qabot.scan.report import NOTHING_CHECKED, headline, render_html
from qabot.scan.sweep import PageResult, ScanResult


def _result(**overrides) -> ScanResult:
    base = {
        "origin": "https://app.test",
        "discovery": Discovery(
            origin="https://app.test", paths=["/", "/a"], counts={"root": 1, "bundle": 1}
        ),
        "pages": [PageResult(path="/", status=200), PageResult(path="/a", status=200)],
        "findings": [],
        "limitations": [],
        "not_visited": [],
    }
    return ScanResult(**{**base, **overrides})


def _finding(oracle: str) -> Finding:
    return Finding(
        workflow_id="scan",
        workflow_name="open /a",
        severity=Severity.BUG,
        outcome=Outcome.FAIL,
        statement="the page returned a server error",
        detail="GET /a -> 500",
        oracle=oracle,
    )


def test_a_scan_that_reached_one_page_never_reads_as_a_clean_bill_of_health() -> None:
    """The founding rule of this codebase, at the new product's front door."""
    thin = _result(
        discovery=Discovery(origin="https://app.test", paths=["/"], counts={"root": 1}),
        pages=[PageResult(path="/", status=200)],
    )
    html = render_html(thin)
    assert NOTHING_CHECKED in html


def test_a_real_scan_with_no_findings_says_so_positively() -> None:
    html = render_html(_result())
    assert NOTHING_CHECKED not in html
    assert "No problems" in html


def test_findings_are_grouped_by_visitor_impact() -> None:
    html = render_html(
        _result(findings=[_finding("server_error"), _finding("browser_console_error")])
    )
    assert html.index("Broken") < html.index("Glitchy")


def test_what_could_not_be_checked_is_always_stated() -> None:
    """Under an anonymous scan there is a lot we cannot see. Omitting it is the lie."""
    html = render_html(_result(not_visited=["/deep"], limitations=["no reset endpoint"]))
    assert "could not check" in html.lower()
    assert "/deep" in html
    assert "no reset endpoint" in html


def test_the_report_is_self_contained() -> None:
    """It gets emailed and dropped into folders. External assets would not survive."""
    html = render_html(_result(findings=[_finding("server_error")]))
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html


def test_headline_counts_broken_pages_in_plain_language() -> None:
    assert headline(_result(findings=[_finding("server_error")])) == "1 page is broken"
    assert headline(_result()) == "No problems found"
