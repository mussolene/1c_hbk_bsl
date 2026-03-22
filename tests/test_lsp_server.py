"""
Tests for LSP server utility functions and server initialization.

These tests do NOT start the actual LSP stdio loop; they test the
helper functions and server object creation in isolation.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------


class TestUriHelpers:
    def test_uri_to_path_file_scheme(self) -> None:
        from onec_hbk_bsl.lsp.server import _uri_to_path
        assert _uri_to_path("file:///home/user/module.bsl") == "/home/user/module.bsl"

    def test_uri_to_path_no_scheme(self) -> None:
        from onec_hbk_bsl.lsp.server import _uri_to_path
        assert _uri_to_path("/absolute/path.bsl") == "/absolute/path.bsl"

    def test_path_to_uri(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.lsp.server import _path_to_uri
        f = tmp_path / "module.bsl"
        f.write_text("//", encoding="utf-8")
        result = _path_to_uri(str(f))
        assert result.startswith("file:///")
        assert "module.bsl" in result

    def test_roundtrip(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.lsp.server import _path_to_uri, _uri_to_path
        f = tmp_path / "module.bsl"
        f.write_text("//", encoding="utf-8")
        path = str(f.resolve())
        assert Path(_uri_to_path(_path_to_uri(path))).resolve() == Path(path).resolve()


# ---------------------------------------------------------------------------
# Server instantiation
# ---------------------------------------------------------------------------


class TestBslLanguageServerInit:
    def test_server_is_created(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        assert ls is not None

    def test_server_has_diagnostics_engine(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        assert isinstance(ls.diagnostics_engine, DiagnosticEngine)

    def test_server_has_empty_docs_cache(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        assert ls._docs == {}


# ---------------------------------------------------------------------------
# Diagnostics publishing helper (internal)
# ---------------------------------------------------------------------------


class TestPublishDiagnostics:
    def test_publish_diagnostics_runs_engine(self, tmp_path: Path, monkeypatch) -> None:
        """_publish_diagnostics should not raise for a valid BSL file."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "mod.bsl"
        bsl.write_text('Пароль = "секрет123";\n', encoding="utf-8")

        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, _publish_diagnostics
        ls = BslLanguageServer()
        # Replace the pygls 2.0 publish method with a mock to capture calls
        ls.text_document_publish_diagnostics = MagicMock()

        uri = _path_to_uri(str(bsl))
        _publish_diagnostics(ls, uri, str(bsl))

        ls.text_document_publish_diagnostics.assert_called_once()
        call_args = ls.text_document_publish_diagnostics.call_args
        params = call_args[0][0]
        assert params.uri == uri

    def test_publish_diagnostics_missing_file_no_crash(self, tmp_path: Path, monkeypatch) -> None:
        """_publish_diagnostics should swallow errors for nonexistent files."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _publish_diagnostics
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        # Path does not exist — engine should raise, but _publish_diagnostics catches it
        _publish_diagnostics(ls, "file:///nonexistent.bsl", "/nonexistent.bsl")
        # Should not raise; publish_diagnostics may or may not be called

    def test_publish_diagnostics_unused_separate_source_and_information(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Dead-code hints use a distinct Problems source and Information severity."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "mod.bsl"
        bsl.write_text(
            "Функция НеВызывается()\nВозврат 0;\nКонецФункции\n",
            encoding="utf-8",
        )
        from unittest.mock import MagicMock

        from lsprotocol.types import DiagnosticSeverity, DiagnosticTag

        from onec_hbk_bsl.lsp.server import (
            BslLanguageServer,
            _path_to_uri,
            _publish_diagnostics,
        )

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        ls.symbol_index.find_unused_symbols = lambda _path: [
            {"name": "НеВызывается", "line": 1, "character": 8},
        ]
        uri = _path_to_uri(str(bsl))
        _publish_diagnostics(ls, uri, str(bsl))
        params = ls.text_document_publish_diagnostics.call_args[0][0]

        def _is_dead(diag: object) -> bool:
            data = getattr(diag, "data", None)
            return isinstance(data, dict) and data.get("bsl") == "BSL-DEAD"

        dead = [d for d in params.diagnostics if _is_dead(d)]
        assert len(dead) == 1
        assert dead[0].code == "UnusedPrivateMethod"
        assert dead[0].source == "onec-hbk-bsl · unused"
        assert dead[0].severity == DiagnosticSeverity.Information
        assert dead[0].tags and DiagnosticTag.Unnecessary in dead[0].tags
        lint_sources = {d.source for d in params.diagnostics if not _is_dead(d)}
        assert lint_sources <= {"onec-hbk-bsl"}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestWordAtPosition:
    def test_word_in_middle_of_line(self) -> None:
        from onec_hbk_bsl.lsp.server import _word_at_position
        content = "Процедура ПолучитьЗначение()\nКонецПроцедуры\n"
        word = _word_at_position(content, 0, 15)
        assert word  # should extract some identifier

    def test_empty_content_returns_empty(self) -> None:
        from onec_hbk_bsl.lsp.server import _word_at_position
        assert _word_at_position("", 0, 0) == ""

    def test_line_beyond_content_returns_empty(self) -> None:
        from onec_hbk_bsl.lsp.server import _word_at_position
        assert _word_at_position("А = 1;\n", 99, 0) == ""

    def test_character_beyond_line_returns_empty(self) -> None:
        from onec_hbk_bsl.lsp.server import _word_at_position
        assert _word_at_position("А = 1;\n", 0, 999) == ""

    def test_at_word_start(self) -> None:
        from onec_hbk_bsl.lsp.server import _word_at_position
        content = "НайтиПоКоду()\n"
        word = _word_at_position(content, 0, 0)
        assert "НайтиПоКоду" in word or word  # extracts identifier


class TestLastIdentifier:
    def test_simple_word(self) -> None:
        from onec_hbk_bsl.lsp.server import _last_identifier
        assert _last_identifier("НайтиПоКоду") == "НайтиПоКоду"

    def test_after_dot(self) -> None:
        from onec_hbk_bsl.lsp.server import _last_identifier
        assert _last_identifier("Объект.Метод") == "Метод"

    def test_empty_string(self) -> None:
        from onec_hbk_bsl.lsp.server import _last_identifier
        assert _last_identifier("") == ""

    def test_ends_with_space(self) -> None:
        from onec_hbk_bsl.lsp.server import _last_identifier
        assert _last_identifier("Объект.") == ""


# ---------------------------------------------------------------------------
# Handler functions (called directly, bypassing LSP wire protocol)
# ---------------------------------------------------------------------------


class TestHandlerFunctions:
    """Call the LSP handler functions directly with mock params."""

    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_on_did_open_caches_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_did_open
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.text_document.text = "А = 1;\n"
        on_did_open(ls, params)
        assert ls._docs["file:///test.bsl"] == "А = 1;\n"

    def test_on_did_change_updates_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_did_change
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "old content"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        change = MagicMock()
        change.text = "new content"
        params.content_changes = [change]
        on_did_change(ls, params)
        assert ls._docs["file:///test.bsl"] == "new content"

    def test_on_did_save_publishes_diagnostics(self, tmp_path, monkeypatch) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _path_to_uri, on_did_save

        # Run background threads synchronously so the assertion fires in time
        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args

            def start(self):
                self._target(*self._args)

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        ls = self._make_server(tmp_path, monkeypatch)
        bsl = tmp_path / "module.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")
        params = MagicMock()
        params.text_document.uri = _path_to_uri(str(bsl))
        params.text = None
        on_did_save(ls, params)
        ls.text_document_publish_diagnostics.assert_called()

    def test_on_definition_no_word_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        # Empty docs cache → word is ""
        result = on_definition(ls, params)
        assert result is None

    def test_on_definition_with_word_fresh_index(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition
        ls = self._make_server(tmp_path, monkeypatch)
        # Use a unique symbol name unlikely to exist in any real index
        ls._docs["file:///test.bsl"] = "ЭтаФункцияТочноНеСуществует();\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 5
        result = on_definition(ls, params)
        # No symbols found for this name → returns None or empty list
        assert result is None or result == []

    def test_on_hover_empty_doc_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_hover
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_hover(ls, params)
        assert result is None

    def test_on_hover_metadata_member_resolves_object_from_chain(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_hover

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///test.bsl"
        ls._docs[uri] = "Справочники.Контрагенты.Товары.Сумма;\n"

        # Emulate metadata availability with chain-aware object resolution.
        ls.symbol_index.has_metadata = lambda: True
        ls.symbol_index.find_meta_object = lambda name: {"name": name} if name == "Контрагенты" else None
        ls.symbol_index.get_meta_members = lambda obj, prefix="": (
            [
                {
                    "name": "Сумма",
                    "kind": "ts_attribute",
                    "type_info": "Число(15,2)",
                    "synonym_ru": "Сумма",
                    "object_name": "Контрагенты",
                    "object_kind": "Catalog",
                }
            ]
            if obj == "Контрагенты"
            else []
        )

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = ls._docs[uri].index("Сумма") + 2
        result = on_hover(ls, params)
        assert result is not None
        assert "Число(15,2)" in str(result.contents)

    def test_on_signature_help_empty_doc_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_signature_help
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_signature_help(ls, params)
        assert result is None

    def test_on_signature_help_platform_function_active_param(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_signature_help
        ls = self._make_server(tmp_path, monkeypatch)
        content = 'Сообщить("Привет", Статус);\\n'
        uri = "file:///test.bsl"
        ls._docs[uri] = content

        line_text = content.splitlines()[0]
        cursor_char = line_text.index(",") + 1  # after comma between args

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = cursor_char

        result = on_signature_help(ls, params)
        assert result is not None
        assert len(result.signatures) == 1
        assert result.active_parameter == 1
        assert result.signatures[0].parameters is not None
        labels = [p.label for p in result.signatures[0].parameters]
        assert "ТекстСообщения" in labels
        assert "Статус?" in labels

    def test_on_document_symbol_empty_index(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_document_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_document_symbol(ls, params)
        assert result == []

    def test_on_workspace_symbol_empty_query(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_workspace_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.query = "   "  # whitespace only
        result = on_workspace_symbol(ls, params)
        assert result == []

    def test_on_workspace_symbol_with_query(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_workspace_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.query = "ПолучитьЗначение"
        result = on_workspace_symbol(ls, params)
        assert isinstance(result, list)  # empty — no symbols in index

    def test_on_references_no_word(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_references
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_references(ls, params)
        assert result is None

    def test_on_references_uses_caller_character(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_references

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///test.bsl"
        ls._docs[uri] = "МойВызов();\n"

        ls.symbol_index.find_callers = lambda name, limit=200: [  # type: ignore[method-assign]
            {"caller_file": "/workspace/a.bsl", "caller_line": 3, "caller_character": 10}
        ]

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = 2
        params.context.include_declaration = False
        result = on_references(ls, params)
        assert result is not None
        assert result[0].range.start.character == 10
        assert result[0].range.end.character == 18  # 10 + len("МойВызов")

    def test_on_completion_empty_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 99  # beyond content
        params.position.character = 0
        result = on_completion(ls, params)
        assert result is None

    def test_on_completion_global_prefix(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "Сообщить\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 8
        result = on_completion(ls, params)
        # Should return a CompletionList (may be empty if no platform funcs match)
        assert result is not None

    def test_on_completion_dot_access(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "Массив.\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 8
        result = on_completion(ls, params)
        # Dot completion — returns CompletionList
        assert result is not None

    def test_on_completion_metadata_chain_uses_base_object(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///test.bsl"
        ls._docs[uri] = "Справочники.Контрагенты.Товары.Су\n"

        ls.symbol_index.has_metadata = lambda: True
        ls.symbol_index.find_meta_object = lambda name: {"name": name} if name == "Контрагенты" else None
        ls.symbol_index.find_meta_objects_by_collection = lambda collection, prefix="": []
        ls.symbol_index.get_meta_members = lambda obj, prefix="": (
            [
                {
                    "name": "Сумма",
                    "kind": "ts_attribute",
                    "type_info": "Число(15,2)",
                    "synonym_ru": "Сумма",
                    "object_name": "Контрагенты",
                    "object_kind": "Catalog",
                }
            ]
            if obj == "Контрагенты" and prefix == "Су"
            else []
        )

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = len(ls._docs[uri].rstrip("\n"))
        result = on_completion(ls, params)
        assert result is not None
        labels = [i.label for i in result.items]
        assert "Сумма" in labels


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_formatting_normalises_keywords(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "процедура Тест()\nконецпроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        result = on_formatting(ls, params)
        assert result is not None
        assert any("Процедура" in e.new_text for e in result)

    def test_formatting_empty_doc_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///nonexistent.bsl"
        params.options.tab_size = 4
        result = on_formatting(ls, params)
        assert result is None

    def test_formatting_already_formatted_returns_empty(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        code = "Процедура Тест()\nКонецПроцедуры\n"
        ls._docs["file:///test.bsl"] = code
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        result = on_formatting(ls, params)
        assert result == []

    def test_range_formatting(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import Position, Range

        from onec_hbk_bsl.lsp.server import on_range_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "процедура Тест()\nконецпроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        params.range = Range(start=Position(line=0, character=0), end=Position(line=0, character=20))
        result = on_range_formatting(ls, params)
        assert result is not None

    def test_range_formatting_end_exclusive_does_not_touch_next_line(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import Position, Range

        from onec_hbk_bsl.lsp.server import on_range_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "процедура Тест()\nа=1;\nб=2;\nконецпроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        # Select only line 1 (end is exclusive at line 2, char 0)
        params.range = Range(start=Position(line=1, character=0), end=Position(line=2, character=0))
        result = on_range_formatting(ls, params)
        assert result is not None
        assert len(result) == 1
        assert result[0].range.start.line == 1
        assert result[0].range.end.line == 2
        assert "Б = 2;" not in result[0].new_text


# ---------------------------------------------------------------------------
# Document Highlight
# ---------------------------------------------------------------------------


class TestDocumentHighlight:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_highlight_finds_occurrences(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_document_highlight
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "МояПерем = 1;\nА = МояПерем;\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 3
        result = on_document_highlight(ls, params)
        assert result is not None
        assert len(result) >= 2  # two occurrences of МояПерем

    def test_highlight_empty_word_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_document_highlight
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_document_highlight(ls, params)
        assert result is None


# ---------------------------------------------------------------------------
# Folding Ranges
# ---------------------------------------------------------------------------


class TestFoldingRange:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_folding_procedure(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_folding_range
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = (
            "Процедура Тест()\n"
            "    А = 1;\n"
            "КонецПроцедуры\n"
        )
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_folding_range(ls, params)
        assert result is not None
        assert any(r.start_line == 0 and r.end_line == 2 for r in result)

    def test_folding_region(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_folding_range
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = (
            "#Область МояОбласть\n"
            "А = 1;\n"
            "#КонецОбласти\n"
        )
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_folding_range(ls, params)
        assert result is not None
        assert len(result) >= 1

    def test_folding_empty_doc_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_folding_range
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///empty.bsl"
        result = on_folding_range(ls, params)
        assert result is None


# ---------------------------------------------------------------------------
# Semantic Tokens
# ---------------------------------------------------------------------------


class TestSemanticTokens:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_semantic_tokens_returns_data(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_semantic_tokens_full
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_semantic_tokens_full(ls, params)
        assert result is not None
        assert len(result.data) > 0
        assert len(result.data) % 5 == 0  # each token is 5 integers

    def test_semantic_tokens_znach_val_are_keywords_not_variables(self, tmp_path, monkeypatch) -> None:
        """Знач/Val in parameter list are modifiers (keyword token), not parameter names."""
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_semantic_tokens_full
        ls = self._make_server(tmp_path, monkeypatch)
        src = "Процедура Записать(Знач ИмяСобытия, Val Detail)\nКонецПроцедуры\n"
        ls._docs["file:///p.bsl"] = src
        params = MagicMock()
        params.text_document.uri = "file:///p.bsl"
        result = on_semantic_tokens_full(ls, params)
        assert result is not None
        assert result.data
        # Decode: [deltaLine, deltaStart, length, tokenType, tokenModifiers] × N
        line0 = 0
        col0 = 0
        keyword_type = 0
        znach_pos = src.index("Знач")
        val_pos = src.index("Val")
        found_znach = found_val = False
        i = 0
        while i < len(result.data):
            d_line, d_start, length, typ, _mod = result.data[i : i + 5]
            if d_line > 0:
                line0 += d_line
                col0 = d_start
            else:
                col0 += d_start
            if typ == keyword_type:
                if line0 == 0 and col0 <= znach_pos < col0 + length:
                    found_znach = True
                if line0 == 0 and col0 <= val_pos < col0 + length:
                    found_val = True
            i += 5
        assert found_znach, "expected semantic token 'keyword' over Знач"
        assert found_val, "expected semantic token 'keyword' over Val"

    def test_semantic_tokens_logical_operators_case_insensitive(self, tmp_path, monkeypatch) -> None:
        """BSL is case-insensitive: и/или/нЕ must get keyword tokens; ИЛИ is one token, not И."""
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_semantic_tokens_full

        ls = self._make_server(tmp_path, monkeypatch)
        src = "Если а и б или в нЕ г Тогда\nКонецЕсли\n"
        ls._docs["file:///log.bsl"] = src
        params = MagicMock()
        params.text_document.uri = "file:///log.bsl"
        result = on_semantic_tokens_full(ls, params)
        assert result is not None and result.data
        keyword_type = 0
        # Collect keyword spans on line 0
        line0 = 0
        col0 = 0
        spans: list[tuple[int, int]] = []
        i = 0
        while i < len(result.data):
            d_line, d_start, length, typ, _mod = result.data[i : i + 5]
            if d_line > 0:
                line0 += d_line
                col0 = d_start
            else:
                col0 += d_start
            if line0 == 0 and typ == keyword_type:
                spans.append((col0, length))
            i += 5

        def covers(pos: int) -> bool:
            return any(s <= pos < s + ln for s, ln in spans)

        assert covers(src.index("и")), "expected keyword token on lowercase и (AND)"
        assert covers(src.index("или")), "expected keyword token on или (OR)"
        assert covers(src.index("нЕ")), "expected keyword token on mixed-case нЕ (NOT)"

    def test_semantic_tokens_empty_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_semantic_tokens_full
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///empty.bsl"
        result = on_semantic_tokens_full(ls, params)
        assert result is None


# ---------------------------------------------------------------------------
# Inlay hints
# ---------------------------------------------------------------------------


class TestInlayHints:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_no_inlay_on_function_declaration_with_znach(self, tmp_path, monkeypatch) -> None:
        """Declaration lines are not call sites — do not prefix Знач: before parameters."""
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_inlay_hint

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///m.bsl"
        ls._docs[uri] = (
            "//\n"
            "&НаКлиенте\n"
            'Функция РазделитьСтрокуЛок(Знач Строка, Разделитель = ",", ВключатьПустые = Истина)\n'
            "\tВозврат Строка;\n"
            "КонецФункции\n"
        )
        params = MagicMock()
        params.text_document.uri = uri
        params.range = MagicMock()
        params.range.start.line = 0
        params.range.end.line = 10
        result = on_inlay_hint(ls, params)
        assert result in (None, [])


# ---------------------------------------------------------------------------
# Code Action
# ---------------------------------------------------------------------------


class TestCodeAction:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_code_action_for_known_diagnostic(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_code_action
        ls = self._make_server(tmp_path, monkeypatch)
        # Populate _docs so line-range check works
        ls._docs["file:///test.bsl"] = "А = 1;  // код\nБ = 2;\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        diag = MagicMock()
        diag.code = "BSL009"
        diag.range.start.line = 0
        params.context.diagnostics = [diag]
        result = on_code_action(ls, params)
        assert result is not None
        assert len(result) >= 1
        # Should have noqa action
        titles = [a.title for a in result]
        assert any("игнор" in t.lower() for t in titles)

    def test_code_action_unknown_diagnostic_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_code_action
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///unknown.bsl"  # not in _docs → empty content
        diag = MagicMock()
        diag.code = "BSL999"
        diag.range.start.line = 0
        params.context.diagnostics = [diag]
        result = on_code_action(ls, params)
        # No doc content → no line actions, no format action → None
        assert result is None

    def test_bslls_quickfix_preserves_tab_indent(self, tmp_path, monkeypatch) -> None:
        """BSLLS-off/on inserts must keep tabs from the diagnostic line, not expand to spaces."""
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_code_action

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///t.bsl"
        ls._docs[uri] = "\tА = А;\nСтрока2\n"
        params = MagicMock()
        params.text_document.uri = uri
        diag = MagicMock()
        diag.code = "BSL009"
        diag.range.start.line = 0
        params.context.diagnostics = [diag]
        params.range = MagicMock()
        params.range.start.line = 0
        result = on_code_action(ls, params)
        assert result
        texts: list[str] = []
        for action in result:
            changes = getattr(action.edit, "changes", None) or {}
            for edits in changes.values():
                for te in edits:
                    texts.append(te.new_text)
        assert any(t.startswith("\t// BSLLS:") for t in texts), texts

    def test_code_action_bsl024_inserts_space_after_slash(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_code_action

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///c.bsl"
        ls._docs[uri] = "Процедура Т()\n\t//коммент\nКонецПроцедуры\n"
        params = MagicMock()
        params.text_document.uri = uri
        diag = MagicMock()
        diag.code = "BSL024"
        diag.range.start.line = 1
        params.context.diagnostics = [diag]
        params.range = MagicMock()
        params.range.start.line = 1
        result = on_code_action(ls, params)
        assert result
        titles = [a.title for a in result]
        assert any("пробел" in t.lower() and "BSL024" in t for t in titles)
        fix_edit = None
        for a in result:
            if getattr(a, "title", "") == "Вставить пробел после «//» (BSL024)":
                fix_edit = a
                break
        assert fix_edit is not None
        changes = fix_edit.edit.changes[uri]
        assert len(changes) == 1
        assert "\t// коммент" in changes[0].new_text


# ---------------------------------------------------------------------------
# Selection Range
# ---------------------------------------------------------------------------


class TestSelectionRange:
    """Tests for _build_selection_range helper."""

    def test_procedure_block(self) -> None:
        from onec_hbk_bsl.lsp.server import _build_selection_range

        lines = [
            "Процедура МойМетод()",   # 0
            "    Если А > 0 Тогда",   # 1
            "        Б = 1;",         # 2
            "    КонецЕсли;",         # 3
            "КонецПроцедуры",         # 4
        ]
        sr = _build_selection_range(lines, cursor_line=2)
        assert sr is not None
        # Innermost: current line
        assert sr.range.start.line == 2
        assert sr.range.end.line == 2
        # Parent: enclosing Если block (lines 1-3)
        assert sr.parent is not None
        assert sr.parent.range.start.line == 1
        assert sr.parent.range.end.line == 3
        # Grandparent: Процедура block (lines 0-4)
        assert sr.parent.parent is not None
        assert sr.parent.parent.range.start.line == 0
        assert sr.parent.parent.range.end.line == 4

    def test_empty_document(self) -> None:
        from onec_hbk_bsl.lsp.server import _build_selection_range

        result = _build_selection_range([], cursor_line=0)
        assert result is None

    def test_cursor_outside_any_block(self) -> None:
        from onec_hbk_bsl.lsp.server import _build_selection_range

        lines = ["А = 1;", "Б = 2;"]
        sr = _build_selection_range(lines, cursor_line=0)
        # Should at least return the current-line range
        assert sr is not None
        assert sr.range.start.line == 0
        assert sr.range.end.line == 0

    def test_english_keywords(self) -> None:
        from onec_hbk_bsl.lsp.server import _build_selection_range

        lines = [
            "Function MyFunc()",   # 0
            "    Return 0;",       # 1
            "EndFunction",         # 2
        ]
        sr = _build_selection_range(lines, cursor_line=1)
        assert sr is not None
        # Walk up to find Function block
        node = sr
        found = False
        while node:
            if node.range.start.line == 0 and node.range.end.line == 2:
                found = True
                break
            node = node.parent
        assert found


# ---------------------------------------------------------------------------
# _make_snippet helper (Iteration 1)
# ---------------------------------------------------------------------------


class TestMakeSnippet:
    def test_snippet_helper_with_params(self) -> None:
        from lsprotocol.types import InsertTextFormat

        from onec_hbk_bsl.lsp.server import _make_snippet

        insert, fmt = _make_snippet("Найти", "Найти(Знач, Кол?)")
        assert fmt == InsertTextFormat.Snippet
        assert insert == "Найти(${1:Знач}, ${2:Кол?})$0"

    def test_snippet_helper_no_params(self) -> None:
        from lsprotocol.types import InsertTextFormat

        from onec_hbk_bsl.lsp.server import _make_snippet

        insert, fmt = _make_snippet("Выполнить", "Выполнить()")
        assert fmt == InsertTextFormat.Snippet
        assert insert == "Выполнить()$0"

    def test_snippet_helper_no_signature(self) -> None:
        from lsprotocol.types import InsertTextFormat

        from onec_hbk_bsl.lsp.server import _make_snippet

        insert, fmt = _make_snippet("Количество", None)
        assert fmt == InsertTextFormat.PlainText
        assert insert == "Количество"


# ---------------------------------------------------------------------------
# _schedule_workspace_reindex helper (Iteration 5)
# ---------------------------------------------------------------------------


class TestWorkspaceReindexSingleFlight:
    def test_schedule_sets_pending_when_running(self) -> None:
        import threading

        from onec_hbk_bsl.lsp.server import _schedule_workspace_reindex

        class _LS:
            def __init__(self) -> None:
                self._reindex_lock = threading.Lock()
                self._reindex_running = True
                self._reindex_pending = False

        ls = _LS()
        _schedule_workspace_reindex(ls, "/workspace", reason="test")
        assert ls._reindex_pending is True

    def test_schedule_runs_once_when_idle(self) -> None:
        import threading
        import time

        from onec_hbk_bsl.lsp.server import _schedule_workspace_reindex

        class _Indexer:
            def __init__(self) -> None:
                self.calls = 0

            def index_workspace(self, workspace_root: str, force: bool = False) -> None:
                self.calls += 1

        class _SymbolIndex:
            def get_stats(self) -> dict[str, int]:
                return {"symbol_count": 1, "file_count": 1}

        class _LS:
            def __init__(self) -> None:
                self._reindex_lock = threading.Lock()
                self._reindex_running = False
                self._reindex_pending = False
                self.indexer = _Indexer()
                self.symbol_index = _SymbolIndex()

        ls = _LS()
        _schedule_workspace_reindex(ls, "/workspace", reason="test")
        time.sleep(0.1)
        assert ls.indexer.calls == 1
        assert ls._reindex_running is False


# ---------------------------------------------------------------------------
# _infer_type_from_content helper (Iteration 3)
# ---------------------------------------------------------------------------


class TestInferType:
    def _parse(self, content: str):
        from onec_hbk_bsl.parser.bsl_parser import BslParser
        parser = BslParser()
        return parser.parse_content(content, file_path="test.bsl")

    def test_infer_novyi_pattern(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Зап = Новый Запрос();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Зап", 0) == "Запрос"

    def test_infer_english_new(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Req = New HTTPRequest(url);\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Req", 0) == "HTTPRequest"

    def test_infer_returns_none(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "А = 1;\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("НесуществующаяПеремен", 0) is None

    def test_infer_case_insensitive(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "зап = НОВЫЙ Запрос();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("ЗАП", 0) == "Запрос"


# ---------------------------------------------------------------------------
# _node_to_dict helper (Iteration 4)
# ---------------------------------------------------------------------------


class TestNodeToDict:
    def test_node_to_dict_basic(self) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _node_to_dict

        node = MagicMock()
        node.type = "module"
        node.text = b"hello"
        node.start_point = (0, 0)
        node.end_point = (1, 5)
        node.children = []

        result = _node_to_dict(node)
        assert result["type"] == "module"
        assert result["text"] == "hello"
        assert result["start"] == [0, 0]
        assert result["end"] == [1, 5]
        assert "children" not in result

    def test_node_to_dict_max_depth(self) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _node_to_dict

        def _make_node(depth_remaining):
            node = MagicMock()
            node.type = "x"
            node.text = ""
            node.start_point = (0, 0)
            node.end_point = (0, 0)
            if depth_remaining > 0:
                child = _make_node(depth_remaining - 1)
                node.children = [child]
            else:
                node.children = []
            return node

        root = _make_node(15)  # deeper than max_depth=12
        result = _node_to_dict(root, max_depth=12)

        # Walk to depth 12 and check truncation
        def _max_depth_in_dict(d, depth=0):
            children = d.get("children", [])
            if not children:
                return depth
            return max(_max_depth_in_dict(c, depth + 1) for c in children)

        assert _max_depth_in_dict(result) <= 12


# ---------------------------------------------------------------------------
# _generate_doc_comment helper (Iteration 5)
# ---------------------------------------------------------------------------


class TestGenerateDocComment:
    def test_generates_for_procedure(self) -> None:
        from onec_hbk_bsl.lsp.server import _generate_doc_comment

        lines = ["Процедура МойМетод(А, Б)\n", "КонецПроцедуры\n"]
        result = _generate_doc_comment(lines[0], 0, lines)
        assert result is not None
        assert "МойМетод" in result
        assert "Параметры" in result
        assert "А" in result
        assert "Б" in result

    def test_skips_if_already_documented(self) -> None:
        from onec_hbk_bsl.lsp.server import _generate_doc_comment

        lines = ["// Уже есть\n", "Процедура МойМетод(А)\n", "КонецПроцедуры\n"]
        result = _generate_doc_comment(lines[1], 1, lines)
        assert result is None

    def test_returns_none_for_non_header(self) -> None:
        from onec_hbk_bsl.lsp.server import _generate_doc_comment

        lines = ["А = 1;\n"]
        result = _generate_doc_comment(lines[0], 0, lines)
        assert result is None

    def test_no_params_no_params_section(self) -> None:
        from onec_hbk_bsl.lsp.server import _generate_doc_comment

        lines = ["Функция БезПараметров()\n", "КонецФункции\n"]
        result = _generate_doc_comment(lines[0], 0, lines)
        assert result is not None
        assert "Параметры" not in result

    def test_preserves_tab_indent(self) -> None:
        from onec_hbk_bsl.lsp.server import _generate_doc_comment

        lines = ["\tПроцедура МойМетод(А)\n", "\tКонецПроцедуры\n"]
        result = _generate_doc_comment(lines[0], 0, lines)
        assert result is not None
        assert result.startswith("\t//")
        assert "\n\t//" in result


# ---------------------------------------------------------------------------
# on_type_formatting (auto-indent on Enter)
# ---------------------------------------------------------------------------


class TestOnTypeFormatting:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_indents_inside_procedure(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_type_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        # User pressed Enter after "Процедура Тест()" — cursor is on line 1 (empty)
        content = "Процедура Тест()\n\nКонецПроцедуры\n"
        ls._docs["file:///test.bsl"] = content
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 1
        params.options.tab_size = 4
        result = on_type_formatting(ls, params)
        assert result is not None
        # Should produce 4-space indent
        assert any(e.new_text == "    " for e in result)

    def test_dedents_konets_procedure(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_type_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        # КонецПроцедуры should be at indent 0
        content = "Процедура Тест()\n    КонецПроцедуры\n"
        ls._docs["file:///test.bsl"] = content
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 1
        params.options.tab_size = 4
        result = on_type_formatting(ls, params)
        assert result is not None
        assert any(e.new_text == "" for e in result)

    def test_empty_content_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_type_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///empty.bsl"
        params.position.line = 1
        params.options.tab_size = 4
        result = on_type_formatting(ls, params)
        assert result is None

    def test_nested_if_indents_body(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_type_formatting
        ls = self._make_server(tmp_path, monkeypatch)
        content = "Процедура Тест()\n    Если А > 0 Тогда\n\n    КонецЕсли;\nКонецПроцедуры\n"
        ls._docs["file:///test.bsl"] = content
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 2  # blank line inside Если
        params.options.tab_size = 4
        result = on_type_formatting(ls, params)
        assert result is not None
        assert any(e.new_text == "        " for e in result)  # 8 spaces (2 levels)


# ---------------------------------------------------------------------------
# _format_doc_comment hover rendering
# ---------------------------------------------------------------------------


class TestFormatDocComment:
    def test_strips_slashes(self) -> None:
        from onec_hbk_bsl.lsp.server import _format_doc_comment
        raw = "// Описание функции."
        result = _format_doc_comment(raw)
        assert result == "Описание функции."

    def test_params_section_as_list(self) -> None:
        from onec_hbk_bsl.lsp.server import _format_doc_comment
        raw = "// Описание.\n//\n// Параметры:\n//   А - Тип - Описание"
        result = _format_doc_comment(raw)
        assert "**Параметры:**" in result
        assert "- А - Тип - Описание" in result

    def test_blank_lines_collapsed(self) -> None:
        from onec_hbk_bsl.lsp.server import _format_doc_comment
        raw = "// А\n//\n//\n// Б"
        result = _format_doc_comment(raw)
        assert "\n\n\n" not in result
