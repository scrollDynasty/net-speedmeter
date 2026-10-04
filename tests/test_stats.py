import pytest

from net_speedmeter.models import RequestResult
from net_speedmeter.stats import describe, summarize


def ok(index: int, nbytes: int, request_time: float, ttfb: float = 0.0) -> RequestResult:
    return RequestResult(
        index=index,
        ok=True,
        status_code=200,
        bytes_downloaded=nbytes,
        request_time=request_time,
        ttfb=ttfb,
    )


def failed(index: int) -> RequestResult:
    return RequestResult(
        index=index,
        ok=False,
        status_code=None,
        bytes_downloaded=0,
        request_time=0.5,
        ttfb=None,
        error="ConnectError",
    )


def test_describe_basic_statistics() -> None:
    dist = describe([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert dist.mean == pytest.approx(5.5)
    assert dist.median == pytest.approx(5.5)
    assert dist.minimum == 1.0
    assert dist.maximum == 10.0
    assert dist.p90 == pytest.approx(9.1)
    assert dist.stdev == pytest.approx(3.0276, rel=1e-4)


def test_describe_single_value_has_zero_spread() -> None:
    dist = describe([2.5])
    assert dist.mean == dist.median == dist.p90 == dist.minimum == dist.maximum == 2.5
    assert dist.stdev == 0.0


def test_describe_rejects_empty_sample() -> None:
    with pytest.raises(ValueError, match="empty"):
        describe([])


def test_summary_throughput_is_time_weighted_not_naive_mean() -> None:
    # 10 MB in 1 s (10 MB/s) and 10 MB in 9 s (~1.11 MB/s):
    # in reality we moved 20 MB in 10 s => 2 MB/s.
    # The naive mean of per-request speeds would claim ~5.56 MB/s.
    results = [ok(1, 10_000_000, 1.0), ok(2, 10_000_000, 9.0)]
    summary = summarize(results)

    assert summary.throughput == pytest.approx(2_000_000)
    assert summary.speed is not None
    assert summary.speed.mean == pytest.approx(5_555_555.6, rel=1e-6)


def test_summary_aggregates_successful_requests_only() -> None:
    results = [
        ok(1, 1_000_000, 2.0, ttfb=0.5),
        failed(2),
        ok(3, 3_000_000, 2.0, ttfb=0.5),
    ]
    summary = summarize(results)

    assert summary.total == 3
    assert summary.succeeded == 2
    assert summary.failed == 1
    assert summary.total_bytes == 4_000_000
    assert summary.total_request_time == pytest.approx(4.0)
    assert summary.total_transfer_time == pytest.approx(3.0)
    assert summary.throughput == pytest.approx(1_000_000)
    assert summary.transfer_throughput == pytest.approx(4_000_000 / 3.0)
    assert summary.request_time is not None
    assert summary.request_time.mean == pytest.approx(2.0)
    assert summary.ttfb is not None
    assert summary.ttfb.mean == pytest.approx(0.5)


def test_summary_with_no_successful_requests() -> None:
    summary = summarize([failed(1), failed(2)])

    assert summary.succeeded == 0
    assert summary.failed == 2
    assert summary.total_bytes == 0
    assert summary.throughput is None
    assert summary.transfer_throughput is None
    assert summary.request_time is None
    assert summary.ttfb is None
    assert summary.speed is None


def test_summary_of_empty_run() -> None:
    summary = summarize([])
    assert summary.total == 0
    assert summary.throughput is None


def test_summary_guards_against_zero_duration() -> None:
    summary = summarize([ok(1, 100, 0.0)])
    assert summary.throughput is None
    assert summary.transfer_throughput is None
    assert summary.speed is None
