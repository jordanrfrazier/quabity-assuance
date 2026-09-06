import json
import subprocess

import pytest

from qabot.journeys.llm import journey_provider
from qabot.llm import LLMError


def test_journey_provider_enforces_json_schema_and_disables_tools(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"structured_output": {"op": "done"}}), ""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert journey_provider().complete_json("system", "page", {"op": ""}) == {"op": "done"}
    argv, kwargs = calls[0]
    assert "--json-schema" in argv and "--system-prompt" in argv
    assert "--append-system-prompt" not in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert "--safe-mode" in argv and "--strict-mcp-config" in argv
    assert kwargs["input"] == "page"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "done" in schema["properties"]["op"]["enum"]
    assert "path" in schema["properties"]
    assert "wait" in schema["properties"]["op"]["enum"]
    assert schema["properties"]["state"]["enum"] == ["visible", "hidden", "enabled"]
    assert schema["properties"]["timeout_ms"]["maximum"] == 60000
    assert schema["properties"]["repeat"] == {"type": "integer", "minimum": 1, "maximum": 30}


def test_journey_provider_refuses_unstructured_success_envelope(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, '{"result":"done"}', ""),
    )
    with pytest.raises(LLMError, match="structured"):
        journey_provider().complete_json("system", "page", {"op": ""})
