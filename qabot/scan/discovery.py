"""What the application says about its own routes.

`routemap.py` reads a server's route table by importing the application. A scan never
gets to do that -- we have a URL and nothing else -- so this module applies the same
principle from outside: ask the app what it serves rather than inferring it.

An SPA ships its router to the browser, so the route table is sitting in the bundle in
plain text. That is the highest-trust source available to a stranger, and measurably
the one that matters: across seven real applications, discovery found between 1 and 32
routes, and the number of defects found tracked it exactly. Crawling `a[href]` alone
finds one page on a React landing page, which is why it cannot be the only source --
but a server-rendered site with no client router has no bundle at all, and for that
site `a[href]` is not a supplement, it is the only source there is.

That link-following is deliberately shallow: only the root page's own anchors are
read, not the anchors on every page discovery goes on to find. Going deeper would
mean fetching pages breadth-first and feeding each one back through this same
extraction, which is a small change in shape but a large one in cost -- and it starts
to blur this module's one hard boundary, that it never touches a browser. `discover`
takes a `fetch` function and nothing else, which is what makes it exhaustively
testable without Chromium; a page whose links are written by JavaScript rather than
present in the served HTML is invisible to it regardless of how many hops it takes,
because there is no browser here to run that script. One hop past the root was
enough to recover every page of the field experiment's server-rendered app, so that
is the line drawn for now -- multi-hop, JS-rendered crawling is a real gap, and it is
a browser-driving feature for a later version, not a quiet claim this one already
makes.

The per-source counts are not telemetry. A scan that reached one page and reported no
problems is not a clean bill of health, and `counts` is how the report tells a reader
which of the two they are holding.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urldefrag, urljoin, urlsplit

from pydantic import BaseModel, Field

#: Fetch a URL and return its body, or None when it could not be read. Injected so
#: every rule in this module is testable without a network.
Fetch = Callable[[str], "str | None"]

#: Router declarations as they survive minification, plus `<Link to=>` targets.
_ROUTE_RE = re.compile(r'(?:\bpath|\bto)\s*:\s*"(/[^"]*)"')
_SCRIPT_RE = re.compile(r'<(?:script[^>]+src|link[^>]+rel="modulepreload"[^>]+href)="([^"]+\.js)"')
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
#: `<a href="...">` targets in served HTML -- the source a server-rendered page has
#: instead of a bundle. Any quoted `href` on an `<a` tag; `followable` does the actual
#: filtering, so this only needs to find candidates, not judge them.
_ANCHOR_RE = re.compile(r'<a\s[^>]*?href="([^"]*)"', re.IGNORECASE)
_ASSET_RE = re.compile(
    r"\.(?:js|css|png|jpe?g|svg|gif|ico|woff2?|ttf|map|json|xml|txt|pdf)$", re.IGNORECASE
)

#: A path naming one of these is a state change, not a page. We drive applications we
#: do not own, so the list is deliberately broad and deliberately dumb: a false
#: exclusion costs one unvisited page, a false inclusion costs somebody their data.
UNSAFE_WORDS = (
    "logout",
    "signout",
    "sign-out",
    "delete",
    "remove",
    "destroy",
    "unsubscribe",
    "cancel",
    "checkout",
    "purchase",
    "billing",
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


def routes_from_anchors(html: str, origin: str) -> set[str]:
    """Same-origin, safe-to-visit paths named by an `<a href>` in served HTML.

    The only source in this module that reads markup a server actually rendered,
    rather than a bundle or a sitemap it happens to publish -- which is exactly why
    it exists: a server-rendered page ships neither of those, and its anchors are the
    whole of what it tells us about itself.
    """
    return {p for href in _ANCHOR_RE.findall(html) if (p := followable(origin, href))}


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
    counts = {"bundle": 0, "sitemap": 0, "root": 0, "links": 0}
    paths: set[str] = set()

    root = fetch(f"{origin}/")
    if root is not None:
        paths.add("/")
        counts["root"] = 1

    # Only the root page's own anchors -- see the module docstring for why this does
    # not chase links a level deeper.
    for path in routes_from_anchors(root or "", origin):
        if path not in paths:
            paths.add(path)
            counts["links"] += 1

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
