import gzip
from collections.abc import Callable, Iterator

import httpx
import pytest

from net_speedmeter.measure import USER_AGENT, benchmark, build_client, measure_once

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
    body: bytes = BODY, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Length": str(len(body)), **(headers or {})},
        stream=ChunkedStream(body),
    )


def client_for(handler: Handler) -> httpx.Client:
    return build_client(httpx.MockTransport(handler))


def test_success_records_bytes_and_timings() -> None:
    with client_for(lambda request: streamed()) as client:
        result = measure_once(client, URL, index=1, clock=StepClock(0.5))

    assert result.ok
    assert result.status_code == 200
    assert result.bytes_downloaded == len(BODY)
    # clock: start=0.0, headers=0.5, last byte=1.0
    assert result.ttfb == pytest.approx(0.5)
    assert result.request_time == pytest.approx(1.0)
    assert result.speed == pytest.approx(len(BODY))
    assert result.final_url == URL


def test_sends_measurement_friendly_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return streamed(b"ok")

    with client_for(handler) as client:
        measure_once(client, URL, index=1)

    assert seen[0].headers["Accept-Encoding"] == "identity"
    assert seen[0].headers["Cache-Control"] == "no-cache"
    assert seen[0].headers["User-Agent"] == USER_AGENT


def test_counts_wire_bytes_even_if_the_server_compresses_anyway() -> None:
    compressed = gzip.compress(b"a" * 1_000_000)

    with client_for(lambda r: streamed(compressed, headers={"Content-Encoding": "gzip"})) as c:
        result = measure_once(c, URL, index=1)

    assert result.bytes_downloaded == len(compressed)  # not the 1 MB decoded size


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, "HTTP 404 Not Found"), (304, "HTTP 304 Not Modified"), (599, "HTTP 599")],
)
def test_non_2xx_is_a_failed_request(status: int, error: str) -> None:
    with client_for(lambda request: streamed(b"page", status)) as client:
        result = measure_once(client, URL, index=3, clock=StepClock(0.5))

    assert not result.ok
    assert result.status_code == status
    assert result.error == error
    assert result.request_time == result.ttfb == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (httpx.ConnectError("connection refused"), "ConnectError: connection refused"),
        (httpx.ReadTimeout(""), "ReadTimeout"),
    ],
)
def test_network_errors_are_captured_not_raised(exc: httpx.HTTPError, error: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert not result.ok
    assert result.status_code is None
    assert result.error == error


def test_stream_error_mid_body_is_captured() -> None:
    class Broken(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x"
            raise httpx.StreamClosed

    with client_for(lambda request: httpx.Response(200, stream=Broken())) as client:
        result = measure_once(client, URL, index=1)

    assert result.error is not None
    assert result.error.startswith("StreamClosed")


def test_invalid_url_is_captured() -> None:
    with client_for(lambda request: streamed()) as client:
        result = measure_once(client, "http://exa\x00mple.test/", index=1)

    assert result.error is not None
    assert result.error.startswith("InvalidURL")


@pytest.mark.parametrize(("declared", "sent"), [(1000, 400), (400, 500)])
def test_content_length_mismatch_is_a_failed_request(declared: int, sent: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": str(declared)}, stream=ChunkedStream(b"x" * sent)
        )

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert result.error == f"incomplete body: got {sent} of {declared} bytes"


@pytest.mark.parametrize("header", [b"\xb2", "٣".encode(), b"12abc", b"-5"])
def test_malformed_content_length_is_ignored(header: bytes) -> None:
    # "²" and the Arabic-Indic "٣" pass str.isdigit(), but int() would choke on them.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers=[(b"Content-Length", header)], stream=ChunkedStream(BODY)
        )

    with client_for(handler) as client:
        result = measure_once(client, URL, index=1)

    assert result.ok
    assert result.bytes_downloaded == len(BODY)


def test_benchmark_is_sequential_and_follows_the_first_redirect_once() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/old.jpg":
            return httpx.Response(302, headers={"Location": URL})
        return streamed()

    results = list(
        benchmark("https://example.test/old.jpg", 3, transport=httpx.MockTransport(handler))
    )

    assert [r.index for r in results] == [1, 2, 3]
    assert all(r.ok and r.bytes_downloaded == len(BODY) for r in results)
    # only request #1 pays for the redirect; #2 and #3 go straight to the final URL
    assert paths == ["/old.jpg", "/big.jpg", "/big.jpg", "/big.jpg"]
