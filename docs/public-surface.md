# Public Surface

This document defines the product-facing contract for `onec-hbk-bsl`.
Development-only tools may exist in the repository, but they should not be the
main user-facing story.

## Product Standard

- Primary project config: `onec-hbk-bsl.toml`.
- `pyproject.toml` support is a convenience for Python-centric projects.
- Suppression comments in source code are supported for compatibility, including
  `// noqa: BSL###` and `// BSLLS-off/on`.
- `.bsl-language-server.json` is not a supported project config.
- Java/BSLLS is not launched at runtime.
- Public docs should describe `onec-hbk-bsl` behavior directly, not as a wrapper
  around another analyzer.

## Diagnostic Rule Identifiers

- `BSL###` is the stable product code for diagnostics output, `--select`,
  `--ignore`, `onec-hbk-bsl.toml`, SARIF/JSON, and `// noqa: BSL###`.
- `BSLLS key` is the compatible diagnostic name from BSL Language Server
  semantics, such as `LineLength` or `ConsecutiveEmptyLines`.
- CLI and config accept both forms; output surfaces use `BSL###`.
- Rule numbering is stable but not continuous. Missing numbers are not valid
  rule identifiers unless they appear in the generated rule reference.
- The generated rule reference is [diagnostic-rules.md](diagnostic-rules.md).

## CLI Classification

### Core User Commands

These are the stable commands users should see first:

```bash
onec-hbk-bsl check .
onec-hbk-bsl format .
onec-hbk-bsl rules
onec-hbk-bsl init
onec-hbk-bsl --version
```

Core options:

- `--select`
- `--ignore`
- `--format text|json|sarif`
- `--jobs`
- `--fix`

### Compatibility Aliases

The command form is the preferred product surface. The legacy mode-flag form is
also supported for editor/runtime compatibility and existing scripts:

| Preferred | Alias |
|---|---|
| `onec-hbk-bsl check .` | `onec-hbk-bsl --check .` |
| `onec-hbk-bsl lsp` | `onec-hbk-bsl --lsp` |
| `onec-hbk-bsl mcp` | `onec-hbk-bsl --mcp` |
| `onec-hbk-bsl index PATH` | `onec-hbk-bsl --index PATH` |
| `onec-hbk-bsl rules` | `onec-hbk-bsl --list-rules` |
| `onec-hbk-bsl init` | `onec-hbk-bsl --init` |

Do not add new product behavior only to the alias form.

### CI Commands

These are stable for automation:

- `--format json`
- `--format sarif`
- `--exit-zero`
- `--baseline`
- `--update-baseline`
- `--diff`
- `--since`
- `--paths-from`

### Server Commands

These are stable integration points:

- `lsp`
- `mcp`
- `mcp --stdio`
- `mcp --workspace PATH`
- `index PATH`

### Removed Non-Product Switches

These switches are intentionally not part of the product CLI. They either
leaked implementation details, duplicated editor/LSP behavior, or were covered
by simpler formats and config:

- `--watch`
- `--bench`
- `--stats`
- `--show-fix`
- `--check-profile`
- `--paths-from0`
- `--changed-lines-only`
- `--split-fragment`
- `--format sonarqube`
- `--sonar-root`

Do not reintroduce these as compatibility aliases. If a need returns, add a
clear workflow-level command or config field instead of another engine switch.

## Library API

Stable import surface:

```python
from onec_hbk_bsl import check_files
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
```

The library contract should expose diagnostics, formatting and config loading.
It should not expose parity scripts, benchmark helpers, MCP handler internals or
VS Code extension implementation details as stable API.

## VS Code Extension

The extension docs should focus on:

- how the server is found;
- diagnostics and formatting;
- project config vs editor settings;
- Docker LSP as an advanced runtime option;
- command palette actions.

Packaging, release mechanics and binary-cache details belong in development
docs, not in the Marketplace README.

## Documentation Layers

Recommended layers:

- `README.md`: quick guide and links.
- `vscode-extension/README.md`: user-facing extension guide.
- `docs/diagnostic-rules.md`: generated rule reference for users and integrators.
- `docs/public-surface.md`: public contract and CLI classification.
- `docs/architecture.md`: implementation architecture.
- `docs/Production-Notes.md`: runbook for maintainers.
- `docs/archive/`: historical plans and old roadmaps.
