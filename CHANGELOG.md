# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.18] - 2026-06-18

### Fixed

- `CompilationDirectiveLost` (`BSL169`) больше не требует директивы компиляции
  в модулях обычных форм, включая layout `Forms/<form>/Ext/Module.bsl`.
- `ServerSideExportFormMethod` (`BSL245`) больше не диагностирует экспортные
  методы в модулях обычных форм и сохраняет проверку для управляемых форм.

## [0.8.17] - 2026-06-16

### Fixed

- `ServerCallsInFormEvents` (`BSL244`) больше не диагностирует серверный
  обработчик формы, который вызывает серверную вспомогательную процедуру.
- `UnusedLocalVariable` (`BSL007`) учитывает использование переменной-приемника
  в динамическом вызове через `Выполнить` / `Execute`, но обычные строковые
  упоминания по-прежнему не считаются чтением переменной.

## [0.8.16] - 2026-06-16

### Changed

- Разделены PyPI-дистрибутивы: `onec-hbk-bsl-core` содержит slim-реализацию
  без MCP-зависимостей по умолчанию, а `onec-hbk-bsl` стал полным
  backwards-compatible метапакетом поверх `onec-hbk-bsl-core[mcp]`.
- `onec-hbk-bsl mcp` без MCP-зависимостей теперь завершается понятной
  подсказкой по установке вместо низкоуровневого `ModuleNotFoundError`.
- Пользовательская документация, README расширения и публичная surface-документация
  сжаты до продуктового вида без локальных parity-артефактов и внутренних путей.
- Публичные описания совместимых диагностических alias больше не используют
  `BSLLS key` / `BSLLS diagnostic names` как пользовательскую терминологию.

### Fixed

- `ServerSideExportMethodsInForm` (`BSL245`) корректнее определяет split-модули
  форм и не стреляет по object-module split-файлам.
- `SelectTopWithoutOrderBy` (`BSL077`) проверяется через SDBL/CST и корректно
  диагностирует `ВЫБРАТЬ ПЕРВЫЕ` без `УПОРЯДОЧИТЬ ПО`.
- Диагностический pipeline переиспользует рассчитанный контекст правил, чтобы
  снизить лишнюю работу при прогоне связанных metadata/query правил.

## [0.8.3] - 2026-06-13

### Fixed

- `SemicolonPresence` (`BSL030`) теперь проверяет statement-узлы CST,
  и больше не даёт ложные срабатывания на многострочных выражениях с переносом
  перед оператором сравнения.

## [0.7.55] - 2026-06-12

### Changed

- Re-formatted the diagnostic message compatibility changes with the repository Ruff
  formatter so the CI format gate passes for the published fix.

## [0.7.54] - 2026-06-12

### Changed

- Structured diagnostic output now includes canonical `rule_message`
  alongside occurrence-specific `message`, so agents and report consumers can
  distinguish the rule wording from local details.
- `CommonModuleInvalidType` (`BSL159`) now reports the canonical message
  `Общий модуль недопустимого типа` instead of the misleading local wording
  about a missing execution context.

## [0.7.53] - 2026-06-12

### Added

- Быстрый advisory-режим CLI для changed files: `--paths-from`,
  `--paths-from0`, `--diff --since`, `--changed-lines-only` и
  `--split-fragment` для точечного подавления split-only шума.
- Публичный Python API `onec_hbk_bsl.check_files(...)` для диагностики
  явного списка `.bsl/.os` файлов без обращения к приватному `_run_checks`.

### Changed

- JSON diagnostic output теперь включает `rule_name` рядом с `file`, `line`,
  `code`, `severity` и `message`.
- Git diff helpers читают пути как UTF-8 с `core.quotepath=false`, чтобы
  корректно работать с кириллическими путями.
- `StyleElementConstructors` (`BSL249`) выровнен как `ERROR`.

## [0.7.48] - 2026-06-02

### Fixed

- Исправлен сбой LSP-диагностик в PyInstaller onefile-сборке на Linux:
  multiprocessing child process теперь обслуживается через
  `multiprocessing.freeze_support()` до разбора CLI-аргументов, поэтому
  служебные аргументы forkserver больше не попадают в обычный `argparse`.

### Changed

- Описания диагностических правил в публичных UI/JSON surfaces теперь
  локализуются на русский: LSP `Diagnostic.data.rule_description`, `--list-rules`,
  SARIF `shortDescription` и MCP `bsl_list_rules`.
- Дефолтный набор диагностик теперь включает совместимые `CodeOutOfRegion` (`BSL156`)
  и `QueryToMissingMetadata` (`BSL236`) по результатам локальных regression checks
  на больших реальных корпусах.
- LSP для больших файлов в VS Code теперь отвечает на первый pull diagnostics быстро:
  полный анализ выполняется в фоне и обновляет Problems через `workspace/diagnostic/refresh`.
- Индекс открытого файла в LSP обновляется из уже построенного `DocumentSnapshot`,
  без повторного чтения и парсинга текущего файла на сохранении.

## [0.7.29] - 2026-05-14

### Changed

- Синхронизированы релизные версии Python runtime и VS Code extension.
- Обновлена metadata лицензии Python-пакета на SPDX-строку `MIT` для актуального setuptools.
- Локальный релизный скрипт теперь обновляет extension manifest, lockfile и runtime `_version.py` согласованно.

## [0.7.27] - 2026-05-06

### Changed

- Сокращен PyInstaller onefile: bundle теперь использует metadata `mcp` вместо legacy `fastmcp` и исключает неиспользуемые в наших режимах `cryptography` и `pygments`.
- Проверены onefile smoke-сценарии для CLI diagnostics, formatter, LSP и MCP после сокращения графа.

## [0.7.26] - 2026-05-06

### Changed

- Убрана прямая зависимость от внешнего `fastmcp`: MCP bridge использует `mcp.server.fastmcp.FastMCP` из официального Python MCP SDK.
- Полная установка остается одним пакетом без extras-разделения; CLI-режимы по-прежнему выбираются ключами `--mcp`, `--stdio`, `--port`, `--workspace`.
- MCP HTTP запуск перенес `host`/`port` в создание приложения, как требует официальный SDK.
- Диагностики и форматирование доведены до стабильного compatibility-профиля на целевых больших корпусах: без message, severity и anchor mismatch.
- Счетчики `MethodSize`, `CognitiveComplexity` и `CyclomaticComplexity` выровнены для многострочных сигнатур, comment-only границ тела, вложенных boolean-expression и многострочных строк.
- Пользовательская документация и README расширения описывают единый compatibility-профиль без legacy/compat режимов.

## [0.7.23] - 2026-05-05

### Changed

- Выравнены диагностики и форматирование `strict-bslls` по локальным compatibility fixtures.
- Синхронизирована версия VS Code extension с runtime package.

## [0.7.22] - 2026-04-16

### Added

- `scripts/lsp_soak_profile.py` и [docs/lsp-soak-runbook.md](docs/lsp-soak-runbook.md) для длительного soak-профилирования LSP (30–60 минут) с метриками drift по памяти, потокам и кэшам.
- `tests/test_bench_scripts.py` для проверки режимов `--cache-mode` в `bench_timing.py` и `bench_profile.py`.
- Новый сервис состояния документов LSP: `src/onec_hbk_bsl/lsp/document_state.py` для явной декомпозиции серверного состояния.

### Changed

- Производительность и потребление ресурсов:
  - `DocumentSnapshot`: оптимизирован regex-fallback и расчёт строк/смещений.
  - `DiagnosticEngine`: heavy-prep структуры строятся лениво по активным семействам правил.
  - `formatter`: снижена повторная токенизация в hot-path.
  - `SymbolIndex`: адаптивные SQLite-профили (`interactive`/`batch`) и env-overrides.
  - MCP help-cache: TTL + eviction по лимиту элементов и байт.
- Бенч-скрипты: `--cache-mode=miss|hit` для корректных и сопоставимых lane-метрик.

## [0.7.13] - 2026-04-09

### Added

- **BSL210** (`LogicalOrInTheWhereSectionOfQuery`): эвристика для встроенных запросов (продолжения `|…`, литералы); стабильная обработка типичных многострочных `ГДЕ` + `ИЛИ`.

### Changed

- **BSL256 (Typo):** вместо LanguageTool — `pyspellchecker` + `pymorphy3` и исключения из `bslls_typo_data` / `TypoDiagnostic_ru.properties`; зависимость `language-tool-python` убрана.
- **BSL254:** включён compatibility-режим через индекс вызовов клиент/сервер.
- **Форматтер (`strict-bslls`):** табы по умолчанию, пробел после `,` в коде, пустые строки с отступом; профиль `compat` по-прежнему с пробелами при явном выборе.
- **LSP / MCP:** `insertSpaces` из запроса форматирования или профиль по умолчанию (для `[bsl]` в расширении — табы); убран принудительный режим «только пробелы» в code action и MCP.

### Docs

- README: пример `editor.insertSpaces` для `[bsl]`; описание `onecHbkBsl.format.indentSize` в `vscode-extension/package.json`.

## [0.7.12] - 2026-03-29

### Added

- **BSL149 (AssignAliasFieldsInQuery):** проверка списка полей `ВЫБРАТЬ`/`SELECT` во встроенных запросах (продолжения `|…` и однострочные литералы до ключевого слова секции); по умолчанию включено; список правил доступен через `onec-hbk-bsl --list-rules`.

### Fixed

- **`__version__`:** в рабочей копии (`src/onec_hbk_bsl` + `.git`) сначала **setuptools-scm** по корню репозитория, чтобы `pytest` и локальный запуск с `PYTHONPATH=src` не подхватывали устаревшую версию из чужой установки в site-packages.

### Changed
- Документация: объединены гайды CST в [docs/cst_policy.md](docs/cst_policy.md); baseline notes перенесены в текущие task reports и CLI tooling; объединены дублирующие CST-документы в docs/cst_policy.md; убраны битые ссылки на локальные пути вне репозитория; CI без загрузки отчёта в Codecov.

### Changed
- **LSP semantic tokens (подсветка):** логические операторы **И** / **ИЛИ** / **НЕ** учитываются в **любом регистре** (`и`, `ИЛИ`, `нЕ` и т.д.); исправлено написание **ИЛИ** (раньше в шаблоне ошибочно фигурировало «Или» без совпадения с ключевым словом в модуле).
- **BSL001 (ParseError):** подавление ложных узлов `(` / `)` от грамматики tree-sitter-bsl не только внутри ``Если (…)``, но и в **присваиваниях** с многострочными скобками и в конструкциях вроде ``Новый("…")`` — ближе к допустимому BSL (см. `BslParser._should_suppress_lone_paren_error`).
- **BSL065 (Missing export comment):** в модулях форм EDT (`path_is_likely_form_module_bsl`) правило не выполняется для `…/Forms/…/Ext/Module.bsl`.
- **BSL153 (CanonicalSpellingKeywords):** в модулях форм EDT (`path_is_likely_form_module_bsl`) правило не выполняется для типичных `Module.bsl` форм.
- **BSL011 (CognitiveComplexity):** в метрику добавлен учёт логических операторов `И`/`ИЛИ`/`And`/`Or`, чтобы совместно с BSL019 корректнее оценивать длинные условия.
- **BSL046 / BSL199:** при включённом BSL199 цепочка «Если/ИначеЕсли без Иначе» даёт только **BSL199** (строка **КонецЕсли**), без дубля BSL046; при отключённом BSL199 по-прежнему срабатывает BSL046 на строке `Если`.
- **BSL036 (IfConditionComplexity):** подсчёт операторов `И`/`ИЛИ` по **всему** условию до `Тогда` (многострочные `Если`/`ИначеЕсли`); **BSL153** не выдаётся на строках этого условия, если с первой строки срабатывает BSL036.
- **BSL024 (SpaceAtStartComment):** дополнительно не помечаются только строки `//&…` (директивы компилятора); `//{`/`//}` и декоративные `//****…` снова проверяются на эталонных модулях.
- **BSL055 (ConsecutiveEmptyLines):** порог — не более **одной** пустой строки подряд между фрагментами кода (`MAX_BLANK_LINES=1`); quick-fix в [fix_engine.py](src/onec_hbk_bsl/analysis/fix_engine.py) согласован.
- **BSL256 (Typo) / BSL208 (LatinAndCyrillicSymbolInWord):** включено по умолчанию правило **BSL256** для идентификаторов, где кириллица состоит только из букв-омоглифов латиницы; намеренное смешение алфавитов по-прежнему даёт **BSL208**. Общая реализация: `_rule_bsl208_bsl256_latin_cyrillic_and_typo`.
- **BSL219 (MissingVariablesDescription):** реализовано для `Перем … Экспорт` / `Var … Export` на уровне модуля без непустой строки описания `//` или `///` непосредственно выше; часто вместе с BSL054 на той же строке.
- **BSL040 (UsingThisForm):** модули форм определяются по пути EDT (`…/Forms/…/Ext/Module.bsl`) и по имени файла (`*форма*`, окончание `form`) — для них **ЭтаФорма** не помечается как ошибочное использование вне обработчика.
- **BSL024 (SpaceAtStartComment):** строгий «допустимый» комментарий: аннотации `//@` / `//(c)` / `//©`, пропуск строк с закомментированным кодом, `///`, `//|`, `//!`; общая функция `bsl024_should_report_line` для движка и LSP quick-fix.
- **BSL004 (EmptyCodeBlock):** пустая ветка после «Тогда» / «Then» даёт то же предупреждение, что и пустой `Исключение`; **BSL059** не дублирует это на той же строке. На сложных условиях **BSL036** подавляет **BSL153**, если оба правила включены.
- Сборка standalone-бинарника: **PyInstaller** (spec [`packaging/onec-hbk-bsl.spec`](packaging/onec-hbk-bsl.spec)) вместо Nuitka; уменьшение графа зависимостей через `excludes` в spec; в CI добавлен smoke-job сборки бинарника на Linux; релизные бинарники и CI — **Python 3.14** (`requires-python >=3.14`).

## [0.7.3] - 2026-03-23

### Changed

- **Версионирование:** номер релиза берётся из **git-тегов** (`v*`) через **setuptools-scm** (`dynamic` в `pyproject.toml`); `onec_hbk_bsl.__version__` — из установленного пакета или `setuptools_scm.get_version` в дереве исходников.
- **Расширение VS Code:** в git в `package.json` и в корне `package-lock.json` зафиксирован плейсхолдер **`0.0.0`**; реальная версия подставляется **`scripts/sync_version.py`**; после локальной **`make vsix`** автоматически вызывается **`scripts/reset_extension_placeholder.py`**.
- **CI / Release:** `actions/checkout` с **`fetch-depth: 0`**; перед сборкой VSIX в релизе — синхронизация версии расширения из git; в тексте релиза для **pip** указана версия без префикса **`v`**.
- **PyInstaller:** в spec добавлено **`copy_metadata("onec-hbk-bsl")`** для корректной **`--version`** в onefile.

### Added

- Скрипты **`scripts/sync_version.py`**, **`scripts/reset_extension_placeholder.py`**; цели **`make sync-version`**, **`make reset-extension-placeholder`**; тест **`tests/test_version.py`**.

## [0.7.2] - 2026-03-23

### Fixed

- **Диагностики — производительность на больших файлах:** при отсечении предупреждений, попадающих внутрь строковых литералов ` "…" `, таблица начал строк (`line_start_offsets`) строится **один раз** на файл и переиспользуется; раньше каждый вызов `line_col_to_offset` заново сканировал весь текст (на тысячах диагностик — доминирующая стоимость).

### Added

- Реестр вызова правил (`diagnostics_rule_registry`): фазы (`RulePhase`), `infer_rule_invoke`, `build_enabled_invoke_snapshot`; метрика `last_metrics["rule_invoke"]` в движке.
- Документация [docs/diagnostics_rule_invoke.md](docs/diagnostics_rule_invoke.md); тесты [tests/test_diagnostics_rule_registry.py](tests/test_diagnostics_rule_registry.py).

### Changed

- **Диагностики:** правила выполняются последовательно через список задач (без параллельного `ThreadPoolExecutor` внутри одного файла — tree-sitter/SQLite не для воркер-потоков).

## [0.7.0] - 2026-03-22

### Fixed

- **Индексатор (большие воркспейсы, десятки тысяч файлов):** у каждого потока парсинга свой `BslParser` (tree-sitter Parser не потокобезопасен); очередь результатов перед записью в SQLite ограничена по размеру (backpressure), чтобы не копить гигабайты RAM при опережении парсинга над коммитами; `BSL_INDEX_PARSE_WORKERS` ограничен сверху (32), дефолт без переменной — `min(4, число CPU)`.

### Changed

- **LSP:** `textDocument/diagnostic` (pull) для клиентов с LSP 3.17; при поддержке pull не шлём `publishDiagnostics` на каждое изменение; группировка Problems: `source` = `onec-hbk-bsl · <код правила>`; MCP: `source` для BSL-DEAD выровнен с LSP.
- Документация: [docs/Production-Notes.md](docs/Production-Notes.md) — индексация и параллелизм.

## [0.6.9] - 2026-03-22

### Fixed

- **LSP:** преобразование `file://` → локальный путь на Windows через `urllib.request.url2pathname` (корректные пути вида `C:\…` вместо `/C:/…`), чтобы корень воркспейса, `cwd` для `git` и индексатор работали; обратное преобразование путь → URI через `Path.resolve().as_uri()`.
- **Расширение VS Code:** на Windows проверка исполняемости бинарника без `fs.constants.X_OK` (ненадёжно для `.exe`); платформа `win32-arm64` использует тот же релизный артефакт `onec-hbk-bsl-win32-x64.exe` (x64 на ARM Windows).

## [0.6.8] - 2026-03-22

### Changed

- Релиз **0.6.8**: синхронизированы версии пакета `onec-hbk-bsl` (PyPI) и расширения VS Code.

## [0.6.7] - 2026-03-21

### Changed
- Имя файла индекса по умолчанию: **`onec-hbk-bsl_index.sqlite`** (в `.git/` и в `~/.cache/onec-hbk-bsl/…`) вместо `bsl_index.sqlite`; существующий `bsl_index.sqlite` в том же каталоге по-прежнему используется, чтобы не пересоздавать индекс.
- Расширение VS Code: для `[bsl]` по умолчанию включён **`editor.formatOnType`**, чтобы при нажатии Enter LSP выставлял только отступ новой строки (без форматирования всего модуля).
- Makefile: цели **`sync-extension-bin`**, **`extension-bin`**, **`vsix`** — копирование свежего `dist/onec-hbk-bsl*` в `vscode-extension/bin/` и сборка VSIX одной командой, чтобы не попадал устаревший бинарник в пакет.

### Fixed
- BSL062: ложное срабатывание на «неиспользуемый параметр» из-за запятой внутри строки по умолчанию (например `Разделитель = ","`) — имена параметров берутся из AST; regex-фолбэк `_parse_params` не режет список по запятым внутри литералов.
- Общая функция `split_commas_outside_double_quotes` (`analysis/bsl_string_split.py`): те же запятые в строках учтены в BSL142, BSL240 (фолбэк), LSP — doc comment для процедуры, сниппеты по сигнатуре, inlay hints и signature help по строке сигнатуры.
- Расширение VS Code: команда **Reindex Workspace** при откате на CLI больше не вызывает голый `onec-hbk-bsl` из `PATH` — подставляется тот же полный путь к бинарнику, что и для LSP; если LSP не запущен, индексация через терминал всё равно возможна при известном бинарнике.
- LSP (stdio): исправлена длина заголовка `Content-Length` для JSON-RPC с не-ASCII (кириллица в hover/символах и т.д.): pygls считал `len(str)` вместо длины UTF-8 в байтах, из‑за чего VS Code терял синхронизацию потока (`Header must provide a Content-Length property`).
- BSL035: повторы строковых литералов учитываются **в пределах одной процедуры/функции** (и отдельно на уровне модуля), а не по всему файлу — убраны ложные срабатывания на одинаковых ключах `Вставить("…")` в разных методах.

### Added
- Документация аудита: `docs/SECURITY_AUDIT.md`, `docs/THIRD_PARTY_NOTICES.md`, `docs/DATA_SOURCES.md`; ссылки из корневого `README.md`.
- `.gitleaks.toml` и workflow **Security** (Gitleaks в CI).

### Changed
- **Ребренд продукта:** PyPI-пакет и CLI — `onec-hbk-bsl`, Python-модуль — `onec_hbk_bsl`, кеш — `~/.cache/onec-hbk-bsl/`, VS Code — id `mussolene.1c-hbk-bsl`, настройки/команды — `onecHbkBsl.*`; конфиг-проект: `onec-hbk-bsl.toml` / `[tool."onec-hbk-bsl"]` в `pyproject.toml`.
- Расширение VS Code: тег GitHub-релиза для fallback-скачивания бинарника берётся как `v` + `version` из `package.json` (согласовано с публикуемой версией расширения).

## [0.6.6] - 2026-03-20

### Changed
- Расширение VS Code: поиск бинарника **не** выполняется по системному `PATH` — используйте явный `onecHbkBsl.serverPath`, бинарник из VSIX (`bin/`) или скачанный в хранилище расширения.

## [0.6.5] - 2026-03-20

### Changed
- Расширение VS Code: активация по `onLanguage:bsl` и `onCommand:*` вместо `*` (производительность).
- Сборка VSIX: убран флаг `--allow-star-activation` у `vsce` (больше не нужен).

### Fixed
- Синхронизированы версии Python-пакета (`pyproject.toml`, `__version__`) и расширения (`package.json`).

## [0.3.0] - 2026-03-19

### Added
- `vscode-extension/README.md`, `vscode-extension/LICENSE` (MIT) — документация и лицензия внутри VSIX; сборка расширения через **webpack** (`npm run compile`), в CI добавлены `npm run typecheck` и `--no-dependencies` / `--allow-star-activation` для `vsce package`.
- `diagnostics_ru.py` — полная русская локализация 147 диагностических правил в панели Problems:
  - Заголовок на русском (`title`) + рекомендация что делать (`hint` со значком 💡)
  - Поддержка 50+ правил BSL001–BSL147
  - Извлечение конкретных значений из английских сообщений (имена переменных, счётчики)
- Hover-карточки полностью на русском: «Определено в», «Возвращает», «Вызывается в N местах»
- Поддержка методов через точку (`Объект.Метод()`): поиск в типах платформы
- Quick-fix действия (`Cmd+.`): BSLLS-off/on вокруг строки, noqa-комментарий, для всего файла
- `DiagnosticEngine.DEFAULT_DISABLED` — правила отключённые по умолчанию (аналогично BSL LS):
  - `BSL121` (TabIndentation) — табуляция не ошибка, стилистика

### Changed
- **BSL018** (RaiseWithLiteral): отключено по умолчанию; подсказки ссылаются на расширенный синтаксис `ВызватьИсключение` (8.3.21+), без `НовоеИсключение()`; включение — через `select`/настройки движка.
- **RULE_METADATA[`name`]**: приведены к совместимым diagnostic aliases (`*Diagnostic` без суффикса); прямая карта `_BSLLS_NAME_TO_CODE` только для подавлений `// BSLLS:…` и внешних отчётов — без лишних синонимов-ключей.

### Fixed
- Критическая ошибка производительности: `find_symbol` не использовал B-tree индекс из-за `LOWER()` —
  добавлена предвычисленная колонка `name_lower`, запрос ускорен с 5 с до <5 мс
- `idx_calls_callee` указывал на неверную колонку → `find_callers` занимал 32 с; исправлено до 13 мс
- `ORDER BY` в `find_symbol` вызывал создание временного B-tree на 3000+ строках (484 мс → 3 мс)
- `publish_diagnostics` pygls 2.0: `ls.publish_diagnostics()` → `ls.text_document_publish_diagnostics()`
- Форматтер: операторы препроцессора `#Если/#КонецЕсли` не влияют на отступы основного модуля
- Форматтер: при выделении фрагмента форматируется только он (range formatting с контекстом)
- Форматтер: добавлена поддержка `Выбор/Когда/КонецВыбора`
- Подавлены лишние предупреждения `Cancel notification for unknown message id` в Output
- Исправлены 6 неверных маппингов в `diagnostics_ru.py`:
  - BSL018, BSL021, BSL028, BSL034, BSL047, BSL054 теперь соответствуют реальным правилам
- Миграция БД переведена в фоновый поток — LSP сервер не блокируется при старте

## [0.2.0] - 2026-03-19

### Added
- Branded icons for VSCode extension, LSP server and MCP server
- Extension icon registered in package.json for VS Marketplace

### Fixed
- Removed unused `defusedxml` dependency
- Fixed ruff I001/E402/F401 import errors in tests (CI now passes)

## [0.1.0] - 2024-03-19

### Added
- LSP server with full IntelliSense for BSL (1C Enterprise)
  - Go to definition (`F12`)
  - Find all references (`Shift+F12`)
  - Call hierarchy (`Shift+Alt+H`) — incoming and outgoing calls
  - Hover documentation with signature and doc-comment
  - Completions: 500+ platform functions + workspace symbols
  - Rename symbol (`F2`)
  - Document and range formatting
  - Semantic tokens
  - Inlay hints (parameter names at call sites)
  - Smart selection (`Shift+Alt+→`)
  - Folding ranges (`#Область` / `#КонецОбласти`)
  - Code actions (quick fixes)
  - Real-time diagnostics with 0.6s debounce
- VSCode extension
  - Official TextMate grammar from 1c-syntax/vsc-language-1c-bsl
  - 219 snippets (RU + EN) for all 1C metadata types
  - Bundled native binary (no Python required)
  - Auto-download from GitHub Releases if binary not found
  - Status bar showing symbol count
  - Commands: Reindex Workspace, Reindex File, Show Status
- MCP server with tools: `bsl_find_symbol`, `bsl_callers`, `bsl_callees`,
  `bsl_diagnostics`, `bsl_definition`, `bsl_file_symbols`, `bsl_status`
- CLI linter: `onec-hbk-bsl --check` with SARIF / SonarQube / JSON output
- Incremental SQLite index (FTS5), ~600 files/sec
- 30+ diagnostic rules (BSL001–BSL055)
- Standalone native binary (no system Python required)

[Unreleased]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.8.18...HEAD
[0.8.18]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.8.17...v0.8.18
[0.8.17]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.8.16...v0.8.17
[0.8.16]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.8.15...v0.8.16
[0.3.0]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mussolene/1c_hbk_bsl/releases/tag/v0.1.0
