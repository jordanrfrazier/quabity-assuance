"""Step planning: a declarative intent becomes a concrete driver Action.

A Step says what a person wants to do ("check out with an expired card"). A Driver
needs an Action ("POST /checkout with this body"). Bridging the two is either
lookup or inference, and the difference is the whole point of this module:

  * `step.hint` is a *recorded* resolution, seeded from an existing test. It is
    evidence, so it is used verbatim -- no model, no guessing, no drift between
    what the test did and what we do.
  * No hint means the resolution must be inferred, which requires a model. With no
    model available we refuse instead of improvising. An invented request is worse
    than an admitted gap: the run would exercise behavior nobody asked about and
    then report on it with a straight face.

Both refusals surface as PlanError. The caller records that as BLOCKED -- "I could
not test this" -- which is neither a pass nor a failure.

Placeholders exist because steps carry state forward: step 1 creates a cart, step 2
checks it out. An unresolved "{cart_id}" is a hard error rather than a literal sent
to the app, because the app would answer a meaningless request with a 404 and the
verifier would faithfully report that 404 as a bug.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from qabot.drivers.base import Action, Observation
from qabot.llm import LLMError, LLMProvider
from qabot.models import Step

#: "{name}" -- deliberately restrictive so JSON braces in prose are left alone.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_SYSTEM = (
    "You resolve a QA step intent into a single concrete HTTP action against the "
    "application under test. Answer with one JSON object and nothing else. Never "
    "invent authentication, never chain multiple requests into one action, and use "
    "the literal values of the variables you are given rather than placeholders."
)

#: Passed to the provider as `schema_hint` and also spelled out in the prompt,
#: because a provider is free to ignore the hint.
_ACTION_SCHEMA: dict = {
    "kind": "http",
    "params": {"method": "POST", "path": "/a/path", "json": {"key": "value"}},
}


class PlanError(RuntimeError):
    """A step could not be turned into an action. The caller records BLOCKED."""


def resolve_step(step: Step, variables: dict[str, object], llm: LLMProvider) -> Action:
    """Resolve `step` into an executable Action.

    A hint is used as-is (with placeholders filled from `variables`). Without one the
    action has to be inferred by `llm`; an offline provider raises LLMError there and
    that becomes PlanError, so the run reports BLOCKED instead of a fabricated request.
    """
    if step.hint is not None:
        return _action_from_hint(step, step.hint, variables)
    return _action_from_llm(step, variables, llm)


def capture_variables(step: Step, observation: Observation, variables: dict[str, object]) -> None:
    """Apply `step.hint["capture"]` -- {"var_name": "json.field"} -- to `variables`.

    Mutates `variables` in place so later steps can refer to "{var_name}". A field the
    response does not contain is a PlanError: the alternative is a later step silently
    substituting None into a URL.
    """
    if step.hint is None:
        return
    capture = step.hint.get("capture")
    if capture is None:
        return
    if not isinstance(capture, dict):
        raise PlanError(f"step {step.intent!r}: hint 'capture' must be an object, got {capture!r}")

    body = observation.evidence.get("json")
    if not isinstance(body, dict):
        raise PlanError(
            f"step {step.intent!r}: cannot capture {sorted(capture)} -- the observation "
            f"has no JSON object body (evidence keys: {sorted(observation.evidence)})"
        )
    for name, field in capture.items():
        variables[name] = _read_field(body, str(field), step.intent)


#: Browser hint keys carried through to the driver, after placeholder substitution.
_BROWSER_KEYS = ("op", "path", "role", "name", "value")


def _action_from_hint(step: Step, hint: dict, variables: dict[str, object]) -> Action:
    # A hint naming an `op` is a browser interaction; one naming method+path is HTTP.
    # The surface is inferred from the hint's shape rather than configured, so a
    # knowledge base can mix HTTP and browser workflows without a mode switch.
    if "op" in hint:
        return _browser_action_from_hint(step, hint, variables)

    method = hint.get("method")
    path = hint.get("path")
    if not isinstance(method, str) or not isinstance(path, str):
        raise PlanError(
            f"step {step.intent!r}: hint needs string 'method' and 'path', got {hint!r}"
        )
    return Action(
        kind="http",
        params={
            "method": method,
            "path": _substitute(path, variables, step.intent),
            "json": _substitute(hint.get("json"), variables, step.intent),
        },
    )


def _browser_action_from_hint(step: Step, hint: dict, variables: dict[str, object]) -> Action:
    op = hint.get("op")
    if not isinstance(op, str):
        raise PlanError(f"step {step.intent!r}: browser hint needs a string 'op', got {hint!r}")
    if op != "goto" and not hint.get("role"):
        raise PlanError(
            f"step {step.intent!r}: browser op {op!r} must target a role. Locators are "
            f"role+accessible-name by design; CSS and XPath are not supported."
        )
    params: dict[str, object] = {"op": op}
    for key in _BROWSER_KEYS[1:]:
        if key in hint:
            params[key] = _substitute(hint[key], variables, step.intent)
    return Action(kind="browser", params=params)


def _action_from_llm(step: Step, variables: dict[str, object], llm: LLMProvider) -> Action:
    prompt = (
        f"Step intent: {step.intent}\n"
        f"Variables captured from earlier steps: {json.dumps(variables, default=str)}\n"
        f"Respond with an object of exactly this shape: {json.dumps(_ACTION_SCHEMA)}"
    )
    try:
        raw = llm.complete_json(_SYSTEM, prompt, _ACTION_SCHEMA)
    except LLMError as exc:
        raise PlanError(
            f"step {step.intent!r}: no hint recorded and no model available to infer an "
            f"action ({exc})"
        ) from exc
    try:
        return Action.model_validate(raw)
    except ValidationError as exc:
        raise PlanError(f"step {step.intent!r}: model returned an unusable action {raw!r}") from exc


def _substitute(value: object, variables: dict[str, object], intent: str) -> object:
    """Fill "{name}" placeholders throughout a hint value."""
    if isinstance(value, str):
        return _substitute_string(value, variables, intent)
    if isinstance(value, dict):
        return {key: _substitute(item, variables, intent) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, variables, intent) for item in value]
    return value


def _substitute_string(text: str, variables: dict[str, object], intent: str) -> object:
    """A whole-string placeholder keeps the variable's type; an embedded one stringifies.

    So {"cart_id": "{cart_id}"} sends the captured integer 7, not "7", while
    "/cart/{cart_id}/checkout" becomes "/cart/7/checkout".
    """
    whole = _PLACEHOLDER.fullmatch(text)
    if whole is not None:
        return _lookup(whole.group(1), variables, intent, text)
    return _PLACEHOLDER.sub(lambda m: str(_lookup(m.group(1), variables, intent, text)), text)


def _lookup(name: str, variables: dict[str, object], intent: str, text: str) -> object:
    if name not in variables:
        raise PlanError(
            f"step {intent!r}: no variable {name!r} for the placeholder in {text!r} "
            f"(captured so far: {sorted(variables)})"
        )
    return variables[name]


def _read_field(body: dict, field: str, intent: str) -> object:
    """Read a dotted path out of a response body."""
    current: object = body
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            raise PlanError(
                f"step {intent!r}: capture field {field!r} is not present in the response body"
            )
        current = current[part]
    return current
