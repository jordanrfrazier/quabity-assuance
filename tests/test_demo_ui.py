"""The browser UI must reproduce the JSON API's defects exactly.

WHY this file is separate from the browser driver tests: these run in-process and
take milliseconds. They pin the *app's* behavior, so that when a browser run reports
a finding we can tell whether the driver or the app changed.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from demo.app import create_app

CART_ID = re.compile(r'name="cart_id" value="(cart_\d+)"')


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def add_widget(client: TestClient, sku: str = "widget") -> str:
    response = client.post("/ui/cart/items", data={"sku": sku, "qty": "1"}, follow_redirects=True)
    assert response.status_code == 200
    match = CART_ID.search(response.text)
    assert match, "cart page should carry its cart id in the checkout form"
    return match.group(1)


def alert_text(html: str) -> str:
    """The text of the page's alert region, which is what a text check scopes to."""
    match = re.search(r'<p role="alert">(.*?)</p>', html, re.DOTALL)
    return match.group(1) if match else ""


def test_shop_page_offers_an_accessible_add_to_cart_control(client: TestClient) -> None:
    body = client.get("/ui").text
    assert "Add to cart" in body
    assert '<label for="sku">Product</label>' in body


def test_adding_an_item_lands_on_the_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    body = client.get(f"/ui/cart/{cart_id}").text
    assert "1 x widget" in body
    assert "Place order" in body


def test_valid_card_confirms_the_order(client: TestClient) -> None:
    cart_id = add_widget(client)
    body = client.post("/ui/checkout", data={"cart_id": cart_id, "card_token": "valid"}).text
    assert "Order confirmed" in body
    assert "Order reference" in body


def test_declined_card_preserves_the_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    body = client.post("/ui/checkout", data={"cart_id": cart_id, "card_token": "declined"}).text
    assert "declined" in alert_text(body).lower()
    assert "Your cart is empty" not in body


def test_defect_expired_card_alert_never_names_the_card(client: TestClient) -> None:
    """DELIBERATE DEFECT: the shopper is not told the card expired."""
    cart_id = add_widget(client)
    body = client.post("/ui/checkout", data={"cart_id": cart_id, "card_token": "expired"}).text
    assert "expired" not in alert_text(body).lower()
    assert alert_text(body) == "Payment failed."


def test_defect_expired_card_clears_the_cart(client: TestClient) -> None:
    """DELIBERATE DEFECT: unlike a decline, an expiry loses the cart."""
    cart_id = add_widget(client)
    body = client.post("/ui/checkout", data={"cart_id": cart_id, "card_token": "expired"}).text
    assert "Your cart is empty" in body


def test_the_word_expired_appears_outside_the_alert(client: TestClient) -> None:
    """Guards the reason text checks are scoped to a region.

    The card <select> carries an option labelled "expired", so a page-wide search for
    "expired" succeeds on the very page whose alert fails to mention it. If this ever
    stops being true the scoping in the verifier is no longer being exercised, and a
    page-wide check would start passing for the wrong reason.
    """
    cart_id = add_widget(client)
    body = client.post("/ui/checkout", data={"cart_id": cart_id, "card_token": "expired"}).text
    assert "expired" in body.lower()
    assert "expired" not in alert_text(body).lower()


def test_defect_remove_control_has_no_accessible_name(client: TestClient) -> None:
    """DELIBERATE DEFECT: the remove button is a bare glyph.

    A role+name locator cannot reach it, which is why the remove workflow reports
    BLOCKED rather than passing or failing.
    """
    cart_id = add_widget(client)
    body = client.get(f"/ui/cart/{cart_id}").text
    remove_form = re.search(
        r'<form method="post" action="/ui/cart/[^"]+/remove".*?</form>', body, re.DOTALL
    )
    assert remove_form, "the cart should offer a remove control"
    markup = remove_form.group(0)
    assert "aria-label" not in markup
    assert "Remove" not in markup


def test_remove_endpoint_itself_works(client: TestClient) -> None:
    """The defect is the missing label, not the behavior behind it."""
    cart_id = add_widget(client)
    client.post(f"/ui/cart/{cart_id}/remove", data={"index": "0"}, follow_redirects=True)
    assert "Your cart is empty" in client.get(f"/ui/cart/{cart_id}").text


def test_unknown_cart_is_reported(client: TestClient) -> None:
    assert "could not find that cart" in client.get("/ui/cart/cart_999").text.lower()
