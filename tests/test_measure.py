import gzip
from collections.abc import Callable, Iterator

import httpx
import pytest

from net_speedmeter.measure import (
    USER_AGENT,
    build_client,
    iter_benchmark,
    measure_once,
    validate_url,
)

URL = "https://example.test/big.jpg"
BODY = b"\xff" * 300_000

Handler = Callable[[httpx.Request], httpx.Response]


class StepClock:
    """Deterministic clock: every call advances time by ``step`` seconds."""

    def __init__(self, step: float = 0.5) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


class ChunkedStream(httpx.SyncByteStream):
    """Unread body delivered in several chunks, like a real socket would."""

    def __init__(self, body: bytes, chunk_size: int = 64 * 1024) -> None:
        self.body = body
        self.chunk_size = chunk_size

    def __iter__(self) -> Iterator[bytes]:
        for offset in range(0, len(self.body), self.chunk_size):
            yield self.body[offset : offset + self.chunk_size]


def streamed(
    body: bytes, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Length": str(len(body)), **(headers or {})},
        stream=ChunkedStream(body),
    )


def client_for(handler: Handler) -> httpx.Client:
    return build_client(timeout=5.0, keepalive=True, transport=httpx.MockTransport(handler))


def serve(body: bytes = BODY, status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return streamed(body, status)

    return handler


def test_successful_request_records_bytes_and_timings() -> None:
    with client_for(serve()) as client:
        result = measure_once(client, URL, index=1, clock=StepClock(0.5))

    assert result.ok
    assert result.error is None
    assert result.status_code == 200
    assert result.bytes_downloaded == len(BODY)
    # clock: start=0.0, headers=0.5, last byte=1.0
    assert result.ttfb == pytest.approx(0.5)
    assert result.request_time == pytest.approx(1.0)
    assert result.transfer_time == pytest.approx(0.5)
    assert result.speed == pytest.approx(len(BODY) / 1.0)


def test_sends_measurement_friendly_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return streamed(b"ok")

    with client_for(handler) as client:
        measure_once(client, URL, index=1)

    headers = seen[0].headers
    assert headers["Accept-Encoding"] == "identity"
    assert headers["Cache-Control"] == "no-cache"
    assert headers["User-Agent"] == USER_AGENT
    assert USER_AGENT.startswith("net-speedmeter/")


def test_counts_wire_bytes_even_if_server_compresses_anyway() -> None:
    compressed = gzip.compress(b"a" * 1_000_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return streamed(compressed, headers={"Content-Encoding": "gzip"})

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert result.ok
    assert result.bytes_downloaded == len(compressed)  # not the 1 MB decoded size


def test_http_error_status_is_a_failed_request() -> None:
    with client_for(serve(b"nope", status=404)) as client:
        result = measure_once(client, URL, index=3)

    assert not result.ok
    assert result.index == 3
    assert result.status_code == 404
    assert result.error == "HTTP 404 Not Found"
    assert result.speed is None


def test_network_error_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert not result.ok
    assert result.status_code is None
    assert result.ttfb is None
    assert result.error == "ConnectError: connection refused"


def test_timeout_is_captured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert not result.ok
    assert result.error == "ReadTimeout"


def test_truncated_body_is_detected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": "1000"},
            stream=ChunkedStream(b"x" * 400),
        )

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert not result.ok
    assert result.bytes_downloaded == 400
    assert result.error == "incomplete body: got 400 of 1000 bytes"


def test_redirects_are_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old.jpg":
            return httpx.Response(302, headers={"Location": URL})
        return streamed(BODY)

    with client_for(handler) as client:
        result = measure_once(client, "https://example.test/old.jpg", index=1)

    assert result.ok
    assert result.bytes_downloaded == len(BODY)


def test_progress_callback_reports_bytes_and_total() -> None:
    calls: list[tuple[int, int, int | None]] = []
    with client_for(serve()) as client:
        measure_once(
            client,
            URL,
            index=7,
            on_progress=lambda i, done, total: calls.append((i, done, total)),
        )

    assert calls
    assert calls[-1] == (7, len(BODY), len(BODY))


def test_iter_benchmark_runs_requests_sequentially() -> None:
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return streamed(BODY)

    results = list(
        iter_benchmark(URL, count=10, transport=httpx.MockTransport(handler), clock=StepClock())
    )

    assert [r.index for r in results] == list(range(1, 11))
    assert all(r.ok for r in results)
    assert len(hits) == 10
    assert sum(r.bytes_downloaded for r in results) == 10 * len(BODY)


def test_iter_benchmark_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError, match="count"):
        list(iter_benchmark(URL, count=0))


@pytest.mark.parametrize("url", ["https://example.com/a.jpg", "http://127.0.0.1:8080/file"])
def test_validate_url_accepts_http_and_https(url: str) -> None:
    assert validate_url(url) == url


@pytest.mark.parametrize("url", ["ftp://example.com/a.jpg", "example.com/a.jpg", "https://", ""])
def test_validate_url_rejects_garbage(url: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        validate_url(url)


@pytest.mark.parametrize("header", [b"\xb2", b"12abc", b"-5"])
def test_malformed_content_length_is_ignored(header: bytes) -> None:
    # b"\xb2" decodes to "²" (superscript two): str.isdigit() is True for it, int() is not.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers=[(b"Content-Length", header)], stream=ChunkedStream(BODY)
        )

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert result.ok
    assert result.bytes_downloaded == len(BODY)
