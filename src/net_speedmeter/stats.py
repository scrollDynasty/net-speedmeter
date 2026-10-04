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
        return Distribution(
            mean=only, median=only, p90=only, minimum=only, maximum=only, stdev=None
        )
    return Distribution(
        mean=statistics.fmean(values),
        median=statistics.median(values),
        p90=statistics.quantiles(values, n=10, method="inclusive")[-1],
        minimum=min(values),
        maximum=max(values),
        stdev=statistics.stdev(values),
    )


def throughput(results: Sequence[RequestResult]) -> float | None:
    """``sum(bytes) / sum(time)`` over successful requests, ``None`` if undefined.

    This is the time-weighted mean of per-request speeds. A plain arithmetic
    mean of speeds would overweight short (fast) requests and overstate the
    real bandwidth.
    """
    ok = [r for r in results if r.ok]
    seconds = sum(r.request_time for r in ok)
    return sum(r.bytes_downloaded for r in ok) / seconds if seconds > 0 else None


def summarize(results: Sequence[RequestResult]) -> Summary:
    ok = [r for r in results if r.ok]

    total_bytes = sum(r.bytes_downloaded for r in ok)
    transfer_times = [t for r in ok if (t := r.transfer_time) is not None]
    ttfbs = [t for r in ok if (t := r.ttfb) is not None]
    speeds = [s for r in ok if (s := r.speed) is not None]
    total_transfer_time = sum(transfer_times)

    first = results[0] if results and results[0].ok else None
    rest = results[1:]

    return Summary(
        total=len(results),
        succeeded=len(ok),
        total_bytes=total_bytes,
        total_request_time=sum(r.request_time for r in ok),
        total_transfer_time=total_transfer_time,
        request_time=describe([r.request_time for r in ok]) if ok else None,
        ttfb=describe(ttfbs) if ttfbs else None,
        speed=describe(speeds) if speeds else None,
        throughput=throughput(results),
        transfer_throughput=total_bytes / total_transfer_time if total_transfer_time > 0 else None,
        first_request=first,
        throughput_excluding_first=throughput(rest),
    )
