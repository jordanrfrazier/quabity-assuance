"""Core data model. This is the contract every other module builds against.

The central idea: an expectation's *provenance* caps how loudly a violation of it
may be reported. The model decides whether an expectation held; the data structure
decides how much that is allowed to mean.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Provenance(StrEnum):
    """Where an expectation came from. Determines maximum finding severity."""

    HUMAN_CONFIRMED = "human_confirmed"
    OBSERVED_IN_RUN = "observed_in_run"
    INFERRED_FROM_TEST = "inferred_from_test"
    INFERRED_FROM_CODE = "inferred_from_code"


class Severity(StrEnum):
    BUG = "bug"
    REGRESSION = "regression"
    CHANGE = "change"
    QUESTION = "question"


#: The provenance cap rule. A violated expectation is reported at, at most, this level.
PROVENANCE_CAP: dict[Provenance, Severity] = {
    Provenance.HUMAN_CONFIRMED: Severity.BUG,
    Provenance.OBSERVED_IN_RUN: Severity.REGRESSION,
    Provenance.INFERRED_FROM_TEST: Severity.CHANGE,
    Provenance.INFERRED_FROM_CODE: Severity.QUESTION,
}


class Outcome(StrEnum):
    """Three outcomes, never blurred. BLOCKED is not FAIL and is not silence."""

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class AnchorKind(StrEnum):
    ROUTE = "route"
    SYMBOL = "symbol"
    FILE = "file"
    COMPONENT = "component"


class WorkflowStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    RETIRED = "retired"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Anchor(BaseModel):
    """A link from knowledge back to code. The drift sensor."""

    kind: AnchorKind
    locator: str
    resolved: bool = True


class Expectation(BaseModel):
    """An assertion about behavior.

    `check` is the machine-checkable form when one could be derived (e.g. from an
    existing test's assert). When it is absent the expectation is prose-only and
    can only be evaluated by a model; offline that yields BLOCKED, never a guess.

    Supported check kinds:
      {"kind": "status", "value": 402}
      {"kind": "json_eq", "path": "error", "value": "card_expired"}
      {"kind": "json_contains", "path": "message", "value": "expired"}
      {"kind": "json_len_gt", "path": "items", "value": 0}
    """

    id: str
    statement: str
    provenance: Provenance
    confidence: float = 0.5
    check: dict | None = None
    step_index: int | None = None
    """Which step of the workflow this expectation describes.

    An assertion in a test follows a specific call, and grading it against any
    other response produces evidence that points at the wrong thing -- the exact
    cry-wolf failure this product exists to prevent. None means "not bound to a
    step", which is evaluated against the last observation available.
    """

    def cap(self) -> Severity:
        return PROVENANCE_CAP[self.provenance]


class Step(BaseModel):
    """A declarative intent. `hint` is a recorded resolution seeded from existing
    tests; the planner uses it when available and infers when it is not."""

    intent: str
    hint: dict | None = None


class Persona(BaseModel):
    id: str
    name: str
    traits: dict[str, object] = Field(default_factory=dict)
    fixture: dict[str, object] = Field(default_factory=dict)


class Workflow(BaseModel):
    id: str
    name: str
    persona: str | None = None
    criticality: Criticality = Criticality.MEDIUM
    status: WorkflowStatus = WorkflowStatus.ACTIVE
    preconditions: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)
    anchors: list[Anchor] = Field(default_factory=list)
    source_ref: str | None = None


class OpenQuestion(BaseModel):
    id: str
    question: str
    trigger: str
    candidates: list[str] = Field(default_factory=list)
    blocking: bool = False
    status: str = "open"
    workflow_id: str | None = None


class KnowledgeBase(BaseModel):
    repo: str
    version: int = 1
    personas: list[Persona] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)

    def workflow(self, wid: str) -> Workflow | None:
        return next((w for w in self.workflows if w.id == wid), None)


class StepResult(BaseModel):
    intent: str
    outcome: Outcome
    detail: str = ""
    evidence: dict[str, object] = Field(default_factory=dict)


class Finding(BaseModel):
    workflow_id: str
    workflow_name: str
    severity: Severity
    outcome: Outcome
    statement: str
    detail: str = ""
    provenance: Provenance | None = None
    oracle: str | None = None
    """Which intrinsic oracle produced this, when no expectation did.

    A finding carries a provenance or an oracle, never both. The first is graded by
    where an expectation came from; the second rests on the application's own error
    signal, where there is no inference to grade and so no cap to apply. See
    qabot/intrinsics.py for why that is not a hole in the cap rule.
    """

    repro: list[str] = Field(default_factory=list)
    evidence: dict[str, object] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    workflow_id: str
    workflow_name: str
    outcome: Outcome
    steps: list[StepResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    verified_expectations: list[Expectation] = Field(default_factory=list)


class RunReport(BaseModel):
    repo: str
    base_ref: str
    head_ref: str
    selected: list[str] = Field(default_factory=list)
    skipped_for_budget: list[str] = Field(default_factory=list)
    stale_workflows: list[str] = Field(default_factory=list)
    results: list[WorkflowResult] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    """Conditions this run could not establish, stated once and applying to every
    result in it -- e.g. an app with no way to reset between workflows. A caveat that
    lives only in the driver's head is a caveat nobody made."""

    @property
    def findings(self) -> list[Finding]:
        return [f for r in self.results for f in r.findings]
