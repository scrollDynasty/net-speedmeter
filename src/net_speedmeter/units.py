"""Unit conversions and human-readable formatting.

Network speeds use SI (decimal) prefixes, the same way ISPs and speed tests do:
1 Mbit/s = 10**6 bit/s, 1 MB/s = 10**6 byte/s.
"""

from __future__ import annotations

BITS_PER_BYTE = 8
MEGA = 1_000_000

_SIZE_UNITS = ("B", "kB", "MB", "GB", "TB")


def to_mbit_per_s(bytes_per_second: float) -> float:
    return bytes_per_second * BITS_PER_BYTE / MEGA


def to_mbyte_per_s(bytes_per_second: float) -> float:
    return bytes_per_second / MEGA


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1000:
        return f"{num_bytes} B"
    value = num_bytes / 1000
    for unit in _SIZE_UNITS[1:-1]:
        if value < 1000:
            return f"{value:.2f} {unit}"
        value /= 1000
    return f"{value:.2f} {_SIZE_UNITS[-1]}"


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.1f} ms"
    return f"{seconds:.3f} s"
