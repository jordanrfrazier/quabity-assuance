"""Tests for regression test emission.

The generated file is a permanent artifact in someone else's repository, so these
tests care about three things above all: that nothing unverified leaks into it,
that each assertion grades the response it was actually verified against, and that
what does get written actually runs. The last few prove the third point the only
way it can be proved -- by running the generated module against a stub app with
real pytest, once per replay mode.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from qabot.models import (
    Expectation,
    Finding,
    Outcome,
    Provenance,
    RunReport,
    Severity,
    StepResult,
    WorkflowResult,
)
from qabot.testgen import emit_tests, render_test_module

CHECKABLE = Expectation(
    id="e_status",
    statement="an expired card is declined with 402",
    provenance=Provenance.HUMAN_CONFIRMED,
    check={"kind": "status", "value": 402},
)

PROSE_ONLY = Expectation(
    id="e_prose",
    statement="the decline message reads like a human wrote it",
    provenance=Provenance.INFERRED_FROM_CODE,
)


def _step(
    intent: str,
    *,
    request: dict[str, object],
    hint: dict[str, object] | None,
    body: dict[str, object],
    status: int,
    outcome: Outcome = Outcome.PASS,
) -> StepResult:
    """A StepResult shaped exactly as `HttpDriver` and `runner` record one."""
    evidence: dict[str, object] = {
        "status": status,
        "json": body,
        "text": json.dumps(body),
        "request": request,
        "elapsed_ms": 1.5,
    }
    if hint is not None:
        evidence["hint"] = hint
    return StepResult(intent=intent, outcome=outcome, detail="", evidence=evidence)


CREATE_ORDER = _step(
    "create an order",
    request={"method": "POST", "path": "/orders", "json": {"sku": "widget"}},
    hint={
        "method": "POST",
        "path": "/orders",
        "json": {"sku": "widget"},
        # {var_name: dotted response field} -- the planner's reading, per the lead.
        "capture": {"order": "id"},
    },
    body={"id": "o1"},
    status=201,
)

PAY_ORDER = _step(
    "pay with an expired card",
    request={"method": "POST", "path": "/orders/o1/pay", "json": {"card": "4000"}},
    hint={"method": "POST", "path": "/orders/{order}/pay", "json": {"card": "4000"}},
    body={"error": "card_expired", "items": [1, 2]},
    status=402,
)

#: The same two steps as the runner records them when a model resolved the step and
#: no hint existed: the templated form never existed, so only the request survives.
CREATE_ORDER_CONCRETE = _step(
    "create an order",
    request={"method": "POST", "path": "/orders", "json": {"sku": "widget"}},
    hint=None,
    body={"id": "o1"},
    status=201,
)

PAY_ORDER_CONCRETE = _step(
    "pay with an expired card",
    request={"method": "POST", "path": "/orders/o1/pay", "json": {"card": "4000"}},
    hint=None,
    body={"error": "card_expired", "items": [1, 2]},
    status=402,
)


def _result(
    outcome: Outcome,
    *,
    workflow_id: str = "wf_checkout",
    workflow_name: str = "Checkout with an expired card",
    steps: list[StepResult] | None = None,
    verified: list[Expectation] | None = None,
    findings: list[Finding] | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        outcome=outcome,
        steps=steps if steps is not None else [CREATE_ORDER, PAY_ORDER],
        verified_expectations=verified if verified is not None else [CHECKABLE],
        findings=findings or [],
    )


def _blocked_finding(statement: str, workflow_id: str = "wf_checkout") -> Finding:
    return Finding(
        workflow_id=workflow_id,
        workflow_name="Checkout with an expired card",
        severity=Severity.QUESTION,
        outcome=Outcome.BLOCKED,
        statement=statement,
        detail="prose-only expectation; no model available to evaluate it offline",
        provenance=Provenance.INFERRED_FROM_CODE,
    )


def _report(results: list[WorkflowResult]) -> RunReport:
    return RunReport(repo="acme/shop", base_ref="main", head_ref="pr-482", results=results)


# --------------------------------------------------------------------------
# Which workflows contribute
# --------------------------------------------------------------------------


def test_passing_and_blocked_workflows_are_emitted_but_failing_ones_are_not() -> None:
    """BLOCKED means "we could not check everything", not "something contradicted
    us", so the expectations it did verify are still confirmed behavior."""
    source = render_test_module(
        [
            _result(Outcome.PASS, workflow_id="wf_pass"),
            _result(Outcome.BLOCKED, workflow_id="wf_blocked"),
            _result(Outcome.FAIL, workflow_id="wf_fail"),
        ]
    )

    assert "def test_wf_pass()" in source
    assert "def test_wf_blocked()" in source
    assert "def test_wf_fail()" not in source


def test_a_failing_workflow_contributes_nothing_and_says_why() -> None:
    source = render_test_module(
        [
            _result(
                Outcome.FAIL,
                workflow_id="wf_fail",
                verified=[
                    Expectation(
                        id="e_leak",
                        statement="this must not be committed",
                        provenance=Provenance.HUMAN_CONFIRMED,
                        check={"kind": "status", "value": 200},
                    )
                ],
            )
        ]
    )

    assert "this must not be committed" not in source
    assert "def test_" not in source
    assert "wf_fail: the run found a failure here" in source
    assert "not safe to codify" in source


def test_a_blocked_workflow_only_replays_the_steps_that_ran() -> None:
    never_ran = _step(
        "fetch the receipt",
        request={"method": "GET", "path": "/receipt", "json": None},
        hint={"method": "GET", "path": "/receipt"},
        body={},
        status=0,
        outcome=Outcome.BLOCKED,
    )
    source = render_test_module(
        [_result(Outcome.BLOCKED, steps=[CREATE_ORDER, PAY_ORDER, never_ran])]
    )

    assert "def test_wf_checkout()" in source
    assert "/receipt" not in source
    assert "fetch the receipt" not in source
    assert "response_2" not in source


def test_a_blocked_workflow_says_in_its_docstring_what_was_not_checked() -> None:
    source = render_test_module(
        [
            _result(
                Outcome.BLOCKED,
                findings=[_blocked_finding("the receipt lists the declined card")],
            )
        ]
    )

    assert "could not check everything in this workflow" in source
    assert "covers only the part that was verified" in source
    assert "- the receipt lists the declined card" in source
    compile(source, "<generated>", "exec")


def test_a_passing_workflow_docstring_makes_no_such_caveat() -> None:
    source = render_test_module([_result(Outcome.PASS)])
    assert "could not check everything" not in source


def test_a_workflow_where_nothing_ran_is_dropped_with_a_note() -> None:
    blocked_immediately = StepResult(
        intent="create an order",
        outcome=Outcome.BLOCKED,
        detail="connection refused",
        evidence={},
    )
    source = render_test_module([_result(Outcome.BLOCKED, steps=[blocked_immediately])])

    assert "def test_" not in source
    assert "no step of this workflow completed" in source


# --------------------------------------------------------------------------
# Which expectations become assertions
# --------------------------------------------------------------------------


def test_prose_only_expectations_are_excluded_with_an_explanation() -> None:
    source = render_test_module([_result(Outcome.PASS, verified=[PROSE_ONLY])])

    assert "def test_wf_checkout()" not in source
    assert "the decline message reads like a human wrote it" not in source
    assert "# Verified but NOT asserted here:" in source
    assert "wf_checkout: every verified expectation is prose-only" in source
    assert "not stable enough to commit" in source


def test_a_workflow_keeps_its_checkable_expectations_and_drops_the_prose_ones() -> None:
    source = render_test_module([_result(Outcome.PASS, verified=[CHECKABLE, PROSE_ONLY])])

    assert "assert response_1.status_code == 402" in source
    assert "the decline message reads like a human wrote it" not in source


def test_every_check_kind_renders_a_readable_assertion() -> None:
    verified = [
        Expectation(
            id="e1",
            statement="s1",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "status", "value": 402},
        ),
        Expectation(
            id="e2",
            statement="s2",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "json_eq", "path": "error", "value": "card_expired"},
        ),
        Expectation(
            id="e3",
            statement="s3",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "json_contains", "path": "error", "value": "expired"},
        ),
        Expectation(
            id="e4",
            statement="s4",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "json_len_gt", "path": "items", "value": 1},
        ),
    ]
    source = render_test_module([_result(Outcome.PASS, verified=verified)])

    assert "assert response_1.status_code == 402" in source
    assert "assert _dig(response_1.json(), 'error') == 'card_expired'" in source
    assert "assert 'expired' in _dig(response_1.json(), 'error')" in source
    assert "assert len(_dig(response_1.json(), 'items')) > 1" in source


def test_an_unknown_check_kind_fails_loudly_rather_than_shrinking_coverage() -> None:
    verified = [
        Expectation(
            id="e_new",
            statement="something new",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "screenshot_matches", "value": "home.png"},
        )
    ]
    with pytest.raises(ValueError, match="screenshot_matches"):
        render_test_module([_result(Outcome.PASS, verified=verified)])


# --------------------------------------------------------------------------
# Which response each assertion grades
# --------------------------------------------------------------------------


def test_step_index_binds_an_assertion_to_its_own_step() -> None:
    verified = [
        Expectation(
            id="e_created",
            statement="creating an order returns 201",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "status", "value": 201},
            step_index=0,
        ),
        CHECKABLE,
    ]
    source = render_test_module([_result(Outcome.PASS, verified=verified)])

    assert "assert response_0.status_code == 201" in source
    assert "assert response_1.status_code == 402" in source
    assert "# graded against step 0: create an order" in source
    assert "# graded against step 1: pay with an expired card" in source


def test_an_unbound_expectation_grades_the_last_response() -> None:
    assert CHECKABLE.step_index is None
    source = render_test_module([_result(Outcome.PASS)])

    assert "assert response_1.status_code == 402" in source
    assert "response_0.status_code" not in source


def test_a_step_index_past_the_steps_that_ran_fails_loudly() -> None:
    """A malformed report, not something to guess around: grading the right claim
    against the wrong response is the cry-wolf failure this product prevents."""
    verified = [
        Expectation(
            id="e_far",
            statement="the receipt is mailed",
            provenance=Provenance.HUMAN_CONFIRMED,
            check={"kind": "status", "value": 200},
            step_index=7,
        )
    ]
    with pytest.raises(ValueError, match="bound to step 7"):
        render_test_module([_result(Outcome.PASS, verified=verified)])


# --------------------------------------------------------------------------
# Replay fidelity
# --------------------------------------------------------------------------


def test_unreplayable_steps_drop_the_whole_workflow_with_a_note() -> None:
    """A partial replay that still asserts the ending is a test that lies, so the
    workflow is dropped whole rather than half-emitted."""
    no_request_recorded = StepResult(
        intent="sign in as a returning customer",
        outcome=Outcome.PASS,
        detail="",
        evidence={"note": "seeded out of band"},
    )
    source = render_test_module([_result(Outcome.PASS, steps=[no_request_recorded, PAY_ORDER])])

    assert "def test_wf_checkout()" not in source
    assert "no recorded request for step(s) 'sign in as a returning customer'" in source
    assert "replayed faithfully" in source


def test_placeholders_and_captures_are_threaded_when_the_run_recorded_hints() -> None:
    source = render_test_module([_result(Outcome.PASS)])

    assert "captured: dict[str, object] = {}" in source
    assert "captured['order'] = _dig(response_0.json(), 'id')" in source
    assert "str(_fill('/orders/{order}/pay', captured))" in source
    assert "json=_fill({'card': '4000'}, captured)" in source
    # The concrete id minted during the generating run must not be baked in.
    assert "/orders/o1/pay" not in source


def test_concrete_replay_is_used_and_flagged_when_a_step_had_no_hint() -> None:
    source = render_test_module(
        [_result(Outcome.PASS, steps=[CREATE_ORDER_CONCRETE, PAY_ORDER_CONCRETE])]
    )

    assert "'/orders/o1/pay'," in source
    assert "_fill(" not in source
    assert "captured" not in source
    assert "resolved some of these steps with a model" in source
    assert "hard-coded here and may not exist in a later" in source


def test_headers_are_replayed_when_the_driver_recorded_them() -> None:
    step = _step(
        "call as an authenticated customer",
        request={
            "method": "GET",
            "path": "/me",
            "json": None,
            "headers": {"Authorization": "Bearer t"},
        },
        hint=None,
        body={"id": "u1"},
        status=200,
    )
    source = render_test_module([_result(Outcome.PASS, steps=[step])])

    assert "headers={'Authorization': 'Bearer t'}," in source
    assert "json=" not in source


# --------------------------------------------------------------------------
# The file itself
# --------------------------------------------------------------------------


def test_generated_source_compiles() -> None:
    source = render_test_module([_result(Outcome.PASS), _result(Outcome.PASS, workflow_id="wf-2")])
    compile(source, "<generated>", "exec")


def test_awkward_ids_and_names_still_compile() -> None:
    source = render_test_module(
        [
            _result(
                Outcome.PASS,
                workflow_id="wf-checkout/expired card",
                workflow_name='Checkout with a """quoted""" \\ name\nacross lines',
            )
        ]
    )
    compile(source, "<generated>", "exec")
    assert "def test_wf_checkout_expired_card()" in source


def test_unused_helpers_are_left_out_of_the_generated_file() -> None:
    """A committed file should not carry dead code a reviewer has to reason about."""
    status_only = Expectation(
        id="e_status_only",
        statement="the page loads",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "status", "value": 200},
    )
    step = _step(
        "load the page",
        request={"method": "GET", "path": "/", "json": None},
        hint=None,
        body={},
        status=200,
    )
    source = render_test_module([_result(Outcome.PASS, steps=[step], verified=[status_only])])

    assert "def _fill(" not in source
    assert "def _dig(" not in source
    compile(source, "<generated>", "exec")


def test_emit_tests_names_the_run_and_the_file() -> None:
    files = emit_tests(_report([_result(Outcome.PASS)]))

    assert set(files) == {"test_qa_generated.py"}
    source = files["test_qa_generated.py"]
    assert "# Generated by qabot." in source
    assert "# Run: acme/shop main -> pr-482" in source
    assert "observed and verified against the running" in source
    compile(source, "<generated>", "exec")


def test_emit_tests_honours_the_module_name() -> None:
    files = emit_tests(_report([_result(Outcome.PASS)]), module_name="checkout_regressions")
    assert set(files) == {"test_checkout_regressions.py"}


def test_emit_tests_writes_nothing_when_only_failures_ran() -> None:
    assert emit_tests(_report([_result(Outcome.FAIL)])) == {}
    assert emit_tests(_report([])) == {}


# --------------------------------------------------------------------------
# End to end: the generated module against a real app
# --------------------------------------------------------------------------


class _StubHandler(BaseHTTPRequestHandler):
    """The smallest app that makes the generated replay meaningful."""

    def do_POST(self) -> None:  # BaseHTTPRequestHandler dictates the name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/orders":
            self._respond(201, {"id": "o1"})
        elif self.path == "/orders/o1/pay":
            self._respond(402, {"error": "card_expired", "items": [1, 2]})
        else:
            self._respond(404, {"error": f"no route for {self.path}"})

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def stub_app() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run_generated(source: str, tmp_path: Path, base_url: str) -> subprocess.CompletedProcess[str]:
    target = tmp_path / "test_qa_generated.py"
    target.write_text(source)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "BASE_URL": base_url},
    )


#: Deliberately mixes a step-0-bound expectation with unbound ones. If step_index
#: were ignored, the 201 would be graded against the 402 response and this fails.
VERIFIED_CHECKOUT = [
    Expectation(
        id="e_created",
        statement="creating an order returns 201",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "status", "value": 201},
        step_index=0,
    ),
    CHECKABLE,
    Expectation(
        id="e_error",
        statement="the error names the expired card",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "json_eq", "path": "error", "value": "card_expired"},
    ),
    Expectation(
        id="e_msg",
        statement="the error mentions expiry",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "json_contains", "path": "error", "value": "expired"},
    ),
    Expectation(
        id="e_items",
        statement="the declined order still lists its items",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "json_len_gt", "path": "items", "value": 1},
    ),
]


def test_templated_replay_runs_against_the_app(stub_app: str, tmp_path: Path) -> None:
    files = emit_tests(_report([_result(Outcome.PASS, verified=VERIFIED_CHECKOUT)]))
    completed = _run_generated(files["test_qa_generated.py"], tmp_path, stub_app)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_concrete_replay_runs_against_the_app(stub_app: str, tmp_path: Path) -> None:
    files = emit_tests(
        _report(
            [
                _result(
                    Outcome.PASS,
                    steps=[CREATE_ORDER_CONCRETE, PAY_ORDER_CONCRETE],
                    verified=VERIFIED_CHECKOUT,
                )
            ]
        )
    )
    completed = _run_generated(files["test_qa_generated.py"], tmp_path, stub_app)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_a_blocked_workflows_generated_test_runs(stub_app: str, tmp_path: Path) -> None:
    files = emit_tests(
        _report(
            [
                _result(
                    Outcome.BLOCKED,
                    verified=VERIFIED_CHECKOUT,
                    findings=[_blocked_finding("the receipt lists the declined card")],
                )
            ]
        )
    )
    completed = _run_generated(files["test_qa_generated.py"], tmp_path, stub_app)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_generated_tests_fail_when_the_app_stops_behaving(stub_app: str, tmp_path: Path) -> None:
    """The point of committing these: if the behavior changes, the test goes red."""
    wrong = Expectation(
        id="e_wrong",
        statement="an expired card is declined with 402",
        provenance=Provenance.HUMAN_CONFIRMED,
        check={"kind": "status", "value": 200},
    )
    files = emit_tests(_report([_result(Outcome.PASS, verified=[wrong])]))
    completed = _run_generated(files["test_qa_generated.py"], tmp_path, stub_app)

    assert completed.returncode == 1
    assert "an expired card is declined with 402" in completed.stdout
