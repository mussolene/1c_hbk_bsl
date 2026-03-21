"""Tests for resolve_index_db_path (hidden index location)."""

from __future__ import annotations

import os

import pytest

from onec_hbk_bsl.indexer.db_path import resolve_index_db_path


def test_explicit_env_overrides(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = str(tmp_path / "custom.sqlite")
    monkeypatch.setenv("INDEX_DB_PATH", custom)
    assert resolve_index_db_path(str(tmp_path)) == custom


def test_git_repo_uses_dot_git_sqlite(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INDEX_DB_PATH", raising=False)
    (tmp_path / ".git").mkdir()
    expected = str(tmp_path / ".git" / "onec-hbk-bsl_index.sqlite")
    assert resolve_index_db_path(str(tmp_path)) == expected


def test_git_repo_uses_legacy_filename_when_present(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
