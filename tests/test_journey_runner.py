import json
import os
import sys
import types
from pathlib import Path

import pytest

from qabot.journeys.approval import ApprovalError, approve_plan
from qabot.journeys.models import (
    Journey,
    JourneyResult,
    JourneyStep,
    ReviewPlan,
    StartupPlan,
    StepOutcome,
    StepResult,
)
from qabot.journeys.runner import resolve_environment, run_plan
from qabot.models import Finding, Outcome, Severity
from tests.test_journey_walker import Decisions


def make_plan(tmp_path, port):
    plan = ReviewPlan(
        repo=str(Path(__file__).resolve().parents[1]),
        base="HEAD",
        head="HEAD",
        description="Local page",
        startup=StartupPlan(
            command=f"{sys.executable} -m http.server {port} --bind 127.0.0.1",
            cwd=str(tmp_path),
            health_url=f"http://127.0.0.1:{port}/",
        ),
        journeys=[
            Journey(
                id="home",
                title="Home",
                persona="reviewer",
                steps=[JourneyStep(do="Open the application", see="Directory listing")],
            )
        ],
    )
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json(indent=2))
    approve_plan(path, "automated test, not human review")
    return path


def test_environment_resolves_references_without_changing_parent(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret-value")
    startup = StartupPlan(
        command="app",
        cwd=".",
        health_url="http://localhost",
        env={"TOKEN": "${TEST_API_KEY}", "RESTRICTED": "true"},
        required_env=["TEST_API_KEY"],
    )
    env, record, _ = resolve_environment(startup)
    assert env["TOKEN"] == "secret-value"
    assert record["supplied"]["TOKEN"] == "${TEST_API_KEY}"
    assert "secret-value" not in json.dumps(record)
    assert "TOKEN" not in os.environ
    assert record["observed"] == {}  # Supplied is not runtime-verified.


def test_missing_environment_fails_explicitly(monkeypatch):
    monkeypatch.delenv("NO_SUCH_SECRET", raising=False)
    startup = StartupPlan(
        command="app", cwd=".", health_url="http://localhost", env={"TOKEN": "${NO_SUCH_SECRET}"}
    )
    with pytest.raises(ValueError, match="NO_SUCH_SECRET"):
        resolve_environment(startup)


def test_env_file_loads_only_required_names_and_preserves_plan_flags(tmp_path):
    path = tmp_path / ".env"
    path.write_text('API_KEY="quoted secret"\nALLOW_CUSTOM=true\nUNRELATED_SECRET=hidden\n')
    startup = StartupPlan(
        command="app",
        cwd=".",
        health_url="http://localhost",
        env={"TOKEN": "${API_KEY}", "ALLOW_CUSTOM": "false"},
        required_env=["API_KEY"],
    )
    env, record, _ = resolve_environment(startup, env_file=path)
    assert env["TOKEN"] == "quoted secret"
    assert env["ALLOW_CUSTOM"] == "false"
    assert "UNRELATED_SECRET" not in env
    assert "quoted secret" not in json.dumps(record)


@pytest.mark.parametrize(
    "startup_env, expected_api_key, expected_secrets",
    [
        ({"TOKEN": "${API_KEY}", "API_KEY": ""}, "", ["primary-secret"]),
        ({"API_KEY": "", "TOKEN": "${API_KEY}"}, "", ["primary-secret"]),
        (
            {"TOKEN": "${API_KEY}", "API_KEY": "${BACKUP_API_KEY}"},
            "backup-secret",
            ["primary-secret", "backup-secret"],
        ),
    ],
)
def test_environment_references_resolve_against_immutable_sources(
    monkeypatch, startup_env, expected_api_key, expected_secrets
):
    monkeypatch.setenv("API_KEY", "primary-secret")
    monkeypatch.setenv("BACKUP_API_KEY", "backup-secret")
    startup = StartupPlan(
        command="app",
        cwd=".",
        health_url="http://localhost",
        env=startup_env,
        required_env=["API_KEY"],
    )

    env, record, secret_values = resolve_environment(startup)

    assert env["TOKEN"] == "primary-secret"
    assert env["API_KEY"] == expected_api_key
    assert secret_values == expected_secrets
    assert "primary-secret" not in json.dumps(record)
    assert "backup-secret" not in json.dumps(record)


def test_alias_secret_source_is_redacted_even_when_required_name_is_overwritten(
    tmp_path, monkeypatch
):
    secret = "synthetic-alias-secret"
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"TOKEN": "${API_KEY}", "API_KEY": ""}
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["setup_commands"] = [
        (
            f"{sys.executable} -c "
            "\"import os, sys; sys.stdout.write(os.environ['TOKEN']); sys.exit(7)\""
        )
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "alias-redacted"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    report_text = (out / "results.json").read_text()
    setup_log = (out / "setup-01.log").read_text()
    assert "setup-01.log" in report_text
    assert secret not in report_text
    assert secret not in setup_log
    assert "[REDACTED]" in setup_log


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "LANGFLOW_SUPERUSER_PASSWORD"])
def test_literal_secret_named_startup_env_rejected_before_output_exists(tmp_path, name):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {name: "synthetic-literal-api-key"}
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "literal-secret"

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, out, headed=False, channel="chrome", llm=Decisions())

    assert not out.exists()
    assert "synthetic-literal-api-key" in path.read_text()


@pytest.mark.parametrize("name", ["AWS_SECRET_ACCESS_KEY", "APIKEY"])
def test_definite_secret_startup_env_names_are_rejected_before_output_exists(tmp_path, name):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {name: "synthetic-literal-secret"}
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, tmp_path / "definite-secret", headed=False, channel="chrome", llm=Decisions())


@pytest.mark.parametrize(
    "name, value",
    [
        ("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/service-account.json"),
        ("DATABASE_URL", "sqlite:///tmp/qabot.db"),
    ],
)
def test_literal_config_paths_are_not_rejected_as_secret_values(tmp_path, name, value):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {name: value}
    data["unresolved"] = ["Stop before launch after validating startup.env."]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    assert run_plan(path, tmp_path / "config-path", headed=False, channel="chrome") == 2


def test_literal_credential_bearing_database_url_rejected_before_unresolved_report(tmp_path):
    url = "postgresql://appuser:synthetic-db-password@localhost:5432/appdb"
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"DATABASE_URL": url}
    data["unresolved"] = ["Stop before launch without persisting the credential URL."]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "credential-url"

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, out, headed=False, channel="chrome")

    assert not out.exists()
    assert url in path.read_text()


def test_malformed_credential_bearing_url_rejected_before_unresolved_report(tmp_path):
    url = "postgresql://appuser:synthetic-db-password@[bad"
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"DATABASE_URL": url}
    data["unresolved"] = ["Stop before launch without persisting the malformed credential URL."]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "malformed-credential-url"

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, out, headed=False, channel="chrome")

    assert not out.exists()


def test_secret_named_startup_env_rejects_reference_with_literal_suffix(tmp_path):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"OPENAI_API_KEY": "${OPENAI_API_KEY}-literal-suffix"}
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, tmp_path / "literal-suffix", headed=False, channel="chrome", llm=Decisions())


@pytest.mark.parametrize(
    "mutation",
    [
        {"unresolved": ["Choose the supported startup command."]},
        {"startup": {"required_env": ["ABSENT_QABOT_TEST_SECRET"]}},
    ],
)
def test_literal_secret_named_startup_env_rejected_before_other_blocked_reports(
    tmp_path, mutation
):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"PASSWORD": "synthetic-literal-password"}
    if "unresolved" in mutation:
        data["unresolved"] = mutation["unresolved"]
    if "startup" in mutation:
        data["startup"].update(mutation["startup"])
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "blocked-secret"

    with pytest.raises(ValueError, match="startup.env"):
        run_plan(path, out, headed=False, channel="chrome", llm=Decisions())

    assert not out.exists()


def test_reference_secrets_and_common_non_secret_knobs_remain_allowed(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "synthetic-referenced-api-key")
    startup = StartupPlan(
        command="app",
        cwd=".",
        health_url="http://localhost",
        env={
            "API_KEY": "${TEST_API_KEY}",
            "TOKEN_LIMIT": "4096",
            "MAX_TOKENS": "8192",
            "DATABASE_URL": "sqlite:///tmp/qabot.db",
        },
        required_env=["TEST_API_KEY"],
    )

    env, record, _ = resolve_environment(startup)

    assert env["API_KEY"] == "synthetic-referenced-api-key"
    assert env["TOKEN_LIMIT"] == "4096"
    assert env["MAX_TOKENS"] == "8192"
    assert env["DATABASE_URL"] == "sqlite:///tmp/qabot.db"
    assert record["supplied"]["API_KEY"] == "${TEST_API_KEY}"
    assert "synthetic-referenced-api-key" not in json.dumps(record)


def test_common_non_secret_knobs_pass_run_plan_validation(tmp_path):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["env"] = {
        "API_KEY": "${TEST_API_KEY}",
        "TOKEN_LIMIT": "4096",
        "MAX_TOKENS": "8192",
        "DATABASE_URL": "sqlite:///tmp/qabot.db",
    }
    data["unresolved"] = ["Stop before launch after validating startup.env."]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "safe-knobs"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    assert (out / "results.json").is_file()


def test_endpoint_preflight_blocks_before_setup_commands(tmp_path, monkeypatch):
    path = make_plan(tmp_path, 9876)
    marker = tmp_path / "setup-ran"
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"SETUP_MARKER": str(marker)}
    data["startup"]["setup_commands"] = [
        f"{sys.executable} -c \"import os; from pathlib import Path; Path(os.environ['SETUP_MARKER']).write_text('ran')\""
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    calls = []

    def occupied(url):
        calls.append(url)
        raise RuntimeError("Target port is already listening")

    monkeypatch.setattr("qabot.journeys.runner.ensure_endpoint_available", occupied)

    assert run_plan(path, tmp_path / "preflight-blocked", headed=False, channel="chrome") == 2

    assert calls == ["http://127.0.0.1:9876/"]
    assert not marker.exists()


def test_endpoint_preflight_repeats_after_setup_before_startup(tmp_path, monkeypatch):
    path = make_plan(tmp_path, 9876)
    marker = tmp_path / "setup-ran"
    data = json.loads(path.read_text())
    data["startup"]["env"] = {"SETUP_MARKER": str(marker)}
    data["startup"]["setup_commands"] = [
        f"{sys.executable} -c \"import os; from pathlib import Path; Path(os.environ['SETUP_MARKER']).write_text('ran')\""
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    calls = []

    def setup_bound_port(url):
        calls.append(url)
        if len(calls) == 2:
            raise RuntimeError("Target port is already listening after setup")

    monkeypatch.setattr("qabot.journeys.runner.ensure_endpoint_available", setup_bound_port)

    out = tmp_path / "post-setup-preflight-blocked"
    assert run_plan(path, out, headed=False, channel="chrome") == 2

    assert calls == ["http://127.0.0.1:9876/", "http://127.0.0.1:9876/"]
    assert marker.exists()
    assert not (out / "startup.log").exists()
    assert "after setup" in (out / "results.json").read_text()


def test_owned_endpoint_verified_after_health_and_after_reset(
    tmp_path, free_tcp_port, monkeypatch
):
    from qabot.journeys.models import JourneyResult, StepOutcome, StepResult
    from qabot.models import Outcome

    class FakeVideo:
        def __init__(self, path):
            self._path = path

        def path(self):
            return str(self._path)

    class FakePage:
        def __init__(self, path):
            self.video = FakeVideo(path)

    class FakeContext:
        def __init__(self, path):
            self._path = path
            self._page = FakePage(path)

        def new_page(self):
            return self._page

        def close(self):
            self._path.write_bytes(b"fake video")

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext(Path(kwargs["record_video_dir"]) / "video.webm")

        def close(self):
            pass

    class FakeChromium:
        def launch(self, *, channel, headless):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_walk(journey, driver, page, llm, artifacts, env):
        return JourneyResult(
            journey=journey,
            outcome=Outcome.PASS,
            steps=[
                StepResult(
                    index=0,
                    do=journey.steps[0].do,
                    see=journey.steps[0].see,
                    outcome=StepOutcome.HELD,
                    reason="held",
                )
            ],
        )

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr("qabot.journeys.runner.JourneyBrowserDriver", lambda *args, **kwargs: object())
    monkeypatch.setattr("qabot.journeys.runner.walk", fake_walk)
    ownership_checks = []
    monkeypatch.setattr(
        "qabot.journeys.runner.require_owned_endpoint",
        lambda url, process: ownership_checks.append((url, process.pid)),
    )
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["startup"]["reset_command"] = f"{sys.executable} -c \"print('reset')\""
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    assert run_plan(path, tmp_path / "owned", headed=False, channel="chrome", llm=Decisions()) == 0

    assert [url for url, _ in ownership_checks] == [
        f"http://127.0.0.1:{free_tcp_port}/",
        f"http://127.0.0.1:{free_tcp_port}/",
    ]


def test_owned_endpoint_verified_before_each_no_reset_journey(
    tmp_path, free_tcp_port, monkeypatch
):
    from qabot.journeys.models import JourneyResult, StepOutcome, StepResult
    from qabot.models import Outcome

    class FakeVideo:
        def __init__(self, path):
            self._path = path

        def path(self):
            return str(self._path)

    class FakePage:
        def __init__(self, path):
            self.video = FakeVideo(path)

    class FakeContext:
        def __init__(self, path):
            self._path = path
            self._page = FakePage(path)

        def new_page(self):
            return self._page

        def close(self):
            self._path.write_bytes(b"fake video")

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext(Path(kwargs["record_video_dir"]) / "video.webm")

        def close(self):
            pass

    class FakeChromium:
        def launch(self, *, channel, headless):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_walk(journey, driver, page, llm, artifacts, env):
        return JourneyResult(
            journey=journey,
            outcome=Outcome.PASS,
            steps=[
                StepResult(
                    index=0,
                    do=journey.steps[0].do,
                    see=journey.steps[0].see,
                    outcome=StepOutcome.HELD,
                    reason="held",
                )
            ],
        )

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr(
        "qabot.journeys.runner.JourneyBrowserDriver", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr("qabot.journeys.runner.walk", fake_walk)
    ownership_checks = []
    monkeypatch.setattr(
        "qabot.journeys.runner.require_owned_endpoint",
        lambda url, process: ownership_checks.append((url, process.pid)),
    )
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["journeys"].append({**data["journeys"][0], "id": "second", "title": "Second"})
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    assert run_plan(path, tmp_path / "owned-no-reset", headed=False, channel="chrome") == 0

    assert [url for url, _ in ownership_checks] == [
        f"http://127.0.0.1:{free_tcp_port}/",
        f"http://127.0.0.1:{free_tcp_port}/",
        f"http://127.0.0.1:{free_tcp_port}/",
    ]


def test_stale_approval_prevents_output_or_launch(tmp_path):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["command"] = "touch SHOULD_NOT_EXIST"
    path.write_text(json.dumps(data))
    with pytest.raises(ApprovalError):
        run_plan(path, tmp_path / "run", headed=False, channel="chrome")
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert not (tmp_path / "run").exists()


def test_failed_setup_command_retains_redacted_log(tmp_path, monkeypatch):
    secret = "synthetic-" + ("x" * 9000) + "-setup-secret"
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["setup_commands"] = [
        (
            f"{sys.executable} -c "
            "\"import os, sys; sys.stdout.write(os.environ['API_KEY']); "
            "sys.stderr.write(' stderr tail'); sys.exit(7)\""
        )
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "setup-failed"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    report_text = (out / "results.json").read_text()
    report = json.loads(report_text)
    assert "setup-01.log" in report["results"][0]["why"]
    assert secret not in report_text
    setup_log = out / "setup-01.log"
    assert setup_log.is_file()
    log_text = setup_log.read_text()
    assert secret not in log_text
    assert "[REDACTED]" in log_text


def test_setup_log_redacts_secret_split_on_read_boundary(tmp_path, monkeypatch):
    secret = "synthetic-boundary-secret"
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["setup_commands"] = [
        (
            f"{sys.executable} -c "
            "\"import os, sys; sys.stdout.write('a' * 16320); "
            "sys.stdout.write(os.environ['API_KEY']); sys.stdout.write('tail'); sys.exit(9)\""
        )
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "setup-boundary"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    log_text = (out / "setup-01.log").read_text()
    assert "a" * 100 in log_text
    assert "tail" in log_text
    assert secret not in log_text
    assert "[REDACTED]" in log_text
    assert log_text == ("a" * 16320) + "[REDACTED]tail"


def test_setup_log_redacts_url_encoded_secret_split_on_read_boundary(tmp_path, monkeypatch):
    from urllib.parse import quote

    secret = "synthetic / encoded / secret"
    encoded = quote(secret, safe="")
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["setup_commands"] = [
        (
            f"{sys.executable} -c "
            f"\"import sys; sys.stdout.write('b' * 16320); "
            f"sys.stdout.write({encoded!r}); sys.stdout.write('tail'); sys.exit(9)\""
        )
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "setup-encoded-boundary"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    log_text = (out / "setup-01.log").read_text()
    assert "b" * 100 in log_text
    assert "tail" in log_text
    assert secret not in log_text
    assert encoded not in log_text
    assert "[REDACTED]" in log_text
    assert log_text == ("b" * 16320) + "[REDACTED]tail"


def test_stream_redaction_matches_full_redaction_when_secret_spans_flush_boundary(tmp_path):
    from qabot.journeys.runner import _capture_process_output
    from qabot.journeys.walker import redact_text

    secret = "synthetic-flush-boundary-secret"
    full_text = ("c" * 16320) + secret + "tail" + ("d" * 9000)
    chunks = [full_text[:8192].encode(), full_text[8192:16384].encode(), full_text[16384:].encode()]

    class FakeStdout:
        def read(self, size):
            return chunks.pop(0) if chunks else b""

    process = types.SimpleNamespace(stdout=FakeStdout())
    log_path = tmp_path / "stream.log"

    _capture_process_output(
        process,
        log_path,
        redact=lambda text: redact_text(text, [secret]),
        secrets=[secret],
    )

    assert log_path.read_text() == redact_text(full_text, [secret])


def test_stream_redaction_stays_bounded_for_repetitive_secret_output(tmp_path):
    from qabot.journeys.runner import _capture_process_output

    secret = "aaa"
    chunks = [(b"a" * 8192) for _ in range(4)]
    redacted_lengths = []

    class FakeStdout:
        def read(self, size):
            return chunks.pop(0) if chunks else b""

    process = types.SimpleNamespace(stdout=FakeStdout())
    log_path = tmp_path / "repetitive.log"

    _capture_process_output(
        process,
        log_path,
        redact=lambda text: redacted_lengths.append(len(text)) or text.replace(secret, "[REDACTED]"),
        secrets=[secret],
    )

    assert max(redacted_lengths) < 10000
    assert secret not in log_path.read_text()


def test_command_cancellation_retains_redacted_log_and_cleans_process(tmp_path, monkeypatch):
    from qabot.journeys.runner import _run_command

    secret = "synthetic-cancel-secret"
    waits = []
    signals = []

    class FakeStdout:
        def __init__(self):
            self._chunks = [secret.encode(), b""]

        def read(self, size):
            return self._chunks.pop(0) if self._chunks else b""

    class FakeProcess:
        pid = 12345
        stdout = FakeStdout()

        def wait(self, timeout=None):
            waits.append(timeout)
            if len(waits) == 1:
                raise KeyboardInterrupt
            return 0

    monkeypatch.setattr(
        "qabot.journeys.runner.subprocess.Popen", lambda *args, **kwargs: FakeProcess()
    )
    monkeypatch.setattr(
        "qabot.journeys.runner.os.killpg",
        lambda pid, sig: signals.append((pid, sig)),
    )
    log_path = tmp_path / "cancelled.log"

    with pytest.raises(KeyboardInterrupt):
        _run_command(
            "test command",
            cwd=tmp_path,
            env={},
            log_path=log_path,
            log_ref="cancelled.log",
            redact=lambda text: text.replace(secret, "[REDACTED]"),
            secrets=[secret],
            label="setup command 1",
        )

    assert secret not in log_path.read_text()
    assert "[REDACTED]" in log_path.read_text()
    assert signals


def test_command_log_open_failure_blocks_even_when_command_succeeds(tmp_path, monkeypatch):
    from qabot.journeys.runner import _run_command

    log_path = tmp_path / "lost.log"
    original_open = Path.open

    def fail_for_log(path, *args, **kwargs):
        if path == log_path:
            raise OSError("cannot open log")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_for_log)

    with pytest.raises(RuntimeError, match="output capture failed.*lost.log"):
        _run_command(
            f"{sys.executable} -c \"print('ok')\"",
            cwd=tmp_path,
            env={},
            log_path=log_path,
            log_ref="lost.log",
            redact=lambda text: text,
            secrets=[],
            label="setup command 1",
        )


def test_command_log_capture_must_finish_when_command_succeeds(tmp_path, monkeypatch):
    from qabot.journeys.runner import _run_command

    class FakeThread:
        capture_error = None

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return True

    class FakeProcess:
        pid = 12346
        stdout = types.SimpleNamespace(read=lambda size: b"")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        "qabot.journeys.runner.subprocess.Popen", lambda *args, **kwargs: FakeProcess()
    )
    monkeypatch.setattr("qabot.journeys.runner._start_log_thread", lambda *args, **kwargs: FakeThread())
    monkeypatch.setattr("qabot.journeys.runner.os.killpg", lambda pid, sig: None)

    with pytest.raises(RuntimeError, match="output capture did not finish.*hung.log"):
        _run_command(
            "test command",
            cwd=tmp_path,
            env={},
            log_path=tmp_path / "hung.log",
            log_ref="hung.log",
            redact=lambda text: text,
            secrets=[],
            label="setup command 1",
        )


def test_command_cancellation_is_not_masked_by_log_capture_failure(tmp_path, monkeypatch):
    from qabot.journeys.runner import _run_command

    class FakeThread:
        def __init__(self):
            self.capture_errors = [OSError("cannot write log")]

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

    class FakeProcess:
        pid = 12347
        stdout = types.SimpleNamespace(read=lambda size: b"")
        waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise KeyboardInterrupt
            return 0

    monkeypatch.setattr(
        "qabot.journeys.runner.subprocess.Popen", lambda *args, **kwargs: FakeProcess()
    )
    monkeypatch.setattr("qabot.journeys.runner._start_log_thread", lambda *args, **kwargs: FakeThread())
    monkeypatch.setattr("qabot.journeys.runner.os.killpg", lambda pid, sig: None)

    with pytest.raises(KeyboardInterrupt):
        _run_command(
            "test command",
            cwd=tmp_path,
            env={},
            log_path=tmp_path / "cancel.log",
            log_ref="cancel.log",
            redact=lambda text: text,
            secrets=[],
            label="setup command 1",
        )


def test_setup_timeout_retains_redacted_log_and_cleans_process(tmp_path, monkeypatch):
    import httpx

    secret = "synthetic-timeout-secret"
    monkeypatch.setenv("API_KEY", secret)
    monkeypatch.setattr("qabot.journeys.runner.STARTUP_TIMEOUT", 0.3)
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["setup_commands"] = [
        (
            f"{sys.executable} -c "
            "\"import os, sys, time; sys.stdout.write(os.environ['API_KEY']); "
            "sys.stdout.flush(); time.sleep(30)\""
        )
    ]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "setup-timeout"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    report_text = (out / "results.json").read_text()
    assert "setup-01.log" in report_text
    assert "timed out" in report_text
    assert secret not in report_text
    assert secret not in (out / "setup-01.log").read_text()
    with pytest.raises(httpx.ConnectError):
        httpx.get("http://127.0.0.1:9876", timeout=1)


def test_failed_reset_command_retains_redacted_log(tmp_path, free_tcp_port, monkeypatch):
    class FakeChromium:
        def launch(self, *, channel, headless):
            return types.SimpleNamespace(close=lambda: None)

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    secret = "synthetic-reset-secret"
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    data["startup"]["reset_command"] = (
        f"{sys.executable} -c "
        "\"import os, sys; sys.stderr.write(os.environ['API_KEY']); sys.exit(5)\""
    )
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "reset-failed"

    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    report_text = (out / "results.json").read_text()
    assert "journey-01-reset.log" in report_text
    assert secret not in report_text
    reset_log = out / "journey-01-reset.log"
    assert reset_log.is_file()
    assert secret not in reset_log.read_text()
    assert "[REDACTED]" in reset_log.read_text()


@pytest.mark.browser
def test_real_chrome_run_records_playable_video_and_cleans_process(tmp_path, free_tcp_port):
    import httpx

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["journeys"][0]["steps"].append({"do": "Inspect the listing", "see": "Directory listing"})
    path.write_text(json.dumps(data))
    approve_plan(path, "automated test")
    llm = Decisions(
        {"op": "goto", "path": "/"},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory listing visible"},
        {"op": "read"},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory listing remains visible"},
    )
    out = tmp_path / "run"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm) == 0
    report = json.loads((out / "results.json").read_text())
    assert report["results"][0]["outcome"] == "pass"
    video = out / report["results"][0]["video"]
    assert video.is_file() and video.stat().st_size > 1000
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        page = browser.new_page()
        page.goto((out / "report.html").as_uri())
        page.wait_for_function("() => document.querySelector('video').readyState >= 2")
        assert page.locator("video").evaluate("v => v.videoWidth") > 0
        chapter = page.locator("a[data-offset]").nth(1)
        offset = float(chapter.get_attribute("data-offset"))
        assert offset > 0
        chapter.click()
        page.wait_for_function(
            "offset => Math.abs(document.querySelector('video').currentTime - offset) < 0.5",
            arg=offset,
        )
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{free_tcp_port}", timeout=1)


def test_missing_secret_writes_blocked_report(tmp_path):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["ABSENT_QABOT_TEST_SECRET"]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    out = tmp_path / "blocked"
    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2
    report = json.loads((out / "results.json").read_text())
    assert report["results"][0]["outcome"] == "blocked"
    assert "ABSENT_QABOT_TEST_SECRET" in report["results"][0]["why"]


@pytest.mark.browser
def test_later_driver_error_preserves_completed_steps_in_report(tmp_path, free_tcp_port):
    pytest.importorskip("playwright.sync_api")
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["journeys"][0]["steps"].append({"do": "Go next", "see": "Next page"})
    path.write_text(json.dumps(data))
    approve_plan(path, "automated test")
    llm = Decisions(
        {"op": "goto", "path": "/"},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory visible"},
        {"op": "goto", "path": "https://outside.example/"},
    )
    out = tmp_path / "partial"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm) == 2
    result = json.loads((out / "results.json").read_text())["results"][0]
    assert result["steps"][0]["outcome"] == "held"
    assert result["steps"][0]["actions"]
    assert (out / result["steps"][0]["screenshot"]).is_file()
    assert result["steps"][1]["outcome"] == "blocked"
    assert (out / result["video"]).is_file()


@pytest.mark.browser
def test_interrupt_preserves_partial_steps_video_and_stops_later_journeys(tmp_path, free_tcp_port):
    pytest.importorskip("playwright.sync_api")
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["journeys"][0]["steps"].append({"do": "Read more", "see": "More"})
    data["journeys"].append({**data["journeys"][0], "id": "later"})
    path.write_text(json.dumps(data))
    approve_plan(path, "test")

    class InterruptingDecisions(Decisions):
        def complete_json(self, *args):
            item = next(self.items)
            if isinstance(item, BaseException):
                raise item
            return item

    llm = InterruptingDecisions(
        {"op": "goto", "path": "/"},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory visible"},
        {"op": "read"},
        KeyboardInterrupt(),
    )
    out = tmp_path / "cancelled"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm) == 130
    report = json.loads((out / "results.json").read_text())
    first, later = report["results"]
    assert first["steps"][0]["outcome"] == "held"
    assert first["steps"][1]["actions"]
    assert "cancel" in first["why"].lower()
    assert (out / first["video"]).stat().st_size > 1000
    assert later["steps"][0]["outcome"] == "not_reached"
    import httpx

    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{free_tcp_port}", timeout=1)


def test_context_close_failure_preserves_completed_result_evidence(
    tmp_path, free_tcp_port, monkeypatch
):
    video_path_calls = []

    class FakeVideo:
        def path(self):
            video_path_calls.append(True)
            raise RuntimeError("video not finalized")

    class FakePage:
        video = FakeVideo()

    class RaisingContext:
        def __init__(self):
            self.page = FakePage()

        def new_page(self):
            return self.page

        def close(self):
            raise RuntimeError("context close failed")

    class FakeBrowser:
        def new_context(self, **kwargs):
            return RaisingContext()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, *, channel, headless):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_walk(journey, driver, page, llm, artifacts, env):
        return JourneyResult(
            journey=journey,
            outcome=Outcome.FAIL,
            why="expected text was absent",
            steps=[
                StepResult(
                    index=0,
                    do=journey.steps[0].do,
                    see=journey.steps[0].see,
                    outcome=StepOutcome.FAILED,
                    reason="expected text was absent",
                    findings=[
                        Finding(
                            workflow_id=journey.id,
                            workflow_name=journey.title,
                            severity=Severity.QUESTION,
                            outcome=Outcome.FAIL,
                            statement="expected to see: Directory listing",
                            detail="expected text was absent",
                            repro=[journey.steps[0].do],
                        )
                    ],
                )
            ],
        )

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    monkeypatch.setattr("qabot.journeys.runner.JourneyBrowserDriver", lambda *args, **kwargs: object())
    monkeypatch.setattr("qabot.journeys.runner.walk", fake_walk)
    path = make_plan(tmp_path, free_tcp_port)

    out = tmp_path / "teardown-failed"
    assert run_plan(path, out, headed=False, channel="chrome", llm=Decisions()) == 2

    result = json.loads((out / "results.json").read_text())["results"][0]
    assert result["outcome"] == "blocked"
    assert "context close failed" in result["why"]
    assert "Required video unavailable" in result["why"]
    assert result["steps"][0]["outcome"] == "failed"
    assert result["steps"][0]["findings"][0]["detail"] == "expected text was absent"
    assert video_path_calls == []


def test_stop_kills_descendant_even_when_launcher_exits_on_term():
    import signal
    import subprocess
    import time

    from qabot.journeys.runner import _stop

    child_code = "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(os.getpid(),flush=True); time.sleep(60)"
    parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    child_pid = int(process.stdout.readline())
    try:
        _stop(process)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Startup descendant survived cleanup")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


@pytest.mark.browser
def test_env_file_secret_reflections_are_redacted_before_first_model_call_and_report(
    tmp_path, free_tcp_port
):
    pytest.importorskip("playwright.sync_api")
    secret = "dummy-reflected-server-api-key"
    (tmp_path / "index.html").write_text(f"<h1>Build failed: {secret}</h1>")
    env_file = tmp_path / ".env"
    env_file.write_text(f"API_KEY={secret}\n")
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    prompts = []

    class ReflectedDecisions(Decisions):
        def complete_json(self, *args):
            prompts.append(args[1])
            return super().complete_json(*args)

    llm = ReflectedDecisions(
        {"op": "goto", "path": "/"},
        {"op": "done"},
        {"verdict": "failed", "reason": "Server reflected " + secret},
    )
    out = tmp_path / "redacted"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm, env_file=env_file) == 1
    assert all(secret not in prompt for prompt in prompts)
    for name in ("results.json", "report.md", "report.html", "startup.log"):
        assert secret not in (out / name).read_text()
    result = json.loads((out / "results.json").read_text())["results"][0]
    assert result["outcome"] == "fail"
    assert "[REDACTED]" in result["steps"][0]["reason"]


@pytest.mark.browser
def test_startup_log_redacts_url_encoded_secret(tmp_path, free_tcp_port, monkeypatch):
    from urllib.parse import quote

    pytest.importorskip("playwright.sync_api")
    secret = "sensitive startup / key"
    encoded = quote(secret, safe="")
    monkeypatch.setenv("API_KEY", secret)
    path = make_plan(tmp_path, free_tcp_port)
    data = json.loads(path.read_text())
    data["startup"]["required_env"] = ["API_KEY"]
    path.write_text(json.dumps(data))
    approve_plan(path, "test")
    llm = Decisions(
        {"op": "goto", "path": "/?token=" + encoded},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory listing visible"},
    )
    out = tmp_path / "encoded-log"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm) == 0
    log = (out / "startup.log").read_text()
    assert "GET /?token=" in log
    assert secret not in log
    assert encoded not in log
    assert "[REDACTED]" in log
