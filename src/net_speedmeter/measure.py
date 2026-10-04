"""HTTP download measurement.

Design notes (the README section "Методика" has the long version):

* the body is streamed with ``iter_raw()`` and thrown away as it arrives, so a
  100 MB file never sits in memory. No re-chunking: httpcore already reads the
  socket in 64 KiB pieces, and re-slicing them into bigger chunks only adds
  copies (measured: ~25% lower throughput on a fast local link);
* the volume is the HTTP body as it came off the wire (``num_bytes_downloaded``,
  before any decompression); ``Accept-Encoding: identity`` asks the server not
  to compress at all, otherwise gzip would distort it;
* timestamps come from ``time.perf_counter`` (monotonic, high resolution),
  never from the wall clock.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import TypeAlias

import httpx

from net_speedmeter._version import __version__
from net_speedmeter.models import RequestResult

DEFAULT_URL = "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg"
DEFAULT_COUNT = 10
MAX_COUNT = 1000
DEFAULT_TIMEOUT = 30.0
MIN_TIMEOUT = 0.1

# Wikimedia (and some CDNs) reject anonymous clients; their policy asks for
# "<client>/<version> (<contact>) <library>/<version>".
USER_AGENT = (
    f"net-speedmeter/{__version__} "
    f"(+https://github.com/scrollDynasty/net-speedmeter) httpx/{httpx.__version__}"
)

Clock: TypeAlias = Callable[[], float]
ProgressCallback: TypeAlias = Callable[[int, int, int | None], None]
"""Called as ``(request_index, bytes_downloaded, total_bytes_or_None)``."""


def validate_url(url: str) -> str:
    """Return ``url`` unchanged if it is an absolute http(s) URL, else raise ``ValueError``."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise ValueError(f"invalid URL {url!r}: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError(f"URL must be an absolute http(s) address, got {url!r}")
    return url


def build_client(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    keepalive: bool = True,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """HTTP client tuned for measuring, not for being clever.

    ``keepalive=False`` disables connection pooling so every request pays for
    DNS + TCP + TLS again - useful to compare "cold" vs "warm" numbers.

    Note: when a custom ``transport`` is given, httpx ignores ``limits`` and
    proxy environment variables - the transport is used as is.
    """
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
        # connect/read/write/pool timeouts apply per operation, so a slow but
        # steadily progressing download is not killed halfway through.
        timeout=httpx.Timeout(timeout),
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1 if keepalive else 0),
        follow_redirects=True,
        transport=transport,
    )


def _describe_error(exc: Exception) -> str:
    message = str(exc)
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length")
    # isdigit() alone would accept e.g. "²" (superscript two) and then crash in int()
    if value is not None and value.isascii() and value.isdecimal():
        return int(value)
    return None


def measure_once(
    client: httpx.Client,
    url: str,
    *,
    index: int,
    clock: Clock = time.perf_counter,
    on_progress: ProgressCallback | None = None,
) -> RequestResult:
    """Download ``url`` once and time it. Network/HTTP errors are returned, not raised."""
    status_code: int | None = None
    ttfb: float | None = None
    downloaded = 0

    def failure(error: str, elapsed: float) -> RequestResult:
        return RequestResult(
            index=index,
            status_code=status_code,
            bytes_downloaded=downloaded,
            request_time=elapsed,
            ttfb=ttfb,
            error=error,
        )

    start = clock()
    try:
        with client.stream("GET", url) as response:
            ttfb = clock() - start
            status_code = response.status_code
            if not response.is_success:
                error = f"HTTP {status_code} {response.reason_phrase}".rstrip()
                return failure(error, ttfb)

            expected = _content_length(response)
            for _chunk in response.iter_raw():
                downloaded = response.num_bytes_downloaded
                if on_progress is not None:
                    on_progress(index, downloaded, expected)
            elapsed = clock() - start
            downloaded = response.num_bytes_downloaded
    except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError) as exc:
        return failure(_describe_error(exc), clock() - start)

    if expected is not None and downloaded != expected:
        return failure(f"incomplete body: got {downloaded} of {expected} bytes", elapsed)

    return RequestResult(
        index=index,
        status_code=status_code,
        bytes_downloaded=downloaded,
        request_time=elapsed,
        ttfb=ttfb,
    )


def iter_benchmark(
    url: str,
    *,
    count: int = DEFAULT_COUNT,
    timeout: float = DEFAULT_TIMEOUT,
    keepalive: bool = True,
    transport: httpx.BaseTransport | None = None,
    clock: Clock = time.perf_counter,
    on_progress: ProgressCallback | None = None,
) -> Iterator[RequestResult]:
    """Run ``count`` sequential downloads, yielding each result as soon as it is ready.

    Arguments are validated immediately (not on the first ``next()``). Being a
    generator lets the caller render results live and still keep the finished
    ones if the run is interrupted with Ctrl+C or a task time limit.
    """
    validate_url(url)
    if not 1 <= count <= MAX_COUNT:
        raise ValueError(f"count must be between 1 and {MAX_COUNT}, got {count}")
    if timeout < MIN_TIMEOUT:
        raise ValueError(f"timeout must be >= {MIN_TIMEOUT} s, got {timeout}")
    return _run(
        url,
        count=count,
        timeout=timeout,
        keepalive=keepalive,
        transport=transport,
        clock=clock,
        on_progress=on_progress,
    )


def _run(
    url: str,
    *,
    count: int,
    timeout: float,
    keepalive: bool,
    transport: httpx.BaseTransport | None,
    clock: Clock,
    on_progress: ProgressCallback | None,
) -> Iterator[RequestResult]:
    with build_client(timeout=timeout, keepalive=keepalive, transport=transport) as client:
        for index in range(1, count + 1):
            yield measure_once(client, url, index=index, clock=clock, on_progress=on_progress)
