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
