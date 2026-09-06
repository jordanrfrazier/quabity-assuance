"""Visitor impact, derived from the oracle that produced a finding."""

from __future__ import annotations

import pytest

from qabot.drivers.base import Observation
from qabot.models import Finding, Outcome, Severity
from qabot.scan.grading import (
    BLANK_PAGE_TEXT_LIMIT,
    Impact,
    blank_page,
    impact_of,
)


def _finding(oracle: str, severity: Severity = Severity.BUG) -> Finding:
    return Finding(
        workflow_id="scan",
        workflow_name="scan",
        severity=severity,
        outcome=Outcome.FAIL,
        statement="x",
        oracle=oracle,
    )


@pytest.mark.parametrize(
    ("oracle", "expected"),
    [
        ("server_error", Impact.BROKEN),
        ("browser_server_error", Impact.BROKEN),
        ("blank_page", Impact.BROKEN),
        ("browser_page_error", Impact.GLITCHY),
        ("browser_console_error", Impact.GLITCHY),
        ("browser_failed_request", Impact.GLITCHY),
        ("server_traceback", Impact.BROKEN),
    ],
)
def test_each_oracle_maps_to_a_visitor_impact(oracle: str, expected: Impact) -> None:
    assert impact_of(_finding(oracle)) == expected


def test_an_unknown_oracle_is_noted_rather_than_guessed_upward() -> None:
    """A new oracle must not silently inherit BROKEN. Under-claiming is recoverable."""
    assert impact_of(_finding("some_oracle_added_later")) == Impact.NOTED


def test_a_finding_with_no_oracle_is_noted() -> None:
    assert impact_of(_finding("x").model_copy(update={"oracle": None})) == Impact.NOTED


def _observation(text: str, page_errors: int) -> Observation:
    return Observation(
        ok=True,
        summary="goto /",
        evidence={
            "text": text,
            "browser_events": {
                "page_errors": [{"text": "boom", "url": None, "line": None}] * page_errors,
                "console_errors": [],
                "failed_requests": [],
                "server_errors": [],
                "suppressed": 0,
                "truncated": {},
                "capture_errors": 0,
            },
        },
    )


def test_blank_page_fires_on_the_full_conjunction() -> None:
    """OK, crashed, and rendered nothing: broken by any definition."""
    detail = blank_page(_observation("", page_errors=1), status=200)
    assert detail is not None
    assert "blank" in detail.lower()


def test_blank_page_does_not_fire_when_the_page_rendered() -> None:
    assert blank_page(_observation("x" * 400, page_errors=1), status=200) is None


def test_blank_page_does_not_fire_without_a_crash() -> None:
    """An empty page that did not throw may simply be an empty page."""
    assert blank_page(_observation("", page_errors=0), status=200) is None


def test_blank_page_does_not_fire_on_a_non_2xx_document() -> None:
    """A 500 is already reported as broken; blank_page must not double-count it."""
    assert blank_page(_observation("", page_errors=1), status=500) is None


def test_blank_page_threshold_is_a_named_constant() -> None:
    assert blank_page(_observation("x" * (BLANK_PAGE_TEXT_LIMIT - 1), 1), 200) is not None
    assert blank_page(_observation("x" * (BLANK_PAGE_TEXT_LIMIT + 1), 1), 200) is None
