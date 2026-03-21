"""
Baseline support for onec-hbk-bsl.

A baseline records known issues so that only *new* issues cause a non-zero
exit code.  This is useful for gradual adoption on legacy codebases.

Workflow
--------
1. Create initial baseline (records all current issues as "known"):

   .. code-block:: bash

       onec-hbk-bsl --check . --update-baseline bsl-baseline.json

2. On subsequent runs, only issues *not* in the baseline are reported:

   .. code-block:: bash

       onec-hbk-bsl --check . --baseline bsl-baseline.json

3. After fixing issues, update the baseline to shrink it:

   .. code-block:: bash

       onec-hbk-bsl --check . --update-baseline bsl-baseline.json

Baseline key
------------
A diagnostic is identified by ``(basename, code, line)`` — line numbers shift
when code is refactored, but this is a reasonable heuristic.  The full absolute
path is intentionally *not* used so that baselines remain valid after the repo
is cloned to a different location.
"""

from __future__ import annotations

import json
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import Diagnostic


def _key(d: Diagnostic) -> tuple[str, str, int]:
    """Stable identity key: (filename-only, code, line)."""
    return (Path(d.file).name, d.code, d.line)


def load_baseline(path: str) -> set[tuple[str, str, int]]:
    """
    Load a baseline JSON file.

    Returns an empty set if the file does not exist or is malformed.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {(item["file"], item["code"], item["line"]) for item in data}
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return set()


def save_baseline(diagnostics: list[Diagnostic], path: str) -> int:
    """
    Write *diagnostics* to *path* as a baseline JSON file.

    Returns the number of entries written.
    """
    data = [
        {"file": Path(d.file).name, "code": d.code, "line": d.line}
        for d in diagnostics
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return len(data)


def filter_baseline(
    diagnostics: list[Diagnostic],
    baseline: set[tuple[str, str, int]],
) -> list[Diagnostic]:
    """Remove diagnostics whose key is present in *baseline*."""
    return [d for d in diagnostics if _key(d) not in baseline]
