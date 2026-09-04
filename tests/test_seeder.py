"""Tests for cold-start seeding.

Two kinds of input. The real `demo/e2e/test_shop_flows.py` is the fixture that matters:
it is written the way a customer writes a suite, and it is what the seeder must survive
unaided. Small inline snippets written to `tmp_path` cover the shapes the demo suite does
not contain -- a missing docstring, an uncapturable placeholder, an assert nobody can
translate -- and the failures the seeder must refuse loudly rather than guess through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qabot.anchors import build_index, resolve_against_index
from qabot.models import AnchorKind, Criticality, OpenQuestion, Provenance, Severity, Workflow
from qabot.seeder import SeedError, seed_from_test_file, seed_knowledge_base

DEMO_SUITE = Path(__file__).resolve().parents[1] / "demo" / "e2e" / "test_shop_flows.py"

REPO = "demo-shop"


@pytest.fixture(scope="module")
def demo_workflows() -> list[Workflow]:
    return seed_from_test_file(DEMO_SUITE, REPO)


def workflow(workflows: list[Workflow], wid: str) -> Workflow:
    found = next((w for w in workflows if w.id == wid), None)
    assert found is not None, f"{wid} not among {[w.id for w in workflows]}"
    return found


def write_snippet(tmp_path: Path, source: str, name: str = "test_snippet.py") -> Path:
    """A source string on disk, as if it were a file in the customer's suite."""
    path = tmp_path / name
    path.write_text(source)
    return path


def seed_snippet(tmp_path: Path, source: str, name: str = "test_snippet.py") -> list[Workflow]:
    """Seed from a source string, discarding any questions it raised."""
    return seed_from_test_file(write_snippet(tmp_path, source, name), REPO)


# --- workflow extraction -------------------------------------------------------------


def test_one_workflow_per_top_level_test_function(demo_workflows: list[Workflow]) -> None:
    assert [w.id for w in demo_workflows] == [
        "wf_add_item_to_cart",
        "wf_checkout_with_valid_card",
        "wf_checkout_with_expired_card_preserves_cart",
        "wf_unknown_sku_returns_404",
    ]


def test_non_test_functions_are_not_workflows(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        '''
def make_cart(client):
    """A helper, not a flow anyone promised."""
    return client.post("/cart/items", json={"sku": "widget", "qty": 1})


def test_real_flow(client):
    """The only flow here."""
    resp = client.get("/health")
    assert resp.status_code == 200
''',
    )
    assert [w.id for w in workflows] == ["wf_real_flow"]


def test_name_is_the_docstrings_first_line(demo_workflows: list[Workflow]) -> None:
    assert workflow(demo_workflows, "wf_add_item_to_cart").name == (
        "A shopper adds a widget to an empty cart and sees it priced in the cart."
    )


def test_name_falls_back_to_humanized_function_name(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        """
def test_add_item_to_cart(client):
    resp = client.get("/health")
    assert resp.status_code == 200
""",
    )
    assert workflows[0].name == "Add item to cart"


def test_source_ref_is_project_relative(demo_workflows: list[Workflow]) -> None:
    assert workflow(demo_workflows, "wf_unknown_sku_returns_404").source_ref == (
        "demo/e2e/test_shop_flows.py::test_unknown_sku_returns_404"
    )


# --- criticality ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("func_name", "docstring", "expected"),
    [
        ("test_checkout_happy_path", "A shopper buys a thing.", Criticality.HIGH),
        ("test_card_refused", "The payment is declined.", Criticality.HIGH),
        ("test_login", "The user authenticates before seeing the account.", Criticality.HIGH),
        ("test_browse_catalog", "A shopper looks at the product list.", Criticality.MEDIUM),
    ],
)
def test_criticality_heuristic(
    tmp_path: Path, func_name: str, docstring: str, expected: Criticality
) -> None:
    workflows = seed_snippet(
        tmp_path,
        f'''
def {func_name}(client):
    """{docstring}"""
    resp = client.get("/health")
    assert resp.status_code == 200
''',
    )
    assert workflows[0].criticality is expected


def test_demo_suite_criticality(demo_workflows: list[Workflow]) -> None:
    assert {w.id: w.criticality for w in demo_workflows} == {
        "wf_add_item_to_cart": Criticality.MEDIUM,
        "wf_checkout_with_valid_card": Criticality.HIGH,
        "wf_checkout_with_expired_card_preserves_cart": Criticality.HIGH,
        "wf_unknown_sku_returns_404": Criticality.MEDIUM,
    }


# --- steps and hints -----------------------------------------------------------------


def test_step_hint_records_method_path_and_body(demo_workflows: list[Workflow]) -> None:
    step = workflow(demo_workflows, "wf_add_item_to_cart").steps[0]
    assert step.hint == {
        "method": "POST",
        "path": "/cart/items",
        "json": {"sku": "widget", "qty": 1},
    }


def test_step_intent_reads_as_an_action(demo_workflows: list[Workflow]) -> None:
    steps = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart").steps
    assert [s.intent for s in steps] == [
        'submit /cart/items with {"sku": "widget", "qty": 3}',
        'submit /checkout/submit with {"cart_id": "{cart_id}", "card_token": "expired"}',
        "fetch /cart/{cart_id}",
    ]


def test_bodyless_call_has_no_json_in_hint(demo_workflows: list[Workflow]) -> None:
    step = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart").steps[2]
    assert "json" not in step.hint
    assert step.hint["method"] == "GET"


def test_steps_are_in_source_order(demo_workflows: list[Workflow]) -> None:
    steps = workflow(demo_workflows, "wf_checkout_with_valid_card").steps
    assert [s.hint["path"] for s in steps] == ["/cart/items", "/checkout/submit"]


def test_fstring_path_becomes_a_placeholder(demo_workflows: list[Workflow]) -> None:
    steps = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart").steps
    assert steps[2].hint["path"] == "/cart/{cart_id}"


def test_variable_body_value_becomes_a_placeholder(demo_workflows: list[Workflow]) -> None:
    """The placeholder carries the local variable's name, not the field it came from."""
    steps = workflow(demo_workflows, "wf_checkout_with_valid_card").steps
    assert steps[1].hint["json"] == {"cart_id": "{cart}", "card_token": "valid"}


# --- what counts as an HTTP request ---------------------------------------------------
#
# The snippets here are lifted from the suites that exposed the bug -- CTFd's Flask
# session dict and langflow's slashless client calls -- because a shape invented to pass
# a test proves nothing about the shape that was actually issuing phantom requests.


def test_dict_lookup_is_not_seeded_as_a_request(tmp_path: Path) -> None:
    """CTFd reads `sess.get("nonce")` off a Flask session 93 times over.

    Every one of them used to become a `GET nonce` step the bot would issue against the
    application, and any assert bound to it would be graded on a request no test made.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_setup(client):
    """An admin completes first-run setup."""
    client.get("/setup")
    with client.session_transaction() as sess:
        data = {"name": "admin", "nonce": sess.get("nonce")}
    resp = client.post("/setup", data=data)
    assert resp.status_code == 200
''',
    )
    assert [s.hint["path"] for s in workflows[0].steps] == ["/setup", "/setup"]
    assert [a.locator for a in workflows[0].anchors if a.kind is AnchorKind.ROUTE] == [
        "GET /setup",
        "POST /setup",
    ]


def test_slashless_path_is_a_request_and_gains_its_leading_slash(tmp_path: Path) -> None:
    """langflow writes `client.get("api/v1/all")` 1121 times, never with a leading slash.

    The path structure is the evidence that it is a route, so the slash is not needed to
    recognise it -- but the anchor needs one, because the run path refuses to load a
    route locator without it.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
async def test_get_all(client, logged_in_headers):
    """A user lists everything they can see."""
    response = await client.get("api/v1/all", headers=logged_in_headers)
    assert response.status_code == 200
''',
    )
    assert [s.hint["path"] for s in workflows[0].steps] == ["/api/v1/all"]
    assert [a.locator for a in workflows[0].anchors if a.kind is AnchorKind.ROUTE] == [
        "GET /api/v1/all"
    ]


def test_orm_lookup_with_a_second_positional_argument_is_not_a_request(tmp_path: Path) -> None:
    """`session.get(Flow, flow_id)` is SQLModel. No HTTP client takes a second position:
    httpx, Flask's test client and Starlette's all make everything after the URL
    keyword-only, so the arity alone settles it."""
    questions: list[object] = []
    workflows = seed_from_test_file(
        write_snippet(
            tmp_path,
            '''
def test_flow_is_stored(client, session):
    """A flow the API created is readable from the database."""
    resp = client.post("/api/v1/flows", json={"name": "f"})
    stored = session.get(Flow, resp.json()["id"])
    assert resp.status_code == 201
''',
        ),
        REPO,
        questions,
    )
    assert [s.hint["path"] for s in workflows[0].steps] == ["/api/v1/flows"]
    assert questions == []


def test_context_variable_get_is_not_a_request(tmp_path: Path) -> None:
    """`ctx.get()` names no URL at all, and langflow's suite has three of them."""
    questions: list[object] = []
    workflows = seed_from_test_file(
        write_snippet(
            tmp_path,
            '''
def test_auto_login_guard(client, authenticated_caller_ctx):
    """An unauthenticated caller is refused."""
    resp = client.get("/api/v1/mcp/projects")
    assert authenticated_caller_ctx.get() is None
    assert resp.status_code == 401
''',
        ),
        REPO,
        questions,
    )
    assert [s.hint["path"] for s in workflows[0].steps] == ["/api/v1/mcp/projects"]
    assert questions == []


def test_unclassifiable_call_becomes_a_question_and_never_a_step(tmp_path: Path) -> None:
    """`client.get(chal_uri)` might be a request; `session.delete(project)` might not.

    Nothing in either call says which, so neither is guessed. Including one fabricates a
    request; dropping it silently leaves a hole in coverage the customer thinks is
    covered. The question is the only honest third answer.
    """
    questions: list[OpenQuestion] = []
    workflows = seed_from_test_file(
        write_snippet(
            tmp_path,
            '''
def test_challenge_visibility(client, chal_uri, session, project):
    """A hidden challenge is not visible to a public user."""
    resp = client.get(chal_uri)
    session.delete(project)
    assert resp.status_code == 404
''',
        ),
        REPO,
        questions,
    )
    assert workflows[0].steps == []
    assert {q.workflow_id for q in questions} == {"wf_challenge_visibility"}
    assert sorted(q.trigger for q in questions) == ["seed", "seed"]
    asked = " ".join(q.question for q in questions)
    assert "`client.get(...)`" in asked
    assert "`session.delete(...)`" in asked


def test_absolute_url_is_a_question_because_the_host_may_not_be_the_app(
    tmp_path: Path,
) -> None:
    """CTFd writes `client.get("http://localhost/login")`; a suite could as easily call
    Stripe. Reducing either to `/login` and issuing it against the app under test would
    fabricate a request in the second case, so the host is asked about, not assumed."""
    questions: list[OpenQuestion] = []
    workflows = seed_from_test_file(
        write_snippet(
            tmp_path,
            '''
def test_redirect(client):
    """A logged-out visitor is redirected to login."""
    resp = client.get("http://localhost/login")
    assert resp.status_code == 200
''',
        ),
        REPO,
        questions,
    )
    assert workflows[0].steps == []
    assert len(questions) == 1


def test_questions_group_by_receiver_and_carry_their_call_sites(tmp_path: Path) -> None:
    """langflow deletes through `session` 70 times; a human answers "is `session` a
    client?" once. One question per receiver, with the lines attached so nobody has to
    go looking for them."""
    questions: list[OpenQuestion] = []
    seed_from_test_file(
        write_snippet(
            tmp_path,
            '''
def test_cleanup(session, flow, folder, user):
    """Deleting a project takes its flows and folders with it."""
    session.delete(flow)
    session.delete(folder)
    session.delete(user)
''',
        ),
        REPO,
        questions,
    )
    assert len(questions) == 1
    assert questions[0].candidates == [
        "test_snippet.py:4",
        "test_snippet.py:5",
        "test_snippet.py:6",
    ]


def test_question_ids_are_stable_across_reseeds(tmp_path: Path) -> None:
    """A curator answers a question once. A fresh id every run re-asks it forever."""
    source = '''
def test_cleanup(session, flow):
    """Deleting a flow."""
    session.delete(flow)
'''
    first: list[OpenQuestion] = []
    second: list[OpenQuestion] = []
    seed_from_test_file(write_snippet(tmp_path, source), REPO, first)
    seed_from_test_file(write_snippet(tmp_path, source), REPO, second)
    assert [q.id for q in first] == [q.id for q in second]
    assert first[0].id.startswith("oq-seed-wf_cleanup-")


def test_open_questions_reach_the_knowledge_base(tmp_path: Path) -> None:
    """`seed_from_test_file`'s accumulator is not the delivery mechanism; the KB is."""
    (tmp_path / "test_flows.py").write_text(
        "def test_lookup(client, url):\n    resp = client.get(url)\n"
        "    assert resp.status_code == 200\n"
    )
    kb = seed_knowledge_base(tmp_path, REPO)
    assert [q.workflow_id for q in kb.open_questions] == ["wf_lookup"]


# --- capture threading ---------------------------------------------------------------


def test_capture_recorded_on_the_step_that_produces_the_value(
    demo_workflows: list[Workflow],
) -> None:
    """The GET's `{cart_id}` is resolved back to the POST whose response held it."""
    steps = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart").steps
    assert steps[0].hint["capture"] == {"cart_id": "cart_id"}
    assert "capture" not in steps[1].hint
    assert "capture" not in steps[2].hint


def test_capture_threads_through_a_request_body_too(demo_workflows: list[Workflow]) -> None:
    steps = workflow(demo_workflows, "wf_checkout_with_valid_card").steps
    assert steps[0].hint["capture"] == {"cart": "cart_id"}


def test_capture_maps_the_variable_to_the_response_field(tmp_path: Path) -> None:
    """`capture` reads in assignment order: {variable: response_field}."""
    workflows = seed_snippet(
        tmp_path,
        '''
def test_rename(client):
    """A flow that renames the value it carries forward."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    basket = resp.json()["cart_id"]
    resp = client.get(f"/cart/{basket}")
    assert resp.status_code == 200
''',
    )
    assert workflows[0].steps[0].hint["capture"] == {"basket": "cart_id"}


def test_capture_direction_survives_a_renamed_order_id(tmp_path: Path) -> None:
    """The regression guard for the flipped-direction bug.

    Variable and field names coincide in most hand-written tests, which makes both
    readings of `capture` behave identically and hides a reversal. They must differ here.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_order_lookup(client):
    """A shopper checks out and then opens the order that came back."""
    resp = client.post("/checkout/submit", json={"cart_id": "c1", "card_token": "valid"})
    oid = resp.json()["order_id"]
    resp = client.get(f"/orders/{oid}")
    assert resp.status_code == 200
''',
    )
    steps = workflows[0].steps
    assert steps[0].hint["capture"] == {"oid": "order_id"}
    assert steps[1].hint["path"] == "/orders/{oid}"


def test_placeholder_with_no_producing_step_is_not_captured(tmp_path: Path) -> None:
    """A fixture value is not something an earlier step can hand over."""
    workflows = seed_snippet(
        tmp_path,
        '''
def test_known_cart(client, cart_id):
    """A shopper returns to a cart the fixture built."""
    resp = client.get(f"/cart/{cart_id}")
    assert resp.status_code == 200
''',
    )
    assert workflows[0].steps[0].hint == {"method": "GET", "path": "/cart/{cart_id}"}


# --- expectations --------------------------------------------------------------------


def test_status_assert_becomes_a_status_check(demo_workflows: list[Workflow]) -> None:
    expectation = workflow(demo_workflows, "wf_unknown_sku_returns_404").expectations[0]
    assert expectation.check == {"kind": "status", "value": 404}
    assert expectation.statement == "response status is 404"


def test_json_eq_assert_becomes_a_json_eq_check(demo_workflows: list[Workflow]) -> None:
    expectation = workflow(demo_workflows, "wf_unknown_sku_returns_404").expectations[1]
    assert expectation.check == {"kind": "json_eq", "path": "error", "value": "unknown_sku"}


def test_json_len_gt_assert_becomes_a_json_len_gt_check(demo_workflows: list[Workflow]) -> None:
    expectation = workflow(demo_workflows, "wf_add_item_to_cart").expectations[1]
    assert expectation.check == {"kind": "json_len_gt", "path": "items", "value": 0}


def test_json_contains_assert_becomes_a_json_contains_check(
    demo_workflows: list[Workflow],
) -> None:
    flow = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart")
    assert flow.expectations[2].check == {
        "kind": "json_contains",
        "path": "message",
        "value": "expired",
    }


def test_untranslatable_assert_is_kept_as_prose(demo_workflows: list[Workflow]) -> None:
    """The assert survives without a check; offline it will read BLOCKED, never a guess."""
    expectation = workflow(demo_workflows, "wf_checkout_with_valid_card").expectations[3]
    assert expectation.check is None
    assert expectation.statement == "the test asserts resp.json()['order_id']"


def test_nested_json_path_is_prose_not_a_wrong_check(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        '''
def test_nested(client):
    """A flow asserting into a nested response."""
    resp = client.get("/cart/abc")
    assert resp.json()["items"][0]["sku"] == "widget"
''',
    )
    assert workflows[0].expectations[0].check is None


def test_expectation_ids_are_sequential_within_the_workflow(demo_workflows: list[Workflow]) -> None:
    flow = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart")
    assert [e.id for e in flow.expectations] == [
        f"wf_checkout_with_expired_card_preserves_cart_e{n}" for n in range(1, 6)
    ]


def test_step_index_binds_each_assert_to_the_call_it_follows(
    demo_workflows: list[Workflow],
) -> None:
    """The 402 is about the checkout call, not about whatever ran last."""
    flow = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart")
    assert [(e.check, e.step_index) for e in flow.expectations] == [
        ({"kind": "status", "value": 201}, 0),
        ({"kind": "status", "value": 402}, 1),
        ({"kind": "json_contains", "path": "message", "value": "expired"}, 1),
        ({"kind": "status", "value": 200}, 2),
        ({"kind": "json_len_gt", "path": "items", "value": 0}, 2),
    ]


def test_step_index_advances_with_each_call(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        '''
def test_two_calls(client):
    """A shopper adds an item and then reads the cart back."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
    assert resp.json()["total"] == 1000
    resp = client.get("/cart/abc")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) > 0
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [0, 0, 1, 1]


def test_trailing_asserts_bind_to_the_response_they_name(tmp_path: Path) -> None:
    """Issue both requests, then assert on both -- the ordinary shape of a real suite.

    Every call precedes every assert here, so position alone cannot tell them apart and
    binds both claims to the last call. That graded `a`'s 200 against `b`'s 201 and
    reported a change against an app that behaved exactly as its test said: D31's bug,
    moved one layer up into the seed.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_two_endpoints(client):
    """A shopper reads the catalog and then adds an item."""
    catalog = client.get("/catalog")
    added = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert catalog.status_code == 200
    assert added.status_code == 201
''',
    )
    assert [(e.check, e.step_index) for e in workflows[0].expectations] == [
        ({"kind": "status", "value": 200}, 0),
        ({"kind": "status", "value": 201}, 1),
    ]


def test_rebound_name_binds_to_the_call_in_effect_at_the_assert(tmp_path: Path) -> None:
    """`resp` means a different response after every reassignment.

    A map of "the step this name was ever bound to" answers step 2 for both asserts and
    reintroduces the same wrong-evidence bug it was written to fix, so the binding has
    to be the one standing at the assert's line and no other.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_rebinding(client):
    """A shopper reads a cart, checks the catalog, then adds an item."""
    resp = client.get("/cart/abc")
    catalog = client.get("/catalog")
    assert resp.status_code == 200
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [0, 2]


def test_awaited_response_binds_to_its_call(tmp_path: Path) -> None:
    """An async suite writes the same binding through `await`, and means the same thing.

    Binding by variable has to see through the `await` or every assert in an `async def`
    test binds to nothing -- honest, but a whole suite's worth of coverage lost to a
    keyword that changes nothing about whose response it is.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
async def test_async_flow(ac):
    """A shopper reads the catalog and then adds an item."""
    catalog = await ac.get("/catalog")
    added = await ac.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert catalog.status_code == 200
    assert added.status_code == 201
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [0, 1]


def test_response_bound_by_a_with_block_binds_to_its_call(tmp_path: Path) -> None:
    """A streamed response is bound by `with ... as` and is still a response."""
    workflows = seed_snippet(
        tmp_path,
        '''
def test_streamed(client):
    """A shopper reads a cart and downloads its invoice."""
    cart = client.get("/cart/abc")
    with client.get("/cart/abc/invoice") as invoice:
        assert invoice.status_code == 200
    assert cart.status_code == 200
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [1, 0]


def test_assert_before_any_call_has_no_step_index(tmp_path: Path) -> None:
    """A precondition check describes no step of the workflow."""
    workflows = seed_snippet(
        tmp_path,
        '''
def test_leading_assert(client, sku):
    """A shopper adds an item the fixture picked."""
    assert sku == "widget"
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [None, 0]


def test_call_written_inside_an_assert_binds_to_itself(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        '''
def test_inline_call(client):
    """A shopper adds an item, then the suite pings health inline."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
    assert client.get("/health").status_code == 200
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [0, 1]


def test_assert_on_a_response_the_seeder_never_saw_binds_to_nothing(tmp_path: Path) -> None:
    """A fixture's response was produced by no step of this workflow.

    Attaching it to the nearest call would cite a response the assert never named -- the
    same false positive as binding by position, wearing a shape that looks deliberate.
    Unbound is the honest answer, and downstream it is BLOCKED rather than graded.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_fixture_response(client, seeded_cart):
    """A shopper reads a cart the fixture already filled."""
    resp = client.get("/cart/abc")
    assert seeded_cart.status_code == 201
    assert resp.status_code == 200
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [None, 0]


def test_assert_naming_no_response_falls_back_to_position(tmp_path: Path) -> None:
    """`data["id"]` reaches into a value, not into a response.

    The seeder cannot say which step produced `data`, and an assert that names no
    response at all is exactly the case the positional rule was always right about.
    """
    workflows = seed_snippet(
        tmp_path,
        '''
def test_indirect(client):
    """A shopper reads a cart through an unpacked body."""
    resp = client.get("/cart/abc")
    data = resp.json()
    assert data["id"] == "abc"
''',
    )
    assert [e.step_index for e in workflows[0].expectations] == [0]


def test_prose_expectation_is_bound_to_a_step_too(demo_workflows: list[Workflow]) -> None:
    """Being unverifiable offline is no reason to cite the wrong response."""
    expectation = workflow(demo_workflows, "wf_checkout_with_valid_card").expectations[3]
    assert expectation.check is None
    assert expectation.step_index == 1


def test_every_seeded_expectation_is_capped_at_change(demo_workflows: list[Workflow]) -> None:
    """The point of seeding: coverage on day one that may never be called a bug."""
    expectations = [e for w in demo_workflows for e in w.expectations]
    assert expectations
    assert all(e.provenance is Provenance.INFERRED_FROM_TEST for e in expectations)
    assert all(e.confidence == 0.6 for e in expectations)
    assert all(e.cap() is Severity.CHANGE for e in expectations)


# --- anchors -------------------------------------------------------------------------


def test_anchors_are_distinct_routes_plus_the_source_file(demo_workflows: list[Workflow]) -> None:
    flow = workflow(demo_workflows, "wf_checkout_with_expired_card_preserves_cart")
    assert [(a.kind, a.locator) for a in flow.anchors] == [
        (AnchorKind.ROUTE, "POST /cart/items"),
        (AnchorKind.ROUTE, "POST /checkout/submit"),
        (AnchorKind.ROUTE, "GET /cart/{cart_id}"),
        (AnchorKind.FILE, "demo/e2e/test_shop_flows.py"),
    ]


def test_repeated_route_yields_one_anchor(tmp_path: Path) -> None:
    workflows = seed_snippet(
        tmp_path,
        '''
def test_two_items(client):
    """A shopper adds two things to the same cart."""
    resp = client.post("/cart/items", json={"sku": "widget", "qty": 1})
    assert resp.status_code == 201
    resp = client.post("/cart/items", json={"sku": "gadget", "qty": 1})
    assert resp.status_code == 201
''',
    )
    routes = [a.locator for a in workflows[0].anchors if a.kind is AnchorKind.ROUTE]
    assert routes == ["POST /cart/items"]
    assert len(workflows[0].steps) == 2


# --- whole knowledge base ------------------------------------------------------------


def test_seed_knowledge_base_from_the_demo_suite() -> None:
    kb = seed_knowledge_base(DEMO_SUITE.parent, REPO)
    assert kb.repo == REPO
    assert len(kb.workflows) == 4
    assert sum(len(w.steps) for w in kb.workflows) == 7
    expectations = [e for w in kb.workflows for e in w.expectations]
    assert len(expectations) == 14
    assert sum(e.check is not None for e in expectations) == 13
    assert kb.workflow("wf_checkout_with_valid_card") is not None


def test_seed_knowledge_base_reads_every_file(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text(
        'def test_one(client):\n    resp = client.get("/a")\n    assert resp.status_code == 200\n'
    )
    (tmp_path / "test_b.py").write_text(
        'def test_two(client):\n    resp = client.get("/b")\n    assert resp.status_code == 200\n'
    )
    kb = seed_knowledge_base(tmp_path, REPO)
    assert [w.id for w in kb.workflows] == ["wf_one", "wf_two"]


def test_every_seeded_anchor_survives_the_run_paths_own_resolver(tmp_path: Path) -> None:
    """The contract the seeder broke: `qabot seed` reported success into `qabot run`'s
    crash, because `staleness_pass` resolves every anchor before anything else and
    raised on `GET nonce`. Whatever a real suite contains, what comes out of here loads.
    """
    (tmp_path / "test_shapes.py").write_text(
        "def test_mixed(client, sess, cart_id):\n"
        '    client.get("/setup")\n'
        '    nonce = sess.get("nonce")\n'
        '    client.post("api/v1/flows", json={"nonce": nonce})\n'
        '    resp = client.get(f"/cart/{cart_id}")\n'
        "    assert resp.status_code == 200\n"
    )
    kb = seed_knowledge_base(tmp_path, REPO)
    index = build_index(tmp_path)
    for workflow in kb.workflows:
        for anchor in workflow.anchors:
            resolve_against_index(anchor, index)


# --- loud failures -------------------------------------------------------------------


def test_anchor_the_run_path_cannot_load_raises_at_seed_time(tmp_path: Path) -> None:
    """A locator the resolver refuses must fail here, where the message names the test
    that produced it -- not three commands later inside somebody's CI run."""
    with pytest.raises(SeedError, match="the run path cannot load"):
        seed_snippet(
            tmp_path,
            '''
def test_search(client):
    """A shopper searches for two words."""
    resp = client.get("/search?q=red widget")
    assert resp.status_code == 200
''',
        )


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="no such test file"):
        seed_from_test_file(tmp_path / "nope.py", REPO)


def test_unparseable_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="not parseable Python"):
        seed_snippet(tmp_path, "def test_broken(:\n")


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="no e2e directory"):
        seed_knowledge_base(tmp_path / "nope", REPO)


def test_empty_directory_raises(tmp_path: Path) -> None:
    """An empty suite is a cold start we cannot fix; say so instead of shipping a shell."""
    with pytest.raises(SeedError, match="nothing to seed from"):
        seed_knowledge_base(tmp_path, REPO)


def test_duplicate_workflow_id_raises(tmp_path: Path) -> None:
    for name in ("test_a.py", "test_b.py"):
        (tmp_path / name).write_text(
            'def test_same(client):\n    resp = client.get("/a")\n    assert resp.status_code == 200\n'
        )
    with pytest.raises(SeedError, match="duplicate workflow id 'wf_same'"):
        seed_knowledge_base(tmp_path, REPO)


def test_unrenderable_path_raises(tmp_path: Path) -> None:
    """`headers=` settles that this is a request; nothing settles where it goes.

    A call we have positively identified as HTTP and still cannot render is the case
    that must stay loud. Without the `headers=`, the same line is merely unclassifiable
    and becomes an open question instead -- see the classification tests above.
    """
    with pytest.raises(SeedError, match="cannot render"):
        seed_snippet(
            tmp_path,
            '''
def test_computed_path(client, carts, auth):
    """A flow whose route the seeder cannot pin down."""
    resp = client.get(carts[0].url, headers=auth)
    assert resp.status_code == 200
''',
        )


def test_missing_path_argument_raises(tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="no positional path argument"):
        seed_snippet(
            tmp_path,
            '''
def test_kwarg_url(client):
    """A flow that names its route by keyword."""
    resp = client.get(url="/cart/abc")
    assert resp.status_code == 200
''',
        )


def test_non_literal_body_key_raises(tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="not a string literal"):
        seed_snippet(
            tmp_path,
            '''
def test_dynamic_key(client, field):
    """A flow whose request body shape is computed."""
    resp = client.post("/cart/items", json={field: "widget"})
    assert resp.status_code == 201
''',
        )
