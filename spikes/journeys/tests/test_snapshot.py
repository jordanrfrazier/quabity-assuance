from collections.abc import Iterator

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright

from spikes.journeys.snapshot import SNAPSHOT_CAP, trimmed_snapshot, visible_text

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


def test_snapshot_lists_controls_by_role_and_name(page):
    page.set_content(
        "<h1>Shop</h1><button>Add to cart</button><a href='/x'>Orders</a>"
        "<label>Product <select><option>widget</option></select></label>"
    )
    snap = trimmed_snapshot(page)
    assert 'button "Add to cart"' in snap
    assert 'link "Orders"' in snap
    assert "combobox" in snap
    assert "[snapshot truncated" not in snap


def test_snapshot_keeps_interactive_lines_when_capped(page):
    filler = "".join(f"<p>paragraph number {i} with some words in it</p>" for i in range(400))
    page.set_content(f"{filler}<button>Run</button>")
    snap = trimmed_snapshot(page, cap=600)
    assert 'button "Run"' in snap
    assert len(snap) <= 600 + 80
    assert "[snapshot truncated" in snap


def test_visible_text_is_body_inner_text(page):
    page.set_content("<p>Something went wrong</p><script>var x=1</script>")
    assert visible_text(page).strip() == "Something went wrong"


def test_cap_constant():
    assert SNAPSHOT_CAP == 12_000
