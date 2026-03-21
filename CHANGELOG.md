# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **RULE_METADATA[`name`]**: приведены к именам диагностик **BSL Language Server** (`*Diagnostic` без суффикса), в духе копирования справочника BSLLS; прямая карта `_BSLLS_NAME_TO_CODE` только для подавлений `// BSLLS:…` и внешних отчётов — без лишних синонимов-ключей.

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
- Nuitka build system for standalone native binary (~40 MB)

[Unreleased]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mussolene/1c_hbk_bsl/releases/tag/v0.1.0
