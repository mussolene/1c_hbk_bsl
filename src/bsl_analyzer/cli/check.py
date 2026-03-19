"""
BSL lint CLI — ruff-style output with parallel processing.

Formats
-------
text       — path:line:col: SEVERITY CODE message  (default, like ruff/flake8)
compact    — path:line:col: CODE (minimal, good for grep/awk pipelines)
json       — structured JSON array
sonarqube  — SonarQube Generic Issue Import Format (for sonar-scanner)
sarif      — SARIF 2.1.0 (GitHub Code Scanning / GitLab SAST)

SonarQube integration
---------------------
Pass the output of ``--format sonarqube`` to sonar-scanner via::

    sonar.externalIssuesReportPaths=bsl-issues.json

Use ``--sonar-root`` to produce project-relative file paths required by SonarQube.

SARIF / GitHub Code Scanning
-----------------------------
Upload the SARIF file to GitHub via the Code Scanning API or workflow action::

    bsl-analyzer --check . --format sarif > bsl-results.sarif

Exit codes
----------
0 — no issues found  (or --exit-zero is set)
1 — one or more issues found
2 — internal error (unreadable file, etc.)
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from bsl_analyzer import __version__
from bsl_analyzer.analysis.diagnostics import (
    RULE_METADATA,
    Diagnostic,
    DiagnosticEngine,
    Severity,
)
from bsl_analyzer.cli.config import _EMPTY, BslConfig

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

# SARIF level mapping
_SARIF_LEVEL = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFORMATION: "note",
    Severity.HINT: "note",
}

BSL_EXTENSIONS = {".bsl", ".os"}


def check(
    paths: list[str],
    format: str = "text",
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    jobs: int = 0,
    sonar_root: str | None = None,
    exit_zero: bool = False,
    baseline: str | None = None,
    update_baseline: str | None = None,
    config: BslConfig | None = None,
    stats: bool = False,
    show_fix: bool = False,
    fix: bool = False,
) -> int:
    """
    Run BSL lint rules on all .bsl/.os files under *paths*.

    Args:
        paths:           Files or directories to check.
        format:          Output format: ``text``, ``json``, ``sonarqube``, or ``sarif``.
        select:          If provided, run only these rule codes.
        ignore:          Rule codes to skip.
        jobs:            Worker threads (0 = auto-detect, 1 = serial).
        sonar_root:      Project root for SonarQube relative path calculation.
        exit_zero:       Always return 0 (never fail even if issues found).
        baseline:        Path to baseline JSON — suppress known issues.
        update_baseline: Write all found issues to this path, then exit 0.
        config:          Merged ``BslConfig`` (overridden by explicit CLI flags).
        fix:             Auto-fix supported issues in-place.

    Returns:
        Exit code: 0 = clean, 1 = issues found, 2 = error.
    """
    cfg = config or _EMPTY

    # Merge config defaults with explicit flags (CLI wins over config)
    effective_format = format if format != "text" or cfg.format is None else cfg.format
    effective_jobs = jobs if jobs != 0 else (cfg.jobs if cfg.jobs is not None else 0)
    effective_exit_zero = exit_zero or cfg.exit_zero
    effective_baseline = baseline or cfg.baseline

    all_files = _collect_files(paths, cfg)
    if not all_files:
        console.print("[yellow]No .bsl/.os files found.[/yellow]")
        return 0

    all_diagnostics, error_occurred = _run_checks(
        sorted(all_files),
        select=select,
        ignore=ignore,
        jobs=effective_jobs,
        config=cfg,
    )

    if error_occurred:
        return 2

    # --fix: apply in-place auto-fixes before reporting
    if fix:
        all_diagnostics = _apply_fixes_to_files(all_diagnostics)

    # --update-baseline: save & exit 0
    if update_baseline:
        from bsl_analyzer.cli.baseline import save_baseline
        n = save_baseline(all_diagnostics, update_baseline)
        console.print(
            f"[green]Baseline updated:[/green] {n} issue(s) written to {update_baseline}"
        )
        return 0

    # --baseline: suppress known issues
    if effective_baseline:
        from bsl_analyzer.cli.baseline import filter_baseline, load_baseline
        known = load_baseline(effective_baseline)
        suppressed = len(all_diagnostics) - len(
            [d for d in all_diagnostics if (Path(d.file).name, d.code, d.line) not in known]
        )
        all_diagnostics = filter_baseline(all_diagnostics, known)
        if suppressed:
            console.print(
                f"[dim]Suppressed {suppressed} baseline issue(s).[/dim]"
            )

    if effective_format == "json":
        _print_json(all_diagnostics)
    elif effective_format == "sonarqube":
        _print_sonarqube(all_diagnostics, sonar_root)
    elif effective_format == "sarif":
        _print_sarif(all_diagnostics, sonar_root)
    elif effective_format == "compact":
        _print_compact(all_diagnostics)
        if not all_diagnostics:
            return 0
    else:
        _print_text(all_diagnostics, show_fix=show_fix)
        if not all_diagnostics:
            console.print(
                f"[green]All clean.[/green] Checked {len(all_files)} file(s)."
            )
            return 0
        _print_summary(all_diagnostics, len(all_files))

    if stats:
        _print_stats(all_diagnostics, len(all_files))

    if effective_exit_zero:
        return 0
    return 0 if not all_diagnostics else 1


def _apply_fixes_to_files(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """
    Group *diagnostics* by file, call :func:`apply_fixes` for each file,
    print a summary to stderr, and return only the unfixed diagnostics.
    """
    from collections import defaultdict

    from bsl_analyzer.analysis.fix_engine import FIXABLE_RULES, apply_fixes

    by_file: dict[str, list[Diagnostic]] = defaultdict(list)
    for d in diagnostics:
        by_file[d.file].append(d)

    total_applied = 0
    total_errors = 0
    remaining: list[Diagnostic] = []

    for file_path, file_diags in sorted(by_file.items()):
        result = apply_fixes(file_path, file_diags)
        if result.error:
            console.print(f"[red]Fix error {file_path}: {result.error}[/red]")
            total_errors += 1
            remaining.extend(file_diags)
            continue
        applied_set = set(result.applied)
        total_applied += len(result.applied)
        # Keep diagnostics that were not fixed
        remaining.extend(
            d for d in file_diags if d.code not in applied_set or d.code not in FIXABLE_RULES
        )

    if total_applied:
        console.print(f"[green]Fixed {total_applied} issue(s) in-place.[/green]")
    if total_errors:
        console.print(f"[red]Fix failed for {total_errors} file(s).[/red]")

    return remaining


def list_rules(tag: str | None = None) -> None:
    """Print a formatted table of all available rules to stdout.

    Args:
        tag: If provided, only show rules with this tag.
    """
    from rich.table import Table

    from bsl_analyzer.analysis.fix_engine import FIXABLE_RULES

    title = f"BSL Analyzer Rules — tag: {tag}" if tag else "BSL Analyzer Rules"
    table = Table(title=title, show_lines=True)
    table.add_column("Code", style="bold cyan", width=8)
    table.add_column("Name", style="bold", width=32)
    table.add_column("Severity", width=12)
    table.add_column("Fix", width=5)
    table.add_column("Tags", width=24)
    table.add_column("Description")

    sev_colors = {
        "ERROR": "bold red",
        "WARNING": "yellow",
        "INFORMATION": "blue",
        "HINT": "dim",
    }

    shown = 0
    for code, meta in sorted(RULE_METADATA.items()):
        tags = meta.get("tags", [])
        if tag and tag.lower() not in [t.lower() for t in tags]:
            continue
        sev = meta["severity"]
        fixable = "[green]✓[/green]" if code in FIXABLE_RULES else ""
        table.add_row(
            code,
            meta["name"],
            f"[{sev_colors.get(sev, 'white')}]{sev}[/]",
            fixable,
            ", ".join(tags),
            meta["description"],
        )
        shown += 1

    console = Console()
    console.print(table)
    console.print(f"[dim]{shown} rule(s) shown[/dim]")


# ---------------------------------------------------------------------------
# Internal processing
# ---------------------------------------------------------------------------


_PROGRESS_THRESHOLD = 20  # show progress bar only for larger batches


def _run_checks(
    files: list[str],
    select: set[str] | None,
    ignore: set[str] | None,
    jobs: int,
    config: BslConfig | None = None,
    show_progress: bool = True,
) -> tuple[list[Diagnostic], bool]:
    """Run checks in parallel (or serial if jobs=1). Returns (diagnostics, error_flag)."""
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    cfg = config or _EMPTY
    engine_kw = cfg.engine_kwargs()

    def _make_engine(extra_ignore: set[str] | None = None) -> DiagnosticEngine:
        effective_ignore = (ignore or set()) | (extra_ignore or set())
        return DiagnosticEngine(
            select=select,
            ignore=effective_ignore or None,
            **engine_kw,
        )

    workers = jobs if jobs > 0 else min(os.cpu_count() or 4, 8)

    all_diagnostics: list[Diagnostic] = []
    error_occurred = False
    use_progress = show_progress and len(files) >= _PROGRESS_THRESHOLD

    progress_ctx: Any = (
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        if use_progress
        else None
    )

    def _run(task_id: Any = None) -> None:
        nonlocal error_occurred
        if workers == 1 or len(files) <= 1:
            engine = _make_engine()
            for fp in files:
                try:
                    per_file_extra = cfg.get_file_ignores(fp)
                    result = (
                        _make_engine(per_file_extra).check_file(fp)
                        if per_file_extra
                        else engine.check_file(fp)
                    )
                    all_diagnostics.extend(result)
                except Exception as exc:
                    console.print(f"[red]Error checking {fp}: {exc}[/red]")
                    error_occurred = True
                if task_id is not None and progress_ctx is not None:
                    progress_ctx.advance(task_id)
        else:
            def _check_one(fp: str) -> list[Diagnostic]:
                return _make_engine(cfg.get_file_ignores(fp)).check_file(fp)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_check_one, fp): fp for fp in files}
                for future in as_completed(futures):
                    fp = futures[future]
                    try:
                        all_diagnostics.extend(future.result())
                    except Exception as exc:
                        console.print(f"[red]Error checking {fp}: {exc}[/red]")
                        error_occurred = True
                    if task_id is not None and progress_ctx is not None:
                        progress_ctx.advance(task_id)

    if progress_ctx is not None:
        with progress_ctx:
            task_id = progress_ctx.add_task(
                f"[cyan]Checking {len(files)} files…", total=len(files)
            )
            _run(task_id)
    else:
        _run()

    all_diagnostics.sort(key=lambda d: (d.file, d.line, d.character))
    return all_diagnostics, error_occurred


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _print_text(diagnostics: list[Diagnostic], show_fix: bool = False) -> None:
    """Print ruff/flake8-style text output to stderr."""
    from bsl_analyzer.analysis.diagnostics import RULE_FIX_HINTS

    for d in diagnostics:
        abbr, style = _SEV_STYLE.get(d.severity, ("?", "white"))
        line_str = f"{d.file}:{d.line}:{d.character}: {abbr} {d.code} {d.message}"
        text = Text(line_str)
        offset = len(d.file) + len(str(d.line)) + len(str(d.character)) + 4
        text.stylize(style, offset)
        console.print(text, highlight=False)
        if show_fix and d.code in RULE_FIX_HINTS:
            console.print(f"  [dim]fix:[/dim] {RULE_FIX_HINTS[d.code]}", highlight=False)


def _print_compact(diagnostics: list[Diagnostic]) -> None:
    """Print compact output (file:line:col: CODE) to stderr — good for grep/awk pipelines."""
    for d in diagnostics:
        _, style = _SEV_STYLE.get(d.severity, ("?", "white"))
        line_str = f"{d.file}:{d.line}:{d.character}: {d.code}"
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


def _print_sarif(
    diagnostics: list[Diagnostic], project_root: str | None = None
) -> None:
    """
    Print SARIF 2.1.0 JSON to stdout.

    Compatible with GitHub Code Scanning and GitLab SAST.
    """
    # Build rule descriptors
    rules: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    for d in diagnostics:
        if d.code not in seen_rules:
            seen_rules.add(d.code)
            meta = RULE_METADATA.get(d.code, {})
            rules.append(
                {
                    "id": d.code,
                    "name": meta.get("name", d.code),
                    "shortDescription": {"text": meta.get("description", d.code)},
                    "defaultConfiguration": {
                        "level": _SARIF_LEVEL.get(d.severity, "warning")
                    },
                    "properties": {"tags": meta.get("tags", [])},
                }
            )

    results: list[dict[str, Any]] = []
    for d in diagnostics:
        file_uri = Path(d.file).as_uri()
        if project_root:
            try:
                rel = Path(d.file).relative_to(project_root)
                file_uri = rel.as_posix()
            except ValueError:
                pass

        results.append(
            {
                "ruleId": d.code,
                "level": _SARIF_LEVEL.get(d.severity, "warning"),
                "message": {"text": d.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": file_uri},
                            "region": {
                                "startLine": d.line,
                                "startColumn": d.character + 1,
                                "endLine": max(d.line, d.end_line),
                                "endColumn": d.end_character + 1,
                            },
                        }
                    }
                ],
            }
        )

    sarif: dict[str, Any] = {
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "bsl-analyzer",
                        "version": __version__,
                        "informationUri": "https://github.com/bsl-analyzer/bsl-analyzer",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    print(json.dumps(sarif, indent=2, ensure_ascii=False))


def _print_stats(diagnostics: list[Diagnostic], file_count: int) -> None:
    """
    Print a machine-readable JSON stats summary to stdout.

    Useful for dashboards, trend tracking, and CI metric collection::

        bsl-analyzer --check . --stats | jq .total
    """
    from collections import Counter

    by_code: dict[str, int] = Counter(d.code for d in diagnostics)  # type: ignore[assignment]
    by_severity: dict[str, int] = Counter(d.severity.name for d in diagnostics)  # type: ignore[assignment]

    summary: dict[str, Any] = {
        "total": len(diagnostics),
        "files_checked": file_count,
        "by_severity": dict(by_severity),
        "by_rule": dict(sorted(by_code.items())),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


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


def _collect_files(
    paths: list[str], config: BslConfig | None = None
) -> list[str]:
    """Recursively collect all .bsl/.os files from paths (files or dirs)."""
    cfg = config or _EMPTY
    result: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix.lower() in BSL_EXTENSIONS:
                resolved = str(p.resolve())
                if not cfg.is_excluded(resolved):
                    result.append(resolved)
        elif p.is_dir():
            for ext in BSL_EXTENSIONS:
                for f in p.rglob(f"*{ext}"):
                    resolved = str(f.resolve())
                    if not cfg.is_excluded(resolved):
                        result.append(resolved)
        else:
            console.print(f"[yellow]Path not found: {raw}[/yellow]")
    return result
