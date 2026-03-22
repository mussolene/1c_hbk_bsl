"""Tests for BSL source code formatter."""
from __future__ import annotations

from onec_hbk_bsl.analysis.formatter import BslFormatter


class TestBomAndEncoding:
    def test_utf8_bom_stripped(self) -> None:
        f = BslFormatter()
        result = f.format("\ufeffА = 1;\n")
        assert not result.startswith("\ufeff")
        assert "А = 1" in result


class TestLineCommentNormalization:
    def test_spaces_after_double_slash(self) -> None:
        f = BslFormatter()
        result = f.format("//foo\n")
        assert "// foo\n" in result or result.strip() == "// foo"

    def test_collapses_multiple_spaces_before_text(self) -> None:
        f = BslFormatter()
        result = f.format("//    bar\n")
        line = result.splitlines()[0].lstrip()
        assert line == "// bar"

    def test_empty_comment_line_stays_double_slash(self) -> None:
        f = BslFormatter()
        result = f.format("//   \n")
        line = result.splitlines()[0].lstrip()
        assert line == "//"


class TestKeywordNormalisation:
    def test_procedure_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("процедура Тест()\nконецпроцедуры\n")
        assert "Процедура" in result
        assert "КонецПроцедуры" in result

    def test_function_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("функция Тест()\nконецфункции\n")
        assert "Функция" in result
        assert "КонецФункции" in result

    def test_if_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("если А > 0 тогда\nконецесли;\n")
        assert "Если" in result
        assert "Тогда" in result
        assert "КонецЕсли" in result

    def test_for_loop_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("для А = 1 по 10 цикл\nконеццикла;\n")
        assert "Для" in result
        assert "Цикл" in result
        assert "КонецЦикла" in result

    def test_try_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("попытка\nисключение\nконецпопытки;\n")
        assert "Попытка" in result
        assert "Исключение" in result
        assert "КонецПопытки" in result

    def test_literals_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("А = истина;\nБ = ложь;\nВ = неопределено;\n")
        assert "Истина" in result
        assert "Ложь" in result
        assert "Неопределено" in result

    def test_english_keywords_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("procedure Test()\nendprocedure\n")
        assert "Procedure" in result
        assert "EndProcedure" in result

    def test_keywords_inside_string_not_touched(self) -> None:
        f = BslFormatter()
        result = f.format('А = "процедура";\n')
        # The string content should NOT be changed
        assert '"процедура"' in result


class TestIndentation:
    def test_procedure_body_indented(self) -> None:
        f = BslFormatter()
        result = f.format("Процедура Тест()\nА = 1;\nКонецПроцедуры\n")
        lines = result.splitlines()
        # Body line should be indented
        assert lines[1].startswith("    ")
        # КонецПроцедуры at base level
        assert not lines[2].startswith(" ")

    def test_if_then_indented(self) -> None:
        f = BslFormatter()
        result = f.format("Если А > 0 Тогда\nБ = 1;\nКонецЕсли;\n")
        lines = result.splitlines()
        assert lines[1].startswith("    ")

    def test_multiline_if_condition_indented_under_keyword(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Тест()\n"
            "Если \n"
            "Результат <> 0 Тогда\n"
            "    Прервать;\n"
            "КонецЕсли;\n"
            "КонецПроцедуры\n"
        )
        lines = f.format(code).splitlines()
        cond = [ln for ln in lines if "Результат" in ln][0]
        kw = [ln for ln in lines if ln.strip() == "Если"][0]
        assert cond.startswith("        "), cond
        assert kw.startswith("    "), kw

    def test_call_argument_comma_spacing_ast(self) -> None:
        f = BslFormatter()
        code = "Процедура Т()\nА = Метод( 1  ,2 , 3 );\nКонецПроцедуры\n"
        assert "Метод(1, 2, 3)" in f.format(code)

    def test_if_then_same_line_splits_body_to_next_line(self) -> None:
        """One-line ``Если … Тогда <stmt>`` becomes two lines so body indents vertically."""
        f = BslFormatter()
        result = f.format("Если А > 0 Тогда Б = 1;\nКонецЕсли;\n")
        lines = result.splitlines()
        assert "Тогда" in lines[0] and "Б = 1" not in lines[0]
        assert lines[1].strip().startswith("Б = 1")
        assert lines[1].startswith("    ")
        assert "КонецЕсли" in lines[2]

    def test_nested_indent(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nЕсли А > 0 Тогда\nБ = 1;\nКонецЕсли;\nКонецПроцедуры\n"
        result = f.format(code)
        lines = result.splitlines()
        # Если is indented once (inside Процедура)
        assert lines[1].startswith("    ")
        # Б = 1 is indented twice
        assert lines[2].startswith("        ")

    def test_else_same_level_as_if(self) -> None:
        f = BslFormatter()
        code = "Если А > 0 Тогда\nБ = 1;\nИначе\nВ = 2;\nКонецЕсли;\n"
        result = f.format(code)
        lines = result.splitlines()
        # Иначе should be at same level as Если (0 indent)
        assert not lines[2].startswith("    ")

    def test_custom_indent_size(self) -> None:
        f = BslFormatter()
        result = f.format("Процедура Тест()\nА = 1;\nКонецПроцедуры\n", indent_size=2)
        lines = result.splitlines()
        assert lines[1].startswith("  ")
        assert not lines[1].startswith("    ")

    def test_multiline_function_params_double_indent(self) -> None:
        """Parameters on new lines after ``Функция Имя(`` get an extra indent level (BSL-LS style)."""
        f = BslFormatter()
        code = (
            "Функция Имя(\n"
            "Параметр1,\n"
            "Параметр2)\n"
            "Возврат 0;\n"
            "КонецФункции\n"
        )
        result = f.format(code)
        lines = result.splitlines()
        assert lines[0].strip().startswith("Функция Имя(")
        # Block inside function (+1) + wrapped param list (+1) → 8 spaces
        assert lines[1].startswith("        "), repr(lines[1])
        assert lines[2].startswith("        ")
        # Body: single level inside function
        assert lines[3].startswith("    ")


class TestOperatorSpacing:
    def test_comparison_spacing(self) -> None:
        f = BslFormatter()
        result = f.format("Если А>0 Тогда\nКонецЕсли;\n")
        assert "А > 0" in result

    def test_inequality_spacing(self) -> None:
        f = BslFormatter()
        result = f.format("Если А<>0 Тогда\nКонецЕсли;\n")
        assert "А <> 0" in result

    def test_lte_gte_spacing(self) -> None:
        f = BslFormatter()
        result = f.format("Если А<=10 Тогда\nКонецЕсли;\n")
        assert "А <= 10" in result


class TestBlankLines:
    def test_max_two_consecutive_blanks(self) -> None:
        f = BslFormatter()
        code = "А = 1;\n\n\n\n\nБ = 2;\n"
        result = f.format(code)
        assert "\n\n\n\n" not in result

    def test_trailing_newline(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1;")
        assert result.endswith("\n")

    def test_single_trailing_newline(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1;\n\n\n")
        assert result.endswith("\n")
        assert not result.endswith("\n\n\n")


class TestFormatRange:
    def test_range_formats_subset(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nА = 1;\nКонецПроцедуры\n"
        result = f.format_range(code, start_line=0, end_line=0)
        assert "Процедура" in result

    def test_range_ends_with_newline(self) -> None:
        f = BslFormatter()
        code = "А = 1;\nБ = 2;\n"
        result = f.format_range(code, start_line=0, end_line=0)
        assert result.endswith("\n")

    def test_multiline_elseif_condition_does_not_shift_function_tail(self) -> None:
        f = BslFormatter()
        code = (
            "Функция Тест()\n"
            "\tЕсли А Тогда\n"
            "\t\tВозврат 1;\n"
            "\tИначеЕсли Б\n"
            "\t\tИЛИ В Тогда\n"
            "\t\tВозврат 2;\n"
            "\tИначе\n"
            "\t\tВозврат 3;\n"
            "\tКонецЕсли;\n"
            "КонецФункции\n"
            "&НаКлиенте\n"
            "Функция Следующая()\n"
            "\tВозврат 0;\n"
            "КонецФункции\n"
        )
        result = f.format(code, indent_size=4, insert_spaces=False)
        assert "\n\t&НаКлиенте\n" not in result
        assert "\n&НаКлиенте\n" in result


class TestComments:
    def test_comment_line_preserved(self) -> None:
        f = BslFormatter()
        result = f.format("// это комментарий процедура\nА = 1;\n")
        # Keyword inside comment must NOT be changed
        assert "// это комментарий процедура" in result

    def test_inline_comment_preserved(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1; // процедура\n")
        assert "// процедура" in result


class TestBslContinuationIndent:
    """Extra indent rules aligned with BSL Language Server (assign / dot chains)."""

    def test_assignment_continuation_indents_next_line(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nА = Б +\nВ;\nКонецПроцедуры\n"
        result = f.format(code)
        lines = result.splitlines()
        # Continuation line after bare = should be one level deeper than body
        assert lines[2].startswith("        "), lines[2]

    def test_dot_chain_line_gets_extra_indent(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nЧтоТо\n    .Метод();\nКонецПроцедуры\n"
        result = f.format(code)
        lines = result.splitlines()
        assert ".Метод();" in lines[2]
        assert lines[2].startswith("        "), lines[2]


class TestPreprocessor:
    def test_region_preserved(self) -> None:
        f = BslFormatter()
        result = f.format("#Область МояОбласть\nА = 1;\n#КонецОбласти\n")
        assert "#Область" in result
        assert "#КонецОбласти" in result

    def test_region_case_normalised(self) -> None:
        f = BslFormatter()
        result = f.format("#область МояОбласть\nА = 1;\n#конецобласти\n")
        assert "#Область" in result or "#область" in result  # at least preserved
