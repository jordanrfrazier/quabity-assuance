import sys
from pathlib import Path

import pytest

from spikes.journeys.fakes import FakeLLM
from spikes.journeys.launcher import (
    Instance,
    LaunchSpec,
    env_key,
    group_by_settings,
    materialise,
    needs_materialising,
    resolve_settings,
)
from spikes.journeys.models import Journey, JourneyStep


def _j(i, settings):
    return Journey(
        id=f"j{i}",
        title=f"t{i}",
        persona="p",
        preconditions={"settings": settings, "state": []},
        steps=[JourneyStep(do="a", see="b")],
    )


def test_env_key_maps_settings_fields_and_passes_env_names():
    assert env_key("settings.components_path") == "LANGFLOW_COMPONENTS_PATH"
    assert env_key("LANGFLOW_LAZY_LOAD_COMPONENTS") == "LANGFLOW_LAZY_LOAD_COMPONENTS"


def test_needs_materialising_reads_descriptions_not_values():
    assert needs_materialising("/path/to/my_components (contains tools/my_tool.py)")
    assert not needs_materialising("true")
    assert not needs_materialising("false")


def test_group_by_settings_keeps_first_appearance_order():
    a = _j(1, {"LANGFLOW_X": "true"})
    b = _j(2, {"LANGFLOW_X": "false"})
    c = _j(3, {"LANGFLOW_X": "true"})
    groups = group_by_settings([a, b, c])
    assert [[j.id for j in m] for _, m in groups] == [["j1", "j3"], ["j2"]]
    assert groups[0][0] == {"LANGFLOW_X": "true"}


def test_materialise_writes_model_files_under_root(tmp_path):
    llm = FakeLLM([{"files": {"tools/my_tool.py": "class MyTool: pass\n"}}])
    m = materialise("LANGFLOW_COMPONENTS_PATH", "contains tools/my_tool.py", tmp_path, llm)
    assert (Path(m.path) / "tools" / "my_tool.py").read_text() == "class MyTool: pass\n"
    assert Path(m.path).is_absolute()
    assert "Precondition: LANGFLOW_COMPONENTS_PATH" in llm.calls[0]["prompt"]


def test_materialise_refuses_escaping_paths(tmp_path):
    llm = FakeLLM([{"files": {"../evil.py": "x"}}])
    with pytest.raises(RuntimeError, match="refusing"):
        materialise("LANGFLOW_COMPONENTS_PATH", "contains", tmp_path, llm)


def test_resolve_settings_materialises_only_descriptions(tmp_path):
    llm = FakeLLM([{"files": {"tools/t.py": "pass\n"}}])
    env, made = resolve_settings(
        {"LANGFLOW_X": "true", "LANGFLOW_COMPONENTS_PATH": "/path/to/x (contains tools/t.py)"},
        tmp_path,
        llm,
    )
    assert env["LANGFLOW_X"] == "true"
    assert env["LANGFLOW_COMPONENTS_PATH"] == made[0].path
    assert len(made) == 1


def test_instance_starts_a_server_with_env_and_stops_it(tmp_path):
    script = tmp_path / "srv.py"
    script.write_text(
        "import os, http.server\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        body = os.environ.get('JOURNEY_FLAG', 'unset').encode()\n"
        "        self.send_response(200); self.end_headers(); self.wfile.write(body)\n"
        "    def log_message(self, *a): pass\n"
        "http.server.HTTPServer(('127.0.0.1', 8799), H).serve_forever()\n"
    )
    spec = LaunchSpec(
        command=f"{sys.executable} {script}", health_url="http://127.0.0.1:8799/", cwd=str(tmp_path)
    )
    inst = Instance(spec, {"JOURNEY_FLAG": "on"}, tmp_path / "srv.log")
    inst.start()
    try:
        assert inst.wait_healthy(timeout=20)
        import urllib.request

        assert urllib.request.urlopen("http://127.0.0.1:8799/").read() == b"on"
    finally:
        inst.stop()
    assert inst._proc is None


def test_resolve_settings_refuses_to_fabricate_the_built_in_directory(tmp_path):
    llm = FakeLLM([])
    env, made = resolve_settings(
        {"LANGFLOW_COMPONENTS_PATH": "the built-in components directory with a trailing /./"},
        tmp_path,
        llm,
    )
    assert env == {} and made == [] and llm.calls == []
