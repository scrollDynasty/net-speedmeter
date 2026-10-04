import json
from collections.abc import Iterator

import pytest
from conftest import FILE_SIZE, ServerState
from typer.testing import CliRunner

from net_speedmeter import __version__, cli
from net_speedmeter.cli import app
from net_speedmeter.models import RequestResult

runner = CliRunner()


def test_human_output_reports_time_volume_and_speed(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/file"), "-n", "3"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "[ 1/3]" in out
    assert "[ 3/3]" in out
    assert "3/3 succeeded" in out
    assert "Avg request time" in out
    assert "6.00 MB" in out  # 3 x 2 MB
    assert "Mbit/s" in out
    assert "MB/s" in out


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
    assert payload["url"] == http_server.url("/file")
    assert payload["keepalive"] is False
    assert payload["interrupted"] is False
    assert [r["index"] for r in payload["requests"]] == [1, 2]
    assert all(r["bytes"] == FILE_SIZE for r in payload["requests"])

    summary = payload["summary"]
    assert summary["total_bytes"] == 2 * FILE_SIZE
    assert summary["speed_mbit_s"] > 0
    assert summary["speed_mbyte_s"] * 8 == pytest.approx(summary["speed_mbit_s"])
    assert set(summary["per_request_speed_mbit_s"]) == {"mean", "median", "p90", "min", "max"}


def test_partial_failure_exits_with_1(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/flaky"), "-n", "4"])

    assert result.exit_code == 1, result.output
    assert "HTTP 503" in result.output
    assert "2/4 succeeded, 2 failed" in result.output


def test_all_requests_failed_exits_with_2(http_server: ServerState) -> None:
    result = runner.invoke(app, [http_server.url("/missing"), "-n", "2", "--json"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["summary"]["succeeded"] == 0
    assert payload["summary"]["speed_mbit_s"] is None


def test_invalid_url_is_a_usage_error() -> None:
    result = runner.invoke(app, ["ftp://example.com/file.jpg"])

    assert result.exit_code == 2
    assert "http(s)" in result.output


def test_count_must_be_positive() -> None:
    result = runner.invoke(app, ["https://example.com/a.jpg", "-n", "0"])
    assert result.exit_code == 2


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_ctrl_c_prints_partial_summary_and_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    finished = RequestResult(
        index=1, ok=True, status_code=200, bytes_downloaded=5_000_000, request_time=1.0, ttfb=0.1
    )

    def fake_benchmark(*args: object, **kwargs: object) -> Iterator[RequestResult]:
        yield finished
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "iter_benchmark", fake_benchmark)
    result = runner.invoke(app, ["https://example.com/a.jpg"])

    assert result.exit_code == 130
    assert "1/1 succeeded" in result.output
    assert "40.00 Mbit/s = 5.00 MB/s" in result.output
    assert "Interrupted" in result.output


def test_unexpected_error_is_reported_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object, **kwargs: object) -> Iterator[RequestResult]:
        raise ValueError("Unknown scheme for proxy URL")
        yield  # pragma: no cover - makes this a generator

    monkeypatch.setattr(cli, "iter_benchmark", broken)
    result = runner.invoke(app, ["https://example.com/a.jpg", "--json"])

    assert result.exit_code == 3
    assert "error: ValueError: Unknown scheme for proxy URL" in result.output
