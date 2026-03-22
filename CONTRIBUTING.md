# Contributing to 1C HBK BSL

Thank you for your interest in contributing!

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- git
- Node.js 20+ (only if working on the VSCode extension)

### Install (Python)

```bash
# Clone the repository
git clone https://github.com/mussolene/1c_hbk_bsl.git
cd 1c_hbk_bsl

# Create a virtual environment and install in editable mode with dev deps
uv venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

uv pip install -e ".[dev]"
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
# All tests
pytest

# With coverage report
pytest --cov=src/onec_hbk_bsl --cov-report=html

# Single test file
pytest tests/test_diagnostics.py -v
```

## Code Style

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Check
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/

# Format
ruff format src/ tests/
```

The ruff configuration is in `pyproject.toml` under `[tool.ruff]`.

## Adding a New Diagnostic Rule

1. Open `src/onec_hbk_bsl/analysis/diagnostics.py`
2. Add a new regex pattern constant (e.g. `_RE_MY_PATTERN = re.compile(...)`)
3. Add a new private method `_rule_bslXXX_description(self, path, content) -> list[Diagnostic]`
4. Call it inside `check_file()`
5. Add tests in `tests/test_diagnostics.py` following the existing pattern
6. See [docs/cst_policy.md](docs/cst_policy.md); refresh [docs/bsl_rules_matrix.md](docs/bsl_rules_matrix.md) if your workflow regenerates it

Rule naming convention: `BSL001–BSL099` are reserved for core rules.
Community rules start at `BSL200`.

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
- For new or renamed rules, refresh [docs/bsl_rules_matrix.md](docs/bsl_rules_matrix.md) if your workflow regenerates it.
- Optional: add a line to [CHANGELOG.md](CHANGELOG.md) for user-visible behavior changes.

## Pull Request Checklist

- [ ] Tests added/updated for the change
- [ ] `ruff check` passes with no new errors
- [ ] `pytest` passes
- [ ] `docs/architecture.md` or `README.md` / `docs/Production-Notes.md` updated if public behavior or settings changed
- [ ] Commit message is descriptive (what & why, not just what)
