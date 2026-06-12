# onec-hbk-bsl

Full meta package for the `onec-hbk-bsl` toolkit.

Install this package for the default backwards-compatible user-facing surface:
CLI, formatter, diagnostics, LSP, Python API, and MCP.

```bash
pip install onec-hbk-bsl
```

The implementation lives in `onec-hbk-bsl-core`. Install that package directly
when you need the slim formatter/diagnostics/Python API surface without MCP
dependencies.

```bash
pip install onec-hbk-bsl-core
```

Install MCP support for a direct core installation with:

```bash
pip install "onec-hbk-bsl-core[mcp]"
```
