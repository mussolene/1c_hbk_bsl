# Аудит диагностик onec-hbk-bsl и BSLLS

Дата проверки: 2026-10-08. Изменения диагностик этого аудита опубликованы
в [релизе 0.8.52](https://github.com/mussolene/1c_hbk_bsl/releases/tag/v0.8.52).
Эта страница показывает текущее проверенное состояние, а не исходную таблицу
до исправлений. Наличие реализации не означает полного паритета с BSLLS.

## Эталон и границы проверки

Эталон выполненного сравнения: BSLLS `v1.1.0-rc.6`, commit
`52a38118b07d6ef2779d46595f349ebf8fd5e8bc`. Это предварительный выпуск.
Первый цикл использовал `v1.0.7`; его результаты не смешиваются с текущими.

Проверены 180 локальных правил на 432 публичных файлах `.bsl` из ресурсов
`v1.0.7`, включая публичные XML/JSON ресурсы. Сохранялись одинаковые файлы,
русские сообщения, стандартные пороги и явный выбор правил. У BSLLS использован
`diagnostics.mode=ONLY` со значением `true` для каждого сопоставимого имени.
Локальная конфигурация не загружалась. Новые фикстуры rc.6, полноценные проекты
с HBK и все сценарии `.os` этим общим прогоном не покрыты.

Строки приведены к нумерации с 1, столбцы остаются с 0; серьезность сравнивается
после `lsp_compat_severity`. Все входы публичные или синтетические. Сборный
набор тестовых проектов не является одной корректной конфигурацией 1С.

## Текущие результаты

| Измерение | Результат |
|---|---:|
| Локальные диагностики | 7267 |
| Диагностики BSLLS | 5819 |
| Совпадения по коду, файлу и диапазону | 5051 |
| Пары на той же строке с другим диапазоном | 150 |
| Только локально | 2050 |
| Только BSLLS | 582 |
| Различия сообщения на точных диапазонах | 6 |
| Различия серьезности после нормализации | 0 |

Остатки присутствия не равны количеству дефектов. Алгоритм сопоставляет
одинаковые координаты или строки; сообщения о том же объекте на разных
строках попадают в два остатка. Контекст, параметры, восстановление после
ошибки и намеренные отличия также требуют отдельной классификации.

В общем наборе у 25 правил нет положительного результата с обеих сторон.
Нулевые строки таблицы не подтверждают корректность правила. Отдельные
семантические тесты и тесты метаданных проверяются дополнительно.

## Что исправлено

- Первый пакет: BSL007/009/026/029/033/052/060/062/175/176/253/265,
  включая ложные срабатывания, пропуски и диапазоны Unicode.
- BSL011/019: переходы, вложенность тернарных условий, логические операторы
  в начале строки и суммарная сложность внешних исполняемых блоков модуля.
  BSL019 теперь проверяет тело модуля также через сериализуемые факты.
- BSL042/212: вызов через получателя больше не считается использованием
  неэкспортного локального метода и не получает параметры чужого локального
  объявления, включая многострочные обращения.
- BSL052 и сбор объявлений: итеративный обход устраняет RecursionError
  на цепочках из 500 и 1000 операндов. Независимое сравнение 260 выражений
  сохранило все 67 600 попарных отношений равенства прежнего алгоритма.
- Уточнены 116 статических сообщений, параметризованные сообщения первого
  пакета и еще 28 шаблонов. Различия текста на точных диапазонах последнего
  цикла сократились с 1883 до 6 без изменения количества и диапазонов.

Оставшиеся шесть различий текста: одно BSL001 с ожидаемыми токенами другого
парсера и пять BSL256 с отличающимся выбором фрагмента слова. Это не число
всех оставшихся семантических проблем.

## Подтвержденные отличия контракта

Это технически обоснованное сохранение поведения, а не одобрение всего остатка.

| Правила | Сохраняемое поведение | Основание |
|---|---|---|
| BSL062 | Проверка `.bsl` и `.os`; BSLLS проверяет `.os` | Существующий публичный контракт проекта |
| BSL175 | Дополнительная проверка устаревшей палитры | Контракт платформы 8.3.12 и отдельные тесты |
| BSL177/178 | Старые имена и проверки, отсутствующие в каталоге rc.6 | Обратная совместимость |
| BSL011/019 | Место сообщения у первого исполняемого токена тела модуля | BSLLS в двух фикстурах указывает объявление метода перед внешним кодом |

Последнее отличие воспроизводится на публичных
`IdenticalExpressionsDiagnostic.bsl` и `NestedStatementsDiagnostic.bsl`:
внешний код начинается на строках 39 и 12, а BSLLS указывает строку 1.
Локальный контракт не переносит сообщение на объявление другого объекта.

BSL042 сохраняет проверку отдельно открытых файлов без полного контекста
конфигурации. Это не подтверждает правильность каждого из 1006 дополнительных
результатов в сборном наборе. Восстановления после поврежденного кода у BSL007,
BSL026, BSL029 и BSL060 также нельзя автоматически выравнивать по BSLLS.

## Открытые вопросы

- Парсер: подтверждены неразобранные случаи BSL007 и BSL052. Исправления
  диапазонов или предикатов правила не заменяют исправления дерева разбора.
- BSL256: требуется проверить выделение слов и исключения; разница текста
  связана с выбираемым фрагментом, а не только с формулировкой.
- BSL013/030/051/215/216/230/235 и другие строки с остатками требуют отдельных
  положительных и отрицательных примеров. Статистика сама по себе не
  доказывает, какая сторона ошибается.
- BSL042/170/236/272 и проверки обработчиков требуют сопоставимого контекста
  вида модуля, метаданных и типов. Например, 203 результата BSLLS у BSL236
  нельзя объявить 203 локальными пропусками без такого контекста.
- Новые фикстуры rc.6 и правила с нестандартными параметрами требуют отдельного
  прогона; общий запуск использовал стандартные пороги.

## Отсутствующие правила

В каталоге rc.6 зарегистрированы 189 правил, локально 180; совпадают 178 имен.
Два старых локальных имени сохраняются для совместимости, 11 актуальных
имен еще не реализованы.

| Имя BSLLS | Результатов на сборном наборе при включении всех правил | Зависимость |
|---|---:|---|
| CommonModuleVariables | 0 | Вид модуля и объявления |
| CompilationDirectiveNotAllowed | 0 | Контекст директив |
| SuspiciousChangeAndValidate | 0 | Контекст аннотаций |
| CompareWithBoolean | 6 | Единственный подтвержденный тип Boolean |
| BadExceptionCategory | 7 | Разрешение элемента перечисления категории ошибки |
| AssignToReadOnlyProperty | 4 | Тип и доступность записи свойства |
| CurrentRowAccess | 0 | Типы и контекст обращения |
| EventHandlerInvalidSignature | 0 | Метаданные и сигнатура обработчика |
| EventHandlerOutsideEventRegion | 0 | Контракт события и области |
| UnavailableMemberCall | 0 | Тип и доступность метода |
| UnknownMember | 1317 | Типы, метаданные и HBK |

Эти результаты получены отдельным запуском всех 189 правил. Они не входят
в сравнение 180 локальных правил выше. UnknownMember без корректного HBK
дает много неизвестных имен; 1317 не является оценкой ошибок реального проекта.
Нулевые результаты не означают, что отсутствующее правило реализовано.

## Воспроизведение и доказательства

Используется существующий инструмент, без отдельного реестра правил:

```sh
BSLLS_JAR=/path/to/bsl-language-server-1.1.0-rc.6-exec.jar \
BSLLS_JAVA=/path/to/java \
./.venv/bin/python scripts/compare_diag_bslls.py \
  --workspace /path/to/public-fixtures \
  --preserve-source-root --select BSL011,BSL019 \
  /path/to/public-fixtures
```

Для полного сравнения задайте явный список всех кодов из каталога и сохраните
описанные выше конфигурацию и состав входов. Проверка топологии исполнения:

```sh
./.venv/bin/python scripts/diagnostic_rule_matrix.py --format summary
```

Локальные воспроизводимые результаты последнего цикла сохранены в
`.tmp/bslls-rc6/current`, результат до него в `.tmp/bslls-rc6/wave2`, исходный
эталон в `.tmp/bslls-rc6/baseline`. Временные файлы не входят в репозиторий
и не требуются пользователям для запуска продукта.

Проверка релизного пакета: 2204 теста прошли, 43 пропущены, покрытие 83,90%.
Также прошли независимые проверки диагностик и LSP, сборки четырех платформ
и публикация артефактов. Это доказательства проверенного пакета, а не полного
паритета всех правил на любых входах.

Источники: [официальные правила BSLLS](https://1c-syntax.github.io/bsl-language-server/en/diagnostics/)
и [конфигурация BSLLS](https://1c-syntax.github.io/bsl-language-server/en/features/ConfigurationFile/).

## Все локальные правила: текущий прогон

Текст и серьезность сравниваются только на точных диапазонах.
Колонки остатка показывают несовпадения, не подтвержденные дефекты.

| Код | Имя | Локально | BSLLS | Точно | Диапазон | Только локально | Только BSLLS | Текст | Серьезность |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [BSL001](rule-contracts/BSL001.md) | ParseError | 124 | 81 | 1 | 14 | 109 | 43 | 1 | 0 |
| [BSL002](rule-contracts/BSL002.md) | MethodSize | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| [BSL003](rule-contracts/BSL003.md) | NonExportMethodsInApiRegion | 17 | 15 | 15 | 0 | 2 | 0 | 0 | 0 |
| [BSL004](rule-contracts/BSL004.md) | EmptyCodeBlock | 101 | 108 | 101 | 0 | 0 | 7 | 0 | 0 |
| [BSL005](rule-contracts/BSL005.md) | UsingHardcodeNetworkAddress | 13 | 13 | 13 | 0 | 0 | 0 | 0 | 0 |
| [BSL006](rule-contracts/BSL006.md) | UsingHardcodePath | 52 | 52 | 52 | 0 | 0 | 0 | 0 | 0 |
| [BSL007](rule-contracts/BSL007.md) | UnusedLocalVariable | 1189 | 1218 | 1182 | 2 | 5 | 34 | 0 | 0 |
| [BSL008](rule-contracts/BSL008.md) | TooManyReturns | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| [BSL009](rule-contracts/BSL009.md) | SelfAssign | 9 | 9 | 9 | 0 | 0 | 0 | 0 | 0 |
| [BSL011](rule-contracts/BSL011.md) | CognitiveComplexity | 17 | 17 | 15 | 0 | 2 | 2 | 0 | 0 |
| [BSL012](rule-contracts/BSL012.md) | UsingHardcodeSecretInformation | 12 | 12 | 2 | 10 | 0 | 0 | 0 | 0 |
| [BSL013](rule-contracts/BSL013.md) | CommentedCode | 11 | 30 | 7 | 0 | 4 | 23 | 0 | 0 |
| [BSL014](rule-contracts/BSL014.md) | LineLength | 75 | 81 | 74 | 0 | 1 | 7 | 0 | 0 |
| [BSL015](rule-contracts/BSL015.md) | NumberOfOptionalParams | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| [BSL016](rule-contracts/BSL016.md) | NonStandardRegion | 63 | 0 | 0 | 0 | 63 | 0 | 0 | 0 |
| [BSL017](rule-contracts/BSL017.md) | CommandModuleExportMethods | 13 | 0 | 0 | 0 | 13 | 0 | 0 | 0 |
| [BSL019](rule-contracts/BSL019.md) | CyclomaticComplexity | 12 | 12 | 10 | 0 | 2 | 2 | 0 | 0 |
| [BSL020](rule-contracts/BSL020.md) | NestedStatements | 5 | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| [BSL022](rule-contracts/BSL022.md) | UsingModalWindows | 26 | 26 | 26 | 0 | 0 | 0 | 0 | 0 |
| [BSL023](rule-contracts/BSL023.md) | UsingServiceTag | 40 | 40 | 40 | 0 | 0 | 0 | 0 | 0 |
| [BSL024](rule-contracts/BSL024.md) | SpaceAtStartComment | 120 | 115 | 104 | 0 | 16 | 11 | 0 | 0 |
| [BSL025](rule-contracts/BSL025.md) | EmptyStatement | 8 | 16 | 7 | 0 | 1 | 9 | 0 | 0 |
| [BSL026](rule-contracts/BSL026.md) | EmptyRegion | 163 | 162 | 162 | 0 | 1 | 0 | 0 | 0 |
| [BSL027](rule-contracts/BSL027.md) | UsingGoto | 21 | 21 | 21 | 0 | 0 | 0 | 0 | 0 |
| [BSL028](rule-contracts/BSL028.md) | MissingCodeTryCatchEx | 15 | 15 | 15 | 0 | 0 | 0 | 0 | 0 |
| [BSL029](rule-contracts/BSL029.md) | MagicNumber | 454 | 444 | 444 | 0 | 10 | 0 | 0 | 0 |
| [BSL030](rule-contracts/BSL030.md) | SemicolonPresence | 65 | 66 | 32 | 8 | 25 | 26 | 0 | 0 |
| [BSL031](rule-contracts/BSL031.md) | NumberOfParams | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| [BSL032](rule-contracts/BSL032.md) | FunctionShouldHaveReturn | 176 | 174 | 172 | 2 | 2 | 0 | 0 | 0 |
| [BSL033](rule-contracts/BSL033.md) | CreateQueryInCycle | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| [BSL035](rule-contracts/BSL035.md) | DuplicateStringLiteral | 58 | 57 | 57 | 0 | 1 | 0 | 0 | 0 |
| [BSL036](rule-contracts/BSL036.md) | IfConditionComplexity | 11 | 11 | 10 | 0 | 1 | 1 | 0 | 0 |
| [BSL039](rule-contracts/BSL039.md) | NestedTernaryOperator | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| [BSL040](rule-contracts/BSL040.md) | UsingThisForm | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL041](rule-contracts/BSL041.md) | DeprecatedMessage | 134 | 133 | 133 | 0 | 1 | 0 | 0 | 0 |
| [BSL042](rule-contracts/BSL042.md) | UnusedLocalMethod | 1006 | 0 | 0 | 0 | 1006 | 0 | 0 | 0 |
| [BSL047](rule-contracts/BSL047.md) | MagicDate | 25 | 25 | 25 | 0 | 0 | 0 | 0 | 0 |
| [BSL051](rule-contracts/BSL051.md) | UnreachableCode | 57 | 43 | 12 | 21 | 24 | 10 | 0 | 0 |
| [BSL052](rule-contracts/BSL052.md) | IdenticalExpressions | 39 | 39 | 35 | 0 | 2 | 2 | 0 | 0 |
| [BSL054](rule-contracts/BSL054.md) | ExportVariables | 20 | 18 | 16 | 0 | 4 | 2 | 0 | 0 |
| [BSL055](rule-contracts/BSL055.md) | ConsecutiveEmptyLines | 72 | 85 | 71 | 1 | 0 | 13 | 0 | 0 |
| [BSL060](rule-contracts/BSL060.md) | DoubleNegatives | 14 | 12 | 12 | 0 | 2 | 0 | 0 | 0 |
| [BSL062](rule-contracts/BSL062.md) | UnusedParameters | 204 | 0 | 0 | 0 | 204 | 0 | 0 | 0 |
| [BSL064](rule-contracts/BSL064.md) | ProcedureReturnsValue | 7 | 8 | 0 | 7 | 0 | 1 | 0 | 0 |
| [BSL065](rule-contracts/BSL065.md) | MissingReturnedValueDescription | 46 | 37 | 37 | 0 | 9 | 0 | 0 | 0 |
| [BSL066](rule-contracts/BSL066.md) | DeprecatedFind | 5 | 4 | 4 | 0 | 1 | 0 | 0 | 0 |
| [BSL077](rule-contracts/BSL077.md) | SelectTopWithoutOrderBy | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| [BSL097](rule-contracts/BSL097.md) | DeprecatedCurrentDate | 11 | 11 | 11 | 0 | 0 | 0 | 0 | 0 |
| [BSL131](rule-contracts/BSL131.md) | DuplicateRegion | 47 | 46 | 45 | 1 | 1 | 0 | 0 | 0 |
| [BSL148](rule-contracts/BSL148.md) | AllFunctionPathMustHaveReturn | 10 | 10 | 7 | 0 | 3 | 3 | 0 | 0 |
| [BSL149](rule-contracts/BSL149.md) | AssignAliasFieldsInQuery | 134 | 125 | 119 | 0 | 15 | 6 | 0 | 0 |
| [BSL150](rule-contracts/BSL150.md) | BadWords | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL151](rule-contracts/BSL151.md) | BeginTransactionBeforeTryCatch | 35 | 35 | 35 | 0 | 0 | 0 | 0 | 0 |
| [BSL152](rule-contracts/BSL152.md) | CachedPublic | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL153](rule-contracts/BSL153.md) | CanonicalSpellingKeywords | 275 | 272 | 272 | 0 | 3 | 0 | 0 | 0 |
| [BSL154](rule-contracts/BSL154.md) | CodeAfterAsyncCall | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL155](rule-contracts/BSL155.md) | CodeBlockBeforeSub | 17 | 12 | 12 | 0 | 5 | 0 | 0 | 0 |
| [BSL156](rule-contracts/BSL156.md) | CodeOutOfRegion | 30 | 0 | 0 | 0 | 30 | 0 | 0 | 0 |
| [BSL157](rule-contracts/BSL157.md) | CommitTransactionOutsideTryCatch | 38 | 42 | 38 | 0 | 0 | 4 | 0 | 0 |
| [BSL158](rule-contracts/BSL158.md) | CommonModuleAssign | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL159](rule-contracts/BSL159.md) | CommonModuleInvalidType | 7 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| [BSL160](rule-contracts/BSL160.md) | CommonModuleMissingAPI | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| [BSL161](rule-contracts/BSL161.md) | CommonModuleNameCached | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL162](rule-contracts/BSL162.md) | CommonModuleNameClient | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL163](rule-contracts/BSL163.md) | CommonModuleNameClientServer | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL164](rule-contracts/BSL164.md) | CommonModuleNameFullAccess | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| [BSL165](rule-contracts/BSL165.md) | CommonModuleNameGlobal | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL166](rule-contracts/BSL166.md) | CommonModuleNameGlobalClient | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL167](rule-contracts/BSL167.md) | CommonModuleNameServerCall | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL168](rule-contracts/BSL168.md) | CommonModuleNameWords | 7 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| [BSL169](rule-contracts/BSL169.md) | CompilationDirectiveLost | 5 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| [BSL170](rule-contracts/BSL170.md) | CompilationDirectiveNeedLess | 200 | 0 | 0 | 0 | 200 | 0 | 0 | 0 |
| [BSL171](rule-contracts/BSL171.md) | CrazyMultilineString | 4 | 7 | 1 | 2 | 1 | 4 | 0 | 0 |
| [BSL172](rule-contracts/BSL172.md) | DataExchangeLoading | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL173](rule-contracts/BSL173.md) | DeletingCollectionItem | 8 | 8 | 8 | 0 | 0 | 0 | 0 | 0 |
| [BSL174](rule-contracts/BSL174.md) | DenyIncompleteValues | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| [BSL175](rule-contracts/BSL175.md) | DeprecatedAttributes8312 | 43 | 33 | 33 | 0 | 10 | 0 | 0 | 0 |
| [BSL176](rule-contracts/BSL176.md) | DeprecatedMethodCall | 52 | 52 | 52 | 0 | 0 | 0 | 0 | 0 |
| [BSL177](rule-contracts/BSL177.md) | DeprecatedMethods8310 | 6 | 0 | 0 | 0 | 6 | 0 | 0 | 0 |
| [BSL178](rule-contracts/BSL178.md) | DeprecatedMethods8317 | 23 | 0 | 0 | 0 | 23 | 0 | 0 | 0 |
| [BSL179](rule-contracts/BSL179.md) | DeprecatedTypeManagedForm | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| [BSL180](rule-contracts/BSL180.md) | DisableSafeMode | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| [BSL181](rule-contracts/BSL181.md) | DuplicatedInsertionIntoCollection | 11 | 21 | 6 | 0 | 5 | 15 | 0 | 0 |
| [BSL182](rule-contracts/BSL182.md) | ExcessiveAutoTestCheck | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL183](rule-contracts/BSL183.md) | ExecuteExternalCode | 22 | 0 | 0 | 0 | 22 | 0 | 0 | 0 |
| [BSL184](rule-contracts/BSL184.md) | ExecuteExternalCodeInCommonModule | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL185](rule-contracts/BSL185.md) | ExternalAppStarting | 22 | 22 | 22 | 0 | 0 | 0 | 0 | 0 |
| [BSL186](rule-contracts/BSL186.md) | ExtraCommas | 15 | 14 | 14 | 0 | 1 | 0 | 0 | 0 |
| [BSL187](rule-contracts/BSL187.md) | FieldsFromJoinsWithoutIsNull | 32 | 29 | 28 | 0 | 4 | 1 | 0 | 0 |
| [BSL188](rule-contracts/BSL188.md) | FileSystemAccess | 61 | 61 | 61 | 0 | 0 | 0 | 0 | 0 |
| [BSL189](rule-contracts/BSL189.md) | ForbiddenMetadataName | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL190](rule-contracts/BSL190.md) | FormDataToValue | 6 | 4 | 4 | 0 | 2 | 0 | 0 | 0 |
| [BSL191](rule-contracts/BSL191.md) | FullOuterJoinQuery | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| [BSL192](rule-contracts/BSL192.md) | FunctionNameStartsWithGet | 6 | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| [BSL193](rule-contracts/BSL193.md) | FunctionOutParameter | 9 | 8 | 8 | 0 | 1 | 0 | 0 | 0 |
| [BSL194](rule-contracts/BSL194.md) | FunctionReturnsSamePrimitive | 5 | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| [BSL195](rule-contracts/BSL195.md) | GetFormMethod | 6 | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| [BSL196](rule-contracts/BSL196.md) | GlobalContextMethodCollision8312 | 20 | 20 | 20 | 0 | 0 | 0 | 0 | 0 |
| [BSL197](rule-contracts/BSL197.md) | IfElseDuplicatedCodeBlock | 9 | 9 | 9 | 0 | 0 | 0 | 0 | 0 |
| [BSL198](rule-contracts/BSL198.md) | IfElseDuplicatedCondition | 6 | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| [BSL199](rule-contracts/BSL199.md) | IfElseIfEndsWithElse | 18 | 18 | 18 | 0 | 0 | 0 | 0 | 0 |
| [BSL200](rule-contracts/BSL200.md) | IncorrectLineBreak | 73 | 73 | 73 | 0 | 0 | 0 | 0 | 0 |
| [BSL201](rule-contracts/BSL201.md) | IncorrectUseLikeInQuery | 20 | 20 | 16 | 4 | 0 | 0 | 0 | 0 |
| [BSL202](rule-contracts/BSL202.md) | IncorrectUseOfStrTemplate | 6 | 12 | 0 | 6 | 0 | 6 | 0 | 0 |
| [BSL203](rule-contracts/BSL203.md) | InternetAccess | 79 | 78 | 78 | 0 | 1 | 0 | 0 | 0 |
| [BSL204](rule-contracts/BSL204.md) | InvalidCharacterInFile | 88 | 88 | 82 | 6 | 0 | 0 | 0 | 0 |
| [BSL205](rule-contracts/BSL205.md) | IsInRoleMethod | 5 | 4 | 4 | 0 | 1 | 0 | 0 | 0 |
| [BSL206](rule-contracts/BSL206.md) | JoinWithSubQuery | 10 | 10 | 10 | 0 | 0 | 0 | 0 | 0 |
| [BSL207](rule-contracts/BSL207.md) | JoinWithVirtualTable | 8 | 9 | 8 | 0 | 0 | 1 | 0 | 0 |
| [BSL208](rule-contracts/BSL208.md) | LatinAndCyrillicSymbolInWord | 29 | 30 | 29 | 0 | 0 | 1 | 0 | 0 |
| [BSL209](rule-contracts/BSL209.md) | LogicalOrInJoinQuerySection | 7 | 8 | 7 | 0 | 0 | 1 | 0 | 0 |
| [BSL210](rule-contracts/BSL210.md) | LogicalOrInTheWhereSectionOfQuery | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| [BSL211](rule-contracts/BSL211.md) | MetadataObjectNameLength | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL212](rule-contracts/BSL212.md) | MissedRequiredParameter | 14 | 15 | 14 | 0 | 0 | 1 | 0 | 0 |
| [BSL213](rule-contracts/BSL213.md) | MissingCommonModuleMethod | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL214](rule-contracts/BSL214.md) | MissingEventSubscriptionHandler | 6 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| [BSL215](rule-contracts/BSL215.md) | MissingParameterDescription | 57 | 53 | 38 | 1 | 18 | 14 | 0 | 0 |
| [BSL216](rule-contracts/BSL216.md) | MissingSpace | 253 | 245 | 238 | 0 | 15 | 7 | 0 | 0 |
| [BSL217](rule-contracts/BSL217.md) | MissingTempStorageDeletion | 5 | 6 | 5 | 0 | 0 | 1 | 0 | 0 |
| [BSL218](rule-contracts/BSL218.md) | MissingTemporaryFileDeletion | 10 | 7 | 7 | 0 | 3 | 0 | 0 | 0 |
| [BSL219](rule-contracts/BSL219.md) | MissingVariablesDescription | 62 | 64 | 61 | 0 | 1 | 3 | 0 | 0 |
| [BSL220](rule-contracts/BSL220.md) | MultilineStringInQuery | 1 | 3 | 1 | 0 | 0 | 2 | 0 | 0 |
| [BSL221](rule-contracts/BSL221.md) | MultilingualStringHasAllDeclaredLanguages | 6 | 6 | 4 | 0 | 2 | 2 | 0 | 0 |
| [BSL222](rule-contracts/BSL222.md) | MultilingualStringUsingWithTemplate | 2 | 4 | 2 | 0 | 0 | 2 | 0 | 0 |
| [BSL223](rule-contracts/BSL223.md) | NestedConstructorsInStructureDeclaration | 15 | 14 | 2 | 12 | 1 | 0 | 0 | 0 |
| [BSL224](rule-contracts/BSL224.md) | NestedFunctionInParameters | 15 | 13 | 13 | 0 | 2 | 0 | 0 | 0 |
| [BSL225](rule-contracts/BSL225.md) | NumberOfValuesInStructureConstructor | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| [BSL226](rule-contracts/BSL226.md) | OSUsersMethod | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| [BSL227](rule-contracts/BSL227.md) | OneStatementPerLine | 9 | 11 | 8 | 0 | 1 | 3 | 0 | 0 |
| [BSL228](rule-contracts/BSL228.md) | OrderOfParams | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| [BSL229](rule-contracts/BSL229.md) | OrdinaryAppSupport | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| [BSL230](rule-contracts/BSL230.md) | PairingBrokenTransaction | 29 | 29 | 0 | 22 | 3 | 3 | 0 | 0 |
| [BSL231](rule-contracts/BSL231.md) | PrivilegedModuleMethodCall | 2 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| [BSL232](rule-contracts/BSL232.md) | ProtectedModule | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL233](rule-contracts/BSL233.md) | PublicMethodsDescription | 6 | 4 | 4 | 0 | 2 | 0 | 0 | 0 |
| [BSL234](rule-contracts/BSL234.md) | QueryNestedFieldsByDot | 47 | 46 | 44 | 0 | 3 | 2 | 0 | 0 |
| [BSL235](rule-contracts/BSL235.md) | QueryParseError | 16 | 12 | 5 | 0 | 11 | 7 | 0 | 0 |
| [BSL236](rule-contracts/BSL236.md) | QueryToMissingMetadata | 0 | 203 | 0 | 0 | 0 | 203 | 0 | 0 |
| [BSL237](rule-contracts/BSL237.md) | RedundantAccessToObject | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL238](rule-contracts/BSL238.md) | RefOveruse | 24 | 23 | 21 | 0 | 3 | 2 | 0 | 0 |
| [BSL239](rule-contracts/BSL239.md) | ReservedParameterNames | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL240](rule-contracts/BSL240.md) | RewriteMethodParameter | 6 | 6 | 0 | 4 | 2 | 2 | 0 | 0 |
| [BSL241](rule-contracts/BSL241.md) | SameMetadataObjectAndChildNames | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL242](rule-contracts/BSL242.md) | ScheduledJobHandler | 7 | 0 | 0 | 0 | 4 | 0 | 0 | 0 |
| [BSL243](rule-contracts/BSL243.md) | SelfInsertion | 2 | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| [BSL244](rule-contracts/BSL244.md) | ServerCallsInFormEvents | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL245](rule-contracts/BSL245.md) | ServerSideExportFormMethod | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL246](rule-contracts/BSL246.md) | SetPermissionsForNewObjects | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL247](rule-contracts/BSL247.md) | SetPrivilegedMode | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| [BSL248](rule-contracts/BSL248.md) | SeveralCompilerDirectives | 11 | 12 | 8 | 2 | 1 | 2 | 0 | 0 |
| [BSL249](rule-contracts/BSL249.md) | StyleElementConstructors | 15 | 23 | 15 | 0 | 0 | 8 | 0 | 0 |
| [BSL250](rule-contracts/BSL250.md) | TempFilesDir | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| [BSL251](rule-contracts/BSL251.md) | TernaryOperatorUsage | 54 | 53 | 53 | 0 | 1 | 0 | 0 | 0 |
| [BSL252](rule-contracts/BSL252.md) | ThisObjectAssign | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| [BSL253](rule-contracts/BSL253.md) | TimeoutsInExternalResources | 41 | 41 | 41 | 0 | 0 | 0 | 0 | 0 |
| [BSL254](rule-contracts/BSL254.md) | TransferringParametersBetweenClientAndServer | 1 | 5 | 1 | 0 | 0 | 4 | 0 | 0 |
| [BSL255](rule-contracts/BSL255.md) | TryNumber | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| [BSL256](rule-contracts/BSL256.md) | Typo | 125 | 155 | 90 | 7 | 28 | 51 | 5 | 0 |
| [BSL257](rule-contracts/BSL257.md) | UnaryPlusInConcatenation | 3 | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| [BSL258](rule-contracts/BSL258.md) | UnionAll | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| [BSL259](rule-contracts/BSL259.md) | UnknownPreprocessorSymbol | 11 | 2 | 1 | 0 | 10 | 1 | 0 | 0 |
| [BSL260](rule-contracts/BSL260.md) | UnsafeFindByCode | 0 | 12 | 0 | 0 | 0 | 12 | 0 | 0 |
| [BSL261](rule-contracts/BSL261.md) | UnsafeSafeModeMethodCall | 8 | 10 | 6 | 0 | 2 | 4 | 0 | 0 |
| [BSL262](rule-contracts/BSL262.md) | UsageWriteLogEvent | 12 | 18 | 12 | 0 | 0 | 6 | 0 | 0 |
| [BSL263](rule-contracts/BSL263.md) | UseLessForEach | 47 | 50 | 47 | 0 | 0 | 3 | 0 | 0 |
| [BSL264](rule-contracts/BSL264.md) | UseSystemInformation | 6 | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| [BSL265](rule-contracts/BSL265.md) | UselessTernaryOperator | 16 | 16 | 16 | 0 | 0 | 0 | 0 | 0 |
| [BSL266](rule-contracts/BSL266.md) | UsingCancelParameter | 7 | 7 | 5 | 2 | 0 | 0 | 0 | 0 |
| [BSL267](rule-contracts/BSL267.md) | UsingExternalCodeTools | 7 | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| [BSL268](rule-contracts/BSL268.md) | UsingFindElementByString | 34 | 35 | 34 | 0 | 0 | 1 | 0 | 0 |
| [BSL269](rule-contracts/BSL269.md) | UsingLikeInQuery | 42 | 42 | 28 | 14 | 0 | 0 | 0 | 0 |
| [BSL271](rule-contracts/BSL271.md) | UsingObjectNotAvailableUnix | 8 | 4 | 4 | 0 | 4 | 0 | 0 | 0 |
| [BSL272](rule-contracts/BSL272.md) | UsingSynchronousCalls | 53 | 0 | 0 | 0 | 53 | 0 | 0 | 0 |
| [BSL273](rule-contracts/BSL273.md) | VirtualTableCallWithoutParameters | 8 | 8 | 7 | 0 | 1 | 1 | 0 | 0 |
| [BSL274](rule-contracts/BSL274.md) | WrongDataPathForFormElements | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 |
| [BSL275](rule-contracts/BSL275.md) | WrongHttpServiceHandler | 3 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| [BSL276](rule-contracts/BSL276.md) | WrongUseFunctionProceedWithCall | 4 | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| [BSL277](rule-contracts/BSL277.md) | WrongUseOfRollbackTransactionMethod | 19 | 19 | 19 | 0 | 0 | 0 | 0 | 0 |
| [BSL278](rule-contracts/BSL278.md) | WrongWebServiceHandler | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| [BSL279](rule-contracts/BSL279.md) | YoLetterUsage | 14 | 14 | 14 | 0 | 0 | 0 | 0 | 0 |
