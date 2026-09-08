"""Structured, text-only journey model calls with no repository tool permissions."""

import json
import shutil
import subprocess

from qabot.llm import LLMError


def _response_schema(hint):
    if "op" in hint:
        return {
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "enum": [
                        "goto",
                        "click",
                        "fill",
                        "select",
                        "read",
                        "press",
                        "wait",
                        "done",
                        "blocked",
                    ],
                },
                "state": {"type": "string", "enum": ["visible", "hidden", "enabled"]},
                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 60000},
                "repeat": {"type": "integer", "minimum": 1, "maximum": 30},
                **{
                    name: {"type": "string"}
                    for name in (
                        "path",
                        "role",
                        "name",
                        "value",
                        "key",
                        "within_role",
                        "within_name",
                        "reason",
                    )
                },
            },
            "required": ["op"],
            "additionalProperties": False,
        }
    if "verdict" in hint:
        return {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["held", "failed", "unclear"]},
                "reason": {"type": "string"},
                "recorded_errors": {
                    "type": "string",
                    "enum": ["expected", "unexpected", "unclear", "none"],
                },
            },
            "required": ["verdict", "reason", "recorded_errors"],
            "additionalProperties": False,
        }
    from qabot.journeys.models import ReviewPlan

    schema = ReviewPlan.model_json_schema()
    for field in ("repo", "base", "head", "description"):
        schema["properties"].pop(field)
    schema["required"] = ["startup", "journeys", "unresolved", "sources"]
    return schema


class JourneyLLM:
    name = "claude-cli/sonnet"

    def __init__(self, timeout=120):
        self.binary = shutil.which("claude")
        if self.binary is None:
            raise LLMError(
                "The authenticated claude CLI is required for journey authoring/execution"
            )
        self.timeout = timeout

    def complete_json(self, system, prompt, schema_hint):
        schema = _response_schema(schema_hint)
        argv = [
            self.binary,
            "-p",
            "--system-prompt",
            system,
            "--tools",
            "",
            "--safe-mode",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--model",
            "sonnet",
            "--effort",
            "medium",
            "--json-schema",
            json.dumps(schema),
            "--output-format",
            "json",
        ]
        try:
            completed = subprocess.run(
                argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Claude completion timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise LLMError(f"Claude CLI could not start: {type(exc).__name__}") from exc
        if completed.returncode:
            raise LLMError(
                f"Claude CLI exited {completed.returncode}; check local model access/quota"
            )
        try:
            envelope = json.loads(completed.stdout)
            result = envelope.get("structured_output")
        except (ValueError, AttributeError) as exc:
            raise LLMError("Claude returned no valid structured response envelope") from exc
        if not isinstance(result, dict) or any(key not in result for key in schema_hint):
            raise LLMError(
                "Claude returned no complete structured response; no verdict was inferred"
            )
        return result


def journey_provider(*, timeout=120):
    return JourneyLLM(timeout=timeout)
