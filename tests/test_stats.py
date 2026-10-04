import pytest
from _factories import failed, ok

from net_speedmeter.measure import RequestResult
from net_speedmeter.stats import summarize, throughput


def test_speed_is_time_weighted_not_the_mean_of_speeds() -> None:
    # 10 MB in 1 s and 10 MB in 9 s is 20 MB in 10 s = 2 MB/s.
    # The mean of the two speeds (10 and 1.11 MB/s) would claim ~5.56 MB/s.
    summary = summarize([ok(1, 10_000_000, 1.0), ok(2, 10_000_000, 9.0)])

    assert summary.speed == pytest.approx(2_000_000)
    assert summary.avg_request_time == pytest.approx(5.0)


def test_only_successful_requests_count() -> None:
    summary = summarize([ok(1, 1_000_000, 2.0, ttfb=0.5), failed(2, request_time=9.0, ttfb=8.0)])

    assert (summary.total, summary.succeeded, summary.failed) == (2, 1, 1)
    assert summary.total_bytes == 1_000_000
    assert summary.avg_request_time == pytest.approx(2.0)
    assert summary.avg_ttfb == pytest.approx(0.5)  # the failed request's TTFB is ignored
    assert summary.speed == pytest.approx(500_000)


def test_speed_without_first_request() -> None:
    summary = summarize([ok(1, 10_000_000, 5.0), ok(2, 10_000_000, 1.0), ok(3, 10_000_000, 1.0)])

    assert summary.speed == pytest.approx(30_000_000 / 7)
    assert summary.speed_without_first == pytest.approx(10_000_000)


@pytest.mark.parametrize(
    "results",
    [
        [ok(1)],  # nothing left without #1
        [failed(1), ok(2), ok(3)],  # #2 would be the cold request, so the number would lie
        [ok(1), failed(2)],
    ],
)
def test_speed_without_first_is_undefined(results: list[RequestResult]) -> None:
    assert summarize(results).speed_without_first is None


def test_nothing_succeeded() -> None:
    summary = summarize([failed(1), failed(2)])

    assert summary.succeeded == 0
    assert summary.total_bytes == 0
    assert summary.speed is None
    assert summary.avg_request_time is None
    assert summary.avg_ttfb is None


def test_empty_run_and_zero_duration() -> None:
    assert summarize([]).speed is None
    assert throughput([ok(1, 100, 0.0)]) is None
