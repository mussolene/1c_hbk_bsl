#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import resource
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

from onec_hbk_bsl.lsp.server import (
    BslLanguageServer,
    on_did_change,
    on_did_close,
    on_did_open,
    on_document_diagnostic,
)


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
    parser.add_argument("--workspace", required=True, help="Workspace root with .bsl files.")
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
        default=".agent/reports/lsp-soak",
        help="Directory for JSONL samples and summary JSON.",
    )
    args = parser.parse_args()

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
