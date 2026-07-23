from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkspaceRevisions:
    """Monotonic semantic-input revisions for one workspace."""

    index: int
    metadata: int
    config: int


@dataclass(frozen=True, slots=True)
class WorkspaceRunContext:
    """Immutable view of services and revisions used by one LSP operation."""

    symbol_index: Any
    indexer: Any
    diagnostics_engine: Any
    revisions: WorkspaceRevisions


@dataclass(frozen=True, slots=True)
class DiagnosticCacheKey:
    """Document content plus every workspace input that can affect diagnostics."""

    content_hash: int
    revisions: WorkspaceRevisions


class DiagnosticRun:
    """Single-flight state for one diagnostics computation."""

    def __init__(self, cache_key: Any) -> None:
        self.cache_key = cache_key
        self.event = threading.Event()
        self.diagnostics: list[Any] | None = None
        self.error: BaseException | None = None


class WorkspaceState:
    """Own the current workspace services and their semantic revisions."""

    def __init__(
        self,
        *,
        symbol_index: Any,
        indexer: Any,
        diagnostics_engine: Any,
        invalidate_caches: Callable[[str], None],
    ) -> None:
        self._lock = threading.RLock()
        self._symbol_index = symbol_index
        self._indexer = indexer
        self._diagnostics_engine = diagnostics_engine
        self._revisions = WorkspaceRevisions(index=1, metadata=1, config=1)
        self._invalidate_caches = invalidate_caches
        self._closed_indexes: list[Any] = []

    def snapshot(self) -> WorkspaceRunContext:
        with self._lock:
            return WorkspaceRunContext(
                symbol_index=self._symbol_index,
                indexer=self._indexer,
                diagnostics_engine=self._diagnostics_engine,
                revisions=self._revisions,
            )

    def is_current(self, context: WorkspaceRunContext) -> bool:
        with self._lock:
            return context.symbol_index is self._symbol_index

    def replace_index(self, *, symbol_index: Any, indexer: Any) -> WorkspaceRunContext:
        """Atomically publish a new index and retire the old instance once."""
        old_index: Any | None = None
        with self._lock:
            if symbol_index is self._symbol_index:
                self._indexer = indexer
                self._diagnostics_engine._symbol_index = symbol_index
                return self.snapshot()
            old_index = self._symbol_index
            self._symbol_index = symbol_index
            self._indexer = indexer
            self._diagnostics_engine._symbol_index = symbol_index
            self._revisions = WorkspaceRevisions(
                index=self._revisions.index + 1,
                metadata=self._revisions.metadata + 1,
                config=self._revisions.config,
            )
            context = self.snapshot()
        try:
            self._invalidate_caches("replace")
        finally:
            self._close_index_once(old_index)
        return context

    def mark_index_changed(
        self,
        *,
        expected_index: Any,
        metadata_changed: bool = False,
    ) -> WorkspaceRevisions | None:
        """Advance revisions only when the writer still targets the current index."""
        with self._lock:
            if expected_index is not self._symbol_index:
                return None
            self._revisions = WorkspaceRevisions(
                index=self._revisions.index + 1,
                metadata=self._revisions.metadata + int(metadata_changed),
                config=self._revisions.config,
            )
            revisions = self._revisions
        self._invalidate_caches("metadata" if metadata_changed else "index")
        return revisions

    def mark_config_changed(self) -> WorkspaceRevisions:
        with self._lock:
            self._revisions = WorkspaceRevisions(
                index=self._revisions.index,
                metadata=self._revisions.metadata,
                config=self._revisions.config + 1,
            )
            revisions = self._revisions
        self._invalidate_caches("config")
        return revisions

    def close(self) -> None:
        with self._lock:
            current = self._symbol_index
        self._close_index_once(current)

    def _close_index_once(self, index: Any) -> None:
        with self._lock:
            if any(closed is index for closed in self._closed_indexes):
                return
            self._closed_indexes.append(index)
        index.close()


class DocumentDiagnosticsState:
    """Owns mutable per-document LSP state with thread-safe accessors."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.docs: dict[str, str] = {}
        self.diag_timers: dict[str, threading.Timer] = {}
        self.diag_last_time: dict[str, float] = {}
        self.diag_result_cache: dict[str, tuple[Any, list[Any]]] = {}
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

    def get_diag_cache(self, uri: str) -> tuple[Any, list[Any]] | None:
        with self.lock:
            return self.diag_result_cache.get(uri)

    def set_diag_cache(self, uri: str, cache_key: Any, diagnostics: list[Any]) -> None:
        with self.lock:
            self.diag_result_cache[uri] = (cache_key, diagnostics)

    def begin_diag_run(self, uri: str, cache_key: Any) -> tuple[str, DiagnosticRun | None]:
        """Return whether caller should run, wait, or use cached diagnostics."""
        with self.lock:
            cached = self.diag_result_cache.get(uri)
            if cached is not None and cached[0] == cache_key:
                return "cached", None
            current = self.diag_inflight.get(uri)
            if current is not None and current.cache_key == cache_key:
                return "wait", current
            run = DiagnosticRun(cache_key)
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
                self.diag_result_cache[uri] = (run.cache_key, diagnostics)
            run.event.set()

    def clear_semantic_caches(self, *, clear_indexed_snapshots: bool = False) -> None:
        """Invalidate results derived from workspace index, metadata, or config."""
        with self.lock:
            self.diag_result_cache.clear()
            if clear_indexed_snapshots:
                self.indexed_snapshot_cache.clear()

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
