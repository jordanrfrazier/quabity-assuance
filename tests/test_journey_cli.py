import subprocess

import pytest

from qabot.cli import main


def test_journeys_help_exposes_reviewed_workflow(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "approve" in output and "plan" in output and "run" in output


def test_run_requires_a_plan(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "run"])
    assert exc.value.code == 2
    assert "plan" in capsys.readouterr().err


def test_missing_approval_is_concise_error(tmp_path, capsys):
    result = main(
        ["journeys", "run", str(tmp_path / "missing.json"), "--out", str(tmp_path / "run")]
    )
    assert result == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_run_defaults_to_a_durable_unique_report_directory(tmp_path, monkeypatch, capsys):
    from qabot.journeys import cli

    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    monkeypatch.chdir(tmp_path)
    outputs = []

    def record_run(plan, out, **kwargs):
        outputs.append(out)
        return 0

    monkeypatch.setattr(cli, "run_plan", record_run)
    for _ in range(2):
        assert main(["journeys", "run", "reviewed.json"]) == 0
    assert outputs[0].parent == tmp_path / "v1/reports"
    assert outputs[0] != outputs[1]
    assert str(outputs[-1] / "report.html") in capsys.readouterr().out


def test_linked_worktree_default_uses_primary_workspace(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from qabot.journeys import cli

    primary = tmp_path / "primary"
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=str(primary / ".git") + "\n"),
    )
    assert cli.default_run_directory(Path("review.json")).parent == primary / "v1/reports"
