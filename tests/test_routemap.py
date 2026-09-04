"""Reading an application's route table, and matching anchors against it.

The Flask adapter is exercised against a hand-built stand-in rather than a real
Flask app, because Flask is not a dependency of qabot and adding one to test a
duck-typed adapter would be paying for the wrong thing. The stand-in reproduces
exactly what the adapter reads -- `url_map.iter_rules()`, `view_functions`, and the
`view_class` Flask leaves on a class-based view -- and the real proof that it works
on real Flask is CTFd, recorded in docs/EVAL.md.

The Starlette side needs no stand-in: FastAPI is already a dependency.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

from qabot._routeprobe import ProbeError, extract_routes, load_app
from qabot.routemap import (
    RouteMap,
    RouteMapError,
    RouteSource,
    build_route_map,
    unavailable_limitation,
)

# --- the Starlette/FastAPI adapter ------------------------------------------


def make_fastapi_app() -> FastAPI:
    app = FastAPI()
    router = APIRouter(prefix="/api/v1")

    @router.get("/challenges/types")
    def challenge_types() -> dict:
        return {}

    @router.post("/challenges/{challenge_id}/attempt")
    def attempt(challenge_id: str) -> dict:
        return {}

    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {}

    return app


def routes_by_key(app: object) -> dict[str, dict]:
    return {f"{entry['method']} {entry['path']}": entry for entry in extract_routes(app)}


def test_router_prefix_is_part_of_the_path() -> None:
    """The decorator says `/challenges/types`; a test calls `/api/v1/challenges/types`.
    Anchoring the former is the defect this module exists to fix."""
    assert "GET /api/v1/challenges/types" in routes_by_key(make_fastapi_app())


def test_handler_resolves_to_its_own_file_and_span() -> None:
    entry = routes_by_key(make_fastapi_app())["POST /api/v1/challenges/{challenge_id}/attempt"]
    _, declared_at = inspect.getsourcelines(make_fastapi_app)

    assert entry["file"] == str(Path(__file__).resolve())
    # The span sits inside this module's factory, decorator line included.
    assert declared_at < entry["start"] < entry["end"]
    assert "def attempt" in Path(__file__).read_text().splitlines()[entry["start"]]


def test_head_is_not_reported_as_a_route() -> None:
    """Starlette answers HEAD for every GET. A workflow never calls it, and recording
    it would claim a handler serves requests nobody wrote."""
    assert "HEAD /health" not in routes_by_key(make_fastapi_app())


def test_an_object_with_no_route_table_is_an_error_not_an_empty_map() -> None:
    with pytest.raises(ProbeError, match="neither a Flask"):
        extract_routes(object())


def test_a_routes_collection_that_declares_no_paths_is_an_error() -> None:
    """datasette's router also has a `routes` list -- of `(regex, view)` tuples. An
    empty result there would be indistinguishable from an app with no routes."""

    class RegexRouter:
        def __init__(self) -> None:
            self.routes = [(r"^/(?P<db>[^/]+)$", print)]

    with pytest.raises(ProbeError, match="not a Starlette router"):
        extract_routes(RegexRouter())


# --- the Flask adapter ------------------------------------------------------


class ChallengeAttempt:
    """Stands in for a Flask-RESTX `Resource`: one class, one method per verb."""

    def post(self) -> dict:
        return {}

    def get(self) -> dict:
        return {}


class Rule:
    """What `url_map.iter_rules()` yields."""

    def __init__(self, rule: str, methods: set[str], endpoint: str) -> None:
        self.rule, self.methods, self.endpoint = rule, methods, endpoint


class FlaskAppStub:
    """Only the two attributes the adapter reads. `view` is what `View.as_view()`
    hands back: a closure defined in flask/views.py, carrying `view_class`."""

    def __init__(self, view_class: type, rules: list[Rule]) -> None:
        def view() -> None:
            raise AssertionError("never called")

        view.view_class = view_class
        self.view_functions = {rule.endpoint: view for rule in rules}
        self.url_map = type("UrlMap", (), {"iter_rules": staticmethod(lambda: rules)})()


def flask_app_stub() -> object:
    return FlaskAppStub(
        ChallengeAttempt,
        [Rule("/api/v1/challenges/attempt", {"POST", "GET", "OPTIONS", "HEAD"}, "att")],
    )


def test_class_based_view_resolves_to_the_method_serving_that_verb() -> None:
    """`view_functions[endpoint]` is a closure inside flask/views.py. Following
    `view_class` to the method is what makes the span mean anything."""
    entries = routes_by_key(flask_app_stub())
    post = entries["POST /api/v1/challenges/attempt"]
    get = entries["GET /api/v1/challenges/attempt"]
    _, post_line = inspect.getsourcelines(ChallengeAttempt.post)

    assert post["file"] == str(Path(__file__).resolve())
    assert post["start"] == post_line
    assert post["start"] != get["start"]


def test_flask_implicit_methods_are_dropped() -> None:
    keys = routes_by_key(flask_app_stub())
    assert not [key for key in keys if key.startswith(("HEAD ", "OPTIONS "))]


def test_a_wrapped_handler_resolves_to_what_it_wraps() -> None:
    """Real handlers are decorated. Locating the wrapper would anchor every route in
    an application to the same few lines of somebody's decorator module."""
    import functools

    @functools.wraps(ChallengeAttempt.post)
    def wrapper(self: object) -> dict:
        return ChallengeAttempt.post(self)

    class Wrapped(ChallengeAttempt):
        post = wrapper

    app = FlaskAppStub(Wrapped, [Rule("/attempt", {"POST"}, "att")])
    _, post_line = inspect.getsourcelines(ChallengeAttempt.post)

    assert extract_routes(app)[0]["start"] == post_line


# --- load_app ---------------------------------------------------------------


def test_a_factory_is_called_and_an_instance_is_not() -> None:
    app = load_app(f"{__name__}:make_fastapi_app")
    assert isinstance(app, FastAPI)
    assert load_app(f"{__name__}:SHARED_APP") is SHARED_APP


SHARED_APP = make_fastapi_app()


@pytest.mark.parametrize("spec", ["nocolon", ":create_app", "module:"])
def test_a_malformed_spec_is_refused(spec: str) -> None:
    with pytest.raises(ProbeError, match="module:attribute"):
        load_app(spec)


def test_a_missing_attribute_names_itself() -> None:
    with pytest.raises(ProbeError, match="no attribute 'nope'"):
        load_app(f"{__name__}:nope")


# --- matching anchors onto the table ----------------------------------------


def demo_map() -> RouteMap:
    source = RouteSource(file="app.py", start=10, end=20)
    return RouteMap(
        sources={
            "GET /api/v1/challenges": source,
            "GET /api/v1/challenges/types": RouteSource(file="app.py", start=30, end=35),
            "GET /api/v1/challenges/{}": RouteSource(file="app.py", start=40, end=50),
            "GET /api/v1/challenges/{}/solves": RouteSource(file="other.py", start=1, end=9),
            "GET /": RouteSource(file="app.py", start=60, end=61),
        }
    )


@pytest.mark.parametrize(
    ("locator", "expected"),
    [
        # a literal path is itself
        ("GET /api/v1/challenges", "GET /api/v1/challenges"),
        # an id a test happened to use
        ("GET /api/v1/challenges/1", "GET /api/v1/challenges/{}"),
        # the seeder's placeholder, named after the test's variable
        ("GET /api/v1/challenges/{chal_id}", "GET /api/v1/challenges/{}"),
        ("GET /api/v1/challenges/1/solves", "GET /api/v1/challenges/{}/solves"),
        # a query selects a representation, not a route
        ("GET /api/v1/challenges?view=admin", "GET /api/v1/challenges"),
        # a static segment beats the slot that would also accept it
        ("GET /api/v1/challenges/types", "GET /api/v1/challenges/types"),
    ],
)
def test_an_anchor_instance_resolves_to_the_pattern_that_serves_it(
    locator: str, expected: str
) -> None:
    assert demo_map().key_for(locator) == expected


@pytest.mark.parametrize(
    "locator",
    [
        "GET /api/v1/nothing",  # no such route
        "POST /api/v1/challenges",  # right path, wrong verb
        "GET /api/v1/challenges/1/hints",  # right prefix, wrong tail
    ],
)
def test_an_anchor_with_nothing_serving_it_resolves_to_nothing(locator: str) -> None:
    assert demo_map().key_for(locator) is None


def test_an_empty_segment_does_not_fill_a_slot() -> None:
    """Otherwise `GET /` matches whatever `/<name>` serves."""
    assert demo_map().key_for("GET /") == "GET /"


def test_a_placeholder_does_not_match_a_literal_segment() -> None:
    """`/challenges/{chal_id}` and `/challenges/types` have the same shape and are
    different endpoints. Only the pattern side may hold a wildcard."""
    narrow = RouteMap(sources={"GET /api/v1/challenges/types": RouteSource("app.py", 1, 2)})
    assert narrow.key_for("GET /api/v1/challenges/{chal_id}") is None


def test_touched_reports_the_routes_whose_handler_lines_changed() -> None:
    assert demo_map().touched({"app.py": {42}}) == {"GET /api/v1/challenges/{}"}


def test_a_change_elsewhere_in_the_file_touches_no_route_directly() -> None:
    assert demo_map().touched({"app.py": {100}}) == set()
    assert demo_map().touched({"unrelated.py": {42}}) == set()


def test_source_for_reaches_the_handler_behind_an_instance() -> None:
    assert demo_map().source_for("GET /api/v1/challenges/7").start == 40
    assert demo_map().source_for("GET /nope") is None


# --- building it ------------------------------------------------------------


TINY_APP = """\
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/api")


@router.get("/widgets/{widget_id}")
def show(widget_id: str) -> dict:
    return {"id": widget_id}


app.include_router(router)
"""


def test_the_probe_runs_under_another_interpreter_and_comes_back_with_a_map(
    tmp_path: Path,
) -> None:
    """End to end through the subprocess: the app is importable only from its own
    working directory, which is the whole reason the probe sets `sys.path[0]`."""
    (tmp_path / "tinyapp.py").write_text(TINY_APP)

    route_map = build_route_map(tmp_path, "tinyapp:app", python=sys.executable)

    assert route_map.sources["GET /api/widgets/{}"] == RouteSource("tinyapp.py", 7, 9)
    assert route_map.limitations == ()


def test_a_failing_probe_raises_with_the_application_s_own_error(tmp_path: Path) -> None:
    (tmp_path / "boom.py").write_text("raise RuntimeError('config is missing')\n")

    with pytest.raises(RouteMapError, match="config is missing"):
        build_route_map(tmp_path, "boom:app", python=sys.executable)


def test_an_app_whose_handlers_live_outside_the_checkout_is_an_error(tmp_path: Path) -> None:
    """An importable app whose routes all resolve into site-packages is not the app in
    this checkout, and a map no diff can ever hit is no better than no map."""
    (tmp_path / "elsewhere.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

    with pytest.raises(RouteMapError, match="not the application in this checkout"):
        build_route_map(tmp_path, "elsewhere:app", python=sys.executable)


def test_in_process_probing_needs_no_interpreter(tmp_path: Path) -> None:
    route_map = build_route_map(Path(__file__).parent, f"{__name__}:make_fastapi_app")
    assert "GET /api/v1/challenges/types" in route_map.sources


def test_a_vendored_dependency_inside_the_checkout_is_not_source(tmp_path: Path) -> None:
    """FastAPI's own `/docs` handler resolves under `source_root` when the virtualenv
    lives there. `anchors.SKIP_DIRS` already draws that line; this reuses it."""
    route_map = build_route_map(Path(__file__).parent, f"{__name__}:make_fastapi_app")
    assert not [source for source in route_map.sources.values() if ".venv" in source.file]


# --- the degraded case ------------------------------------------------------


def test_unavailable_is_empty_and_says_why() -> None:
    route_map = RouteMap.unavailable("datasette's router is not one we can read")

    assert route_map.sources == {}
    assert route_map.limitations == (
        unavailable_limitation("datasette's router is not one we can read"),
    )
    assert "not evidence that no other workflow was put at risk" in route_map.limitations[0]


def test_a_degraded_map_states_itself_on_the_run(tmp_path: Path) -> None:
    """The point of `unavailable`: an empty selection reaches the report with a reason
    attached instead of reading as a clean bill of health."""
    from qabot.llm import DeterministicLLM
    from qabot.models import KnowledgeBase
    from qabot.runner import run

    class NoopDriver:
        def reset(self) -> None: ...

        def execute(self, action: object) -> object:
            raise AssertionError("nothing was selected, so nothing should run")

    report = run(
        kb=KnowledgeBase(repo="acme/shop"),
        driver=NoopDriver(),
        source_root=tmp_path,
        diff_text="",
        llm=DeterministicLLM(),
        route_map=RouteMap.unavailable("the app would not import"),
    )

    assert report.selected == []
    assert report.limitations == [unavailable_limitation("the app would not import")]
