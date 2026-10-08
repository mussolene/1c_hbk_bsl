"""
Tests for FileWatcher debounce logic and real filesystem indexing.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from onec_hbk_bsl.indexer.watcher import FileWatcher


class TestFileWatcherInit:
    def test_default_debounce(self) -> None:
        fw = FileWatcher()
        assert fw.debounce == 0.5

    def test_custom_debounce(self) -> None:
        fw = FileWatcher(debounce=1.0)
        assert fw.debounce == 1.0

    def test_initial_state(self) -> None:
        fw = FileWatcher()
        assert fw._pending == set()
        assert fw._timer is None


class TestDebounceLogic:
    def test_cancelled_timer_cannot_consume_rescheduled_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timer = MagicMock()
        monkeypatch.setattr("onec_hbk_bsl.indexer.watcher.threading.Timer", timer)
        fw = FileWatcher()
        cb = MagicMock()
        fw._schedule_callback(["/a.bsl"], cb)
        old_call = timer.call_args
        fw._schedule_callback(["/b.bsl"], cb)
        current_call = timer.call_args

        # Timer.cancel cannot prevent a callback that has already started.
        old_call.args[1](*old_call.kwargs["args"])
        cb.assert_not_called()
        assert fw._pending == {"/a.bsl", "/b.bsl"}
        assert fw._timer is timer.return_value

        current_call.args[1](*current_call.kwargs["args"])
        cb.assert_called_once()
        assert set(cb.call_args.args[0]) == {"/a.bsl", "/b.bsl"}

    def test_schedule_callback_adds_paths(self) -> None:
        fw = FileWatcher(debounce=10.0)  # long timeout so it doesn't fire
        cb = MagicMock()
        fw._schedule_callback(["/a.bsl", "/b.bsl"], cb)
        try:
            assert "/a.bsl" in fw._pending
            assert "/b.bsl" in fw._pending
        finally:
            fw._cancel_pending()

    def test_schedule_callback_fires_after_debounce(self) -> None:
        fw = FileWatcher(debounce=0.05)  # 50ms for fast test
        received: list[list[str]] = []

        def cb(paths: list[str]) -> None:
            received.append(paths)

        fw._schedule_callback(["/a.bsl"], cb)
        time.sleep(0.15)  # wait for debounce to fire

        assert len(received) == 1
        assert "/a.bsl" in received[0]

    def test_multiple_schedules_coalesced(self) -> None:
        fw = FileWatcher(debounce=0.05)
        received: list[list[str]] = []

        def cb(paths: list[str]) -> None:
            received.append(list(paths))

        fw._schedule_callback(["/a.bsl"], cb)
        fw._schedule_callback(["/b.bsl"], cb)
        fw._schedule_callback(["/c.bsl"], cb)
        time.sleep(0.15)

        # All three should arrive in a single batch
        assert len(received) == 1
        assert set(received[0]) == {"/a.bsl", "/b.bsl", "/c.bsl"}

    def test_cancel_pending_stops_timer(self) -> None:
        fw = FileWatcher(debounce=10.0)
        cb = MagicMock()
        fw._schedule_callback(["/x.bsl"], cb)
        assert fw._timer is not None
        fw._cancel_pending()
        assert fw._timer is None
        time.sleep(0.05)
        cb.assert_not_called()


class TestFireCallback:
    def test_fire_callback_clears_pending(self) -> None:
        fw = FileWatcher()
        fw._pending = {"/a.bsl"}
        cb = MagicMock()
        fw._fire_callback(cb, fw._timer_generation)
        assert fw._pending == set()
        cb.assert_called_once_with(["/a.bsl"])

    def test_fire_callback_handles_exception(self) -> None:
        fw = FileWatcher()
        fw._pending = {"/a.bsl"}

        def bad_cb(paths: list[str]) -> None:
            raise RuntimeError("oops")

        # Should not raise
        fw._fire_callback(bad_cb, fw._timer_generation)

    def test_fire_callback_skips_when_empty(self) -> None:
        fw = FileWatcher()
        fw._pending = set()
        cb = MagicMock()
        fw._fire_callback(cb, fw._timer_generation)
        cb.assert_not_called()


class TestStop:
    def test_stop_discards_batch_and_rejects_late_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timer = MagicMock()
        monkeypatch.setattr("onec_hbk_bsl.indexer.watcher.threading.Timer", timer)
        fw = FileWatcher()
        cb = MagicMock()
        fw._schedule_callback(["/old.bsl"], cb)
        old_call = timer.call_args
        fw.stop()
        assert fw._pending == set()
        fw._schedule_callback(["/late.bsl"], cb)
        assert timer.call_count == 1
        assert fw._pending == set()

        def watch(workspace, *, stop_event):
            assert not stop_event.is_set()
            yield {(1, "/new.bsl")}
            current_call = timer.call_args
            old_call.args[1](*old_call.kwargs["args"])
            cb.assert_not_called()
            current_call.args[1](*current_call.kwargs["args"])

        monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(watch=watch))
        fw.watch("/workspace", cb)
        cb.assert_called_once_with(["/new.bsl"])

    def test_stop_sets_event(self) -> None:
        fw = FileWatcher()
        assert not fw._stop_event.is_set()
        fw.stop()
        assert fw._stop_event.is_set()

    def test_stop_cancels_pending_timer(self) -> None:
        fw = FileWatcher(debounce=10.0)
        cb = MagicMock()
        fw._schedule_callback(["/a.bsl"], cb)
        fw.stop()
        assert fw._timer is None


class TestWatchMissingDependency:
    def test_watch_without_watchfiles_returns_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """watch() should return (not raise) when watchfiles is not installed."""
        import sys

        # Temporarily hide watchfiles from the import system
        monkeypatch.setitem(sys.modules, "watchfiles", None)  # type: ignore[arg-type]

        fw = FileWatcher()
        cb = MagicMock()

        # Should return immediately instead of blocking or raising
        fw.watch("/nonexistent/workspace", cb)
        cb.assert_not_called()


class TestWatchEvents:
    def test_save_delete_and_rename_paths_are_coalesced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        timer = MagicMock()
        monkeypatch.setattr("onec_hbk_bsl.indexer.watcher.threading.Timer", timer)
        cb = MagicMock()

        def watch(workspace, *, stop_event):
            yield {(2, "/save.bsl"), (3, "/old.bsl"), (2, "/ignore.txt")}
            yield {(1, "/renamed.OS"), (3, "/save.bsl"), (1, "/save.bsl")}
            call = timer.call_args
            call.args[1](*call.kwargs["args"])

        monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(watch=watch))
        fw = FileWatcher()
        fw.watch("/workspace", cb)
        cb.assert_called_once()
        assert set(cb.call_args.args[0]) == {"/save.bsl", "/old.bsl", "/renamed.OS"}

    def test_watch_exit_discards_pending_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        timer = MagicMock()
        monkeypatch.setattr("onec_hbk_bsl.indexer.watcher.threading.Timer", timer)

        def watch(workspace, *, stop_event):
            yield {(2, "/old.bsl")}

        monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(watch=watch))
        fw = FileWatcher()
        cb = MagicMock()
        fw.watch("/workspace", cb)
        assert fw._pending == set()
        call = timer.call_args
        call.args[1](*call.kwargs["args"])
        cb.assert_not_called()


@pytest.mark.integration
def test_real_watchfiles_batches_converge_to_exact_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import watchfiles.main

    from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

    monkeypatch.setenv("BSL_INDEX_MODE", "full")
    monkeypatch.setenv("BSL_INDEX_PARSE_WORKERS", "2")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    indexer = IncrementalIndexer(db_path=str(tmp_path / "symbols.sqlite"), quiet=True)
    watcher = FileWatcher(debounce=0.05)
    ready = threading.Event()
    completed: Queue = Queue()
    observed: set[str] = set()
    native_notify = watchfiles.main.RustNotify

    def notify_ready(*args, **kwargs):
        # Observe registration only; the real native worker delivers every event.
        native = native_notify(*args, **kwargs)
        ready.set()
        return native

    monkeypatch.setattr(watchfiles.main, "RustNotify", notify_ready)
    initial = {workspace / f"module_{i:02d}.bsl": f"Initial{i}" for i in range(32)}
    for path, name in initial.items():
        path.write_text(f"Procedure {name}()\nOldTarget();\nEndProcedure\n", encoding="utf-8")
    assert indexer._index_files([str(path) for path in initial], str(workspace)) == {
        "indexed": 32,
        "skipped": 0,
        "pruned": 0,
        "errors": 0,
    }
    assert len(indexer.index.find_callers("OldTarget", limit=100)) == 32

    def on_change(paths: list[str]) -> None:
        try:
            result = indexer._index_files(paths, str(workspace))
            actual = {
                path: tuple(symbol["name"] for symbol in indexer.index.get_file_symbols(path))
                for path in indexer.index.get_indexed_files()
            }
            completed.put((paths, result, actual))
        except Exception as exc:
            completed.put(exc)

    def run_watch() -> None:
        try:
            watcher.watch(str(workspace), on_change)
        except Exception as exc:
            completed.put(exc)

    def await_index(expected: dict[Path, str]) -> None:
        deadline = time.monotonic() + 15
        expected_symbols = {str(path): (name,) for path, name in expected.items()}
        while True:
            update = completed.get(timeout=max(0, deadline - time.monotonic()))
            if isinstance(update, Exception):
                raise update
            paths, result, actual = update
            observed.update(paths)
            assert result["errors"] == 0
            if actual == expected_symbols:
                return

    worker = threading.Thread(target=run_watch, name="test-real-bsl-watch", daemon=True)
    worker.start()
    try:
        assert ready.wait(timeout=10), "Native watchfiles registration did not complete"
        saved = {path: f"Saved{i}" for i, path in enumerate(initial)}
        for path, name in saved.items():
            path.write_text(f"Procedure {name}()\nSavedTarget();\nEndProcedure\n", encoding="utf-8")
        await_index(saved)
        assert indexer.index.find_callers("OldTarget", limit=100) == []
        assert len(indexer.index.find_callers("SavedTarget", limit=100)) == 32

        created_files = {workspace / f"created_{i:02d}.bsl": f"Transient{i}" for i in range(32)}
        for path, name in created_files.items():
            path.write_text(f"Procedure {name}()\nEndProcedure\n", encoding="utf-8")
        await_index(saved | created_files)

        final: dict[Path, str] = {}
        for i, path in enumerate(initial):
            if i < 16:
                renamed = workspace / f"renamed_{i:02d}.OS"
                path.rename(renamed)
                final[renamed] = saved[path]
            else:
                path.unlink()
        for i, created in enumerate(created_files):
            replacement = workspace / f"replacement_{i:02d}.tmp"
            replacement.write_text(
                f"Procedure Final{i}()\nFinalTarget();\nEndProcedure\n", encoding="utf-8"
            )
            replacement.replace(created)
            final[created] = f"Final{i}"
        ignored = workspace / "ignored.txt"
        ignored.write_text("Procedure Ignored()\nEndProcedure\n", encoding="utf-8")
        await_index(final)

        assert observed.issuperset(str(path) for path in initial)
        assert observed.issuperset(str(path) for path in final)
        assert str(ignored) not in observed
        assert indexer.index.find_symbol("Ignored") == []
        assert indexer.index.find_symbol("Transient0") == []
        assert indexer.index.find_callers("OldTarget", limit=100) == []
        assert len(indexer.index.find_callers("SavedTarget", limit=100)) == 16
        assert len(indexer.index.find_callers("FinalTarget", limit=100)) == 32
    finally:
        watcher.stop()
        worker.join(timeout=10)
        indexer.index.close()
    assert not worker.is_alive()
    assert watcher._pending == set()
    assert watcher._timer is None
