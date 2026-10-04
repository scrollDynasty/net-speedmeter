from __future__ import annotations

from collections.abc import Iterator

import pytest
from _http_server import ServerState, running_server

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _no_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither env proxies nor OS-level ones (Windows registry, macOS settings) may
    hijack requests to the local test server."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")


@pytest.fixture
def http_server() -> Iterator[ServerState]:
    with running_server() as state:
        yield state
