import pytest

from net_speedmeter.units import (
    format_bytes,
    format_duration,
    to_mbit_per_s,
    to_mbyte_per_s,
)


def test_mbit_uses_decimal_megabits() -> None:
    # 1 MB/s == 8 Mbit/s (SI prefixes, as ISPs advertise)
    assert to_mbit_per_s(1_000_000) == pytest.approx(8.0)
    assert to_mbit_per_s(12_500_000) == pytest.approx(100.0)


def test_mbyte_uses_decimal_megabytes() -> None:
    assert to_mbyte_per_s(1_000_000) == pytest.approx(1.0)
    assert to_mbyte_per_s(2**20) == pytest.approx(1.048576)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (999, "999 B"),
        (1_000, "1.00 kB"),
        (999_999, "1.00 MB"),  # must not render as "1000.00 kB"
        (1_000_000, "1.00 MB"),
        (14_679_474, "14.68 MB"),
        (146_794_740, "146.79 MB"),
        (2_500_000_000, "2.50 GB"),
        (5_000_000_000_000, "5.00 TB"),
        (7_000_000_000_000_000, "7000.00 TB"),
    ],
)
def test_format_bytes(value: int, expected: str) -> None:
    assert format_bytes(value) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0004, "0.4 ms"),
        (0.045, "45.0 ms"),
        (0.9994, "999.4 ms"),
        (0.99996, "1.000 s"),  # must not render as "1000.0 ms"
        (1.0, "1.000 s"),
        (12.3456, "12.346 s"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected
