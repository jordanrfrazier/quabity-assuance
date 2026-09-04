"""Planner tests.

The through-line: a recorded hint is followed exactly, an unresolvable step is a loud
PlanError, and nothing in between is ever invented.
"""

from __future__ import annotations

import pytest

from qabot.drivers.base import Action, Observation
from qabot.llm import DeterministicLLM, LLMError
from qabot.models import Step
from qabot.planner import PlanError, capture_variables, resolve_step


class ScriptedLLM:
    """A provider that hands back a fixed object -- stands in for a real model."""

    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str, dict]] = []

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        self.calls.append((system, prompt, schema_hint))
        return self.payload


def observation(json_body: dict | None = None, **evidence: object) -> Observation:
    body: dict[str, object] = dict(evidence)
    if json_body is not None:
        body["json"] = json_body
    return Observation(ok=True, summary="scripted", evidence=body)


# --- hint-driven resolution -------------------------------------------------------


def test_hint_becomes_an_http_action():
    step = Step(intent="check out", hint={"method": "POST", "path": "/checkout", "json": {"a": 1}})

    action = resolve_step(step, {}, DeterministicLLM())

    assert isinstance(action, Action)
    assert action.kind == "http"
    assert action.params == {"method": "POST", "path": "/checkout", "json": {"a": 1}}


def test_hint_without_a_body_carries_no_json():
    step = Step(intent="list carts", hint={"method": "GET", "path": "/carts"})

    action = resolve_step(step, {}, DeterministicLLM())

    assert action.params == {"method": "GET", "path": "/carts", "json": None}


def test_placeholder_in_path_is_substituted():
    step = Step(intent="check out", hint={"method": "POST", "path": "/cart/{cart_id}/checkout"})

    action = resolve_step(step, {"cart_id": 7}, DeterministicLLM())

    assert action.params["path"] == "/cart/7/checkout"


def test_placeholder_in_json_string_value_is_substituted():
    step = Step(
        intent="pay",
        hint={"method": "POST", "path": "/pay", "json": {"cart": "{cart_id}", "note": "n/a"}},
    )

    action = resolve_step(step, {"cart_id": "abc"}, DeterministicLLM())

    assert action.params["json"] == {"cart": "abc", "note": "n/a"}


def test_whole_string_placeholder_preserves_the_variable_type():
    """{"cart": "{cart_id}"} must send the integer 7, not the string "7"."""
    step = Step(
        intent="pay", hint={"method": "POST", "path": "/pay", "json": {"cart": "{cart_id}"}}
    )

    action = resolve_step(step, {"cart_id": 7}, DeterministicLLM())

    assert action.params["json"] == {"cart": 7}


def test_embedded_placeholder_is_stringified():
    step = Step(
        intent="pay",
        hint={"method": "POST", "path": "/pay", "json": {"ref": "cart-{cart_id}-x"}},
    )

    action = resolve_step(step, {"cart_id": 7}, DeterministicLLM())

    assert action.params["json"] == {"ref": "cart-7-x"}


def test_placeholders_are_substituted_inside_nested_structures():
    step = Step(
        intent="pay",
        hint={
            "method": "POST",
            "path": "/pay",
            "json": {"items": [{"cart": "{cart_id}"}], "meta": {"user": "{user}"}},
        },
    )

    action = resolve_step(step, {"cart_id": 7, "user": "ada"}, DeterministicLLM())

    assert action.params["json"] == {"items": [{"cart": 7}], "meta": {"user": "ada"}}


def test_missing_variable_in_path_raises_rather_than_sending_a_literal_brace():
    step = Step(intent="check out", hint={"method": "POST", "path": "/cart/{cart_id}/checkout"})

    with pytest.raises(PlanError) as exc:
        resolve_step(step, {}, DeterministicLLM())

    assert "cart_id" in str(exc.value)


def test_missing_variable_in_json_raises():
    step = Step(intent="pay", hint={"method": "POST", "path": "/pay", "json": {"c": "{cart_id}"}})

    with pytest.raises(PlanError):
        resolve_step(step, {"other": 1}, DeterministicLLM())


def test_hint_without_method_or_path_raises():
    with pytest.raises(PlanError):
        resolve_step(Step(intent="x", hint={"path": "/p"}), {}, DeterministicLLM())
    with pytest.raises(PlanError):
        resolve_step(Step(intent="x", hint={"method": "GET"}), {}, DeterministicLLM())


def test_non_placeholder_braces_are_left_alone():
    step = Step(intent="x", hint={"method": "POST", "path": "/p", "json": {"t": "a {} b"}})

    action = resolve_step(step, {}, DeterministicLLM())

    assert action.params["json"] == {"t": "a {} b"}


# --- model-driven resolution ------------------------------------------------------


def test_no_hint_offline_raises_planerror_so_the_caller_records_blocked():
    step = Step(intent="check out with an expired card")

    with pytest.raises(PlanError) as exc:
        resolve_step(step, {}, DeterministicLLM())

    assert "no model available" in str(exc.value)


def test_no_hint_offline_chains_the_llm_error():
    with pytest.raises(PlanError) as exc:
        resolve_step(Step(intent="do a thing"), {}, DeterministicLLM())

    assert isinstance(exc.value.__cause__, LLMError)


def test_no_hint_uses_the_model_and_passes_it_the_variables():
    llm = ScriptedLLM({"kind": "http", "params": {"method": "POST", "path": "/checkout"}})

    action = resolve_step(Step(intent="check out"), {"cart_id": 7}, llm)

    assert action.kind == "http"
    assert action.params == {"method": "POST", "path": "/checkout"}
    _system, prompt, schema_hint = llm.calls[0]
    assert "check out" in prompt
    assert "cart_id" in prompt
    assert "params" in schema_hint


def test_unusable_model_output_raises_planerror():
    llm = ScriptedLLM({"not": "an action"})

    with pytest.raises(PlanError):
        resolve_step(Step(intent="check out"), {}, llm)


# --- variable capture -------------------------------------------------------------


def test_capture_writes_response_fields_into_variables():
    step = Step(
        intent="create a cart",
        hint={"method": "POST", "path": "/cart", "capture": {"cart_id": "id"}},
    )
    variables: dict[str, object] = {}

    capture_variables(step, observation({"id": 7, "items": []}), variables)

    assert variables == {"cart_id": 7}


def test_capture_round_trips_into_the_next_step():
    create = Step(
        intent="create a cart",
        hint={"method": "POST", "path": "/cart", "capture": {"cart_id": "id"}},
    )
    checkout = Step(intent="check out", hint={"method": "POST", "path": "/cart/{cart_id}/checkout"})
    variables: dict[str, object] = {}

    capture_variables(create, observation({"id": "c-42"}), variables)
    action = resolve_step(checkout, variables, DeterministicLLM())

    assert action.params["path"] == "/cart/c-42/checkout"


def test_capture_reads_a_dotted_path():
    step = Step(
        intent="create",
        hint={"method": "POST", "path": "/cart", "capture": {"token": "auth.token"}},
    )
    variables: dict[str, object] = {}

    capture_variables(step, observation({"auth": {"token": "t-1"}}), variables)

    assert variables == {"token": "t-1"}


def test_capture_of_a_missing_field_raises():
    step = Step(
        intent="create", hint={"method": "POST", "path": "/cart", "capture": {"cart_id": "id"}}
    )

    with pytest.raises(PlanError) as exc:
        capture_variables(step, observation({"other": 1}), {})

    assert "id" in str(exc.value)


def test_capture_without_a_json_body_raises():
    step = Step(
        intent="create", hint={"method": "POST", "path": "/cart", "capture": {"cart_id": "id"}}
    )

    with pytest.raises(PlanError):
        capture_variables(step, observation(status=201), {})


def test_capture_is_a_noop_without_a_hint_or_capture_key():
    variables: dict[str, object] = {"kept": 1}

    capture_variables(Step(intent="x"), observation({"id": 1}), variables)
    capture_variables(
        Step(intent="x", hint={"method": "GET", "path": "/p"}), observation({"id": 1}), variables
    )

    assert variables == {"kept": 1}
