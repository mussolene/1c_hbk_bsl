# Диагностические правила

<div class="doc-lang doc-lang-ru" markdown="1">

Справочник генерируется из runtime-реестра `onec-hbk-bsl`. Код правила
ведёт на единственную страницу с описанием, примерами, подавлениями и
полным инженерным контрактом.

</div>

<div class="doc-lang doc-lang-en" markdown="1">

This reference is generated from the `onec-hbk-bsl` runtime registry. Every
rule code links to its single page with usage documentation, examples,
suppressions, and the complete engineering contract.

</div>

## Идентификаторы / Identifiers

- `BSL###` — основной стабильный код для вывода, `select`, `ignore`,
  `onec-hbk-bsl.toml`, SARIF/JSON и `// noqa: BSL###`.
- Совместимый псевдоним можно использовать во входной конфигурации и
  комментариях `// BSLLS:<RuleName>-off/on`; вывод всегда использует `BSL###`.
- Нумерация стабильна, но не обязана быть непрерывной.

## Каталог / Catalog

| Code | Compatible alias | Default | Severity | Русское описание | English description | Tags |
|---|---|---:|---|---|---|---|
| [`BSL001`](rule-contracts/BSL001.md) | `ParseError` | Yes | ERROR | Ошибка разбора исходного кода | Source code parse error | syntax |
| [`BSL002`](rule-contracts/BSL002.md) | `MethodSize` | Yes | ERROR | Ограничение на размер метода | Method size | size, brain-overload |
| [`BSL003`](rule-contracts/BSL003.md) | `NonExportMethodsInApiRegion` | Yes | INFORMATION | Неэкспортные методы в областях ПрограммныйИнтерфейс и СлужебныйПрограммныйИнтерфейс | Non export methods in API regions | design, api |
| [`BSL004`](rule-contracts/BSL004.md) | `EmptyCodeBlock` | Yes | ERROR | Пустой блок кода | Empty code block | error-handling |
| [`BSL005`](rule-contracts/BSL005.md) | `UsingHardcodeNetworkAddress` | Yes | WARNING | Хранение ip-адресов в коде | Using hardcode ip addresses in code | security, hardware-related |
| [`BSL006`](rule-contracts/BSL006.md) | `UsingHardcodePath` | Yes | WARNING | Хранение путей к файлам в коде | Using hardcode file paths in code | security, hardware-related |
| [`BSL007`](rule-contracts/BSL007.md) | `UnusedLocalVariable` | Yes | WARNING | Неиспользуемая локальная переменная | Unused local variable | unused |
| [`BSL008`](rule-contracts/BSL008.md) | `TooManyReturns` | Yes | WARNING | Метод не должен содержать много возвратов | Methods should not have too many return statements | brain-overload |
| [`BSL009`](rule-contracts/BSL009.md) | `SelfAssign` | Yes | WARNING | Присвоение переменной самой себе | Variable is assigned to itself | suspicious |
| [`BSL011`](rule-contracts/BSL011.md) | `CognitiveComplexity` | Yes | WARNING | Когнитивная сложность | Cognitive complexity | brain-overload, complexity |
| [`BSL012`](rule-contracts/BSL012.md) | `UsingHardcodeSecretInformation` | Yes | ERROR | Хранение конфиденциальной информации в коде | Storing confidential information in code | security, credentials |
| [`BSL013`](rule-contracts/BSL013.md) | `CommentedCode` | Yes | WARNING | Закомментированный фрагмент кода | Commented out code | unused |
| [`BSL014`](rule-contracts/BSL014.md) | `LineLength` | Yes | INFORMATION | Ограничение на длину строки | Line Length limit | design |
| [`BSL015`](rule-contracts/BSL015.md) | `NumberOfOptionalParams` | Yes | WARNING | Ограничение на количество не обязательных параметров метода | Limit number of optional parameters in method | design, brain-overload |
| [`BSL016`](rule-contracts/BSL016.md) | `NonStandardRegion` | Yes | INFORMATION | Нестандартные разделы модуля | Non-standard region of module | convention |
| [`BSL017`](rule-contracts/BSL017.md) | `CommandModuleExportMethods` | Yes | WARNING | Экспортные методы в модулях команд и общих команд | Export methods in command and general command modules | design |
| [`BSL019`](rule-contracts/BSL019.md) | `CyclomaticComplexity` | Yes | WARNING | Цикломатическая сложность | Cyclomatic complexity | brain-overload, complexity |
| [`BSL020`](rule-contracts/BSL020.md) | `NestedStatements` | Yes | WARNING | Управляющие конструкции не должны быть вложены слишком глубоко | Control flow statements should not be nested too deep | brain-overload |
| [`BSL022`](rule-contracts/BSL022.md) | `UsingModalWindows` | Yes | WARNING | Использование модальных окон | Using modal windows | deprecated, ui |
| [`BSL023`](rule-contracts/BSL023.md) | `UsingServiceTag` | Yes | INFORMATION | Использование служебных тегов | Using service tags | convention |
| [`BSL024`](rule-contracts/BSL024.md) | `SpaceAtStartComment` | Yes | INFORMATION | Пробел в начале комментария | Space at the beginning of the comment | convention, style |
| [`BSL025`](rule-contracts/BSL025.md) | `EmptyStatement` | Yes | WARNING | Пустой оператор | Empty statement | syntax, convention |
| [`BSL026`](rule-contracts/BSL026.md) | `EmptyRegion` | Yes | INFORMATION | Область не должна быть пустой | The region should not be empty | unused |
| [`BSL027`](rule-contracts/BSL027.md) | `UsingGoto` | Yes | WARNING | Оператор "Перейти" не должен использоваться | "goto" statement should not be used | design, brain-overload |
| [`BSL028`](rule-contracts/BSL028.md) | `MissingCodeTryCatchEx` | Yes | INFORMATION | Конструкция "Попытка...Исключение...КонецПопытки" не содержит кода в исключении | Missing code in Raise block in "Try ... Raise ... EndTry" | error-handling, robustness |
| [`BSL029`](rule-contracts/BSL029.md) | `MagicNumber` | Yes | INFORMATION | Магические числа | Magic numbers | convention, readability |
| [`BSL030`](rule-contracts/BSL030.md) | `SemicolonPresence` | Yes | INFORMATION | Выражение должно заканчиваться символом ";" | Statement should end with semicolon symbol ";" | convention, style |
| [`BSL031`](rule-contracts/BSL031.md) | `NumberOfParams` | Yes | WARNING | Ограничение на количество параметров метода | Number of parameters in method | design, brain-overload |
| [`BSL032`](rule-contracts/BSL032.md) | `FunctionShouldHaveReturn` | Yes | WARNING | Функция должна содержать возврат | The function should have return | suspicious, design |
| [`BSL033`](rule-contracts/BSL033.md) | `CreateQueryInCycle` | Yes | WARNING | Выполнение запроса в цикле | Execution query on cycle | performance, brain-overload |
| [`BSL035`](rule-contracts/BSL035.md) | `DuplicateStringLiteral` | Yes | INFORMATION | Повторное использование строкового литерала | Duplicate string literal | convention, readability |
| [`BSL036`](rule-contracts/BSL036.md) | `IfConditionComplexity` | Yes | WARNING | Использование сложных выражений в условии оператора "Если" | Usage of complex expressions in the "If" condition | brain-overload, complexity |
| [`BSL039`](rule-contracts/BSL039.md) | `NestedTernaryOperator` | Yes | WARNING | Вложенный тернарный оператор | Nested ternary operator | brain-overload, readability |
| [`BSL040`](rule-contracts/BSL040.md) | `UsingThisForm` | Yes | INFORMATION | Использование устаревшего свойства "ЭтаФорма" | Using deprecated property "ThisForm" | design, ui |
| [`BSL041`](rule-contracts/BSL041.md) | `DeprecatedMessage` | Yes | WARNING | Ограничение на использование устаревшего метода "Сообщить" | Restriction on the use of deprecated "Message" method | deprecated, ui |
| [`BSL042`](rule-contracts/BSL042.md) | `UnusedLocalMethod` | Yes | WARNING | Неиспользуемый локальный метод | Unused local method | design, api |
| [`BSL047`](rule-contracts/BSL047.md) | `MagicDate` | Yes | INFORMATION | Магические даты | Magic dates | design, date-time |
| [`BSL051`](rule-contracts/BSL051.md) | `UnreachableCode` | Yes | WARNING | Недостижимый код | Unreachable Code | suspicious, dead-code |
| [`BSL052`](rule-contracts/BSL052.md) | `IdenticalExpressions` | Yes | WARNING | Одинаковые выражения слева и справа от "foo" оператора | There are identical sub-expressions to the left and to the right of the "foo" operator | suspicious, logic |
| [`BSL054`](rule-contracts/BSL054.md) | `ExportVariables` | Yes | INFORMATION | Запрет экспортных глобальных переменных модуля | Ban export global module variables | design, global-state |
| [`BSL055`](rule-contracts/BSL055.md) | `ConsecutiveEmptyLines` | Yes | INFORMATION | Подряд идущие пустые строки | Consecutive empty lines | style, formatting |
| [`BSL060`](rule-contracts/BSL060.md) | `DoubleNegatives` | Yes | WARNING | Двойные отрицания | Double negatives | brainoverload, badpractice |
| [`BSL062`](rule-contracts/BSL062.md) | `UnusedParameters` | Yes | WARNING | Неиспользуемый параметр | Unused parameter | unused, design |
| [`BSL064`](rule-contracts/BSL064.md) | `ProcedureReturnsValue` | Yes | ERROR | Процедура не должна возвращать значение | Procedure should not return Value | correctness, design |
| [`BSL065`](rule-contracts/BSL065.md) | `MissingReturnedValueDescription` | Yes | INFORMATION | Отсутствует описание возвращаемого значения функции | Function returned values description is missing | design, documentation |
| [`BSL066`](rule-contracts/BSL066.md) | `DeprecatedFind` | Yes | WARNING | Использование устаревшего метода "Найти" | Using of the deprecated method "Find" | deprecated, compatibility |
| [`BSL077`](rule-contracts/BSL077.md) | `SelectTopWithoutOrderBy` | Yes | WARNING | Использование 'ВЫБРАТЬ ПЕРВЫЕ' без 'УПОРЯДОЧИТЬ ПО' | Using 'SELECT TOP' without 'ORDER BY' | performance, maintainability |
| [`BSL097`](rule-contracts/BSL097.md) | `DeprecatedCurrentDate` | Yes | WARNING | Использование устаревшего метода "ТекущаяДата" | Using of the deprecated method "CurrentDate" | standard, deprecated, unpredictable |
| [`BSL131`](rule-contracts/BSL131.md) | `DuplicateRegion` | Yes | INFORMATION | Повторяющиеся разделы модуля | Duplicate regions | style |
| [`BSL148`](rule-contracts/BSL148.md) | `AllFunctionPathMustHaveReturn` | Yes | ERROR | Все возможные пути выполнения функции должны содержать оператор Возврат | All execution paths of a function must have a Return statement | error-handling, correctness |
| [`BSL149`](rule-contracts/BSL149.md) | `AssignAliasFieldsInQuery` | Yes | INFORMATION | Назначение псевдонимов выбранным полям в запросе | Assigning aliases to selected fields in a query | convention, query |
| [`BSL150`](rule-contracts/BSL150.md) | `BadWords` | Yes | WARNING | Запрещенные слова | Prohibited words | convention |
| [`BSL151`](rule-contracts/BSL151.md) | `BeginTransactionBeforeTryCatch` | Yes | ERROR | Нарушение правил работы с транзакциями для метода 'НачатьТранзакцию' | Violating transaction rules for the 'BeginTransaction' method | standard |
| [`BSL152`](rule-contracts/BSL152.md) | `CachedPublic` | Yes | WARNING | Кеширование программного интерфейса | Cached public methods | design, performance |
| [`BSL153`](rule-contracts/BSL153.md) | `CanonicalSpellingKeywords` | Yes | INFORMATION | Каноническое написание ключевых слов | Canonical keyword writing | convention, style |
| [`BSL154`](rule-contracts/BSL154.md) | `CodeAfterAsyncCall` | Yes | WARNING | После вызова асинхронного метода есть строки кода | Lines of code after the asynchronous method call | async, correctness |
| [`BSL155`](rule-contracts/BSL155.md) | `CodeBlockBeforeSub` | Yes | ERROR | Определения методов должны размещаться перед операторами тела модуля | Method definitions must be placed before the module body operators | error |
| [`BSL156`](rule-contracts/BSL156.md) | `CodeOutOfRegion` | Yes | INFORMATION | Код расположен вне области | Code out of region | convention, structure |
| [`BSL157`](rule-contracts/BSL157.md) | `CommitTransactionOutsideTryCatch` | Yes | ERROR | Нарушение правил работы с транзакциями для метода 'ЗафиксироватьТранзакцию' | Violating transaction rules for the 'CommitTransaction' method | transaction, error-handling |
| [`BSL158`](rule-contracts/BSL158.md) | `CommonModuleAssign` | Yes | ERROR | Присвоение общему модулю | CommonModuleAssign | correctness, module |
| [`BSL159`](rule-contracts/BSL159.md) | `CommonModuleInvalidType` | Yes | ERROR | Общий модуль недопустимого типа | Common module invalid type | design, module |
| [`BSL160`](rule-contracts/BSL160.md) | `CommonModuleMissingAPI` | Yes | INFORMATION | Общий модуль должен иметь программный интерфейс | Common module should have a programming interface | design, module, api |
| [`BSL161`](rule-contracts/BSL161.md) | `CommonModuleNameCached` | Yes | INFORMATION | Пропущен постфикс "ПовтИсп" | Missed postfix "Cached" | convention, naming, module |
| [`BSL162`](rule-contracts/BSL162.md) | `CommonModuleNameClient` | Yes | INFORMATION | Пропущен постфикс "Клиент" | Missed postfix "Client" | convention, naming, module |
| [`BSL163`](rule-contracts/BSL163.md) | `CommonModuleNameClientServer` | Yes | INFORMATION | Пропущен постфикс "КлиентСервер" | Missed postfix "ClientServer" | convention, naming, module |
| [`BSL164`](rule-contracts/BSL164.md) | `CommonModuleNameFullAccess` | Yes | INFORMATION | Пропущен постфикс "ПолныеПрава" | Missed postfix "FullAccess" | convention, naming, module |
| [`BSL165`](rule-contracts/BSL165.md) | `CommonModuleNameGlobal` | Yes | INFORMATION | Пропущен постфикс "Глобальный" | Missed postfix "Global" | convention, naming, module |
| [`BSL166`](rule-contracts/BSL166.md) | `CommonModuleNameGlobalClient` | Yes | INFORMATION | Глобальный модуль с постфиксом "Клиент" | Global module with postfix "Client" | convention, naming, module |
| [`BSL167`](rule-contracts/BSL167.md) | `CommonModuleNameServerCall` | Yes | INFORMATION | Пропущен постфикс "ВызовСервера" | Missed postfix "ServerCall" | convention, naming, module |
| [`BSL168`](rule-contracts/BSL168.md) | `CommonModuleNameWords` | Yes | INFORMATION | Нерекомендуемое имя общего модуля | Unrecommended common module name | convention, naming, module |
| [`BSL169`](rule-contracts/BSL169.md) | `CompilationDirectiveLost` | Yes | ERROR | Директивы компиляции методов | Methods compilation directive | correctness, directive |
| [`BSL170`](rule-contracts/BSL170.md) | `CompilationDirectiveNeedLess` | Yes | INFORMATION | Лишняя директива компиляции | Needless compilation directive | redundant, directive |
| [`BSL171`](rule-contracts/BSL171.md) | `CrazyMultilineString` | Yes | INFORMATION | Безумные многострочные литералы | Crazy multiline literals | style, readability |
| [`BSL172`](rule-contracts/BSL172.md) | `DataExchangeLoading` | Yes | WARNING | Отсутствует проверка признака ОбменДанными.Загрузка в обработчике событий объекта | There is no check for the attribute DataExchange.Load in the object's event handler | correctness, data-exchange |
| [`BSL173`](rule-contracts/BSL173.md) | `DeletingCollectionItem` | Yes | ERROR | Удаление элемента при обходе коллекции посредством оператора "Для каждого ... Из ... Цикл" | Deleting an item when iterating through collection using the operator "For each ... In ... Do" | correctness, loop |
| [`BSL174`](rule-contracts/BSL174.md) | `DenyIncompleteValues` | Yes | WARNING | Запрет незаполненных значений у измерений регистров | Deny incomplete values for dimensions | transaction, error-handling |
| [`BSL175`](rule-contracts/BSL175.md) | `DeprecatedAttributes8312` | Yes | INFORMATION | Устаревшие объекты платформы 8.3.12 | Deprecated 8.3.12 platform features. | deprecated, compatibility |
| [`BSL176`](rule-contracts/BSL176.md) | `DeprecatedMethodCall` | Yes | INFORMATION | Устаревшие методы не должны использоваться | Deprecated methods should not be used | deprecated |
| [`BSL177`](rule-contracts/BSL177.md) | `DeprecatedMethods8310` | Yes | INFORMATION | Использование устаревшего метода клиентского приложения | Deprecated client application method. | deprecated, compatibility |
| [`BSL178`](rule-contracts/BSL178.md) | `DeprecatedMethods8317` | Yes | INFORMATION | Использование устаревших глобальных методов платформы 8.3.17 | Using of deprecated platform 8.3.17 global methods | deprecated, compatibility |
| [`BSL179`](rule-contracts/BSL179.md) | `DeprecatedTypeManagedForm` | Yes | WARNING | Устаревшее использование типа "УправляемаяФорма" | Deprecated ManagedForm type | deprecated, ui |
| [`BSL180`](rule-contracts/BSL180.md) | `DisableSafeMode` | Yes | WARNING | Отключение безопасного режима | Disable safe mode | security |
| [`BSL181`](rule-contracts/BSL181.md) | `DuplicatedInsertionIntoCollection` | Yes | WARNING | Повторное добавление/вставка значений в коллекцию | Duplicate adding or pasting a value to a collection | correctness, suspicious |
| [`BSL182`](rule-contracts/BSL182.md) | `ExcessiveAutoTestCheck` | Yes | INFORMATION | Избыточная проверка параметра АвтоТест | Excessive AutoTest Check | testing |
| [`BSL183`](rule-contracts/BSL183.md) | `ExecuteExternalCode` | Yes | WARNING | Выполнение произвольного кода на сервере | Executing of external code on the server | security |
| [`BSL184`](rule-contracts/BSL184.md) | `ExecuteExternalCodeInCommonModule` | Yes | WARNING | Выполнение произвольного кода в общем модуле на сервере | Executing of external code in a common module on the server | security, module |
| [`BSL185`](rule-contracts/BSL185.md) | `ExternalAppStarting` | Yes | WARNING | Запуск внешних приложений | External applications starting | security |
| [`BSL186`](rule-contracts/BSL186.md) | `ExtraCommas` | Yes | WARNING | Запятые без указания параметра в конце вызова метода | Commas without a parameter at the end of a method call | syntax, style |
| [`BSL187`](rule-contracts/BSL187.md) | `FieldsFromJoinsWithoutIsNull` | Yes | WARNING | Отсутствие проверки на NULL для полей из присоединяемых таблиц | No NULL checks for fields from joined tables | query, correctness |
| [`BSL188`](rule-contracts/BSL188.md) | `FileSystemAccess` | Yes | WARNING | Доступ к файловой системе | File system access | security, compatibility |
| [`BSL189`](rule-contracts/BSL189.md) | `ForbiddenMetadataName` | Yes | WARNING | Объекту метаданных присвоено запрещенное имя | Metadata object has a forbidden name | naming, convention |
| [`BSL190`](rule-contracts/BSL190.md) | `FormDataToValue` | Yes | WARNING | Использование метода ДанныеФормыВЗначение | FormDataToValue method call | performance, ui |
| [`BSL191`](rule-contracts/BSL191.md) | `FullOuterJoinQuery` | Yes | WARNING | Использование конструкции "ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ" в запросах | Using of "FULL OUTER JOIN" in queries | query, design |
| [`BSL192`](rule-contracts/BSL192.md) | `FunctionNameStartsWithGet` | Yes | INFORMATION | Имя функции не должно начинаться с "Получить" | Function name shouldn't start with "Получить" | naming, convention |
| [`BSL193`](rule-contracts/BSL193.md) | `FunctionOutParameter` | Yes | WARNING | Исходящий параметр функции | Out function parameter | design |
| [`BSL194`](rule-contracts/BSL194.md) | `FunctionReturnsSamePrimitive` | Yes | ERROR | Функция всегда возвращает одно и то же примитивное значение | The function always returns the same primitive value | redundant, design |
| [`BSL195`](rule-contracts/BSL195.md) | `GetFormMethod` | Yes | WARNING | Использование метода ПолучитьФорму | GetForm method call | deprecated, ui |
| [`BSL196`](rule-contracts/BSL196.md) | `GlobalContextMethodCollision8312` | Yes | ERROR | Конфликт имен методов с методами глобального контекста | Global context method names collision | correctness, compatibility |
| [`BSL197`](rule-contracts/BSL197.md) | `IfElseDuplicatedCodeBlock` | Yes | WARNING | Повторяющиеся блоки кода в синтаксической конструкции Если...Тогда...ИначеЕсли... | Duplicated code blocks in If...Then...ElseIf... statements | suspicious, duplicate |
| [`BSL198`](rule-contracts/BSL198.md) | `IfElseDuplicatedCondition` | Yes | WARNING | Повторяющиеся условия в синтаксической конструкции Если...Тогда...ИначеЕсли... | Duplicated conditions in If...Then...ElseIf... statements | suspicious, correctness |
| [`BSL199`](rule-contracts/BSL199.md) | `IfElseIfEndsWithElse` | Yes | INFORMATION | Использование синтаксической конструкции Если...Тогда...ИначеЕсли... | Else...The...ElseIf... statement should end with Else branch | design, robustness |
| [`BSL200`](rule-contracts/BSL200.md) | `IncorrectLineBreak` | Yes | INFORMATION | Неправильный перенос выражения | Incorrect expression line break | style, convention |
| [`BSL201`](rule-contracts/BSL201.md) | `IncorrectUseLikeInQuery` | Yes | WARNING | Некорректное использование 'ПОДОБНО' | Incorrect use of 'LIKE' | query, correctness |
| [`BSL202`](rule-contracts/BSL202.md) | `IncorrectUseOfStrTemplate` | Yes | ERROR | Неверное использование "СтрШаблон" | Incorrect use of "StrTemplate" | correctness |
| [`BSL203`](rule-contracts/BSL203.md) | `InternetAccess` | Yes | WARNING | Обращение к Интернет-ресурсам | Referring to Internet resources | security |
| [`BSL204`](rule-contracts/BSL204.md) | `InvalidCharacterInFile` | Yes | WARNING | Недопустимый символ | Invalid character | correctness, encoding |
| [`BSL205`](rule-contracts/BSL205.md) | `IsInRoleMethod` | Yes | WARNING | Использование метода РольДоступна | IsInRole global method call | security, access-control |
| [`BSL206`](rule-contracts/BSL206.md) | `JoinWithSubQuery` | Yes | WARNING | Соединение с вложенными запросами | Join with sub queries | query, performance |
| [`BSL207`](rule-contracts/BSL207.md) | `JoinWithVirtualTable` | Yes | WARNING | Соединение с виртуальными таблицами | Join with virtual table | query, performance |
| [`BSL208`](rule-contracts/BSL208.md) | `LatinAndCyrillicSymbolInWord` | Yes | WARNING | Смешивание латинских и кириллических символов в одном идентификаторе | Mixing Latin and Cyrillic characters in one identifier | suspicious, naming |
| [`BSL209`](rule-contracts/BSL209.md) | `LogicalOrInJoinQuerySection` | Yes | WARNING | Логическое 'ИЛИ' в соединениях запроса | Logical 'OR' in 'JOIN' query section | query, performance |
| [`BSL210`](rule-contracts/BSL210.md) | `LogicalOrInTheWhereSectionOfQuery` | Yes | WARNING | Использование логического "ИЛИ" в секции "ГДЕ" запроса | Using a logical "OR" in the "WHERE" section of a query | query, performance, standard |
| [`BSL211`](rule-contracts/BSL211.md) | `MetadataObjectNameLength` | Yes | WARNING | Имена объектов метаданных не должны превышать допустимой длины наименования | Metadata object names must not exceed the allowed length | naming, convention |
| [`BSL212`](rule-contracts/BSL212.md) | `MissedRequiredParameter` | Yes | ERROR | Пропущен обязательный параметр метода | Missed a required method parameter | correctness |
| [`BSL213`](rule-contracts/BSL213.md) | `MissingCommonModuleMethod` | Yes | ERROR | Обращение к отсутствующему методу общего модуля | Referencing a missing common module method | correctness, module |
| [`BSL214`](rule-contracts/BSL214.md) | `MissingEventSubscriptionHandler` | Yes | ERROR | Отсутствует обработчик подписки на событие | Event subscription handler missing | correctness, events |
| [`BSL215`](rule-contracts/BSL215.md) | `MissingParameterDescription` | Yes | INFORMATION | Отсутствует описание параметров метода | Method parameters description are missing | documentation, api |
| [`BSL216`](rule-contracts/BSL216.md) | `MissingSpace` | Yes | INFORMATION | Пропущены пробелы слева или справа от операторов `+ - * / = % < > <> <= >=`, от ключевых слов, а так же справа от `,` и `;` | Missing spaces to the left or right of operators + - * / = % < > <> <= >=, keywords, and also to the right of , and ; | style, convention |
| [`BSL217`](rule-contracts/BSL217.md) | `MissingTempStorageDeletion` | Yes | WARNING | Отсутствует удаление данных из временного хранилища после использования | Missing temporary storage data deletion after using | resource-management, memory |
| [`BSL218`](rule-contracts/BSL218.md) | `MissingTemporaryFileDeletion` | Yes | WARNING | Отсутствует удаление временного файла после использования | Missing temporary file deletion after using | resource-management |
| [`BSL219`](rule-contracts/BSL219.md) | `MissingVariablesDescription` | Yes | INFORMATION | Все объявления переменных должны иметь описание | All variables declarations must have a description | documentation, convention |
| [`BSL220`](rule-contracts/BSL220.md) | `MultilineStringInQuery` | Yes | INFORMATION | Многострочный литерал в запросе | Multi-line literal in query | query, style |
| [`BSL221`](rule-contracts/BSL221.md) | `MultilingualStringHasAllDeclaredLanguages` | Yes | WARNING | Есть локализованный текст для всех заявленных в конфигурации языков | There is a localized text for all languages declared in the configuration | localization |
| [`BSL222`](rule-contracts/BSL222.md) | `MultilingualStringUsingWithTemplate` | Yes | INFORMATION | Частично локализованный текст используется в функции СтрШаблон | Partially localized text is used in the StrTemplate function | localization, style |
| [`BSL223`](rule-contracts/BSL223.md) | `NestedConstructorsInStructureDeclaration` | Yes | INFORMATION | Использование конструкторов с параметрами при объявлении структуры | Nested constructors with parameters in structure declaration | readability, design |
| [`BSL224`](rule-contracts/BSL224.md) | `NestedFunctionInParameters` | Yes | INFORMATION | Инициализация параметров методов и конструкторов вызовом вложенных методов | Initialization of method and constructor parameters by calling nested methods | readability, brain-overload |
| [`BSL225`](rule-contracts/BSL225.md) | `NumberOfValuesInStructureConstructor` | Yes | INFORMATION | Ограничение на количество значений свойств, передаваемых в конструктор структуры | Limit on the number of property values passed to the structure constructor | design, readability |
| [`BSL226`](rule-contracts/BSL226.md) | `OSUsersMethod` | Yes | WARNING | Использование метода ПользователиОС | Using method OSUsers | security |
| [`BSL227`](rule-contracts/BSL227.md) | `OneStatementPerLine` | Yes | INFORMATION | Одно выражение в одной строке | One statement per line | style, convention |
| [`BSL228`](rule-contracts/BSL228.md) | `OrderOfParams` | Yes | WARNING | Порядок параметров метода | Order of Parameters in method | design, convention |
| [`BSL229`](rule-contracts/BSL229.md) | `OrdinaryAppSupport` | Yes | WARNING | Поддержка обычного приложения | Ordinary application support | compatibility, ui |
| [`BSL230`](rule-contracts/BSL230.md) | `PairingBrokenTransaction` | Yes | ERROR | Нарушение парности использования методов "НачатьТранзакцию()" и "ЗафиксироватьТранзакцию()" / "ОтменитьТранзакцию()" | Violation of pairing using methods "BeginTransaction()" & "CommitTransaction()" / "RollbackTransaction()" | transaction, correctness |
| [`BSL231`](rule-contracts/BSL231.md) | `PrivilegedModuleMethodCall` | Yes | WARNING | Обращение к методам привилегированных модулей | Accessing privileged module methods | security, access-control |
| [`BSL232`](rule-contracts/BSL232.md) | `ProtectedModule` | Yes | INFORMATION | Защищенные модули | Protected modules | design |
| [`BSL233`](rule-contracts/BSL233.md) | `PublicMethodsDescription` | Yes | INFORMATION | Все методы программного интерфейса должны иметь описание | All public methods must have a description | documentation, api |
| [`BSL234`](rule-contracts/BSL234.md) | `QueryNestedFieldsByDot` | Yes | WARNING | Разыменование ссылочных полей запроса через точку | Getting objects nested fields data by dot in database query text | query, performance |
| [`BSL235`](rule-contracts/BSL235.md) | `QueryParseError` | Yes | WARNING | Ошибка разбора текста запроса | Query text parsing error | query, correctness |
| [`BSL236`](rule-contracts/BSL236.md) | `QueryToMissingMetadata` | Yes | ERROR | Обращение к несуществующим метаданным в запросе | Using non-existent metadata in the query | query, correctness |
| [`BSL237`](rule-contracts/BSL237.md) | `RedundantAccessToObject` | Yes | INFORMATION | Избыточное обращение к объекту | Redundant access to an object | redundant, performance |
| [`BSL238`](rule-contracts/BSL238.md) | `RefOveruse` | Yes | INFORMATION | Избыточное использование "Ссылка" в запросе | Overuse "Reference" in a query | performance, readability |
| [`BSL239`](rule-contracts/BSL239.md) | `ReservedParameterNames` | Yes | WARNING | Зарезервированные имена параметров | Reserved parameter names | naming, suspicious |
| [`BSL240`](rule-contracts/BSL240.md) | `RewriteMethodParameter` | Yes | WARNING | Перезапись параметров метода | Rewrite method parameter | suspicious, correctness |
| [`BSL241`](rule-contracts/BSL241.md) | `SameMetadataObjectAndChildNames` | Yes | ERROR | Совпадает имя объекта метаданного и его дочернего | Same metadata object and child name | naming, design |
| [`BSL242`](rule-contracts/BSL242.md) | `ScheduledJobHandler` | Yes | ERROR | Обработчик регламентного задания | Scheduled job handler | correctness, scheduled-jobs |
| [`BSL243`](rule-contracts/BSL243.md) | `SelfInsertion` | Yes | ERROR | Вставка коллекции в саму себя | Insert a collection into itself | correctness, suspicious |
| [`BSL244`](rule-contracts/BSL244.md) | `ServerCallsInFormEvents` | Yes | ERROR | Серверные вызовы в событиях форм | Server calls in form events | correctness, ui, performance |
| [`BSL245`](rule-contracts/BSL245.md) | `ServerSideExportFormMethod` | Yes | WARNING | Серверный экспортный метод формы | Server-side export form method | correctness, ui |
| [`BSL246`](rule-contracts/BSL246.md) | `SetPermissionsForNewObjects` | Yes | ERROR | Флажок «Устанавливать права для новых объектов» должен быть установлен только у роли ПолныеПрава | The check box «Set permissions for new objects» should only be selected for the FullAccess role | security, access-control |
| [`BSL247`](rule-contracts/BSL247.md) | `SetPrivilegedMode` | Yes | WARNING | Использование привилегированного режима | Using privileged mode | security |
| [`BSL248`](rule-contracts/BSL248.md) | `SeveralCompilerDirectives` | Yes | ERROR | Ошибочное указание нескольких директив компиляции | Erroneous indication of several compilation directives | correctness, directive |
| [`BSL249`](rule-contracts/BSL249.md) | `StyleElementConstructors` | Yes | ERROR | Конструктор элемента стиля | Style element constructor | ui, design |
| [`BSL250`](rule-contracts/BSL250.md) | `TempFilesDir` | Yes | WARNING | Вызов функции КаталогВременныхФайлов() | TempFilesDir() method call | standard, badpractice |
| [`BSL251`](rule-contracts/BSL251.md) | `TernaryOperatorUsage` | Yes | INFORMATION | Использование тернарного оператора | Ternary operator usage | style, readability |
| [`BSL252`](rule-contracts/BSL252.md) | `ThisObjectAssign` | Yes | ERROR | Присвоение значения свойству ЭтотОбъект | ThisObject assign | correctness, suspicious |
| [`BSL253`](rule-contracts/BSL253.md) | `TimeoutsInExternalResources` | Yes | WARNING | Таймауты при работе с внешними ресурсами | Timeouts working with external resources | robustness, performance |
| [`BSL254`](rule-contracts/BSL254.md) | `TransferringParametersBetweenClientAndServer` | Yes | WARNING | Передача параметров между клиентом и сервером | Transferring parameters between the client and the server | performance, design |
| [`BSL255`](rule-contracts/BSL255.md) | `TryNumber` | Yes | WARNING | Приведение к числу в попытке | Cast to number of try catch block | error-handling, suspicious |
| [`BSL256`](rule-contracts/BSL256.md) | `Typo` | Yes | INFORMATION | Опечатка | Typo | convention |
| [`BSL257`](rule-contracts/BSL257.md) | `UnaryPlusInConcatenation` | Yes | ERROR | Унарный плюс в конкатенации строк | Unary Plus sign in string concatenation | suspicious, brainoverload |
| [`BSL258`](rule-contracts/BSL258.md) | `UnionAll` | Yes | WARNING | Использование ключевого слова "ОБЪЕДИНИТЬ" в запросах | Using keyword "UNION" in queries | query, performance |
| [`BSL259`](rule-contracts/BSL259.md) | `UnknownPreprocessorSymbol` | Yes | WARNING | Неизвестный символ препроцессора | Unknown preprocessor symbol | correctness, directive |
| [`BSL260`](rule-contracts/BSL260.md) | `UnsafeFindByCode` | Yes | WARNING | Небезопасное использование метода НайтиПоКоду() | Unsafe FindByCode() method usage | correctness, robustness |
| [`BSL261`](rule-contracts/BSL261.md) | `UnsafeSafeModeMethodCall` | Yes | WARNING | Небезопасное использование функции БезопасныйРежим() | Unsafe SafeMode method call | security, correctness |
| [`BSL262`](rule-contracts/BSL262.md) | `UsageWriteLogEvent` | Yes | INFORMATION | Неверное использование метода "ЗаписьЖурналаРегистрации" | Incorrect use of the method "WriteLogEvent" | standard, badpractice |
| [`BSL263`](rule-contracts/BSL263.md) | `UseLessForEach` | Yes | WARNING | Бесполезный перебор коллекции | Useless collection iteration | redundant, suspicious |
| [`BSL264`](rule-contracts/BSL264.md) | `UseSystemInformation` | Yes | WARNING | Использование системной информации | Use of system information | security |
| [`BSL265`](rule-contracts/BSL265.md) | `UselessTernaryOperator` | Yes | INFORMATION | Бесполезный тернарный оператор | Useless ternary operator | redundant, readability |
| [`BSL266`](rule-contracts/BSL266.md) | `UsingCancelParameter` | Yes | WARNING | Работа с параметром "Отказ" | Using parameter "Cancel" | correctness, events |
| [`BSL267`](rule-contracts/BSL267.md) | `UsingExternalCodeTools` | Yes | ERROR | Использование возможностей выполнения внешнего кода | Using external code tools | standard, design |
| [`BSL268`](rule-contracts/BSL268.md) | `UsingFindElementByString` | Yes | WARNING | Использование методов "НайтиПоНаименованию", "НайтиПоКоду" и "НайтиПоНомеру" | Using FindByName, FindByCode and FindByNumber | performance |
| [`BSL269`](rule-contracts/BSL269.md) | `UsingLikeInQuery` | Yes | INFORMATION | Использование 'ПОДОБНО' в запросе | Using 'LIKE' in query | query, performance |
| [`BSL271`](rule-contracts/BSL271.md) | `UsingObjectNotAvailableUnix` | Yes | WARNING | Использование объектов недоступных в Unix системах | Using unavailable in Unix objects | compatibility |
| [`BSL272`](rule-contracts/BSL272.md) | `UsingSynchronousCalls` | Yes | WARNING | Использование синхронных вызовов | Using synchronous calls | performance, ui |
| [`BSL273`](rule-contracts/BSL273.md) | `VirtualTableCallWithoutParameters` | Yes | WARNING | Обращение к виртуальной таблице без параметров | Virtual table call without parameters | query, performance |
| [`BSL274`](rule-contracts/BSL274.md) | `WrongDataPathForFormElements` | Yes | ERROR | У полей формы не указан путь к данным | Form fields do not have a data path | correctness, ui |
| [`BSL275`](rule-contracts/BSL275.md) | `WrongHttpServiceHandler` | Yes | ERROR | Неверно задан обработчик метода http-сервиса | Missing handler for http service | correctness, http |
| [`BSL276`](rule-contracts/BSL276.md) | `WrongUseFunctionProceedWithCall` | Yes | ERROR | Некорректное использование функции ПродолжитьВызов() | Wrong use of ProceedWithCall function | correctness, extensions |
| [`BSL277`](rule-contracts/BSL277.md) | `WrongUseOfRollbackTransactionMethod` | Yes | ERROR | Некорректное использование метода ОтменитьТранзакцию() | Not recommended using of RollbackTransaction method | transaction, error-handling |
| [`BSL278`](rule-contracts/BSL278.md) | `WrongWebServiceHandler` | Yes | ERROR | Неверно задан обработчик операции web-сервиса | Wrong handler for web service | correctness, web-service |
| [`BSL279`](rule-contracts/BSL279.md) | `YoLetterUsage` | Yes | INFORMATION | Использование буквы "ё" в текстах модулей | Using Russian character "yo" ("ё") in code | style, convention |

## Сопровождение / Maintenance

После изменения `RULE_METADATA`, `RULE_DESCRIPTIONS_RU` или поведения
правил обновите индекс и генерируемые заголовки страниц:

```bash
./.venv/bin/python scripts/build_diagnostic_rules_doc.py
```
