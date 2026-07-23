# Public Surface

This document defines what `onec-hbk-bsl` treats as product-facing API and UI.
It is a guardrail for future changes, not a user guide. User-facing docs live in
[README.md](../README.md) and [vscode-extension/README.md](../vscode-extension/README.md).

## Product Contract

- Primary project config: `onec-hbk-bsl.toml`.
- `pyproject.toml` support is a convenience for Python-centric projects.
- Stable rule identifiers: `BSL###`.
- Compatible rule aliases are accepted in `select` / `ignore` for existing BSL projects.
- Suppressions: `// noqa: BSL###` and compatible `// BSLLS-off/on` comments.
- `.bsl-language-server.json` is not a supported project config.
- No separate Java analyzer is launched at runtime.
- Configuration precedence is stable across CLI, Python API, LSP, and MCP:
  explicit option > supported environment variable > project config > built-in default.
- Supported config environment mappings are `BSL_SELECT`, `BSL_IGNORE`,
  `BSL_INDEX_MODE`, and `BSL_INDEX_MAX_BYTES`; adding another mapping is a
  public-surface change.

## Stable User Surfaces

| Surface | Stable contract |
|---|---|
| CLI | `check`, `format`, `rules`, `init`, `lsp`, `mcp`, `index` |
| Reports | `--format text`, `--format json`, `--format sarif` |
| Rule control | `--select`, `--ignore`, config `ignore`, per-file ignores |
| Check execution | `--jobs`, `--no-config`, `--fix` |
| CI adoption | `--exit-zero`, `--baseline`, `--update-baseline`, `--diff`, `--since`, `--paths-from` |
| Workspace index | `--force`, `--status`, `--clean`, `--compact`, `--mode`, `--max-bytes` |
| VS Code | diagnostics, formatting, definition/references/rename, call hierarchy, hover, completion, signature help, folding, code actions, inlay hints, semantic tokens |
| Python API | `check_files(...)`, `DiagnosticEngine` |

Legacy flag aliases such as `--check`, `--lsp`, `--mcp`, `--index`,
`--list-rules`, and `--init` remain supported for existing integrations. New
behavior should be added to command forms first.

## Packaging

- `onec-hbk-bsl-core`: CLI, formatter, diagnostics, Python API and LSP without MCP dependencies.
- `onec-hbk-bsl`: full compatibility package depending on the same-version
  `onec-hbk-bsl-core[mcp]` wheel.
- Both PyPI distributions require Python 3.12 or newer.
- Release VSIX artifacts bundle a standalone server for `darwin-arm64`,
  `darwin-x64`, `linux-x64`, and `win32-x64`; they do not require a system Python.
- The extension requires VS Code API 1.85 or newer and binds only `.bsl` / `.os`
  file documents to the LSP client.

Running `onec-hbk-bsl mcp` from a slim core installation without MCP should exit
with a clear installation hint rather than an import traceback.

## Non-Product Surface

Do not expose these as stable CLI/API features:

- research or comparison scripts;
- benchmark helpers;
- MCP handler internals;
- VS Code extension implementation details;
- removed switches such as `--watch`, `--bench`, `--stats`, `--show-fix`,
  `--check-profile`, `--paths-from0`, `--changed-lines-only`,
  `--split-fragment`, `--format sonarqube`, `--sonar-root`.

Development docs may mention internal tools, but README and Marketplace docs
should stay focused on how to install, configure, run, and troubleshoot the
product.
