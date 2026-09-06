from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright

from demo.app import create_app
from demo.server import serve
from qabot.drivers.browser import BrowserDriver
from qabot.models import Outcome, Severity
from spikes.journeys.fakes import FakeLLM
from spikes.journeys.models import Journey, JourneyStep, StepOutcome
from spikes.journeys.walker import MAX_ACTIONS_PER_STEP, page_checks, unmet_preconditions, walk

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def shop_url() -> Iterator[str]:
    with serve(create_app()) as url:
        yield url


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


@pytest.fixture
def driver(shop_url: str, page: Page, tmp_path: Path) -> BrowserDriver:
    d = BrowserDriver(
        base_url=shop_url,
        page=page,
        artifacts_dir=tmp_path / "shots",
        timeout_ms=3000,
        reset_path=None,
    )
    d.reset()
    return d


def _journey() -> Journey:
    return Journey(
        id="j1",
        title="Add a widget",
        persona="a shopper",
        steps=[
            JourneyStep(do="Open the shop", see="a Product picker and an Add to cart button"),
            JourneyStep(do="Pick 'widget' and add it to the cart", see="the cart lists widget"),
        ],
    )


def test_walk_completes_a_journey_from_scripted_decisions(driver, page, tmp_path):
    llm = FakeLLM(
        [
            {"op": "goto", "path": "/ui"},
            {"op": "done"},
            {"verdict": "held", "reason": "picker and button are on screen"},
            {"op": "select", "role": "combobox", "name": "Product", "value": "widget"},
            {"op": "click", "role": "button", "name": "Add to cart"},
            {"op": "done"},
            {"verdict": "held", "reason": "cart shows widget"},
        ]
    )
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.PASS
    assert [s.outcome for s in result.steps] == [StepOutcome.HELD, StepOutcome.HELD]
    assert [a.op for a in result.steps[1].actions] == ["select", "click"]
    assert result.steps[1].screenshot and Path(result.steps[1].screenshot).exists()
    assert "Add to cart" in llm.calls[3]["prompt"]


def test_walk_marks_failed_when_see_does_not_hold_and_keeps_walking(driver, page, tmp_path):
    llm = FakeLLM(
        [
            {"op": "goto", "path": "/ui"},
            {"op": "done"},
            {"verdict": "failed", "reason": "no picker on screen"},
            {"op": "done"},
            {"verdict": "held", "reason": "cart is fine"},
        ]
    )
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.FAIL
    assert result.why == "no picker on screen"
    assert result.steps[0].outcome == StepOutcome.FAILED
    assert result.steps[1].outcome == StepOutcome.HELD  # the walk went on to the next step
    inferred = [f for f in result.steps[0].findings if f.oracle is None]
    assert inferred and inferred[0].severity == Severity.QUESTION


def test_walk_blocks_after_the_action_cap(driver, page, tmp_path):
    llm = FakeLLM([{"op": "goto", "path": "/ui"}] * MAX_ACTIONS_PER_STEP)
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.BLOCKED
    assert result.steps[0].outcome == StepOutcome.BLOCKED
    assert str(MAX_ACTIONS_PER_STEP) in result.steps[0].reason


def test_walk_honours_blocked_from_the_model(driver, page, tmp_path):
    llm = FakeLLM([{"op": "blocked", "reason": "no such control"}])
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.BLOCKED
    assert "no such control" in result.steps[0].reason


def test_page_checks_name_error_and_white_screens():
    assert page_checks("Something went wrong. The application encountered an unexpected error.")
    assert page_checks("") == ["the page is blank: no visible text"]
    assert page_checks("Welcome to the shop") == []


def test_unmet_preconditions_block_before_any_action(driver, page, tmp_path):
    journey = _journey()
    journey.preconditions.settings = {"SHOP_MODE": "custom", "SHOP_PATH": "/x"}
    llm = FakeLLM([])
    result = walk(journey, driver, page, llm, tmp_path, env={"SHOP_MODE": "default"})
    assert result.outcome == Outcome.BLOCKED
    assert "SHOP_MODE must be 'custom'" in result.why
    assert "SHOP_PATH is required" in result.why
    assert all(s.outcome == StepOutcome.NOT_REACHED for s in result.steps)
    assert llm.calls == []


def test_matching_or_unknown_env_blocks_nothing():
    journey = _journey()
    journey.preconditions.settings = {"SHOP_MODE": "Custom"}
    assert unmet_preconditions(journey, {"SHOP_MODE": "custom"}) == []
    assert unmet_preconditions(journey, None) == []


def test_materialised_and_mapped_settings_satisfy_the_gate():
    journey = _journey()
    journey.preconditions.settings = {
        "settings.components_path": "/path/to/x (contains tools/t.py)",
        "LANGFLOW_X": "true",
    }
    env = {"LANGFLOW_COMPONENTS_PATH": "/tmp/fixtures/group_3", "LANGFLOW_X": "true"}
    assert unmet_preconditions(journey, env) == []
    expected = (
        "settings.components_path is required ('/path/to/x (contains tools/t.py)') "
        "and this instance does not set it"
    )
    assert unmet_preconditions(journey, {"LANGFLOW_X": "true"}) == [expected]


def test_strict_mode_duplicate_falls_back_to_first_match(driver, page, tmp_path):
    page.set_content(
        "<button onclick=\"document.title='clicked'\">Add</button><button>Add</button>"
    )
    llm = FakeLLM(
        [
            {"op": "click", "role": "button", "name": "Add"},
            {"op": "done"},
            {"verdict": "held", "reason": "ok"},
        ]
    )
    journey = Journey(id="j", title="t", persona="p", steps=[JourneyStep(do="add", see="added")])
    result = walk(journey, driver, page, llm, tmp_path)
    assert result.steps[0].actions[0].ok
    assert "first of the controls" in result.steps[0].actions[0].summary
    assert page.title() == "clicked"


def test_judge_sees_json_pages_as_key_counts(page):
    from spikes.journeys.walker import _page_summary

    page.goto('data:application/json,{"tools":{"a":1,"b":2},"embeddings":{}}')
    summary = _page_summary(page)
    assert "tools: 2 entries [a, b]" in summary
    assert "embeddings: 0 entries" in summary
