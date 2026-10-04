"""Plain data containers shared by the measurement, statistics and CLI layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestResult:
    """Outcome of a single GET request.

    All times are in seconds and measured with a monotonic clock:

    * ``ttfb`` - from sending the request until response headers arrived
      (includes DNS/TCP/TLS when a new connection had to be opened);
    * ``request_time`` - from sending the request until the last body byte arrived.
    """

    index: int
    ok: bool
    status_code: int | None
    bytes_downloaded: int
    request_time: float
    ttfb: float | None
    error: str | None = None

    @property
    def transfer_time(self) -> float | None:
        """Time spent receiving the body only (``request_time - ttfb``)."""
        if self.ttfb is None:
            return None
        return self.request_time - self.ttfb

    @property
    def speed(self) -> float | None:
        """Bytes per second over the whole request, ``None`` for failed/instant requests."""
        if not self.ok or self.request_time <= 0:
            return None
        return self.bytes_downloaded / self.request_time


@dataclass(frozen=True, slots=True)
class Distribution:
    """Descriptive statistics of a sample."""

    mean: float
    median: float
    p90: float
    minimum: float
    maximum: float
    stdev: float


@dataclass(frozen=True, slots=True)
class Summary:
    """Aggregated benchmark results. Only successful requests contribute to the numbers."""

    total: int
    succeeded: int
    total_bytes: int
    total_request_time: float
    total_transfer_time: float
    request_time: Distribution | None
    ttfb: Distribution | None
    speed: Distribution | None
    throughput: float | None
    """Bytes per second: total bytes / total request time (the headline number)."""
    transfer_throughput: float | None
    """Bytes per second: total bytes / total body transfer time (excludes TTFB)."""

    @property
    def failed(self) -> int:
        return self.total - self.succeeded
