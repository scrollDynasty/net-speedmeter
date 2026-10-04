"""Plain data containers shared by the measurement, statistics and CLI layers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from net_speedmeter.units import to_mbit_per_s, to_mbyte_per_s

_TIME_DIGITS = 6
_SPEED_DIGITS = 4


def _seconds(value: float | None) -> float | None:
    return None if value is None else round(value, _TIME_DIGITS)


def _mbyte(bytes_per_second: float | None) -> float | None:
    return (
        None if bytes_per_second is None else round(to_mbyte_per_s(bytes_per_second), _SPEED_DIGITS)
    )


def _mbit(bytes_per_second: float | None) -> float | None:
    return (
        None if bytes_per_second is None else round(to_mbit_per_s(bytes_per_second), _SPEED_DIGITS)
    )


@dataclass(frozen=True, slots=True)
class RequestResult:
    """Outcome of a single GET request; ``error is None`` means success.

    All times are in seconds, measured with a monotonic clock from the moment
    the request starts (on a new connection that includes DNS + TCP + TLS):

    * ``ttfb`` - until the response headers have been received;
    * ``request_time`` - until the last body byte has been received.
    """

    index: int
    status_code: int | None
    bytes_downloaded: int
    request_time: float
    ttfb: float | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "ok": self.ok,
            "status_code": self.status_code,
            "bytes": self.bytes_downloaded,
            "request_time_s": _seconds(self.request_time),
            "ttfb_s": _seconds(self.ttfb),
            "transfer_time_s": _seconds(self.transfer_time),
            "speed_mbyte_s": _mbyte(self.speed),
            "speed_mbit_s": _mbit(self.speed),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Distribution:
    """Descriptive statistics of a sample. ``stdev`` is ``None`` for a single value."""

    mean: float
    median: float
    p90: float
    minimum: float
    maximum: float
    stdev: float | None

    def to_dict(self, convert: Callable[[float], float | None]) -> dict[str, float | None]:
        return {
            "mean": convert(self.mean),
            "median": convert(self.median),
            "p90": convert(self.p90),
            "min": convert(self.minimum),
            "max": convert(self.maximum),
            "stdev": None if self.stdev is None else convert(self.stdev),
        }


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
    first_request: RequestResult | None
    """The first request of the run if it succeeded: it pays for DNS/TCP/TLS and slow start."""
    throughput_excluding_first: float | None
    """Same as ``throughput`` but without the first request (``None`` if nothing is left)."""

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "total_bytes": self.total_bytes,
            "speed_mbyte_s": _mbyte(self.throughput),
            "speed_mbit_s": _mbit(self.throughput),
            "transfer_speed_mbyte_s": _mbyte(self.transfer_throughput),
            "transfer_speed_mbit_s": _mbit(self.transfer_throughput),
            "speed_excluding_first_mbyte_s": _mbyte(self.throughput_excluding_first),
            "speed_excluding_first_mbit_s": _mbit(self.throughput_excluding_first),
            "request_time_s": None
            if self.request_time is None
            else self.request_time.to_dict(_seconds),
            "ttfb_s": None if self.ttfb is None else self.ttfb.to_dict(_seconds),
            "per_request_speed_mbyte_s": None if self.speed is None else self.speed.to_dict(_mbyte),
            "first_request": None if self.first_request is None else self.first_request.to_dict(),
        }
