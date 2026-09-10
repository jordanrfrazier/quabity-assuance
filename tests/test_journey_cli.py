import json
import subprocess

import pytest

from qabot.cli import main


def test_journeys_help_exposes_reviewed_workflow(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert (
        "approve" in output
        and "bundle" in output
        and "doctor" in output
        and "plan" in output
        and "run" in output
    )


def test_run_requires_a_plan(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "run"])
    assert exc.value.code == 2
    assert "plan" in capsys.readouterr().err


def test_bundle_help_mentions_review_and_no_upload(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "bundle", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "Review before sharing" in output
    assert "no sanitization or upload" in output


def test_bundle_prints_sensitive_review_warning(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "report.html").write_text("<html></html>")
    (run_dir / "report.md").write_text("# report\n")
    (run_dir / "results.json").write_text(
        json.dumps({"model": "test", "artifact_paths": "relative-to-report", "results": []})
        + "\n"
    )

    assert main(["journeys", "bundle", str(run_dir)]) == 0

    output = capsys.readouterr().out
    assert "may contain sensitive information" in output
    assert "does not guarantee sanitization" in output
    assert str(tmp_path / "run.zip") in output


def test_bundle_error_returns_exit_2(tmp_path, capsys):
    result = main(["journeys", "bundle", str(tmp_path / "missing")])

    assert result == 2
    assert "run directory does not exist" in capsys.readouterr().err


def test_doctor_command_returns_success(monkeypatch):
    from qabot.journeys import cli

    calls = []

    def fake_doctor(args):
        calls.append(args.repo)
        return 0

    monkeypatch.setattr(cli, "doctor_command", fake_doctor)

    assert main(["journeys", "doctor", "--repo", "/tmp/repo"]) == 0
    assert calls == ["/tmp/repo"]


def test_doctor_command_returns_failure(monkeypatch):
    from qabot.journeys import cli

    monkeypatch.setattr(cli, "doctor_command", lambda args: 2)

    assert main(["journeys", "doctor"]) == 2


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
