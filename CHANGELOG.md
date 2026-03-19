# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- BSLLS block-level suppression compatible with `1c-syntax/bsl-language-server`:
  - `// BSLLS:RuleName-off` / `// BSLLS:RuleName-on` — disable/re-enable specific rule
  - `// BSLLS-off` / `// BSLLS-on` — disable/re-enable all diagnostics
  - Russian flags supported: `-выкл` / `-вкл`
  - 50+ BSLLS diagnostic names mapped to BSL rule codes (`_BSLLS_NAME_TO_CODE`)
  - Multiple rules can be independently nested and toggled
  - 8 new tests covering all suppression scenarios

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
- CLI linter: `bsl-analyzer --check` with SARIF / SonarQube / JSON output
- Incremental SQLite index (FTS5), ~600 files/sec
- 30+ diagnostic rules (BSL001–BSL055)
- Nuitka build system for standalone native binary (~40 MB)

[Unreleased]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mussolene/1c_hbk_bsl/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mussolene/1c_hbk_bsl/releases/tag/v0.1.0
