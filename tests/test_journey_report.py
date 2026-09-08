import json
import shutil

from qabot.journeys.models import JourneyResult
from qabot.journeys.report import write_report


def result_for(out, *, measured=False):
    media = out / "journey-01"
    media.mkdir(parents=True)
    (media / "video.webm").write_bytes(b"test media")
    (media / "screen.png").write_bytes(b"test screenshot")
    step = {
        "index": 0,
        "do": "Sign in",
        "see": "Dashboard",
        "outcome": "held",
        "screenshot": str(media / "screen.png"),
        "actions": [{"op": "click", "ok": True, "screenshot": str(media / "screen.png")}],
    }
    if measured:
        step.update(
            started_offset_s=3.25,
            timing={
                "actor_s": 1.2, "judge_s": 2.3, "action_s": 0.1,
                "wait_s": 0.5, "evidence_s": 0.2, "total_s": 4.4,
                "actor_calls": 2, "judge_calls": 1,
            },
        )
    return JourneyResult.model_validate({
        "journey": {
            "id": "login", "title": "Login", "persona": "reviewer",
            "steps": [{"do": "Sign in", "see": "Dashboard"}],
        },
        "outcome": "pass", "steps": [step], "video": str(media / "video.webm"),
    })


def test_report_media_survives_moving_the_bundle(tmp_path):
    out = tmp_path / "original"
    result = result_for(out)
    write_report(out, {"model": "test"}, [result])
    moved = tmp_path / "retained"
    shutil.move(out, moved)
    data = json.loads((moved / "results.json").read_text())
    saved = data["results"][0]
    assert saved["video"] == "journey-01/video.webm"
    assert saved["steps"][0]["screenshot"] == "journey-01/screen.png"
    assert saved["steps"][0]["actions"][0]["screenshot"] == "journey-01/screen.png"
    assert (moved / saved["video"]).is_file()
    assert str(out) not in (moved / "report.md").read_text()
    assert result.video == str(out / "journey-01/video.webm")


def test_measured_report_has_phase_times_and_a_video_chapter(tmp_path):
    out = tmp_path / "run"
    write_report(out, {"model": "test"}, [result_for(out, measured=True)])
    document = (out / "report.html").read_text()
    markdown = (out / "report.md").read_text()
    assert 'data-offset="3.25"' in document
    assert "Actor" in document and "Judge" in document
    assert "1.20" in document and "2.30" in document
    assert "4.40" in markdown
    assert "Approximate" in document


def test_legacy_report_does_not_invent_timings_or_chapters(tmp_path):
    out = tmp_path / "run"
    write_report(out, {"model": "test"}, [result_for(out)])
    document = (out / "report.html").read_text()
    assert "Timing unavailable" in document
    assert "data-offset=" not in document
