"""HttpDriver tests, driven against the real demo app in-process.

The load-bearing assertion here is the ok/status split: a 402 must come back
ok=True (the app answered) while an unreachable port must come back ok=False (it
did not). Downstream, that is the entire difference between FAIL and BLOCKED.
"""

from __future__ import annotations

import contextlib
import json
import socket
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.testclient import TestClient

from demo.app import create_app
from qabot.drivers import Action, DriverError
from qabot.drivers.http import NO_RESET_LIMITATION, REDACTED, HttpDriver


def asgi_client(app: FastAPI) -> TestClient:
    """An in-process client for the driver to borrow. TestClient is used instead of
    httpx.ASGITransport because that transport is async-only and the driver is sync."""
    return TestClient(app, base_url="http://test")


@pytest.fixture
def driver() -> Iterator[HttpDriver]:
    client = asgi_client(create_app())
    driver = HttpDriver(base_url="http://test", client=client)
    yield driver
    driver.close()
    client.close()


def closed_port() -> int:
    """A port nothing is listening on: bind, read, release."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def post_widget(driver: HttpDriver) -> str:
    observation = driver.execute(
        Action(
            kind="http",
            params={"method": "POST", "path": "/cart/items", "json": {"sku": "widget", "qty": 1}},
        )
    )
    return str(observation.evidence["json"]["cart_id"])  # type: ignore[index]


def test_name() -> None:
    assert HttpDriver.name == "http"


def test_reset(driver: HttpDriver) -> None:
    post_widget(driver)
    driver.reset()

    observation = driver.execute(
        Action(kind="http", params={"method": "GET", "path": "/cart/cart_1", "json": None})
    )
    assert observation.evidence["status"] == 404


def test_reset_raises_when_endpoint_missing() -> None:
    """No /reset means no known starting state, and that must be loud."""
    client = asgi_client(FastAPI())
    driver = HttpDriver(base_url="http://test", client=client)
    with pytest.raises(DriverError, match="reset failed"):
        driver.reset()
    client.close()


def test_reset_can_be_declared_absent_and_is_then_stated(driver: HttpDriver) -> None:
    """No third-party app has a /reset endpoint. The caller may say so at construction
    -- the empty app below would 404 and raise if a request were still sent -- but the
    cost is a limitation carried on the run, not silence."""
    client = asgi_client(FastAPI())
    no_reset = HttpDriver(base_url="http://test", client=client, reset_path=None)

    no_reset.reset()

    assert no_reset.limitations == [NO_RESET_LIMITATION]
    assert driver.limitations == []
    client.close()


def test_reset_raises_when_app_unreachable() -> None:
    driver = HttpDriver(base_url=f"http://127.0.0.1:{closed_port()}", timeout=0.25)
    with pytest.raises(DriverError, match="could not reach"):
        driver.reset()
    driver.close()


def test_created_response_is_ok(driver: HttpDriver) -> None:
    observation = driver.execute(
        Action(
            kind="http",
            params={"method": "POST", "path": "/cart/items", "json": {"sku": "widget", "qty": 2}},
        )
    )
    assert observation.ok is True
    assert observation.summary == "POST /cart/items -> 201"
    assert observation.evidence["status"] == 201
    assert observation.evidence["json"] == {
        "cart_id": "cart_1",
        "items": [{"sku": "widget", "qty": 2, "price": 1000}],
        "total": 2000,
    }


def test_evidence_contents(driver: HttpDriver) -> None:
    request = {"method": "GET", "path": "/health", "json": None}
    observation = driver.execute(Action(kind="http", params=request))

    assert set(observation.evidence) == {"status", "json", "text", "request", "elapsed_ms"}
    assert observation.evidence["status"] == 200
    assert observation.evidence["json"] == {"status": "ok"}
    assert observation.evidence["text"] == '{"status":"ok"}'
    assert observation.evidence["request"] == request
    assert isinstance(observation.evidence["elapsed_ms"], float)
    assert observation.evidence["elapsed_ms"] >= 0


def test_payment_required_is_ok_true(driver: HttpDriver) -> None:
    """A 402 is a completed interaction. ok tracks reachability, not correctness."""
    cart_id = post_widget(driver)
    observation = driver.execute(
        Action(
            kind="http",
            params={
                "method": "POST",
                "path": "/checkout/submit",
                "json": {"cart_id": cart_id, "card_token": "expired"},
            },
        )
    )
    assert observation.ok is True
    assert observation.summary == "POST /checkout/submit -> 402"
    assert observation.evidence["status"] == 402
    assert observation.evidence["json"] == {"error": "payment_failed", "message": "Payment failed."}


def test_headers_are_forwarded(driver: HttpDriver) -> None:
    cart_id = post_widget(driver)
    driver.execute(
        Action(
            kind="http",
            params={
                "method": "POST",
                "path": "/checkout/submit",
                "json": {"cart_id": cart_id, "card_token": "valid"},
            },
        )
    )
    observation = driver.execute(
        Action(
            kind="http",
            params={
                "method": "POST",
                "path": "/admin/refund",
                "json": {"order_id": "order_1"},
                "headers": {"X-Role": "admin"},
            },
        )
    )
    assert observation.evidence["status"] == 200
    assert observation.evidence["request"]["headers"] == {"X-Role": "admin"}  # type: ignore[index]


def test_unknown_action_kind(driver: HttpDriver) -> None:
    with pytest.raises(DriverError, match="cannot execute action kind 'browser'"):
        driver.execute(Action(kind="browser", params={"selector": "#submit"}))


def test_unreachable_app_is_not_ok() -> None:
    driver = HttpDriver(base_url=f"http://127.0.0.1:{closed_port()}", timeout=0.25)
    observation = driver.execute(
        Action(kind="http", params={"method": "GET", "path": "/health", "json": None})
    )
    assert observation.ok is False
    assert "transport error" in observation.summary
    assert observation.evidence["status"] is None
    assert observation.evidence["json"] is None
    assert observation.evidence["request"] == {"method": "GET", "path": "/health", "json": None}
    assert "error" in observation.evidence
    driver.close()


def test_close_leaves_injected_client_open() -> None:
    """The injector owns the client; closing it out from under them is a bug."""
    client = asgi_client(create_app())
    driver = HttpDriver(base_url="http://test", client=client)
    driver.close()
    assert client.is_closed is False
    client.close()


#: Stand-ins for the two things a caller hands this driver. Distinctive strings, so a
#: leak test that greps for them cannot pass by accident.
TOKEN = "sk-live-0f3d9c1a-not-a-real-token"
BEARER = f"Bearer {TOKEN}"
SESSION = "sess-71c4-not-a-real-session"


def auth_app() -> FastAPI:
    """An app that answers with what it actually received.

    Credentials are proved to arrive by asking the app, never by reading back our own
    recorded evidence: that would only prove we recorded what we meant to send, which
    is the weaker claim and the one that stays true when the sending is broken.

    `/quiet` exists because `/echo` deliberately reflects the token in its body, and a
    redaction test has to run against a response that does not.
    """
    app = FastAPI()

    @app.get("/echo")
    def echo(request: Request) -> dict[str, object]:
        return {"headers": dict(request.headers), "cookies": dict(request.cookies)}

    @app.get("/quiet")
    def quiet() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/login")
    def login() -> Response:
        response = JSONResponse({"ok": True})
        response.set_cookie("session", SESSION)
        return response

    @app.post("/reset")
    def reset(request: Request) -> Response:
        if request.headers.get("authorization") != BEARER:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse({"ok": True})

    return app


@contextlib.contextmanager
def auth_driver(**kwargs: object) -> Iterator[HttpDriver]:
    client = asgi_client(auth_app())
    driver = HttpDriver(base_url="http://test", client=client, **kwargs)  # type: ignore[arg-type]
    try:
        yield driver
    finally:
        driver.close()
        client.close()


def get(driver: HttpDriver, path: str, headers: dict[str, str] | None = None) -> dict:
    params: dict[str, object] = {"method": "GET", "path": path, "json": None}
    if headers is not None:
        params["headers"] = headers
    return driver.execute(Action(kind="http", params=params)).evidence


def test_static_headers_are_sent_on_every_request() -> None:
    """Every request, not the first: the credential belongs to the run, not to a step."""
    with auth_driver(headers={"Authorization": BEARER}) as driver:
        first = get(driver, "/echo")["json"]
        second = get(driver, "/echo")["json"]

    assert first["headers"]["authorization"] == BEARER  # type: ignore[index]
    assert second["headers"]["authorization"] == BEARER  # type: ignore[index]


def test_a_per_action_header_beats_a_static_one_of_the_same_name() -> None:
    """Case-insensitively, which is the reason the merge is httpx's and not a dict
    update here. A dict merge would have sent both and let the app choose, and two
    Authorization headers on one request is the kind of wrongness that costs a day."""
    with auth_driver(headers={"Authorization": BEARER}) as driver:
        body = get(driver, "/echo", {"authorization": "Bearer per-action"})["json"]

    assert body["headers"]["authorization"] == "Bearer per-action"  # type: ignore[index]


def test_reset_carries_the_static_headers() -> None:
    """An app that wants credentials to answer /reset wants them to answer /reset. A
    driver that authenticated its steps but not its reset would raise at the top of
    every run against a real application."""
    with auth_driver(headers={"Authorization": BEARER}) as driver:
        driver.reset()

    with auth_driver() as unauthenticated, pytest.raises(DriverError, match="returned 401"):
        unauthenticated.reset()


def test_cookies_are_sent_on_every_request() -> None:
    with auth_driver(cookies={"session": SESSION}) as driver:
        body = get(driver, "/echo")["json"]

    assert body["cookies"] == {"session": SESSION}  # type: ignore[index]


def test_a_cookie_set_by_a_response_persists_to_the_next_step() -> None:
    """The claim in the class docstring, pinned rather than trusted. httpx keeps a jar
    per client and this driver keeps a client per run, so a cookie handed out during
    step 1 goes back out on step 2 -- within the run, and only within the run."""
    with auth_driver() as driver:
        driver.execute(Action(kind="http", params={"method": "POST", "path": "/login"}))
        body = get(driver, "/echo")["json"]

    assert body["cookies"] == {"session": SESSION}  # type: ignore[index]


def test_credential_values_are_redacted_where_evidence_is_recorded() -> None:
    """Names kept, values dropped. A reader debugging a 401 has to be able to see that
    we did send an Authorization header; nobody has to see what was in it."""
    with auth_driver(headers={"Authorization": BEARER}) as driver:
        evidence = get(driver, "/quiet", {"X-Api-Key": "key-9999", "X-Role": "admin"})

    assert evidence["request"]["headers"] == {  # type: ignore[index]
        "Authorization": REDACTED,
        "X-Api-Key": REDACTED,
        "X-Role": "admin",
    }
    assert TOKEN not in json.dumps(evidence)
    assert "key-9999" not in json.dumps(evidence)


def test_an_injected_header_is_redacted_whatever_it_is_called() -> None:
    """We cannot tell an API key from an Accept by reading its name, and only one of
    those two guesses is expensive. Anything set for the whole run is assumed to be a
    credential -- the reason someone reached for --header in the first place."""
    with auth_driver(headers={"X-Tenant": "acme-prod"}) as driver:
        evidence = get(driver, "/quiet")

    assert evidence["request"]["headers"] == {"X-Tenant": REDACTED}  # type: ignore[index]


def test_cookie_names_are_recorded_and_their_values_never_are() -> None:
    """Same trade as headers. "We sent a session cookie and still got a 302" and "we
    sent nothing" are different bugs, and a reader cannot tell them apart from a
    request that mentions no cookies at all."""
    with auth_driver(cookies={"session": SESSION}) as driver:
        evidence = get(driver, "/quiet")

    assert evidence["request"]["cookies"] == {"session": REDACTED}  # type: ignore[index]
    assert "headers" not in evidence["request"]  # type: ignore[operator]
    assert SESSION not in json.dumps(evidence)


def test_a_cookie_the_app_set_mid_run_is_recorded_too() -> None:
    """Read off the jar, not off the constructor argument: by the time a workflow
    fails, which credentials were in play is the first question asked."""
    with auth_driver() as driver:
        before = get(driver, "/quiet")
        driver.execute(Action(kind="http", params={"method": "POST", "path": "/login"}))
        after = get(driver, "/quiet")

    assert "cookies" not in before["request"]  # type: ignore[operator]
    assert after["request"]["cookies"] == {"session": REDACTED}  # type: ignore[index]
    assert SESSION not in json.dumps(after)
