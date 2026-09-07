import json
import os
import sys
from pathlib import Path

import pytest

from qabot.journeys.approval import ApprovalError, approve_plan
from qabot.journeys.models import Journey, JourneyStep, ReviewPlan, StartupPlan
from qabot.journeys.runner import resolve_environment, run_plan
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
    env, record = resolve_environment(startup)
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
    env, record = resolve_environment(startup, env_file=path)
    assert env["TOKEN"] == "quoted secret"
    assert env["ALLOW_CUSTOM"] == "false"
    assert "UNRELATED_SECRET" not in env
    assert "quoted secret" not in json.dumps(record)


def test_stale_approval_prevents_output_or_launch(tmp_path):
    path = make_plan(tmp_path, 9876)
    data = json.loads(path.read_text())
    data["startup"]["command"] = "touch SHOULD_NOT_EXIST"
    path.write_text(json.dumps(data))
    with pytest.raises(ApprovalError):
        run_plan(path, tmp_path / "run", headed=False, channel="chrome")
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert not (tmp_path / "run").exists()


@pytest.mark.browser
def test_real_chrome_run_records_playable_video_and_cleans_process(tmp_path, free_tcp_port):
    import httpx

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    path = make_plan(tmp_path, free_tcp_port)
    llm = Decisions(
        {"op": "goto", "path": "/"},
        {"op": "done"},
        {"verdict": "held", "reason": "Directory listing visible"},
    )
    out = tmp_path / "run"
    assert run_plan(path, out, headed=False, channel="chrome", llm=llm) == 0
    report = json.loads((out / "results.json").read_text())
    assert report["results"][0]["outcome"] == "pass"
    video = Path(report["results"][0]["video"])
    assert video.is_file() and video.stat().st_size > 1000
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        page = browser.new_page()
        page.goto((out / "report.html").as_uri())
        page.wait_for_function("() => document.querySelector('video').readyState >= 2")
        assert page.locator("video").evaluate("v => v.videoWidth") > 0
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
    assert Path(result["steps"][0]["screenshot"]).is_file()
    assert result["steps"][1]["outcome"] == "blocked"
    assert Path(result["video"]).is_file()


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
    assert Path(first["video"]).stat().st_size > 1000
    assert later["steps"][0]["outcome"] == "not_reached"
    import httpx

    with pytest.raises(httpx.ConnectError):
        httpx.get(f"http://127.0.0.1:{free_tcp_port}", timeout=1)


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
