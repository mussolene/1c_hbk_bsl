"""
BSL lint CLI — ruff-style output with parallel processing.

Formats
-------
text       — path:line:col: SEVERITY CODE message  (default, like ruff/flake8)
json       — structured JSON array
sonarqube  — SonarQube Generic Issue Import Format (for sonar-scanner)

SonarQube integration
---------------------
Pass the output of ``--format sonarqube`` to sonar-scanner via::

    sonar.externalIssuesReportPaths=bsl-issues.json

Use ``--sonar-root`` to produce project-relative file paths required by SonarQube.

Exit codes
----------
0 — no issues found
1 — one or more issues found
2 — internal error (unreadable file, etc.)
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.text import Text

from bsl_analyzer.analysis.diagnostics import (
    RULE_METADATA,
    Diagnostic,
    DiagnosticEngine,
    Severity,
)

console = Console(stderr=True)

# Severity abbreviation and colour for text output
_SEV_STYLE = {
    Severity.ERROR: ("E", "bold red"),
    Severity.WARNING: ("W", "yellow"),
    Severity.INFORMATION: ("I", "blue"),
    Severity.HINT: ("H", "dim"),
}

# SonarQube severity mapping
_SONAR_SEVERITY = {
    Severity.ERROR: "BLOCKER",
    Severity.WARNING: "MAJOR",
    Severity.INFORMATION: "MINOR",
    Severity.HINT: "INFO",
}

BSL_EXTENSIONS = {".bsl", ".os"}


def check(
    paths: list[str],
    format: str = "text",
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    jobs: int = 0,
    sonar_root: str | None = None,
) -> int:
    """
    Run BSL lint rules on all .bsl/.os files under *paths*.

    Args:
        paths:      Files or directories to check.
        format:     Output format: ``text`` (default), ``json``, or ``sonarqube``.
        select:     If provided, run only these rule codes (e.g. ``{"BSL001", "BSL002"}``).
        ignore:     Rule codes to skip (e.g. ``{"BSL002"}``).
        jobs:       Worker threads (0 = auto-detect from CPU count, 1 = serial).
        sonar_root: Project root for SonarQube relative path calculation.

    Returns:
        Exit code: 0 = clean, 1 = issues found, 2 = error.
    """
    all_files = _collect_files(paths)
    if not all_files:
        console.print("[yellow]No .bsl/.os files found.[/yellow]")
        return 0

    all_diagnostics, error_occurred = _run_checks(
        sorted(all_files), select=select, ignore=ignore, jobs=jobs
    )

    if error_occurred:
        return 2

    if format == "json":
        _print_json(all_diagnostics)
    elif format == "sonarqube":
        _print_sonarqube(all_diagnostics, sonar_root)
    else:
        _print_text(all_diagnostics)
        if not all_diagnostics:
            console.print(
                f"[green]All clean.[/green] Checked {len(all_files)} file(s)."
            )
            return 0
        _print_summary(all_diagnostics, len(all_files))

    return 0 if not all_diagnostics else 1


def list_rules() -> None:
    """Print a formatted table of all available rules to stdout."""
    from rich.table import Table

    table = Table(title="BSL Analyzer Rules", show_lines=True)
    table.add_column("Code", style="bold cyan", width=8)
    table.add_column("Name", style="bold", width=32)
    table.add_column("Severity", width=12)
    table.add_column("SonarQube Type", width=16)
    table.add_column("Description")

    sev_colors = {
        "ERROR": "bold red",
        "WARNING": "yellow",
        "INFORMATION": "blue",
        "HINT": "dim",
    }

    for code, meta in sorted(RULE_METADATA.items()):
        sev = meta["severity"]
        table.add_row(
            code,
            meta["name"],
            f"[{sev_colors.get(sev, 'white')}]{sev}[/]",
            meta["sonar_type"],
            meta["description"],
        )

    Console().print(table)


# ---------------------------------------------------------------------------
# Internal processing
# ---------------------------------------------------------------------------


def _run_checks(
    files: list[str],
    select: set[str] | None,
    ignore: set[str] | None,
    jobs: int,
) -> tuple[list[Diagnostic], bool]:
    """Run checks in parallel (or serial if jobs=1). Returns (diagnostics, error_flag)."""

    def _make_engine() -> DiagnosticEngine:
        return DiagnosticEngine(select=select, ignore=ignore)

    workers = jobs if jobs > 0 else min(os.cpu_count() or 4, 8)

    all_diagnostics: list[Diagnostic] = []
    error_occurred = False

    if workers == 1 or len(files) <= 1:
        engine = _make_engine()
        for fp in files:
            try:
                all_diagnostics.extend(engine.check_file(fp))
            except Exception as exc:
                console.print(f"[red]Error checking {fp}: {exc}[/red]")
                error_occurred = True
    else:
        # Each thread gets its own engine (BslParser is not thread-safe to share)
        def _check_one(fp: str) -> list[Diagnostic]:
            return _make_engine().check_file(fp)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_check_one, fp): fp for fp in files}
            for future in as_completed(futures):
                fp = futures[future]
                try:
                    all_diagnostics.extend(future.result())
                except Exception as exc:
                    console.print(f"[red]Error checking {fp}: {exc}[/red]")
                    error_occurred = True

    all_diagnostics.sort(key=lambda d: (d.file, d.line, d.character))
    return all_diagnostics, error_occurred


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _print_text(diagnostics: list[Diagnostic]) -> None:
    """Print ruff/flake8-style text output to stderr."""
    for d in diagnostics:
        abbr, style = _SEV_STYLE.get(d.severity, ("?", "white"))
        line_str = f"{d.file}:{d.line}:{d.character}: {abbr} {d.code} {d.message}"
        text = Text(line_str)
        offset = len(d.file) + len(str(d.line)) + len(str(d.character)) + 4
        text.stylize(style, offset)
        console.print(text, highlight=False)


def _print_json(diagnostics: list[Diagnostic]) -> None:
    """Print JSON array of diagnostic dicts to stdout."""
    data = [d.to_dict() for d in diagnostics]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_sonarqube(
    diagnostics: list[Diagnostic], project_root: str | None = None
) -> None:
    """
    Print SonarQube Generic Issue Import Format JSON to stdout.

    See: https://docs.sonarqube.org/latest/analyzing-source-code/importing-external-issues/
    """
    issues = []
    for d in diagnostics:
        meta = RULE_METADATA.get(d.code, {})

        # Resolve file path — SonarQube requires project-relative paths
        file_path = d.file
        if project_root:
            try:
                file_path = str(Path(d.file).relative_to(project_root))
            except ValueError:
                pass  # keep absolute if not under project_root

        # Map severity
        sonar_sev = meta.get("sonar_severity") or _SONAR_SEVERITY.get(
            d.severity, "MAJOR"
        )
        sonar_type = meta.get("sonar_type", "CODE_SMELL")

        issue: dict = {
            "engineId": "bsl-analyzer",
            "ruleId": d.code,
            "severity": sonar_sev,
            "type": sonar_type,
            "primaryLocation": {
                "message": d.message,
                "filePath": file_path,
                "textRange": {
                    "startLine": d.line,
                    "endLine": max(d.line, d.end_line),
                    "startColumn": d.character,
                    "endColumn": d.end_character,
                },
            },
        }
        issues.append(issue)

    print(json.dumps({"issues": issues}, indent=2, ensure_ascii=False))


def _print_summary(diagnostics: list[Diagnostic], file_count: int) -> None:
    """Print a rich summary line similar to ruff."""
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
    console.print(f"Found {', '.join(parts)} in {file_count} file(s).")


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
