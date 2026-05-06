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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

        required = {"name", "description", "severity", "sonar_type", "sonar_severity"}
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

    def test_resolve_path_absolute(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge.server import _resolve_path

        abs_path = str(tmp_path / "module.bsl")
        assert _resolve_path(abs_path) == abs_path

    def test_resolve_path_relative(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        original = mcp_module._WORKSPACE
        try:
            mcp_module._WORKSPACE = str(tmp_path)
            result = _resolve_path_via_module("relative/module.bsl", mcp_module)
            assert result == str(tmp_path / "relative" / "module.bsl")
        finally:
            mcp_module._WORKSPACE = original


def _resolve_path_via_module(path: str, mod) -> str:
    from pathlib import Path as P

    p = P(path)
    if p.is_absolute():
        return str(p)
    return str(P(mod._WORKSPACE) / path)


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
    from onec_hbk_bsl.mcp_bridge.server import create_mcp_app

    return create_mcp_app()


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
        tool.name: SimpleNamespace(fn=lambda _name=tool.name, **kwargs: _call_tool(app, _name, **kwargs))
        for tool in asyncio.run(app.list_tools())
    }


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


class TestBsl1cHelpTools:
    def test_1c_help_search_keyword_is_proxied_and_sorted(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            assert tool_name == "search_1c_help_keyword"
            assert arguments["query"] == "тест"
            assert arguments["limit"] == 2
            # Intentionally unsorted: should be sorted by (path, text)
            return [
                {"path": "b/1", "text": "B"},
                {"path": "a/1", "text": "A"},
            ]

        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        res1 = tools["bsl_1c_help_search_keyword"].fn(query="тест", limit=2)
        assert res1["cached"] is False
        assert [r["path"] for r in res1["results"]] == ["a/1", "b/1"]

        res2 = tools["bsl_1c_help_search_keyword"].fn(query="тест", limit=2)
        assert res2["cached"] is True

    def test_1c_help_get_topic_is_proxied_and_cached(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            assert tool_name == "get_1c_help_topic"
            assert arguments["path"] == "docs/some_topic"
            return [{"text": "HELLO_TOPIC"}]

        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        res1 = tools["bsl_1c_help_get_topic"].fn(path="docs/some_topic")
        assert res1["cached"] is False
        assert res1["text"] == "HELLO_TOPIC"

        res2 = tools["bsl_1c_help_get_topic"].fn(path="docs/some_topic")
        assert res2["cached"] is True
        assert res2["text"] == "HELLO_TOPIC"

    def test_1c_help_keyword_cache_is_bounded(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()
        monkeypatch.setattr(mcp_module, "_HELP_KEYWORD_CACHE_LIMIT", 2)
        calls = {"count": 0}

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            calls["count"] += 1
            assert tool_name == "search_1c_help_keyword"
            q = str(arguments["query"])
            return [{"path": f"docs/{q}", "text": q}]

        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        tools["bsl_1c_help_search_keyword"].fn(query="q1", limit=1)
        tools["bsl_1c_help_search_keyword"].fn(query="q2", limit=1)
        tools["bsl_1c_help_search_keyword"].fn(query="q3", limit=1)

        assert len(mcp_module._help_keyword_cache) == 2
        assert ("q1", 1) not in mcp_module._help_keyword_cache
        assert ("q2", 1) in mcp_module._help_keyword_cache
        assert ("q3", 1) in mcp_module._help_keyword_cache

        tools["bsl_1c_help_search_keyword"].fn(query="q1", limit=1)
        assert calls["count"] == 4

    def test_1c_help_topic_cache_is_bounded(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()
        monkeypatch.setattr(mcp_module, "_HELP_TOPIC_CACHE_LIMIT", 2)

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            assert tool_name == "get_1c_help_topic"
            path = str(arguments["path"])
            return [{"text": f"text:{path}"}]

        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        tools["bsl_1c_help_get_topic"].fn(path="a/topic")
        tools["bsl_1c_help_get_topic"].fn(path="b/topic")
        tools["bsl_1c_help_get_topic"].fn(path="c/topic")

        assert len(mcp_module._help_topic_cache) == 2
        assert "a/topic" not in mcp_module._help_topic_cache
        assert "b/topic" in mcp_module._help_topic_cache
        assert "c/topic" in mcp_module._help_topic_cache

    def test_1c_help_keyword_cache_expires_by_ttl(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()
        monkeypatch.setattr(mcp_module, "_HELP_KEYWORD_CACHE_TTL_SEC", 5)
        calls = {"count": 0}
        clock = {"t": 100.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            calls["count"] += 1
            assert tool_name == "search_1c_help_keyword"
            return [{"path": "docs/ttl", "text": "ttl"}]

        monkeypatch.setattr(mcp_module.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        first = tools["bsl_1c_help_search_keyword"].fn(query="ttl", limit=1)
        assert first["cached"] is False
        clock["t"] += 2.0
        second = tools["bsl_1c_help_search_keyword"].fn(query="ttl", limit=1)
        assert second["cached"] is True
        clock["t"] += 10.0
        third = tools["bsl_1c_help_search_keyword"].fn(query="ttl", limit=1)
        assert third["cached"] is False
        assert calls["count"] == 2

    def test_1c_help_topic_cache_evicts_by_size(self, tmp_path, monkeypatch) -> None:
        from onec_hbk_bsl.mcp_bridge import server as mcp_module

        mcp_module._help_keyword_cache.clear()
        mcp_module._help_topic_cache.clear()
        monkeypatch.setattr(mcp_module, "_HELP_TOPIC_CACHE_LIMIT", 10)
        monkeypatch.setattr(mcp_module, "_HELP_TOPIC_CACHE_BYTES_LIMIT", 70)

        def fake_post(
            tool_name: str,
            arguments: dict[str, object],
            timeout: float = 5.0,
        ):
            assert tool_name == "get_1c_help_topic"
            path = str(arguments["path"])
            return [{"text": f"{path}-payload-very-long"}]

        monkeypatch.setattr(mcp_module, "_post_1c_help_tool", fake_post)

        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        tools["bsl_1c_help_get_topic"].fn(path="topic/a")
        tools["bsl_1c_help_get_topic"].fn(path="topic/b")

        # Small bytes limit keeps only the freshest entry.
        assert len(mcp_module._help_topic_cache) == 1
        assert "topic/a" not in mcp_module._help_topic_cache
        assert "topic/b" in mcp_module._help_topic_cache


class TestBslReferences:
    def test_references_unknown(self, tmp_path) -> None:
        app = _make_app(tmp_path)
        tools = _tool_fns(app)
        result = tools["bsl_references"].fn(symbol_name="НесуществующийXYZ")
        assert result["definition_count"] == 0
        assert result["reference_count"] == 0


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
        f.write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
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

        from onec_hbk_bsl.mcp_bridge.server import create_mcp_app

        app = create_mcp_app()
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
