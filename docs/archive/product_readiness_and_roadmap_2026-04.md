# Product Readiness And Roadmap (2026-04)

> Статус: исторический документ parity-кампании апреля 2026. Актуальный пользовательский контракт см. в [README.md](../../README.md), эксплуатационный release-gate — в [Production-Notes.md](../Production-Notes.md).

## Текущий статус после 2026-05-05

Последующая parity-итерация закрыла целевые большие oracle-корпуса до `exact_match=true`: без `only_ours`, `only_bslls`, message, severity и anchor mismatch. Этот файл больше не является актуальным backlog-документом по диагностическим расхождениям.

Актуальный продуктовый курс:

- удерживать BSLLS-parity как release-gate на выбранных корпусах;
- расширять oracle-проверки малыми, воспроизводимыми срезами;
- проверять LSP/extension stability: запуск, индексацию, latency, Docker/local binary parity;
- документировать единый BSLLS-совместимый режим без legacy/compat переключателей.

## Исторический контекст

В апреле 2026 этот документ использовался для планирования parity-кампании. Тогда большие sequential-прогоны на внешнем dev-корпусе показывали воспроизводимые группы расхождений:

- `only_bslls`: `CodeOutOfRegion`, `Typo`, `ServerSideExportFormMethod`, `CanonicalSpellingKeywords`, `LatinAndCyrillicSymbolInWord`, `MissingSpace`;
- `only_ours`: `UnusedLocalVariable`, `Typo`, `ParseError`, `DeprecatedMessage`, `UnknownPreprocessorSymbol`, `NestedStatements`;
- `message_mismatch`: `UsingThisForm`, `CognitiveComplexity`, `ConsecutiveEmptyLines`, `LineLength`;
- `anchor_mismatch`: малый хвост вокруг `Typo` и `UsingServiceTag`.

Эти пункты оставлены только как историческая запись исходной оценки. Для текущих релизных решений используйте свежие oracle-отчеты, README и Production Notes.

## Дальнейшая работа

1. Держать parity-проверки короткими и воспроизводимыми на этапе разработки.
2. Для релиза прогонять выбранные большие корпуса и фиксировать результаты как evidence.
3. Расширять документацию только вокруг текущего публичного контракта: диагностики как BSLLS, форматирование как BSLLS, LSP для расширения.
