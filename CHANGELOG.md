# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/your-org/1c_hbk_bsl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/1c_hbk_bsl/releases/tag/v0.1.0
