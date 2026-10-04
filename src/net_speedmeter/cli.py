"""Command-line interface: ``net-speedmeter [URL] [-n 10] [--json]``."""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from net_speedmeter._version import __version__
from net_speedmeter.measure import (
    DEFAULT_COUNT,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    MAX_COUNT,
    MIN_TIMEOUT,
    iter_benchmark,
    validate_url,
)
from net_speedmeter.models import RequestResult, Summary
from net_speedmeter.stats import summarize
from net_speedmeter.units import format_bytes, format_duration, to_mbit_per_s, to_mbyte_per_s

JSON_SCHEMA_VERSION = 1


class ExitCode(IntEnum):
    OK = 0
    PARTIAL_FAILURE = 1
    USAGE = 2  # reserved by Click for bad arguments
    ALL_FAILED = 3
    ERROR = 4  # broken environment: bad proxy settings, missing CA bundle, ...
    INTERRUPTED = 130  # conventional 128 + SIGINT


EPILOG = (
    "Examples:  net-speedmeter -n 3 | "
    'net-speedmeter "https://speed.cloudflare.com/__down?bytes=25000000" | '
    "net-speedmeter --json | jq .summary.speed_mbyte_s"
    "\n\n"
    "Exit codes: 0 all ok, 1 some requests failed, 2 bad arguments, "
    "3 all requests failed, 4 environment error, 130 interrupted."
)

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Measure download speed: fetch URL N times sequentially, then report the average "
        "request time, downloaded volume and speed in MB/s and Mbit/s."
    ),
)


def _url_callback(value: str) -> str:
    try:
        return validate_url(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"net-speedmeter {__version__}")
        raise typer.Exit


@app.command(epilog=EPILOG)
def run(
    url: Annotated[
        str,
        typer.Argument(
            metavar="URL",
            show_default=False,
            help=(
                "URL of a heavy file to download (an image, a .bin, ...). "
                "Default: a 14.7 MB photo from Wikimedia Commons."
            ),
            callback=_url_callback,
        ),
    ] = DEFAULT_URL,
    count: Annotated[
        int,
        typer.Option("--count", "-n", min=1, max=MAX_COUNT, help="Number of sequential requests."),
    ] = DEFAULT_COUNT,
    timeout: Annotated[
        float,
        typer.Option(
            min=MIN_TIMEOUT,
            help="Timeout in seconds for each network operation (connect, each read).",
        ),
    ] = DEFAULT_TIMEOUT,
    keepalive: Annotated[
        bool,
        typer.Option(
            "--keepalive/--no-keepalive",
            help="Reuse one connection or open a fresh one for every request.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of human output."),
    ] = False,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
) -> None:
    """Download URL several times in a row and report the average speed."""
    console = Console(highlight=False)

    if not json_output:
        mode = "keep-alive" if keepalive else "new connection per request"
        console.print(Text(f"net-speedmeter {__version__}", style="bold"))
        console.print(Text(f"URL:      {url}"), soft_wrap=True)
        console.print(Text(f"Requests: {count} sequential GET, {mode}"), soft_wrap=True)
        console.print()

    results: list[RequestResult] = []
    interrupted = False
    progress = Progress(
        TextColumn("{task.description}", markup=False),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        disable=json_output or not console.is_terminal,
    )
    with progress:
        task = progress.add_task("connecting", total=None)

        def on_progress(index: int, done: int, total: int | None) -> None:
            progress.update(task, description=f"[{index:>2}/{count}]", completed=done, total=total)

        try:
            for result in iter_benchmark(
                url,
                count=count,
                timeout=timeout,
                keepalive=keepalive,
                # no per-chunk callback at all when nothing is rendered
                on_progress=None if progress.disable else on_progress,
            ):
                results.append(result)
                progress.reset(task, description="connecting", total=None)
                if not json_output:
                    console.print(_format_result(result, count), soft_wrap=True)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:  # last-resort guard at the CLI boundary
            progress.stop()
            typer.echo(f"error: {type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(ExitCode.ERROR) from exc

    summary = summarize(results)
    if json_output:
        report = _to_json(
            url=url, keepalive=keepalive, interrupted=interrupted, results=results, summary=summary
        )
        typer.echo(json.dumps(report, indent=2))
    else:
        _print_summary(console, summary, keepalive=keepalive, interrupted=interrupted)

    raise typer.Exit(_exit_code(summary, interrupted=interrupted))


def _exit_code(summary: Summary, *, interrupted: bool) -> ExitCode:
    if interrupted:
        return ExitCode.INTERRUPTED
    if summary.succeeded == 0:
        return ExitCode.ALL_FAILED
    if summary.failed:
        return ExitCode.PARTIAL_FAILURE
    return ExitCode.OK


def _speed_pair(bytes_per_second: float) -> str:
    return (
        f"{to_mbyte_per_s(bytes_per_second):.2f} MB/s "
        f"= {to_mbit_per_s(bytes_per_second):.2f} Mbit/s"
    )


def _format_result(result: RequestResult, count: int) -> Text:
    prefix = f"[{result.index:>2}/{count}] "
    if not result.ok:
        return Text(prefix + f"FAILED  {result.error}", style="red")
    speed = result.speed or 0.0
    ttfb = format_duration(result.ttfb) if result.ttfb is not None else "-"
    return Text(
        prefix
        + f"{result.status_code}  {format_bytes(result.bytes_downloaded):>9}  "
        + f"{format_duration(result.request_time):>9}  "
        + f"TTFB {ttfb:>8}  "
        + f"{to_mbyte_per_s(speed):>7.2f} MB/s  {to_mbit_per_s(speed):>8.2f} Mbit/s"
    )


_LABEL_WIDTH = 18


def _row(label: str, value: str, *, style: str = "", note: str = "") -> Text:
    text = Text(f"{label:<{_LABEL_WIDTH}}", style="bold")
    text.append(value, style=style)
    if note:
        text.append(f"  ({note})", style="dim")
    return text


def _summary_rows(summary: Summary, *, keepalive: bool) -> list[Text]:
    """What the task asks for, plus the one extra that changes the conclusion.

    Body-only speed and per-request percentiles stay in ``--json``.
    """
    requests = f"{summary.succeeded}/{summary.total} succeeded"
    if summary.failed:
        requests += f", {summary.failed} failed"
    rows = [
        _row("Requests", requests, style="red" if summary.failed else "green"),
        _row("Downloaded", f"{format_bytes(summary.total_bytes)} ({summary.total_bytes:,} bytes)"),
    ]
    if (rt := summary.request_time) is not None:
        rows.append(_row("Avg request time", format_duration(rt.mean), style="bold"))
        if rt.stdev is not None:
            rows.append(
                _row(
                    "Spread",
                    f"min {format_duration(rt.minimum)}, median {format_duration(rt.median)}, "
                    f"max {format_duration(rt.maximum)}",
                )
            )
    if summary.ttfb is not None:
        rows.append(_row("Avg TTFB", format_duration(summary.ttfb.mean)))
    if summary.throughput is None:
        rows.append(_row("Speed", "n/a", style="red", note="no successful requests"))
        return rows

    rows.append(
        _row(
            "Speed",
            _speed_pair(summary.throughput),
            style="bold cyan",
            note="total bytes / total time",
        )
    )
    # Only meaningful when later requests reuse the connection #1 opened.
    if keepalive and summary.first_request is not None:
        rest = summary.throughput_excluding_first
        if rest is not None:
            rows.append(
                _row("Without #1", _speed_pair(rest), note="excludes connection set-up and warm-up")
            )
    return rows


def _print_summary(
    console: Console, summary: Summary, *, keepalive: bool, interrupted: bool
) -> None:
    console.print()
    console.print(Text("Summary", style="bold underline"))
    for row in _summary_rows(summary, keepalive=keepalive):
        console.print(row, soft_wrap=True)
    if interrupted:
        console.print(
            Text("Interrupted by user: summary covers finished requests only.", style="yellow")
        )


def _to_json(
    *,
    url: str,
    keepalive: bool,
    interrupted: bool,
    results: list[RequestResult],
    summary: Summary,
) -> dict[str, Any]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "url": url,
        "keepalive": keepalive,
        "interrupted": interrupted,
        "requests": [r.to_dict() for r in results],
        "summary": summary.to_dict(),
    }


def main() -> None:
    app()
