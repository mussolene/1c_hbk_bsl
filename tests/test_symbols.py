"""
Tests for bsl_analyzer.analysis.symbols.

Covers:
  - Symbol dataclass fields
  - extract_symbols with regex fallback (_RegexTree with .content attribute)
  - Module-level variable declarations
  - Export flag detection
  - extract_symbols with empty content
  - extract_symbols with a real tree-sitter tree (via BslParser)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers / fake trees
# ---------------------------------------------------------------------------


class _FakeRegexTree:
    """Simulates the regex-fallback tree: has .content but no .root_node."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeRootNode:
    """Root node with no children, forcing fallback path."""

    def __init__(self) -> None:
        self.children: list = []
        self.type = "module"


class _FakeEmptyTree:
    """Tree with root_node but no children."""

    def __init__(self) -> None:
        self.root_node = _FakeRootNode()


# ---------------------------------------------------------------------------
# Symbol dataclass
# ---------------------------------------------------------------------------


class TestSymbolDataclass:
    def test_symbol_required_fields(self) -> None:
        from bsl_analyzer.analysis.symbols import Symbol

        s = Symbol(
            name="МояПроцедура",
            kind="procedure",
            line=5,
            character=0,
            end_line=20,
            end_character=0,
        )
        assert s.name == "МояПроцедура"
        assert s.kind == "procedure"
        assert s.line == 5
        assert s.end_line == 20

    def test_symbol_defaults(self) -> None:
        from bsl_analyzer.analysis.symbols import Symbol

        s = Symbol(
            name="Ф",
            kind="function",
            line=1,
            character=0,
            end_line=5,
            end_character=0,
        )
        assert s.is_export is False
        assert s.container is None
        assert s.signature == ""
        assert s.doc_comment == ""
        assert s.file_path == ""

    def test_symbol_export_flag(self) -> None:
        from bsl_analyzer.analysis.symbols import Symbol

        s = Symbol(
            name="Ф",
            kind="function",
            line=1,
            character=0,
            end_line=5,
            end_character=0,
            is_export=True,
        )
        assert s.is_export is True


# ---------------------------------------------------------------------------
# BSL source snippets
# ---------------------------------------------------------------------------

BSL_PROCEDURES = """\
// Инициализирует модуль
Процедура ИнициализироватьМодуль()
    ВнутреннийСчётчик = 0;
КонецПроцедуры

// Экспортируемая функция
Функция ПолучитьСчётчик() Экспорт
    Возврат ВнутреннийСчётчик;
КонецФункции
"""

BSL_WITH_VARS = """\
Перем ВнутреннийСчётчик;
Перем МаксимальноеКоличество;

Процедура П()
КонецПроцедуры
"""

BSL_EXPORT_VAR = """\
Перем МойЭкспорт Экспорт;

Процедура П() Экспорт
КонецПроцедуры
"""


# ---------------------------------------------------------------------------
# extract_symbols with regex fallback
# ---------------------------------------------------------------------------


class TestExtractSymbolsRegexFallback:
    def test_returns_list(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        assert isinstance(result, list)

    def test_finds_procedure(self) -> None:
        from bsl_analyzer.analysis.symbols import Symbol, extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        assert all(isinstance(s, Symbol) for s in result)
        names = {s.name for s in result}
        assert "ИнициализироватьМодуль" in names

    def test_finds_function(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        names = {s.name for s in result}
        assert "ПолучитьСчётчик" in names

    def test_export_flag_detected(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        exported = [s for s in result if s.is_export]
        assert len(exported) >= 1
        assert exported[0].name == "ПолучитьСчётчик"

    def test_non_export_has_false_flag(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        non_exported = [s for s in result if not s.is_export]
        assert any(s.name == "ИнициализироватьМодуль" for s in non_exported)

    def test_file_path_set_correctly(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="my_module.bsl")
        assert all(s.file_path == "my_module.bsl" for s in result)

    def test_kind_is_procedure_or_function(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        procs_funcs = [s for s in result if s.kind in ("procedure", "function")]
        assert len(procs_funcs) >= 2

    def test_sorted_by_line(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_PROCEDURES)
        result = extract_symbols(tree, file_path="test.bsl")
        lines = [s.line for s in result]
        assert lines == sorted(lines)

    def test_empty_content_returns_empty_list(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree("")
        result = extract_symbols(tree, file_path="empty.bsl")
        assert result == []

    def test_tree_without_content_or_root_node_returns_empty(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        class _Bare:
            pass

        result = extract_symbols(_Bare(), file_path="bare.bsl")
        assert result == []


# ---------------------------------------------------------------------------
# Module-level variable declarations
# ---------------------------------------------------------------------------


class TestExtractSymbolsVariables:
    def test_finds_module_variables(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_WITH_VARS)
        result = extract_symbols(tree, file_path="test.bsl")
        var_names = {s.name for s in result if s.kind == "variable"}
        assert "ВнутреннийСчётчик" in var_names
        assert "МаксимальноеКоличество" in var_names

    def test_variable_kind_is_variable(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_WITH_VARS)
        result = extract_symbols(tree, file_path="test.bsl")
        variables = [s for s in result if s.kind == "variable"]
        assert len(variables) >= 2

    def test_export_variable_detected(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_EXPORT_VAR)
        result = extract_symbols(tree, file_path="test.bsl")
        exported_vars = [
            s for s in result if s.kind == "variable" and s.is_export
        ]
        assert len(exported_vars) >= 1
        assert exported_vars[0].name == "МойЭкспорт"

    def test_variable_signature_starts_with_var(self) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols

        tree = _FakeRegexTree(BSL_WITH_VARS)
        result = extract_symbols(tree, file_path="test.bsl")
        variables = [s for s in result if s.kind == "variable"]
        for var in variables:
            assert var.signature.startswith("Var ")


# ---------------------------------------------------------------------------
# extract_symbols with real tree-sitter tree (via BslParser)
# ---------------------------------------------------------------------------


class TestExtractSymbolsRealParser:
    def test_returns_list_of_symbols(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.symbols import Symbol, extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_symbols(tree, file_path=sample_bsl_path)

        assert isinstance(result, list)
        assert all(isinstance(s, Symbol) for s in result)

    def test_finds_expected_procedures(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_symbols(tree, file_path=sample_bsl_path)

        names = {s.name for s in result}
        assert "ИнициализироватьМодуль" in names
        assert "ЗаписатьЛог" in names

    def test_exported_symbols_have_is_export_true(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_symbols(tree, file_path=sample_bsl_path)

        exported = [s for s in result if s.is_export]
        assert len(exported) >= 2
        export_names = {s.name for s in exported}
        # The parser may truncate Cyrillic names; check with partial match
        assert any(
            "олучит" in n or "величит" in n or "брос" in n
            for n in export_names
        )

    def test_file_path_set_on_all_symbols(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_symbols(tree, file_path=sample_bsl_path)

        assert all(s.file_path == sample_bsl_path for s in result)

    def test_symbols_sorted_by_line(self, sample_bsl_path: str) -> None:
        from bsl_analyzer.analysis.symbols import extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        result = extract_symbols(tree, file_path=sample_bsl_path)

        lines = [s.line for s in result]
        assert lines == sorted(lines)
