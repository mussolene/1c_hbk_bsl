from __future__ import annotations

import importlib.util
import io
import json
import signal
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def soak():
    path = Path(__file__).resolve().parents[1] / "scripts/lsp_soak_profile.py"
    spec = importlib.util.spec_from_file_location("lsp_soak_profile", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_utf8_frames_preserve_message_boundaries(soak):
    first = {"jsonrpc": "2.0", "id": 1, "result": "Привет"}
    second = {"jsonrpc": "2.0", "id": 2, "result": None}
    stream = io.BytesIO()
    for message in (first, second):
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        stream.write(
            f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("ascii")
            + body
        )
    stream.seek(0)
    assert soak._read_message(stream) == first
    assert soak._read_message(stream) == second


@pytest.mark.parametrize(
    "frame", [b"\r\n{}", b"Content-Length: -1\r\n\r\n", b"Content-Length: 5\r\n\r\n{}"]
)
def test_invalid_or_incomplete_frame_fails(soak, frame):
    with pytest.raises((ValueError, EOFError)):
        soak._read_message(io.BytesIO(frame))


def test_latency_percentiles_use_nearest_rank(soak):
    samples = [{"operation": "hover", "elapsed_ms": value} for value in range(1, 21)]
    assert soak._transport_summary(samples) == {"hover": {"count": 20, "p50_ms": 10, "p95_ms": 19}}


@pytest.mark.parametrize("padding_bytes", [0, 1_000_000])
def test_real_stdio_reports_latest_diagnostics_without_source_or_paths(soak, padding_bytes):
    report = soak.run_transport(runs=2, timeout=15, padding_bytes=padding_bytes)
    assert report["mode"] == "transport"
    assert report["server_version"] != "unknown"
    assert report["diagnostics"]["status"] == "PASS"
    assert report["diagnostics"]["final_version"] == 7
    assert report["diagnostics"]["count"] == 1
    if padding_bytes:
        assert report["diagnostics"]["empty_reports_before_final"] >= 2
        assert report["diagnostics"]["refresh_requests"] >= 2
        assert report["diagnostics"]["async_refresh"] == "PASS"
    assert report["shutdown"] == {"graceful": True, "process_reaped": True}
    assert report["cancellation"]["status"] in {"PASS", "UNKNOWN"}
    assert len(report["samples"]) == 7
    assert report["latency"]["change_burst_to_final_diagnostic"]["count"] == 2
    encoded = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "file://",
        str(Path.home()),
        "synthetic.bsl",
        "Если Тогда",
        "workspace",
        "textDocument/didChange",
    ):
        assert forbidden not in encoded


def test_real_process_is_reaped_after_protocol_error(soak, tmp_path):
    client = soak._Transport(tmp_path, timeout=5)
    try:
        with pytest.raises(RuntimeError, match="returned an error"):
            client.request("unknown/method", {})
    finally:
        client.close()
    assert client.process.poll() is not None
    assert not client.reader.is_alive()


def test_stalled_process_has_bounded_request_and_forced_cleanup(soak, tmp_path):
    client = soak._Transport(tmp_path, timeout=5)
    try:
        client.request("initialize", {"processId": None, "capabilities": {}})
        client.process.send_signal(signal.SIGSTOP)
        client.timeout = 0.1
        with pytest.raises(TimeoutError, match="deadline exceeded"):
            client.request("textDocument/hover", {})
    finally:
        graceful = client.close()
    assert not graceful
    assert client.process.poll() is not None
    assert not client.reader.is_alive()


@pytest.mark.parametrize(
    "runs,timeout,padding", [(0, 1, 0), (1, 0, 0), (1, float("nan"), 0), (1, 1, -1)]
)
def test_invalid_limits_rejected_before_launch(soak, runs, timeout, padding):
    with pytest.raises(ValueError):
        soak.run_transport(runs=runs, timeout=timeout, padding_bytes=padding)
