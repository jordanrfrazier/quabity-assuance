"""Impact analysis: what this diff might have broken, and in what order to spend
the CI budget on it.

A run in CI is time-boxed, so the bot cannot exercise every workflow it knows
about. This module turns a unified diff into a ranked, deterministic selection:
parse the diff, map changed lines back to the symbols and routes that contain
them, and score each workflow by how directly its anchors were hit.

"Map changed lines back to routes" is the step that decides whether any of this
works on a real application. Read from source syntax it resolves one decorator idiom
and nothing else (see `routemap`), so every function here takes an optional
`RouteMap` -- the route table read from the running app -- and uses it in preference
to inference when the caller supplies one. Optional rather than required because the
bundled demo genuinely does not need it, and because a knowledge base full of symbol
and file anchors is still scored correctly without one.

Ranking is by a workflow's *strongest* evidence, never by how much evidence it
accumulated. Under a real CI budget those two rules select different workflows and
only one of them is defensible: measured on CTFd, additive scoring put the tests whose
entire subject is the rewritten handler at ranks 16-19, below workflows that call that
handler *and* two unrelated routes that merely live in the same file. Breadth of
coincidence outranked precision, so the tests most about the change were the ones that
did not run. `score_workflow` states the replacement rule and the invariant it keeps.

The rule that matters most here is the last one: nothing is silently dropped. A
workflow that scored but lost to the budget is returned as `skipped_for_budget` so
the reporter can say "these were at risk and were not tested". A truncated run
that looks like a clean run is the failure mode this module exists to prevent.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from qabot.anchors import (
    AnchorError,
    normalize_route,
    normalize_source_path,
    route_decorators,
    split_symbol_locator,
)
from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    KnowledgeBase,
    Workflow,
    WorkflowStatus,
)
from qabot.routemap import RouteMap

#: An anchor whose exact route or symbol was edited: the code answering this
#: workflow's request is the code that changed.
DIRECT_HIT_SCORE: float = 2.0
#: An anchor whose file was touched, but not the definition it names. Real evidence,
#: much weaker -- "something near what you call moved".
FILE_HIT_SCORE: float = 1.0
#: What each anchor hit *beyond the first at the same strength* adds. Deliberately an
#: order of magnitude below the gap between the two tiers above: a second direct hit
#: says "and another part of this workflow changed too", which breaks a tie between
#: equals and must never promote a workflow past one with stronger evidence.
CORROBORATION_SCORE: float = 0.1
#: Ceiling on that term. It exists to make the dominance rule structural rather than
#: probable: with the cap strictly below DIRECT_HIT_SCORE - FILE_HIT_SCORE, no quantity
#: of file-level coincidence can ever reach a single direct hit. Without it, eleven
#: file hits would, and nobody would notice until it happened on a customer's diff.
CORROBORATION_CAP: float = 0.5
#: Drifted workflows are worth re-examining -- but only when the diff already
#: implicates them. An unconditional bonus would select every stale workflow in the
#: knowledge base regardless of the diff and flood the budget.
STALE_BONUS: float = 0.5

CRITICALITY_MULTIPLIER: dict[Criticality, float] = {
    Criticality.HIGH: 1.5,
    Criticality.MEDIUM: 1.0,
    Criticality.LOW: 0.6,
}

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class DiffError(ValueError):
    """The diff could not be parsed. Loud, because a mis-parsed diff silently
    selects the wrong workflows and the run still looks green."""


def _header_path(line: str, prefix: str) -> str | None:
    """`"+++ b/demo/app.py\tts"` -> `"demo/app.py"`; `/dev/null` -> None."""
    raw = line[len(prefix) :].split("\t", 1)[0].strip()
    if raw == "/dev/null":
        return None
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return normalize_source_path(raw)


def parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Map each touched path to the line numbers changed on the *new* side.

    A deleted file maps to an empty set: it is present in the result (so file-level
    anchors into it still register as impact) but contributes no line numbers,
    because there is no new side to number. Renames record both paths the same way
    -- the old path vanishing is exactly the kind of drift anchors care about.
    """
    changed: dict[str, set[int]] = {}
    old_path: str | None = None
    current: str | None = None
    new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            old_path, current, in_hunk = None, None, False
            continue
        if line.startswith("rename from "):
            changed.setdefault(normalize_source_path(line[len("rename from ") :]), set())
            continue
        if line.startswith("rename to "):
            changed.setdefault(normalize_source_path(line[len("rename to ") :]), set())
            continue
        if line.startswith("--- "):
            old_path, in_hunk = _header_path(line, "--- "), False
            continue
        if line.startswith("+++ "):
            new_path = _header_path(line, "+++ ")
            current = new_path if new_path is not None else old_path
            if current is None:
                raise DiffError(f"file header names no path on either side: {line!r}")
            changed.setdefault(current, set())
            in_hunk = False
            continue
        if line.startswith("@@"):
            match = _HUNK_RE.match(line)
            if match is None:
                raise DiffError(f"malformed hunk header: {line!r}")
            if current is None:
                raise DiffError(f"hunk header before any file header: {line!r}")
            new_lineno = int(match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("\\"):  # "\ No newline at end of file"
            continue
        if line.startswith("+"):
            changed[current].add(new_lineno)
            new_lineno += 1
        elif line.startswith("-"):
            continue
        else:  # context line (a leading space, or an empty line some tools emit)
            new_lineno += 1

    return changed


def _definition_span(node: ast.AST) -> tuple[int, int]:
    """Line range a definition occupies, decorators included -- editing a route
    decorator is a change to that route even though the `def` line is untouched."""
    start = min([node.lineno] + [dec.lineno for dec in getattr(node, "decorator_list", [])])
    return start, node.end_lineno or node.lineno


def changed_symbols(
    diff: dict[str, set[int]], source_root: Path, route_map: RouteMap | None = None
) -> set[str]:
    """Symbols whose body overlaps the diff, as `"path::name"` and bare `"name"`,
    plus `"POST /path"` for any route whose handler was touched.

    Both the qualified and the bare form are emitted so that either anchor style
    matches without the caller having to know which one the knowledge base used.

    Routes come from two places and the difference is the whole point. Without a
    `route_map` they are read out of decorator syntax, which is a guess about how the
    framework was spelled and is wrong on most real applications. With one they are the
    routes the application itself says those lines serve. Both are emitted when a map is
    supplied rather than one replacing the other: they key on the same normalized route
    strings, so a correct decorator hit and a route-table hit are the same entry, and
    the union costs nothing while covering a handler the probe could not place.
    """
    root = Path(source_root)
    hits: set[str] = set()
    if route_map is not None:
        hits |= route_map.touched(diff)

    for rel_path, lines in sorted(diff.items()):
        if not lines or not rel_path.endswith(".py"):
            continue
        path = root / rel_path
        if not path.is_file():  # deleted by this diff, or outside the checkout
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AnchorError(f"cannot parse changed file {rel_path}: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            start, end = _definition_span(node)
            if not any(start <= line <= end for line in lines):
                continue
            hits.add(f"{rel_path}::{node.name}")
            hits.add(node.name)
            hits.update(route_decorators(node))

    return hits


def anchor_file(anchor: Anchor, route_map: RouteMap | None = None) -> str | None:
    """The source path an anchor implicates, or None when it names no file.

    A route anchor names no file on its own, but the route table knows which file
    serves it -- so with a map, editing anything in the module that handles a route
    counts as a file-level hit on the workflows that call it. That is the signal the
    seeder's FILE anchors were meant to carry and do not: every one of them points at
    the *test* the workflow was seeded from, while diffs land on application source.
    """
    match anchor.kind:
        case AnchorKind.ROUTE:
            if route_map is None:
                return None
            source = route_map.source_for(normalize_route(anchor.locator))
            return None if source is None else source.file
        case AnchorKind.SYMBOL:
            return split_symbol_locator(anchor.locator)[0]
        case AnchorKind.FILE | AnchorKind.COMPONENT:
            return normalize_source_path(anchor.locator)
    raise AnchorError(f"unhandled anchor kind: {anchor.kind!r}")


def anchor_symbol(anchor: Anchor, route_map: RouteMap | None = None) -> str | None:
    """The key to look up in `changed_symbols` output, or None for path anchors.

    A route map resolves the anchor's *instance* -- `/api/v1/challenges/1`, as some
    test happened to call it -- to the *pattern* the application serves, which is the
    form `changed_symbols` emits. Falling back to the literal when nothing matches is
    deliberate: an anchor to a route the app no longer has should score zero here and
    be caught by the staleness pass, not quietly matched to a neighbour.
    """
    match anchor.kind:
        case AnchorKind.ROUTE:
            route = normalize_route(anchor.locator)
            if route_map is None:
                return route
            return route_map.key_for(route) or route
        case AnchorKind.SYMBOL:
            file_path, name = split_symbol_locator(anchor.locator)
            return name if file_path is None else f"{file_path}::{name}"
        case AnchorKind.FILE | AnchorKind.COMPONENT:
            return None
    raise AnchorError(f"unhandled anchor kind: {anchor.kind!r}")


def _file_touched(file_path: str, diff: dict[str, set[int]]) -> bool:
    """Exact path, or a directory anchor containing a changed path."""
    if file_path in diff:
        return True
    prefix = file_path.rstrip("/") + "/"
    return any(touched.startswith(prefix) for touched in diff)


def anchor_strength(
    anchor: Anchor,
    diff: dict[str, set[int]],
    symbols: set[str],
    route_map: RouteMap | None = None,
) -> float:
    """How hard this diff hit this one anchor: direct, file-level, or not at all.

    A direct hit supersedes the file hit rather than adding to it. They are not two
    findings: the changed lines are *inside* the file, so counting both scores one
    piece of evidence twice, and it is the double-count that made a broad workflow
    look better-evidenced than a precise one.
    """
    symbol = anchor_symbol(anchor, route_map)
    if symbol is not None and symbol in symbols:
        return DIRECT_HIT_SCORE
    file_path = anchor_file(anchor, route_map)
    if file_path is not None and _file_touched(file_path, diff):
        return FILE_HIT_SCORE
    return 0.0


def score_workflow(
    workflow: Workflow,
    diff: dict[str, set[int]],
    symbols: set[str],
    route_map: RouteMap | None = None,
) -> float:
    """How much this diff threatens this workflow. 0.0 means "not implicated".

    The strongest single anchor decides the score; further anchors *at that same
    strength* add a small corroboration term, capped. Summing hits instead -- the
    obvious rule, and the one this replaced -- ranks by how much of the application a
    workflow happens to touch, so a workflow calling the rewritten handler plus two
    bystander routes in the same file beats one whose only subject is that handler.
    That is backwards under a budget: the tests most about the change are the ones that
    then do not run.

    Corroboration counts only hits at the strongest tier, which is the part worth
    arguing. Counting *every* other hit is the same defect in miniature -- when two
    workflows are both directly implicated, letting file-level coincidence order them
    is letting coincidence decide which one CI spends its minutes on. Measured on CTFd
    it also does not work: the four tests written against the rewritten endpoint move
    from rank 16-19 to 14-17 and are still cut by a budget of ten, because every
    workflow calling that endpoint has exactly one direct hit and the tiebreak is
    entirely bystander routes. Under this rule they tie at the top, which is the honest
    answer -- with respect to this diff those workflows *are* equally implicated, and
    the ordering within the tie is `select_workflows`' id sort, not a claim about risk.

    Criticality and staleness are applied afterwards and may reorder across tiers on
    purpose. They are standing priorities about a workflow, not evidence about this
    diff, and the dominance rule is a statement about evidence.
    """
    hits = [anchor_strength(anchor, diff, symbols, route_map) for anchor in workflow.anchors]
    hits = [hit for hit in hits if hit > 0.0]
    if not hits:
        return 0.0

    strongest = max(hits)
    corroboration = min(CORROBORATION_CAP, CORROBORATION_SCORE * (hits.count(strongest) - 1))

    score = (strongest + corroboration) * CRITICALITY_MULTIPLIER[workflow.criticality]
    if workflow.status == WorkflowStatus.STALE:
        score += STALE_BONUS
    return score


def select_workflows(
    kb: KnowledgeBase,
    diff_text: str,
    source_root: Path,
    budget: int,
    route_map: RouteMap | None = None,
) -> tuple[list[Workflow], list[str]]:
    """Pick the `budget` most-threatened workflows; report the rest by name.

    Ordering is score descending, ties broken by workflow id, so the same diff and
    the same knowledge base always produce the same run. RETIRED workflows are never
    selected. The second return value is every workflow that scored above zero and
    still did not fit -- the reporter turns it into "not tested", which is the whole
    point of returning it instead of dropping it.
    """
    if budget < 1:
        raise ValueError(f"budget must be at least 1, got {budget}")

    diff = parse_unified_diff(diff_text)
    symbols = changed_symbols(diff, source_root, route_map)

    scored = [
        (workflow, score_workflow(workflow, diff, symbols, route_map))
        for workflow in kb.workflows
        if workflow.status != WorkflowStatus.RETIRED
    ]
    ranked = sorted(((w, s) for w, s in scored if s > 0.0), key=lambda pair: (-pair[1], pair[0].id))

    selected = [workflow for workflow, _ in ranked[:budget]]
    skipped = [workflow.id for workflow, _ in ranked[budget:]]
    return selected, skipped
