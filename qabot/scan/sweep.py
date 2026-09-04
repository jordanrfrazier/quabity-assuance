"""Drive one application we do not own, under a budget, and collect what it says.

The only impure unit in this package, which is why every other one is pure: the
expensive thing to test is tested once, here, and the cheap things are tested
thoroughly elsewhere.

Two rules govern everything below. **We are a guest**: bounded pages, a delay between
them, an immediate stop on 429, no form submission, no request the app did not invite.
And **nothing is silently dropped**: a page the budget cut is reported as not visited,
because a truncated run that reads like a complete one is the failure this whole
project exists to refuse.

Safe interaction is the part of this design most likely to be wrong, so it is the part
kept most reversible: the roles we will click are one constant, the names we refuse are
another, and every control actually clicked is recorded on the page result so a
surprising finding can be traced to the click that produced it.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, Field

from qabot.drivers.base import Action, DriverError, Observation
from qabot.intrinsics import intrinsic_findings
from qabot.models import Finding, Outcome, Severity, Step, Workflow
from qabot.scan.discovery import UNSAFE_WORDS, Discovery
from qabot.scan.grading import blank_page

#: Roles whose activation shows something already on the page. A `link` is excluded --
#: following it is navigation, and navigation is the crawler's job, not the clicker's.
SAFE_CLICK_ROLES: tuple[str, ...] = ("tab", "button")

#: How many controls to click per page. A cap rather than a filter: a page with forty
#: buttons is a page we should sample, not exhaust.
MAX_CLICKS_PER_PAGE = 5


class Budget(BaseModel):
    """What we are willing to spend on somebody else's server."""

    max_pages: int = 25
    delay_s: float = 1.0
    page_timeout_ms: float = 20000.0


class PageResult(BaseModel):
    path: str
    status: int | None = None
    title: str | None = None
    final_url: str | None = None
    screenshot: str | None = None
    clicked: list[str] = Field(default_factory=list)


class ScanResult(BaseModel):
    origin: str
    discovery: Discovery
    pages: list[PageResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    not_visited: list[str] = Field(default_factory=list)
    stopped: str | None = None


def _safe_to_click(name: str) -> bool:
    """A control whose name suggests it changes something is never clicked.

    The same vocabulary discovery refuses to follow. Matching on the accessible name
    is a blunt instrument and deliberately so: on an application we do not own, a
    false refusal costs one unclicked button and a false acceptance can cost somebody
    their data.
    """
    lowered = name.lower()
    return bool(name.strip()) and not any(word in lowered for word in UNSAFE_WORDS)


def _accessible_name(locator) -> str:
    """The name a user perceives, which is not the same as the element's text.

    A button labelled `aria-label="Close dialog"` whose text is "X" is reachable as
    "Close dialog" and unreachable as "X" -- so reading text alone yields names the
    driver cannot then locate, and each one costs a full click timeout to discover.
    aria-label wins because that is what the accessibility tree exposes.
    """
    try:
        return (locator.get_attribute("aria-label") or locator.inner_text() or "").strip()
    except Exception:  # noqa: BLE001 -- probing an element must never fail the sweep
        return ""


def _click_safely(driver, page) -> tuple[list[str], list[Observation]]:
    """Click a bounded sample of safe controls. Returns the names clicked AND the
    observations those clicks produced.

    **Returning the observations is not a convenience, it is the whole point.** The
    driver drains its event buffer on every `execute` call, so an error a click causes
    lands in that click's own Observation and is gone by the time anything reads the
    page again. A version of this that returned only names would click things and throw
    away precisely the evidence clicking exists to gather -- the trailing `read` would
    find an empty buffer and the run would report nothing.

    Two further rules separate a record from a fiction. A name is only used when it
    resolves to exactly one control: zero means we read a name the accessibility tree
    does not expose, and more than one is a strict-mode violation the driver would raise
    on -- both waste a full timeout to learn nothing. And a name is recorded only when
    the interaction reported `ok`, because `driver.execute` returns a failed Observation
    rather than raising. Every observation is returned regardless of `ok`, though:
    events are evidence whether or not the interaction completed, and a page too broken
    to finish a click is exactly the page whose errors matter most.
    """
    clicked: list[str] = []
    observations: list[Observation] = []
    for role in SAFE_CLICK_ROLES:
        try:
            candidates = page.get_by_role(role).all()
        except Exception:  # noqa: BLE001, S112 -- probing the page must never fail the sweep
            continue
        for candidate in candidates:
            if len(clicked) >= MAX_CLICKS_PER_PAGE:
                return clicked, observations
            name = _accessible_name(candidate)
            if not _safe_to_click(name):
                continue
            try:
                if page.get_by_role(role, name=name).count() != 1:
                    continue
            except Exception:  # noqa: BLE001, S112 -- a strict-mode probe must never fail the sweep
                continue
            try:
                observation = driver.execute(
                    Action(kind="browser", params={"op": "click", "role": role, "name": name})
                )
            except DriverError:
                continue  # a malformed action is an authoring bug, not a finding here
            observations.append(observation)
            if observation.ok:
                clicked.append(name)
    return clicked, observations


def _merge_events(first: Observation, second: Observation) -> Observation:
    """Fold a follow-up read's events into the observation that caused them.

    A page's most interesting events arrive after load settles -- a failed XHR, a
    deferred script throwing. Attributing them to the navigation that started them is
    the same principle the driver applies per interaction.
    """
    a = first.evidence.get("browser_events") or {}
    b = second.evidence.get("browser_events") or {}
    merged: dict[str, object] = {}
    for key in set(a) | set(b):
        left, right = a.get(key), b.get(key)
        if isinstance(left, list) or isinstance(right, list):
            merged[key] = list(left or []) + list(right or [])
        elif isinstance(left, int) and isinstance(right, int):
            merged[key] = left + right
        else:
            merged[key] = right if left is None else left
    first.evidence["browser_events"] = merged
    if second.evidence.get("text"):
        first.evidence["text"] = second.evidence["text"]
    return first


def sweep(
    discovery: Discovery,
    driver,
    status_of: Callable[[str], int | None],
    budget: Budget = Budget(),  # noqa: B008 -- Budget is immutable; nothing here mutates the shared default
) -> ScanResult:
    """Visit every discovered path we can afford, and report what the app said."""
    pages: list[PageResult] = []
    observations: dict[int, Observation] = {}
    steps: list[Step] = []
    extra: list[Finding] = []
    stopped: str | None = None
    visited: list[str] = []

    for path in discovery.paths:
        if len(pages) >= budget.max_pages:
            stopped = f"page budget of {budget.max_pages} reached"
            break

        status = status_of(path)
        if status == 429:
            stopped = "the application asked us to slow down (HTTP 429)"
            break

        observation = driver.execute(Action(kind="browser", params={"op": "goto", "path": path}))
        settled = driver.execute(Action(kind="browser", params={"op": "read"}))
        observation = _merge_events(observation, settled)

        # driver._page: BrowserDriver exposes no "what is on this page" query, and
        # adding one would be a change to shared CI-product code for a scan-only need.
        clicked, click_observations = _click_safely(driver, driver._page)
        # Fold in what each click produced. The driver drained those events into the
        # click's own Observation, so they exist nowhere else by now.
        for click_observation in click_observations:
            observation = _merge_events(observation, click_observation)
        if clicked:
            after = driver.execute(Action(kind="browser", params={"op": "read"}))
            observation = _merge_events(observation, after)

        index = len(pages)
        observations[index] = observation
        steps.append(Step(intent=f"open {path}"))
        pages.append(
            PageResult(
                path=path,
                status=status,
                title=str(observation.evidence.get("title") or "") or None,
                final_url=str(observation.evidence.get("url") or "") or None,
                screenshot=str(observation.evidence.get("screenshot") or "") or None,
                clicked=clicked,
            )
        )
        visited.append(path)

        detail = blank_page(observation, status)
        if detail:
            extra.append(
                Finding(
                    workflow_id="scan",
                    workflow_name=f"open {path}",
                    severity=Severity.BUG,
                    outcome=Outcome.FAIL,
                    statement="the page loaded but rendered nothing",
                    detail=detail,
                    oracle="blank_page",
                )
            )

        if budget.delay_s:
            time.sleep(budget.delay_s)

    workflow = Workflow(id="scan", name=f"scan of {discovery.origin}", steps=steps)
    findings = [*intrinsic_findings(workflow, observations), *extra]

    return ScanResult(
        origin=discovery.origin,
        discovery=discovery,
        pages=pages,
        findings=findings,
        limitations=list(getattr(driver, "limitations", [])),
        not_visited=sorted(set(discovery.paths) - set(visited)),
        stopped=stopped,
    )
