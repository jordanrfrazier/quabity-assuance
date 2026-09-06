import pytest
from pydantic import ValidationError

from spikes.journeys.fakes import FakeLLM
from spikes.journeys.models import Journey, JourneyStep, StepOutcome


def test_journey_requires_see_on_every_step():
    with pytest.raises(ValidationError):
        Journey(id="j1", title="t", persona="p", steps=[{"do": "open the app", "see": ""}])


def test_journey_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        Journey(id="j1", title="t", persona="p", steps=[])


def test_journey_provenance_is_fixed():
    j = Journey(
        id="j1", title="t", persona="p", steps=[JourneyStep(do="open the app", see="the home")]
    )
    assert j.provenance == "inferred_from_diff"
    with pytest.raises(ValidationError):
        Journey(
            id="j1",
            title="t",
            persona="p",
            provenance="human_confirmed",
            steps=[JourneyStep(do="a", see="b")],
        )


def test_step_outcomes_are_four_and_named():
    assert {o.value for o in StepOutcome} == {"held", "failed", "blocked", "not_reached"}


def test_fake_llm_replays_in_order_and_records_prompts():
    llm = FakeLLM([{"a": 1}, {"b": 2}])
    assert llm.complete_json("sys", "first", {}) == {"a": 1}
    assert llm.complete_json("sys", "second", {}) == {"b": 2}
    assert [c["prompt"] for c in llm.calls] == ["first", "second"]
    with pytest.raises(RuntimeError, match="no more"):
        llm.complete_json("sys", "third", {})
