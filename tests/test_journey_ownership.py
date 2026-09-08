import os
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from qabot.journeys.ownership import ensure_endpoint_available, require_owned_endpoint


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _free_dual_stack_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ipv4:
        ipv4.bind(("127.0.0.1", 0))
        port = ipv4.getsockname()[1]
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as ipv6:
            ipv6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            ipv6.bind(("::1", port))
    return port


def _wait_for_listen(port, *, host="127.0.0.1", family=socket.AF_INET, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for test listener on {port}")


def _terminate_group(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, 15)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, 9)
        process.wait(timeout=5)


@pytest.fixture
def test_processes():
    processes = []
    try:
        yield processes
    finally:
        for process in processes:
            _terminate_group(process)


def _start_http_server(port, test_processes, *, status=200):
    code = f"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response({status})
        self.end_headers()
        self.wfile.write(b"test")

    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
"""
    process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    test_processes.append(process)
    _wait_for_listen(port)
    return process


def _start_tcp_listener(port, test_processes, *, host):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    code = f"""
import socket
import time

family = socket.AF_INET6 if {family == socket.AF_INET6!r} else socket.AF_INET
sock = socket.socket(family, socket.SOCK_STREAM)
if family == socket.AF_INET6:
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(({host!r}, {port}))
sock.listen()
time.sleep(60)
"""
    process = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    test_processes.append(process)
    _wait_for_listen(port, host=host, family=family)
    return process


def test_available_endpoint_passes_when_no_local_listener_exists():
    port = _free_port()

    ensure_endpoint_available(f"http://127.0.0.1:{port}/health")


def test_available_endpoint_rejects_foreign_listener_returning_503(test_processes):
    port = _free_port()
    _start_http_server(port, test_processes, status=503)

    with pytest.raises(RuntimeError, match="already.*listening"):
        ensure_endpoint_available(f"http://127.0.0.1:{port}/health")


def test_available_endpoint_rejects_ipv6_listener_on_target_port(test_processes):
    try:
        port = _free_dual_stack_port()
    except OSError as exc:
        pytest.skip(f"IPv6 loopback binding unavailable: {exc}")
    _start_tcp_listener(port, test_processes, host="::1")

    with pytest.raises(RuntimeError, match="already.*listening"):
        ensure_endpoint_available(f"http://127.0.0.1:{port}/health")


def test_owned_endpoint_accepts_live_reviewed_process_listener(test_processes):
    port = _free_port()
    process = _start_http_server(port, test_processes)

    require_owned_endpoint(f"http://127.0.0.1:{port}/health", process)


def test_owned_endpoint_requires_reviewed_process_group_to_match_pid(monkeypatch):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        monkeypatch.setattr(
            "qabot.journeys.ownership.subprocess.run",
            lambda *args, **kwargs: SimpleNamespace(
                returncode=0,
                stdout=f"p{process.pid}\nf3\nPTCP\nn127.0.0.1:43210\nTST=LISTEN\n",
                stderr="",
            ),
        )

        with pytest.raises(RuntimeError, match="start_new_session"):
            require_owned_endpoint("http://127.0.0.1:43210/", process)
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_owned_endpoint_rejects_foreign_listener_while_reviewed_process_is_alive(test_processes):
    port = _free_port()
    owned_sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    test_processes.append(owned_sleeper)
    _start_http_server(port, test_processes, status=200)

    with pytest.raises(RuntimeError, match="not owned"):
        require_owned_endpoint(f"http://127.0.0.1:{port}/health", owned_sleeper)


def test_owned_endpoint_rejects_mixed_ownership_on_same_port_different_binds(test_processes):
    try:
        port = _free_dual_stack_port()
    except OSError as exc:
        pytest.skip(f"IPv6 loopback binding unavailable: {exc}")
    owned = _start_tcp_listener(port, test_processes, host="127.0.0.1")
    _start_tcp_listener(port, test_processes, host="::1")

    with pytest.raises(RuntimeError, match="not owned"):
        require_owned_endpoint(f"http://127.0.0.1:{port}/health", owned)


def test_owned_endpoint_rechecks_reviewed_process_after_listener_inspection(monkeypatch):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )

    def inspect_and_exit(*args, **kwargs):
        process.terminate()
        process.wait(timeout=5)
        return SimpleNamespace(
            returncode=0,
            stdout=f"p{process.pid}\nf3\nPTCP\nn127.0.0.1:43210\nTST=LISTEN\n",
            stderr="",
        )

    monkeypatch.setattr("qabot.journeys.ownership.subprocess.run", inspect_and_exit)

    with pytest.raises(RuntimeError, match="exited"):
        require_owned_endpoint("http://127.0.0.1:43210/", process)


def test_owned_endpoint_rejects_dead_reviewed_process():
    port = _free_port()
    process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    process.wait(timeout=5)

    with pytest.raises(RuntimeError, match="exited"):
        require_owned_endpoint(f"http://127.0.0.1:{port}/health", process)


def test_available_endpoint_fails_when_listener_inspection_is_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr("qabot.journeys.ownership.subprocess.run", unavailable)

    with pytest.raises(RuntimeError, match="inspect.*listeners"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_when_listener_inspection_times_out(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["lsof"], timeout=5)

    monkeypatch.setattr("qabot.journeys.ownership.subprocess.run", timeout)

    with pytest.raises(RuntimeError, match="timed out"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_when_lsof_exit_one_has_stderr(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="permission denied"
        ),
    )

    with pytest.raises(RuntimeError, match="Unable to inspect"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_when_lsof_exit_zero_has_no_records(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="Unexpected listener inspection output"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_on_malformed_listener_inspection(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="pnot-a-pid\nPTCP\nn127.0.0.1:43210\n"),
    )

    with pytest.raises(RuntimeError, match="Unexpected listener inspection output"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_on_incomplete_lsof_process_record(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="p12345\n", stderr=""),
    )

    with pytest.raises(RuntimeError, match="Unexpected listener inspection output"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_fails_on_wrong_port_lsof_record(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="p12345\nf3\nPTCP\nn127.0.0.1:43211\nTST=LISTEN\n",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="Unexpected listener inspection output"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_available_endpoint_parses_ipv6_and_wildcard_lsof_records(monkeypatch):
    monkeypatch.setattr(
        "qabot.journeys.ownership.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                "p12345\nf3\nPTCP\nn[::1]:43210\nTST=LISTEN\n"
                "p23456\nf4\nPTCP\nn*:43210\nTST=LISTEN\n"
            ),
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="already.*listening"):
        ensure_endpoint_available("http://127.0.0.1:43210/")


def test_owned_endpoint_fails_when_process_disappears_during_ownership_check(monkeypatch):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        monkeypatch.setattr(process, "poll", lambda: None)

        def gone(_pid):
            raise ProcessLookupError(_pid)

        monkeypatch.setattr("qabot.journeys.ownership.os.getpgid", gone)

        with pytest.raises(RuntimeError, match="process disappeared"):
            require_owned_endpoint("http://127.0.0.1:43210/", process)
    finally:
        _terminate_group(process)


def test_unsupported_url_fails_closed():
    with pytest.raises(ValueError, match="local HTTP"):
        ensure_endpoint_available("file:///tmp/app")
