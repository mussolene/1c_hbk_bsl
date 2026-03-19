"""
Tests for bsl_analyzer.analysis.call_graph.

Covers:
  - Call dataclass fields
  - extract_calls with regex fallback (_RegexTree with .content attribute)
  - extract_calls returns a list of Call objects
  - _extract_from_source parses BSL source with function calls
  - build_call_graph with a mock SymbolIndex
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers / fake trees
# ---------------------------------------------------------------------------


class _FakeRegexTree:
    """Simulates the regex-fallback tree: has .content but no .root_node."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeRootNode:
    """Minimal root_node with no children — causes is_ts detection to use fallback."""

    def __init__(self) -> None:
        self.children: list = []
        self.type = "module"


class _FakeEmptyTree:
    """Tree with root_node but no children — triggers fallback path."""

    def __init__(self) -> None:
        self.root_node = _FakeRootNode()


# ---------------------------------------------------------------------------
# Call dataclass
# ---------------------------------------------------------------------------


class TestCallDataclass:
    def test_call_fields(self) -> None:
        from bsl_analyzer.analysis.call_graph import Call

        c = Call(
            caller_file="test.bsl",
            caller_line=10,
            caller_name="МояПроцедура",
            callee_name="ПроцедураБ",
            callee_args_count=2,
        )
        assert c.caller_file == "test.bsl"
        assert c.caller_line == 10
        assert c.caller_name == "МояПроцедура"
        assert c.callee_name == "ПроцедураБ"
        assert c.callee_args_count == 2

    def test_call_default_args_count(self) -> None:
        from bsl_analyzer.analysis.call_graph import Call

        c = Call(caller_file="f.bsl", caller_line=1, caller_name=None, callee_name="Ф")
        assert c.callee_args_count == 0


# ---------------------------------------------------------------------------
# extract_calls with regex fallback tree
# ---------------------------------------------------------------------------


BSL_WITH_CALLS = """\
Процедура ОбработатьЗаказ(Заказ)
    ВалидироватьСтроки(Заказ.Строки);
    ЗаписатьЛог("Заказ обработан");
КонецПроцедуры

Функция ПолучитьДанные() Экспорт
    Возврат ПолучитьИзБД();
КонецФункции
"""


class TestExtractCallsRegexFallback:
    def test_returns_list(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        tree = _FakeRegexTree(BSL_WITH_CALLS)
        result = extract_calls(tree, file_path="test.bsl")
        assert isinstance(result, list)

    def test_returns_call_objects(self) -> None:
        from bsl_analyzer.analysis.call_graph import Call, extract_calls

        tree = _FakeRegexTree(BSL_WITH_CALLS)
        result = extract_calls(tree, file_path="test.bsl")
        assert all(isinstance(c, Call) for c in result)

    def test_finds_known_callee(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        tree = _FakeRegexTree(BSL_WITH_CALLS)
        result = extract_calls(tree, file_path="test.bsl")
        callee_names = {c.callee_name for c in result}
        assert "ВалидироватьСтроки" in callee_names or "ЗаписатьЛог" in callee_names

    def test_caller_file_set_correctly(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        tree = _FakeRegexTree(BSL_WITH_CALLS)
        result = extract_calls(tree, file_path="my_module.bsl")
        assert all(c.caller_file == "my_module.bsl" for c in result)

    def test_caller_name_tracks_procedure(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        tree = _FakeRegexTree(BSL_WITH_CALLS)
        result = extract_calls(tree, file_path="test.bsl")
        # Calls inside ОбработатьЗаказ should have caller_name set
        inside_proc = [c for c in result if c.caller_name == "ОбработатьЗаказ"]
        assert len(inside_proc) >= 1

    def test_empty_content_returns_empty_list(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        tree = _FakeRegexTree("")
        result = extract_calls(tree, file_path="empty.bsl")
        assert result == []

    def test_tree_without_root_node_or_content_returns_empty(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        # An object with neither .root_node nor .content
        class _Bare:
            pass

        result = extract_calls(_Bare(), file_path="bare.bsl")
        assert result == []

    def test_args_count_single_arg(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        source = "ЗаписатьЛог(\"Сообщение\");\n"
        tree = _FakeRegexTree(source)
        result = extract_calls(tree, file_path="test.bsl")
        calls_named = [c for c in result if c.callee_name == "ЗаписатьЛог"]
        assert len(calls_named) >= 1
        assert calls_named[0].callee_args_count == 1

    def test_args_count_multiple_args(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        source = "ОбработатьЗаказ(Заказ, Режим, Флаг);\n"
        tree = _FakeRegexTree(source)
        result = extract_calls(tree, file_path="test.bsl")
        calls_named = [c for c in result if c.callee_name == "ОбработатьЗаказ"]
        assert len(calls_named) >= 1
        assert calls_named[0].callee_args_count == 3

    def test_keywords_not_included_as_calls(self) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls

        # BSL keywords should not appear as callee names
        source = "Если Условие(Аргумент) Тогда\nКонецЕсли;\n"
        tree = _FakeRegexTree(source)
        result = extract_calls(tree, file_path="test.bsl")
        callee_names_lower = {c.callee_name.lower() for c in result}
        assert "если" not in callee_names_lower


# ---------------------------------------------------------------------------
# extract_calls with real tree-sitter tree (via BslParser)
# ---------------------------------------------------------------------------


class TestExtractCallsRealParser:
    def test_extract_calls_from_sample_bsl(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.call_graph import Call, extract_calls
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_calls(tree, file_path=sample_bsl_path)

        assert isinstance(result, list)
        assert all(isinstance(c, Call) for c in result)

    def test_sample_bsl_calls_записатьлог(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.call_graph import extract_calls
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_calls(tree, file_path=sample_bsl_path)

        callee_names = {c.callee_name for c in result}
        # sample.bsl calls ЗаписатьЛог in several places
        assert "ЗаписатьЛог" in callee_names


# ---------------------------------------------------------------------------
# build_call_graph
# ---------------------------------------------------------------------------


class TestBuildCallGraph:
    def _make_mock_index(
        self,
        symbol_name: str = "ОбработатьЗаказ",
        file_path: str = "/ws/orders.bsl",
        line: int = 10,
        end_line: int = 40,
    ) -> Any:
        mock_index = MagicMock()
        mock_index.find_symbol.return_value = [
            {
                "name": symbol_name,
                "file_path": file_path,
                "line": line,
                "end_line": end_line,
                "signature": f"Procedure {symbol_name}()",
            }
        ]
        mock_index.find_callers.return_value = []
        mock_index.find_callees.return_value = []
        return mock_index

    def test_build_call_graph_returns_dict(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert isinstance(result, dict)

    def test_result_has_required_keys(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert "name" in result
        assert "definition" in result
        assert "callers" in result
        assert "callees" in result

    def test_name_matches_queried_symbol(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert result["name"] == "ОбработатьЗаказ"

    def test_definition_populated_when_found(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert result["definition"]["file"] == "/ws/orders.bsl"
        assert result["definition"]["line"] == 10

    def test_definition_none_when_symbol_not_found(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = MagicMock()
        mock_index.find_symbol.return_value = []
        mock_index.find_callers.return_value = []
        mock_index.find_callees.return_value = []

        result = build_call_graph(mock_index, "НесуществующийСимвол")

        assert result["definition"]["file"] is None
        assert result["definition"]["line"] is None

    def test_callers_empty_when_no_callers(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        mock_index.find_callers.return_value = []
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert result["callers"] == []

    def test_callers_populated_from_index(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        mock_index.find_callers.return_value = [
            {
                "caller_name": "ГлавнаяФункция",
                "caller_file": "/ws/main.bsl",
                "caller_line": 5,
            }
        ]
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        assert len(result["callers"]) == 1
        assert result["callers"][0]["caller_name"] == "ГлавнаяФункция"

    def test_callees_populated_from_index(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index(line=10, end_line=40)
        mock_index.find_callees.return_value = [
            {
                "callee_name": "ВалидироватьСтроки",
                "caller_line": 25,
                "callee_file": None,
                "callee_line": None,
            }
        ]
        result = build_call_graph(mock_index, "ОбработатьЗаказ")

        callee_names = {c["callee_name"] for c in result["callees"]}
        assert "ВалидироватьСтроки" in callee_names

    def test_depth_zero_returns_empty_callers(self) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        mock_index = self._make_mock_index()
        mock_index.find_callers.return_value = [
            {"caller_name": "Кто-то", "caller_file": "/ws/f.bsl", "caller_line": 1}
        ]
        result = build_call_graph(mock_index, "ОбработатьЗаказ", depth=0)

        assert result["callers"] == []

    def test_build_call_graph_with_real_index(
        self, populated_index: Any
    ) -> None:
        from bsl_analyzer.analysis.call_graph import build_call_graph

        result = build_call_graph(populated_index, "ЗаписатьЛог")

        assert result["name"] == "ЗаписатьЛог"
        assert isinstance(result["callers"], list)
        assert isinstance(result["callees"], list)
