"""Verification: did the app behave as expected, and how loudly may we say so?

Three rules live here, and they are the product.

1. **Provenance caps severity.** `severity_for` is a table lookup, not a judgement
   call. Evaluation decides *whether* an expectation held; `PROVENANCE_CAP` decides
   what a violation is *allowed to mean*. An expectation inferred from code that was
   never observed running can only ever be a QUESTION, however confident the model
   sounded when it flagged it. This is the thing that stops the bot crying wolf, and
   it works precisely because it is a data structure rather than a prompt.

2. **Three outcomes, never blurred.** PASS, FAIL, BLOCKED. BLOCKED means "I could not
   test this": not a pass, not a failure, and never silence -- it is reported as a
   QUESTION finding so a human sees the gap. A prose-only expectation offline is
   BLOCKED, because the alternative is guessing, and one guessed pass costs more
   trust than ten honest gaps.

3. **Evidence must point at the response it is about.** An expectation is graded
   against the step it describes, never against whatever response happened to come
   last. Grading a checkout assertion against a trailing cart read produces a finding
   whose evidence contradicts its claim -- a false positive dressed in real data,
   which is worse than no finding at all for a tool whose entire pitch is that its
   findings are worth reading.

The same asymmetry governs `verified_expectations`: only expectations that actually
PASSED go in, because downstream those become generated regression tests, and we do
not codify behavior we could not confirm.

One class of finding does not pass through rule 1, because it does not pass through
an expectation at all: the intrinsic oracles in `qabot.intrinsics`, where the app
itself declared the error. Read that module before concluding the cap has a hole in
it -- an uncapped finding there is rule 1 applied, not waived, and the signals that
would need a reading to become defects are held at QUESTION for exactly rule 1's
reason.
"""

from __future__ import annotations

import json

from qabot.drivers.base import Observation
from qabot.intrinsics import declares_failure, intrinsic_findings
from qabot.llm import DeterministicLLM, LLMError, LLMProvider
from qabot.models import (
    PROVENANCE_CAP,
    Expectation,
    Finding,
    Outcome,
    Severity,
    StepResult,
    Workflow,
    WorkflowResult,
)

#: Distinguishes "the path holds None" from "the path is absent".
_MISSING = object()

_SYSTEM = (
    "You judge whether a stated expectation about an application's behavior held, "
    "given the evidence from one interaction. Answer with one JSON object and nothing "
    "else. Judge only what the evidence shows; if it does not settle the question, say "
    "the expectation did not hold and explain what was missing."
)

#: Passed as `schema_hint` and restated in the prompt, since a provider may ignore it.
_VERDICT_SCHEMA: dict = {"held": "bool", "reason": "str"}

_NO_MODEL = "prose-only expectation; no model available to evaluate it offline"


def evaluate_check(check: dict, observation: Observation) -> tuple[bool, str]:
    """Evaluate one machine-checkable assertion against an observation.

    Returns (passed, detail) where detail names actual against expected, because a
    finding a human cannot act on is barely better than no finding.

    A malformed *check* raises ValueError -- that is an authoring bug and must be loud.
    A malformed *observation* (missing status, absent JSON path, a list where a number
    was expected) returns False: that is the app under test not doing what we said it
    would, which is exactly what a failed expectation is.
    """
    kind = check.get("kind")

    if kind == "status":
        expected = _required(check, "value")
        actual = observation.evidence.get("status", _MISSING)
        if actual is _MISSING:
            return False, f"expected status {expected}, but the observation recorded no status"
        return actual == expected, f"expected status {expected}, got {actual}"

    if kind == "json_eq":
        path = _required(check, "path")
        expected = _required(check, "value")
        actual = _dig(observation, str(path))
        if actual is _MISSING:
            return False, f"expected {path} == {expected!r}, but {path!r} is {_absent(observation)}"
        return actual == expected, f"expected {path} == {expected!r}, got {actual!r}"

    if kind == "json_contains":
        path = _required(check, "path")
        expected = _required(check, "value")
        actual = _dig(observation, str(path))
        if actual is _MISSING:
            return (
                False,
                f"expected {path} to contain {expected!r}, but {path!r} is {_absent(observation)}",
            )
        passed = str(expected).lower() in str(actual).lower()
        return passed, f"expected {path} to contain {expected!r} (any case), got {actual!r}"

    if kind == "json_len_gt":
        path = _required(check, "path")
        threshold = _required(check, "value")
        actual = _dig(observation, str(path))
        if actual is _MISSING:
            return (
                False,
                f"expected len({path}) > {threshold}, but {path!r} is {_absent(observation)}",
            )
        if not hasattr(actual, "__len__"):
            return False, f"expected a sized value at {path!r} to measure, got {actual!r}"
        return len(actual) > threshold, f"expected len({path}) > {threshold}, got {len(actual)}"

    if kind in {"text_visible", "text_absent"}:
        expected = str(_required(check, "value"))
        scope, where = _page_text(check, observation)
        if scope is _MISSING:
            return (
                False,
                f"expected text {expected!r} {where}, but that region is not present on the page",
            )
        present = expected.lower() in str(scope).lower()
        if kind == "text_visible":
            return present, f"expected {where} to contain {expected!r} (any case), got {scope!r}"
        return not present, f"expected {where} NOT to contain {expected!r}, got {scope!r}"

    if kind == "url_contains":
        expected = str(_required(check, "value"))
        actual = observation.evidence.get("url", _MISSING)
        if actual is _MISSING:
            return False, f"expected the url to contain {expected!r}, but none was recorded"
        return expected in str(actual), f"expected url to contain {expected!r}, got {actual!r}"

    raise ValueError(
        f"unknown check kind {kind!r}; supported kinds are "
        "status, json_eq, json_contains, json_len_gt, "
        "text_visible, text_absent, url_contains"
    )


def _page_text(check: dict, observation: Observation) -> tuple[object, str]:
    """Resolve which slice of the page a text check applies to.

    WHY scoping matters more than it looks: matching against the whole page is
    almost always wrong. The demo shop renders a card <select> containing an option
    labelled "expired", so a page-wide search for "expired" passes on the very page
    whose error message fails to mention it -- a false pass on the exact defect we
    are hunting. A text check therefore names the region it means, and only falls
    back to the whole page when it explicitly says so.
    """
    role = check.get("role")
    if role == "alert":
        alerts = observation.evidence.get("alerts", _MISSING)
        if alerts is _MISSING:
            return _MISSING, "the page alert"
        if not alerts:
            return _MISSING, "the page alert"
        return " ".join(str(a) for a in alerts), "the page alert"
    if role:
        raise ValueError(
            f"text checks currently scope to role 'alert' or the whole page; got {role!r}"
        )
    text = observation.evidence.get("text", _MISSING)
    return text, "the page text"


def evaluate_expectation(
    exp: Expectation, observation: Observation, llm: LLMProvider
) -> tuple[Outcome, str]:
    """Decide PASS / FAIL / BLOCKED for one expectation against one observation.

    With a `check` the answer is deterministic and is only ever PASS or FAIL. Without
    one the expectation is prose and only a model can read it; when no model is
    available the answer is BLOCKED, never a guess in either direction.
    """
    if exp.check is not None:
        passed, detail = evaluate_check(exp.check, observation)
        return (Outcome.PASS if passed else Outcome.FAIL), detail

    prompt = (
        f"Expectation: {exp.statement}\n"
        f"Observation: {observation.summary}\n"
        f"Evidence: {json.dumps(observation.evidence, default=str)}\n"
        f"Respond with an object of exactly this shape: {json.dumps(_VERDICT_SCHEMA)}"
    )
    try:
        verdict = llm.complete_json(_SYSTEM, prompt, _VERDICT_SCHEMA)
    except LLMError:
        return Outcome.BLOCKED, _NO_MODEL

    held = verdict.get("held")
    if not isinstance(held, bool):
        return (
            Outcome.BLOCKED,
            f"prose-only expectation; the model returned no usable verdict: {verdict!r}",
        )
    reason = str(verdict.get("reason", "")) or "no reason given"
    return (Outcome.PASS if held else Outcome.FAIL), reason


def severity_for(exp: Expectation) -> Severity:
    """The provenance cap. Where an expectation came from bounds what breaking it means."""
    return PROVENANCE_CAP[exp.provenance]


def verify_workflow(
    workflow: Workflow,
    step_results: list[StepResult],
    observations: dict[int, Observation],
    llm: LLMProvider | None = None,
) -> WorkflowResult:
    """Assemble the verdict for one workflow.

    Two kinds of finding come out. Expectation findings, graded and capped by
    provenance; and intrinsic findings from `qabot.intrinsics`, which rest on what the
    application said about itself. Only the intrinsic tier the app declared outright
    is uncapped, and only that tier votes on the workflow's outcome.

    `observations` maps a step's *index* in `workflow.steps` to its Observation. Index
    rather than intent because two steps may share an intent string, and a dict keyed
    by intent would silently drop one of them.

    **Which observation does an expectation evaluate against?** The step it names.
    `exp.step_index` binds an expectation to the call it describes, and grading it
    anywhere else produces evidence pointing at the wrong response. An expectation
    bound to a step that was never reached is BLOCKED -- we say we could not check it
    rather than grading it against a response it was never about. `step_index is None`
    is the unbound fallback: the last observation recorded, which is only meaningful
    for expectations that genuinely describe the workflow's end state.

    A `step_index` outside the workflow's steps raises ValueError: that is a malformed
    knowledge base, and it must be loud rather than quietly graded against something.

    `llm` is optional and defaults to DeterministicLLM, i.e. offline: prose-only
    expectations come back BLOCKED. Pass a real provider to have them judged.
    """
    provider = llm if llm is not None else DeterministicLLM()
    repro = [step.intent for step in workflow.steps]

    findings: list[Finding] = []
    verified: list[Expectation] = []
    any_failed = False
    any_blocked = any(result.outcome == Outcome.BLOCKED for result in step_results)

    for exp in workflow.expectations:
        observation, unavailable = _observation_for(exp, len(workflow.steps), observations)
        if observation is None:
            outcome, detail = Outcome.BLOCKED, unavailable
        else:
            outcome, detail = evaluate_expectation(exp, observation, provider)

        if outcome == Outcome.PASS:
            verified.append(exp)
            continue

        if outcome == Outcome.FAIL:
            any_failed = True
            severity = severity_for(exp)
        else:
            any_blocked = True
            severity = Severity.QUESTION

        findings.append(
            Finding(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                severity=severity,
                outcome=outcome,
                statement=exp.statement,
                detail=detail,
                provenance=exp.provenance,
                repro=repro,
                evidence=dict(observation.evidence) if observation is not None else {},
            )
        )

    # Intrinsic findings are assembled here, not in the runner, for two reasons. A
    # Finding reaches the report only through a WorkflowResult and this is the only
    # place one is built; and the suppression guard needs `workflow.expectations`
    # bound to steps, which is the mapping this function already exists to apply.
    # They are not capped -- see qabot/intrinsics.py for why that follows from rule 1.
    intrinsic = intrinsic_findings(workflow, observations)
    findings.extend(intrinsic)

    # An app that declared its own error did not pass. The workflow reads FAIL for
    # the same reason a failed expectation makes it FAIL, and with the same effect
    # downstream: testgen will not promote anything observed during a crashing run
    # into a regression test.
    #
    # Only the declared-failure tier gets that vote. The other intrinsic tier is, by
    # construction, findings we refuse to call defects -- a console error may be the
    # app logging an expected condition -- and something we will not call a defect
    # must not act like one behind the reader's back. Letting it fail the workflow
    # would also stop testgen promoting expectations that genuinely passed, which is
    # a real cost paid on a signal we just said we could not read.
    if any_failed or any(declares_failure(f) for f in intrinsic):
        workflow_outcome = Outcome.FAIL
    elif any_blocked:
        workflow_outcome = Outcome.BLOCKED
    else:
        workflow_outcome = Outcome.PASS

    return WorkflowResult(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        outcome=workflow_outcome,
        steps=list(step_results),
        findings=findings,
        verified_expectations=verified,
    )


def _observation_for(
    exp: Expectation, step_count: int, observations: dict[int, Observation]
) -> tuple[Observation | None, str]:
    """The observation an expectation is graded against.

    Returns (observation, "") when one is available, or (None, reason) when the
    expectation cannot be evaluated. There is deliberately no third case: we never
    substitute a different step's response for a missing one.
    """
    if exp.step_index is None:
        observation = _final_observation(observations)
        if observation is None:
            return None, "no step produced an observation to verify against"
        return observation, ""

    if not 0 <= exp.step_index < step_count:
        raise ValueError(
            f"expectation {exp.id!r} is bound to step {exp.step_index}, but its workflow "
            f"has {step_count} steps"
        )

    observation = observations.get(exp.step_index)
    if observation is None:
        return None, (
            f"step {exp.step_index} was never reached, so this expectation could not be evaluated"
        )
    return observation, ""


def _final_observation(observations: dict[int, Observation]) -> Observation | None:
    """The last observation recorded. The runner fills indices in ascending order and
    stops at the first failure, so the highest key is the furthest step reached."""
    if not observations:
        return None
    return observations[max(observations)]


def _required(check: dict, key: str) -> object:
    if key not in check:
        raise ValueError(f"check {check!r} of kind {check.get('kind')!r} is missing {key!r}")
    return check[key]


def _dig(observation: Observation, path: str) -> object:
    """Walk a dotted path into the observation's JSON body, or _MISSING."""
    current = observation.evidence.get("json", _MISSING)
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _absent(observation: Observation) -> str:
    body = observation.evidence.get("json")
    if not isinstance(body, dict):
        return "absent (the observation has no JSON object body)"
    return f"absent (body keys: {sorted(body)})"
