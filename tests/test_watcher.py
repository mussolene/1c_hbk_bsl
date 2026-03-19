"""
Tests for FileWatcher — debounce logic and internal helpers.

The blocking ``watch()`` method is not tested end-to-end (it requires watchfiles
and a real filesystem); instead we test the debounce helpers directly.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from bsl_analyzer.indexer.watcher import FileWatcher


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
        fw._fire_callback(cb)
        assert fw._pending == set()
        cb.assert_called_once_with(["/a.bsl"])

    def test_fire_callback_handles_exception(self) -> None:
        fw = FileWatcher()
        fw._pending = {"/a.bsl"}

        def bad_cb(paths: list[str]) -> None:
            raise RuntimeError("oops")

        # Should not raise
        fw._fire_callback(bad_cb)

    def test_fire_callback_skips_when_empty(self) -> None:
        fw = FileWatcher()
        fw._pending = set()
        cb = MagicMock()
        fw._fire_callback(cb)
        cb.assert_not_called()


class TestStop:
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
