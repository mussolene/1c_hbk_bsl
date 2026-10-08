# Аудит диагностики onec-hbk-bsl и BSLLS

Дата: 2026-10-08. Основные числа и таблица всех правил ниже сохраняют исходный прогон до исправлений логики. Результаты последующего цикла приведены отдельно, чтобы не смешивать исходный аудит с текущим состоянием.

## Состояние цикла исправлений

Поддержка `.bsl-language-server.json`, исправления координат подсветки и ускорение материализации процедур отправлены в main отдельно от изменений диагностик. Релиз 0.8.51 еще не опубликован: локальная проверка расширения блокируется недоступностью npm, а CI выявил уязвимую зависимость `brace-expansion` 5.0.9.

Сравнения используют те же 432 публичных файла и настройки исходного прогона. Свежий общий прогон: 7262 локальных результата, 5821 BSLLS, 5048 точных диапазонов вместо исходных 4503; диапазонных пар 150 вместо 510. Остаток присутствия: 2048 только локально и 587 только BSLLS. Отличий сообщения на точных диапазонах 1886 вместо 4327; серьезности 0 вместо 206. Эти числа не заменяют семантическую проверку каждого остатка.

После независимой проверки исправлены дополнительные ложные срабатывания BSL009 и BSL052, а также координаты UTF-16 в BSL007 и BSL175. Итоговая проверка пакета: 2099 тестов прошли, 43 пропущены; покрытие 83.65%. Ruff, форматирование, генерация контрактов, проверка исходников релиза и проверка изменений на утечки проходят. Это проверка текущего пакета, а не завершение всего аудита.

| Правило | Текущий результат сравнения | Остаток |
|---|---|---|
| BSL007 | 1182 точных совпадения | 5 локальных восстановлений после ошибочного кода, 31 отличие контекста или восстановления upstream, 3 пропуска и 2 диапазона из-за ошибок зависимости парсера |
| BSL009 | 9 точных совпадений | Независимая проверка дополнительно исправила сравнение строковых ключей с учетом регистра |
| BSL026 | 162 точных совпадения | 1 корректная пустая область после поврежденного цикла, которую upstream пропускает |
| BSL029 | 444 точных совпадения | 10 результатов для унарной арифметики, отрицательных аргументов и восстановления поврежденного кода; закреплены тестами |
| BSL033 | 10 точных совпадений | Различий присутствия и диапазонов нет |
| BSL052 | 35 точных совпадений | 2 корректных составных выражения пропущены upstream, 2 выражения не разобраны локальным парсером; ложное срабатывание на перестановке операндов конкатенации устранено |
| BSL060 | 12 точных совпадений | 2 выражения `НЕ НЕ` восстановлены локально и пропущены upstream |
| BSL062 | Убраны 21 ложное срабатывание на многострочных заголовках | Расширенная область `.bsl` сохранена как существующий контракт проекта; upstream проверяет только `.os` |
| BSL175 | 33 точных совпадения | 10 проверок устаревшей палитры сохранены по контракту платформы 8.3.12; дубли ClearEventLog удалены после исправления BSL176 |
| BSL176 | 52 точных совпадения | Различий присутствия и диапазонов нет |
| BSL253 | 41 точное совпадение | Различий присутствия и диапазонов нет |
| BSL265 | 16 точных совпадений | Различий присутствия и диапазонов нет |

Обновлены 116 статических сообщений и LSP-серьезность актуальных имен правил. После нормализации серьезности расхождений в свежем публичном прогоне нет. Параметризованные сообщения исправлены для BSL002, BSL003, BSL007, BSL008, BSL011, BSL015, BSL019, BSL031, BSL042 и BSL062; еще 28 шаблонов требуют отдельного цикла. У BSL011 остаются подтвержденные различия расчета сложности: 26 против 28 в двух случаях и 16 против 18 в одном. Они не признаны допустимыми.

Аудит всех 180 правил и подготовка общего релиза остаются незавершенными. Совпадение отдельных правил на этом наборе не доказывает эквивалентность на всех входах.

Сравнение с BSLLS v1.0.7, последним опубликованным выпуском по GitHub API на момент проверки, commit `f377f95aefa16a4cf0e4d9af5b1c83800366bebc` тега `v1.0.7`. JDK: Homebrew OpenJDK 25.0.2. Все команды Python выполнены через ./.venv/bin/python проекта.

Проверены 180 локальных правил, 180 страниц контрактов и выполнение матрицы diagnostic_rule_matrix.py. В upstream зарегистрированы 186 правил. Имена DeprecatedMethods8310 и DeprecatedMethods8317 уже отсутствуют в upstream. Локально отсутствуют восемь новых имен, перечисленных ниже.

## Условия сравнения

Основной набор: 432 публичных файла .bsl из src/test/resources тега v1.0.7. Копия сохраняет структуру каталогов и публичные XML/JSON ресурсы; .os исключены, чтобы обеспечить одинаковый набор файлов. Равенство набора файлов проверено явно. Дополнительный набор: 215 файлов .bsl только из diagnostics. Все 180 кодов явно выбраны; у BSLLS diagnostics.mode=ONLY, parameters содержит true для каждого совместимого имени. Для локальных BSL176 и BSL254 использован индексированный DiagnosticEngine из существующего compare_diag_bslls.py. Локальная конфигурация не загружалась. Сообщения сравнивались на русском языке. Строки нормализованы из BSLLS 0-based в 1-based; столбцы остались 0-based. Перед сравнением серьезности применена `lsp_compat_severity`. Сравнение выполнялось при явно выбранных правилах и стандартных параметрах, без параметров из Java-тестов отдельных диагностик. Поэтому правила с особой конфигурацией теста требуют отдельного прогона.

Основной набор является коллекцией разных тестовых проектов, а не одной корректной конфигурацией 1С. Поэтому пропуски правил, требующих метаданных, правильного вида модуля или HBK, не считаются автоматически дефектами. Проверка .os ограничена отдельным синтетическим BSL062 тестом.

## Итог основного набора

Файлов: 432. Локальных диагностик: 7266. BSLLS: 5821. Точных совпадений по коду, файлу и диапазону: 4503. Пар на той же строке с другим диапазоном: 510. Остаток только локально: 2239; только BSLLS: 772. Избыточных одинаковых диагностик: локально 14, BSLLS 36. Неотображаемых результатов: 0.

Числа остатка являются несовпадениями присутствия или координат, а не доказанным количеством семантических дефектов. Алгоритм сравнения спаривает только одинаковые начальные координаты или строки. Например, у BSL052 есть сдвиг диапазона на одну строку, который попадает в остаток.

На точных диапазонах найдены 4327 отличий текста сообщения и 206 отличий серьезности после LSP-нормализации. Текстовые отличия часто означают локальный общий заголовок вместо сообщения с параметрами. У 25 правил нет ни одного результата с обеих сторон; они остаются непроверенными положительным примером. У 129 правил есть результаты с обеих сторон. Только шесть правил имеют положительные результаты и совпадают по всем измеренным полям на этом наборе; даже это не доказывает эквивалентность на всех входах.

Дополнительный набор 215 файлов: локально 4757, BSLLS 3612, точных диапазонов 2887, диапазонных пар 307, остаток локально 1559, BSLLS 403. После LSP-нормализации 196 отличий серьезности, 2741 отличие сообщения. Необходимость нормализации подтверждена: исходные 914 отличий серьезности уменьшились до 196.

## Классификация подтвержденных отличий

- Языковая область: BSL062 UnusedParameters действует в upstream только для .os начиная как минимум с v0.29.0. Синтетический неиспользуемый параметр: локально один результат и для .bsl, и для .os; BSLLS 0.29.0 и 1.0.7 выдают один только для .os. Используемый параметр не вызывает результатов ни у кого. Контракт BSL062 сейчас описывает параметры вообще и не оговаривает область языка. Это давно существующее расхождение контракта, а не новое изменение upstream.
- Контекст и модуль: BSL042 UnusedLocalMethod, BSL170 CompilationDirectiveNeedLess и BSL272 UsingSynchronousCalls требуют анализа вида модуля/HBK. Отсутствие результатов BSLLS в отдельных фикстурах без такого контекста не означает, что алгоритм поиска локально неверен. Требуется отдельная проверка корректных конфигураций.
- Семантика BSL029 MagicNumber: публичный MagicNumberDiagnostic.bsl, строка 45, прямой Возврат 12 локально диагностируется, upstream пропускает; строки 64 и 68, конструктор Дата с числовыми компонентами, также дают лишние локальные результаты. Это конкретные отрицательные примеры upstream.
- Семантика BSL007 UnusedLocalVariable: публичный UnusedLocalVariableDiagnostic.bsl, строка 2, переменная модуля с &НаКлиенте пропущена локально и диагностируется upstream. Контекст клиентского директивного объявления требует проверки.
- Семантика BSL176 DeprecatedMethodCall: публичный DeprecatedMethodCallDiagnostic.bsl, строка 29, вызов локальной процедуры с описанием устаревания не диагностируется локально, upstream выдает результат.
- Диапазон BSL052 IdenticalExpressions: выражение на строке 5 публичной фикстуры получает локальный диапазон строки 6, выражение на строке 7 получает диапазон строки 8. Есть также остаточные неподтвержденные семантические отличия.
- Диапазоны BSL026 EmptyRegion, BSL175 DeprecatedAttributes8312, BSL253 TimeoutsInExternalResources: соответственно 162, 33, 40 пар с отличающимися диапазонами в основном наборе.
- Парсер: BSL001, локально 124, BSLLS 81, точный диапазон один, 14 диапазонных пар, 23 повторных диагностики upstream. Разные парсеры и восстановление после ошибки, результаты нельзя считать все истинными ошибками реализации.
- Сообщения: BSL002 MethodSize сообщает локальный общий заголовок вместо upstream текста с именем метода, длиной и порогом; пример MethodSizeDiagnostic.bsl, строка 7. Аналогичные отличия затрагивают 105 правил в основном наборе.
- Серьезность: BSL008 TooManyReturns локально WARNING, BSLLS INFORMATION; BSL148 AllFunctionPathMustHaveReturn локально ERROR, BSLLS WARNING. Суммарно после LSP-нормализации расхождения остаются у 11 правил.
- Дубликаты: 14 локальных и 36 upstream повторных результатов в основном наборе. Это отдельная категория; не следует складывать их с семантическими остатками.

## Отсутствующие правила upstream

Дополнительный запуск BSLLS явно включил все 186 актуальных имен, включая отсутствующие локально. Результаты на том же основном наборе:

| Имя | Результатов BSLLS |
|---|---:|
| AssignToReadOnlyProperty | 4 |
| BadExceptionCategory | 7 |
| CommonModuleVariables | 0 |
| CompareWithBoolean | 6 |
| EventHandlerInvalidSignature | 0 |
| EventHandlerOutsideEventRegion | 0 |
| UnavailableMemberCall | 0 |
| UnknownMember | 1326 |

UnknownMember выключен по умолчанию и без корректного HBK дает много неизвестных имен в сборном наборе; число 1326 не является оценкой реального количества ошибок. Нулевые результаты четырех отсутствующих правил не означают, что они реализованы локально.

## Воспроизведение

Временные сценарии только оркестрируют существующий scripts/compare_diag_bslls.py и не добавляют новую возможность в репозиторий:

```sh
./.venv/bin/python scripts/diagnostic_rule_matrix.py --format summary
BSLLS_JAVA=/opt/homebrew/opt/openjdk/bin/java ./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/run_audit.py
BSLLS_JAVA=/opt/homebrew/opt/openjdk/bin/java ./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/run_full.py
./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/classify.py
./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/classify_full.py
BSLLS_JAVA=/opt/homebrew/opt/openjdk/bin/java ./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/probe062.py
BSLLS_JAVA=/opt/homebrew/opt/openjdk/bin/java ./.venv/bin/python /tmp/bslls-public-audit-xAlSiN/upstream_all.py
```

Артефакты: full/parity.json, full/per-rule.json, full/message-examples.json, full/severity-examples.json, coverage.json, missing-rule-counts.json, scope062.json. Отчет использует только публичный upstream и синтетические примеры. Частные корпуса и их пути не читались. Временные файлы могут быть удалены системой.

Источники: [официальные правила BSLLS](https://1c-syntax.github.io/bsl-language-server/en/diagnostics/) и [конфигурация BSLLS](https://1c-syntax.github.io/bsl-language-server/en/features/ConfigurationFile/). Исходный код сравнивался на теге v1.0.7 с указанным выше commit; историческая область UnusedParameters дополнительно проверена на теге v0.29.0.

## Все локальные правила

Колонки текста и серьезности относятся только к точным диапазонам. Нули с обеих сторон означают отсутствие положительного покрытия.

| Код | Имя | Локально | BSLLS | Точно | Диапазон | Только локально | Только BSLLS | Текст | Серьезность |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BSL001 | ParseError | 124 | 81 | 1 | 14 | 109 | 43 | 1 | 0 |
| BSL002 | MethodSize | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| BSL003 | NonExportMethodsInApiRegion | 17 | 15 | 15 | 0 | 2 | 0 | 15 | 0 |
| BSL004 | EmptyCodeBlock | 101 | 108 | 101 | 0 | 0 | 7 | 101 | 0 |
| BSL005 | UsingHardcodeNetworkAddress | 13 | 13 | 13 | 0 | 0 | 0 | 13 | 0 |
| BSL006 | UsingHardcodePath | 52 | 52 | 52 | 0 | 0 | 0 | 52 | 0 |
| BSL007 | UnusedLocalVariable | 1165 | 1218 | 960 | 116 | 89 | 142 | 960 | 0 |
| BSL008 | TooManyReturns | 7 | 7 | 7 | 0 | 0 | 0 | 7 | 7 |
| BSL009 | SelfAssign | 6 | 9 | 1 | 5 | 0 | 3 | 1 | 0 |
| BSL011 | CognitiveComplexity | 17 | 17 | 15 | 0 | 2 | 2 | 15 | 0 |
| BSL012 | UsingHardcodeSecretInformation | 12 | 12 | 2 | 10 | 0 | 0 | 2 | 0 |
| BSL013 | CommentedCode | 11 | 30 | 7 | 0 | 4 | 23 | 7 | 0 |
| BSL014 | LineLength | 75 | 81 | 74 | 0 | 1 | 7 | 74 | 0 |
| BSL015 | NumberOfOptionalParams | 4 | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| BSL016 | NonStandardRegion | 63 | 0 | 0 | 0 | 63 | 0 | 0 | 0 |
| BSL017 | CommandModuleExportMethods | 13 | 0 | 0 | 0 | 13 | 0 | 0 | 0 |
| BSL019 | CyclomaticComplexity | 7 | 12 | 7 | 0 | 0 | 5 | 7 | 0 |
| BSL020 | NestedStatements | 5 | 5 | 5 | 0 | 0 | 0 | 5 | 0 |
| BSL022 | UsingModalWindows | 26 | 26 | 26 | 0 | 0 | 0 | 26 | 0 |
| BSL023 | UsingServiceTag | 40 | 40 | 40 | 0 | 0 | 0 | 40 | 0 |
| BSL024 | SpaceAtStartComment | 120 | 115 | 104 | 0 | 16 | 11 | 104 | 0 |
| BSL025 | EmptyStatement | 8 | 16 | 7 | 0 | 1 | 9 | 7 | 0 |
| BSL026 | EmptyRegion | 163 | 162 | 0 | 162 | 1 | 0 | 0 | 0 |
| BSL027 | UsingGoto | 21 | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| BSL028 | MissingCodeTryCatchEx | 15 | 15 | 15 | 0 | 0 | 0 | 15 | 0 |
| BSL029 | MagicNumber | 491 | 444 | 438 | 0 | 53 | 6 | 438 | 0 |
| BSL030 | SemicolonPresence | 65 | 66 | 32 | 8 | 25 | 26 | 32 | 0 |
| BSL031 | NumberOfParams | 4 | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| BSL032 | FunctionShouldHaveReturn | 176 | 174 | 172 | 2 | 2 | 0 | 172 | 0 |
| BSL033 | CreateQueryInCycle | 0 | 10 | 0 | 0 | 0 | 10 | 0 | 0 |
| BSL035 | DuplicateStringLiteral | 58 | 57 | 57 | 0 | 1 | 0 | 57 | 0 |
| BSL036 | IfConditionComplexity | 11 | 11 | 10 | 0 | 1 | 1 | 10 | 0 |
| BSL039 | NestedTernaryOperator | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 0 |
| BSL040 | UsingThisForm | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL041 | DeprecatedMessage | 134 | 133 | 133 | 0 | 1 | 0 | 133 | 0 |
| BSL042 | UnusedLocalMethod | 1006 | 0 | 0 | 0 | 1006 | 0 | 0 | 0 |
| BSL047 | MagicDate | 25 | 25 | 25 | 0 | 0 | 0 | 25 | 0 |
| BSL051 | UnreachableCode | 57 | 43 | 12 | 21 | 24 | 10 | 12 | 0 |
| BSL052 | IdenticalExpressions | 32 | 39 | 0 | 5 | 27 | 32 | 0 | 0 |
| BSL054 | ExportVariables | 20 | 18 | 16 | 0 | 4 | 2 | 16 | 0 |
| BSL055 | ConsecutiveEmptyLines | 72 | 85 | 71 | 1 | 0 | 13 | 71 | 0 |
| BSL060 | DoubleNegatives | 10 | 12 | 8 | 0 | 2 | 4 | 8 | 0 |
| BSL062 | UnusedParameters | 225 | 0 | 0 | 0 | 225 | 0 | 0 | 0 |
| BSL064 | ProcedureReturnsValue | 7 | 8 | 0 | 7 | 0 | 1 | 0 | 0 |
| BSL065 | MissingReturnedValueDescription | 46 | 39 | 37 | 0 | 9 | 2 | 37 | 0 |
| BSL066 | DeprecatedFind | 5 | 4 | 4 | 0 | 1 | 0 | 4 | 0 |
| BSL077 | SelectTopWithoutOrderBy | 10 | 10 | 10 | 0 | 0 | 0 | 10 | 0 |
| BSL097 | DeprecatedCurrentDate | 11 | 11 | 11 | 0 | 0 | 0 | 11 | 0 |
| BSL131 | DuplicateRegion | 47 | 46 | 45 | 1 | 1 | 0 | 45 | 0 |
| BSL148 | AllFunctionPathMustHaveReturn | 10 | 10 | 7 | 0 | 3 | 3 | 7 | 7 |
| BSL149 | AssignAliasFieldsInQuery | 134 | 125 | 119 | 0 | 15 | 6 | 119 | 0 |
| BSL150 | BadWords | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL151 | BeginTransactionBeforeTryCatch | 35 | 35 | 35 | 0 | 0 | 0 | 35 | 0 |
| BSL152 | CachedPublic | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL153 | CanonicalSpellingKeywords | 275 | 272 | 272 | 0 | 3 | 0 | 272 | 0 |
| BSL154 | CodeAfterAsyncCall | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL155 | CodeBlockBeforeSub | 17 | 12 | 12 | 0 | 5 | 0 | 12 | 0 |
| BSL156 | CodeOutOfRegion | 30 | 0 | 0 | 0 | 30 | 0 | 0 | 0 |
| BSL157 | CommitTransactionOutsideTryCatch | 38 | 42 | 38 | 0 | 0 | 4 | 38 | 0 |
| BSL158 | CommonModuleAssign | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL159 | CommonModuleInvalidType | 7 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| BSL160 | CommonModuleMissingAPI | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| BSL161 | CommonModuleNameCached | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL162 | CommonModuleNameClient | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL163 | CommonModuleNameClientServer | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL164 | CommonModuleNameFullAccess | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| BSL165 | CommonModuleNameGlobal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL166 | CommonModuleNameGlobalClient | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL167 | CommonModuleNameServerCall | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL168 | CommonModuleNameWords | 7 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| BSL169 | CompilationDirectiveLost | 5 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| BSL170 | CompilationDirectiveNeedLess | 200 | 0 | 0 | 0 | 200 | 0 | 0 | 0 |
| BSL171 | CrazyMultilineString | 4 | 7 | 1 | 2 | 1 | 4 | 1 | 1 |
| BSL172 | DataExchangeLoading | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL173 | DeletingCollectionItem | 8 | 8 | 8 | 0 | 0 | 0 | 8 | 0 |
| BSL174 | DenyIncompleteValues | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| BSL175 | DeprecatedAttributes8312 | 45 | 33 | 0 | 33 | 12 | 0 | 0 | 0 |
| BSL176 | DeprecatedMethodCall | 41 | 52 | 28 | 0 | 13 | 24 | 25 | 0 |
| BSL177 | DeprecatedMethods8310 | 6 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| BSL178 | DeprecatedMethods8317 | 23 | 0 | 0 | 0 | 23 | 0 | 0 | 0 |
| BSL179 | DeprecatedTypeManagedForm | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| BSL180 | DisableSafeMode | 4 | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| BSL181 | DuplicatedInsertionIntoCollection | 11 | 21 | 6 | 0 | 5 | 15 | 6 | 0 |
| BSL182 | ExcessiveAutoTestCheck | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL183 | ExecuteExternalCode | 22 | 0 | 0 | 0 | 22 | 0 | 0 | 0 |
| BSL184 | ExecuteExternalCodeInCommonModule | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL185 | ExternalAppStarting | 22 | 22 | 22 | 0 | 0 | 0 | 22 | 0 |
| BSL186 | ExtraCommas | 15 | 14 | 14 | 0 | 1 | 0 | 14 | 0 |
| BSL187 | FieldsFromJoinsWithoutIsNull | 32 | 29 | 28 | 0 | 4 | 1 | 0 | 0 |
| BSL188 | FileSystemAccess | 61 | 61 | 61 | 0 | 0 | 0 | 61 | 61 |
| BSL189 | ForbiddenMetadataName | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL190 | FormDataToValue | 6 | 4 | 4 | 0 | 2 | 0 | 4 | 0 |
| BSL191 | FullOuterJoinQuery | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| BSL192 | FunctionNameStartsWithGet | 6 | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| BSL193 | FunctionOutParameter | 9 | 8 | 8 | 0 | 1 | 0 | 0 | 0 |
| BSL194 | FunctionReturnsSamePrimitive | 5 | 5 | 5 | 0 | 0 | 0 | 5 | 0 |
| BSL195 | GetFormMethod | 6 | 6 | 6 | 0 | 0 | 0 | 6 | 0 |
| BSL196 | GlobalContextMethodCollision8312 | 20 | 20 | 20 | 0 | 0 | 0 | 0 | 0 |
| BSL197 | IfElseDuplicatedCodeBlock | 9 | 9 | 9 | 0 | 0 | 0 | 9 | 0 |
| BSL198 | IfElseDuplicatedCondition | 6 | 6 | 6 | 0 | 0 | 0 | 6 | 0 |
| BSL199 | IfElseIfEndsWithElse | 18 | 18 | 18 | 0 | 0 | 0 | 18 | 0 |
| BSL200 | IncorrectLineBreak | 73 | 73 | 73 | 0 | 0 | 0 | 73 | 0 |
| BSL201 | IncorrectUseLikeInQuery | 20 | 20 | 16 | 4 | 0 | 0 | 0 | 16 |
| BSL202 | IncorrectUseOfStrTemplate | 6 | 12 | 0 | 6 | 0 | 6 | 0 | 0 |
| BSL203 | InternetAccess | 79 | 78 | 78 | 0 | 1 | 0 | 78 | 78 |
| BSL204 | InvalidCharacterInFile | 88 | 88 | 82 | 6 | 0 | 0 | 82 | 0 |
| BSL205 | IsInRoleMethod | 5 | 4 | 4 | 0 | 1 | 0 | 4 | 0 |
| BSL206 | JoinWithSubQuery | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| BSL207 | JoinWithVirtualTable | 8 | 9 | 8 | 0 | 0 | 1 | 8 | 0 |
| BSL208 | LatinAndCyrillicSymbolInWord | 29 | 30 | 29 | 0 | 0 | 1 | 29 | 0 |
| BSL209 | LogicalOrInJoinQuerySection | 7 | 8 | 7 | 0 | 0 | 1 | 7 | 0 |
| BSL210 | LogicalOrInTheWhereSectionOfQuery | 7 | 7 | 7 | 0 | 0 | 0 | 7 | 0 |
| BSL211 | MetadataObjectNameLength | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL212 | MissedRequiredParameter | 14 | 15 | 14 | 0 | 0 | 1 | 14 | 0 |
| BSL213 | MissingCommonModuleMethod | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL214 | MissingEventSubscriptionHandler | 6 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| BSL215 | MissingParameterDescription | 57 | 53 | 38 | 1 | 18 | 14 | 38 | 0 |
| BSL216 | MissingSpace | 253 | 245 | 238 | 0 | 15 | 7 | 238 | 0 |
| BSL217 | MissingTempStorageDeletion | 5 | 6 | 5 | 0 | 0 | 1 | 5 | 0 |
| BSL218 | MissingTemporaryFileDeletion | 10 | 7 | 7 | 0 | 3 | 0 | 7 | 0 |
| BSL219 | MissingVariablesDescription | 62 | 64 | 61 | 0 | 1 | 3 | 61 | 0 |
| BSL220 | MultilineStringInQuery | 1 | 3 | 1 | 0 | 0 | 2 | 0 | 1 |
| BSL221 | MultilingualStringHasAllDeclaredLanguages | 6 | 6 | 4 | 0 | 2 | 2 | 4 | 4 |
| BSL222 | MultilingualStringUsingWithTemplate | 2 | 4 | 2 | 0 | 0 | 2 | 2 | 2 |
| BSL223 | NestedConstructorsInStructureDeclaration | 15 | 14 | 2 | 12 | 1 | 0 | 0 | 0 |
| BSL224 | NestedFunctionInParameters | 15 | 13 | 13 | 0 | 2 | 0 | 13 | 0 |
| BSL225 | NumberOfValuesInStructureConstructor | 7 | 7 | 7 | 0 | 0 | 0 | 7 | 0 |
| BSL226 | OSUsersMethod | 3 | 3 | 3 | 0 | 0 | 0 | 3 | 0 |
| BSL227 | OneStatementPerLine | 9 | 11 | 8 | 0 | 1 | 3 | 8 | 0 |
| BSL228 | OrderOfParams | 7 | 7 | 7 | 0 | 0 | 0 | 7 | 0 |
| BSL229 | OrdinaryAppSupport | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| BSL230 | PairingBrokenTransaction | 29 | 29 | 0 | 22 | 3 | 3 | 0 | 0 |
| BSL231 | PrivilegedModuleMethodCall | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| BSL232 | ProtectedModule | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL233 | PublicMethodsDescription | 6 | 4 | 4 | 0 | 2 | 0 | 4 | 0 |
| BSL234 | QueryNestedFieldsByDot | 47 | 46 | 44 | 0 | 3 | 2 | 44 | 0 |
| BSL235 | QueryParseError | 16 | 12 | 5 | 0 | 11 | 7 | 5 | 0 |
| BSL236 | QueryToMissingMetadata | 0 | 203 | 0 | 0 | 0 | 203 | 0 | 0 |
| BSL237 | RedundantAccessToObject | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL238 | RefOveruse | 24 | 23 | 21 | 0 | 3 | 2 | 21 | 0 |
| BSL239 | ReservedParameterNames | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL240 | RewriteMethodParameter | 6 | 6 | 0 | 4 | 2 | 2 | 0 | 0 |
| BSL241 | SameMetadataObjectAndChildNames | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL242 | ScheduledJobHandler | 7 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| BSL243 | SelfInsertion | 2 | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| BSL244 | ServerCallsInFormEvents | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL245 | ServerSideExportFormMethod | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL246 | SetPermissionsForNewObjects | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL247 | SetPrivilegedMode | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| BSL248 | SeveralCompilerDirectives | 11 | 12 | 8 | 2 | 1 | 2 | 8 | 0 |
| BSL249 | StyleElementConstructors | 15 | 23 | 15 | 0 | 0 | 8 | 15 | 0 |
| BSL250 | TempFilesDir | 3 | 3 | 3 | 0 | 0 | 0 | 3 | 0 |
| BSL251 | TernaryOperatorUsage | 54 | 53 | 53 | 0 | 1 | 0 | 53 | 0 |
| BSL252 | ThisObjectAssign | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| BSL253 | TimeoutsInExternalResources | 44 | 41 | 0 | 41 | 3 | 0 | 0 | 0 |
| BSL254 | TransferringParametersBetweenClientAndServer | 1 | 5 | 1 | 0 | 0 | 4 | 1 | 0 |
| BSL255 | TryNumber | 3 | 3 | 3 | 0 | 0 | 0 | 3 | 0 |
| BSL256 | Typo | 125 | 155 | 90 | 7 | 28 | 51 | 90 | 0 |
| BSL257 | UnaryPlusInConcatenation | 3 | 3 | 3 | 0 | 0 | 0 | 3 | 0 |
| BSL258 | UnionAll | 2 | 2 | 2 | 0 | 0 | 0 | 2 | 0 |
| BSL259 | UnknownPreprocessorSymbol | 11 | 2 | 1 | 0 | 10 | 1 | 1 | 1 |
| BSL260 | UnsafeFindByCode | 0 | 12 | 0 | 0 | 0 | 12 | 0 | 0 |
| BSL261 | UnsafeSafeModeMethodCall | 8 | 10 | 6 | 0 | 2 | 4 | 0 | 0 |
| BSL262 | UsageWriteLogEvent | 12 | 18 | 12 | 0 | 0 | 6 | 12 | 0 |
| BSL263 | UseLessForEach | 47 | 50 | 47 | 0 | 0 | 3 | 47 | 0 |
| BSL264 | UseSystemInformation | 6 | 6 | 6 | 0 | 0 | 0 | 6 | 0 |
| BSL265 | UselessTernaryOperator | 16 | 16 | 16 | 0 | 0 | 0 | 0 | 0 |
| BSL266 | UsingCancelParameter | 7 | 7 | 5 | 2 | 0 | 0 | 0 | 0 |
| BSL267 | UsingExternalCodeTools | 7 | 7 | 7 | 0 | 0 | 0 | 7 | 0 |
| BSL268 | UsingFindElementByString | 34 | 35 | 34 | 0 | 0 | 1 | 34 | 0 |
| BSL269 | UsingLikeInQuery | 42 | 42 | 28 | 14 | 0 | 0 | 0 | 28 |
| BSL271 | UsingObjectNotAvailableUnix | 8 | 4 | 4 | 0 | 4 | 0 | 0 | 0 |
| BSL272 | UsingSynchronousCalls | 53 | 0 | 0 | 0 | 53 | 0 | 0 | 0 |
| BSL273 | VirtualTableCallWithoutParameters | 8 | 8 | 7 | 0 | 1 | 1 | 7 | 0 |
| BSL274 | WrongDataPathForFormElements | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| BSL275 | WrongHttpServiceHandler | 3 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| BSL276 | WrongUseFunctionProceedWithCall | 4 | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| BSL277 | WrongUseOfRollbackTransactionMethod | 19 | 19 | 19 | 0 | 0 | 0 | 19 | 0 |
| BSL278 | WrongWebServiceHandler | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| BSL279 | YoLetterUsage | 14 | 14 | 14 | 0 | 0 | 0 | 14 | 0 |
