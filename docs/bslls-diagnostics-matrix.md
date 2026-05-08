# BSLLS diagnostics static matrix

Источник BSLLS: upstream `bsl-language-server` develop, статическое чтение Java/properties.
Локальный источник: `src/onec_hbk_bsl/analysis/diagnostics.py` и `src/onec_hbk_bsl/analysis/diagnostic/**`.

## Summary

- BSLLS diagnostics: 180
- Local rules: 180
- Implemented by static refs: 180
- Implemented but not registered clearly: 0
- Metadata only: 0
- Missing in local map: 0
- Local-only rules: 0

## Priority gaps

- No missing or metadata-only BSLLS diagnostics found by name.

## Matrix

| BSLLS name | Local code | Status | BSLLS source | Type | Severity | Params | Local source |
|---|---:|---|---|---|---|---|---|
| `AllFunctionPathMustHaveReturn` | `BSL148` | `implemented` | upstream:diagnostics/AllFunctionPathMustHaveReturnDiagnostic.java:61 | CODE_SMELL | MAJOR | loopsExecutedAtLeastOnce, ignoreMissingElseOnExit | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1997 |
| `AssignAliasFieldsInQuery` | `BSL149` | `implemented` | upstream:diagnostics/AssignAliasFieldsInQueryDiagnostic.java:44 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3581 |
| `BadWords` | `BSL150` | `implemented` | upstream:diagnostics/BadWordsDiagnostic.java:44 | CODE_SMELL | MAJOR | badWords, findInComments | src/onec_hbk_bsl/analysis/diagnostic/bslls_runtime/rules.py:664 |
| `BeginTransactionBeforeTryCatch` | `BSL151` | `implemented` | upstream:diagnostics/BeginTransactionBeforeTryCatchDiagnostic.java:47 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3329 |
| `CachedPublic` | `BSL152` | `implemented` | upstream:diagnostics/CachedPublicDiagnostic.java:52 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3374 |
| `CanonicalSpellingKeywords` | `BSL153` | `implemented` | upstream:diagnostics/CanonicalSpellingKeywordsDiagnostic.java:53 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4800 |
| `CodeAfterAsyncCall` | `BSL154` | `implemented` | upstream:diagnostics/CodeAfterAsyncCallDiagnostic.java:59 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3387 |
| `CodeBlockBeforeSub` | `BSL155` | `implemented` | upstream:diagnostics/CodeBlockBeforeSubDiagnostic.java:39 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3396 |
| `CodeOutOfRegion` | `BSL156` | `implemented` | upstream:diagnostics/CodeOutOfRegionDiagnostic.java:61 | CODE_SMELL | INFO | checkUnknownModuleType | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3405 |
| `CognitiveComplexity` | `BSL011` | `implemented` | upstream:diagnostics/CognitiveComplexityDiagnostic.java:52 | CODE_SMELL | CRITICAL | complexityThreshold, checkModuleBody | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1063 |
| `CommandModuleExportMethods` | `BSL017` | `implemented` | upstream:diagnostics/CommandModuleExportMethodsDiagnostic.java:45 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1254 |
| `CommentedCode` | `BSL013` | `implemented` | upstream:diagnostics/CommentedCodeDiagnostic.java:61 | CODE_SMELL | MINOR | threshold, exclusionPrefixes | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1117 |
| `CommitTransactionOutsideTryCatch` | `BSL157` | `implemented` | upstream:diagnostics/CommitTransactionOutsideTryCatchDiagnostic.java:46 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3457 |
| `CommonModuleAssign` | `BSL158` | `implemented` | upstream:diagnostics/CommonModuleAssignDiagnostic.java:40 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3414 |
| `CommonModuleInvalidType` | `BSL159` | `implemented` | upstream:diagnostics/CommonModuleInvalidTypeDiagnostic.java:49 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3423 |
| `CommonModuleMissingAPI` | `BSL160` | `implemented` | upstream:diagnostics/CommonModuleMissingAPIDiagnostic.java:51 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3432 |
| `CommonModuleNameCached` | `BSL161` | `implemented` | upstream:diagnostics/CommonModuleNameCachedDiagnostic.java:48 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameClient` | `BSL162` | `implemented` | upstream:diagnostics/CommonModuleNameClientDiagnostic.java:47 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameClientServer` | `BSL163` | `implemented` | upstream:diagnostics/CommonModuleNameClientServerDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameFullAccess` | `BSL164` | `implemented` | upstream:diagnostics/CommonModuleNameFullAccessDiagnostic.java:47 | SECURITY_HOTSPOT | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameGlobalClient` | `BSL166` | `implemented` | upstream:diagnostics/CommonModuleNameGlobalClientDiagnostic.java:45 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameGlobal` | `BSL165` | `implemented` | upstream:diagnostics/CommonModuleNameGlobalDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameServerCall` | `BSL167` | `implemented` | upstream:diagnostics/CommonModuleNameServerCallDiagnostic.java:47 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CommonModuleNameWords` | `BSL168` | `implemented` | upstream:diagnostics/CommonModuleNameWordsDiagnostic.java:51 | CODE_SMELL | INFO | words | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3445 |
| `CompilationDirectiveLost` | `BSL169` | `implemented` | upstream:diagnostics/CompilationDirectiveLostDiagnostic.java:50 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `CompilationDirectiveNeedLess` | `BSL170` | `implemented` | upstream:diagnostics/CompilationDirectiveNeedLessDiagnostic.java:57 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `ConsecutiveEmptyLines` | `BSL055` | `implemented` | upstream:diagnostics/ConsecutiveEmptyLinesDiagnostic.java:51 | CODE_SMELL | INFO | allowedEmptyLinesCount | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2692 |
| `CrazyMultilineString` | `BSL171` | `implemented` | upstream:diagnostics/CrazyMultilineStringDiagnostic.java:41 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `CreateQueryInCycle` | `BSL033` | `implemented` | upstream:diagnostics/CreateQueryInCycleDiagnostic.java:57 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2053 |
| `CyclomaticComplexity` | `BSL019` | `implemented` | upstream:diagnostics/CyclomaticComplexityDiagnostic.java:52 | CODE_SMELL | CRITICAL | complexityThreshold, checkModuleBody | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1300 |
| `DataExchangeLoading` | `BSL172` | `implemented` | upstream:diagnostics/DataExchangeLoadingDiagnostic.java:61 | ERROR | CRITICAL | findFirst | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3565 |
| `DeletingCollectionItem` | `BSL173` | `implemented` | upstream:diagnostics/DeletingCollectionItemDiagnostic.java:48 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3556 |
| `DenyIncompleteValues` | `BSL174` | `implemented` | upstream:diagnostics/DenyIncompleteValuesDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6064 |
| `DeprecatedAttributes8312` | `BSL175` | `implemented` | upstream:diagnostics/DeprecatedAttributes8312Diagnostic.java:54 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4296 |
| `DeprecatedCurrentDate` | `BSL097` | `implemented` | upstream:diagnostics/DeprecatedCurrentDateDiagnostic.java:46 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3167 |
| `DeprecatedFind` | `BSL066` | `implemented` | upstream:diagnostics/DeprecatedFindDiagnostic.java:43 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3005 |
| `DeprecatedMessage` | `BSL041` | `implemented` | upstream:diagnostics/DeprecatedMessageDiagnostic.java:44 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2359 |
| `DeprecatedMethodCall` | `BSL176` | `implemented` | upstream:diagnostics/DeprecatedMethodCallDiagnostic.java:48 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4296 |
| `DeprecatedMethods8310` | `BSL177` | `implemented` | upstream:diagnostics/DeprecatedMethods8310Diagnostic.java:51 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4296 |
| `DeprecatedMethods8317` | `BSL178` | `implemented` | upstream:diagnostics/DeprecatedMethods8317Diagnostic.java:46 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4740 |
| `DeprecatedTypeManagedForm` | `BSL179` | `implemented` | upstream:diagnostics/DeprecatedTypeManagedFormDiagnostic.java:56 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4296 |
| `DisableSafeMode` | `BSL180` | `implemented` | upstream:diagnostics/DisableSafeModeDiagnostic.java:45 | VULNERABILITY | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `DoubleNegatives` | `BSL060` | `implemented` | upstream:diagnostics/DoubleNegativesDiagnostic.java:44 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2759 |
| `DuplicateRegion` | `BSL131` | `implemented` | upstream:diagnostics/DuplicateRegionDiagnostic.java:52 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3241 |
| `DuplicateStringLiteral` | `BSL035` | `implemented` | upstream:diagnostics/DuplicateStringLiteralDiagnostic.java:53 | CODE_SMELL | MINOR | allowedNumberCopies, analyzeFile, caseSensitive, minTextLength | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2119 |
| `DuplicatedInsertionIntoCollection` | `BSL181` | `implemented` | upstream:diagnostics/DuplicatedInsertionIntoCollectionDiagnostic.java:63 | CODE_SMELL | MAJOR | isAllowedMethodADD | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `EmptyCodeBlock` | `BSL004` | `implemented` | upstream:diagnostics/EmptyCodeBlockDiagnostic.java:47 | CODE_SMELL | MAJOR | commentAsCode | src/onec_hbk_bsl/analysis/diagnostic/engine.py:705 |
| `EmptyRegion` | `BSL026` | `implemented` | upstream:diagnostics/EmptyRegionDiagnostic.java:53 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1654 |
| `EmptyStatement` | `BSL025` | `implemented` | upstream:diagnostics/EmptyStatementDiagnostic.java:51 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1472 |
| `ExcessiveAutoTestCheck` | `BSL182` | `implemented` | upstream:diagnostics/ExcessiveAutoTestCheckDiagnostic.java:51 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `ExecuteExternalCode` | `BSL183` | `implemented` | upstream:diagnostics/ExecuteExternalCodeDiagnostic.java:55 | VULNERABILITY | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5251 |
| `ExecuteExternalCodeInCommonModule` | `BSL184` | `implemented` | upstream:diagnostics/ExecuteExternalCodeInCommonModuleDiagnostic.java:47 | SECURITY_HOTSPOT | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `ExportVariables` | `BSL054` | `implemented` | upstream:diagnostics/ExportVariablesDiagnostic.java:43 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2595 |
| `ExternalAppStarting` | `BSL185` | `implemented` | upstream:diagnostics/ExternalAppStartingDiagnostic.java:45 | SECURITY_HOTSPOT | MAJOR | checkGotoUrl, userPatternString | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `ExtraCommas` | `BSL186` | `implemented` | upstream:diagnostics/ExtraCommasDiagnostic.java:41 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3574 |
| `FieldsFromJoinsWithoutIsNull` | `BSL187` | `implemented` | upstream:diagnostics/FieldsFromJoinsWithoutIsNullDiagnostic.java:60 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6064 |
| `FileSystemAccess` | `BSL188` | `implemented` | upstream:diagnostics/FileSystemAccessDiagnostic.java:48 | VULNERABILITY | MAJOR | globalMethods, newExpression | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `ForbiddenMetadataName` | `BSL189` | `implemented` | upstream:diagnostics/ForbiddenMetadataNameDiagnostic.java:57 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `FormDataToValue` | `BSL190` | `implemented` | upstream:diagnostics/FormDataToValueDiagnostic.java:48 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4181 |
| `FullOuterJoinQuery` | `BSL191` | `implemented` | upstream:diagnostics/FullOuterJoinQueryDiagnostic.java:46 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3642 |
| `FunctionNameStartsWithGet` | `BSL192` | `implemented` | upstream:diagnostics/FunctionNameStartsWithGetDiagnostic.java:44 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3657 |
| `FunctionOutParameter` | `BSL193` | `implemented` | upstream:diagnostics/FunctionOutParameterDiagnostic.java:50 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3657 |
| `FunctionReturnsSamePrimitive` | `BSL194` | `implemented` | upstream:diagnostics/FunctionReturnsSamePrimitiveDiagnostic.java:57 | ERROR | MAJOR | skipAttachable, caseSensitiveForString | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3657 |
| `FunctionShouldHaveReturn` | `BSL032` | `implemented` | upstream:diagnostics/FunctionShouldHaveReturnDiagnostic.java:44 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1955 |
| `GetFormMethod` | `BSL195` | `implemented` | upstream:diagnostics/GetFormMethodDiagnostic.java:43 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4296 |
| `GlobalContextMethodCollision8312` | `BSL196` | `implemented` | upstream:diagnostics/GlobalContextMethodCollision8312Diagnostic.java:44 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `IdenticalExpressions` | `BSL052` | `implemented` | upstream:diagnostics/IdenticalExpressionsDiagnostic.java:61 | ERROR | MAJOR | popularDivisors | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2532 |
| `IfConditionComplexity` | `BSL036` | `implemented` | upstream:diagnostics/IfConditionComplexityDiagnostic.java:42 | CODE_SMELL | MINOR | maxIfConditionComplexity | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2245 |
| `IfElseDuplicatedCodeBlock` | `BSL197` | `implemented` | upstream:diagnostics/IfElseDuplicatedCodeBlockDiagnostic.java:53 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4218 |
| `IfElseDuplicatedCondition` | `BSL198` | `implemented` | upstream:diagnostics/IfElseDuplicatedConditionDiagnostic.java:53 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4227 |
| `IfElseIfEndsWithElse` | `BSL199` | `implemented` | upstream:diagnostics/IfElseIfEndsWithElseDiagnostic.java:39 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4883 |
| `IncorrectLineBreak` | `BSL200` | `implemented` | upstream:diagnostics/IncorrectLineBreakDiagnostic.java:47 | CODE_SMELL | INFO | checkFirstSymbol, listOfIncorrectFirstSymbol, checkLastSymbol, listOfIncorrectLastSymbol | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4892 |
| `IncorrectUseLikeInQuery` | `BSL201` | `implemented` | upstream:diagnostics/IncorrectUseLikeInQueryDiagnostic.java:49 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3642 |
| `IncorrectUseOfStrTemplate` | `BSL202` | `implemented` | upstream:diagnostics/IncorrectUseOfStrTemplateDiagnostic.java:53 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5375 |
| `InternetAccess` | `BSL203` | `implemented` | upstream:diagnostics/InternetAccessDiagnostic.java:45 | VULNERABILITY | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `InvalidCharacterInFile` | `BSL204` | `implemented` | upstream:diagnostics/InvalidCharacterInFileDiagnostic.java:54 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `IsInRoleMethod` | `BSL205` | `implemented` | upstream:diagnostics/IsInRoleMethodDiagnostic.java:50 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5375 |
| `JoinWithSubQuery` | `BSL206` | `implemented` | upstream:diagnostics/JoinWithSubQueryDiagnostic.java:43 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4166 |
| `JoinWithVirtualTable` | `BSL207` | `implemented` | upstream:diagnostics/JoinWithVirtualTableDiagnostic.java:43 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4166 |
| `LatinAndCyrillicSymbolInWord` | `BSL208` | `implemented` | upstream:diagnostics/LatinAndCyrillicSymbolInWordDiagnostic.java:49 | CODE_SMELL | MINOR | excludeWords, allowTrailingPartsInAnotherLanguage | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5259 |
| `LineLength` | `BSL014` | `implemented` | upstream:diagnostics/LineLengthDiagnostic.java:54 | CODE_SMELL | MINOR | maxLineLength, checkMethodDescription, excludeTrailingComments | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1161 |
| `LogicalOrInJoinQuerySection` | `BSL209` | `implemented` | upstream:diagnostics/LogicalOrInJoinQuerySectionDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4166 |
| `LogicalOrInTheWhereSectionOfQuery` | `BSL210` | `implemented` | upstream:diagnostics/LogicalOrInTheWhereSectionOfQueryDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3594 |
| `MagicDate` | `BSL047` | `implemented` | upstream:diagnostics/MagicDateDiagnostic.java:51 | CODE_SMELL | MINOR | authorizedDates | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2426 |
| `MagicNumber` | `BSL029` | `implemented` | upstream:diagnostics/MagicNumberDiagnostic.java:47 | CODE_SMELL | MINOR | authorizedNumbers, allowMagicIndexes | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1775 |
| `MetadataObjectNameLength` | `BSL211` | `implemented` | upstream:diagnostics/MetadataObjectNameLengthDiagnostic.java:46 | ERROR | MAJOR | maxMetadataObjectNameLength | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `MethodSize` | `BSL002` | `implemented` | upstream:diagnostics/MethodSizeDiagnostic.java:41 | CODE_SMELL | MAJOR | maxMethodSize | src/onec_hbk_bsl/analysis/diagnostic/engine.py:628 |
| `MissedRequiredParameter` | `BSL212` | `implemented` | upstream:diagnostics/MissedRequiredParameterDiagnostic.java:53 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4156 |
| `MissingCodeTryCatchEx` | `BSL028` | `implemented` | upstream:diagnostics/MissingCodeTryCatchExDiagnostic.java:46 | ERROR | MAJOR | commentAsCode | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1738 |
| `MissingCommonModuleMethod` | `BSL213` | `implemented` | upstream:diagnostics/MissingCommonModuleMethodDiagnostic.java:53 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `MissingEventSubscriptionHandler` | `BSL214` | `implemented` | upstream:diagnostics/MissingEventSubscriptionHandlerDiagnostic.java:50 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `MissingParameterDescription` | `BSL215` | `implemented` | upstream:diagnostics/MissingParameterDescriptionDiagnostic.java:51 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4865 |
| `MissingReturnedValueDescription` | `BSL065` | `implemented` | upstream:diagnostics/MissingReturnedValueDescriptionDiagnostic.java:46 | CODE_SMELL | MAJOR | allowShortDescriptionReturnValues | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2942 |
| `MissingSpace` | `BSL216` | `implemented` | upstream:diagnostics/MissingSpaceDiagnostic.java:58 | CODE_SMELL | INFO | listForCheckLeft, listForCheckRight, listForCheckLeftAndRight, checkSpaceToRightOfUnary, allowMultipleCommas | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4986 |
| `MissingTempStorageDeletion` | `BSL217` | `implemented` | upstream:diagnostics/MissingTempStorageDeletionDiagnostic.java:55 | CODE_SMELL | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `MissingTemporaryFileDeletion` | `BSL218` | `implemented` | upstream:diagnostics/MissingTemporaryFileDeletionDiagnostic.java:50 | ERROR | MAJOR | searchDeleteFileMethod | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5366 |
| `MissingVariablesDescription` | `BSL219` | `implemented` | upstream:diagnostics/MissingVariablesDescriptionDiagnostic.java:40 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2641 |
| `MultilineStringInQuery` | `BSL220` | `implemented` | upstream:diagnostics/MultilineStringInQueryDiagnostic.java:43 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3627 |
| `MultilingualStringHasAllDeclaredLanguages` | `BSL221` | `implemented` | upstream:diagnostics/MultilingualStringHasAllDeclaredLanguagesDiagnostic.java:40 | ERROR | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5581 |
| `MultilingualStringUsingWithTemplate` | `BSL222` | `implemented` | upstream:diagnostics/MultilingualStringUsingWithTemplateDiagnostic.java:40 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5581 |
| `NestedConstructorsInStructureDeclaration` | `BSL223` | `implemented` | upstream:diagnostics/NestedConstructorsInStructureDeclarationDiagnostic.java:56 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5375 |
| `NestedFunctionInParameters` | `BSL224` | `implemented` | upstream:diagnostics/NestedFunctionInParametersDiagnostic.java:49 | CODE_SMELL | MINOR | allowOneliner, allowedMethodNames | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5357 |
| `NestedStatements` | `BSL020` | `implemented` | upstream:diagnostics/NestedStatementsDiagnostic.java:54 | CODE_SMELL | CRITICAL | maxAllowedLevel | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1329 |
| `NestedTernaryOperator` | `BSL039` | `implemented` | upstream:diagnostics/NestedTernaryOperatorDiagnostic.java:43 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2285 |
| `NonExportMethodsInApiRegion` | `BSL003` | `implemented` | upstream:diagnostics/NonExportMethodsInApiRegionDiagnostic.java:48 | CODE_SMELL | MAJOR | skipAnnotatedMethods | src/onec_hbk_bsl/analysis/diagnostic/engine.py:666 |
| `NonStandardRegion` | `BSL016` | `implemented` | upstream:diagnostics/NonStandardRegionDiagnostic.java:51 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1221 |
| `NumberOfOptionalParams` | `BSL015` | `implemented` | upstream:diagnostics/NumberOfOptionalParamsDiagnostic.java:41 | CODE_SMELL | MINOR | maxOptionalParamsCount | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1192 |
| `NumberOfParams` | `BSL031` | `implemented` | upstream:diagnostics/NumberOfParamsDiagnostic.java:41 | CODE_SMELL | MINOR | maxParamsCount | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1921 |
| `NumberOfValuesInStructureConstructor` | `BSL225` | `implemented` | upstream:diagnostics/NumberOfValuesInStructureConstructorDiagnostic.java:47 | CODE_SMELL | MINOR | maxValuesCount | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6122 |
| `OSUsersMethod` | `BSL226` | `implemented` | upstream:diagnostics/OSUsersMethodDiagnostic.java:44 | SECURITY_HOTSPOT | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `OneStatementPerLine` | `BSL227` | `implemented` | upstream:diagnostics/OneStatementPerLineDiagnostic.java:57 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4236 |
| `OrderOfParams` | `BSL228` | `implemented` | upstream:diagnostics/OrderOfParamsDiagnostic.java:43 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3657 |
| `OrdinaryAppSupport` | `BSL229` | `implemented` | upstream:diagnostics/OrdinaryAppSupportDiagnostic.java:50 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5736 |
| `PairingBrokenTransaction` | `BSL230` | `implemented` | upstream:diagnostics/PairingBrokenTransactionDiagnostic.java:48 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6158 |
| `ParseError` | `BSL001` | `implemented` | upstream:diagnostics/ParseErrorDiagnostic.java:47 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:608 |
| `PrivilegedModuleMethodCall` | `BSL231` | `implemented` | upstream:diagnostics/PrivilegedModuleMethodCallDiagnostic.java:52 | SECURITY_HOTSPOT | MAJOR | validateNestedCalls | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `ProcedureReturnsValue` | `BSL064` | `implemented` | upstream:diagnostics/ProcedureReturnsValueDiagnostic.java:42 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2896 |
| `ProtectedModule` | `BSL232` | `implemented` | upstream:diagnostics/ProtectedModuleDiagnostic.java:52 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `PublicMethodsDescription` | `BSL233` | `implemented` | upstream:diagnostics/PublicMethodsDescriptionDiagnostic.java:48 | CODE_SMELL | INFO | checkAllRegion | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4874 |
| `QueryNestedFieldsByDot` | `BSL234` | `implemented` | upstream:diagnostics/QueryNestedFieldsByDotDiagnostic.java:40 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6131 |
| `QueryParseError` | `BSL235` | `implemented` | upstream:diagnostics/QueryParseErrorDiagnostic.java:44 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3627 |
| `QueryToMissingMetadata` | `BSL236` | `implemented` | upstream:diagnostics/QueryToMissingMetadataDiagnostic.java:52 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6064 |
| `RedundantAccessToObject` | `BSL237` | `implemented` | upstream:diagnostics/RedundantAccessToObjectDiagnostic.java:62 | CODE_SMELL | INFO | checkObjectModule, checkFormModule, checkRecordSetModule | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6140 |
| `RefOveruse` | `BSL238` | `implemented` | upstream:diagnostics/RefOveruseDiagnostic.java:65 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6064 |
| `ReservedParameterNames` | `BSL239` | `implemented` | upstream:diagnostics/ReservedParameterNamesDiagnostic.java:46 | CODE_SMELL | MAJOR | reservedWords | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5581 |
| `RewriteMethodParameter` | `BSL240` | `implemented` | upstream:diagnostics/RewriteMethodParameterDiagnostic.java:64 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6181 |
| `SameMetadataObjectAndChildNames` | `BSL241` | `implemented` | upstream:diagnostics/SameMetadataObjectAndChildNamesDiagnostic.java:58 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `ScheduledJobHandler` | `BSL242` | `implemented` | upstream:diagnostics/ScheduledJobHandlerDiagnostic.java:54 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `SelectTopWithoutOrderBy` | `BSL077` | `implemented` | upstream:diagnostics/SelectTopWithoutOrderByDiagnostic.java:46 | CODE_SMELL | MAJOR | skipSelectTopOne | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3052 |
| `SelfAssign` | `BSL009` | `implemented` | upstream:diagnostics/SelfAssignDiagnostic.java:42 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1036 |
| `SelfInsertion` | `BSL243` | `implemented` | upstream:diagnostics/SelfInsertionDiagnostic.java:45 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5375 |
| `SemicolonPresence` | `BSL030` | `implemented` | upstream:diagnostics/SemicolonPresenceDiagnostic.java:52 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1480 |
| `ServerCallsInFormEvents` | `BSL244` | `implemented` | upstream:diagnostics/ServerCallsInFormEventsDiagnostic.java:57 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6102 |
| `ServerSideExportFormMethod` | `BSL245` | `implemented` | upstream:diagnostics/ServerSideExportFormMethodDiagnostic.java:51 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6149 |
| `SetPermissionsForNewObjects` | `BSL246` | `implemented` | upstream:diagnostics/SetPermissionsForNewObjectsDiagnostic.java:52 | VULNERABILITY | CRITICAL | namesFullAccessRole | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `SetPrivilegedMode` | `BSL247` | `implemented` | upstream:diagnostics/SetPrivilegedModeDiagnostic.java:46 | SECURITY_HOTSPOT | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `SeveralCompilerDirectives` | `BSL248` | `implemented` | upstream:diagnostics/SeveralCompilerDirectivesDiagnostic.java:42 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `SpaceAtStartComment` | `BSL024` | `implemented` | upstream:diagnostics/SpaceAtStartCommentDiagnostic.java:55 | CODE_SMELL | INFO | commentsAnnotation, useStrictValidation | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1437 |
| `StyleElementConstructors` | `BSL249` | `implemented` | upstream:diagnostics/StyleElementConstructorsDiagnostic.java:46 | ERROR | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5375 |
| `TempFilesDir` | `BSL250` | `implemented` | upstream:diagnostics/TempFilesDirDiagnostic.java:45 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `TernaryOperatorUsage` | `BSL251` | `implemented` | upstream:diagnostics/TernaryOperatorUsageDiagnostic.java:41 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `ThisObjectAssign` | `BSL252` | `implemented` | upstream:diagnostics/ThisObjectAssignDiagnostic.java:53 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `TimeoutsInExternalResources` | `BSL253` | `implemented` | upstream:diagnostics/TimeoutsInExternalResourcesDiagnostic.java:54 | ERROR | CRITICAL | analyzeInternetMailProfileZeroTimeout | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6102 |
| `TooManyReturns` | `BSL008` | `implemented` | upstream:diagnostics/TooManyReturnsDiagnostic.java:52 | CODE_SMELL | MINOR | maxReturnsCount | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1006 |
| `TransferringParametersBetweenClientAndServer` | `BSL254` | `implemented` | upstream:diagnostics/TransferringParametersBetweenClientAndServerDiagnostic.java:68 | CODE_SMELL | MAJOR | cachedValueNames | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5235 |
| `TryNumber` | `BSL255` | `implemented` | upstream:diagnostics/TryNumberDiagnostic.java:45 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5244 |
| `Typo` | `BSL256` | `implemented` | upstream:diagnostics/TypoDiagnostic.java:71 | CODE_SMELL | INFO | minWordLength, userWordsToIgnore, caseInsensitive | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5329 |
| `UnaryPlusInConcatenation` | `BSL257` | `implemented` | upstream:diagnostics/UnaryPlusInConcatenationDiagnostic.java:44 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6213 |
| `UnionAll` | `BSL258` | `implemented` | upstream:diagnostics/UnionAllDiagnostic.java:45 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4749 |
| `UnknownPreprocessorSymbol` | `BSL259` | `implemented` | upstream:diagnostics/UnknownPreprocessorSymbolDiagnostic.java:40 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `UnreachableCode` | `BSL051` | `implemented` | upstream:diagnostics/UnreachableCodeDiagnostic.java:56 | ERROR | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2455 |
| `UnsafeFindByCode` | `BSL260` | `implemented` | upstream:diagnostics/UnsafeFindByCodeDiagnostic.java:80 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5877 |
| `UnsafeSafeModeMethodCall` | `BSL261` | `implemented` | upstream:diagnostics/UnsafeSafeModeMethodCallDiagnostic.java:50 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6102 |
| `UnusedLocalMethod` | `BSL042` | `implemented` | upstream:diagnostics/UnusedLocalMethodDiagnostic.java:59 | CODE_SMELL | MAJOR | attachableMethodPrefixes, checkObjectModule | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2386 |
| `UnusedLocalVariable` | `BSL007` | `implemented` | upstream:diagnostics/UnusedLocalVariableDiagnostic.java:56 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:826 |
| `UnusedParameters` | `BSL062` | `implemented` | upstream:diagnostics/UnusedParametersDiagnostic.java:49 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2797 |
| `UsageWriteLogEvent` | `BSL262` | `implemented` | upstream:diagnostics/UsageWriteLogEventDiagnostic.java:50 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/bslls_runtime/rules.py:2470 |
| `UseLessForEach` | `BSL263` | `implemented` | upstream:diagnostics/UseLessForEachDiagnostic.java:47 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6195 |
| `UseSystemInformation` | `BSL264` | `implemented` | upstream:diagnostics/UseSystemInformationDiagnostic.java:45 | SECURITY_HOTSPOT | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `UselessTernaryOperator` | `BSL265` | `implemented` | upstream:diagnostics/UselessTernaryOperatorDiagnostic.java:52 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6204 |
| `UsingCancelParameter` | `BSL266` | `implemented` | upstream:diagnostics/UsingCancelParameterDiagnostic.java:47 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3657 |
| `UsingExternalCodeTools` | `BSL267` | `implemented` | upstream:diagnostics/UsingExternalCodeToolsDiagnostic.java:47 | SECURITY_HOTSPOT | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `UsingFindElementByString` | `BSL268` | `implemented` | upstream:diagnostics/UsingFindElementByStringDiagnostic.java:48 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3672 |
| `UsingGoto` | `BSL027` | `implemented` | upstream:diagnostics/UsingGotoDiagnostic.java:40 | CODE_SMELL | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1698 |
| `UsingHardcodeNetworkAddress` | `BSL005` | `implemented` | upstream:diagnostics/UsingHardcodeNetworkAddressDiagnostic.java:46 | VULNERABILITY | CRITICAL | searchWordsExclusion, searchPopularVersionExclusion | src/onec_hbk_bsl/analysis/diagnostic/engine.py:769 |
| `UsingHardcodePath` | `BSL006` | `implemented` | upstream:diagnostics/UsingHardcodePathDiagnostic.java:47 | ERROR | CRITICAL | searchWordsStdPathsUnix | src/onec_hbk_bsl/analysis/diagnostic/engine.py:802 |
| `UsingHardcodeSecretInformation` | `BSL012` | `implemented` | upstream:diagnostics/UsingHardcodeSecretInformationDiagnostic.java:50 | VULNERABILITY | CRITICAL | searchWords | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1092 |
| `UsingLikeInQuery` | `BSL269` | `implemented` | upstream:diagnostics/UsingLikeInQueryDiagnostic.java:45 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3627 |
| `UsingModalWindows` | `BSL022` | `implemented` | upstream:diagnostics/UsingModalWindowsDiagnostic.java:51 | CODE_SMELL | MAJOR | forceModalityMode | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1370 |
| `UsingObjectNotAvailableUnix` | `BSL271` | `implemented` | upstream:diagnostics/UsingObjectNotAvailableUnixDiagnostic.java:47 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5581 |
| `UsingServiceTag` | `BSL023` | `implemented` | upstream:diagnostics/UsingServiceTagDiagnostic.java:41 | CODE_SMELL | INFO | serviceTags | src/onec_hbk_bsl/analysis/diagnostic/engine.py:1409 |
| `UsingSynchronousCalls` | `BSL272` | `implemented` | upstream:diagnostics/UsingSynchronousCallsDiagnostic.java:55 | CODE_SMELL | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:4511 |
| `UsingThisForm` | `BSL040` | `implemented` | upstream:diagnostics/UsingThisFormDiagnostic.java:64 | CODE_SMELL | MINOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:2314 |
| `VirtualTableCallWithoutParameters` | `BSL273` | `implemented` | upstream:diagnostics/VirtualTableCallWithoutParametersDiagnostic.java:43 | ERROR | MAJOR |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:3627 |
| `WrongDataPathForFormElements` | `BSL274` | `implemented` | upstream:diagnostics/WrongDataPathForFormElementsDiagnostic.java:53 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6083 |
| `WrongHttpServiceHandler` | `BSL275` | `implemented` | upstream:diagnostics/WrongHttpServiceHandlerDiagnostic.java:50 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5736 |
| `WrongUseFunctionProceedWithCall` | `BSL276` | `implemented` | upstream:diagnostics/WrongUseFunctionProceedWithCallDiagnostic.java:48 | ERROR | BLOCKER |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5581 |
| `WrongUseOfRollbackTransactionMethod` | `BSL277` | `implemented` | upstream:diagnostics/WrongUseOfRollbackTransactionMethodDiagnostic.java:44 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6165 |
| `WrongWebServiceHandler` | `BSL278` | `implemented` | upstream:diagnostics/WrongWebServiceHandlerDiagnostic.java:49 | ERROR | CRITICAL |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:5736 |
| `YoLetterUsage` | `BSL279` | `implemented` | upstream:diagnostics/YoLetterUsageDiagnostic.java:41 | CODE_SMELL | INFO |  | src/onec_hbk_bsl/analysis/diagnostic/engine.py:6222 |

## Local-only rules
