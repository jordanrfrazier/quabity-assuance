"""Execution substrate boundary.

A Driver turns a resolved action into a real interaction with the running app and
returns evidence. Adding a surface (browser, CLI) means adding a Driver, not
touching the planner, verifier, or reporter.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class Action(BaseModel):
    """A concrete, driver-specific action resolved from a step intent."""

    kind: str
    params: dict[str, object] = Field(default_factory=dict)


class Observation(BaseModel):
    """What the app did. `ok` means the interaction completed, not that it was correct."""

    ok: bool
    summary: str
    evidence: dict[str, object] = Field(default_factory=dict)


class DriverError(RuntimeError):
    pass


class Driver(Protocol):
    name: str

    def reset(self) -> None:
        """Return the app to a known state between workflows."""
        ...

    def execute(self, action: Action) -> Observation: ...
