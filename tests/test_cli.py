import io
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest
from _factories import failed, ok
from _http_server import ServerState

from net_speedmeter import __version__, cli
from net_speedmeter.measure import RequestResult

URL = "https://example.test/a.jpg"


def fake_benchmark(
    monkeypatch: pytest.MonkeyPatch,
    results: list[RequestResult],
    *,
    then: BaseException | None = None,
) -> list[tuple[str, int]]:
    """Replace the network layer; returns the (url, count) calls the CLI made."""
    calls: list[tuple[str, int]] = []

    def fake(url: str, count: int, **kwargs: Any) -> Iterator[RequestResult]:
        calls.append((url, count))
        yield from results
        if then is not None:
            raise then

    monkeypatch.setattr(cli, "benchmark", fake)
    return calls


def test_report_contains_what_the_task_asks_for(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 5 MB in 4 s, then 5 MB in 1 s twice: 15 MB / 6 s; mean time 2 s
    calls = fake_benchmark(monkeypatch, [ok(1, request_time=4.0), ok(2), ok(3)])

    code = cli.main([URL, "-n", "3"])

    out = capsys.readouterr().out
    assert code == 0
    assert calls == [(URL, 3)]
    assert "[ 2/3] 200      5.00 MB     1.000 s  TTFB   100 ms     5.00 MB/s" in out
    assert "Requests          3/3 succeeded" in out
    assert "Downloaded        15.00 MB (15,000,000 bytes)" in out
    assert "Avg request time  2.000 s" in out
    assert "Avg TTFB          100 ms" in out
    assert "Speed             2.50 MB/s (20.00 Mbit/s)" in out
    assert "Without #1        5.00 MB/s (40.00 Mbit/s)" in out


def test_default_is_ten_requests_to_a_heavy_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_benchmark(monkeypatch, [ok(1)])

    cli.main([])

    assert calls == [(cli.DEFAULT_URL, 10)]


def test_any_failed_request_gives_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_benchmark(monkeypatch, [ok(1), failed(2)])

    assert cli.main([URL, "-n", "2"]) == 1
    out = capsys.readouterr().out
    assert "[ 2/2] FAILED  boom" in out
    assert "1/2 succeeded, 1 failed" in out


def test_nothing_succeeded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_benchmark(monkeypatch, [failed(1)])

    assert cli.main([URL, "-n", "1"]) == 1
    out = capsys.readouterr().out
    assert "Speed             n/a" in out
    assert "Avg request time" not in out


def test_redirect_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_benchmark(monkeypatch, [ok(1, redirected_to="https://cdn.example.test/a.jpg")])

    cli.main(["https://example.test/old", "-n", "1"])

    assert "redirected to https://cdn.example.test/a.jpg" in capsys.readouterr().out


def test_no_redirect_line_without_a_redirect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # httpx normalises e.g. the host case or non-ASCII paths; that is not a redirect
    fake_benchmark(monkeypatch, [ok(1)])

    cli.main(["https://EXAMPLE.test/café.jpg", "-n", "1"])

    assert "redirected" not in capsys.readouterr().out


def test_ctrl_c_prints_a_partial_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_benchmark(monkeypatch, [ok(1)], then=KeyboardInterrupt())

    assert cli.main([URL]) == 130
    out = capsys.readouterr().out
    assert "1/1 succeeded" in out
    assert "Interrupted after 1 of 10 requests." in out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["ftp://example.test/a.jpg"], "http(s)"),
        (["example.test/a.jpg"], "http(s)"),
        (["http://exa" + chr(0) + "mple.test/"], "invalid URL"),
        ([URL, "-n", "0"], "between 1 and 1000"),
        ([URL, "-n", "1001"], "between 1 and 1000"),
        ([URL, "-n", "ten"], "invalid int value"),
    ],
)
def test_bad_arguments_exit_2_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    message: str,
) -> None:
    calls = fake_benchmark(monkeypatch, [ok(1)])

    with pytest.raises(SystemExit) as exit_info:
        cli.main(args)

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err
    assert calls == []


def test_runs_as_a_module_against_a_real_server(http_server: ServerState) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "net_speedmeter", http_server.url("/file"), "-n", "2"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"net-speedmeter {__version__}" in completed.stdout
    assert "2/2 succeeded" in completed.stdout


def test_output_to_a_non_utf8_file_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows: stdout redirected to a file defaults to the ANSI code page (e.g. cp1251)
    buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buffer, encoding="cp1251"))
    fake_benchmark(monkeypatch, [ok(1)])

    cli.main(["https://example.test/日本.jpg", "-n", "1"])

    sys.stdout.flush()
    assert "https://example.test/日本.jpg" in buffer.getvalue().decode("utf-8")
