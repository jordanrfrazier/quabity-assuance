"""Package a completed journey run and its referenced evidence."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

REQUIRED_REPORTS = ("report.html", "report.md", "results.json")
VIDEO_SUFFIXES = {".webm", ".mp4", ".mov"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class BundleError(ValueError):
    """A journey run cannot be safely packaged."""


def _regular_nonempty(path: Path, label: str) -> None:
    try:
        stat = path.lstat()
    except OSError as exc:
        raise BundleError(f"missing {label}: {path}") from exc
    if path.is_symlink():
        raise BundleError(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise BundleError(f"{label} must be a regular file: {path}")
    if stat.st_size == 0:
        raise BundleError(f"{label} must not be empty: {path}")


def _child_without_symlinks(root: Path, reference: str, label: str, suffixes: set[str]) -> Path:
    if not isinstance(reference, str) or not reference:
        raise BundleError(f"{label} must be a non-empty relative path")
    if "\\" in reference or ":" in reference:
        raise BundleError(f"{label} must be a portable relative path: {reference}")
    ref = Path(reference)
    if ref.is_absolute():
        raise BundleError(f"{label} must be relative: {reference}")
    if any(part in {"", ".", ".."} for part in ref.parts):
        raise BundleError(f"{label} must stay within the run directory: {reference}")
    if ref.suffix.lower() not in suffixes:
        raise BundleError(f"{label} has unsupported evidence type: {reference}")
    path = root / ref
    current = root
    for part in ref.parts:
        current = current / part
        if current.is_symlink():
            raise BundleError(f"{label} must not contain symlinks: {reference}")
    _regular_nonempty(path, label)
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise BundleError(f"{label} escapes the run directory: {reference}") from exc
    except OSError as exc:
        raise BundleError(f"missing {label}: {reference}") from exc
    return path


def _optional_reference(value: Any, root: Path, label: str, suffixes: set[str]) -> Path | None:
    if value is None or value == "":
        return None
    return _child_without_symlinks(root, value, label, suffixes)


def _result_evidence(root: Path, metadata: dict[str, Any]) -> list[Path]:
    if metadata.get("artifact_paths") != "relative-to-report":
        raise BundleError("results.json metadata must declare artifact_paths='relative-to-report'")
    if not isinstance(metadata.get("model"), str) or not metadata["model"]:
        raise BundleError("results.json metadata must include a non-empty model")
    results = metadata.get("results")
    if not isinstance(results, list):
        raise BundleError("results.json metadata must include a results list")

    evidence: list[Path] = []
    for result_index, result in enumerate(results):
        if not isinstance(result, dict):
            raise BundleError(f"results[{result_index}] must be an object")
        video = _optional_reference(
            result.get("video"), root, f"results[{result_index}].video", VIDEO_SUFFIXES
        )
        if video is not None:
            evidence.append(video)
        steps = result.get("steps")
        if not isinstance(steps, list):
            raise BundleError(f"results[{result_index}].steps must be a list")
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise BundleError(f"results[{result_index}].steps[{step_index}] must be an object")
            screenshot = _optional_reference(
                step.get("screenshot"),
                root,
                f"results[{result_index}].steps[{step_index}].screenshot",
                IMAGE_SUFFIXES,
            )
            if screenshot is not None:
                evidence.append(screenshot)
            actions = step.get("actions")
            if not isinstance(actions, list):
                raise BundleError(
                    f"results[{result_index}].steps[{step_index}].actions must be a list"
                )
            for action_index, action in enumerate(actions):
                if not isinstance(action, dict):
                    raise BundleError(
                        f"results[{result_index}].steps[{step_index}].actions[{action_index}] "
                        "must be an object"
                    )
                action_screenshot = _optional_reference(
                    action.get("screenshot"),
                    root,
                    (
                        f"results[{result_index}].steps[{step_index}]."
                        f"actions[{action_index}].screenshot"
                    ),
                    IMAGE_SUFFIXES,
                )
                if action_screenshot is not None:
                    evidence.append(action_screenshot)
    return evidence


def bundle_run(run_dir: Path) -> Path:
    """Create a ZIP archive beside ``run_dir`` containing reports and referenced evidence."""

    root = Path(run_dir).resolve()
    if not root.is_dir():
        raise BundleError(f"run directory does not exist: {run_dir}")

    reports = [root / name for name in REQUIRED_REPORTS]
    for report in reports:
        _regular_nonempty(report, report.name)
    try:
        metadata = json.loads((root / "results.json").read_text())
    except json.JSONDecodeError as exc:
        raise BundleError(f"results.json is malformed: {exc.msg}") from exc
    if not isinstance(metadata, dict):
        raise BundleError("results.json must contain an object")

    paths = reports + _result_evidence(root, metadata)
    archive = root.with_name(root.name + ".zip")
    created = False
    try:
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zf:
            created = True
            seen: set[str] = set()
            for path in paths:
                name = path.relative_to(root).as_posix()
                if name in seen:
                    continue
                seen.add(name)
                zf.write(path, name)
    except FileExistsError as exc:
        raise BundleError(f"archive already exists: {archive}") from exc
    except BaseException:
        if created:
            try:
                archive.unlink()
            except FileNotFoundError:
                pass
        raise
    return archive
