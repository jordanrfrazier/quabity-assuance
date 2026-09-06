import json
import subprocess
from pathlib import Path

from spikes.journeys.run import main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "a.py").write_text("x = 2  # LANGFLOW_FLAG\n")
    _git(repo, "commit", "-qam", "head")
    return repo


def test_author_only_writes_journeys_and_evidence(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    journeys = [
        {
            "id": f"j{i}",
            "title": f"t{i}",
            "persona": "p",
            "steps": [{"do": "open", "see": "home"}],
            "traces_to": "a.py",
        }
        for i in range(1, 4)
    ]
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps([{"journeys": journeys}]))
    monkeypatch.setenv("JOURNEYS_LLM", f"fake:{fake}")
    out = tmp_path / "out"
    code = main(
        [
            "--repo",
            str(repo),
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
            "--out",
            str(out),
            "--author-only",
        ]
    )
    assert code == 0
    written = json.loads((out / "journeys.json").read_text())
    assert [j["id"] for j in written] == ["j1", "j2", "j3"]
    ev = json.loads((out / "evidence.json").read_text())
    assert ev["settings_names"] == ["LANGFLOW_FLAG"]
    assert not (out / "results.json").exists()


def test_launch_mode_starts_app_per_settings_group(tmp_path, monkeypatch):
    import sys as _sys

    repo = _repo(tmp_path)
    journeys = [
        {
            "id": "j1",
            "title": "t1",
            "persona": "p",
            "traces_to": "a.py",
            "preconditions": {"settings": {"JOURNEY_FLAG": "on"}, "state": []},
            "steps": [{"do": "open", "see": "on"}],
        },
        {
            "id": "j2",
            "title": "t2",
            "persona": "p",
            "traces_to": "a.py",
            "preconditions": {"settings": {"JOURNEY_FLAG": "off"}, "state": []},
            "steps": [{"do": "open", "see": "off"}],
        },
    ]
    jf = tmp_path / "journeys.json"
    jf.write_text(json.dumps(journeys))
    # walker: goto, done, judge -- twice
    fake = tmp_path / "fake.json"
    fake.write_text(
        json.dumps(
            [
                {"op": "goto", "path": "/"},
                {"op": "done"},
                {"verdict": "held", "reason": "on"},
                {"op": "goto", "path": "/"},
                {"op": "done"},
                {"verdict": "held", "reason": "off"},
            ]
        )
    )
    monkeypatch.setenv("JOURNEYS_LLM", f"fake:{fake}")
    script = tmp_path / "srv.py"
    script.write_text(
        "import os, http.server\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        f = os.environ.get('JOURNEY_FLAG', '?')\n"
        "        b = ('<html><body>' + f + '</body></html>').encode()\n"
        "        self.send_response(200); self.send_header('Content-Type', 'text/html')\n"
        "        self.end_headers(); self.wfile.write(b)\n"
        "    def log_message(self, *a): pass\n"
        "http.server.HTTPServer(('127.0.0.1', 8798), H).serve_forever()\n"
    )
    out = tmp_path / "out"
    code = main(
        [
            "--repo",
            str(repo),
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
            "--out",
            str(out),
            "--journeys",
            str(jf),
            "--launch",
            f"{_sys.executable} {script}",
            "--health",
            "http://127.0.0.1:8798/",
            "--cwd",
            str(tmp_path),
        ]
    )
    assert code == 0
    envs = json.loads((out / "environments.json").read_text())
    assert [e["env"]["JOURNEY_FLAG"] for e in envs] == ["on", "off"]
    results = json.loads((out / "results.json").read_text())
    assert [r["outcome"] for r in results] == ["pass", "pass"]
    assert "on" in (out / "report.md").read_text()


def test_model_outage_blocks_the_journey_instead_of_crashing(tmp_path, monkeypatch):
    from qabot.llm import LLMError
    from spikes.journeys import run as run_mod

    class Outage:
        name = "outage"

        def complete_json(self, system, prompt, schema_hint):
            raise LLMError("session limit")

    monkeypatch.setattr(run_mod, "_llm", lambda: Outage())
    repo = _repo(tmp_path)
    jf = tmp_path / "journeys.json"
    jf.write_text(
        json.dumps(
            [
                {
                    "id": "j1",
                    "title": "t",
                    "persona": "p",
                    "traces_to": "a",
                    "steps": [{"do": "open", "see": "home"}],
                }
            ]
        )
    )
    script = tmp_path / "srv.py"
    script.write_text(
        "import http.server\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(b'<html></html>')\n"
        "    def log_message(self, *a): pass\n"
        "http.server.HTTPServer(('127.0.0.1', 8797), H).serve_forever()\n"
    )
    import sys as _sys

    out = tmp_path / "out"
    code = main(
        [
            "--repo",
            str(repo),
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
            "--out",
            str(out),
            "--journeys",
            str(jf),
            "--launch",
            f"{_sys.executable} {script}",
            "--health",
            "http://127.0.0.1:8797/",
            "--cwd",
            str(tmp_path),
        ]
    )
    assert code == 0
    results = json.loads((out / "results.json").read_text())
    assert results[0]["outcome"] == "blocked"
    assert "model was unavailable" in results[0]["why"]
