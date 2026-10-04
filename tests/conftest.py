"""A real (threaded, HTTP/1.1, keep-alive capable) local server for end-to-end tests.

Unlike in-process mocks it goes through actual sockets, so it can verify
connection reuse and how truncated bodies surface from the HTTP stack.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

FILE_SIZE = 2_000_000
_CHUNK = 64 * 1024


@dataclass
class ServerState:
    base_url: str
    client_ports: list[int] = field(default_factory=list)
    flaky_hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @property
    def connections(self) -> int:
        return len(set(self.client_ports))


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    state: ServerState


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # enables persistent connections
    server: _Server

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
        with state.lock:
            state.client_ports.append(self.client_address[1])
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


@pytest.fixture
def http_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[ServerState]:
    # Corporate proxy variables must not hijack requests to the local server.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)

    server = _Server(("127.0.0.1", 0), _Handler)
    host, port = server.server_address[:2]
    server.state = ServerState(base_url=f"http://{host!s}:{port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
