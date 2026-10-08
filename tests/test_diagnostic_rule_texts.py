from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule, render_rule_message
from onec_hbk_bsl.analysis.diagnostics import (
    _BSLLS_NAME_TO_CODE,
    RULE_DESCRIPTIONS_RU,
    RULE_METADATA,
    Diagnostic,
    Severity,
    lsp_compat_severity,
)


def _load_rules_doc_builder():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_diagnostic_rules_doc.py"
    spec = importlib.util.spec_from_file_location("build_diagnostic_rules_doc", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_bslls_rules_have_ru_titles() -> None:
    assert set(RULE_DESCRIPTIONS_RU) == set(_BSLLS_NAME_TO_CODE.values())


def test_problematic_ru_titles_match_bslls_meaning() -> None:
    expected = {
        "BSL022": "Использование модальных окон",
        "BSL025": "Пустой оператор",
        "BSL065": "Отсутствует описание возвращаемого значения функции",
        "BSL174": "Запрет незаполненных значений у измерений регистров",
    }
    for code, title in expected.items():
        assert RULE_DESCRIPTIONS_RU[code] == title
        assert get_rule(code).description == title
        assert get_rule(code).message


def test_metadata_descriptions_use_bslls_english_titles() -> None:
    expected = {
        "BSL022": "Using modal windows",
        "BSL025": "Empty statement",
        "BSL065": "Function returned values description is missing",
        "BSL174": "Deny incomplete values for dimensions",
    }
    for code, title in expected.items():
        assert RULE_METADATA[code]["description"] == title


def test_public_rule_descriptions_are_localized_for_ui() -> None:
    expected = {
        "BSL022": "Использование модальных окон",
        "BSL025": "Пустой оператор",
        "BSL065": "Отсутствует описание возвращаемого значения функции",
        "BSL174": "Запрет незаполненных значений у измерений регистров",
    }
    for code, title in expected.items():
        assert get_rule(code).description == title


def test_structured_diagnostics_include_catalog_message() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL159",
    )

    assert get_rule("BSL159").message == "Общий модуль недопустимого типа"
    assert diag.to_dict(include_rule_name=True)["rule_message"] == (
        "Общий модуль недопустимого типа"
    )


def test_rule_catalog_resolves_code_and_bslls_name_to_same_rule() -> None:
    by_code = get_rule("BSL236")
    by_name = get_rule("QueryToMissingMetadata")

    assert by_code == by_name
    assert by_code.code == "BSL236"
    assert by_code.name == "QueryToMissingMetadata"
    assert by_code.description == "Обращение к несуществующим метаданным в запросе"
    assert by_code.message == "Обращение к несуществующим метаданным в запросе"
    assert by_code.severity == "ERROR"
    assert by_code.tags == ("query", "correctness")
    assert by_code.implemented is True


def test_rule_catalog_can_return_english_rule_text() -> None:
    rule = get_rule("RefOveruse", locale="en")

    assert rule.code == "BSL238"
    assert rule.name == "RefOveruse"
    assert rule.description == 'Overuse "Reference" in a query'
    assert rule.message == 'Get rid of getting the "Reference" field in the query.'


def test_bsl241_rule_catalog_severity_matches_emitted_error() -> None:
    rule = get_rule("BSL241")

    assert rule.name == "SameMetadataObjectAndChildNames"
    assert rule.severity == "ERROR"


def test_diagnostic_uses_i18n_message_by_default() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL236",
    )

    assert diag.message == get_rule("BSL236").message


def test_diagnostic_renders_structured_message_arguments() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=12,
        severity=Severity.INFORMATION,
        code="BSL176",
        message_args=("СтарыйМетод", " Используйте НовыйМетод."),
    )

    assert diag.message == (
        'Удалите обращение к устаревшему "СтарыйМетод". Используйте НовыйМетод.'
    )
    assert diag.to_dict()["message"] == diag.message


def test_diagnostic_accepts_explicit_occurrence_message() -> None:
    diag = Diagnostic(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=12,
        severity=Severity.INFORMATION,
        code="BSL175",
        message='Метод "СтарыйМетод" устарел. Используйте "НовыйМетод".',
    )

    assert diag.message == 'Метод "СтарыйМетод" устарел. Используйте "НовыйМетод".'


def test_diagnostic_rejects_ambiguous_or_unrendered_message() -> None:
    common = dict(
        file="m.bsl",
        line=1,
        character=0,
        end_line=1,
        end_character=1,
        severity=Severity.ERROR,
        code="BSL196",
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        Diagnostic(**common, message="Текст", message_args=("Метод",))
    with pytest.raises(ValueError, match="unrendered placeholder"):
        Diagnostic(**common, message='Метод "%s" устарел')


def test_catalog_never_exposes_unrendered_placeholders() -> None:
    for code in RULE_METADATA:
        for locale in ("ru", "en"):
            assert "%s" not in get_rule(code, locale=locale).message
            assert "%d" not in get_rule(code, locale=locale).message


@pytest.mark.parametrize("code", ["BSL002", "BSL011", "BSL019"])
def test_english_numeric_message_templates(code: str) -> None:
    message = render_rule_message(code, "Method", 11, 10, locale="en")
    assert '"Method"' in message
    assert "11" in message
    assert "10" in message
    with pytest.raises(ValueError, match="expects 3 argument"):
        render_rule_message(code, "Method", locale="en")
    with pytest.raises(ValueError, match="arguments are invalid"):
        render_rule_message(code, "Method", "eleven", 10, locale="en")


def test_message_template_rendering_validates_arity() -> None:
    assert render_rule_message("BSL196", "СтарыйМетод") == (
        'Метод "СтарыйМетод" должен быть удален или переименован'
    )
    with pytest.raises(ValueError, match="expects 1 argument"):
        render_rule_message("BSL196")
    with pytest.raises(ValueError, match="expects 1 argument"):
        render_rule_message("BSL196", "one", "two")


def test_parameterized_rules_supply_occurrence_message_data() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "onec_hbk_bsl"
    parameterized_codes = {
        code for code in RULE_METADATA if "%s" in get_rule(code).message_template
    }
    missing: list[str] = []
    for source_path in root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            keywords = {item.arg: item.value for item in call.keywords if item.arg is not None}
            code_node = keywords.get("code")
            if not (
                isinstance(code_node, ast.Constant)
                and isinstance(code_node.value, str)
                and code_node.value in parameterized_codes
            ):
                continue
            function_name = ast.unparse(call.func)
            if not function_name.endswith(("Diagnostic", "add_range", "add_match")):
                continue
            if "message" not in keywords and "message_args" not in keywords:
                missing.append(f"{source_path.relative_to(root)}:{call.lineno}:{code_node.value}")

    assert missing == []


def test_lsp_compat_severity_documents_bslls_facing_source_of_truth() -> None:
    expected = {
        "BSL156": Severity.HINT,  # CodeOutOfRegion
        "BSL256": Severity.HINT,  # Typo
        "BSL200": Severity.HINT,  # IncorrectLineBreak
        "BSL249": Severity.ERROR,  # StyleElementConstructors
    }
    for code, severity in expected.items():
        metadata_severity = Severity[RULE_METADATA[code]["severity"]]
        assert lsp_compat_severity(code, metadata_severity) is severity


# Frozen from BSLLS v1.0.7 *_ru.properties diagnosticMessage entries.
@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("BSL004", "Наполните блок кодом или удалите его"),
        ("BSL005", "Используется хранение в коде ip-адреса"),
        ("BSL006", "Используется хранение в коде пути к файлу"),
        ("BSL009", "Удалите бесполезное присваивание переменной самой себе"),
        ("BSL012", "Используется хранение конфиденциальной информации в коде"),
        ("BSL013", "Программные модули не должны иметь закомментированных фрагментов кода"),
        ("BSL017", "Не следует размещать экспортные методы в модулях команд и общих команд"),
        ("BSL020", "Превышен допустимый уровень вложенности управляющих конструкций"),
        (
            "BSL024",
            "Между символами комментария '//' и самим текстом комментария должен быть пробел.",
        ),
        ("BSL025", 'Удалите ";"'),
        ("BSL027", 'Оператор "Перейти" не должен использоваться'),
        ("BSL028", 'Отсутствует код в блоке "Исключение"'),
        ("BSL030", "Пропущена точка с запятой в конце выражения"),
        ("BSL032", 'Функция не содержит "Возврат"'),
        (
            "BSL033",
            "Необходимо модифицировать запрос для поддержки множества значений и удалить цикл",
        ),
        ("BSL036", "Выделите условие оператора Если в отдельный метод или переменную"),
        ("BSL039", "Не рекомендуется использовать вложенный тернарный оператор"),
        ("BSL040", 'Вместо устаревшего свойства "ЭтаФорма" следует использовать "ЭтотОбъект"'),
        ("BSL041", 'Не следует использовать устаревший метод "Сообщить"'),
        ("BSL051", "Исправьте алгоритм, т.к. этот код никогда не будет исполнен"),
        (
            "BSL054",
            "Не рекомендуется использовать экспортные переменные. Это может стать источником трудновоспроизводимых ошибок",
        ),
        ("BSL055", "Удалите лишние последовательные пустые строки"),
        ("BSL060", "Использование двойных отрицаний усложняет понимание кода"),
        ("BSL064", 'Процедура содержит "Возврат" со значением'),
        ("BSL065", "Добавьте описание возвращаемого значения функции"),
        ("BSL066", 'Используйте "СтрНайти" вместо устаревшего "Найти"'),
        ("BSL077", "Нужно изменить запрос, добавив упорядочивание"),
        ("BSL097", 'Используйте "ТекущаяДатаСеанса" вместо устаревшего "ТекущаяДата"'),
        ("BSL148", "Не все пути выполнения функции возвращают значение"),
        (
            "BSL151",
            "Метод 'НачатьТранзакцию' должен быть за пределами блока 'Попытка-Исключение' непосредственно перед оператором 'Попытка'",
        ),
        ("BSL152", "Переместите методы в Служебный Программный интерфейс"),
        ("BSL155", "Необходимо разместить тело модуля после определения методов"),
        ("BSL156", "Переместите код в область"),
        (
            "BSL157",
            "Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке 'Попытка' перед оператором 'Исключение'",
        ),
        ("BSL159", "Общий модуль недопустимого типа"),
        (
            "BSL160",
            'Общий модуль должен иметь хотя бы один экспортный метод, а также область "ПрограммныйИнтерфейс" или "СлужебныйПрограммныйИнтерфейс".',
        ),
        ("BSL161", 'Добавьте постфикс "ПовтИсп" к имени общего модуля'),
        ("BSL162", 'Добавьте постфикс "Клиент" к имени общего модуля'),
        ("BSL163", 'Добавьте постфикс "КлиентСервер" к имени общего модуля'),
        ("BSL164", 'Добавьте постфикс "ПолныеПрава" к имени общего модуля'),
        ("BSL165", 'Добавьте постфикс "Глобальный" к имени общего модуля'),
        ("BSL166", 'Удалите постфикс "Клиент" у глобального модуля'),
        ("BSL167", 'Добавьте постфикс "ВызовСервера" к имени общего модуля'),
        ("BSL168", "Переименуйте общий модуль"),
        ("BSL170", "Удалите директиву компиляции"),
        (
            "BSL171",
            "Воспользуйтесь 'классическим' способом создания многострочных литералов, используя `|` и `+`",
        ),
        ("BSL172", "Добавьте проверку признака ОбменДанными.Загрузка в самом начале процедуры"),
        ("BSL179", 'Замените устаревшее использование типа "УправляемаяФорма"'),
        ("BSL180", "Проверьте отключение безопасного режима"),
        ("BSL182", 'Удалите проверку параметра "АвтоТест"'),
        ("BSL183", "Запрещено выполнение произвольного кода на сервере"),
        (
            "BSL184",
            "Выполнение произвольного кода в общем модуле на сервере является потенциальной уязвимостью ",
        ),
        ("BSL185", "Проверьте запуск внешнего приложения"),
        ("BSL186", "Не используйте запятые для параметров по умолчанию в конце вызова метода."),
        (
            "BSL187",
            "Для полей из соединений добавьте проверки полей через Есть NULL или используйте приведение через ЕстьNULL или используйте внутреннее соединение",
        ),
        ("BSL188", "Проверьте обращение к файловой системе"),
        ("BSL190", "Не рекомендуемое использование метода ДанныеФормыВЗначение"),
        ("BSL191", 'Перепишите запрос без использования "ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ"'),
        ("BSL192", 'Уберите слово "Получить" из имени функции'),
        ("BSL193", "Параметр функции не должен возвращать значение"),
        (
            "BSL194",
            "Проверьте правильность возврата одного и того же примитивного значения в функции",
        ),
        ("BSL195", "Не рекомендуемое использование метода ПолучитьФорму"),
        (
            "BSL197",
            'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся блоки кода',
        ),
        (
            "BSL198",
            'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся условия',
        ),
        (
            "BSL199",
            'Синтаксическая конструкция вида "Если...Тогда...ИначеЕсли..." должна содержать ветвь "Иначе".',
        ),
        ("BSL200", "Проверьте правильность переноса операндов, операторов и параметров"),
        ("BSL201", "Нужно исправить выражение в соответствии со стандартом"),
        ("BSL202", 'Исправьте передачу параметров при вызове метода "СтрШаблон"'),
        ("BSL203", "Проверьте обращение к Интернет-ресурсам"),
        ("BSL204", "Нужно исправить недопустимый символ"),
        ("BSL205", "Для проверки прав доступа в коде следует использовать метод ПравоДоступа"),
        ("BSL206", "Не следует использовать соединения с вложенными запросами"),
        ("BSL207", "Не следует использовать соединения с виртуальными таблицами"),
        ("BSL208", "Нельзя использовать латинские и кириллические символы в одном идентификаторе"),
        ("BSL209", "Обнаружен оператор 'ИЛИ' в условии соединения"),
        ("BSL210", 'Не следует использовать логическое "ИЛИ" в секции "ГДЕ" запроса'),
        ("BSL215", "Необходимо добавить описание всех параметров метода"),
        (
            "BSL217",
            'Нужно добавить удаление данных из временного хранилища после использования, вызвав "УдалитьИзВременногоХранилища"',
        ),
        ("BSL218", "Нужно добавить удаление временного файла после использования"),
        ("BSL219", "Добавьте описание переменной"),
        ("BSL220", "Проверьте корректность многострочного литерала"),
        ("BSL223", "Не используйте конструкторы с параметрами при объявлении структуры"),
        ("BSL225", "Уменьшите количество значений свойств, передаваемых в конструктор структуры"),
        ("BSL226", "Проверить потенциально вредоносное использование метода ПользователиОС"),
        ("BSL227", "Перенесите выражение на новую строку"),
        ("BSL228", "Переместите необязательные параметры после обязательных"),
        ("BSL229", "Поддержка обычного приложения"),
        ("BSL233", "Добавьте описание метода программного интерфейса"),
        ("BSL234", "Обнаружено разыменование ссылочного поля"),
        ("BSL235", "Текст запроса должен быть корректным и открываться конструктором запросов"),
        (
            "BSL237",
            "Избавьтесь от избыточного обращения внутри модуля через его имя или псевдоним ЭтотОбъект",
        ),
        ("BSL238", 'Избавьтесь от получения поля "Ссылка" в запросе.'),
        ("BSL243", "Удалите вставку коллекции в саму себя"),
        ("BSL245", "Запрещено создавать серверные экспортные методы в форме"),
        ("BSL247", "Проверьте установку привилегированного режима"),
        ("BSL248", "Указано несколько директив компиляции"),
        ("BSL250", "Не рекомендуемый вызов функции КаталогВременныхФайлов()"),
        ("BSL251", "Используйте конструкцию Если-Иначе вместо тернарного оператора"),
        ("BSL252", "Свойство ЭтотОбъект доступно только для чтения"),
        ("BSL253", "Не указан таймаут при работе с внешним ресурсом"),
        ("BSL255", "Не следует использовать исключения для приведения значения к типу"),
        (
            "BSL257",
            "Унарный плюс в конкатенации строк потенциально приводит к ошибке времени выполнения",
        ),
        ("BSL258", "Замените конструкцию ОБЪЕДИНИТЬ на ОБЪЕДИНИТЬ ВСЕ"),
        ("BSL260", "Небезопасное использование метода НайтиПоКоду()"),
        ("BSL261", "Используйте явное сравнение с Булево при вызове БезопасныйРежим()"),
        ("BSL262", 'Исправьте передачу неверных параметров в методе "ЗаписьЖурналаРегистрации"'),
        ("BSL263", "Итератор не используется в теле цикла"),
        ("BSL264", "Избавьтесь от использования объекта `СистемнаяИнформация`"),
        ("BSL265", "Бесполезный тернарный оператор"),
        ("BSL266", "Не следует присваивать параметру Отказ значение отличное от Истина"),
        ("BSL267", "Запрещено использование возможности выполнения внешнего кода"),
        ("BSL269", "Измените выражение, чтобы не использовать 'ПОДОБНО'"),
        ("BSL273", "Не следует использовать виртуальные таблицы без параметров"),
        (
            "BSL276",
            "Использовать функцию ПродолжитьВызов() можно только в расширениях и только в методах с аннотацией &Вместо.",
        ),
        (
            "BSL277",
            "Метод ОтменитьТранзакцию() должен быть в попытке и первым методом блока исключения",
        ),
        ("BSL279", 'В текстах модулях не допускается использовать букву "Ё".'),
    ],
)
def test_constant_messages_match_upstream_catalog(code: str, message: str) -> None:
    assert get_rule(code).message_template == message
    assert get_rule(code).message == message
    assert render_rule_message(code) == message


# Frozen from BSLLS v1.0.7 Java DiagnosticMetadata annotations and
# DiagnosticInfo.computeLSPSeverity, including the annotation defaults.
@pytest.mark.parametrize(
    ("level", "codes"),
    [
        (
            Severity.ERROR,
            "BSL001 BSL005 BSL006 BSL009 BSL012 BSL028 BSL032 BSL033 BSL051 BSL052 BSL064 BSL097 BSL151 BSL155 BSL157 BSL158 BSL159 BSL172 BSL173 BSL180 BSL183 BSL187 BSL188 BSL189 BSL194 BSL195 BSL196 BSL201 BSL202 BSL203 BSL204 BSL211 BSL212 BSL213 BSL214 BSL218 BSL220 BSL221 BSL222 BSL230 BSL236 BSL241 BSL242 BSL243 BSL244 BSL245 BSL246 BSL248 BSL249 BSL252 BSL253 BSL257 BSL259 BSL261 BSL263 BSL269 BSL271 BSL273 BSL274 BSL275 BSL276 BSL277 BSL278",
        ),
        (
            Severity.WARNING,
            "BSL002 BSL003 BSL004 BSL007 BSL011 BSL019 BSL020 BSL022 BSL027 BSL039 BSL042 BSL054 BSL060 BSL062 BSL065 BSL077 BSL148 BSL149 BSL150 BSL152 BSL154 BSL161 BSL163 BSL164 BSL165 BSL166 BSL169 BSL170 BSL171 BSL174 BSL181 BSL184 BSL185 BSL186 BSL191 BSL193 BSL198 BSL199 BSL205 BSL206 BSL207 BSL209 BSL210 BSL215 BSL217 BSL226 BSL228 BSL229 BSL231 BSL232 BSL234 BSL235 BSL238 BSL239 BSL240 BSL247 BSL250 BSL254 BSL255 BSL260 BSL264 BSL266 BSL267 BSL268 BSL272",
        ),
        (
            Severity.INFORMATION,
            "BSL008 BSL013 BSL014 BSL015 BSL029 BSL030 BSL031 BSL035 BSL036 BSL040 BSL041 BSL047 BSL066 BSL160 BSL162 BSL167 BSL176 BSL182 BSL197 BSL208 BSL219 BSL223 BSL224 BSL225 BSL227 BSL251 BSL258",
        ),
        (
            Severity.HINT,
            "BSL016 BSL017 BSL023 BSL024 BSL025 BSL026 BSL055 BSL131 BSL153 BSL156 BSL168 BSL175 BSL179 BSL190 BSL192 BSL200 BSL216 BSL233 BSL237 BSL256 BSL262 BSL265 BSL279",
        ),
    ],
)
def test_all_known_upstream_lsp_levels(level: Severity, codes: str) -> None:
    for code in codes.split():
        internal_level = Severity[RULE_METADATA[code]["severity"]]
        assert lsp_compat_severity(code, internal_level) is level


@pytest.mark.parametrize("code", ["BSL177", "BSL178", "BSL999"])
@pytest.mark.parametrize("severity", list(Severity))
def test_unknown_or_removed_upstream_rules_keep_internal_level(
    code: str, severity: Severity
) -> None:
    assert lsp_compat_severity(code, severity) is severity


def test_lsp_level_does_not_change_cli_severity_policy() -> None:
    assert get_rule("BSL008").severity == "WARNING"
    assert get_rule("BSL148").severity == "ERROR"
    assert lsp_compat_severity("BSL008", Severity.WARNING) is Severity.INFORMATION
    assert lsp_compat_severity("BSL148", Severity.ERROR) is Severity.WARNING


def test_unknown_rule_title_does_not_use_generic_translation_fallback() -> None:
    assert get_rule("BSL999").description == "BSL999"


def test_diagnostic_rules_doc_is_generated_from_registry() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "diagnostic-rules.md"
    assert doc_path.read_text(encoding="utf-8") == _load_rules_doc_builder().build_markdown()


def test_all_rule_pages_have_current_generated_headers_and_localized_descriptions() -> None:
    root = Path(__file__).resolve().parents[1]
    builder = _load_rules_doc_builder()
    pages = builder.expected_rule_pages()

    assert len(pages) == 180
    for path, expected in pages.items():
        actual = path.read_text(encoding="utf-8")
        assert actual == expected
        assert "<!-- localized-rule-description:start -->" in actual
        assert "<!-- engineering-contract:start -->" not in actual
        assert "Engineering contract" not in actual
        assert '<div class="doc-lang doc-lang-ru"' in actual
        assert '<div class="doc-lang doc-lang-en"' in actual
        assert f"# {path.stem} -" in actual
        assert path.is_relative_to(root / "docs")


def test_rule_header_explains_suppression_scopes_unambiguously() -> None:
    header = _load_rules_doc_builder().build_rule_header("BSL002")

    assert "Все три семейства подавлений работают для текущей строки и диапазона" in header
    assert "Если открывающий комментарий стоит после кода" in header
    assert "// noqa-enable: BSL002" in header
    assert "// bsl-enable: BSL002" in header
    assert "// BSLLS:MethodSize-on" in header
    assert "должны принадлежать одному семейству" in header
    assert "support both a current line and a range" in header
    assert "When an opening comment follows code" in header
    assert "must belong to the same family" in header


@pytest.mark.parametrize(
    ("code", "args", "message"),
    [
        (
            "BSL002",
            ("Тест", 201, 200),
            'Длина метода "Тест" равна 201, что больше установленного лимита в 200 строк',
        ),
        (
            "BSL003",
            ("Тест", "ПрограммныйИнтерфейс"),
            'Переместите неэкспортный метод "Тест" из области "ПрограммныйИнтерфейс"',
        ),
        (
            "BSL008",
            ("Тест", 4, 3),
            'Сократите количество возвратов в методе "Тест" с "4" до максимально допустимого "3"',
        ),
        ("BSL011", ("body", 16, 15), 'Уменьшите когнитивную сложность "body" с 16 до 15'),
        ("BSL015", (4, 3), "Уменьшите количество необязательных параметров c 4 до допустимого 3"),
        ("BSL019", ("Тест", 21, 20), 'Уменьшите цикломатическую сложность "Тест" с 21 до 20'),
        ("BSL031", (8, 7), "Уменьшите количество параметров c 8 до допустимого 7"),
        ("BSL042", ("Тест",), 'Метод "Тест" не вызывается в теле модуля'),
        ("BSL062", ("Параметр",), 'Уберите неиспользуемый параметр "Параметр"'),
    ],
)
def test_procedure_messages_render_upstream_values(
    code: str, args: tuple[object, ...], message: str
) -> None:
    assert render_rule_message(code, *args) == message


def test_module_body_complexity_preserves_computed_value(tmp_path: Path) -> None:
    from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
    from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot

    text = "Если А Тогда\n    Если Б Тогда\n        А = 1;\n    КонецЕсли;\nКонецЕсли;\n"
    path = tmp_path / "Module.bsl"
    path.write_text(text, encoding="utf-8")
    snapshot = build_document_snapshot(str(path), content=text)
    facts = snapshot.module_body_cognitive_complexity_facts(2)
    assert len(facts) == 1
    assert facts[0].complexity == 3
    diagnostics = DiagnosticEngine(select={"BSL011"}, max_cognitive_complexity=2).check_file(
        str(path)
    )
    assert [diag.message for diag in diagnostics] == [
        'Уменьшите когнитивную сложность "body" с 3 до 2'
    ]


@pytest.mark.parametrize(
    ("code", "args", "ru", "en"),
    [
        (
            "BSL014",
            (121, 120),
            "Длина строки 121 превышает максимально допустимую 120",
            "String length 121 exceeded maximum 120",
        ),
        (
            "BSL022",
            ("Предупреждение", "ПоказатьПредупреждение"),
            "Вместо модального метода `Предупреждение` необходимо использовать `ПоказатьПредупреждение`",
            "Instead of the modal method `Предупреждение`, use `ПоказатьПредупреждение`",
        ),
        ("BSL023", ("// TODO",), 'Найден служебный тег "// TODO"', 'Found service tag "// TODO"'),
        (
            "BSL026",
            ("API",),
            'Область "API" не содержит функций или процедур',
            'The region "API" does not contain functions.',
        ),
        (
            "BSL029",
            ("42",),
            'Создайте константу с понятным названием, присвойте ей значение "42" и используйте эту константу вместо магического числа.',
            'Assign this magic number "42" to a well-named constant, and use the constant instead.',
        ),
        (
            "BSL035",
            ('"test"',),
            'Необходимо избавиться от многократного использования строкового литерала "test"',
            'Need to get rid of reuse of string literal "test"',
        ),
        (
            "BSL047",
            ('"20000101"',),
            'Создайте переменную с понятным названием, присвойте ей значение ""20000101"" и используйте эту константу вместо магической даты.',
            'Assign this magic number ""20000101"" to a well-named constant, and use the constant instead.',
        ),
        (
            "BSL131",
            ("API",),
            'Нужно удалить дубли раздела "API"',
            'Delete duplicates of region "API"',
        ),
        (
            "BSL149",
            ("Table.Ref",),
            'Полю "Table.Ref" не назначен псевдоним или пропущено ключевое слово КАК',
            'The field "Table.Ref" has no alias assigned or the AS keyword is missing',
        ),
        (
            "BSL153",
            ("iF",),
            'Ключевое слово "iF" написано не канонически',
            'Keyword "iF" is not written canonically',
        ),
        (
            "BSL173",
            ("Items",),
            'Не следует удалять элементы коллекции "Items" при ее обходе оператором "Для каждого ... Из ... Цикл"',
            'Don\'t delete elements of collection "Items" when iterating through collection using the operator "For each ... In ... Do"',
        ),
        (
            "BSL176",
            ("Old", " Следует использовать: New"),
            'Удалите обращение к устаревшему "Old". Следует использовать: New',
            'Remove access to deprecated "Old". Use instead: New',
        ),
        (
            "BSL181",
            ('"Key"', "Items"),
            'Проверьте повторную вставку "Key" в коллекцию Items',
            'Check the re-addition of "Key" to the collection with name Items ',
        ),
        (
            "BSL212",
            ("'Arg'",),
            "Укажите обязательный параметр 'Arg'",
            "Specify a required parameter 'Arg'",
        ),
        (
            "BSL216",
            ("Слева и справа", "="),
            "Слева и справа от '=' не хватает пробела",
            "Left and right of the '=' missing space",
        ),
        (
            "BSL221",
            ("[ru, en]",),
            "Добавьте строки для языков: [ru, en]",
            "Add lines for languages: [ru, en]",
        ),
        ("BSL222", ("[ru]",), "Добавьте строки для языков: [ru]", "Add lines for languages: [ru]"),
        (
            "BSL224",
            ("конструктора", "Structure"),
            'Уберите инициализацию параметров конструктора "Structure" вложенными методами',
            'Remove parameter initialization for constructor "Structure" by nested methods',
        ),
        (
            "BSL249",
            ("Color",),
            "Замените конструктор Color на получение элемента стиля",
            "Replace constructor Color to get style element",
        ),
        (
            "BSL254",
            ("Arg", "Server"),
            'Установите модификатор "Знач" для параметра Arg метода Server',
            'Set the modifier "ByValue" for the "Arg" parameter of the "Server" method',
        ),
        (
            "BSL256",
            ("Misspelled",),
            'Возможная опечатка в "Misspelled"',
            'Possible typo in word "Misspelled"',
        ),
        (
            "BSL259",
            ("Unknown",),
            'Неизвестный символ препроцессора "Unknown"',
            'Unknown preprocessor symbol "Unknown"',
        ),
        (
            "BSL268",
            ("FindByCode",),
            'Не следует использовать  метод "FindByCode" и поиск по строке',
            'Don\'t use method "FindByCode" and finding by string.',
        ),
    ],
)
def test_remaining_occurrence_templates_in_both_locales(
    code: str, args: tuple[object, ...], ru: str, en: str
) -> None:
    assert render_rule_message(code, *args) == ru
    assert render_rule_message(code, *args, locale="en") == en


@pytest.mark.parametrize(
    ("code", "variant", "args", "ru", "en"),
    [
        (
            "BSL065",
            "isProcedure",
            (),
            "Удалите описание возвращаемого значения для процедуры",
            "Remove returned values description for procedure",
        ),
        (
            "BSL175",
            "deprecatedAttributeMessage",
            ("Old", "New"),
            'Атрибут "Old" устарел. Вместо него стоит использовать New',
            '"Old" attribute is deprecated. You should use New',
        ),
        (
            "BSL175",
            "deprecatedMethodsMessage",
            ("Old", "New"),
            'Метод "Old" устарел. Вместо него стоит использовать "New"',
            '"Old" method is deprecated. You should use "New"',
        ),
        (
            "BSL175",
            "deprecatedEnumNameMessage",
            ("Old", "New"),
            'Используется старое наименование "Old". Вместо него необходимо использовать "New"',
            'Deprecated enum name "Old". You should use "New" instead.',
        ),
        (
            "BSL204",
            "diagnosticMessageDash",
            (),
            'Нужно исправить на правильный символ "-"',
            'Correct character to "-"',
        ),
        (
            "BSL204",
            "diagnosticMessageSpace",
            (),
            "Нужно заменить символ неразрывного пробела на обычный пробел",
            "Replace non-breaking space character with space character",
        ),
        (
            "BSL215",
            "missingDescription",
            ("Arg",),
            'Необходимо добавить описание параметра "Arg"',
            'Add description for the "Arg" parameter',
        ),
        (
            "BSL215",
            "emptyDescription",
            ("Arg",),
            'Необходимо добавить описание типа параметра "Arg"',
            'Add type description for the "Arg" parameter',
        ),
        (
            "BSL215",
            "missingInSignature",
            ("Arg",),
            'Необходимо удалить описания параметров "Arg", отсутствующих в сигнатуре метода',
            'Remove description for the "Arg", they are missing in the signature',
        ),
        (
            "BSL215",
            "wrongOrder",
            (),
            "Необходимо исправить порядок описаний параметров",
            "Correct the order for parameter descriptions",
        ),
        (
            "BSL224",
            "diagnosticMessageWithoutName",
            ("конструктора",),
            "Уберите инициализацию параметров конструктора вложенными методами",
            "Remove parameter initialization for constructor by nested methods",
        ),
        (
            "BSL262",
            "wrongNumberMessage",
            (),
            "Неверное число параметров метода",
            "Incorrect number of method parameters",
        ),
        (
            "BSL262",
            "noSecondParameter",
            (),
            'Не указан 2й параметр с типом "УровеньЖурналаРегистрации"',
            'The 2nd parameter with the type "EventLogLevel" is missing',
        ),
        (
            "BSL262",
            "noDetailErrorDescription",
            (),
            'В тексте комментария нет вызова "ПодробноеПредставлениеОшибки(ИнформацияОбОшибке())"',
            'There is no call to "DetailErrorDescription(ErrorInfo())" in the comment text',
        ),
    ],
)
def test_occurrence_message_variants_in_both_locales(
    code: str, variant: str, args: tuple[object, ...], ru: str, en: str
) -> None:
    assert render_rule_message(code, *args, variant=variant) == ru
    assert render_rule_message(code, *args, variant=variant, locale="en") == en
    diag = Diagnostic(
        file="m.bsl",
        line=2,
        character=3,
        end_line=2,
        end_character=8,
        severity=Severity.WARNING,
        code=code,
        message_args=args,
        message_variant=variant,
    )
    assert diag.to_dict()["message"] == ru
