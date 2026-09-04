"""Diff parsing, symbol overlap, scoring, and budget selection.

Like the anchor tests, every test builds its own source tree under `tmp_path`.
Diffs are written against that tree with line numbers looked up at runtime
(`line_of`), so editing the fixture source cannot silently invalidate a hunk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qabot.impact import (
    DIRECT_HIT_SCORE,
    FILE_HIT_SCORE,
    STALE_BONUS,
    DiffError,
    changed_symbols,
    parse_unified_diff,
    score_workflow,
    select_workflows,
)
from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    KnowledgeBase,
    Workflow,
    WorkflowStatus,
)
from qabot.routemap import RouteMap, RouteSource

APP_SOURCE = """\
from fastapi import FastAPI

app = FastAPI()


@app.post("/cart/items")
def add_item(item_id: str) -> dict:
    total = price_of(item_id)
    return {"ok": True, "total": total}


@app.post("/checkout")
async def checkout_submit(token: str) -> dict:
    return {"status": "ok", "token": token}


def price_of(sku: str) -> int:
    return len(sku)


class CartService:
    def total(self) -> int:
        return 0
"""


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "app.py").write_text(APP_SOURCE)
    (tmp_path / "demo" / "ui").mkdir()
    (tmp_path / "demo" / "ui" / "cart.tsx").write_text("export const Cart = () => null;\n")
    return tmp_path


def line_of(source_root: Path, rel: str, needle: str) -> int:
    for number, line in enumerate((source_root / rel).read_text().splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not found in {rel}")


def edit(rel: str, start: int, replaced: int, lines: list[str]) -> str:
    """A minimal but well-formed diff replacing `replaced` lines at `start`."""
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{rel} b/{rel}\n"
        f"index 1111111..2222222 100644\n"
        f"--- a/{rel}\n"
        f"+++ b/{rel}\n"
        f"@@ -{start},{replaced} +{start},{len(lines)} @@\n"
        f"{body}"
    )


# --- parse_unified_diff -----------------------------------------------------


def test_parses_a_single_hunk_onto_new_side_line_numbers() -> None:
    diff = (
        "diff --git a/demo/app.py b/demo/app.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/demo/app.py\n"
        "+++ b/demo/app.py\n"
        "@@ -6,4 +6,5 @@ app = FastAPI()\n"
        ' @app.post("/cart/items")\n'
        " def add_item(item_id: str) -> dict:\n"
        "-    total = price_of(item_id)\n"
        "+    total = price_of(item_id) * 2\n"
        "+    assert total >= 0\n"
        '     return {"ok": True, "total": total}\n'
    )
    assert parse_unified_diff(diff) == {"demo/app.py": {8, 9}}


def test_parses_multiple_hunks_in_one_file() -> None:
    diff = (
        "diff --git a/demo/app.py b/demo/app.py\n"
        "--- a/demo/app.py\n"
        "+++ b/demo/app.py\n"
        "@@ -1,2 +1,3 @@\n"
        " from fastapi import FastAPI\n"
        "+import logging\n"
        " \n"
        "@@ -17,2 +18,2 @@\n"
        "-def price_of(sku: str) -> int:\n"
        "+def price_of(sku: str, currency: str) -> int:\n"
        "     return len(sku)\n"
    )
    assert parse_unified_diff(diff) == {"demo/app.py": {2, 18}}


def test_parses_multiple_files() -> None:
    diff = edit("demo/app.py", 8, 1, ["    total = 0"]) + edit(
        "demo/helpers.py", 3, 1, ["def price_of(sku): ...", "# note"]
    )
    assert parse_unified_diff(diff) == {"demo/app.py": {8}, "demo/helpers.py": {3, 4}}


def test_parses_an_added_file() -> None:
    diff = (
        "diff --git a/demo/new.py b/demo/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/demo/new.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def brand_new() -> None:\n"
        "+    pass\n"
        "+\n"
    )
    assert parse_unified_diff(diff) == {"demo/new.py": {1, 2, 3}}


def test_parses_a_removed_file_as_a_touched_path_with_no_lines() -> None:
    """A deleted file has no new side to number, but file-level anchors into it
    must still register as impact -- so it is present with an empty set."""
    diff = (
        "diff --git a/demo/old.py b/demo/old.py\n"
        "deleted file mode 100644\n"
        "--- a/demo/old.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-def gone() -> None:\n"
        "-    pass\n"
    )
    assert parse_unified_diff(diff) == {"demo/old.py": set()}


def test_parses_a_rename_with_no_content_change() -> None:
    diff = (
        "diff --git a/demo/old.py b/demo/new.py\n"
        "similarity index 100%\n"
        "rename from demo/old.py\n"
        "rename to demo/new.py\n"
    )
    assert parse_unified_diff(diff) == {"demo/old.py": set(), "demo/new.py": set()}


def test_ignores_the_no_newline_marker() -> None:
    diff = (
        "--- a/demo/app.py\n"
        "+++ b/demo/app.py\n"
        "@@ -18,1 +18,1 @@\n"
        "-    return len(sku)\n"
        "+    return len(sku) + 1\n"
        "\\ No newline at end of file\n"
    )
    assert parse_unified_diff(diff) == {"demo/app.py": {18}}


def test_strips_timestamps_from_headers() -> None:
    diff = (
        "--- a/demo/app.py\t2026-08-27 10:00:00.000000000 +0000\n"
        "+++ b/demo/app.py\t2026-08-27 10:01:00.000000000 +0000\n"
        "@@ -8,1 +8,1 @@\n"
        "+    total = 0\n"
    )
    assert parse_unified_diff(diff) == {"demo/app.py": {8}}


def test_empty_diff_is_empty() -> None:
    assert parse_unified_diff("") == {}


def test_malformed_hunk_header_raises() -> None:
    diff = "--- a/demo/app.py\n+++ b/demo/app.py\n@@ nonsense @@\n+x\n"
    with pytest.raises(DiffError, match="malformed hunk header"):
        parse_unified_diff(diff)


def test_hunk_before_any_file_header_raises() -> None:
    with pytest.raises(DiffError, match="before any file header"):
        parse_unified_diff("@@ -1,1 +1,1 @@\n+x\n")


# --- changed_symbols --------------------------------------------------------


def test_symbol_and_route_detected_from_a_body_edit(source_root: Path) -> None:
    body = line_of(source_root, "demo/app.py", "total = price_of")
    symbols = changed_symbols({"demo/app.py": {body}}, source_root)

    assert symbols == {"demo/app.py::add_item", "add_item", "POST /cart/items"}


def test_decorator_edit_counts_as_touching_the_function(source_root: Path) -> None:
    """The `def` line is untouched, but changing the decorator changes the route."""
    decorator = line_of(source_root, "demo/app.py", '@app.post("/checkout")')
    symbols = changed_symbols({"demo/app.py": {decorator}}, source_root)

    assert symbols == {
        "demo/app.py::checkout_submit",
        "checkout_submit",
        "POST /checkout",
    }


def test_non_overlapping_definitions_are_not_reported(source_root: Path) -> None:
    body = line_of(source_root, "demo/app.py", "return len(sku)")
    symbols = changed_symbols({"demo/app.py": {body}}, source_root)

    assert symbols == {"demo/app.py::price_of", "price_of"}


def test_method_edit_reports_both_method_and_enclosing_class(source_root: Path) -> None:
    body = line_of(source_root, "demo/app.py", "return 0")
    symbols = changed_symbols({"demo/app.py": {body}}, source_root)

    assert symbols == {
        "demo/app.py::total",
        "total",
        "demo/app.py::CartService",
        "CartService",
    }


def test_module_level_edit_reports_no_symbols(source_root: Path) -> None:
    assert changed_symbols({"demo/app.py": {1}}, source_root) == set()


def test_deleted_and_non_python_and_missing_paths_are_skipped(source_root: Path) -> None:
    diff = {
        "demo/app.py": set(),  # deleted: no new-side lines
        "demo/ui/cart.tsx": {1},  # not Python
        "demo/vanished.py": {1, 2},  # not in the checkout
    }
    assert changed_symbols(diff, source_root) == set()


# --- score_workflow ---------------------------------------------------------


def workflow(
    wid: str,
    *anchors: Anchor,
    criticality: Criticality = Criticality.MEDIUM,
    status: WorkflowStatus = WorkflowStatus.ACTIVE,
) -> Workflow:
    return Workflow(
        id=wid,
        name=f"workflow {wid}",
        anchors=list(anchors),
        criticality=criticality,
        status=status,
    )


def route(locator: str) -> Anchor:
    return Anchor(kind=AnchorKind.ROUTE, locator=locator)


def symbol(locator: str) -> Anchor:
    return Anchor(kind=AnchorKind.SYMBOL, locator=locator)


def file_anchor(locator: str) -> Anchor:
    return Anchor(kind=AnchorKind.FILE, locator=locator)


APP_DIFF = {"demo/app.py": {8}}
APP_SYMBOLS = {"demo/app.py::add_item", "add_item", "POST /cart/items"}


def test_route_hit_scores_a_direct_hit_only() -> None:
    """A route anchor names no file, so it collects the 2.0 and nothing else."""
    wf = workflow("wf", route("POST /cart/items"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 2.0


def test_a_symbol_hit_is_not_added_to_its_own_file_being_touched() -> None:
    """The file hit is implied by the symbol hit -- a function's file is touched
    whenever the function is. Adding them would score the same evidence twice."""
    wf = workflow("wf", symbol("demo/app.py::add_item"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == DIRECT_HIT_SCORE


def test_bare_symbol_hit_has_no_file_component() -> None:
    wf = workflow("wf", symbol("add_item"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 2.0


def test_file_anchor_scores_the_file_level_hit() -> None:
    wf = workflow("wf", file_anchor("demo/app.py"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 1.0


def test_directory_component_anchor_matches_a_file_beneath_it() -> None:
    wf = workflow("wf", Anchor(kind=AnchorKind.COMPONENT, locator="demo/ui"))
    assert score_workflow(wf, {"demo/ui/cart.tsx": {1}}, set()) == 1.0


def test_a_weaker_anchor_never_adds_to_a_stronger_one() -> None:
    """Dominance, not accumulation. A workflow directly implicated by the diff is
    scored on that, and file-level coincidence alongside it changes nothing."""
    wf = workflow("wf", route("POST /cart/items"), file_anchor("demo/app.py"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == DIRECT_HIT_SCORE


def test_specificity_outranks_breadth() -> None:
    """The rule the budget depends on, pinned.

    A workflow whose only subject is the changed route must outrank one that calls it
    and happens to touch bystander routes in the same file. Under the summing rule this
    replaced, breadth won -- so under a budget the tests most about a change were
    exactly the ones that did not run.
    """
    focused = workflow("focused", route("POST /cart/items"))
    broad = workflow(
        "broad",
        route("POST /cart/items"),
        file_anchor("demo/app.py"),
        file_anchor("demo/ui.py"),
    )
    assert score_workflow(focused, APP_DIFF, APP_SYMBOLS) >= score_workflow(
        broad, APP_DIFF, APP_SYMBOLS
    )


def test_untouched_symbol_in_a_touched_file_still_scores_the_file() -> None:
    wf = workflow("wf", symbol("demo/app.py::price_of"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 1.0


@pytest.mark.parametrize(
    ("criticality", "expected"),
    [(Criticality.HIGH, 3.0), (Criticality.MEDIUM, 2.0), (Criticality.LOW, 1.2)],
)
def test_criticality_multiplies_the_base_score(criticality: Criticality, expected: float) -> None:
    wf = workflow("wf", route("POST /cart/items"), criticality=criticality)
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == pytest.approx(expected)


def test_stale_workflows_get_a_bonus_on_top_of_the_multiplier() -> None:
    wf = workflow(
        "wf",
        route("POST /cart/items"),
        criticality=Criticality.HIGH,
        status=WorkflowStatus.STALE,
    )
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == pytest.approx(3.0 + STALE_BONUS)


def test_unimplicated_workflow_scores_zero() -> None:
    wf = workflow("wf", route("GET /orders"), symbol("demo/orders.py::list_orders"))
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 0.0


def test_stale_bonus_does_not_lift_an_unimplicated_workflow() -> None:
    """Otherwise every stale workflow in the knowledge base would be selected on
    every diff and drown the budget in work the diff never touched."""
    wf = workflow("wf", route("GET /orders"), status=WorkflowStatus.STALE)
    assert score_workflow(wf, APP_DIFF, APP_SYMBOLS) == 0.0


def test_anchorless_workflow_scores_zero() -> None:
    assert score_workflow(workflow("wf"), APP_DIFF, APP_SYMBOLS) == 0.0


# --- select_workflows -------------------------------------------------------


def build_kb() -> KnowledgeBase:
    return KnowledgeBase(
        repo="acme/shop",
        workflows=[
            # 2.0 direct + 1.0 file, HIGH -> 4.5
            workflow("wf-cart", symbol("demo/app.py::add_item"), criticality=Criticality.HIGH),
            # 2.0 direct, MEDIUM -> 2.0
            workflow("wf-route", route("POST /cart/items")),
            # 1.0 file, MEDIUM -> 1.0
            workflow("wf-file", file_anchor("demo/app.py")),
            # untouched
            workflow("wf-orders", route("GET /orders")),
            # touched but retired
            workflow(
                "wf-retired",
                symbol("demo/app.py::add_item"),
                criticality=Criticality.HIGH,
                status=WorkflowStatus.RETIRED,
            ),
        ],
    )


def diff_text(source_root: Path) -> str:
    body = line_of(source_root, "demo/app.py", "total = price_of")
    return edit("demo/app.py", body, 1, ["    total = price_of(item_id) * 2"])


def test_selection_is_ordered_by_score_descending(source_root: Path) -> None:
    selected, skipped = select_workflows(build_kb(), diff_text(source_root), source_root, 10)

    assert [w.id for w in selected] == ["wf-cart", "wf-route", "wf-file"]
    assert skipped == []


def test_zero_scoring_and_retired_workflows_appear_nowhere(source_root: Path) -> None:
    selected, skipped = select_workflows(build_kb(), diff_text(source_root), source_root, 10)

    assert "wf-orders" not in [w.id for w in selected] + skipped
    assert "wf-retired" not in [w.id for w in selected] + skipped


def test_budget_truncation_is_reported_not_silent(source_root: Path) -> None:
    selected, skipped = select_workflows(build_kb(), diff_text(source_root), source_root, 1)

    assert [w.id for w in selected] == ["wf-cart"]
    assert skipped == ["wf-route", "wf-file"]


def test_budget_larger_than_the_field_skips_nothing(source_root: Path) -> None:
    selected, skipped = select_workflows(build_kb(), diff_text(source_root), source_root, 99)

    assert len(selected) == 3
    assert skipped == []


def test_ties_are_broken_by_workflow_id(source_root: Path) -> None:
    kb = KnowledgeBase(
        repo="acme/shop",
        workflows=[
            workflow("wf-zulu", route("POST /cart/items")),
            workflow("wf-alpha", route("POST /cart/items")),
            workflow("wf-mike", route("POST /cart/items")),
        ],
    )
    selected, skipped = select_workflows(kb, diff_text(source_root), source_root, 2)

    assert [w.id for w in selected] == ["wf-alpha", "wf-mike"]
    assert skipped == ["wf-zulu"]


def test_selection_is_deterministic_across_calls(source_root: Path) -> None:
    diff = diff_text(source_root)
    first = select_workflows(build_kb(), diff, source_root, 2)
    second = select_workflows(build_kb(), diff, source_root, 2)

    assert [w.id for w in first[0]] == [w.id for w in second[0]]
    assert first[1] == second[1]


def test_an_empty_diff_selects_nothing(source_root: Path) -> None:
    assert select_workflows(build_kb(), "", source_root, 5) == ([], [])


def test_a_deleted_file_still_selects_its_file_anchored_workflows(source_root: Path) -> None:
    """The strongest possible drift signal must not fall through the cracks."""
    diff = (
        "diff --git a/demo/app.py b/demo/app.py\n"
        "deleted file mode 100644\n"
        "--- a/demo/app.py\n"
        "+++ /dev/null\n"
        "@@ -1,1 +0,0 @@\n"
        "-from fastapi import FastAPI\n"
    )
    selected, _ = select_workflows(build_kb(), diff, source_root, 10)

    assert [w.id for w in selected] == ["wf-cart", "wf-file"]


def test_a_budget_below_one_raises(source_root: Path) -> None:
    with pytest.raises(ValueError, match="budget must be at least 1"):
        select_workflows(build_kb(), diff_text(source_root), source_root, 0)


# --- with a route map -------------------------------------------------------
#
# The case the source-text route matcher cannot reach: paths composed from a
# namespace prefix, declared on a class, with the id a test used baked into the
# anchor. Nothing here is inferable from the decorator; all of it is inferable from
# the running application, which is what a RouteMap holds.

NAMESPACE_SOURCE = """\
challenges = Namespace("challenges")


@challenges.route("/<challenge_id>")
class Challenge:
    def get(self, challenge_id):
        return {"id": challenge_id}


@challenges.route("/attempt")
class ChallengeAttempt:
    def post(self):
        return {"status": "correct"}
"""


@pytest.fixture
def namespace_root(tmp_path: Path) -> Path:
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "challenges.py").write_text(NAMESPACE_SOURCE)
    return tmp_path


def namespace_map(namespace_root: Path) -> RouteMap:
    def span(needle: str) -> RouteSource:
        start = line_of(namespace_root, "api/challenges.py", needle)
        return RouteSource(file="api/challenges.py", start=start, end=start + 2)

    return RouteMap(
        sources={
            "GET /api/v1/challenges/{}": span("def get"),
            "POST /api/v1/challenges/attempt": span("def post"),
        }
    )


def attempt_diff(namespace_root: Path) -> str:
    body = line_of(namespace_root, "api/challenges.py", '"status": "correct"')
    return edit("api/challenges.py", body, 1, ['        return {"status": "wrong"}'])


def test_a_route_the_decorator_matcher_cannot_read_is_still_a_direct_hit(
    namespace_root: Path,
) -> None:
    diff = parse_unified_diff(attempt_diff(namespace_root))

    assert changed_symbols(diff, namespace_root) & {"POST /api/v1/challenges/attempt"} == set()
    assert "POST /api/v1/challenges/attempt" in changed_symbols(
        diff, namespace_root, namespace_map(namespace_root)
    )


def test_an_anchor_carrying_a_concrete_id_scores_only_with_the_route_table(
    namespace_root: Path,
) -> None:
    """`GET /api/v1/challenges/1` is what a test called; `/{challenge_id}` is what the
    app serves. Without the table they are unrelated strings."""
    wf = workflow("wf", route("GET /api/v1/challenges/1"))
    route_map = namespace_map(namespace_root)
    get_diff = parse_unified_diff(
        edit(
            "api/challenges.py",
            line_of(namespace_root, "api/challenges.py", 'return {"id"'),
            1,
            ['        return {"id": int(challenge_id)}'],
        )
    )

    without = score_workflow(wf, get_diff, changed_symbols(get_diff, namespace_root))
    with_map = score_workflow(
        wf, get_diff, changed_symbols(get_diff, namespace_root, route_map), route_map
    )

    assert without == 0.0
    assert with_map == DIRECT_HIT_SCORE


def test_a_route_map_gives_a_route_anchor_the_file_it_had_no_way_to_name(
    namespace_root: Path,
) -> None:
    """A route anchor names no file on its own. With the table it names the module
    that serves it, so churn around the handler registers as impact -- which is the
    signal the seeder's FILE anchors were meant to carry and cannot, because every one
    of them points at the test the workflow was seeded from."""
    wf = workflow("wf", route("GET /api/v1/challenges/1"))
    route_map = namespace_map(namespace_root)
    diff = parse_unified_diff(attempt_diff(namespace_root))  # a *different* handler

    assert score_workflow(wf, diff, changed_symbols(diff, namespace_root, route_map)) == 0.0
    assert (
        score_workflow(wf, diff, changed_symbols(diff, namespace_root, route_map), route_map)
        == FILE_HIT_SCORE
    )


def test_selection_goes_from_nothing_to_the_workflows_that_call_the_route(
    namespace_root: Path,
) -> None:
    """CTFd in miniature, and the whole point: same knowledge base, same diff, zero
    selected without the route table and the right ones with it."""
    kb = KnowledgeBase(
        repo="acme/ctf",
        workflows=[
            workflow("wf-attempt", route("POST /api/v1/challenges/attempt")),
            workflow("wf-detail", route("GET /api/v1/challenges/1")),
            workflow("wf-elsewhere", route("GET /api/v1/teams/1")),
        ],
    )
    diff = attempt_diff(namespace_root)

    blind, _ = select_workflows(kb, diff, namespace_root, 10)
    seeing, _ = select_workflows(kb, diff, namespace_root, 10, namespace_map(namespace_root))

    assert [w.id for w in blind] == []
    assert [w.id for w in seeing] == ["wf-attempt", "wf-detail"]


def test_an_anchor_to_a_route_the_app_no_longer_serves_stays_unmatched(
    namespace_root: Path,
) -> None:
    """Falling back to the literal rather than to the nearest pattern. A route that
    has gone is the staleness pass's business, not something to quietly re-point."""
    wf = workflow("wf", route("GET /api/v1/challenges/1/hints"))
    route_map = namespace_map(namespace_root)
    diff = parse_unified_diff(attempt_diff(namespace_root))

    assert (
        score_workflow(wf, diff, changed_symbols(diff, namespace_root, route_map), route_map) == 0.0
    )
