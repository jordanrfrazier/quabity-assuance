"""Anchors: the drift sensor.

The knowledge base is hosted, not committed next to the customer's code, so nothing
in their repo forces it to stay honest. Anchors are the counterweight. Every
workflow carries links back to concrete code -- a route, a symbol, a file -- and
every run re-resolves those links against the checkout under test. A link that no
longer resolves is neither a crash nor a silent pass: it demotes the workflow to
STALE, caps the confidence of what that workflow claims, and surfaces an
OpenQuestion naming the exact locator that broke. Without this, hosted knowledge
quietly rots as the customer refactors and the bot keeps reporting on a codebase
that no longer exists.

Resolution is AST-based on purpose. A regex over source text happily matches a
route inside a comment, a docstring, or a string literal and reports the workflow
healthy. The dangerous failure direction for a drift sensor is a false *resolve*,
so we parse. Regex is a fallback only for sources Python's `ast` cannot read.
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

from qabot.models import (
    Anchor,
    AnchorKind,
    KnowledgeBase,
    OpenQuestion,
    Workflow,
    WorkflowStatus,
)

#: Directories that are never part of the customer's source of truth.
SKIP_DIRS: frozenset[str] = frozenset({".venv", ".git", "__pycache__"})

#: Decorator attribute names that declare an HTTP route (`@app.post(...)`).
HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)

#: A stale workflow's expectations may not claim more confidence than this. Applied
#: with min() so repeated staleness passes are idempotent rather than compounding.
STALE_CONFIDENCE_CAP: float = 0.5


class AnchorError(RuntimeError):
    """Raised when an anchor or a source tree cannot be interpreted at all.

    Distinct from an anchor that simply does not resolve: that is drift and is
    reported, not raised.
    """


def normalize_route(locator: str) -> str:
    """`" post  /cart/items/ "` -> `"POST /cart/items"`.

    Raises AnchorError on anything that is not `METHOD /path`, because a route
    anchor we cannot even parse would otherwise be silently un-resolvable forever.
    """
    parts = locator.split()
    if len(parts) != 2:
        raise AnchorError(f"route locator must be 'METHOD /path', got {locator!r}")
    method, path = parts
    if method.lower() not in HTTP_METHODS:
        raise AnchorError(f"unknown HTTP method {method!r} in route locator {locator!r}")
    if not path.startswith("/"):
        raise AnchorError(f"route path must start with '/', got {locator!r}")
    return f"{method.upper()} {normalize_path_segment(path)}"


def normalize_path_segment(path: str) -> str:
    """Trailing slashes are not meaningful for route identity; `/` stays `/`."""
    stripped = path.rstrip("/")
    return stripped or "/"


def normalize_source_path(path: str) -> str:
    """Repo-relative, POSIX, no `./` prefix -- the single key shape for file lookups."""
    return Path(path.strip()).as_posix().removeprefix("./")


def split_symbol_locator(locator: str) -> tuple[str | None, str]:
    """`"demo/app.py::checkout_submit"` -> `("demo/app.py", "checkout_submit")`.

    A bare `"checkout_submit"` -> `(None, "checkout_submit")`, meaning "defined
    anywhere in the tree".
    """
    text = locator.strip()
    if not text:
        raise AnchorError("symbol locator is empty")
    if "::" not in text:
        return None, text
    file_part, _, name_part = text.partition("::")
    if not file_part or not name_part:
        raise AnchorError(f"symbol locator must be 'path::name' or 'name', got {locator!r}")
    return normalize_source_path(file_part), name_part.strip()


@dataclass(frozen=True)
class SourceIndex:
    """One walk of the source tree, reused by every anchor in a run.

    Built once per public call so that a knowledge base with hundreds of anchors
    does not re-walk the customer's repo hundreds of times.
    """

    root: Path
    routes: frozenset[str]
    symbols_by_file: dict[str, frozenset[str]]
    all_symbols: frozenset[str]

    def defines(self, file_path: str | None, name: str) -> bool:
        if file_path is None:
            return name in self.all_symbols
        return name in self.symbols_by_file.get(file_path, frozenset())

    def path_exists(self, locator: str) -> bool:
        return (self.root / normalize_source_path(locator)).exists()


def iter_source_files(source_root: Path) -> list[Path]:
    """Every `.py` file under `source_root`, excluding SKIP_DIRS, in sorted order."""
    root = Path(source_root)
    if not root.is_dir():
        raise AnchorError(f"source root is not a directory: {root}")
    return sorted(
        p
        for p in root.rglob("*.py")
        if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts)
    )


def route_decorators(node: ast.AST) -> list[str]:
    """Normalized routes declared by a decorated def, e.g. `["POST /cart/items"]`.

    Matches the `@app.post("/x")` / `@router.post("/x")` shape: an attribute call
    whose attribute is an HTTP method and whose first positional argument is a
    string literal.
    """
    decorators = getattr(node, "decorator_list", [])
    found: list[str] = []
    for dec in decorators:
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        method = dec.func.attr.lower()
        if method not in HTTP_METHODS or not dec.args:
            continue
        first = dec.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append(f"{method.upper()} {normalize_path_segment(first.value)}")
    return found


def build_index(source_root: Path) -> SourceIndex:
    """Walk the tree once and record what it defines: routes and symbol names.

    A file that does not parse raises rather than being skipped. A skipped file is
    an invisible hole in the drift sensor -- anchors into it would resolve as
    "missing" and be reported as drift that is really a parser problem.
    """
    root = Path(source_root)
    routes: set[str] = set()
    symbols_by_file: dict[str, frozenset[str]] = {}
    all_symbols: set[str] = set()

    for path in iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AnchorError(f"cannot parse source file {rel}: {exc}") from exc
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.add(node.name)
                routes.update(route_decorators(node))
        symbols_by_file[rel] = frozenset(names)
        all_symbols |= names

    return SourceIndex(
        root=root,
        routes=frozenset(routes),
        symbols_by_file=symbols_by_file,
        all_symbols=frozenset(all_symbols),
    )


def resolve_against_index(anchor: Anchor, index: SourceIndex) -> bool:
    """The resolution rules themselves, against an already-built index."""
    match anchor.kind:
        case AnchorKind.ROUTE:
            return normalize_route(anchor.locator) in index.routes
        case AnchorKind.SYMBOL:
            file_path, name = split_symbol_locator(anchor.locator)
            if file_path is not None and not (index.root / file_path).is_file():
                return False
            return index.defines(file_path, name)
        case AnchorKind.FILE | AnchorKind.COMPONENT:
            return index.path_exists(anchor.locator)
    raise AnchorError(f"unhandled anchor kind: {anchor.kind!r}")


def resolve_anchor(anchor: Anchor, source_root: Path) -> bool:
    """Does this anchor still point at real code? Does not mutate the anchor."""
    return resolve_against_index(anchor, build_index(source_root))


def resolve_workflow(workflow: Workflow, source_root: Path) -> list[Anchor]:
    """Re-resolve every anchor on `workflow`, returning the ones that failed.

    Mutates `Anchor.resolved` in place: the anchor object is the record of what the
    last run found, and the reporter reads it.
    """
    return resolve_workflow_against(workflow, build_index(source_root))


def resolve_workflow_against(workflow: Workflow, index: SourceIndex) -> list[Anchor]:
    unresolved: list[Anchor] = []
    for anchor in workflow.anchors:
        anchor.resolved = resolve_against_index(anchor, index)
        if not anchor.resolved:
            unresolved.append(anchor)
    return unresolved


def staleness_question_id(workflow_id: str, locator: str) -> str:
    """Stable across processes and runs, so the curator can dedupe rather than
    accumulate one copy of the same question per CI run. `hash()` is salted per
    process and would defeat that, hence an explicit digest.
    """
    digest = hashlib.sha1(locator.encode("utf-8")).hexdigest()[:8]
    return f"oq-stale-{workflow_id}-{digest}"


def staleness_pass(kb: KnowledgeBase, source_root: Path) -> tuple[list[str], list[OpenQuestion]]:
    """Re-resolve the whole knowledge base against the checkout under test.

    Mutates `kb` in place -- anchors get their `resolved` flag, workflows with any
    broken anchor become STALE, and their expectations get their confidence capped,
    because a claim anchored to code that no longer exists has not earned its old
    confidence. Returns the stale workflow ids and one OpenQuestion per broken
    locator. The questions are *returned*, not appended to `kb.open_questions`: the
    runner emits, the async curator applies.

    RETIRED workflows are left entirely alone. Promoting one to STALE would make it
    selectable again by impact analysis, resurrecting work someone deliberately
    retired.
    """
    index = build_index(source_root)
    stale_ids: list[str] = []
    questions: list[OpenQuestion] = []

    for workflow in kb.workflows:
        if workflow.status == WorkflowStatus.RETIRED:
            continue
        unresolved = resolve_workflow_against(workflow, index)
        if not unresolved:
            continue
        workflow.status = WorkflowStatus.STALE
        stale_ids.append(workflow.id)
        for expectation in workflow.expectations:
            expectation.confidence = min(expectation.confidence, STALE_CONFIDENCE_CAP)
        for anchor in unresolved:
            questions.append(
                OpenQuestion(
                    id=staleness_question_id(workflow.id, anchor.locator),
                    question=(
                        f"Workflow {workflow.id} ({workflow.name!r}) anchors to "
                        f"{anchor.kind.value} {anchor.locator!r}, which no longer exists in "
                        f"the source tree. Was it renamed, moved, or removed?"
                    ),
                    trigger="staleness_pass",
                    blocking=False,
                    workflow_id=workflow.id,
                )
            )

    return stale_ids, questions
