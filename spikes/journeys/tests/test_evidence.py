import subprocess
from pathlib import Path

from spikes.journeys.evidence import DIFF_CAP, gather, related_specs, settings_in


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _repo_with_two_commits(tmp_path: Path) -> Path:
    repo = tmp_path / "app"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("def load(settings):\n    return settings.components_path\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "flow.spec.ts").write_text(
        "test('load components_path', async () => { await page.click('Run'); });\n"
    )
    (repo / "tests" / "other.spec.ts").write_text("test('unrelated', async () => {});\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text(
        "def load(settings):\n"
        "    if os.environ.get('LANGFLOW_LAZY_LOAD_COMPONENTS'):\n"
        "        return settings.allow_custom_components\n"
        "    return settings.components_path\n"
    )
    _git(repo, "commit", "-qam", "head")
    return repo


def test_settings_in_finds_env_and_settings_tokens():
    diff = "+ if settings.allow_custom_components and LANGFLOW_LAZY_LOAD_COMPONENTS:\n"
    assert settings_in(diff) == [
        "LANGFLOW_LAZY_LOAD_COMPONENTS",
        "settings.allow_custom_components",
    ]


def test_related_specs_ranks_by_shared_tokens(tmp_path):
    repo = _repo_with_two_commits(tmp_path)
    specs = related_specs(repo, ["components_path", "load"], limit=1)
    assert list(specs) == ["tests/flow.spec.ts"]


def test_gather_reads_the_range(tmp_path):
    repo = _repo_with_two_commits(tmp_path)
    ev = gather(repo, "HEAD~1", "HEAD", description="fix: lazy loading")
    assert "LANGFLOW_LAZY_LOAD_COMPONENTS" in ev.settings_names
    assert "settings.allow_custom_components" in ev.settings_names
    assert ev.changed_files == ["app.py"]
    assert "load" in ev.changed_symbols
    assert ev.description == "fix: lazy loading"
    assert ev.diff_truncated is False
    assert "tests/flow.spec.ts" in ev.related_specs


def test_gather_caps_and_records_truncation(tmp_path, monkeypatch):
    repo = _repo_with_two_commits(tmp_path)
    monkeypatch.setattr("spikes.journeys.evidence.DIFF_CAP", 40)
    ev = gather(repo, "HEAD~1", "HEAD")
    assert ev.diff_truncated is True
    assert len(ev.diff) <= 40
    assert DIFF_CAP == 60_000
