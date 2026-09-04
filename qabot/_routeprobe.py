"""Ask a running application for its own route table. Stdlib only, on purpose.

This file has two callers and one rule. The rule is that it must never import
anything but the standard library and the application under test, because its second
caller is the *customer's* interpreter: qabot cannot import CTFd (Flask, gevent,
SQLAlchemy, a database) and CTFd's virtualenv cannot import qabot, so the only place
the two can meet is a bare script run by `<their python> qabot/_routeprobe.py`. A
`from qabot.models import ...` added here would work in every test and fail on every
real customer -- hence a separate module whose import list can be checked at a glance,
rather than deferred imports inside `routemap.py` that look ordinary and are not.

What it extracts is deliberately raw: the framework's own path template, its methods,
and the handler's absolute file and line span. Normalizing that into anchor
vocabulary happens in `routemap.py`, in qabot's interpreter, where `qabot.anchors`
is importable and there is exactly one definition of what a route string looks like.

Framework support is duck-typed against the attribute each adapter actually reads --
`url_map` + `view_functions` for Flask, `routes` for Starlette/FastAPI. That is the
whole of the "detection": an object that exposes the table we know how to read is one
we can read. Adding a third framework means adding a function that returns the same
list of dicts, and nothing else moves.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys

#: Methods a framework answers on a route's behalf. Anchoring on them would claim a
#: handler serves requests its author never wrote -- Werkzeug adds OPTIONS to every
#: rule in the map, and HEAD to every GET.
IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})


class ProbeError(RuntimeError):
    """The application was reachable but its route table was not."""


def extract_routes(app: object) -> list[dict]:
    """Every HTTP route the app serves, as `{method, path, file, start, end}`.

    Raises rather than returning `[]` for an unrecognized object: an empty route map
    and an unreadable one produce the same (empty) impact selection, and the whole
    point of this work is that those two must never look alike.
    """
    if hasattr(app, "url_map") and hasattr(app, "view_functions"):
        return _flask_routes(app)
    if hasattr(app, "routes"):
        routes = _starlette_routes(app.routes, "")
        if not routes:
            # Duck-typing has a false-positive direction, and this is it: datasette's
            # router also holds a `routes` list, of `(compiled regex, view)` tuples
            # that this walk cannot read a single path out of. Returning [] would make
            # an unreadable router indistinguishable from an app with no routes.
            raise ProbeError(
                f"{type(app).__module__}.{type(app).__name__} has a `routes` collection "
                "but nothing in it declares an HTTP path and method, so it is not a "
                "Starlette router"
            )
        return routes
    raise ProbeError(
        f"{type(app).__module__}.{type(app).__name__} exposes neither a Flask `url_map` "
        "nor a Starlette `routes` collection, so its route table cannot be read"
    )


def _flask_routes(app: object) -> list[dict]:
    """Werkzeug's URL map, resolved through `view_functions` back to source.

    The indirection matters: `view_functions[endpoint]` for a class-based view (every
    Flask-RESTX `Resource`, which is what CTFd's entire API is built from) is a closure
    manufactured by `View.as_view`, and `inspect` on it reports flask/views.py. Flask
    leaves `view_class` on it for exactly this reason, so we walk back to the class and
    then to the method serving this verb -- which narrows the span from "the whole
    resource" to "this handler", and that narrowing is what makes a line-overlap test
    mean something on a 400-line class.
    """
    routes: list[dict] = []
    for rule in app.url_map.iter_rules():
        view = app.view_functions.get(rule.endpoint)
        if view is None:
            continue
        view_class = getattr(view, "view_class", None)
        for method in sorted(set(rule.methods or ()) - IMPLICIT_METHODS):
            target = view
            if view_class is not None:
                target = getattr(view_class, method.lower(), None) or view_class
            located = _locate(target)
            if located is not None:
                routes.append({"method": method, "path": rule.rule, **located})
    return routes


def _starlette_routes(routes: object, prefix: str) -> list[dict]:
    """Starlette's route list, recursing through `Mount` so a mounted sub-app's paths
    come back as the full path a client calls rather than the fragment it was declared
    with. FastAPI bakes `APIRouter(prefix=...)` into `route.path` itself, so the same
    walk covers both composition styles.

    Anything with no `methods` -- a websocket, a static mount -- is skipped: this maps
    what an HTTP workflow can call.
    """
    found: list[dict] = []
    for route in _flattened(routes):
        # `path` is None, not absent, on anything that is not really a route -- a
        # RouteContext wrapping something FastAPI's flattener did not recognize.
        path = prefix + (getattr(route, "path", None) or "")
        children = getattr(route, "routes", None)
        if children:
            found.extend(_starlette_routes(children, path))
            continue
        endpoint = getattr(route, "endpoint", None)
        methods = getattr(route, "methods", None)
        if endpoint is None or not methods:
            continue
        located = _locate(endpoint)
        if located is None:
            continue
        for method in sorted(set(methods) - IMPLICIT_METHODS):
            found.append({"method": method, "path": path, **located})
    return found


def _flattened(routes: object) -> list:
    """`app.routes` with FastAPI's lazily-included routers expanded, if there are any.

    FastAPI used to copy an `include_router`'d route into `app.routes` at include time;
    current versions leave a private `_IncludedRouter` placeholder there and resolve it
    per request. Walking `app.routes` naively therefore finds a modern FastAPI app's
    four built-in documentation routes and *nothing else* -- measured against langflow,
    which mounts its entire API through three `include_router` calls. `openapi.utils`
    faces the same problem and solves it with `routing.iter_route_contexts`, so we use
    the framework's own flattener rather than reimplementing its prefix arithmetic
    against private attributes that will move again.

    ImportError alone is caught: an app that is Starlette but not FastAPI has nothing
    to flatten, which is not a failure. Anything else the flattener raises is news.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return list(routes)
    return list(iter_route_contexts(routes))


def _locate(target: object) -> dict | None:
    """Absolute file and inclusive line span of `target`, or None if it has no source.

    `inspect.unwrap` first, because a handler in real code is wrapped: CTFd's
    `@during_ctf_time_only`, `@require_verified_emails` and friends each return a new
    function, and locating the outermost one anchors every route in the application to
    the same few lines of the decorator module -- which would resolve, look healthy,
    and be wrong. A decorator that does not set `__wrapped__` still defeats this; that
    is a known and visible failure (spans land in the decorator's file), not a silent
    one.

    Returns None rather than raising for a builtin or a C-implemented view: one route
    we cannot place is not a reason to abandon the other 248.
    """
    try:
        unwrapped = inspect.unwrap(target)
        file = inspect.getsourcefile(unwrapped)
        lines, start = inspect.getsourcelines(unwrapped)
    except (OSError, TypeError, ValueError):
        return None
    if file is None:
        return None
    return {"file": os.path.abspath(file), "start": start, "end": start + len(lines) - 1}


def load_app(spec: str) -> object:
    """`"CTFd:create_app"` or `"demo.app:app"` -> the application object.

    Accepts a factory or an instance without a flag distinguishing them: an object that
    already exposes a route table is the app, anything else callable is called to
    produce one. A flag here would be one more thing for a customer to get wrong in a
    config file, diagnosed by an error message far from the mistake.
    """
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ProbeError(f"app spec must be 'module:attribute', got {spec!r}")
    module = importlib.import_module(module_name)
    try:
        obj = getattr(module, attribute)
    except AttributeError as exc:
        raise ProbeError(f"{module_name!r} has no attribute {attribute!r}") from exc
    if hasattr(obj, "url_map") or hasattr(obj, "routes"):
        return obj
    if callable(obj):
        return obj()
    raise ProbeError(f"{spec!r} is neither an application nor a factory for one")


def main(argv: list[str]) -> int:
    """`python _routeprobe.py <app_spec> <output_path>`, run from the app's root.

    Output goes to a file the caller names, not to stdout, because importing a real
    application prints: CTFd announces gevent monkey-patching and every plugin it
    loads. Fishing our JSON back out of that would be a parsing problem we do not have
    to have. `sys.path[0]` is *replaced* rather than prepended -- leaving qabot's own
    package directory ahead of the app's root would let `import store` inside the
    customer's code find qabot's module instead of theirs.
    """
    if len(argv) != 2:
        raise ProbeError(f"expected <app_spec> <output_path>, got {argv!r}")
    spec, output_path = argv
    sys.path[0] = os.getcwd()
    routes = extract_routes(load_app(spec))
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(routes, handle)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main(sys.argv[1:]))
