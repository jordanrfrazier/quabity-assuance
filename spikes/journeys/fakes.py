"""A scripted model for tests. Replays responses in order and remembers every prompt,
so a test can assert both what the code did with an answer and what it asked."""

from __future__ import annotations


class FakeLLM:
    name = "fake"

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, prompt: str, schema_hint: dict) -> dict:
        self.calls.append({"system": system, "prompt": prompt})
        if not self._responses:
            raise RuntimeError(f"FakeLLM has no more responses (call {len(self.calls)})")
        return self._responses.pop(0)
