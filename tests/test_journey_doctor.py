from pathlib import Path
from types import SimpleNamespace

from qabot.journeys import doctor
from qabot.journeys.doctor import CheckResult, DoctorResult, command, format_doctor, run_doctor


def test_doctor_passes_when_local_prerequisites_are_present(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    monkeypatch.setattr(
        "qabot.journeys.doctor.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=str(tmp_path) + "\n"),
    )

    result = run_doctor(
        tmp_path,
        system="Darwin",
        which=lambda name: f"/usr/local/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert result.ok
    assert result.exit_code == 0
    output = format_doctor(result)
    assert "[OK] claude: /usr/local/bin/claude" in output
    assert "does not verify provider auth" in output


def test_doctor_fails_with_actionable_missing_prerequisites(tmp_path):
    result = run_doctor(
        system="Darwin",
        which=lambda name: None if name == "claude" else f"/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_exists=lambda path: path == Path(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert not result.ok
    assert result.exit_code == 2
    output = format_doctor(result)
    assert "[MISSING] claude: not found on PATH" in output
    assert "Install `claude`" in output


def test_doctor_fails_when_playwright_import_is_missing(tmp_path):
    result = run_doctor(
        system="Darwin",
        which=lambda name: f"/bin/{name}",
        import_playwright=lambda: (
            False,
            "could not import playwright.sync_api.sync_playwright: missing dependency",
        ),
        path_exists=lambda path: path == Path(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert not result.ok
    output = format_doctor(result)
    assert "could not import playwright.sync_api.sync_playwright" in output
    assert "uv sync --extra browser" in output


def test_default_playwright_import_reports_corrupt_install(monkeypatch):
    def raise_runtime_error(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            raise RuntimeError("broken local package")
        return original_import(name, globals, locals, fromlist, level)

    original_import = doctor.__builtins__["__import__"]
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setitem(doctor.__builtins__, "__import__", raise_runtime_error)

    ok, detail = doctor._default_import_playwright()

    assert not ok
    assert detail == "could not import playwright.sync_api.sync_playwright: broken local package"


def test_doctor_fails_when_chrome_executable_is_missing(tmp_path):
    result = run_doctor(
        system="Darwin",
        which=lambda name: f"/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_exists=lambda path: False,
        path_is_file=lambda path: False,
        path_is_executable=lambda path: False,
        home=tmp_path,
    )

    assert not result.ok
    output = format_doctor(result)
    assert "[MISSING] Google Chrome: Google Chrome executable was not found" in output


def test_doctor_fails_on_unsupported_os(tmp_path):
    result = run_doctor(
        system="Linux",
        which=lambda name: f"/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_exists=lambda path: path == Path(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert not result.ok
    output = format_doctor(result)
    assert "[MISSING] macOS: unsupported platform: Linux" in output


def test_doctor_fails_when_optional_repo_path_does_not_exist(tmp_path):
    missing = tmp_path / "missing"
    result = run_doctor(
        missing,
        system="Darwin",
        which=lambda name: f"/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_exists=lambda path: path == Path(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert not result.ok
    output = format_doctor(result)
    assert f"[MISSING] repo: path does not exist: {missing}" in output


def test_doctor_validates_optional_repo_path(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        "qabot.journeys.doctor.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=128, stdout="", stderr="fatal: not a git repository\n"
        ),
    )

    result = run_doctor(
        repo,
        system="Darwin",
        which=lambda name: f"/bin/{name}",
        import_playwright=lambda: (True, "playwright.sync_api.sync_playwright import is available"),
        path_exists=lambda path: path == Path(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ),
        path_is_file=lambda path: True,
        path_is_executable=lambda path: True,
        home=tmp_path,
    )

    assert not result.ok
    output = format_doctor(result)
    assert "[MISSING] repo: fatal: not a git repository" in output
    assert "valid local Git repository" in output


def test_doctor_command_prints_success_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(
        "qabot.journeys.doctor.run_doctor",
        lambda repo: DoctorResult((CheckResult("git", True, "/bin/git"),)),
    )

    args = SimpleNamespace(repo=None)
    result = command(args)

    captured = capsys.readouterr()
    assert result == 0
    assert "[OK] git: /bin/git" in captured.out
    assert "does not verify provider auth" in captured.out
    assert captured.err == ""


def test_doctor_command_prints_failures_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        "qabot.journeys.doctor.run_doctor",
        lambda repo: DoctorResult((CheckResult("git", False, "not found", "Install Git."),)),
    )

    args = SimpleNamespace(repo=None)
    result = command(args)

    captured = capsys.readouterr()
    assert result == 2
    assert "[MISSING] git: not found" in captured.err
    assert "does not verify provider auth" in captured.err
    assert captured.out == ""
