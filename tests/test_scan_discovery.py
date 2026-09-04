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
