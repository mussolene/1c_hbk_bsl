"""Shared helpers for diagnostic semantic test families."""

from __future__ import annotations

import textwrap
from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.i18n import get_rule
from onec_hbk_bsl.analysis.diagnostics import Diagnostic, DiagnosticEngine


def _engine(**kwargs) -> DiagnosticEngine:
    return DiagnosticEngine(**kwargs)


def _check(content: str, tmp_path: Path, **engine_kwargs) -> list[Diagnostic]:
    """Write content to a temporary BSL file and run the diagnostic engine."""
    bsl_file = tmp_path / "test.bsl"
    bsl_file.write_text(textwrap.dedent(content), encoding="utf-8")
    return DiagnosticEngine(**engine_kwargs).check_file(str(bsl_file))


def _codes(diags: list[Diagnostic]) -> list[str]:
    return [diagnostic.code for diagnostic in diags]


def _rule_msg(code: str) -> str:
    return get_rule(code).message
