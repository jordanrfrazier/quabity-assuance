"""Wire the pure units in this package to one impure command.

Every other module in `qabot.scan` is pure: `discover` takes a fetch function,
`sweep` takes a driver and a status function, `render_html` takes a `ScanResult`.
None of them knows how to talk to a real network or launch a real browser, on
purpose, so that they stay cheap to test. This module is where that changes -- it
builds the one `httpx.Client` and the one Chromium instance a scan needs, and hands
them to the pure units instead of teaching those units to build their own.

WHY `reset_path=None` is not a flag here: `qabot run` lets a caller opt out of reset
because they might be testing their own app and know it lacks one. A scan never has
that option to begin with -- the whole premise of this command is a URL and nothing
else, so there is no app we could plausibly be trusted to reset. Passing anything
other than `None` here would be a standing invitation to POST `/reset` at a stranger's
production server.

WHY `cmd_scan` returns 0 unconditionally: `qabot run` is a merge gate, and a workflow
that failed must fail the build. A scan is a report handed to someone who cannot act
on an exit code -- they are going to open the HTML file regardless of what the process
returned. Making the exit code track findings would only give a CI pipeline a reason
to treat "the report finished" and "the report is bad news" as the same event, which
they are not.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from qabot.drivers.browser import BrowserDriver
from qabot.scan.discovery import discover
from qabot.scan.report import headline, render_html
from qabot.scan.sweep import Budget, sweep

#: Identifies the traffic as ours to whoever operates the app we are reading, and
#: says plainly what it will and will not do -- the same spirit as a crawler's UA
#: string, scaled down to a tool that only ever performs GETs.
_USER_AGENT = "qabot-scan/0.1 (+read-only page loads)"


def cmd_scan(args: argparse.Namespace) -> int:
    origin = args.url.rstrip("/")
    client = httpx.Client(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
        timeout=10.0,
    )

    def fetch(url: str) -> str | None:
        # An unreadable source is an absent one, not an error: discovery has other
        # sources to fall back on, and a scan that aborted because one script 404'd
        # would be a worse outcome than a scan that just noted less.
        try:
            response = client.get(url)
        except httpx.HTTPError:
            return None
        return response.text if response.is_success else None

    def status_of(path: str) -> int | None:
        try:
            return client.get(f"{origin}{path}").status_code
        except httpx.HTTPError:
            return None

    discovery = discover(origin, fetch)
    budget = Budget(max_pages=args.max_pages, delay_s=args.delay)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        driver = BrowserDriver(
            base_url=origin,
            page=page,
            artifacts_dir=Path(args.artifacts),
            reset_path=None,
            timeout_ms=budget.page_timeout_ms,
        )
        try:
            result = sweep(discovery, driver, status_of, budget)
        finally:
            driver.close()
            browser.close()

    client.close()

    out_path = Path(args.out)
    out_path.write_text(render_html(result))
    print(headline(result))
    print(f"report written to {out_path}")
    return 0
