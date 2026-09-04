"""Hand-authored browser workflows for the demo.

WHY these are written by hand: the AST seeder reads an existing pytest+httpx suite.
Seeding browser workflows from an existing Playwright suite is the same idea applied
to a different fixture, and it is not built yet -- so these stand in for what that
seeder would produce, and they are written in exactly the shape it would emit.

The three workflows are chosen to exercise the three outcomes through a browser:
one FAILs on both demo defects, one PASSes cleanly, and one is BLOCKED by a control
that has no accessible name.
"""

from __future__ import annotations

from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    Expectation,
    KnowledgeBase,
    Persona,
    Provenance,
    Step,
    Workflow,
)

SHOPPER = Persona(
    id="shopper",
    name="A signed-out shopper buying one item",
    traits={"authenticated": False, "cart": "empty at start"},
    fixture={"reset": "POST /reset"},
)

_UI_ANCHORS = [
    Anchor(kind=AnchorKind.ROUTE, locator="GET /ui"),
    Anchor(kind=AnchorKind.ROUTE, locator="POST /ui/checkout"),
    Anchor(kind=AnchorKind.FILE, locator="demo/ui.py"),
]


def _add_widget_steps() -> list[Step]:
    """The shared opening: land on the shop and put one widget in the cart."""
    return [
        Step(intent="open the shop", hint={"op": "goto", "path": "/ui"}),
        Step(
            intent="choose the widget product",
            hint={"op": "select", "role": "combobox", "name": "Product", "value": "widget"},
        ),
        Step(
            intent="add it to the cart",
            hint={"op": "click", "role": "button", "name": "Add to cart"},
        ),
    ]


def browser_knowledge_base(repo: str = "demo/shop") -> KnowledgeBase:
    expired = Workflow(
        id="wf_ui_checkout_expired_card",
        name="A shopper paying with an expired card is told why, and keeps their cart.",
        persona=SHOPPER.id,
        criticality=Criticality.HIGH,
        preconditions=["the shop is reachable", "the cart starts empty"],
        steps=[
            *_add_widget_steps(),
            Step(
                intent="choose the expired saved card",
                hint={"op": "select", "role": "combobox", "name": "Card", "value": "expired"},
            ),
            Step(
                intent="place the order",
                hint={"op": "click", "role": "button", "name": "Place order"},
            ),
        ],
        expectations=[
            Expectation(
                id="wf_ui_checkout_expired_card_e1",
                statement="the error shown to the shopper says the card is expired",
                provenance=Provenance.HUMAN_CONFIRMED,
                confidence=0.95,
                # Scoped to the alert on purpose. The card <select> on this very page
                # contains an option labelled "expired", so a page-wide search would
                # pass on the exact page whose error message fails to mention it.
                check={"kind": "text_visible", "role": "alert", "value": "expired"},
                step_index=4,
            ),
            Expectation(
                id="wf_ui_checkout_expired_card_e2",
                statement="the cart survives a failed payment so the shopper can retry",
                provenance=Provenance.INFERRED_FROM_TEST,
                confidence=0.6,
                check={"kind": "text_absent", "value": "Your cart is empty"},
                step_index=4,
            ),
        ],
        anchors=list(_UI_ANCHORS),
    )

    happy = Workflow(
        id="wf_ui_checkout_valid_card",
        name="A shopper paying with a good card reaches an order confirmation.",
        persona=SHOPPER.id,
        criticality=Criticality.HIGH,
        preconditions=["the shop is reachable", "the cart starts empty"],
        steps=[
            *_add_widget_steps(),
            Step(
                intent="choose the working saved card",
                hint={"op": "select", "role": "combobox", "name": "Card", "value": "valid"},
            ),
            Step(
                intent="place the order",
                hint={"op": "click", "role": "button", "name": "Place order"},
            ),
        ],
        expectations=[
            Expectation(
                id="wf_ui_checkout_valid_card_e1",
                statement="the shopper is shown an order confirmation",
                provenance=Provenance.INFERRED_FROM_TEST,
                confidence=0.6,
                check={"kind": "text_visible", "value": "Order confirmed"},
                step_index=4,
            ),
            Expectation(
                id="wf_ui_checkout_valid_card_e2",
                statement="the confirmation quotes an order reference",
                provenance=Provenance.INFERRED_FROM_TEST,
                confidence=0.6,
                check={"kind": "text_visible", "value": "Order reference"},
                step_index=4,
            ),
        ],
        anchors=list(_UI_ANCHORS),
    )

    remove = Workflow(
        id="wf_ui_remove_item",
        name="A shopper removes an item from their cart.",
        persona=SHOPPER.id,
        criticality=Criticality.MEDIUM,
        preconditions=["the cart holds one widget"],
        steps=[
            *_add_widget_steps(),
            # The remove control is an icon-only button with no accessible name, so
            # this step cannot complete. That is the point: it reports BLOCKED with a
            # reason a developer can act on, rather than a pass or a failure.
            Step(
                intent="remove the widget from the cart",
                hint={"op": "click", "role": "button", "name": "Remove widget"},
            ),
        ],
        expectations=[
            Expectation(
                id="wf_ui_remove_item_e1",
                statement="the cart is empty after removing the only item",
                provenance=Provenance.INFERRED_FROM_TEST,
                confidence=0.6,
                check={"kind": "text_visible", "value": "Your cart is empty"},
                step_index=3,
            ),
        ],
        anchors=list(_UI_ANCHORS),
    )

    return KnowledgeBase(repo=repo, personas=[SHOPPER], workflows=[expired, happy, remove])
