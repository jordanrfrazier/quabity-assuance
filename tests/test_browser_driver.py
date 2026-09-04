"""BrowserDriver against a real browser and a real server.

These are the slow tests in the suite -- they launch Chromium -- and they are worth
it. A browser driver verified only against a mock proves nothing about the thing it
exists to do. They are marked `browser` so they can be deselected.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from demo.app import create_app
from demo.server import serve
from qabot.drivers.base import Action, DriverError

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, sync_playwright

from qabot.drivers.browser import EVENT_EVIDENCE_LIMIT, EVENT_KINDS, BrowserDriver

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def shop_url() -> Iterator[str]:
    with serve(create_app()) as url:
        yield url


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


@pytest.fixture
def driver(shop_url: str, page: Page) -> BrowserDriver:
    d = BrowserDriver(base_url=shop_url, page=page, timeout_ms=3000)
    d.reset()
    return d


def goto_shop(driver: BrowserDriver) -> None:
    assert driver.execute(Action(kind="browser", params={"op": "goto", "path": "/ui"})).ok


def add_widget(driver: BrowserDriver) -> None:
    goto_shop(driver)
    driver.execute(
        Action(
            kind="browser",
            params={"op": "select", "role": "combobox", "name": "Product", "value": "widget"},
        )
    )
    driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": "Add to cart"})
    )


def test_goto_records_url_and_title(driver: BrowserDriver) -> None:
    observation = driver.execute(Action(kind="browser", params={"op": "goto", "path": "/ui"}))
    assert observation.ok
    assert observation.evidence["url"].endswith("/ui")
    assert observation.evidence["title"] == "Shop"
    assert "Add to cart" in observation.evidence["text"]


def test_click_and_select_drive_a_real_form(driver: BrowserDriver) -> None:
    add_widget(driver)
    observation = driver.execute(Action(kind="browser", params={"op": "read"}))
    assert "1 x widget" in observation.evidence["text"]


def test_a_failing_payment_is_a_completed_interaction(driver: BrowserDriver) -> None:
    """ok=True means the interaction happened, not that the app behaved."""
    add_widget(driver)
    driver.execute(
        Action(
            kind="browser",
            params={"op": "select", "role": "combobox", "name": "Card", "value": "expired"},
        )
    )
    observation = driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": "Place order"})
    )
    assert observation.ok
    assert observation.evidence["alerts"] == ["Payment failed."]


def test_alerts_are_captured_separately_from_page_text(driver: BrowserDriver) -> None:
    """The scoping the verifier relies on has to exist in the evidence."""
    add_widget(driver)
    driver.execute(
        Action(
            kind="browser",
            params={"op": "select", "role": "combobox", "name": "Card", "value": "expired"},
        )
    )
    observation = driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": "Place order"})
    )
    alerts = " ".join(observation.evidence["alerts"])
    assert "expired" not in alerts.lower()
    # ...while the page as a whole does contain it, via the card dropdown.
    assert "expired" in observation.evidence["text"].lower()


def test_an_unlabeled_control_is_unreachable_and_explained(driver: BrowserDriver) -> None:
    """The accessibility defect surfaces as a BLOCKED-shaped observation."""
    add_widget(driver)
    observation = driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": "Remove widget"})
    )
    assert observation.ok is False
    assert "no accessible control" in observation.evidence["error"]
    assert "accessibility defect" in observation.evidence["error"]


def test_screenshots_are_written_when_an_artifacts_dir_is_given(
    shop_url: str, page: Page, tmp_path
) -> None:
    driver = BrowserDriver(base_url=shop_url, page=page, artifacts_dir=tmp_path)
    driver.reset()
    observation = driver.execute(Action(kind="browser", params={"op": "goto", "path": "/ui"}))
    shot = observation.evidence["screenshot"]
    assert shot.endswith(".png")
    assert (tmp_path / "step_001.png").exists()


def test_wrong_action_kind_is_rejected(driver: BrowserDriver) -> None:
    with pytest.raises(DriverError, match="cannot execute action kind"):
        driver.execute(Action(kind="http", params={"method": "GET", "path": "/ui"}))


def test_unknown_op_is_rejected(driver: BrowserDriver) -> None:
    with pytest.raises(DriverError, match="unknown browser op"):
        driver.execute(Action(kind="browser", params={"op": "teleport"}))


def test_targeting_without_a_role_is_rejected(driver: BrowserDriver) -> None:
    """CSS and XPath are not a supported escape hatch."""
    goto_shop(driver)
    with pytest.raises(DriverError, match="must target a role"):
        driver.execute(Action(kind="browser", params={"op": "click"}))


def test_reset_is_loud_when_the_endpoint_is_missing(page: Page, shop_url: str) -> None:
    driver = BrowserDriver(base_url=shop_url, page=page, reset_path="/no-such-reset")
    with pytest.raises(DriverError, match="reset failed"):
        driver.reset()


# -- error signals -----------------------------------------------------------
#
# A page that reports every kind of error a browser can report, on purpose. Every
# one of them happens before the load event, so a single `goto` observes all four
# with no sleeps and nothing to go flaky.

#: How many console errors the spam button emits -- deliberately above the cap.
SPAM_COUNT = 57

_BROKEN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Broken</title></head>
<body>
<h1>Broken page</h1>
<button id="boom">Break it</button>
<button id="spam">Spam the console</button>
<script src="/boom.js"></script>
<img src="http://127.0.0.1:DEAD_PORT/never.png" alt="">
<script src="https://analytics.not-a-real-host.invalid/collect.js"></script>
<img src="/favicon.ico" alt="">
<script>
  console.log("chatter that is not an error");
  console.warn("a dev-mode warning");
  console.error("cart total computed as NaN");
  document.getElementById("boom").addEventListener("click", () => { null.total; });
  document.getElementById("spam").addEventListener("click", () => {
    for (let i = 0; i < SPAM_COUNT; i++) console.error("render loop " + i);
  });
</script>
<script>throw new Error("checkout total is not a number");</script>
</body></html>"""


def line_of(needle: str) -> int:
    """Where a line lives in the page, counted the way an editor counts.

    Derived rather than hard-coded so an edit to the page above cannot silently
    turn the off-by-one assertion into a tautology.
    """
    return next(i for i, text in enumerate(_BROKEN_PAGE.splitlines(), 1) if needle in text)


def dead_port() -> int:
    """A port nothing is listening on, so a request to it fails outright."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def broken_app() -> FastAPI:
    app = FastAPI()
    body = _BROKEN_PAGE.replace("DEAD_PORT", str(dead_port())).replace(
        "SPAM_COUNT", str(SPAM_COUNT)
    )

    @app.post("/reset")
    def reset() -> Response:
        return PlainTextResponse("ok")

    @app.get("/broken")
    def broken() -> Response:
        return HTMLResponse(body)

    @app.get("/boom.js")
    def boom_js() -> Response:
        return PlainTextResponse("the server fell over", status_code=500)

    @app.get("/favicon.ico")
    def favicon() -> Response:
        return PlainTextResponse("the server fell over", status_code=500)

    return app


@pytest.fixture(scope="module")
def broken_url() -> Iterator[str]:
    with serve(broken_app()) as url:
        yield url


@pytest.fixture
def broken_driver(broken_url: str, page: Page) -> BrowserDriver:
    d = BrowserDriver(base_url=broken_url, page=page, timeout_ms=3000)
    d.reset()
    return d


def goto_broken(driver: BrowserDriver) -> dict:
    observation = driver.execute(Action(kind="browser", params={"op": "goto", "path": "/broken"}))
    assert observation.ok
    return observation.evidence["browser_events"]


def click(driver: BrowserDriver, name: str) -> dict:
    observation = driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": name})
    )
    assert observation.ok
    return observation.evidence["browser_events"]


def test_all_four_error_signals_survive_one_page_load(broken_driver: BrowserDriver) -> None:
    """The whole point: a page can look fine and be shouting all four of these."""
    events = goto_broken(broken_driver)

    assert [e["text"] for e in events["page_errors"]] == ["checkout total is not a number"]
    assert "cart total computed as NaN" in [e["text"] for e in events["console_errors"]]
    assert any("never.png" in e["url"] for e in events["failed_requests"])
    assert [
        (e["method"], e["status"]) for e in events["server_errors"] if "boom.js" in e["url"]
    ] == [("GET", 500)]


def test_an_event_says_where_it_came_from(broken_driver: BrowserDriver) -> None:
    """A message with no source location is a bug report that starts with a search.

    Chromium numbers console locations from zero and stack frames from one, so this
    also pins the normalisation: both mean the line an editor would show.
    """
    events = goto_broken(broken_driver)

    console = next(e for e in events["console_errors"] if e["text"] == "cart total computed as NaN")
    assert console["url"].endswith("/broken")
    assert console["line"] == line_of("cart total computed as NaN")

    page_error = events["page_errors"][0]
    assert page_error["url"].endswith("/broken")
    assert page_error["line"] == line_of("checkout total is not a number")

    failure = next(e for e in events["failed_requests"] if "never.png" in e["url"])
    assert failure["method"] == "GET"
    assert failure["failure"]


def test_events_belong_to_the_interaction_that_caused_them(broken_driver: BrowserDriver) -> None:
    """Rule 3, in the driver: evidence must point at the step it is about."""
    goto_broken(broken_driver)
    events = click(broken_driver, "Break it")

    assert [e["text"] for e in events["page_errors"]] == [
        "Cannot read properties of null (reading 'total')"
    ]
    # The load-time noise left with the observation that earned it.
    assert events["console_errors"] == []
    assert events["server_errors"] == []


def test_a_step_that_caused_nothing_reports_nothing(broken_driver: BrowserDriver) -> None:
    goto_broken(broken_driver)
    observation = broken_driver.execute(Action(kind="browser", params={"op": "read"}))
    events = observation.evidence["browser_events"]

    assert all(events[kind] == [] for kind in EVENT_KINDS)
    assert events["suppressed"] == 0
    assert events["truncated"] == {}


def test_third_party_and_favicon_noise_is_suppressed_but_counted(
    broken_driver: BrowserDriver,
) -> None:
    """Filtered is not the same as forgotten. A run must be able to say how much."""
    events = goto_broken(broken_driver)

    reported = [str(event.get("url") or "") for kind in EVENT_KINDS for event in events[kind]]
    assert not [url for url in reported if "not-a-real-host.invalid" in url]
    assert not [url for url in reported if "favicon" in url]
    # The unresolvable third-party script, its console error, and the failing favicon.
    assert events["suppressed"] >= 3


def test_console_output_below_error_level_is_not_captured(broken_driver: BrowserDriver) -> None:
    """Deliberate scope, not an oversight: a warning is not evidence of a defect."""
    texts = " ".join(e["text"] for e in goto_broken(broken_driver)["console_errors"])
    assert "chatter that is not an error" not in texts
    assert "a dev-mode warning" not in texts


def test_the_cap_bounds_the_evidence_but_never_the_truth(broken_driver: BrowserDriver) -> None:
    goto_broken(broken_driver)
    events = click(broken_driver, "Spam the console")

    assert len(events["console_errors"]) == EVENT_EVIDENCE_LIMIT
    assert events["truncated"] == {"console_errors": SPAM_COUNT}


def test_reset_does_not_carry_events_into_the_next_workflow(
    broken_driver: BrowserDriver, page: Page
) -> None:
    """An error nobody observed must not be blamed on the workflow that comes next."""
    goto_broken(broken_driver)
    page.evaluate("console.error('late arrival, after the last observation')")

    broken_driver.reset()
    observation = broken_driver.execute(Action(kind="browser", params={"op": "read"}))
    assert observation.evidence["browser_events"]["console_errors"] == []


def test_a_listener_that_raises_is_counted_rather_than_propagated(
    broken_driver: BrowserDriver,
) -> None:
    """Capture must never be the thing that fails a step -- but it must say it broke."""

    def explode(_event: object) -> None:
        raise RuntimeError("the capture layer itself is broken")

    broken_driver._guard(explode)(None)

    observation = broken_driver.execute(Action(kind="browser", params={"op": "read"}))
    assert observation.ok
    assert observation.evidence["browser_events"]["capture_errors"] == 1


def test_a_clean_page_still_reports_the_full_shape(driver: BrowserDriver) -> None:
    """ "No errors" and "this driver does not report errors" must not look alike."""
    goto_shop(driver)
    events = driver.execute(Action(kind="browser", params={"op": "read"})).evidence[
        "browser_events"
    ]

    assert all(events[kind] == [] for kind in EVENT_KINDS)
    assert events == {
        **{kind: [] for kind in EVENT_KINDS},
        "suppressed": 0,
        "truncated": {},
        "capture_errors": 0,
    }


def test_a_blocked_step_still_carries_the_page_errors(broken_driver: BrowserDriver) -> None:
    """The step that could not complete is exactly where an error explains why."""
    goto_broken(broken_driver)
    observation = broken_driver.execute(
        Action(kind="browser", params={"op": "click", "role": "button", "name": "No such button"})
    )
    assert observation.ok is False
    assert "browser_events" in observation.evidence


@pytest.fixture(scope="module")
def redirecting_app() -> Iterator[str]:
    """One server, reachable under two hostnames, so a redirect can change host
    without changing port.

    `urlsplit(...).hostname` drops the port, so two `127.0.0.1` ports served by
    `demo.server.serve()` are indistinguishable to the origin rule -- that was the
    flaw in this fixture's first draft, caught because the test it produced passed
    even against the unfixed driver. `localhost` reaches the same `127.0.0.1`-bound
    server under a hostname `urlsplit` sees as genuinely different, which is exactly
    what a redirect to a vanity domain looks like from the driver's point of view,
    with no DNS or `/etc/hosts` entry a test has no business writing.
    """
    app = FastAPI()

    @app.get("/landed")
    def landed() -> HTMLResponse:
        return HTMLResponse(
            "<html><body>landed"
            "<script>console.error('error from the vanity host')</script>"
            "</body></html>"
        )

    with serve(app) as url:
        port = urlsplit(url).port

        @app.get("/redirects-away")
        def redirects_away() -> Response:
            return Response(
                status_code=307, headers={"Location": f"http://localhost:{port}/landed"}
            )

        yield url


def test_events_from_a_host_the_app_redirected_us_to_are_not_third_party(
    page: Page, redirecting_app: str
) -> None:
    """The origin rule exists to drop other people's scripts, not the app's own
    second domain. An app served from a vanity host it redirects to is still the app."""
    driver = BrowserDriver(base_url=redirecting_app, page=page)

    observation = driver.execute(
        Action(kind="browser", params={"op": "goto", "path": "/redirects-away"})
    )

    events = observation.evidence["browser_events"]
    assert [e["text"] for e in events["console_errors"]] == ["error from the vanity host"]
    assert events["suppressed"] == 0
