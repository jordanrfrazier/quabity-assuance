"""The target application the prototype is demonstrated against.

WHY this exists: a QA agent is only credible if it exercises a *running* app rather
than reasoning about source. This is a deliberately small shop with in-memory state
so a run is fast, hermetic, and resettable between workflows.

It ships two DELIBERATE DEFECTS (marked below). They are the point of the demo: one
violates a human-confirmed expectation and must surface as a BUG, the other violates
a test-inferred expectation and must surface as a CHANGE. The same run producing two
different severities from two real violations is the thing being demonstrated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

#: Prices in integer cents. Two skus is enough to make a cart interesting.
CATALOG: dict[str, int] = {"widget": 1000, "gadget": 2500}

#: The only card tokens the fake payment processor understands.
CARD_TOKENS: frozenset[str] = frozenset({"valid", "expired", "declined"})

CartItem = dict[str, str | int]


class AddItemRequest(BaseModel):
    sku: str
    qty: int
    cart_id: str | None = None


class CheckoutRequest(BaseModel):
    cart_id: str
    card_token: str


class RefundRequest(BaseModel):
    order_id: str


class ShopState:
    """All mutable state, in one object, so /reset is a single call.

    Ids are sequential ("cart_1", "order_1") rather than uuids: a QA report that
    says "cart_2" is readable, and a deterministic run is a reproducible run.
    """

    def __init__(self) -> None:
        self.carts: dict[str, list[CartItem]] = {}
        self.orders: dict[str, str] = {}
        self._next_cart: int = 1
        self._next_order: int = 1

    def clear(self) -> None:
        self.carts.clear()
        self.orders.clear()
        self._next_cart = 1
        self._next_order = 1

    def new_cart(self) -> str:
        cart_id = f"cart_{self._next_cart}"
        self._next_cart += 1
        self.carts[cart_id] = []
        return cart_id

    def new_order(self) -> str:
        order_id = f"order_{self._next_order}"
        self._next_order += 1
        return order_id


def cart_view(cart_id: str, items: list[CartItem]) -> dict[str, object]:
    """The cart representation every cart-shaped response returns."""
    total = sum(int(item["price"]) * int(item["qty"]) for item in items)
    return {"cart_id": cart_id, "items": items, "total": total}


def create_app() -> FastAPI:
    """Build an app with its own isolated state, so tests never share carts."""
    app = FastAPI(title="demo-shop")
    state = ShopState()

    @app.post("/reset")
    def reset() -> dict[str, bool]:
        state.clear()
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/cart/items")
    def add_item(req: AddItemRequest) -> Response:
        if req.sku not in CATALOG:
            return JSONResponse(status_code=404, content={"error": "unknown_sku"})

        if req.cart_id is None:
            cart_id = state.new_cart()
        elif req.cart_id in state.carts:
            cart_id = req.cart_id
        else:
            return JSONResponse(status_code=404, content={"error": "unknown_cart"})

        items = state.carts[cart_id]
        existing = next((item for item in items if item["sku"] == req.sku), None)
        if existing is None:
            items.append({"sku": req.sku, "qty": req.qty, "price": CATALOG[req.sku]})
        else:
            existing["qty"] = int(existing["qty"]) + req.qty

        return JSONResponse(status_code=201, content=cart_view(cart_id, items))

    @app.get("/cart/{cart_id}")
    def get_cart(cart_id: str) -> Response:
        if cart_id not in state.carts:
            return JSONResponse(status_code=404, content={"error": "unknown_cart"})
        return JSONResponse(status_code=200, content=cart_view(cart_id, state.carts[cart_id]))

    @app.post("/checkout/submit")
    def submit_checkout(req: CheckoutRequest) -> Response:
        if req.cart_id not in state.carts:
            return JSONResponse(status_code=404, content={"error": "unknown_cart"})
        if req.card_token not in CARD_TOKENS:
            return JSONResponse(status_code=400, content={"error": "unknown_card_token"})

        if req.card_token == "declined":
            # The cart survives a decline so the shopper can retry with another card.
            return JSONResponse(
                status_code=402,
                content={"error": "payment_declined", "message": "Card was declined."},
            )

        if req.card_token == "expired":
            # DELIBERATE DEFECT (demo): an expired card is reported with a generic
            # failure that never names the card as expired, so the shopper cannot
            # tell what to fix. Violates a human-confirmed expectation -> BUG.
            # DELIBERATE DEFECT (demo): and the cart is cleared on this failure path,
            # unlike "declined" above which preserves it. Violates a test-inferred
            # expectation that a failed payment keeps the cart -> CHANGE. The
            # asymmetry between the two failure paths is the smell to catch.
            state.carts[req.cart_id] = []
            return JSONResponse(
                status_code=402,
                content={"error": "payment_failed", "message": "Payment failed."},
            )

        order_id = state.new_order()
        state.orders[order_id] = "confirmed"
        state.carts[req.cart_id] = []
        return JSONResponse(status_code=200, content={"order_id": order_id, "status": "confirmed"})

    @app.post("/admin/refund")
    def refund(
        req: RefundRequest,
        x_role: Annotated[str | None, Header(alias="X-Role")] = None,
    ) -> Response:
        if x_role != "admin":
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if req.order_id not in state.orders:
            return JSONResponse(status_code=404, content={"error": "unknown_order"})
        state.orders[req.order_id] = "refunded"
        return JSONResponse(
            status_code=200, content={"order_id": req.order_id, "status": "refunded"}
        )

    # Imported here, not at module scope: demo.ui reads CATALOG/ShopState from this
    # module, so a top-level import would be circular.
    from demo.ui import register_ui

    register_ui(app, state)

    return app


#: Module-level instance so `uvicorn demo.app:app` works.
app = create_app()
