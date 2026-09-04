"""HTTP execution substrate.

WHY the ok/status split matters: `Observation.ok` records whether the *interaction
completed*, never whether the response was a success status. A 402 is a completed
interaction (ok=True) that a verifier may well judge correct; a connection refused
is not (ok=False) and can only ever be BLOCKED. Collapsing the two would let an
unreachable app masquerade as a failing app, which is the single most expensive
mistake a QA bot can make.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import httpx

from qabot.drivers.base import Action, DriverError, Observation

#: Carried on the run when the caller declared the app has no reset endpoint.
NO_RESET_LIMITATION = (
    "the app has no reset endpoint, so workflows ran in sequence against whatever "
    "state earlier ones left behind: a finding here may depend on that accumulated "
    "state rather than on the diff, and a run of the same workflows in another order "
    "may not reproduce it"
)

#: Stands in for a credential wherever evidence records one. Part of the evidence
#: contract with the runner and `qabot.testgen`, which must not replay it.
REDACTED = "<redacted>"

#: Substrings that mark a header name as carrying a credential, matched against the
#: lowercased name so `X-Api-Key` and `X-Auth-Token` are caught next to `Authorization`.
#: Deliberately over-broad: over-redacting costs a reader one header value they did not
#: need, under-redacting costs the customer a rotated credential and a PR comment they
#: have to go delete.
SECRET_HEADER_MARKERS: tuple[str, ...] = (
    "auth",
    "cookie",
    "credential",
    "key",
    "password",
    "secret",
    "session",
    "token",
)


class HttpDriver:
    """Drives a running HTTP app. Accepts an injected client so the same code path
    runs in-process against an ASGI app in tests and over the network in a real run.

    `reset_path=None` says the app has no reset capability. It is a decision the
    caller makes at construction, never one a failed request makes for us -- see
    `reset`.

    `headers` and `cookies` are credentials somebody else already obtained. Every
    interesting workflow in a real application sits behind a login, and this driver
    deliberately does not know how to perform one: a login is a form post here, a
    CSRF nonce scraped out of HTML there, an OAuth redirect somewhere else. Guessing
    at that per application is a project; accepting the result of it is an argument.
    So the caller authenticates however their app requires and hands us what came
    back. That is the entire auth story, and it is meant to stay that way.

    They are set on the client rather than merged per request, so httpx does the
    merging and a per-action `headers` param beats a static header of the same name
    case-insensitively -- which a dict merge here would not, and two `Authorization`
    headers on one request is the kind of silent wrongness that costs an afternoon.
    The cost is that we mutate a client we may not own: an injected client comes back
    carrying our headers and cookies, and an injector who reuses it will send them.

    Cookies persist across steps. `httpx.Client` keeps a cookie jar, so a `Set-Cookie`
    from step 1 goes back out on step 2 -- pinned by a test rather than trusted. They
    do not persist across *runs*: `cli.cmd_run` builds a driver, and with it a client,
    per run. Nor can this driver log in to fill that jar itself -- it sends JSON bodies
    only, and most login forms are urlencoded. Hence `--cookie`.

    One sharp edge there, measured rather than guessed at: an injected cookie enters the
    jar with no domain, so an app that re-issues a `Set-Cookie` of the same name gets a
    second entry rather than replacing the first, and both go out on the next request.
    Pinning the injected one to the base URL's host would fix that and break the
    in-process ASGI case, where the effective host is not the one in `base_url` -- so it
    is left alone and stated instead. A caller who hits it can pass the credential as
    `--header 'Cookie: ...'`, which suppresses the jar entirely for that request.

    Evidence is redacted where it is recorded, not where it is rendered. An
    `Observation.evidence` dict is copied into findings, serialized into the run
    report, written into generated tests and pasted verbatim into the verifier's LLM
    prompt; redacting in the reporter would leave the token in the other four. So the
    recorded request names every header and every cookie the request carried and gives
    the value of neither -- names, because "we sent a session cookie and still got a
    302" and "we sent nothing" are different bugs and a reader has to be able to tell
    them apart; values, never. What that does not cover, stated because a half-known
    guarantee is worse than none: a secret the caller put in a URL, and a token the
    *application* hands back in a response body, which is recorded as-is because the
    verifier grades against it.
    """

    name = "http"

    def __init__(
        self,
        base_url: str,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        reset_path: str | None = "/reset",
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
    ):
        self.base_url = base_url
        self._client = (
            client if client is not None else httpx.Client(base_url=base_url, timeout=timeout)
        )
        #: Only close what we opened; an injected client belongs to its injector.
        self._owns_client = client is None
        self._reset_path = reset_path
        self._headers = dict(headers or {})
        #: Anything the caller set for the whole run is treated as a credential in
        #: evidence, whatever it is called. We cannot tell an `Accept` from an API key
        #: by name, and only one of those two guesses is expensive to get wrong.
        self._injected_names = {name.lower() for name in self._headers}
        if self._headers:
            self._client.headers.update(self._headers)
        if cookies:
            self._client.cookies.update(dict(cookies))
        #: What this driver could not guarantee about the run. The runner reads it and
        #: the reporter prints it; opting out of reset is stated, never swallowed.
        self.limitations: list[str] = [] if reset_path is not None else [NO_RESET_LIMITATION]

    def reset(self) -> None:
        """Return the app to a known state, if it has one to return to.

        Loud on failure, because a run that starts from an unknown state produces
        findings nobody can trust. That is exactly why opting out is a constructor
        argument and not a rescued exception: no third-party app has a /reset
        endpoint, and treating its 404 as "fine" would turn every foreign run into
        the untrustworthy kind without anyone deciding to. `reset_path=None` is the
        caller deciding to, once, in the open -- and it costs them a stated
        limitation on the whole run rather than silence.
        """
        if self._reset_path is None:
            return
        try:
            response = self._client.post(self._reset_path)
        except httpx.RequestError as exc:
            raise DriverError(
                f"reset failed: could not reach {self.base_url}{self._reset_path}: {exc}"
            ) from exc
        if not response.is_success:
            raise DriverError(
                f"reset failed: POST {self._reset_path} returned {response.status_code}"
            )

    def _is_credential(self, name: str) -> bool:
        lowered = name.lower()
        return lowered in self._injected_names or any(
            marker in lowered for marker in SECRET_HEADER_MARKERS
        )

    def _recorded_headers(self, headers: Mapping[str, str] | None) -> dict[str, str] | None:
        """What to record about the headers a request carried.

        Names are kept and values dropped, rather than the header being omitted
        outright: a developer reading a 401 in this report needs to know whether we
        authenticated at all, and "there was an Authorization header" answers that
        without printing the token into a PR comment.
        """
        merged = {**self._headers, **(headers or {})}
        if not merged:
            return None
        return {
            name: REDACTED if self._is_credential(name) else value for name, value in merged.items()
        }

    def _recorded_cookies(self) -> dict[str, str] | None:
        """The names of the cookies this request will carry, and none of their values.

        Read off the jar rather than off the constructor argument, so a session the
        *app* handed us mid-run is reported too: by the time a workflow fails, which
        credentials were in play is the first question, and "the caller passed none"
        is not an answer to it.
        """
        names = list(self._client.cookies)
        return {name: REDACTED for name in names} if names else None

    def execute(self, action: Action) -> Observation:
        if action.kind != "http":
            raise DriverError(f"HttpDriver cannot execute action kind {action.kind!r}")

        method = str(action.params["method"]).upper()
        path = str(action.params["path"])
        payload = action.params.get("json")
        headers = action.params.get("headers")

        request: dict[str, object] = {"method": method, "path": path, "json": payload}
        # The static headers are recorded even though they were never in `params`:
        # what the app saw is the fact worth keeping, and a reader who cannot tell an
        # authenticated 403 from an unauthenticated one has been handed a puzzle.
        recorded = self._recorded_headers(headers)  # type: ignore[arg-type]
        if recorded:
            request["headers"] = recorded
        cookies = self._recorded_cookies()
        if cookies:
            request["cookies"] = cookies

        started = time.perf_counter()
        try:
            response = self._client.request(method, path, json=payload, headers=headers)
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return Observation(
                ok=False,
                summary=f"{method} {path} -> transport error: {type(exc).__name__}",
                evidence={
                    "status": None,
                    "json": None,
                    "text": "",
                    "request": request,
                    "elapsed_ms": elapsed_ms,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        elapsed_ms = (time.perf_counter() - started) * 1000

        try:
            body = response.json()
        except ValueError:
            body = None

        return Observation(
            ok=True,
            summary=f"{method} {path} -> {response.status_code}",
            evidence={
                "status": response.status_code,
                "json": body,
                "text": response.text,
                "request": request,
                "elapsed_ms": elapsed_ms,
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
