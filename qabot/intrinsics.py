"""Intrinsic oracles: the findings the application declared about itself.

Everything else in this codebase reasons from an `Expectation` -- something a human
confirmed, a test asserted, or a model inferred -- and every finding it produces is
graded by where that expectation came from. An intrinsic oracle is a different class
of finding: nothing was inferred. A 500 is not our reading of what the app was
supposed to do, it is the app's own report that it could not do it.

**Why the top tier bypasses PROVENANCE_CAP.** This is not an exception to rule 1 of
`verifier.py`, it is what rule 1 implies. The cap exists to bound *inference*:
HUMAN_CONFIRMED earns BUG because a person vouched for the statement,
INFERRED_FROM_CODE earns only QUESTION because we read the code and guessed at its
intent, and a guess that is wrong about intent produces a finding about nothing. A
finding that says only "the server returned 500" carries no statement about intended
behavior, so there is no inference in it to discount. Capping it would mean
discounting the application's own error signal by our confidence in an expectation
that does not exist. The cap is not abandoned here; it is inapplicable.

**Two tiers, and the test that splits them.** Skipping the cap is earned by one
property only -- that the application declared the failure itself -- so every signal
is tested against that literally, not by whether it smells like a defect:

  * `page_errors` and 5xx: the JavaScript runtime and the server each reported their
    own failure. Nothing read, nothing inferred. **BUG, uncapped.**
  * `console.error`: an app-authored log line. Calling it a defect infers that the
    developer's choice of log level means something is broken, and real applications
    log expected conditions at error level constantly. That is an inference, so it
    does not clear the bar. **QUESTION.**
  * a failed request: often the app getting what it asked for -- navigation cancels
    in-flight requests and `net::ERR_ABORTED` is the intended outcome. Also an
    inference. **QUESTION.**

QUESTION is not a hedge and it is not silence, which this codebase treats as the one
unacceptable outcome; it is the severity this product already uses for "noticed,
cannot call it". The tiers must stay countable apart, because a false-positive rate
published over both at once would let a good number in one hide a bad one in the
other. The partition is exactly `(finding.oracle is not None, finding.severity)` --
see `declares_failure` -- and never a substring of a finding's prose.

The corollary is a duty rather than a licence: the uncapped tier may only assert
things the app itself said. The moment an oracle there starts inferring -- "this
response looks wrong", "this page is probably broken" -- it has quietly re-acquired
a provenance and forfeited the reason it was allowed to skip the cap.

**Why 4xx is deliberately not an oracle.** A 401 on an unauthenticated request and a
404 on a resource that genuinely does not exist are the app behaving correctly, and
both are routine in any run that exercises auth or reads an id it did not create.
4xx means "your request was wrong", which is a claim about the caller; only an
expectation can say whether the caller was right to make that request. 5xx means "I
failed", which is a claim the app makes about itself. Firing on 4xx would trade this
layer's one real asset -- that it cannot be wrong about whether something is wrong --
for volume, and STRATEGY.md §7 puts the price of that at a <10% false-positive
budget for the entire product.

**Two shapes of oracle.** A response oracle reads a property one response either has
or does not: a status, a body. An event oracle reads a stream the browser recorded
during one interaction, where the same defect can arrive forty times from one page,
so its findings are aggregated by message with a count. Both are pure functions over
an Observation and neither knows which driver produced it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import NamedTuple

from qabot.drivers.base import Observation
from qabot.models import Finding, Outcome, Severity, Workflow

#: At or above this, the response is the application reporting its own failure.
SERVER_ERROR_STATUS = 500

#: The severity that marks the uncapped tier. See `declares_failure`.
DECLARED_FAILURE = Severity.BUG

#: Literal strings that only appear when a stack trace has reached the client.
#: Literals rather than shape heuristics on purpose: a heuristic that fires on prose
#: costs a false positive, and this is the one class of finding that must not have
#: one. Node and Ruby are absent for that reason -- their frame shape ("    at fn
#: (file.js:1:2)") is close enough to ordinary indented text that detecting them
#: cheaply would cost more precision than the missed traceback costs recall.
TRACEBACK_MARKERS: tuple[str, ...] = (
    "Traceback (most recent call last)",  # CPython, and anything embedding it
    "Werkzeug Debugger",  # Flask/Werkzeug interactive debug page
    "Django Version:",  # Django's technical 500 page
    'Exception in thread "',  # JVM uncaught exception dump
    "\n\tat ",  # JVM stack frame
)

#: Where the browser driver leaves the events it drained for one interaction, and the
#: categories inside it. Named as a string contract rather than imported, because
#: `qabot.drivers.browser` needs playwright and an HTTP-only install must not.
BROWSER_EVENTS = "browser_events"


class ResponseOracle(NamedTuple):
    """An oracle over one response. `detect` returns the detail line, or None."""

    name: str
    severity: Severity
    statement: str
    detect: Callable[[Observation], str | None]


class EventOracle(NamedTuple):
    """An oracle over the events one interaction produced.

    `category` is the key inside the driver's bundle. `describe` turns one event into
    the line that identifies it, which is also the key its findings aggregate by.
    """

    name: str
    severity: Severity
    statement: str
    category: str
    describe: Callable[[dict], str]


def declares_failure(finding: Finding) -> bool:
    """Whether this finding is one the application declared, rather than one we noticed.

    The single definition of the tier split, so the verifier's verdict, the report's
    sections and any measurement of this layer all partition the same way. It reads
    two typed fields and never the prose, because prose gets reworded and a
    false-positive rate that moves when someone edits a sentence is not a measurement.
    """
    return finding.oracle is not None and finding.severity is DECLARED_FAILURE


# --- response oracles ---------------------------------------------------------------


def server_error(observation: Observation) -> str | None:
    """Fires on 5xx. Returns the detail line, or None when the oracle is silent.

    An observation with no recorded status (a browser page, a transport failure) is
    not evidence either way, and silence is the only honest answer to it.
    """
    status = observation.evidence.get("status")
    if not isinstance(status, int) or status < SERVER_ERROR_STATUS:
        return None
    return f"{observation.summary} (status {status})"


def server_traceback(observation: Observation) -> str | None:
    """Fires when a server-side stack trace reached the client.

    Independent of status because the failure mode this catches is the 200 that
    carries a rendered exception page -- the app broke and told the user so in
    prose, which no status check can see.

    The known cost of reading the whole body: a page that merely *quotes* a trace --
    documentation, a changelog, a tutorial on error handling -- fires too. Narrowing
    the scope the way text checks narrow to role="alert" would not help, because a
    debug page renders its trace as ordinary body content, and it would lose the case
    this oracle exists for. Written down rather than tuned away: EVAL.md measures this
    layer's false-positive rate, and a known one nobody recorded gets rediscovered as
    a surprise.
    """
    body = observation.evidence.get("text")
    if not isinstance(body, str) or not body:
        return None
    marker = next((m for m in TRACEBACK_MARKERS if m in body), None)
    if marker is None:
        return None
    return f"{observation.summary}; the response body contains {marker!r}"


# --- event oracles ------------------------------------------------------------------


def describe_message(event: dict) -> str:
    """A logged message, keyed by its text alone.

    Deliberately not keyed by source location as well: one page can log the same
    message from more than one bundle, and the point of aggregating is that a reader
    sees one line per problem. The first occurrence's location goes in the detail,
    where it helps without splitting the count.
    """
    return str(event.get("text", "")).strip() or "(no message)"


def describe_request(event: dict) -> str:
    return f"{event.get('method', '?')} {event.get('url', '?')} -- {event.get('failure', '?')}"


def describe_response(event: dict) -> str:
    return f"{event.get('method', '?')} {event.get('url', '?')} -> {event.get('status', '?')}"


#: Ordered loudest-first within each shape, and stable: the name travels on the
#: Finding, so a reader can tell which app-declared signal they are looking at, and a
#: measurement can group by it, without parsing prose.
RESPONSE_ORACLES: tuple[ResponseOracle, ...] = (
    ResponseOracle(
        "server_error",
        Severity.BUG,
        "the application returned a server error",
        server_error,
    ),
    ResponseOracle(
        "server_traceback",
        Severity.BUG,
        "the application rendered a server-side stack trace into the response",
        server_traceback,
    ),
)

EVENT_ORACLES: tuple[EventOracle, ...] = (
    EventOracle(
        "browser_page_error",
        Severity.BUG,
        "the page raised an uncaught JavaScript error",
        "page_errors",
        describe_message,
    ),
    EventOracle(
        "browser_server_error",
        Severity.BUG,
        "a request the page made returned a server error",
        "server_errors",
        describe_response,
    ),
    EventOracle(
        "browser_console_error",
        Severity.QUESTION,
        "the page logged an error to its console",
        "console_errors",
        describe_message,
    ),
    EventOracle(
        "browser_failed_request",
        Severity.QUESTION,
        "a request the page made did not complete",
        "failed_requests",
        describe_request,
    ),
)


def intrinsic_findings(workflow: Workflow, observations: dict[int, Observation]) -> list[Finding]:
    """Every intrinsic finding this workflow's observations support.

    Response findings come first, in step order; event findings follow, aggregated
    across the whole workflow because a page that logs the same error on every step
    has one problem, not one per step.

    Note what is *not* here: any consultation of the workflow's outcome. A workflow
    that went BLOCKED at step 3 still produced observations at steps 0-2, and a 500
    at step 1 is very often the reason step 3 could not run. That crash is the most
    actionable thing the run found, and reporting only "could not test" would bury it.
    """
    if not observations:
        return []

    final_index = max(observations)
    graded = {
        index: observation
        for index, observation in observations.items()
        if not _expected(workflow, index, final_index)
    }
    if not graded:
        return []

    repro = [step.intent for step in workflow.steps]
    findings = _response_findings(workflow, graded, repro)
    findings += _event_findings(workflow, graded, repro)
    return findings


def _response_findings(
    workflow: Workflow, observations: dict[int, Observation], repro: list[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for index in sorted(observations):
        observation = observations[index]
        for oracle in RESPONSE_ORACLES:
            detail = oracle.detect(observation)
            if detail is None:
                continue
            findings.append(
                _finding(
                    workflow,
                    oracle.name,
                    oracle.severity,
                    oracle.statement,
                    detail,
                    repro,
                    observation,
                )
            )
    return findings


def _event_findings(
    workflow: Workflow, observations: dict[int, Observation], repro: list[str]
) -> list[Finding]:
    """One finding per distinct message, however many times the page emitted it.

    Forty copies of one console error is one defect and fifty findings from one page
    would cost the report both its readability and its precision number, so the count
    goes in the detail rather than into the finding list.

    `suppressed` is deliberately not folded into any detail. By the driver's own rule
    a suppressed event came from another origin, so attributing it to a finding about
    this application would misattribute it; the count stays in the finding's evidence,
    where anyone measuring the filter can still read it.
    """
    findings: list[Finding] = []
    for oracle in EVENT_ORACLES:
        counts: dict[str, int] = {}
        first_step: dict[str, int] = {}
        places: dict[str, list[str]] = {}
        truncated = 0
        for index in sorted(observations):
            events = observations[index].evidence.get(BROWSER_EVENTS)
            if not isinstance(events, dict):
                continue
            truncated = max(truncated, _truncated_count(events, oracle.category))
            for event in _events_in(events, oracle.category):
                key = oracle.describe(event)
                counts[key] = counts.get(key, 0) + 1
                first_step.setdefault(key, index)
                _add_place(places.setdefault(key, []), event)

        for key, count in counts.items():
            index = first_step[key]
            findings.append(
                _finding(
                    workflow,
                    oracle.name,
                    oracle.severity,
                    oracle.statement,
                    _event_detail(workflow, key, places[key], count, index, truncated),
                    repro,
                    observations[index],
                )
            )
    return findings


def _events_in(bundle: dict, category: str) -> Iterator[dict]:
    """The events of one category, skipping anything not shaped like an event.

    Tolerant on purpose: this reads a bundle another driver produced, and one
    malformed entry must not take down the oracle that would have reported the
    twenty valid ones beside it.
    """
    events = bundle.get(category)
    if not isinstance(events, list):
        return
    for event in events:
        if isinstance(event, dict):
            yield event


def _truncated_count(bundle: dict, category: str) -> int:
    """How many events of this category the browser saw when it saw more than it kept."""
    truncated = bundle.get("truncated")
    if not isinstance(truncated, dict):
        return 0
    count = truncated.get(category)
    return count if isinstance(count, int) else 0


def _event_detail(
    workflow: Workflow, key: str, places: list[str], count: int, index: int, truncated: int
) -> str:
    when = _step_label(workflow, index)
    occurrences = f"{count} occurrences, first during" if count > 1 else "during"
    detail = f"{key}{_where(places)} ({occurrences}: {when})"
    if truncated:
        detail += (
            f"; the browser recorded {truncated} of these in a single step, more than the "
            "driver keeps, so this count is a floor"
        )
    return detail


#: How many distinct source locations a finding names before it stops listing them.
PLACE_LIMIT = 3


def _add_place(places: list[str], event: dict) -> None:
    """Record where this event came from, keeping the distinct places in first order.

    Aggregation keys on the message alone, which is what makes forty copies one
    finding -- but one message can genuinely come from two call sites, and the first
    real browser run produced exactly that: the same TypeError thrown from two lines.
    Naming only the first would send a developer to fix one of them and believe they
    were done, so every distinct place is carried on the one finding rather than
    splitting the count.
    """
    place = _location(event)
    if place and place not in places:
        places.append(place)


def _where(places: list[str]) -> str:
    if not places:
        return ""
    if len(places) <= PLACE_LIMIT:
        return f" [{', '.join(places)}]"
    listed = ", ".join(places[:PLACE_LIMIT])
    return f" [{listed} and {len(places) - PLACE_LIMIT} more]"


def _location(event: dict) -> str:
    """Where a logged message came from, when the browser knew.

    Empty for request events: their url is already in the key, and repeating it would
    make the detail longer without making it say more.
    """
    if "text" not in event:
        return ""
    url = event.get("url")
    if not url:
        return ""
    line = event.get("line")
    return f"{url}:{line}" if isinstance(line, int) else str(url)


def _step_label(workflow: Workflow, index: int) -> str:
    if 0 <= index < len(workflow.steps):
        return workflow.steps[index].intent
    return f"step {index}"


def _finding(
    workflow: Workflow,
    oracle: str,
    severity: Severity,
    statement: str,
    detail: str,
    repro: list[str],
    observation: Observation,
) -> Finding:
    return Finding(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        severity=severity,
        outcome=Outcome.FAIL,
        statement=statement,
        detail=detail,
        provenance=None,
        oracle=oracle,
        repro=repro,
        evidence=dict(observation.evidence),
    )


def _expected(workflow: Workflow, index: int, final_index: int) -> bool:
    """Whether this workflow deliberately expects a server error at this step.

    An app that answers 503 where the knowledge base says it should answer 503 is
    behaving as specified, and calling that a BUG would be exactly the false positive
    this layer claims it cannot produce. Suppression is per step and covers every
    oracle: an expectation that says "this call returns 5xx" declares the whole error
    response intended -- the trace in its body and the browser's record of the same
    5xx are that one expected error seen from other angles, not extra defects.

    Binding mirrors `verifier._observation_for` -- a named step, or no step and
    therefore the last observation of the run. The guard has to ask the same question
    the verifier asks, "which expectations speak about *this* response", or it will
    suppress on the strength of an expectation about a different one.
    """
    for exp in workflow.expectations:
        bound = exp.step_index if exp.step_index is not None else final_index
        if bound != index or not exp.check:
            continue
        if exp.check.get("kind") != "status":
            continue
        value = exp.check.get("value")
        if isinstance(value, int) and value >= SERVER_ERROR_STATUS:
            return True
    return False
