"""The library API promised in the README: usable without the CLI (Celery task, script)."""

import json
import subprocess
import sys

import httpx

import net_speedmeter
from net_speedmeter import iter_benchmark, summarize


def test_public_names_are_exported() -> None:
    for name in net_speedmeter.__all__:
        assert hasattr(net_speedmeter, name), name


def test_library_round_trip_without_cli() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Length": "4"}, stream=httpx.ByteStream(b"abcd")
        )

    results = iter_benchmark(
        "https://cdn.example.test/creative.jpg", count=3, transport=httpx.MockTransport(handler)
    )
    summary = summarize(list(results))

    assert summary.succeeded == 3
    assert summary.total_bytes == 12
    payload = json.loads(json.dumps(summary.to_dict()))
    assert payload["succeeded"] == 3


def test_package_is_typed() -> None:
    from importlib.resources import files

    assert files("net_speedmeter").joinpath("py.typed").is_file()


def test_module_entry_point() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "net_speedmeter", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == f"net-speedmeter {net_speedmeter.__version__}"
