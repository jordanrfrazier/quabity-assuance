from __future__ import annotations

import json
from pathlib import Path

import pytest

from qabot.journeys.approval import ApprovalError, approve_plan, require_approval
from qabot.journeys.models import Journey, JourneyStep, ReviewPlan, StartupPlan


def _write_plan(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "product"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    setup_script = scripts / "setup.sh"
    setup_script.write_text("#!/bin/sh\necho ready\n", encoding="utf-8")

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
