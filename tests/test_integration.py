"""End to end over real sockets against local HTTP/1.1 keep-alive servers."""

from _http_server import FILE_SIZE, ServerState, closed_port_url, running_server

from net_speedmeter.measure import benchmark
from net_speedmeter.stats import summarize


def test_ten_sequential_downloads_reuse_one_connection(http_server: ServerState) -> None:
    results = list(benchmark(http_server.url("/file")))

    assert len(results) == 10
    assert all(r.ok and r.bytes_downloaded == FILE_SIZE for r in results)
    assert all(r.ttfb is not None and 0 < r.ttfb <= r.request_time for r in results)
    assert summarize(results).total_bytes == 10 * FILE_SIZE
    assert http_server.connections_opened == 1


def test_error_responses_do_not_break_keep_alive(http_server: ServerState) -> None:
    # /flaky alternates 200 and 503: undrained error bodies would force a reconnect each time
    results = list(benchmark(http_server.url("/flaky"), 6))

    assert [r.ok for r in results] == [True, False] * 3
    assert http_server.connections_opened == 1


def test_cross_host_redirect_is_resolved_once(http_server: ServerState) -> None:
    with running_server() as cdn:
        url = http_server.url(f"/redirect?to={cdn.url('/file')}")
        results = list(benchmark(url, 5))

    assert all(r.ok for r in results)
    assert results[0].final_url == cdn.url("/file")
    # only request #1 pays for the redirect hop; the rest go straight to the final URL
    assert http_server.requests_handled == 1
    assert cdn.requests_handled == 5
    assert cdn.connections_opened == 1


def test_connection_dropped_mid_body(http_server: ServerState) -> None:
    (result,) = benchmark(http_server.url("/truncated"), 1)

    assert result.error is not None
    # Linux/macOS report the early close as a protocol error, Windows may see a reset.
    assert result.error.startswith(("RemoteProtocolError", "ReadError"))


def test_unreachable_host() -> None:
    # Linux refuses at once (ConnectError); Windows retries SYN until the timeout.
    (result,) = benchmark(closed_port_url(), 1)

    assert result.status_code is None
    assert result.error is not None
    assert result.error.startswith(("ConnectError", "ConnectTimeout"))
