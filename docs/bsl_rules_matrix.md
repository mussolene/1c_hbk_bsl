# Матрица правил BSL: onec-hbk-bsl ↔ BSLLS

Автогенерация: `2026-03-21`. Источники: `src/onec_hbk_bsl/analysis/diagnostics.py` (`RULE_METADATA`, `_BSLLS_NAME_TO_CODE`, `DiagnosticEngine._run_rules`, `DEFAULT_DISABLED`) и при необходимости локальный справочник классов диагностик сопоставимого Java-анализатора (не входит в репозиторий).

## Сводка


| Показатель                                                    | Значение |
| ------------------------------------------------------------- | -------- |
| Кодов в `RULE_METADATA` (BSL001–BSL280)                       | 280      |
| Кодов с веткой в `_run_rules` (`_rule_enabled`)               | 170      |
| Кодов в `DEFAULT_DISABLED` по умолчанию                       | 200      |
| Имён в `_BSLLS_NAME_TO_CODE`                                  | 180      |
| Конкретных классов `*Diagnostic.java` в BSLLS (без Abstract*) | 181      |
| Совпадение `RULE_METADATA.name` с именем класса BSLLS         | 207      |
| Правил только в BSLLS (нет такого `name` у нас)               | 2        |
| Явных `implemented: True` в метаданных                        | 3        |
| Явных `implemented: False` в метаданных                       | 132      |


### Намеренные дубликаты семантики BSLLS (отдельные коды BSL)

Некоторые правила в BSLLS имеют один канонический код `EmptyCodeBlock` (**BSL004**). В движке onec-hbk-bsl для исторических сценариев остаются отдельные реализации с кодами **BSL080**, **BSL092**, **BSL107**; они **выключены по умолчанию** (`DEFAULT_DISABLED`), чтобы не дублировать **BSL004** на той же конструкции. При включении такого кода ожидайте пересечение с **BSL004** — предпочтительнее пользоваться **BSL004** и профилем BSLLS.

Если на одной строке срабатывают **BSL036** (IfConditionComplexity) и **BSL153** (CanonicalSpellingKeywords), движок подавляет **BSL153**, когда включены оба правила: приоритет у сложности условия, как у BSLLS на пересечениях «сложное условие» vs «написание ключевых слов». Для **многострочного** условия `Если … Тогда` учёт операторов `И`/`ИЛИ`/`And`/`Or` идёт по всему блоку до `Тогда`; **BSL153** на строках продолжения подавляется, если первая строка условия даёт **BSL036** (согласование с BSLLS).

**BSL065** (Missing export comment для экспортных процедур/функций): в модулях форм (`…/Form/Module.bsl`) правило **не** применяется — как контекстное сужение к поведению BSLLS на формах.

**BSL024** (SpaceAtStartComment): не сообщается для строк директив компилятора `//&…`; остальные полнострочные `//` комментарии — по `bsl024_should_report_line` (в т.ч. `//{`/`//}` и `//****…`, как в типичном прогоне BSLLS на модулях EDT).

**BSL055** (ConsecutiveEmptyLines): допускается не более **одной** пустой строки подряд (`MAX_BLANK_LINES=1`).

Для идентификаторов с латиницей и кириллицей: если все кириллические буквы — омоглифы латиницы (слово сводится к «латинскому» виду), движок выдаёт **BSL256** (Typo), иначе **BSL208** (LatinAndCyrillicSymbolInWord), как у BSLLS относительно Typo vs mixed-script.

### Легенда колонок


| Колонка                      | Смысл                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| **Каноническое имя BSLLS**   | Из `_BSLLS_NAME_TO_CODE` (если есть), иначе `—`.                                          |
| **Имя в `RULE_METADATA*`*    | Поле `name` в нашем реестре.                                                              |
| **BSLLS Java**               | Есть файл `ИмяDiagnostic.java` с тем же префиксом, что и `RULE_METADATA.name`.            |
| **Ветка в движке**           | В `DiagnosticEngine._run_rules` вызывается `if self._rule_enabled("BSL…")` с реализацией. |
| `**implemented` в metadata** | Явное поле; если нет — логика считается по факту ветки в движке.                          |
| **По умолчанию выкл.**       | Код входит в `DEFAULT_DISABLED`.                                                          |


## Полная таблица BSL001–BSL280


| Код    | Канон. имя BSLLS                             | Имя в RULE_METADATA                          | Severity    | BSLLS Java | Ветка в движке | implemented | Выкл. по умолч. |
| ------ | -------------------------------------------- | -------------------------------------------- | ----------- | ---------- | -------------- | ----------- | --------------- |
| BSL001 | ParseError                                   | ParseError                                   | ERROR       | да         | да             | —           | нет             |
| BSL002 | MethodSize                                   | MethodSize                                   | WARNING     | да         | да             | —           | нет             |
| BSL003 | NonExportMethodsInApiRegion                  | NonExportMethodsInApiRegion                  | WARNING     | да         | да             | —           | нет             |
| BSL004 | EmptyCodeBlock                               | EmptyCodeBlock                               | WARNING     | да         | да             | —           | нет             |
| BSL005 | UsingHardcodeNetworkAddress                  | UsingHardcodeNetworkAddress                  | WARNING     | да         | да             | —           | нет             |
| BSL006 | UsingHardcodePath                            | UsingHardcodePath                            | WARNING     | да         | да             | —           | нет             |
| BSL007 | UnusedLocalVariable                          | UnusedLocalVariable                          | WARNING     | да         | да             | —           | нет             |
| BSL008 | TooManyReturns                               | TooManyReturns                               | WARNING     | да         | да             | —           | нет             |
| BSL009 | SelfAssign                                   | SelfAssign                                   | WARNING     | да         | да             | —           | нет             |
| BSL010 | —                                            | UselessReturn                                | INFORMATION | нет        | да             | —           | нет             |
| BSL011 | CognitiveComplexity                          | CognitiveComplexity                          | WARNING     | да         | да             | —           | нет             |
| BSL012 | UsingHardcodeSecretInformation               | UsingHardcodeSecretInformation               | ERROR       | да         | да             | —           | нет             |
| BSL013 | CommentedCode                                | CommentedCode                                | INFORMATION | да         | да             | —           | да              |
| BSL014 | LineLength                                   | LineLength                                   | INFORMATION | да         | да             | —           | нет             |
| BSL015 | NumberOfOptionalParams                       | NumberOfOptionalParams                       | WARNING     | да         | да             | —           | нет             |
| BSL016 | NonStandardRegion                            | NonStandardRegion                            | INFORMATION | да         | да             | —           | нет             |
| BSL017 | CommandModuleExportMethods                   | CommandModuleExportMethods                   | WARNING     | да         | да             | —           | нет             |
| BSL018 | —                                            | RaiseExceptionWithLiteral                    | WARNING     | нет        | да             | —           | да              |
| BSL019 | CyclomaticComplexity                         | CyclomaticComplexity                         | WARNING     | да         | да             | —           | нет             |
| BSL020 | NestedStatements                             | NestedStatements                             | WARNING     | да         | да             | —           | нет             |
| BSL021 | —                                            | UnusedValParameter                           | WARNING     | нет        | да             | —           | нет             |
| BSL022 | DeprecatedMessage                            | DeprecatedMessage                            | WARNING     | да         | да             | —           | нет             |
| BSL023 | UsingServiceTag                              | UsingServiceTag                              | INFORMATION | да         | да             | —           | нет             |
| BSL024 | SpaceAtStartComment                          | SpaceAtStartComment                          | INFORMATION | да         | да             | —           | нет             |
| BSL025 | EmptyStatement                               | EmptyStatement                               | WARNING     | да         | да             | —           | нет             |
| BSL026 | EmptyRegion                                  | EmptyRegion                                  | INFORMATION | да         | да             | —           | нет             |
| BSL027 | UsingGoto                                    | UsingGoto                                    | WARNING     | да         | да             | —           | нет             |
| BSL028 | MissingCodeTryCatchEx                        | MissingCodeTryCatchEx                        | INFORMATION | да         | да             | —           | нет             |
| BSL029 | MagicNumber                                  | MagicNumber                                  | INFORMATION | да         | да             | —           | нет             |
| BSL030 | SemicolonPresence                            | SemicolonPresence                            | INFORMATION | да         | да             | —           | нет             |
| BSL031 | NumberOfParams                               | NumberOfParams                               | WARNING     | да         | да             | —           | нет             |
| BSL032 | FunctionShouldHaveReturn                     | FunctionShouldHaveReturn                     | WARNING     | да         | да             | —           | нет             |
| BSL033 | CreateQueryInCycle                           | CreateQueryInCycle                           | WARNING     | да         | да             | —           | нет             |
| BSL034 | —                                            | UnusedErrorVariable                          | WARNING     | нет        | да             | —           | нет             |
| BSL035 | DuplicateStringLiteral                       | DuplicateStringLiteral                       | INFORMATION | да         | да             | —           | нет             |
| BSL036 | IfConditionComplexity                        | IfConditionComplexity                        | WARNING     | да         | да             | —           | нет             |
| BSL037 | —                                            | OverrideBuiltinMethod                        | WARNING     | нет        | да             | —           | нет             |
| BSL038 | —                                            | StringConcatenationInLoop                    | WARNING     | нет        | да             | —           | нет             |
| BSL039 | NestedTernaryOperator                        | NestedTernaryOperator                        | INFORMATION | да         | да             | —           | нет             |
| BSL040 | UsingThisForm                                | UsingThisForm                                | INFORMATION | да         | да             | —           | нет             |
| BSL041 | —                                            | NotifyDescriptionToModalWindow               | INFORMATION | нет        | да             | —           | нет             |
| BSL042 | UnusedLocalMethod                            | UnusedLocalMethod                            | WARNING     | да         | да             | —           | нет             |
| BSL043 | —                                            | TooManyVariables                             | INFORMATION | нет        | да             | —           | нет             |
| BSL044 | —                                            | FunctionNoReturnValue                        | WARNING     | нет        | да             | —           | нет             |
| BSL045 | —                                            | MultilineStringLiteral                       | INFORMATION | нет        | да             | —           | нет             |
| BSL046 | —                                            | MissingElseBranch                            | INFORMATION | нет        | да             | —           | нет             |
| BSL047 | MagicDate                                    | MagicDate                                    | INFORMATION | да         | да             | —           | нет             |
| BSL048 | —                                            | EmptyFile                                    | INFORMATION | нет        | да             | —           | нет             |
| BSL049 | —                                            | UnconditionalExceptionRaise                  | INFORMATION | нет        | да             | —           | нет             |
| BSL050 | —                                            | LargeTransaction                             | WARNING     | нет        | да             | —           | нет             |
| BSL051 | UnreachableCode                              | UnreachableCode                              | WARNING     | да         | да             | —           | нет             |
| BSL052 | IdenticalExpressions                         | IdenticalExpressions                         | WARNING     | да         | да             | —           | нет             |
| BSL053 | —                                            | ExecuteExternalCode                          | WARNING     | да         | да             | —           | нет             |
| BSL054 | ExportVariables                              | ExportVariables                              | INFORMATION | да         | да             | —           | нет             |
| BSL055 | ConsecutiveEmptyLines                        | ConsecutiveEmptyLines                        | INFORMATION | да         | да             | —           | нет             |
| BSL056 | —                                            | ShortMethodName                              | INFORMATION | нет        | да             | —           | нет             |
| BSL057 | —                                            | DeprecatedInputDialog                        | WARNING     | нет        | да             | —           | нет             |
| BSL058 | —                                            | QueryWithoutWhere                            | WARNING     | нет        | да             | —           | нет             |
| BSL059 | —                                            | BooleanLiteralComparison                     | INFORMATION | нет        | да             | —           | нет             |
| BSL060 | DoubleNegatives                              | DoubleNegatives                              | INFORMATION | да         | да             | —           | нет             |
| BSL061 | —                                            | AbruptLoopExit                               | INFORMATION | нет        | да             | —           | нет             |
| BSL062 | UnusedParameters                             | UnusedParameters                             | WARNING     | да         | да             | —           | нет             |
| BSL063 | —                                            | LargeModule                                  | WARNING     | нет        | да             | —           | нет             |
| BSL064 | ProcedureReturnsValue                        | ProcedureReturnsValue                        | ERROR       | да         | да             | —           | нет             |
| BSL065 | MissingReturnedValueDescription              | MissingReturnedValueDescription              | INFORMATION | да         | да             | —           | нет             |
| BSL066 | DeprecatedFind                               | DeprecatedFind                               | WARNING     | да         | да             | —           | нет             |
| BSL067 | —                                            | VarDeclarationAfterCode                      | WARNING     | нет        | да             | —           | нет             |
| BSL068 | —                                            | TooManyElseIf                                | INFORMATION | нет        | да             | —           | нет             |
| BSL069 | —                                            | InfiniteLoop                                 | WARNING     | нет        | да             | —           | нет             |
| BSL070 | —                                            | EmptyLoopBody                                | WARNING     | нет        | да             | —           | нет             |
| BSL071 | —                                            | MagicNumber                                  | INFORMATION | да         | да             | —           | да              |
| BSL072 | —                                            | StringConcatenationInLoop                    | WARNING     | нет        | да             | —           | да              |
| BSL073 | —                                            | MissingElseBranch                            | INFORMATION | нет        | да             | —           | да              |
| BSL074 | —                                            | TodoComment                                  | INFORMATION | нет        | да             | —           | да              |
| BSL075 | —                                            | ExportVariables                              | INFORMATION | да         | да             | —           | да              |
| BSL076 | —                                            | NegativeConditionFirst                       | INFORMATION | нет        | да             | —           | да              |
| BSL077 | SelectTopWithoutOrderBy                      | SelectTopWithoutOrderBy                      | WARNING     | да         | да             | —           | нет             |
| BSL078 | —                                            | RaiseWithoutMessage                          | WARNING     | нет        | да             | —           | да              |
| BSL079 | —                                            | UsingGoto                                    | WARNING     | да         | да             | —           | да              |
| BSL080 | —                                            | EmptyCodeBlock                               | WARNING     | да         | да             | —           | да              |
| BSL081 | —                                            | LongMethodChain                              | INFORMATION | нет        | да             | —           | да              |
| BSL082 | —                                            | MissingNewlineAtEndOfFile                    | INFORMATION | нет        | да             | —           | да              |
| BSL083 | —                                            | TooManyModuleVariables                       | INFORMATION | нет        | да             | —           | да              |
| BSL084 | —                                            | FunctionShouldHaveReturn                     | WARNING     | да         | да             | —           | да              |
| BSL085 | —                                            | IdenticalExpressions                         | WARNING     | да         | да             | —           | да              |
| BSL086 | —                                            | HttpRequestInLoop                            | WARNING     | нет        | да             | —           | да              |
| BSL087 | —                                            | ObjectCreationInLoop                         | INFORMATION | нет        | да             | —           | да              |
| BSL088 | —                                            | MissingReturnedValueDescription              | INFORMATION | да         | да             | —           | да              |
| BSL089 | —                                            | TransactionInLoop                            | WARNING     | нет        | да             | —           | да              |
| BSL090 | —                                            | UsingHardcodeSecretInformation               | WARNING     | да         | да             | —           | да              |
| BSL091 | —                                            | RedundantElseAfterReturn                     | INFORMATION | нет        | да             | —           | да              |
| BSL092 | —                                            | EmptyCodeBlock                               | WARNING     | да         | да             | —           | да              |
| BSL093 | —                                            | ComparisonToNull                             | WARNING     | нет        | да             | —           | да              |
| BSL094 | —                                            | SelfAssign                                   | WARNING     | да         | да             | —           | да              |
| BSL095 | —                                            | MultipleStatementsOnOneLine                  | INFORMATION | нет        | да             | —           | да              |
| BSL096 | —                                            | MissingReturnedValueDescription              | INFORMATION | да         | да             | —           | да              |
| BSL097 | DeprecatedCurrentDate                        | DeprecatedCurrentDate                        | INFORMATION | да         | да             | —           | нет             |
| BSL098 | —                                            | UseOfExecute                                 | WARNING     | нет        | да             | —           | да              |
| BSL099 | —                                            | NumberOfParams                               | WARNING     | да         | да             | —           | да              |
| BSL100 | —                                            | UsingHardcodePath                            | WARNING     | да         | да             | —           | да              |
| BSL101 | —                                            | NestedStatements                             | WARNING     | да         | да             | —           | да              |
| BSL102 | —                                            | LargeModule                                  | INFORMATION | нет        | да             | —           | да              |
| BSL103 | —                                            | UseOfEval                                    | WARNING     | нет        | да             | —           | да              |
| BSL104 | —                                            | MissingModuleComment                         | INFORMATION | нет        | да             | —           | да              |
| BSL105 | —                                            | UseOfSleep                                   | WARNING     | нет        | да             | —           | да              |
| BSL106 | —                                            | CreateQueryInCycle                           | WARNING     | да         | да             | —           | да              |
| BSL107 | —                                            | EmptyCodeBlock                               | WARNING     | да         | да             | —           | да              |
| BSL108 | —                                            | ExportVariables                              | WARNING     | да         | да             | —           | да              |
| BSL109 | —                                            | NegativeConditionalReturn                    | INFORMATION | нет        | да             | —           | да              |
| BSL110 | —                                            | StringConcatInLoop                           | WARNING     | нет        | да             | —           | да              |
| BSL111 | —                                            | MixedLanguageIdentifiers                     | WARNING     | нет        | да             | —           | нет             |
| BSL112 | —                                            | UnterminatedTransaction                      | ERROR       | нет        | да             | —           | да              |
| BSL113 | —                                            | AssignmentInCondition                        | WARNING     | нет        | нет            | —           | да              |
| BSL114 | —                                            | EmptyModule                                  | INFORMATION | нет        | да             | —           | да              |
| BSL115 | —                                            | DoubleNegatives                              | WARNING     | да         | да             | —           | да              |
| BSL116 | —                                            | UseOfObsoleteIterator                        | INFORMATION | нет        | да             | —           | да              |
| BSL117 | —                                            | ProcedureCalledAsFunction                    | ERROR       | нет        | да             | —           | нет             |
| BSL118 | —                                            | FunctionShouldHaveReturn                     | WARNING     | да         | да             | —           | да              |
| BSL119 | —                                            | LineLength                                   | INFORMATION | да         | да             | —           | да              |
| BSL120 | —                                            | TrailingWhitespace                           | INFORMATION | нет        | да             | —           | да              |
| BSL121 | —                                            | TabIndentation                               | INFORMATION | нет        | да             | —           | да              |
| BSL122 | —                                            | UnusedParameters                             | WARNING     | да         | да             | —           | да              |
| BSL123 | —                                            | CommentedCode                                | INFORMATION | да         | да             | —           | да              |
| BSL124 | —                                            | ShortProcedureName                           | INFORMATION | нет        | да             | —           | да              |
| BSL125 | —                                            | UseOfAbortOutsideLoop                        | ERROR       | нет        | да             | —           | нет             |
| BSL126 | —                                            | UseOfContinueOutsideLoop                     | ERROR       | нет        | да             | —           | нет             |
| BSL127 | —                                            | MultipleReturnValues                         | INFORMATION | нет        | да             | —           | да              |
| BSL128 | —                                            | UnreachableCode                              | WARNING     | да         | да             | —           | да              |
| BSL129 | —                                            | RecursiveCall                                | WARNING     | нет        | да             | —           | да              |
| BSL130 | —                                            | LineLength                                   | INFORMATION | да         | да             | —           | да              |
| BSL131 | —                                            | EmptyRegion                                  | INFORMATION | да         | да             | —           | да              |
| BSL132 | —                                            | DuplicateStringLiteral                       | INFORMATION | да         | да             | —           | да              |
| BSL133 | —                                            | RequiredParamAfterOptional                   | WARNING     | нет        | да             | —           | нет             |
| BSL134 | —                                            | CyclomaticComplexity                         | WARNING     | да         | да             | —           | да              |
| BSL135 | —                                            | NestedFunctionCalls                          | INFORMATION | нет        | да             | —           | да              |
| BSL136 | —                                            | MissingSpaceBeforeComment                    | INFORMATION | нет        | да             | —           | да              |
| BSL137 | —                                            | UseOfFindByDescription                       | WARNING     | нет        | да             | —           | да              |
| BSL138 | —                                            | UseOfDebugOutput                             | WARNING     | нет        | да             | —           | да              |
| BSL139 | —                                            | TooLongParameterName                         | INFORMATION | нет        | да             | —           | да              |
| BSL140 | —                                            | UnreachableElseIf                            | WARNING     | нет        | да             | —           | нет             |
| BSL141 | —                                            | MagicBooleanReturn                           | INFORMATION | нет        | да             | —           | да              |
| BSL142 | —                                            | LargeParameterDefaultValue                   | INFORMATION | нет        | да             | —           | да              |
| BSL143 | —                                            | DuplicateElseIfCondition                     | WARNING     | нет        | да             | —           | нет             |
| BSL144 | —                                            | UnnecessaryParentheses                       | INFORMATION | нет        | да             | —           | да              |
| BSL145 | —                                            | StringFormatInsteadOfConcat                  | INFORMATION | нет        | да             | —           | да              |
| BSL146 | —                                            | ModuleInitializationCode                     | INFORMATION | нет        | да             | —           | да              |
| BSL147 | —                                            | UseOfUICall                                  | WARNING     | нет        | да             | —           | нет             |
| BSL148 | AllFunctionPathMustHaveReturn                | AllFunctionPathMustHaveReturn                | ERROR       | да         | нет            | нет         | да              |
| BSL149 | AssignAliasFieldsInQuery                     | AssignAliasFieldsInQuery                     | INFORMATION | да         | нет            | нет         | да              |
| BSL150 | BadWords                                     | BadWords                                     | WARNING     | да         | нет            | нет         | да              |
| BSL151 | BeginTransactionBeforeTryCatch               | BeginTransactionBeforeTryCatch               | ERROR       | да         | да             | нет         | да              |
| BSL152 | CachedPublic                                 | CachedPublic                                 | WARNING     | да         | нет            | нет         | да              |
| BSL153 | CanonicalSpellingKeywords                    | CanonicalSpellingKeywords                    | INFORMATION | да         | да             | нет         | да              |
| BSL154 | CodeAfterAsyncCall                           | CodeAfterAsyncCall                           | WARNING     | да         | нет            | нет         | да              |
| BSL155 | CodeBlockBeforeSub                           | CodeBlockBeforeSub                           | WARNING     | да         | нет            | нет         | да              |
| BSL156 | CodeOutOfRegion                              | CodeOutOfRegion                              | INFORMATION | да         | нет            | нет         | да              |
| BSL157 | CommitTransactionOutsideTryCatch             | CommitTransactionOutsideTryCatch             | ERROR       | да         | да             | нет         | да              |
| BSL158 | CommonModuleAssign                           | CommonModuleAssign                           | ERROR       | да         | нет            | нет         | да              |
| BSL159 | CommonModuleInvalidType                      | CommonModuleInvalidType                      | ERROR       | да         | нет            | нет         | да              |
| BSL160 | CommonModuleMissingAPI                       | CommonModuleMissingAPI                       | INFORMATION | да         | нет            | нет         | да              |
| BSL161 | CommonModuleNameCached                       | CommonModuleNameCached                       | INFORMATION | да         | нет            | нет         | да              |
| BSL162 | CommonModuleNameClient                       | CommonModuleNameClient                       | INFORMATION | да         | нет            | нет         | да              |
| BSL163 | CommonModuleNameClientServer                 | CommonModuleNameClientServer                 | INFORMATION | да         | нет            | нет         | да              |
| BSL164 | CommonModuleNameFullAccess                   | CommonModuleNameFullAccess                   | INFORMATION | да         | нет            | нет         | да              |
| BSL165 | CommonModuleNameGlobal                       | CommonModuleNameGlobal                       | INFORMATION | да         | нет            | нет         | да              |
| BSL166 | CommonModuleNameGlobalClient                 | CommonModuleNameGlobalClient                 | INFORMATION | да         | нет            | нет         | да              |
| BSL167 | CommonModuleNameServerCall                   | CommonModuleNameServerCall                   | INFORMATION | да         | нет            | нет         | да              |
| BSL168 | CommonModuleNameWords                        | CommonModuleNameWords                        | INFORMATION | да         | нет            | нет         | да              |
| BSL169 | CompilationDirectiveLost                     | CompilationDirectiveLost                     | ERROR       | да         | нет            | нет         | да              |
| BSL170 | CompilationDirectiveNeedLess                 | CompilationDirectiveNeedLess                 | INFORMATION | да         | нет            | нет         | да              |
| BSL171 | CrazyMultilineString                         | CrazyMultilineString                         | INFORMATION | да         | нет            | нет         | да              |
| BSL172 | DataExchangeLoading                          | DataExchangeLoading                          | WARNING     | да         | да             | нет         | да              |
| BSL173 | DeletingCollectionItem                       | DeletingCollectionItem                       | ERROR       | да         | да             | нет         | да              |
| BSL174 | DenyIncompleteValues                         | DenyIncompleteValues                         | WARNING     | да         | нет            | нет         | да              |
| BSL175 | DeprecatedAttributes8312                     | DeprecatedAttributes8312                     | WARNING     | да         | нет            | нет         | да              |
| BSL176 | DeprecatedMethodCall                         | DeprecatedMethodCall                         | WARNING     | да         | нет            | нет         | да              |
| BSL177 | DeprecatedMethods8310                        | DeprecatedMethods8310                        | INFORMATION | да         | нет            | нет         | да              |
| BSL178 | DeprecatedMethods8317                        | DeprecatedMethods8317                        | INFORMATION | да         | нет            | нет         | да              |
| BSL179 | DeprecatedTypeManagedForm                    | DeprecatedTypeManagedForm                    | WARNING     | да         | нет            | нет         | да              |
| BSL180 | DisableSafeMode                              | DisableSafeMode                              | WARNING     | да         | нет            | нет         | да              |
| BSL181 | DuplicatedInsertionIntoCollection            | DuplicatedInsertionIntoCollection            | WARNING     | да         | нет            | нет         | да              |
| BSL182 | ExcessiveAutoTestCheck                       | ExcessiveAutoTestCheck                       | INFORMATION | да         | нет            | нет         | да              |
| BSL183 | ExecuteExternalCode                          | ExecuteExternalCode                          | WARNING     | да         | да             | нет         | да              |
| BSL184 | ExecuteExternalCodeInCommonModule            | ExecuteExternalCodeInCommonModule            | WARNING     | да         | нет            | нет         | да              |
| BSL185 | ExternalAppStarting                          | ExternalAppStarting                          | WARNING     | да         | нет            | нет         | да              |
| BSL186 | ExtraCommas                                  | ExtraCommas                                  | WARNING     | да         | да             | нет         | да              |
| BSL187 | FieldsFromJoinsWithoutIsNull                 | FieldsFromJoinsWithoutIsNull                 | WARNING     | да         | нет            | нет         | да              |
| BSL188 | FileSystemAccess                             | FileSystemAccess                             | WARNING     | да         | нет            | нет         | да              |
| BSL189 | ForbiddenMetadataName                        | ForbiddenMetadataName                        | WARNING     | да         | нет            | нет         | да              |
| BSL190 | FormDataToValue                              | FormDataToValue                              | WARNING     | да         | нет            | нет         | да              |
| BSL191 | FullOuterJoinQuery                           | FullOuterJoinQuery                           | WARNING     | да         | нет            | нет         | да              |
| BSL192 | FunctionNameStartsWithGet                    | FunctionNameStartsWithGet                    | INFORMATION | да         | нет            | нет         | да              |
| BSL193 | FunctionOutParameter                         | FunctionOutParameter                         | WARNING     | да         | нет            | нет         | да              |
| BSL194 | FunctionReturnsSamePrimitive                 | FunctionReturnsSamePrimitive                 | INFORMATION | да         | нет            | нет         | да              |
| BSL195 | GetFormMethod                                | GetFormMethod                                | WARNING     | да         | нет            | нет         | да              |
| BSL196 | GlobalContextMethodCollision8312             | GlobalContextMethodCollision8312             | ERROR       | да         | нет            | нет         | да              |
| BSL197 | IfElseDuplicatedCodeBlock                    | IfElseDuplicatedCodeBlock                    | WARNING     | да         | да             | нет         | да              |
| BSL198 | IfElseDuplicatedCondition                    | IfElseDuplicatedCondition                    | WARNING     | да         | да             | нет         | да              |
| BSL199 | IfElseIfEndsWithElse                         | IfElseIfEndsWithElse                         | INFORMATION | да         | да             | нет         | да              |
| BSL200 | IncorrectLineBreak                           | IncorrectLineBreak                           | INFORMATION | да         | нет            | нет         | да              |
| BSL201 | IncorrectUseLikeInQuery                      | IncorrectUseLikeInQuery                      | WARNING     | да         | нет            | нет         | да              |
| BSL202 | IncorrectUseOfStrTemplate                    | IncorrectUseOfStrTemplate                    | ERROR       | да         | нет            | нет         | да              |
| BSL203 | InternetAccess                               | InternetAccess                               | WARNING     | да         | нет            | нет         | да              |
| BSL204 | InvalidCharacterInFile                       | InvalidCharacterInFile                       | WARNING     | да         | нет            | нет         | да              |
| BSL205 | IsInRoleMethod                               | IsInRoleMethod                               | WARNING     | да         | нет            | нет         | да              |
| BSL206 | JoinWithSubQuery                             | JoinWithSubQuery                             | WARNING     | да         | нет            | нет         | да              |
| BSL207 | JoinWithVirtualTable                         | JoinWithVirtualTable                         | WARNING     | да         | нет            | нет         | да              |
| BSL208 | LatinAndCyrillicSymbolInWord                 | LatinAndCyrillicSymbolInWord                 | WARNING     | да         | да             | нет         | да              |
| BSL209 | LogicalOrInJoinQuerySection                  | LogicalOrInJoinQuerySection                  | WARNING     | да         | нет            | нет         | да              |
| BSL210 | LogicalOrInTheWhereSectionOfQuery            | LogicalOrInTheWhereSectionOfQuery            | WARNING     | да         | нет            | нет         | да              |
| BSL211 | MetadataObjectNameLength                     | MetadataObjectNameLength                     | WARNING     | да         | нет            | нет         | да              |
| BSL212 | MissedRequiredParameter                      | MissedRequiredParameter                      | ERROR       | да         | нет            | нет         | да              |
| BSL213 | MissingCommonModuleMethod                    | MissingCommonModuleMethod                    | ERROR       | да         | нет            | нет         | да              |
| BSL214 | MissingEventSubscriptionHandler              | MissingEventSubscriptionHandler              | ERROR       | да         | нет            | нет         | да              |
| BSL215 | MissingParameterDescription                  | MissingParameterDescription                  | INFORMATION | да         | нет            | нет         | да              |
| BSL216 | MissingSpace                                 | MissingSpace                                 | INFORMATION | да         | да             | нет         | да              |
| BSL217 | MissingTempStorageDeletion                   | MissingTempStorageDeletion                   | WARNING     | да         | нет            | нет         | да              |
| BSL218 | MissingTemporaryFileDeletion                 | MissingTemporaryFileDeletion                 | WARNING     | да         | нет            | нет         | да              |
| BSL219 | MissingVariablesDescription                  | MissingVariablesDescription                  | INFORMATION | да         | да             | да          | нет             |
| BSL220 | MultilineStringInQuery                       | MultilineStringInQuery                       | INFORMATION | да         | нет            | нет         | да              |
| BSL221 | MultilingualStringHasAllDeclaredLanguages    | MultilingualStringHasAllDeclaredLanguages    | WARNING     | да         | нет            | нет         | да              |
| BSL222 | MultilingualStringUsingWithTemplate          | MultilingualStringUsingWithTemplate          | INFORMATION | да         | нет            | нет         | да              |
| BSL223 | NestedConstructorsInStructureDeclaration     | NestedConstructorsInStructureDeclaration     | INFORMATION | да         | нет            | нет         | да              |
| BSL224 | NestedFunctionInParameters                   | NestedFunctionInParameters                   | INFORMATION | да         | нет            | нет         | да              |
| BSL225 | NumberOfValuesInStructureConstructor         | NumberOfValuesInStructureConstructor         | INFORMATION | да         | нет            | нет         | да              |
| BSL226 | OSUsersMethod                                | OSUsersMethod                                | WARNING     | да         | нет            | нет         | да              |
| BSL227 | OneStatementPerLine                          | OneStatementPerLine                          | INFORMATION | да         | да             | нет         | да              |
| BSL228 | OrderOfParams                                | OrderOfParams                                | INFORMATION | да         | нет            | нет         | да              |
| BSL229 | OrdinaryAppSupport                           | OrdinaryAppSupport                           | WARNING     | да         | нет            | нет         | да              |
| BSL230 | PairingBrokenTransaction                     | PairingBrokenTransaction                     | ERROR       | да         | да             | нет         | да              |
| BSL231 | PrivilegedModuleMethodCall                   | PrivilegedModuleMethodCall                   | WARNING     | да         | нет            | нет         | да              |
| BSL232 | ProtectedModule                              | ProtectedModule                              | INFORMATION | да         | нет            | нет         | да              |
| BSL233 | PublicMethodsDescription                     | PublicMethodsDescription                     | INFORMATION | да         | нет            | нет         | да              |
| BSL234 | QueryNestedFieldsByDot                       | QueryNestedFieldsByDot                       | WARNING     | да         | нет            | нет         | да              |
| BSL235 | QueryParseError                              | QueryParseError                              | ERROR       | да         | нет            | нет         | да              |
| BSL236 | QueryToMissingMetadata                       | QueryToMissingMetadata                       | ERROR       | да         | нет            | нет         | да              |
| BSL237 | RedundantAccessToObject                      | RedundantAccessToObject                      | INFORMATION | да         | нет            | нет         | да              |
| BSL238 | RefOveruse                                   | RefOveruse                                   | INFORMATION | да         | нет            | нет         | да              |
| BSL239 | ReservedParameterNames                       | ReservedParameterNames                       | WARNING     | да         | нет            | нет         | да              |
| BSL240 | RewriteMethodParameter                       | RewriteMethodParameter                       | WARNING     | да         | да             | нет         | да              |
| BSL241 | SameMetadataObjectAndChildNames              | SameMetadataObjectAndChildNames              | WARNING     | да         | нет            | нет         | да              |
| BSL242 | ScheduledJobHandler                          | ScheduledJobHandler                          | ERROR       | да         | нет            | нет         | да              |
| BSL243 | SelfInsertion                                | SelfInsertion                                | ERROR       | да         | нет            | нет         | да              |
| BSL244 | ServerCallsInFormEvents                      | ServerCallsInFormEvents                      | WARNING     | да         | нет            | нет         | да              |
| BSL245 | ServerSideExportFormMethod                   | ServerSideExportFormMethod                   | WARNING     | да         | нет            | нет         | да              |
| BSL246 | SetPermissionsForNewObjects                  | SetPermissionsForNewObjects                  | WARNING     | да         | нет            | нет         | да              |
| BSL247 | SetPrivilegedMode                            | SetPrivilegedMode                            | WARNING     | да         | нет            | нет         | да              |
| BSL248 | SeveralCompilerDirectives                    | SeveralCompilerDirectives                    | ERROR       | да         | нет            | нет         | да              |
| BSL249 | StyleElementConstructors                     | StyleElementConstructors                     | INFORMATION | да         | нет            | нет         | да              |
| BSL250 | TempFilesDir                                 | TempFilesDir                                 | WARNING     | да         | нет            | нет         | да              |
| BSL251 | TernaryOperatorUsage                         | TernaryOperatorUsage                         | INFORMATION | да         | нет            | нет         | да              |
| BSL252 | ThisObjectAssign                             | ThisObjectAssign                             | ERROR       | да         | нет            | нет         | да              |
| BSL253 | TimeoutsInExternalResources                  | TimeoutsInExternalResources                  | WARNING     | да         | нет            | нет         | да              |
| BSL254 | TransferringParametersBetweenClientAndServer | TransferringParametersBetweenClientAndServer | WARNING     | да         | нет            | нет         | да              |
| BSL255 | TryNumber                                    | TryNumber                                    | WARNING     | да         | да             | нет         | да              |
| BSL256 | Typo                                         | Typo                                         | INFORMATION | да         | да             | да          | нет             |
| BSL257 | UnaryPlusInConcatenation                     | UnaryPlusInConcatenation                     | WARNING     | да         | да             | нет         | да              |
| BSL258 | UnionAll                                     | UnionAll                                     | WARNING     | да         | да             | нет         | да              |
| BSL259 | UnknownPreprocessorSymbol                    | UnknownPreprocessorSymbol                    | WARNING     | да         | нет            | нет         | да              |
| BSL260 | UnsafeFindByCode                             | UnsafeFindByCode                             | WARNING     | да         | нет            | нет         | да              |
| BSL261 | UnsafeSafeModeMethodCall                     | UnsafeSafeModeMethodCall                     | WARNING     | да         | нет            | нет         | да              |
| BSL262 | UsageWriteLogEvent                           | UsageWriteLogEvent                           | WARNING     | да         | нет            | нет         | да              |
| BSL263 | UseLessForEach                               | UseLessForEach                               | WARNING     | да         | да             | нет         | да              |
| BSL264 | UseSystemInformation                         | UseSystemInformation                         | WARNING     | да         | нет            | нет         | да              |
| BSL265 | UselessTernaryOperator                       | UselessTernaryOperator                       | WARNING     | да         | да             | нет         | да              |
| BSL266 | UsingCancelParameter                         | UsingCancelParameter                         | WARNING     | да         | нет            | нет         | да              |
| BSL267 | UsingExternalCodeTools                       | UsingExternalCodeTools                       | WARNING     | да         | нет            | нет         | да              |
| BSL268 | UsingFindElementByString                     | UsingFindElementByString                     | WARNING     | да         | нет            | нет         | да              |
| BSL269 | UsingLikeInQuery                             | UsingLikeInQuery                             | INFORMATION | да         | нет            | нет         | да              |
| BSL270 | UsingModalWindows                            | UsingModalWindows                            | WARNING     | да         | нет            | нет         | да              |
| BSL271 | UsingObjectNotAvailableUnix                  | UsingObjectNotAvailableUnix                  | WARNING     | да         | нет            | нет         | да              |
| BSL272 | UsingSynchronousCalls                        | UsingSynchronousCalls                        | WARNING     | да         | нет            | нет         | да              |
| BSL273 | VirtualTableCallWithoutParameters            | VirtualTableCallWithoutParameters            | WARNING     | да         | нет            | нет         | да              |
| BSL274 | WrongDataPathForFormElements                 | WrongDataPathForFormElements                 | ERROR       | да         | нет            | нет         | да              |
| BSL275 | WrongHttpServiceHandler                      | WrongHttpServiceHandler                      | ERROR       | да         | нет            | нет         | да              |
| BSL276 | WrongUseFunctionProceedWithCall              | WrongUseFunctionProceedWithCall              | ERROR       | да         | нет            | нет         | да              |
| BSL277 | WrongUseOfRollbackTransactionMethod          | WrongUseOfRollbackTransactionMethod          | ERROR       | да         | нет            | нет         | да              |
| BSL278 | WrongWebServiceHandler                       | WrongWebServiceHandler                       | ERROR       | да         | нет            | нет         | да              |
| BSL279 | YoLetterUsage                                | YoLetterUsage                                | INFORMATION | да         | да             | нет         | да              |
| BSL280 | UnknownMetadataObjectReference               | UnknownMetadataObjectReference               | WARNING     | нет        | да             | да          | нет             |


## Описание (кратко) по коду

- **BSL001** (`ParseError`): Syntax error detected by the BSL parser
- **BSL002** (`MethodSize`): Procedure or function exceeds maximum allowed length
- **BSL003** (`NonExportMethodsInApiRegion`): Method in public API region is not marked as Export
- **BSL004** (`EmptyCodeBlock`): Empty exception handler — errors are silently swallowed
- **BSL005** (`UsingHardcodeNetworkAddress`): Hardcoded IP address or URL found in source
- **BSL006** (`UsingHardcodePath`): Hardcoded file-system path found in source
- **BSL007** (`UnusedLocalVariable`): Local variable is declared but never referenced
- **BSL008** (`TooManyReturns`): Method has more return statements than the allowed maximum
- **BSL009** (`SelfAssign`): Variable is assigned to itself — likely a copy-paste error
- **BSL010** (`UselessReturn`): Redundant Возврат statement at the very end of a Procedure
- **BSL011** (`CognitiveComplexity`): Method cognitive complexity exceeds the allowed threshold
- **BSL012** (`UsingHardcodeSecretInformation`): Possible hardcoded password, token, or secret
- **BSL013** (`CommentedCode`): Block of commented-out source code detected
- **BSL014** (`LineLength`): Line exceeds the maximum allowed length
- **BSL015** (`NumberOfOptionalParams`): Too many optional (default-value) parameters in one method
- **BSL016** (`NonStandardRegion`): Region name is not in the standard BSL region vocabulary
- **BSL017** (`CommandModuleExportMethods`): Export modifier should not be used in command or form modules
- **BSL019** (`CyclomaticComplexity`): Method McCabe cyclomatic complexity exceeds the allowed threshold
- **BSL020** (`NestedStatements`): Code block nesting depth exceeds the allowed maximum
- **BSL021** (`UnusedValParameter`): Value parameter (Знач/Val) is never read inside the method body
- **BSL022** (`DeprecatedMessage`): Предупреждение()/Warning() is a deprecated modal dialog — use status bar messaging instead
- **BSL023** (`UsingServiceTag`): Service tag (TODO/FIXME/HACK/КЕЙС) found — should be resolved or linked to a ticket
- **BSL024** (`SpaceAtStartComment`): Comment text should start with a space after '//'
- **BSL025** (`EmptyStatement`): Statement is not terminated with a semicolon
- **BSL026** (`EmptyRegion`): #Область/#Region block contains no executable code
- **BSL027** (`UsingGoto`): Перейти/Goto statement makes control flow hard to follow
- **BSL028** (`MissingCodeTryCatchEx`): Method body contains no error handling (Try/Except) for potentially risky operations
- **BSL029** (`MagicNumber`): Magic number literal used directly in code — extract it to a named constant
- **BSL030** (`SemicolonPresence`): Procedure/function header line ends with a semicolon (not needed in BSL)
- **BSL031** (`NumberOfParams`): Method has too many parameters (including required ones)
- **BSL032** (`FunctionShouldHaveReturn`): Function may exit without returning a value (missing Возврат)
- **BSL033** (`CreateQueryInCycle`): Query execution inside a loop — severe performance risk in 1C
- **BSL034** (`UnusedErrorVariable`): ИнформацияОбОшибке()/ErrorInfo() result assigned but never used
- **BSL035** (`DuplicateStringLiteral`): String literal is duplicated — extract to a constant
- **BSL036** (`IfConditionComplexity`): Condition expression has too many boolean operators
- **BSL037** (`OverrideBuiltinMethod`): Method name shadows a 1C platform built-in function
- **BSL038** (`StringConcatenationInLoop`): String concatenation operator '+' inside a loop — use StrTemplate or array join
- **BSL039** (`NestedTernaryOperator`): Nested ternary ?() expression reduces readability
- **BSL040** (`UsingThisForm`): Direct use of ЭтаФорма/ThisForm outside event handlers is fragile
- **BSL041** (`NotifyDescriptionToModalWindow`): ОписаниеОповещения/NotifyDescription call with modal window is deprecated
- **BSL042** (`UnusedLocalMethod`): Exported method has no meaningful body (empty stub)
- **BSL043** (`TooManyVariables`): Method declares too many local variables (default >15)
- **BSL044** (`FunctionNoReturnValue`): Exported Function contains no explicit Возврат/Return with a value
- **BSL045** (`MultilineStringLiteral`): Multi-line string via repeated concatenation — use | continuation instead
- **BSL046** (`MissingElseBranch`): If…ElseIf chain has no Else branch — unhandled case may hide bugs
- **BSL047** (`MagicDate`): ТекущаяДата()/CurrentDate() returns local server time — use CurrentUniversalDate() for UTC-safe code
- **BSL048** (`EmptyFile`): BSL file contains no executable code (empty or comments only)
- **BSL050** (`LargeTransaction`): НачатьТранзакцию/BeginTransaction without close-by ЗафиксироватьТранзакцию/CommitTransaction may leave transaction open
- **BSL051** (`UnreachableCode`): Code after an unconditional Возврат/Return or ВызватьИсключение/Raise is unreachable
- **BSL052** (`IdenticalExpressions`): Condition is always True or always False (literal Истина/Ложь/True/False)
- **BSL053** (`ExecuteExternalCode`): Выполнить()/Execute() runs dynamically constructed code — security and maintenance risk
- **BSL054** (`ExportVariables`): Module-level Перем/Var declaration creates shared mutable state — prefer local variables
- **BSL055** (`ConsecutiveEmptyLines`): More than 2 consecutive blank lines reduce readability
- **BSL056** (`ShortMethodName`): Method name is too short (< 3 characters) — use a descriptive name
- **BSL057** (`DeprecatedInputDialog`): ВвестиЗначение/ВвестиЧисло/ВвестиДату/ВвестиСтроку are synchronous modal dialogs deprecated in 8.3
- **BSL058** (`QueryWithoutWhere`): Embedded query text has no WHERE clause — may return all rows and cause performance issues
- **BSL059** (`BooleanLiteralComparison`): Comparison to boolean literal (А = Истина / А = Ложь) — use the expression directly
- **BSL060** (`DoubleNegatives`): НЕ НЕ expression — double negation cancels out, use the expression directly
- **BSL061** (`AbruptLoopExit`): Прервать/Break as the last statement of a loop body — consider restructuring the condition
- **BSL062** (`UnusedParameters`): Procedure/function parameter is never referenced in the method body
- **BSL063** (`LargeModule`): Module file exceeds the maximum allowed line count
- **BSL064** (`ProcedureReturnsValue`): Procedure (Процедура) contains 'Возврат ' — should be declared as Function
- **BSL065** (`MissingReturnedValueDescription`): Exported method has no preceding description comment (// or ///)
- **BSL066** (`DeprecatedFind`): Call to a deprecated 1C platform method that has a modern replacement
- **BSL067** (`VarDeclarationAfterCode`): Перем variable declaration appears after executable code — move it to the top
- **BSL068** (`TooManyElseIf`): Если/ИначеЕсли chain has too many branches — consider a map or pattern
- **BSL069** (`InfiniteLoop`): Пока Истина Цикл without a Прервать — potential infinite loop
- **BSL070** (`EmptyLoopBody`): Loop body contains no executable statements (empty loop)
- **BSL071** (`MagicNumber`): Magic number literal used directly in code — extract to a named constant
- **BSL072** (`StringConcatenationInLoop`): String concatenation with '+' inside a loop — use an array and StrConcat
- **BSL073** (`MissingElseBranch`): Если/If statement has no Иначе/Else branch — may miss unexpected values
- **BSL074** (`TodoComment`): TODO/FIXME/HACK comment found — unresolved technical debt
- **BSL075** (`ExportVariables`): Method modifies a module-level variable — prefer explicit parameters/return
- **BSL076** (`NegativeConditionFirst`): Condition starts with НЕ/Not — prefer positive form for readability
- **BSL077** (`SelectTopWithoutOrderBy`): SELECT */ВЫБРАТЬ * in a query — enumerate columns explicitly
- **BSL078** (`RaiseWithoutMessage`): ВызватьИсключение/Raise without a message — provide context for the error
- **BSL079** (`UsingGoto`): Goto/Перейти statement found — avoid unstructured control flow
- **BSL080** (`EmptyCodeBlock`): Exception handler ignores the error — no ИнформацияОбОшибке or re-raise
- **BSL081** (`LongMethodChain`): Method call chain is too long — split into intermediate variables
- **BSL082** (`MissingNewlineAtEndOfFile`): File does not end with a newline character
- **BSL083** (`TooManyModuleVariables`): Module has too many module-level Перем declarations — encapsulate in a structure
- **BSL084** (`FunctionShouldHaveReturn`): Функция/Function has no Возврат with a value — should be Процедура
- **BSL085** (`IdenticalExpressions`): Если Истина/Ложь Тогда — constant condition always true or false
- **BSL086** (`HttpRequestInLoop`): HTTP request call inside a loop — batch requests or move outside
- **BSL087** (`ObjectCreationInLoop`): Новый/New object creation inside a loop — consider moving outside
- **BSL088** (`MissingReturnedValueDescription`): Export method has parameters but no // Parameters: comment in header
- **BSL089** (`TransactionInLoop`): НачатьТранзакцию/BeginTransaction called inside a loop — move outside
- **BSL090** (`UsingHardcodeSecretInformation`): Hardcoded database connection string or DSN in source code
- **BSL091** (`RedundantElseAfterReturn`): Иначе/Else after Возврат/Return is redundant — remove the Else block
- **BSL092** (`EmptyCodeBlock`): Empty Иначе/Else block — remove it or add a comment explaining intent
- **BSL093** (`ComparisonToNull`): Use 'Значение = Неопределено' or 'ЗначениеЗаполнено()' instead of comparison to Null/NULL
- **BSL094** (`SelfAssign`): Compound assignment where left and right sides match (А += 0, А *= 1)
- **BSL095** (`MultipleStatementsOnOneLine`): Two or more executable statements on a single line — split into separate lines
- **BSL096** (`MissingReturnedValueDescription`): Export method has no preceding comment block
- **BSL097** (`DeprecatedCurrentDate`): ТекущаяДата()/CurrentDate() returns server time — use ТекущаяДатаСеанса() for session time
- **BSL098** (`UseOfExecute`): Выполнить()/Execute() executes code from a string — security and maintainability risk
- **BSL099** (`NumberOfParams`): Procedure/function has too many parameters — split into a structure or separate methods
- **BSL100** (`UsingHardcodePath`): Hardcoded file path in a string literal — use a parameter or configuration value
- **BSL101** (`NestedStatements`): Code nesting depth exceeds the allowed maximum — refactor into smaller functions
- **BSL102** (`LargeModule`): Module exceeds the maximum allowed number of lines — split into smaller modules
- **BSL103** (`UseOfEval`): Вычислить()/Eval() evaluates a dynamic expression — security and maintainability risk
- **BSL104** (`MissingModuleComment`): Module has no comment header at the top — add a description of its purpose
- **BSL105** (`UseOfSleep`): Приостановить()/Sleep() blocks the current thread — avoid in server-side code
- **BSL106** (`CreateQueryInCycle`): SQL query (ВЫБРАТЬ/SELECT) inside a loop — move outside the loop or use batch queries
- **BSL107** (`EmptyCodeBlock`): Empty Тогда branch in Если statement — remove the branch or add meaningful code
- **BSL108** (`ExportVariables`): Module-level exported variable — avoid mutable shared state
- **BSL109** (`NegativeConditionalReturn`): Если НЕ ... Тогда Возврат — invert the condition to reduce nesting
- **BSL110** (`StringConcatInLoop`): String concatenation inside a loop — use a list and join instead
- **BSL111** (`MixedLanguageIdentifiers`): Identifier mixes Cyrillic and Latin characters — use one script consistently
- **BSL112** (`UnterminatedTransaction`): НачатьТранзакцию() without matching ЗафиксироватьТранзакцию/ОтменитьТранзакцию
- **BSL113** (`AssignmentInCondition`): Assignment operator inside an Если condition — likely a typo for comparison
- **BSL114** (`EmptyModule`): Module contains no executable code — remove or populate it
- **BSL115** (`DoubleNegatives`): Double negation НЕ НЕ — simplify to the positive condition
- **BSL116** (`UseOfObsoleteIterator`): Use of obsolete iteration pattern — prefer ДляКаждого/ForEach
- **BSL117** (`ProcedureCalledAsFunction`): Result of a procedure call is used in an expression — procedures do not return values
- **BSL118** (`FunctionShouldHaveReturn`): Функция body has no Возврат with a value — returns Неопределено implicitly
- **BSL119** (`LineLength`): Line length exceeds 120 characters — split into multiple lines
- **BSL120** (`TrailingWhitespace`): Line has trailing whitespace — remove for consistent diffs
- **BSL121** (`TabIndentation`): Tab character used for indentation — use spaces for consistent formatting
- **BSL122** (`UnusedParameters`): Parameter declared in the signature is never referenced in the body
- **BSL123** (`CommentedCode`): Comment line appears to contain commented-out code — remove or restore
- **BSL124** (`ShortProcedureName`): Procedure/function name is shorter than 3 characters — use a descriptive name
- **BSL125** (`UseOfAbortOutsideLoop`): Прервать/Break used outside a loop — has no effect or causes an error
- **BSL126** (`UseOfContinueOutsideLoop`): Продолжить/Continue used outside a loop — has no effect or causes an error
- **BSL127** (`MultipleReturnValues`): Multiple Возврат statements at the same nesting level — consolidate to one exit point
- **BSL128** (`UnreachableCode`): Unreachable code after unconditional Возврат at the top level of a function/procedure body
- **BSL129** (`RecursiveCall`): Function/procedure directly calls itself — verify that recursion is intentional and guarded
- **BSL130** (`LineLength`): Comment line exceeds 120 characters — split into multiple shorter lines
- **BSL131** (`EmptyRegion`): #Область/#Region immediately followed by #КонецОбласти/#EndRegion with no code inside
- **BSL132** (`DuplicateStringLiteral`): String literal appears 4 or more times in the file — extract to a named constant
- **BSL133** (`RequiredParamAfterOptional`): Required parameter appears after an optional (default-valued) parameter in the signature
- **BSL134** (`CyclomaticComplexity`): Cyclomatic complexity exceeds the allowed maximum — refactor into smaller functions
- **BSL135** (`NestedFunctionCalls`): Function call result passed directly as argument to another function — extract to a variable
- **BSL136** (`MissingSpaceBeforeComment`): Inline // comment is not preceded by a space — add a space for readability
- **BSL137** (`UseOfFindByDescription`): НайтиПоНаименованию/FindByDescription performs a full-table scan — use an index or НайтиПоСсылке
- **BSL138** (`UseOfDebugOutput`): Сообщить()/Message()/Предупреждение() debug output should not be in production code
- **BSL139** (`TooLongParameterName`): Parameter name is longer than 30 characters — shorten it for readability
- **BSL140** (`UnreachableElseIf`): ИначеЕсли/ElsIf branch appears after an unconditional Иначе/Else — it can never be reached
- **BSL141** (`MagicBooleanReturn`): Function returns literal Истина/Ложь — replace with a direct boolean expression
- **BSL142** (`LargeParameterDefaultValue`): Default parameter value is longer than 50 characters — move to a named constant
- **BSL143** (`DuplicateElseIfCondition`): The same condition appears more than once in an Если/ИначеЕсли chain
- **BSL144** (`UnnecessaryParentheses`): Return value is wrapped in redundant parentheses — remove them
- **BSL145** (`StringFormatInsteadOfConcat`): Three or more string parts joined with '+' — use СтрШаблон()/StrTemplate() instead
- **BSL146** (`ModuleInitializationCode`): Executable code at module level outside procedures — move to an Инициализация() procedure
- **BSL147** (`UseOfUICall`): ОткрытьФорму()/OpenForm() UI calls should not appear in server-side code
- **BSL148** (`AllFunctionPathMustHaveReturn`): Not all code paths in the function have a return statement
- **BSL149** (`AssignAliasFieldsInQuery`): Query fields should be assigned aliases for clarity
- **BSL150** (`BadWords`): Inappropriate or forbidden words found in source code
- **BSL151** (`BeginTransactionBeforeTryCatch`): НачатьТранзакцию/BeginTransaction must be placed immediately before a Try/Except block
- **BSL152** (`CachedPublic`): Export method in a cached common module — caching and export conflict
- **BSL153** (`CanonicalSpellingKeywords`): BSL keyword is not written in canonical (title-case) form
- **BSL154** (`CodeAfterAsyncCall`): Executable code follows an asynchronous call — result may be lost
- **BSL155** (`CodeBlockBeforeSub`): Executable code appears before procedure/function definitions (module body)
- **BSL156** (`CodeOutOfRegion`): Code is located outside any #Region/#Область block
- **BSL157** (`CommitTransactionOutsideTryCatch`): ЗафиксироватьТранзакцию/CommitTransaction must be inside a Try/Except block
- **BSL158** (`CommonModuleAssign`): Common module object is assigned a value — this is always an error
- **BSL159** (`CommonModuleInvalidType`): Common module has incompatible type flags (e.g. Global + Privileged)
- **BSL160** (`CommonModuleMissingAPI`): Common module has no exported methods — consider making it non-public
- **BSL161** (`CommonModuleNameCached`): Cached common module name does not match naming convention
- **BSL162** (`CommonModuleNameClient`): Client common module name does not match naming convention
- **BSL163** (`CommonModuleNameClientServer`): Client-server common module name does not match naming convention
- **BSL164** (`CommonModuleNameFullAccess`): Full-access (privileged) common module name does not match naming convention
- **BSL165** (`CommonModuleNameGlobal`): Global common module name does not match naming convention
- **BSL166** (`CommonModuleNameGlobalClient`): Global client common module name does not match naming convention
- **BSL167** (`CommonModuleNameServerCall`): Server-call common module name does not match naming convention
- **BSL168** (`CommonModuleNameWords`): Common module name uses forbidden words
- **BSL169** (`CompilationDirectiveLost`): Compilation directive on the method is missing or differs from calling context
- **BSL170** (`CompilationDirectiveNeedLess`): Redundant compilation directive on the method
- **BSL171** (`CrazyMultilineString`): Multiline string literal uses inconsistent indentation
- **BSL172** (`DataExchangeLoading`): Modification handlers do not check ОбменДаннымиЗагрузка/DataExchangeLoad flag
- **BSL173** (`DeletingCollectionItem`): Collection item is deleted inside a Для Каждого/For Each loop — may cause errors
- **BSL174** (`DenyIncompleteValues`): НачатьТранзакцию used without ОтменитьТранзакцию in error path
- **BSL175** (`DeprecatedAttributes8312`): Deprecated platform attribute used (removed in 8.3.12+)
- **BSL176** (`DeprecatedMethodCall`): Deprecated platform method called — use the modern replacement
- **BSL177** (`DeprecatedMethods8310`): Platform method deprecated since 8.3.10
- **BSL178** (`DeprecatedMethods8317`): Platform method deprecated since 8.3.17
- **BSL179** (`DeprecatedTypeManagedForm`): Deprecated type УправляемаяФорма/ManagedForm used directly
- **BSL180** (`DisableSafeMode`): УстановитьБезопасныйРежим(Ложь)/SetSafeMode(False) disables security sandbox
- **BSL181** (`DuplicatedInsertionIntoCollection`): The same element is inserted into the collection more than once
- **BSL182** (`ExcessiveAutoTestCheck`): АвтоТестПроверка check is excessive or incorrectly placed
- **BSL183** (`ExecuteExternalCode`): Выполнить()/Execute() runs arbitrary external code — security risk
- **BSL184** (`ExecuteExternalCodeInCommonModule`): Dynamic code execution (Выполнить/Execute) inside a common module
- **BSL185** (`ExternalAppStarting`): ЗапуститьПриложение()/StartApplication() launches external processes
- **BSL186** (`ExtraCommas`): Trailing or extra comma in method call or declaration
- **BSL187** (`FieldsFromJoinsWithoutIsNull`): Fields from outer joins used without ЕСТЬ NULL/IS NULL check
- **BSL188** (`FileSystemAccess`): Direct file system access — may fail in web client or thin client contexts
- **BSL189** (`ForbiddenMetadataName`): Metadata object name is in the list of forbidden names
- **BSL190** (`FormDataToValue`): ДанныеФормыВЗначение()/FormDataToValue() is slow — prefer working with server objects directly
- **BSL191** (`FullOuterJoinQuery`): Full outer join (ПОЛНОЕ ВНЕШНЕЕ/FULL OUTER JOIN) in query — usually a design mistake
- **BSL192** (`FunctionNameStartsWithGet`): Function name should start with 'Получить'/'Get' to indicate it returns a value
- **BSL193** (`FunctionOutParameter`): Function modifies a reference parameter (out-parameter) — use a Procedure instead
- **BSL194** (`FunctionReturnsSamePrimitive`): Function always returns the same primitive value — it may be simplified
- **BSL195** (`GetFormMethod`): ПолучитьФорму()/GetForm() usage is deprecated — open forms via OpenForm()
- **BSL196** (`GlobalContextMethodCollision8312`): Method name collides with a global context method added in 8.3.12
- **BSL197** (`IfElseDuplicatedCodeBlock`): Identical code block appears in multiple branches of If/ElseIf
- **BSL198** (`IfElseDuplicatedCondition`): Duplicate condition in If/ElseIf chain — branch is unreachable
- **BSL199** (`IfElseIfEndsWithElse`): If/ElseIf chain does not end with an Else branch
- **BSL200** (`IncorrectLineBreak`): Line break character used incorrectly or inconsistently
- **BSL201** (`IncorrectUseLikeInQuery`): ПОДОБНО/LIKE pattern in query is written incorrectly
- **BSL202** (`IncorrectUseOfStrTemplate`): СтрШаблон()/StrTemplate() is called with mismatched argument count
- **BSL203** (`InternetAccess`): Direct internet access — should be isolated or proxied for security
- **BSL204** (`InvalidCharacterInFile`): File contains invalid or non-printable characters
- **BSL205** (`IsInRoleMethod`): РольДоступна()/IsInRole() is used — prefer permission-based access control
- **BSL206** (`JoinWithSubQuery`): Query join uses a subquery — may cause poor performance
- **BSL207** (`JoinWithVirtualTable`): Query join with a virtual table without parameters — may return too many rows
- **BSL208** (`LatinAndCyrillicSymbolInWord`): Identifier contains both Latin and Cyrillic characters — visually ambiguous
- **BSL209** (`LogicalOrInJoinQuerySection`): Logical OR (ИЛИ/OR) in JOIN ON condition — causes performance issues
- **BSL210** (`LogicalOrInTheWhereSectionOfQuery`): Logical OR (ИЛИ/OR) in WHERE clause may prevent index usage
- **BSL211** (`MetadataObjectNameLength`): Metadata object name exceeds maximum allowed length
- **BSL212** (`MissedRequiredParameter`): Required parameter is missing in method call
- **BSL213** (`MissingCommonModuleMethod`): Called method does not exist in the referenced common module
- **BSL214** (`MissingEventSubscriptionHandler`): Event subscription references a handler method that does not exist
- **BSL215** (`MissingParameterDescription`): Export method parameter has no description in the comment block
- **BSL216** (`MissingSpace`): Missing space before or after an operator or keyword
- **BSL217** (`MissingTempStorageDeletion`): Temporary storage (УдалитьИзВременногоХранилища) is not deleted after use
- **BSL218** (`MissingTemporaryFileDeletion`): Temporary file created with GetTempFileName is not deleted after use
- **BSL219** (`MissingVariablesDescription`): Module-level variable declaration has no description comment
- **BSL220** (`MultilineStringInQuery`): Multiline string literal used inside a query text
- **BSL221** (`MultilingualStringHasAllDeclaredLanguages`): НСтр() string does not include all languages declared in the configuration
- **BSL222** (`MultilingualStringUsingWithTemplate`): НСтр() is used inside СтрШаблон() — localized strings should be composed differently
- **BSL223** (`NestedConstructorsInStructureDeclaration`): Structure constructor contains nested constructors — hard to read and maintain
- **BSL224** (`NestedFunctionInParameters`): Function call is used as an argument to another function — reduces readability
- **BSL225** (`NumberOfValuesInStructureConstructor`): Структура/Structure constructor has too many initial values
- **BSL226** (`OSUsersMethod`): ПользователиОС()/OSUsers() is used — OS user enumeration is a security concern
- **BSL227** (`OneStatementPerLine`): Multiple statements on one line — reduces readability
- **BSL228** (`OrderOfParams`): Method parameter order does not follow the agreed convention
- **BSL229** (`OrdinaryAppSupport`): Code uses API not supported in Ordinary (thick) application mode
- **BSL230** (`PairingBrokenTransaction`): НачатьТранзакцию/ЗафиксироватьТранзакцию/ОтменитьТранзакцию calls are unbalanced
- **BSL231** (`PrivilegedModuleMethodCall`): Method from a privileged module is called from a non-privileged context
- **BSL232** (`ProtectedModule`): Module is protected (ЗащищенныйМодуль) — source is not accessible
- **BSL233** (`PublicMethodsDescription`): Exported method has no documentation comment
- **BSL234** (`QueryNestedFieldsByDot`): Nested (dot-notation) field access in query text — causes implicit joins
- **BSL235** (`QueryParseError`): Embedded query text has a syntax error
- **BSL236** (`QueryToMissingMetadata`): Query references a metadata object that does not exist in the configuration
- **BSL237** (`RedundantAccessToObject`): Redundant object access — intermediate result is not used
- **BSL238** (`RefOveruse`): Excessive use of .Ссылка/.Ref — retrieve the object once and reuse
- **BSL239** (`ReservedParameterNames`): Parameter name shadows a built-in platform identifier
- **BSL240** (`RewriteMethodParameter`): Method parameter is overwritten before being read — likely a mistake
- **BSL241** (`SameMetadataObjectAndChildNames`): Metadata object and its child (attribute/tabular section) share the same name
- **BSL242** (`ScheduledJobHandler`): Scheduled job handler method has incorrect signature or is missing
- **BSL243** (`SelfInsertion`): Object is inserted into itself — causes infinite recursion or error
- **BSL244** (`ServerCallsInFormEvents`): Server call inside a client form event handler without &НаКлиентеНаСервере
- **BSL245** (`ServerSideExportFormMethod`): Form module export method is marked &НаСервере — inaccessible from client
- **BSL246** (`SetPermissionsForNewObjects`): НастройкаПравДоступаДляНовыхОбъектов is called incorrectly
- **BSL247** (`SetPrivilegedMode`): УстановитьПривилегированныйРежим(Истина)/SetPrivilegedMode(True) elevates permissions
- **BSL248** (`SeveralCompilerDirectives`): Method has multiple conflicting compilation directives
- **BSL249** (`StyleElementConstructors`): Style element is created with a constructor instead of using built-in styles
- **BSL250** (`TempFilesDir`): КаталогВременныхФайлов()/TempFilesDir() used — may cause issues in web context
- **BSL251** (`TernaryOperatorUsage`): Ternary operator (?(cond, true, false)) reduces readability — consider If/Else
- **BSL252** (`ThisObjectAssign`): ЭтотОбъект/ThisObject is assigned a value — always an error
- **BSL253** (`TimeoutsInExternalResources`): External resource access has no timeout set — may hang indefinitely
- **BSL254** (`TransferringParametersBetweenClientAndServer`): Large or non-serializable object is passed between client and server
- **BSL255** (`TryNumber`): Numeric conversion inside Попытка/Try — exception obscures conversion errors
- **BSL256** (`Typo`): Possible spelling mistake found in comments or string literals
- **BSL257** (`UnaryPlusInConcatenation`): Unary plus (+) before a value in string concatenation — usually a mistake
- **BSL258** (`UnionAll`): ОБЪЕДИНИТЬ/UNION without ALL causes implicit deduplication — use UNION ALL
- **BSL259** (`UnknownPreprocessorSymbol`): Unknown preprocessor symbol used in #Если/#If directive
- **BSL260** (`UnsafeFindByCode`): НайтиПоКоду()/FindByCode() is called without existence check — may return Undefined
- **BSL261** (`UnsafeSafeModeMethodCall`): Safe-mode method called in a context where it may not be available
- **BSL262** (`UsageWriteLogEvent`): ЗаписьЖурналаРегистрации/WriteLogEvent called with incorrect parameters
- **BSL263** (`UseLessForEach`): Для Каждого/For Each loop body does nothing useful with the iteration variable
- **BSL264** (`UseSystemInformation`): СистемнаяИнформация()/SystemInformation() exposes sensitive system data
- **BSL265** (`UselessTernaryOperator`): Ternary operator returns its condition directly — simplify to the condition
- **BSL266** (`UsingCancelParameter`): Параметр «Отказ»/Cancel is modified but not checked correctly in the handler
- **BSL267** (`UsingExternalCodeTools`): External code execution tools (AddIn, COM, WSProxy) are used
- **BSL268** (`UsingFindElementByString`): НайтиПоНаименованию()/FindByDescription() used — slow full-text search
- **BSL269** (`UsingLikeInQuery`): ПОДОБНО/LIKE operator in query — may prevent index usage and cause full scans
- **BSL270** (`UsingModalWindows`): Modal window (Предупреждение, Вопрос, ВвестиЗначение) used in managed UI
- **BSL271** (`UsingObjectNotAvailableUnix`): Object or method not available on Linux/Unix server
- **BSL272** (`UsingSynchronousCalls`): Synchronous call to a server method — should be async in managed UI
- **BSL273** (`VirtualTableCallWithoutParameters`): Virtual table (e.g. РегистрНакопления.Остатки) called without parameters
- **BSL274** (`WrongDataPathForFormElements`): Form element data path references a non-existent attribute
- **BSL275** (`WrongHttpServiceHandler`): HTTP service handler method has incorrect signature
- **BSL276** (`WrongUseFunctionProceedWithCall`): ПродолжитьВызов()/ProceedWithCall() used incorrectly in extension method
- **BSL277** (`WrongUseOfRollbackTransactionMethod`): ОтменитьТранзакцию/RollbackTransaction called outside Except block
- **BSL278** (`WrongWebServiceHandler`): Web service operation handler method has incorrect signature
- **BSL279** (`YoLetterUsage`): Letter «ё» used in identifiers or string literals — use «е» for consistency

## Правила BSLLS без строки в `RULE_METADATA` с тем же `name`

Классы `*Diagnostic.java`, для которых имя (без суффикса `Diagnostic`) не совпадает ни с одним полем `name` в `RULE_METADATA`:

- `BSL` → `BSLDiagnostic.java`
- `DuplicateRegion` → `DuplicateRegionDiagnostic.java`

