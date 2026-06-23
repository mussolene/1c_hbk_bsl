# Diagnostic Rules

This reference is generated from the `onec-hbk-bsl` runtime registry.
It is the product-facing source for rule identifiers used by CLI, config,
LSP, MCP, SARIF/JSON output, and suppression comments.

## Identifiers

- `BSL###` is the stable `onec-hbk-bsl` rule code used in diagnostics output,
  `--select`, `--ignore`, `onec-hbk-bsl.toml`, and `// noqa: BSL###`.
- `Compatible key` is the stable diagnostic alias accepted for compatibility
  with existing BSL projects, such as `LineLength` or `ConsecutiveEmptyLines`.
- CLI and config accept both forms, but output uses `BSL###`.
- Rule numbering is stable but not continuous. Missing numbers, for example
  `BSL053`, are not valid rules unless they appear in this table.
- Unknown rule codes or compatible keys are configuration errors.

## Справочник Правил

| Code | Compatible key | Default | Severity | Русское описание | English description | Tags |
|---|---|---:|---|---|---|---|
| `BSL001` | `ParseError` | Yes | ERROR | Ошибка разбора исходного кода | Source code parse error | syntax |
| `BSL002` | `MethodSize` | Yes | ERROR | Ограничение на размер метода | Method size | size, brain-overload |
| `BSL003` | `NonExportMethodsInApiRegion` | Yes | INFORMATION | Неэкспортные методы в областях ПрограммныйИнтерфейс и СлужебныйПрограммныйИнтерфейс | Non export methods in API regions | design, api |
| `BSL004` | `EmptyCodeBlock` | Yes | ERROR | Пустой блок кода | Empty code block | error-handling |
| `BSL005` | `UsingHardcodeNetworkAddress` | Yes | WARNING | Хранение ip-адресов в коде | Using hardcode ip addresses in code | security, hardware-related |
| `BSL006` | `UsingHardcodePath` | Yes | WARNING | Хранение путей к файлам в коде | Using hardcode file paths in code | security, hardware-related |
| `BSL007` | `UnusedLocalVariable` | Yes | WARNING | Неиспользуемая локальная переменная | Unused local variable | unused |
| `BSL008` | `TooManyReturns` | Yes | WARNING | Метод не должен содержать много возвратов | Methods should not have too many return statements | brain-overload |
| `BSL009` | `SelfAssign` | Yes | WARNING | Присвоение переменной самой себе | Variable is assigned to itself | suspicious |
| `BSL011` | `CognitiveComplexity` | Yes | WARNING | Когнитивная сложность | Cognitive complexity | brain-overload, complexity |
| `BSL012` | `UsingHardcodeSecretInformation` | Yes | ERROR | Хранение конфиденциальной информации в коде | Storing confidential information in code | security, credentials |
| `BSL013` | `CommentedCode` | Yes | WARNING | Закомментированный фрагмент кода | Commented out code | unused |
| `BSL014` | `LineLength` | Yes | INFORMATION | Ограничение на длину строки | Line Length limit | design |
| `BSL015` | `NumberOfOptionalParams` | Yes | WARNING | Ограничение на количество не обязательных параметров метода | Limit number of optional parameters in method | design, brain-overload |
| `BSL016` | `NonStandardRegion` | Yes | INFORMATION | Нестандартные разделы модуля | Non-standard region of module | convention |
| `BSL017` | `CommandModuleExportMethods` | Yes | WARNING | Экспортные методы в модулях команд и общих команд | Export methods in command and general command modules | design |
| `BSL019` | `CyclomaticComplexity` | Yes | WARNING | Цикломатическая сложность | Cyclomatic complexity | brain-overload, complexity |
| `BSL020` | `NestedStatements` | Yes | WARNING | Управляющие конструкции не должны быть вложены слишком глубоко | Control flow statements should not be nested too deep | brain-overload |
| `BSL022` | `UsingModalWindows` | Yes | WARNING | Использование модальных окон | Using modal windows | deprecated, ui |
| `BSL023` | `UsingServiceTag` | Yes | INFORMATION | Использование служебных тегов | Using service tags | convention |
| `BSL024` | `SpaceAtStartComment` | Yes | INFORMATION | Пробел в начале комментария | Space at the beginning of the comment | convention, style |
| `BSL025` | `EmptyStatement` | Yes | WARNING | Пустой оператор | Empty statement | syntax, convention |
| `BSL026` | `EmptyRegion` | Yes | INFORMATION | Область не должна быть пустой | The region should not be empty | unused |
| `BSL027` | `UsingGoto` | Yes | WARNING | Оператор "Перейти" не должен использоваться | "goto" statement should not be used | design, brain-overload |
| `BSL028` | `MissingCodeTryCatchEx` | Yes | INFORMATION | Конструкция "Попытка...Исключение...КонецПопытки" не содержит кода в исключении | Missing code in Raise block in "Try ... Raise ... EndTry" | error-handling, robustness |
| `BSL029` | `MagicNumber` | Yes | INFORMATION | Магические числа | Magic numbers | convention, readability |
| `BSL030` | `SemicolonPresence` | Yes | INFORMATION | Выражение должно заканчиваться символом ";" | Statement should end with semicolon symbol ";" | convention, style |
| `BSL031` | `NumberOfParams` | Yes | WARNING | Ограничение на количество параметров метода | Number of parameters in method | design, brain-overload |
| `BSL032` | `FunctionShouldHaveReturn` | Yes | WARNING | Функция должна содержать возврат | The function should have return | suspicious, design |
| `BSL033` | `CreateQueryInCycle` | Yes | WARNING | Выполнение запроса в цикле | Execution query on cycle | performance, brain-overload |
| `BSL035` | `DuplicateStringLiteral` | Yes | INFORMATION | Повторное использование строкового литерала | Duplicate string literal | convention, readability |
| `BSL036` | `IfConditionComplexity` | Yes | WARNING | Использование сложных выражений в условии оператора "Если" | Usage of complex expressions in the "If" condition | brain-overload, complexity |
| `BSL039` | `NestedTernaryOperator` | Yes | WARNING | Вложенный тернарный оператор | Nested ternary operator | brain-overload, readability |
| `BSL040` | `UsingThisForm` | Yes | INFORMATION | Использование устаревшего свойства "ЭтаФорма" | Using deprecated property "ThisForm" | design, ui |
| `BSL041` | `DeprecatedMessage` | Yes | WARNING | Ограничение на использование устаревшего метода "Сообщить" | Restriction on the use of deprecated "Message" method | deprecated, ui |
| `BSL042` | `UnusedLocalMethod` | Yes | WARNING | Неиспользуемый локальный метод | Unused local method | design, api |
| `BSL047` | `MagicDate` | Yes | INFORMATION | Магические даты | Magic dates | design, date-time |
| `BSL051` | `UnreachableCode` | Yes | WARNING | Недостижимый код | Unreachable Code | suspicious, dead-code |
| `BSL052` | `IdenticalExpressions` | Yes | WARNING | Одинаковые выражения слева и справа от "foo" оператора | There are identical sub-expressions to the left and to the right of the "foo" operator | suspicious, logic |
| `BSL054` | `ExportVariables` | Yes | INFORMATION | Запрет экспортных глобальных переменных модуля | Ban export global module variables | design, global-state |
| `BSL055` | `ConsecutiveEmptyLines` | Yes | INFORMATION | Подряд идущие пустые строки | Consecutive empty lines | style, formatting |
| `BSL060` | `DoubleNegatives` | Yes | WARNING | Двойные отрицания | Double negatives | brainoverload, badpractice |
| `BSL062` | `UnusedParameters` | Yes | WARNING | Неиспользуемый параметр | Unused parameter | unused, design |
| `BSL064` | `ProcedureReturnsValue` | Yes | ERROR | Процедура не должна возвращать значение | Procedure should not return Value | correctness, design |
| `BSL065` | `MissingReturnedValueDescription` | Yes | INFORMATION | Отсутствует описание возвращаемого значения функции | Function returned values description is missing | design, documentation |
| `BSL066` | `DeprecatedFind` | Yes | WARNING | Использование устаревшего метода "Найти" | Using of the deprecated method "Find" | deprecated, compatibility |
| `BSL077` | `SelectTopWithoutOrderBy` | Yes | WARNING | Использование 'ВЫБРАТЬ ПЕРВЫЕ' без 'УПОРЯДОЧИТЬ ПО' | Using 'SELECT TOP' without 'ORDER BY' | performance, maintainability |
| `BSL097` | `DeprecatedCurrentDate` | Yes | WARNING | Использование устаревшего метода "ТекущаяДата" | Using of the deprecated method "CurrentDate" | standard, deprecated, unpredictable |
| `BSL131` | `DuplicateRegion` | Yes | INFORMATION | Повторяющиеся разделы модуля | Duplicate regions | style |
| `BSL148` | `AllFunctionPathMustHaveReturn` | Yes | ERROR | Все возможные пути выполнения функции должны содержать оператор Возврат | All execution paths of a function must have a Return statement | error-handling, correctness |
| `BSL149` | `AssignAliasFieldsInQuery` | Yes | INFORMATION | Назначение псевдонимов выбранным полям в запросе | Assigning aliases to selected fields in a query | convention, query |
| `BSL150` | `BadWords` | Yes | WARNING | Запрещенные слова | Prohibited words | convention |
| `BSL151` | `BeginTransactionBeforeTryCatch` | Yes | ERROR | Нарушение правил работы с транзакциями для метода 'НачатьТранзакцию' | Violating transaction rules for the 'BeginTransaction' method | standard |
| `BSL152` | `CachedPublic` | Yes | WARNING | Кеширование программного интерфейса | Cached public methods | design, performance |
| `BSL153` | `CanonicalSpellingKeywords` | Yes | INFORMATION | Каноническое написание ключевых слов | Canonical keyword writing | convention, style |
| `BSL154` | `CodeAfterAsyncCall` | Yes | WARNING | После вызова асинхронного метода есть строки кода | Lines of code after the asynchronous method call | async, correctness |
| `BSL155` | `CodeBlockBeforeSub` | Yes | ERROR | Определения методов должны размещаться перед операторами тела модуля | Method definitions must be placed before the module body operators | error |
| `BSL156` | `CodeOutOfRegion` | Yes | INFORMATION | Код расположен вне области | Code out of region | convention, structure |
| `BSL157` | `CommitTransactionOutsideTryCatch` | Yes | ERROR | Нарушение правил работы с транзакциями для метода 'ЗафиксироватьТранзакцию' | Violating transaction rules for the 'CommitTransaction' method | transaction, error-handling |
| `BSL158` | `CommonModuleAssign` | Yes | ERROR | Присвоение общему модулю | CommonModuleAssign | correctness, module |
| `BSL159` | `CommonModuleInvalidType` | Yes | ERROR | Общий модуль недопустимого типа | Common module invalid type | design, module |
| `BSL160` | `CommonModuleMissingAPI` | Yes | INFORMATION | Общий модуль должен иметь программный интерфейс | Common module should have a programming interface | design, module, api |
| `BSL161` | `CommonModuleNameCached` | Yes | INFORMATION | Пропущен постфикс "ПовтИсп" | Missed postfix "Cached" | convention, naming, module |
| `BSL162` | `CommonModuleNameClient` | Yes | INFORMATION | Пропущен постфикс "Клиент" | Missed postfix "Client" | convention, naming, module |
| `BSL163` | `CommonModuleNameClientServer` | Yes | INFORMATION | Пропущен постфикс "КлиентСервер" | Missed postfix "ClientServer" | convention, naming, module |
| `BSL164` | `CommonModuleNameFullAccess` | Yes | INFORMATION | Пропущен постфикс "ПолныеПрава" | Missed postfix "FullAccess" | convention, naming, module |
| `BSL165` | `CommonModuleNameGlobal` | Yes | INFORMATION | Пропущен постфикс "Глобальный" | Missed postfix "Global" | convention, naming, module |
| `BSL166` | `CommonModuleNameGlobalClient` | Yes | INFORMATION | Глобальный модуль с постфиксом "Клиент" | Global module with postfix "Client" | convention, naming, module |
| `BSL167` | `CommonModuleNameServerCall` | Yes | INFORMATION | Пропущен постфикс "ВызовСервера" | Missed postfix "ServerCall" | convention, naming, module |
| `BSL168` | `CommonModuleNameWords` | Yes | INFORMATION | Нерекомендуемое имя общего модуля | Unrecommended common module name | convention, naming, module |
| `BSL169` | `CompilationDirectiveLost` | Yes | ERROR | Директивы компиляции методов | Methods compilation directive | correctness, directive |
| `BSL170` | `CompilationDirectiveNeedLess` | Yes | INFORMATION | Лишняя директива компиляции | Needless compilation directive | redundant, directive |
| `BSL171` | `CrazyMultilineString` | Yes | INFORMATION | Безумные многострочные литералы | Crazy multiline literals | style, readability |
| `BSL172` | `DataExchangeLoading` | Yes | WARNING | Отсутствует проверка признака ОбменДанными.Загрузка в обработчике событий объекта | There is no check for the attribute DataExchange.Load in the object's event handler | correctness, data-exchange |
| `BSL173` | `DeletingCollectionItem` | Yes | ERROR | Удаление элемента при обходе коллекции посредством оператора "Для каждого ... Из ... Цикл" | Deleting an item when iterating through collection using the operator "For each ... In ... Do" | correctness, loop |
| `BSL174` | `DenyIncompleteValues` | Yes | WARNING | Запрет незаполненных значений у измерений регистров | Deny incomplete values for dimensions | transaction, error-handling |
| `BSL175` | `DeprecatedAttributes8312` | Yes | INFORMATION | Устаревшие объекты платформы 8.3.12 | Deprecated 8.3.12 platform features. | deprecated, compatibility |
| `BSL176` | `DeprecatedMethodCall` | Yes | INFORMATION | Устаревшие методы не должны использоваться | Deprecated methods should not be used | deprecated |
| `BSL177` | `DeprecatedMethods8310` | Yes | INFORMATION | Использование устаревшего метода клиентского приложения | Deprecated client application method. | deprecated, compatibility |
| `BSL178` | `DeprecatedMethods8317` | Yes | INFORMATION | Использование устаревших глобальных методов платформы 8.3.17 | Using of deprecated platform 8.3.17 global methods | deprecated, compatibility |
| `BSL179` | `DeprecatedTypeManagedForm` | Yes | WARNING | Устаревшее использование типа "УправляемаяФорма" | Deprecated ManagedForm type | deprecated, ui |
| `BSL180` | `DisableSafeMode` | Yes | WARNING | Отключение безопасного режима | Disable safe mode | security |
| `BSL181` | `DuplicatedInsertionIntoCollection` | Yes | WARNING | Повторное добавление/вставка значений в коллекцию | Duplicate adding or pasting a value to a collection | correctness, suspicious |
| `BSL182` | `ExcessiveAutoTestCheck` | Yes | INFORMATION | Избыточная проверка параметра АвтоТест | Excessive AutoTest Check | testing |
| `BSL183` | `ExecuteExternalCode` | Yes | WARNING | Выполнение произвольного кода на сервере | Executing of external code on the server | security |
| `BSL184` | `ExecuteExternalCodeInCommonModule` | Yes | WARNING | Выполнение произвольного кода в общем модуле на сервере | Executing of external code in a common module on the server | security, module |
| `BSL185` | `ExternalAppStarting` | Yes | WARNING | Запуск внешних приложений | External applications starting | security |
| `BSL186` | `ExtraCommas` | Yes | WARNING | Запятые без указания параметра в конце вызова метода | Commas without a parameter at the end of a method call | syntax, style |
| `BSL187` | `FieldsFromJoinsWithoutIsNull` | Yes | WARNING | Отсутствие проверки на NULL для полей из присоединяемых таблиц | No NULL checks for fields from joined tables | query, correctness |
| `BSL188` | `FileSystemAccess` | Yes | WARNING | Доступ к файловой системе | File system access | security, compatibility |
| `BSL189` | `ForbiddenMetadataName` | Yes | WARNING | Объекту метаданных присвоено запрещенное имя | Metadata object has a forbidden name | naming, convention |
| `BSL190` | `FormDataToValue` | Yes | WARNING | Использование метода ДанныеФормыВЗначение | FormDataToValue method call | performance, ui |
| `BSL191` | `FullOuterJoinQuery` | Yes | WARNING | Использование конструкции "ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ" в запросах | Using of "FULL OUTER JOIN" in queries | query, design |
| `BSL192` | `FunctionNameStartsWithGet` | Yes | INFORMATION | Имя функции не должно начинаться с "Получить" | Function name shouldn't start with "Получить" | naming, convention |
| `BSL193` | `FunctionOutParameter` | Yes | WARNING | Исходящий параметр функции | Out function parameter | design |
| `BSL194` | `FunctionReturnsSamePrimitive` | Yes | ERROR | Функция всегда возвращает одно и то же примитивное значение | The function always returns the same primitive value | redundant, design |
| `BSL195` | `GetFormMethod` | Yes | WARNING | Использование метода ПолучитьФорму | GetForm method call | deprecated, ui |
| `BSL196` | `GlobalContextMethodCollision8312` | Yes | ERROR | Конфликт имен методов с методами глобального контекста | Global context method names collision | correctness, compatibility |
| `BSL197` | `IfElseDuplicatedCodeBlock` | Yes | WARNING | Повторяющиеся блоки кода в синтаксической конструкции Если...Тогда...ИначеЕсли... | Duplicated code blocks in If...Then...ElseIf... statements | suspicious, duplicate |
| `BSL198` | `IfElseDuplicatedCondition` | Yes | WARNING | Повторяющиеся условия в синтаксической конструкции Если...Тогда...ИначеЕсли... | Duplicated conditions in If...Then...ElseIf... statements | suspicious, correctness |
| `BSL199` | `IfElseIfEndsWithElse` | Yes | INFORMATION | Использование синтаксической конструкции Если...Тогда...ИначеЕсли... | Else...The...ElseIf... statement should end with Else branch | design, robustness |
| `BSL200` | `IncorrectLineBreak` | Yes | INFORMATION | Неправильный перенос выражения | Incorrect expression line break | style, convention |
| `BSL201` | `IncorrectUseLikeInQuery` | Yes | WARNING | Некорректное использование 'ПОДОБНО' | Incorrect use of 'LIKE' | query, correctness |
| `BSL202` | `IncorrectUseOfStrTemplate` | Yes | ERROR | Неверное использование "СтрШаблон" | Incorrect use of "StrTemplate" | correctness |
| `BSL203` | `InternetAccess` | Yes | WARNING | Обращение к Интернет-ресурсам | Referring to Internet resources | security |
| `BSL204` | `InvalidCharacterInFile` | Yes | WARNING | Недопустимый символ | Invalid character | correctness, encoding |
| `BSL205` | `IsInRoleMethod` | Yes | WARNING | Использование метода РольДоступна | IsInRole global method call | security, access-control |
| `BSL206` | `JoinWithSubQuery` | Yes | WARNING | Соединение с вложенными запросами | Join with sub queries | query, performance |
| `BSL207` | `JoinWithVirtualTable` | Yes | WARNING | Соединение с виртуальными таблицами | Join with virtual table | query, performance |
| `BSL208` | `LatinAndCyrillicSymbolInWord` | Yes | WARNING | Смешивание латинских и кириллических символов в одном идентификаторе | Mixing Latin and Cyrillic characters in one identifier | suspicious, naming |
| `BSL209` | `LogicalOrInJoinQuerySection` | Yes | WARNING | Логическое 'ИЛИ' в соединениях запроса | Logical 'OR' in 'JOIN' query section | query, performance |
| `BSL210` | `LogicalOrInTheWhereSectionOfQuery` | Yes | WARNING | Использование логического "ИЛИ" в секции "ГДЕ" запроса | Using a logical "OR" in the "WHERE" section of a query | query, performance, standard |
| `BSL211` | `MetadataObjectNameLength` | Yes | WARNING | Имена объектов метаданных не должны превышать допустимой длины наименования | Metadata object names must not exceed the allowed length | naming, convention |
| `BSL212` | `MissedRequiredParameter` | Yes | ERROR | Пропущен обязательный параметр метода | Missed a required method parameter | correctness |
| `BSL213` | `MissingCommonModuleMethod` | Yes | ERROR | Обращение к отсутствующему методу общего модуля | Referencing a missing common module method | correctness, module |
| `BSL214` | `MissingEventSubscriptionHandler` | Yes | ERROR | Отсутствует обработчик подписки на событие | Event subscription handler missing | correctness, events |
| `BSL215` | `MissingParameterDescription` | Yes | INFORMATION | Отсутствует описание параметров метода | Method parameters description are missing | documentation, api |
| `BSL216` | `MissingSpace` | Yes | INFORMATION | Пропущены пробелы слева или справа от операторов `+ - * / = % < > <> <= >=`, от ключевых слов, а так же справа от `,` и `;` | Missing spaces to the left or right of operators + - * / = % < > <> <= >=, keywords, and also to the right of , and ; | style, convention |
| `BSL217` | `MissingTempStorageDeletion` | Yes | WARNING | Отсутствует удаление данных из временного хранилища после использования | Missing temporary storage data deletion after using | resource-management, memory |
| `BSL218` | `MissingTemporaryFileDeletion` | Yes | WARNING | Отсутствует удаление временного файла после использования | Missing temporary file deletion after using | resource-management |
| `BSL219` | `MissingVariablesDescription` | Yes | INFORMATION | Все объявления переменных должны иметь описание | All variables declarations must have a description | documentation, convention |
| `BSL220` | `MultilineStringInQuery` | Yes | INFORMATION | Многострочный литерал в запросе | Multi-line literal in query | query, style |
| `BSL221` | `MultilingualStringHasAllDeclaredLanguages` | Yes | WARNING | Есть локализованный текст для всех заявленных в конфигурации языков | There is a localized text for all languages declared in the configuration | localization |
| `BSL222` | `MultilingualStringUsingWithTemplate` | Yes | INFORMATION | Частично локализованный текст используется в функции СтрШаблон | Partially localized text is used in the StrTemplate function | localization, style |
| `BSL223` | `NestedConstructorsInStructureDeclaration` | Yes | INFORMATION | Использование конструкторов с параметрами при объявлении структуры | Nested constructors with parameters in structure declaration | readability, design |
| `BSL224` | `NestedFunctionInParameters` | Yes | INFORMATION | Инициализация параметров методов и конструкторов вызовом вложенных методов | Initialization of method and constructor parameters by calling nested methods | readability, brain-overload |
| `BSL225` | `NumberOfValuesInStructureConstructor` | Yes | INFORMATION | Ограничение на количество значений свойств, передаваемых в конструктор структуры | Limit on the number of property values passed to the structure constructor | design, readability |
| `BSL226` | `OSUsersMethod` | Yes | WARNING | Использование метода ПользователиОС | Using method OSUsers | security |
| `BSL227` | `OneStatementPerLine` | Yes | INFORMATION | Одно выражение в одной строке | One statement per line | style, convention |
| `BSL228` | `OrderOfParams` | Yes | INFORMATION | Порядок параметров метода | Order of Parameters in method | design, convention |
| `BSL229` | `OrdinaryAppSupport` | Yes | WARNING | Поддержка обычного приложения | Ordinary application support | compatibility, ui |
| `BSL230` | `PairingBrokenTransaction` | Yes | ERROR | Нарушение парности использования методов "НачатьТранзакцию()" и "ЗафиксироватьТранзакцию()" / "ОтменитьТранзакцию()" | Violation of pairing using methods "BeginTransaction()" & "CommitTransaction()" / "RollbackTransaction()" | transaction, correctness |
| `BSL231` | `PrivilegedModuleMethodCall` | Yes | WARNING | Обращение к методам привилегированных модулей | Accessing privileged module methods | security, access-control |
| `BSL232` | `ProtectedModule` | Yes | INFORMATION | Защищенные модули | Protected modules | design |
| `BSL233` | `PublicMethodsDescription` | Yes | INFORMATION | Все методы программного интерфейса должны иметь описание | All public methods must have a description | documentation, api |
| `BSL234` | `QueryNestedFieldsByDot` | Yes | WARNING | Разыменование ссылочных полей запроса через точку | Getting objects nested fields data by dot in database query text | query, performance |
| `BSL235` | `QueryParseError` | Yes | WARNING | Ошибка разбора текста запроса | Query text parsing error | query, correctness |
| `BSL236` | `QueryToMissingMetadata` | Yes | ERROR | Обращение к несуществующим метаданным в запросе | Using non-existent metadata in the query | query, correctness |
| `BSL237` | `RedundantAccessToObject` | Yes | INFORMATION | Избыточное обращение к объекту | Redundant access to an object | redundant, performance |
| `BSL238` | `RefOveruse` | Yes | INFORMATION | Избыточное использование "Ссылка" в запросе | Overuse "Reference" in a query | performance, readability |
| `BSL239` | `ReservedParameterNames` | Yes | WARNING | Зарезервированные имена параметров | Reserved parameter names | naming, suspicious |
| `BSL240` | `RewriteMethodParameter` | Yes | WARNING | Перезапись параметров метода | Rewrite method parameter | suspicious, correctness |
| `BSL241` | `SameMetadataObjectAndChildNames` | Yes | ERROR | Совпадает имя объекта метаданного и его дочернего | Same metadata object and child name | naming, design |
| `BSL242` | `ScheduledJobHandler` | Yes | ERROR | Обработчик регламентного задания | Scheduled job handler | correctness, scheduled-jobs |
| `BSL243` | `SelfInsertion` | Yes | ERROR | Вставка коллекции в саму себя | Insert a collection into itself | correctness, suspicious |
| `BSL244` | `ServerCallsInFormEvents` | Yes | ERROR | Серверные вызовы в событиях форм | Server calls in form events | correctness, ui, performance |
| `BSL245` | `ServerSideExportFormMethod` | Yes | WARNING | Серверный экспортный метод формы | Server-side export form method | correctness, ui |
| `BSL246` | `SetPermissionsForNewObjects` | Yes | ERROR | Флажок «Устанавливать права для новых объектов» должен быть установлен только у роли ПолныеПрава | The check box «Set permissions for new objects» should only be selected for the FullAccess role | security, access-control |
| `BSL247` | `SetPrivilegedMode` | Yes | WARNING | Использование привилегированного режима | Using privileged mode | security |
| `BSL248` | `SeveralCompilerDirectives` | Yes | ERROR | Ошибочное указание нескольких директив компиляции | Erroneous indication of several compilation directives | correctness, directive |
| `BSL249` | `StyleElementConstructors` | Yes | ERROR | Конструктор элемента стиля | Style element constructor | ui, design |
| `BSL250` | `TempFilesDir` | Yes | WARNING | Вызов функции КаталогВременныхФайлов() | TempFilesDir() method call | standard, badpractice |
| `BSL251` | `TernaryOperatorUsage` | Yes | INFORMATION | Использование тернарного оператора | Ternary operator usage | style, readability |
| `BSL252` | `ThisObjectAssign` | Yes | ERROR | Присвоение значения свойству ЭтотОбъект | ThisObject assign | correctness, suspicious |
| `BSL253` | `TimeoutsInExternalResources` | Yes | WARNING | Таймауты при работе с внешними ресурсами | Timeouts working with external resources | robustness, performance |
| `BSL254` | `TransferringParametersBetweenClientAndServer` | Yes | WARNING | Передача параметров между клиентом и сервером | Transferring parameters between the client and the server | performance, design |
| `BSL255` | `TryNumber` | Yes | WARNING | Приведение к числу в попытке | Cast to number of try catch block | error-handling, suspicious |
| `BSL256` | `Typo` | Yes | INFORMATION | Опечатка | Typo | convention |
| `BSL257` | `UnaryPlusInConcatenation` | Yes | ERROR | Унарный плюс в конкатенации строк | Unary Plus sign in string concatenation | suspicious, brainoverload |
| `BSL258` | `UnionAll` | Yes | WARNING | Использование ключевого слова "ОБЪЕДИНИТЬ" в запросах | Using keyword "UNION" in queries | query, performance |
| `BSL259` | `UnknownPreprocessorSymbol` | Yes | WARNING | Неизвестный символ препроцессора | Unknown preprocessor symbol | correctness, directive |
| `BSL260` | `UnsafeFindByCode` | Yes | WARNING | Небезопасное использование метода НайтиПоКоду() | Unsafe FindByCode() method usage | correctness, robustness |
| `BSL261` | `UnsafeSafeModeMethodCall` | Yes | WARNING | Небезопасное использование функции БезопасныйРежим() | Unsafe SafeMode method call | security, correctness |
| `BSL262` | `UsageWriteLogEvent` | Yes | INFORMATION | Неверное использование метода "ЗаписьЖурналаРегистрации" | Incorrect use of the method "WriteLogEvent" | standard, badpractice |
| `BSL263` | `UseLessForEach` | Yes | WARNING | Бесполезный перебор коллекции | Useless collection iteration | redundant, suspicious |
| `BSL264` | `UseSystemInformation` | Yes | WARNING | Использование системной информации | Use of system information | security |
| `BSL265` | `UselessTernaryOperator` | Yes | INFORMATION | Бесполезный тернарный оператор | Useless ternary operator | redundant, readability |
| `BSL266` | `UsingCancelParameter` | Yes | WARNING | Работа с параметром "Отказ" | Using parameter "Cancel" | correctness, events |
| `BSL267` | `UsingExternalCodeTools` | Yes | ERROR | Использование возможностей выполнения внешнего кода | Using external code tools | standard, design |
| `BSL268` | `UsingFindElementByString` | Yes | WARNING | Использование методов "НайтиПоНаименованию", "НайтиПоКоду" и "НайтиПоНомеру" | Using FindByName, FindByCode and FindByNumber | performance |
| `BSL269` | `UsingLikeInQuery` | Yes | INFORMATION | Использование 'ПОДОБНО' в запросе | Using 'LIKE' in query | query, performance |
| `BSL271` | `UsingObjectNotAvailableUnix` | Yes | WARNING | Использование объектов недоступных в Unix системах | Using unavailable in Unix objects | compatibility |
| `BSL272` | `UsingSynchronousCalls` | Yes | WARNING | Использование синхронных вызовов | Using synchronous calls | performance, ui |
| `BSL273` | `VirtualTableCallWithoutParameters` | Yes | WARNING | Обращение к виртуальной таблице без параметров | Virtual table call without parameters | query, performance |
| `BSL274` | `WrongDataPathForFormElements` | Yes | ERROR | У полей формы не указан путь к данным | Form fields do not have a data path | correctness, ui |
| `BSL275` | `WrongHttpServiceHandler` | Yes | ERROR | Неверно задан обработчик метода http-сервиса | Missing handler for http service | correctness, http |
| `BSL276` | `WrongUseFunctionProceedWithCall` | Yes | ERROR | Некорректное использование функции ПродолжитьВызов() | Wrong use of ProceedWithCall function | correctness, extensions |
| `BSL277` | `WrongUseOfRollbackTransactionMethod` | Yes | ERROR | Некорректное использование метода ОтменитьТранзакцию() | Not recommended using of RollbackTransaction method | transaction, error-handling |
| `BSL278` | `WrongWebServiceHandler` | Yes | ERROR | Неверно задан обработчик операции web-сервиса | Wrong handler for web service | correctness, web-service |
| `BSL279` | `YoLetterUsage` | Yes | INFORMATION | Использование буквы "ё" в текстах модулей | Using Russian character "yo" ("ё") in code | style, convention |

## Maintenance

Regenerate this file after changing `RULE_METADATA`,
`RULE_DESCRIPTIONS_RU`, or diagnostic default behavior:

```bash
./.venv/bin/python scripts/build_diagnostic_rules_doc.py
```
