"""Verifier tests.

Three things are worth breaking the build over: the provenance cap holds for every
provenance, BLOCKED is never laundered into PASS or FAIL, and only confirmed
expectations reach `verified_expectations`.
"""

from __future__ import annotations

import pytest

from qabot.drivers.base import Observation
from qabot.llm import DeterministicLLM
from qabot.models import (
    PROVENANCE_CAP,
    Expectation,
    Outcome,
    Provenance,
    Severity,
    Step,
    StepResult,
    Workflow,
)
from qabot.verifier import (
    evaluate_check,
    evaluate_expectation,
    severity_for,
    verify_workflow,
)


class ScriptedLLM:
    """A provider that returns a fixed verdict -- stands in for a real model."""

    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        return self.payload


def observation(status: int = 200, json_body: dict | None = None) -> Observation:
    evidence: dict[str, object] = {"status": status}
    if json_body is not None:
        evidence["json"] = json_body
    return Observation(ok=True, summary=f"HTTP {status}", evidence=evidence)


def expectation(
    provenance: Provenance = Provenance.HUMAN_CONFIRMED, check: dict | None = None
) -> Expectation:
    return Expectation(
        id="e1", statement="checkout is rejected", provenance=provenance, check=check
    )


# --- evaluate_check: every kind, passing and failing -------------------------------


def test_status_check_passes():
    passed, detail = evaluate_check({"kind": "status", "value": 402}, observation(status=402))
    assert passed is True
    assert "402" in detail


def test_status_check_fails_and_reports_actual_versus_expected():
    passed, detail = evaluate_check({"kind": "status", "value": 402}, observation(status=200))
    assert passed is False
    assert "expected status 402" in detail and "got 200" in detail


def test_status_check_fails_when_no_status_was_recorded():
    bare = Observation(ok=True, summary="nothing", evidence={})
    passed, detail = evaluate_check({"kind": "status", "value": 402}, bare)
    assert passed is False
    assert "no status" in detail


def test_json_eq_passes_and_fails():
    obs = observation(json_body={"error": "card_expired"})
    assert evaluate_check({"kind": "json_eq", "path": "error", "value": "card_expired"}, obs)[0]
    failed, detail = evaluate_check({"kind": "json_eq", "path": "error", "value": "declined"}, obs)
    assert failed is False
    assert "card_expired" in detail


def test_json_eq_traverses_a_dotted_path():
    obs = observation(json_body={"payment": {"card": {"state": "expired"}}})
    check = {"kind": "json_eq", "path": "payment.card.state", "value": "expired"}
    assert evaluate_check(check, obs)[0] is True


def test_json_eq_fails_on_an_absent_path_rather_than_raising():
    obs = observation(json_body={"error": "card_expired"})
    passed, detail = evaluate_check({"kind": "json_eq", "path": "missing", "value": 1}, obs)
    assert passed is False
    assert "absent" in detail


def test_json_eq_fails_when_the_path_runs_through_a_non_object():
    obs = observation(json_body={"error": "card_expired"})
    check = {"kind": "json_eq", "path": "error.deeper", "value": 1}
    assert evaluate_check(check, obs)[0] is False


def test_json_contains_is_case_insensitive():
    obs = observation(json_body={"message": "Your Card Has EXPIRED"})
    assert evaluate_check({"kind": "json_contains", "path": "message", "value": "expired"}, obs)[0]


def test_json_contains_fails_when_absent():
    obs = observation(json_body={"message": "all good"})
    passed, detail = evaluate_check(
        {"kind": "json_contains", "path": "message", "value": "expired"}, obs
    )
    assert passed is False
    assert "all good" in detail


def test_json_len_gt_passes_and_fails():
    obs = observation(json_body={"items": [1, 2]})
    assert evaluate_check({"kind": "json_len_gt", "path": "items", "value": 0}, obs)[0] is True
    assert evaluate_check({"kind": "json_len_gt", "path": "items", "value": 5}, obs)[0] is False


def test_json_len_gt_on_an_empty_list_fails():
    obs = observation(json_body={"items": []})
    passed, detail = evaluate_check({"kind": "json_len_gt", "path": "items", "value": 0}, obs)
    assert passed is False
    assert "got 0" in detail


def test_json_len_gt_fails_on_an_unsized_value():
    obs = observation(json_body={"items": 3})
    passed, detail = evaluate_check({"kind": "json_len_gt", "path": "items", "value": 0}, obs)
    assert passed is False
    assert "sized" in detail


def test_unknown_check_kind_raises():
    with pytest.raises(ValueError) as exc:
        evaluate_check({"kind": "vibes", "value": 1}, observation())
    assert "vibes" in str(exc.value)


def test_check_missing_its_kind_raises():
    with pytest.raises(ValueError):
        evaluate_check({"path": "error", "value": 1}, observation())


def test_malformed_check_raises_rather_than_silently_failing():
    with pytest.raises(ValueError):
        evaluate_check({"kind": "json_eq", "value": 1}, observation(json_body={}))
    with pytest.raises(ValueError):
        evaluate_check({"kind": "status"}, observation())


# --- evaluate_expectation ---------------------------------------------------------


def test_checked_expectation_passes_and_fails_deterministically():
    exp = expectation(check={"kind": "status", "value": 402})
    assert evaluate_expectation(exp, observation(402), DeterministicLLM())[0] == Outcome.PASS
    assert evaluate_expectation(exp, observation(200), DeterministicLLM())[0] == Outcome.FAIL


def test_prose_only_expectation_is_blocked_offline():
    """Offline we say "couldn't check". We never guess a pass and never invent a bug."""
    outcome, detail = evaluate_expectation(expectation(), observation(402), DeterministicLLM())

    assert outcome == Outcome.BLOCKED
    assert detail == "prose-only expectation; no model available to evaluate it offline"


def test_prose_only_expectation_is_judged_when_a_model_is_available():
    exp = expectation()
    held = ScriptedLLM({"held": True, "reason": "the response rejected the card"})
    broke = ScriptedLLM({"held": False, "reason": "checkout succeeded"})

    assert evaluate_expectation(exp, observation(402), held) == (
        Outcome.PASS,
        "the response rejected the card",
    )
    assert evaluate_expectation(exp, observation(200), broke) == (
        Outcome.FAIL,
        "checkout succeeded",
    )


def test_an_unusable_model_verdict_is_blocked_not_guessed():
    outcome, detail = evaluate_expectation(expectation(), observation(), ScriptedLLM({"x": 1}))

    assert outcome == Outcome.BLOCKED
    assert "no usable verdict" in detail


# --- the provenance cap -----------------------------------------------------------


@pytest.mark.parametrize(
    ("provenance", "expected"),
    [
        (Provenance.HUMAN_CONFIRMED, Severity.BUG),
        (Provenance.OBSERVED_IN_RUN, Severity.REGRESSION),
        (Provenance.INFERRED_FROM_TEST, Severity.CHANGE),
        (Provenance.INFERRED_FROM_CODE, Severity.QUESTION),
    ],
)
def test_severity_is_capped_by_provenance(provenance: Provenance, expected: Severity):
    assert severity_for(expectation(provenance)) == expected


def test_every_provenance_has_a_cap():
    """A new provenance without a cap must fail loudly, not default to something loud."""
    for provenance in Provenance:
        assert severity_for(expectation(provenance)) == PROVENANCE_CAP[provenance]


def test_confidence_does_not_move_the_cap():
    """A confident model does not get to promote an inference into a bug."""
    exp = Expectation(
        id="e",
        statement="s",
        provenance=Provenance.INFERRED_FROM_CODE,
        confidence=0.99,
    )
    assert severity_for(exp) == Severity.QUESTION


# --- verify_workflow --------------------------------------------------------------


def workflow(*expectations: Expectation) -> Workflow:
    """Two steps: index 0 creates a cart, index 1 checks out."""
    return Workflow(
        id="w1",
        name="Checkout",
        steps=[Step(intent="create a cart"), Step(intent="check out")],
        expectations=list(expectations),
    )


def bound(step_index: int | None, check: dict | None = None, **kwargs: object) -> Expectation:
    return Expectation(
        id=kwargs.pop("id", "e1"),
        statement=kwargs.pop("statement", "checkout is rejected"),
        provenance=kwargs.pop("provenance", Provenance.HUMAN_CONFIRMED),
        check=check,
        step_index=step_index,
    )


def ran(*intents: str, outcome: Outcome = Outcome.PASS) -> list[StepResult]:
    return [StepResult(intent=intent, outcome=outcome) for intent in intents]


BOTH_STEPS = ran("create a cart", "check out")


def test_a_passing_workflow_passes_and_records_the_verified_expectation():
    wf = workflow(bound(1, {"kind": "status", "value": 402}))

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert result.outcome == Outcome.PASS
    assert result.findings == []
    assert [e.id for e in result.verified_expectations] == ["e1"]
    assert result.workflow_id == "w1" and result.workflow_name == "Checkout"


# --- which observation an expectation is graded against ---------------------------


def test_an_expectation_is_graded_against_the_step_it_names():
    """The demo bug: checkout really did return 402, but the expectation was graded
    against a trailing cart read and reported as a false FAIL."""
    wf = workflow(bound(0, {"kind": "status", "value": 402}))
    observations = {0: observation(402), 1: observation(200, {"items": [1], "total": 3000})}

    result = verify_workflow(wf, BOTH_STEPS, observations)

    assert result.outcome == Outcome.PASS
    assert result.findings == []
    assert [e.id for e in result.verified_expectations] == ["e1"]


def test_each_expectation_is_graded_against_its_own_step():
    wf = workflow(
        Expectation(
            id="created",
            statement="the cart is created",
            provenance=Provenance.OBSERVED_IN_RUN,
            check={"kind": "status", "value": 201},
            step_index=0,
        ),
        Expectation(
            id="refused",
            statement="checkout is refused",
            provenance=Provenance.OBSERVED_IN_RUN,
            check={"kind": "status", "value": 402},
            step_index=1,
        ),
    )

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert result.outcome == Outcome.PASS
    assert {e.id for e in result.verified_expectations} == {"created", "refused"}


def test_an_expectation_bound_to_an_unreached_step_is_blocked_not_graded_elsewhere():
    """No falling back to another step's response -- grading against the wrong
    response is the bug being fixed, and a wrong FAIL is worse than an honest gap."""
    wf = workflow(bound(1, {"kind": "status", "value": 402}))
    steps = [
        StepResult(intent="create a cart", outcome=Outcome.PASS),
        StepResult(intent="check out", outcome=Outcome.BLOCKED, detail="connection refused"),
    ]

    result = verify_workflow(wf, steps, {0: observation(201)})

    assert result.outcome == Outcome.BLOCKED
    (finding,) = result.findings
    assert finding.outcome == Outcome.BLOCKED
    assert finding.severity == Severity.QUESTION
    assert "step 1 was never reached" in finding.detail
    assert result.verified_expectations == []


def test_an_unreached_binding_is_blocked_even_when_the_other_step_would_have_passed():
    """Step 0 returned exactly the 402 the expectation wants; it is still BLOCKED,
    because that 402 is not the response the expectation is about."""
    wf = workflow(bound(1, {"kind": "status", "value": 402}))
    steps = [
        StepResult(intent="create a cart", outcome=Outcome.PASS),
        StepResult(intent="check out", outcome=Outcome.BLOCKED),
    ]

    result = verify_workflow(wf, steps, {0: observation(402)})

    assert result.findings[0].outcome == Outcome.BLOCKED
    assert result.verified_expectations == []


def test_an_unbound_expectation_falls_back_to_the_last_observation():
    wf = workflow(bound(None, {"kind": "status", "value": 402}))

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert result.outcome == Outcome.PASS


def test_the_fallback_is_the_furthest_step_reached_not_the_last_step_declared():
    """Execution died at checkout; the cart creation is what remains to inspect."""
    wf = workflow(bound(None, {"kind": "status", "value": 201}))
    steps = [
        StepResult(intent="create a cart", outcome=Outcome.PASS),
        StepResult(intent="check out", outcome=Outcome.BLOCKED),
    ]

    result = verify_workflow(wf, steps, {0: observation(201)})

    assert result.verified_expectations != []
    assert result.outcome == Outcome.BLOCKED


def test_a_step_index_outside_the_workflow_raises():
    """A malformed knowledge base is loud, never quietly graded against something."""
    wf = workflow(bound(5, {"kind": "status", "value": 402}))

    with pytest.raises(ValueError) as exc:
        verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert "5" in str(exc.value)


def test_a_negative_step_index_raises_rather_than_indexing_from_the_end():
    wf = workflow(bound(-1, {"kind": "status", "value": 402}))

    with pytest.raises(ValueError):
        verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})


# --- findings, severity and outcome precedence ------------------------------------


def test_a_failed_expectation_becomes_a_finding_capped_by_provenance():
    exp = Expectation(
        id="e1",
        statement="checkout is rejected",
        provenance=Provenance.INFERRED_FROM_CODE,
        check={"kind": "status", "value": 402},
        step_index=1,
    )
    wf = workflow(exp)

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(200)})

    assert result.outcome == Outcome.FAIL
    (finding,) = result.findings
    assert finding.outcome == Outcome.FAIL
    assert finding.severity == Severity.QUESTION
    assert finding.provenance == Provenance.INFERRED_FROM_CODE
    assert finding.statement == "checkout is rejected"
    assert "got 200" in finding.detail
    assert finding.repro == ["create a cart", "check out"]
    assert result.verified_expectations == []


def test_finding_evidence_comes_from_the_step_the_expectation_names():
    """The evidence attached to a finding must be the response it is complaining
    about; that is the whole reason expectations are bound to steps."""
    wf = workflow(bound(0, {"kind": "status", "value": 402}))
    observations = {0: observation(201, {"cart_id": "c1"}), 1: observation(200, {"items": []})}

    result = verify_workflow(wf, BOTH_STEPS, observations)

    (finding,) = result.findings
    assert finding.evidence["status"] == 201
    assert finding.evidence["json"] == {"cart_id": "c1"}


def test_a_human_confirmed_failure_is_reported_as_a_bug():
    wf = workflow(bound(1, {"kind": "status", "value": 402}, provenance=Provenance.HUMAN_CONFIRMED))

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(200)})

    assert result.findings[0].severity == Severity.BUG


def test_blocked_expectations_are_reported_as_questions_never_as_failures():
    wf = workflow(bound(1))

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert result.outcome == Outcome.BLOCKED
    (finding,) = result.findings
    assert finding.outcome == Outcome.BLOCKED
    assert finding.severity == Severity.QUESTION
    assert result.verified_expectations == []


def test_blocked_is_reported_not_swallowed():
    """Even with nothing checkable, the gap appears in the report."""
    result = verify_workflow(workflow(bound(1)), BOTH_STEPS, {0: observation(), 1: observation()})

    assert result.findings != []


def test_a_blocked_step_blocks_the_workflow_even_when_every_expectation_passes():
    wf = workflow(bound(0, {"kind": "status", "value": 201}))
    steps = [
        StepResult(intent="create a cart", outcome=Outcome.PASS),
        StepResult(intent="check out", outcome=Outcome.BLOCKED, detail="could not resolve"),
    ]

    result = verify_workflow(wf, steps, {0: observation(201)})

    assert result.outcome == Outcome.BLOCKED
    assert result.verified_expectations != []


def test_failure_outranks_blocked():
    wf = workflow(
        bound(1, {"kind": "status", "value": 402}, id="checked"),
        Expectation(
            id="prose", statement="prose", provenance=Provenance.OBSERVED_IN_RUN, step_index=1
        ),
    )

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(200)})

    assert result.outcome == Outcome.FAIL
    assert {f.outcome for f in result.findings} == {Outcome.FAIL, Outcome.BLOCKED}


def test_verified_expectations_contains_only_the_passes():
    wf = workflow(
        Expectation(
            id="passes",
            statement="status is 402",
            provenance=Provenance.OBSERVED_IN_RUN,
            check={"kind": "status", "value": 402},
            step_index=1,
        ),
        Expectation(
            id="fails",
            statement="body names the card",
            provenance=Provenance.OBSERVED_IN_RUN,
            check={"kind": "json_eq", "path": "error", "value": "card_expired"},
            step_index=1,
        ),
        Expectation(
            id="blocked",
            statement="prose",
            provenance=Provenance.OBSERVED_IN_RUN,
            step_index=1,
        ),
    )

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(402)})

    assert [e.id for e in result.verified_expectations] == ["passes"]


def test_no_observation_at_all_blocks_every_expectation():
    wf = workflow(
        bound(0, {"kind": "status", "value": 402}, id="checked"),
        Expectation(
            id="prose", statement="prose", provenance=Provenance.HUMAN_CONFIRMED, step_index=None
        ),
    )

    result = verify_workflow(wf, ran("create a cart", outcome=Outcome.BLOCKED), {})

    assert result.outcome == Outcome.BLOCKED
    assert [f.outcome for f in result.findings] == [Outcome.BLOCKED, Outcome.BLOCKED]
    assert all(f.severity == Severity.QUESTION for f in result.findings)
    assert all(f.evidence == {} for f in result.findings)
    assert result.verified_expectations == []


def test_a_workflow_with_no_expectations_passes_when_its_steps_did():
    result = verify_workflow(workflow(), BOTH_STEPS, {0: observation(), 1: observation()})

    assert result.outcome == Outcome.PASS
    assert result.findings == []


def test_a_model_provider_unblocks_prose_only_expectations():
    wf = workflow(bound(1))
    llm = ScriptedLLM({"held": False, "reason": "the cart still checked out"})

    result = verify_workflow(wf, BOTH_STEPS, {0: observation(201), 1: observation(200)}, llm)

    assert result.outcome == Outcome.FAIL
    assert result.findings[0].severity == Severity.BUG
