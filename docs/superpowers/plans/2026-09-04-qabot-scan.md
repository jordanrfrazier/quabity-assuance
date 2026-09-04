# qabot scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `qabot scan <url>`, which checks a web application we were given nothing but the URL of and writes a self-contained HTML report a non-engineer can act on.

**Architecture:** A new `qabot/scan/` package reuses the two modules the CI evaluation vindicated — `BrowserDriver` for capture and `intrinsics.py` for oracles — and adds four pure units around them (discovery, grading, source maps, report) plus one impure one (sweep). Two latent bugs in `BrowserDriver` are fixed first because the scan cannot work around them. `intrinsics.py` and every knowledge-base module are left untouched.

**Tech Stack:** Python 3.11+, Playwright (Chromium), httpx, pydantic, pytest, ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-scan-design.md`

## Global Constraints

- `from __future__ import annotations` at the top of every new module.
- Docstrings argue **why** a decision was made and state its tradeoff. Calibrate on `qabot/drivers/browser.py` and `qabot/intrinsics.py` before writing.
- Ruff: line length 100. Run `uv run ruff check` and `uv run ruff format` on **only** the files touched by the task.
- Python: `uv run python` / `uv run pytest`. Never bare `python`/`pytest`.
- Full suite must pass at the end of every task. Baseline at plan time: **455 passed, 1 skipped**. Record before/after counts in each commit message body.
- **Do NOT modify** `qabot/intrinsics.py`, `qabot/seeder.py`, `qabot/impact.py`, `qabot/anchors.py`, `qabot/verifier.py`, `qabot/planner.py`, `qabot/routemap.py`, `qabot/testgen.py`, `qabot/reporter.py`, or `qabot/llm.py`.
- Browser-dependent tests carry `pytestmark = pytest.mark.browser` (existing marker, already registered).
- No new third-party dependencies. Source-map decoding is hand-rolled against the stdlib.
- Never emit a report that reads as a clean bill of health when little or nothing was checked. This is the project's founding rule and Task 8 pins it.

---

## File Structure

| File | Responsibility |
|---|---|
| `qabot/drivers/browser.py` (modify) | Effective-origin tracking; optional reset |
| `qabot/scan/__init__.py` (create) | Package marker |
| `qabot/scan/discovery.py` (create) | Root URL → candidate paths, with per-source counts |
| `qabot/scan/grading.py` (create) | Finding → visitor-impact severity; the `blank_page` oracle |
| `qabot/scan/sourcemaps.py` (create) | Minified frame → original file/line/name, or an honest failure |
| `qabot/scan/sweep.py` (create) | Drive one app under budget; safe interactions; collect observations |
| `qabot/scan/report.py` (create) | Scan result → one self-contained HTML file |
| `qabot/scan/cli.py` (create) | `qabot scan` subcommand |
| `qabot/cli.py` (modify) | Register the `scan` subcommand |
| `tests/test_scan_discovery.py` … `tests/test_scan_cli.py` (create) | One test module per unit |

---

## Task 1: BrowserDriver follows redirects when deciding what is third-party

**Files:**
- Modify: `qabot/drivers/browser.py` (`__init__`, `_is_noise`, and a new `_note_origin`)
- Test: `tests/test_browser_driver.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `BrowserDriver` suppresses an event only when its host is neither the configured host nor any host the app has redirected the browser to during this run.

**Why:** `_is_noise` compares each event's host against the host parsed from `base_url` at construction. Measured on a real app, `snake-survival.lovable.app` redirects to `www.snakesurvival.com`, so every console error, failed request and 5xx it produced was suppressed as third-party; only its uncaught exception survived, because `page_errors` are exempt. A scan whose entire input is a stranger's vanity domain would report silence.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_browser_driver.py`:

```python
def test_events_from_a_host_the_app_redirected_us_to_are_not_third_party(
    page: Page, two_host_app: tuple[str, str]
) -> None:
    """The origin rule exists to drop other people's scripts, not the app's own
    second domain. An app served from a vanity host it redirects to is still the app."""
    start_url, _ = two_host_app
    driver = BrowserDriver(base_url=start_url, page=page, reset_path=None)

    observation = driver.execute(
        Action(kind="browser", params={"op": "goto", "path": "/redirects-away"})
    )

    events = observation.evidence["browser_events"]
    assert [e["text"] for e in events["console_errors"]] == ["error from the vanity host"]
    assert events["suppressed"] == 0
```

And the fixture that serves two hosts, placed beside the existing fixtures in that file:

```python
@pytest.fixture(scope="module")
def two_host_app() -> Iterator[tuple[str, str]]:
    """Two ports, so 127.0.0.1:A can redirect to 127.0.0.1:B.

    Two ports rather than two names because a redirect between ports exercises the
    same code path -- the host recorded on the event differs from the configured one --
    without needing DNS or an /etc/hosts entry a test has no business writing.
    """
    second = FastAPI()

    @second.get("/landed")
    def landed() -> HTMLResponse:
        return HTMLResponse(
            "<html><body>landed"
            "<script>console.error('error from the vanity host')</script>"
            "</body></html>"
        )

    with serve(second) as second_url:
        first = FastAPI()

        @first.get("/redirects-away")
        def redirects_away() -> Response:
            return Response(status_code=307, headers={"Location": f"{second_url}/landed"})

        with serve(first) as first_url:
            yield first_url, second_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_browser_driver.py::test_events_from_a_host_the_app_redirected_us_to_are_not_third_party -v`
Expected: FAIL — `console_errors` is empty and `suppressed` is 1, because the event's host is the second port and `self._host` is the first.

- [ ] **Step 3: Write minimal implementation**

In `qabot/drivers/browser.py`, replace the single `self._host` with a set that grows as the app redirects. In `__init__`, after `self._host = urlsplit(self.base_url).hostname`:

```python
        #: Every host this app has served us from. The configured one seeds it; a
        #: redirect adds to it. See `_note_origin` for why this is a set and not a
        #: constant.
        self._hosts: set[str] = {self._host} if self._host else set()
```

Add the method:

```python
    def _note_origin(self) -> None:
        """Record the host actually serving the page as one of the app's own.

        The origin rule drops events from hosts the app's team cannot fix. A host the
        app itself redirected the browser to fails that description: it is the app,
        wearing its production name. Reading the host after every interaction rather
        than only after `goto` costs nothing and covers a client-side route change that
        swaps origin.
        """
        host = urlsplit(self._page.url).hostname
        if host:
            self._hosts.add(host)
```

Call it at the top of `_observe`, before evidence is assembled:

```python
        self._note_origin()
```

And widen the comparison in `_is_noise`:

```python
        return bool(parts.hostname) and parts.hostname not in self._hosts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_browser_driver.py -v -m browser`
Expected: PASS, including every pre-existing browser test — the single-host case is unchanged because the set holds exactly the configured host.

Then: `uv run pytest` — expect 456 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/drivers/browser.py tests/test_browser_driver.py
uv run ruff format qabot/drivers/browser.py tests/test_browser_driver.py
git add qabot/drivers/browser.py tests/test_browser_driver.py
git commit -m "fix(browser): treat hosts the app redirected to as the app, not third-party"
```

---

## Task 2: BrowserDriver can be told the app has no reset endpoint

**Files:**
- Modify: `qabot/drivers/browser.py` (`__init__` signature, `reset`)
- Test: `tests/test_browser_driver.py`

**Interfaces:**
- Consumes: Task 1's driver.
- Produces: `BrowserDriver(base_url, page, reset_path=None)` — `reset()` clears cookies and returns without issuing any request; `driver.limitations` is a `list[str]` carrying `NO_RESET_LIMITATION` when reset was declined.

**Why:** `reset_path` is a plain `str` defaulting to `/reset`, so `reset()` would POST to a stranger's application. `HttpDriver` already takes `str | None` for this reason. Matching it keeps one story about opting out across both drivers, and the limitation is stated rather than swallowed.

- [ ] **Step 1: Write the failing test**

```python
def test_reset_without_a_reset_path_issues_no_request_and_states_the_limitation(
    page: Page, app_url: str
) -> None:
    """A scan drives applications we do not own. Opting out is the caller's decision,
    made once and in the open, and it costs them a stated limitation on the run."""
    driver = BrowserDriver(base_url=app_url, page=page, reset_path=None)

    driver.reset()  # must not raise, and must not POST anywhere

    assert NO_RESET_LIMITATION in driver.limitations
```

Extend the import at the top of the test module:

```python
from qabot.drivers.browser import (
    EVENT_EVIDENCE_LIMIT,
    EVENT_KINDS,
    NO_RESET_LIMITATION,
    BrowserDriver,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_browser_driver.py::test_reset_without_a_reset_path_issues_no_request_and_states_the_limitation -v`
Expected: FAIL — `ImportError: cannot import name 'NO_RESET_LIMITATION'`.

- [ ] **Step 3: Write minimal implementation**

In `qabot/drivers/browser.py`, near the other module constants:

```python
#: Carried on the run when the caller declared the app has no reset endpoint.
NO_RESET_LIMITATION = (
    "the app has no reset endpoint, so pages were visited in sequence against whatever "
    "state earlier ones left behind: a finding here may depend on that accumulated "
    "state, and visiting the same pages in another order may not reproduce it"
)
```

Change the signature `reset_path: str = "/reset"` to `reset_path: str | None = "/reset"`, and in `__init__` after `self._reset_path = reset_path`:

```python
        #: What this driver could not guarantee about the run. The caller reads it and
        #: the report prints it; opting out of reset is stated, never swallowed.
        self.limitations: list[str] = [] if reset_path is not None else [NO_RESET_LIMITATION]
```

Guard `reset`, keeping the cookie clear (which is local to us and always safe):

```python
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
        ...  # existing body unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_browser_driver.py -v -m browser`
Expected: PASS. Then `uv run pytest` — expect 457 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/drivers/browser.py tests/test_browser_driver.py
uv run ruff format qabot/drivers/browser.py tests/test_browser_driver.py
git add qabot/drivers/browser.py tests/test_browser_driver.py
git commit -m "feat(browser): allow reset to be declined, and state it as a run limitation"
```

---

## Task 3: Discovery — what the app says about its own routes

**Files:**
- Create: `qabot/scan/__init__.py` (empty), `qabot/scan/discovery.py`
- Test: `tests/test_scan_discovery.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class Discovery(BaseModel)` with fields `origin: str`, `paths: list[str]`, `counts: dict[str, int]`, `disallowed: list[str]`
  - `def followable(origin: str, href: str) -> str | None`
  - `def routes_from_bundle(text: str, origin: str) -> set[str]`
  - `def routes_from_sitemap(xml: str, origin: str) -> set[str]`
  - `def parse_robots(text: str) -> tuple[list[str], list[str]]` → `(disallowed_prefixes, sitemap_urls)`
  - `def discover(origin: str, fetch: Fetch, max_bundles: int = 6) -> Discovery` where `Fetch = Callable[[str], str | None]`

**Why:** The spike measured discovery as bimodal — 1 to 32 routes across seven apps — and the findings tracked it exactly. An app we never entered must not be reported as an app we found nothing wrong with. `counts` is what lets the report tell those apart.

`discover` takes a `fetch` callable rather than doing its own HTTP so that every rule in this module is testable without a network.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scan_discovery.py`:

```python
"""Discovery decides whether a scan sees an app or only its front door."""

from __future__ import annotations

from qabot.scan.discovery import (
    Discovery,
    discover,
    followable,
    parse_robots,
    routes_from_bundle,
    routes_from_sitemap,
)

ORIGIN = "https://example.test"


def test_route_literals_are_recovered_from_a_minified_bundle() -> None:
    """Real bundle shape: React Router config survives minification as `path:"/x"`."""
    bundle = 'a({path:"/",element:x}),a({path:"/pricing",element:y}),c({to:"/about"})'
    assert routes_from_bundle(bundle, ORIGIN) == {"/", "/pricing", "/about"}


def test_route_patterns_are_not_pages() -> None:
    """`/post/:id` is a template. Visiting it literally requests a page named ':id'."""
    bundle = 'a({path:"/post/:id"}),a({path:"/docs/*"}),a({path:"/ok"})'
    assert routes_from_bundle(bundle, ORIGIN) == {"/ok"}


def test_sitemap_locations_are_reduced_to_paths() -> None:
    xml = (
        "<urlset><url><loc>https://example.test/a</loc></url>"
        "<url><loc>https://example.test/b?x=1</loc></url>"
        "<url><loc>https://elsewhere.test/c</loc></url></urlset>"
    )
    assert routes_from_sitemap(xml, ORIGIN) == {"/a", "/b?x=1"}


def test_robots_yields_disallowed_prefixes_and_sitemaps() -> None:
    text = "User-agent: *\nDisallow: /admin\nDisallow:\nSitemap: https://example.test/sitemap.xml\n"
    disallowed, sitemaps = parse_robots(text)
    assert disallowed == ["/admin"]
    assert sitemaps == ["https://example.test/sitemap.xml"]


def test_paths_that_look_destructive_are_never_followed() -> None:
    """We drive applications we do not own. A link named /logout is not curiosity."""
    for href in ("/logout", "/account/delete", "/cancel-subscription", "/checkout"):
        assert followable(ORIGIN, href) is None


def test_offsite_and_asset_links_are_not_followed() -> None:
    assert followable(ORIGIN, "https://other.test/x") is None
    assert followable(ORIGIN, "/bundle.js") is None
    assert followable(ORIGIN, "mailto:a@b.test") is None
    assert followable(ORIGIN, "/pricing#plans") == "/pricing"


def test_discover_records_where_every_path_came_from() -> None:
    """The counts are the report's evidence that the scan saw the app, not its lobby."""
    pages = {
        f"{ORIGIN}/": '<script src="/a.js"></script>',
        f"{ORIGIN}/a.js": 'r({path:"/dash"})',
        f"{ORIGIN}/robots.txt": "Sitemap: https://example.test/sitemap.xml\nDisallow: /admin\n",
        f"{ORIGIN}/sitemap.xml": "<urlset><url><loc>https://example.test/pricing</loc></url></urlset>",
    }
    found = discover(ORIGIN, lambda url: pages.get(url))

    assert isinstance(found, Discovery)
    assert set(found.paths) == {"/", "/dash", "/pricing"}
    assert found.counts == {"bundle": 1, "sitemap": 1, "root": 1}
    assert found.disallowed == ["/admin"]


def test_discover_honours_robots_disallow() -> None:
    pages = {
        f"{ORIGIN}/": "",
        f"{ORIGIN}/robots.txt": "Disallow: /admin\n",
        f"{ORIGIN}/sitemap.xml": (
            "<urlset><url><loc>https://example.test/admin/secrets</loc></url>"
            "<url><loc>https://example.test/ok</loc></url></urlset>"
        ),
    }
    found = discover(ORIGIN, lambda url: pages.get(url))
    assert "/admin/secrets" not in found.paths
    assert "/ok" in found.paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qabot.scan'`.

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/__init__.py` as an empty file. Create `qabot/scan/discovery.py`:

```python
"""What the application says about its own routes.

`routemap.py` reads a server's route table by importing the application. A scan never
gets to do that -- we have a URL and nothing else -- so this module applies the same
principle from outside: ask the app what it serves rather than inferring it.

An SPA ships its router to the browser, so the route table is sitting in the bundle in
plain text. That is the highest-trust source available to a stranger, and measurably
the one that matters: across seven real applications, discovery found between 1 and 32
routes, and the number of defects found tracked it exactly. Crawling `a[href]` alone
finds one page on a React landing page, which is why it cannot be the only source.

The per-source counts are not telemetry. A scan that reached one page and reported no
problems is not a clean bill of health, and `counts` is how the report tells a reader
which of the two they are holding.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urljoin, urldefrag, urlsplit

from pydantic import BaseModel, Field

#: Fetch a URL and return its body, or None when it could not be read. Injected so
#: every rule in this module is testable without a network.
Fetch = Callable[[str], "str | None"]

#: Router declarations as they survive minification, plus `<Link to=>` targets.
_ROUTE_RE = re.compile(r'(?:\bpath|\bto)\s*:\s*"(/[^"]*)"')
_SCRIPT_RE = re.compile(r'<(?:script[^>]+src|link[^>]+rel="modulepreload"[^>]+href)="([^"]+\.js)"')
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_ASSET_RE = re.compile(r"\.(?:js|css|png|jpe?g|svg|gif|ico|woff2?|ttf|map|json|xml|txt|pdf)$", re.I)

#: A path naming one of these is a state change, not a page. We drive applications we
#: do not own, so the list is deliberately broad and deliberately dumb: a false
#: exclusion costs one unvisited page, a false inclusion costs somebody their data.
UNSAFE_WORDS = (
    "logout", "signout", "sign-out", "delete", "remove", "destroy",
    "unsubscribe", "cancel", "checkout", "purchase", "billing",
)


class Discovery(BaseModel):
    """Paths to visit, and the evidence for how well we found them."""

    origin: str
    paths: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    disallowed: list[str] = Field(default_factory=list)


def followable(origin: str, href: str) -> str | None:
    """The same-origin path this link names, or None when we must not visit it."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
        return None
    absolute, _ = urldefrag(urljoin(origin + "/", href))
    o, u = urlsplit(origin), urlsplit(absolute)
    if (u.scheme, u.netloc) != (o.scheme, o.netloc):
        return None
    path = u.path or "/"
    if ":" in path or "*" in path:  # a route pattern is a template, not a page
        return None
    if _ASSET_RE.search(path):
        return None
    if any(word in path.lower() for word in UNSAFE_WORDS):
        return None
    return path + (f"?{u.query}" if u.query else "")


def routes_from_bundle(text: str, origin: str) -> set[str]:
    """Route literals declared by a JavaScript bundle's router configuration."""
    return {p for raw in _ROUTE_RE.findall(text) if (p := followable(origin, raw))}


def routes_from_sitemap(xml: str, origin: str) -> set[str]:
    return {p for loc in _LOC_RE.findall(xml) if (p := followable(origin, loc))}


def parse_robots(text: str) -> tuple[list[str], list[str]]:
    """`(disallowed prefixes, sitemap urls)`.

    Deliberately not a full robots parser: we honour every `Disallow` we see whatever
    user-agent block it sits in. Over-honouring costs a page; under-honouring means
    fetching something a stranger asked us not to.
    """
    disallowed, sitemaps = [], []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if not value:
            continue
        if key.strip().lower() == "disallow":
            disallowed.append(value)
        elif key.strip().lower() == "sitemap":
            sitemaps.append(value)
    return disallowed, sitemaps


def discover(origin: str, fetch: Fetch, max_bundles: int = 6) -> Discovery:
    """Everything the app tells us about itself, with the provenance of each path."""
    origin = origin.rstrip("/")
    counts = {"bundle": 0, "sitemap": 0, "root": 0}
    paths: set[str] = set()

    root = fetch(f"{origin}/")
    if root is not None:
        paths.add("/")
        counts["root"] = 1

    robots = fetch(f"{origin}/robots.txt") or ""
    disallowed, sitemaps = parse_robots(robots)

    for src in _SCRIPT_RE.findall(root or "")[:max_bundles]:
        body = fetch(urljoin(f"{origin}/", src))
        if body is None:
            continue
        for path in routes_from_bundle(body, origin):
            if path not in paths:
                paths.add(path)
                counts["bundle"] += 1

    for sitemap_url in [*sitemaps, f"{origin}/sitemap.xml"]:
        body = fetch(sitemap_url)
        if body is None:
            continue
        for path in routes_from_sitemap(body, origin):
            if path not in paths:
                paths.add(path)
                counts["sitemap"] += 1
        break

    kept = [p for p in sorted(paths) if not any(p.startswith(d) for d in disallowed)]
    return Discovery(origin=origin, paths=kept, counts=counts, disallowed=disallowed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_discovery.py -v`
Expected: PASS (8 tests). Then `uv run pytest` — expect 465 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/scan/ tests/test_scan_discovery.py
uv run ruff format qabot/scan/ tests/test_scan_discovery.py
git add qabot/scan/__init__.py qabot/scan/discovery.py tests/test_scan_discovery.py
git commit -m "feat(scan): discover routes from the app's own bundle, sitemap and robots"
```

---

## Task 4: Grading — visitor impact, and the blank-page oracle

**Files:**
- Create: `qabot/scan/grading.py`
- Test: `tests/test_scan_grading.py`

**Interfaces:**
- Consumes: `qabot.models.Finding`, `qabot.models.Observation`, `qabot.intrinsics` (read-only).
- Produces:
  - `class Impact(StrEnum)` with `BROKEN`, `GLITCHY`, `NOTED`
  - `def impact_of(finding: Finding) -> Impact`
  - `def blank_page(observation: Observation, status: int | None) -> str | None`
  - `IMPACT_ORDER: tuple[Impact, ...]`
  - `BLANK_PAGE_TEXT_LIMIT: int`

**Why:** The CI severities order findings by how much we may *claim*, given where an expectation came from. That is the right axis for a merge gate and the wrong one here. The spike settled it: the most useful thing found across seven apps was a console error, which the CI map files under QUESTION — "noticed, not called". This module re-cuts the axis to visitor impact without touching `intrinsics.py`, by deriving severity from `finding.oracle` at report time and never storing it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scan_grading.py`:

```python
"""Visitor impact, derived from the oracle that produced a finding."""

from __future__ import annotations

import pytest

from qabot.drivers.base import Observation
from qabot.models import Finding, Outcome, Severity
from qabot.scan.grading import (
    BLANK_PAGE_TEXT_LIMIT,
    Impact,
    blank_page,
    impact_of,
)


def _finding(oracle: str, severity: Severity = Severity.BUG) -> Finding:
    return Finding(
        workflow_id="scan", workflow_name="scan", severity=severity,
        outcome=Outcome.FAIL, statement="x", oracle=oracle,
    )


@pytest.mark.parametrize(
    ("oracle", "expected"),
    [
        ("server_error", Impact.BROKEN),
        ("browser_server_error", Impact.BROKEN),
        ("blank_page", Impact.BROKEN),
        ("browser_page_error", Impact.GLITCHY),
        ("browser_console_error", Impact.GLITCHY),
        ("browser_failed_request", Impact.GLITCHY),
        ("server_traceback", Impact.BROKEN),
    ],
)
def test_each_oracle_maps_to_a_visitor_impact(oracle: str, expected: Impact) -> None:
    assert impact_of(_finding(oracle)) == expected


def test_an_unknown_oracle_is_noted_rather_than_guessed_upward() -> None:
    """A new oracle must not silently inherit BROKEN. Under-claiming is recoverable."""
    assert impact_of(_finding("some_oracle_added_later")) == Impact.NOTED


def test_a_finding_with_no_oracle_is_noted() -> None:
    assert impact_of(_finding("x").model_copy(update={"oracle": None})) == Impact.NOTED


def _observation(text: str, page_errors: int) -> Observation:
    return Observation(
        ok=True, summary="goto /",
        evidence={
            "text": text,
            "browser_events": {
                "page_errors": [{"text": "boom", "url": None, "line": None}] * page_errors,
                "console_errors": [], "failed_requests": [], "server_errors": [],
                "suppressed": 0, "truncated": {}, "capture_errors": 0,
            },
        },
    )


def test_blank_page_fires_on_the_full_conjunction() -> None:
    """OK, crashed, and rendered nothing: broken by any definition."""
    detail = blank_page(_observation("", page_errors=1), status=200)
    assert detail is not None
    assert "blank" in detail.lower()


def test_blank_page_does_not_fire_when_the_page_rendered() -> None:
    assert blank_page(_observation("x" * 400, page_errors=1), status=200) is None


def test_blank_page_does_not_fire_without_a_crash() -> None:
    """An empty page that did not throw may simply be an empty page."""
    assert blank_page(_observation("", page_errors=0), status=200) is None


def test_blank_page_does_not_fire_on_a_non_2xx_document() -> None:
    """A 500 is already reported as broken; blank_page must not double-count it."""
    assert blank_page(_observation("", page_errors=1), status=500) is None


def test_blank_page_threshold_is_a_named_constant() -> None:
    assert blank_page(_observation("x" * (BLANK_PAGE_TEXT_LIMIT - 1), 1), 200) is not None
    assert blank_page(_observation("x" * (BLANK_PAGE_TEXT_LIMIT + 1), 1), 200) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan_grading.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qabot.scan.grading'`.

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/grading.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_grading.py -v`
Expected: PASS (12 tests). Then `uv run pytest` — expect 477 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/scan/grading.py tests/test_scan_grading.py
uv run ruff format qabot/scan/grading.py tests/test_scan_grading.py
git add qabot/scan/grading.py tests/test_scan_grading.py
git commit -m "feat(scan): grade findings by visitor impact, and add the blank-page oracle"
```

---

## Task 5: Source maps — turning `Wl` back into a name

**Files:**
- Create: `qabot/scan/sourcemaps.py`
- Test: `tests/test_scan_sourcemaps.py`

**Interfaces:**
- Consumes: `Fetch` from `qabot.scan.discovery`.
- Produces:
  - `class Frame(BaseModel)` with `file: str | None`, `line: int | None`, `name: str | None`, `resolved: bool`
  - `def decode_vlq(segment: str) -> list[int]`
  - `def resolve(url: str | None, line: int | None, column: int | None, fetch: Fetch) -> Frame`

**Why:** The spike found the severity ceiling inverted — the top-severity finding across seven apps arrived as the message `"Wl"`, a mangled symbol, while lower-severity console errors carried real stacks. Where an app ships `.map` files, resolving a frame is the difference between a finding a builder can act on and noise. Unresolved must be *stated*, never presented as resolved.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scan_sourcemaps.py`:

```python
"""Minified frames back to original names, or an honest admission."""

from __future__ import annotations

import json

from qabot.scan.sourcemaps import Frame, decode_vlq, resolve


def test_decode_vlq_handles_sign_and_continuation() -> None:
    """Base64 VLQ: 'A' is 0, 'C' is 1, 'D' is -1, 'gB' is 16."""
    assert decode_vlq("A") == [0]
    assert decode_vlq("C") == [1]
    assert decode_vlq("D") == [-1]
    assert decode_vlq("gB") == [16]
    assert decode_vlq("AACA") == [0, 0, 1, 0]


def _map_for(sources: list[str], names: list[str], mappings: str) -> str:
    return json.dumps(
        {"version": 3, "sources": sources, "names": names, "mappings": mappings}
    )


def test_a_frame_resolves_to_its_original_file_line_and_name() -> None:
    """One segment on generated line 1: source 0, original line 10, name 0."""
    sourcemap = _map_for(["src/cart.ts"], ["computeTotal"], "AAUAA")
    fetch = {"https://app.test/b.js.map": sourcemap}.get

    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=fetch)

    assert frame.resolved is True
    assert frame.file == "src/cart.ts"
    assert frame.line == 11  # 0-based in the map, 1-based for a human
    assert frame.name == "computeTotal"


def test_a_missing_map_degrades_to_an_unresolved_frame() -> None:
    """Never present a minified frame as if it were original."""
    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=lambda _: None)
    assert frame.resolved is False
    assert frame.file == "https://app.test/b.js"
    assert frame.line == 1
    assert frame.name is None


def test_a_malformed_map_degrades_rather_than_raising() -> None:
    frame = resolve("https://app.test/b.js", 1, 0, lambda _: "not json")
    assert frame.resolved is False


def test_no_location_at_all_is_an_unresolved_frame_not_a_crash() -> None:
    frame = resolve(None, None, None, lambda _: None)
    assert frame.resolved is False
    assert frame.file is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan_sourcemaps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qabot.scan.sourcemaps'`.

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/sourcemaps.py`:

```python
"""A minified stack frame, resolved back to something a person can open.

Measured across seven real applications, the highest-severity signal this tool
produces was also its least actionable: an uncaught exception arrived carrying the
message `"Wl"` -- a mangled symbol -- while a lower-severity console error carried a
real file and line. A finding a builder cannot act on is barely better than no finding,
so where an application ships its `.map` files we read them.

Hand-rolled rather than taking a dependency: we need one direction of one format --
generated position to original position -- and the whole of it is Base64 VLQ over
comma- and semicolon-separated segments.

The rule that matters is the failure mode. A map that is missing, unfetchable or
malformed produces `resolved=False` carrying the minified location unchanged, and the
report says so. Presenting an unresolved frame as though it were original would send
somebody to read a file that does not exist.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel

Fetch = Callable[[str], "str | None"]

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_VLQ_SHIFT = 5
_VLQ_CONTINUE = 1 << _VLQ_SHIFT
_VLQ_MASK = _VLQ_CONTINUE - 1


class Frame(BaseModel):
    """Where an error happened. `resolved` says whether to believe the file name."""

    file: str | None = None
    line: int | None = None
    name: str | None = None
    resolved: bool = False


def decode_vlq(segment: str) -> list[int]:
    """Base64 VLQ segment to signed integers.

    Each value is a run of 6-bit groups, little-endian, the top bit marking
    continuation; the lowest bit of the assembled value carries the sign.
    """
    values, shift, accumulated = [], 0, 0
    for char in segment:
        digit = _B64.index(char)
        accumulated += (digit & _VLQ_MASK) << shift
        if digit & _VLQ_CONTINUE:
            shift += _VLQ_SHIFT
            continue
        negative = accumulated & 1
        value = accumulated >> 1
        values.append(-value if negative else value)
        shift, accumulated = 0, 0
    return values


def _lookup(raw: str, line: int, column: int) -> tuple[int, int, int] | None:
    """(source index, original line, name index) for a generated position, 0-based."""
    document = json.loads(raw)
    mappings = document.get("mappings", "")
    source_i = orig_line = orig_col = name_i = 0
    best: tuple[int, int, int] | None = None
    for generated_line, group in enumerate(mappings.split(";")):
        generated_col = 0
        for segment in group.split(","):
            if not segment:
                continue
            fields = decode_vlq(segment)
            generated_col += fields[0]
            if len(fields) >= 4:
                source_i += fields[1]
                orig_line += fields[2]
                orig_col += fields[3]
            if len(fields) >= 5:
                name_i += fields[4]
            # The mapping in force at a position is the last one at or before it.
            if generated_line == line and generated_col <= column:
                best = (source_i, orig_line, name_i if len(fields) >= 5 else -1)
        if generated_line > line:
            break
    return best


def resolve(url: str | None, line: int | None, column: int | None, fetch: Fetch) -> Frame:
    """Resolve one frame, or return it unresolved with the minified location intact."""
    if url is None or line is None:
        return Frame(file=url, line=line, resolved=False)

    unresolved = Frame(file=url, line=line, resolved=False)
    raw = fetch(url + ".map")
    if raw is None:
        return unresolved
    try:
        document = json.loads(raw)
        found = _lookup(raw, line - 1, column or 0)
    except (ValueError, KeyError, IndexError):
        return unresolved
    if found is None:
        return unresolved

    source_i, orig_line, name_i = found
    sources = document.get("sources") or []
    names = document.get("names") or []
    if not 0 <= source_i < len(sources):
        return unresolved
    return Frame(
        file=sources[source_i],
        line=orig_line + 1,
        name=names[name_i] if 0 <= name_i < len(names) else None,
        resolved=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_sourcemaps.py -v`
Expected: PASS (5 tests). Then `uv run pytest` — expect 482 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/scan/sourcemaps.py tests/test_scan_sourcemaps.py
uv run ruff format qabot/scan/sourcemaps.py tests/test_scan_sourcemaps.py
git add qabot/scan/sourcemaps.py tests/test_scan_sourcemaps.py
git commit -m "feat(scan): resolve minified frames through source maps, or say we could not"
```

---

## Task 6: Sweep — drive the app under budget

**Files:**
- Create: `qabot/scan/sweep.py`
- Test: `tests/test_scan_sweep.py`

**Interfaces:**
- Consumes: `Discovery` (Task 3), `blank_page` (Task 4), `BrowserDriver` (Tasks 1–2), `qabot.intrinsics.intrinsic_findings`.
- Produces:
  - `class PageResult(BaseModel)`: `path`, `status: int | None`, `title: str | None`, `final_url: str | None`, `screenshot: str | None`, `clicked: list[str]`
  - `class ScanResult(BaseModel)`: `origin`, `discovery: Discovery`, `pages: list[PageResult]`, `findings: list[Finding]`, `limitations: list[str]`, `not_visited: list[str]`, `stopped: str | None`
  - `class Budget(BaseModel)`: `max_pages: int = 25`, `delay_s: float = 1.0`, `page_timeout_ms: float = 20000.0`
  - `SAFE_CLICK_ROLES: tuple[str, ...]`
  - `def sweep(discovery: Discovery, driver, status_of: Callable[[str], int | None], budget: Budget = Budget()) -> ScanResult`

**Why:** This is the only impure unit, so everything else was kept pure to be tested without a browser. It is also where the design is most likely to be wrong — safe interaction is a judgement about somebody else's application — so the unsafe vocabulary and the allowed roles are two constants and every click is recorded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scan_sweep.py`:

```python
"""Sweep against a real browser and a deliberately broken app."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from demo.server import serve
from qabot.scan.discovery import Discovery

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page, sync_playwright

from qabot.drivers.browser import BrowserDriver
from qabot.scan.sweep import Budget, ScanResult, sweep

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def broken_app() -> Iterator[str]:
    """Four pages, each broken in exactly one way we claim to detect."""
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return '<html><body><h1>Home</h1><a href="/blank">blank</a></body></html>'

    @app.get("/blank", response_class=HTMLResponse)
    def blank() -> str:
        return "<html><body><script>null.x</script></body></html>"

    @app.get("/xhr", response_class=HTMLResponse)
    def xhr() -> str:
        return (
            "<html><body><p>" + "padding " * 40 + "</p>"
            "<script>fetch('/api/boom')</script></body></html>"
        )

    @app.get("/api/boom")
    def boom() -> JSONResponse:
        return JSONResponse({"detail": "no"}, status_code=500)

    @app.get("/tabs", response_class=HTMLResponse)
    def tabs() -> str:
        return (
            "<html><body><p>" + "padding " * 40 + "</p>"
            "<button id='t'>Show details</button>"
            "<script>document.getElementById('t')"
            ".addEventListener('click', () => { undefinedFunction(); })</script>"
            "</body></html>"
        )

    with serve(app) as url:
        yield url


@pytest.fixture(scope="module")
def browser_page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


def _sweep(url: str, page: Page, paths: list[str]) -> ScanResult:
    import httpx

    driver = BrowserDriver(base_url=url, page=page, reset_path=None, timeout_ms=15000)
    client = httpx.Client(base_url=url, timeout=10.0)

    def status_of(path: str) -> int | None:
        try:
            return client.get(path).status_code
        except httpx.HTTPError:
            return None

    discovery = Discovery(origin=url, paths=paths, counts={"root": 1})
    result = sweep(discovery, driver, status_of, Budget(max_pages=10, delay_s=0.0))
    client.close()
    return result


def test_a_page_that_crashes_and_renders_nothing_is_reported_blank(
    broken_app: str, browser_page: Page
) -> None:
    result = _sweep(broken_app, browser_page, ["/blank"])
    assert any(f.oracle == "blank_page" for f in result.findings)


def test_a_failing_background_request_is_reported(
    broken_app: str, browser_page: Page
) -> None:
    """A 200 page whose XHR 500s is not a healthy page."""
    result = _sweep(broken_app, browser_page, ["/xhr"])
    assert any(f.oracle == "browser_server_error" for f in result.findings)


def test_safe_clicks_surface_errors_a_load_alone_would_miss(
    broken_app: str, browser_page: Page
) -> None:
    """The whole argument for interacting: this error only exists after a click."""
    result = _sweep(broken_app, browser_page, ["/tabs"])
    assert any(f.oracle == "browser_page_error" for f in result.findings)
    assert "Show details" in result.pages[0].clicked


def test_the_budget_is_reported_rather_than_silently_truncating(
    broken_app: str, browser_page: Page
) -> None:
    """A truncated run that looks like a complete one is the failure to avoid."""
    import httpx

    driver = BrowserDriver(base_url=broken_app, page=browser_page, reset_path=None)
    client = httpx.Client(base_url=broken_app, timeout=10.0)
    discovery = Discovery(
        origin=broken_app, paths=["/", "/xhr", "/tabs"], counts={"root": 1}
    )
    result = sweep(
        discovery, driver, lambda p: client.get(p).status_code, Budget(max_pages=1, delay_s=0.0)
    )
    client.close()

    assert len(result.pages) == 1
    assert result.not_visited == ["/tabs", "/xhr"]


def test_the_no_reset_limitation_is_carried_onto_the_result(
    broken_app: str, browser_page: Page
) -> None:
    result = _sweep(broken_app, browser_page, ["/"])
    assert any("reset" in limitation for limitation in result.limitations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan_sweep.py -v -m browser`
Expected: FAIL — `ModuleNotFoundError: No module named 'qabot.scan.sweep'`.

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/sweep.py`:

```python
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
from qabot.models import Finding, Step, Workflow
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
        except Exception:  # noqa: BLE001 -- probing the page must never fail the sweep
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
            except Exception:  # noqa: BLE001
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
    budget: Budget = Budget(),
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

        # Private access is deliberate: BrowserDriver exposes no "what is on this page"
        # query, and adding one would change shared CI-product code for a scan-only need.
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
                    severity=Finding.model_fields["severity"].annotation.BUG,
                    outcome=Finding.model_fields["outcome"].annotation.FAIL,
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
```

Replace the awkward `Finding.model_fields[...]` severity lookup with plain imports at the top of the file — `from qabot.models import Finding, Outcome, Severity, Step, Workflow` — and build the finding with `severity=Severity.BUG, outcome=Outcome.FAIL`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_sweep.py -v -m browser`
Expected: PASS (5 tests). Then `uv run pytest` — expect 487 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/scan/sweep.py tests/test_scan_sweep.py
uv run ruff format qabot/scan/sweep.py tests/test_scan_sweep.py
git add qabot/scan/sweep.py tests/test_scan_sweep.py
git commit -m "feat(scan): sweep an app under budget with safe interactions"
```

---

## Task 7: Report — one file, written for somebody who does not use GitHub

**Files:**
- Create: `qabot/scan/report.py`
- Test: `tests/test_scan_report.py`

**Interfaces:**
- Consumes: `ScanResult` (Task 6), `Impact`/`impact_of`/`IMPACT_ORDER` (Task 4).
- Produces:
  - `def render_html(result: ScanResult) -> str`
  - `def headline(result: ScanResult) -> str`
  - `NOTHING_CHECKED: str`

**Why:** A pure function over the run, so it is testable without a browser. The section that matters most is the last one: under an anonymous scan there is a great deal we cannot see, and a report that quietly omits it is the false green in a new costume.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scan_report.py`:

```python
"""The report is a pure function of the run, so it is testable without a browser."""

from __future__ import annotations

from qabot.models import Finding, Outcome, Severity
from qabot.scan.discovery import Discovery
from qabot.scan.report import NOTHING_CHECKED, headline, render_html
from qabot.scan.sweep import PageResult, ScanResult


def _result(**overrides) -> ScanResult:
    base = {
        "origin": "https://app.test",
        "discovery": Discovery(origin="https://app.test", paths=["/", "/a"],
                               counts={"root": 1, "bundle": 1}),
        "pages": [PageResult(path="/", status=200), PageResult(path="/a", status=200)],
        "findings": [],
        "limitations": [],
        "not_visited": [],
    }
    return ScanResult(**{**base, **overrides})


def _finding(oracle: str) -> Finding:
    return Finding(
        workflow_id="scan", workflow_name="open /a", severity=Severity.BUG,
        outcome=Outcome.FAIL, statement="the page returned a server error",
        detail="GET /a -> 500", oracle=oracle,
    )


def test_a_scan_that_reached_one_page_never_reads_as_a_clean_bill_of_health() -> None:
    """The founding rule of this codebase, at the new product's front door."""
    thin = _result(
        discovery=Discovery(origin="https://app.test", paths=["/"], counts={"root": 1}),
        pages=[PageResult(path="/", status=200)],
    )
    html = render_html(thin)
    assert NOTHING_CHECKED in html


def test_a_real_scan_with_no_findings_says_so_positively() -> None:
    html = render_html(_result())
    assert NOTHING_CHECKED not in html
    assert "No problems" in html


def test_findings_are_grouped_by_visitor_impact() -> None:
    html = render_html(_result(findings=[_finding("server_error"), _finding("browser_console_error")]))
    assert html.index("Broken") < html.index("Glitchy")


def test_what_could_not_be_checked_is_always_stated() -> None:
    """Under an anonymous scan there is a lot we cannot see. Omitting it is the lie."""
    html = render_html(_result(not_visited=["/deep"], limitations=["no reset endpoint"]))
    assert "could not check" in html.lower()
    assert "/deep" in html
    assert "no reset endpoint" in html


def test_the_report_is_self_contained() -> None:
    """It gets emailed and dropped into folders. External assets would not survive."""
    html = render_html(_result(findings=[_finding("server_error")]))
    assert "<script src=" not in html
    assert "<link rel=\"stylesheet\"" not in html


def test_headline_counts_broken_pages_in_plain_language() -> None:
    assert headline(_result(findings=[_finding("server_error")])) == "1 page is broken"
    assert headline(_result()) == "No problems found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qabot.scan.report'`.

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/report.py`. It must:

- Build one HTML string with an inline `<style>` block and no external references.
- Group findings with `impact_of`, iterate `IMPACT_ORDER`, and title the groups
  `Broken`, `Glitchy`, `Noted`.
- Emit `NOTHING_CHECKED` whenever `len(result.pages) <= 1` **or**
  `sum(result.discovery.counts.values()) <= 1`, defined as:

```python
NOTHING_CHECKED = (
    "This scan reached almost none of your app. That is not the same as finding "
    "nothing wrong -- most of your pages were never opened, so this report is not "
    "evidence that they work."
)
```

- Always render a "What I could not check" section listing `result.limitations`,
  `result.not_visited`, `result.stopped`, and the standing anonymous-scan caveat
  ("pages behind a login were not reached; forms were found but not submitted").
- Escape all interpolated text with `html.escape`.
- `headline(result)` returns `"No problems found"` when there are no BROKEN or GLITCHY
  findings, otherwise `"N page(s) is/are broken"` counting distinct
  `finding.workflow_name` among BROKEN findings, falling back to a glitch count.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_report.py -v`
Expected: PASS (6 tests). Then `uv run pytest` — expect 493 passed, 1 skipped.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check qabot/scan/report.py tests/test_scan_report.py
uv run ruff format qabot/scan/report.py tests/test_scan_report.py
git add qabot/scan/report.py tests/test_scan_report.py
git commit -m "feat(scan): render a self-contained report that states what it could not check"
```

---

## Task 8: `qabot scan` end to end

**Files:**
- Create: `qabot/scan/cli.py`
- Modify: `qabot/cli.py` (module docstring; `main`'s subparser registration)
- Test: `tests/test_scan_cli.py`

**Interfaces:**
- Consumes: every prior task.
- Produces: `def cmd_scan(args: argparse.Namespace) -> int`, and `qabot scan <url> [--out report.html] [--max-pages N] [--delay S]`.

**Why:** Wires the pure units to the impure one behind a single command, and pins the property that matters most across the whole product.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scan_cli.py`:

```python
"""The command, against a real local app."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from demo.server import serve
from qabot.cli import main

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def small_app() -> Iterator[str]:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (
            "<html><body><h1>Shop</h1>"
            "<p>" + "words " * 40 + "</p>"
            '<a href="/broken">broken</a></body></html>'
        )

    @app.get("/broken", response_class=HTMLResponse)
    def broken() -> str:
        return "<html><body><script>null.x</script></body></html>"

    with serve(app) as url:
        yield url


def test_scan_writes_a_report_naming_the_broken_page(small_app: str, tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    code = main(["scan", small_app, "--out", str(out), "--delay", "0"])

    assert code == 0
    html = out.read_text()
    assert "/broken" in html
    assert "Broken" in html


def test_scan_reports_honestly_when_it_reached_almost_nothing(tmp_path: Path) -> None:
    """A one-page app must not produce a document that reads as 'all clear'."""
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<html><body><p>" + "words " * 40 + "</p></body></html>"

    from qabot.scan.report import NOTHING_CHECKED

    with serve(app) as url:
        out = tmp_path / "thin.html"
        main(["scan", url, "--out", str(out), "--delay", "0"])
        assert NOTHING_CHECKED in out.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scan_cli.py -v -m browser`
Expected: FAIL — `argparse` exits with "invalid choice: 'scan'".

- [ ] **Step 3: Write minimal implementation**

Create `qabot/scan/cli.py` holding `cmd_scan`, which:

1. Builds an `httpx.Client` with a `User-Agent` of `qabot-scan/0.1 (+read-only page loads)`, `follow_redirects=True`.
2. Defines `fetch(url) -> str | None` returning `response.text` on 2xx and `None` otherwise, swallowing `httpx.HTTPError` into `None` — discovery treats an unreadable source as an absent one.
3. Calls `discover(origin, fetch)`.
4. Launches Chromium via `sync_playwright`, builds `BrowserDriver(base_url=origin, page=page, artifacts_dir=..., reset_path=None, timeout_ms=budget.page_timeout_ms)`.
5. Calls `sweep(...)` with `status_of` backed by the same client.
6. Writes `render_html(result)` to `--out` (default `qabot-scan-report.html`).
7. Prints `headline(result)` and the output path to stdout.
8. Returns `0` always — this is a report, not a gate. A scan that finds problems has succeeded.

In `qabot/cli.py`, register the subcommand inside `main`:

```python
    p_scan = sub.add_parser("scan", help="check a live app you have only the URL of")
    p_scan.add_argument("url")
    p_scan.add_argument("--out", default="qabot-scan-report.html")
    p_scan.add_argument("--max-pages", type=int, default=25)
    p_scan.add_argument("--delay", type=float, default=1.0)
    p_scan.add_argument("--artifacts", default="qa-artifacts")
    p_scan.set_defaults(func=cmd_scan)
```

and import `cmd_scan` from `qabot.scan.cli`. Update `qabot/cli.py`'s module docstring, which currently says "Three commands" and lists them, to describe the scan command as well and to say why it is a different product from the other three.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan_cli.py -v -m browser`
Expected: PASS (2 tests). Then `uv run pytest` — expect 495 passed, 1 skipped.

- [ ] **Step 5: Verify against a real third-party application**

Tests are not proof for this product. Run it against one of the spike's apps and read the output:

```bash
uv run qabot scan https://challengebrew.com --out /tmp/cb.html --max-pages 12
```

Expected: the report names `/account` and reports the `Cannot read properties of null (reading 'tier')` error under **Glitchy**. If it does not, the sweep or the grading is wrong — report that rather than adjusting the test.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check qabot/scan/cli.py qabot/cli.py tests/test_scan_cli.py
uv run ruff format qabot/scan/cli.py qabot/cli.py tests/test_scan_cli.py
git add qabot/scan/cli.py qabot/cli.py tests/test_scan_cli.py
git commit -m "feat(scan): add the qabot scan command"
```

---

## Task 9: Document the second product

**Files:**
- Modify: `README.md`, `docs/DECISIONS.md`

**Interfaces:**
- Consumes: the finished command.
- Produces: no code.

**Why:** The repository now holds two products for two buyers, and every existing docstring argues for the first one. A reader who finds `qabot/scan/` with no explanation will assume it is part of the merge gate and misread all of it.

- [ ] **Step 1: Add a README section**

Under the existing content, add a `## Two products` section: the merge gate (`seed`, `run`, `demo`) and the scan (`scan`), what each needs as input, and the one-line reason they share a repository — the driver and the oracles are the same thing in both.

- [ ] **Step 2: Add a DECISIONS entry**

Add `D51 — The scan product reuses the oracles and abandons the knowledge base`, in the existing voice and numbering, recording: the measurement that motivated it (28/28 false positives on the expectation tier, 0 on the intrinsic tier across 120 routes), the choice to derive severity rather than store it, and the two `BrowserDriver` changes with the redirect bug that forced them.

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest
git add README.md docs/DECISIONS.md
git commit -m "docs: describe the scan product and record D51"
```

---

## Self-Review

**Spec coverage.** §2 boundary → Tasks 1, 2 (driver) and 3–8 (new package). §3 discovery → Task 3. §4 sweep → Task 6. §5 grading, `blank_page`, source maps → Tasks 4 and 5. §6 report → Task 7. §7 module layout → the File Structure table; every listed module has a task. §8 operating on apps we do not own → encoded in Task 3 (`UNSAFE_WORDS`, robots), Task 6 (budget, 429, safe clicks, no reset) and Task 2. §9 testing → each task's tests, with the honesty property in Tasks 7 and 8. §10 falsifiers → not code; recorded in the spec.

**Placeholder scan.** No TBDs. Task 7's implementation step describes required behaviour with the exact constant and predicate rather than a full code block, because the HTML body is long and its content is pinned by six tests; every other code step is complete.

**Type consistency.** `Fetch` is defined in `discovery.py` and re-declared in `sourcemaps.py` to avoid a circular import — intentional, and both are the same shape. `Discovery`, `PageResult`, `ScanResult`, `Budget`, `Impact` and `Frame` are used with the fields defined here. `impact_of`, `blank_page`, `discover`, `followable`, `sweep`, `render_html`, `headline` keep one name each throughout. Task 6's draft reaches `Finding.model_fields[...]` for enums and the step immediately instructs replacing it with direct imports.

**One known wart, deliberate.** `sweep` reads `driver._page` to enumerate clickable controls. `BrowserDriver` exposes no "what is on this page" query, and adding one is a change to shared CI code for a scan-only need. If a second consumer wants it, promote it to a real method then.
