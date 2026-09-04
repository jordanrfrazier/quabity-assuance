"""The route table as the application reports it, keyed for impact analysis.

Impact analysis asks one question: this diff touched these lines -- which workflows
call a route those lines serve? `anchors.route_decorators` answers it by matching
decorator syntax, which works for one idiom (`@app.get("/literal")`) and one shape of
application (one where the whole path is written in the decorator). Neither holds on
real code. Flask-RESTX writes `@ns.route("/types")` under a namespace mounted at
`/api/v1/challenges`; Flask itself writes `@app.route("/x", methods=["POST"])`, whose
attribute is `route`, not a verb; FastAPI composes `APIRouter(prefix=...)`. Measured
against CTFd, decorator matching extracts **zero** routes from the file that defines
seventeen of them, and selection therefore picks nothing out of a 410-workflow
knowledge base against a diff that rewrites a request handler.

So stop inferring. A running application already holds the map from URL to handler --
it must, or it could not serve a request -- and `inspect` turns a handler into a file
and a line span. A diff overlapping that span is a *direct* hit on every workflow that
calls that path: the same signal `impact.score_workflow` already wants, taken from the
framework's routing table instead of from a guess about how the framework was spelled.

**Anchors are instances; route tables are patterns.** The knowledge base, seeded from
tests, holds `GET /api/v1/challenges/1` and `GET /api/v1/challenges/{chal_id}`; Flask
holds `/api/v1/challenges/<challenge_id>`. Three vocabularies for one route, and the
parameter *name* is not shared -- the test author picked `chal_id`, the route author
picked `challenge_id`, and the instance has no name at all. So a parameter segment
collapses to a nameless slot on both sides and matching is segment-wise, literal
before slot, the way a router itself resolves a request. Erasing the name is the only
way those three ever meet.

The operational cost is real and belongs in the open: this needs the application
*importable*, which means its dependencies, which means running the probe under the
target's own interpreter (`python=` below). It costs one process start and whatever
the app's import does -- for CTFd, roughly two seconds and a database connection. In
CI that is nothing next to standing the app up, which the customer's pipeline already
did; on a developer's laptop it is the difference between configuring an app spec and
not having impact analysis at all. When it cannot be paid, `RouteMap.unavailable`
carries a stated limitation instead, on the precedent of `HttpDriver(reset_path=None)`:
an opt-out is explicit, visible in the report, and never silent.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from qabot._routeprobe import extract_routes, load_app
from qabot.anchors import SKIP_DIRS, normalize_path_segment

#: What a parameter segment collapses to, whatever the framework or the test called it.
SLOT = "{}"

#: How long to wait for the target's interpreter to import the app and dump its routes.
#: Generous because a real app's import runs migrations and opens connections.
PROBE_TIMEOUT: float = 120.0


class RouteMapError(RuntimeError):
    """The route table could not be built.

    Loud by construction. An unreadable route table and an application with no routes
    produce the same empty selection, and the entire value of this module is that those
    two must never look alike. A caller that decides to continue anyway says so with
    `RouteMap.unavailable`, which costs it a stated limitation on the run.
    """


def unavailable_limitation(reason: str) -> str:
    """The sentence a report carries when impact analysis ran without a route table."""
    return (
        f"the application's route table could not be read ({reason}), so impact selection "
        "fell back to matching route decorators in the source text -- an idiom real "
        "frameworks stop using as soon as paths are composed from blueprints, namespaces "
        "or routers, where it matches nothing at all: the workflows selected for this run "
        "are not evidence that no other workflow was put at risk by this diff"
    )


@dataclass(frozen=True)
class RouteSource:
    """Where the handler for one route lives, repo-relative and inclusive of both ends.

    The span covers decorators as well as the body, matching `impact._definition_span`:
    editing a route's decorator changes that route even though the `def` line is
    untouched.
    """

    file: str
    start: int
    end: int

    def overlaps(self, lines: set[int]) -> bool:
        return any(self.start <= line <= self.end for line in lines)


@dataclass(frozen=True)
class RouteMap:
    """`"POST /api/v1/challenges/{}"` -> the file and lines that serve it."""

    sources: dict[str, RouteSource] = field(default_factory=dict)

    limitations: tuple[str, ...] = ()
    """What this map could not establish, stated once and applying to the whole run.
    Read off by the runner exactly as driver limitations are, so a degraded map reaches
    the report as a sentence rather than as an unexplained absence of findings."""

    @classmethod
    def unavailable(cls, reason: str) -> RouteMap:
        """An empty map that says why it is empty.

        The counterpart to `RouteMapError`: the error is for a caller who should stop,
        this is for a caller who has decided to continue without route-based impact
        analysis. Both are explicit; neither is silent.
        """
        return cls(sources={}, limitations=(unavailable_limitation(reason),))

    def key_for(self, route: str) -> str | None:
        """`"GET /api/v1/challenges/1"` -> `"GET /api/v1/challenges/{}"`, or None.

        `route` is already `normalize_route`'d -- this deals only with the mismatch
        between a concrete path a test called and the pattern the framework declared.
        A query string is dropped: `?view=admin` selects a representation, not a route,
        and no framework's table records it.

        Ties go to the pattern with the fewest slots, which is how a router resolves
        `/challenges/types` against both `/challenges/types` and `/challenges/<id>`,
        then to the lexicographically first key so that the same knowledge base and the
        same application always select the same workflows.
        """
        method, _, raw_path = route.partition(" ")
        wanted = _canonical_segments(raw_path)
        exact = f"{method} {_join(wanted)}"
        if exact in self.sources:
            return exact
        candidates = [
            key
            for key in self.sources
            if key.startswith(f"{method} ") and _matches(wanted, _segments_of(key))
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda key: (key.count(SLOT), key))

    def source_for(self, route: str) -> RouteSource | None:
        """The handler behind a route anchor, or None when nothing serves that path."""
        key = self.key_for(route)
        return None if key is None else self.sources[key]

    def touched(self, diff: Mapping[str, set[int]]) -> set[str]:
        """Route keys whose handler's lines this diff edited.

        These are the direct hits: not "a file containing routes changed" but "the code
        that answers this exact request changed".
        """
        return {
            key
            for key, source in self.sources.items()
            if source.overlaps(diff.get(source.file) or set())
        }


def build_route_map(
    source_root: Path,
    app_spec: str,
    python: str | Path | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> RouteMap:
    """Import the app named by `app_spec` and read its route table.

    `python` names the interpreter that can import it. Leave it None only when qabot's
    own interpreter already can (the bundled demo, or a customer who installed qabot
    into the app's environment); point it at the target's virtualenv otherwise. The
    probe runs with `source_root` as its working directory because that is how the
    application's own package becomes importable, and it is where the app expects to
    find its config and database.

    Raises `RouteMapError` on anything that goes wrong -- the app not importing, the
    framework not being one of the two we read, no route landing inside the checkout.
    That last one is not pedantry: an app whose handlers all resolve into site-packages
    is not the app in `source_root`, and a map of routes no diff can ever touch is
    indistinguishable from no map at all.
    """
    if python is None:
        raw = _probe_in_process(app_spec)
    else:
        raw = _probe_subprocess(source_root, app_spec, python, timeout)
    return _from_routes(raw, source_root)


def _probe_in_process(app_spec: str) -> list[dict]:
    try:
        return extract_routes(load_app(app_spec))
    except Exception as exc:  # an import-time failure of any kind is the same news
        raise RouteMapError(f"cannot read routes from {app_spec!r}: {exc}") from exc


def _probe_subprocess(
    source_root: Path, app_spec: str, python: str | Path, timeout: float
) -> list[dict]:
    """Run the probe under the target's interpreter and read back its JSON.

    Only the last line of stderr reaches the error. For a Python traceback that line
    is the exception itself, and the frames above it are qabot's own stack rather than
    anything the customer can act on -- and this string ends up quoted inside a
    limitation sentence in the report, where a pasted traceback would bury the one
    clause that says what to fix. The rest is discarded: a real app's import is noisy
    (CTFd announces gevent monkey-patching and every plugin it loads) and that noise is
    never the news.
    """
    probe = Path(__file__).with_name("_routeprobe.py")
    with tempfile.TemporaryDirectory() as workdir:
        output = Path(workdir) / "routes.json"
        try:
            completed = subprocess.run(
                [str(python), str(probe), app_spec, str(output)],
                cwd=str(source_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except OSError as exc:
            raise RouteMapError(f"cannot run {python!s}: {exc}") from exc
        if completed.returncode != 0:
            noise = completed.stderr or completed.stdout
            said = [line.strip() for line in noise.splitlines() if line.strip()]
            reason = said[-1] if said else f"exit status {completed.returncode}"
            raise RouteMapError(f"probing {app_spec!r} failed: {reason}")
        try:
            return json.loads(output.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RouteMapError(
                f"probe of {app_spec!r} wrote no usable route table: {exc}"
            ) from exc


def _from_routes(raw: list[dict], source_root: Path) -> RouteMap:
    """Normalize the probe's output into anchor vocabulary, dropping foreign files.

    A route served by a library -- Flask's static endpoint, flask-restx's swagger UI --
    resolves outside the checkout and is dropped rather than recorded with an absolute
    path: no diff of this repository can touch it, so it can only ever be noise. The
    same goes for a vendored `.venv` *inside* the checkout, which is why the drop reuses
    `anchors.SKIP_DIRS` rather than testing containment alone -- FastAPI's own `/docs`
    route resolves to a file under `source_root` when the virtualenv lives there.

    Duplicate canonical keys keep the first entry. In practice they are trailing-slash
    aliases of one rule, which collapse to the same key *because* they are the same
    handler; keeping the first is deterministic given the framework's own ordering.
    """
    root = Path(source_root).resolve()
    sources: dict[str, RouteSource] = {}
    for entry in raw:
        try:
            relative = Path(entry["file"]).resolve().relative_to(root)
        except (KeyError, ValueError):
            continue
        if SKIP_DIRS & set(relative.parts):
            continue
        key = f"{entry['method'].upper()} {_join(_canonical_segments(entry['path']))}"
        sources.setdefault(
            key, RouteSource(file=relative.as_posix(), start=entry["start"], end=entry["end"])
        )
    if not sources:
        raise RouteMapError(
            f"no route resolved to a file under {root}: the application was read, but it "
            "is not the application in this checkout"
        )
    return RouteMap(sources=sources)


def _canonical_segments(path: str) -> tuple[str, ...]:
    """A path as segments, every parameter reduced to `SLOT`.

    Covers all three spellings this has to reconcile: Flask's `<int:challenge_id>`,
    Starlette's `{challenge_id}`, and the `{chal_id}` placeholder the seeder writes for
    a value one step captures and the next interpolates.
    """
    without_query = path.split("?", 1)[0].split("#", 1)[0]
    normalized = normalize_path_segment(without_query)
    return tuple(SLOT if _is_parameter(segment) else segment for segment in normalized.split("/"))


def _is_parameter(segment: str) -> bool:
    return (segment.startswith("<") and segment.endswith(">")) or (
        segment.startswith("{") and segment.endswith("}")
    )


def _matches(concrete: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    """Does this concrete path fit this route pattern? Slots match one segment each.

    Asymmetric on purpose. A slot in the *pattern* accepts any single segment, but a
    slot in the anchor does not accept a literal: `GET /challenges/{chal_id}` must not
    resolve to `GET /challenges/types`, which is a different endpoint that happens to
    have the same shape. An empty segment never fills a slot either, or `GET /` would
    resolve to whatever `/<name>` serves.
    """
    if len(concrete) != len(pattern):
        return False
    return all(
        have == want if want != SLOT else bool(have) for have, want in zip(concrete, pattern)
    )


def _segments_of(key: str) -> tuple[str, ...]:
    return tuple(key.partition(" ")[2].split("/"))


def _join(segments: tuple[str, ...]) -> str:
    return "/".join(segments)


def main(argv: list[str]) -> int:  # pragma: no cover - operator convenience
    """`python -m qabot.routemap <source_root> <app_spec> [python]` -- print the map.

    Exists so that "is the route table right?" is answerable by looking, without a run.
    """
    if not 2 <= len(argv) <= 3:
        print("usage: python -m qabot.routemap <source_root> <app_spec> [python]")
        return 2
    root, spec = Path(argv[0]), argv[1]
    interpreter = argv[2] if len(argv) == 3 else None
    route_map = build_route_map(root, spec, python=interpreter)
    for key, source in sorted(route_map.sources.items()):
        print(f"{key}\n    {source.file}:{source.start}-{source.end}")
    print(f"\n{len(route_map.sources)} routes")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
