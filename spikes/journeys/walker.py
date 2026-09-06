"""Walk one journey: for each step, act until the model says the step is done, then judge
whether what the step said would be seen is on screen.

Two kinds of finding come out and stay apart. App-declared ones (a 5xx, an uncaught
error, the app's own error screen) come from `qabot.intrinsics` and `page_checks` and
keep their severity. A `see` the judge calls failed is an inference and is filed at
QUESTION; the walker never upgrades it.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

from qabot.drivers.base import Action, Observation
from qabot.drivers.browser import OPS
from qabot.intrinsics import intrinsic_findings
from qabot.models import Finding, Outcome, Provenance, Severity, Step, Workflow
from spikes.journeys.models import (
    ActionRecord,
    Journey,
    JourneyResult,
    StepOutcome,
    StepResult,
)
from spikes.journeys.snapshot import trimmed_snapshot, visible_text

MAX_ACTIONS_PER_STEP = 6
#: After every action the page is given this long to go quiet before it is read. A
#: single-page app answers `goto` with its shell and draws the real page later; deciding
#: from the shell is deciding from "Loading…".
SETTLE_NETWORK_IDLE_MS = 8000
SETTLE_PAUSE_S = 0.5
#: The page is "settled" when its visible text has not changed across this many
#: consecutive samples, or when this much time has passed. A single-page app's own
#: "Loading…" screen is text that changes, so it never counts as settled.
SETTLE_STABLE_SAMPLES = 2
SETTLE_MAX_S = 20.0

WALK_SYSTEM = (
    "You operate a web application through a browser to carry out one step of a user "
    'journey. You see the page as an accessibility outline (role "name"). Choose ONE next '
    "action, in exactly this vocabulary:\n"
    '{"op":"goto","path":"/..."} | {"op":"click","role":"button","name":"..."} | '
    '{"op":"fill","role":"textbox","name":"...","value":"..."} | '
    '{"op":"select","role":"combobox","name":"...","value":"..."} | '
    '{"op":"done"} when the step\'s action is complete and its expected result should be '
    'on screen | {"op":"blocked","reason":"..."} when no control on the page can do this '
    "step.\n"
    "Use role and name exactly as the outline shows them. Never submit a form the step did "
    "not ask for. Never invent a control that is not in the outline. The step describes a "
    "purpose, not a pixel: when the control it names is absent, use the control on the page "
    "that plainly serves the same purpose (a first-run welcome screen's 'Create first flow' "
    "is how a fresh install reaches its starter templates), and say blocked only when "
    "nothing on the page serves it. Work toward what the step expects to SEE: if the "
    "expected items are not on screen but a control promises more of them ('Browse more', "
    "'See all', a search box), use it before leaving the screen; never say done until the "
    "expected result is either on screen or plainly absent. Answer with ONLY the JSON object."
)

JUDGE_SYSTEM = (
    "You judge whether a user journey step's expected result is on screen. You get the "
    "expectation and the page's visible text and outline. Answer ONLY "
    '{"verdict":"held"|"failed"|"unclear","reason":"<=25 words"}. "held" only if the '
    'expectation is plainly satisfied; "failed" only if the screen plainly contradicts it; '
    'otherwise "unclear".'
)

_ERROR_SCREEN = [
    r"the application encountered an unexpected error",
    r"application error: a client-side exception",
    r"something went wrong",
    r"an unexpected error (has )?occurred",
    r"unable to connect to|connection failed",
    r"flow build blocked|build failed|internal server error",
]


def page_checks(text: str) -> list[str]:
    """App-declared failure in the page's own words, or a blank page."""
    norm = " ".join(text.split())
    if not norm:
        return ["the page is blank: no visible text"]
    for pat in _ERROR_SCREEN:
        m = re.search(pat, norm, re.IGNORECASE)
        if m:
            excerpt = norm[max(0, m.start() - 40) : m.end() + 80]
            return [f"the page shows its own error text: …{excerpt}…"]
    return []


def _settle(page) -> None:
    """Wait for the page to stop changing; never fail the walk over a slow page.

    Network idle is necessary and not sufficient: Langflow answers `goto` with a shell
    that says "Loading…" and draws the page seconds later from its own store. So after
    the network goes quiet the visible text is sampled until it holds still.
    """
    with contextlib.suppress(Exception):  # a busy page is still a page we can read
        page.wait_for_load_state("networkidle", timeout=SETTLE_NETWORK_IDLE_MS)
    deadline = time.monotonic() + SETTLE_MAX_S
    last, stable = None, 0
    while time.monotonic() < deadline:
        time.sleep(SETTLE_PAUSE_S)
        text = _text_or_none(page)
        if text is None:
            continue  # mid-navigation; sample again
        loading = text.strip().lower() in ("", "loading...", "loading…")
        stable = stable + 1 if (text == last and not loading) else 0
        last = text
        if stable >= SETTLE_STABLE_SAMPLES - 1:
            return


def _text_or_none(page) -> str | None:
    try:
        return visible_text(page)
    except Exception:  # noqa: BLE001 -- the document is being replaced
        return None


def _is_html(page) -> bool:
    try:
        return str(page.evaluate("() => document.contentType")).startswith("text/html")
    except Exception:  # noqa: BLE001 -- unreadable document: do not grade its text
        return False


def _screenshot(page, artifacts: Path, index: int, n: int) -> str | None:
    path = Path(artifacts) / f"settled_{index + 1:02d}_{n:02d}.png"
    try:
        page.screenshot(path=str(path))
    except Exception:  # noqa: BLE001 -- a screenshot is evidence, not a step
        return None
    return str(path)


def _decide(llm, journey: Journey, step_index: int, page, history: list[str]) -> dict:
    step = journey.steps[step_index]
    prompt = (
        f"Journey: {journey.title}\nStep {step_index + 1}: DO: {step.do}\n"
        f"EXPECT TO SEE: {step.see}\n"
        f"Current URL: {page.url}\nLast actions: {json.dumps(history[-3:])}\n\n"
        f"Page outline:\n{trimmed_snapshot(page)}"
    )
    return llm.complete_json(WALK_SYSTEM, prompt, {"op": ""})


def _page_summary(page) -> str:
    """What the judge reads. An API response is summarised structurally -- top-level keys
    with the number of entries under each -- because 6,000 characters of raw JSON say
    nothing about whether a category is empty, and that is usually the question."""
    text = visible_text(page)
    if _is_html(page):
        return f"Visible text:\n{text[:6000]}\n\nOutline:\n{trimmed_snapshot(page, cap=6000)}"
    try:
        data = json.loads(text)
    except ValueError:
        return f"Raw response (not HTML):\n{text[:6000]}"
    if isinstance(data, dict):
        lines = [f"JSON object with {len(data)} top-level keys:"]
        for key, value in list(data.items())[:200]:
            size = len(value) if isinstance(value, (dict, list)) else 1
            names = ", ".join(list(value)[:12]) if isinstance(value, dict) else ""
            lines.append(f"- {key}: {size} entries" + (f" [{names}]" if names else ""))
        return "\n".join(lines)
    if isinstance(data, list):
        return f"JSON array with {len(data)} items; first: {json.dumps(data[:1])[:800]}"
    return f"JSON value: {text[:800]}"


def _judge(llm, step_see: str, page) -> dict:
    prompt = f"Expected to see: {step_see}\n\n{_page_summary(page)}"
    return llm.complete_json(JUDGE_SYSTEM, prompt, {"verdict": "", "reason": ""})


def _click_first(page, action: Action, failed: Observation) -> Observation:
    """A name that resolves to two controls is, in this UI, one control drawn twice (a
    sidebar item is a div with a role and a button inside it). Click the first and say so;
    the driver's refusal stays in the record as the reason a fallback was needed."""
    role, name = str(action.params.get("role")), str(action.params.get("name"))
    try:
        page.get_by_role(role, name=name).first.click(timeout=10000)
    except Exception as exc:  # noqa: BLE001 -- the fallback failing is just a failed click
        return Observation(
            ok=False,
            summary=f"{failed.summary} (first-match fallback failed)",
            evidence={**failed.evidence, "fallback_error": str(exc)[:300]},
        )
    return Observation(
        ok=True,
        summary=f"click first of the controls named {name!r}",
        evidence={**failed.evidence, "fallback": "first match after a strict-mode violation"},
    )


def _to_action(decision: dict) -> Action | None:
    op = decision.get("op")
    if op not in OPS:
        return None
    keys = ("op", "path", "role", "name", "value")
    params = {k: v for k, v in decision.items() if k in keys}
    return Action(kind="browser", params=params)


def _declared_findings(journey: Journey, do: str, obs: Observation, page) -> list[Finding]:
    wf = Workflow(id=journey.id, name=journey.title, steps=[Step(intent=do)])
    found = intrinsic_findings(wf, {0: obs})
    if not _is_html(page):
        return found  # an API response is data, not a screen; its words are not errors
    for detail in page_checks(visible_text(page)):
        found.append(
            Finding(
                workflow_id=journey.id,
                workflow_name=journey.title,
                severity=Severity.BUG,
                outcome=Outcome.FAIL,
                statement="the page rendered an error state",
                detail=detail,
                provenance=None,
                oracle="page_error_screen",
                repro=[do],
                evidence={"url": page.url},
            )
        )
    return found


def _inferred_finding(journey: Journey, step_see: str, reason: str) -> Finding:
    return Finding(
        workflow_id=journey.id,
        workflow_name=journey.title,
        severity=Severity.QUESTION,
        outcome=Outcome.FAIL,
        statement=f"expected to see: {step_see}",
        detail=reason,
        provenance=Provenance.INFERRED_FROM_CODE,
        oracle=None,
        repro=[],
        evidence={},
    )


def _walk_step(journey: Journey, index: int, driver, page, llm, artifacts: Path) -> StepResult:
    step = journey.steps[index]
    actions: list[ActionRecord] = []
    findings: list[Finding] = []
    history: list[str] = []
    outcome = StepOutcome.BLOCKED
    reason = f"could not complete in {MAX_ACTIONS_PER_STEP} actions"
    for _ in range(MAX_ACTIONS_PER_STEP):
        decision = _decide(llm, journey, index, page, history)
        op = decision.get("op")
        if op == "done":
            verdict = _judge(llm, step.see, page)
            reason = str(verdict.get("reason", ""))
            v = verdict.get("verdict")
            if v == "held":
                outcome = StepOutcome.HELD
            elif v == "failed":
                outcome = StepOutcome.FAILED
                findings.append(_inferred_finding(journey, step.see, reason))
            else:
                reason = f"could not tell whether it held: {reason}"
            break
        if op == "blocked":
            reason = str(decision.get("reason", "the model could not find a way"))
            break
        action = _to_action(decision)
        if action is None:
            reason = f"model returned an unusable action: {decision!r}"
            break
        obs = driver.execute(action)
        if not obs.ok and "strict mode violation" in str(obs.evidence.get("error", "")):
            obs = _click_first(page, action, obs)
        _settle(page)
        shot = _screenshot(page, artifacts, index, len(actions) + 1)
        actions.append(
            ActionRecord(
                op=str(action.params["op"]),
                params=dict(action.params),
                ok=obs.ok,
                summary=obs.summary,
                error=str(obs.evidence.get("error") or ""),
                screenshot=shot,
            )
        )
        history.append(obs.summary)
        findings.extend(_declared_findings(journey, step.do, obs, page))
    return StepResult(
        index=index,
        do=step.do,
        see=step.see,
        outcome=outcome,
        reason=reason,
        actions=actions,
        findings=findings,
        screenshot=actions[-1].screenshot if actions else None,
    )


def unmet_preconditions(journey: Journey, env: dict[str, str] | None) -> list[str]:
    """Settings the journey needs that this instance does not provide, in words.

    A journey that asks for a custom components path on an instance without one is
    not a failing journey, it is one this run cannot check; walking it anyway is how
    an unmet precondition becomes a false finding. `env` is what the operator says the
    instance was started with; `None` means "unknown", which blocks nothing and is
    stated in the report.
    """
    from spikes.journeys.launcher import env_key, needs_materialising

    if env is None:
        return []
    unmet = []
    for key, wanted in journey.preconditions.settings.items():
        have = env.get(key, env.get(env_key(key)))
        if have is None:
            unmet.append(f"{key} is required ({wanted!r}) and this instance does not set it")
        elif needs_materialising(str(wanted)):
            continue  # the description was materialised; the instance has *a* value for it
        elif str(have).strip().lower() != str(wanted).strip().lower():
            unmet.append(f"{key} must be {wanted!r} but this instance has {have!r}")
    return unmet


def walk(
    journey: Journey, driver, page, llm, artifacts: Path, env: dict[str, str] | None = None
) -> JourneyResult:
    Path(artifacts).mkdir(parents=True, exist_ok=True)
    results: list[StepResult] = []
    outcome = Outcome.PASS
    why = ""
    failed_reason: str | None = None
    unmet = unmet_preconditions(journey, env)
    if unmet:
        why = "precondition not met: " + "; ".join(unmet)
        results = [
            StepResult(index=i, do=st.do, see=st.see, outcome=StepOutcome.NOT_REACHED, reason=why)
            for i, st in enumerate(journey.steps)
        ]
        return JourneyResult(journey=journey, outcome=Outcome.BLOCKED, steps=results, why=why)
    for index, step in enumerate(journey.steps):
        if outcome is not Outcome.PASS:
            results.append(
                StepResult(index=index, do=step.do, see=step.see, outcome=StepOutcome.NOT_REACHED)
            )
            continue
        result = _walk_step(journey, index, driver, page, llm, artifacts)
        results.append(result)
        declared = [
            f for f in result.findings if f.oracle is not None and f.severity is Severity.BUG
        ]
        if declared:
            outcome = Outcome.FAIL
            why = declared[0].detail
        elif result.outcome is StepOutcome.FAILED:
            # An inferred failure marks the journey but does not end the walk: a later
            # step may be the decisive one (an API count after a UI impression), and the
            # reader wants to see it. Only an app-declared failure or a dead end stops us.
            if failed_reason is None:
                failed_reason = result.reason
        elif result.outcome is StepOutcome.BLOCKED:
            outcome = Outcome.BLOCKED
            why = result.reason
    if failed_reason is not None and outcome is Outcome.PASS:
        outcome, why = Outcome.FAIL, failed_reason
    elif failed_reason is not None and outcome is Outcome.BLOCKED:
        outcome, why = Outcome.FAIL, f"{failed_reason}; then blocked: {why}"
    return JourneyResult(journey=journey, outcome=outcome, steps=results, why=why)
