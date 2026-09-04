"""The report is a pure function of the run, so it is testable without a browser."""

from __future__ import annotations

from qabot.drivers.base import Observation
from qabot.intrinsics import intrinsic_findings
from qabot.models import Finding, Step, Workflow
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


#: One Observation per oracle these tests exercise, shaped exactly as the signal that
#: oracle actually reads -- a 5xx status for `server_error`, a console-error event for
#: `browser_console_error` -- so `intrinsic_findings` is what produces the Finding,
#: not the test fabricating one by hand.
_OBSERVATIONS: dict[str, Observation] = {
    "server_error": Observation(ok=True, summary="GET /a", evidence={"status": 500}),
    "browser_console_error": Observation(
        ok=True,
        summary="read",
        evidence={"browser_events": {"console_errors": [{"text": "boom"}]}},
    ),
}


def _finding(oracle: str, path: str = "/a") -> Finding:
    """A Finding built the way `sweep` actually builds one: one `Workflow` per page,
    run through `intrinsic_findings`. C2 found that this pipeline can only ever stamp
    `workflow_name=f"open {path}"` -- a value the previous version of this test
    fabricated directly via a `name=` keyword, which is exactly why the tests here
    never noticed the pipeline could not produce the shape they were asserting on.
    """
    workflow = Workflow(id=f"scan:{path}", name=f"open {path}", steps=[Step(intent=f"open {path}")])
    findings = intrinsic_findings(workflow, {0: _OBSERVATIONS[oracle]})
    assert len(findings) == 1, f"expected exactly one finding for oracle {oracle!r}: {findings}"
    return findings[0]


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


def test_headline_never_calls_a_glitch_a_broken_page() -> None:
    """BROKEN and GLITCHY are different claims. The headline must not blur them."""
    one_glitchy = _result(findings=[_finding("browser_console_error")])
    assert headline(one_glitchy) == "1 page has problems"
    assert "broken" not in headline(one_glitchy)


def test_headline_pluralizes_the_glitchy_count() -> None:
    two_glitchy = _result(
        findings=[
            _finding("browser_console_error", path="/a"),
            _finding("browser_console_error", path="/b"),
        ]
    )
    assert headline(two_glitchy) == "2 pages have problems"


def test_headline_prefers_broken_over_glitchy_when_both_are_present() -> None:
    mixed = _result(
        findings=[_finding("server_error", path="/a"), _finding("browser_console_error")]
    )
    assert headline(mixed) == "1 page is broken"
