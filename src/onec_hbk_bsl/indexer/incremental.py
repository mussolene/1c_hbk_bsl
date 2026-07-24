"""
Incremental BSL workspace indexer.

Uses committed, staged, unstaged and untracked Git deltas to detect changed
files, so only modified .bsl/.os files are re-parsed on each run.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from onec_hbk_bsl.analysis.semantic import extract_semantic_model
from onec_hbk_bsl.indexer.db_path import cleanup_corrupt_index_storage, index_storage_lock
from onec_hbk_bsl.indexer.discovery import is_discovery_dir
from onec_hbk_bsl.indexer.metadata_parser import (
    crawl_config,
    find_config_root,
    find_edt_configuration_marker,
    iter_metadata_input_xmls,
)
from onec_hbk_bsl.indexer.symbol_index import INDEX_POLICY_VERSION, SymbolIndex
from onec_hbk_bsl.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

BSL_EXTENSIONS = {".bsl", ".os"}

# Upper bound for BSL_INDEX_PARSE_WORKERS — each worker holds a Tree-sitter parser
# and parsed AST payloads; unbounded queues previously allowed RAM to grow to 100+ GB
# on 30k+ file workspaces when parsing outran SQLite.
_MAX_PARSE_WORKERS = 32
INDEX_MODES = {"off", "symbols", "full"}


class IndexSizeLimitExceeded(RuntimeError):
    """Raised when a configured persistent-index size budget is exceeded."""


def _split_git_paths(raw: bytes | str) -> list[bytes]:
    """Split NUL-delimited git output, tolerating newline mocks/older callers."""
    value = os.fsencode(raw)
    return [part for part in (value.split(b"\0") if b"\0" in value else value.splitlines()) if part]


def _parse_workers_from_env() -> int:
    raw = os.environ.get("BSL_INDEX_PARSE_WORKERS", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), _MAX_PARSE_WORKERS))
        except ValueError:
            logger.warning("Invalid BSL_INDEX_PARSE_WORKERS=%r — using default", raw)
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu))


class IncrementalIndexer:
    """
    Indexes a BSL workspace into a :class:`SymbolIndex`.

    Args:
        db_path:    Path to the SQLite index database. ``None`` uses the same
            default as :class:`SymbolIndex`.
        index:      Existing SymbolIndex instance (overrides db_path).
        on_progress: Optional callback ``fn(current, total, file_path)`` for progress.
        quiet:      Suppress Rich progress bar output (set True when running inside
            the LSP server's background thread — stdout is the JSON-RPC pipe).
    """

    def __init__(
        self,
        db_path: str | None = None,
        index: SymbolIndex | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        quiet: bool | None = None,
    ) -> None:
        self.index = index or SymbolIndex(db_path=db_path)
        # tree_sitter.Parser is not thread-safe — one BslParser per thread (see _get_parser).
        self._parser_tls = threading.local()
        self._on_progress = on_progress
        # Suppress Rich progress when quiet=True or when BSL_LSP_MODE env is set
        # (LSP stdio mode — stdout is the JSON-RPC pipe, any non-JSON output corrupts it).
        if quiet is None:
            quiet = os.environ.get("BSL_LSP_MODE", "") not in ("", "0", "false")
        self._quiet = quiet
        # Parsing can be parallelized; SQLite writes stay serialized in SymbolIndex.
        self._parse_workers = _parse_workers_from_env()
        # Single-flight guard for background metadata indexing.
        self._metadata_lock = threading.Lock()
        self._metadata_running = False
        self._metadata_pending = False
        self._metadata_pending_workspace: str | None = None
        self._index_mode = self._index_mode_from_env() or "full"

    @staticmethod
    def _index_mode_from_env() -> str | None:
        value = os.environ.get("BSL_INDEX_MODE", "").strip().lower()
        return value if value in INDEX_MODES else None

    def _apply_workspace_settings(self, workspace: str) -> None:
        from onec_hbk_bsl.cli.config import load_config  # noqa: PLC0415

        config = load_config(workspace)
        self._index_mode = self._index_mode_from_env() or config.index_mode
        if "BSL_INDEX_MAX_BYTES" not in os.environ:
            self.index.max_size_bytes = config.index_max_bytes

    def _get_parser(self) -> BslParser:
        """Return a thread-local :class:`BslParser` (required for parallel indexing)."""
        p: BslParser | None = getattr(self._parser_tls, "parser", None)
        if p is None:
            p = BslParser()
            self._parser_tls.parser = p
        return p

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_workspace(self, workspace: str, force: bool = False) -> dict:
        """
        Index (or incrementally update) a BSL workspace.

        Args:
            workspace: Absolute path to the workspace root.
            force:     If True, always perform a full reindex.

        Returns:
            Dict with ``indexed``, ``skipped``, ``errors`` counts.
        """
        workspace = str(Path(workspace).resolve())
        self._apply_workspace_settings(workspace)
        if self._index_mode == "off":
            logger.info("Workspace indexing disabled by index-mode=off")
            return {"indexed": 0, "skipped": 0, "errors": 0, "disabled": True}

        self.index.wait_for_background_migration()
        with index_storage_lock(self.index.db_path) as acquired:
            if not acquired:
                logger.info("Workspace index writer is active in another process; skipping")
                return {"indexed": 0, "skipped": 0, "errors": 0, "locked": True}
            cleanup_corrupt_index_storage(self.index.db_path)
            result = self._index_workspace_locked(workspace, force=force)
            self.index.checkpoint(truncate=True)

        # Metadata uses the same writer lock in its own background pass.
        self._start_metadata_indexing(workspace)
        return result

    def _index_workspace_locked(self, workspace: str, *, force: bool) -> dict:
        """Index a workspace while the caller owns the cross-process writer lock."""
        previous_mode = self.index.get_last_index_mode()
        mode_changed = previous_mode is not None and previous_mode != self._index_mode
        previous_policy = self.index.get_last_index_policy_version()
        policy_changed = previous_policy is not None and previous_policy != INDEX_POLICY_VERSION
        last_commit = (
            None if force or mode_changed or policy_changed else self.index.get_last_commit()
        )
        current_commit = self._get_current_commit(workspace)

        if not force and last_commit:
            files = self.get_changed_files(since_commit=last_commit, workspace=workspace)
            if last_commit == current_commit and not files:
                logger.info(
                    "Index and worktree are up-to-date at %s. Nothing to do.", current_commit[:8]
                )
                return {"indexed": 0, "skipped": 0, "errors": 0}
            logger.info(
                "Incremental index: %d committed or worktree files since %s",
                len(files),
                last_commit[:8],
            )
        else:
            files = self._find_all_bsl_files(workspace)
            logger.info("Full index: %d BSL files in %s", len(files), workspace)

        result = self._index_files(files, workspace, prune_missing=last_commit is None)

        if current_commit:
            self.index.save_commit(
                current_commit, workspace_root=workspace, index_mode=self._index_mode
            )

        return result

    def index_metadata(
        self, workspace: str, config_root: str | None = None, *, force: bool = False
    ) -> dict:
        """
        Find and index 1C configuration metadata (XML export) within *workspace*.

        Returns:
            Dict with ``objects`` and ``members`` counts, or ``{"skipped": True}`` if no config found.
        """
        workspace = str(Path(workspace).resolve())
        self._apply_workspace_settings(workspace)
        if self._index_mode == "off":
            return {"skipped": True, "reason": "index_disabled"}
        self.index.wait_for_background_migration()
        with index_storage_lock(self.index.db_path) as acquired:
            if not acquired:
                return {"skipped": True, "reason": "writer_locked"}
            return self._index_metadata_locked(workspace, config_root, force=force)

    def _index_metadata_locked(
        self, workspace: str, config_root: str | None = None, *, force: bool = False
    ) -> dict:
        resolved_config_root = (
            Path(config_root).resolve() if config_root else find_config_root(workspace)
        )
        if resolved_config_root is None:
            edt_mdo = find_edt_configuration_marker(workspace)
            if edt_mdo is not None:
                logger.debug(
                    "EDT project marker found at %s — XML crawl not applicable; export to files first",
                    edt_mdo,
                )
                return {
                    "skipped": True,
                    "reason": "edt_layout_detected",
                    "edt_configuration_mdo": str(edt_mdo),
                }
            logger.debug("No 1C config root found in %s — skipping metadata indexing", workspace)
            return {"skipped": True}

        config_root = str(resolved_config_root)
        fingerprint = self._metadata_fingerprint(config_root)
        if not force:
            cached_state = self.index.get_metadata_state(config_root)
            if cached_state is not None and cached_state.get("fingerprint") == fingerprint:
                logger.debug("Metadata index is up-to-date for %s", config_root)
                return {
                    "objects": int(cached_state.get("object_count") or 0),
                    "members": int(cached_state.get("member_count") or 0),
                    "skipped": True,
                    "reason": "metadata_unchanged",
                }

        logger.info("Indexing 1C metadata from %s", config_root)
        try:
            meta_objects = crawl_config(config_root)
            total_members = self.index.upsert_metadata(meta_objects)
            self.index.save_metadata_state(
                config_root=config_root,
                fingerprint=fingerprint,
                object_count=len(meta_objects),
                member_count=total_members,
            )
            logger.info(
                "Metadata indexed: %d objects, %d members",
                len(meta_objects),
                total_members,
            )
            return {"objects": len(meta_objects), "members": total_members}
        except Exception as exc:
            logger.error("Metadata indexing failed: %s", exc)
            return {"objects": 0, "members": 0, "error": str(exc)}

    @staticmethod
    def _metadata_fingerprint(config_root: str) -> str:
        """
        Return a cheap fingerprint for Designer XML metadata inputs.

        Uses relative XML paths plus size and nanosecond mtime. This avoids parsing
        10k+ XML files on every LSP/index warm path while still invalidating when
        the exported metadata tree changes.
        """
        root = Path(config_root)
        digest = hashlib.blake2b(digest_size=20)

        for xml_file in iter_metadata_input_xmls(root):
            IncrementalIndexer._fingerprint_file(digest, root, xml_file)
        return digest.hexdigest()

    @staticmethod
    def _fingerprint_file(digest: Any, root: Path, path: Path) -> None:
        try:
            stat = path.stat()
        except OSError:
            return
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b":")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\n")

    def _start_metadata_indexing(self, workspace: str) -> None:
        """Start metadata indexing with single-flight + pending coalescing."""
        workspace = str(Path(workspace).resolve())
        with self._metadata_lock:
            if self._metadata_running:
                self._metadata_pending = True
                self._metadata_pending_workspace = workspace
                logger.debug("Metadata indexing already running; marked pending for %s", workspace)
                return
            self._metadata_running = True
            self._metadata_pending = False
            self._metadata_pending_workspace = None

        def _worker(initial_workspace: str) -> None:
            current_workspace = initial_workspace
            try:
                while True:
                    self.index_metadata(current_workspace)
                    with self._metadata_lock:
                        if self._metadata_pending:
                            self._metadata_pending = False
                            current_workspace = (
                                self._metadata_pending_workspace or current_workspace
                            )
                            self._metadata_pending_workspace = None
                            continue
                        self._metadata_running = False
                        break
            finally:
                with self._metadata_lock:
                    if self._metadata_running and not self._metadata_pending:
                        self._metadata_running = False

        threading.Thread(
            target=_worker,
            args=(workspace,),
            daemon=True,
            name="bsl-metadata-index",
        ).start()

    def get_changed_files(self, since_commit: str, workspace: str) -> list[str]:
        """
        Return absolute paths of .bsl/.os files changed since *since_commit*.

        Combines committed, staged, unstaged and untracked paths. Rename
        detection is disabled so both the deleted old path and added new path
        enter the update set.
        Falls back to full scan if git is unavailable.
        """
        from onec_hbk_bsl.cli.config import load_config  # noqa: PLC0415

        try:
            commands = (
                (
                    "committed",
                    [
                        "git",
                        "diff",
                        "--name-only",
                        "--no-renames",
                        "-z",
                        since_commit,
                        "HEAD",
                        "--",
                    ],
                ),
                (
                    "staged",
                    [
                        "git",
                        "diff",
                        "--cached",
                        "--name-only",
                        "--no-renames",
                        "-z",
                        "--",
                    ],
                ),
                (
                    "unstaged",
                    [
                        "git",
                        "diff",
                        "--name-only",
                        "--no-renames",
                        "-z",
                        "--",
                    ],
                ),
                (
                    "untracked",
                    ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
                ),
            )
            raw_paths = b""
            for delta_kind, command in commands:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    cwd=workspace,
                    timeout=30,
                )
                if result.returncode != 0:
                    logger.warning(
                        "git %s delta failed (rc=%d): %s. Falling back to full scan.",
                        delta_kind,
                        result.returncode,
                        os.fsdecode(result.stderr).strip(),
                    )
                    return self._find_all_bsl_files(workspace)
                raw_paths += os.fsencode(result.stdout)

            config = load_config(workspace)
            changed: set[str] = set()
            for raw_path in _split_git_paths(raw_paths):
                rel_path = os.fsdecode(raw_path)
                abs_path = str((Path(workspace) / rel_path).resolve())
                if Path(rel_path).suffix.lower() in BSL_EXTENSIONS and not config.is_index_excluded(
                    abs_path
                ):
                    changed.add(abs_path)
            return sorted(changed)

        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("git not available (%s). Falling back to full scan.", exc)
            return self._find_all_bsl_files(workspace)

    def index_file(self, path: str) -> dict:
        """
        Parse a single BSL file and upsert it into the index.

        Returns:
            Dict with ``symbols`` and ``calls`` counts, plus ``error`` if failed.
        """
        self._apply_workspace_settings(str(Path(path).resolve().parent))
        if self._index_mode == "off":
            return {"symbols": 0, "calls": 0, "disabled": True}
        self.index.wait_for_background_migration()
        with index_storage_lock(self.index.db_path) as acquired:
            if not acquired:
                return {"symbols": 0, "calls": 0, "locked": True}
            return self._index_file_locked(path)

    def _index_file_locked(self, path: str) -> dict:
        try:
            parsed = self._parse_file(path)
            if "error" in parsed:
                return {"symbols": 0, "calls": 0, "error": parsed["error"]}
            sym_dicts = parsed["symbols"]
            call_dicts = parsed["calls"]
            self.index.upsert_file(path, sym_dicts, call_dicts)
            return {"symbols": len(sym_dicts), "calls": len(call_dicts)}

        except Exception as exc:
            logger.error("Failed to index %s: %s", path, exc)
            return {"symbols": 0, "calls": 0, "error": str(exc)}

    def index_snapshot(self, path: str, snapshot: Any) -> dict:
        """
        Upsert index data from an already parsed document snapshot.

        This is the LSP hot path: diagnostics already materialize a DocumentSnapshot,
        so re-reading and re-parsing the same open file on save wastes time.
        """
        self._apply_workspace_settings(str(Path(path).resolve().parent))
        if self._index_mode == "off":
            return {"symbols": 0, "calls": 0, "disabled": True}
        self.index.wait_for_background_migration()
        with index_storage_lock(self.index.db_path) as acquired:
            if not acquired:
                return {"symbols": 0, "calls": 0, "locked": True}
            return self._index_snapshot_locked(path, snapshot)

    def _index_snapshot_locked(self, path: str, snapshot: Any) -> dict:
        try:
            semantic = extract_semantic_model(snapshot.tree, file_path=path)
            sym_dicts = [_symbol_to_dict(s) for s in semantic.symbols]
            call_dicts = (
                [_call_to_dict(c) for c in semantic.calls] if self._index_mode == "full" else []
            )
            self.index.upsert_file(path, sym_dicts, call_dicts)
            return {"symbols": len(sym_dicts), "calls": len(call_dicts)}
        except Exception as exc:
            logger.error("Failed to index snapshot %s: %s", path, exc)
            return {"symbols": 0, "calls": 0, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index_files(
        self, files: list[str], workspace: str, *, prune_missing: bool = False
    ) -> dict:
        indexed = 0
        skipped = 0
        errors = 0
        pruned = 0

        bulk_enabled = os.environ.get("BSL_INDEX_SQLITE_BULK", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        bulk_ctx = self.index.bulk_write if bulk_enabled and len(files) > 0 else nullcontext

        progress_ctx = (
            nullcontext()
            if self._quiet
            else Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                transient=True,
            )
        )
        with progress_ctx as progress:
            task = (
                None
                if progress is None
                else progress.add_task("Indexing BSL files", total=len(files))
            )
            with bulk_ctx():
                if prune_missing:
                    eligible = {str(Path(path).resolve()) for path in files}
                    workspace_path = Path(workspace).resolve()
                    stale = {
                        path
                        for path in self.index.get_indexed_files()
                        if Path(path).is_relative_to(workspace_path)
                        and str(Path(path).resolve()) not in eligible
                    }
                    for path in stale:
                        self.index.remove_file(path)
                    pruned = len(stale)

                existing: list[str] = []
                for path in files:
                    if not Path(path).exists():
                        # File was deleted — remove from index
                        self.index.remove_file(path)
                        skipped += 1
                        if self._on_progress:
                            self._on_progress(indexed + skipped + errors, len(files), path)
                        if progress is not None:
                            progress.advance(task)
                        continue
                    existing.append(path)

                if self._parse_workers <= 1 or len(existing) <= 1:
                    # Sequential mode.
                    for path in existing:
                        if progress is not None:
                            progress.update(task, description=f"[bold blue]{Path(path).name}")
                        parsed = self._parse_file(path)
                        if "error" in parsed:
                            errors += 1
                        else:
                            self.index.upsert_file(path, parsed["symbols"], parsed["calls"])
                            indexed += 1
                            if indexed % 100 == 0:
                                self._enforce_size_limit()
                        if self._on_progress:
                            self._on_progress(indexed + skipped + errors, len(files), path)
                        if progress is not None:
                            progress.advance(task)
                else:
                    # Parallel parse with daemon workers to avoid stop-timeout regressions
                    # during LSP process shutdown.
                    work_q: Queue[str] = Queue()
                    worker_count = min(self._parse_workers, len(existing))
                    # Bound backpressure: main thread serializes SQLite writes; without a
                    # maxsize, producers could queue tens of thousands of parsed trees in RAM.
                    out_max = max(8, worker_count * 2)
                    out_q: Queue[tuple[str, dict[str, Any]]] = Queue(maxsize=out_max)
                    for path in existing:
                        work_q.put(path)

                    def _worker() -> None:
                        while True:
                            try:
                                p = work_q.get_nowait()
                            except Empty:
                                return
                            try:
                                out_q.put((p, self._parse_file(p)))
                            finally:
                                work_q.task_done()

                    workers: list[threading.Thread] = []
                    for i in range(worker_count):
                        t = threading.Thread(
                            target=_worker,
                            daemon=True,
                            name=f"bsl-index-parse-{i + 1}",
                        )
                        t.start()
                        workers.append(t)

                    processed = 0
                    while processed < len(existing):
                        path, parsed = out_q.get()
                        if progress is not None:
                            progress.update(task, description=f"[bold blue]{Path(path).name}")
                        if "error" in parsed:
                            errors += 1
                        else:
                            self.index.upsert_file(path, parsed["symbols"], parsed["calls"])
                            indexed += 1
                            if indexed % 100 == 0:
                                self._enforce_size_limit()

                        if self._on_progress:
                            self._on_progress(indexed + skipped + errors, len(files), path)
                        if progress is not None:
                            progress.advance(task)
                        processed += 1

                    for t in workers:
                        t.join(timeout=0.1)

                self._enforce_size_limit()

        logger.info(
            "Indexing complete: %d indexed, %d skipped, %d pruned, %d errors",
            indexed,
            skipped,
            pruned,
            errors,
        )
        return {"indexed": indexed, "skipped": skipped, "pruned": pruned, "errors": errors}

    def _enforce_size_limit(self) -> None:
        limit = self.index.max_size_bytes
        if not limit:
            return
        size = self.index._index_size_stats()["index_size_bytes"]
        if size > limit:
            raise IndexSizeLimitExceeded(
                f"Index size {size} bytes exceeds configured limit {limit} bytes"
            )

    def _parse_file(self, path: str) -> dict[str, Any]:
        """Parse one file and return prepared symbol/call dict lists."""
        try:
            tree = self._get_parser().parse_file(path)
            semantic = extract_semantic_model(tree, file_path=path)
            return {
                "symbols": [_symbol_to_dict(s) for s in semantic.symbols],
                "calls": (
                    [_call_to_dict(c) for c in semantic.calls] if self._index_mode == "full" else []
                ),
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    @staticmethod
    def _find_all_bsl_files(workspace: str) -> list[str]:
        """Return tracked and non-ignored BSL sources, applying index excludes."""
        from onec_hbk_bsl.cli.config import load_config  # noqa: PLC0415

        root = os.path.abspath(workspace)
        config = load_config(root)

        try:
            result = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "-co",
                    "--exclude-standard",
                    "-z",
                    "--",
                    "*.bsl",
                    "*.os",
                ],
                capture_output=True,
                cwd=root,
                timeout=60,
            )
            if result.returncode == 0:
                git_files = {
                    str((Path(root) / os.fsdecode(raw_path)).resolve())
                    for raw_path in _split_git_paths(result.stdout)
                }
                return sorted(path for path in git_files if not config.is_index_excluded(path))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Non-git fallback: retain the existing filesystem walk, but honor config excludes.
        result: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [name for name in dirnames if is_discovery_dir(name)]
            for name in filenames:
                suf = Path(name).suffix.lower()
                if suf in BSL_EXTENSIONS:
                    path = os.path.join(dirpath, name)
                    if not config.is_index_excluded(path):
                        result.append(path)
        result.sort()
        return result

    @staticmethod
    def _get_current_commit(workspace: str) -> str | None:
        """Return current HEAD commit hash, or None if not a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=workspace,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None


# ---------------------------------------------------------------------------
# Helper converters
# ---------------------------------------------------------------------------


def _symbol_to_dict(symbol: Any) -> dict:  # noqa: ANN401
    """Convert a Symbol dataclass to a plain dict for the index."""
    return {
        "name": symbol.name,
        "line": symbol.line,
        "character": symbol.character,
        "end_line": symbol.end_line,
        "end_character": symbol.end_character,
        "kind": symbol.kind,
        "is_export": symbol.is_export,
        "container": symbol.container,
        "signature": symbol.signature,
        "doc_comment": symbol.doc_comment,
    }


def _call_to_dict(call: Any) -> dict:  # noqa: ANN401
    """Convert a Call dataclass to a plain dict for the index."""
    return {
        "caller_line": call.caller_line,
        "caller_character": getattr(call, "caller_character", 0),
        "caller_name": call.caller_name,
        "callee_name": call.callee_name,
        "callee_args_count": call.callee_args_count,
        "receiver_expression": getattr(call, "receiver_expression", None),
    }
