"""The command, against a real local app."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from demo.server import serve
from qabot.cli import main

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def small_app() -> Iterator[str]:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (
            "<html><body><h1>Shop</h1>"
            "<p>" + "words " * 40 + "</p>"
            '<a href="/broken">broken</a></body></html>'
        )

    @app.get("/broken", response_class=HTMLResponse)
    def broken() -> str:
        return "<html><body><script>null.x</script></body></html>"

    with serve(app) as url:
        yield url


def test_scan_writes_a_report_naming_the_broken_page(small_app: str, tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    code = main(["scan", small_app, "--out", str(out), "--delay", "0"])

    assert code == 0
    html = out.read_text()
    assert "/broken" in html
    assert "Broken" in html


def test_scan_reports_honestly_when_it_reached_almost_nothing(tmp_path: Path) -> None:
    """A one-page app must not produce a document that reads as 'all clear'."""
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<html><body><p>" + "words " * 40 + "</p></body></html>"

    from qabot.scan.report import NOTHING_CHECKED

    with serve(app) as url:
        out = tmp_path / "thin.html"
        main(["scan", url, "--out", str(out), "--delay", "0"])
        assert NOTHING_CHECKED in out.read_text()
