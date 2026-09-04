"""Cold-start seeding: turn a customer's existing e2e suite into knowledge.

A new customer's knowledge base is empty; their repository is not. A hand-written e2e
suite already encodes which flows matter, names them in domain language, and records the
assertions a human cared enough to write down. This module reads that suite with `ast`
and produces Workflows from it. No model is involved: seeding is fully deterministic, so
the same repository always yields the same knowledge base and a diff of it is reviewable.

What it produces is deliberately second-class. Every Expectation lands with provenance
INFERRED_FROM_TEST, which caps any finding derived from it at Severity.CHANGE. An assert
records what the code did on the day someone wrote it, not what the product owner
promised. Seeding buys coverage on day one; only a human confirming an expectation
promotes it to something we are allowed to call a bug.

Asserts we cannot translate into a machine check are kept, not dropped -- as prose-only
Expectations with `check=None`. Downstream those evaluate to BLOCKED offline rather than
to a guess, which is the honest outcome and the whole point of the three-outcome model.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from bisect import bisect_right
from collections.abc import Iterator
from enum import Enum
from pathlib import Path

from qabot.anchors import AnchorError, SourceIndex, resolve_against_index
from qabot.models import (
    Anchor,
    AnchorKind,
    Criticality,
    Expectation,
    KnowledgeBase,
    OpenQuestion,
    Provenance,
    Step,
    Workflow,
)

#: Confidence for anything inferred from a test. Below the 0.5 default's neighbours on
#: purpose: a test's assert is evidence, not a promise.
INFERRED_CONFIDENCE = 0.6

_TEST_PREFIX = "test_"

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

#: Keyword arguments only an HTTP client takes. A dict, a cache, an ORM session and a
#: queue all answer to `.get`; none of them answers to `headers=`. `timeout=` is
#: deliberately absent -- `queue.get(timeout=1)` is the counterexample.
_REQUEST_KWARGS = frozenset(
    {
        "json",
        "headers",
        "params",
        "data",
        "files",
        "content",
        "cookies",
        "auth",
        "follow_redirects",
        "allow_redirects",
    }
)

#: Keywords that name the URL itself. The call is a request; `_hint` then refuses it for
#: not saying which route, which is a better error than pretending it was never HTTP.
_URL_KWARGS = frozenset({"url", "path"})

#: Method -> the verb that makes a step intent read as an action rather than as a route.
_METHOD_VERB = {
    "get": "fetch",
    "post": "submit",
    "put": "replace",
    "patch": "update",
    "delete": "delete",
    "head": "check",
    "options": "check",
}

#: A flow naming any of these is money or identity, and is worth more of a run's budget.
_CRITICAL_TERMS = ("checkout", "payment", "auth")

#: Files whose presence marks a project root, for path resolution in source refs.
_ROOT_MARKERS = ("pyproject.toml", ".git")

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

#: A source position, `(line, column)`. Calls, bindings and asserts are ordered by it.
_Position = tuple[int, int]


#: How far up from a test file to look for the package a route module is imported from.
_IMPORT_SEARCH_DEPTH = 8


class SeedError(RuntimeError):
    """Raised when a test file cannot be turned into knowledge.

    Never downgraded to a skip: a flow the seeder silently drops is a flow the customer
    believes is covered and is not.
    """


# --- constant folding ----------------------------------------------------------------
#
# WHY this exists: real suites do not inline URLs. Mealie writes
# `api_client.post(api_routes.recipes, json=...)` -- 554 such calls against exactly one
# string literal -- and every other mature codebase eventually grows the same route
# constants module, because duplicating a URL in 60 tests is how you get 60 wrong URLs.
# A seeder that only reads literals therefore reads nothing real. Rather than teach every
# extraction path about symbols, we resolve the constants once and rewrite them into the
# tree as literals, so the rest of the seeder is unchanged and unaware.


def _module_candidates(test_file: Path, parts: tuple[str, ...]) -> Iterator[Path]:
    """Where a dotted module name might live, relative to a test file.

    Walks upward rather than guessing a project root: the importable root is whichever
    ancestor makes the dotted path resolve, which is exactly what Python itself does.
    """
    for ancestor in list(test_file.parents)[:_IMPORT_SEARCH_DEPTH]:
        base = ancestor.joinpath(*parts)
        yield base / "__init__.py"
        yield base.with_suffix(".py")


def _string_constants(module: Path) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments. Anything else is ignored."""
    try:
        tree = ast.parse(module.read_text(), filename=str(module))
    except (OSError, SyntaxError):
        return {}
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[target.id] = node.value.value
    return found


def _constant_table(tree: ast.Module, test_file: Path) -> dict[str, str]:
    """Resolve `from pkg import routes` into {"routes.NAME": "/a/path"}.

    Only modules reachable on disk are read, and only their string constants are taken.
    Nothing is imported or executed: seeding a customer's repository must never run
    their code.
    """
    table: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None or node.level:
            continue
        for alias in node.names:
            parts = (*node.module.split("."), alias.name)
            bound = alias.asname or alias.name
            for candidate in _module_candidates(test_file, parts):
                if candidate.is_file():
                    for name, value in _string_constants(candidate).items():
                        table[f"{bound}.{name}"] = value
                    break
    # Constants defined in the test file itself, referenced bare.
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                table[target.id] = node.value.value
    return table


class _FoldConstants(ast.NodeTransformer):
    """Rewrite known constant references into the literals they stand for."""

    def __init__(self, table: dict[str, str]):
        self._table = table

    def visit_Attribute(self, node: ast.Attribute) -> ast.expr:
        if isinstance(node.value, ast.Name):
            dotted = f"{node.value.id}.{node.attr}"
            if dotted in self._table:
                return ast.copy_location(ast.Constant(value=self._table[dotted]), node)
        return self.generic_visit(node)


def seed_from_test_file(
    path: Path, repo: str, questions: list[OpenQuestion] | None = None
) -> list[Workflow]:
    """Extract one Workflow per top-level `test_*` function in `path`.

    `repo` names the repository these workflows belong to. It carries no information the
    workflows themselves hold, and is accepted for symmetry with `seed_knowledge_base`,
    which is the caller that has it.

    `questions` collects the calls this file's traversal could not classify as HTTP or
    not (see `_classify`). It is filled in rather than returned so that the questions come
    out of the very traversal that made the decision: a second pass to rediscover what was
    ambiguous is a second opinion, and the two disagreeing is how a dropped step becomes
    invisible again.
    """
    path = Path(path)
    if not path.is_file():
        raise SeedError(f"no such test file: {path}")
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:
        raise SeedError(f"{path} is not parseable Python: {exc}") from exc

    # Resolve route constants into literals before extraction, so every downstream
    # path sees a real URL rather than a symbol it would have to refuse.
    tree = _FoldConstants(_constant_table(tree, path)).visit(tree)

    rel = _relative_path(path)
    workflows = [
        _workflow_from_function(node, rel, questions if questions is not None else [])
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith(_TEST_PREFIX)
    ]
    for workflow in workflows:
        _reject_unloadable_anchors(workflow)
    return workflows


def seed_knowledge_base(e2e_dir: Path, repo: str) -> KnowledgeBase:
    """Seed a whole knowledge base from every `test_*.py` under `e2e_dir`."""
    e2e_dir = Path(e2e_dir)
    if not e2e_dir.is_dir():
        raise SeedError(f"no e2e directory at {e2e_dir}")
    files = sorted(e2e_dir.rglob(f"{_TEST_PREFIX}*.py"))
    if not files:
        raise SeedError(f"no {_TEST_PREFIX}*.py files under {e2e_dir}; nothing to seed from")

    workflows: list[Workflow] = []
    questions: list[OpenQuestion] = []
    seen: dict[str, str] = {}
    for file in files:
        for workflow in seed_from_test_file(file, repo, questions):
            if workflow.id in seen:
                raise SeedError(
                    f"duplicate workflow id {workflow.id!r} from {workflow.source_ref} "
                    f"and {seen[workflow.id]}"
                )
            seen[workflow.id] = workflow.source_ref or ""
            workflows.append(workflow)
    return KnowledgeBase(repo=repo, workflows=workflows, open_questions=questions)


def _reject_unloadable_anchors(workflow: Workflow) -> None:
    """Refuse at seed time any anchor the run path will refuse to resolve.

    The seeder used to write knowledge bases that `qabot run` could not load: a phantom
    step from `sess.get("status")` became the ROUTE anchor `GET status`, and
    `staleness_pass` -- which runs before anything else, every run -- raised on it and
    took the whole run with it. `qabot seed` reported success; `qabot run` exploded. A
    producer that emits what its own consumer rejects has no contract at all, and the
    customer finds out at the worst moment.

    So we resolve every anchor here through `resolve_against_index`, the run path's own
    function, against an empty index. Every anchor comes back unresolved and we discard
    that answer: what is being checked is that resolution *runs*. Calling the real
    resolver rather than restating its rules is the point -- a private copy of the
    normalization is a copy that can drift back out of agreement, which is the bug.
    """
    empty = SourceIndex(
        root=Path(), routes=frozenset(), symbols_by_file={}, all_symbols=frozenset()
    )
    for anchor in workflow.anchors:
        try:
            resolve_against_index(anchor, empty)
        except AnchorError as exc:
            raise SeedError(
                f"{workflow.source_ref}: seeded an anchor the run path cannot load -- "
                f"{anchor.kind.value} {anchor.locator!r}: {exc}"
            ) from exc


# --- workflow assembly ---------------------------------------------------------------


def _workflow_from_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef, rel: str, questions: list[OpenQuestion]
) -> Workflow:
    docstring = ast.get_docstring(func)
    calls, unclear = _http_calls(func)
    hints = [_hint(method, call) for method, call in calls]
    bound_at = _thread_captures(func, calls, hints)

    steps = [Step(intent=_intent(hint), hint=hint) for hint in hints]
    workflow_id = f"wf_{func.name[len(_TEST_PREFIX) :]}"
    questions.extend(_unclear_questions(workflow_id, rel, unclear))
    return Workflow(
        id=workflow_id,
        name=_workflow_name(func.name, docstring),
        criticality=_criticality(func.name, docstring),
        steps=steps,
        expectations=_expectations(func, workflow_id, calls, bound_at),
        anchors=_anchors(hints, rel),
        source_ref=f"{rel}::{func.name}",
    )


def _unclear_questions(
    workflow_id: str, rel: str, unclear: list[tuple[str, ast.Call]]
) -> list[OpenQuestion]:
    """One question per receiver this workflow calls a verb on that we could not read.

    Grouped by receiver rather than raised per call because that is the question a human
    actually answers: langflow's `session.delete(...)` appears 70 times and settling
    "is `session` an HTTP client?" once settles all of them. The call sites travel along
    as candidates so nobody has to go looking.
    """
    grouped: dict[tuple[str, str], list[int]] = {}
    for verb, call in unclear:
        receiver = call.func.value.id  # type: ignore[union-attr]  # _http_verb checked
        grouped.setdefault((receiver, verb), []).append(call.lineno)
    return [
        OpenQuestion(
            id=_seed_question_id(workflow_id, receiver, verb),
            question=(
                f"Is `{receiver}.{verb}(...)` in {rel} an HTTP request? The seeder could "
                f"not tell from the call, so {workflow_id} was seeded without "
                f"{'it' if len(lines) == 1 else f'these {len(lines)} calls'}. If it is a "
                f"request the flow is missing part of what the test does; if it is a "
                f"dict, an ORM session or a queue, nothing is missing."
            ),
            trigger="seed",
            candidates=[f"{rel}:{line}" for line in lines],
            blocking=False,
            workflow_id=workflow_id,
        )
        for (receiver, verb), lines in grouped.items()
    ]


def _seed_question_id(workflow_id: str, receiver: str, verb: str) -> str:
    """Stable across re-seeds, for `anchors.staleness_question_id`'s reason: a question
    a curator has already answered must not come back with a new id every run."""
    digest = hashlib.sha1(f"{receiver}.{verb}".encode()).hexdigest()[:8]
    return f"oq-seed-{workflow_id}-{digest}"


def _workflow_name(func_name: str, docstring: str | None) -> str:
    """The docstring's first line if the author wrote one, else the name, humanized."""
    if docstring:
        return docstring.strip().splitlines()[0].strip()
    words = func_name[len(_TEST_PREFIX) :].replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _criticality(func_name: str, docstring: str | None) -> Criticality:
    haystack = f"{func_name} {docstring or ''}".lower()
    if any(term in haystack for term in _CRITICAL_TERMS):
        return Criticality.HIGH
    return Criticality.MEDIUM


# --- steps ---------------------------------------------------------------------------


class _Call(Enum):
    """What a `<name>.<verb>(...)` call turned out to be."""

    REQUEST = "request"
    NOT_A_REQUEST = "not a request"
    UNCLEAR = "unclear"


def _http_calls(func: ast.AST) -> tuple[list[tuple[str, ast.Call]], list[tuple[str, ast.Call]]]:
    """The requests in this function and the calls we could not classify, in source order.

    Both are returned because the caller owes the customer an account of each: the
    requests become steps, and the unclassifiable ones become open questions. A call this
    function decided was *not* a request needs no account -- `sess.get("nonce")` is not a
    gap in anyone's coverage.
    """
    requests: list[tuple[str, ast.Call]] = []
    unclear: list[tuple[str, ast.Call]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or (verb := _http_verb(node)) is None:
            continue
        match _classify(node):
            case _Call.REQUEST:
                requests.append((verb, node))
            case _Call.UNCLEAR:
                unclear.append((verb, node))
            case _Call.NOT_A_REQUEST:
                pass
    for calls in (requests, unclear):
        calls.sort(key=lambda pair: (pair[1].lineno, pair[1].col_offset))
    return requests, unclear


def _http_verb(call: ast.Call) -> str | None:
    """The HTTP verb this call is *named* after. Says nothing about what it does."""
    func = call.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.attr in _HTTP_METHODS
    ):
        return func.attr
    return None


def _classify(call: ast.Call) -> _Call:
    """Is a verb-named call an HTTP request, something else, or unreadable?

    Being named `.get` proves nothing. Every dict, cache, ORM session, context variable,
    queue and mocking library in Python answers to it, and real suites call them
    constantly: CTFd reads `sess.get("nonce")` off a Flask session 93 times. Accepting
    any `<name>.<verb>(...)` made 127 of 1018 seeded steps requests no test ever issued
    -- requests the bot would then send to the application and grade assertions against.
    A fabricated request carrying real evidence is D47's failure reached from the other
    end, and it is the one this module must never commit.

    So a call earns REQUEST only on evidence, and the evidence is how it names a URL:

    * a keyword only an HTTP client takes (`json=`, `headers=`, `params=` ...), or one
      that names the URL outright (`url=`);
    * a first argument with path structure -- any literal fragment containing `/`. This
      is what separates langflow's `client.get("api/v1/all")`, which has no leading slash
      and 1121 siblings, from `sess.get("nonce")`. Across CTFd's and langflow's suites
      there are 355 slashless string-literal first arguments and not one is a request.

    Two counts of evidence say the opposite. More or fewer than one positional argument:
    httpx, Flask's test client and Starlette's all make everything after the URL
    keyword-only, so `d.get(k, default)`, `session.get(Model, pk)` and `ctx.get()` are
    shapes no request has. And a bare string literal with no `/` in it, which is a key.

    Everything else is UNCLEAR and becomes an OpenQuestion instead of a step:
    `client.get(chal_uri)`, `session.delete(project)`, and an absolute URL, whose host we
    cannot show is the application under test rather than a third-party service. Guessing
    either way is what we refuse -- included it invents a request, dropped it is a silent
    hole in coverage the customer believes is covered.
    """
    first = call.args[0] if call.args else None
    fragments = [] if first is None else list(_literal_texts(first))
    if any("://" in text for text in fragments):
        return _Call.UNCLEAR
    if any(kw.arg in _REQUEST_KWARGS or kw.arg in _URL_KWARGS for kw in call.keywords):
        return _Call.REQUEST
    if len(call.args) != 1:
        return _Call.NOT_A_REQUEST
    if any("/" in text for text in fragments):
        return _Call.REQUEST
    return _Call.NOT_A_REQUEST if _is_literal(first, str) else _Call.UNCLEAR


def _literal_texts(node: ast.expr) -> Iterator[str]:
    """The string fragments written literally in an expression, interpolations aside.

    `f"/challenges/{cid}"` yields `"/challenges/"`, which is all the evidence needed to
    call it a route; `f"{cid}"` yields nothing, which is why that stays unclear.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            yield from _literal_texts(part)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _literal_texts(node.left)
        yield from _literal_texts(node.right)


def _hint(method: str, call: ast.Call) -> dict:
    """The recorded resolution of a call: how the planner replays it without guessing."""
    if not call.args:
        raise SeedError(
            f"line {call.lineno}: {method}() has no positional path argument; "
            "the seeder cannot tell which route this step touches"
        )
    path = _render(call.args[0])
    if not isinstance(path, str):
        raise SeedError(f"line {call.lineno}: request path is not a string: {path!r}")
    if not path.startswith("/"):
        # `client.get("api/v1/all")` -- langflow writes 1121 of these. httpx and every
        # test client resolve a relative path against the base URL by stripping exactly
        # this slash, so adding it changes no request; without it the ROUTE anchor is one
        # the run path refuses to load, and the seed succeeds into a crash.
        path = f"/{path}"

    hint: dict = {"method": method.upper(), "path": path}
    body = next((kw.value for kw in call.keywords if kw.arg == "json"), None)
    if body is not None:
        hint["json"] = _render(body)
    return hint


def _intent(hint: dict) -> str:
    """A human-readable action. The planner prefers `hint`; this is what a person reads
    in a report, and what a model reads when the hint has gone stale."""
    verb = _METHOD_VERB[hint["method"].lower()]
    intent = f"{verb} {hint['path']}"
    if "json" in hint:
        intent += f" with {json.dumps(hint['json'])}"
    return intent


def _thread_captures(
    func: ast.AST, calls: list[tuple[str, ast.Call]], hints: list[dict]
) -> dict[str, list[tuple[_Position, int]]]:
    """Record, on the step that produces a value, that a later step needs it.

    A test threads state through local variables (`cart = resp.json()["cart_id"]`), which
    is invisible to a runner replaying steps. We reconstruct the dependency: a
    `{placeholder}` in a later step's path or body is resolved back to the earlier
    response field it came from, and recorded as `capture` on that earlier step.

    `capture` reads in assignment order -- {variable: response_field}. The assignment
    above seeds `{"cart": "cart_id"}`: bind `cart` from the response's `cart_id`, exactly
    as the test wrote it. Reversing it silently misnames every value a flow carries
    forward the moment a test calls a field something other than its own name.

    Returns the response bindings this scan already computes -- every point at which a
    name was bound to a step's response, in source order -- because `_expectations` needs
    exactly that to bind an assert to the response it names. Handing it over rather than
    recomputing it keeps one answer to "what does `resp` mean here"; a second scan is a
    second place for rebinding to be got wrong.
    """
    index_of = {id(call): i for i, (_, call) in enumerate(calls)}
    response_of: dict[str, int] = {}
    bound_at: dict[str, list[tuple[_Position, int]]] = {}
    captured_from: dict[str, tuple[int, str]] = {}

    for position, target, value in _name_bindings(func):
        if isinstance(value, ast.Call) and id(value) in index_of:
            response_of[target] = index_of[id(value)]
            bound_at.setdefault(target, []).append((position, index_of[id(value)]))
            continue
        source = _json_subscript(value)
        if source is not None and source[0] in response_of:
            captured_from[target] = (response_of[source[0]], source[1])

    for i, hint in enumerate(hints):
        for var in _placeholders(hint["path"]) + _placeholders(hint.get("json")):
            origin = captured_from.get(var)
            # A placeholder with no earlier response behind it is a fixture value, not
            # something a previous step can hand over.
            if origin is None or origin[0] >= i:
                continue
            hints[origin[0]].setdefault("capture", {})[var] = origin[1]
    return bound_at


def _name_bindings(func: ast.AST) -> list[tuple[_Position, str, ast.expr]]:
    """Every `name = <expr>` and `with <expr> as name`, in source order.

    `with` is here because a streamed response is bound that way and is a response like
    any other, and `await` because `resp = await ac.get(...)` is the same binding an
    async suite writes for the same reason. Tuple unpacking is not: nothing downstream
    can say which element of `a, b = ...` holds the response, and inventing an answer is
    the failure this whole module exists to avoid.
    """
    bindings: list[tuple[_Position, str, ast.expr]] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bindings.append(((node.lineno, node.col_offset), target.id, _awaited(node.value)))
        elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
            item = node.context_expr
            position = (item.lineno, item.col_offset)
            bindings.append((position, node.optional_vars.id, _awaited(item)))
    bindings.sort(key=lambda binding: binding[0])
    return bindings


def _awaited(value: ast.expr) -> ast.expr:
    """The call behind an `await`. Awaiting a request does not change whose it is."""
    return value.value if isinstance(value, ast.Await) else value


def _placeholders(value: object) -> list[str]:
    """Every `{name}` appearing in a rendered path or body, in order, deduplicated."""
    if isinstance(value, str):
        return list(dict.fromkeys(_PLACEHOLDER_RE.findall(value)))
    if isinstance(value, dict):
        return list(dict.fromkeys(v for item in value.values() for v in _placeholders(item)))
    if isinstance(value, list):
        return list(dict.fromkeys(v for item in value for v in _placeholders(item)))
    return []


# --- expectations --------------------------------------------------------------------


def _expectations(
    func: ast.AST,
    workflow_id: str,
    calls: list[tuple[str, ast.Call]],
    bound_at: dict[str, list[tuple[_Position, int]]],
) -> list[Expectation]:
    """Every assert in the function, each bound to the step it is about.

    `resp = client.post(...)` followed by `assert resp.status_code == 402` is a claim
    about *that* response. Losing that link makes a verifier grade the assert against
    whichever response happened last and cite the wrong evidence -- reporting a bug at
    the one moment the app behaved.
    """
    step_positions = [(call.lineno, call.col_offset) for _, call in calls]
    asserts = sorted(
        (n for n in ast.walk(func) if isinstance(n, ast.Assert)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    expectations = []
    for n, node in enumerate(asserts, start=1):
        check, statement = _translate(node.test)
        expectations.append(
            Expectation(
                id=f"{workflow_id}_e{n}",
                statement=statement,
                provenance=Provenance.INFERRED_FROM_TEST,
                confidence=INFERRED_CONFIDENCE,
                check=check,
                step_index=_step_for_assert(step_positions, bound_at, node),
            )
        )
    return expectations


def _step_for_assert(
    step_positions: list[_Position],
    bound_at: dict[str, list[tuple[_Position, int]]],
    node: ast.Assert,
) -> int | None:
    """The step whose response this assert is about, or None if it is about no step.

    Source position alone is the wrong answer, and was the bug here. A suite that writes
    `a = client.get("/a")`, `b = client.post("/b")`, then asserts on both, puts every
    call before every assert -- so "the last step begun before this line" binds `a`'s
    claim to `b`'s response, grades a 200 against a 201, and reports a change against an
    application that behaved exactly as its own test said it should. That is D31 again,
    one layer up: the same wrong evidence, baked into the knowledge base at seed time
    instead of chosen at grading time, where no later layer can detect it.

    So the response variable the assert names decides. `a.status_code` is a claim about
    whatever `a` was bound to *at that line*, which is also what makes a rebound `resp`
    work -- a name is reassigned freely, and only the binding in effect matters.

    An assert naming a variable we never saw bound to a call -- a fixture's response, a
    value from outside the function -- binds to nothing. Unbound is BLOCKED downstream,
    which is honest; attaching it to whichever step happens to be nearest is the same
    false positive wearing a shape that looks deliberate.

    Position still decides the two cases carrying no such variable: a call written inside
    the assert (`assert client.get("/health").status_code == 200`) is its own subject,
    and an assert reaching into no name at all (`assert data["id"] == "abc"`) falls back
    to the last call before it, which is all anyone can say about it.
    """
    subject = node.test
    at = (subject.lineno, subject.col_offset)
    index = bisect_right(step_positions, (subject.end_lineno, subject.end_col_offset)) - 1
    if index >= 0 and step_positions[index] >= at:
        return index

    names = _subject_names(subject)
    if not names:
        return index if index >= 0 else None
    for name in names:
        step = _binding_before(bound_at.get(name, []), at)
        if step is not None:
            return step
    return None


def _subject_names(test: ast.expr) -> list[str]:
    """Names the assert reaches into, leftmost first.

    `resp` in `resp.status_code` and in `len(resp.json()["items"])`. Taking an attribute
    of a name is what separates a response being examined from a value being compared:
    `assert sku == "widget"` names `sku` but claims nothing about any response, so it has
    to keep falling through to position rather than binding to nothing.
    """
    holders = sorted(
        (
            node
            for node in ast.walk(test)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    return list(dict.fromkeys(node.value.id for node in holders))


def _binding_before(history: list[tuple[_Position, int]], position: _Position) -> int | None:
    """The step a name was last bound to before `position`, or None if it was not.

    Only the latest binding counts. Taking any binding of the name -- the first, or the
    last in the function -- is the naive shortcut that puts the positional bug straight
    back in, since `resp = ...` twice over means two different responses.
    """
    step = None
    for bound, index in history:
        if bound >= position:
            break
        step = index
    return step


def _translate(test: ast.expr) -> tuple[dict | None, str]:
    """An assert as (machine check, statement). The check is None when the assert says
    something we can only restate, and the statement is then all a verifier has."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, left, right = test.ops[0], test.left, test.comparators[0]

        if isinstance(op, ast.Eq):
            if _is_status_code(left) and _is_literal(right, int):
                return (
                    {"kind": "status", "value": right.value},
                    f"response status is {right.value}",
                )
            field = _json_field(left)
            if field is not None and isinstance(right, ast.Constant):
                return (
                    {"kind": "json_eq", "path": field, "value": right.value},
                    f"response field {field!r} equals {right.value!r}",
                )

        if isinstance(op, ast.Gt):
            field = _len_of_json_field(left)
            if field is not None and _is_literal(right, int):
                return (
                    {"kind": "json_len_gt", "path": field, "value": right.value},
                    f"response field {field!r} holds more than {right.value} item(s)",
                )

        if isinstance(op, ast.In):
            field = _json_field(right)
            if field is not None and _is_literal(left, str):
                return (
                    {"kind": "json_contains", "path": field, "value": left.value},
                    f"response field {field!r} contains {left.value!r}",
                )

    return None, f"the test asserts {ast.unparse(test)}"


def _is_status_code(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "status_code"


def _is_literal(node: ast.expr, kind: type) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is kind


def _json_subscript(node: ast.expr) -> tuple[str, str] | None:
    """`(holder, field)` for `<holder>.json()["<field>"]`, else None."""
    if not isinstance(node, ast.Subscript) or not _is_literal(node.slice, str):
        return None
    call = node.value
    if not isinstance(call, ast.Call) or call.args or call.keywords:
        return None
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "json":
        return None
    if not isinstance(func.value, ast.Name):
        return None
    return func.value.id, node.slice.value


def _json_field(node: ast.expr) -> str | None:
    found = _json_subscript(node)
    return found[1] if found is not None else None


def _len_of_json_field(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    if node.func.id != "len" or len(node.args) != 1:
        return None
    return _json_field(node.args[0])


# --- anchors -------------------------------------------------------------------------


def _anchors(hints: list[dict], rel: str) -> list[Anchor]:
    """One ROUTE per distinct route the flow touches, plus the FILE it was seeded from.

    These are the drift sensors: when a diff moves one of these routes or rewrites this
    file, the workflow that depends on it is the one that needs re-checking.
    """
    routes = dict.fromkeys(f"{hint['method']} {hint['path']}" for hint in hints)
    anchors = [Anchor(kind=AnchorKind.ROUTE, locator=route) for route in routes]
    anchors.append(Anchor(kind=AnchorKind.FILE, locator=rel))
    return anchors


# --- source rendering ----------------------------------------------------------------


def _render(node: ast.expr) -> object:
    """A source expression as the value it stands for.

    Literals become themselves. A variable or an f-string interpolation becomes a
    `{name}` placeholder, because that is exactly what it is at seed time: a slot whose
    value a previous step produces. Anything else is refused loudly -- a step we render
    wrongly would send a runner at the wrong route with the wrong body.
    """
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        pass

    if isinstance(node, ast.Name):
        return f"{{{node.id}}}"
    if isinstance(node, ast.JoinedStr):
        return _render_fstring(node)
    if isinstance(node, ast.Dict):
        return {_render_key(key): _render(value) for key, value in zip(node.keys, node.values)}
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return [_render(element) for element in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # `routes.recipes + f"/{recipe_id}"` -- a constant base joined to a templated
        # suffix. Common once a suite has a route constants module, since that module
        # can only hold the collection URL.
        left, right = _render(node.left), _render(node.right)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise SeedError(
            f"line {node.lineno}: cannot join {ast.unparse(node)!r} into a path; "
            "both sides must render to strings"
        )
    raise SeedError(
        f"line {node.lineno}: cannot render {ast.unparse(node)!r} into a step value; "
        "the seeder handles literals, variables and f-strings only"
    )


def _render_key(node: ast.expr | None) -> str:
    """`None` is a `**expansion`, which hides which fields the request actually sends."""
    if node is None:
        raise SeedError("request body uses ** expansion; the seeder needs literal keys")
    if not _is_literal(node, str):
        raise SeedError(f"request body key {ast.unparse(node)!r} is not a string literal")
    return node.value


def _render_fstring(node: ast.JoinedStr) -> str:
    parts = []
    for part in node.values:
        if isinstance(part, ast.Constant):
            parts.append(str(part.value))
        elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            parts.append(f"{{{part.value.id}}}")
        else:
            raise SeedError(
                f"line {node.lineno}: f-string interpolates "
                f"{ast.unparse(part)!r}; the seeder handles plain variables only"
            )
    return "".join(parts)


# --- paths ---------------------------------------------------------------------------


def _relative_path(path: Path) -> str:
    """The path as it appears in source refs and FILE anchors.

    Relative to the project root -- the nearest ancestor holding a `pyproject.toml` or a
    `.git` -- so that a source ref means the same thing on every machine. A file outside
    any project (a fixture written to a temporary directory) is named by itself.
    """
    resolved = path.resolve()
    for parent in resolved.parents:
        if any((parent / marker).exists() for marker in _ROOT_MARKERS):
            return str(resolved.relative_to(parent))
    return resolved.name
