"""Local approval records for reviewed journey plans."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from qabot.journeys.models import ReviewPlan

_SCRIPT_SUFFIXES = {
    ".bash",
    ".cjs",
    ".js",
    ".mjs",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".sh",
    ".ts",
    ".zsh",
}


class ApprovalError(RuntimeError):
    pass


def _approval_path(plan_path: Path) -> Path:
    return plan_path.with_name(f"{plan_path.name}.approval.json")


def _load_json(path: Path, label: str) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApprovalError(f"{label} does not exist: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"could not read {label} {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ApprovalError(f"{label} must contain a JSON object: {path}")
    return raw


def _load_plan(plan_path: Path) -> tuple[dict, ReviewPlan]:
    raw = _load_json(plan_path, "plan")
    try:
        return raw, ReviewPlan.model_validate(raw)
    except ValidationError as exc:
        raise ApprovalError(f"plan is invalid and cannot be approved: {exc}") from exc


def _json_identity(value: dict) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _plan_repo_path(plan: ReviewPlan, plan_path: Path) -> Path:
    repo = Path(plan.repo)
    if not repo.is_absolute():
        repo = plan_path.parent / repo
    return repo


def _git_output(repo: Path, args: list[str], label: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ApprovalError("git is required to approve journey plans") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        if not detail:
            detail = str(exc)
        raise ApprovalError(f"could not resolve {label} for approval: {detail}") from exc
    return completed.stdout.strip()


def _target_git_binding(plan: ReviewPlan, plan_path: Path) -> dict[str, str]:
    repo = _plan_repo_path(plan, plan_path)
    top_level = Path(_git_output(repo, ["rev-parse", "--show-toplevel"], "target repository"))
    try:
        target_repo = str(repo.resolve(strict=True))
        canonical_repo = str(top_level.resolve(strict=True))
    except OSError as exc:
        raise ApprovalError(f"could not resolve target repository for approval: {exc}") from exc
    return {
        "repo": canonical_repo,
        "target_repo": target_repo,
        "base_ref": plan.base,
        "base_sha": _git_output(top_level, ["rev-parse", "--verify", f"{plan.base}^{{commit}}"], "base revision"),
        "head_ref": plan.head,
        "head_sha": _git_output(top_level, ["rev-parse", "--verify", f"{plan.head}^{{commit}}"], "head revision"),
    }


def _script_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError as exc:
        raise ApprovalError(f"could not parse reviewed command {command!r}: {exc}") from exc
    command_position = True
    for index, token in enumerate(tokens):
        if command_position and token in {"cd", "pushd", "popd"}:
            raise ApprovalError(
                "Shell directory changes cannot be approved; use startup.cwd instead"
            )
        if index and tokens[index - 1] in {"-c", "-lc", "-ec"}:
            _script_tokens(token)
        if token and all(char in ";&|()\n" for char in token):
            command_position = True
        elif command_position and (
            "=" in token
            or token in {"command", "builtin", "exec", "env", "if", "then", "else", "do", "!"}
        ):
            continue
        else:
            command_position = False
    expanded: list[str] = []
    for index, token in enumerate(tokens):
        if index and tokens[index - 1] in {"-c", "-lc", "-ec"}:
            expanded.extend(_script_tokens(token))
            continue
        expanded.append(token)
        if any(char.isspace() for char in token):
            try:
                nested = shlex.shlex(token, posix=True, punctuation_chars=True)
                nested.whitespace_split = True
                expanded.extend(nested)
            except ValueError:
                pass
    return expanded


def _looks_like_script(token: str) -> bool:
    if (
        not token
        or token.startswith(("-", "${", "http://", "https://"))
        or "=" in token
        or "<" in token
        or ">" in token
    ):
        return False
    path = Path(token)
    if path.suffix:
        return path.suffix.lower() in _SCRIPT_SUFFIXES
    return "/" in token


def _script_identities(plan: ReviewPlan, plan_path: Path) -> dict[str, str]:
    repo = _plan_repo_path(plan, plan_path)
    cwd = Path(plan.startup.cwd)
    if not cwd.is_absolute():
        cwd = repo / cwd

    commands = [plan.startup.command, *plan.startup.setup_commands]
    if plan.startup.reset_command:
        commands.append(plan.startup.reset_command)

    paths: dict[str, Path] = {}
    for command in commands:
        for token in _script_tokens(command):
            cleaned = token.strip(";&|()")
            if not _looks_like_script(cleaned):
                continue
            candidate = Path(cleaned)
            if not candidate.is_absolute():
                candidate = cwd / candidate
            if candidate.is_dir():
                continue
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise ApprovalError(f"referenced setup script does not exist: {candidate}") from exc
            if not resolved.is_file():
                raise ApprovalError(f"referenced setup script is not a file: {resolved}")
            paths[str(resolved)] = resolved

    identities: dict[str, str] = {}
    for label, path in sorted(paths.items()):
        try:
            identities[label] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ApprovalError(f"could not read referenced setup script {path}: {exc}") from exc
    return identities


def approve_plan(plan_path: Path, reviewer: str) -> Path:
    plan_path = Path(plan_path).resolve()
    if not reviewer.strip():
        raise ApprovalError("reviewer must not be empty")
    raw, plan = _load_plan(plan_path)
    approval = {
        "version": 1,
        "plan_path": str(plan_path),
        "plan_sha256": _json_identity(raw),
        "reviewer": reviewer,
        "approved_at": datetime.now(UTC).isoformat(),
        "git": _target_git_binding(plan, plan_path),
        "setup_scripts": _script_identities(plan, plan_path),
    }
    approval_path = _approval_path(plan_path)
    try:
        approval_path.write_text(json.dumps(approval, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ApprovalError(f"could not write approval {approval_path}: {exc}") from exc
    return approval_path


def require_approval(plan_path: Path) -> dict:
    plan_path = Path(plan_path).resolve()
    raw, plan = _load_plan(plan_path)
    approval_path = _approval_path(plan_path)
    approval = _load_json(approval_path, "approval")
    if approval.get("plan_sha256") != _json_identity(raw):
        raise ApprovalError(
            f"approval is stale because plan content changed; review and approve {plan_path} again"
        )
    approved_git = approval.get("git")
    if not isinstance(approved_git, dict):
        raise ApprovalError(
            f"approval is stale because it has no Git binding; review and approve {plan_path} again"
        )
    current_git = _target_git_binding(plan, plan_path)
    if approved_git.get("repo") != current_git["repo"]:
        raise ApprovalError(
            "approval is stale because target repository changed; "
            f"review and approve {plan_path} again"
        )
    if approved_git.get("target_repo") != current_git["target_repo"]:
        raise ApprovalError(
            "approval is stale because target repository changed; "
            f"review and approve {plan_path} again"
        )
    for name in ("base", "head"):
        key = f"{name}_sha"
        if approved_git.get(key) != current_git[key]:
            raise ApprovalError(
                f"approval is stale because {name} revision changed; "
                f"review and approve {plan_path} again"
            )
    approved_scripts = approval.get("setup_scripts")
    if not isinstance(approved_scripts, dict):
        raise ApprovalError(f"approval has no valid setup script identities: {approval_path}")
    current_scripts = _script_identities(plan, plan_path)
    if approved_scripts != current_scripts:
        changed = sorted(set(approved_scripts) | set(current_scripts))
        raise ApprovalError(
            "approval is stale because a referenced setup script changed: " + ", ".join(changed)
        )
    if not isinstance(approval.get("reviewer"), str) or not approval["reviewer"].strip():
        raise ApprovalError(f"approval has no valid reviewer: {approval_path}")
    if not isinstance(approval.get("approved_at"), str) or not approval["approved_at"].strip():
        raise ApprovalError(f"approval has no valid timestamp: {approval_path}")
    return approval
