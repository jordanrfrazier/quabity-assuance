import json

from spikes.journeys.viewer import main


def test_viewer_renders_story_marks_and_video(tmp_path):
    j = {
        "id": "j1",
        "title": "Run it",
        "persona": "a tester",
        "goal": "to run a flow",
        "because": "that is the point",
        "preconditions": {"settings": {"X": "1"}, "state": []},
        "steps": [{"do": "open", "see": "home"}, {"do": "run", "see": "reply"}],
        "traces_to": "diff",
    }
    for name, outcomes, video in (
        ("fixed", ["held", "held"], "v.webm"),
        ("broken", ["failed", "not_reached"], None),
    ):
        d = tmp_path / name
        d.mkdir()
        (d / "journeys.json").write_text(json.dumps([j]))
        res = {
            "journey": j,
            "outcome": "pass" if name == "fixed" else "fail",
            "why": "" if name == "fixed" else "no reply",
            "video": str(d / video) if video else None,
            "steps": [
                {
                    "index": i,
                    "do": s["do"],
                    "see": s["see"],
                    "outcome": o,
                    "reason": "",
                    "actions": [],
                    "findings": [],
                    "screenshot": None,
                }
                for i, (s, o) in enumerate(zip(j["steps"], outcomes))
            ],
        }
        (d / "results.json").write_text(json.dumps([res]))
    out = tmp_path / "view.html"
    assert (
        main(
            [
                "--title",
                "T",
                "--run",
                f"fixed={tmp_path / 'fixed'}",
                "--run",
                f"broken={tmp_path / 'broken'}",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    page = out.read_text()
    assert "As a a tester, I want to run a flow because that is the point." in page
    assert "fixed: ✓ · broken: ✗" in page
    assert "FAIL</span> at step 1" in page
    assert '<video controls preload="metadata" src="fixed/v.webm"' in page
