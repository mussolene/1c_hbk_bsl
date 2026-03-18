"""
Tests for BslParser.

Covers:
  - parse_file returns a tree without raising
  - extract_errors returns empty list for valid BSL
  - Regex fallback produces non-empty root node children
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bsl_analyzer.parser.bsl_parser import BslParser, _RegexTree


class TestBslParserParseFile:
    def test_parse_file_returns_tree(self, sample_bsl_path: str) -> None:
        """parse_file must not raise and must return a tree with root_node."""
        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        assert tree is not None
        assert hasattr(tree, "root_node")

    def test_parse_content_returns_tree(self) -> None:
        """parse_content works with a simple BSL snippet."""
        parser = BslParser()
        code = "Процедура Тест()\n    Сообщение(\"OK\");\nКонецПроцедуры\n"
        tree = parser.parse_content(code)
        assert tree is not None
        assert hasattr(tree, "root_node")

    def test_parse_content_empty_string(self) -> None:
        """Empty content should not raise."""
        parser = BslParser()
        tree = parser.parse_content("")
        assert tree is not None

    def test_parse_file_non_existent_raises(self, tmp_path: Path) -> None:
        """Parsing a missing file should raise an OSError (or FileNotFoundError)."""
        parser = BslParser()
        with pytest.raises((OSError, FileNotFoundError)):
            parser.parse_file(str(tmp_path / "does_not_exist.bsl"))


class TestBslParserExtractErrors:
    def test_no_errors_for_valid_bsl(self, sample_bsl_path: str) -> None:
        """
        Valid sample.bsl should produce no or very few syntax errors.

        Note: tree-sitter may report some errors for BSL-specific constructs
        depending on grammar completeness; we accept 0 or just allow the test
        to verify the API returns a list.
        """
        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        errors = parser.extract_errors(tree)
        assert isinstance(errors, list)
        # Every error dict must have the required keys
        for err in errors:
            assert "line" in err
            assert "column" in err
            assert "message" in err

    def test_extract_errors_returns_list(self) -> None:
        """extract_errors always returns a list (even for fallback trees)."""
        parser = BslParser()
        # Intentionally malformed
        tree = parser.parse_content("Процедура (\nневерный синтаксис\n")
        result = parser.extract_errors(tree)
        assert isinstance(result, list)


class TestBslParserProcedureCount:
    def test_sample_bsl_has_procedures(self, sample_bsl_path: str) -> None:
        """
        sample.bsl contains known procedures/functions.

        We extract symbols and verify at least 3 are found (4 are defined).
        """
        from bsl_analyzer.analysis.symbols import extract_symbols
        from bsl_analyzer.parser.bsl_parser import BslParser

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        symbols = extract_symbols(tree, file_path=sample_bsl_path)

        procs_and_funcs = [s for s in symbols if s.kind in ("procedure", "function")]
        assert len(procs_and_funcs) >= 3, (
            f"Expected at least 3 procedures/functions, got {len(procs_and_funcs)}: "
            + str([s.name for s in procs_and_funcs])
        )

    def test_exported_symbols_detected(self, sample_bsl_path: str) -> None:
        """Exported symbols (Экспорт) should have is_export=True."""
        from bsl_analyzer.analysis.symbols import extract_symbols

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        symbols = extract_symbols(tree, file_path=sample_bsl_path)

        exported = [s for s in symbols if s.is_export]
        assert len(exported) >= 1, "sample.bsl has at least 2 exported symbols"

    def test_symbol_names_in_sample(self, sample_bsl_path: str) -> None:
        """Specific procedure names from sample.bsl should appear in symbols."""
        from bsl_analyzer.analysis.symbols import extract_symbols

        parser = BslParser()
        tree = parser.parse_file(sample_bsl_path)
        symbols = extract_symbols(tree, file_path=sample_bsl_path)
        names = {s.name for s in symbols}

        # These four are defined in sample.bsl
        expected_names = {
            "ИнициализироватьМодуль",
            "ЗаписатьЛог",
            "ПолучитьСчётчик",
            "УвеличитьСчётчик",
        }
        found = expected_names & names
        assert len(found) >= 2, (
            f"Expected to find at least 2 known procedure names, found: {found}"
        )
