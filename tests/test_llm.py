"""ClaudeCliLLM tests.

The through-line: the `claude` CLI is a chat interface wearing an API's clothes, so the
reading side must survive fences and surrounding prose -- and when there is no JSON at
all it must say so out loud, because an empty dict here would reach the verifier as a
model with no opinion and be laundered into an honest-looking BLOCKED.

Nothing in here spawns a process. The one test that does is marked `live_llm` and is
skipped unless it is asked for by name.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from qabot.llm import ClaudeCliLLM, DeterministicLLM, LLMError, Runner, default_provider


class FakeCli:
    """Stands in for the subprocess boundary -- records the argv it was handed and
    returns a canned result, so a unit test never starts an agent session."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], str, float]] = []

    def __call__(
        self, argv: list[str], prompt: str, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, prompt, timeout))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def never_returns(argv: list[str], prompt: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """A boundary behaving like a session that never came back."""
    raise subprocess.TimeoutExpired(argv, timeout)


def unrunnable(argv: list[str], prompt: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """A boundary behaving like a binary that vanished between construction and use."""
    raise OSError(8, "Exec format error")


#: A binary that certainly exists, so the constructor's PATH check passes without these
#: tests depending on a real `claude` being installed on the machine running them.
PRESENT = sys.executable


def provider(runner: Runner, timeout: float = 5.0) -> ClaudeCliLLM:
    """A provider wired to a fake boundary and to a binary that is really there."""
    return ClaudeCliLLM(binary=PRESENT, timeout=timeout, runner=runner)


def answer(cli: FakeCli) -> dict:
    return provider(cli).complete_json("be terse", "is 7 > 3?", {"held": "bool"})


@pytest.fixture
def stub_cli(tmp_path: Path) -> str:
    """A real executable that behaves like the CLI -- reads its prompt from stdin and
    reports back what it received. Used only where a fake boundary proves nothing
    because the behavior under test belongs to the spawn itself."""
    script = tmp_path / "claude-stub"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        'print(json.dumps({"argv": argv, "stdin_chars": len(sys.stdin.read())}))\n'
    )
    script.chmod(0o755)
    return str(script)


# --- construction -----------------------------------------------------------------


def test_missing_binary_refuses_to_construct():
    with pytest.raises(LLMError) as exc:
        ClaudeCliLLM(binary="claude-that-is-not-installed")
    assert "not on PATH" in str(exc.value)


def test_binary_is_taken_from_the_environment(monkeypatch):
    monkeypatch.setenv("QABOT_CLAUDE_BIN", PRESENT)
    cli = FakeCli('{"held": true}')
    ClaudeCliLLM(runner=cli).complete_json("be terse", "is 7 > 3?", {})
    assert cli.calls[0][0][0] == PRESENT


def test_explicit_binary_beats_the_environment(monkeypatch):
    monkeypatch.setenv("QABOT_CLAUDE_BIN", "claude-that-is-not-installed")
    cli = FakeCli('{"held": true}')
    answer(cli)
    assert cli.calls[0][0][0] == PRESENT


# --- the command it builds --------------------------------------------------------


def test_system_prompt_is_appended_and_the_prompt_is_not_in_argv():
    cli = FakeCli('{"held": true}')
    provider(cli, timeout=9.0).complete_json("be terse", "is 7 > 3?", {"held": "bool"})
    argv, prompt, timeout = cli.calls[0]
    assert argv == [PRESENT, "--append-system-prompt", "be terse", "-p"]
    assert "is 7 > 3?" not in argv
    assert prompt == "is 7 > 3?"
    assert timeout == 9.0


def test_a_two_megabyte_prompt_survives_a_real_spawn(stub_cli: str):
    """The reason the prompt is on stdin: argv is capped at ARG_MAX (1 MiB here) and
    stdin is not, while `HttpDriver` records `response.text` uncapped, so one
    server-rendered page interpolated into a verifier prompt clears the cap. A faked
    boundary could not prove this -- E2BIG is raised by the spawn itself -- so this
    test spawns a real, cheap stand-in and checks the whole prompt arrived."""
    prompt = "x" * 2_000_000
    verdict = ClaudeCliLLM(binary=stub_cli).complete_json("be terse", prompt, {})
    assert verdict["stdin_chars"] == len(prompt)
    assert verdict["argv"] == ["--append-system-prompt", "be terse", "-p"]


# --- reading the answer -----------------------------------------------------------


def test_bare_json_object():
    assert answer(FakeCli('{"held": true, "reason": "7 > 3"}\n')) == {
        "held": True,
        "reason": "7 > 3",
    }


def test_fenced_json():
    fenced = 'Here you go:\n\n```json\n{"held": true, "reason": "7 > 3"}\n```\n'
    assert answer(FakeCli(fenced)) == {"held": True, "reason": "7 > 3"}


def test_prose_wrapped_json():
    prose = 'Sure. {"held": false, "reason": "the cart still checked out"} Hope that helps!'
    assert answer(FakeCli(prose)) == {"held": False, "reason": "the cart still checked out"}


def test_a_brace_in_the_prose_does_not_derail_the_scan():
    """Bracketing on the first `{` and the last `}` would swallow both braces and fail;
    scanning for the first one that decodes finds the real object."""
    prose = 'The shape {held, reason} is: {"held": true, "reason": "yes"} -- {done}'
    assert answer(FakeCli(prose)) == {"held": True, "reason": "yes"}


def test_no_json_raises_and_echoes_the_output():
    with pytest.raises(LLMError) as exc:
        answer(FakeCli("I'm not able to help with that.\n"))
    assert "no parseable JSON object" in str(exc.value)
    assert "I'm not able to help with that." in str(exc.value)


def test_a_wall_of_prose_is_truncated_in_the_error():
    with pytest.raises(LLMError) as exc:
        answer(FakeCli("no json here " * 200))
    assert "chars total" in str(exc.value)
    assert len(str(exc.value)) < 600


# --- failure is loud --------------------------------------------------------------


def test_timeout_raises_rather_than_returning_a_default():
    with pytest.raises(LLMError) as exc:
        provider(never_returns, timeout=0.5).complete_json("be terse", "is 7 > 3?", {})
    assert "0.5s" in str(exc.value)


def test_non_zero_exit_carries_the_cli_complaint():
    with pytest.raises(LLMError) as exc:
        answer(FakeCli(returncode=1, stderr="Invalid API key"))
    assert "exited 1" in str(exc.value)
    assert "Invalid API key" in str(exc.value)


def test_a_spawn_failure_arrives_as_an_llm_error():
    """Callers catch LLMError; a raw OSError escaping here would end the whole run."""
    with pytest.raises(LLMError):
        provider(unrunnable).complete_json("be terse", "is 7 > 3?", {})


# --- provider selection -----------------------------------------------------------


def test_no_env_var_is_still_deterministic(monkeypatch):
    monkeypatch.delenv("QABOT_LLM", raising=False)
    assert isinstance(default_provider(), DeterministicLLM)


def test_claude_cli_is_selected_by_name(monkeypatch):
    monkeypatch.setenv("QABOT_LLM", "claude-cli")
    monkeypatch.setenv("QABOT_CLAUDE_BIN", PRESENT)
    assert default_provider().name == "claude-cli"


def test_anthropic_selection_is_unchanged(monkeypatch):
    monkeypatch.setenv("QABOT_LLM", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError) as exc:
        default_provider()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


# --- the real thing ---------------------------------------------------------------


@pytest.mark.live_llm
@pytest.mark.skipif(
    not os.environ.get("QABOT_LIVE_LLM"),
    reason="set QABOT_LIVE_LLM=1 to spend real tokens on the installed claude CLI",
)
def test_live_cli_returns_a_usable_verdict():
    """The only test here that proves the flag names and the parsing agree with the
    CLI as actually installed. Everything else would keep passing if they did not."""
    verdict = ClaudeCliLLM().complete_json(
        "You answer with one JSON object and nothing else.",
        'Does the number 7 exceed the number 3? Answer {"held": bool, "reason": str}',
        {"held": "bool", "reason": "str"},
    )
    assert verdict["held"] is True
    assert isinstance(verdict["reason"], str)
