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
        "caller_name": "ОбработатьЗаказ",
        "callee_name": "ВалидироватьСтроки",
        "callee_args_count": 1,
    },
    {
        "caller_line": 30,
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
