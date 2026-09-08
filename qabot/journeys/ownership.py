"""Verify that local journey startup endpoints are free and owned."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class _Endpoint:
    host: str
    port: int


@dataclass(frozen=True)
class _Listener:
    pid: int
    name: str


def ensure_endpoint_available(health_url) -> None:
    endpoint = _parse_local_http_endpoint(health_url)
    listeners = _tcp_listeners(endpoint.port)
    if listeners:
        raise RuntimeError(f"Target port {endpoint.port} is already listening")


def require_owned_endpoint(health_url, process) -> None:
    endpoint = _parse_local_http_endpoint(health_url)
    if process.poll() is not None:
        raise RuntimeError("Application process exited before endpoint ownership could be verified")
    try:
        expected_group = os.getpgid(process.pid)
    except ProcessLookupError as exc:
        raise RuntimeError(
            "Application process disappeared before endpoint ownership could be verified"
        ) from exc
    if expected_group != process.pid:
        raise RuntimeError(
            "Application process group does not match its PID; start_new_session=True is required"
        )
    listeners = _tcp_listeners(endpoint.port)
    if process.poll() is not None:
        raise RuntimeError("Application process exited before endpoint ownership could be verified")
    if not listeners:
        raise RuntimeError(f"Target port {endpoint.port} has no verified local TCP listener")
    foreign = []
    for listener in listeners:
        try:
            listener_group = os.getpgid(listener.pid)
        except ProcessLookupError as exc:
            raise RuntimeError(
                f"Listener process {listener.pid} disappeared before endpoint ownership could "
                "be verified"
            ) from exc
        if listener_group != expected_group:
            foreign.append(listener)
    if foreign:
        pids = ", ".join(str(listener.pid) for listener in foreign)
        raise RuntimeError(
            f"Target port {endpoint.port} is not owned by the reviewed process group: {pids}"
        )


def _parse_local_http_endpoint(health_url) -> _Endpoint:
    parsed = urlsplit(str(health_url))
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Startup health URL must be a local HTTP endpoint")
    port = parsed.port or {"http": 80, "https": 443}[parsed.scheme]
    return _Endpoint(host=parsed.hostname, port=port)


def _tcp_listeners(port: int) -> list[_Listener]:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pcPTn"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Unable to inspect local TCP listeners: lsof is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Unable to inspect local TCP listeners: lsof timed out") from exc
    if not hasattr(result, "returncode") or not hasattr(result, "stdout"):
        raise RuntimeError("Unexpected listener inspection output")
    stderr = result.stderr if hasattr(result, "stderr") else ""
    if result.returncode not in {0, 1} or stderr.strip():
        raise RuntimeError("Unable to inspect local TCP listeners")
    if result.returncode == 0 and not result.stdout.strip():
        raise RuntimeError("Unexpected listener inspection output")
    if result.returncode == 1 and result.stdout.strip():
        raise RuntimeError("Unexpected listener inspection output")
    listeners = _parse_lsof_output(result.stdout, port)
    if result.stdout.strip() and not listeners:
        raise RuntimeError("Unexpected listener inspection output")
    return listeners


def _parse_lsof_output(output: str, port: int) -> list[_Listener]:
    listeners: list[_Listener] = []
    current_pid: int | None = None
    protocol: str | None = None
    state = False
    names: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        field = raw_line[0]
        value = raw_line[1:]
        if field == "p":
            listeners.extend(_record_listeners(current_pid, protocol, state, names, port))
            try:
                current_pid = int(value)
            except ValueError as exc:
                raise RuntimeError("Unexpected listener inspection output") from exc
            protocol = None
            state = False
            names = []
        elif field == "P":
            protocol = value
        elif field == "T":
            if value == "ST=LISTEN":
                state = True
        elif field == "n":
            if current_pid is None:
                raise RuntimeError("Unexpected listener inspection output")
            names.append(value)
        elif field in {"c", "f"}:
            if current_pid is None:
                raise RuntimeError("Unexpected listener inspection output")
        else:
            raise RuntimeError("Unexpected listener inspection output")
    listeners.extend(_record_listeners(current_pid, protocol, state, names, port))
    return listeners


def _record_listeners(
    pid: int | None, protocol: str | None, state: bool, names: list[str], port: int
) -> list[_Listener]:
    if pid is None:
        if protocol or state or names:
            raise RuntimeError("Unexpected listener inspection output")
        return []
    if protocol not in {None, "TCP"}:
        raise RuntimeError("Unexpected listener inspection output")
    if not state or not names:
        raise RuntimeError("Unexpected listener inspection output")
    listeners = []
    for name in names:
        if _name_uses_port(name, port):
            listeners.append(_Listener(pid=pid, name=name))
    return listeners


def _name_uses_port(name: str, port: int) -> bool:
    if ":" not in name:
        raise RuntimeError("Unexpected listener inspection output")
    _, raw_port = name.rsplit(":", 1)
    try:
        return int(raw_port) == port
    except ValueError as exc:
        raise RuntimeError("Unexpected listener inspection output") from exc
