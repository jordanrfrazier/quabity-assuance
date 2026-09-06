import pytest

from spikes.journeys.author import AuthorError, author
from spikes.journeys.evidence import Evidence
from spikes.journeys.fakes import FakeLLM


def _evidence() -> Evidence:
    return Evidence(
        base="a",
        head="b",
        diff="+ if settings.allow_custom_components:\n",
        diff_truncated=False,
        changed_files=["components.py"],
        changed_symbols=["load"],
        settings_names=["LANGFLOW_ALLOW_CUSTOM_COMPONENTS"],
        description="fix: lazy loading wipes registry",
        related_specs={"tests/flow.spec.ts": "test('run flow')"},
    )


def _journey(i: int) -> dict:
    return {
        "id": f"j{i}",
        "title": f"journey {i}",
        "persona": "a first-time user",
        "preconditions": {
            "settings": {"LANGFLOW_ALLOW_CUSTOM_COMPONENTS": "false"},
            "state": [],
        },
        "steps": [{"do": "open the app", "see": "the projects page"}],
        "traces_to": "components.py: allow_custom_components",
    }


def test_author_returns_validated_journeys_and_shows_evidence():
    llm = FakeLLM([{"journeys": [_journey(1), _journey(2), _journey(3)]}])
    journeys = author(_evidence(), llm)
    assert [j.id for j in journeys] == ["j1", "j2", "j3"]
    assert journeys[0].provenance == "inferred_from_diff"
    prompt = llm.calls[0]["prompt"]
    assert "LANGFLOW_ALLOW_CUSTOM_COMPONENTS" in prompt
    assert "tests/flow.spec.ts" in prompt
    assert "fix: lazy loading wipes registry" in prompt


def test_author_reasks_once_with_the_validation_error():
    bad = _journey(1)
    bad["steps"] = [{"do": "open the app", "see": ""}]
    llm = FakeLLM(
        [
            {"journeys": [bad, _journey(2), _journey(3)]},
            {"journeys": [_journey(1), _journey(2), _journey(3)]},
        ]
    )
    journeys = author(_evidence(), llm)
    assert len(journeys) == 3
    assert "see" in llm.calls[1]["prompt"]


def test_author_fails_loudly_after_second_bad_answer():
    llm = FakeLLM([{"journeys": []}, {"journeys": []}])
    with pytest.raises(AuthorError, match="3"):
        author(_evidence(), llm)


def test_author_caps_journey_count():
    too_many = {"journeys": [_journey(i) for i in range(1, 12)]}
    llm = FakeLLM([too_many, too_many])
    with pytest.raises(AuthorError, match="8"):
        author(_evidence(), llm)
