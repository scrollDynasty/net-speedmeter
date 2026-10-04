import json

import pytest

from net_speedmeter.models import RequestResult
from net_speedmeter.stats import describe, summarize, throughput


def ok(index: int, nbytes: int, request_time: float, ttfb: float = 0.0) -> RequestResult:
    return RequestResult(
        index=index,
        status_code=200,
        bytes_downloaded=nbytes,
        request_time=request_time,
        ttfb=ttfb,
    )


def failed(index: int, *, request_time: float = 0.5, ttfb: float | None = None) -> RequestResult:
    return RequestResult(
        index=index,
        status_code=None if ttfb is None else 503,
        bytes_downloaded=0,
        request_time=request_time,
        ttfb=ttfb,
        error="boom",
    )


def test_ok_is_derived_from_error() -> None:
    assert ok(1, 10, 1.0).ok
    assert not failed(1).ok


def test_describe_basic_statistics() -> None:
    dist = describe([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert dist.mean == pytest.approx(5.5)
    assert dist.median == pytest.approx(5.5)
    assert dist.minimum == 1.0
    assert dist.maximum == 10.0
    assert dist.p90 == pytest.approx(9.1)
    assert dist.stdev == pytest.approx(3.0276, rel=1e-4)


def test_describe_single_value_has_no_stdev() -> None:
    dist = describe([2.5])
    assert dist.mean == dist.median == dist.p90 == dist.minimum == dist.maximum == 2.5
    assert dist.stdev is None  # undefined for one sample, not "0"


def test_describe_rejects_empty_sample() -> None:
    with pytest.raises(ValueError, match="empty"):
        describe([])


def test_throughput_is_time_weighted_not_naive_mean() -> None:
    # 10 MB in 1 s (10 MB/s) and 10 MB in 9 s (~1.11 MB/s):
    # in reality we moved 20 MB in 10 s => 2 MB/s.
    # The naive mean of per-request speeds would claim ~5.56 MB/s.
    results = [ok(1, 10_000_000, 1.0), ok(2, 10_000_000, 9.0)]
    summary = summarize(results)

    assert summary.throughput == pytest.approx(2_000_000)
    assert summary.speed is not None
    assert summary.speed.mean == pytest.approx(5_555_555.6, rel=1e-6)


def test_throughput_of_nothing_is_undefined() -> None:
    assert throughput([]) is None
    assert throughput([failed(1)]) is None


def test_summary_aggregates_successful_requests_only() -> None:
    results = [
        ok(1, 1_000_000, 2.0, ttfb=0.5),
        failed(2, request_time=9.0, ttfb=8.0),  # has a TTFB, must still be ignored
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


def test_first_request_is_reported_separately() -> None:
    # the cold first request (connection set-up + slow start) is much slower
    results = [ok(1, 10_000_000, 5.0), ok(2, 10_000_000, 1.0), ok(3, 10_000_000, 1.0)]
    summary = summarize(results)

    assert summary.first_request == results[0]
    assert summary.throughput == pytest.approx(30_000_000 / 7.0)
    assert summary.throughput_excluding_first == pytest.approx(10_000_000)


def test_failed_first_request_is_not_reported_as_first() -> None:
    summary = summarize([failed(1), ok(2, 1_000, 1.0)])

    assert summary.first_request is None
    assert summary.throughput_excluding_first == pytest.approx(1_000)


def test_single_request_has_nothing_left_without_first() -> None:
    summary = summarize([ok(1, 1_000, 1.0)])

    assert summary.first_request is not None
    assert summary.throughput_excluding_first is None


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
    assert summary.first_request is None


def test_summary_of_empty_run() -> None:
    summary = summarize([])
    assert summary.total == 0
    assert summary.throughput is None


def test_summary_guards_against_zero_duration() -> None:
    summary = summarize([ok(1, 100, 0.0)])
    assert summary.throughput is None
    assert summary.transfer_throughput is None
    assert summary.speed is None


def test_to_dict_is_json_ready_with_exact_numbers() -> None:
    results = [
        ok(1, 2_000_000, 2.0, ttfb=0.123456),
        ok(2, 2_000_000, 1.0, ttfb=0.1),
        ok(3, 2_000_000, 1.0, ttfb=0.1),
    ]
    data = summarize(results).to_dict()
    json.dumps(data)  # must be serialisable as is

    assert data["total_bytes"] == 6_000_000
    assert data["speed_mbyte_s"] == 1.5  # 6 MB / 4 s
    assert data["speed_mbit_s"] == 12.0
    assert data["speed_excluding_first_mbyte_s"] == 2.0  # 4 MB / 2 s
    assert data["transfer_speed_mbyte_s"] == pytest.approx(6 / (4 - 0.323456), abs=1e-4)
    assert data["request_time_s"]["mean"] == pytest.approx(4 / 3, abs=1e-6)
    assert data["request_time_s"]["median"] == 1.0
    assert data["ttfb_s"]["max"] == 0.123456
    assert data["per_request_speed_mbyte_s"]["max"] == 2.0
    assert data["first_request"]["index"] == 1
    assert data["first_request"]["ttfb_s"] == 0.123456


def test_request_to_dict() -> None:
    data = ok(7, 5_000_000, 1.0, ttfb=0.25).to_dict()

    assert data == {
        "index": 7,
        "ok": True,
        "status_code": 200,
        "bytes": 5_000_000,
        "request_time_s": 1.0,
        "ttfb_s": 0.25,
        "transfer_time_s": 0.75,
        "speed_mbyte_s": 5.0,
        "speed_mbit_s": 40.0,
        "error": None,
    }


def test_summary_to_dict_maps_every_field() -> None:
    # every key must come from its own source (mutation testing found swaps going unnoticed)
    data = summarize(
        [
            ok(1, 4_000_000, 4.0, ttfb=2.0),
            ok(2, 1_000_000, 1.0, ttfb=0.5),
            ok(3, 2_000_000, 1.0, ttfb=0.5),
        ]
    ).to_dict()

    assert data["transfer_speed_mbit_s"] == pytest.approx(7 / 3 * 8, abs=1e-4)  # 7 MB / 3 s
    assert data["speed_excluding_first_mbit_s"] == 12.0  # 3 MB / 2 s
    rt = data["request_time_s"]
    assert (rt["min"], rt["median"], rt["max"]) == (1.0, 1.0, 4.0)
    assert rt["p90"] == pytest.approx(3.4)


def test_failed_request_to_dict() -> None:
    data = failed(2).to_dict()

    assert data["ok"] is False
    assert data["speed_mbyte_s"] is None
    assert data["error"] == "boom"
