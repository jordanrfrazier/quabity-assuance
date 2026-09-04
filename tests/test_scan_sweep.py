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

from qabot.drivers.browser import BrowserDriver
from qabot.scan.sweep import Budget, ScanResult, sweep

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
