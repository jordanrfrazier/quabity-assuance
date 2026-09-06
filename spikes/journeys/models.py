"""The user journey and what walking it produced.

A journey is written for a person first: each step says what to do and what to see.
It is authored by a model from a diff, so its provenance is fixed to
"inferred_from_diff" and can never be upgraded by the code that produced it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from qabot.models import Finding, Outcome


class JourneyStep(BaseModel):
    do: str = Field(min_length=1)
    see: str = Field(min_length=1)


class Preconditions(BaseModel):
    settings: dict[str, str] = Field(default_factory=dict)
    state: list[str] = Field(default_factory=list)


class Journey(BaseModel):
    id: str
    title: str
    persona: str
    goal: str = ""
    because: str = ""
    preconditions: Preconditions = Field(default_factory=Preconditions)
    steps: list[JourneyStep] = Field(min_length=1)
    traces_to: str = ""
    provenance: Literal["inferred_from_diff"] = "inferred_from_diff"


class StepOutcome(StrEnum):
    HELD = "held"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_REACHED = "not_reached"


class ActionRecord(BaseModel):
    op: str
    params: dict[str, object] = Field(default_factory=dict)
    ok: bool
    summary: str = ""
    error: str = ""
    screenshot: str | None = None


class StepResult(BaseModel):
    index: int
    do: str
    see: str
    outcome: StepOutcome
    reason: str = ""
    actions: list[ActionRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    screenshot: str | None = None


class JourneyResult(BaseModel):
    journey: Journey
    outcome: Outcome
    steps: list[StepResult]
    why: str = ""
    video: str | None = None
