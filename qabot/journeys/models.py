"""Reviewable user journeys and the evidence produced while walking them."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from qabot.models import Finding, Outcome


class JourneyStep(BaseModel):
    do: str = Field(min_length=1)
    see: str = Field(min_length=1)
    expected_error: bool = False


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


class StartupPlan(BaseModel):
    command: str
    cwd: str
    health_url: str
    env: dict[str, str] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    reset_command: str | None = None
    sources: list[str] = Field(default_factory=list)


class ReviewPlan(BaseModel):
    repo: str
    base: str
    head: str
    description: str
    startup: StartupPlan
    journeys: list[Journey]
    unresolved: list[str] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
