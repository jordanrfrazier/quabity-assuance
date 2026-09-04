"""Render a scan into the one artifact its actual reader will open.

Every other module in `qabot.scan` produces data for the next stage of a pipeline;
this one produces data for a person. That person did not write the app by hand, does
not use pull requests, and will not open a terminal to read a stack trace -- so the
report is not a debug dump, it is the single self-contained file this project hands
back: one `<html>` string, styled inline, with nothing it depends on fetching over
the network. It gets emailed and dropped into folders, and a `<script src=...>` or a
screenshot referenced by a `/tmp/...` path would both be dead the moment it left this
machine.

The section this module exists to get right is not the findings list, it is the
frame around it. A scan that opened one page and found nothing wrong is not
evidence the app works, and a report that lets that scan wear the same "0 findings"
badge as a real one is the exact false green this whole project was built to refuse
-- see `NOTHING_CHECKED`. The mirror image of that lie is quietly dropping what an
anonymous scan could never see in the first place (anything behind a login, any form
we declined to submit); "What I could not check" always renders, for the same reason.
"""

from __future__ import annotations

import base64
import html
from pathlib import Path

from qabot.models import Finding
from qabot.scan.grading import IMPACT_ORDER, Impact, impact_of
from qabot.scan.sweep import PageResult, ScanResult

#: Shown whenever the run cannot support "no problems found" as a claim, because it
#: barely entered the app. Two independent triggers point at the same failure mode --
#: `len(pages) <= 1` catches a sweep that gave up almost immediately (budget, a 429,
#: a driver that could not proceed), `sum(discovery.counts.values()) <= 1` catches a
#: sweep that ran fully but was only ever given one path to visit -- and either one
#: alone is enough, because a reader cannot tell "we looked and it was fine" from "we
#: never really looked" unless this module tells them. The wording is exact: it says
#: what happened (almost nothing was reached) before it says what that does *not* mean
#: (a clean bill of health), because a reader skimming for the second half without the
#: first is exactly the reader this sentence is for.
NOTHING_CHECKED = (
    "This scan reached almost none of your app. That is not the same as finding "
    "nothing wrong -- most of your pages were never opened, so this report is not "
    "evidence that they work."
)

#: What an anonymous scan can never see, regardless of how thorough it otherwise was.
#: Stated once, always, independent of `result.limitations` -- those are what *this
#: particular run* additionally could not do; this is what *no* anonymous run could
#: ever do, so it cannot be conditioned on anything the run happened to observe.
ANONYMOUS_SCAN_CAVEAT = (
    "Pages behind a login were not reached, and any forms found on the site were not submitted."
)

_IMPACT_TITLE: dict[Impact, str] = {
    Impact.BROKEN: "Broken",
    Impact.GLITCHY: "Glitchy",
    Impact.NOTED: "Noted",
}

#: Prose for each group, written for the person who has to decide whether to worry.
_IMPACT_BLURB: dict[Impact, str] = {
    Impact.BROKEN: "A visitor could not use the page.",
    Impact.GLITCHY: "The page worked, but something on it misbehaved.",
    Impact.NOTED: "Worth a look, but nothing a visitor would have noticed.",
}


def _nothing_checked(result: ScanResult) -> bool:
    """Whether this run is too thin to let "no problems" read as good news.

    Two conditions, not one, because they catch different failures. A sweep can visit
    every path it was given and still have been given almost nothing (discovery found
    one route); or discovery can find plenty and the sweep still barely move (budget,
    a 429, an early crash). Either alone is disqualifying, so this is an `or`.
    """
    return len(result.pages) <= 1 or sum(result.discovery.counts.values()) <= 1


def headline(result: ScanResult) -> str:
    """One line, in plain language, for someone who will read nothing else.

    Counts distinct workflow names, not findings, in both the BROKEN and GLITCHY
    cases: two findings on the same page ("open /a") describe one broken or glitchy
    experience, not two, and a reader counting problems on their site does not think
    in oracle counts. The two cases get different sentences on purpose -- BROKEN and
    GLITCHY are the whole reason this package grades by visitor impact instead of
    reusing the CI product's severity axis, and a headline that calls a page with a
    console error "broken" collapses that distinction on the one line every reader is
    guaranteed to see. "Has/have problems" is deliberately milder than "is/are broken":
    a page that renders but logs an error or fails a background request is not the
    same claim as a page that could not be used at all.
    """
    broken_pages = {f.workflow_name for f in result.findings if impact_of(f) is Impact.BROKEN}
    if broken_pages:
        n = len(broken_pages)
        return f"{n} page is broken" if n == 1 else f"{n} pages are broken"
    glitchy_pages = {f.workflow_name for f in result.findings if impact_of(f) is Impact.GLITCHY}
    if glitchy_pages:
        n = len(glitchy_pages)
        return f"{n} page has problems" if n == 1 else f"{n} pages have problems"
    return "No problems found"


def _screenshot_data_uri(path: str | None) -> str | None:
    """A page's screenshot as something an emailed file can still show.

    `PageResult.screenshot` is wherever the driver happened to save it -- typically a
    temp directory on the machine that ran the scan, which will not exist by the time
    anyone opens this report. Inlining the bytes is the only way a screenshot survives
    being copied out of this process; a missing or unreadable file degrades to no
    image rather than a broken link, because a scan's own housekeeping (or a screenshot
    that failed to write at all) must never turn into an error in someone else's report.
    """
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    suffix = Path(path).suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _e(value: object) -> str:
    """Escape for HTML text content. Every interpolated value goes through this.

    Findings carry strings the target application produced -- a statement, a detail
    line, a title -- and none of it is ours to trust. An app whose error page HTML
    happens to be echoed into a detail field must not be able to inject markup into
    a report we then hand to someone else to open.
    """
    return html.escape(str(value), quote=True)


def _findings_section(findings: list[Finding]) -> str:
    if not findings:
        return '<p class="ok">No problems found.</p>'
    grouped: dict[Impact, list[Finding]] = {impact: [] for impact in IMPACT_ORDER}
    for finding in findings:
        grouped[impact_of(finding)].append(finding)
    parts: list[str] = []
    for impact in IMPACT_ORDER:
        group = grouped[impact]
        if not group:
            continue
        title = _IMPACT_TITLE[impact]
        parts.append(f'<section class="impact impact-{impact.value}">')
        parts.append(f"<h2>{_e(title)} ({len(group)})</h2>")
        parts.append(f'<p class="blurb">{_e(_IMPACT_BLURB[impact])}</p>')
        parts.append("<ul>")
        for finding in group:
            parts.append(
                "<li><strong>{name}</strong>: {statement}{detail}</li>".format(
                    name=_e(finding.workflow_name),
                    statement=_e(finding.statement),
                    detail=f"<br><code>{_e(finding.detail)}</code>" if finding.detail else "",
                )
            )
        parts.append("</ul></section>")
    return "\n".join(parts)


def _pages_section(pages: list[PageResult]) -> str:
    if not pages:
        return ""
    rows: list[str] = []
    for page in pages:
        image = _screenshot_data_uri(page.screenshot)
        thumb = f'<img src="{image}" alt="{_e(page.path)}">' if image else ""
        status = _e(page.status) if page.status is not None else "?"
        title = _e(page.title) if page.title else ""
        rows.append(
            f"<li>{thumb}<div><code>{_e(page.path)}</code> "
            f"&mdash; status {status} {title}</div></li>"
        )
    return (
        '<section><h2>Pages visited ({count})</h2><ul class="pages">{rows}</ul></section>'
    ).format(count=len(pages), rows="\n".join(rows))


def _not_checked_section(result: ScanResult) -> str:
    """Always rendered. This is not an apology, it is the scope of the claim above it.

    Four sources, none optional: `limitations` (what this run's driver could not do),
    `not_visited` (what the budget or a stop condition cut short), `stopped` (why the
    sweep ended early, when it did), and `ANONYMOUS_SCAN_CAVEAT` (what no anonymous
    scan -- however thorough -- can ever see). Dropping any one of them because it
    happened to be empty this run is how a report quietly narrows its own honesty.
    """
    items: list[str] = []
    for limitation in result.limitations:
        items.append(f"<li>{_e(limitation)}</li>")
    if result.not_visited:
        paths = ", ".join(_e(p) for p in result.not_visited)
        items.append(f"<li>Not visited: {paths}</li>")
    if result.stopped:
        items.append(f"<li>Stopped early: {_e(result.stopped)}</li>")
    items.append(f"<li>{_e(ANONYMOUS_SCAN_CAVEAT)}</li>")
    return (
        '<section class="not-checked"><h2>What I could not check</h2>'
        f"<ul>{''.join(items)}</ul></section>"
    )


#: Inline, because an external stylesheet is the same broken-when-forwarded problem
#: as an external script -- see the module docstring.
_STYLE = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 760px;
       margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 1.6rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; }
.headline { font-size: 1.3rem; font-weight: 600; }
.warning { background: #fff3cd; border: 1px solid #e0a800; border-radius: 6px;
           padding: 0.75rem 1rem; margin: 1rem 0; }
.ok { color: #1a7f37; font-weight: 600; }
.blurb { color: #555; margin-top: -0.5rem; }
.impact-broken h2 { color: #b42318; }
.impact-glitchy h2 { color: #b54708; }
.impact-noted h2 { color: #444; }
.not-checked { background: #f6f8fa; border-radius: 6px; padding: 0.5rem 1rem 1rem; }
.pages img { max-width: 160px; display: block; margin: 0.25rem 0; border: 1px solid #ddd; }
ul { padding-left: 1.25rem; }
code { background: #f0f0f0; padding: 0 0.25rem; border-radius: 3px; }
"""


def render_html(result: ScanResult) -> str:
    """One self-contained HTML string: the report, and nothing it depends on fetching.

    Structure top to bottom mirrors how much a reader can trust each claim: the
    headline first, immediately qualified by `NOTHING_CHECKED` when the run cannot
    back it up, then the findings that back the rest of the headline, then -- always,
    never conditionally -- the boundary of what any of this could have found.
    """
    thin = _nothing_checked(result)
    parts: list[str] = [
        '<!doctype html><html><head><meta charset="utf-8">',
        f"<title>QA scan of {_e(result.origin)}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>Scan of {_e(result.origin)}</h1>",
        f'<p class="headline">{_e(headline(result))}</p>',
    ]
    if thin:
        parts.append(f'<p class="warning">{_e(NOTHING_CHECKED)}</p>')
    parts.append(_findings_section(result.findings))
    parts.append(_pages_section(result.pages))
    parts.append(_not_checked_section(result))
    parts.append("</body></html>")
    return "\n".join(p for p in parts if p)
