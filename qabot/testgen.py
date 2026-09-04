"""Regression test emission: the part of a run that outlives the run.

The report is read once and scrolls away. The generated tests get committed, run
on every future PR, and are the reason the customer never has to take this bot's
word for anything -- every claim it makes is handed back as something they can
execute themselves.

That only works if the tests are true, so the filter here is deliberately harsh:

  * A workflow contributes only if its outcome is PASS or BLOCKED. BLOCKED means
    "we could not check everything", not "something contradicted us", so the
    expectations it *did* verify are still confirmed behavior and still worth
    committing. FAIL is different in kind: the app is misbehaving, so anything
    observed alongside the failure may be an artifact of it, and codifying that
    is unsafe.
  * Within a contributing workflow, only `verified_expectations` that carry a
    machine-checkable `check` are asserted. A prose expectation that a model
    judged to hold is a judgment, not an observation -- committing it would mean
    a future engineer's build breaks on the opinion of a model nobody can rerun.
  * A workflow whose executed steps were not recorded in enough detail to replay
    is dropped whole, because a test that replays a workflow only partly and then
    asserts the ending is a test that lies.

Every drop leaves a comment in the generated file. Silence about reduced coverage
is the failure mode this entire module exists to avoid.

Which response an assertion grades. `Expectation.step_index` binds an expectation
to the call it describes, and the verifier graded it against exactly that step's
observation (`None` meaning the last one). The generated test keeps one response
variable per replayed step and asserts against the same one, because an assertion
that grades the right claim against the wrong response is the cry-wolf failure
this product exists to prevent.

Replay contract. Only steps with `outcome == PASS` are replayed -- a BLOCKED step
never produced an interaction, so replaying it would be inventing one. The runner
breaks at the first non-PASS step, so the PASS steps are a prefix of the workflow
and their position is the workflow step index the verifier bound against.

Each step is replayed from `StepResult.evidence`, in one of two modes:

  * TEMPLATED -- `evidence["hint"]` is the step's pre-substitution hint
    (`method`, `path`, `json`, optional `capture` as `{var_name: dotted.field}`).
    `{var}` placeholders are threaded through a `captured` dict exactly as
    `planner._substitute` and `planner.capture_variables` do at run time, so the
    test re-derives ids instead of hard-coding them. This is the normal mode.
  * CONCRETE -- reached only when a step had no hint, i.e. a model resolved it and
    no templated form exists anywhere. The replay re-issues the literal request
    from the generating run and the test says so in a comment, because an id the
    app minted during that run may not exist during a later one.
"""

from __future__ import annotations

import textwrap

from qabot.drivers.http import REDACTED
from qabot.models import Expectation, Outcome, RunReport, StepResult, WorkflowResult

#: Keys in `StepResult.evidence`. The contract with the driver and the runner.
HINT_KEY = "hint"
REQUEST_KEY = "request"
METHOD_KEY = "method"
PATH_KEY = "path"
JSON_KEY = "json"
HEADERS_KEY = "headers"
COOKIES_KEY = "cookies"
CAPTURE_KEY = "capture"

#: The generating run sent credentials the driver withheld from evidence. Neither
#: half of that can be quiet: replaying the literal marker would send a nonsense
#: Authorization header, and saying nothing would ship a file that 401s for reasons
#: nothing in it explains.
WITHHELD_CREDENTIALS_NOTE = (
    "The generating run authenticated. Those credentials are deliberately not in this "
    "file -- a committed token is a leaked token -- so these requests replay without "
    "them and the app will reject them before any assertion below is reached. Supply "
    "the same credentials qabot was given (its --header / --cookie arguments) to run it."
)

#: Workflow outcomes whose verified expectations may be committed as tests.
EMITTING_OUTCOMES: frozenset[Outcome] = frozenset({Outcome.PASS, Outcome.BLOCKED})

_FILL_HELPER = '''
def _fill(value: object, captured: dict[str, object]) -> object:
    """Thread captured values into {placeholders}, the way the qabot runner did."""
    if isinstance(value, str):
        return value.format(**captured)
    if isinstance(value, dict):
        return {key: _fill(item, captured) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, captured) for item in value]
    return value
'''

_DIG_HELPER = '''
def _dig(payload: object, path: str) -> object:
    """Walk a dotted path into a parsed JSON body. A missing key raises, loudly."""
    for part in path.split("."):
        payload = payload[part]
    return payload
'''

_CONCRETE_WARNING = (
    "NOTE: the generating run resolved some of these steps with a model rather than a "
    "recorded template, so those requests replay the literal values it sent. Any id the "
    "app minted during that run is hard-coded here and may not exist in a later one."
)


def _identifier(workflow_id: str) -> str:
    """`test_<workflow_id>`, with anything Python will not accept in a name folded
    to an underscore. A leading digit is harmless because of the `test_` prefix."""
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in workflow_id)


def _docstring_safe(text: str) -> str:
    """Make `text` safe to drop inside a triple-quoted docstring."""
    flattened = text.replace("\\", "\\\\").replace("\r", " ").replace("\n", " ")
    return flattened.replace('"""', "'''").rstrip('"')


def _intent_label(intent: str) -> str:
    """A step intent short enough to sit in a comment inside 100 columns."""
    return textwrap.shorten(intent, width=58, placeholder="...")


def _replayed_steps(result: WorkflowResult) -> list[StepResult]:
    """The steps that actually ran, in workflow order.

    The runner stops at the first non-PASS step, so this is a prefix and each
    step's position here is its index in `Workflow.steps` -- the same index
    `Expectation.step_index` refers to.
    """
    return [step for step in result.steps if step.outcome is Outcome.PASS]


def _replay_source(step: StepResult) -> tuple[dict, bool] | None:
    """The request to replay and whether it still carries `{var}` templates.

    None means the step left no record of what it sent, which disqualifies the
    whole workflow: half a replay followed by a real assertion is a test that lies.
    """
    hint = step.evidence.get(HINT_KEY)
    if isinstance(hint, dict) and METHOD_KEY in hint and PATH_KEY in hint:
        return hint, True
    request = step.evidence.get(REQUEST_KEY)
    if isinstance(request, dict) and METHOD_KEY in request and PATH_KEY in request:
        return request, False
    return None


def _checkable(result: WorkflowResult) -> list[Expectation]:
    return [e for e in result.verified_expectations if e.check]


def _response_var(index: int) -> str:
    return f"response_{index}"


def _graded_against(expectation: Expectation, step_count: int) -> int:
    """The replayed step whose response this expectation was graded against.

    Out of range is a malformed report rather than something to paper over: the
    verifier only ever binds an expectation to a step that produced an observation.
    """
    if expectation.step_index is None:
        return step_count - 1
    if not 0 <= expectation.step_index < step_count:
        raise ValueError(
            f"expectation {expectation.id!r} is bound to step {expectation.step_index}, "
            f"but only {step_count} step(s) of its workflow ran; qabot.testgen will not "
            "guess which response it was verified against"
        )
    return expectation.step_index


def _assert_expression(expectation: Expectation, response: str) -> str:
    """Render one `check` dict as a Python assert expression against `response`.

    An unknown kind raises rather than being skipped: it means the verifier grew a
    check this module cannot express, and a run that silently emits fewer tests
    than it verified is the exact dishonesty this module is built to prevent.
    """
    check = expectation.check  # _checkable guarantees this is populated
    kind = check["kind"]
    if kind == "status":
        return f"{response}.status_code == {check['value']!r}"
    if kind == "json_eq":
        return f"_dig({response}.json(), {check['path']!r}) == {check['value']!r}"
    if kind == "json_contains":
        return f"{check['value']!r} in _dig({response}.json(), {check['path']!r})"
    if kind == "json_len_gt":
        return f"len(_dig({response}.json(), {check['path']!r})) > {check['value']!r}"
    raise ValueError(
        f"qabot.testgen cannot emit an assertion for check kind {kind!r} "
        f"(expectation {expectation.id!r}); teach testgen the kind or stop emitting it"
    )


def _render_assertion(expectation: Expectation, steps: list[StepResult], indent: str) -> list[str]:
    index = _graded_against(expectation, len(steps))
    response = _response_var(index)
    message = f"{expectation.statement} [verified by qabot in the generating run]"
    return [
        f"{indent}# provenance: {expectation.provenance.value}",
        f"{indent}# graded against step {index}: {_intent_label(steps[index].intent)}",
        f"{indent}assert {_assert_expression(expectation, response)}, (",
        f"{indent}    {message!r}",
        f"{indent})",
        "",
    ]


def _argument(value: object, templated: bool) -> str:
    return f"_fill({value!r}, captured)" if templated else repr(value)


def _sendable_headers(source: dict) -> dict | None:
    """The headers a replay may send: everything the driver did not withhold.

    A redacted value is a credential the generating run held and this file must not,
    so it is dropped rather than emitted. Sending the literal marker would produce a
    rejection that looks like a finding, which is the same lie as a partial replay.
    """
    headers = source.get(HEADERS_KEY)
    if not isinstance(headers, dict):
        return None
    return {name: value for name, value in headers.items() if value != REDACTED} or None


def _withheld_credentials(emittable: list[tuple[WorkflowResult, list[Expectation]]]) -> bool:
    """Did the generating run send credentials this file cannot carry?

    Read off the recorded request rather than the replay source, because the two
    differ exactly here: a templated step replays from its hint, which never held the
    credentials, so the hint alone would say "no auth" about an authenticated run.
    Cookies count as much as headers -- a replay missing a session is rejected exactly
    as hard as one missing a bearer token.
    """
    for result, _ in emittable:
        for step in _replayed_steps(result):
            request = step.evidence.get(REQUEST_KEY)
            if not isinstance(request, dict):
                continue
            for key in (HEADERS_KEY, COOKIES_KEY):
                sent = request.get(key)
                if isinstance(sent, dict) and REDACTED in sent.values():
                    return True
    return False


def _render_step(step: StepResult, index: int, indent: str) -> list[str]:
    source, templated = _replay_source(step)  # type: ignore[misc]  # _plan filtered these
    response = _response_var(index)
    path = _argument(source[PATH_KEY], templated)

    lines = [
        f"{indent}# step {index}: {_intent_label(step.intent)}",
        f"{indent}{response} = client.request(",
        f"{indent}    {source[METHOD_KEY]!r},",
        f"{indent}    {f'str({path})' if templated else path},",
    ]
    if source.get(JSON_KEY) is not None:
        lines.append(f"{indent}    json={_argument(source[JSON_KEY], templated)},")
    headers = _sendable_headers(source)
    if headers:
        lines.append(f"{indent}    headers={_argument(headers, templated)},")
    lines.append(f"{indent})")

    lines += [
        f"{indent}captured[{name!r}] = _dig({response}.json(), {str(field)!r})"
        for name, field in (source.get(CAPTURE_KEY) or {}).items()
    ]
    lines.append("")
    return lines


def _uncheckable_statements(result: WorkflowResult) -> list[str]:
    return [f.statement for f in result.findings if f.outcome is Outcome.BLOCKED]


def _render_docstring(result: WorkflowResult, indent: str) -> list[str]:
    lines = [
        f'{indent}"""{_docstring_safe(result.workflow_name)}',
        "",
        f"{indent}Generated by qabot from a verified run: every assertion below was",
        f"{indent}observed against the running app, not inferred from reading code.",
    ]
    uncheckable = _uncheckable_statements(result)
    if result.outcome is Outcome.BLOCKED:
        lines += [
            "",
            f"{indent}The generating run could not check everything in this workflow, so",
            f"{indent}this test covers only the part that was verified. Not checked:",
        ]
        lines += [f"{indent}  - {_docstring_safe(s)}" for s in uncheckable] or [
            f"{indent}  - (no reason recorded)"
        ]
    lines.append(f'{indent}"""')
    return lines


def _render_test(result: WorkflowResult, expectations: list[Expectation]) -> list[str]:
    steps = _replayed_steps(result)
    templated = any(_replay_source(s)[1] for s in steps)  # type: ignore[index]

    lines = [f"def test_{_identifier(result.workflow_id)}() -> None:"]
    lines += _render_docstring(result, "    ")
    if templated:
        lines.append("    captured: dict[str, object] = {}")
    lines.append("    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:")
    if not templated:
        lines += [f"        # {line}" for line in textwrap.wrap(_CONCRETE_WARNING, width=80)]
    lines += [
        "        # Replay. These steps are setup, not claims -- qabot asserts only",
        "        # the expectations it verified, which follow the last step.",
    ]
    for index, step in enumerate(steps):
        lines += _render_step(step, index, "        ")
    lines.append("        # Verified expectations. These, and only these, are the claims.")
    for expectation in expectations:
        lines += _render_assertion(expectation, steps, "        ")
    lines.append("")
    return lines


def _plan(
    results: list[WorkflowResult],
) -> tuple[list[tuple[WorkflowResult, list[Expectation]]], list[str]]:
    """Split contributing workflows into the ones we will commit a test for and the
    ones we will only account for in a comment."""
    emittable: list[tuple[WorkflowResult, list[Expectation]]] = []
    notes: list[str] = []
    for result in results:
        if result.outcome not in EMITTING_OUTCOMES:
            notes.append(
                f"{result.workflow_id}: the run found a failure here, so behavior observed "
                "alongside it may be an artifact of the failure and is not safe to codify."
            )
            continue

        expectations = _checkable(result)
        if not expectations:
            notes.append(
                f"{result.workflow_id}: every verified expectation is prose-only. A "
                "model's judgment that something held is not stable enough to commit "
                "as a test, so nothing is asserted here."
                if result.verified_expectations
                else f"{result.workflow_id}: nothing was verified, so there is nothing to assert."
            )
            continue

        steps = _replayed_steps(result)
        if not steps:
            notes.append(
                f"{result.workflow_id}: no step of this workflow completed, so there is "
                "no interaction to replay."
            )
            continue

        # Browser workflows are recognised and declined explicitly. Their steps have
        # no HTTP request to replay, and generating a Playwright regression test is a
        # different generator that does not exist yet. Saying so is better than the
        # generic "no recorded request" note, which would misdiagnose it.
        if any(isinstance(s.evidence.get("op"), str) for s in steps):
            notes.append(
                f"{result.workflow_id}: this is a browser workflow. qabot verified it "
                "through a real browser, but does not yet generate Playwright "
                "regression tests, so nothing is committed for it here."
            )
            continue

        unreplayable = [s.intent for s in steps if _replay_source(s) is None]
        if unreplayable:
            notes.append(
                f"{result.workflow_id}: no recorded request for step(s) "
                f"{', '.join(repr(i) for i in unreplayable)}, so the workflow cannot be "
                "replayed faithfully. A partial replay that still asserts the ending "
                "would be a test that lies."
            )
            continue

        emittable.append((result, expectations))
    return emittable, notes


def _needs_fill(emittable: list[tuple[WorkflowResult, list[Expectation]]]) -> bool:
    return any(
        _replay_source(s)[1]  # type: ignore[index]
        for result, _ in emittable
        for s in _replayed_steps(result)
    )


def _needs_dig(emittable: list[tuple[WorkflowResult, list[Expectation]]]) -> bool:
    captures = any(
        _replay_source(s)[0].get(CAPTURE_KEY)  # type: ignore[index]
        for result, _ in emittable
        for s in _replayed_steps(result)
    )
    return captures or any(e.check["kind"] != "status" for _, exps in emittable for e in exps)


def _render_module(
    results: list[WorkflowResult],
    base_url_var: str,
    run_ref: str | None,
) -> str:
    emittable, notes = _plan(results)

    header = ["# Generated by qabot. Do not edit by hand -- regenerate from a QA run."]
    if run_ref is not None:
        header.append(f"# Run: {run_ref}")
    header += [
        "#",
        "# Every assertion in this file was observed and verified against the running",
        "# app during that run. Nothing here asserts behavior qabot could not confirm:",
        "# failing workflows contribute nothing, and expectations only a model judged",
        "# to hold are listed below as omissions rather than committed.",
    ]
    if _withheld_credentials(emittable):
        header.append("#")
        header += [f"# {line}" for line in textwrap.wrap(WITHHELD_CREDENTIALS_NOTE, width=84)]
    if notes:
        header += ["#", "# Verified but NOT asserted here:"]
        for note in notes:
            wrapped = textwrap.wrap(note, width=84)
            header.append(f"#   - {wrapped[0]}")
            header += [f"#     {line}" for line in wrapped[1:]]

    lines = [
        *header,
        "",
        "import os",
        "",
        "import httpx",
        "",
        f"{base_url_var} = os.environ[{base_url_var!r}]  # no default, on purpose",
        "",
    ]
    if _needs_fill(emittable):
        lines.append(_FILL_HELPER)
    if _needs_dig(emittable):
        lines.append(_DIG_HELPER)
    lines.append("")
    for result, expectations in emittable:
        lines += _render_test(result, expectations)
    return "\n".join(lines).rstrip() + "\n"


def render_test_module(results: list[WorkflowResult], base_url_var: str = "BASE_URL") -> str:
    """Render contributing workflows as a runnable pytest + httpx module."""
    return _render_module(results, base_url_var=base_url_var, run_ref=None)


def emit_tests(report: RunReport, module_name: str = "qa_generated") -> dict[str, str]:
    """Map of filename -> source for the tests this run earned the right to commit.

    Empty when no workflow contributed: there is then nothing verified to write
    down, and an empty test file next to a report full of findings reads like
    coverage.
    """
    # Contributing outcomes are necessary but not sufficient: a workflow can pass and
    # still earn no test (every expectation prose-only, or a browser workflow we do
    # not codify yet). Planning first means we never write a module whose only content
    # is an explanation of why it is empty -- that is a report's job, not a test file's.
    emittable, _ = _plan(report.results)
    if not emittable:
        return {}
    run_ref = f"{report.repo} {report.base_ref} -> {report.head_ref}"
    source = _render_module(report.results, base_url_var="BASE_URL", run_ref=run_ref)
    return {f"test_{module_name}.py": source}
