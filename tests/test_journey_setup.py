from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from qabot.journeys.setup import DiscoveryError, discover_plan


class RecordingLLM:
    name = "recording"

    def __init__(self, answer: dict):
        self.answer = answer
        self.calls: list[dict] = []

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        self.calls.append({"system": system, "prompt": prompt, "schema_hint": schema_hint})
        return self.answer


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "product"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    (repo / "README.md").write_text(
        "Run `uv run demo-app` and wait for http://127.0.0.1:8123/health.\n"
        "Set API_TOKEN before starting.\n",
        encoding="utf-8",
    )
    docs = repo / "docs"
    docs.mkdir()
    (docs / "flows.md").write_text(
        "Create flows from the editor or use the Assistant entry point.\n",
        encoding="utf-8",
    )
    (repo / ".env.example").write_text("API_TOKEN=${API_TOKEN}\n", encoding="utf-8")
    (repo / ".env").write_text("API_TOKEN=old-real-secret\n", encoding="utf-8")
    (repo / "app.py").write_text("TITLE = 'before'\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    (repo / "app.py").write_text("TITLE = 'after'\n", encoding="utf-8")
    (repo / ".env").write_text("API_TOKEN=new-real-secret\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "head")
    return repo


def _answer(*, unresolved: list[str] | None = None, expected_error: bool = False) -> dict:
    return {
        "startup": {
            "command": "API_TOKEN=literal-command-secret uv run demo-app",
            "cwd": ".",
            "health_url": "http://127.0.0.1:8123/health",
            "env": {"API_TOKEN": "literal-secret", "APP_MODE": "test"},
            "required_env": ["API_TOKEN"],
            "sources": ["README.md", ".env.example"],
        },
        "journeys": [
            {
                "id": "assistant-flow",
                "title": "Build from Assistant",
                "persona": "flow author",
                "goal": "create a flow with the Assistant",
                "because": "the alternate entry point must keep working",
                "steps": [
                    {
                        "do": "Open the Assistant and create a flow",
                        "see": "The new flow opens in the editor",
                        "expected_error": expected_error,
                    }
                ],
                "traces_to": "docs/flows.md and app.py",
            }
        ],
        "unresolved": unresolved or [],
        "sources": {
            "README.md": "startup and health check",
            "docs/flows.md": "Assistant entry point",
        },
    }


def test_discover_plan_uses_repository_docs_and_never_reads_real_env(tmp_path):
    repo = _repo(tmp_path)
    llm = RecordingLLM(_answer())

    plan = discover_plan(repo, "HEAD~1", "HEAD", "exercise the changed flow", llm)

    assert plan.repo == str(repo.resolve())
    assert (plan.base, plan.head, plan.description) == (
        "HEAD~1",
        "HEAD",
        "exercise the changed flow",
    )
    assert [journey.id for journey in plan.journeys] == ["assistant-flow"]
    assert plan.startup.command == "API_TOKEN=${API_TOKEN} uv run demo-app"
    assert plan.startup.env == {"API_TOKEN": "${API_TOKEN}", "APP_MODE": "test"}
    prompt = llm.calls[0]["prompt"]
    assert "uv run demo-app" in prompt
    assert "Assistant entry point" in prompt
    assert "TITLE = 'after'" in prompt
    assert "API_TOKEN=${API_TOKEN}" in prompt
    assert "old-real-secret" not in prompt
    assert "new-real-secret" not in prompt


def test_discover_plan_keeps_required_setup_conflicts_unresolved(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs" / "development.md").write_text(
        "Development may instead start with `make serve`; the canonical command is unknown.\n",
        encoding="utf-8",
    )
    llm = RecordingLLM(
        _answer(unresolved=["Confirm whether `uv run demo-app` or `make serve` is canonical."])
    )

    plan = discover_plan(repo, "HEAD~1", "HEAD", "exercise the changed flow", llm)

    assert plan.unresolved == ["Confirm whether `uv run demo-app` or `make serve` is canonical."]
    assert "make serve" in llm.calls[0]["prompt"]


def test_discover_plan_preserves_deliberate_expected_error_steps(tmp_path):
    repo = _repo(tmp_path)
    llm = RecordingLLM(_answer(expected_error=True))

    plan = discover_plan(repo, "HEAD~1", "HEAD", "verify a documented rejection", llm)

    assert plan.journeys[0].steps[0].expected_error is True
    assert "expected rejection" in llm.calls[0]["system"]


def test_discovery_prompt_contains_complete_output_contract(tmp_path):
    repo = _repo(tmp_path)
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "exercise the flow", llm)
    prompt = llm.calls[0]["prompt"]
    assert '"startup"' in prompt
    assert '"setup_commands"' in prompt
    assert '"expected_error"' in prompt
    assert "expected_error=true" in prompt


def test_discovery_requires_correct_behavior_not_known_defect_as_oracle(tmp_path):
    repo = _repo(tmp_path)
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "Verify the documented payment bug", llm)
    system = llm.calls[0]["system"]
    assert "intended correct behavior" in system
    assert "Never encode a known defect as a successful expected observation" in system
    assert "unresolved" in system


def test_subdirectory_discovery_does_not_import_unrelated_root_diff(tmp_path):
    repo = _repo(tmp_path)
    target = repo / "demo"
    target.mkdir()
    (target / "app.py").write_text('TITLE = "demo before"\n')
    _git(repo, "add", "demo")
    _git(repo, "commit", "-qm", "demo base")
    (target / "app.py").write_text('TITLE = "demo after"\n')
    (repo / "unrelated.md").write_text("Invented checkout requires FICTIONAL_PAYMENT_SERVICE\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "mixed head")
    llm = RecordingLLM(_answer())
    discover_plan(target, "HEAD~1", "HEAD", "exercise demo", llm)
    prompt = llm.calls[0]["prompt"]
    assert "demo after" in prompt
    assert "FICTIONAL_PAYMENT_SERVICE" not in prompt


def test_discovery_prioritizes_current_product_docs_over_workflows_and_archives(tmp_path):
    repo = _repo(tmp_path)
    (repo / "docs/flows.md").unlink()
    for directory in [".github/workflows", "docs/versioned_docs/version-1", "docs/docs/Flows"]:
        (repo / directory).mkdir(parents=True)
    for index in range(40):
        (repo / f".github/workflows/ci-{index}.yml").write_text("name: CI\n")
        (repo / f"docs/versioned_docs/version-1/old-{index}.mdx").write_text(
            "Old flow assistant component build instructions.\n"
        )
    (repo / "docs/package-lock.json").write_text('{"obsoleteLockMarker": true}')
    (repo / "docs/docs/Flows/product-helper.mdx").write_text(
        "# Flow helper\nCreate a flow from the Assistant entry point in the editor.\n"
    )
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "exercise changed flow build components", llm)
    prompt = llm.calls[0]["prompt"]
    assert "uv run demo-app" in prompt
    assert "Assistant entry point" in prompt
    assert "obsoleteLockMarker" not in prompt
    assert "Old flow assistant" not in prompt


@pytest.mark.parametrize(
    "command",
    [
        "app --api-key literal-secret",
        "app --password=literal-secret",
        "app --auth-token 'literal secret'",
    ],
)
def test_discovery_rejects_literal_secret_arguments(tmp_path, command):
    repo = _repo(tmp_path)
    answer = _answer()
    answer["startup"]["command"] = command
    with pytest.raises(DiscoveryError, match="secret") as exc:
        discover_plan(repo, "HEAD~1", "HEAD", "exercise the flow", RecordingLLM(answer))
    assert "literal-secret" not in str(exc.value)
    assert "literal secret" not in str(exc.value)


def test_discovery_rejects_secret_value_repeated_in_journey_text(tmp_path):
    repo = _repo(tmp_path)
    answer = _answer()
    answer["journeys"][0]["steps"][0]["do"] = "Fill password with literal-secret"
    with pytest.raises(DiscoveryError, match="secret"):
        discover_plan(repo, "HEAD~1", "HEAD", "exercise the flow", RecordingLLM(answer))


def test_discovery_accepts_secret_argument_reference(tmp_path):
    repo = _repo(tmp_path)
    answer = _answer()
    answer["startup"]["command"] = 'app --api-key "${API_TOKEN}"'
    plan = discover_plan(repo, "HEAD~1", "HEAD", "exercise the flow", RecordingLLM(answer))
    assert plan.startup.command == 'app --api-key "${API_TOKEN}"'


def test_discovery_bounds_large_repository_prompt_and_marks_excerpts(tmp_path):
    repo = _repo(tmp_path)
    for index in range(35):
        (repo / f"docs/flow-{index}.md").write_text("Flow creation and build details.\n" * 300)
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "flow build " * 3000, llm)
    prompt = llm.calls[0]["prompt"]
    assert len(prompt) <= 65_000
    assert "[TRUNCATED]" in prompt
    assert "### README.md" in prompt


def test_discovery_reads_late_startup_recipes_credentials_and_product_sections(tmp_path):
    repo = _repo(tmp_path)
    (repo / "Makefile").write_text(
        "# Packaging notes\n"
        + "# unrelated maintenance details\n" * 160
        + "\nbackend: setup\n\tuv run uvicorn demo.main:create_app --port 8123\n"
        + "\nsetup:\n\tuv sync\n"
    )
    (repo / ".env.example").write_text(
        "# Optional integrations\n"
        + "# optional integration documentation\n" * 130
        + "# Disable auto login to use the login form.\nAPP_AUTO_LOGIN=false\n"
        + "# Administrator login name\nAPP_SUPERUSER=\n"
        + "# Administrator login password\nAPP_SUPERUSER_PASSWORD=\n"
    )
    (repo / "docs/flows.md").unlink()
    (repo / "docs/assistant.mdx").write_text(
        "# Assistant\nThe assistant can assemble built-in components or generate custom code.\n"
        "## Prerequisites\nCustom component creation requires ALLOW_CUSTOM_COMPONENTS=true.\n"
        "## Generate a custom component\n```python\n"
        + "# Large example implementation\n"
        * 200
        + "```\n## Build a complete flow\n"
        "Open Assistant, request a flow using built-in Input and Output components, "
        "then select Add to Canvas.\n"
        "## Local models\nSelect an installed local model.\n"
    )
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "Review restricted flow creation and building", llm)
    prompt = llm.calls[0]["prompt"]
    assert "uv run uvicorn demo.main:create_app --port 8123" in prompt
    assert "APP_SUPERUSER_PASSWORD=" in prompt
    assert "APP_AUTO_LOGIN=false" in prompt
    assert "select Add to Canvas" in prompt
    assert "## Local models" in prompt
    assert "L" in prompt[prompt.index("### Makefile") : prompt.index("### Makefile") + 100]
    assert "Large example implementation" not in prompt
    assert len(prompt) + len(llm.calls[0]["system"]) <= 60_000


def test_discovery_includes_sibling_ui_routes_and_late_app_registration(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        + "# Backend business logic details\n" * 160
        + "from ui import register_ui\nregister_ui(app)\n"
        + "if __name__ == '__main__':\n    import uvicorn\n    uvicorn.run(app, port=8123)\n"
    )
    (repo / "ui.py").write_text(
        "from fastapi.responses import HTMLResponse\n"
        + "# Shared presentation definitions\n" * 180
        + "def register_ui(app):\n"
        + "    @app.get('/checkout', response_class=HTMLResponse)\n"
        + "    def checkout():\n"
        + "        return '<h1>Checkout</h1><button>Place order</button>'\n"
    )
    llm = RecordingLLM(_answer())
    discover_plan(repo, "HEAD~1", "HEAD", "Review browser checkout workflow", llm)
    prompt = llm.calls[0]["prompt"]
    assert "### ui.py" in prompt
    assert "from ui import register_ui" in prompt
    assert "register_ui(app)" in prompt
    assert "uvicorn.run(app, port=8123)" in prompt
    assert "@app.get('/checkout'" in prompt
    assert "Place order" in prompt
