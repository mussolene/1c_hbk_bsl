from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, order=True, slots=True)
class WorkspaceId:
    """Canonical identity of one workspace root."""

    root: str

    @classmethod
    def from_root(cls, root: str) -> WorkspaceId:
        return cls(str(Path(root).resolve()))


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

    def __init__(self, cache_key: Any, generation: int) -> None:
        self.cache_key = cache_key
        self.generation = generation
        self.event = threading.Event()
        self.diagnostics: list[Any] | None = None
        self.error: BaseException | None = None
        self.committed = False


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
        self._retired = False

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
            return (
                not self._retired
                and context.symbol_index is self._symbol_index
                and context.revisions == self._revisions
            )

    def run_if_current(
        self,
        context: WorkspaceRunContext,
        action: Callable[[], bool],
    ) -> bool:
        """Run an update while the complete workspace context is still current."""
        with self._lock:
            if (
                self._retired
                or context.symbol_index is not self._symbol_index
                or context.revisions != self._revisions
            ):
                return False
            return action()

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
            if self._retired or expected_index is not self._symbol_index:
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

    def replace_diagnostics_engine(self, diagnostics_engine: Any) -> WorkspaceRunContext:
        """Atomically publish diagnostics configured for the current workspace."""
        with self._lock:
            diagnostics_engine._symbol_index = self._symbol_index
            self._diagnostics_engine = diagnostics_engine
            self._revisions = WorkspaceRevisions(
                index=self._revisions.index,
                metadata=self._revisions.metadata,
                config=self._revisions.config + 1,
            )
            context = self.snapshot()
        self._invalidate_caches("config")
        return context

    def close(self) -> None:
        with self._lock:
            self._retired = True
            current = self._symbol_index
        self._close_index_once(current)

    def _close_index_once(self, index: Any) -> None:
        with self._lock:
            if any(closed is index for closed in self._closed_indexes):
                return
            self._closed_indexes.append(index)
        index.close()


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    """Services and root-local configuration owned by one workspace."""

    workspace_id: WorkspaceId
    state: WorkspaceState
    config: Any
    index_mode: str


class WorkspaceRegistry:
    """Thread-safe multi-root ownership and lifecycle registry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[WorkspaceId, WorkspaceEntry] = {}

    def add(self, entry: WorkspaceEntry) -> None:
        with self._lock:
            if entry.workspace_id in self._entries:
                raise ValueError(f"workspace root already registered: {entry.workspace_id.root}")
            self._entries[entry.workspace_id] = entry

    def remove(self, workspace_id: WorkspaceId) -> WorkspaceEntry:
        with self._lock:
            try:
                entry = self._entries.pop(workspace_id)
            except KeyError as exc:
                raise KeyError(f"workspace root is not registered: {workspace_id.root}") from exc
        entry.state.close()
        return entry

    def get(self, workspace_id: WorkspaceId) -> WorkspaceEntry:
        with self._lock:
            try:
                return self._entries[workspace_id]
            except KeyError as exc:
                raise KeyError(f"workspace root is not registered: {workspace_id.root}") from exc

    def entries(self) -> tuple[WorkspaceEntry, ...]:
        with self._lock:
            return tuple(self._entries[workspace_id] for workspace_id in sorted(self._entries))

    def owner_for_path(self, path: str) -> WorkspaceEntry:
        """Return the deepest containing root; reject missing or ambiguous owners."""
        candidate_path = Path(path).resolve()
        with self._lock:
            matches = [
                entry
                for entry in self._entries.values()
                if candidate_path == Path(entry.workspace_id.root)
                or Path(entry.workspace_id.root) in candidate_path.parents
            ]
        if not matches:
            raise ValueError(f"path is outside registered workspace roots: {candidate_path}")
        depth = max(len(Path(entry.workspace_id.root).parts) for entry in matches)
        owners = [entry for entry in matches if len(Path(entry.workspace_id.root).parts) == depth]
        if len(owners) != 1:
            roots = ", ".join(sorted(entry.workspace_id.root for entry in owners))
            raise ValueError(f"ambiguous workspace ownership for {candidate_path}: {roots}")
        return owners[0]

    def close(self) -> None:
        with self._lock:
            entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in entries:
            entry.state.close()


class DocumentDiagnosticsState:
    """Owns mutable per-document LSP state with thread-safe accessors."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.docs: dict[str, str] = {}
        self.doc_generations: dict[str, int] = {}
        self.diag_timers: dict[str, threading.Timer] = {}
        self.diag_last_time: dict[str, float] = {}
        self.diag_result_cache: dict[str, tuple[Any, list[Any]]] = {}
        self.diag_inflight: dict[str, DiagnosticRun] = {}
        self.indexed_snapshot_cache: dict[str, tuple[int, int]] = {}
        self.published_diagnostics: dict[str, tuple[int, Any]] = {}

    def get_doc(self, uri: str, default: str | None = None) -> str | None:
        with self.lock:
            if default is None:
                return self.docs.get(uri)
            return self.docs.get(uri, default)

    def get_doc_snapshot(self, uri: str) -> tuple[str | None, int]:
        """Return document text and its generation from one locked snapshot."""
        with self.lock:
            return self.docs.get(uri), self.doc_generations.get(uri, 0)

    def set_doc(self, uri: str, text: str) -> int:
        """Store text and advance the monotonic generation for this URI."""
        with self.lock:
            self.docs[uri] = text
            generation = self.doc_generations.get(uri, 0) + 1
            self.doc_generations[uri] = generation
            return generation

    def open_uris(self) -> tuple[str, ...]:
        with self.lock:
            return tuple(self.docs)

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

    def begin_diag_run(
        self,
        uri: str,
        cache_key: Any,
        generation: int | None = None,
    ) -> tuple[str, DiagnosticRun | None]:
        """Return whether caller should run, wait, use cache, or discard stale work."""
        with self.lock:
            current_generation = self.doc_generations.get(uri, 0)
            if generation is None:
                generation = current_generation
            if generation != current_generation:
                return "stale", None
            cached = self.diag_result_cache.get(uri)
            if cached is not None and cached[0] == cache_key:
                return "cached", None
            current = self.diag_inflight.get(uri)
            if (
                current is not None
                and current.cache_key == cache_key
                and current.generation == generation
            ):
                return "wait", current
            run = DiagnosticRun(cache_key, generation)
            self.diag_inflight[uri] = run
            return "run", run

    def finish_diag_run(
        self,
        uri: str,
        run: DiagnosticRun,
        diagnostics: list[Any] | None = None,
        error: BaseException | None = None,
        *,
        workspace_is_current: bool = True,
    ) -> bool:
        """CAS-complete a diagnostics run and wake waiters."""
        with self.lock:
            committed = (
                self.diag_inflight.get(uri) is run
                and self.doc_generations.get(uri, 0) == run.generation
                and workspace_is_current
            )
            if self.diag_inflight.get(uri) is run:
                self.diag_inflight.pop(uri, None)
            run.diagnostics = diagnostics
            run.error = error
            run.committed = committed
            if committed and diagnostics is not None and error is None:
                self.diag_result_cache[uri] = (run.cache_key, diagnostics)
            run.event.set()
            return committed

    def clear_semantic_caches(self, *, clear_indexed_snapshots: bool = False) -> None:
        """Invalidate results derived from workspace index, metadata, or config."""
        with self.lock:
            self.diag_result_cache.clear()
            if clear_indexed_snapshots:
                self.indexed_snapshot_cache.clear()

    def index_if_current(
        self,
        uri: str,
        generation: int,
        content_hash: int,
        action: Callable[[], None],
    ) -> bool:
        """Run one index update only while its document generation is current."""
        with self.lock:
            if self.doc_generations.get(uri, 0) != generation:
                return False
            current = self.docs.get(uri)
            if current is not None and hash(current) != content_hash:
                return False
            identity = (generation, content_hash)
            if self.indexed_snapshot_cache.get(uri) == identity:
                return False
            action()
            self.indexed_snapshot_cache[uri] = identity
            return True

    def publish_if_current(
        self,
        uri: str,
        generation: int,
        cache_key: Any,
        action: Callable[[], None],
    ) -> bool:
        """Publish a diagnostic identity once while its generation is current."""
        with self.lock:
            if self.doc_generations.get(uri, 0) != generation:
                return False
            identity = (generation, cache_key)
            if self.published_diagnostics.get(uri) == identity:
                return False
            action()
            self.published_diagnostics[uri] = identity
            return True

    def close_document(self, uri: str) -> threading.Timer | None:
        with self.lock:
            timer = self.diag_timers.pop(uri, None)
            self.docs.pop(uri, None)
            self.doc_generations.pop(uri, None)
            self.diag_last_time.pop(uri, None)
            self.diag_result_cache.pop(uri, None)
            self.diag_inflight.pop(uri, None)
            self.indexed_snapshot_cache.pop(uri, None)
            self.published_diagnostics.pop(uri, None)
            return timer
