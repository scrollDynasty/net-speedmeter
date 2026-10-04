"""Aggregation of per-request results into a benchmark summary."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from net_speedmeter.models import Distribution, RequestResult, Summary


def describe(values: Sequence[float]) -> Distribution:
    if not values:
        raise ValueError("cannot describe an empty sample")
    if len(values) == 1:
        (only,) = values
        return Distribution(only, only, only, only, only, 0.0)
    return Distribution(
        mean=statistics.fmean(values),
        median=statistics.median(values),
        p90=statistics.quantiles(values, n=10, method="inclusive")[-1],
        minimum=min(values),
        maximum=max(values),
        stdev=statistics.stdev(values),
    )


def _rate(num_bytes: int, seconds: float) -> float | None:
    return num_bytes / seconds if seconds > 0 else None


def summarize(results: Sequence[RequestResult]) -> Summary:
    """Build a summary from successful requests.

    The headline throughput is ``sum(bytes) / sum(time)``: the time-weighted
    mean of per-request speeds. A plain arithmetic mean of speeds would
    overweight short (fast) requests and overstate the real bandwidth.
    """
    ok = [r for r in results if r.ok]

    total_bytes = sum(r.bytes_downloaded for r in ok)
    total_request_time = sum(r.request_time for r in ok)
    transfer_times = [r.transfer_time for r in ok if r.transfer_time is not None]
    ttfbs = [r.ttfb for r in ok if r.ttfb is not None]
    speeds = [s for r in ok if (s := r.speed) is not None]
    total_transfer_time = sum(transfer_times)

    return Summary(
        total=len(results),
        succeeded=len(ok),
        total_bytes=total_bytes,
        total_request_time=total_request_time,
        total_transfer_time=total_transfer_time,
        request_time=describe([r.request_time for r in ok]) if ok else None,
        ttfb=describe(ttfbs) if ttfbs else None,
        speed=describe(speeds) if speeds else None,
        throughput=_rate(total_bytes, total_request_time),
        transfer_throughput=_rate(total_bytes, total_transfer_time),
    )
