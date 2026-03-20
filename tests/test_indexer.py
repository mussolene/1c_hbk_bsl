"""
Tests for SymbolIndex and IncrementalIndexer.

Covers:
  - upsert_file stores and retrieves symbols
  - find_symbol exact and fuzzy search
  - find_callers returns call sites
  - remove_file removes all data for a file
  - get_stats returns accurate counts
  - save_commit / get_last_commit round-trip
"""

from __future__ import annotations

from pathlib import Path

from bsl_analyzer.indexer.symbol_index import SymbolIndex

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_FILE = "/workspace/orders.bsl"
SAMPLE_SYMBOLS = [
    {
        "name": "ОбработатьЗаказ",
        "line": 10,
        "character": 0,
        "end_line": 40,
        "end_character": 0,
        "kind": "procedure",
        "is_export": True,
        "container": None,
        "signature": "Procedure ОбработатьЗаказ(Заказ) Export",
        "doc_comment": "Обрабатывает входящий заказ.",
    },
    {
        "name": "ВалидироватьСтроки",
        "line": 42,
        "character": 0,
        "end_line": 70,
        "end_character": 0,
        "kind": "function",
        "is_export": False,
        "container": None,
        "signature": "Function ВалидироватьСтроки(Строки)",
        "doc_comment": "",
    },
    {
        "name": "Статус",
        "line": 5,
        "character": 4,
        "end_line": 5,
        "end_character": 10,
        "kind": "variable",
        "is_export": False,
        "container": None,
        "signature": "Var Статус",
        "doc_comment": "",
    },
]

SAMPLE_CALLS = [
    {
        "caller_line": 25,
        "caller_character": 12,
        "caller_name": "ОбработатьЗаказ",
        "callee_name": "ВалидироватьСтроки",
        "callee_args_count": 1,
    },
    {
        "caller_line": 30,
        "caller_character": 8,
        "caller_name": "ОбработатьЗаказ",
        "callee_name": "ЗаписатьЛог",
        "callee_args_count": 2,
    },
]


# ---------------------------------------------------------------------------
# Upsert and retrieval
# ---------------------------------------------------------------------------


class TestUpsertAndFind:
    def test_upsert_and_find_exact(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        results = symbol_index.find_symbol("ОбработатьЗаказ")
        assert len(results) == 1
        sym = results[0]
        assert sym["name"] == "ОбработатьЗаказ"
        assert sym["file_path"] == SAMPLE_FILE
        assert sym["line"] == 10
        assert bool(sym["is_export"]) is True

    def test_upsert_and_find_case_insensitive(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        # lower-cased query
        results = symbol_index.find_symbol("обработатьзаказ")
        assert len(results) == 1

    def test_find_symbol_with_file_filter(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)
        symbol_index.upsert_file(
            "/workspace/other.bsl",
            [
                {
                    "name": "ОбработатьЗаказ",
                    "line": 1,
                    "character": 0,
                    "end_line": 10,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "container": None,
                    "signature": "Procedure ОбработатьЗаказ()",
                    "doc_comment": "",
                }
            ],
            [],
        )

        # filter by filename
        results = symbol_index.find_symbol("ОбработатьЗаказ", file_filter="orders")
        assert all("orders" in r["file_path"] for r in results)

    def test_find_symbol_not_found(self, symbol_index: SymbolIndex) -> None:
        results = symbol_index.find_symbol("НесуществующийСимвол")
        assert results == []

    def test_get_file_symbols_returns_all(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        all_syms = symbol_index.get_file_symbols(SAMPLE_FILE)
        assert len(all_syms) == len(SAMPLE_SYMBOLS)
        # Should be sorted by line
        lines = [s["line"] for s in all_syms]
        assert lines == sorted(lines)


# ---------------------------------------------------------------------------
# Call graph queries
# ---------------------------------------------------------------------------


class TestFindCallers:
    def test_find_callers_returns_sites(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        callers = symbol_index.find_callers("ВалидироватьСтроки")
        assert len(callers) >= 1
        caller = callers[0]
        assert caller["callee_name"] == "ВалидироватьСтроки"
        assert caller["caller_name"] == "ОбработатьЗаказ"
        assert caller["caller_character"] == 12

    def test_find_callers_no_results(self, symbol_index: SymbolIndex) -> None:
        callers = symbol_index.find_callers("НесуществующаяФункция")
        assert callers == []

    def test_find_callees_by_file(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        callees = symbol_index.find_callees(SAMPLE_FILE)
        callee_names = {c["callee_name"] for c in callees}
        assert "ВалидироватьСтроки" in callee_names
        assert "ЗаписатьЛог" in callee_names


# ---------------------------------------------------------------------------
# Remove file
# ---------------------------------------------------------------------------


class TestRemoveFile:
    def test_remove_file_clears_symbols(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)
        assert len(symbol_index.get_file_symbols(SAMPLE_FILE)) > 0

        symbol_index.remove_file(SAMPLE_FILE)
        assert symbol_index.get_file_symbols(SAMPLE_FILE) == []
        assert symbol_index.find_callers("ВалидироватьСтроки") == []

    def test_remove_nonexistent_file_is_noop(self, symbol_index: SymbolIndex) -> None:
        """Removing a file that was never indexed should not raise."""
        symbol_index.remove_file("/no/such/file.bsl")  # Should not raise


# ---------------------------------------------------------------------------
# Git state
# ---------------------------------------------------------------------------


class TestGitState:
    def test_get_last_commit_none_initially(self, symbol_index: SymbolIndex) -> None:
        assert symbol_index.get_last_commit() is None

    def test_save_and_get_commit(self, symbol_index: SymbolIndex) -> None:
        commit_hash = "abc123def456"
        symbol_index.save_commit(commit_hash, workspace_root="/workspace")
        assert symbol_index.get_last_commit() == commit_hash

    def test_save_commit_updates_existing(self, symbol_index: SymbolIndex) -> None:
        symbol_index.save_commit("old_hash")
        symbol_index.save_commit("new_hash")
        assert symbol_index.get_last_commit() == "new_hash"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_stats_after_upsert(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(SAMPLE_FILE, SAMPLE_SYMBOLS, SAMPLE_CALLS)

        stats = symbol_index.get_stats()
        assert stats["symbol_count"] == len(SAMPLE_SYMBOLS)
        assert stats["file_count"] == 1
        assert stats["call_count"] == len(SAMPLE_CALLS)

    def test_stats_empty_index(self, symbol_index: SymbolIndex) -> None:
        stats = symbol_index.get_stats()
        assert stats["symbol_count"] == 0
        assert stats["file_count"] == 0


# ---------------------------------------------------------------------------
# IncrementalIndexer
# ---------------------------------------------------------------------------


class TestIncrementalIndexer:
    def test_index_file_populates_index(
        self, symbol_index: SymbolIndex, sample_bsl_path: str
    ) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file(sample_bsl_path)

        assert "error" not in result
        assert result["symbols"] > 0

        stats = symbol_index.get_stats()
        assert stats["symbol_count"] > 0

    def test_index_file_missing_path(self, symbol_index: SymbolIndex) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file("/no/such/file.bsl")

        assert "error" in result


# ---------------------------------------------------------------------------
# IncrementalIndexer extended tests
# ---------------------------------------------------------------------------


class TestIncrementalIndexerExtended:
    def test_find_all_bsl_files_finds_bsl(self, tmp_path: Path) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        src = tmp_path / "src"
        src.mkdir()
        (src / "mod1.bsl").write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")
        (src / "mod2.bsl").write_text("Функция Ф()\nКонецФункции\n", encoding="utf-8")
        (src / "notes.txt").write_text("not bsl", encoding="utf-8")

        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))

        assert any("mod1.bsl" in f for f in files)
        assert any("mod2.bsl" in f for f in files)
        assert not any("notes.txt" in f for f in files)

    def test_find_all_bsl_files_includes_os_extension(self, tmp_path: Path) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        (tmp_path / "script.os").write_text("", encoding="utf-8")
        files = IncrementalIndexer._find_all_bsl_files(str(tmp_path))
        assert any("script.os" in f for f in files)

    def test_get_current_commit_non_git_dir(self, tmp_path: Path) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        result = IncrementalIndexer._get_current_commit(str(tmp_path))
        # Non-git directory returns None
        assert result is None

    def test_get_current_commit_git_dir(self) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        # The project itself is a git repo
        project_root = str(Path(__file__).parent.parent)
        result = IncrementalIndexer._get_current_commit(project_root)
        # Should return a hex string or None (if not a git repo in CI)
        assert result is None or (isinstance(result, str) and len(result) >= 7)

    def test_get_changed_files_mocked_success(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "changed.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "changed.bsl\n"

        with patch("subprocess.run", return_value=mock_result):
            files = indexer.get_changed_files(
                since_commit="abc123", workspace=str(tmp_path)
            )

        assert any("changed.bsl" in f for f in files)

    def test_get_changed_files_git_failure_fallback(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "fallback.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "not a git repository"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            files = indexer.get_changed_files(
                since_commit="abc123", workspace=str(tmp_path)
            )

        # Falls back to full scan — should include our bsl file
        assert any("fallback.bsl" in f for f in files)

    def test_get_changed_files_git_not_found_fallback(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        bsl_file = tmp_path / "nofallback.bsl"
        bsl_file.write_text("Процедура П()\nКонецПроцедуры\n", encoding="utf-8")

        indexer = IncrementalIndexer(index=symbol_index)

        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            files = indexer.get_changed_files(
                since_commit="abc123", workspace=str(tmp_path)
            )

        assert any("nofallback.bsl" in f for f in files)

    def test_index_workspace_force_true(
        self, symbol_index: SymbolIndex, temp_workspace: str
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "bsl_analyzer.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer.index_workspace(temp_workspace, force=True)

        assert result["indexed"] >= 1
        assert result["errors"] == 0

    def test_index_workspace_up_to_date_returns_early(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        fake_commit = "deadbeef1234567890"
        symbol_index.save_commit(fake_commit, workspace_root=str(tmp_path))

        indexer = IncrementalIndexer(index=symbol_index)

        with patch(
            "bsl_analyzer.indexer.incremental.IncrementalIndexer._get_current_commit",
            return_value=fake_commit,
        ):
            result = indexer.index_workspace(str(tmp_path), force=False)

        assert result == {"indexed": 0, "skipped": 0, "errors": 0}

    def test_index_files_with_missing_file_increments_skipped(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        nonexistent = str(tmp_path / "gone.bsl")
        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "bsl_analyzer.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer._index_files([nonexistent], workspace=str(tmp_path))

        assert result["skipped"] == 1
        assert result["indexed"] == 0

    def test_index_file_with_calls_count(
        self, symbol_index: SymbolIndex, sample_bsl_path: str
    ) -> None:
        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        indexer = IncrementalIndexer(index=symbol_index)
        result = indexer.index_file(sample_bsl_path)

        assert "error" not in result
        assert result["calls"] >= 0  # calls may be 0 for simple files

    def test_on_progress_callback_called(
        self, symbol_index: SymbolIndex, temp_workspace: str
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        progress_calls: list = []

        def on_progress(current: int, total: int, path: str) -> None:
            progress_calls.append((current, total, path))

        indexer = IncrementalIndexer(index=symbol_index, on_progress=on_progress)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "bsl_analyzer.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            indexer.index_workspace(temp_workspace, force=True)

        assert len(progress_calls) >= 1

    def test_index_workspace_many_files_stress(
        self, symbol_index: SymbolIndex, tmp_path: Path
    ) -> None:
        from unittest.mock import MagicMock, patch

        from bsl_analyzer.indexer.incremental import IncrementalIndexer

        # Create many small modules to emulate a larger workspace.
        file_count = 120
        for i in range(file_count):
            p = tmp_path / f"mod_{i:03d}.bsl"
            p.write_text(
                f"Процедура Тест{i}()\n    Сообщить(\"{i}\");\nКонецПроцедуры\n",
                encoding="utf-8",
            )

        indexer = IncrementalIndexer(index=symbol_index)

        mock_progress_instance = MagicMock()
        mock_progress_instance.__enter__ = MagicMock(return_value=mock_progress_instance)
        mock_progress_instance.__exit__ = MagicMock(return_value=False)
        mock_progress_instance.add_task = MagicMock(return_value=0)
        mock_progress_instance.update = MagicMock()
        mock_progress_instance.advance = MagicMock()

        with patch(
            "bsl_analyzer.indexer.incremental.Progress",
            return_value=mock_progress_instance,
        ):
            result = indexer.index_workspace(str(tmp_path), force=True)

        assert result["errors"] == 0
        # At least all created files should be processed.
        assert result["indexed"] >= file_count
        # Spot-check that symbols are queryable after bulk indexing.
        sym = symbol_index.find_symbol("Тест42", limit=1)
        assert len(sym) == 1


# ---------------------------------------------------------------------------
# get_module_exports (Iteration 2)
# ---------------------------------------------------------------------------


class TestGetModuleExports:
    def test_get_module_exports_finds_exported(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/ОбщийМодуль.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "ЭкспортнаяФункция",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": True,
                    "signature": "ЭкспортнаяФункция()",
                    "doc_comment": None,
                },
                {
                    "name": "НеЭкспорт",
                    "line": 10,
                    "character": 0,
                    "end_line": 15,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "signature": "НеЭкспорт()",
                    "doc_comment": None,
                },
            ],
            [],
        )
        results = symbol_index.get_module_exports("ОбщийМодуль")
        names = [r["name"] for r in results]
        assert "ЭкспортнаяФункция" in names

    def test_get_module_exports_ignores_non_export(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/МодульБезЭкспорта.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "Внутренняя",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "procedure",
                    "is_export": False,
                    "signature": "Внутренняя()",
                    "doc_comment": None,
                }
            ],
            [],
        )
        results = symbol_index.get_module_exports("МодульБезЭкспорта")
        assert results == []

    def test_get_module_exports_case_insensitive(self, symbol_index: SymbolIndex) -> None:
        file_path = "/workspace/МойМодуль.bsl"
        symbol_index.upsert_file(
            file_path,
            [
                {
                    "name": "Метод",
                    "line": 1,
                    "character": 0,
                    "end_line": 5,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": True,
                    "signature": "Метод()",
                    "doc_comment": None,
                }
            ],
            [],
        )
        # lookup with different case
        results = symbol_index.get_module_exports("мойМОДУЛЬ")
        names = [r["name"] for r in results]
        assert "Метод" in names


# ---------------------------------------------------------------------------
# find_unused_symbols + find_callers_count_non_recursive (Unused detection)
# ---------------------------------------------------------------------------


class TestFindUnusedSymbols:
    _FILE = "/workspace/module.bsl"
    _CALLER_FILE = "/workspace/caller.bsl"

    def _sym(self, name: str, kind: str = "function", is_export: bool = False) -> dict:
        return {
            "name": name,
            "line": 1,
            "character": 0,
            "end_line": 5,
            "end_character": 0,
            "kind": kind,
            "is_export": is_export,
            "signature": f"{name}()",
            "doc_comment": None,
        }

    def test_unused_private_function_detected(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("НеВызывается")], [])
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert any(u["name"] == "НеВызывается" for u in unused)

    def test_used_function_not_in_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Вызывается")], [])
        symbol_index.upsert_file(
            self._CALLER_FILE,
            [self._sym("КаллерМетод")],
            [{"caller_file": self._CALLER_FILE, "caller_line": 10,
              "caller_name": "КаллерМетод", "callee_name": "Вызывается",
              "callee_args_count": 0}],
        )
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert not any(u["name"] == "Вызывается" for u in unused)

    def test_export_function_not_in_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("ЭкспортМетод", is_export=True)], [])
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert not any(u["name"] == "ЭкспортМетод" for u in unused)

    def test_recursive_function_is_unused(self, symbol_index: SymbolIndex) -> None:
        """A function that only calls itself counts as unused."""
        symbol_index.upsert_file(self._FILE, [self._sym("Рекурсия")], [])
        symbol_index.upsert_file(
            self._FILE,
            [self._sym("Рекурсия")],
            [{"caller_file": self._FILE, "caller_line": 3,
              "caller_name": "Рекурсия", "callee_name": "Рекурсия",
              "callee_args_count": 0}],
        )
        unused = symbol_index.find_unused_symbols(self._FILE)
        assert any(u["name"] == "Рекурсия" for u in unused)

    def test_non_recursive_count_zero_for_unused(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Функция1")], [])
        count = symbol_index.find_callers_count_non_recursive("Функция1")
        assert count == 0

    def test_non_recursive_count_positive_for_used(self, symbol_index: SymbolIndex) -> None:
        symbol_index.upsert_file(self._FILE, [self._sym("Функция2")], [])
        symbol_index.upsert_file(
            self._CALLER_FILE,
            [self._sym("Другая")],
            [{"caller_file": self._CALLER_FILE, "caller_line": 5,
              "caller_name": "Другая", "callee_name": "Функция2",
              "callee_args_count": 0}],
        )
        count = symbol_index.find_callers_count_non_recursive("Функция2")
        assert count == 1
