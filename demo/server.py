"""Run the demo app on a real port.

WHY a real server: a browser needs a real origin. Cookies, redirects, form posts and
navigation all behave differently against an in-process ASGI transport, so a browser
run that used the transport shortcut would be testing a fiction. The HTTP demo keeps
the shortcut because for HTTP it changes nothing.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI

#: How long to wait for uvicorn to come up before giving up loudly.
STARTUP_TIMEOUT_S = 10.0


@contextlib.contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    """Serve `app` on an ephemeral port for the duration of the block.

    The listening socket is bound here and handed to uvicorn, rather than picking a
    free port and reconnecting to it, so nothing can claim the port in between.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()

    deadline = time.time() + STARTUP_TIMEOUT_S
    while not server.started:
        if time.time() > deadline:
            server.should_exit = True
            raise RuntimeError(f"demo server did not start within {STARTUP_TIMEOUT_S}s")
        time.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
