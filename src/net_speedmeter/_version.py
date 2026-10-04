from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("net-speedmeter")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.0.0+unknown"
