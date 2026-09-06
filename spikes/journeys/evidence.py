"""What changed, gathered in terms a journey author can use.

The diff is the primary source. Settings names are pulled out separately because a
journey's *preconditions* usually live there, and a model that has to find
`LANGFLOW_ALLOW_CUSTOM_COMPONENTS` inside 60 KB of diff will miss it. Related specs are
the product's own end-to-end tests: the closest thing to journeys written by people
who know what the product should do.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from qabot.impact import changed_symbols, parse_unified_diff

DIFF_CAP = 60_000
_ENV_RE = re.compile(r"\bLANGFLOW_[A-Z0-9_]+\b")
_SETTINGS_RE = re.compile(r"\bsettings\.[a-z_][a-z0-9_]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class Evidence(BaseModel):
    base: str
    head: str
    diff: str
    diff_truncated: bool
    changed_files: list[str]
    changed_symbols: list[str]
    settings_names: list[str]
    description: str = ""
    related_specs: dict[str, str] = Field(default_factory=dict)


def git_diff(repo: Path, base: str, head: str) -> str:
    return subprocess.run(
        ["git", "diff", f"{base}..{head}"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def settings_in(diff: str) -> list[str]:
    """Every env-style and `settings.x` token on a changed line, in first-seen order."""
    seen: dict[str, None] = {}
    for line in diff.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        for match in _ENV_RE.findall(line) + _SETTINGS_RE.findall(line):
            seen.setdefault(match, None)
    return list(seen)


def related_specs(
    repo: Path, tokens: list[str], limit: int = 5, excerpt: int = 4000
) -> dict[str, str]:
    """Playwright specs sharing the most identifier tokens with the change."""
    wanted = {t.split("::")[-1] for t in tokens if len(t.split("::")[-1]) > 2}
    scored: list[tuple[int, str, str]] = []
    for path in repo.rglob("*.spec.ts"):
        if "node_modules" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        idents = set(_IDENT_RE.findall(text))
        score = len(wanted & idents)
        if score:
            scored.append((score, str(path.relative_to(repo)), text[:excerpt]))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return {rel: text for _, rel, text in scored[:limit]}


def gather(repo: Path, base: str, head: str, description: str = "") -> Evidence:
    repo = Path(repo)
    full = git_diff(repo, base, head)
    truncated = len(full) > DIFF_CAP
    diff = full[:DIFF_CAP]
    by_file = parse_unified_diff(full)
    symbols = sorted(s for s in changed_symbols(by_file, repo) if "::" not in s)
    files = sorted(by_file)
    tokens = symbols + [Path(f).stem for f in files]
    return Evidence(
        base=base,
        head=head,
        diff=diff,
        diff_truncated=truncated,
        changed_files=files,
        changed_symbols=symbols,
        settings_names=settings_in(full),
        description=description,
        related_specs=related_specs(repo, tokens),
    )
