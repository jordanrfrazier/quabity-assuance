"""Contract tests for the demo shop.

These pin the app's behaviour *including its two deliberate defects*. If someone
"fixes" the expired-card path without updating the demo narrative, these fail and
say so loudly, rather than the prototype quietly losing the finding it exists to show.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from demo.app import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # TestClient is the sync client that can drive an ASGI app in-process; httpx's
    # own ASGITransport is async-only, so a plain sync httpx.Client cannot.
    with TestClient(create_app(), base_url="http://test") as client:
        yield client


def add_widget(client: TestClient, cart_id: str | None = None) -> str:
    body: dict[str, object] = {"sku": "widget", "qty": 1}
    if cart_id is not None:
        body["cart_id"] = cart_id
    response = client.post("/cart/items", json=body)
    assert response.status_code == 201
    return str(response.json()["cart_id"])


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reset_clears_carts_and_ids(client: TestClient) -> None:
    cart_id = add_widget(client)
    assert cart_id == "cart_1"

    assert client.post("/reset").json() == {"ok": True}

    assert client.get("/cart/cart_1").status_code == 404
    # Ids restart, so a reset run reads identically to the first run.
    assert add_widget(client) == "cart_1"


def test_add_item_creates_cart(client: TestClient) -> None:
    response = client.post("/cart/items", json={"sku": "gadget", "qty": 2})
    assert response.status_code == 201
    assert response.json() == {
        "cart_id": "cart_1",
        "items": [{"sku": "gadget", "qty": 2, "price": 2500}],
        "total": 5000,
    }


def test_add_item_to_existing_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.post("/cart/items", json={"sku": "gadget", "qty": 1, "cart_id": cart_id})
    assert response.status_code == 201
    assert response.json() == {
        "cart_id": "cart_1",
        "items": [
            {"sku": "widget", "qty": 1, "price": 1000},
            {"sku": "gadget", "qty": 1, "price": 2500},
        ],
        "total": 3500,
    }


def test_add_same_sku_merges_quantity(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.post("/cart/items", json={"sku": "widget", "qty": 3, "cart_id": cart_id})
    assert response.json() == {
        "cart_id": "cart_1",
        "items": [{"sku": "widget", "qty": 4, "price": 1000}],
        "total": 4000,
    }


def test_separate_carts_get_separate_ids(client: TestClient) -> None:
    assert add_widget(client) == "cart_1"
    assert add_widget(client) == "cart_2"


def test_add_unknown_sku(client: TestClient) -> None:
    response = client.post("/cart/items", json={"sku": "sprocket", "qty": 1})
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_sku"}


def test_add_item_to_unknown_cart(client: TestClient) -> None:
    response = client.post("/cart/items", json={"sku": "widget", "qty": 1, "cart_id": "cart_99"})
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_cart"}


def test_get_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.get(f"/cart/{cart_id}")
    assert response.status_code == 200
    assert response.json() == {
        "cart_id": "cart_1",
        "items": [{"sku": "widget", "qty": 1, "price": 1000}],
        "total": 1000,
    }


def test_get_unknown_cart(client: TestClient) -> None:
    response = client.get("/cart/cart_99")
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_cart"}


def test_checkout_valid_confirms_and_clears_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "valid"})
    assert response.status_code == 200
    assert response.json() == {"order_id": "order_1", "status": "confirmed"}

    cart = client.get(f"/cart/{cart_id}")
    assert cart.status_code == 200
    assert cart.json()["items"] == []
    assert cart.json()["total"] == 0


def test_checkout_declined_preserves_cart(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "declined"})
    assert response.status_code == 402
    assert response.json() == {"error": "payment_declined", "message": "Card was declined."}

    cart = client.get(f"/cart/{cart_id}")
    assert cart.json()["items"] == [{"sku": "widget", "qty": 1, "price": 1000}]
    assert cart.json()["total"] == 1000


def test_defect_expired_card_error_is_generic(client: TestClient) -> None:
    """DELIBERATE DEFECT 1: the response never identifies the card as expired."""
    cart_id = add_widget(client)
    response = client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "expired"})
    assert response.status_code == 402
    assert response.json() == {"error": "payment_failed", "message": "Payment failed."}
    assert "expired" not in response.text


def test_defect_expired_card_clears_cart(client: TestClient) -> None:
    """DELIBERATE DEFECT 2: a failed payment drops the cart, unlike "declined"."""
    cart_id = add_widget(client)
    client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "expired"})

    cart = client.get(f"/cart/{cart_id}")
    assert cart.status_code == 200
    assert cart.json()["items"] == []
    assert cart.json()["total"] == 0


def test_checkout_unknown_cart(client: TestClient) -> None:
    response = client.post("/checkout/submit", json={"cart_id": "cart_99", "card_token": "valid"})
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_cart"}


def test_checkout_unknown_card_token(client: TestClient) -> None:
    cart_id = add_widget(client)
    response = client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "mystery"})
    assert response.status_code == 400
    assert response.json() == {"error": "unknown_card_token"}


def test_refund_requires_admin_role(client: TestClient) -> None:
    cart_id = add_widget(client)
    client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "valid"})

    response = client.post("/admin/refund", json={"order_id": "order_1"})
    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_refund_as_admin(client: TestClient) -> None:
    cart_id = add_widget(client)
    client.post("/checkout/submit", json={"cart_id": cart_id, "card_token": "valid"})

    response = client.post(
        "/admin/refund", json={"order_id": "order_1"}, headers={"X-Role": "admin"}
    )
    assert response.status_code == 200
    assert response.json() == {"order_id": "order_1", "status": "refunded"}


def test_refund_unknown_order(client: TestClient) -> None:
    response = client.post(
        "/admin/refund", json={"order_id": "order_99"}, headers={"X-Role": "admin"}
    )
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_order"}
