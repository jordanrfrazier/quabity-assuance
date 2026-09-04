"""LLM boundary.

Everything model-driven goes through `LLMProvider`. Three implementations:
`DeterministicLLM` (no network, used by tests and by the demo), `AnthropicLLM` (real,
over the SDK) and `ClaudeCliLLM` (real, over the locally installed `claude` CLI, for
machines that have a logged-in Claude Code and no API key). Selection is explicit and
failure is loud: asking for a real provider without what it needs -- a key for one, the
binary on PATH for the other -- raises rather than silently degrading to the fake, because
an evaluation that quietly ran against the rule-based stand-in measures nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        """Return a JSON object conforming loosely to `schema_hint`."""
        ...


class DeterministicLLM:
    """Rule-based stand-in. Resolves step intents using seeded hints and evaluates
    expectations by keyword matching against observed evidence.

    It is deliberately dumb: the prototype's value is the surrounding machinery
    (provenance capping, staleness, three-outcome verification), and a deterministic
    provider makes that machinery testable without a network or an API key.
    """

    name = "deterministic"

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        raise LLMError(
            "DeterministicLLM has no general completion path; callers must use the "
            "explicit resolve_step/evaluate_expectation helpers in planner.py and "
            "verifier.py, which fall back to deterministic rules."
        )


class AnthropicLLM:
    """Real provider. Constructed only when a key is present."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Refusing to construct AnthropicLLM. "
                "Use DeterministicLLM explicitly if you want the offline path."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError("anthropic package not installed; pip install 'qabot[llm]'") from exc
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        import json

        msg = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError(f"model returned no JSON object: {text[:200]!r}")
        return json.loads(text[start : end + 1])


#: One CLI call is a whole agent session, so seconds -- not milliseconds -- is normal.
#: The cap exists so a stalled session cannot hang a CI run indefinitely.
DEFAULT_CLI_TIMEOUT = 120.0

#: How much offending output an error message carries. Enough to see what the model
#: actually said, short enough that a log line stays readable.
_ECHO_CHARS = 400

#: The subprocess boundary, as a type. See `ClaudeCliLLM` for why it is injectable.
Runner = Callable[[list[str], str, float], "subprocess.CompletedProcess[str]"]


def _run_cli(argv: list[str], prompt: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """The real spawn. The prompt goes in on stdin rather than in `argv` -- see
    `ClaudeCliLLM.complete_json`.

    `check=False` because a non-zero exit is reported by `ClaudeCliLLM` as an LLMError
    carrying the CLI's own complaint, which is more use to a reader than a
    CalledProcessError."""
    return subprocess.run(
        argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False
    )


class ClaudeCliLLM:
    """Real provider driven through the locally installed `claude` CLI.

    Exists because a developer machine often has a logged-in Claude Code and no
    ANTHROPIC_API_KEY at all, and on such a machine `AnthropicLLM` cannot even be
    constructed. The alternative is running an evaluation against `DeterministicLLM`
    and quietly reporting the rule-based stand-in's numbers as a model's -- exactly
    the confident-wrong-answer failure this codebase exists to avoid. A process per
    call and a few seconds of latency are a cheap price for measuring the real thing.

    The subprocess boundary is injected for the same reason `HttpDriver` takes a
    client: unit tests must exercise the parsing without spawning an agent session,
    and injection keeps the argv this class builds under test rather than patched out.
    """

    name = "claude-cli"

    def __init__(
        self,
        binary: str | None = None,
        timeout: float = DEFAULT_CLI_TIMEOUT,
        runner: Runner | None = None,
    ):
        requested = binary or os.environ.get("QABOT_CLAUDE_BIN") or "claude"
        resolved = shutil.which(requested)
        if resolved is None:
            raise LLMError(
                f"claude CLI {requested!r} is not on PATH. Refusing to construct "
                "ClaudeCliLLM. Point QABOT_CLAUDE_BIN at the binary, or use "
                "DeterministicLLM explicitly if you want the offline path."
            )
        self._binary = resolved
        self._timeout = timeout
        self._run = runner or _run_cli

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        """Ask the CLI once, headless, and read one JSON object back.

        **The prompt goes in on stdin, never in argv.** argv is capped at ARG_MAX --
        1 MiB on macOS -- and prompts here are not small by construction: `HttpDriver`
        records `response.text` uncapped, and `verifier.py` JSON-escapes the whole
        evidence dict into the prompt. One server-rendered page from a real app is
        enough to turn every model call in a run into an E2BIG, which is a failure mode
        that scales with how interesting the app under test is. stdin has no such cap.
        `system` stays on argv: it is small, fixed, and belongs to a named flag.

        `schema_hint` is ignored for the same reason `AnthropicLLM` ignores it: every
        caller already restates the shape it wants inside `prompt`, and a provider that
        silently rewrote the prompt would make what the model saw unauditable.
        """
        argv = [self._binary, "--append-system-prompt", system, "-p"]
        try:
            completed = self._run(argv, prompt, self._timeout)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f"claude CLI produced no answer within {self._timeout}s; treat this as a "
                "gap, not as a verdict"
            ) from exc
        except OSError as exc:
            # The PATH check happens in __init__, so reaching here means the binary
            # moved or is unrunnable. Still an LLMError: callers catch that type, and
            # a raw OSError escaping this boundary would take down a whole run.
            raise LLMError(f"could not run the claude CLI at {self._binary!r}: {exc}") from exc

        if completed.returncode != 0:
            raise LLMError(
                f"claude CLI exited {completed.returncode}: "
                f"{_echo(completed.stderr or completed.stdout)}"
            )
        return _first_json_object(completed.stdout)


def _first_json_object(text: str) -> dict:
    """The first JSON object in `text`, however it happens to be dressed.

    The CLI is a chat interface rather than an API, so it will wrap an answer in prose
    or in a ```json fence whenever it feels like it. Scanning for the first `{` that
    decodes handles both without having to detect which happened, and unlike bracketing
    on the first `{` and last `}` it does not choke on a stray brace in the surrounding
    prose.

    No object at all raises. Returning `{}` would be worse than useless: `verifier.py`
    reads a verdict without a usable `held` as BLOCKED, so a broken provider would
    disguise itself as a model that merely had no opinion, and the run would report
    honest-looking gaps that were really a bug in this file.
    """
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise LLMError(f"claude CLI returned no parseable JSON object: {_echo(text)!r}")


def _echo(text: str) -> str:
    """Offending output, trimmed, with the original length kept so a reader can tell a
    short refusal from a truncated wall of prose."""
    stripped = text.strip()
    if len(stripped) <= _ECHO_CHARS:
        return stripped
    return f"{stripped[:_ECHO_CHARS]}... ({len(stripped)} chars total)"


def default_provider() -> LLMProvider:
    """Deterministic unless a real provider is asked for by name. Never silently uses
    the network, and never silently substitutes the fake for a real one that failed."""
    requested = os.environ.get("QABOT_LLM")
    if requested == "anthropic":
        return AnthropicLLM()
    if requested == "claude-cli":
        return ClaudeCliLLM()
    return DeterministicLLM()
