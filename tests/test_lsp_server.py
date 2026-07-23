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
    def test_lsp_diagnostic_code_is_canonical_bsl_id(self) -> None:
        from onec_hbk_bsl.lsp.server import _lsp_diagnostic_code_fields

        code, description = _lsp_diagnostic_code_fields("BSL009")
        assert code == "BSL009"
        assert description is not None
        assert description.href == "urn:onec-hbk-bsl:rule:BSL009"

    def test_diagnostics_enabled_environment_switch(self, monkeypatch) -> None:
        from onec_hbk_bsl.lsp.server import _diagnostics_enabled

        monkeypatch.delenv("BSL_DIAGNOSTICS_ENABLED", raising=False)
        assert _diagnostics_enabled() is True
        for value in ("0", "false", "NO", "off"):
            monkeypatch.setenv("BSL_DIAGNOSTICS_ENABLED", value)
            assert _diagnostics_enabled() is False

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

    def test_server_version_uses_package_version(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl import __version__
        from onec_hbk_bsl.lsp.server import BslLanguageServer

        assert BslLanguageServer().version == __version__

    def test_server_defaults_diagnostics_to_all_public_rules(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl.analysis.diagnostics import _PUBLIC_RULE_CODES
        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        assert ls.diagnostics_engine._select is None
        assert ls.diagnostics_engine._enabled_rule_codes() == frozenset(_PUBLIC_RULE_CODES)
        for code in ("BSL156", "BSL236", "BSL187", "BSL188", "BSL203", "BSL264"):
            assert ls.diagnostics_engine._rule_enabled(code)

    def test_server_has_empty_docs_cache(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        assert ls._docs == {}

    def test_server_close_closes_symbol_index(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        ls.symbol_index.close = MagicMock()  # type: ignore[method-assign]
        ls.close()
        ls.symbol_index.close.assert_called_once()

    def test_initialize_replaces_workspace_index_for_every_dependent_service(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import ClientCapabilities, InitializeParams

        import onec_hbk_bsl.lsp.server as srv

        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "initial.sqlite"))
        ls = srv.BslLanguageServer()
        roots = (tmp_path / "workspace-a", tmp_path / "workspace-b")
        for root in roots:
            root.mkdir()

        created: list[object] = []

        class _FakeIndex:
            def __init__(self, db_path: str, max_size_bytes: int) -> None:
                self.db_path = db_path
                self.max_size_bytes = max_size_bytes
                self.close = MagicMock()
                created.append(self)

        monkeypatch.setattr(srv, "SymbolIndex", _FakeIndex)
        monkeypatch.setattr(srv, "resolve_index_db_path", lambda root: f"{root}/index.sqlite")
        monkeypatch.setattr(srv, "_schedule_workspace_reindex", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(srv, "_start_branch_watcher", lambda *_args, **_kwargs: None)

        srv.on_initialize(
            ls,
            InitializeParams(capabilities=ClientCapabilities(), root_path=str(roots[0])),
        )
        context_a = ls.workspace_run_context()
        ls.doc_state.diag_result_cache["file:///stale.bsl"] = (object(), [])
        ls.doc_state.indexed_snapshot_cache["file:///stale.bsl"] = 1
        srv.on_initialize(
            ls,
            InitializeParams(capabilities=ClientCapabilities(), root_path=str(roots[1])),
        )
        context_b = ls.workspace_run_context()

        assert len(created) == 2
        assert context_a.symbol_index is created[0]
        assert context_b.symbol_index is created[1]
        assert context_b.indexer.index is context_b.symbol_index
        assert context_b.diagnostics_engine._symbol_index is context_b.symbol_index
        assert context_b.revisions.index == context_a.revisions.index + 1
        assert context_b.revisions.metadata == context_a.revisions.metadata + 1
        assert context_b.revisions.config == context_a.revisions.config + 1
        assert ls.doc_state.diag_result_cache == {}
        assert ls.doc_state.indexed_snapshot_cache == {}
        created[0].close.assert_called_once()
        created[1].close.assert_not_called()


# ---------------------------------------------------------------------------
# Document state service boundary
# ---------------------------------------------------------------------------


class TestDocumentDiagnosticsState:
    def test_close_document_cleans_all_per_uri_state(self) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.document_state import DocumentDiagnosticsState

        state = DocumentDiagnosticsState()
        uri = "file:///module.bsl"
        timer = MagicMock()
        state.docs[uri] = "А = 1;"
        state.diag_timers[uri] = timer
        state.diag_last_time[uri] = 0.12
        state.diag_result_cache[uri] = (123, [])
        state.doc_generations[uri] = 7
        state.indexed_snapshot_cache[uri] = (7, 123)
        state.published_diagnostics[uri] = (7, 123)

        popped = state.close_document(uri)

        assert popped is timer
        assert uri not in state.docs
        assert uri not in state.diag_timers
        assert uri not in state.diag_last_time
        assert uri not in state.diag_result_cache
        assert uri not in state.doc_generations
        assert uri not in state.indexed_snapshot_cache
        assert uri not in state.published_diagnostics

    def test_diag_cache_roundtrip(self) -> None:
        from onec_hbk_bsl.lsp.document_state import DocumentDiagnosticsState

        state = DocumentDiagnosticsState()
        uri = "file:///module.bsl"
        payload: list[object] = []
        state.set_diag_cache(uri, 99, payload)
        cached = state.get_diag_cache(uri)
        assert cached is not None
        assert cached[0] == 99
        assert cached[1] is payload

    def test_semantic_cache_key_includes_workspace_revisions(self) -> None:
        from onec_hbk_bsl.lsp.document_state import (
            DiagnosticCacheKey,
            DocumentDiagnosticsState,
            WorkspaceRevisions,
        )

        first = DiagnosticCacheKey(99, WorkspaceRevisions(index=1, metadata=1, config=1))
        changed_keys = (
            DiagnosticCacheKey(99, WorkspaceRevisions(index=2, metadata=1, config=1)),
            DiagnosticCacheKey(99, WorkspaceRevisions(index=1, metadata=2, config=1)),
            DiagnosticCacheKey(99, WorkspaceRevisions(index=1, metadata=1, config=2)),
        )

        for changed in changed_keys:
            state = DocumentDiagnosticsState()
            uri = "file:///module.bsl"
            state.set_diag_cache(uri, first, [])
            assert state.begin_diag_run(uri, first)[0] == "cached"
            assert state.begin_diag_run(uri, changed)[0] == "run"

    def test_stale_generation_cannot_commit_index_or_publish(self) -> None:
        import threading

        from onec_hbk_bsl.lsp.document_state import DocumentDiagnosticsState

        state = DocumentDiagnosticsState()
        uri = "file:///module.bsl"
        old_generation = state.set_doc(uri, "Старое = 1;")
        action, old_run = state.begin_diag_run(uri, "old", old_generation)
        assert action == "run"
        assert old_run is not None

        old_started = threading.Event()
        allow_old_finish = threading.Event()
        old_finished = threading.Event()
        effects: list[str] = []

        def _finish_old() -> None:
            old_started.set()
            assert allow_old_finish.wait(timeout=5)
            assert not state.finish_diag_run(uri, old_run, diagnostics=["old"])
            assert not state.index_if_current(
                uri,
                old_generation,
                hash("Старое = 1;"),
                lambda: effects.append("old-index"),
            )
            assert not state.publish_if_current(
                uri,
                old_generation,
                "old",
                lambda: effects.append("old-publish"),
            )
            old_finished.set()

        old_thread = threading.Thread(target=_finish_old)
        old_thread.start()
        assert old_started.wait(timeout=5)

        new_generation = state.set_doc(uri, "Новое = 2;")
        action, new_run = state.begin_diag_run(uri, "new", new_generation)
        assert action == "run"
        assert new_run is not None
        assert state.finish_diag_run(uri, new_run, diagnostics=["new"])
        assert state.index_if_current(
            uri,
            new_generation,
            hash("Новое = 2;"),
            lambda: effects.append("new-index"),
        )
        assert state.publish_if_current(
            uri,
            new_generation,
            "new",
            lambda: effects.append("new-publish"),
        )
        assert not state.publish_if_current(
            uri,
            new_generation,
            "new",
            lambda: effects.append("duplicate-publish"),
        )

        allow_old_finish.set()
        assert old_finished.wait(timeout=5)
        old_thread.join(timeout=5)
        assert not old_thread.is_alive()

        assert state.get_diag_cache(uri) == ("new", ["new"])
        assert effects == ["new-index", "new-publish"]

    def test_workspace_state_replaces_services_and_closes_each_index_once(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.document_state import WorkspaceState

        index_a = SimpleNamespace(close=MagicMock())
        index_b = SimpleNamespace(close=MagicMock())
        indexer_a = object()
        indexer_b = object()
        engine = SimpleNamespace(_symbol_index=index_a)
        invalidations: list[str] = []
        state = WorkspaceState(
            symbol_index=index_a,
            indexer=indexer_a,
            diagnostics_engine=engine,
            invalidate_caches=invalidations.append,
        )

        before = state.snapshot()
        after = state.replace_index(symbol_index=index_b, indexer=indexer_b)
        unchanged = state.replace_index(symbol_index=index_b, indexer=indexer_b)
        state.close()
        state.close()

        assert before.symbol_index is index_a
        assert after.symbol_index is index_b
        assert after.indexer is indexer_b
        assert after.diagnostics_engine._symbol_index is index_b
        assert after.revisions.index == before.revisions.index + 1
        assert after.revisions.metadata == before.revisions.metadata + 1
        assert unchanged.revisions == after.revisions
        assert invalidations == ["replace"]
        index_a.close.assert_called_once()
        index_b.close.assert_called_once()

    def test_workspace_revisions_are_monotonic_and_ignore_stale_writers(self) -> None:
        from types import SimpleNamespace

        from onec_hbk_bsl.lsp.document_state import WorkspaceState

        index = SimpleNamespace(close=lambda: None)
        engine = SimpleNamespace(_symbol_index=index)
        invalidations: list[str] = []
        state = WorkspaceState(
            symbol_index=index,
            indexer=object(),
            diagnostics_engine=engine,
            invalidate_caches=invalidations.append,
        )
        initial = state.snapshot().revisions
        index_only = state.mark_index_changed(expected_index=index)
        with_metadata = state.mark_index_changed(
            expected_index=index,
            metadata_changed=True,
        )
        with_config = state.mark_config_changed()

        assert index_only is not None
        assert with_metadata is not None
        assert index_only.index == initial.index + 1
        assert index_only.metadata == initial.metadata
        assert with_metadata.index == index_only.index + 1
        assert with_metadata.metadata == index_only.metadata + 1
        assert with_config.config == with_metadata.config + 1
        assert state.mark_index_changed(expected_index=object()) is None
        assert state.snapshot().revisions == with_config
        assert invalidations == ["index", "metadata", "config"]

    def test_clear_config_caches_refreshes_filesystem_views(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
            clear_config_caches,
            read_text_cached,
        )

        config_file = tmp_path / "Configuration.xml"
        config_file.write_text("A", encoding="utf-8")
        assert read_text_cached(str(config_file)) == "A"
        config_file.write_text("B", encoding="utf-8")
        assert read_text_cached(str(config_file)) == "A"

        clear_config_caches()

        assert read_text_cached(str(config_file)) == "B"


# ---------------------------------------------------------------------------
# Diagnostics publishing helper (internal)
# ---------------------------------------------------------------------------


class TestPublishDiagnostics:
    def test_stale_run_finishing_last_does_not_publish_over_latest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp import server as srv
        from onec_hbk_bsl.lsp.server import BslLanguageServer, _publish_diagnostics

        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        uri = (tmp_path / "module.bsl").as_uri()
        old_content = "Старое = 1;"
        new_content = "Новое = 2;"
        ls.doc_state.set_doc(uri, old_content)

        old_started = threading.Event()
        allow_old_finish = threading.Event()
        old_finished = threading.Event()

        def _build_inner(
            _ls: object,
            _uri: str,
            _path: str,
            *,
            workspace_context: object,
            content_override: str,
        ) -> list:
            if content_override == old_content:
                old_started.set()
                assert allow_old_finish.wait(timeout=5)
            return []

        monkeypatch.setattr(srv, "_build_lsp_diagnostics_inner", _build_inner)
        monkeypatch.setattr(srv, "_get_lsp_document_context", lambda *_a, **_k: None)

        def _publish_old() -> None:
            _publish_diagnostics(ls, uri, str(tmp_path / "module.bsl"))
            old_finished.set()

        old_thread = threading.Thread(target=_publish_old)
        old_thread.start()
        assert old_started.wait(timeout=5)

        ls.doc_state.set_doc(uri, new_content)
        _publish_diagnostics(ls, uri, str(tmp_path / "module.bsl"))
        _publish_diagnostics(ls, uri, str(tmp_path / "module.bsl"))
        allow_old_finish.set()
        assert old_finished.wait(timeout=5)
        old_thread.join(timeout=5)

        assert not old_thread.is_alive()
        ls.text_document_publish_diagnostics.assert_called_once()
        cached = ls.doc_state.get_diag_cache(uri)
        assert cached is not None
        assert cached[0].content_hash == hash(new_content)

    def test_workspace_revision_change_discards_inflight_result(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp import server as srv
        from onec_hbk_bsl.lsp.server import BslLanguageServer, _publish_diagnostics

        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        uri = (tmp_path / "module.bsl").as_uri()
        content = "Значение = 1;"
        ls.doc_state.set_doc(uri, content)

        old_started = threading.Event()
        allow_old_finish = threading.Event()
        old_finished = threading.Event()
        calls = 0

        def _build_inner(
            _ls: object,
            _uri: str,
            _path: str,
            *,
            workspace_context: object,
            content_override: str,
        ) -> list:
            nonlocal calls
            calls += 1
            if calls == 1:
                old_started.set()
                assert allow_old_finish.wait(timeout=5)
            return []

        monkeypatch.setattr(srv, "_build_lsp_diagnostics_inner", _build_inner)
        monkeypatch.setattr(srv, "_get_lsp_document_context", lambda *_a, **_k: None)

        def _publish_old() -> None:
            _publish_diagnostics(ls, uri, str(tmp_path / "module.bsl"))
            old_finished.set()

        old_thread = threading.Thread(target=_publish_old)
        old_thread.start()
        assert old_started.wait(timeout=5)

        current_revisions = ls.workspace_state.mark_config_changed()
        _publish_diagnostics(ls, uri, str(tmp_path / "module.bsl"))
        allow_old_finish.set()
        assert old_finished.wait(timeout=5)
        old_thread.join(timeout=5)

        assert not old_thread.is_alive()
        assert calls == 2
        ls.text_document_publish_diagnostics.assert_called_once()
        cached = ls.doc_state.get_diag_cache(uri)
        assert cached is not None
        assert cached[0].revisions == current_revisions

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
        """_publish_diagnostics should not raise for nonexistent files (Problems still update)."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _publish_diagnostics

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        _publish_diagnostics(ls, "file:///nonexistent.bsl", "/nonexistent.bsl")
        ls.text_document_publish_diagnostics.assert_called_once()

    def test_publish_diagnostics_engine_failure_returns_failure_diagnostic(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When engine diagnostics raises, publish a single DiagnosticsFailure."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "mod.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")

        from unittest.mock import MagicMock

        from lsprotocol.types import DiagnosticSeverity

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, _publish_diagnostics

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()

        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("boom")

        ls.diagnostics_engine.check_snapshot = _boom  # type: ignore[method-assign]
        ls.diagnostics_engine.check_content = _boom  # type: ignore[method-assign]

        uri = _path_to_uri(str(bsl))
        ls._docs[uri] = bsl.read_text(encoding="utf-8")
        _publish_diagnostics(ls, uri, str(bsl))
        params = ls.text_document_publish_diagnostics.call_args[0][0]
        assert len(params.diagnostics) == 1
        d0 = params.diagnostics[0]
        assert d0.severity == DiagnosticSeverity.Error
        assert "boom" in d0.message
        data = d0.data
        assert isinstance(data, dict) and data.get("bsl") == "BSL-LSP-ERR"
        assert data.get("rule_description") == "Ошибка выполнения диагностики"

    def test_publish_diagnostics_unused_separate_source_and_information(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Dead-code hints use rule-scoped Problems source and Warning severity."""
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
        assert dead[0].code == "BSL-DEAD"
        assert dead[0].source == "onec-hbk-bsl · BSL-DEAD"
        assert dead[0].severity == DiagnosticSeverity.Warning
        assert dead[0].tags and DiagnosticTag.Unnecessary in dead[0].tags
        dead_data = dead[0].data
        assert isinstance(dead_data, dict)
        assert dead_data.get("rule_description") == "Неиспользуемая функция или метод"
        lint_sources = {d.source for d in params.diagnostics if not _is_dead(d)}
        assert all(s.startswith("onec-hbk-bsl · BSL") for s in lint_sources)

    def test_document_diagnostic_pull_returns_report(self, tmp_path: Path, monkeypatch) -> None:
        """textDocument/diagnostic returns RelatedFullDocumentDiagnosticReport (pull model)."""
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "pull.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")

        from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, on_document_diagnostic

        ls = BslLanguageServer()
        uri = _path_to_uri(str(bsl))
        ls._docs[uri] = bsl.read_text(encoding="utf-8")
        params = DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri))
        report = on_document_diagnostic(ls, params)
        assert report.kind == "full"
        assert isinstance(report.items, (list, tuple))

    def test_document_diagnostic_disabled_returns_empty_without_running_engine(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, on_document_diagnostic

        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        monkeypatch.setenv("BSL_DIAGNOSTICS_ENABLED", "0")
        bsl = tmp_path / "disabled.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")
        ls = BslLanguageServer()
        ls.diagnostics_engine.check_content = MagicMock()  # type: ignore[method-assign]
        uri = _path_to_uri(str(bsl))
        params = DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri))

        report = on_document_diagnostic(ls, params)

        assert report.items == []
        ls.diagnostics_engine.check_content.assert_not_called()

    def test_document_diagnostic_data_contains_russian_rule_description(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "localized-description.bsl"
        content = "Процедура Тест()\n\tА = 1\nКонецПроцедуры\n"
        bsl.write_text(content, encoding="utf-8")

        from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, on_document_diagnostic

        ls = BslLanguageServer()
        uri = _path_to_uri(str(bsl))
        ls._docs[uri] = content
        params = DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri))
        report = on_document_diagnostic(ls, params)

        descriptions = {
            d.data["bsl"]: d.data["rule_description"]
            for d in report.items
            if isinstance(getattr(d, "data", None), dict) and "rule_description" in d.data
        }
        assert descriptions["BSL007"] == "Неиспользуемая локальная переменная"
        assert descriptions["BSL030"] == 'Выражение должно заканчиваться символом ";"'

    def test_large_pull_diagnostics_returns_immediately_and_refreshes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

        from onec_hbk_bsl.lsp import server as srv
        from onec_hbk_bsl.lsp.server import BslLanguageServer, _path_to_uri, on_document_diagnostic

        captured: dict[str, object] = {}

        class _CapturedThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                captured["target"] = target
                captured["args"] = args
                captured["kwargs"] = kwargs or {}

            def start(self):
                captured["started"] = True

        monkeypatch.setattr(srv, "_ASYNC_PULL_DIAGNOSTICS_MIN_BYTES", 1)
        monkeypatch.setattr(srv.threading, "Thread", _CapturedThread)
        monkeypatch.setattr(srv, "_build_lsp_diagnostics_inner", MagicMock(return_value=[]))

        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        bsl = tmp_path / "large.bsl"
        content = "Процедура Тест()\nКонецПроцедуры\n"
        bsl.write_text(content, encoding="utf-8")
        uri = _path_to_uri(str(bsl))

        ls = BslLanguageServer()
        ls.client_pull_diagnostics = True
        ls.client_diagnostic_refresh = True
        ls.workspace_diagnostic_refresh = MagicMock()  # type: ignore[method-assign]
        ls._docs[uri] = content

        params = DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri))
        report = on_document_diagnostic(ls, params)

        assert report.items == []
        assert captured["started"] is True
        srv._build_lsp_diagnostics_inner.assert_not_called()

        target = captured["target"]
        assert callable(target)
        target()

        srv._build_lsp_diagnostics_inner.assert_called_once()
        ls.workspace_diagnostic_refresh.assert_called_once()


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

    def test_large_documents_skip_sync_local_scope_parse(self) -> None:
        from onec_hbk_bsl.lsp.server import _allow_sync_local_scope_parse

        assert _allow_sync_local_scope_parse("А = 1;\n")
        assert not _allow_sync_local_scope_parse("А" * 1_000_001)

    def test_large_document_uses_background_local_scope_cache(self, tmp_path, monkeypatch) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition, on_did_open, on_hover

        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        uri = "file:///large.bsl"
        content = (
            "Процедура Большая(Параметр)\n"
            + ("// длинный комментарий\n" * 60_000)
            + "    Параметр = Параметр;\n"
            + "КонецПроцедуры\n"
        )
        open_params = MagicMock()
        open_params.text_document.uri = uri
        open_params.text_document.text = content

        on_did_open(ls, open_params)

        hover_params = MagicMock()
        hover_params.text_document.uri = uri
        hover_params.position.line = 0
        hover_params.position.character = content.splitlines()[0].index("Параметр") + 2
        hover = on_hover(ls, hover_params)
        assert hover is not None
        assert "Параметр" in str(hover.contents)

        definition = on_definition(ls, hover_params)
        assert definition
        assert definition[0].target_selection_range.start.line == 0

    def test_large_document_code_lens_reuses_parsed_document_cache(
        self, tmp_path, monkeypatch
    ) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_code_lens, on_did_open
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        uri = "file:///large.bsl"
        content = (
            "Процедура Большая(Параметр)\n"
            + ("// длинный комментарий\n" * 60_000)
            + "КонецПроцедуры\n"
        )
        open_params = MagicMock()
        open_params.text_document.uri = uri
        open_params.text_document.text = content
        on_did_open(ls, open_params)

        def fail_parse_content(self, content: str, file_path: str = "<string>") -> object:
            raise AssertionError("code lens should reuse cached parse tree")

        monkeypatch.setattr(BslParser, "parse_content", fail_parse_content)

        lens_params = MagicMock()
        lens_params.text_document.uri = uri
        result = on_code_lens(ls, lens_params)
        assert result

    def test_small_document_reuses_shared_lsp_context_for_hover_and_definition(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition, on_did_open, on_hover
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        uri = "file:///small.bsl"
        content = "Процедура Тест(Параметр)\n    Параметр = 1;\nКонецПроцедуры\n"
        open_params = MagicMock()
        open_params.text_document.uri = uri
        open_params.text_document.text = content
        on_did_open(ls, open_params)

        original_parse_content = BslParser.parse_content
        parse_calls = 0

        def counted_parse_content(self, content: str, file_path: str = "<string>") -> object:
            nonlocal parse_calls
            parse_calls += 1
            return original_parse_content(self, content, file_path=file_path)

        monkeypatch.setattr(BslParser, "parse_content", counted_parse_content)

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 1
        params.position.character = content.splitlines()[1].index("Параметр") + 2

        definition = on_definition(ls, params)
        hover = on_hover(ls, params)

        assert definition
        assert hover is not None
        assert parse_calls == 1

    def test_lsp_diagnostics_reuse_shared_context_after_hover(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _build_lsp_diagnostics_inner, on_did_open, on_hover
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        path = tmp_path / "small.bsl"
        content = "Процедура Тест(Параметр)\n    Параметр = 1;\nКонецПроцедуры\n"
        path.write_text(content, encoding="utf-8")
        uri = path.as_uri()

        open_params = MagicMock()
        open_params.text_document.uri = uri
        open_params.text_document.text = content
        on_did_open(ls, open_params)

        hover_params = MagicMock()
        hover_params.text_document.uri = uri
        hover_params.position.line = 1
        hover_params.position.character = content.splitlines()[1].index("Параметр") + 2
        assert on_hover(ls, hover_params) is not None

        def fail_parse_content(self, content: str, file_path: str = "<string>") -> object:
            raise AssertionError("diagnostics should reuse the shared LSP snapshot")

        monkeypatch.setattr(BslParser, "parse_content", fail_parse_content)

        diagnostics = _build_lsp_diagnostics_inner(ls, uri, str(path))
        assert isinstance(diagnostics, list)

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

    def test_document_symbols_use_open_document_without_index(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_did_open, on_document_symbol

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        uri = (tmp_path / "unsaved.bsl").as_uri()
        params = MagicMock()
        params.text_document.uri = uri
        params.text_document.text = (
            "Процедура ОткрытаяПроцедура(Параметр) Экспорт\n"
            "КонецПроцедуры\n"
            "\n"
            "Функция ОткрытаяФункция()\n"
            "    Возврат 1;\n"
            "КонецФункции\n"
        )
        on_did_open(ls, params)

        symbol_params = MagicMock()
        symbol_params.text_document.uri = uri
        symbols = on_document_symbol(ls, symbol_params)

        assert [symbol.name for symbol in symbols] == [
            "ОткрытаяПроцедура",
            "ОткрытаяФункция",
        ]
        assert symbols[0].detail == "Процедура ОткрытаяПроцедура(Параметр) Экспорт"
        assert symbols[0].range.start.line == 0
        assert symbols[1].range.start.line == 3

    def test_document_symbols_reflect_unsaved_changes(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_did_change, on_did_open, on_document_symbol

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        uri = (tmp_path / "changed.bsl").as_uri()
        open_params = MagicMock()
        open_params.text_document.uri = uri
        open_params.text_document.text = "Процедура СтароеИмя()\nКонецПроцедуры\n"
        on_did_open(ls, open_params)

        change_params = MagicMock()
        change_params.text_document.uri = uri
        change = MagicMock()
        change.text = "Процедура НовоеИмя()\nКонецПроцедуры\n"
        change_params.content_changes = [change]
        on_did_change(ls, change_params)

        symbol_params = MagicMock()
        symbol_params.text_document.uri = uri
        symbols = on_document_symbol(ls, symbol_params)

        assert [symbol.name for symbol in symbols] == ["НовоеИмя"]

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

    def test_on_did_save_pull_diagnostics_skips_direct_index_file(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _path_to_uri, on_did_save

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        ls.indexer.index_file = MagicMock()  # type: ignore[method-assign]
        bsl = tmp_path / "module.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")
        params = MagicMock()
        params.text_document.uri = _path_to_uri(str(bsl))
        params.text = "А = 2;\n"

        on_did_save(ls, params)

        ls.indexer.index_file.assert_not_called()
        ls.text_document_publish_diagnostics.assert_not_called()
        assert ls._docs[params.text_document.uri] == "А = 2;\n"

    def test_on_did_save_with_diagnostics_disabled_still_updates_index(
        self, tmp_path, monkeypatch
    ) -> None:
        import threading
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import _path_to_uri, on_did_save

        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args

            def start(self):
                self._target(*self._args)

        monkeypatch.setattr(threading, "Thread", _SyncThread)
        monkeypatch.setenv("BSL_DIAGNOSTICS_ENABLED", "false")
        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        ls.indexer.index_file = MagicMock(return_value={})  # type: ignore[method-assign]
        bsl = tmp_path / "module.bsl"
        bsl.write_text("А = 1;\n", encoding="utf-8")
        params = MagicMock()
        params.text_document.uri = _path_to_uri(str(bsl))
        params.text = "А = 2;\n"

        on_did_save(ls, params)

        ls.indexer.index_file.assert_called_once_with(str(bsl))
        ls.text_document_publish_diagnostics.assert_not_called()

    def test_pull_diagnostics_indexes_from_snapshot_once_without_index_file(
        self, tmp_path, monkeypatch
    ) -> None:
        import threading
        from unittest.mock import MagicMock

        from lsprotocol.types import DocumentDiagnosticParams, TextDocumentIdentifier

        from onec_hbk_bsl.lsp.server import _path_to_uri, on_document_diagnostic

        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args

            def start(self):
                self._target(*self._args)

        monkeypatch.setattr(threading, "Thread", _SyncThread)

        ls = self._make_server(tmp_path, monkeypatch)
        ls.client_pull_diagnostics = True
        ls.indexer.index_file = MagicMock()  # type: ignore[method-assign]
        ls.indexer.index_snapshot = MagicMock(return_value={"symbols": 1, "calls": 0})  # type: ignore[method-assign]
        bsl = tmp_path / "module.bsl"
        content = "Процедура Тест()\nКонецПроцедуры\n"
        bsl.write_text(content, encoding="utf-8")
        uri = _path_to_uri(str(bsl))
        ls._docs[uri] = content
        params = DocumentDiagnosticParams(text_document=TextDocumentIdentifier(uri=uri))

        on_document_diagnostic(ls, params)
        on_document_diagnostic(ls, params)

        ls.indexer.index_file.assert_not_called()
        ls.indexer.index_snapshot.assert_called_once()

    def test_on_did_close_cleans_document_state_and_cancels_timer(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_did_close

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///test.bsl"
        timer = MagicMock()
        ls._docs[uri] = "А = 1;\n"
        ls._diag_timers[uri] = timer
        ls._diag_last_time[uri] = 0.42
        ls._diag_result_cache[uri] = (123, [])
        params = MagicMock()
        params.text_document.uri = uri

        on_did_close(ls, params)

        assert uri not in ls._docs
        assert uri not in ls._diag_timers
        assert uri not in ls._diag_last_time
        assert uri not in ls._diag_result_cache
        timer.cancel.assert_called_once()
        ls.text_document_publish_diagnostics.assert_called_once()
        published = ls.text_document_publish_diagnostics.call_args[0][0]
        assert published.uri == uri
        assert published.diagnostics == []

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

    def test_chained_workspace_call_has_hover_and_definition(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition, on_hover

        ls = self._make_server(tmp_path, monkeypatch)
        library = tmp_path / "Library.bsl"
        library.write_text(
            "// Возвращает служебный модуль.\n"
            "Функция УникальныйЧленЦепочки() Экспорт\n"
            "    Возврат Неопределено;\n"
            "КонецФункции\n",
            encoding="utf-8",
        )
        assert ls.indexer.index_file(str(library))["symbols"] == 1

        content = "ПолучитьФасад().УникальныйЧленЦепочки();\n"
        caller = tmp_path / "Caller.bsl"
        uri = caller.as_uri()
        ls._docs[uri] = content
        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.index("УникальныйЧленЦепочки") + 2

        hover = on_hover(ls, params)
        definition = on_definition(ls, params)

        assert hover is not None
        assert "Возвращает служебный модуль" in str(hover.contents)
        assert definition and definition[0].target_uri == library.as_uri()
        assert definition[0].target_selection_range.start.line == 1

    def test_chained_workspace_call_does_not_resolve_private_symbol(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_definition, on_hover

        ls = self._make_server(tmp_path, monkeypatch)
        library = tmp_path / "Library.bsl"
        library.write_text(
            "Функция УникальныйПриватныйЧлен()\n    Возврат Неопределено;\nКонецФункции\n",
            encoding="utf-8",
        )
        assert ls.indexer.index_file(str(library))["symbols"] == 1

        content = "НеизвестныйОбъект.УникальныйПриватныйЧлен();\n"
        uri = (tmp_path / "Caller.bsl").as_uri()
        ls._docs[uri] = content
        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.index("УникальныйПриватныйЧлен") + 2

        assert on_hover(ls, params) is None
        assert on_definition(ls, params) is None

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
        ls.symbol_index.find_meta_object = lambda name: (
            {"name": name} if name == "Контрагенты" else None
        )
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

    def test_on_signature_help_platform_function_active_param(self, tmp_path, monkeypatch) -> None:
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

    def test_call_hierarchy_incoming_caches_repeated_caller_lookups(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_call_hierarchy_incoming

        ls = self._make_server(tmp_path, monkeypatch)
        ls.symbol_index.find_callers = lambda name, limit=200: [  # type: ignore[method-assign]
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 3,
                "caller_character": 10,
                "caller_name": "ОбработатьЗаказ",
                "callee_name": "Цель",
            },
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 7,
                "caller_character": 12,
                "caller_name": "ОбработатьЗаказ",
                "callee_name": "Цель",
            },
        ]
        calls = {"count": 0}

        def _find_symbol(name, limit=20, file_filter=None, fuzzy=False):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if name == "ОбработатьЗаказ":
                return [
                    {
                        "name": "ОбработатьЗаказ",
                        "kind": "function",
                        "file_path": "/workspace/a.bsl",
                        "line": 1,
                        "character": 0,
                        "end_line": 5,
                        "end_character": 0,
                        "signature": "Function ОбработатьЗаказ()",
                    }
                ]
            return []

        ls.symbol_index.find_symbol = _find_symbol  # type: ignore[method-assign]

        params = MagicMock()
        params.item.name = "Цель"
        result = on_call_hierarchy_incoming(ls, params)
        assert result is not None
        assert len(result) == 2
        assert calls["count"] == 1

    def test_call_hierarchy_outgoing_caches_repeated_callee_lookups(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_call_hierarchy_outgoing

        ls = self._make_server(tmp_path, monkeypatch)
        ls.symbol_index.find_callees = lambda caller_file, caller_name=None, caller_line=None: [  # type: ignore[method-assign]
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 3,
                "caller_character": 10,
                "callee_name": "ЗаписатьЛог",
            },
            {
                "caller_file": "/workspace/a.bsl",
                "caller_line": 7,
                "caller_character": 12,
                "callee_name": "ЗаписатьЛог",
            },
        ]
        calls = {"count": 0}

        def _find_symbol(name, limit=20, file_filter=None, fuzzy=False):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if name == "ЗаписатьЛог":
                return [
                    {
                        "name": "ЗаписатьЛог",
                        "kind": "procedure",
                        "file_path": "/workspace/log.bsl",
                        "line": 10,
                        "character": 0,
                        "end_line": 12,
                        "end_character": 0,
                        "signature": "Procedure ЗаписатьЛог()",
                    }
                ]
            return []

        ls.symbol_index.find_symbol = _find_symbol  # type: ignore[method-assign]

        params = MagicMock()
        params.item.name = "ОбработатьЗаказ"
        params.item.uri = "file:///workspace/a.bsl"
        result = on_call_hierarchy_outgoing(ls, params)
        assert result is not None
        assert len(result) == 2
        assert calls["count"] == 1

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

    def test_on_completion_ignores_workspace_index_failure(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion

        ls = self._make_server(tmp_path, monkeypatch)
        ls.symbol_index.find_symbol = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("index unavailable")
        )
        ls._docs["file:///test.bsl"] = "Сообщить\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 0
        params.position.character = 8

        result = on_completion(ls, params)

        assert result is not None
        assert result.items is not None

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

    def test_on_completion_metadata_chain_uses_base_object(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_completion

        ls = self._make_server(tmp_path, monkeypatch)
        uri = "file:///test.bsl"
        ls._docs[uri] = "Справочники.Контрагенты.Товары.Су\n"

        ls.symbol_index.has_metadata = lambda: True
        ls.symbol_index.find_meta_object = lambda name: (
            {"name": name} if name == "Контрагенты" else None
        )
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
        code = "Процедура Тест()\nКонецПроцедуры"
        ls._docs["file:///test.bsl"] = code
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        result = on_formatting(ls, params)
        assert result == []

    def test_format_on_save_recovers_multiline_query_string_indent(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_formatting

        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = (
            "// &НаСервере\n"
            "Процедура ДобавитьВычисляемоеПолеОбработкаПриглашений(СхемаКомпоновкиДанных)\n"
            "\t\n"
            "\tВыражениеПоля =\n"
            '\t\t"\tВЫБОР\n'
            "\t\t\t|\t\tКОГДА Экстраверт = Истина ТОГДА\n"
            '\t\t\t\t|\t\t\t""Автоматически""\n'
            "\t\t\t\t|\t\tИНАЧЕ\n"
            '\t\t\t\t|\t\t\t""Контрагентом вручную""\n'
            '\t\t\t\t|\tКОНЕЦ";\n'
            "\t\t\n"
            "\t\tВычисляемоеПоле = СхемаКомпоновкиДанных.ВычисляемыеПоля.Добавить();\n"
            '\t\tВычисляемоеПоле.ПутьКДанным = "ОбработкаПриглашений";\n'
            "\t\tВычисляемоеПоле.Выражение = ВыражениеПоля;\n"
            "\t\t\n"
            "\tКонецПроцедуры\n"
        )
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        params.options.insert_spaces = False

        result = on_formatting(ls, params)

        assert result is not None
        assert len(result) == 1
        assert "\n\t\t\t|\t\tКОГДА" not in result[0].new_text
        assert "\n\t\t|\t\tКОГДА" in result[0].new_text
        assert "\n\t\tВычисляемоеПоле =" not in result[0].new_text
        assert "\n\tВычисляемоеПоле =" in result[0].new_text
        assert result[0].new_text.endswith("КонецПроцедуры")

    def test_range_formatting(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import Position, Range

        from onec_hbk_bsl.lsp.server import on_range_formatting

        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "процедура Тест()\nконецпроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.options.tab_size = 4
        params.range = Range(
            start=Position(line=0, character=0), end=Position(line=0, character=20)
        )
        result = on_range_formatting(ls, params)
        assert result is not None

    def test_range_formatting_end_exclusive_does_not_touch_next_line(
        self, tmp_path, monkeypatch
    ) -> None:
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
        ls._docs["file:///test.bsl"] = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        result = on_folding_range(ls, params)
        assert result is not None
        assert any(r.start_line == 0 and r.end_line == 2 for r in result)

    def test_folding_region(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_folding_range

        ls = self._make_server(tmp_path, monkeypatch)
        ls._docs["file:///test.bsl"] = "#Область МояОбласть\nА = 1;\n#КонецОбласти\n"
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

    def test_semantic_tokens_znach_val_are_keywords_not_variables(
        self, tmp_path, monkeypatch
    ) -> None:
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

    def test_semantic_tokens_logical_operators_case_insensitive(
        self, tmp_path, monkeypatch
    ) -> None:
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
# Rename Symbol
# ---------------------------------------------------------------------------


class TestRenameSymbol:
    def _make_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_prepare_rename_uses_open_document_symbols_without_index(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_prepare_rename

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "module.bsl").as_uri()
        content = "Процедура СтароеИмя()\nКонецПроцедуры\n"
        ls._docs[uri] = content

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.splitlines()[0].index("СтароеИмя") + 2

        result = on_prepare_rename(ls, params)

        assert result is not None
        assert result.start.character == content.splitlines()[0].index("СтароеИмя")
        assert result.end.character == result.start.character + len("СтароеИмя")

    def test_rename_open_document_method_and_calls_without_renaming_variables(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_rename

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "module.bsl").as_uri()
        content = "Процедура СтароеИмя()\n\tСтароеИмя = 1;\n\tСтароеИмя();\nКонецПроцедуры\n"
        ls._docs[uri] = content

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.splitlines()[0].index("СтароеИмя") + 2
        params.new_name = "НовоеИмя"

        result = on_rename(ls, params)

        assert result is not None
        edits = result.changes[uri]
        ranges = {(edit.range.start.line, edit.range.start.character) for edit in edits}
        assert ranges == {
            (0, content.splitlines()[0].index("СтароеИмя")),
            (2, content.splitlines()[2].index("СтароеИмя")),
        }
        assert {edit.new_text for edit in edits} == {"НовоеИмя"}

    def test_rename_uses_utf16_exact_spans_after_non_bmp_text(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.analysis.lsp_positions import utf16_len
        from onec_hbk_bsl.lsp.server import on_rename

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "unicode.bsl").as_uri()
        content = 'Процедура СтароеИмя()\n    Текст = "😀"; СтароеИмя();\nКонецПроцедуры\n'
        ls._docs[uri] = content
        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.splitlines()[0].index("СтароеИмя") + 2
        params.new_name = "НовоеИмя"

        result = on_rename(ls, params)

        assert result is not None
        call_edit = next(edit for edit in result.changes[uri] if edit.range.start.line == 1)
        prefix = content.splitlines()[1].split("СтароеИмя", 1)[0]
        assert call_edit.range.start.character == utf16_len(prefix)
        assert call_edit.range.end.character == utf16_len(prefix + "СтароеИмя")

    def test_rename_rejects_invalid_new_identifier(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_rename

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "module.bsl").as_uri()
        content = "Процедура СтароеИмя()\nКонецПроцедуры\n"
        ls._docs[uri] = content

        params = MagicMock()
        params.text_document.uri = uri
        params.position.line = 0
        params.position.character = content.splitlines()[0].index("СтароеИмя") + 2
        params.new_name = "123Нельзя"

        assert on_rename(ls, params) is None


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

    def test_code_action_extracts_selected_statements_to_procedure(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import Position, Range

        from onec_hbk_bsl.lsp.server import on_code_action

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "extract.bsl").as_uri()
        content = "Процедура Тест()\n\tА = 1;\n\tСообщить(А);\nКонецПроцедуры\n"
        ls._docs[uri] = content

        params = MagicMock()
        params.text_document.uri = uri
        params.context.diagnostics = []
        params.range = Range(
            start=Position(line=1, character=0),
            end=Position(line=3, character=0),
        )

        result = on_code_action(ls, params)

        assert result is not None
        action = next(action for action in result if action.title == "Извлечь в процедуру")
        edits = action.edit.changes[uri]
        assert edits[0].new_text == "\tИзвлеченныйФрагмент();"
        assert "Процедура ИзвлеченныйФрагмент()" in edits[1].new_text
        assert "\tА = 1;" in edits[1].new_text
        assert "\tСообщить(А);" in edits[1].new_text

    def test_code_action_extracts_selected_expression_to_function(
        self, tmp_path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from lsprotocol.types import Position, Range

        from onec_hbk_bsl.lsp.server import on_code_action

        ls = self._make_server(tmp_path, monkeypatch)
        uri = (tmp_path / "extract-function.bsl").as_uri()
        content = "Процедура Тест()\n\tРезультат = А + Б;\nКонецПроцедуры\n"
        ls._docs[uri] = content
        line = content.splitlines()[1]
        start = line.index("А + Б")

        params = MagicMock()
        params.text_document.uri = uri
        params.context.diagnostics = []
        params.range = Range(
            start=Position(line=1, character=start),
            end=Position(line=1, character=start + len("А + Б")),
        )

        result = on_code_action(ls, params)

        assert result is not None
        action = next(action for action in result if action.title == "Извлечь в функцию")
        edits = action.edit.changes[uri]
        assert edits[0].new_text == "ИзвлеченнаяФункция()"
        assert "Функция ИзвлеченнаяФункция()" in edits[1].new_text
        assert "\tВозврат А + Б;" in edits[1].new_text


# ---------------------------------------------------------------------------
# Selection Range
# ---------------------------------------------------------------------------


class TestSelectionRange:
    """Tests for _build_selection_range helper."""

    def test_procedure_block(self) -> None:
        from onec_hbk_bsl.lsp.server import _build_selection_range

        lines = [
            "Процедура МойМетод()",  # 0
            "    Если А > 0 Тогда",  # 1
            "        Б = 1;",  # 2
            "    КонецЕсли;",  # 3
            "КонецПроцедуры",  # 4
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
            "Function MyFunc()",  # 0
            "    Return 0;",  # 1
            "EndFunction",  # 2
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
                from types import SimpleNamespace

                self._reindex_lock = threading.Lock()
                self._reindex_running = False
                self._reindex_pending = False
                self.indexer = _Indexer()
                self.symbol_index = _SymbolIndex()
                self.workspace_state = SimpleNamespace(mark_index_changed=lambda **_kwargs: None)

            def workspace_run_context(self):
                from types import SimpleNamespace

                return SimpleNamespace(
                    indexer=self.indexer,
                    symbol_index=self.symbol_index,
                )

        ls = _LS()
        _schedule_workspace_reindex(ls, "/workspace", reason="test")
        time.sleep(0.1)
        assert ls.indexer.calls == 1
        assert ls._reindex_running is False

    def test_successful_reindex_requests_pull_diagnostic_refresh(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp import server as srv
        from onec_hbk_bsl.lsp.server import BslLanguageServer, _schedule_workspace_reindex

        class _SyncThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                self._target(*self._args, **self._kwargs)

        monkeypatch.setattr(srv.threading, "Thread", _SyncThread)
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        ls = BslLanguageServer()
        ls.client_pull_diagnostics = True
        ls.client_diagnostic_refresh = True
        ls.workspace_diagnostic_refresh = MagicMock()  # type: ignore[method-assign]
        ls.indexer.index_workspace = MagicMock()  # type: ignore[method-assign]

        _schedule_workspace_reindex(ls, str(tmp_path), reason="test")

        ls.indexer.index_workspace.assert_called_once_with(str(tmp_path), force=False)
        ls.workspace_diagnostic_refresh.assert_called_once()
        assert ls._reindex_running is False


class TestStatusAndReindexContract:
    def _make_status_server(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer

        ls = BslLanguageServer()
        ls.text_document_publish_diagnostics = MagicMock()
        return ls

    def test_on_bsl_status_includes_size_and_reindex_state(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.lsp.server import on_bsl_status

        ls = self._make_status_server(tmp_path, monkeypatch)
        ls.symbol_index.upsert_file(
            "/workspace/demo.bsl",
            [
                {
                    "name": "Функция1",
                    "line": 1,
                    "character": 0,
                    "end_line": 3,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": True,
                    "container": None,
                    "signature": "Function Функция1()",
                    "doc_comment": "",
                }
            ],
            [],
        )
        ls._reindex_running = True
        ls._reindex_pending = False

        result = on_bsl_status(ls, {})
        assert result["index_mode"] == "full"
        assert result["ready"] is True
        assert result["indexing"] is True
        assert result["reindex_running"] is True
        assert result["reindex_pending"] is False
        assert result["index_size_bytes"] == (
            result["db_size_bytes"] + result["wal_size_bytes"] + result["shm_size_bytes"]
        )
        assert result["index_size_bytes"] > 0
        assert result["index_revision"] >= 1
        assert result["metadata_revision"] >= 1
        assert result["config_revision"] >= 1

    def test_workspace_index_mode_reads_project_config(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.lsp.server import _workspace_index_mode

        monkeypatch.delenv("BSL_INDEX_MODE", raising=False)
        (tmp_path / "onec-hbk-bsl.toml").write_text('index-mode = "symbols"\n', encoding="utf-8")

        assert _workspace_index_mode(str(tmp_path)) == "symbols"

    def test_reindex_workspace_rejects_off_mode(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.lsp.server import on_bsl_reindex_workspace

        ls = self._make_status_server(tmp_path, monkeypatch)
        ls.index_mode = "off"

        result = on_bsl_reindex_workspace(ls, {"root": str(tmp_path)})

        assert result["success"] is False
        assert "disabled" in result["error"]

    def test_on_bsl_reindex_workspace_reports_started_not_complete(
        self, tmp_path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.lsp.server import on_bsl_reindex_workspace

        ls = self._make_status_server(tmp_path, monkeypatch)
        ls.indexer.index_workspace = lambda root, force=True: None  # type: ignore[method-assign]
        result = on_bsl_reindex_workspace(ls, {"root": str(tmp_path)})
        assert result["success"] is True
        assert result["started"] is True
        assert result["indexing"] is True


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

    def test_infer_nested_access_chain_global_manager(self) -> None:
        # Справочники.Организации.НайтиПоКоду(...) nests the access chain
        # (access(access(identifier), ".", property)) — the outer `access`
        # node has no direct `identifier` child at all.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Орг = Справочники.Организации.НайтиПоКоду(Код);\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Орг", 0) == "СправочникСсылка"

    def test_infer_nested_access_chain_document_manager(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Док = Документы.ПереносОтпуска.СоздатьДокумент();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Док", 0) == "ДокументОбъект"

    def test_infer_single_segment_access_still_resolves(self) -> None:
        # Regression guard: the multi-segment fix must not break the
        # single-segment (`Обj.Метод()`) resolution path.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Зап = Новый Запрос();\nРез = Зап.Выполнить();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Рез", 1) == "РезультатЗапроса"

    def test_infer_chained_calls(self) -> None:
        # Запрос.Выполнить().Выгрузить() — the first hop's method_call lives
        # *inside* the access subtree, not as a sibling of the last hop.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Т = Запрос.Выполнить().Выгрузить();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Т", 0) == "ТаблицаЗначений"

    def test_infer_nested_manager_then_chained_call(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "О = Справочники.Организации.НайтиПоКоду(1).ПолучитьОбъект();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("О", 0) == "СправочникОбъект"

    def test_local_value_shadows_global_manager_collection(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = (
            "Справочники = Новый Запрос();\nРезультат = Справочники.Организации.НайтиПоКоду(1);\n"
        )
        tree = self._parse(content)
        engine = BslTypeEngine(tree)

        assert engine.infer("Справочники", 1) == "Запрос"
        assert engine.infer("Результат", 1) is None

    def test_unknown_manager_method_stays_unresolved(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Результат = Справочники.Организации.НесуществующийМетод();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)

        assert engine.infer("Результат", 0) is None


# ---------------------------------------------------------------------------
# BslTypeEngine — specific metadata identity (Kind.Name), real-code-derived
# ---------------------------------------------------------------------------


class TestInferSpecificMetadataIdentity:
    def _parse(self, content: str):
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        parser = BslParser()
        return parser.parse_content(content, file_path="test.bsl")

    # -- item 1: compound "Kind.Name" identity, threaded through the chain --

    def test_metadata_only_compound_catalog_identity(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Орг = Справочники.Организации.НайтиПоКоду(Код);\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Орг", 0, metadata_only=True) == "СправочникСсылка.Организации"
        assert engine.infer("Орг", 0) == "СправочникСсылка"  # default unchanged (hover-safe)

    def test_metadata_only_compound_document_identity(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Док = Документы.ПереносОтпуска.СоздатьДокумент();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Док", 0, metadata_only=True) == "ДокументОбъект.ПереносОтпуска"

    def test_metadata_only_none_for_non_metadata_chain(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Т = Запрос.Выполнить().Выгрузить();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Т", 0, metadata_only=True) is None
        assert engine.infer("Т", 0) == "ТаблицаЗначений"  # default unchanged

    def test_metadata_identity_survives_intermediate_variable(self) -> None:
        # Мен = Справочники.Организации; Эл = Мен.НайтиПоКоду(1);
        # — property_access (no call) assigned to a variable, then used as
        # the base of a later chain. Found in real ZUP code.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Мен = Справочники.Организации;\nЭл = Мен.НайтиПоКоду(1);\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Мен", 0, metadata_only=True) == "СправочникМенеджер.Организации"
        assert engine.infer("Эл", 1, metadata_only=True) == "СправочникСсылка.Организации"

    # -- item 2: generic manager methods missing from RETURN_TYPE_MAP --

    def test_metadata_only_empty_ref(self) -> None:
        # Справочники.Пользователи.ПустаяСсылка() —
        # ИК_ОбщиеПроцедурыИФункцииПовтИсп/Module.bsl and
        # zup30.../Catalogs/РеестрДокументов/ManagerModule.bsl.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Авт = Справочники.Пользователи.ПустаяСсылка();\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Авт", 0, metadata_only=True) == "СправочникСсылка.Пользователи"
        assert engine.infer("Авт", 0) == "СправочникСсылка"

    def test_metadata_identity_survives_selection_cursor(self) -> None:
        # Справочники.Организации.Выбрать() ... Организация.Ссылка —
        # ИК_ОбщиеПроцедурыИФункцииПовтИсп/Module.bsl:102-104.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Организация = Справочники.Организации.Выбрать();\nР = Организация.Ссылка;\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Организация", 0, metadata_only=True) == "СправочникВыборка.Организации"
        assert engine.infer("Р", 1, metadata_only=True) == "СправочникСсылка.Организации"

    # -- item 3: enum value access (self-limiting, no RETURN_TYPE_MAP entry) --

    def test_metadata_only_enum_value_access(self) -> None:
        # Перечисления.ВариантыВажностиЗадачи.Обычная —
        # БизнесПроцессыЗаявокСотрудников/Module.bsl:40.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Приоритет = Перечисления.ВариантыВажностиЗадачи.Обычная;\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Приоритет", 0) == "ПеречислениеСсылка"
        assert (
            engine.infer("Приоритет", 0, metadata_only=True)
            == "ПеречислениеСсылка.ВариантыВажностиЗадачи"
        )

    # -- item 4: type narrowing via Если ТипЗнч(Х) = Тип("Kind.Name") Тогда --

    def test_type_guard_narrows_only_inside_then_branch(self) -> None:
        # ИК_ОбщиеПроцедурыИФункцииПовтИсп/Module.bsl:110-112 pattern.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = (
            "Функция Ф(ПравилоОбработкиЗаявки) Экспорт\n"
            "\tОрганизация = ПравилоОбработкиЗаявки.Подразделение.Источник;\n"
            '\tЕсли ТипЗнч(Организация) = Тип("СправочникСсылка.ПодразделенияОрганизаций") Тогда\n'
            "\t\tРез = Организация.ГоловнаяОрганизация;\n"
            "\tКонецЕсли;\n"
            "КонецФункции\n"
        )
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Организация", 1, metadata_only=True) is None  # before the guard
        assert (
            engine.infer("Организация", 3, metadata_only=True)
            == "СправочникСсылка.ПодразделенияОрганизаций"
        )  # inside Тогда
        assert engine.infer("Организация", 4, metadata_only=True) is None  # after КонецЕсли

    def test_type_guard_or_chain_same_kind_narrows_to_list(self) -> None:
        # ИК_ОбщиеПроцедурыИФункцииПовтИсп/Module.bsl:122-146 pattern — the
        # dominant real-code form: multiple ТипЗнч(Х)=Тип(...) checks joined
        # by ИЛИ, all against the same variable and the same generic Kind.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = (
            "Функция Ф(Ссылка) Экспорт\n"
            '\tЕсли ТипЗнч(Ссылка) = Тип("ДокументСсылка.А")\n'
            '\t\tИЛИ ТипЗнч(Ссылка) = Тип("ДокументСсылка.Б") Тогда\n'
            "\t\tРезультат = Ссылка.Организация;\n"
            "\tКонецЕсли;\n"
            "КонецФункции\n"
        )
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Ссылка", 3, metadata_only=True) == [
            "ДокументСсылка.А",
            "ДокументСсылка.Б",
        ]

    def test_type_guard_or_chain_non_matching_disjunct_no_narrowing(self) -> None:
        # Conservative all-or-nothing: one disjunct not shaped like
        # ТипЗнч(Х)=Тип(...) means no narrowing at all, not a partial one.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = (
            "Функция Ф(Ссылка) Экспорт\n"
            '\tЕсли ТипЗнч(Ссылка) = Тип("ДокументСсылка.А")\n'
            "\t\tИЛИ Ссылка = Неопределено Тогда\n"
            "\t\tРезультат = Ссылка;\n"
            "\tКонецЕсли;\n"
            "КонецФункции\n"
        )
        tree = self._parse(content)
        engine = BslTypeEngine(tree)
        assert engine.infer("Ссылка", 3, metadata_only=True) is None

    # -- item 5: implicit Ссылка/ЭтотОбъект in ObjectModule/RecordSetModule --

    def test_implicit_vars_in_catalog_object_module(self) -> None:
        # Catalogs/Сотрудники/Ext/ObjectModule.bsl — Ссылка/ЭтотОбъект are
        # never assigned in the module body; the platform supplies them.
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Процедура П() Экспорт\n\tX = Ссылка;\n\tY = ЭтотОбъект;\nКонецПроцедуры\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree, module_path="/fake/Catalogs/Сотрудники/Ext/ObjectModule.bsl")
        assert engine.infer("Ссылка", 1, metadata_only=True) == "СправочникСсылка.Сотрудники"
        assert engine.infer("Ссылка", 1) == "СправочникСсылка"
        assert engine.infer("ЭтотОбъект", 2, metadata_only=True) == "СправочникОбъект.Сотрудники"

    def test_implicit_var_in_information_register_recordset_module(self) -> None:
        # InformationRegisters/БудущиеСобытия.../Ext/RecordSetModule.bsl —
        # ЭтотОбъект exists, Ссылка does not (registers have no ref type).
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Процедура П() Экспорт\n\tY = ЭтотОбъект;\nКонецПроцедуры\n"
        tree = self._parse(content)
        engine = BslTypeEngine(
            tree,
            module_path="/fake/InformationRegisters/БудущиеСобытия/Ext/RecordSetModule.bsl",
        )
        assert (
            engine.infer("ЭтотОбъект", 1, metadata_only=True)
            == "РегистрСведенийНаборЗаписей.БудущиеСобытия"
        )
        assert engine.infer("Ссылка", 1) is None

    def test_no_implicit_vars_in_manager_module(self) -> None:
        from onec_hbk_bsl.analysis.type_inference import BslTypeEngine

        content = "Процедура П() Экспорт\n\tX = Ссылка;\n\tY = ЭтотОбъект;\nКонецПроцедуры\n"
        tree = self._parse(content)
        engine = BslTypeEngine(tree, module_path="/fake/Catalogs/Сотрудники/Ext/ManagerModule.bsl")
        assert engine.infer("Ссылка", 1) is None
        assert engine.infer("ЭтотОбъект", 2) is None


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
    def _generate(self, content: str, line_idx: int = 0) -> str | None:
        from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
        from onec_hbk_bsl.lsp.server import _generate_doc_comment_for_proc

        snapshot = build_document_snapshot("<test>", content=content)
        lines = content.splitlines(keepends=True)
        proc = next((item for item in snapshot.procedures if item.start_idx == line_idx), None)
        if proc is None:
            return None
        return _generate_doc_comment_for_proc(proc, lines)

    def test_generates_for_procedure(self) -> None:
        result = self._generate("Процедура МойМетод(А, Б)\nКонецПроцедуры\n")
        assert result is not None
        assert "МойМетод" in result
        assert "Параметры" in result
        assert "А" in result
        assert "Б" in result

    def test_skips_if_already_documented(self) -> None:
        result = self._generate("// Уже есть\nПроцедура МойМетод(А)\nКонецПроцедуры\n", 1)
        assert result is None

    def test_returns_none_for_non_header(self) -> None:
        result = self._generate("А = 1;\n")
        assert result is None

    def test_no_params_no_params_section(self) -> None:
        result = self._generate("Функция БезПараметров()\nКонецФункции\n")
        assert result is not None
        assert "Параметры" not in result

    def test_function_gets_return_value_section(self) -> None:
        result = self._generate("Функция МойМетод(А)\nКонецФункции\n")
        assert result is not None
        assert "Возвращаемое значение" in result
        assert "Параметры" in result

    def test_procedure_has_no_return_value_section(self) -> None:
        result = self._generate("Процедура МойМетод(А)\nКонецПроцедуры\n")
        assert result is not None
        assert "Возвращаемое значение" not in result

    def test_generated_comment_passes_bsl024(self) -> None:
        """Every generated comment line must pass BSL024 (space after //)."""
        from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.rules import (
            bsl024_should_report_line,
        )

        result = self._generate("Функция Тест(П1, П2)\nКонецФункции\n")
        assert result is not None
        for line in result.splitlines():
            assert not bsl024_should_report_line(line), f"BSL024 fires on: {line!r}"

    def test_preserves_tab_indent(self) -> None:
        result = self._generate("\tПроцедура МойМетод(А)\n\tКонецПроцедуры\n")
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
        params.options.insert_spaces = False
        result = on_type_formatting(ls, params)
        assert result is not None
        # [bsl] defaults to tabs (see vscode-extension package.json)
        assert any(e.new_text == "\t" for e in result)

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
        params.options.insert_spaces = False
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
        params.options.insert_spaces = False
        result = on_type_formatting(ls, params)
        assert result is not None
        assert any(e.new_text == "\t\t" for e in result)  # 2 tab levels

    def test_insert_spaces_true_uses_spaces(self, tmp_path, monkeypatch) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import on_type_formatting

        ls = self._make_server(tmp_path, monkeypatch)
        content = "Процедура Тест()\n\nКонецПроцедуры\n"
        ls._docs["file:///test.bsl"] = content
        params = MagicMock()
        params.text_document.uri = "file:///test.bsl"
        params.position.line = 1
        params.options.tab_size = 4
        params.options.insert_spaces = True
        result = on_type_formatting(ls, params)
        assert result is not None
        assert any(e.new_text == "    " for e in result)


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
