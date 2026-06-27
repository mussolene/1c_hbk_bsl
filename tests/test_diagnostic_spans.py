from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def _single_diag(content: str, code: str, tmp_path: Path, **engine_kwargs):
    path = tmp_path / "Module.bsl"
    path.write_text(content, encoding="utf-8")
    diags = DiagnosticEngine(select={code}, **engine_kwargs).check_file(str(path))
    assert diags, f"expected at least one {code} diagnostic"
    return diags[0]


def test_bsl014_uses_full_line_span_from_column_zero(tmp_path: Path) -> None:
    diag = _single_diag('А = "' + ("x" * 130) + '";\n', "BSL014", tmp_path)
    assert diag.character == 0
    assert diag.end_character > 120


def test_bsl011_attaches_to_method_name_span(tmp_path: Path) -> None:
    content = """\
Функция ОченьСложнаяФункция(Знач А, Знач Б, Знач В) Экспорт
    Если А Тогда
        Если Б Тогда
            Если В Тогда
                Возврат 1;
            ИначеЕсли А Тогда
                Возврат 2;
            Иначе
                Возврат 3;
            КонецЕсли;
        Иначе
            Возврат 4;
        КонецЕсли;
    ИначеЕсли Б Тогда
        Возврат 5;
    Иначе
        Возврат 6;
    КонецЕсли;
КонецФункции
"""
    diag = _single_diag(content, "BSL011", tmp_path, max_cognitive_complexity=1)
    header = content.splitlines()[0]
    start = header.index("ОченьСложнаяФункция")
    assert diag.character == start
    assert diag.end_character == start + len("ОченьСложнаяФункция")


def test_bsl019_attaches_to_method_name_span(tmp_path: Path) -> None:
    content = """\
Функция СложнаяФункция(Знач А, Знач Б, Знач В) Экспорт
    Если А Тогда
        Возврат 1;
    КонецЕсли;
    Если Б Тогда
        Возврат 2;
    КонецЕсли;
    Если В Тогда
        Возврат 3;
    КонецЕсли;
    Для Каждого Элемент Из Новый Массив Цикл
        Если Элемент = Неопределено Тогда
            Возврат 4;
        КонецЕсли;
    КонецЦикла;
    Возврат 0;
КонецФункции
"""
    diag = _single_diag(content, "BSL019", tmp_path, max_mccabe_complexity=1)
    header = content.splitlines()[0]
    start = header.index("СложнаяФункция")
    assert diag.character == start
    assert diag.end_character == start + len("СложнаяФункция")


def test_bsl008_attaches_to_method_name_span(tmp_path: Path) -> None:
    content = """\
Функция МногоВыходов(Знач А) Экспорт
    Если А = 1 Тогда
        Возврат 1;
    КонецЕсли;
    Если А = 2 Тогда
        Возврат 2;
    КонецЕсли;
    Если А = 3 Тогда
        Возврат 3;
    КонецЕсли;
    Возврат 0;
КонецФункции
"""
    diag = _single_diag(content, "BSL008", tmp_path, max_returns=3)
    header = content.splitlines()[0]
    start = header.index("МногоВыходов")
    assert diag.character == start
    assert diag.end_character == start + len("МногоВыходов")


def test_bsl173_uses_catalog_message(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Для Каждого Элемент Из Коллекция Цикл
        Коллекция.Удалить(Элемент);
    КонецЦикла;
КонецПроцедуры
"""
    diag = _single_diag(content, "BSL173", tmp_path)
    assert diag.message == get_rule("BSL173").message


def test_bsl036_uses_bslls_condition_parts_threshold(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Если А И Б И В И Г Тогда
        Возврат;
    КонецЕсли;
КонецПроцедуры
"""
    diag = _single_diag(content, "BSL036", tmp_path)
    assert diag.line == 2
    assert diag.character == len("    Если ")


def test_bsl020_uses_bslls_default_nesting_depth(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Если А Тогда
        Если Б Тогда
            Если В Тогда
                Если Г Тогда
                    Если Д Тогда
                        Возврат;
                    КонецЕсли;
                КонецЕсли;
            КонецЕсли;
        КонецЕсли;
    КонецЕсли;
КонецПроцедуры
"""
    diag = _single_diag(content, "BSL020", tmp_path)
    assert diag.line == 6


def test_bsl029_preserves_column_after_string_literals(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Таблица.Колонки.Добавить("Сумма", ОбщегоНазначения.ОписаниеТипаЧисло(15, 2));
КонецПроцедуры
"""
    path = tmp_path / "Module.bsl"
    path.write_text(content, encoding="utf-8")
    diags = DiagnosticEngine(select={"BSL029"}).check_file(str(path))
    cols = [d.character for d in diags]
    assert cols == [73, 77]


def test_bsl199_attaches_to_konec_esli_token(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Если А Тогда
        Возврат;
    ИначеЕсли Б Тогда
        Возврат;
    КонецЕсли;
КонецПроцедуры
"""
    diag = _single_diag(content, "BSL199", tmp_path)
    assert diag.line == 6
    assert diag.character == len("    КонецЕсли;") - len("    КонецЕсли;".lstrip())
    assert diag.severity.name == "WARNING"


def test_bsl155_ignores_utf8_bom_before_preprocessor(tmp_path: Path) -> None:
    content = """\
\ufeff
#Если Сервер Тогда
#КонецЕсли

Процедура Тест()
КонецПроцедуры
"""
    path = tmp_path / "Module.bsl"
    path.write_text(content, encoding="utf-8")
    diags = DiagnosticEngine(select={"BSL155"}).check_file(str(path))
    assert not diags


def test_bsl156_ignores_utf8_bom_before_regions(tmp_path: Path) -> None:
    content = """\
\ufeff
#Если Сервер Тогда
#Область ПрограммныйИнтерфейс
Процедура Тест()
КонецПроцедуры
#КонецОбласти
#КонецЕсли
"""
    path = tmp_path / "CommonModules" / "ПервыйОбщийМодуль" / "Ext" / "Module.bsl"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    diags = DiagnosticEngine(select={"BSL156"}).check_file(str(path))
    assert not diags
