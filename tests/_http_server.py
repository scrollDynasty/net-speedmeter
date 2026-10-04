"""A real (threaded, HTTP/1.1, keep-alive capable) local server for end-to-end tests.

Unlike in-process mocks it goes through actual sockets, so it can verify
connection reuse and how dropped connections surface from the HTTP stack.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

FILE_SIZE = 2_000_000
_CHUNK = 64 * 1024


@dataclass
class ServerState:
    base_url: str
    connections_opened: int = 0
    flaky_hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    state: ServerState


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # enables persistent connections
    server: _Server

    def setup(self) -> None:
        # One handler instance per accepted TCP connection: count connections
        # directly instead of guessing from client ports (which can be reused).
        super().setup()
        with self.server.state.lock:
            self.server.state.connections_opened += 1

    def log_message(self, format: str, *args: object) -> None:
        """Keep test output clean."""

    def _send_body(self, size: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        chunk = b"\0" * _CHUNK
        remaining = size
        while remaining > 0:
            part = chunk[: min(_CHUNK, remaining)]
            self.wfile.write(part)
            remaining -= len(part)

    def _send_status(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        state = self.server.state
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)

        if parts.path == "/file":
            self._send_body(int(query.get("size", [str(FILE_SIZE)])[0]))
        elif parts.path == "/flaky":
            with state.lock:
                state.flaky_hits += 1
                hit = state.flaky_hits
            if hit % 2 == 0:
                self._send_status(503)
            else:
                self._send_body(FILE_SIZE)
        elif parts.path == "/truncated":
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 400)
            self.close_connection = True
        else:
            self._send_status(404)


@contextmanager
def running_server() -> Iterator[ServerState]:
    server = _Server(("127.0.0.1", 0), _Handler)
    host, port = server.server_address[:2]
    server.state = ServerState(base_url=f"http://{host!s}:{port}")
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def closed_port_url() -> str:
    """URL of a localhost port that is guaranteed to have no listener."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))  # bound but never listening, released on exit
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/file"
