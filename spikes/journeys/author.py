"""Journeys from evidence. One model call, validated hard, re-asked once.

The output is for a person before it is for the walker: every step is a sentence a
tester could follow and a sentence describing what they should then see. The prompt
insists on traceability so a journey that came from nowhere is visible as such.
"""

from __future__ import annotations

from pydantic import ValidationError

from qabot.llm import LLMError
from spikes.journeys.evidence import Evidence
from spikes.journeys.models import Journey

MIN_JOURNEYS = 3
MAX_JOURNEYS = 8

SYSTEM = (
    "You write user journeys for a QA tester who has never seen this product. You are given "
    "a code change (a diff, its description, the settings it touches, and the product's own "
    "end-to-end tests that are closest to it). Write the journeys a careful tester would "
    "walk to confirm this change did what it claims and broke nothing beside it.\n"
    "Rules:\n"
    f"- Between {MIN_JOURNEYS} and {MAX_JOURNEYS} journeys.\n"
    "- Journey 1 is always the happy path the change protects.\n"
    "- Each journey has `goal` (what the persona wants, one clause) and `because` (why they "
    "want it, one clause), so it reads: As a <persona>, I want <goal> because <because>.\n"
    "- At least one journey runs under the condition that makes the change matter; put "
    "that condition in preconditions.settings using the exact setting names from the "
    "evidence.\n"
    "- Every step has `do` (one action a person performs, present tense, naming the "
    "visible control) and `see` (what the screen shows if the product is correct). No "
    "step without a `see`.\n"
    "- `traces_to` names the diff hunk, symbol or description sentence the journey comes "
    "from.\n"
    "- Steps use the product's own words for controls and pages, taken from the specs "
    "when possible. Never invent a control the evidence does not suggest exists.\n"
    'Answer with ONLY a JSON object: {"journeys": [Journey, ...]} where Journey = '
    "{id, title, persona, goal, because, preconditions:{settings:{}, state:[]}, steps:[{do, see}], "
    "traces_to}."
)


class AuthorError(RuntimeError):
    pass


def _prompt(ev: Evidence) -> str:
    specs = "\n\n".join(f"### {path}\n{text}" for path, text in ev.related_specs.items())
    truncated = " [TRUNCATED]" if ev.diff_truncated else ""
    return (
        f"## Change description\n{ev.description or '(none given)'}\n\n"
        f"## Settings and flags touched\n{', '.join(ev.settings_names) or '(none)'}\n\n"
        f"## Changed files\n{', '.join(ev.changed_files)}\n\n"
        f"## Changed symbols\n{', '.join(ev.changed_symbols) or '(none)'}\n\n"
        f"## Diff ({ev.base}..{ev.head}){truncated}\n```\n{ev.diff}\n```\n\n"
        f"## The product's closest end-to-end tests\n{specs or '(none found)'}\n"
    )


def _parse(raw: dict) -> list[Journey]:
    items = raw.get("journeys") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise TypeError("answer has no 'journeys' list")
    journeys = [Journey.model_validate(item) for item in items]
    if not MIN_JOURNEYS <= len(journeys) <= MAX_JOURNEYS:
        raise ValueError(
            f"{len(journeys)} journeys; need between {MIN_JOURNEYS} and {MAX_JOURNEYS}"
        )
    return journeys


def author(evidence: Evidence, llm) -> list[Journey]:
    prompt = _prompt(evidence)
    schema = {
        "journeys": [{"id": "", "title": "", "persona": "", "steps": [{"do": "", "see": ""}]}]
    }
    last_error = ""
    for attempt in range(2):
        ask = (
            prompt
            if attempt == 0
            else (
                f"{prompt}\n\nYour previous answer was rejected: {last_error}\n"
                "Answer again, fixing exactly that."
            )
        )
        try:
            raw = llm.complete_json(SYSTEM, ask, schema)
            return _parse(raw)
        except LLMError as exc:
            raise AuthorError(f"model unavailable: {exc}") from exc
        except (ValidationError, ValueError, TypeError) as exc:
            last_error = str(exc)[:600]
    raise AuthorError(f"journeys rejected twice; last reason: {last_error}")
