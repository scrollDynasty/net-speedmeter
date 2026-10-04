"""Aggregate per-request results into the numbers the task asks for."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from net_speedmeter.measure import RequestResult


@dataclass(frozen=True, slots=True)
class Summary:
    """Only successful requests contribute to the numbers; speeds are in bytes/s."""

    total: int
    succeeded: int
    total_bytes: int
    avg_request_time: float | None
    avg_ttfb: float | None
    speed: float | None
    """Total bytes / total request time: the headline number."""
    speed_without_first: float | None
    """Same without request #1, which pays for connection set-up and TCP warm-up.
    ``None`` unless #1 succeeded and at least one more request did."""

    @property
    def failed(self) -> int:
        return self.total - self.succeeded


def throughput(results: Sequence[RequestResult]) -> float | None:
    """``sum(bytes) / sum(time)`` over successful requests.

    This is the time-weighted mean of per-request speeds. A plain arithmetic
    mean of speeds would overweight short (fast) requests and overstate the
    real bandwidth.
    """
    ok = [r for r in results if r.ok]
    seconds = sum(r.request_time for r in ok)
    return sum(r.bytes_downloaded for r in ok) / seconds if seconds > 0 else None


def summarize(results: Sequence[RequestResult]) -> Summary:
    ok = [r for r in results if r.ok]
    ttfbs = [r.ttfb for r in ok if r.ttfb is not None]
    first_ok = bool(results) and results[0].ok
    return Summary(
        total=len(results),
        succeeded=len(ok),
        total_bytes=sum(r.bytes_downloaded for r in ok),
        avg_request_time=fmean(r.request_time for r in ok) if ok else None,
        avg_ttfb=fmean(ttfbs) if ttfbs else None,
        speed=throughput(results),
        speed_without_first=throughput(results[1:]) if first_ok else None,
    )
