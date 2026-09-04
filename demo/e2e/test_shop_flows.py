"""End-to-end tests for the demo shop, written the way a customer's own suite is written.

These exercise what a shopper actually does -- fill a cart, pay, survive a refused card --
and they are the only place in this repository where those flows are named in domain
language. That is exactly why `qabot.seeder` reads this file to cold-start a knowledge
base: a hand-written e2e suite is a record of which flows a human thought were worth
protecting.

Nothing here imports qabot, and pytest's `testpaths` excludes this directory: this file is
input data for the seeder, not part of qabot's own test run.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    """A client pointed at a freshly reset shop."""
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as session:
        session.post("/reset")
        yield session


def test_add_item_to_cart(client: httpx.Client) -> None:
    """A shopper adds a widget to an empty cart and sees it priced in the cart."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
    assert len(resp.json()["items"]) > 0
    assert resp.json()["total"] == 1000


def test_checkout_with_valid_card(client: httpx.Client) -> None:
    """A shopper checks out a cart of gadgets with a good card and gets a confirmed order."""
    resp = client.post("/cart/items", json={"sku": "gadget", "qty": 2})
    assert resp.status_code == 201
    cart = resp.json()["cart_id"]

    resp = client.post("/checkout/submit", json={"cart_id": cart, "card_token": "valid"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"
    assert resp.json()["order_id"]


def test_checkout_with_expired_card_preserves_cart(client: httpx.Client) -> None:
    """A shopper whose card has expired is refused payment but keeps the cart intact."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 3})
    assert resp.status_code == 201
    cart_id = resp.json()["cart_id"]

    resp = client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "expired"})
    assert resp.status_code == 402
    assert "expired" in resp.json()["message"]

    resp = client.get(f"/cart/{cart_id}")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) > 0


def test_unknown_sku_returns_404(client: httpx.Client) -> None:
    """A shopper who asks for a product the catalog does not carry is told it does not exist."""
    resp = client.post("/cart/items", json={"sku": "nonexistent", "qty": 1})
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_sku"
