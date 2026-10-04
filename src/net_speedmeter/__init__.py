"""Measure download speed by fetching a heavy file several times in a row."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("net-speedmeter")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
