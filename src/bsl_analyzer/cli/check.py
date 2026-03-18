"""
BSL lint CLI — ruff-style output.

Formats
-------
text  — path:line:col: SEVERITY CODE message  (default, like ruff/flake8)
json  — structured JSON array

Exit codes
----------
0 — no issues found
1 — one or more issues found
2 — internal error (unreadable file, etc.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.text import Text

from bsl_analyzer.analysis.diagnostics import Diagnostic, DiagnosticEngine, Severity
from bsl_analyzer.parser.bsl_parser import BslParser

console = Console(stderr=True)

# Severity abbreviation and color for text output
_SEV_STYLE = {
    Severity.ERROR: ("E", "bold red"),
    Severity.WARNING: ("W", "yellow"),
    Severity.INFORMATION: ("I", "blue"),
    Severity.HINT: ("H", "dim"),
}

BSL_EXTENSIONS = {".bsl", ".os"}


def check(paths: list[str], format: str = "text") -> int:
    """
    Run BSL lint rules on all .bsl/.os files under *paths*.

    Args:
        paths:  List of files or directories to check.
        format: Output format: "text" (default) or "json".

    Returns:
        Exit code: 0 = clean, 1 = issues found, 2 = error.
    """
    parser = BslParser()
    engine = DiagnosticEngine(parser=parser)

    all_files = _collect_files(paths)
    if not all_files:
        console.print("[yellow]No .bsl/.os files found.[/yellow]")
        return 0

    all_diagnostics: list[Diagnostic] = []

    for file_path in sorted(all_files):
        try:
            issues = engine.check_file(file_path)
            all_diagnostics.extend(issues)
        except Exception as exc:
            console.print(f"[red]Error checking {file_path}: {exc}[/red]")
            return 2

    if format == "json":
        _print_json(all_diagnostics)
    else:
        _print_text(all_diagnostics)

    if not all_diagnostics:
        if format == "text":
            console.print(
                f"[green]All clean.[/green] Checked {len(all_files)} file(s)."
            )
        return 0

    if format == "text":
        _print_summary(all_diagnostics, len(all_files))

    return 1


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _print_text(diagnostics: list[Diagnostic]) -> None:
    """Print ruff/flake8-style text output to stdout."""
    for d in sorted(diagnostics, key=lambda x: (x.file, x.line, x.character)):
        abbr, style = _SEV_STYLE.get(d.severity, ("?", "white"))
        # ruff format: file:line:col: CODE message
        line_str = f"{d.file}:{d.line}:{d.character}: {abbr} {d.code} {d.message}"
        text = Text(line_str)
        text.stylize(style, len(d.file) + len(str(d.line)) + len(str(d.character)) + 4)
        console.print(text, highlight=False)


def _print_json(diagnostics: list[Diagnostic]) -> None:
    """Print JSON array of diagnostic dicts to stdout."""
    data = [d.to_dict() for d in diagnostics]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_summary(diagnostics: list[Diagnostic], file_count: int) -> None:
    """Print a summary line (like ruff's 'Found N errors')."""
    errors = sum(1 for d in diagnostics if d.severity == Severity.ERROR)
    warnings = sum(1 for d in diagnostics if d.severity == Severity.WARNING)
    parts = []
    if errors:
        parts.append(f"[bold red]{errors} error(s)[/bold red]")
    if warnings:
        parts.append(f"[yellow]{warnings} warning(s)[/yellow]")
    other = len(diagnostics) - errors - warnings
    if other:
        parts.append(f"{other} info/hint(s)")

    console.print(
        f"Found {', '.join(parts)} in {file_count} file(s)."
    )


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------


def _collect_files(paths: list[str]) -> list[str]:
    """Recursively collect all .bsl/.os files from paths (files or dirs)."""
    result: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix.lower() in BSL_EXTENSIONS:
                result.append(str(p.resolve()))
        elif p.is_dir():
            for ext in BSL_EXTENSIONS:
                result.extend(str(f.resolve()) for f in p.rglob(f"*{ext}"))
        else:
            console.print(f"[yellow]Path not found: {raw}[/yellow]")
    return result
