# Product Readiness And Roadmap (2026-04)

## Контекст и цель
Документ фиксирует текущее состояние сервера `onec-hbk-bsl` по итогам parity-кампаний и задает практичный план: как использовать сервер в продукте уже сейчас и как добить ключевые gap-блоки без бесконечного trial-and-error.

## Что накопали по факту
Свежие большие sequential-прогоны на корпусе `/Users/maxon/git/config` (две независимые выборки `sample=120`, разные seed):
- `.nosync/reports/dev-corpus/parity-20260415-223523.json`
- `.nosync/reports/dev-corpus/parity-20260415-224005.json`

Устойчивые (повторяемые между seed) проблемные зоны:
- `only_bslls`: `CodeOutOfRegion`, `Typo`, `ServerSideExportFormMethod`, `CanonicalSpellingKeywords`, `LatinAndCyrillicSymbolInWord`, `MissingSpace`.
- `only_ours`: `UnusedLocalVariable`, `Typo`, `ParseError`, `DeprecatedMessage`, `UnknownPreprocessorSymbol`, `NestedStatements`.
- `message_mismatch`: доминирует `UsingThisForm`; также заметны `CognitiveComplexity`, `ConsecutiveEmptyLines`, `LineLength`.
- `anchor_mismatch`: относительно малый хвост, в основном `Typo` и `UsingServiceTag`.

Отдельное наблюдение по reliability:
- very-heavy mixed-срезы с гигантскими файлами (десятки MB) дают слишком долгий `compare`-шаг;
- это выглядит как runtime hot-path bottleneck, а не как случайный шум oracle.

## Оценка готовности к продукту
Сервер готов к **controlled production**:
- внутренние команды, пилоты, ограниченный rollout;
- основной стек LSP/MCP/индексации работоспособен;
- качество уже достаточно высокое для практичной разработки.

Сервер пока не готов к роли полного drop-in эквивалента BSLLS:
- остаются системные и воспроизводимые parity-группы;
- пока нельзя честно обещать 100% совпадение diagnostics/formatting surface.

## Рекомендованная продуктовая политика
1. Перевести parity из blocking-gate в nightly regression gate с трендами.
2. Оставить blocking только по продуктовым P0:
   - стабильность сервера;
   - latency/индексация;
   - отсутствие критических регрессий по core-правилам.
3. Остальные parity-gap закрывать целевыми пакетами по rule-family.

## Дорожная карта (по фазам)

### Фаза 1: Stabilize (1-2 недели)
Цель: убрать риски релиза и сделать метрики прозрачными.
- Зафиксировать nightly parity dashboard по:
  - `only_ours`, `only_bslls`, `message_mismatch`, `anchor_mismatch`, `formatting_diff_files`.
- В CI добавить budget alerts (не блокирующие) по этим метрикам.
- Привязать release-notes к стабильным rule-блокам, а не к ad-hoc фиксам.

Критерий выхода:
- Все nightly прогоны завершаются стабильно.
- Есть исторический тренд минимум за 5-7 дней.

### Фаза 2: Message/Severity normalization (1-2 недели)
Цель: быстро снять большой объем mismatch без рискованных AST-изменений.
- Пакетно нормализовать сообщения/уровни для top-blockers:
  - `UsingThisForm`, `CognitiveComplexity`, `ConsecutiveEmptyLines`, `LineLength`,
  - `GetFormMethod`, `FormDataToValue`, `UselessTernaryOperator`.
- Каждую группу закрывать micro-fixture + real-corpus evidence.

Критерий выхода:
- `message_mismatch` и `severity_mismatch` снижены минимум на 50% от текущего baseline.

### Фаза 3: Semantic parity packs (2-4 недели)
Цель: закрывать устойчивые `only_bslls/only_ours` пачками.
- Pack A: `Typo` + `LatinAndCyrillicSymbolInWord` (словари, token-part политика, anchor alignment).
- Pack B: `CodeOutOfRegion` + `ServerSideExportFormMethod` (form/module context).
- Pack C: `UnusedLocalVariable` + `ParseError` + `UnknownPreprocessorSymbol` (parser/flow/presets).
- Pack D: `MissingSpace` + formatter-диффы (не comment-only).

Критерий выхода:
- Для каждого pack есть отдельный delta-отчет и подтвержденное устойчивое улучшение на двух seed.

### Фаза 4: Performance hardening for large corpora (1-2 недели)
Цель: predictable completion на тяжелых корпусах.
- Профилирование compare hot-path на giant files.
- Оптимизация без изменения rule semantics (индексация/кеши/батчинг).
- Лимитные smoke-профили для крупных файлов (операционные guardrails).

Критерий выхода:
- Heavy-lane compare завершается в целевом окне времени на эталонной машине.

### Фаза 5: Re-evaluate blocking parity (после фаз 2-4)
Цель: решить, возвращать ли жесткий parity-gate в релизный контур.
- Если метрики и стабильность достаточно улучшены — постепенно возвращать blocking для выбранных rule-family.
- Иначе оставить nightly gate и продолжать pack-подход.

Критерий выхода:
- Формальное решение по policy (blocking vs nightly) принято на основе данных, а не ожиданий.

## Что делаем прямо сейчас
- Сохраняем продуктовый курс на controlled production.
- Не отключаем parity полностью: переводим в data-driven nightly режим.
- Развиваем сервер по целевым rule-pack, начиная с тех, что дают максимальный устойчивый выигрыш.
