"""Tests for resolve_index_db_path (hidden index location)."""

from __future__ import annotations

import os

import pytest

from onec_hbk_bsl.indexer.db_path import (
    cleanup_corrupt_index_storage,
    cleanup_index_storage,
    index_storage_lock,
    resolve_index_db_path,
)


def test_explicit_env_overrides(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = str(tmp_path / "custom.sqlite")
    monkeypatch.setenv("INDEX_DB_PATH", custom)
    assert resolve_index_db_path(str(tmp_path)) == custom


def test_git_repo_uses_dot_git_sqlite(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INDEX_DB_PATH", raising=False)
    (tmp_path / ".git").mkdir()
    expected = str(tmp_path / ".git" / "onec-hbk-bsl_index.sqlite")
    assert resolve_index_db_path(str(tmp_path)) == expected


def test_git_repo_uses_legacy_filename_when_present(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INDEX_DB_PATH", raising=False)
    (tmp_path / ".git").mkdir()
    legacy = tmp_path / ".git" / "bsl_index.sqlite"
    legacy.touch()
    assert resolve_index_db_path(str(tmp_path)) == str(legacy)


def test_git_repo_prefers_new_over_legacy_when_both_exist(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INDEX_DB_PATH", raising=False)
    (tmp_path / ".git").mkdir()
    new_p = tmp_path / ".git" / "onec-hbk-bsl_index.sqlite"
    old_p = tmp_path / ".git" / "bsl_index.sqlite"
    new_p.touch()
    old_p.touch()
    assert resolve_index_db_path(str(tmp_path)) == str(new_p)


def test_non_git_uses_user_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INDEX_DB_PATH", raising=False)
    p = resolve_index_db_path(str(tmp_path))
    assert "onec-hbk-bsl" in p.replace("\\", "/")
    assert p.endswith("onec-hbk-bsl_index.sqlite")
    assert os.path.expanduser("~") in p


def test_index_storage_lock_rejects_second_writer(tmp_path) -> None:
    db = str(tmp_path / "index.sqlite")
    with index_storage_lock(db) as first:
        assert first is True
        with index_storage_lock(db) as second:
            assert second is False


def test_cleanup_index_storage_removes_sidecars_and_legacy_corrupt(tmp_path) -> None:
    db = tmp_path / "index.sqlite"
    paths = [
        db,
        tmp_path / "index.sqlite-wal",
        tmp_path / "index.sqlite-shm",
        tmp_path / "index.sqlite.corrupt.123",
        tmp_path / "index.sqlite-wal.corrupt.123",
    ]
    for path in paths:
        path.write_bytes(b"1234")

    with index_storage_lock(str(db)) as acquired:
        assert acquired is True
        result = cleanup_index_storage(str(db), include_corrupt=True)

    assert result == {"files_removed": 5, "bytes_removed": 20}
    assert not any(path.exists() for path in paths)


def test_cleanup_corrupt_index_storage_preserves_active_db(tmp_path) -> None:
    db = tmp_path / "index.sqlite"
    corrupt = tmp_path / "index.sqlite.corrupt.123"
    db.write_bytes(b"active")
    corrupt.write_bytes(b"old")

    with index_storage_lock(str(db)) as acquired:
        assert acquired is True
        result = cleanup_corrupt_index_storage(str(db))

    assert result == {"files_removed": 1, "bytes_removed": 3}
    assert db.read_bytes() == b"active"
    assert not corrupt.exists()
