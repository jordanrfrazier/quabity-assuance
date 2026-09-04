"""A browser-facing UI over the same shop state.

WHY a UI exists at all: "impersonate a real user" means a browser, and a driver you
cannot point at a page is a driver you cannot trust. This is deliberately plain
server-rendered HTML -- no client framework, no build step -- so the browser driver
is exercised against real navigation, real forms, and a real accessibility tree
rather than a fixture that flatters it.

The UI reads the SAME state and reproduces the SAME two defects as the JSON API, so
the browser run and the HTTP run should reach the same verdicts by different routes.
It adds a third, browser-only defect (an unlabeled control) described below.
"""

from __future__ import annotations

import html

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from demo.app import CARD_TOKENS, CATALOG, ShopState, cart_view

_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<h1>{heading}</h1>
{body}
</body>
</html>"""


def _page(title: str, heading: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        _PAGE.format(title=html.escape(title), heading=html.escape(heading), body=body)
    )


def _cart_body(cart_id: str, items: list[dict[str, object]], total: int, error: str | None) -> str:
    rows = []
    for index, item in enumerate(items):
        label = f"{item['qty']} x {item['sku']}"
        # DELIBERATE DEFECT (demo, browser-only): this control has no accessible
        # name -- no text, no aria-label, no title. A sighted user sees the glyph;
        # a screen reader user and any role+name locator find nothing. A workflow
        # that tries to remove an item therefore goes BLOCKED with "no accessible
        # control", which is simultaneously a real accessibility bug. BLOCKED
        # earning its keep is the point.
        rows.append(
            f"<li>{html.escape(label)} "
            f'<form method="post" action="/ui/cart/{html.escape(cart_id)}/remove" '
            f'style="display:inline">'
            f'<input type="hidden" name="index" value="{index}">'
            f'<button type="submit">&#10005;</button>'
            f"</form></li>"
        )
    items_html = f"<ul>{''.join(rows)}</ul>" if rows else "<p>Your cart is empty.</p>"

    error_html = f'<p role="alert">{html.escape(error)}</p>' if error else ""

    card_options = "".join(
        f'<option value="{html.escape(token)}">{html.escape(token)}</option>'
        for token in sorted(CARD_TOKENS)
    )

    return f"""{error_html}
{items_html}
<p>Total: {total} cents</p>
<form method="post" action="/ui/checkout">
  <input type="hidden" name="cart_id" value="{html.escape(cart_id)}">
  <label for="card">Card</label>
  <select id="card" name="card_token">{card_options}</select>
  <button type="submit">Place order</button>
</form>
<p><a href="/ui">Continue shopping</a></p>"""


def register_ui(app: FastAPI, state: ShopState) -> None:
    """Mount the browser UI onto an existing app, sharing its state object."""

    @app.get("/ui")
    def shop() -> Response:
        options = "".join(
            f'<option value="{html.escape(sku)}">{html.escape(sku)} ({price} cents)</option>'
            for sku, price in sorted(CATALOG.items())
        )
        body = f"""<form method="post" action="/ui/cart/items">
  <label for="sku">Product</label>
  <select id="sku" name="sku">{options}</select>
  <label for="qty">Quantity</label>
  <input id="qty" name="qty" type="number" value="1" min="1">
  <button type="submit">Add to cart</button>
</form>"""
        return _page("Shop", "Shop", body)

    @app.post("/ui/cart/items")
    def ui_add_item(
        sku: str = Form(...), qty: int = Form(...), cart_id: str | None = Form(None)
    ) -> Response:
        if sku not in CATALOG:
            return _page("Shop", "Shop", '<p role="alert">We do not sell that.</p>')
        target = cart_id if cart_id in state.carts else state.new_cart()
        state.carts.setdefault(target, [])
        state.carts[target].append({"sku": sku, "qty": qty, "price": CATALOG[sku]})
        return RedirectResponse(url=f"/ui/cart/{target}", status_code=303)

    @app.get("/ui/cart/{cart_id}")
    def ui_cart(cart_id: str, error: str | None = None) -> Response:
        if cart_id not in state.carts:
            return _page("Cart", "Cart", '<p role="alert">We could not find that cart.</p>')
        view = cart_view(cart_id, state.carts[cart_id])
        return _page("Cart", "Your cart", _cart_body(cart_id, view["items"], view["total"], error))

    @app.post("/ui/cart/{cart_id}/remove")
    def ui_remove(cart_id: str, index: int = Form(...)) -> Response:
        if cart_id in state.carts and 0 <= index < len(state.carts[cart_id]):
            state.carts[cart_id].pop(index)
        return RedirectResponse(url=f"/ui/cart/{cart_id}", status_code=303)

    @app.post("/ui/checkout")
    def ui_checkout(cart_id: str = Form(...), card_token: str = Form(...)) -> Response:
        if cart_id not in state.carts:
            return _page("Cart", "Cart", '<p role="alert">We could not find that cart.</p>')

        if card_token == "declined":
            # Matches the JSON API: a decline preserves the cart so the shopper can retry.
            return _page(
                "Cart",
                "Your cart",
                _cart_body(
                    cart_id,
                    cart_view(cart_id, state.carts[cart_id])["items"],
                    cart_view(cart_id, state.carts[cart_id])["total"],
                    "Card was declined.",
                ),
            )

        if card_token == "expired":
            # DELIBERATE DEFECT (demo): the same two defects as the JSON API, reached
            # through the UI. The message never names the card as expired (-> BUG
            # against a human-confirmed expectation), and the cart is cleared on this
            # failure path unlike "declined" above (-> CHANGE). A browser run and an
            # HTTP run should therefore reach the same verdicts by different routes.
            state.carts[cart_id] = []
            return _page(
                "Cart",
                "Your cart",
                _cart_body(cart_id, [], 0, "Payment failed."),
            )

        order_id = state.new_order()
        state.orders[order_id] = "confirmed"
        state.carts[cart_id] = []
        body = f"<p>Order confirmed</p><p>Order reference: {html.escape(order_id)}</p>"
        return _page("Order confirmed", "Order confirmed", body)
