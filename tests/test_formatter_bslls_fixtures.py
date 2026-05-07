"""Formatter parity checks derived from BSLLS ``FormatProviderTest`` fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.formatter import BslFormatter

_BSLLS_PROVIDER_FIXTURES = (
    Path(
        os.environ.get(
            "BSLLS_SOURCE_ROOT",
            str(Path(__file__).resolve().parents[1] / ".nosync" / "bsl-language-server"),
        )
    )
    / "src"
    / "test"
    / "resources"
    / "providers"
)


def _fixture(name: str) -> str:
    path = _BSLLS_PROVIDER_FIXTURES / name
    if not path.exists():
        pytest.skip(f"BSLLS formatter fixture is not available: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("source_name", "expected_name", "indent_size"),
    [
        ("formatKeywordsRu.bsl", "format_formattedKeywordsRu.bsl", 2),
        ("formatKeywordsEng.bsl", "format_formattedKeywordsEng.bsl", 2),
    ],
)
def test_bslls_keyword_fixture_parity(
    source_name: str,
    expected_name: str,
    indent_size: int,
) -> None:
    formatter = BslFormatter()
    assert formatter.format(_fixture(source_name), indent_size=indent_size, insert_spaces=True) == _fixture(
        expected_name
    )


def test_bslls_unary_minus_fixture_parity() -> None:
    formatter = BslFormatter()
    assert formatter.format("Возврат-1>-2", indent_size=4, insert_spaces=True) == "Возврат -1 > -2"


def test_bslls_general_fixture_parity() -> None:
    formatter = BslFormatter()
    assert formatter.format(_fixture("format.bsl"), indent_size=4, insert_spaces=True) == _fixture(
        "format_formatted.bsl"
    )


def test_bslls_range_fixture_parity() -> None:
    formatter = BslFormatter()
    source = _fixture("format.bsl")
    expected_lines = _fixture("format_formatted.bsl").split("\n")
    expected_range = "\n".join(line for index, line in enumerate(expected_lines) if 4 <= index <= 25)
    assert formatter.format_range(source, 4, 25, indent_size=4, insert_spaces=True) == expected_range


def test_bslls_fluent_fixture_parity() -> None:
    formatter = BslFormatter()
    assert formatter.format(_fixture("formatFluent.bsl"), indent_size=2, insert_spaces=True) == _fixture(
        "format_formattedFluent.bsl"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            'Процедура Тест()\n'
            '\tЗапрос = Новый Запрос("ВЫБРАТЬ\n'
            '\t                      |Поле\n'
            '\t                      |" +\n'
            "\t                      ?(Условие,\n"
            '\t                      "\tИ Поле <> &А",\n'
            '\t                      "\tИ Поле = &А") +\n'
            '\t                      "\n'
            '\t                      |И НЕ Поле");\n'
            "КонецПроцедуры\n",
            'Процедура Тест()\n'
            '\tЗапрос = Новый Запрос("ВЫБРАТЬ\n'
            "\t\t\t|Поле\n"
            '\t\t\t|" +\n'
            "\t\t\t?(Условие,\n"
            '\t\t\t\t"\tИ Поле <> &А",\n'
            '\t\t\t\t"\tИ Поле = &А") +\n'
            '\t\t\t"\n'
            '\t\t\t|И НЕ Поле");\n'
            "КонецПроцедуры",
        ),
        (
            'Процедура Тест()\n'
            "\tЕсли Условие Тогда\n"
            '\t\tЗапрос.Текст = Запрос.Текст + "\n'
            '\t\t                  |\tИ Поле = &Поле";\n'
            "\tКонецЕсли;\n"
            '\tЗапрос.Текст = Запрос.Текст + "\n'
            "\t\t            |УПОРЯДОЧИТЬ ПО\n"
            '\t\t            |\tПоле";\n'
            "КонецПроцедуры\n",
            'Процедура Тест()\n'
            "\tЕсли Условие Тогда\n"
            '\t\tЗапрос.Текст = Запрос.Текст + "\n'
            '\t\t\t|\tИ Поле = &Поле";\n'
            "\tКонецЕсли;\n"
            '\tЗапрос.Текст = Запрос.Текст + "\n'
            "\t\t|УПОРЯДОЧИТЬ ПО\n"
            '\t\t|\tПоле";\n'
            "КонецПроцедуры",
        ),
        (
            "Процедура Тест()\n"
            "\tЭтоОшибка = (Тип = А\n"
            "\t            ИЛИ Тип = Б\n"
            "\t            ИЛИ Тип = В);\n"
            "КонецПроцедуры\n",
            "Процедура Тест()\n"
            "\tЭтоОшибка = (Тип = А\n"
            "\t\t\tИЛИ Тип = Б\n"
            "\t\t\tИЛИ Тип = В);\n"
            "КонецПроцедуры",
        ),
        (
            "Процедура Тест()\n"
            '\tФайл = Таблица.НайтиСтроки(Новый Структура("Имя","packageDescription.xml"));\n'
            '\tФайл2 = Таблица.НайтиСтроки(Новый Структура("Имя" ,"packageDescription.xml"));\n'
            "КонецПроцедуры\n",
            "Процедура Тест()\n"
            '\tФайл = Таблица.НайтиСтроки(Новый Структура("Имя", "packageDescription.xml"));\n'
            '\tФайл2 = Таблица.НайтиСтроки(Новый Структура("Имя", "packageDescription.xml"));\n'
            "КонецПроцедуры",
        ),
        (
            "Процедура Тест()\n"
            '\tПредставление = "" + Объект.Предмет + ". Отправка" ;\n'
            "КонецПроцедуры\n",
            "Процедура Тест()\n"
            '\tПредставление = "" + Объект.Предмет + ". Отправка";\n'
            "КонецПроцедуры",
        ),
    ],
)
def test_bslls_large_file_gap_repro_cases(source: str, expected: str) -> None:
    formatter = BslFormatter()
    assert formatter.format(source) == expected
