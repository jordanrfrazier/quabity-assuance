# User Journeys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a code change, author plain-language user journeys a human can read and repeat, walk them in a real browser against a running instance, and report PASS / FAIL / BLOCKED per journey with evidence — then measure it on Langflow PR #14913, fixed vs broken.

**Architecture:** A spike package `spikes/journeys/` with five pure-ish modules and one command. `evidence.py` turns a git range into what-changed facts; `author.py` asks the model for journeys and validates them against a strict schema; `walker.py` drives `qabot.drivers.browser.BrowserDriver` one action at a time from an accessibility snapshot, running the product's intrinsic oracles plus two page-text checks after every action; `report.py` renders Markdown a person can follow; `run.py` wires them. Nothing under `qabot/` changes.

**Tech Stack:** Python 3.13, pydantic, Playwright 1.62 (`aria_snapshot`), `qabot.llm.ClaudeCliLLM` (local `claude -p`), pytest with the existing `browser` marker, `uv run` for everything.

**Spec:** `docs/superpowers/specs/2026-09-05-user-journeys-design.md`

## Global Constraints

- All Python via `uv run python` / `uv run pytest` (user rule).
- No commits and no pushes; Jordan commits. Every "checkpoint" step below is a ruff + test run, never `git commit`.
- Do not modify anything under `qabot/`, `demo/`, or `tests/`.
- Ruff line length 100 applies to `spikes/` too; `ruff check` does not gate E501, so run `awk 'length > 100'` on every file you touch.
- Snapshot cap 12,000 characters; diff cap 60,000 characters; walker cap 6 actions per step. Caps are recorded in outputs, never silent.
- Inferred verdicts are reported at `Severity.QUESTION`; app-declared failures keep the severity `qabot.intrinsics` assigns.
- Spike tests live in `spikes/journeys/tests/` and run with `uv run pytest spikes/journeys/tests`; browser tests carry `pytestmark = pytest.mark.browser`.
- LLM access only through the `LLMProvider` protocol (`complete_json(system, prompt, schema_hint) -> dict`), so every test can inject `FakeLLM`.

---

### Task 1: Package skeleton, journey schema, and the fake model

**Files:**
- Create: `spikes/__init__.py` (empty)
- Create: `spikes/journeys/__init__.py` (empty)
- Create: `spikes/journeys/models.py`
- Create: `spikes/journeys/fakes.py`
- Create: `spikes/journeys/tests/__init__.py` (empty)
- Test: `spikes/journeys/tests/test_models.py`

**Interfaces:**
- Produces: `JourneyStep(do, see)`, `Preconditions(settings, state)`, `Journey(id, title, persona, preconditions, steps, traces_to, provenance)`, `StepOutcome` enum (`HELD`, `FAILED`, `BLOCKED`, `NOT_REACHED`), `ActionRecord`, `StepResult`, `JourneyResult`, and `FakeLLM(responses: list[dict])` whose `complete_json` returns responses in order and records every prompt in `.calls`.

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_models.py
import pytest
from pydantic import ValidationError

from spikes.journeys.fakes import FakeLLM
from spikes.journeys.models import Journey, JourneyStep, StepOutcome


def test_journey_requires_see_on_every_step():
    with pytest.raises(ValidationError):
        Journey(id="j1", title="t", persona="p", steps=[{"do": "open the app", "see": ""}])


def test_journey_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        Journey(id="j1", title="t", persona="p", steps=[])


def test_journey_provenance_is_fixed():
    j = Journey(id="j1", title="t", persona="p",
                steps=[JourneyStep(do="open the app", see="the home page")])
    assert j.provenance == "inferred_from_diff"
    with pytest.raises(ValidationError):
        Journey(id="j1", title="t", persona="p", provenance="human_confirmed",
                steps=[JourneyStep(do="a", see="b")])


def test_step_outcomes_are_four_and_named():
    assert {o.value for o in StepOutcome} == {"held", "failed", "blocked", "not_reached"}


def test_fake_llm_replays_in_order_and_records_prompts():
    llm = FakeLLM([{"a": 1}, {"b": 2}])
    assert llm.complete_json("sys", "first", {}) == {"a": 1}
    assert llm.complete_json("sys", "second", {}) == {"b": 2}
    assert [c["prompt"] for c in llm.calls] == ["first", "second"]
    with pytest.raises(RuntimeError, match="no more"):
        llm.complete_json("sys", "third", {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'spikes'`

- [ ] **Step 3: Write the models and the fake**

```python
# spikes/journeys/models.py
"""The user journey and what walking it produced.

A journey is written for a person first: each step says what to do and what to see.
It is authored by a model from a diff, so its provenance is fixed to
"inferred_from_diff" and can never be upgraded by the code that produced it.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from qabot.models import Finding, Outcome


class JourneyStep(BaseModel):
    do: str = Field(min_length=1)
    see: str = Field(min_length=1)


class Preconditions(BaseModel):
    settings: dict[str, str] = Field(default_factory=dict)
    state: list[str] = Field(default_factory=list)


class Journey(BaseModel):
    id: str
    title: str
    persona: str
    preconditions: Preconditions = Field(default_factory=Preconditions)
    steps: list[JourneyStep] = Field(min_length=1)
    traces_to: str = ""
    provenance: Literal["inferred_from_diff"] = "inferred_from_diff"


class StepOutcome(StrEnum):
    HELD = "held"
    FAILED = "failed"
    BLOCKED = "blocked"
    NOT_REACHED = "not_reached"


class ActionRecord(BaseModel):
    op: str
    params: dict[str, object] = Field(default_factory=dict)
    ok: bool
    summary: str = ""
    screenshot: str | None = None


class StepResult(BaseModel):
    index: int
    do: str
    see: str
    outcome: StepOutcome
    reason: str = ""
    actions: list[ActionRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    screenshot: str | None = None


class JourneyResult(BaseModel):
    journey: Journey
    outcome: Outcome
    steps: list[StepResult]
    why: str = ""
```

```python
# spikes/journeys/fakes.py
"""A scripted model for tests. Replays responses in order and remembers every prompt,
so a test can assert both what the code did with an answer and what it asked."""
from __future__ import annotations


class FakeLLM:
    name = "fake"

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        self.calls.append({"system": system, "prompt": prompt})
        if not self._responses:
            raise RuntimeError(f"FakeLLM has no more responses (call {len(self.calls)})")
        return self._responses.pop(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_models.py -q`
Expected: 5 passed

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py`
Expected: no output from awk, ruff clean

---

### Task 2: Evidence — what changed, in the author's terms

**Files:**
- Create: `spikes/journeys/evidence.py`
- Test: `spikes/journeys/tests/test_evidence.py`

**Interfaces:**
- Consumes: `qabot.impact.parse_unified_diff(diff_text) -> dict[str, set[int]]`, `qabot.impact.changed_symbols(diff, source_root, route_map=None) -> set[str]`.
- Produces: `Evidence` model and `gather(repo: Path, base: str, head: str, description: str = "") -> Evidence`; helpers `settings_in(diff: str) -> list[str]`, `related_specs(repo: Path, tokens: list[str], limit: int = 5, excerpt: int = 4000) -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_evidence.py
import subprocess
from pathlib import Path

from spikes.journeys.evidence import DIFF_CAP, gather, related_specs, settings_in


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout


def _repo_with_two_commits(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text(
        "def load(settings):\n    return settings.components_path\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "flow.spec.ts").write_text(
        "test('load components_path', async () => { await page.click('Run'); });\n")
    (repo / "tests" / "other.spec.ts").write_text("test('unrelated', async () => {});\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text(
        "def load(settings):\n"
        "    if os.environ.get('LANGFLOW_LAZY_LOAD_COMPONENTS'):\n"
        "        return settings.allow_custom_components\n"
        "    return settings.components_path\n")
    _git(repo, "commit", "-qam", "head")
    return repo


def test_settings_in_finds_env_and_settings_tokens():
    diff = "+ if settings.allow_custom_components and LANGFLOW_LAZY_LOAD_COMPONENTS:\n"
    assert settings_in(diff) == ["LANGFLOW_LAZY_LOAD_COMPONENTS", "settings.allow_custom_components"]


def test_related_specs_ranks_by_shared_tokens(tmp_path):
    repo = _repo_with_two_commits(tmp_path)
    specs = related_specs(repo, ["components_path", "load"], limit=1)
    assert list(specs) == ["tests/flow.spec.ts"]


def test_gather_reads_the_range(tmp_path):
    repo = _repo_with_two_commits(tmp_path)
    ev = gather(repo, "HEAD~1", "HEAD", description="fix: lazy loading")
    assert "LANGFLOW_LAZY_LOAD_COMPONENTS" in ev.settings_names
    assert "settings.allow_custom_components" in ev.settings_names
    assert ev.changed_files == ["app.py"]
    assert "load" in ev.changed_symbols
    assert ev.description == "fix: lazy loading"
    assert ev.diff_truncated is False
    assert "tests/flow.spec.ts" in ev.related_specs


def test_gather_caps_and_records_truncation(tmp_path, monkeypatch):
    repo = _repo_with_two_commits(tmp_path)
    monkeypatch.setattr("spikes.journeys.evidence.DIFF_CAP", 40)
    ev = gather(repo, "HEAD~1", "HEAD")
    assert ev.diff_truncated is True
    assert len(ev.diff) <= 40
    assert DIFF_CAP == 60_000  # the module constant the CLI reports
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_evidence.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'spikes.journeys.evidence'`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/evidence.py
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
```

Note: `changed_symbols` reads the source at `repo` as it is on disk. Task 8 checks out `head` before gathering, so the symbols match the diff's new side.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_evidence.py -q`
Expected: 4 passed. If `test_gather_reads_the_range` fails on `"load" in ev.changed_symbols`, print `ev.changed_symbols` — `changed_symbols` emits bare names for Python defs whose body overlaps changed lines; `load` spans lines 1–4 on the new side, all changed.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q`

---

### Task 3: Author — journeys from evidence

**Files:**
- Create: `spikes/journeys/author.py`
- Test: `spikes/journeys/tests/test_author.py`

**Interfaces:**
- Consumes: `Evidence`, `Journey`, `LLMProvider.complete_json`.
- Produces: `author(evidence: Evidence, llm) -> list[Journey]`, `AuthorError`, module constants `SYSTEM` and `MIN_JOURNEYS = 3`, `MAX_JOURNEYS = 8`.

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_author.py
import pytest

from spikes.journeys.author import AuthorError, author
from spikes.journeys.evidence import Evidence
from spikes.journeys.fakes import FakeLLM


def _evidence() -> Evidence:
    return Evidence(base="a", head="b", diff="+ if settings.allow_custom_components:\n",
                    diff_truncated=False, changed_files=["components.py"],
                    changed_symbols=["load"],
                    settings_names=["LANGFLOW_ALLOW_CUSTOM_COMPONENTS"],
                    description="fix: lazy loading wipes registry",
                    related_specs={"tests/flow.spec.ts": "test('run flow')"})


def _journey(i: int) -> dict:
    return {"id": f"j{i}", "title": f"journey {i}", "persona": "a first-time user",
            "preconditions": {"settings": {"LANGFLOW_ALLOW_CUSTOM_COMPONENTS": "false"},
                              "state": []},
            "steps": [{"do": "open the app", "see": "the projects page"}],
            "traces_to": "components.py: allow_custom_components"}


def test_author_returns_validated_journeys_and_shows_evidence():
    llm = FakeLLM([{"journeys": [_journey(1), _journey(2), _journey(3)]}])
    journeys = author(_evidence(), llm)
    assert [j.id for j in journeys] == ["j1", "j2", "j3"]
    assert journeys[0].provenance == "inferred_from_diff"
    prompt = llm.calls[0]["prompt"]
    assert "LANGFLOW_ALLOW_CUSTOM_COMPONENTS" in prompt
    assert "tests/flow.spec.ts" in prompt
    assert "fix: lazy loading wipes registry" in prompt


def test_author_reasks_once_with_the_validation_error():
    bad = _journey(1); bad["steps"] = [{"do": "open the app", "see": ""}]
    llm = FakeLLM([{"journeys": [bad, _journey(2), _journey(3)]},
                   {"journeys": [_journey(1), _journey(2), _journey(3)]}])
    journeys = author(_evidence(), llm)
    assert len(journeys) == 3
    assert "see" in llm.calls[1]["prompt"]


def test_author_fails_loudly_after_second_bad_answer():
    llm = FakeLLM([{"journeys": []}, {"journeys": []}])
    with pytest.raises(AuthorError, match="3"):
        author(_evidence(), llm)


def test_author_caps_journey_count():
    llm = FakeLLM([{"journeys": [_journey(i) for i in range(1, 12)]}])
    with pytest.raises(AuthorError, match="8"):
        author(_evidence(), llm)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_author.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/author.py
"""Journeys from evidence. One model call, validated hard, re-asked once.

The output is for a person before it is for the walker: every step is a sentence a
tester could follow and a sentence describing what they should then see. The prompt
insists on traceability so a journey that came from nowhere is visible as such.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from qabot.llm import LLMError
from spikes.journeys.evidence import Evidence
from spikes.journeys.models import Journey

MIN_JOURNEYS = 3
MAX_JOURNEYS = 8

SYSTEM = (
    "You write user journeys for a QA tester who has never seen this product. You are given a "
    "code change (a diff, its description, the settings it touches, and the product's own "
    "end-to-end tests that are closest to it). Write the journeys a careful tester would walk "
    "to confirm this change did what it claims and broke nothing beside it.\n"
    "Rules:\n"
    f"- Between {MIN_JOURNEYS} and {MAX_JOURNEYS} journeys.\n"
    "- Journey 1 is always the happy path the change protects.\n"
    "- At least one journey runs under the condition that makes the change matter; put that "
    "condition in preconditions.settings using the exact setting names from the evidence.\n"
    "- Every step has `do` (one action a person performs, present tense, naming the visible "
    "control) and `see` (what the screen shows if the product is correct). No step without "
    "a `see`.\n"
    "- `traces_to` names the diff hunk, symbol or description sentence the journey comes from.\n"
    "- Steps use the product's own words for controls and pages, taken from the specs when "
    "possible. Never invent a control the evidence does not suggest exists.\n"
    "Answer with ONLY a JSON object: {\"journeys\": [Journey, ...]} where Journey = "
    "{id, title, persona, preconditions:{settings:{}, state:[]}, steps:[{do, see}], traces_to}."
)


class AuthorError(RuntimeError):
    pass


def _prompt(ev: Evidence) -> str:
    specs = "\n\n".join(f"### {path}\n{text}" for path, text in ev.related_specs.items())
    return (
        f"## Change description\n{ev.description or '(none given)'}\n\n"
        f"## Settings and flags touched\n{', '.join(ev.settings_names) or '(none)'}\n\n"
        f"## Changed files\n{', '.join(ev.changed_files)}\n\n"
        f"## Changed symbols\n{', '.join(ev.changed_symbols) or '(none)'}\n\n"
        f"## Diff ({ev.base}..{ev.head}){' [TRUNCATED]' if ev.diff_truncated else ''}\n"
        f"```\n{ev.diff}\n```\n\n"
        f"## The product's closest end-to-end tests\n{specs or '(none found)'}\n"
    )


def _parse(raw: dict) -> list[Journey]:
    items = raw.get("journeys") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ValueError("answer has no 'journeys' list")
    journeys = [Journey.model_validate(item) for item in items]
    if not MIN_JOURNEYS <= len(journeys) <= MAX_JOURNEYS:
        raise ValueError(
            f"{len(journeys)} journeys; need between {MIN_JOURNEYS} and {MAX_JOURNEYS}"
        )
    return journeys


def author(evidence: Evidence, llm) -> list[Journey]:
    prompt = _prompt(evidence)
    schema = {"journeys": [{"id": "", "title": "", "persona": "", "steps": [{"do": "", "see": ""}]}]}
    last_error = ""
    for attempt in range(2):
        ask = prompt if attempt == 0 else (
            f"{prompt}\n\nYour previous answer was rejected: {last_error}\n"
            "Answer again, fixing exactly that."
        )
        try:
            raw = llm.complete_json(SYSTEM, ask, schema)
            return _parse(raw)
        except LLMError as exc:
            raise AuthorError(f"model unavailable: {exc}") from exc
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)[:600]
    raise AuthorError(f"journeys rejected twice; last reason: {last_error}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_author.py -q`
Expected: 4 passed. Note the `match="3"` and `match="8"` assertions rely on the numbers appearing in the error text via the f-string in `_parse`.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q`

---

### Task 4: Snapshot — the page as the walker sees it

**Files:**
- Create: `spikes/journeys/snapshot.py`
- Test: `spikes/journeys/tests/test_snapshot.py`

**Interfaces:**
- Consumes: a Playwright `Page`.
- Produces: `trimmed_snapshot(page, cap: int = SNAPSHOT_CAP) -> str`, `visible_text(page) -> str`, `SNAPSHOT_CAP = 12_000`, `INTERACTIVE_ROLES`.

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_snapshot.py
from collections.abc import Iterator

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright

from spikes.journeys.snapshot import SNAPSHOT_CAP, trimmed_snapshot, visible_text

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


def test_snapshot_lists_controls_by_role_and_name(page):
    page.set_content("<h1>Shop</h1><button>Add to cart</button><a href='/x'>Orders</a>"
                     "<label>Product <select><option>widget</option></select></label>")
    snap = trimmed_snapshot(page)
    assert 'button "Add to cart"' in snap
    assert 'link "Orders"' in snap
    assert "combobox" in snap
    assert "[snapshot truncated" not in snap


def test_snapshot_keeps_interactive_lines_when_capped(page):
    filler = "".join(f"<p>paragraph number {i} with some words in it</p>" for i in range(400))
    page.set_content(f"{filler}<button>Run</button>")
    snap = trimmed_snapshot(page, cap=600)
    assert 'button "Run"' in snap
    assert len(snap) <= 600 + 80
    assert "[snapshot truncated" in snap


def test_visible_text_is_body_inner_text(page):
    page.set_content("<p>Something went wrong</p><script>var x=1</script>")
    assert visible_text(page).strip() == "Something went wrong"


def test_cap_constant():
    assert SNAPSHOT_CAP == 12_000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_snapshot.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/snapshot.py
"""The accessibility tree, trimmed to what a walker can act on.

`aria_snapshot()` is a YAML-ish outline: one line per node, `- role "name"`. Under the
cap, interactive nodes are kept first because they are what the next action names; the
truncation is stated in the snapshot itself so the model, and a reader of the log, know
the page had more than they saw.
"""
from __future__ import annotations

from playwright.sync_api import Page

SNAPSHOT_CAP = 12_000
INTERACTIVE_ROLES = (
    "button", "link", "textbox", "combobox", "checkbox", "radio", "menuitem", "tab",
    "option", "switch", "slider", "searchbox", "spinbutton", "heading", "dialog", "alert",
)


def _interactive(line: str) -> bool:
    stripped = line.lstrip("- ").lstrip()
    return stripped.startswith(INTERACTIVE_ROLES)


def trimmed_snapshot(page: Page, cap: int = SNAPSHOT_CAP) -> str:
    raw = page.locator("body").aria_snapshot()
    if len(raw) <= cap:
        return raw
    lines = raw.splitlines()
    kept: list[str] = []
    size = 0
    for line in [ln for ln in lines if _interactive(ln)] + [ln for ln in lines if not _interactive(ln)]:
        if size + len(line) + 1 > cap:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept) + f"\n[snapshot truncated: kept {len(kept)} of {len(lines)} lines]"


def visible_text(page: Page) -> str:
    return page.evaluate("() => document.body ? document.body.innerText : ''")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_snapshot.py -q`
Expected: 4 passed. If the role/name quoting differs from `button "Add to cart"`, print `snap` once and adjust only the assertions' quoting — never the snapshot content.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q`

---

### Task 5: Walker — one journey, one action at a time

**Files:**
- Create: `spikes/journeys/walker.py`
- Test: `spikes/journeys/tests/test_walker.py`

**Interfaces:**
- Consumes: `BrowserDriver.execute(Action) -> Observation` (`qabot.drivers.base.Action(kind="browser", params={...})`, `Observation(ok, summary, evidence)`), `qabot.drivers.browser.OPS`, `qabot.intrinsics.intrinsic_findings(workflow, {index: observation})`, `qabot.models.Workflow(id, name, steps=[Step(intent=...)])`, `trimmed_snapshot`, `visible_text`, models from Task 1.
- Produces: `walk(journey: Journey, driver, page, llm, artifacts: Path) -> JourneyResult`, constants `MAX_ACTIONS_PER_STEP = 6`, `WALK_SYSTEM`, `JUDGE_SYSTEM`, and `page_checks(text: str) -> list[str]` (the error-screen / white-screen detail lines).

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_walker.py
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright

from demo.app import create_app
from demo.server import serve
from qabot.drivers.browser import BrowserDriver
from qabot.models import Outcome, Severity
from spikes.journeys.fakes import FakeLLM
from spikes.journeys.models import Journey, JourneyStep, StepOutcome
from spikes.journeys.walker import MAX_ACTIONS_PER_STEP, page_checks, walk

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def shop_url() -> Iterator[str]:
    with serve(create_app()) as url:
        yield url


@pytest.fixture(scope="module")
def page() -> Iterator[Page]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser.new_page()
        browser.close()


@pytest.fixture
def driver(shop_url: str, page: Page) -> BrowserDriver:
    d = BrowserDriver(base_url=shop_url, page=page, timeout_ms=3000, reset_path=None)
    d.reset()
    return d


def _journey() -> Journey:
    return Journey(id="j1", title="Add a widget", persona="a shopper", steps=[
        JourneyStep(do="Open the shop", see="a Product picker and an Add to cart button"),
        JourneyStep(do="Pick 'widget' and add it to the cart", see="the cart lists widget"),
    ])


def test_walk_completes_a_journey_from_scripted_decisions(driver, page, tmp_path):
    llm = FakeLLM([
        {"op": "goto", "path": "/ui"},
        {"op": "done"},
        {"verdict": "held", "reason": "picker and button are on screen"},
        {"op": "select", "role": "combobox", "name": "Product", "value": "widget"},
        {"op": "click", "role": "button", "name": "Add to cart"},
        {"op": "done"},
        {"verdict": "held", "reason": "cart shows widget"},
    ])
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.PASS
    assert [s.outcome for s in result.steps] == [StepOutcome.HELD, StepOutcome.HELD]
    assert [a.op for a in result.steps[1].actions] == ["select", "click"]
    assert result.steps[1].screenshot and Path(result.steps[1].screenshot).exists()
    assert "Add to cart" in llm.calls[3]["prompt"]  # the snapshot reached the model


def test_walk_marks_failed_when_see_does_not_hold(driver, page, tmp_path):
    llm = FakeLLM([
        {"op": "goto", "path": "/ui"},
        {"op": "done"},
        {"verdict": "failed", "reason": "no picker on screen"},
    ])
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.FAIL
    assert result.steps[0].outcome == StepOutcome.FAILED
    assert result.steps[1].outcome == StepOutcome.NOT_REACHED
    inferred = [f for f in result.steps[0].findings if f.oracle is None]
    assert inferred and inferred[0].severity == Severity.QUESTION


def test_walk_blocks_after_the_action_cap(driver, page, tmp_path):
    llm = FakeLLM([{"op": "goto", "path": "/ui"}] * MAX_ACTIONS_PER_STEP)
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.BLOCKED
    assert result.steps[0].outcome == StepOutcome.BLOCKED
    assert str(MAX_ACTIONS_PER_STEP) in result.steps[0].reason


def test_walk_honours_blocked_from_the_model(driver, page, tmp_path):
    llm = FakeLLM([{"op": "blocked", "reason": "no such control"}])
    result = walk(_journey(), driver, page, llm, tmp_path)
    assert result.outcome == Outcome.BLOCKED
    assert "no such control" in result.steps[0].reason


def test_page_checks_name_error_and_white_screens():
    assert page_checks("Something went wrong. The application encountered an unexpected error.")
    assert page_checks("") == ["the page is blank: no visible text"]
    assert page_checks("Welcome to the shop") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_walker.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/walker.py
"""Walk one journey: for each step, act until the model says the step is done, then judge
whether what the step said would be seen is on screen.

Two kinds of finding come out and stay apart. App-declared ones (a 5xx, an uncaught
error, the app's own error screen) come from `qabot.intrinsics` and `page_checks` and
keep their severity. A `see` the judge calls failed is an inference and is filed at
QUESTION; the walker never upgrades it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from qabot.drivers.base import Action, Observation
from qabot.drivers.browser import OPS
from qabot.intrinsics import intrinsic_findings
from qabot.models import Finding, Outcome, Provenance, Severity, Step, Workflow
from spikes.journeys.models import (
    ActionRecord, Journey, JourneyResult, StepOutcome, StepResult,
)
from spikes.journeys.snapshot import trimmed_snapshot, visible_text

MAX_ACTIONS_PER_STEP = 6

WALK_SYSTEM = (
    "You operate a web application through a browser to carry out one step of a user "
    "journey. You see the page as an accessibility outline (role \"name\"). Choose ONE next "
    "action, in exactly this vocabulary:\n"
    '{"op":"goto","path":"/..."} | {"op":"click","role":"button","name":"..."} | '
    '{"op":"fill","role":"textbox","name":"...","value":"..."} | '
    '{"op":"select","role":"combobox","name":"...","value":"..."} | '
    '{"op":"done"} when the step\'s action is complete and its expected result should be on '
    'screen | {"op":"blocked","reason":"..."} when no control on the page can do this step.\n'
    "Use role and name exactly as the outline shows them. Never submit a form the step did "
    "not ask for. Never invent a control that is not in the outline. Answer with ONLY the "
    "JSON object."
)

JUDGE_SYSTEM = (
    "You judge whether a user journey step's expected result is on screen. You get the "
    "expectation and the page's visible text and outline. Answer ONLY "
    '{"verdict":"held"|"failed"|"unclear","reason":"<=25 words"}. "held" only if the '
    "expectation is plainly satisfied; \"failed\" only if the screen plainly contradicts it; "
    "otherwise \"unclear\"."
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
    hits = []
    for pat in _ERROR_SCREEN:
        m = re.search(pat, norm, re.I)
        if m:
            hits.append(f"the page shows its own error text: …{norm[max(0, m.start()-40):m.end()+80]}…")
            break
    return hits


def _decide(llm, journey: Journey, step_index: int, page, history: list[str]) -> dict:
    step = journey.steps[step_index]
    prompt = (
        f"Journey: {journey.title}\nStep {step_index + 1}: DO: {step.do}\nEXPECT TO SEE: {step.see}\n"
        f"Current URL: {page.url}\nLast actions: {json.dumps(history[-3:])}\n\n"
        f"Page outline:\n{trimmed_snapshot(page)}"
    )
    return llm.complete_json(WALK_SYSTEM, prompt, {"op": ""})


def _judge(llm, step_see: str, page) -> dict:
    prompt = (
        f"Expected to see: {step_see}\n\nVisible text:\n{visible_text(page)[:6000]}\n\n"
        f"Outline:\n{trimmed_snapshot(page, cap=6000)}"
    )
    return llm.complete_json(JUDGE_SYSTEM, prompt, {"verdict": "", "reason": ""})


def _to_action(decision: dict) -> Action | None:
    op = decision.get("op")
    if op not in OPS:
        return None
    params = {k: v for k, v in decision.items() if k in ("op", "path", "role", "name", "value")}
    return Action(kind="browser", params=params)


def _declared_findings(journey: Journey, do: str, obs: Observation, page) -> list[Finding]:
    wf = Workflow(id=journey.id, name=journey.title, steps=[Step(intent=do)])
    found = intrinsic_findings(wf, {0: obs})
    for detail in page_checks(visible_text(page)):
        found.append(Finding(
            workflow_id=journey.id, workflow_name=journey.title, severity=Severity.BUG,
            outcome=Outcome.FAIL, statement="the page rendered an error state", detail=detail,
            provenance=None, oracle="page_error_screen", repro=[do], evidence={"url": page.url},
        ))
    return found


def _inferred_finding(journey: Journey, step_see: str, reason: str) -> Finding:
    return Finding(
        workflow_id=journey.id, workflow_name=journey.title, severity=Severity.QUESTION,
        outcome=Outcome.FAIL, statement=f"expected to see: {step_see}", detail=reason,
        provenance=Provenance.INFERRED_FROM_CODE, oracle=None, repro=[], evidence={},
    )


def walk(journey: Journey, driver, page, llm, artifacts: Path) -> JourneyResult:
    artifacts = Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    results: list[StepResult] = []
    outcome = Outcome.PASS
    why = ""
    for index, step in enumerate(journey.steps):
        if outcome is not Outcome.PASS:
            results.append(StepResult(index=index, do=step.do, see=step.see,
                                      outcome=StepOutcome.NOT_REACHED))
            continue
        actions: list[ActionRecord] = []
        findings: list[Finding] = []
        history: list[str] = []
        step_outcome = StepOutcome.BLOCKED
        reason = f"could not complete in {MAX_ACTIONS_PER_STEP} actions"
        for _ in range(MAX_ACTIONS_PER_STEP):
            decision = _decide(llm, journey, index, page, history)
            if decision.get("op") == "done":
                verdict = _judge(llm, step.see, page)
                v = verdict.get("verdict")
                reason = str(verdict.get("reason", ""))
                if v == "held":
                    step_outcome = StepOutcome.HELD
                elif v == "failed":
                    step_outcome = StepOutcome.FAILED
                    findings.append(_inferred_finding(journey, step.see, reason))
                else:
                    step_outcome = StepOutcome.BLOCKED
                    reason = f"could not tell whether it held: {reason}"
                break
            if decision.get("op") == "blocked":
                reason = str(decision.get("reason", "the model could not find a way"))
                break
            action = _to_action(decision)
            if action is None:
                reason = f"model returned an unusable action: {decision!r}"
                break
            obs = driver.execute(action)
            shot = obs.evidence.get("screenshot")
            actions.append(ActionRecord(op=str(action.params["op"]), params=dict(action.params),
                                        ok=obs.ok, summary=obs.summary,
                                        screenshot=str(shot) if shot else None))
            history.append(obs.summary)
            findings.extend(_declared_findings(journey, step.do, obs, page))
        shot = actions[-1].screenshot if actions else None
        results.append(StepResult(index=index, do=step.do, see=step.see, outcome=step_outcome,
                                  reason=reason, actions=actions, findings=findings,
                                  screenshot=shot))
        declared = [f for f in findings if f.oracle is not None and f.severity is Severity.BUG]
        if step_outcome is StepOutcome.FAILED or declared:
            outcome = Outcome.FAIL
            why = reason if step_outcome is StepOutcome.FAILED else declared[0].detail
        elif step_outcome is StepOutcome.BLOCKED:
            outcome = Outcome.BLOCKED
            why = reason
    return JourneyResult(journey=journey, outcome=outcome, steps=results, why=why)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_walker.py -q`
Expected: 5 passed. If `test_walk_completes_a_journey_from_scripted_decisions` fails on `Add to cart in llm.calls[3]`, the index is the fourth call (goto, done, judge, then the select decision); count calls from `llm.calls` and fix the index in the test only if the sequence differs from the plan.

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q`

---

### Task 6: Report — the page a person follows

**Files:**
- Create: `spikes/journeys/report.py`
- Test: `spikes/journeys/tests/test_report.py`

**Interfaces:**
- Consumes: `JourneyResult`, `Evidence` (optional header), models from Task 1.
- Produces: `render(results: list[JourneyResult], evidence: Evidence | None = None, caps: dict | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# spikes/journeys/tests/test_report.py
from qabot.models import Finding, Outcome, Severity
from spikes.journeys.models import (
    ActionRecord, Journey, JourneyResult, JourneyStep, StepOutcome, StepResult,
)
from spikes.journeys.report import render


def _result(outcome, step_outcomes, findings=()):
    j = Journey(id="j1", title="Run the starter flow", persona="a first-time user",
                preconditions={"settings": {"LANGFLOW_ALLOW_CUSTOM_COMPONENTS": "false"},
                               "state": []},
                steps=[JourneyStep(do="Open the Basic Prompting starter", see="the canvas"),
                       JourneyStep(do="Click Run", see="a reply appears")])
    steps = [StepResult(index=i, do=s.do, see=s.see, outcome=o, reason="r" if o != "held" else "",
                        actions=[ActionRecord(op="click", ok=True, summary="clicked",
                                              screenshot="shots/step_001.png")],
                        findings=list(findings) if i == 1 else [], screenshot="shots/step_001.png")
             for i, (s, o) in enumerate(zip(j.steps, step_outcomes, strict=True))]
    return JourneyResult(journey=j, outcome=outcome, steps=steps, why="r" if outcome != "pass" else "")


def test_render_has_summary_steps_and_marks():
    md = render([_result(Outcome.PASS, [StepOutcome.HELD, StepOutcome.HELD])])
    assert "| Run the starter flow | PASS |" in md
    assert "1. ✓ **Open the Basic Prompting starter** — see: the canvas" in md
    assert "shots/step_001.png" in md
    assert "LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false" in md


def test_render_keeps_declared_and_inferred_findings_apart():
    declared = Finding(workflow_id="j1", workflow_name="t", severity=Severity.BUG,
                       outcome=Outcome.FAIL, statement="the page rendered an error state",
                       detail="Flow build blocked", oracle="page_error_screen")
    inferred = Finding(workflow_id="j1", workflow_name="t", severity=Severity.QUESTION,
                       outcome=Outcome.FAIL, statement="expected to see: a reply",
                       detail="no reply", oracle=None)
    md = render([_result(Outcome.FAIL, [StepOutcome.HELD, StepOutcome.FAILED],
                         findings=[declared, inferred])])
    assert md.index("The app said (BUG)") < md.index("We inferred (QUESTION)")
    assert "Flow build blocked" in md and "no reply" in md


def test_render_lists_what_it_could_not_check():
    md = render([_result(Outcome.BLOCKED, [StepOutcome.BLOCKED, StepOutcome.NOT_REACHED])])
    assert "## What this run could not check" in md
    assert "○" in md and "–" in md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest spikes/journeys/tests/test_report.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/report.py
"""Markdown a tester can follow. Every step keeps its `do` and `see`, so the report is
also the journey, re-runnable by hand."""
from __future__ import annotations

from qabot.models import Severity
from spikes.journeys.evidence import Evidence
from spikes.journeys.models import JourneyResult, StepOutcome

_MARK = {StepOutcome.HELD: "✓", StepOutcome.FAILED: "✗", StepOutcome.BLOCKED: "–",
         StepOutcome.NOT_REACHED: "○"}


def render(results: list[JourneyResult], evidence: Evidence | None = None,
           caps: dict | None = None) -> str:
    out: list[str] = ["# User journeys — walked", ""]
    if evidence is not None:
        out += [f"Change: `{evidence.base}..{evidence.head}`"
                + (" (diff truncated)" if evidence.diff_truncated else ""),
                f"Settings touched: {', '.join(evidence.settings_names) or 'none'}", ""]
    if caps:
        out += ["Caps: " + ", ".join(f"{k}={v}" for k, v in caps.items()), ""]
    out += ["| Journey | Outcome |", "|---|---|"]
    out += [f"| {r.journey.title} | {r.outcome.value.upper()} |" for r in results]
    out.append("")
    for r in results:
        j = r.journey
        out += [f"## {j.title}", "", f"*{j.persona}*", ""]
        if j.preconditions.settings or j.preconditions.state:
            pre = [f"{k}={v}" for k, v in j.preconditions.settings.items()] + j.preconditions.state
            out += ["Preconditions: " + "; ".join(pre), ""]
        if j.traces_to:
            out += [f"Traces to: {j.traces_to}", ""]
        for s in r.steps:
            line = f"{s.index + 1}. {_MARK[s.outcome]} **{s.do}** — see: {s.see}"
            if s.reason and s.outcome is not StepOutcome.HELD:
                line += f"  \n   {s.outcome.value}: {s.reason}"
            if s.screenshot:
                line += f"  \n   screenshot: `{s.screenshot}`"
            out.append(line)
            declared = [f for f in s.findings if f.oracle is not None]
            inferred = [f for f in s.findings if f.oracle is None]
            if declared:
                out.append("   - The app said (BUG): " + "; ".join(f.detail for f in declared
                           if f.severity is Severity.BUG) or "")
            if inferred:
                out.append("   - We inferred (QUESTION): " + "; ".join(f.detail for f in inferred))
        out += ["", f"**Outcome: {r.outcome.value.upper()}**" + (f" — {r.why}" if r.why else ""), ""]
    blocked = [(r.journey.title, s) for r in results for s in r.steps
               if s.outcome in (StepOutcome.BLOCKED, StepOutcome.NOT_REACHED)]
    out += ["## What this run could not check", ""]
    if not blocked:
        out.append("Every step of every journey was walked and judged.")
    for title, s in blocked:
        out.append(f"- {title}, step {s.index + 1} ({_MARK[s.outcome]} {s.outcome.value}): "
                   f"{s.reason or 'an earlier step did not hold'}")
    return "\n".join(out) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest spikes/journeys/tests/test_report.py -q`
Expected: 3 passed

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q`

---

### Task 7: The command

**Files:**
- Create: `spikes/journeys/run.py`
- Test: `spikes/journeys/tests/test_run.py`

**Interfaces:**
- Consumes: everything above, `qabot.llm.ClaudeCliLLM`, `qabot.drivers.browser.BrowserDriver`, Playwright.
- Produces: `main(argv) -> int`; env `JOURNEYS_LLM=fake:<json file>` selects `FakeLLM` from a JSON list of responses (tests only); outputs `journeys.json`, `results.json`, `report.md`, `evidence.json`, `shots/` under `--out`.

- [ ] **Step 1: Write the failing test**

```python
# spikes/journeys/tests/test_run.py
import json
import subprocess
from pathlib import Path

from spikes.journeys.run import main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "app"; repo.mkdir()
    _git(repo, "init", "-q"); _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n"); _git(repo, "add", "."); _git(repo, "commit", "-qm", "base")
    (repo / "a.py").write_text("x = 2  # LANGFLOW_FLAG\n"); _git(repo, "commit", "-qam", "head")
    return repo


def test_author_only_writes_journeys_and_evidence(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    journeys = [{"id": f"j{i}", "title": f"t{i}", "persona": "p",
                 "steps": [{"do": "open", "see": "home"}], "traces_to": "a.py"} for i in range(1, 4)]
    fake = tmp_path / "fake.json"; fake.write_text(json.dumps([{"journeys": journeys}]))
    monkeypatch.setenv("JOURNEYS_LLM", f"fake:{fake}")
    out = tmp_path / "out"
    code = main(["--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD",
                 "--out", str(out), "--author-only"])
    assert code == 0
    written = json.loads((out / "journeys.json").read_text())
    assert [j["id"] for j in written] == ["j1", "j2", "j3"]
    ev = json.loads((out / "evidence.json").read_text())
    assert ev["settings_names"] == ["LANGFLOW_FLAG"]
    assert not (out / "results.json").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest spikes/journeys/tests/test_run.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# spikes/journeys/run.py
"""Author journeys from a change, then walk them against a running instance.

    uv run python -m spikes.journeys.run --repo PATH --base REF --head REF \
        --url http://127.0.0.1:7860 --out runs/journeys/fixed [--pr-text FILE] \
        [--author-only] [--journeys FILE] [--headed]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from spikes.journeys.author import author
from spikes.journeys.evidence import DIFF_CAP, gather
from spikes.journeys.models import Journey
from spikes.journeys.report import render
from spikes.journeys.snapshot import SNAPSHOT_CAP
from spikes.journeys.walker import MAX_ACTIONS_PER_STEP, walk


def _llm():
    spec = os.environ.get("JOURNEYS_LLM", "")
    if spec.startswith("fake:"):
        from spikes.journeys.fakes import FakeLLM
        return FakeLLM(json.loads(Path(spec[5:]).read_text()))
    from qabot.llm import ClaudeCliLLM
    return ClaudeCliLLM(timeout=180.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="journeys")
    p.add_argument("--repo", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--url")
    p.add_argument("--pr-text")
    p.add_argument("--journeys", help="reuse authored journeys from this file")
    p.add_argument("--author-only", action="store_true")
    p.add_argument("--headed", action="store_true")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = _llm()

    description = Path(args.pr_text).read_text() if args.pr_text else ""
    evidence = gather(Path(args.repo), args.base, args.head, description)
    (out / "evidence.json").write_text(evidence.model_dump_json(indent=1))
    if args.journeys:
        journeys = [Journey.model_validate(j) for j in json.loads(Path(args.journeys).read_text())]
    else:
        journeys = author(evidence, llm)
    (out / "journeys.json").write_text(
        json.dumps([j.model_dump() for j in journeys], indent=1, ensure_ascii=False))
    print(f"{len(journeys)} journeys -> {out / 'journeys.json'}", file=sys.stderr)
    if args.author_only:
        return 0
    if not args.url:
        print("--url is required to walk journeys", file=sys.stderr)
        return 2

    from playwright.sync_api import sync_playwright
    from qabot.drivers.browser import BrowserDriver

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        for journey in journeys:
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            driver = BrowserDriver(base_url=args.url, page=page,
                                   artifacts_dir=out / "shots" / journey.id,
                                   timeout_ms=15000.0, reset_path=None)
            try:
                results.append(walk(journey, driver, page, llm, out / "shots" / journey.id))
            finally:
                page.context.close()
            print(f"{journey.id} {results[-1].outcome.value}: {journey.title}", file=sys.stderr)
        browser.close()
    caps = {"snapshot_chars": SNAPSHOT_CAP, "diff_chars": DIFF_CAP,
            "actions_per_step": MAX_ACTIONS_PER_STEP}
    (out / "results.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in results], indent=1, ensure_ascii=False))
    (out / "report.md").write_text(render(results, evidence, caps))
    print(f"report -> {out / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest spikes/journeys/tests/test_run.py -q`
Expected: 1 passed

- [ ] **Step 5: Checkpoint (no commit)**

Run: `uv run ruff check spikes && uv run ruff format --check spikes && awk 'length > 100 {print FILENAME": "FNR}' spikes/journeys/*.py && uv run pytest spikes/journeys/tests -q && uv run pytest -q -m "not browser"`
Expected: all spike tests pass; the existing suite is unchanged (527 passed, 1 skipped, minus deselected browser tests).

---

### Task 8: The Langflow measurement (runbook, no new code)

**Files:**
- Create: `qa-artifacts/journeys-2026-09-05/pr-14913.md` (the PR title + body, from `gh pr view 14913 --repo langflow-ai/langflow --json title,body`)
- Outputs under `qa-artifacts/journeys-2026-09-05/{fixed,broken}/`

Prerequisites (already running from this session; check the logs):
- `/Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow` at `84a3649` (fixed); `../install_fixed.log` ends with a successful frontend build into `src/backend/base/langflow/frontend`.
- `/Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow-broken` worktree at `84a3649^`; `../install_broken.log` ends with a successful `uv sync`.

- [ ] **Step 1: Start the fixed instance (port 7860), with the condition the change protects**

```bash
cd /Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow
LANGFLOW_CONFIG_DIR=/tmp/lf-fixed LANGFLOW_DATABASE_URL=sqlite:////tmp/lf-fixed/langflow.db \
LANGFLOW_LAZY_LOAD_COMPONENTS=true LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false LANGFLOW_AUTO_LOGIN=true \
nohup uv run langflow run --host 127.0.0.1 --port 7860 --log-level info \
  --frontend-path src/backend/base/langflow/frontend > /tmp/lf-fixed.log 2>&1 &
until curl -sf http://127.0.0.1:7860/health >/dev/null; do sleep 3; done; echo fixed up
```

- [ ] **Step 2: Start the broken instance (port 7861), same frontend build, same settings**

```bash
cd /Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow-broken
LANGFLOW_CONFIG_DIR=/tmp/lf-broken LANGFLOW_DATABASE_URL=sqlite:////tmp/lf-broken/langflow.db \
LANGFLOW_LAZY_LOAD_COMPONENTS=true LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false LANGFLOW_AUTO_LOGIN=true \
nohup uv run langflow run --host 127.0.0.1 --port 7861 --log-level info \
  --frontend-path ../langflow/src/backend/base/langflow/frontend > /tmp/lf-broken.log 2>&1 &
until curl -sf http://127.0.0.1:7861/health >/dev/null; do sleep 3; done; echo broken up
```

- [ ] **Step 3: Author the journeys once, from the fixed checkout, and stop**

```bash
cd /Users/jordan.frazier/Documents/frazier_projects/quabity-assuance
gh pr view 14913 --repo langflow-ai/langflow --json title,body --jq '"# " + .title + "\n\n" + .body' \
  > qa-artifacts/journeys-2026-09-05/pr-14913.md
QABOT_LLM=claude-cli uv run python -m spikes.journeys.run \
  --repo /Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow \
  --base 84a3649^ --head 84a3649 --pr-text qa-artifacts/journeys-2026-09-05/pr-14913.md \
  --out qa-artifacts/journeys-2026-09-05/authored --author-only
```
Read `authored/journeys.json`. Record, before walking: does journey 1 run a starter flow; does any journey name `LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false` and `LANGFLOW_LAZY_LOAD_COMPONENTS=true` in its preconditions; does every step name a control a Langflow user would recognise. Hand the file to Jordan for reading — this is the first deliverable.

- [ ] **Step 4: Walk the same journeys on both instances**

```bash
for which in fixed:7860 broken:7861; do
  name=${which%%:*}; port=${which##*:}
  uv run python -m spikes.journeys.run \
    --repo /Users/jordan.frazier/Documents/frazier_projects/qa-targets/langflow \
    --base 84a3649^ --head 84a3649 --journeys qa-artifacts/journeys-2026-09-05/authored/journeys.json \
    --url http://127.0.0.1:$port --out qa-artifacts/journeys-2026-09-05/$name
done
```

- [ ] **Step 5: Adjudicate and record**

For each journey on each instance, open the screenshots named in `report.md`. Score:
- fixed: every FAIL is a false positive (name its mechanism); every BLOCKED is a walker limitation (name the control it could not find).
- broken: the run-flow journey must FAIL with the app's own text ("custom components are not allowed" or the build-blocked banner) in "The app said (BUG)"; if it FAILs only under "We inferred (QUESTION)", the regression was caught by inference alone — record that distinction.
Append a section "User journeys on Langflow PR #14913" to `docs/EVAL.md` with: journeys authored (count, precondition named yes/no), steps walked / attempted per instance, outcomes per journey per instance, false positives on fixed, whether broken was caught and by which tier, and Jordan's reading of the journeys. Do not commit.

- [ ] **Step 6: Stop the instances**

```bash
pkill -f "langflow run --host 127.0.0.1 --port 786" || true
```

---

## Self-review notes

- Spec coverage: evidence (T2), author (T3), walker incl. snapshot and both finding tiers (T4, T5), report (T6), command incl. `--author-only` and `--journeys` reuse (T7), the measurement with its five questions (T8). Caps recorded in outputs (T7 `caps`, T2 `diff_truncated`, T4 truncation line).
- Type consistency: `walk(journey, driver, page, llm, artifacts)` is used identically in T5 tests and T7; `render(results, evidence, caps)` in T6 and T7; `gather(repo, base, head, description)` in T2, T7; `FakeLLM(list[dict])` in T1, T3, T5, T7.
- The `Finding` constructor in T5 passes `repro` and `evidence`; both exist on `qabot.models.Finding` (see `qabot/intrinsics.py::_finding`).
