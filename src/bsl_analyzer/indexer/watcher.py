"""
Live file watcher for BSL workspaces.

Uses ``watchfiles`` to detect .bsl/.os changes and triggers incremental
re-indexing via a debounced callback.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

BSL_EXTENSIONS = {".bsl", ".os"}
DEBOUNCE_SECONDS = 0.5  # Batch rapid saves within this window


class FileWatcher:
    """
    Watches a workspace for .bsl/.os file changes and calls *callback*.

    The callback receives a list of absolute file paths that changed.
    Changes are debounced (batched) within a 500ms window so that rapid
    multi-file saves (e.g. after a git checkout) are coalesced.

    Args:
        debounce: Debounce interval in seconds (default: 0.5).

    Example::

        def on_change(paths):
            indexer.index_files(paths)

        watcher = FileWatcher()
        watcher.watch("/path/to/workspace", on_change)  # blocks
    """

    def __init__(self, debounce: float = DEBOUNCE_SECONDS) -> None:
        self.debounce = debounce
        self._stop_event = threading.Event()
        self._pending: set[str] = set()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def watch(self, workspace: str, callback: Callable[[list[str]], None]) -> None:
        """
        Start watching *workspace* for BSL file changes.

        This method **blocks** until :meth:`stop` is called or a
        ``KeyboardInterrupt`` / ``SystemExit`` is raised.

        Args:
            workspace: Absolute path to the directory to watch.
            callback:  Called with a list of changed file paths.
        """
        try:
            from watchfiles import watch as wf_watch, Change
        except ImportError:
            logger.error(
                "watchfiles is not installed. "
                "Install with: pip install watchfiles"
            )
            return

        logger.info("Watching %s for BSL file changes…", workspace)
        self._stop_event.clear()

        try:
            for changes in wf_watch(workspace, stop_event=self._stop_event):
                changed_paths: list[str] = []
                for change_type, path in changes:
                    if Path(path).suffix.lower() in BSL_EXTENSIONS:
                        changed_paths.append(path)

                if changed_paths:
                    self._schedule_callback(changed_paths, callback)

        except KeyboardInterrupt:
            logger.info("File watcher stopped by user.")
        finally:
            self._cancel_pending()

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()
        self._cancel_pending()

    # ------------------------------------------------------------------
    # Debounce logic
    # ------------------------------------------------------------------

    def _schedule_callback(
        self,
        paths: list[str],
        callback: Callable[[list[str]], None],
    ) -> None:
        with self._lock:
            self._pending.update(paths)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(
                self.debounce,
                self._fire_callback,
                args=(callback,),
            )
            self._timer.daemon = True
            self._timer.start()

    def _fire_callback(self, callback: Callable[[list[str]], None]) -> None:
        with self._lock:
            paths = list(self._pending)
            self._pending.clear()
            self._timer = None

        if paths:
            logger.debug("File change batch: %d file(s)", len(paths))
            try:
                callback(paths)
            except Exception as exc:
                logger.exception("Error in file watcher callback: %s", exc)

    def _cancel_pending(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
