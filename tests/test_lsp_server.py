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
        from bsl_analyzer.lsp.server import _uri_to_path
        assert _uri_to_path("file:///home/user/module.bsl") == "/home/user/module.bsl"

    def test_uri_to_path_no_scheme(self) -> None:
        from bsl_analyzer.lsp.server import _uri_to_path
        assert _uri_to_path("/absolute/path.bsl") == "/absolute/path.bsl"

    def test_path_to_uri(self) -> None:
        from bsl_analyzer.lsp.server import _path_to_uri
        result = _path_to_uri("/home/user/module.bsl")
        assert result == "file:///home/user/module.bsl"

    def test_roundtrip(self) -> None:
        from bsl_analyzer.lsp.server import _path_to_uri, _uri_to_path
        path = "/some/project/module.bsl"
        assert _uri_to_path(_path_to_uri(path)) == path


# ---------------------------------------------------------------------------
# Server instantiation
# ---------------------------------------------------------------------------


class TestBslLanguageServerInit:
    def test_server_is_created(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from bsl_analyzer.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        assert ls is not None

    def test_server_has_diagnostics_engine(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        from bsl_analyzer.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        assert isinstance(ls.diagnostics_engine, DiagnosticEngine)

    def test_server_has_empty_docs_cache(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from bsl_analyzer.lsp.server import BslLanguageServer
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

        from bsl_analyzer.lsp.server import BslLanguageServer, _path_to_uri, _publish_diagnostics
        ls = BslLanguageServer()
        # Replace the publish_diagnostics method with a mock to capture calls
        ls.publish_diagnostics = MagicMock()

        uri = _path_to_uri(str(bsl))
        _publish_diagnostics(ls, uri, str(bsl))

        ls.publish_diagnostics.assert_called_once()
        call_args = ls.publish_diagnostics.call_args
        published_uri = call_args[0][0]
        assert published_uri == uri

    def test_publish_diagnostics_missing_file_no_crash(self, tmp_path: Path, monkeypatch) -> None:
        """_publish_diagnostics should swallow errors for nonexistent files."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import BslLanguageServer, _publish_diagnostics
        ls = BslLanguageServer()
        ls.publish_diagnostics = MagicMock()
        # Path does not exist — engine should raise, but _publish_diagnostics catches it
        _publish_diagnostics(ls, "file:///nonexistent.bsl", "/nonexistent.bsl")
        # Should not raise; publish_diagnostics may or may not be called


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestWordAtPosition:
    def test_word_in_middle_of_line(self) -> None:
        from bsl_analyzer.lsp.server import _word_at_position
        content = "Процедура ПолучитьЗначение()\nКонецПроцедуры\n"
        word = _word_at_position(content, 0, 15)
        assert word  # should extract some identifier

    def test_empty_content_returns_empty(self) -> None:
        from bsl_analyzer.lsp.server import _word_at_position
        assert _word_at_position("", 0, 0) == ""

    def test_line_beyond_content_returns_empty(self) -> None:
        from bsl_analyzer.lsp.server import _word_at_position
        assert _word_at_position("А = 1;\n", 99, 0) == ""

    def test_character_beyond_line_returns_empty(self) -> None:
        from bsl_analyzer.lsp.server import _word_at_position
        assert _word_at_position("А = 1;\n", 0, 999) == ""

    def test_at_word_start(self) -> None:
        from bsl_analyzer.lsp.server import _word_at_position
        content = "НайтиПоКоду()\n"
        word = _word_at_position(content, 0, 0)
        assert "НайтиПоКоду" in word or word  # extracts identifier


class TestLastIdentifier:
    def test_simple_word(self) -> None:
        from bsl_analyzer.lsp.server import _last_identifier
        assert _last_identifier("НайтиПоКоду") == "НайтиПоКоду"

    def test_after_dot(self) -> None:
        from bsl_analyzer.lsp.server import _last_identifier
        assert _last_identifier("Объект.Метод") == "Метод"

    def test_empty_string(self) -> None:
        from bsl_analyzer.lsp.server import _last_identifier
        assert _last_identifier("") == ""

    def test_ends_with_space(self) -> None:
        from bsl_analyzer.lsp.server import _last_identifier
        assert _last_identifier("Объект.") == ""


# ---------------------------------------------------------------------------
# Handler functions (called directly, bypassing LSP wire protocol)
# ---------------------------------------------------------------------------


class TestHandlerFunctions:
    """Call the LSP handler functions directly with mock params."""

    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import BslLanguageServer
        ls = BslLanguageServer()
        ls.publish_diagnostics = MagicMock()
        return ls

    def test_on_did_open_caches_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_did_open
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.text_document.text = "А = 1;\n"
        on_did_open(ls, params)
        assert ls._docs["file:///test.bsl"] == "А = 1;\n"

    def test_on_did_change_updates_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_did_change
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
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import _path_to_uri, on_did_save
        ls = self._make_server(tmp_path, monkeypatch)
        bsl = tmp_path / "module.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")
        params = MagicMock()
        params.text_document.uri = _path_to_uri(str(bsl))
        on_did_save(ls, params)
        ls.publish_diagnostics.assert_called()

    def test_on_definition_no_word_returns_none(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_definition
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

        from bsl_analyzer.lsp.server import on_definition
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

        from bsl_analyzer.lsp.server import on_hover
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_hover(ls, params)
        assert result is None

    def test_on_document_symbol_empty_index(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_document_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_document_symbol(ls, params)
        assert result == []

    def test_on_workspace_symbol_empty_query(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_workspace_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.query = "   "  # whitespace only
        result = on_workspace_symbol(ls, params)
        assert result == []

    def test_on_workspace_symbol_with_query(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_workspace_symbol
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.query = "ПолучитьЗначение"
        result = on_workspace_symbol(ls, params)
        assert isinstance(result, list)  # empty — no symbols in index

    def test_on_references_no_word(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_references
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 0
        result = on_references(ls, params)
        assert result is None

    def test_on_completion_empty_content(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_completion
        ls = self._make_server(tmp_path, monkeypatch)
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 99  # beyond content
        params.position.character = 0
        result = on_completion(ls, params)
        assert result is None

    def test_on_completion_global_prefix(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from bsl_analyzer.lsp.server import on_completion
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

        from bsl_analyzer.lsp.server import on_completion
        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "Массив.\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 8
        result = on_completion(ls, params)
        # Dot completion — returns CompletionList
        assert result is not None
