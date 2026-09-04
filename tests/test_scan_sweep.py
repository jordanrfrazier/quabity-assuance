"""Sweep against a real browser and a deliberately broken app."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from demo.server import serve
from qabot.scan.discovery import Discovery

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, sync_playwright

from qabot.drivers.base import Action, Observation
from qabot.drivers.browser import BrowserDriver
from qabot.scan.sweep import (
    MAX_CLICKS_PER_PAGE,
    Budget,
    ScanResult,
    _click_safely,
    _merge_events,
    _safe_to_click,
    sweep,
)

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def broken_app() -> Iterator[str]:
    """Four pages, each broken in exactly one way we claim to detect."""
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return '<html><body><h1>Home</h1><a href="/blank">blank</a></body></html>'

    @app.get("/blank", response_class=HTMLResponse)
    def blank() -> str:
        return "<html><body><script>null.x</script></body></html>"

    @app.get("/xhr", response_class=HTMLResponse)
    def xhr() -> str:
        return (
            "<html><body><p>" + "padding " * 40 + "</p>"
            "<script>fetch('/api/boom')</script></body></html>"
        )

    @app.get("/api/boom")
    def boom() -> JSONResponse:
        return JSONResponse({"detail": "no"}, status_code=500)

    @app.get("/tabs", response_class=HTMLResponse)
    def tabs() -> str:
        return (
            "<html><body><p>" + "padding " * 40 + "</p>"
            "<button id='t'>Show details</button>"
            "<script>document.getElementById('t')"
            ".addEventListener('click', () => { undefinedFunction(); })</script>"
            "</body></html>"
        )

    @app.get("/formguard", response_class=HTMLResponse)
    def formguard() -> str:
        """A safely-named control inside a <form>, and an identical one outside it."""
        return (
            "<html><body>"
            "<form><button>Reveal A</button></form>"
            "<button>Reveal B</button>"
            "</body></html>"
        )

    @app.get("/manybuttons", response_class=HTMLResponse)
    def manybuttons() -> str:
        """More safe, uniquely-named controls than the per-page click cap allows."""
        buttons = "".join(f"<button>Item {i}</button>" for i in range(MAX_CLICKS_PER_PAGE + 2))
        return f"<html><body>{buttons}</body></html>"

    @app.get("/titlechange", response_class=HTMLResponse)
    def titlechange() -> str:
        """A title set only after a click -- the pre-click title is stale evidence."""
        return (
            "<html><body><button id='t'>Reveal</button>"
            "<script>document.getElementById('t')"
            ".addEventListener('click', () => { document.title = 'Revealed'; });</script>"
            "</body></html>"
        )

    with serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def browser_page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def _sweep(url: str, page: Page, paths: list[str]) -> ScanResult:
    import httpx

    driver = BrowserDriver(base_url=url, page=page, reset_path=None, timeout_ms=15000)
    client = httpx.Client(base_url=url, timeout=10.0)

    def status_of(path: str) -> int | None:
        try:
            return client.get(path).status_code
        except httpx.HTTPError:
            return None

    discovery = Discovery(origin=url, paths=paths, counts={"root": 1})
    result = sweep(discovery, driver, status_of, Budget(max_pages=10, delay_s=0.0))
    client.close()
    return result


def test_a_page_that_crashes_and_renders_nothing_is_reported_blank(
    broken_app: str, browser_page: Page
) -> None:
    result = _sweep(broken_app, browser_page, ["/blank"])
    assert any(f.oracle == "blank_page" for f in result.findings)


def test_a_failing_background_request_is_reported(broken_app: str, browser_page: Page) -> None:
    """A 200 page whose XHR 500s is not a healthy page."""
    result = _sweep(broken_app, browser_page, ["/xhr"])
    assert any(f.oracle == "browser_server_error" for f in result.findings)


def test_safe_clicks_surface_errors_a_load_alone_would_miss(
    broken_app: str, browser_page: Page
) -> None:
    """The whole argument for interacting: this error only exists after a click."""
    result = _sweep(broken_app, browser_page, ["/tabs"])
    assert any(f.oracle == "browser_page_error" for f in result.findings)
    assert "Show details" in result.pages[0].clicked


def test_the_budget_is_reported_rather_than_silently_truncating(
    broken_app: str, browser_page: Page
) -> None:
    """A truncated run that looks like a complete one is the failure to avoid."""
    import httpx

    driver = BrowserDriver(base_url=broken_app, page=browser_page, reset_path=None)
    client = httpx.Client(base_url=broken_app, timeout=10.0)
    discovery = Discovery(origin=broken_app, paths=["/", "/xhr", "/tabs"], counts={"root": 1})
    result = sweep(
        discovery, driver, lambda p: client.get(p).status_code, Budget(max_pages=1, delay_s=0.0)
    )
    client.close()

    assert len(result.pages) == 1
    assert result.not_visited == ["/tabs", "/xhr"]


def test_the_no_reset_limitation_is_carried_onto_the_result(
    broken_app: str, browser_page: Page
) -> None:
    result = _sweep(broken_app, browser_page, ["/"])
    assert any("reset" in limitation for limitation in result.limitations)


@pytest.mark.parametrize(
    "name",
    [
        "Submit",
        "Save changes",
        "Confirm",
        "Sign in",
        "Send message",
        "Post comment",
        "Pay now",
        "Add to cart",
        "Update profile",
        "Log out",
        "log-out",
        "LogOut",
    ],
)
def test_unsafe_click_words_refuse_common_mutating_and_account_actions(name: str) -> None:
    """Finding A: the vocabulary reused from discovery permitted every one of these."""
    assert _safe_to_click(name) is False


def test_a_control_inside_a_form_is_skipped_but_an_identical_one_outside_is_clicked(
    broken_app: str, browser_page: Page
) -> None:
    """Finding A: the structural guard is what actually enforces "no form submission"."""
    driver = BrowserDriver(
        base_url=broken_app, page=browser_page, reset_path=None, timeout_ms=15000
    )
    driver.execute(Action(kind="browser", params={"op": "goto", "path": "/formguard"}))
    clicked, _ = _click_safely(driver, browser_page)
    assert "Reveal A" not in clicked
    assert "Reveal B" in clicked


def test_merge_events_sums_truncated_counts_per_key_instead_of_dropping_them() -> None:
    """Finding B: a click's truncation count was silently lost by the catch-all branch."""
    first = Observation(
        ok=True, summary="goto", evidence={"browser_events": {"suppressed": 1, "truncated": {}}}
    )
    second = Observation(
        ok=True,
        summary="click",
        evidence={"browser_events": {"suppressed": 2, "truncated": {"console_errors": 57}}},
    )
    merged = _merge_events(first, second)
    assert merged.evidence["browser_events"]["suppressed"] == 3
    assert merged.evidence["browser_events"]["truncated"] == {"console_errors": 57}


def test_a_title_set_after_a_click_is_the_title_reported(
    broken_app: str, browser_page: Page
) -> None:
    """Finding C: title/final_url/screenshot were always the stale pre-click snapshot."""
    result = _sweep(broken_app, browser_page, ["/titlechange"])
    assert "Reveal" in result.pages[0].clicked
    assert result.pages[0].title == "Revealed"


def test_the_click_cap_is_enforced_and_returns_both_names_and_observations(
    broken_app: str, browser_page: Page
) -> None:
    """Finding D: the early-return on the click cap must not regress to a bare list."""
    driver = BrowserDriver(
        base_url=broken_app, page=browser_page, reset_path=None, timeout_ms=15000
    )
    driver.execute(Action(kind="browser", params={"op": "goto", "path": "/manybuttons"}))
    clicked, observations = _click_safely(driver, browser_page)
    assert len(clicked) == MAX_CLICKS_PER_PAGE
    assert len(observations) == MAX_CLICKS_PER_PAGE
