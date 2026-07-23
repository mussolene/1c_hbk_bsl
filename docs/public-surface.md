# Public Surface

This document defines what `onec-hbk-bsl` treats as product-facing API and UI.
It is a guardrail for future changes, not a user guide. User-facing docs live in
[README.md](../README.md) and [vscode-extension/README.md](../vscode-extension/README.md).

## Documentation Ownership

This table is the documentation index and the normative ownership registry.
Each owner key appears exactly once and owns only the facts named in its scope.
Other documents may explain or operate a surface, but must link to its canonical
owner instead of defining a second compatibility contract.

<!-- docs-index:start -->
| Owner key | Canonical owner | Normative scope |
|---|---|---|
| `product-guide` | [README.md](../README.md) | Product overview, installation, first-run examples and navigation into detailed docs |
| `product-contract` | [public-surface.md](public-surface.md) | Stable CLI, Python, LSP, MCP, configuration and packaging compatibility |
| `extension-guide` | [vscode-extension/README.md](../vscode-extension/README.md) | Published extension settings, startup resolution, commands and editor behavior |
| `diagnostics-reference` | [diagnostic-rules.md](diagnostic-rules.md) | Generated public rule identifiers, aliases, severity, descriptions and implementation state |
| `release-history` | [CHANGELOG.md](../CHANGELOG.md) | Versioned user-visible changes reconstructed from release tags |
| `operations` | [Production-Notes.md](Production-Notes.md) | Operational runbook, go/no-go checks and dated verification snapshots; not a compatibility contract |
| `architecture` | [architecture.md](architecture.md) | Current internal component, data-flow and storage design; not a product promise |
| `third-party` | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Dependency provenance, notices and redistribution notes |
<!-- docs-index:end -->

Product boundaries with adjacent repositories are tracked only in
[issue #8](https://github.com/mussolene/1c_hbk_bsl/issues/8). This index must
not create a second product-boundary backlog.

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
- LSP rename and MCP `bsl_rename` share exact semantic spans. MCP rename dry-run
  returns an immutable plan; `apply=true` is all-or-nothing and refuses
  ambiguity, collisions, or stale content before writing.

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
| MCP | project-local navigation/diagnostics plus exact-span transactional `bsl_rename` |
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
