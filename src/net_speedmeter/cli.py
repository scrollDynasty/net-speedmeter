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

from net_speedmeter import __version__
from net_speedmeter.measure import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COUNT,
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    iter_benchmark,
    validate_url,
)
from net_speedmeter.models import RequestResult, Summary
from net_speedmeter.stats import summarize
from net_speedmeter.units import format_bytes, format_duration, to_mbit_per_s, to_mbyte_per_s


class ExitCode(IntEnum):
    OK = 0
    PARTIAL_FAILURE = 1
    ALL_FAILED = 2  # also what Click uses for usage errors
    ERROR = 3  # broken environment: bad proxy settings, missing CA bundle, ...
    INTERRUPTED = 130  # conventional 128 + SIGINT


app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help=(
        "Measure download speed: fetch URL N times sequentially, then report the average "
        "request time, downloaded volume and speed in Mbit/s and MB/s."
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


@app.command()
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
        typer.Option("--count", "-n", min=1, max=1000, help="Number of sequential requests."),
    ] = DEFAULT_COUNT,
    timeout: Annotated[
        float,
        typer.Option(
            min=0.1, help="Timeout in seconds for each network operation (connect, each read)."
        ),
    ] = DEFAULT_TIMEOUT,
    keepalive: Annotated[
        bool,
        typer.Option(
            "--keepalive/--no-keepalive",
            help="Reuse one connection (default) or open a fresh one for every request.",
        ),
    ] = True,
    chunk_size: Annotated[
        int,
        typer.Option(min=1024, help="Read buffer size in bytes."),
    ] = DEFAULT_CHUNK_SIZE,
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
    quiet = json_output

    if not quiet:
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
        disable=quiet or not console.is_terminal,
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
                chunk_size=chunk_size,
                # no per-chunk callback at all when nothing is rendered
                on_progress=None if progress.disable else on_progress,
            ):
                results.append(result)
                progress.reset(task, description="connecting", total=None)
                if not quiet:
                    console.print(_format_result(result, count), soft_wrap=True)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:
            progress.stop()
            typer.echo(f"error: {type(exc).__name__}: {exc}", err=True)
            raise typer.Exit(int(ExitCode.ERROR)) from exc

    summary = summarize(results)
    if quiet:
        typer.echo(json.dumps(_to_json(url, keepalive, interrupted, results, summary), indent=2))
    else:
        _print_summary(console, summary, interrupted)

    raise typer.Exit(int(_exit_code(summary, interrupted)))


def _exit_code(summary: Summary, interrupted: bool) -> ExitCode:
    if interrupted:
        return ExitCode.INTERRUPTED
    if summary.succeeded == 0:
        return ExitCode.ALL_FAILED
    if summary.failed:
        return ExitCode.PARTIAL_FAILURE
    return ExitCode.OK


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
        + f"{to_mbit_per_s(speed):>8.2f} Mbit/s  {to_mbyte_per_s(speed):>7.2f} MB/s"
    )


def _speed_text(bytes_per_second: float | None) -> str:
    if bytes_per_second is None:
        return "n/a"
    return (
        f"{to_mbit_per_s(bytes_per_second):.2f} Mbit/s "
        f"= {to_mbyte_per_s(bytes_per_second):.2f} MB/s"
    )


_LABEL_WIDTH = 18


def _row(label: str, value: str, style: str = "", note: str = "") -> Text:
    text = Text(f"{label:<{_LABEL_WIDTH}}", style="bold")
    text.append(value, style=style)
    if note:
        text.append(f"  ({note})", style="dim")
    return text


def _print_summary(console: Console, summary: Summary, interrupted: bool) -> None:
    rows: list[Text] = []

    requests = f"{summary.succeeded}/{summary.total} succeeded"
    if summary.failed:
        requests += f", {summary.failed} failed"
    rows.append(_row("Requests", requests, style="red" if summary.failed else "green"))
    rows.append(
        _row("Downloaded", f"{format_bytes(summary.total_bytes)} ({summary.total_bytes:,} bytes)")
    )
    if (rt := summary.request_time) is not None:
        rows.append(_row("Avg request time", format_duration(rt.mean), style="bold"))
        rows.append(
            _row(
                "Spread",
                f"min {format_duration(rt.minimum)}, median {format_duration(rt.median)}, "
                f"max {format_duration(rt.maximum)}, stdev {format_duration(rt.stdev)}",
            )
        )
    if summary.ttfb is not None:
        rows.append(_row("Avg TTFB", format_duration(summary.ttfb.mean)))
    rows.append(
        _row(
            "Speed",
            _speed_text(summary.throughput),
            style="bold cyan",
            note="total bytes / total time",
        )
    )
    rows.append(
        _row("Body transfer", _speed_text(summary.transfer_throughput), note="excluding TTFB")
    )
    if (sp := summary.speed) is not None:
        rows.append(
            _row(
                "Per-request",
                f"median {to_mbit_per_s(sp.median):.2f} / p90 {to_mbit_per_s(sp.p90):.2f} / "
                f"min {to_mbit_per_s(sp.minimum):.2f} / max {to_mbit_per_s(sp.maximum):.2f} "
                "Mbit/s",
            )
        )

    console.print()
    console.print(Text("Summary", style="bold underline"))
    for row in rows:
        console.print(row, soft_wrap=True)
    if interrupted:
        console.print(
            Text("Interrupted by user: summary covers finished requests only.", style="yellow")
        )


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _mbit(value: float | None) -> float | None:
    return None if value is None else round(to_mbit_per_s(value), 4)


def _mbyte(value: float | None) -> float | None:
    return None if value is None else round(to_mbyte_per_s(value), 4)


def _to_json(
    url: str,
    keepalive: bool,
    interrupted: bool,
    results: list[RequestResult],
    summary: Summary,
) -> dict[str, Any]:
    speed = summary.speed
    request_time = summary.request_time
    return {
        "url": url,
        "keepalive": keepalive,
        "interrupted": interrupted,
        "requests": [
            {
                "index": r.index,
                "ok": r.ok,
                "status_code": r.status_code,
                "bytes": r.bytes_downloaded,
                "request_time_s": _round(r.request_time),
                "ttfb_s": _round(r.ttfb),
                "transfer_time_s": _round(r.transfer_time),
                "speed_mbit_s": _mbit(r.speed),
                "speed_mbyte_s": _mbyte(r.speed),
                "error": r.error,
            }
            for r in results
        ],
        "summary": {
            "total": summary.total,
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "total_bytes": summary.total_bytes,
            "avg_request_time_s": None if request_time is None else _round(request_time.mean),
            "median_request_time_s": None if request_time is None else _round(request_time.median),
            "stdev_request_time_s": None if request_time is None else _round(request_time.stdev),
            "avg_ttfb_s": None if summary.ttfb is None else _round(summary.ttfb.mean),
            "speed_mbit_s": _mbit(summary.throughput),
            "speed_mbyte_s": _mbyte(summary.throughput),
            "transfer_speed_mbit_s": _mbit(summary.transfer_throughput),
            "transfer_speed_mbyte_s": _mbyte(summary.transfer_throughput),
            "per_request_speed_mbit_s": None
            if speed is None
            else {
                "mean": _mbit(speed.mean),
                "median": _mbit(speed.median),
                "p90": _mbit(speed.p90),
                "min": _mbit(speed.minimum),
                "max": _mbit(speed.maximum),
            },
        },
    }


def main() -> None:
    app()
