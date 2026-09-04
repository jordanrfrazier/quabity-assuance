"""Anchor resolution and the staleness pass.

Every test builds its own throwaway source tree under `tmp_path`, so this file
depends on nothing but `qabot.models` and `qabot.anchors`. The tree is a small
FastAPI-shaped module because that is the shape the route rules target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qabot.anchors import (
    STALE_CONFIDENCE_CAP,
    AnchorError,
    resolve_anchor,
    resolve_workflow,
    staleness_pass,
    staleness_question_id,
)
from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    Expectation,
    KnowledgeBase,
    Provenance,
    Workflow,
    WorkflowStatus,
)

APP_SOURCE = """\
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.post("/cart/items")
def add_item(item_id: str) -> dict:
    return {"ok": True, "item_id": item_id}


@router.get("/cart")
def view_cart() -> dict:
    return {"items": []}


@app.post("/checkout/")
async def checkout_submit(token: str) -> dict:
    # A route that exists only in a comment: @app.post("/ghost")
    ROUTE_IN_A_STRING = "@app.post('/phantom')"
    return {"status": "ok", "note": ROUTE_IN_A_STRING, "token": token}


class CartService:
    def total(self) -> int:
        return 0
"""

HELPERS_SOURCE = """\
def price_of(sku: str) -> int:
    return len(sku)
"""

HIDDEN_SOURCE = """\
app = None


@app.post("/venv/only")
def should_not_be_indexed() -> None:
    return None
"""


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "__init__.py").write_text("")
    (tmp_path / "demo" / "app.py").write_text(APP_SOURCE)
    (tmp_path / "demo" / "helpers.py").write_text(HELPERS_SOURCE)
    (tmp_path / "demo" / "ui").mkdir()
    (tmp_path / "demo" / "ui" / "cart.tsx").write_text("export const Cart = () => null;\n")
    # Both must be invisible to the walker.
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "hidden.py").write_text(HIDDEN_SOURCE)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text(HIDDEN_SOURCE)
    return tmp_path


def anchor(kind: AnchorKind, locator: str) -> Anchor:
    return Anchor(kind=kind, locator=locator)


# --- ROUTE ------------------------------------------------------------------


def test_route_resolves_via_app_decorator(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.ROUTE, "POST /cart/items"), source_root)


def test_route_resolves_via_router_decorator(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.ROUTE, "GET /cart"), source_root)


def test_route_resolves_on_async_def(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.ROUTE, "POST /checkout"), source_root)


def test_route_locator_is_normalized(source_root: Path) -> None:
    # Lowercase method, trailing slash: same route.
    assert resolve_anchor(anchor(AnchorKind.ROUTE, "post /checkout/"), source_root)
    assert resolve_anchor(anchor(AnchorKind.ROUTE, "POST /cart/items/"), source_root)


def test_route_with_wrong_method_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.ROUTE, "GET /cart/items"), source_root)


def test_missing_route_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.ROUTE, "POST /cart/gone"), source_root)


def test_route_in_comment_or_string_does_not_resolve(source_root: Path) -> None:
    """The reason resolution is AST-based: a regex would call both of these healthy."""
    assert not resolve_anchor(anchor(AnchorKind.ROUTE, "POST /ghost"), source_root)
    assert not resolve_anchor(anchor(AnchorKind.ROUTE, "POST /phantom"), source_root)


def test_route_inside_skipped_dir_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.ROUTE, "POST /venv/only"), source_root)


def test_malformed_route_locator_raises(source_root: Path) -> None:
    for bad in ("/cart/items", "POST", "POST /a /b", "FETCH /cart", "POST cart"):
        with pytest.raises(AnchorError):
            resolve_anchor(anchor(AnchorKind.ROUTE, bad), source_root)


# --- SYMBOL -----------------------------------------------------------------


def test_qualified_symbol_resolves(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.SYMBOL, "demo/app.py::checkout_submit"), source_root)


def test_qualified_symbol_resolves_for_class_and_method(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.SYMBOL, "demo/app.py::CartService"), source_root)
    assert resolve_anchor(anchor(AnchorKind.SYMBOL, "demo/app.py::total"), source_root)


def test_bare_symbol_resolves_from_any_file(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.SYMBOL, "price_of"), source_root)


def test_symbol_in_the_wrong_file_does_not_resolve(source_root: Path) -> None:
    """`price_of` exists, just not there. Right name, wrong home, still drift."""
    assert not resolve_anchor(anchor(AnchorKind.SYMBOL, "demo/app.py::price_of"), source_root)


def test_symbol_in_a_missing_file_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.SYMBOL, "demo/gone.py::add_item"), source_root)


def test_missing_symbol_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.SYMBOL, "renamed_checkout"), source_root)


def test_symbol_inside_skipped_dir_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.SYMBOL, "should_not_be_indexed"), source_root)


def test_malformed_symbol_locator_raises(source_root: Path) -> None:
    for bad in ("::name", "demo/app.py::", "  "):
        with pytest.raises(AnchorError):
            resolve_anchor(anchor(AnchorKind.SYMBOL, bad), source_root)


# --- FILE / COMPONENT -------------------------------------------------------


def test_file_anchor_resolves(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.FILE, "demo/app.py"), source_root)
    assert resolve_anchor(anchor(AnchorKind.FILE, "./demo/helpers.py"), source_root)


def test_missing_file_anchor_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.FILE, "demo/checkout.py"), source_root)


def test_component_anchor_resolves_for_non_python_paths(source_root: Path) -> None:
    assert resolve_anchor(anchor(AnchorKind.COMPONENT, "demo/ui/cart.tsx"), source_root)
    assert resolve_anchor(anchor(AnchorKind.COMPONENT, "demo/ui"), source_root)


def test_missing_component_anchor_does_not_resolve(source_root: Path) -> None:
    assert not resolve_anchor(anchor(AnchorKind.COMPONENT, "demo/ui/Checkout.tsx"), source_root)


# --- source tree failures ---------------------------------------------------


def test_missing_source_root_raises(tmp_path: Path) -> None:
    with pytest.raises(AnchorError, match="source root"):
        resolve_anchor(anchor(AnchorKind.FILE, "demo/app.py"), tmp_path / "nope")


def test_unparseable_source_file_raises(source_root: Path) -> None:
    """A file we cannot parse is a hole in the drift sensor, not a resolution
    failure -- anchors into it would be reported as drift that is really our bug."""
    (source_root / "demo" / "broken.py").write_text("def oops(:\n")
    with pytest.raises(AnchorError, match="cannot parse"):
        resolve_anchor(anchor(AnchorKind.SYMBOL, "add_item"), source_root)


# --- resolve_workflow -------------------------------------------------------


def workflow(wid: str, *anchors: Anchor, **kwargs: object) -> Workflow:
    return Workflow(
        id=wid,
        name=f"workflow {wid}",
        anchors=list(anchors),
        **kwargs,  # type: ignore[arg-type]
    )


def test_resolve_workflow_reports_only_the_broken_anchors(source_root: Path) -> None:
    good = anchor(AnchorKind.ROUTE, "POST /cart/items")
    bad_symbol = anchor(AnchorKind.SYMBOL, "demo/app.py::renamed_checkout")
    bad_file = anchor(AnchorKind.FILE, "demo/gone.py")
    wf = workflow("wf-cart", good, bad_symbol, bad_file)

    unresolved = resolve_workflow(wf, source_root)

    assert [a.locator for a in unresolved] == [bad_symbol.locator, bad_file.locator]
    assert good.resolved is True
    assert bad_symbol.resolved is False
    assert bad_file.resolved is False


def test_resolve_workflow_repairs_a_stale_resolved_flag(source_root: Path) -> None:
    """`resolved` records what *this* run found, so a previously-false flag on an
    anchor that now resolves must flip back."""
    healed = Anchor(kind=AnchorKind.ROUTE, locator="GET /cart", resolved=False)
    assert resolve_workflow(workflow("wf-cart", healed), source_root) == []
    assert healed.resolved is True


# --- staleness_pass ---------------------------------------------------------


def expectation(eid: str, confidence: float) -> Expectation:
    return Expectation(
        id=eid,
        statement="the cart totals correctly",
        provenance=Provenance.HUMAN_CONFIRMED,
        confidence=confidence,
    )


def build_kb() -> KnowledgeBase:
    return KnowledgeBase(
        repo="acme/shop",
        workflows=[
            workflow(
                "wf-healthy",
                anchor(AnchorKind.ROUTE, "POST /cart/items"),
                anchor(AnchorKind.SYMBOL, "demo/app.py::add_item"),
                expectations=[expectation("exp-healthy", 0.9)],
            ),
            workflow(
                "wf-broken",
                anchor(AnchorKind.ROUTE, "POST /checkout"),
                anchor(AnchorKind.SYMBOL, "demo/app.py::renamed_checkout"),
                anchor(AnchorKind.FILE, "demo/gone.py"),
                expectations=[expectation("exp-high", 0.95), expectation("exp-low", 0.2)],
                criticality=Criticality.HIGH,
            ),
            workflow(
                "wf-retired",
                anchor(AnchorKind.SYMBOL, "demo/app.py::long_gone"),
                status=WorkflowStatus.RETIRED,
                expectations=[expectation("exp-retired", 0.8)],
            ),
        ],
    )


def test_staleness_pass_marks_only_drifted_workflows(source_root: Path) -> None:
    kb = build_kb()
    stale_ids, _ = staleness_pass(kb, source_root)

    assert stale_ids == ["wf-broken"]
    assert kb.workflow("wf-healthy").status is WorkflowStatus.ACTIVE
    assert kb.workflow("wf-broken").status is WorkflowStatus.STALE


def test_staleness_pass_sets_resolved_flags_in_place(source_root: Path) -> None:
    kb = build_kb()
    staleness_pass(kb, source_root)

    healthy = kb.workflow("wf-healthy")
    assert [a.resolved for a in healthy.anchors] == [True, True]
    broken = kb.workflow("wf-broken")
    assert [a.resolved for a in broken.anchors] == [True, False, False]


def test_staleness_pass_emits_one_question_per_broken_locator(source_root: Path) -> None:
    kb = build_kb()
    _, questions = staleness_pass(kb, source_root)

    assert len(questions) == 2
    assert {q.workflow_id for q in questions} == {"wf-broken"}
    assert all(q.trigger == "staleness_pass" for q in questions)
    assert all(q.blocking is False for q in questions)
    assert all(q.status == "open" for q in questions)
    # Each question names the locator that actually broke.
    assert "demo/app.py::renamed_checkout" in questions[0].question
    assert "demo/gone.py" in questions[1].question


def test_staleness_pass_question_ids_are_deterministic(source_root: Path) -> None:
    """Same drift, same ids -- otherwise every CI run adds duplicate questions."""
    first_ids = [q.id for q in staleness_pass(build_kb(), source_root)[1]]
    second_ids = [q.id for q in staleness_pass(build_kb(), source_root)[1]]

    assert first_ids == second_ids
    assert len(set(first_ids)) == 2
    assert all(qid.startswith("oq-stale-wf-broken-") for qid in first_ids)
    assert first_ids[0] == staleness_question_id("wf-broken", "demo/app.py::renamed_checkout")


def test_staleness_pass_does_not_append_to_the_knowledge_base(source_root: Path) -> None:
    """The runner emits questions; the curator applies them."""
    kb = build_kb()
    _, questions = staleness_pass(kb, source_root)

    assert questions
    assert kb.open_questions == []


def test_staleness_pass_caps_confidence_of_stale_expectations(source_root: Path) -> None:
    kb = build_kb()
    staleness_pass(kb, source_root)

    broken = {e.id: e.confidence for e in kb.workflow("wf-broken").expectations}
    assert broken["exp-high"] == STALE_CONFIDENCE_CAP  # lowered
    assert broken["exp-low"] == 0.2  # already below the cap, untouched
    assert kb.workflow("wf-healthy").expectations[0].confidence == 0.9


def test_staleness_pass_is_idempotent(source_root: Path) -> None:
    """Running twice must not compound the confidence penalty."""
    kb = build_kb()
    first_ids, first_questions = staleness_pass(kb, source_root)
    second_ids, second_questions = staleness_pass(kb, source_root)

    assert first_ids == second_ids
    assert [q.id for q in first_questions] == [q.id for q in second_questions]
    assert kb.workflow("wf-broken").expectations[0].confidence == STALE_CONFIDENCE_CAP


def test_staleness_pass_leaves_retired_workflows_alone(source_root: Path) -> None:
    """Promoting a retired workflow to STALE would make impact analysis select it
    again, resurrecting work someone deliberately retired."""
    kb = build_kb()
    stale_ids, questions = staleness_pass(kb, source_root)

    retired = kb.workflow("wf-retired")
    assert "wf-retired" not in stale_ids
    assert retired.status is WorkflowStatus.RETIRED
    assert retired.anchors[0].resolved is True  # untouched default, not re-resolved
    assert retired.expectations[0].confidence == 0.8
    assert all(q.workflow_id != "wf-retired" for q in questions)


def test_staleness_pass_on_a_clean_tree_reports_nothing(source_root: Path) -> None:
    kb = KnowledgeBase(
        repo="acme/shop",
        workflows=[workflow("wf-ok", anchor(AnchorKind.COMPONENT, "demo/ui/cart.tsx"))],
    )
    assert staleness_pass(kb, source_root) == ([], [])
