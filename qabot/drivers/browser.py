"""Browser execution substrate.

WHY role+name and never CSS: a locator is knowledge, and knowledge that encodes DOM
structure (`div.sc-1x2y > button:nth-child(3)`) is invalidated by every restyle. A
role and an accessible name describe what a *user perceives* -- "the button labelled
Place order" -- which survives refactors and is the browser-side expression of the
rule that steps are intents, not selectors.

It has a second effect worth stating: the driver can only touch controls that are
actually in the accessibility tree. A button with no accessible name is unreachable,
the step reports BLOCKED with "no accessible control", and that is not a limitation
being papered over -- it is a real accessibility defect surfaced by the attempt.

WHY ok/false means "the interaction did not happen": identical to the HTTP driver.
A missing element or a timeout means we learned nothing, so it must reach the
verifier as BLOCKED. Only a completed interaction can support a pass or a failure.

WHY the driver listens to what the page says about itself: a title, some body text
and a screenshot describe what a *user* would see, and a page can look perfectly
healthy while it is throwing uncaught exceptions and its background fetches are
coming back 500. Those four signals -- uncaught exceptions, console errors, failed
requests, 5xx responses -- are the highest-precision evidence a browser can hand us,
because none of them had to be inferred: the page reported them itself.

WHY the four stay in separate categories rather than one list: they are not equally
strong, and the split is what lets a consumer act on the difference instead of
inheriting it. An uncaught exception and a 5xx are the runtime and the server each
reporting their own failure -- no reading is involved, so there is nothing in them to
be wrong about. A console.error is an app-authored log line, and real apps log
expected conditions at error level: a failed optional fetch, a noisy third-party
widget, a deprecation someone escalated. A failed request may equally be one the app
deliberately aborted. Those two are evidence, not verdicts. This driver captures all
four and grades none of them; what a signal is allowed to *mean* is the oracle
layer's call, made with the evidence in front of it. A driver that pre-judged it here
would be smuggling a severity decision into a capture layer, where nobody would think
to look for one.

WHY events are drained into each observation rather than accumulated over the run:
an error is only actionable if you know which interaction caused it. A buffer that
smears every event across a whole workflow yields evidence that does not support the
claim attached to it -- the exact failure verifier.py rule 3 exists to prevent -- so
each Observation carries precisely the events that arrived since the previous one.

WHY only two filter rules, and why they are about origin rather than severity: real
apps are noisy, and an unpredictable filter is worse than no filter, because nobody
can tell afterwards whether a quiet run was clean or censored. So exactly two rules,
both mechanical: (1) an event whose URL is not on the host under test is suppressed
-- an analytics tag exploding inside a third-party script is not a defect this team
can fix; (2) favicon requests are suppressed -- the browser asks for one unprompted
and a missing icon is not a bug anyone filed. Nothing is dropped for *looking*
unimportant, because that judgement is precisely what the oracle layer is supposed
to make with the evidence in front of it. Everything suppressed is counted, so a run
can say "12 suppressed" and a reader can go look; silence is the one outcome this
codebase treats as unacceptable.

Two capture scopes are narrower than they could be, also deliberately. Console
messages below `error` level are not collected at all: a dev-mode framework warning
is not evidence of a defect, and counting every console.log as "suppressed" would
turn a useful number into noise. Responses are collected at 5xx only: a 401 or a 404
is frequently the app behaving exactly as designed, whereas a 5xx never is.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from qabot.drivers.base import Action, DriverError, Observation

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from playwright.sync_api import ConsoleMessage, Locator, Page, Request, Response

#: Operations the driver understands. Anything else is a malformed plan.
OPS = frozenset({"goto", "click", "fill", "select", "read"})

#: How much page text to carry as evidence. Enough to explain a verdict, not so much
#: that a run report becomes a DOM dump.
TEXT_EVIDENCE_LIMIT = 2000

#: How many events of one kind to keep per observation. A page stuck in a render loop
#: emits thousands of identical console errors; twenty is far more than anyone needs to
#: diagnose one, and the true count travels alongside, so a cap can never be mistaken
#: for a quiet page.
EVENT_EVIDENCE_LIMIT = 20

#: The event categories captured, and the order they appear in evidence.
EVENT_KINDS = ("page_errors", "console_errors", "failed_requests", "server_errors")

#: Carried on the run when the caller declared the app has no reset endpoint.
NO_RESET_LIMITATION = (
    "the app has no reset endpoint, so pages were visited in sequence against whatever "
    "state earlier ones left behind: a finding here may depend on that accumulated "
    "state, and visiting the same pages in another order may not reproduce it"
)

#: First `http(s)://host/file.js:LINE:COL` in a stack trace. Uncaught exceptions reach
#: us as a message plus a stack and nothing else, so this is the only way to say where
#: one came from -- and a "where" is the difference between a report a developer can
#: open and one they have to reproduce first.
_STACK_FRAME = re.compile(r"(https?://[^\s)]+?):(\d+):\d+")


class BrowserDriver:
    """Drives a running web app through a real browser.

    Accepts an injected Page so tests can supply their own browser lifecycle, the
    same way HttpDriver accepts an injected client.
    """

    name = "browser"

    def __init__(
        self,
        base_url: str,
        page: Page,
        artifacts_dir: Path | None = None,
        timeout_ms: float = 5000.0,
        reset_path: str | None = "/reset",
    ):
        self.base_url = base_url.rstrip("/")
        self._page = page
        self._artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        if self._artifacts_dir:
            self._artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._timeout_ms = timeout_ms
        self._reset_path = reset_path
        self._shot_counter = 0
        #: The host the app under test is served from -- the whole of the origin rule.
        self._host = urlsplit(self.base_url).hostname
        #: Every host this app has served us from. The configured one seeds it; a
        #: redirect adds to it. See `_note_origin` for why this is a set and not a
        #: constant.
        self._hosts: set[str] = {self._host} if self._host else set()
        #: What this driver could not guarantee about the run. The caller reads it and
        #: the report prints it; opting out of reset is stated, never swallowed.
        self.limitations: list[str] = [] if reset_path is not None else [NO_RESET_LIMITATION]
        self._clear_events()
        page.on("pageerror", self._guard(self._on_page_error))
        page.on("console", self._guard(self._on_console))
        page.on("requestfailed", self._guard(self._on_request_failed))
        page.on("response", self._guard(self._on_response))

    def reset(self) -> None:
        """Return the app to a known state, if it has one to return to.

        Loud on failure, because a run that starts from an unknown state produces
        findings nobody can trust. That is exactly why opting out is a constructor
        argument rather than a rescued exception: no third-party app has a `/reset`
        endpoint, and treating its 404 as "fine" would turn every foreign run into the
        untrustworthy kind without anyone deciding to. `reset_path=None` is the caller
        deciding to, once, in the open. Cookies are still cleared -- that is our own
        browser state, and clearing it asks nothing of the app.
        """
        if self._reset_path is None:
            self._page.context.clear_cookies()
            self._clear_events()
            return
        try:
            response = self._page.request.post(f"{self.base_url}{self._reset_path}")
        except Exception as exc:  # playwright raises a broad Error type
            raise DriverError(
                f"reset failed: could not reach {self.base_url}{self._reset_path}: {exc}"
            ) from exc
        if not response.ok:
            raise DriverError(f"reset failed: POST {self._reset_path} returned {response.status}")
        self._page.context.clear_cookies()
        self._clear_events()

    def execute(self, action: Action) -> Observation:
        if action.kind != "browser":
            raise DriverError(f"BrowserDriver cannot execute action kind {action.kind!r}")

        op = str(action.params.get("op", ""))
        if op not in OPS:
            raise DriverError(f"unknown browser op {op!r}; expected one of {sorted(OPS)}")

        started = time.perf_counter()
        try:
            summary = self._perform(op, action.params)
        except DriverError:
            # A malformed action is an authoring bug in the knowledge base, not an
            # app that could not be tested. It must stay loud rather than becoming a
            # BLOCKED that quietly reads as "the app was unreachable".
            raise
        except Exception as exc:  # noqa: BLE001 -- playwright timeouts are broad
            return self._observe(
                ok=False,
                summary=f"{op} -> {type(exc).__name__}",
                op=op,
                params=action.params,
                started=started,
                error=self._explain(op, action.params, exc),
            )
        return self._observe(ok=True, summary=summary, op=op, params=action.params, started=started)

    def close(self) -> None:
        """The page's owner closes it. The driver never closes what it did not open."""

    # -- internals -----------------------------------------------------------

    def _perform(self, op: str, params: dict[str, object]) -> str:
        page = self._page
        if op == "goto":
            path = str(params["path"])
            page.goto(f"{self.base_url}{path}", timeout=self._timeout_ms)
            return f"goto {path} -> {page.url}"
        if op == "read":
            return f"read {page.url}"

        locator = self._locate(params)
        target = self._describe(params)
        if op == "click":
            locator.click(timeout=self._timeout_ms)
            return f"click {target}"
        if op == "fill":
            value = str(params["value"])
            locator.fill(value, timeout=self._timeout_ms)
            return f"fill {target} with {value!r}"
        if op == "select":
            value = str(params["value"])
            locator.select_option(value, timeout=self._timeout_ms)
            return f"select {value!r} in {target}"
        raise DriverError(f"unhandled op {op!r}")  # pragma: no cover -- guarded above

    def _locate(self, params: dict[str, object]) -> Locator:
        role = params.get("role")
        name = params.get("name")
        if not role:
            raise DriverError(
                "browser actions must target a role (and usually an accessible name); "
                "CSS and XPath are deliberately unsupported"
            )
        page = self._page
        if name:
            return page.get_by_role(str(role), name=str(name))
        return page.get_by_role(str(role))

    @staticmethod
    def _describe(params: dict[str, object]) -> str:
        role, name = params.get("role"), params.get("name")
        return f"{role} named {name!r}" if name else f"{role}"

    def _explain(self, op: str, params: dict[str, object], exc: Exception) -> str:
        """Turn a driver failure into something a developer can act on.

        A bare TimeoutError tells a reader nothing. Naming the control that could not
        be reached is the difference between "the bot broke" and "your button has no
        accessible name".
        """
        if op in {"click", "fill", "select"} and "Timeout" in type(exc).__name__:
            return (
                f"no accessible control matching {self._describe(params)} became "
                f"available within {self._timeout_ms:.0f}ms. Either it does not "
                f"exist, or it exists but has no accessible name -- which is itself "
                f"an accessibility defect worth fixing."
            )
        return f"{type(exc).__name__}: {exc}"

    def _observe(
        self,
        ok: bool,
        summary: str,
        op: str,
        params: dict[str, object],
        started: float,
        error: str | None = None,
    ) -> Observation:
        page = self._page
        elapsed_ms = (time.perf_counter() - started) * 1000
        evidence: dict[str, object] = {
            "op": op,
            "target": {k: v for k, v in params.items() if k in {"role", "name", "path", "value"}},
            "url": page.url,
            "elapsed_ms": elapsed_ms,
        }
        try:
            evidence["title"] = page.title()
            evidence["text"] = page.inner_text("body")[:TEXT_EVIDENCE_LIMIT]
            evidence["alerts"] = page.get_by_role("alert").all_inner_texts()
        except Exception as exc:  # noqa: BLE001 -- a dead page must not mask the result
            evidence["evidence_error"] = f"{type(exc).__name__}: {exc}"
        # Drained last, and unconditionally: the round trips above give the browser a
        # moment to deliver events the interaction only just triggered -- a fetch that
        # fails after the click returned is still that click's fault -- and a page too
        # dead to report its title is exactly the page whose errors matter most.
        evidence["browser_events"] = self._drain_events()
        if error:
            evidence["error"] = error
        shot = self._screenshot()
        if shot:
            evidence["screenshot"] = str(shot)
        return Observation(ok=ok, summary=summary, evidence=evidence)

    # -- error signals -------------------------------------------------------

    def _clear_events(self) -> None:
        """Start a fresh buffer.

        Called from `__init__` and from `reset()`, so one workflow never inherits the
        previous one's errors. Navigation deliberately does NOT clear: the events a
        page emits while loading are the most interesting ones it will ever emit, and
        they belong to the `goto` that caused them.
        """
        self._events: dict[str, list[dict[str, object]]] = {kind: [] for kind in EVENT_KINDS}
        self._event_counts: dict[str, int] = dict.fromkeys(EVENT_KINDS, 0)
        self._suppressed = 0
        self._capture_errors = 0

    def _guard(self, handler: Callable[[Any], None]) -> Callable[[Any], None]:
        """Wrap a listener so it can never take the step down with it.

        Playwright dispatches listeners inside whatever call happens to be in flight,
        so an exception raised while recording evidence would surface as a failure of
        the interaction it was meant to describe -- a BLOCKED caused by the observer.
        Same precedent as `_observe` and `_screenshot`. The failure is counted rather
        than swallowed, because a capture layer that quietly stops capturing is
        indistinguishable from a healthy app.
        """

        def listen(event: Any) -> None:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 -- evidence capture must never fail a step
                self._capture_errors += 1

        return listen

    def _on_page_error(self, error: Any) -> None:
        """An uncaught exception: exempt from the origin rule, and rightly so.

        There are never many of them, they routinely leave the page half-rendered, and
        the top stack frame is as likely to be a library the app called incorrectly as
        the culprit -- so filtering these by origin would discard real defects to
        remove noise that was not there.
        """
        text = str(getattr(error, "message", error))
        url, line = _stack_origin(str(getattr(error, "stack", "") or ""))
        self._record("page_errors", {"text": text, **_where(url, line)})

    def _on_console(self, message: ConsoleMessage) -> None:
        if message.type != "error":
            return
        location = message.location or {}
        url = str(location.get("url") or "")
        if self._is_noise(url):
            self._suppressed += 1
            return
        # Chromium numbers console locations from zero and stack frames from one. Left
        # alone, `line` would mean a different thing depending on which listener
        # produced it, and a line number quietly off by one sends a developer to read
        # code that is not the code -- worse than shipping no line number at all.
        line = location.get("lineNumber")
        line = line + 1 if isinstance(line, int) else None
        self._record("console_errors", {"text": message.text, **_where(url, line)})

    def _on_request_failed(self, request: Request) -> None:
        if self._is_noise(request.url):
            self._suppressed += 1
            return
        self._record(
            "failed_requests",
            {"url": request.url, "method": request.method, "failure": request.failure or "unknown"},
        )

    def _on_response(self, response: Response) -> None:
        if response.status < 500:
            return
        if self._is_noise(response.url):
            self._suppressed += 1
            return
        self._record(
            "server_errors",
            {"url": response.url, "method": response.request.method, "status": response.status},
        )

    def _note_origin(self) -> None:
        """Record the host actually serving the page as one of the app's own.

        The origin rule drops events from hosts the app's team cannot fix. A host the
        app itself redirected the browser to fails that description: it is the app,
        wearing its production name. Called from `_is_noise` -- at judgement time,
        not after the fact -- because a load-time event (a console.error the page's
        own inline script raises before `load` fires) is judged *while `goto` is
        still running*, long before an `_observe` gets a chance to look. `page.url` is
        already the post-redirect URL by then, so reading it here rather than caching
        it after the interaction is what makes the very first event from a redirected
        origin count as the app's own instead of being lost to the race.

        This also covers a client-side route change that swaps origin, for free.

        WHY not a `framenavigated` listener instead, keeping this predicate pure: that
        event fires for every frame, not just the top one, so an ad in an iframe
        navigating would add *its* host to the app's own set -- whitelisting exactly
        what the filter exists to remove. `page.url` is the main frame's URL by
        definition, so reading it here is immune to that for free.
        """
        try:
            host = urlsplit(self._page.url).hostname
        except Exception:  # noqa: BLE001 -- a dead page must not lose the event being judged
            return
        if host:
            self._hosts.add(host)

    def _is_noise(self, url: str) -> bool:
        """The whole filter, in one predictable pair of rules.

        An event with no host at all is KEPT: we cannot show it came from somewhere
        else, and suppressing on absent evidence is exactly the guess this filter
        exists to avoid.
        """
        self._note_origin()
        parts = urlsplit(url or "")
        if parts.path.rsplit("/", 1)[-1].startswith("favicon."):
            return True
        return bool(parts.hostname) and parts.hostname not in self._hosts

    def _record(self, kind: str, event: dict[str, object]) -> None:
        """Count first, store second.

        The cap bounds memory; the count makes sure it can never bound the truth.
        """
        self._event_counts[kind] += 1
        if len(self._events[kind]) < EVENT_EVIDENCE_LIMIT:
            self._events[kind].append(event)

    def _drain_events(self) -> dict[str, object]:
        """Hand over everything seen since the last observation, and start empty.

        The shape is fixed and always present -- empty lists and zeroes on a clean
        step -- so a consumer never has to distinguish "no errors" from "this driver
        does not report errors", which are opposite facts that must not look alike.
        """
        drained: dict[str, object] = dict(self._events)
        drained["suppressed"] = self._suppressed
        drained["truncated"] = {
            kind: self._event_counts[kind]
            for kind in EVENT_KINDS
            if self._event_counts[kind] > len(self._events[kind])
        }
        drained["capture_errors"] = self._capture_errors
        self._clear_events()
        return drained

    def _screenshot(self) -> Path | None:
        """A QA report without a picture of the failure is a report nobody trusts."""
        if not self._artifacts_dir:
            return None
        self._shot_counter += 1
        path = self._artifacts_dir / f"step_{self._shot_counter:03d}.png"
        try:
            self._page.screenshot(path=str(path))
        except Exception:  # noqa: BLE001 -- evidence capture must never fail a step
            return None
        return path


def _where(url: object, line: object) -> dict[str, object]:
    """Normalise a source position for an event record.

    Absent is None and never "" or 0, because a reader has to be able to tell "the
    first line of the file" from "nobody told us which line".
    """
    return {
        "url": str(url) if url else None,
        "line": int(line) if isinstance(line, int) else None,
    }


def _stack_origin(stack: str) -> tuple[str | None, int | None]:
    """Pull the first source location out of a stack trace, or admit there is none.

    Best effort by construction: stack formats are not a contract, and a missing
    location must degrade to "we do not know" rather than to a wrong file name, which
    would send someone to read code that never ran.
    """
    match = _STACK_FRAME.search(stack)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))
