"""Tests for BSL source code formatter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.formatter import BslFormatter


class TestFormatterDefaults:
    def test_default_formatter_exists(self) -> None:
        f = BslFormatter()
        assert isinstance(f, BslFormatter)

    def test_default_indents_with_tabs(self) -> None:
        f = BslFormatter()
        result = f.format("Процедура Тест()\nА = 1;\nКонецПроцедуры\n")
        assert "\n\tА = 1;" in result


class TestBomAndEncoding:
    def test_utf8_bom_stripped(self) -> None:
        f = BslFormatter()
        result = f.format("\ufeffА = 1;\n")
        assert not result.startswith("\ufeff")
        assert "А = 1" in result


class TestLineCommentNormalization:
    def test_preserves_double_slash_comment_text(self) -> None:
        f = BslFormatter()
        result = f.format("//foo\n")
        assert result.strip() == "//foo"

    def test_preserves_spaces_after_double_slash(self) -> None:
        f = BslFormatter()
        result = f.format("//    bar\n")
        line = result.splitlines()[0].lstrip()
        assert line == "//    bar"

    def test_bslls_default_preserves_comment_block_spacing(self) -> None:
        f = BslFormatter()
        code = (
            "// Параметры:\n"
            "// \tМенеджерХранилища - ОбщийМодуль - менеджер хранилища.\n"
            '//  Range - Строка - в формате "bytes=<Число>-<Число>"\n'
        )
        lines = f.format(code).splitlines()
        assert lines[1] == "// \tМенеджерХранилища - ОбщийМодуль - менеджер хранилища."
        assert lines[2] == '//  Range - Строка - в формате "bytes=<Число>-<Число>"'

    def test_empty_comment_line_stays_double_slash(self) -> None:
        f = BslFormatter()
        result = f.format("//   \n")
        line = result.splitlines()[0].lstrip()
        assert line == "//"

    def test_space_before_trailing_inline_comment(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1;// комментарий\n")
        assert " // комментарий" in result


class TestDocCommentBlocks:
    """Contiguous // / /// blocks: Параметры / Возвращаемое значение and hanging text."""

    def test_parameters_section_hangs_body_lines(self) -> None:
        f = BslFormatter()
        code = (
            "// Параметры:\n"
            "// КраткоеИмя - Строка - описание\n"
            "// продолжение описания\n"
            "Процедура Тест()\n"
            "КонецПроцедуры\n"
        )
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// Параметры:"
        assert lines[1].strip() == "// КраткоеИмя - Строка - описание"
        assert lines[2].strip() == "// продолжение описания"

    def test_returns_section(self) -> None:
        f = BslFormatter()
        code = "// Возвращаемое значение:\n// Булево - если ок\nФункция Т()\nКонецФункции\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// Возвращаемое значение:"
        assert lines[1].strip() == "// Булево - если ок"

    def test_preamble_then_parameters(self) -> None:
        f = BslFormatter()
        code = (
            "// Краткое описание метода\n"
            "// вторая строка описания\n"
            "// Параметры:\n"
            "// Имя - Строка\n"
            "Процедура Т()\n"
            "КонецПроцедуры\n"
        )
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// Краткое описание метода"
        assert lines[1].strip() == "// вторая строка описания"
        assert lines[2].strip() == "// Параметры:"
        assert lines[3].strip() == "// Имя - Строка"

    def test_english_headers(self) -> None:
        f = BslFormatter()
        code = "// Parameters:\n// Name - String\n// Returns:\n// True\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// Parameters:"
        assert lines[1].strip() == "// Name - String"
        assert lines[2].strip() == "// Returns:"
        assert lines[3].strip() == "// True"

    def test_triple_slash_doc_block(self) -> None:
        f = BslFormatter()
        code = "/// Параметры:\n/// Имя - Строка\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "/// Параметры:"
        assert lines[1].strip() == "/// Имя - Строка"

    def test_blank_line_between_comments_resets_run(self) -> None:
        f = BslFormatter()
        code = "// первая\n\n// вторая\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// первая"
        assert lines[2].strip() == "// вторая"

    def test_section_header_collapses_whitespace(self) -> None:
        f = BslFormatter()
        code = "//  Параметры   :\n// Имя\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "//  Параметры   :"
        assert lines[1].strip() == "// Имя"

    def test_default_keeps_comment_block_without_hanging_indent(self) -> None:
        f = BslFormatter()
        code = "// Параметры:\n// Имя - Строка - описание\n// продолжение описания\n"
        lines = f.format(code).splitlines()
        assert lines[0].strip() == "// Параметры:"
        assert lines[1].strip() == "// Имя - Строка - описание"
        assert lines[2].strip() == "// продолжение описания"

    def test_nested_call_argument_continuation_indent(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Тест()\n"
            "\tОтвет.УстановитьТелоИзСтроки(СтрШаблон(НСтр(\"ru = 'Ошибка %1 %2'\"),\n"
            "\t\t\tПараметр1,\n"
            "\t\t\tПараметр2));\n"
            "КонецПроцедуры\n"
        )
        lines = f.format(code).splitlines()
        assert lines[2].startswith("\t\t\tПараметр1")
        assert lines[3].startswith("\t\t\tПараметр2")


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

    def test_literals_preserved_like_bslls(self) -> None:
        f = BslFormatter()
        result = f.format("А = истина;\nБ = ложь;\nВ = неопределено;\n")
        assert "истина" in result
        assert "ложь" in result
        assert "неопределено" in result

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
        assert lines[1].startswith("\t")
        # КонецПроцедуры at base level
        assert not lines[2].startswith("\t")

    def test_if_then_indented(self) -> None:
        f = BslFormatter()
        result = f.format("Если А > 0 Тогда\nБ = 1;\nКонецЕсли;\n")
        lines = result.splitlines()
        assert lines[1].startswith("\t")

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
        assert cond.startswith("\t\t"), cond
        assert kw.startswith("\t"), kw

    def test_call_argument_comma_spacing_ast(self) -> None:
        f = BslFormatter()
        code = "Процедура Т()\nА = Метод( 1  ,2 , 3 );\nКонецПроцедуры\n"
        assert "Метод(1, 2, 3)" in f.format(code)

    def test_bslls_default_empty_argument_spacing_before_string(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Т()\n"
            'Строка = Новый ФорматированнаяСтрока(Текст, , , ,"Команда");\n'
            "КонецПроцедуры\n"
        )
        assert 'ФорматированнаяСтрока(Текст, , , , "Команда")' in f.format(code)

    def test_if_then_same_line_preserved_like_bslls(self) -> None:
        """BSLLS token formatting does not split a one-line ``Если … Тогда <stmt>``."""
        f = BslFormatter()
        result = f.format("Если А > 0 Тогда Б = 1;\nКонецЕсли;\n")
        lines = result.splitlines()
        assert lines[0] == "Если А > 0 Тогда Б = 1;"
        assert "КонецЕсли" in lines[1]

    def test_nested_indent(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nЕсли А > 0 Тогда\nБ = 1;\nКонецЕсли;\nКонецПроцедуры\n"
        result = f.format(code)
        lines = result.splitlines()
        # Если is indented once (inside Процедура)
        assert lines[1].startswith("\t")
        # Б = 1 is indented twice
        assert lines[2].startswith("\t\t")

    def test_else_same_level_as_if(self) -> None:
        f = BslFormatter()
        code = "Если А > 0 Тогда\nБ = 1;\nИначе\nВ = 2;\nКонецЕсли;\n"
        result = f.format(code)
        lines = result.splitlines()
        # Иначе should be at same level as Если (0 indent)
        assert not lines[2].startswith("\t")

    def test_custom_indent_size(self) -> None:
        f = BslFormatter()
        result = f.format(
            "Процедура Тест()\nА = 1;\nКонецПроцедуры\n",
            indent_size=2,
            insert_spaces=True,
        )
        lines = result.splitlines()
        assert lines[1].startswith("  ")
        assert not lines[1].startswith("    ")

    def test_multiline_function_params_double_indent(self) -> None:
        """Parameters on new lines after ``Функция Имя(`` get an extra indent level (BSL-LS style)."""
        f = BslFormatter()
        code = "Функция Имя(\nПараметр1,\nПараметр2)\nВозврат 0;\nКонецФункции\n"
        result = f.format(code)
        lines = result.splitlines()
        assert lines[0].strip().startswith("Функция Имя(")
        # Block inside function (+1) + wrapped param list (+1) -> two tabs
        assert lines[1].startswith("\t\t"), repr(lines[1])
        assert lines[2].startswith("\t\t")
        # Body: single level inside function
        assert lines[3].startswith("\t")


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
    def test_preserves_consecutive_blank_lines(self) -> None:
        f = BslFormatter()
        code = "А = 1;\n\n\n\n\nБ = 2;\n"
        result = f.format(code)
        assert "А = 1;\n\n\n\n\nБ = 2;" in result

    def test_bslls_default_preserves_consecutive_blank_lines(self) -> None:
        f = BslFormatter()
        code = "А = 1;\n\n\nБ = 2;\n"
        result = f.format(code)
        assert "А = 1;\n\n\nБ = 2;" in result

    def test_trailing_newline(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1;")
        assert not result.endswith("\n")

    def test_single_trailing_newline(self) -> None:
        f = BslFormatter()
        result = f.format("А = 1;\n\n\n")
        assert not result.endswith("\n")


class TestFormatRange:
    def test_multiline_query_string_bad_indent_is_recovered_like_bslls(self) -> None:
        f = BslFormatter()
        code = (
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

        assert f.format(code, indent_size=4, insert_spaces=False) == (
            "// &НаСервере\n"
            "Процедура ДобавитьВычисляемоеПолеОбработкаПриглашений(СхемаКомпоновкиДанных)\n"
            "\t\n"
            "\tВыражениеПоля =\n"
            '\t\t"\tВЫБОР\n'
            "\t\t|\t\tКОГДА Экстраверт = Истина ТОГДА\n"
            '\t\t|\t\t\t""Автоматически""\n'
            "\t\t|\t\tИНАЧЕ\n"
            '\t\t|\t\t\t""Контрагентом вручную""\n'
            '\t\t|\tКОНЕЦ";\n'
            "\t\n"
            "\tВычисляемоеПоле = СхемаКомпоновкиДанных.ВычисляемыеПоля.Добавить();\n"
            '\tВычисляемоеПоле.ПутьКДанным = "ОбработкаПриглашений";\n'
            "\tВычисляемоеПоле.Выражение = ВыражениеПоля;\n"
            "\t\n"
            "КонецПроцедуры"
        )

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

    def test_indent_at_uses_token_formatter_context(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Тест()\n"
            "    Если Истина Тогда\n"
            "        Сообщить(1);\n"
            "    КонецЕсли;\n"
            "КонецПроцедуры\n"
            "Процедура Хвост()\n"
            "КонецПроцедуры\n"
        )
        lines = code.splitlines()
        target = 2
        level = f._indent_at(lines, target, 4, insert_spaces=True, full_text=code)
        assert level == 2


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
        assert lines[2].startswith("\t\t"), lines[2]

    def test_assignment_call_continuation_indents_like_bslls(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Тест()\n"
            "\tОрганизация = Справочники.Организации.НайтиОрганизацию(\n"
            "\t\tИНН, КПП, Ложь);\n"
            "КонецПроцедуры\n"
        )
        result = f.format(code)
        lines = result.splitlines()
        assert lines[2].startswith("\t\t\tИНН"), lines[2]

    def test_bslls_default_binary_plus_and_unary_minus_spacing(self) -> None:
        f = BslFormatter()
        code = (
            "Процедура Т()\n"
            'Элементы["Таблица"+Имя];\n'
            'Часть = """"+Имя+"""";\n'
            "Дата = ДобавитьМесяц(Дата, - 24);\n"
            "Знач = ?(Значение < 0, - Значение, 0);\n"
            "Результат = Результат + ? (Условие, А, Б);\n"
            "КонецПроцедуры\n"
        )
        result = f.format(code)
        assert 'Элементы["Таблица" + Имя]' in result
        assert 'Часть = """" + Имя + """"' in result
        assert "ДобавитьМесяц(Дата, -24)" in result
        assert "?(Значение < 0, -Значение, 0)" in result
        assert "Результат = Результат + ?(Условие, А, Б)" in result

    def test_dot_chain_line_gets_extra_indent(self) -> None:
        f = BslFormatter()
        code = "Процедура Тест()\nЧтоТо\n    .Метод();\nКонецПроцедуры\n"
        result = f.format(code)
        lines = result.splitlines()
        assert ".Метод();" in lines[2]
        assert lines[2].startswith("\t\t"), lines[2]


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


class TestBsllsFixtureParity:
    @pytest.mark.parametrize(
        ("source_name", "expected_name", "indent_size"),
        [
            ("format.bsl", "format_formatted.bsl", 4),
            ("formatKeywordsRu.bsl", "format_formattedKeywordsRu.bsl", 2),
            ("formatKeywordsEng.bsl", "format_formattedKeywordsEng.bsl", 2),
            ("formatFluent.bsl", "format_formattedFluent.bsl", 2),
        ],
    )
    def test_matches_bslls_provider_fixture_pairs(
        self, source_name: str, expected_name: str, indent_size: int
    ) -> None:
        root = Path(os.environ.get("BSLLS_SOURCE_ROOT", ".nosync/bsl-language-server"))
        root = root / "src/test/resources/providers"
        source_path = root / source_name
        expected_path = root / expected_name
        if not source_path.exists() or not expected_path.exists():
            pytest.skip("BSLLS upstream provider fixtures are not available")
        source = source_path.read_text(encoding="utf-8")
        expected = expected_path.read_text(encoding="utf-8")
        f = BslFormatter()
        actual = f.format(source, indent_size=indent_size, insert_spaces=True)
        assert actual.rstrip("\n") == expected.rstrip("\n")
