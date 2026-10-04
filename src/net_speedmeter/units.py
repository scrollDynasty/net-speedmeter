"""Unit conversions and human-readable formatting.

Network speeds use SI (decimal) prefixes, the same way ISPs and speed tests do:
1 Mbit/s = 10**6 bit/s, 1 MB/s = 10**6 byte/s.
"""

from __future__ import annotations

BITS_PER_BYTE = 8
KILO = 1_000
MEGA = 1_000_000

_SIZE_UNITS = ("kB", "MB", "GB", "TB")


def to_mbit_per_s(bytes_per_second: float) -> float:
    return bytes_per_second * BITS_PER_BYTE / MEGA


def to_mbyte_per_s(bytes_per_second: float) -> float:
    return bytes_per_second / MEGA


def format_bytes(num_bytes: int) -> str:
    if num_bytes < KILO:
        return f"{num_bytes} B"
    value = float(num_bytes)
    for unit in _SIZE_UNITS:
        value /= KILO
        # compare the *rounded* value, otherwise 999_999 B would print as "1000.00 kB"
        if round(value, 2) < KILO or unit == _SIZE_UNITS[-1]:
            return f"{value:.2f} {unit}"
    raise AssertionError("unreachable")  # pragma: no cover


def format_duration(seconds: float) -> str:
    if round(seconds * KILO, 1) < KILO:
        return f"{seconds * KILO:.1f} ms"
    return f"{seconds:.3f} s"
