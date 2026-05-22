from __future__ import annotations

import threading
from typing import Any


class DiagnosticRun:
    """Single-flight state for one diagnostics computation."""

    def __init__(self, content_hash: int) -> None:
        self.content_hash = content_hash
        self.event = threading.Event()
        self.diagnostics: list[Any] | None = None
        self.error: BaseException | None = None


class DocumentDiagnosticsState:
    """Owns mutable per-document LSP state with thread-safe accessors."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.docs: dict[str, str] = {}
        self.diag_timers: dict[str, threading.Timer] = {}
        self.diag_last_time: dict[str, float] = {}
        self.diag_result_cache: dict[str, tuple[int, list[Any]]] = {}
        self.diag_inflight: dict[str, DiagnosticRun] = {}
        self.indexed_snapshot_cache: dict[str, int] = {}

    def get_doc(self, uri: str, default: str | None = None) -> str | None:
        with self.lock:
            if default is None:
                return self.docs.get(uri)
            return self.docs.get(uri, default)

    def set_doc(self, uri: str, text: str) -> None:
        with self.lock:
            self.docs[uri] = text

    def pop_timer(self, uri: str) -> threading.Timer | None:
        with self.lock:
            return self.diag_timers.pop(uri, None)

    def set_timer(self, uri: str, timer: threading.Timer) -> None:
        with self.lock:
            self.diag_timers[uri] = timer

    def clear_cache_for_uri(self, uri: str) -> None:
        with self.lock:
            self.diag_result_cache.pop(uri, None)
            self.indexed_snapshot_cache.pop(uri, None)

    def get_last_diag_time(self, uri: str) -> float:
        with self.lock:
            return self.diag_last_time.get(uri, 0.0)

    def set_last_diag_time(self, uri: str, seconds: float) -> None:
        with self.lock:
            self.diag_last_time[uri] = seconds

    def get_diag_cache(self, uri: str) -> tuple[int, list[Any]] | None:
        with self.lock:
            return self.diag_result_cache.get(uri)

    def set_diag_cache(self, uri: str, content_hash: int, diagnostics: list[Any]) -> None:
        with self.lock:
            self.diag_result_cache[uri] = (content_hash, diagnostics)

    def begin_diag_run(self, uri: str, content_hash: int) -> tuple[str, DiagnosticRun | None]:
        """Return whether caller should run, wait, or use cached diagnostics."""
        with self.lock:
            cached = self.diag_result_cache.get(uri)
            if cached is not None and cached[0] == content_hash:
                return "cached", None
            current = self.diag_inflight.get(uri)
            if current is not None and current.content_hash == content_hash:
                return "wait", current
            run = DiagnosticRun(content_hash)
            self.diag_inflight[uri] = run
            return "run", run

    def finish_diag_run(
        self,
        uri: str,
        run: DiagnosticRun,
        diagnostics: list[Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Complete a single-flight diagnostics run and wake waiters."""
        with self.lock:
            if self.diag_inflight.get(uri) is run:
                self.diag_inflight.pop(uri, None)
            run.diagnostics = diagnostics
            run.error = error
            if diagnostics is not None and error is None:
                self.diag_result_cache[uri] = (run.content_hash, diagnostics)
            run.event.set()

    def mark_snapshot_indexed(self, uri: str, content_hash: int) -> bool:
        """Return True when this content hash has not been indexed yet."""
        with self.lock:
            if self.indexed_snapshot_cache.get(uri) == content_hash:
                return False
            self.indexed_snapshot_cache[uri] = content_hash
            return True

    def close_document(self, uri: str) -> threading.Timer | None:
        with self.lock:
            timer = self.diag_timers.pop(uri, None)
            self.docs.pop(uri, None)
            self.diag_last_time.pop(uri, None)
            self.diag_result_cache.pop(uri, None)
            self.diag_inflight.pop(uri, None)
            self.indexed_snapshot_cache.pop(uri, None)
            return timer
