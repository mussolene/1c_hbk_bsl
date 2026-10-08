#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import random
import resource
import select
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

from onec_hbk_bsl.lsp.server import (
    _ASYNC_PULL_DIAGNOSTICS_MIN_BYTES,
    BslLanguageServer,
    on_did_change,
    on_did_close,
    on_did_open,
    on_document_diagnostic,
)


def _read_message(stream: BinaryIO) -> dict:
    """Decode one Content-Length frame; bodies are UTF-8 octets."""
    length = None
    while True:
        line = stream.readline(8193)
        if not line:
            raise EOFError("LSP transport closed")
        if len(line) > 8192:
            raise ValueError("LSP header too large")
        if line == b"\r\n":
            break
        key, value = line.decode("ascii").split(":", 1)
        if key.lower() == "content-length":
            length = int(value.strip())
    if length is None or not 0 <= length <= 32 * 1024 * 1024:
        raise ValueError("Invalid LSP Content-Length")
    body = bytearray()
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            raise EOFError("Incomplete LSP body")
        body.extend(chunk)
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Invalid LSP message")
    return message


class _Transport:
    """Own a bounded stdio session and answer server-to-client requests."""

    def __init__(self, workspace: Path, timeout: float):
        env = os.environ.copy()
        root = Path(__file__).resolve().parents[1]
        env.update(
            {
                "PYTHONPATH": str(root / "src"),
                "INDEX_DB_PATH": str(workspace / "index.sqlite"),
                "BSL_INDEX_MODE": "off",
                "BSL_SELECT": "BSL001",
                "BSL_IGNORE": "",
                "BSL_DIAGNOSTICS_ENABLED": "1",
                "BSL_DIAG_PROCESS_RULES": "0",
            }
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "onec_hbk_bsl", "lsp"],
            cwd=workspace,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.timeout = timeout
        assert self.process.stdin is not None
        os.set_blocking(self.process.stdin.fileno(), False)
        self.next_id = 0
        self.refreshes = 0
        self.messages: queue.Queue = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        try:
            assert self.process.stdout is not None
            while True:
                self.messages.put(_read_message(self.process.stdout))
        except (EOFError, ValueError, OSError):
            self.messages.put(None)

    def send(self, message: dict) -> None:
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        assert self.process.stdin is not None
        frame = memoryview(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        deadline = time.monotonic() + self.timeout
        fd = self.process.stdin.fileno()
        while frame:
            if not select.select([], [fd], [], max(0.0, deadline - time.monotonic()))[1]:
                raise TimeoutError("LSP write deadline exceeded")
            try:
                frame = frame[os.write(fd, frame) :]
            except BlockingIOError:
                continue

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict, *, cancel: bool = False) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if cancel:
            self.notify("$/cancelRequest", {"id": request_id})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError("LSP request deadline exceeded") from None
            if message is None:
                raise RuntimeError("LSP transport closed before response")
            if "method" in message:
                if message["method"] == "workspace/diagnostic/refresh":
                    self.refreshes += 1
                if "id" in message:
                    result = [] if message["method"] == "workspace/configuration" else None
                    self.send({"jsonrpc": "2.0", "id": message["id"], "result": result})
            elif message.get("id") == request_id:
                if "error" in message and not cancel:
                    raise RuntimeError("LSP request returned an error")
                return message

    def close(self) -> bool:
        graceful = False
        try:
            if self.process.poll() is None:
                self.request("shutdown", {})
                self.notify("exit", {})
                self.process.wait(timeout=self.timeout)
                graceful = self.process.returncode == 0
        except (TimeoutError, RuntimeError, OSError, subprocess.TimeoutExpired):
            pass
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=min(self.timeout, 2.0))
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2.0)
            self.reader.join(timeout=2.0)
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
        return graceful


def _transport_summary(samples: list[dict]) -> dict:
    summary = {}
    for operation in sorted({sample["operation"] for sample in samples}):
        values = sorted(
            sample["elapsed_ms"] for sample in samples if sample["operation"] == operation
        )
        summary[operation] = {
            "count": len(values),
            "p50_ms": values[math.ceil(len(values) * 0.5) - 1],
            "p95_ms": values[math.ceil(len(values) * 0.95) - 1],
        }
    return summary


def run_transport(*, runs: int, timeout: float, padding_bytes: int = 0) -> dict:
    """Measure synthetic requests, including the final diagnostic after an edit burst.

    A unique syntax error at the final version's line is the completion witness.
    Empty asynchronous reports cannot satisfy it, even when refresh races a reply.
    """
    if runs < 1 or not math.isfinite(timeout) or timeout <= 0 or padding_bytes < 0:
        raise ValueError("Transport runs and timeout must be positive; padding must be nonnegative")
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/bench_100.bsl"
    content = fixture.read_text(encoding="utf-8") + "\n"
    content += "//" + "x" * padding_bytes + "\n"
    expect_refresh = len(content.encode("utf-8")) >= _ASYNC_PULL_DIAGNOSTICS_MIN_BYTES
    samples = []
    with tempfile.TemporaryDirectory(prefix="bsl-transport-") as temp_dir:
        workspace = Path(temp_dir)
        uri = (workspace / "synthetic.bsl").as_uri()
        client = _Transport(workspace, timeout)
        try:
            started = time.perf_counter()
            initialized = client.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "rootUri": workspace.as_uri(),
                    "capabilities": {
                        "textDocument": {"diagnostic": {"relatedDocumentSupport": True}},
                        "workspace": {"diagnostics": {"refreshSupport": True}},
                    },
                },
            )
            samples.append(
                {
                    "operation": "initialize",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
            client.notify("initialized", {})
            client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "bsl",
                        "version": 1,
                        "text": content,
                    }
                },
            )
            position = {"textDocument": {"uri": uri}, "position": {"line": 6, "character": 15}}
            version = 1
            final_count = 0
            empty_reports = 0
            for iteration in range(runs):
                for method in ("textDocument/hover", "textDocument/completion"):
                    started = time.perf_counter()
                    client.request(method, position)
                    samples.append(
                        {
                            "operation": method,
                            "iteration": iteration,
                            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                        }
                    )
                started = time.perf_counter()
                previous_refreshes = client.refreshes
                for change in range(3):
                    version += 1
                    # Each final witness is at a new line, unlike previous versions.
                    text = content + "\n" * version
                    if change == 2:
                        text += "Процедура Тест()\n    Если Тогда\nКонецПроцедуры\n"
                    client.notify(
                        "textDocument/didChange",
                        {
                            "textDocument": {"uri": uri, "version": version},
                            "contentChanges": [{"text": text}],
                        },
                    )
                expected_line = len((content + "\n" * version).splitlines()) + 1
                deadline = time.monotonic() + timeout
                while True:
                    response = client.request(
                        "textDocument/diagnostic", {"textDocument": {"uri": uri}}
                    )
                    items = response.get("result", {}).get("items", [])
                    if not items:
                        empty_reports += 1
                    if any(item["range"]["start"]["line"] == expected_line for item in items) and (
                        not expect_refresh or client.refreshes > previous_refreshes
                    ):
                        final_count = len(items)
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Final diagnostic or async refresh deadline exceeded")
                    time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
                samples.append(
                    {
                        "operation": "change_burst_to_final_diagnostic",
                        "iteration": iteration,
                        "version": version,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
            cancelled = client.request("textDocument/hover", position, cancel=True)
            cancellation = "PASS" if cancelled.get("error", {}).get("code") == -32800 else "UNKNOWN"
            report = {
                "schema_version": 1,
                "mode": "transport",
                "dataset": "bench_100",
                "python_version": sys.version.split()[0],
                "server_version": initialized.get("result", {})
                .get("serverInfo", {})
                .get("version", "unknown"),
                "rules": ["BSL001"],
                "index_mode": "off",
                "runs": runs,
                "padding_bytes": padding_bytes,
                "timeout_sec": timeout,
                "samples": samples,
                "latency": _transport_summary(samples),
                "diagnostics": {
                    "status": "PASS",
                    "final_version": version,
                    "count": final_count,
                    "refresh_requests": client.refreshes,
                    "empty_reports_before_final": empty_reports,
                    "async_refresh": "PASS" if expect_refresh else "NOT_APPLICABLE",
                },
                "cancellation": {
                    "status": cancellation,
                    "reason": "request_cancelled_response"
                    if cancellation == "PASS"
                    else "no_request_cancelled_response_observed",
                },
            }
        finally:
            graceful = client.close()
        report["shutdown"] = {
            "graceful": graceful,
            "process_reaped": client.process.poll() is not None,
        }
        return report


def _collect_files(workspace: Path, limit: int, seed: int) -> list[Path]:
    files = [p for p in workspace.rglob("*.bsl") if p.is_file()]
    files.sort()
    rng = random.Random(seed)  # noqa: S311 - deterministic sampling for benchmark reproducibility
    rng.shuffle(files)
    return files[:limit]


def _did_open_params(uri: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(text_document=SimpleNamespace(uri=uri, text=text))


def _did_change_params(uri: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text_document=SimpleNamespace(uri=uri),
        content_changes=[SimpleNamespace(text=text)],
    )


def _did_close_params(uri: str) -> SimpleNamespace:
    return SimpleNamespace(text_document=SimpleNamespace(uri=uri))


def _maxrss_mb() -> float:
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KB; macOS reports bytes.
    if maxrss > 10_000_000:
        return maxrss / (1024.0 * 1024.0)
    return maxrss / 1024.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="30-60 min LSP soak profile for memory/thread/cache drift."
    )
    parser.add_argument("--workspace", help="Workspace root with .bsl files (direct mode).")
    parser.add_argument(
        "--transport",
        action="store_true",
        help="Profile a real stdio LSP using synthetic content only.",
    )
    parser.add_argument("--transport-runs", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument(
        "--transport-padding-bytes",
        type=int,
        default=0,
        help="Synthetic comment padding; 1000000 exercises async diagnostics.",
    )
    parser.add_argument(
        "--duration-min",
        type=float,
        default=30.0,
        help="Soak duration in minutes (recommended: 30-60).",
    )
    parser.add_argument(
        "--sample-interval-sec",
        type=float,
        default=15.0,
        help="Interval for drift snapshots.",
    )
    parser.add_argument(
        "--file-limit",
        type=int,
        default=200,
        help="Max sampled files from workspace.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed.")
    parser.add_argument(
        "--index-workspace",
        action="store_true",
        help="Run initial index_workspace before soak loop.",
    )
    parser.add_argument(
        "--output-dir",
        default=".tmp/reports/lsp-soak",
        help="Directory for JSONL samples and summary JSON.",
    )
    args = parser.parse_args()

    if args.transport:
        if args.workspace or args.index_workspace:
            parser.error("transport mode uses a temporary synthetic workspace")
        report = run_transport(
            runs=args.transport_runs,
            timeout=args.timeout_sec,
            padding_bytes=args.transport_padding_bytes,
        )
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "lsp_transport_summary.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report))
        return 0
    if not args.workspace:
        parser.error("--workspace is required in direct mode")

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace is not a directory: {workspace}")

    files = _collect_files(workspace, args.file_limit, args.seed)
    if not files:
        raise SystemExit(f"no .bsl files found under: {workspace}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    started_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at))
    samples_path = output_dir / "lsp_soak_samples.jsonl"
    summary_path = output_dir / "lsp_soak_summary.json"

    ls = BslLanguageServer()
    ls.client_pull_diagnostics = True  # avoid push threads; drive diagnostics explicitly
    if args.index_workspace:
        ls.indexer.index_workspace(str(workspace), force=False)

    import tracemalloc

    tracemalloc.start()
    duration_sec = args.duration_min * 60.0
    loop_started_mono = time.monotonic()
    next_sample_at = time.monotonic()
    file_index = 0
    operations = 0
    unique_uris: set[str] = set()
    samples: list[dict[str, object]] = []

    with samples_path.open("w", encoding="utf-8") as out:
        while True:
            now = time.monotonic()
            if time.time() - started_at >= duration_sec:
                break

            path = files[file_index % len(files)]
            file_index += 1
            uri = path.as_uri()
            unique_uris.add(uri)
            content = path.read_text(encoding="utf-8", errors="replace")

            on_did_open(ls, _did_open_params(uri, content))
            on_document_diagnostic(
                ls,
                DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri)),
            )
            on_did_change(ls, _did_change_params(uri, content))
            on_document_diagnostic(
                ls,
                DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri)),
            )
            on_did_close(ls, _did_close_params(uri))
            operations += 1

            now = time.monotonic()
            if now >= next_sample_at:
                current_mem, peak_mem = tracemalloc.get_traced_memory()
                stats = ls.symbol_index.get_stats()
                sample = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "elapsed_sec": round(now - loop_started_mono, 3),
                    "ops": operations,
                    "unique_uris": len(unique_uris),
                    "python_heap_mb": round(current_mem / (1024.0 * 1024.0), 3),
                    "python_heap_peak_mb": round(peak_mem / (1024.0 * 1024.0), 3),
                    "process_maxrss_mb": round(_maxrss_mb(), 3),
                    "threads": threading.active_count(),
                    "doc_cache_size": len(ls._docs),
                    "diag_timer_count": len(ls._diag_timers),
                    "diag_cache_size": len(ls._diag_result_cache),
                    "symbol_count": stats.get("symbol_count", 0),
                    "file_count": stats.get("file_count", 0),
                    "reindex_running": ls._reindex_running,
                    "reindex_pending": ls._reindex_pending,
                }
                samples.append(sample)
                out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                out.flush()
                next_sample_at = now + args.sample_interval_sec

    ls.close()

    first = samples[0] if samples else {}
    last = samples[-1] if samples else {}
    summary = {
        "started_at": started_at_iso,
        "duration_min": args.duration_min,
        "workspace": str(workspace),
        "sampled_files": len(files),
        "operations": operations,
        "samples_count": len(samples),
        "start": first,
        "end": last,
        "drift": {
            "python_heap_mb": round(
                float(last.get("python_heap_mb", 0.0)) - float(first.get("python_heap_mb", 0.0)),
                3,
            ),
            "process_maxrss_mb": round(
                float(last.get("process_maxrss_mb", 0.0))
                - float(first.get("process_maxrss_mb", 0.0)),
                3,
            ),
            "doc_cache_size": int(last.get("doc_cache_size", 0))
            - int(first.get("doc_cache_size", 0)),
            "diag_timer_count": int(last.get("diag_timer_count", 0))
            - int(first.get("diag_timer_count", 0)),
            "diag_cache_size": int(last.get("diag_cache_size", 0))
            - int(first.get("diag_cache_size", 0)),
            "threads": int(last.get("threads", 0)) - int(first.get("threads", 0)),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps({"samples": str(samples_path), "summary": str(summary_path)}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
