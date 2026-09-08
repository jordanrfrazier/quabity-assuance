from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from qabot.journeys.approval import ApprovalError, approve_plan, require_approval
from qabot.journeys.models import Journey, JourneyStep, ReviewPlan, StartupPlan


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, filename: str, content: str) -> str:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", f"commit {filename}")
    return _git(repo, "rev-parse", "HEAD")


def _init_product_repo(repo: Path) -> tuple[str, str]:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "qabot@example.test")
    _git(repo, "config", "user.name", "qabot approval test")
    base_sha = _commit(repo, "scripts/setup.sh", "#!/bin/sh\necho ready\n")
    _git(repo, "switch", "-c", "feature")
    head_sha = _commit(repo, "app.txt", "feature\n")
    return base_sha, head_sha


def _write_plan(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "product"
    _init_product_repo(repo)
    scripts = repo / "scripts"
    setup_script = scripts / "setup.sh"

    plan = ReviewPlan(
        repo=str(repo),
        base="main",
        head="feature",
        description="review the flow change",
        startup=StartupPlan(
            command="uv run app",
            cwd=".",
            health_url="http://127.0.0.1:8123/health",
            setup_commands=["sh scripts/setup.sh"],
            sources=["README.md"],
        ),
        journeys=[
            Journey(
                id="happy-path",
                title="Create a flow",
                persona="flow author",
                steps=[JourneyStep(do="Create a flow", see="The editor opens")],
            )
        ],
    )
    plan_path = tmp_path / "review-plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return plan_path, setup_script


def _write_relative_plan(parent: Path) -> tuple[Path, str, str]:
    repo = parent / "product"
    base_sha, head_sha = _init_product_repo(repo)
    plan = ReviewPlan(
        repo="product",
        base="main",
        head="feature",
        description="review the flow change",
        startup=StartupPlan(
            command="uv run app",
            cwd=".",
            health_url="http://127.0.0.1:8123/health",
            setup_commands=["sh scripts/setup.sh"],
        ),
        journeys=[
            Journey(
                id="happy-path",
                title="Create a flow",
                persona="flow author",
                steps=[JourneyStep(do="Create a flow", see="The editor opens")],
            )
        ],
    )
    plan_path = parent / "review-plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return plan_path, base_sha, head_sha


def test_unchanged_plan_reuses_approval_after_formatting_edit(tmp_path):
    plan_path, _ = _write_plan(tmp_path)

    approval_path = approve_plan(plan_path, reviewer="Jordan")
    parsed = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_path.write_text(
        json.dumps(parsed, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    approval = require_approval(plan_path)
    assert approval_path.is_file()
    assert approval["reviewer"] == "Jordan"
    assert approval["plan_sha256"]
    assert approval["setup_scripts"]
    assert approval["git"]["head_sha"]


def test_changed_referenced_setup_script_invalidates_approval(tmp_path):
    plan_path, setup_script = _write_plan(tmp_path)
    approve_plan(plan_path, reviewer="Jordan")
    setup_script.write_text("#!/bin/sh\necho changed\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="setup script"):
        require_approval(plan_path)


@pytest.mark.parametrize("field", ["command", "setup_commands", "reset_command"])
@pytest.mark.parametrize("path_style", ["relative", "absolute", "nested"])
def test_changed_extensionless_script_invalidates_approval(tmp_path, field, path_style):
    plan_path, original = _write_plan(tmp_path)
    script = original.with_suffix("")
    original.rename(script)
    token = str(script) if path_style == "absolute" else "scripts/setup"
    command = f'sh -c "sh {token}"' if path_style == "nested" else f"sh {token}"
    parsed = json.loads(plan_path.read_text())
    parsed["startup"]["setup_commands"] = []
    parsed["startup"][field] = [command] if field == "setup_commands" else command
    plan_path.write_text(json.dumps(parsed))
    approve_plan(plan_path, "test")
    require_approval(plan_path)

    script.write_text("#!/bin/sh\necho changed\n")

    with pytest.raises(ApprovalError, match="setup script"):
        require_approval(plan_path)


def test_missing_extensionless_script_cannot_be_approved(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    parsed = json.loads(plan_path.read_text())
    parsed["startup"]["command"] = "sh scripts/missing"
    plan_path.write_text(json.dumps(parsed))

    with pytest.raises(ApprovalError, match="script does not exist"):
        approve_plan(plan_path, "test")


def test_changed_plan_invalidates_approval(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    approve_plan(plan_path, reviewer="Jordan")
    parsed = json.loads(plan_path.read_text(encoding="utf-8"))
    parsed["startup"]["command"] = "uv run changed-app"
    plan_path.write_text(json.dumps(parsed), encoding="utf-8")

    with pytest.raises(ApprovalError, match="plan content"):
        require_approval(plan_path)


@pytest.mark.parametrize(
    "command",
    [
        "sh scripts/setup.sh;uv run app",
        "sh scripts/setup.sh&&uv run app",
        'sh -c "sh scripts/setup.sh;uv run app"',
    ],
)
def test_shell_punctuation_does_not_hide_referenced_scripts(tmp_path, command):
    plan_path, setup_script = _write_plan(tmp_path)
    parsed = json.loads(plan_path.read_text())
    parsed["startup"]["command"] = command
    parsed["startup"]["setup_commands"] = []
    plan_path.write_text(json.dumps(parsed))
    approve_plan(plan_path, reviewer="Jordan")
    setup_script.write_text("echo changed\n")
    with pytest.raises(ApprovalError, match="setup script"):
        require_approval(plan_path)


def test_directory_option_is_not_a_referenced_script(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    parsed = json.loads(plan_path.read_text())
    (tmp_path / "product/frontend").mkdir()
    parsed["startup"]["command"] = "uv run app --frontend-path ./frontend"
    plan_path.write_text(json.dumps(parsed))
    approve_plan(plan_path, reviewer="Jordan")
    assert require_approval(plan_path)["reviewer"] == "Jordan"


@pytest.mark.parametrize(
    "command",
    [
        "cd scripts && sh setup.sh",
        "pushd scripts; sh setup.sh",
        "popd; sh setup.sh",
        'sh -c "cd scripts && sh setup.sh"',
        "true\ncd scripts\nsh setup.sh",
        "if true; then cd scripts; fi; sh setup.sh",
    ],
)
def test_shell_directory_changes_cannot_bind_the_wrong_script(tmp_path, command):
    plan_path, _ = _write_plan(tmp_path)
    (tmp_path / "product/setup.sh").write_text("echo decoy\n")
    parsed = json.loads(plan_path.read_text())
    parsed["startup"]["command"] = command
    plan_path.write_text(json.dumps(parsed))
    with pytest.raises(ApprovalError, match="startup.cwd"):
        approve_plan(plan_path, "test")


def test_mutable_head_ref_drift_invalidates_unchanged_approval(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    repo = tmp_path / "product"
    parsed = json.loads(plan_path.read_text())
    parsed["head"] = "HEAD"
    plan_path.write_text(json.dumps(parsed))
    approve_plan(plan_path, "Jordan")

    _commit(repo, "app.txt", "feature changed\n")

    with pytest.raises(ApprovalError, match="head revision changed"):
        require_approval(plan_path)


def test_mutable_base_ref_drift_invalidates_unchanged_approval(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    repo = tmp_path / "product"
    approve_plan(plan_path, "Jordan")

    _git(repo, "switch", "main")
    _commit(repo, "base.txt", "base changed\n")
    _git(repo, "switch", "feature")

    with pytest.raises(ApprovalError, match="base revision changed"):
        require_approval(plan_path)


def test_pinned_commit_approval_survives_later_branch_movement(tmp_path):
    plan_path, _, head_sha = _write_relative_plan(tmp_path)
    repo = tmp_path / "product"
    parsed = json.loads(plan_path.read_text())
    parsed["base"] = _git(repo, "rev-parse", "main")
    parsed["head"] = head_sha
    plan_path.write_text(json.dumps(parsed))
    approve_plan(plan_path, "Jordan")

    _commit(repo, "app.txt", "feature changed\n")

    assert require_approval(plan_path)["git"]["head_sha"] == head_sha


def test_old_approval_without_git_binding_requires_review(tmp_path):
    plan_path, _ = _write_plan(tmp_path)
    approval_path = plan_path.with_name(f"{plan_path.name}.approval.json")
    approval_path.write_text(
        json.dumps(
            {
                "version": 1,
                "plan_path": str(plan_path),
                "plan_sha256": "will be replaced",
                "reviewer": "Jordan",
                "approved_at": "2026-09-08T00:00:00+00:00",
                "setup_scripts": {},
            }
        )
    )
    approve_plan(plan_path, "Jordan")
    current = json.loads(approval_path.read_text())
    current.pop("git")
    approval_path.write_text(json.dumps(current))

    with pytest.raises(ApprovalError, match="approval is stale.*Git binding"):
        require_approval(plan_path)


def test_relative_plan_repo_copy_cannot_silently_retarget(tmp_path):
    original = tmp_path / "original"
    copied = tmp_path / "copied"
    original.mkdir()
    copied.mkdir()
    plan_path, _, _ = _write_relative_plan(original)
    approve_plan(plan_path, "Jordan")

    copied_plan = copied / "review-plan.json"
    copied_approval = copied / "review-plan.json.approval.json"
    copied_plan.write_text(plan_path.read_text())
    copied_approval.write_text(plan_path.with_name("review-plan.json.approval.json").read_text())
    _write_relative_plan(copied)

    with pytest.raises(ApprovalError, match="target repository changed"):
        require_approval(copied_plan)


def test_relative_symlink_repo_cannot_retarget_within_same_git_root(tmp_path):
    repo = tmp_path / "monorepo"
    _init_product_repo(repo)
    (repo / "apps/a").mkdir(parents=True)
    (repo / "apps/b").mkdir(parents=True)
    (repo / "apps/a/app.txt").write_text("a\n", encoding="utf-8")
    (repo / "apps/b/app.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "apps")
    _git(repo, "commit", "-m", "commit apps")
    link = repo / "current"
    link.symlink_to(repo / "apps/a", target_is_directory=True)
    plan = ReviewPlan(
        repo="current",
        base="main",
        head="feature",
        description="review the linked app",
        startup=StartupPlan(
            command="uv run app",
            cwd=".",
            health_url="http://127.0.0.1:8123/health",
        ),
        journeys=[
            Journey(
                id="happy-path",
                title="Create a flow",
                persona="flow author",
                steps=[JourneyStep(do="Create a flow", see="The editor opens")],
            )
        ],
    )
    plan_path = repo / "review-plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    approve_plan(plan_path, "Jordan")

    link.unlink()
    link.symlink_to(repo / "apps/b", target_is_directory=True)

    with pytest.raises(ApprovalError, match="target repository changed"):
        require_approval(plan_path)
