"""Execute an approved local startup plan and retain browser evidence."""

from __future__ import annotations

import codecs
import json
import os
import re
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus, urlsplit

import httpx

from qabot.drivers.base import Action
from qabot.drivers.browser import BrowserDriver
from qabot.journeys.approval import require_approval
from qabot.journeys.credentials import has_url_credentials, is_credential_name, reference_name
from qabot.journeys.llm import journey_provider
from qabot.journeys.models import JourneyResult, ReviewPlan, StepOutcome, StepResult
from qabot.journeys.ownership import ensure_endpoint_available, require_owned_endpoint
from qabot.journeys.report import write_report
from qabot.journeys.walker import WalkCancelled, redact_data, redact_text, walk
from qabot.models import Outcome

STARTUP_TIMEOUT = 180.0
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_NAME = re.compile(r"PASSWORD|PASSWD|TOKEN|API_?KEY|SECRET|PRIVATE_?KEY", re.IGNORECASE)
_ARROW_KEYS = {"ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"}
_MOVEMENT_KEYS = _ARROW_KEYS | {f"Shift+{key}" for key in _ARROW_KEYS}


def resolve_environment(startup, *, env_file: Path | None = None):
    source_env = dict(os.environ)
    required = set(startup.required_env)
    for value in startup.env.values():
        required.update(_REFERENCE.findall(value))
    if env_file is not None:
        from dotenv import dotenv_values

        if not Path(env_file).is_file():
            raise ValueError(f"Environment file does not exist: {env_file}")
        values = dotenv_values(env_file, interpolate=False)
        for name in required:
            if values.get(name):
                source_env[name] = values[name]
    missing = sorted(name for name in required if not source_env.get(name))
    if missing:
        raise ValueError("Missing required environment variables: " + ", ".join(missing))
    env = dict(source_env)
    for key, value in startup.env.items():
        env[key] = _REFERENCE.sub(lambda match: source_env[match[1]], value)
    secret_values = [source_env[name] for name in sorted(required) if source_env.get(name)]
    return env, {
        "required": sorted(required),
        "supplied": dict(startup.env),
        "observed": {},
        "required_available": {name: True for name in sorted(required)},
        "limitations": [
            "Supplied environment is not proof of effective runtime configuration.",
            "The child process inherits the operator environment; values are not exported.",
        ],
    }, secret_values


def _validate_startup_env_literals(startup) -> None:
    for key, value in startup.env.items():
        if value and reference_name(value) is None and (
            is_credential_name(key) or has_url_credentials(value)
        ):
            raise ValueError(
                f"startup.env.{key} must use an environment reference such as ${{{key}}}"
            )


class JourneyBrowserDriver(BrowserDriver):
    def __init__(self, *args, env=None, secret_values=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.env = env or {}
        self._secrets = set(secret_values)
        self._application_origin = self._origin(self.base_url)
        self._navigation_blocked = False
        self._page.context.route("**/*", self._guard_navigation)

    def redact(self, text):
        return redact_text(text, self._secrets)

    @staticmethod
    def _origin(url):
        parsed = urlsplit(url)
        port = parsed.port or {"http": 80, "https": 443}.get(parsed.scheme)
        return parsed.scheme, parsed.hostname, port

    def _guard_navigation(self, route):
        request = route.request
        if request.is_navigation_request():
            try:
                top_level = request.frame.parent_frame is None
            except Exception:  # noqa: BLE001 -- Playwright can expose requests before frames exist.
                top_level = True  # A popup can request its document before its frame exists.
            if top_level and self._origin(request.url) != self._application_origin:
                self._navigation_blocked = True
                route.abort("blockedbyclient")
                return
        route.fallback()

    def _require_application_origin(self, *, allow_blank=False):
        if self._navigation_blocked:
            raise ValueError("Cross-origin browser navigation was blocked")
        if allow_blank and self._page.url == "about:blank":
            return
        if self._origin(self._page.url) != self._application_origin:
            raise ValueError("Browser interaction requires the reviewed application origin")

    def _locate(self, params):
        scope = self._page
        if params.get("within_role"):
            scope = scope.get_by_role(
                str(params["within_role"]), name=str(params.get("within_name", "")), exact=True
            )
        return scope.get_by_role(str(params["role"]), name=str(params.get("name", "")), exact=True)

    def execute(self, action):
        original = dict(action.params)
        params = dict(original)
        if params.get("op") == "press":
            key = str(params.get("key", ""))
            repeat = params.get("repeat", 1)
            if type(repeat) is not int or not 1 <= repeat <= 30:
                raise ValueError("press repeat must be an integer between 1 and 30")
            if repeat > 1 and key not in _MOVEMENT_KEYS:
                raise ValueError("press repeat greater than one is allowed only for arrow keys")
            if key not in _MOVEMENT_KEYS | {"Enter", "Space", "Escape", "Tab"}:
                raise ValueError("Unsupported browser key")
        if params.get("op") == "wait":
            timeout = params.get("timeout_ms", 30000)
            if type(timeout) is not int or not 1 <= timeout <= 60000:
                raise ValueError("wait timeout_ms must be an integer between 1 and 60000")
            if params.get("state", "visible") not in {"visible", "hidden", "enabled"}:
                raise ValueError("wait state must be visible, hidden, or enabled")
        self._require_application_origin(allow_blank=params.get("op") in {"goto", "read"})
        value = str(params.get("value", ""))
        references = _REFERENCE.findall(value)
        for name in references:
            if not self.env.get(name):
                raise ValueError(f"Browser input requires environment variable {name}")
            self._secrets.add(self.env[name])
        if references:
            if any(_SECRET_NAME.search(name) for name in references) and (
                params.get("op") != "fill"
                or not self._locate(params).evaluate(
                    "element => element.tagName === 'INPUT' && element.type === 'password'"
                )
            ):
                raise ValueError("Secret environment references require a masked password input")
            params["value"] = _REFERENCE.sub(lambda m: self.env[m[1]], value)
        if params.get("op") == "goto":
            path = str(params.get("path", ""))
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError("Browser navigation must use an application-relative path")
        if params.get("op") == "wait":
            started = time.perf_counter()
            state = params.get("state", "visible")
            try:
                locator = self._locate(params)
                if state == "enabled":
                    from playwright.sync_api import expect

                    expect(locator).to_be_enabled(timeout=timeout)
                else:
                    locator.wait_for(state=state, timeout=timeout)
                obs = self._observe(
                    True,
                    f"wait for {self._describe(params)} to be {state}",
                    "wait",
                    params,
                    started,
                )
            except Exception as exc:  # noqa: BLE001 -- preserve timed-out waits as browser evidence.
                obs = self._observe(False, "wait failed", "wait", params, started, str(exc))
        elif params.get("op") == "press":
            started = time.perf_counter()
            try:
                locator = self._locate(params)
                keyboard_target = ""
                if locator.count() > 1:
                    candidates = [
                        index
                        for index in range(locator.count())
                        if locator.nth(index).is_visible()
                        and locator.nth(index).is_enabled()
                        and locator.nth(index).evaluate("element => element.tabIndex >= 0")
                    ]
                    if len(candidates) == 1:
                        locator = locator.nth(candidates[0])
                        keyboard_target = " (unique visible enabled sequential tab stop)"
                for _ in range(repeat):
                    self._require_application_origin()
                    locator.press(key, timeout=self._timeout_ms)
                repetitions = f" {repeat} times" if repeat > 1 else ""
                obs = self._observe(
                    True,
                    f"press {key}{repetitions} on {self._describe(params)}{keyboard_target}",
                    "press",
                    params,
                    started,
                )
            except Exception as exc:  # noqa: BLE001 -- Playwright failures are recorded action evidence.
                obs = self._observe(False, "press failed", "press", params, started, str(exc))
        else:
            obs = super().execute(Action(kind=action.kind, params=params))
        self._require_application_origin(allow_blank=params.get("op") == "read")
        if references:
            obs.summary = f"fill {self._describe(original)} with environment reference {value}"
        return redact_data(obs, self.redact)


def _healthy(url):
    try:
        return httpx.get(url, timeout=2, follow_redirects=False).is_success
    except httpx.HTTPError:
        return False


def _process_group_members(pgid: int) -> list[str]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat="],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not inspect process group {pgid}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"ps exited {result.returncode}"
        raise RuntimeError(f"could not inspect process group {pgid}: {detail}")
    if not result.stdout.strip():
        raise RuntimeError(f"could not inspect process group {pgid}: ps returned no rows")
    members = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            raise RuntimeError(f"could not inspect process group {pgid}: malformed ps row")
        try:
            pid = int(parts[0])
            member_pgid = int(parts[1])
        except ValueError:
            raise RuntimeError(f"could not inspect process group {pgid}: malformed ps row")
        if member_pgid == pgid:
            members.append(f"{pid} {parts[2]}")
    return members


def _stop(process):
    diagnostics = []
    if process is None:
        return diagnostics
    sigkill_error = None
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        # A later SIGKILL/wait can still verify cleanup; report only unresolved final failures.
        pass
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        pass
    # A shell can exit while its children ignore SIGTERM. Always finish the group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        sigkill_error = exc
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        diagnostics.append(f"process group {process.pid} did not exit after SIGKILL: {exc}")
    if sigkill_error is not None:
        try:
            members = _process_group_members(process.pid)
        except RuntimeError as exc:
            diagnostics.append(f"SIGKILL process group {process.pid} failed: {sigkill_error}; {exc}")
        else:
            if members:
                sample = "; ".join(members[:5])
                diagnostics.append(
                    f"SIGKILL process group {process.pid} failed: {sigkill_error}; "
                    f"surviving members: {sample}"
                )
    return diagnostics


def _secret_variants(secrets):
    return {
        variant
        for secret in secrets
        if secret
        for variant in (
            str(secret),
            json.dumps(str(secret))[1:-1],
            json.dumps(str(secret), ensure_ascii=False)[1:-1],
            quote(str(secret), safe=""),
            quote_plus(str(secret)),
        )
    }


def _redaction_overlap_size(secrets):
    longest = max((len(variant) for variant in _secret_variants(secrets)), default=0)
    return max(0, longest - 1)


def _next_secret_variant_match(text, variants, limit):
    best: tuple[int, str] | None = None
    for variant in variants:
        index = text.find(variant)
        if index == -1:
            continue
        if index >= limit:
            continue
        if best is None or index < best[0] or (index == best[0] and len(variant) > len(best[1])):
            best = (index, variant)
    return best


def _capture_process_output(process, log_path, *, redact, secrets):
    variants = sorted(_secret_variants(secrets), key=len, reverse=True)
    overlap_size = _redaction_overlap_size(secrets)
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    with Path(log_path).open("w", encoding="utf-8") as log:
        while True:
            chunk = process.stdout.read(8192)
            if not chunk:
                break
            pending += decoder.decode(chunk)
            if overlap_size == 0:
                log.write(redact(pending))
                pending = ""
            else:
                while len(pending) > overlap_size + 8192:
                    safe_limit = len(pending) - overlap_size
                    match = _next_secret_variant_match(pending, variants, safe_limit)
                    if match is None:
                        safe = pending[:safe_limit]
                        pending = pending[safe_limit:]
                        log.write(redact(safe))
                        continue
                    index, variant = match
                    if index:
                        log.write(redact(pending[:index]))
                    log.write("[REDACTED]")
                    pending = pending[index + len(variant) :]
            log.flush()
        pending += decoder.decode(b"", final=True)
        if pending:
            log.write(redact(pending))
            log.flush()


def _start_log_thread(process, log_path, *, redact, secrets):
    capture_errors = []

    def capture():
        try:
            _capture_process_output(process, log_path, redact=redact, secrets=secrets)
        except Exception as exc:  # noqa: BLE001 -- surface lost diagnostics to the runner.
            capture_errors.append(exc)

    thread = threading.Thread(
        target=capture,
        daemon=True,
    )
    thread.capture_errors = capture_errors
    thread.start()
    return thread


def _run_command(command, *, cwd, env, log_path, log_ref, redact, secrets, label):
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_thread = _start_log_thread(process, log_path, redact=redact, secrets=secrets)
    primary_error = None
    try:
        try:
            returncode = process.wait(timeout=STARTUP_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            primary_error = RuntimeError(f"{label} timed out; inspect {log_ref}")
            primary_error.__cause__ = exc
        except BaseException as exc:  # noqa: BLE001 -- cleanup before preserving cancellation.
            primary_error = exc
        else:
            if returncode:
                primary_error = RuntimeError(
                    f"{label} exited with status {returncode}; inspect {log_ref}"
                )
        if primary_error is not None:
            raise primary_error
    finally:
        cleanup_diagnostics = _stop(process)
        log_thread.join(timeout=5)
        if not isinstance(primary_error, KeyboardInterrupt):
            if cleanup_diagnostics:
                raise RuntimeError(
                    f"{label} cleanup incomplete for {log_ref}: "
                    + "; ".join(cleanup_diagnostics)
                )
            capture_errors = getattr(log_thread, "capture_errors", [])
            if capture_errors:
                raise RuntimeError(
                    f"{label} output capture failed for {log_ref}"
                ) from capture_errors[0]
            if log_thread.is_alive():
                raise RuntimeError(f"{label} output capture did not finish for {log_ref}")


def _blocked(journey, reason):
    return JourneyResult(
        journey=journey,
        outcome=Outcome.BLOCKED,
        why=reason,
        steps=[
            StepResult(index=i, do=s.do, see=s.see, outcome=StepOutcome.NOT_REACHED, reason=reason)
            for i, s in enumerate(journey.steps)
        ],
    )


def _block_result(result, reason):
    if result.outcome == Outcome.BLOCKED:
        result.why = f"{result.why}; {reason}" if result.why else reason
        return
    prior = result.why or f"completed with {result.outcome.value}"
    result.outcome = Outcome.BLOCKED
    result.why = f"{reason}; completed result was {prior}"


def _block_pass_results(results, reason):
    for result in results:
        if result.outcome == Outcome.PASS:
            _block_result(result, reason)


def run_plan(
    plan_path: Path,
    out: Path,
    *,
    headed: bool,
    channel: str,
    selected: list[str] | None = None,
    llm=None,
    env_file: Path | None = None,
) -> int:
    approval = require_approval(plan_path)
    plan = ReviewPlan.model_validate_json(Path(plan_path).read_text())
    journeys = [j for j in plan.journeys if selected is None or j.id in selected]
    if not journeys or (selected and set(selected) - {j.id for j in journeys}):
        raise ValueError(
            "Selection must name existing journey IDs and contain at least one journey"
        )
    _validate_startup_env_literals(plan.startup)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "approval": approval,
        "plan": plan.model_dump(mode="json"),
        "channel": channel,
        "configuration": {},
        "limitations": [
            (
                "Screenshots and video are not automatically redacted. A trusted application must not "
                "reflect credentials into visible content; text/model redaction cannot protect those pixels."
            )
        ],
        "model": getattr(llm, "name", "claude-cli/sonnet"),
    }
    results = []
    process = None
    log_thread = None
    cancelled = False
    secrets = []

    def persist():
        redact = lambda text: redact_text(text, secrets)
        safe_metadata = redact_data(metadata, redact)
        safe_metadata["plan"] = redact_data(plan, redact).model_dump(mode="json")
        write_report(out, safe_metadata, [redact_data(result, redact) for result in results])

    try:
        if plan.unresolved:
            raise ValueError("Unresolved plan requirements: " + "; ".join(plan.unresolved))
        env, metadata["configuration"], secrets = resolve_environment(
            plan.startup, env_file=env_file
        )
        redact = lambda text: redact_text(text, secrets)
        metadata["configuration"]["logs"] = {"startup": "startup.log"}
        repo = Path(plan.repo)
        if not repo.is_absolute():
            repo = Path(plan_path).resolve().parent / repo
        cwd = Path(plan.startup.cwd)
        if not cwd.is_absolute():
            cwd = repo / cwd
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        expected = subprocess.run(
            ["git", "rev-parse", plan.head], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.strip()
        if revision != expected:
            raise ValueError("Target checkout HEAD does not match the reviewed head revision")
        metadata["revision"] = revision
        metadata["worktree_status"] = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if metadata["worktree_status"]:
            metadata["limitations"].append(
                "Target has tracked local changes; revision alone does not identify tested source."
            )
        origin = urlsplit(plan.startup.health_url)
        if origin.scheme not in {"http", "https"} or origin.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Startup health URL must address the local application")
        ensure_endpoint_available(plan.startup.health_url)

        for index, command in enumerate(plan.startup.setup_commands, start=1):
            log_ref = f"setup-{index:02d}.log"
            metadata["configuration"]["logs"][f"setup-{index:02d}"] = log_ref
            _run_command(
                command,
                cwd=cwd,
                env=env,
                log_path=out / log_ref,
                log_ref=log_ref,
                redact=redact,
                secrets=secrets,
                label=f"setup command {index}",
            )
        ensure_endpoint_available(plan.startup.health_url)
        print(f"Starting application in {cwd}", flush=True)
        process = subprocess.Popen(
            plan.startup.command,
            shell=True,
            cwd=cwd,
            env=env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_thread = _start_log_thread(
            process,
            out / "startup.log",
            redact=redact,
            secrets=secrets,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while not _healthy(plan.startup.health_url):
            if process.poll() is not None:
                raise RuntimeError("Application exited before readiness; inspect startup.log")
            if time.monotonic() >= deadline:
                raise RuntimeError("Application readiness timed out; inspect startup.log")
            time.sleep(0.5)
        require_owned_endpoint(plan.startup.health_url, process)
        metadata["configuration"]["observed"]["health_url"] = plan.startup.health_url
        llm = llm or journey_provider()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel=channel, headless=not headed)
            try:
                for index, journey in enumerate(journeys):
                    print(f"[{index + 1}/{len(journeys)}] {journey.title}", flush=True)
                    artifacts = out / f"journey-{index + 1:02d}"
                    artifacts.mkdir()
                    if plan.startup.reset_command:
                        log_ref = f"journey-{index + 1:02d}-reset.log"
                        metadata["configuration"]["logs"][f"{journey.id}-reset"] = log_ref
                        _run_command(
                            plan.startup.reset_command,
                            cwd=cwd,
                            env=env,
                            log_path=out / log_ref,
                            log_ref=log_ref,
                            redact=redact,
                            secrets=secrets,
                            label=f"reset command for {journey.id}",
                        )
                    else:
                        metadata["limitations"].append(
                            f"{journey.id}: fresh browser context; persistent application state is not reset."
                        )
                    require_owned_endpoint(plan.startup.health_url, process)
                    context = browser.new_context(
                        viewport={"width": 1440, "height": 1000},
                        record_video_dir=str(artifacts),
                        record_video_size={"width": 1440, "height": 1000},
                    )
                    result = None
                    page = None
                    try:
                        page = context.new_page()
                        driver = JourneyBrowserDriver(
                            f"{origin.scheme}://{origin.netloc}",
                            page,
                            artifacts,
                            timeout_ms=10000,
                            reset_path=None,
                            env=env,
                            secret_values=secrets,
                        )
                        result = walk(journey, driver, page, llm, artifacts, env=env)
                    except WalkCancelled as exc:
                        result = exc.result
                        cancelled = True
                    except KeyboardInterrupt:
                        result = _blocked(journey, "Execution cancelled by operator")
                        cancelled = True
                    except Exception as exc:  # noqa: BLE001 -- retain browser initialization failures.
                        result = _blocked(
                            journey,
                            f"Browser execution could not complete: {type(exc).__name__}: {exc}",
                        )
                    results.append(result)
                    context_closed = False
                    try:
                        context.close()
                        context_closed = True
                    except KeyboardInterrupt:
                        _block_result(result, "Browser context cleanup was cancelled")
                        cancelled = True
                    except Exception as exc:  # noqa: BLE001 -- preserve completed result evidence.
                        _block_result(
                            result, f"Browser context cleanup failed: {type(exc).__name__}: {exc}"
                        )
                    try:
                        if not context_closed:
                            raise RuntimeError("browser context cleanup did not complete")
                        if page is None:
                            raise RuntimeError("Page was not created")
                        video = Path(page.video.path())
                        if not video.is_file() or video.stat().st_size == 0:
                            raise RuntimeError("Recording missing or empty")
                        result.video = str(video)
                    except Exception as exc:  # noqa: BLE001 -- missing video must block the result.
                        _block_result(result, f"Required video unavailable: {exc}")
                    persist()
                    print(
                        f"  {result.outcome.value.upper()}: {result.why or 'All expected observations held'}",
                        flush=True,
                    )
                    if cancelled:
                        results.extend(
                            _blocked(j, "Not reached: execution cancelled by operator")
                            for j in journeys[len(results) :]
                        )
                        break
            finally:
                try:
                    browser.close()
                except KeyboardInterrupt:
                    cancelled = True
                    metadata["limitations"].append("Browser cleanup was cancelled.")
                except Exception as exc:  # noqa: BLE001 -- cleanup failure belongs in the report.
                    metadata["limitations"].append(
                        f"Browser cleanup failed: {type(exc).__name__}: {exc}"
                    )
    except KeyboardInterrupt:
        cancelled = True
        results.extend(
            _blocked(j, "Execution cancelled by operator") for j in journeys[len(results) :]
        )
    except Exception as exc:  # noqa: BLE001 -- persist completed results on any execution failure.
        reason = f"Execution blocked: {type(exc).__name__}: {exc}"
        results.extend(_blocked(j, reason) for j in journeys[len(results) :])
    finally:
        cleanup_diagnostics = []
        try:
            cleanup_diagnostics = _stop(process)
        except Exception as exc:  # noqa: BLE001 -- final report must retain cleanup diagnostics.
            cleanup_diagnostics = [f"application process cleanup raised {type(exc).__name__}: {exc}"]
        if cleanup_diagnostics:
            reason = "Application cleanup incomplete: " + "; ".join(cleanup_diagnostics)
            metadata.setdefault("cleanup", {})["application"] = cleanup_diagnostics
            metadata["limitations"].append(reason)
            _block_pass_results(results, reason)
        if log_thread:
            startup_log_diagnostics = []
            try:
                log_thread.join(timeout=5)
                capture_errors = getattr(log_thread, "capture_errors", [])
                for error in capture_errors:
                    startup_log_diagnostics.append(f"startup log capture failed: {error}")
                alive = log_thread.is_alive()
                if alive:
                    startup_log_diagnostics.append("startup log capture did not finish")
            except Exception as exc:  # noqa: BLE001 -- preserve final report with cleanup diagnostic.
                startup_log_diagnostics.append(
                    f"startup log finalization raised {type(exc).__name__}: {exc}"
                )
            if startup_log_diagnostics:
                reason = "Application output capture incomplete: " + "; ".join(
                    startup_log_diagnostics
                )
                metadata.setdefault("cleanup", {})["startup_log"] = [reason]
                metadata["limitations"].append(reason)
                _block_pass_results(results, reason)
        metadata["finished_at"] = datetime.now(UTC).isoformat()
        metadata["cancelled"] = cancelled
        persist()
    if cancelled:
        return 130
    if any(r.outcome == Outcome.FAIL for r in results):
        return 1
    return 2 if any(r.outcome == Outcome.BLOCKED for r in results) else 0
