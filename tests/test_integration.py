from _http_server import FILE_SIZE, ServerState, closed_port_url

from net_speedmeter import iter_benchmark, summarize


def test_ten_sequential_downloads_over_a_real_socket(http_server: ServerState) -> None:
    results = list(iter_benchmark(http_server.url("/file"), count=10))

    assert len(results) == 10
    assert all(r.ok for r in results), [r.error for r in results]
    assert all(r.bytes_downloaded == FILE_SIZE for r in results)
    assert all(r.ttfb is not None and 0 < r.ttfb <= r.request_time for r in results)

    summary = summarize(results)
    assert summary.total_bytes == 10 * FILE_SIZE
    assert summary.throughput is not None
    assert summary.throughput > 0


def test_keepalive_reuses_a_single_connection(http_server: ServerState) -> None:
    list(iter_benchmark(http_server.url("/file"), count=10, keepalive=True))
    assert http_server.connections_opened == 1


def test_no_keepalive_opens_a_fresh_connection_per_request(http_server: ServerState) -> None:
    list(iter_benchmark(http_server.url("/file"), count=10, keepalive=False))
    assert http_server.connections_opened == 10


def test_connection_dropped_mid_body_is_reported(http_server: ServerState) -> None:
    (result,) = iter_benchmark(http_server.url("/truncated"), count=1)

    assert not result.ok
    assert result.error is not None
    # Linux/macOS report the early close as a protocol error, Windows may see a reset.
    assert result.error.startswith(("RemoteProtocolError", "ReadError"))


def test_unreachable_host_is_reported() -> None:
    # Linux refuses immediately (ConnectError), Windows retries SYN until the
    # timeout (ConnectTimeout) - both must end up as a failed request.
    (result,) = iter_benchmark(closed_port_url(), count=1, timeout=1.0)

    assert not result.ok
    assert result.status_code is None
    assert result.error is not None
    assert result.error.startswith(("ConnectError", "ConnectTimeout"))
