"""The accessibility tree, trimmed to what a walker can act on.

`aria_snapshot()` is a YAML-ish outline: one line per node, `- role "name"`. Under the
cap, interactive nodes are kept first because they are what the next action names; the
truncation is stated in the snapshot itself so the model, and a reader of the log, know
the page had more than they saw.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

SNAPSHOT_CAP = 12_000
INTERACTIVE_ROLES = (
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "option",
    "switch",
    "slider",
    "searchbox",
    "spinbutton",
    "heading",
    "dialog",
    "alert",
)


def _interactive(line: str) -> bool:
    stripped = line.lstrip("- ").lstrip()
    return stripped.startswith(INTERACTIVE_ROLES)


def trimmed_snapshot(page: Page, cap: int = SNAPSHOT_CAP) -> str:
    raw = page.locator("body").aria_snapshot()
    if len(raw) <= cap:
        return raw
    lines = raw.splitlines()
    ordered = [ln for ln in lines if _interactive(ln)] + [
        ln for ln in lines if not _interactive(ln)
    ]
    kept: list[str] = []
    size = 0
    for line in ordered:
        if size + len(line) + 1 > cap:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept) + f"\n[snapshot truncated: kept {len(kept)} of {len(lines)} lines]"


def visible_text(page: Page) -> str:
    return page.evaluate("() => document.body ? document.body.innerText : ''")
