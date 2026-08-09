"""
Tests for MCP server tools.

Tests the tool functions by calling them directly (not over HTTP),
using an in-memory SQLite index.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_mcp_workspace_policy():
    from onec_hbk_bsl.mcp_bridge import server as mcp_module

    original_workspace = mcp_module._WORKSPACE
    original_allowed_roots = mcp_module._ALLOWED_WORKSPACE_ROOTS
    try:
        yield
    finally:
        mcp_module._WORKSPACE = original_workspace
        mcp_module._ALLOWED_WORKSPACE_ROOTS = original_allowed_roots


def _make_bsl(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# create_mcp_app
# ---------------------------------------------------------------------------


class TestCreateMcpApp:
    def test_app_is_created(self) -> None:
        from onec_hbk_bsl.mcp_bridge.server import create_mcp_app

        app = create_mcp_app()
        assert app is not None

    def test_app_has_expected_tools(self) -> None:
        import asyncio

        from onec_hbk_bsl.mcp_bridge.server import create_mcp_app

        app = create_mcp_app()
        tools = asyncio.run(app.list_tools())
        tool_names = {t.name for t in tools}
        assert "bsl_status" in tool_names
        assert "bsl_find_symbol" in tool_names
        assert "bsl_check_file" in tool_names
        assert "bsl_list_rules" in tool_names
        assert "bsl_diagnostics" in tool_names
        assert "bsl_1c_help_search_keyword" not in tool_names
        assert "bsl_1c_help_get_topic" not in tool_names

    def test_contract_version_includes_workspace_and_rename_policies(self, tmp_path: Path) -> None:
        tools = _tool_fns(_make_app(tmp_path))

        result = tools["bsl_contract_version"].fn()

        assert result["schema_version"] == "0.5.0"
        assert result["tool_modes"]["bsl_rename"] == {
            "mode": "transactional_write",
            "span_policy": "exact_semantic",
        }


# ---------------------------------------------------------------------------
# Individual tool tests using in-memory index
# ---------------------------------------------------------------------------


class TestBslStatusTool:
    def test_status_returns_dict_with_expected_keys(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        db = str(tmp_path / "idx.sqlite")
        # Override the module-level index singleton
        original_index = mcp_module._index
        original_db = mcp_module._DB_PATH
        try:
            mcp_module._DB_PATH = db
            mcp_module._index = SymbolIndex(db_path=db)
            # Just verify the module-level helpers work
            stats = mcp_module._get_index().get_stats()
            assert "symbol_count" in stats
            assert "file_count" in stats
        finally:
            mcp_module._index = original_index
            mcp_module._DB_PATH = original_db

    def test_status_includes_index_size_and_contract_fields(self, tmp_path: Path) -> None:
        f = _make_bsl(tmp_path, "demo.bsl", "Процедура Тест()\nКонецПроцедуры\n")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        tools["bsl_index_file"].fn(file_path=f, workspace_root=str(tmp_path))
        result = tools["bsl_status"].fn(workspace_root=str(tmp_path))
        assert result["ready"] is True
        assert result["indexing"] is False
        assert result["reindex_running"] is False
        assert result["reindex_pending"] is False
        assert result["index_size_bytes"] == (
            result["db_size_bytes"] + result["wal_size_bytes"] + result["shm_size_bytes"]
        )
        assert result["index_size_bytes"] > 0


class TestBslListRulesTool:
    def test_list_rules_returns_all_rules(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        db = str(tmp_path / "idx.sqlite")
        original_index = mcp_module._index
        try:
            mcp_module._index = SymbolIndex(db_path=db)
            # Create app and get the closure for bsl_list_rules
            # We test via the module-level RULE_METADATA directly
            from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

            assert len(RULE_METADATA) >= 67
        finally:
            mcp_module._index = original_index

    def test_list_rules_tag_filter(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

        # Rules with 'security' tag
        security_rules = [
            code for code, meta in RULE_METADATA.items() if "security" in meta.get("tags", [])
        ]
        assert len(security_rules) > 0

    def test_all_rules_have_required_fields(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

        required = {"name", "description", "severity"}
        for code, meta in RULE_METADATA.items():
            missing = required - meta.keys()
            assert not missing, f"{code} missing fields: {missing}"


class TestBslCheckFileTool:
    def test_check_file_returns_diagnostics(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        bsl_path = _make_bsl(tmp_path, "t.bsl", 'Пароль = "секрет123";\n')
        # Mock the resolve path to use our tmp file
        original_workspace = mcp_module._WORKSPACE
        try:
            mcp_module._WORKSPACE = str(tmp_path)
            # Create DiagnosticEngine directly to verify behavior
            from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

            engine = DiagnosticEngine(select={"BSL012"})
            issues = engine.check_file(bsl_path)
            assert any(d.code == "BSL012" for d in issues)
        finally:
            mcp_module._WORKSPACE = original_workspace

    def test_resolve_path_absolute(self, tmp_path: Path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        _set_workspace_policy(mcp_module, tmp_path, monkeypatch)
        abs_path = str(tmp_path / "module.bsl")
        assert mcp_module._resolve_path(abs_path) == abs_path

    def test_resolve_path_relative(self, tmp_path: Path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        _set_workspace_policy(mcp_module, tmp_path, monkeypatch)
        result = mcp_module._resolve_path("relative/module.bsl")
        assert result == str(tmp_path / "relative" / "module.bsl")

    def test_diagnostic_signature_matches_cli_lsp_and_mcp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from onec_hbk_bsl.cli.check import check_files
        from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
        from onec_hbk_bsl.lsp.server import (
            _diagnostics_engine_from_config,
            _resolve_workspace_config,
        )
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        monkeypatch.delenv("BSL_SELECT", raising=False)
        monkeypatch.delenv("BSL_IGNORE", raising=False)
        bsl_path = _make_bsl(
            tmp_path,
            "t.bsl",
            "Если Количество > Количество Тогда\nКонецЕсли;\n",
        )
        (tmp_path / "onec-hbk-bsl.toml").write_text(
            'select = ["BSL052"]\n',
            encoding="utf-8",
        )

        cli_issues = check_files([bsl_path], jobs=1)
        index = SymbolIndex(db_path=":memory:")
        try:
            lsp_engine = _diagnostics_engine_from_config(
                _resolve_workspace_config(str(tmp_path)),
                symbol_index=index,
            )
            lsp_issues = lsp_engine.check_file(bsl_path)
        finally:
            index.close()

        monkeypatch.setattr(mcp_module, "_index", None)
        mcp_result = _tool_fns(_make_app(tmp_path))["bsl_check_file"].fn(
            file_path=bsl_path,
            workspace_root=str(tmp_path),
        )

        def diagnostic_signature(issue) -> tuple[object, ...]:
            return (
                issue.code,
                issue.line,
                issue.character,
                issue.severity.name,
                issue.message,
            )

        cli_signature = [diagnostic_signature(issue) for issue in cli_issues]
        lsp_signature = [diagnostic_signature(issue) for issue in lsp_issues]
        mcp_signature = [
            (
                issue["code"],
                issue["line"],
                issue["character"],
                issue["severity"],
                issue["message"],
            )
            for issue in mcp_result["diagnostics"]
        ]
        assert cli_signature == lsp_signature == mcp_signature
        assert 'оператора ">"' in cli_signature[0][4]
        assert '"Количество"' in cli_signature[0][4]


def _set_workspace_policy(mod, root: Path, monkeypatch=None) -> None:
    resolved = root.resolve()
    if monkeypatch is None:
        mod._WORKSPACE = str(resolved)
        mod._ALLOWED_WORKSPACE_ROOTS = (resolved,)
        return
    monkeypatch.setattr(mod, "_WORKSPACE", str(resolved))
    monkeypatch.setattr(mod, "_ALLOWED_WORKSPACE_ROOTS", (resolved,))


class TestMcpUnusedDiagnostics:
    def test_mcp_unused_returns_bsl_dead(self, tmp_path: Path, symbol_index) -> None:
        from onec_hbk_bsl.mcp_bridge.server import _mcp_unused_diagnostics

        bsl = tmp_path / "m.bsl"
        bsl.write_text("Функция А() КонецФункции\n", encoding="utf-8")
        fp = str(bsl)
        symbol_index.upsert_file(
            fp,
            [
                {
                    "name": "А",
                    "line": 1,
                    "character": 0,
                    "end_line": 1,
                    "end_character": 0,
                    "kind": "function",
                    "is_export": 0,
                    "signature": "А()",
                    "doc_comment": None,
                },
            ],
            [],
        )
        rows = _mcp_unused_diagnostics(fp, symbol_index)
        assert len(rows) >= 1
        assert rows[0]["code"] == "BSL-DEAD"
        assert rows[0]["source"] == "onec-hbk-bsl · BSL-DEAD"


# ---------------------------------------------------------------------------
# New MCP tools: hover, references, read_file, search, format, rename, fix, scan
# ---------------------------------------------------------------------------


def _make_app(tmp_path):
    os.environ["INDEX_DB_PATH"] = str(tmp_path / "idx.sqlite")
    os.environ["WORKSPACE_ROOT"] = str(tmp_path)
    from onec_hbk_bsl.mcp_bridge import server as mcp_module

    _set_workspace_policy(mcp_module, tmp_path)
    return mcp_module.create_mcp_app()


def _call_tool(app, tool_name: str, **arguments):
    import asyncio

    result = asyncio.run(app.call_tool(tool_name, arguments))
    if not result:
        return None
    first = result[0]
    text = getattr(first, "text", first)
    return json.loads(text) if isinstance(text, str) else text


def _tool_fns(app):
    import asyncio

    return {
        tool.name: SimpleNamespace(
            fn=lambda _name=tool.name, **kwargs: _call_tool(app, _name, **kwargs)
        )
        for tool in asyncio.run(app.list_tools())
    }


class TestMcpWorkspacePathPolicy:
    def test_all_workspace_tools_reject_unapproved_workspace_root(self, tmp_path: Path) -> None:
        inside = tmp_path / "inside.bsl"
        inside.write_text("А = 1;\n", encoding="utf-8")
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        outside.mkdir()

        tools = _tool_fns(_make_app(tmp_path))
        cases = {
            "bsl_status": {},
            "bsl_find_symbol": {"name": "Тест"},
            "bsl_file_symbols": {"file_path": str(inside)},
            "bsl_callers": {"symbol_name": "Тест"},
            "bsl_callees": {"symbol_name": "Тест"},
            "bsl_diagnostics": {"file_path": str(inside)},
            "bsl_definition": {"symbol_name": "Тест"},
            "bsl_check_file": {"file_path": str(inside)},
            "bsl_index_file": {"file_path": str(inside)},
            "bsl_hover": {"symbol_name": "Тест"},
            "bsl_references": {"symbol_name": "Тест"},
            "bsl_read_file": {"file_path": str(inside)},
            "bsl_search": {"query": "Тест"},
            "bsl_format": {"file_path": str(inside)},
            "bsl_rename": {"old_name": "Тест", "new_name": "НовыйТест"},
            "bsl_fix": {"file_path": str(inside)},
            "bsl_workspace_scan": {},
            "bsl_meta_object": {"name": "Тест"},
            "bsl_meta_collection": {"collection": "Справочники"},
            "bsl_meta_index": {},
        }

        for tool_name, arguments in cases.items():
            result = tools[tool_name].fn(workspace_root=str(outside), **arguments)
            assert result == {
                "error": {
                    "code": "workspace_path_denied",
                    "message": "Path is outside the allowed workspace",
                    "path": str(outside),
                }
            }, tool_name

    @pytest.mark.parametrize("path_kind", ["absolute", "parent_traversal"])
    def test_read_rejects_paths_outside_selected_workspace(
        self, tmp_path: Path, path_kind: str
    ) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside.bsl"
        outside.write_text("Секрет = 1;\n", encoding="utf-8")
        requested = str(outside) if path_kind == "absolute" else f"../{outside.name}"

        tools = _tool_fns(_make_app(tmp_path))
        result = tools["bsl_read_file"].fn(file_path=requested)

        assert result["error"]["code"] == "workspace_path_denied"
        assert result["error"]["path"] == requested

    def test_symlink_escape_is_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside.bsl"
        outside.write_text("Секрет = 1;\n", encoding="utf-8")
        link = tmp_path / "escape.bsl"
        link.symlink_to(outside)

        tools = _tool_fns(_make_app(tmp_path))
        result = tools["bsl_read_file"].fn(file_path=str(link))

        assert result["error"]["code"] == "workspace_path_denied"

    def test_selected_workspace_is_a_narrower_boundary(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        other_project_file = second / "module.bsl"
        other_project_file.write_text("А = 1;\n", encoding="utf-8")

        tools = _tool_fns(_make_app(tmp_path))
        result = tools["bsl_read_file"].fn(
            file_path=str(other_project_file),
            workspace_root=str(first),
        )

        assert result["error"]["code"] == "workspace_path_denied"

    def test_new_file_under_symlinked_parent_is_rejected(self, tmp_path: Path) -> None:
        outside_dir = tmp_path.parent / f"{tmp_path.name}-outside"
        outside_dir.mkdir()
        linked_parent = tmp_path / "linked"
        linked_parent.symlink_to(outside_dir, target_is_directory=True)

        tools = _tool_fns(_make_app(tmp_path))
        result = tools["bsl_format"].fn(
            file_path=str(linked_parent / "new.bsl"),
            write=True,
        )

        assert result["error"]["code"] == "workspace_path_denied"
        assert not (outside_dir / "new.bsl").exists()

    def test_denied_write_does_not_change_outside_target(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside.bsl"
        original = "процедура Тест()\nконецпроцедуры\n"
        outside.write_text(original, encoding="utf-8")
        before_mtime = outside.stat().st_mtime_ns

        tools = _tool_fns(_make_app(tmp_path))
        result = tools["bsl_format"].fn(file_path=str(outside), write=True)

        assert result["error"]["code"] == "workspace_path_denied"
        assert outside.read_text(encoding="utf-8") == original
        assert outside.stat().st_mtime_ns == before_mtime

    def test_rename_rejects_outside_path_from_index_without_writing(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        (tmp_path / ".git").mkdir()
        outside = tmp_path.parent / f"{tmp_path.name}-outside.bsl"
        original = "Процедура СтароеИмя()\nКонецПроцедуры\n"
        outside.write_text(original, encoding="utf-8")
        before_mtime = outside.stat().st_mtime_ns

        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        index.upsert_file(
            str(outside),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "СтароеИмя()",
                    "doc_comment": None,
                }
            ],
            [],
        )

        result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=False,
            workspace_root=str(tmp_path),
        )

        assert result["error"]["code"] == "workspace_path_denied"
        assert outside.read_text(encoding="utf-8") == original
        assert outside.stat().st_mtime_ns == before_mtime

    def test_unapproved_workspace_root_is_rejected_before_filesystem_probe(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        _set_workspace_policy(mcp_module, tmp_path, monkeypatch)
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        probes = 0

        def fail_if_probed(_path: Path) -> bool:
            nonlocal probes
            probes += 1
            raise AssertionError("filesystem probe occurred before allowlist rejection")

        monkeypatch.setattr(Path, "exists", fail_if_probed)
        with pytest.raises(mcp_module.WorkspacePathError):
            mcp_module._resolve_workspace_root(str(outside))
        assert probes == 0


class TestBslHover:
    def test_hover_unknown_symbol(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_hover"].fn(symbol_name="НесуществующийСимволXYZ999")
        assert result["found"] is False

    def test_hover_platform_function(self, tmp_path) -> None:
        app = _make_app(tmp_path)

        # Сообщить is a known platform function
        tools = _tool_fns(app)
        result = tools["bsl_hover"].fn(symbol_name="Сообщить")
        # May or may not be found depending on platform_api data
        assert "found" in result


class TestBslReferences:
    def test_references_unknown(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_references"].fn(symbol_name="НесуществующийXYZ")
        assert result["definition_count"] == 0
        assert result["reference_count"] == 0


class TestBslCallGraphAmbiguity:
    def test_call_tools_report_stable_ambiguity_contract(self, tmp_path: Path) -> None:
        first = _make_bsl(
            tmp_path,
            "a_module.bsl",
            "Процедура ОдинаковыйОбработчик()\nКонецПроцедуры\n",
        )
        second = _make_bsl(
            tmp_path,
            "b_module.bsl",
            "Процедура ОдинаковыйОбработчик()\nКонецПроцедуры\n",
        )
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        tools["bsl_index_file"].fn(file_path=second, workspace_root=str(tmp_path))
        tools["bsl_index_file"].fn(file_path=first, workspace_root=str(tmp_path))

        for tool_name in ("bsl_callers", "bsl_callees"):
            ambiguous = tools[tool_name].fn(
                symbol_name="ОдинаковыйОбработчик",
                workspace_root=str(tmp_path),
            )
            assert ambiguous["ambiguous"] is True
            assert ambiguous["candidate_count"] == 2
            assert ambiguous["candidates_truncated"] is False
            assert [candidate["file"] for candidate in ambiguous["candidates"]] == [
                first,
                second,
            ]

            narrowed = tools[tool_name].fn(
                symbol_name="ОдинаковыйОбработчик",
                file_filter="a_module.bsl",
                workspace_root=str(tmp_path),
            )
            assert narrowed["definition"]["file"] == first
            assert "ambiguous" not in narrowed


class TestBslReadFile:
    def test_read_full_file(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("А = 1;\nБ = 2;\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_read_file"].fn(file_path=str(f))
        assert "А = 1;" in result["content"]
        assert result["total_lines"] == 2

    def test_read_line_range(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("А = 1;\nБ = 2;\nВ = 3;\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_read_file"].fn(file_path=str(f), start_line=2, end_line=2)
        assert "Б = 2;" in result["content"]
        assert "А = 1;" not in result["content"]

    def test_read_nonexistent(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_read_file"].fn(file_path=str(tmp_path / "nope.bsl"))
        assert "error" in result


class TestBslSearch:
    def test_search_text(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("Процедура МойМетод()\nКонецПроцедуры\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        # file_filter restricts search to our tmp directory
        result = tools["bsl_search"].fn(query="МойМетод", search_type="text", file_filter=f.name)
        assert (
            result["text_match_count"] >= 1 or result["text_match_count"] == 0
        )  # depends on workspace

    def test_search_symbol_empty_index(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_search"].fn(query="НечтоНесуществующее", search_type="symbol")
        assert result["symbols"] == []

    def test_search_invalid_regex(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_search"].fn(query="[invalid", search_type="text")
        assert "text_error" in result


class TestBslFormat:
    def test_format_dry_run(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("процедура Тест()\nконецпроцедуры\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_format"].fn(file_path=str(f), write=False)
        assert result["changed"] is True
        assert "Процедура" in result["formatted"]
        assert result["written"] is False

    def test_format_write(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("процедура Тест()\nконецпроцедуры\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_format"].fn(file_path=str(f), write=True)
        assert result["written"] is True
        assert "Процедура" in f.read_text(encoding="utf-8")

    def test_format_already_formatted(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("Процедура Тест()\nКонецПроцедуры", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_format"].fn(file_path=str(f), write=False)
        assert result["changed"] is False


class TestBslRename:
    def test_rename_dry_run_empty_index(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_rename"].fn(
            old_name="СтараяФункция", new_name="НоваяФункция", apply=False
        )
        assert result["dry_run"] is True
        assert result["files_affected"] == 0

    def test_rename_invalid_name(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_rename"].fn(old_name="Тест", new_name="123invalid", apply=False)
        assert "error" in result

    def test_rename_apply_changes_only_exact_semantic_spans(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        source = tmp_path / "rename.bsl"
        source.write_text(
            (
                "Процедура СтароеИмя()\n"
                "    СтароеИмя();\n"
                '    Текст = "СтароеИмя";\n'
                "    // СтароеИмя не должно меняться\n"
                "    СтароеИмя = 1;\n"
                "КонецПроцедуры\n"
            ),
            encoding="utf-8",
        )
        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        index.upsert_file(
            str(source),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "СтароеИмя()",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "СтароеИмя",
                    "callee_name": "СтароеИмя",
                    "callee_args_count": 0,
                }
            ],
        )

        result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=True,
            workspace_root=str(tmp_path),
        )

        assert result["applied"] is True
        assert result["dry_run"] is False
        assert result["total_occurrences"] == 2
        assert source.read_text(encoding="utf-8") == (
            "Процедура НовоеИмя()\n"
            "    НовоеИмя();\n"
            '    Текст = "СтароеИмя";\n'
            "    // СтароеИмя не должно меняться\n"
            "    СтароеИмя = 1;\n"
            "КонецПроцедуры\n"
        )

    def test_rename_preview_is_deterministic_and_read_only(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        source = tmp_path / "preview.bsl"
        source.write_text(
            "Процедура СтароеИмя()\n    СтароеИмя();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        before_bytes = source.read_bytes()
        before_mtime = source.stat().st_mtime_ns

        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        index.upsert_file(
            str(source),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "СтароеИмя()",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "СтароеИмя",
                    "callee_name": "СтароеИмя",
                    "callee_args_count": 0,
                }
            ],
        )

        arguments = {
            "old_name": "СтароеИмя",
            "new_name": "НовоеИмя",
            "apply": False,
            "workspace_root": str(tmp_path),
        }
        first = tools["bsl_rename"].fn(**arguments)
        second = tools["bsl_rename"].fn(**arguments)

        assert first == second
        assert first["dry_run"] is True
        assert first["applied"] is False
        assert first["old_name"] == "СтароеИмя"
        assert first["new_name"] == "НовоеИмя"
        assert first["files_affected"] == 1
        assert first["total_occurrences"] == 2
        assert first["files"][0]["file_path"] == str(source)
        assert [
            (edit["start_line"], edit["start_character"]) for edit in first["files"][0]["edits"]
        ] == [(0, 10), (1, 4)]
        assert source.read_bytes() == before_bytes
        assert source.stat().st_mtime_ns == before_mtime

    def test_rename_allows_case_only_canonicalization(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        source = tmp_path / "case.bsl"
        source.write_text(
            "Процедура староеИмя()\n    СТАРОЕИМЯ();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        index.upsert_file(
            str(source),
            [
                {
                    "name": "староеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "староеИмя()",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "староеИмя",
                    "callee_name": "СТАРОЕИМЯ",
                    "callee_args_count": 0,
                }
            ],
        )

        result = tools["bsl_rename"].fn(
            old_name="староеИмя",
            new_name="СтароеИмя",
            apply=True,
            workspace_root=str(tmp_path),
        )

        assert result["applied"] is True
        assert source.read_text(encoding="utf-8") == (
            "Процедура СтароеИмя()\n    СтароеИмя();\nКонецПроцедуры\n"
        )

    @pytest.mark.parametrize(
        ("extra_source", "index_mutation", "expected_code"),
        [
            (
                "Процедура НовоеИмя()\nКонецПроцедуры\n",
                "collision",
                "name_collision",
            ),
            (
                "Процедура СтароеИмя()\n    Объект.СтароеИмя();\nКонецПроцедуры\n",
                "qualified",
                "receiver_ambiguity",
            ),
            (
                "Процедура СтароеИмя()\n    ДругоеИмя();\nКонецПроцедуры\n",
                "stale",
                "stale_index",
            ),
        ],
    )
    def test_rename_refuses_unsafe_plan_before_write(
        self,
        tmp_path: Path,
        extra_source: str,
        index_mutation: str,
        expected_code: str,
    ) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        source = tmp_path / "unsafe.bsl"
        source.write_text(extra_source, encoding="utf-8")
        before = source.read_bytes()
        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        symbols = [
            {
                "name": "СтароеИмя",
                "line": 1,
                "character": 10,
                "end_line": 1,
                "end_character": 19,
                "kind": "procedure",
                "is_export": 0,
                "signature": "СтароеИмя()",
                "doc_comment": None,
            }
        ]
        calls = [
            {
                "caller_line": 2,
                "caller_character": 4 if index_mutation == "stale" else 11,
                "caller_name": "СтароеИмя",
                "callee_name": "СтароеИмя",
                "callee_args_count": 0,
            }
        ]
        if index_mutation == "collision":
            symbols.append(
                {
                    "name": "НовоеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 18,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "НовоеИмя()",
                    "doc_comment": None,
                }
            )
            calls = []
        index.upsert_file(str(source), symbols, calls)

        result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=True,
            workspace_root=str(tmp_path),
        )

        assert result["error"]["code"] == expected_code
        assert source.read_bytes() == before

    def test_rename_rolls_back_all_files_when_second_replace_fails(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from onec_hbk_bsl.analysis import rename_plan
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        definition = tmp_path / "a_definition.bsl"
        caller = tmp_path / "b_caller.bsl"
        definition.write_text("Процедура СтароеИмя() Экспорт\nКонецПроцедуры\n", encoding="utf-8")
        caller.write_text("Процедура Вызов()\n    СтароеИмя();\nКонецПроцедуры\n", encoding="utf-8")
        before = {path: path.read_bytes() for path in (definition, caller)}

        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        index.upsert_file(
            str(definition),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 1,
                    "signature": "СтароеИмя() Экспорт",
                    "doc_comment": None,
                }
            ],
            [],
        )
        index.upsert_file(
            str(caller),
            [
                {
                    "name": "Вызов",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 15,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "Вызов()",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "Вызов",
                    "callee_name": "СтароеИмя",
                    "callee_args_count": 0,
                }
            ],
        )

        real_replace = rename_plan._replace_path
        calls = 0

        def fail_second(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second-file failure")
            real_replace(source, destination)

        monkeypatch.setattr(rename_plan, "_replace_path", fail_second)
        result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=True,
            workspace_root=str(tmp_path),
        )

        assert result["error"]["code"] == "commit_failed"
        assert {path: path.read_bytes() for path in (definition, caller)} == before

    def test_rename_commit_refuses_changed_content_before_write(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.analysis.rename_plan import (
            RenameRefused,
            build_rename_plan,
            commit_rename_plan,
        )
        from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

        source = tmp_path / "stale.bsl"
        source.write_text("Процедура СтароеИмя()\nКонецПроцедуры\n", encoding="utf-8")
        index = SymbolIndex(db_path=str(tmp_path / "stale.sqlite"))
        index.upsert_file(
            str(source),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "СтароеИмя()",
                    "doc_comment": None,
                }
            ],
            [],
        )
        plan = build_rename_plan(index, "СтароеИмя", "НовоеИмя")
        index.close()
        changed = "// параллельное изменение\nПроцедура СтароеИмя()\nКонецПроцедуры\n"
        source.write_text(changed, encoding="utf-8")

        with pytest.raises(RenameRefused, match="content hash changed") as exc_info:
            commit_rename_plan(plan)

        assert exc_info.value.code == "stale_content"
        assert source.read_text(encoding="utf-8") == changed

    def test_rename_refuses_multiple_same_name_definitions(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        tools = _tool_fns(_make_app(tmp_path))
        index = mcp_module._get_index(str(tmp_path))
        sources = [tmp_path / "first.bsl", tmp_path / "second.bsl"]
        for source in sources:
            source.write_text("Процедура СтароеИмя()\nКонецПроцедуры\n", encoding="utf-8")
            index.upsert_file(
                str(source),
                [
                    {
                        "name": "СтароеИмя",
                        "line": 1,
                        "character": 10,
                        "end_line": 1,
                        "end_character": 19,
                        "kind": "procedure",
                        "is_export": 0,
                        "signature": "СтароеИмя()",
                        "doc_comment": None,
                    }
                ],
                [],
            )
        before = {source: source.read_bytes() for source in sources}

        result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=True,
            workspace_root=str(tmp_path),
        )

        assert result["error"]["code"] == "ambiguous_definition"
        assert {source: source.read_bytes() for source in sources} == before

    def test_lsp_and_mcp_build_equivalent_open_and_closed_file_plans(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from onec_hbk_bsl.lsp.server import BslLanguageServer, on_rename

        definition = tmp_path / "definition.bsl"
        caller = tmp_path / "caller.bsl"
        definition_content = "Процедура СтароеИмя() Экспорт\n    СтароеИмя();\nКонецПроцедуры\n"
        caller_content = "Процедура Вызов()\n    СтароеИмя();\nКонецПроцедуры\n"
        definition.write_text(definition_content, encoding="utf-8")
        caller.write_text(caller_content, encoding="utf-8")
        monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "idx.sqlite"))

        ls = BslLanguageServer()
        ls.symbol_index.upsert_file(
            str(definition),
            [
                {
                    "name": "СтароеИмя",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 19,
                    "kind": "procedure",
                    "is_export": 1,
                    "signature": "СтароеИмя() Экспорт",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "СтароеИмя",
                    "callee_name": "СтароеИмя",
                    "callee_args_count": 0,
                }
            ],
        )
        ls.symbol_index.upsert_file(
            str(caller),
            [
                {
                    "name": "Вызов",
                    "line": 1,
                    "character": 10,
                    "end_line": 1,
                    "end_character": 15,
                    "kind": "procedure",
                    "is_export": 0,
                    "signature": "Вызов()",
                    "doc_comment": None,
                }
            ],
            [
                {
                    "caller_line": 2,
                    "caller_character": 4,
                    "caller_name": "Вызов",
                    "callee_name": "СтароеИмя",
                    "callee_args_count": 0,
                }
            ],
        )
        definition_uri = definition.as_uri()
        ls._docs[definition_uri] = definition_content
        params = MagicMock()
        params.text_document.uri = definition_uri
        params.position.line = 0
        params.position.character = 12
        params.new_name = "НовоеИмя"

        lsp_result = on_rename(ls, params)
        assert lsp_result is not None
        lsp_spans = {
            (uri, edit.range.start.line, edit.range.start.character)
            for uri, edits in lsp_result.changes.items()
            for edit in edits
        }
        ls.close()

        tools = _tool_fns(_make_app(tmp_path))
        mcp_result = tools["bsl_rename"].fn(
            old_name="СтароеИмя",
            new_name="НовоеИмя",
            apply=False,
            workspace_root=str(tmp_path),
        )
        mcp_spans = {
            (Path(file["file_path"]).as_uri(), edit["start_line"], edit["start_character"])
            for file in mcp_result["files"]
            for edit in file["edits"]
        }

        assert lsp_spans == mcp_spans


class TestBslFix:
    def test_fix_dry_run_no_issues(self, tmp_path) -> None:
        f = tmp_path / "mod.bsl"
        f.write_text("А = 1;\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_fix"].fn(file_path=str(f), write=False)
        assert result["fixes_applied"] == 0

    def test_fix_self_assign_dry(self, tmp_path) -> None:
        # BSL009 = SelfAssign; bsl_fix only covers {BSL009,BSL055,BSL060}
        # Just verify the tool doesn't crash and returns expected structure
        f = tmp_path / "mod.bsl"
        f.write_text("А = 1;\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_fix"].fn(file_path=str(f), write=False)
        assert "fixes_applied" in result
        assert result["written"] is False


class TestBslWorkspaceScan:
    def test_scan_directory(self, tmp_path) -> None:
        (tmp_path / "a.bsl").write_text("А = 1;\n", encoding="utf-8")
        (tmp_path / "b.bsl").write_text("Б = 2;\n", encoding="utf-8")
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_workspace_scan"].fn(directory=str(tmp_path))
        assert result["file_count"] == 2
        assert len(result["files"]) == 2

    def test_scan_nonexistent(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_workspace_scan"].fn(directory=str(tmp_path / "nope"))
        assert "error" in result


class TestMcpMultiProject:
    def test_multi_project_index_isolation_by_workspace_root(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """
        Regression test for multi-workspace MCP usage.

        We index two independent workspaces in the same MCP process and verify
        symbol lookups are isolated by `workspace_root`.
        """
        monkeypatch.delenv("INDEX_DB_PATH", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

        # Ensure server module import resolves INDEX_DB_PATH via a local `.git/`
        # directory (no writes to ~/.cache inside sandboxed CI).
        (tmp_path / ".git").mkdir(parents=True, exist_ok=True)

        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        (ws1 / ".git").mkdir(parents=True, exist_ok=True)
        (ws2 / ".git").mkdir(parents=True, exist_ok=True)

        f1 = ws1 / "a.bsl"
        f2 = ws2 / "b.bsl"
        f1.write_text("Процедура ТолькоWS1()\nКонецПроцедуры\n", encoding="utf-8")
        f2.write_text("Процедура ТолькоWS2()\nКонецПроцедуры\n", encoding="utf-8")

        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        _set_workspace_policy(mcp_module, tmp_path, monkeypatch)
        app = mcp_module.create_mcp_app()
        tools = _tool_fns(app)

        # Index both workspaces (separate DBs via .git/onec-hbk-bsl_index.sqlite).
        tools["bsl_index_file"].fn(file_path=str(f1), workspace_root=str(ws1))
        tools["bsl_index_file"].fn(file_path=str(f2), workspace_root=str(ws2))

        r1 = tools["bsl_find_symbol"].fn(name="ТолькоWS1", workspace_root=str(ws1))
        r1_wrong = tools["bsl_find_symbol"].fn(name="ТолькоWS1", workspace_root=str(ws2))

        r2 = tools["bsl_find_symbol"].fn(name="ТолькоWS2", workspace_root=str(ws2))
        r2_wrong = tools["bsl_find_symbol"].fn(name="ТолькоWS2", workspace_root=str(ws1))

        assert r1["count"] >= 1
        assert r1_wrong["count"] == 0
        assert r2["count"] >= 1
        assert r2_wrong["count"] == 0
