import json
from collections.abc import Iterator
from typing import Any

import pytest
from _http_server import FILE_SIZE, ServerState
from typer.testing import CliRunner

from net_speedmeter import __version__, cli
from net_speedmeter.cli import ExitCode, _exit_code, app
from net_speedmeter.models import RequestResult
from net_speedmeter.stats import summarize

# Wide, colourless "terminal": assertions must not depend on wrapping or ANSI codes.
runner = CliRunner(env={"NO_COLOR": "1", "COLUMNS": "200", "TERM": "dumb"})
URL = "https://example.com/a.jpg"


def ok(index: int, nbytes: int = 5_000_000, request_time: float = 1.0) -> RequestResult:
    return RequestResult(
        index=index,
        status_code=200,
        bytes_downloaded=nbytes,
        request_time=request_time,
        ttfb=0.1,
    )


def failed(index: int) -> RequestResult:
    return RequestResult(
        index=index,
        status_code=503,
        bytes_downloaded=0,
        request_time=0.1,
        ttfb=0.1,
        error="HTTP 503 Service Unavailable",
    )


def fake_benchmark(
    monkeypatch: pytest.MonkeyPatch,
    results: list[RequestResult],
    *,
    then: BaseException | None = None,
) -> dict[str, Any]:
    """Replace the network layer; returns the kwargs the CLI passed to it."""
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> Iterator[RequestResult]:
        seen.update(url=url, **kwargs)
        yield from results
        if then is not None:
            raise then

    monkeypatch.setattr(cli, "iter_benchmark", fake)
    return seen


# --- end to end against the real local server ------------------------------------


def test_human_output_reports_time_volume_and_speed(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/file"), "-n", "3"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "[ 1/3]" in out
    assert "[ 3/3]" in out
    assert "3/3 succeeded" in out
    assert "Avg request time" in out
    assert "6.00 MB" in out  # 3 x 2 MB
    assert "Without #1" in out
    assert "MB/s = " in out
    assert "Mbit/s" in out


def test_default_count_is_ten(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/file"), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["requests"]) == 10
    assert payload["summary"]["succeeded"] == 10


def test_json_output_is_machine_readable(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/file"), "-n", "2", "--json", "--no-keepalive"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["url"] == http_server.url("/file")
    assert payload["keepalive"] is False
    assert payload["interrupted"] is False
    assert [r["index"] for r in payload["requests"]] == [1, 2]
    assert all(r["bytes"] == FILE_SIZE for r in payload["requests"])

    summary = payload["summary"]
    assert summary["total_bytes"] == 2 * FILE_SIZE
    assert summary["speed_mbyte_s"] > 0
    assert summary["speed_mbyte_s"] * 8 == pytest.approx(summary["speed_mbit_s"], rel=1e-4)
    assert set(summary["per_request_speed_mbyte_s"]) == {
        "mean",
        "median",
        "p90",
        "min",
        "max",
        "stdev",
    }


def test_partial_failure_exits_with_1(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/flaky"), "-n", "4"])

    assert result.exit_code == ExitCode.PARTIAL_FAILURE, result.output
    assert "HTTP 503" in result.output
    assert "2/4 succeeded, 2 failed" in result.output


def test_all_failed_human_output(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/missing"), "-n", "2"])

    assert result.exit_code == ExitCode.ALL_FAILED
    assert "0/2 succeeded, 2 failed" in result.output
    assert "n/a" in result.output
    assert "Avg request time" not in result.output


def test_all_failed_json_output(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/missing"), "-n", "2", "--json"])

    assert result.exit_code == ExitCode.ALL_FAILED
    payload = json.loads(result.output)
    assert payload["summary"]["succeeded"] == 0
    assert payload["summary"]["speed_mbyte_s"] is None


# --- CLI wiring with the network layer replaced -----------------------------------


def test_options_are_passed_to_the_benchmark(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = fake_benchmark(monkeypatch, [ok(1)])

    result = runner.invoke(app, [URL, "-n", "3", "--no-keepalive", "--timeout", "2.5", "--json"])

    assert result.exit_code == 0, result.output
    assert seen["url"] == URL
    assert seen["count"] == 3
    assert seen["keepalive"] is False
    assert seen["timeout"] == 2.5
    assert seen["on_progress"] is None  # nothing is rendered in JSON mode


def test_human_numbers_are_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    # 5 MB in 4 s, 5 MB in 1 s, 5 MB in 1 s => 15 MB / 6 s; mean time 2 s, median 1 s
    fake_benchmark(monkeypatch, [ok(1, request_time=4.0), ok(2), ok(3)])

    result = runner.invoke(app, [URL, "-n", "3"])

    out = result.output
    assert "[ 2/3] 200    5.00 MB    1.000 s  TTFB 100.0 ms     5.00 MB/s     40.00 Mbit/s" in out
    assert "Avg request time  2.000 s" in out
    assert "median 1.000 s" in out
    assert "Speed             2.50 MB/s = 20.00 Mbit/s" in out
    assert "Without #1        5.00 MB/s = 40.00 Mbit/s" in out


def test_single_request_shows_no_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_benchmark(monkeypatch, [ok(1)])

    result = runner.invoke(app, [URL, "-n", "1"])

    assert "Avg request time  1.000 s" in result.output
    assert "Spread" not in result.output
    assert "Without #1" not in result.output


def test_without_first_is_hidden_when_every_request_is_cold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_benchmark(monkeypatch, [ok(1, request_time=4.0), ok(2), ok(3)])

    result = runner.invoke(app, [URL, "-n", "3", "--no-keepalive"])

    assert "Speed             2.50 MB/s" in result.output
    assert "Without #1" not in result.output


def test_ctrl_c_prints_partial_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_benchmark(monkeypatch, [ok(1)], then=KeyboardInterrupt())

    result = runner.invoke(app, [URL])

    assert result.exit_code == ExitCode.INTERRUPTED
    assert "1/1 succeeded" in result.output
    assert "5.00 MB/s = 40.00 Mbit/s" in result.output
    assert "Interrupted" in result.output


def test_ctrl_c_in_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_benchmark(monkeypatch, [ok(1)], then=KeyboardInterrupt())

    result = runner.invoke(app, [URL, "--json"])

    assert result.exit_code == ExitCode.INTERRUPTED
    assert json.loads(result.output)["interrupted"] is True


def test_unexpected_error_is_reported_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_benchmark(monkeypatch, [], then=ValueError("Unknown scheme for proxy URL"))

    result = runner.invoke(app, [URL, "--json"])

    assert result.exit_code == ExitCode.ERROR
    assert "error: ValueError: Unknown scheme for proxy URL" in result.output


@pytest.mark.parametrize(
    ("results", "interrupted", "expected"),
    [
        ([ok(1)], False, ExitCode.OK),
        ([ok(1), ok(2), failed(3)], False, ExitCode.PARTIAL_FAILURE),
        ([failed(1)], False, ExitCode.ALL_FAILED),
        ([], True, ExitCode.INTERRUPTED),
        ([failed(1)], True, ExitCode.INTERRUPTED),
    ],
)
def test_exit_code_table(
    results: list[RequestResult], interrupted: bool, expected: ExitCode
) -> None:
    assert _exit_code(summarize(results), interrupted=interrupted) is expected


# --- argument validation --------------------------------------------------------


def test_invalid_url_is_a_usage_error() -> None:
    result = runner.invoke(app, ["ftp://example.com/file.jpg"])

    assert result.exit_code == ExitCode.USAGE
    assert "http(s)" in result.output


@pytest.mark.parametrize("args", [["-n", "0"], ["-n", "1001"], ["--timeout", "0.05"]])
def test_option_bounds(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    seen = fake_benchmark(monkeypatch, [ok(1)])

    result = runner.invoke(app, [*args, URL])

    assert result.exit_code == ExitCode.USAGE
    assert "Invalid value" in result.output
    assert not seen  # rejected before any network activity


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help(flag: str) -> None:
    result = runner.invoke(app, [flag])

    assert result.exit_code == 0
    assert "Exit codes" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
