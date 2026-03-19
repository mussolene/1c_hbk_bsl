"""
1C Enterprise Platform API registry.

Provides symbol information for the built-in 1C platform objects and global
functions, enabling LSP hover/completion and MCP search.

Data is embedded in this module as a compact dict; additional definitions
can be loaded from JSON files in ``data/platform_api/``.

JSON file format (one object per file)::

    {
        "name": "Запрос",
        "name_en": "Query",
        "kind": "class",
        "description": "Объект для выполнения запросов к базе данных",
        "methods": [
            {
                "name": "Выполнить",
                "name_en": "Execute",
                "signature": "Выполнить() → РезультатЗапроса",
                "description": "Выполняет запрос и возвращает результат"
            }
        ],
        "properties": [
            {
                "name": "Текст",
                "name_en": "Text",
                "description": "Текст запроса"
            }
        ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ApiMethod:
    name: str
    name_en: str = ""
    signature: str = ""
    description: str = ""
    returns: str = ""


@dataclass
class ApiProperty:
    name: str
    name_en: str = ""
    description: str = ""
    read_only: bool = False


@dataclass
class ApiType:
    name: str
    name_en: str = ""
    kind: str = "class"  # class | enum | global
    description: str = ""
    methods: list[ApiMethod] = field(default_factory=list)
    properties: list[ApiProperty] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in data (minimal but functional bootstrap)
# ---------------------------------------------------------------------------

_BUILTIN_GLOBALS: list[dict] = [
    # Output / messaging
    {"name": "Сообщить", "name_en": "Message",
     "signature": "Сообщить(ТекстСообщения, Статус?)",
     "description": "Выводит сообщение пользователю"},
    {"name": "Предупреждение", "name_en": "DoMessageBox",
     "signature": "Предупреждение(ТекстПредупреждения, Таймаут?)",
     "description": "Отображает диалог-предупреждение"},
    {"name": "Вопрос", "name_en": "Question",
     "signature": "Вопрос(ТекстВопроса, КнопкиДиалога, Таймаут?) → КодВозвратаДиалога",
     "description": "Задаёт вопрос пользователю"},
    # Error handling
    {"name": "ОписаниеОшибки", "name_en": "ErrorDescription",
     "signature": "ОписаниеОшибки() → Строка",
     "description": "Возвращает описание последней ошибки"},
    {"name": "ИнформацияОбОшибке", "name_en": "ErrorInfo",
     "signature": "ИнформацияОбОшибке() → ИнформацияОбОшибке",
     "description": "Возвращает объект с детальной информацией об ошибке"},
    {"name": "НовоеИсключение", "name_en": "CreateException",
     "signature": "НовоеИсключение(Описание, Причина?) → Исключение",
     "description": "Создаёт объект исключения для ВызватьИсключение"},
    # Type checking
    {"name": "ТипЗнч", "name_en": "TypeOf",
     "signature": "ТипЗнч(Значение) → Тип",
     "description": "Возвращает тип переданного значения"},
    {"name": "Тип", "name_en": "Type",
     "signature": "Тип(ИмяТипа) → Тип",
     "description": "Возвращает объект типа по имени"},
    {"name": "ЗначениеЗаполнено", "name_en": "ValueIsFilled",
     "signature": "ЗначениеЗаполнено(Значение) → Булево",
     "description": "Проверяет, заполнено ли значение (не пустое)"},
    # String functions
    {"name": "СтрДлина", "name_en": "StrLen",
     "signature": "СтрДлина(Строка) → Число",
     "description": "Возвращает длину строки"},
    {"name": "Лев", "name_en": "Left",
     "signature": "Лев(Строка, ЧислоСимволов) → Строка",
     "description": "Возвращает левую часть строки"},
    {"name": "Прав", "name_en": "Right",
     "signature": "Прав(Строка, ЧислоСимволов) → Строка",
     "description": "Возвращает правую часть строки"},
    {"name": "Сред", "name_en": "Mid",
     "signature": "Сред(Строка, НачальнаяПозиция, ЧислоСимволов?) → Строка",
     "description": "Возвращает подстроку"},
    {"name": "СтрНайти", "name_en": "StrFind",
     "signature": "СтрНайти(Строка, ПодстрокаПоиска, НаправлениеПоиска?, НачальнаяПозиция?) → Число",
     "description": "Ищет подстроку в строке"},
    {"name": "СтрЗаменить", "name_en": "StrReplace",
     "signature": "СтрЗаменить(Строка, ПодстрокаПоиска, ПодстрокаЗамены) → Строка",
     "description": "Заменяет подстроку в строке"},
    {"name": "НРег", "name_en": "Lower",
     "signature": "НРег(Строка) → Строка",
     "description": "Переводит строку в нижний регистр"},
    {"name": "ВРег", "name_en": "Upper",
     "signature": "ВРег(Строка) → Строка",
     "description": "Переводит строку в верхний регистр"},
    {"name": "СокрЛ", "name_en": "TrimL",
     "signature": "СокрЛ(Строка) → Строка",
     "description": "Удаляет пробелы слева"},
    {"name": "СокрП", "name_en": "TrimR",
     "signature": "СокрП(Строка) → Строка",
     "description": "Удаляет пробелы справа"},
    {"name": "СокрЛП", "name_en": "TrimAll",
     "signature": "СокрЛП(Строка) → Строка",
     "description": "Удаляет пробелы с обеих сторон"},
    {"name": "ПустаяСтрока", "name_en": "IsBlankString",
     "signature": "ПустаяСтрока(Строка) → Булево",
     "description": "Проверяет, является ли строка пустой или состоит только из пробелов"},
    # Type conversion
    {"name": "Строка", "name_en": "String",
     "signature": "Строка(Значение) → Строка",
     "description": "Преобразует значение в строку"},
    {"name": "Число", "name_en": "Number",
     "signature": "Число(Значение) → Число",
     "description": "Преобразует значение в число"},
    {"name": "Булево", "name_en": "Boolean",
     "signature": "Булево(Значение) → Булево",
     "description": "Преобразует значение в булево"},
    {"name": "Дата", "name_en": "Date",
     "signature": "Дата(Год, Месяц, День, Час?, Минута?, Секунда?) → Дата",
     "description": "Создаёт значение типа Дата"},
    # Math
    {"name": "Окр", "name_en": "Round",
     "signature": "Окр(Число, Разрядность?, РежимОкругления?) → Число",
     "description": "Округляет число"},
    {"name": "Цел", "name_en": "Int",
     "signature": "Цел(Число) → Число",
     "description": "Возвращает целую часть числа"},
    {"name": "Abs", "name_en": "Abs",
     "signature": "Abs(Число) → Число",
     "description": "Возвращает абсолютное значение числа"},
    {"name": "Макс", "name_en": "Max",
     "signature": "Макс(Значение1, Значение2, ...) → Значение",
     "description": "Возвращает максимальное из переданных значений"},
    {"name": "Мин", "name_en": "Min",
     "signature": "Мин(Значение1, Значение2, ...) → Значение",
     "description": "Возвращает минимальное из переданных значений"},
    # Date
    {"name": "ТекущаяДата", "name_en": "CurrentDate",
     "signature": "ТекущаяДата() → Дата",
     "description": "Возвращает текущую дату и время"},
    {"name": "НачалоДня", "name_en": "BegOfDay",
     "signature": "НачалоДня(Дата) → Дата",
     "description": "Возвращает начало дня (00:00:00)"},
    {"name": "КонецДня", "name_en": "EndOfDay",
     "signature": "КонецДня(Дата) → Дата",
     "description": "Возвращает конец дня (23:59:59)"},
    {"name": "НачалоМесяца", "name_en": "BegOfMonth",
     "signature": "НачалоМесяца(Дата) → Дата",
     "description": "Возвращает первый день месяца"},
    {"name": "КонецМесяца", "name_en": "EndOfMonth",
     "signature": "КонецМесяца(Дата) → Дата",
     "description": "Возвращает последний день месяца"},
    {"name": "ДобавитьМесяц", "name_en": "AddMonth",
     "signature": "ДобавитьМесяц(Дата, ЧислоМесяцев) → Дата",
     "description": "Добавляет указанное количество месяцев к дате"},
    {"name": "Год", "name_en": "Year",
     "signature": "Год(Дата) → Число",
     "description": "Возвращает год из даты"},
    {"name": "Месяц", "name_en": "Month",
     "signature": "Месяц(Дата) → Число",
     "description": "Возвращает месяц из даты"},
    {"name": "День", "name_en": "Day",
     "signature": "День(Дата) → Число",
     "description": "Возвращает день из даты"},
    # Collections
    {"name": "Новый", "name_en": "New",
     "signature": "Новый <ИмяТипа>(...)",
     "description": "Создаёт новый объект платформы"},
    # More string functions
    {"name": "СтрРазделить", "name_en": "StrSplit",
     "signature": "СтрРазделить(Строка, Разделители?, ВключатьПустые?) → Массив",
     "description": "Разбивает строку на части по разделителям"},
    {"name": "СтрСоединить", "name_en": "StrConcat",
     "signature": "СтрСоединить(МассивСтрок, Разделитель?) → Строка",
     "description": "Соединяет строки массива в одну строку"},
    {"name": "СтрСодержит", "name_en": "StrContains",
     "signature": "СтрСодержит(Строка, ПодстрокаПоиска) → Булево",
     "description": "Проверяет вхождение подстроки"},
    {"name": "СтрНачинаетсяС", "name_en": "StrStartsWith",
     "signature": "СтрНачинаетсяС(Строка, Начало) → Булево",
     "description": "Проверяет, начинается ли строка с заданной подстроки"},
    {"name": "СтрЗаканчиваетсяНа", "name_en": "StrEndsWith",
     "signature": "СтрЗаканчиваетсяНа(Строка, Конец) → Булево",
     "description": "Проверяет, заканчивается ли строка заданной подстрокой"},
    {"name": "СтрКоличествоСтрок", "name_en": "StrLineCount",
     "signature": "СтрКоличествоСтрок(Строка) → Число",
     "description": "Возвращает количество строк в многострочной строке"},
    {"name": "СтрПолучитьСтроку", "name_en": "StrGetLine",
     "signature": "СтрПолучитьСтроку(Строка, НомерСтроки) → Строка",
     "description": "Возвращает строку по номеру из многострочной строки"},
    {"name": "Символ", "name_en": "Char",
     "signature": "Символ(КодСимвола) → Строка",
     "description": "Возвращает символ по коду Unicode"},
    {"name": "КодСимвола", "name_en": "CharCode",
     "signature": "КодСимвола(Строка, НомерСимвола?) → Число",
     "description": "Возвращает код Unicode символа"},
    {"name": "Формат", "name_en": "Format",
     "signature": "Формат(Значение, ФорматнаяСтрока) → Строка",
     "description": "Форматирует значение по форматной строке"},
    {"name": "СтрШаблон", "name_en": "StrTemplate",
     "signature": "СтрШаблон(Шаблон, ЗначениеПодстановки1, ...) → Строка",
     "description": "Заполняет шаблон строки подстановочными значениями"},
    # More date functions
    {"name": "НачалоГода", "name_en": "BegOfYear",
     "signature": "НачалоГода(Дата) → Дата",
     "description": "Возвращает начало года"},
    {"name": "КонецГода", "name_en": "EndOfYear",
     "signature": "КонецГода(Дата) → Дата",
     "description": "Возвращает конец года"},
    {"name": "НачалоКвартала", "name_en": "BegOfQuarter",
     "signature": "НачалоКвартала(Дата) → Дата",
     "description": "Возвращает начало квартала"},
    {"name": "КонецКвартала", "name_en": "EndOfQuarter",
     "signature": "КонецКвартала(Дата) → Дата",
     "description": "Возвращает конец квартала"},
    {"name": "НачалоНедели", "name_en": "BegOfWeek",
     "signature": "НачалоНедели(Дата) → Дата",
     "description": "Возвращает начало недели"},
    {"name": "КонецНедели", "name_en": "EndOfWeek",
     "signature": "КонецНедели(Дата) → Дата",
     "description": "Возвращает конец недели"},
    {"name": "ДеньНедели", "name_en": "WeekDay",
     "signature": "ДеньНедели(Дата) → Число",
     "description": "Возвращает день недели (1=Понедельник, 7=Воскресенье)"},
    {"name": "НеделяГода", "name_en": "WeekOfYear",
     "signature": "НеделяГода(Дата) → Число",
     "description": "Возвращает номер недели в году"},
    {"name": "Час", "name_en": "Hour",
     "signature": "Час(Дата) → Число",
     "description": "Возвращает час из значения даты"},
    {"name": "Минута", "name_en": "Minute",
     "signature": "Минута(Дата) → Число",
     "description": "Возвращает минуты из значения даты"},
    {"name": "Секунда", "name_en": "Second",
     "signature": "Секунда(Дата) → Число",
     "description": "Возвращает секунды из значения даты"},
    # JSON
    {"name": "ЗаписатьJSON", "name_en": "WriteJSON",
     "signature": "ЗаписатьJSON(ЗаписьJSON, Значение, ПараметрыПреобразования?)",
     "description": "Сериализует значение в JSON"},
    {"name": "ПрочитатьJSON", "name_en": "ReadJSON",
     "signature": "ПрочитатьJSON(ЧтениеJSON, ИменаСвойствСоответствие?, ПространстваИмен?) → Произвольный",
     "description": "Десериализует JSON в значение 1С"},
    # System/environment
    {"name": "ЗначениеВСтрокуВнутр", "name_en": "ValueToStringInternal",
     "signature": "ЗначениеВСтрокуВнутр(Значение) → Строка",
     "description": "Сериализует значение во внутренний формат строки"},
    {"name": "ЗначениеИзСтрокиВнутр", "name_en": "ValueFromStringInternal",
     "signature": "ЗначениеИзСтрокиВнутр(Строка) → Произвольный",
     "description": "Десериализует значение из внутреннего формата"},
    {"name": "ОбщийМодуль", "name_en": "CommonModule",
     "signature": "ОбщийМодуль(Имя) → ОбщийМодуль",
     "description": "Возвращает ссылку на общий модуль по имени"},
    {"name": "ПолучитьСеансовыеДанные", "name_en": "GetSessionData",
     "signature": "ПолучитьСеансовыеДанные() → СохраняемыеДанныеФормы",
     "description": "Возвращает сеансовые данные"},
    {"name": "УстановитьСеансовыеДанные", "name_en": "SetSessionData",
     "signature": "УстановитьСеансовыеДанные(СеансовыеДанные)",
     "description": "Устанавливает сеансовые данные"},
    {"name": "ТранзакцияАктивна", "name_en": "TransactionActive",
     "signature": "ТранзакцияАктивна() → Булево",
     "description": "Возвращает Истина, если активна транзакция"},
    {"name": "НачатьТранзакцию", "name_en": "BeginTransaction",
     "signature": "НачатьТранзакцию()",
     "description": "Начинает транзакцию базы данных"},
    {"name": "ЗафиксироватьТранзакцию", "name_en": "CommitTransaction",
     "signature": "ЗафиксироватьТранзакцию()",
     "description": "Фиксирует транзакцию базы данных"},
    {"name": "ОтменитьТранзакцию", "name_en": "RollbackTransaction",
     "signature": "ОтменитьТранзакцию()",
     "description": "Отменяет транзакцию базы данных"},
    {"name": "ЗаблокироватьДанныеДляРедактирования", "name_en": "LockDataForEdit",
     "signature": "ЗаблокироватьДанныеДляРедактирования(Ссылка, Версия?)",
     "description": "Устанавливает управляемую блокировку"},
    {"name": "РазблокироватьДанныеДляРедактирования", "name_en": "UnlockDataForEdit",
     "signature": "РазблокироватьДанныеДляРедактирования(Ссылка)",
     "description": "Снимает управляемую блокировку"},
]

_BUILTIN_TYPES: list[dict] = [
    {
        "name": "Запрос", "name_en": "Query", "kind": "class",
        "description": "Объект для построения и выполнения запросов к информационной базе",
        "methods": [
            {"name": "Выполнить", "name_en": "Execute",
             "signature": "Выполнить() → РезультатЗапроса",
             "description": "Выполняет запрос"},
            {"name": "УстановитьПараметр", "name_en": "SetParameter",
             "signature": "УстановитьПараметр(ИмяПараметра, Значение)",
             "description": "Устанавливает значение параметра запроса"},
            {"name": "ВыполнитьПакет", "name_en": "ExecuteBatch",
             "signature": "ВыполнитьПакет() → Массив",
             "description": "Выполняет пакет запросов"},
        ],
        "properties": [
            {"name": "Текст", "name_en": "Text", "description": "Текст запроса на языке запросов 1С"},
        ],
    },
    {
        "name": "HTTPСоединение", "name_en": "HTTPConnection", "kind": "class",
        "description": "HTTP-соединение с удалённым сервером",
        "methods": [
            {"name": "Получить", "name_en": "Get",
             "signature": "Получить(Запрос, ПутьКФайлу?) → HTTPОтвет",
             "description": "Выполняет HTTP GET запрос"},
            {"name": "Отправить", "name_en": "Post",
             "signature": "Отправить(Запрос, ПутьКФайлу?) → HTTPОтвет",
             "description": "Выполняет HTTP POST запрос"},
            {"name": "ЗаписатьJSON", "name_en": "Put",
             "signature": "Записать(Запрос, ПутьКФайлу?) → HTTPОтвет",
             "description": "Выполняет HTTP PUT запрос"},
        ],
        "properties": [],
    },
    {
        "name": "ТаблицаЗначений", "name_en": "ValueTable", "kind": "class",
        "description": "Динамическая таблица произвольных значений",
        "methods": [
            {"name": "Добавить", "name_en": "Add",
             "signature": "Добавить() → СтрокаТаблицыЗначений",
             "description": "Добавляет новую строку в конец таблицы"},
            {"name": "Количество", "name_en": "Count",
             "signature": "Количество() → Число",
             "description": "Возвращает количество строк"},
            {"name": "Найти", "name_en": "Find",
             "signature": "Найти(Значение, КолонкиПоиска?) → СтрокаТаблицыЗначений",
             "description": "Ищет строку по значению"},
            {"name": "Очистить", "name_en": "Clear",
             "signature": "Очистить()",
             "description": "Удаляет все строки"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить(СтрокаИлиИндекс)",
             "description": "Удаляет строку"},
            {"name": "Скопировать", "name_en": "Copy",
             "signature": "Скопировать(Строки?, Колонки?) → ТаблицаЗначений",
             "description": "Копирует таблицу"},
            {"name": "Итог", "name_en": "Total",
             "signature": "Итог(КолонкаИлиИмя) → Число",
             "description": "Возвращает итог по колонке"},
        ],
        "properties": [
            {"name": "Колонки", "name_en": "Columns",
             "description": "Коллекция колонок таблицы"},
        ],
    },
    {
        "name": "Массив", "name_en": "Array", "kind": "class",
        "description": "Упорядоченная коллекция значений произвольного типа",
        "methods": [
            {"name": "Добавить", "name_en": "Add",
             "signature": "Добавить(Значение)",
             "description": "Добавляет значение в конец массива"},
            {"name": "Количество", "name_en": "Count",
             "signature": "Количество() → Число",
             "description": "Возвращает количество элементов"},
            {"name": "Найти", "name_en": "Find",
             "signature": "Найти(Значение) → Число",
             "description": "Возвращает индекс значения или -1"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить(Индекс)",
             "description": "Удаляет элемент по индексу"},
            {"name": "Вставить", "name_en": "Insert",
             "signature": "Вставить(Индекс, Значение)",
             "description": "Вставляет значение по индексу"},
            {"name": "Очистить", "name_en": "Clear",
             "signature": "Очистить()",
             "description": "Удаляет все элементы"},
        ],
        "properties": [],
    },
    {
        "name": "Структура", "name_en": "Structure", "kind": "class",
        "description": "Коллекция пар ключ-значение с именованными полями",
        "methods": [
            {"name": "Вставить", "name_en": "Insert",
             "signature": "Вставить(Ключ, Значение?)",
             "description": "Добавляет или заменяет значение по ключу"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить(Ключ)",
             "description": "Удаляет элемент по ключу"},
            {"name": "Получить", "name_en": "Get",
             "signature": "Получить(Ключ) → Значение",
             "description": "Возвращает значение по ключу (или Неопределено)"},
            {"name": "Свойство", "name_en": "Property",
             "signature": "Свойство(ИмяСвойства, Значение?) → Булево",
             "description": "Проверяет наличие свойства и получает значение"},
            {"name": "Количество", "name_en": "Count",
             "signature": "Количество() → Число",
             "description": "Возвращает количество элементов"},
        ],
        "properties": [],
    },
    {
        "name": "Соответствие", "name_en": "Map", "kind": "class",
        "description": "Коллекция пар ключ-значение произвольного типа",
        "methods": [
            {"name": "Вставить", "name_en": "Insert",
             "signature": "Вставить(Ключ, Значение)",
             "description": "Добавляет или обновляет пару ключ-значение"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить(Ключ)",
             "description": "Удаляет пару по ключу"},
            {"name": "Получить", "name_en": "Get",
             "signature": "Получить(Ключ) → Значение",
             "description": "Возвращает значение по ключу"},
            {"name": "Количество", "name_en": "Count",
             "signature": "Количество() → Число",
             "description": "Возвращает количество пар"},
        ],
        "properties": [],
    },
    {
        "name": "РезультатЗапроса", "name_en": "QueryResult", "kind": "class",
        "description": "Результат выполнения запроса",
        "methods": [
            {"name": "Выбрать", "name_en": "Choose",
             "signature": "Выбрать(ТипОбхода?) → ВыборкаИзРезультатаЗапроса",
             "description": "Создаёт выборку для обхода результата"},
            {"name": "Выгрузить", "name_en": "Unload",
             "signature": "Выгрузить() → ТаблицаЗначений",
             "description": "Выгружает результат в таблицу значений"},
            {"name": "Пустой", "name_en": "IsEmpty",
             "signature": "Пустой() → Булево",
             "description": "Проверяет, пуст ли результат"},
        ],
        "properties": [],
    },
    {
        "name": "ЗаписьЖурналаРегистрации", "name_en": "EventLogEntryTransactionStatus",
        "kind": "enum",
        "description": "Статус транзакции в журнале регистрации",
        "methods": [],
        "properties": [
            {"name": "НеВТранзакции", "name_en": "NotInTransaction", "description": ""},
            {"name": "ВТранзакции", "name_en": "InTransaction", "description": ""},
            {"name": "ОтменаТранзакции", "name_en": "TransactionCancelled", "description": ""},
            {"name": "ФиксацияТранзакции", "name_en": "TransactionCommitted", "description": ""},
        ],
    },
    {
        "name": "Файл", "name_en": "File", "kind": "class",
        "description": "Объект для работы с файлами и каталогами файловой системы",
        "methods": [
            {"name": "Существует", "name_en": "Exists",
             "signature": "Существует() → Булево",
             "description": "Проверяет существование файла или каталога"},
            {"name": "ЭтоКаталог", "name_en": "IsDirectory",
             "signature": "ЭтоКаталог() → Булево",
             "description": "Проверяет, является ли объект каталогом"},
            {"name": "ЭтоФайл", "name_en": "IsFile",
             "signature": "ЭтоФайл() → Булево",
             "description": "Проверяет, является ли объект файлом"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить()",
             "description": "Удаляет файл или пустой каталог"},
            {"name": "Переименовать", "name_en": "Rename",
             "signature": "Переименовать(НовоеПолноеИмя)",
             "description": "Переименовывает файл или каталог"},
        ],
        "properties": [
            {"name": "Имя", "name_en": "Name", "description": "Имя файла без пути"},
            {"name": "ПолноеИмя", "name_en": "FullName", "description": "Полный путь к файлу"},
            {"name": "Путь", "name_en": "Path", "description": "Путь к каталогу без имени файла"},
            {"name": "Расширение", "name_en": "Extension", "description": "Расширение файла"},
            {"name": "Размер", "name_en": "Size", "description": "Размер файла в байтах"},
        ],
    },
    {
        "name": "HTTPЗапрос", "name_en": "HTTPRequest", "kind": "class",
        "description": "HTTP-запрос для отправки через HTTPСоединение",
        "methods": [
            {"name": "УстановитьЗаголовок", "name_en": "SetHeader",
             "signature": "УстановитьЗаголовок(ИмяЗаголовка, ЗначениеЗаголовка)",
             "description": "Устанавливает HTTP-заголовок запроса"},
            {"name": "УстановитьТелоИзСтроки", "name_en": "SetBodyFromString",
             "signature": "УстановитьТелоИзСтроки(Строка, Кодировка?, ИспользованиеByteOrderMark?)",
             "description": "Устанавливает тело запроса из строки"},
            {"name": "УстановитьТелоИзДвоичныхДанных", "name_en": "SetBodyFromBinaryData",
             "signature": "УстановитьТелоИзДвоичныхДанных(ДвоичныеДанные)",
             "description": "Устанавливает тело запроса из двоичных данных"},
        ],
        "properties": [
            {"name": "АдресРесурса", "name_en": "ResourceAddress", "description": "URI ресурса"},
            {"name": "Заголовки", "name_en": "Headers", "description": "HTTP-заголовки запроса"},
        ],
    },
    {
        "name": "HTTPОтвет", "name_en": "HTTPResponse", "kind": "class",
        "description": "HTTP-ответ, полученный от сервера",
        "methods": [
            {"name": "ПолучитьТелоКакСтроку", "name_en": "GetBodyAsString",
             "signature": "ПолучитьТелоКакСтроку(Кодировка?) → Строка",
             "description": "Возвращает тело ответа как строку"},
            {"name": "ПолучитьТелоКакДвоичныеДанные", "name_en": "GetBodyAsBinaryData",
             "signature": "ПолучитьТелоКакДвоичныеДанные() → ДвоичныеДанные",
             "description": "Возвращает тело ответа как двоичные данные"},
        ],
        "properties": [
            {"name": "КодСостояния", "name_en": "StatusCode", "description": "HTTP-статус ответа"},
            {"name": "Заголовки", "name_en": "Headers", "description": "HTTP-заголовки ответа"},
        ],
    },
    {
        "name": "ЧтениеJSON", "name_en": "JSONReader", "kind": "class",
        "description": "Потоковое чтение JSON",
        "methods": [
            {"name": "ОткрытьФайл", "name_en": "OpenFile",
             "signature": "ОткрытьФайл(ПутьКФайлу, Кодировка?)",
             "description": "Открывает файл JSON для чтения"},
            {"name": "УстановитьСтроку", "name_en": "SetString",
             "signature": "УстановитьСтроку(Строка)",
             "description": "Устанавливает строку JSON для чтения"},
            {"name": "Прочитать", "name_en": "Read",
             "signature": "Прочитать() → Булево",
             "description": "Читает следующий токен JSON"},
            {"name": "Закрыть", "name_en": "Close",
             "signature": "Закрыть()",
             "description": "Закрывает ридер"},
        ],
        "properties": [
            {"name": "ТипТекущегоЗначения", "name_en": "CurrentValueType",
             "description": "Тип текущего значения JSON"},
            {"name": "ТекущееЗначение", "name_en": "CurrentValue",
             "description": "Текущее значение токена JSON"},
        ],
    },
    {
        "name": "ЗаписьJSON", "name_en": "JSONWriter", "kind": "class",
        "description": "Потоковая запись JSON",
        "methods": [
            {"name": "ОткрытьФайл", "name_en": "OpenFile",
             "signature": "ОткрытьФайл(ПутьКФайлу, Кодировка?, ПараметрыJSON?)",
             "description": "Открывает файл для записи JSON"},
            {"name": "УстановитьСтроку", "name_en": "SetString",
             "signature": "УстановитьСтроку()",
             "description": "Готовит запись в строку"},
            {"name": "Закрыть", "name_en": "Close",
             "signature": "Закрыть() → Строка",
             "description": "Закрывает запись, возвращает строку если запись в строку"},
            {"name": "ЗаписатьНачалоОбъекта", "name_en": "WriteStartObject",
             "signature": "ЗаписатьНачалоОбъекта()",
             "description": "Записывает начало JSON-объекта {"},
            {"name": "ЗаписатьКонецОбъекта", "name_en": "WriteEndObject",
             "signature": "ЗаписатьКонецОбъекта()",
             "description": "Записывает конец JSON-объекта }"},
            {"name": "ЗаписатьИмяСвойства", "name_en": "WritePropertyName",
             "signature": "ЗаписатьИмяСвойства(Имя)",
             "description": "Записывает имя свойства JSON"},
            {"name": "ЗаписатьЗначение", "name_en": "WriteValue",
             "signature": "ЗаписатьЗначение(Значение)",
             "description": "Записывает значение JSON"},
        ],
        "properties": [],
    },
    {
        "name": "ДеревоЗначений", "name_en": "ValueTree", "kind": "class",
        "description": "Иерархическая коллекция строк с произвольными колонками",
        "methods": [
            {"name": "Строки", "name_en": "Rows",
             "signature": "Строки() → КоллекцияСтрокДереваЗначений",
             "description": "Возвращает корневые строки дерева"},
            {"name": "Колонки", "name_en": "Columns",
             "signature": "Колонки() → КоллекцияКолонок",
             "description": "Возвращает коллекцию колонок"},
            {"name": "Скопировать", "name_en": "Copy",
             "signature": "Скопировать() → ДеревоЗначений",
             "description": "Создаёт копию дерева"},
        ],
        "properties": [],
    },
    {
        "name": "СписокЗначений", "name_en": "ValueList", "kind": "class",
        "description": "Список значений с пометками и представлениями",
        "methods": [
            {"name": "Добавить", "name_en": "Add",
             "signature": "Добавить(Значение?, Представление?, Пометка?, Картинка?) → ЭлементСпискаЗначений",
             "description": "Добавляет элемент в список"},
            {"name": "Вставить", "name_en": "Insert",
             "signature": "Вставить(Индекс, Значение?, Представление?, Пометка?)",
             "description": "Вставляет элемент по индексу"},
            {"name": "Количество", "name_en": "Count",
             "signature": "Количество() → Число",
             "description": "Возвращает количество элементов"},
            {"name": "Удалить", "name_en": "Delete",
             "signature": "Удалить(ЭлементИлиИндекс)",
             "description": "Удаляет элемент"},
            {"name": "НайтиПоЗначению", "name_en": "FindByValue",
             "signature": "НайтиПоЗначению(Значение) → ЭлементСпискаЗначений",
             "description": "Ищет элемент по значению"},
            {"name": "ВыгрузитьЗначения", "name_en": "UnloadValues",
             "signature": "ВыгрузитьЗначения() → Массив",
             "description": "Возвращает массив значений элементов"},
            {"name": "ЗагрузитьЗначения", "name_en": "LoadValues",
             "signature": "ЗагрузитьЗначения(Массив)",
             "description": "Заполняет список из массива"},
        ],
        "properties": [],
    },
]


# ---------------------------------------------------------------------------
# PlatformApi class
# ---------------------------------------------------------------------------


class PlatformApi:
    """
    Registry of 1C platform types and global functions.

    Supports completion, hover, and search for both Russian and English names.
    Can be extended with JSON files from ``data/platform_api/``.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._types: dict[str, ApiType] = {}
        self._globals: list[ApiMethod] = []
        self._type_index: dict[str, str] = {}  # lowercase name → canonical name

        # Load built-in data
        self._load_builtin()

        # Load JSON files if directory is provided
        if data_dir is not None:
            self._load_from_dir(Path(data_dir))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_type(self, name: str) -> ApiType | None:
        """Look up a platform type by name (case-insensitive)."""
        canonical = self._type_index.get(name.lower())
        return self._types.get(canonical) if canonical else None

    def find_global(self, name: str) -> ApiMethod | None:
        """Look up a global function by name (case-insensitive)."""
        name_lo = name.lower()
        for m in self._globals:
            if m.name.lower() == name_lo or m.name_en.lower() == name_lo:
                return m
        return None

    def find_type_method(self, method_name: str) -> list[tuple[ApiType, ApiMethod]]:
        """Find all platform types that have a method with the given name (case-insensitive).

        Returns list of (ApiType, ApiMethod) pairs — there can be multiple since
        many types share method names (e.g. «Выбрать», «Добавить», «Количество»).
        """
        name_lo = method_name.lower()
        results: list[tuple[ApiType, ApiMethod]] = []
        for t in self._types.values():
            for m in t.methods:
                if m.name.lower() == name_lo or (m.name_en and m.name_en.lower() == name_lo):
                    results.append((t, m))
                    break
        return results

    def find_type_property(self, prop_name: str) -> list[tuple[ApiType, ApiProperty]]:
        """Find all platform types that have a property with the given name (case-insensitive)."""
        name_lo = prop_name.lower()
        results: list[tuple[ApiType, ApiProperty]] = []
        for t in self._types.values():
            for p in t.properties:
                if p.name.lower() == name_lo or (p.name_en and p.name_en.lower() == name_lo):
                    results.append((t, p))
                    break
        return results

    def get_method_completions(self, type_name: str) -> list[dict]:
        """Return completion items for methods of a given type."""
        t = self.find_type(type_name)
        if t is None:
            return []
        return [
            {
                "label": m.name,
                "label_en": m.name_en,
                "kind": "method",
                "signature": m.signature,
                "description": m.description,
            }
            for m in t.methods
        ] + [
            {
                "label": p.name,
                "label_en": p.name_en,
                "kind": "property",
                "description": p.description,
            }
            for p in t.properties
        ]

    def get_global_completions(self, prefix: str = "") -> list[dict]:
        """Return global function completions matching *prefix* (case-insensitive)."""
        prefix_lo = prefix.lower()
        result = []
        for m in self._globals:
            if m.name.lower().startswith(prefix_lo) or m.name_en.lower().startswith(prefix_lo):
                result.append(
                    {
                        "label": m.name,
                        "label_en": m.name_en,
                        "kind": "function",
                        "signature": m.signature,
                        "description": m.description,
                    }
                )
        return result

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """
        Full-text search across types, methods, and global functions.

        Returns a list of dicts with ``kind``, ``name``, ``signature``,
        ``description`` keys.
        """
        query_lo = query.lower()
        results: list[dict] = []

        # Global functions
        for m in self._globals:
            if query_lo in m.name.lower() or query_lo in m.name_en.lower():
                results.append(
                    {
                        "kind": "global_function",
                        "name": m.name,
                        "name_en": m.name_en,
                        "signature": m.signature,
                        "description": m.description,
                    }
                )

        # Types + their methods
        for t in self._types.values():
            if query_lo in t.name.lower() or query_lo in t.name_en.lower():
                results.append(
                    {
                        "kind": t.kind,
                        "name": t.name,
                        "name_en": t.name_en,
                        "description": t.description,
                    }
                )
            for m in t.methods:
                if query_lo in m.name.lower() or query_lo in m.name_en.lower():
                    results.append(
                        {
                            "kind": "method",
                            "name": f"{t.name}.{m.name}",
                            "name_en": f"{t.name_en}.{m.name_en}",
                            "signature": m.signature,
                            "description": m.description,
                        }
                    )

        return results[:limit]

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load_builtin(self) -> None:
        for g in _BUILTIN_GLOBALS:
            self._globals.append(
                ApiMethod(
                    name=g["name"],
                    name_en=g.get("name_en", ""),
                    signature=g.get("signature", g["name"] + "()"),
                    description=g.get("description", ""),
                )
            )
        for td in _BUILTIN_TYPES:
            self._register_type(td)

    def _register_type(self, td: dict) -> None:
        methods = [
            ApiMethod(
                name=m["name"],
                name_en=m.get("name_en", ""),
                signature=m.get("signature", ""),
                description=m.get("description", ""),
            )
            for m in td.get("methods", [])
        ]
        properties = [
            ApiProperty(
                name=p["name"],
                name_en=p.get("name_en", ""),
                description=p.get("description", ""),
                read_only=p.get("read_only", False),
            )
            for p in td.get("properties", [])
        ]
        t = ApiType(
            name=td["name"],
            name_en=td.get("name_en", ""),
            kind=td.get("kind", "class"),
            description=td.get("description", ""),
            methods=methods,
            properties=properties,
        )
        self._types[t.name] = t
        self._type_index[t.name.lower()] = t.name
        if t.name_en:
            self._type_index[t.name_en.lower()] = t.name

    def _load_from_dir(self, data_dir: Path) -> None:
        """Load JSON type definitions from *data_dir*."""
        if not data_dir.is_dir():
            return
        for json_file in sorted(data_dir.glob("*.json")):
            try:
                td = json.loads(json_file.read_text(encoding="utf-8"))
                self._register_type(td)
            except Exception:  # noqa: BLE001
                pass  # silently skip malformed files


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialised)
# ---------------------------------------------------------------------------

_default_api: PlatformApi | None = None


def get_platform_api(data_dir: str | Path | None = None) -> PlatformApi:
    """
    Return the shared PlatformApi instance, creating it on first call.

    Pass *data_dir* to load additional JSON files on the first call.
    """
    global _default_api
    if _default_api is None:
        # Try the project-relative data/platform_api directory
        if data_dir is None:
            here = Path(__file__).parent
            candidate = here.parent.parent.parent / "data" / "platform_api"
            if candidate.is_dir():
                data_dir = candidate
        _default_api = PlatformApi(data_dir=data_dir)
    return _default_api
