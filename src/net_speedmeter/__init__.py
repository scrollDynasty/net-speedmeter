"""Measure download speed by fetching a heavy file several times in a row.

Library usage::

    from net_speedmeter import iter_benchmark, summarize

    summary = summarize(list(iter_benchmark("https://example.com/big.jpg", count=5)))
    summary.throughput  # bytes per second, or None if every request failed
    summary.to_dict()   # JSON-ready, the "summary" block of `net-speedmeter --json`
"""

from net_speedmeter._version import __version__
from net_speedmeter.measure import build_client, iter_benchmark, measure_once, validate_url
from net_speedmeter.models import Distribution, RequestResult, Summary
from net_speedmeter.stats import summarize

__all__ = [
    "Distribution",
    "RequestResult",
    "Summary",
    "__version__",
    "build_client",
    "iter_benchmark",
    "measure_once",
    "summarize",
    "validate_url",
]
