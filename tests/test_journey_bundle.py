import json
import zipfile
from pathlib import Path

import pytest

from qabot.journeys.bundle import BundleError, bundle_run


def write_run(
    run_dir: Path,
    *,
    video="journey-01/video.webm",
    step="journey-01/step.png",
    action="journey-01/action.jpg",
):
    run_dir.mkdir(parents=True)
    media = run_dir / "journey-01"
    media.mkdir()
    files = {
        "report.html": b"<html>report</html>",
        "report.md": b"# report\n",
        "results.json": None,
        "journey-01/video.webm": b"video bytes",
        "journey-01/step.png": b"step bytes",
        "journey-01/action.jpg": b"action bytes",
    }
    metadata = {
        "model": "test-model",
        "artifact_paths": "relative-to-report",
        "results": [
            {
                "video": video,
                "steps": [
                    {
                        "screenshot": step,
                        "actions": [{"screenshot": action}],
                    }
                ],
            }
        ],
    }
    for name, payload in files.items():
        if payload is None:
            continue
        (run_dir / name).write_bytes(payload)
    (run_dir / "results.json").write_text(json.dumps(metadata) + "\n")
    return metadata


def zip_entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_bundle_contains_reports_and_all_evidence_levels(tmp_path):
    run_dir = tmp_path / "run.v1"
    write_run(run_dir)
    (run_dir / "startup.log").write_text("do not include")
    (run_dir / ".env").write_text("SECRET=value")
    (run_dir / "state.db").write_text("private")

    archive = bundle_run(run_dir)

    assert archive == tmp_path / "run.v1.zip"
    entries = zip_entries(archive)
    assert set(entries) == {
        "report.html",
        "report.md",
        "results.json",
        "journey-01/video.webm",
        "journey-01/step.png",
        "journey-01/action.jpg",
    }
    assert entries["report.html"] == b"<html>report</html>"
    assert entries["journey-01/video.webm"] == b"video bytes"
    assert entries["journey-01/step.png"] == b"step bytes"
    assert entries["journey-01/action.jpg"] == b"action bytes"


def test_bundle_paths_remain_relative_after_extraction(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    archive = bundle_run(run_dir)
    extract = tmp_path / "extract"

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)

    report = json.loads((extract / "results.json").read_text())
    assert (extract / report["results"][0]["video"]).read_bytes() == b"video bytes"
    assert (extract / report["results"][0]["steps"][0]["screenshot"]).read_bytes() == b"step bytes"
    assert (
        extract / report["results"][0]["steps"][0]["actions"][0]["screenshot"]
    ).read_bytes() == b"action bytes"


def test_bundle_allows_missing_video_and_legacy_missing_timing(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir, video=None)
    data = json.loads((run_dir / "results.json").read_text())
    assert "timing" not in data["results"][0]["steps"][0]
    (run_dir / "results.json").write_text(json.dumps(data) + "\n")

    entries = zip_entries(bundle_run(run_dir))

    assert "journey-01/video.webm" not in entries
    assert "journey-01/step.png" in entries


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.pop("artifact_paths"), "artifact_paths"),
        (lambda data: data.pop("model"), "model"),
        (lambda data: data.__setitem__("results", {}), "results list"),
        (lambda data: data["results"][0].__setitem__("steps", {}), "steps must be a list"),
        (
            lambda data: data["results"][0]["steps"][0].__setitem__("actions", {}),
            "actions must be a list",
        ),
    ],
)
def test_bundle_rejects_malformed_metadata(tmp_path, mutate, message):
    run_dir = tmp_path / "run"
    data = write_run(run_dir)
    mutate(data)
    (run_dir / "results.json").write_text(json.dumps(data) + "\n")

    with pytest.raises(BundleError, match=message):
        bundle_run(run_dir)


def test_bundle_rejects_malformed_json(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    (run_dir / "results.json").write_text("{")

    with pytest.raises(BundleError, match="malformed"):
        bundle_run(run_dir)


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("/etc/passwd", "relative"),
        ("../outside.png", "within the run directory"),
        ("journey-01/../../outside.png", "within the run directory"),
        ("..\\outside.png", "portable relative path"),
        ("C:\\outside.png", "portable relative path"),
        ("journey-01/secrets.env", "unsupported evidence type"),
        ("journey-01/startup.log", "unsupported evidence type"),
        ("journey-01/state.db", "unsupported evidence type"),
    ],
)
def test_bundle_rejects_unsafe_media_references(tmp_path, reference, message):
    run_dir = tmp_path / "run"
    data = write_run(run_dir)
    (run_dir / "journey-01" / "secrets.env").write_text("SECRET=value")
    (run_dir / "journey-01" / "startup.log").write_text("logs")
    (run_dir / "journey-01" / "state.db").write_text("db")
    data["results"][0]["steps"][0]["screenshot"] = reference
    (run_dir / "results.json").write_text(json.dumps(data) + "\n")

    with pytest.raises(BundleError, match=message):
        bundle_run(run_dir)


def test_bundle_rejects_missing_media(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    (run_dir / "journey-01" / "step.png").unlink()

    with pytest.raises(BundleError, match="missing"):
        bundle_run(run_dir)


def test_bundle_rejects_missing_required_report(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    (run_dir / "report.md").unlink()

    with pytest.raises(BundleError, match="missing report.md"):
        bundle_run(run_dir)


def test_bundle_rejects_empty_required_report(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    (run_dir / "report.md").write_text("")

    with pytest.raises(BundleError, match="must not be empty"):
        bundle_run(run_dir)


def test_bundle_rejects_symlink_evidence(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    target = run_dir / "journey-01" / "step.png"
    target.unlink()
    target.symlink_to(run_dir / "journey-01" / "action.jpg")

    with pytest.raises(BundleError, match="symlinks"):
        bundle_run(run_dir)


def test_bundle_rejects_symlink_report(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    report = run_dir / "report.md"
    report.unlink()
    report.symlink_to(run_dir / "report.html")

    with pytest.raises(BundleError, match="symlink"):
        bundle_run(run_dir)


def test_bundle_preserves_existing_archive(tmp_path):
    run_dir = tmp_path / "run"
    write_run(run_dir)
    archive = tmp_path / "run.zip"
    archive.write_bytes(b"existing")

    with pytest.raises(BundleError, match="already exists"):
        bundle_run(run_dir)

    assert archive.read_bytes() == b"existing"


@pytest.mark.parametrize("failure", [RuntimeError("disk full"), KeyboardInterrupt()])
def test_bundle_removes_partial_archive_on_failure(tmp_path, monkeypatch, failure):
    run_dir = tmp_path / "run"
    write_run(run_dir)

    class FailingZip(zipfile.ZipFile):
        def write(self, *args, **kwargs):
            super().write(*args, **kwargs)
            raise failure

    monkeypatch.setattr(zipfile, "ZipFile", FailingZip)

    with pytest.raises(type(failure)):
        bundle_run(run_dir)

    assert not (tmp_path / "run.zip").exists()
