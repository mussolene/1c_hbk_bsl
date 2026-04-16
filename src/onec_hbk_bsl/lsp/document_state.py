from __future__ import annotations

import threading
from typing import Any


class DocumentDiagnosticsState:
    """Owns mutable per-document LSP state with thread-safe accessors."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.docs: dict[str, str] = {}
        self.diag_timers: dict[str, threading.Timer] = {}
        self.diag_last_time: dict[str, float] = {}
        self.diag_result_cache: dict[str, tuple[int, list[Any]]] = {}

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

    def close_document(self, uri: str) -> threading.Timer | None:
        with self.lock:
            timer = self.diag_timers.pop(uri, None)
            self.docs.pop(uri, None)
            self.diag_last_time.pop(uri, None)
            self.diag_result_cache.pop(uri, None)
            return timer
