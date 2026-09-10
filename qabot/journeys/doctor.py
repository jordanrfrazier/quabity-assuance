"""Deterministic local prerequisite checks for journey runs."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class DoctorResult:
    checks: tuple[CheckResult, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 2


ImportPlaywright = Callable[[], tuple[bool, str]]
PathExists = Callable[[Path], bool]
PathIsFile = Callable[[Path], bool]
PathIsExecutable = Callable[[Path], bool]
Which = Callable[[str], str | None]


def _default_import_playwright() -> tuple[bool, str]:
    if importlib.util.find_spec("playwright") is None:
        return False, "Python package was not found"
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        # Import-time failures can come from a corrupt local Playwright install, not just ImportError.
        return False, f"could not import playwright.sync_api.sync_playwright: {exc}"
    return True, "playwright.sync_api.sync_playwright import is available"


def _executable_check(name: str, which: Which) -> CheckResult:
    path = which(name)
    if path:
        return CheckResult(name, True, path)
    return CheckResult(
        name,
        False,
        "not found on PATH",
        f"Install `{name}` and ensure it is available on PATH.",
    )


def _playwright_check(import_playwright: ImportPlaywright) -> CheckResult:
    ok, detail = import_playwright()
    if ok:
        return CheckResult("playwright", True, detail)
    return CheckResult(
        "playwright",
        False,
        detail,
        "Install the browser extra in the local environment, for example `uv sync --extra browser`.",
    )


def _macos_check(system: str) -> CheckResult:
    if system == "Darwin":
        return CheckResult("macOS", True, "Darwin")
    return CheckResult(
        "macOS",
        False,
        f"unsupported platform: {system or 'unknown'}",
        "Run this private-alpha journey workflow from a supported macOS machine.",
    )


def _chrome_check(
    home: Path,
    exists: PathExists,
    is_file: PathIsFile,
    is_executable: PathIsExecutable,
) -> CheckResult:
    candidates = tuple(
        app / "Contents" / "MacOS" / "Google Chrome"
        for app in (
            Path("/Applications/Google Chrome.app"),
            home / "Applications" / "Google Chrome.app",
        )
    )
    for candidate in candidates:
        if exists(candidate) and is_file(candidate) and is_executable(candidate):
            return CheckResult("Google Chrome", True, str(candidate))
    return CheckResult(
        "Google Chrome",
        False,
        "Google Chrome executable was not found in /Applications or ~/Applications",
        "Install Google Chrome for macOS before running headed Chrome journeys.",
    )


def _repo_check(repo: Path) -> CheckResult:
    if not repo.exists():
        return CheckResult(
            "repo",
            False,
            f"path does not exist: {repo}",
            "Pass an existing local repository path.",
        )
    if not repo.is_dir():
        return CheckResult(
            "repo",
            False,
            f"path is not a directory: {repo}",
            "Pass a local Git repository directory.",
        )
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult(
            "repo",
            False,
            f"could not inspect Git repository: {exc}",
            "Ensure Git is installed and the repo path is accessible.",
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"git exited {result.returncode}"
        return CheckResult(
            "repo",
            False,
            detail,
            "Pass a path inside a valid local Git repository.",
        )
    return CheckResult("repo", True, result.stdout.strip())


def run_doctor(
    repo: Path | None = None,
    *,
    which: Which = shutil.which,
    import_playwright: ImportPlaywright = _default_import_playwright,
    path_exists: PathExists = Path.exists,
    path_is_file: PathIsFile = Path.is_file,
    path_is_executable: PathIsExecutable = lambda path: os.access(path, os.X_OK),
    system: str | None = None,
    home: Path | None = None,
) -> DoctorResult:
    """Run local prerequisite checks without network, auth, or server side effects."""
    checks = [
        _macos_check(system if system is not None else platform.system()),
        _executable_check("git", which),
        _executable_check("uv", which),
        _executable_check("lsof", which),
        _executable_check("claude", which),
        _playwright_check(import_playwright),
        _chrome_check(home or Path.home(), path_exists, path_is_file, path_is_executable),
    ]
    if repo is not None:
        checks.append(_repo_check(repo.resolve()))
    return DoctorResult(tuple(checks))


def format_doctor(result: DoctorResult) -> str:
    lines = ["qabot journeys doctor"]
    for check in result.checks:
        marker = "OK" if check.ok else "MISSING"
        lines.append(f"[{marker}] {check.name}: {check.detail}")
        if check.fix:
            lines.append(f"      fix: {check.fix}")
    if result.ok:
        lines.append("All required local prerequisites are present.")
    else:
        lines.append("Missing required local prerequisites; fix the items above and rerun doctor.")
    lines.append("Note: doctor checks local prerequisites only; it does not verify provider auth.")
    return "\n".join(lines)


def command(args) -> int:
    repo = Path(args.repo) if getattr(args, "repo", None) else None
    result = run_doctor(repo)
    output = format_doctor(result)
    stream = sys.stdout if result.ok else sys.stderr
    print(output, file=stream)
    return result.exit_code
