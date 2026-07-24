# Contributing to 1C HBK BSL

Thank you for your interest in contributing!

## Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- git
- Node.js 20+ (only if working on the VSCode extension)

### Install (Python)

```bash
# Clone the repository
git clone https://github.com/mussolene/1c_hbk_bsl.git
cd 1c_hbk_bsl

# Create/update the project virtual environment from the lockfile
uv sync --all-extras

# Verify that the project runtime is available
./.venv/bin/python --version          # Linux/macOS
# .venv\Scripts\python.exe --version  # Windows
```

### Install (VSCode Extension)

```bash
cd vscode-extension
npm ci
npm run compile
```

### Локальный VSIX и бинарник сервера

Бинарник для расширения лежит в **`vscode-extension/bin/`** (каталог в `.gitignore`). Чтобы в VSIX не попал устаревший файл, после **`make build`** всегда копируйте артефакт из `dist/`:

- **`make extension-bin`** — `make build` и копирование `dist/onec-hbk-bsl*` → `vscode-extension/bin/`
- **`make sync-extension-bin`** — только копирование (если `make build` уже выполняли)
- **`make vsix`** — `extension-bin`, затем `npm run compile` и `vsce package` → `vscode-extension/onec-hbk-bsl-<version>-local.vsix`

Перед первым `make vsix` установите зависимости: `cd vscode-extension && npm ci`.

На **Windows** без GNU Make: скопируйте `dist\onec-hbk-bsl.exe` в `vscode-extension\bin\onec-hbk-bsl.exe`, затем `cd vscode-extension && npm run compile && npx @vscode/vsce package --no-dependencies`.

## Running Tests

```bash
# All tests with the configured coverage gate
./.venv/bin/python -m pytest -q

# With coverage report
./.venv/bin/python -m pytest --cov-report=html

# Single test file
./.venv/bin/python -m pytest tests/test_diagnostics.py -v
```

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check
./.venv/bin/python -m ruff check src tests scripts

# Fix auto-fixable issues
./.venv/bin/python -m ruff check --fix src tests scripts

# Format
./.venv/bin/python -m ruff format src tests scripts
```

The ruff configuration is in `pyproject.toml` under `[tool.ruff]`.

## Adding a New Diagnostic Rule

1. Read the rule description and create or update its public page in
   `docs/rule-contracts/BSL###.md`.
2. Add or update metadata in `src/onec_hbk_bsl/analysis/diagnostics.py`.
3. Reuse `DocumentSnapshot`, CST facts, or an existing domain model. Do not add
   a regex fallback to a structural rule without a documented semantic reason.
4. Register execution through `analysis/diagnostic/diagnostic_runtime` and keep
   shared semantic work outside individual rule callbacks.
5. Add focused positive, negative, range, and malformed-input tests.
6. Regenerate and check the public rule reference:

```bash
./.venv/bin/python scripts/build_diagnostic_rules_doc.py
git diff --exit-code -- docs/diagnostic-rules.md docs/rule-contracts
./.venv/bin/python -m onec_hbk_bsl rules
```

See [docs/cst_policy.md](docs/cst_policy.md) for structural-rule policy and
[docs/diagnostics_rule_invoke.md](docs/diagnostics_rule_invoke.md) for runtime
execution phases.

### Rule severity guidelines

| Severity    | When to use                                              |
|-------------|----------------------------------------------------------|
| ERROR       | Code that will fail at runtime or won't compile          |
| WARNING     | Likely bugs, anti-patterns, or maintainability issues    |
| INFORMATION | Style suggestions                                        |
| HINT        | Very minor nits, auto-fixable issues                     |

## Architecture Overview

See [docs/architecture.md](docs/architecture.md) for the component diagram,
data flow, and SQLite schema. Operational notes: [docs/Production-Notes.md](docs/Production-Notes.md).

## Documentation (user-facing changes)

If the PR changes LSP/MCP behavior, diagnostic rules, VS Code settings in `vscode-extension/package.json`, or MCP tool names:

- Update [README.md](README.md) and/or [docs/Production-Notes.md](docs/Production-Notes.md) as needed.
- For new or renamed rules, verify `./.venv/bin/python -m onec_hbk_bsl rules`
  and update user-facing docs when behavior changes.
- Optional: add a line to [CHANGELOG.md](CHANGELOG.md) for user-visible behavior changes.

## Pull Request Checklist

- [ ] Tests added/updated for the change
- [ ] `./.venv/bin/python -m ruff check src tests scripts` passes
- [ ] `./.venv/bin/python -m ruff format --check src tests scripts` passes
- [ ] `./.venv/bin/python -m pytest -q` passes
- [ ] Extension lint, typecheck, and compile pass when extension code or settings change
- [ ] Generated diagnostic documentation and rule contracts are current
- [ ] `docs/architecture.md` or `README.md` / `docs/Production-Notes.md` updated if public behavior or settings changed
- [ ] Commit message is descriptive (what & why, not just what)
