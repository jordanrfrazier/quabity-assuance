"""Knowledge base persistence.

Hosted in production; a JSON file here. Snapshots are what the runner reads: the
runner never mutates the KB, it emits open questions that the async curator loop
applies. `snapshot()` returns a deep copy to enforce that at the type level.
"""

from __future__ import annotations

import json
from pathlib import Path

from qabot.models import KnowledgeBase


class KBStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> KnowledgeBase:
        if not self.path.exists():
            raise FileNotFoundError(f"no knowledge base at {self.path}")
        return KnowledgeBase.model_validate_json(self.path.read_text())

    def save(self, kb: KnowledgeBase) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(kb.model_dump(mode="json"), indent=2) + "\n")

    def snapshot(self) -> KnowledgeBase:
        """An immutable-for-this-run copy, pinned at read time."""
        return self.load().model_copy(deep=True)
