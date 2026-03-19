# Contributing to BSL Analyzer

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
npm install
npm run compile
```

## Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=src/bsl_analyzer --cov-report=html

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

1. Open `src/bsl_analyzer/analysis/diagnostics.py`
2. Add a new regex pattern constant (e.g. `_RE_MY_PATTERN = re.compile(...)`)
3. Add a new private method `_rule_bslXXX_description(self, path, content) -> list[Diagnostic]`
4. Call it inside `check_file()`
5. Add tests in `tests/test_diagnostics.py` following the existing pattern
6. Update the rule table in `docs/architecture.md`

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

See [docs/architecture.md](docs/architecture.md) for the full component diagram,
data flow, SQLite schema, and roadmap.

## Pull Request Checklist

- [ ] Tests added/updated for the change
- [ ] `ruff check` passes with no new errors
- [ ] `pytest` passes
- [ ] `docs/architecture.md` updated if new capabilities were added
- [ ] Commit message is descriptive (what & why, not just what)
