"""Hand-made results for tests that do not need the network."""

from net_speedmeter.measure import RequestResult


def ok(
    index: int, nbytes: int = 5_000_000, request_time: float = 1.0, ttfb: float = 0.1
) -> RequestResult:
    return RequestResult(
        index, 200, nbytes, request_time, ttfb, final_url="https://example.test/a.jpg"
    )


def failed(index: int, *, request_time: float = 0.5, ttfb: float | None = None) -> RequestResult:
    status = None if ttfb is None else 503
    return RequestResult(index, status, 0, request_time, ttfb, error="boom")
