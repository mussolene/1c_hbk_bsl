# Third-party notices

This project (**onec-hbk-bsl**) is distributed under the [MIT License](../LICENSE). It builds on many open-source packages. This file summarizes **runtime** and **tooling** dependencies for compliance review. It is not legal advice.

## Regenerate (Python)

Runtime-only tree (matches `pip install onec-hbk-bsl` / `uv pip install -e .` without dev extras):

```bash
uv venv /tmp/bsl-lic-tmp -p 3.14
uv pip install pip-licenses --python /tmp/bsl-lic-tmp/bin/python
uv pip install -e . --python /tmp/bsl-lic-tmp/bin/python
/tmp/bsl-lic-tmp/bin/pip-licenses --from=mixed --format=markdown --with-urls --order=license
```

## Regenerate (VS Code extension / npm)

From `vscode-extension/`:

```bash
npx license-checker --production --csv
```

## Direct runtime dependencies (Python, declared in `pyproject.toml`)

| Package | SPDX / PyPI license | Notes |
|---------|----------------------|--------|
| tree-sitter | MIT | Parser runtime |
| tree-sitter-bsl | MIT | BSL grammar ([alkoleft/tree-sitter-bsl](https://github.com/alkoleft/tree-sitter-bsl)) |
| watchfiles | MIT | File watching |
| fastmcp | Apache-2.0 | MCP server framework |
| pygls | Apache-2.0 | LSP framework ([pygls](https://github.com/openlawlibrary/pygls), per `LICENSE.txt` in wheel) |
| rich | MIT | Terminal UI |

Transitive dependencies include **MIT**, **Apache-2.0**, **BSD-2/3-Clause**, **ISC**, **MPL-2.0** (certifi), **PSF-2.0** (typing_extensions), **Unlicense** (email-validator), and others compatible with redistribution of this project under MIT, provided license texts are preserved where required.

### Packages with mixed / notable license metadata

| Package | Note |
|---------|------|
| **docutils** | PyPI metadata lists multiple licenses (BSD/GPL/Public Domain). Typical use is under the permissive terms; verify for your distribution if you vendor docutils separately. |
| **cryptography** | Apache-2.0 OR BSD-3-Clause (dual). |
| **packaging** | Apache-2.0 OR BSD-2-Clause. |

## Build-only dependencies (`[project.optional-dependencies]`)

| Package | License | Note |
|---------|---------|------|
| **PyInstaller** | GPL-2.0-or-later (bootloader and tools have additional permissive terms; see [PyInstaller licensing](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt)) | Used in CI and local builds to produce standalone onefile binaries (`packaging/onec-hbk-bsl.spec` — import graph from `__main__.py`, no `collect_all`). |
| pytest, pytest-cov, ruff | MIT / Apache-2.0 | Tests and lint only — not shipped in the wheel. |

## High-level credits (see also [README](../README.md))

| Project | License | Role |
|---------|---------|------|
| [vsc-language-1c-bsl](https://github.com/1c-syntax/vsc-language-1c-bsl) | MIT | Platform API reference data lineage (see [DATA_SOURCES.md](DATA_SOURCES.md)) |
| [tree-sitter-bsl](https://github.com/alkoleft/tree-sitter-bsl) | MIT | Grammar |
| [bsl-language-server](https://github.com/1c-syntax/bsl-language-server) | LGPL-3.0 | Diagnostic **codes/names** reference only — **not** linked or bundled as a runtime dependency |

## VS Code extension — production `npm` dependencies

Resolved with `license-checker --production` (extension `vscode-languageclient` stack):

| Module | License |
|--------|---------|
| vscode-languageclient | MIT |
| vscode-languageserver-protocol | MIT |
| vscode-languageserver-types | MIT |
| vscode-jsonrpc | MIT |
| semver | ISC |
| minimatch | ISC |
| balanced-match, brace-expansion | MIT |

DevDependencies (webpack, typescript, eslint, etc.) are used only at build time to produce `extension.js`.

## MIT compatibility

All identified **runtime** dependencies used to deliver **onec-hbk-bsl** and the **published VSIX** are under permissive licenses commonly considered **compatible** with distributing this project under MIT, subject to retaining copyright notices where required (Apache-2.0, BSD, etc.). **GPL/LGPL** does not apply to the shipped Python wheel’s dependency tree as of the last automated scan; the **bsl-language-server** relationship is documentary/reference only.
