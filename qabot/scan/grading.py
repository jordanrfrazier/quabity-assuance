"""How loudly to say a finding, for a reader who cannot read a stack trace.

`intrinsics.py` orders findings by *how much we may claim* -- BUG for what the
application declared about itself, QUESTION for what we merely noticed. That ordering
is epistemic, it is correct, and it is the wrong one to show a builder. Measured
against seven real applications, the single most useful thing found was a console
error, which that ordering files under "noticed, not called".

So this module keeps the oracles and replaces the axis. The question here is not how
sure we are, it is what a visitor experiences: can they use this page, or not.

Two properties are load-bearing and must survive any later edit. The mapping is a
lookup on `finding.oracle`, never a match on prose -- a severity that moves when
somebody rewords a sentence is not a measurement. And it is a pure function *over*
findings rather than a field *on* them, so `intrinsics.py` is untouched, the CI
product keeps its own ordering, and this can be re-cut later without migrating data.
"""

from __future__ import annotations

from enum import StrEnum

from qabot.drivers.base import Observation
from qabot.models import Finding


class Impact(StrEnum):
    """What a visitor experiences. Ordered most severe first."""

    BROKEN = "broken"
    GLITCHY = "glitchy"
    NOTED = "noted"


#: Presentation order, so the report and any measurement agree without re-deriving it.
IMPACT_ORDER: tuple[Impact, ...] = (Impact.BROKEN, Impact.GLITCHY, Impact.NOTED)

#: Below this many characters of body text, a page that also threw has rendered
#: nothing a visitor could use. Generous on purpose: the oracle only fires in
#: conjunction with a crash, so the threshold decides sensitivity, not correctness.
BLANK_PAGE_TEXT_LIMIT = 120

#: oracle name -> what it means for somebody trying to use the page.
_IMPACT: dict[str, Impact] = {
    "server_error": Impact.BROKEN,
    "server_traceback": Impact.BROKEN,
    "browser_server_error": Impact.BROKEN,
    "blank_page": Impact.BROKEN,
    "browser_page_error": Impact.GLITCHY,
    "browser_console_error": Impact.GLITCHY,
    "browser_failed_request": Impact.GLITCHY,
}


def impact_of(finding: Finding) -> Impact:
    """The visitor impact of a finding, from the oracle that produced it.

    An oracle this table has not heard of is NOTED, never BROKEN. A new signal
    inheriting the loudest tier by default is how a precision claim quietly stops
    being true; under-claiming is visible and recoverable.
    """
    if finding.oracle is None:
        return Impact.NOTED
    return _IMPACT.get(finding.oracle, Impact.NOTED)


def blank_page(observation: Observation, status: int | None) -> str | None:
    """The page loaded, threw, and rendered nothing. Detail line, or None.

    The only oracle here that reads a *combination* of signals, which is why it lives
    in the scan package rather than in `intrinsics.py`. Each conjunct is mechanical --
    a 2xx status, at least one uncaught exception, less than `BLANK_PAGE_TEXT_LIMIT`
    characters of body text after the page settled -- and the conjunction is close to
    unarguable: a page that returned OK, crashed, and drew nothing is broken by any
    definition a builder would accept.

    It requires the 2xx deliberately. A 500 is already reported by `server_error`, and
    a blank 500 page is one defect, not two.
    """
    if status is None or not 200 <= status < 300:
        return None
    events = observation.evidence.get("browser_events") or {}
    if not events.get("page_errors"):
        return None
    text = str(observation.evidence.get("text") or "")
    if len(text.strip()) >= BLANK_PAGE_TEXT_LIMIT:
        return None
    return (
        f"the page returned {status} but rendered blank "
        f"({len(text.strip())} characters of text) after raising an uncaught error"
    )
