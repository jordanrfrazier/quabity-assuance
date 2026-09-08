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


class StepTiming(BaseModel):
    """Measured wall time, not provider-internal reasoning time.

    Driver-reported interaction time is action_s (explicit waits use wait_s).
    Evidence includes capture, prompt preparation and remaining driver overhead.
    A driver call that raises before returning timing is charged wholly to its
    action/wait phase because its evidence portion cannot be separated.
    """

    actor_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    judge_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    action_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    wait_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    evidence_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    total_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    actor_calls: int = Field(default=0, ge=0, strict=True)
    judge_calls: int = Field(default=0, ge=0, strict=True)


class StepResult(BaseModel):
    index: int
    do: str
    see: str
    outcome: StepOutcome
    reason: str = ""
    actions: list[ActionRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    screenshot: str | None = None
    timing: StepTiming | None = None
    started_offset_s: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        description="Seconds since walk start; approximate video chapter offset",
    )


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
