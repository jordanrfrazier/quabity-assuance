"""Run the application the way each journey needs it.

A journey's `preconditions.settings` is a contract about the server, not a hint for the
reader. This module honours it: journeys are grouped by the settings they need, and for
each group the application is started with exactly those settings, health-checked, walked,
and stopped. A precondition that names a *thing* rather than a value -- "a custom
components path containing one component named MyTool" -- is materialised on disk before
the start, by the model, and the report says what was written.

Everything here is local: the command is one the operator supplied, the environment is
the operator's plus the journey's, and nothing is sent anywhere.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from spikes.journeys.models import Journey

#: Langflow reads every settings field from the environment under this prefix, so a
#: precondition written as `settings.components_path` is served by LANGFLOW_COMPONENTS_PATH.
ENV_PREFIX = "LANGFLOW_"
HEALTH_TIMEOUT_S = 240.0
HEALTH_POLL_S = 3.0

FIXTURE_SYSTEM = (
    "You write the smallest possible Langflow custom component that satisfies a described "
    'precondition. Answer ONLY a JSON object {"files": {"<relative path>": "<python '
    'source>"}}. Paths are relative to the custom components directory and must include a '
    "category subfolder (e.g. tools/my_tool.py). Each file defines one class deriving from "
    "lfx.custom.Component with display_name, description, inputs (MessageTextInput) and one "
    "Output whose method returns a Message. No network, no extra imports beyond lfx."
)


class LaunchSpec(BaseModel):
    command: str
    health_url: str
    cwd: str
    base_env: dict[str, str] = Field(default_factory=dict)


class Materialised(BaseModel):
    """What was written to satisfy a value-less precondition, so the report can say so."""

    setting: str
    path: str
    files: dict[str, str] = Field(default_factory=dict)


def env_key(setting: str) -> str:
    """`settings.components_path` -> LANGFLOW_COMPONENTS_PATH; env names pass through."""
    if setting.startswith("settings."):
        return ENV_PREFIX + setting[len("settings.") :].upper()
    return setting


def needs_materialising(value: str) -> bool:
    """A precondition value that describes a thing to create rather than a value to set."""
    return bool(
        re.search(r"/path/to|contains|symlink|written with|directory", value, re.IGNORECASE)
    )


def group_by_settings(journeys: list[Journey]) -> list[tuple[dict[str, str], list[Journey]]]:
    """Journeys that need the same settings share one server start. Order is preserved
    by first appearance, so journey 1's group runs first."""
    groups: list[tuple[dict[str, str], list[Journey]]] = []
    for j in journeys:
        wanted = {env_key(k): v for k, v in j.preconditions.settings.items()}
        for settings, members in groups:
            if settings == wanted:
                members.append(j)
                break
        else:
            groups.append((wanted, [j]))
    return groups


def materialise(setting: str, description: str, root: Path, llm) -> Materialised:
    """Ask the model for the files the precondition describes and write them under `root`."""
    # Absolute on purpose: the application runs from its own working directory, and a
    # relative fixture path was silently "non-existent" to it.
    target = Path(root).resolve() / re.sub(r"[^a-z0-9]+", "_", setting.lower()).strip("_")
    target.mkdir(parents=True, exist_ok=True)
    raw = llm.complete_json(FIXTURE_SYSTEM, f"Precondition: {setting} = {description}", {})
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict) or not files:
        raise RuntimeError(f"model produced no files for precondition {setting!r}")
    written: dict[str, str] = {}
    for rel, source in files.items():
        rel = str(rel).lstrip("/")
        if ".." in rel or not rel.endswith(".py"):
            raise RuntimeError(f"refusing to write fixture path {rel!r}")
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(source))
        written[rel] = str(source)
    return Materialised(setting=setting, path=str(target), files=written)


def resolve_settings(
    settings: dict[str, str], fixtures_root: Path, llm
) -> tuple[dict[str, str], list[Materialised]]:
    """Turn a group's settings into environment values, materialising the ones that
    describe a thing. Returns the env and what was written."""
    env: dict[str, str] = {}
    made: list[Materialised] = []
    for key, value in settings.items():
        if re.search(r"built-?in components? (directory|path|folder)", value, re.IGNORECASE):
            continue  # a precondition about the product's own directory is not ours to fabricate
        if needs_materialising(value):
            m = materialise(key, value, fixtures_root, llm)
            made.append(m)
            env[key] = m.path
        else:
            env[key] = str(value)
    return env, made


class Instance:
    """One started application. `stop()` always terminates what `start()` began."""

    def __init__(self, spec: LaunchSpec, env: dict[str, str], log_path: Path):
        self.spec = spec
        self.env = env
        self.log_path = Path(log_path)
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        full_env = {**os.environ, **self.spec.base_env, **self.env}
        self._log = self.log_path.open("w")
        self._proc = subprocess.Popen(
            self.spec.command,
            shell=True,
            cwd=self.spec.cwd,
            env=full_env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def wait_healthy(self, timeout: float = HEALTH_TIMEOUT_S) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False
            with (
                contextlib.suppress(Exception),
                urllib.request.urlopen(self.spec.health_url, timeout=5) as r,
            ):
                if 200 <= r.status < 300:
                    return True
            time.sleep(HEALTH_POLL_S)
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(self._proc.pid), 15)
        with contextlib.suppress(Exception):
            self._proc.wait(timeout=20)
        if self._proc.poll() is None:
            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(self._proc.pid), 9)
        with contextlib.suppress(Exception):
            self._log.close()
        self._proc = None
