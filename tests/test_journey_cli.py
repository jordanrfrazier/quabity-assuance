import pytest

from qabot.cli import main


def test_journeys_help_exposes_reviewed_workflow(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "approve" in output and "plan" in output and "run" in output


def test_run_requires_plan_and_output(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["journeys", "run"])
    assert exc.value.code == 2
    assert "--out" in capsys.readouterr().err


def test_missing_approval_is_concise_error(tmp_path, capsys):
    result = main(
        ["journeys", "run", str(tmp_path / "missing.json"), "--out", str(tmp_path / "run")]
    )
    assert result == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
