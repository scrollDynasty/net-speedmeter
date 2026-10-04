"""Download a URL several times in a row and time every request.

* The body is streamed with ``iter_raw()`` and thrown away as it arrives, so a
  large file never sits in memory.
* The volume is the HTTP body as it came off the wire (``num_bytes_downloaded``,
  before any decompression); ``Accept-Encoding: identity`` asks the server not
  to compress at all.
* Timestamps come from ``time.perf_counter`` (monotonic, high resolution).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx

from net_speedmeter import __version__

TIMEOUT = 30.0  # seconds per network operation (connect, each read), not per download

# Wikimedia rejects anonymous clients; its policy asks for "<client>/<version> (<contact>)".
USER_AGENT = (
    f"net-speedmeter/{__version__} "
    f"(+https://github.com/scrollDynasty/net-speedmeter) httpx/{httpx.__version__}"
)

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RequestResult:
    """One GET request; ``error is None`` means success.

    Times are in seconds from the start of the request (on a new connection
    that includes DNS + TCP + TLS, and redirect hops if any):
    ``ttfb`` until the response headers, ``request_time`` until the last body byte.
    """

    index: int
    status_code: int | None
    bytes_downloaded: int
    request_time: float
    ttfb: float | None
    final_url: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def speed(self) -> float | None:
        """Bytes per second, ``None`` for failed or instant requests."""
        if not self.ok or self.request_time <= 0:
            return None
        return self.bytes_downloaded / self.request_time


def build_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        },
        timeout=TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("Content-Length")
    # isdigit() alone would accept e.g. "²" (superscript two) and then crash in int()
    if value is not None and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def measure_once(
    client: httpx.Client, url: str, *, index: int, clock: Clock = time.perf_counter
) -> RequestResult:
    """Download ``url`` once. Network and HTTP errors are returned, not raised."""
    status: int | None = None
    ttfb: float | None = None
    downloaded = 0

    def failure(error: str, elapsed: float) -> RequestResult:
        return RequestResult(index, status, downloaded, elapsed, ttfb, error=error)

    start = clock()
    try:
        with client.stream("GET", url) as response:
            ttfb = clock() - start
            status = response.status_code
            if not response.is_success:
                response.read()  # drain the (small) error body so keep-alive survives
                error = f"HTTP {status} {response.reason_phrase}".rstrip()
                return failure(error, ttfb)
            expected = _content_length(response)
            for _ in response.iter_raw():
                pass
            elapsed = clock() - start
            downloaded = response.num_bytes_downloaded
            final_url = str(response.url)
    except (httpx.HTTPError, httpx.InvalidURL, httpx.StreamError) as exc:
        return failure(_describe(exc), clock() - start)

    if expected is not None and downloaded != expected:
        return failure(f"incomplete body: got {downloaded} of {expected} bytes", elapsed)
    return RequestResult(index, status, downloaded, elapsed, ttfb, final_url=final_url)


def benchmark(
    url: str,
    count: int = 10,
    *,
    transport: httpx.BaseTransport | None = None,
    clock: Clock = time.perf_counter,
) -> Iterator[RequestResult]:
    """Run ``count`` sequential downloads over one keep-alive client.

    If the first request was redirected, the rest go straight to the final URL:
    a redirect to another host would otherwise cost a new connection every time.
    """
    with build_client(transport) as client:
        for index in range(1, count + 1):
            result = measure_once(client, url, index=index, clock=clock)
            if index == 1 and result.final_url is not None:
                url = result.final_url
            yield result
