"""Command line: ``net-speedmeter [URL] [-n 10]``."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence

import httpx

from net_speedmeter import __version__
from net_speedmeter.measure import RequestResult, benchmark
from net_speedmeter.stats import Summary, summarize

DEFAULT_URL = "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg"
MAX_COUNT = 1000
MEGA = 1_000_000  # SI prefixes, as ISPs use: 1 MB/s = 10**6 B/s = 8 Mbit/s
EXIT_OK, EXIT_FAILED, EXIT_INTERRUPTED = 0, 1, 130  # 2 = bad arguments (argparse)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="net-speedmeter",
        description="Download URL N times in a row and print the average request time, "
        "downloaded volume and speed in MB/s.",
        epilog="Exit codes: 0 all requests succeeded, 1 some failed, 2 bad arguments, "
        "130 interrupted (Ctrl+C).",
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        metavar="URL",
        help="heavy file to download (default: a 14.7 MB photo from Wikimedia Commons)",
    )
    parser.add_argument(
        "-n", "--count", type=int, default=10, help="number of sequential requests (default: 10)"
    )
    args = parser.parse_args(argv)

    if not 1 <= args.count <= MAX_COUNT:
        parser.error(f"--count must be between 1 and {MAX_COUNT}")
    try:
        url = httpx.URL(args.url)
    except httpx.InvalidURL as exc:
        parser.error(f"invalid URL: {exc}")
    if url.scheme not in {"http", "https"} or not url.host:
        parser.error(f"URL must be an absolute http(s) address, got {args.url!r}")
    return args


def _speed(bytes_per_second: float) -> str:
    return f"{bytes_per_second / MEGA:.2f} MB/s ({bytes_per_second * 8 / MEGA:.2f} Mbit/s)"


def format_result(result: RequestResult, count: int) -> str:
    prefix = f"[{result.index:>2}/{count}]"
    if not result.ok or result.ttfb is None:
        return f"{prefix} FAILED  {result.error}"
    speed = result.speed or 0.0
    return (
        f"{prefix} {result.status_code}  {result.bytes_downloaded / MEGA:8.2f} MB  "
        f"{result.request_time:8.3f} s  TTFB {result.ttfb * 1000:5.0f} ms  "
        f"{speed / MEGA:7.2f} MB/s"
    )


def format_summary(summary: Summary) -> list[str]:
    requests = f"{summary.succeeded}/{summary.total} succeeded"
    if summary.failed:
        requests += f", {summary.failed} failed"
    lines = [
        f"Requests          {requests}",
        f"Downloaded        {summary.total_bytes / MEGA:.2f} MB ({summary.total_bytes:,} bytes)",
    ]
    if summary.avg_request_time is not None:
        lines.append(f"Avg request time  {summary.avg_request_time:.3f} s")
    if summary.avg_ttfb is not None:
        lines.append(f"Avg TTFB          {summary.avg_ttfb * 1000:.0f} ms")
    if summary.speed is None:
        lines.append("Speed             n/a (no successful requests)")
        return lines
    lines.append(f"Speed             {_speed(summary.speed)}  <- total bytes / total time")
    if summary.speed_without_first is not None:
        lines.append(f"Without #1        {_speed(summary.speed_without_first)}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    # A redirected stdout on Windows may be cp1251: never crash on a non-ASCII URL.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")

    args = _parse_args(argv)
    noun = "request" if args.count == 1 else "requests"
    print(f"net-speedmeter {__version__}: {args.count} sequential GET {noun}")
    print(f"URL: {args.url}\n", flush=True)

    results: list[RequestResult] = []
    interrupted = False
    try:
        for result in benchmark(args.url, args.count):
            results.append(result)
            print(format_result(result, args.count), flush=True)
            if result.index == 1 and result.final_url not in (None, args.url):
                print(f"        redirected to {result.final_url}; next requests go there")
    except KeyboardInterrupt:
        interrupted = True

    summary = summarize(results)
    print()
    print("\n".join(format_summary(summary)))
    if interrupted:
        print("Interrupted: the summary covers finished requests only.")
        return EXIT_INTERRUPTED
    return EXIT_FAILED if summary.failed or not summary.succeeded else EXIT_OK
