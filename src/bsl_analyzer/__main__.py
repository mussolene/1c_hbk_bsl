"""
Entry point for bsl-analyzer CLI.

Usage:
    bsl-analyzer --lsp                              Start LSP server on stdio
    bsl-analyzer --mcp [--port 8051]               Start MCP HTTP server
    bsl-analyzer --check [PATH ...]                 Run linter (ruff-style output)
    bsl-analyzer --check [PATH] --diff              Check only git-changed BSL files
    bsl-analyzer --index [PATH]                     Force full reindex of workspace
    bsl-analyzer --list-rules                       Show all available rules
    bsl-analyzer --watch [PATH ...]                 Watch for changes and re-lint
    bsl-analyzer --init                             Generate starter bsl-analyzer.toml

Check mode flags:
    --select BSL001,BSL002         Run only these rules
    --ignore BSL002                Skip these rules
    --format text|json|sonarqube|sarif  Output format (default: text)
    --jobs N                       Parallel workers (0 = auto, 1 = serial)
    --sonar-root PATH              Project root for SonarQube/SARIF relative paths
    --exit-zero                    Always exit 0 (don't fail CI on issues)
    --baseline FILE                Suppress issues listed in baseline
    --update-baseline FILE         Save current issues as new baseline, exit 0

Config file:
    bsl-analyzer.toml (or [tool.bsl-analyzer] in pyproject.toml) is
    automatically loaded from the checked directory (or cwd).
    CLI flags override config file values.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from rich.logging import RichHandler

from bsl_analyzer import __version__


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def _run_lsp() -> None:
    from bsl_analyzer.lsp.server import start_lsp_server
    logging.getLogger(__name__).info("Starting BSL LSP server on stdio")
    start_lsp_server()


def _run_mcp(port: int) -> None:
    from bsl_analyzer.mcp.server import create_mcp_app
    logging.getLogger(__name__).info("Starting BSL MCP server on port %d", port)
    app = create_mcp_app()
    app.run(transport="streamable-http", host="0.0.0.0", port=port)


def _run_check(
    paths: list[str],
    fmt: str,
    select: set[str] | None,
    ignore: set[str] | None,
    jobs: int,
    sonar_root: str | None,
    exit_zero: bool,
    baseline: str | None,
    update_baseline: str | None,
    stats: bool,
    show_fix: bool,
    diff: bool,
    since: str | None,
    fix: bool,
) -> int:
    from bsl_analyzer.cli.check import check
    from bsl_analyzer.cli.config import load_config

    # Load config from the first checked path (or cwd)
    search_from = paths[0] if paths else os.getcwd()
    cfg = load_config(search_from)

    # --diff: resolve paths to git-changed BSL files
    if diff:
        from bsl_analyzer.cli.git_utils import git_changed_files
        workspace = paths[0] if len(paths) == 1 and os.path.isdir(paths[0]) else search_from
        git_paths = git_changed_files(workspace, since=since)
        if not git_paths:
            import logging
            logging.getLogger(__name__).info("--diff: no changed BSL files found")
            return 0
        paths = git_paths

    return check(
        paths,
        format=fmt,
        select=select,
        ignore=ignore,
        jobs=jobs,
        sonar_root=sonar_root,
        exit_zero=exit_zero,
        baseline=baseline,
        update_baseline=update_baseline,
        config=cfg,
        stats=stats,
        show_fix=show_fix,
        fix=fix,
    )


def _run_watch(
    paths: list[str],
    fmt: str,
    select: set[str] | None,
    ignore: set[str] | None,
    jobs: int,
    sonar_root: str | None,
    exit_zero: bool,
) -> None:
    """Watch paths for BSL file changes and re-run checks on each save."""
    from rich.console import Console

    from bsl_analyzer.cli.check import (
        _print_json,
        _print_sarif,
        _print_sonarqube,
        _print_summary,
        _print_text,
        _run_checks,
    )
    from bsl_analyzer.cli.config import load_config
    from bsl_analyzer.indexer.watcher import FileWatcher

    _console = Console(stderr=True)
    search_from = paths[0] if paths else os.getcwd()
    cfg = load_config(search_from)
    workspace = paths[0] if len(paths) == 1 and os.path.isdir(paths[0]) else os.path.commonpath(paths) if paths else os.getcwd()

    _console.print(f"[bold green]Watching[/bold green] {workspace} for BSL changes (Ctrl+C to stop)")

    def _on_change(changed: list[str]) -> None:
        _console.print(f"\n[dim]Changed:[/dim] {', '.join(os.path.basename(f) for f in changed)}")
        diags, _ = _run_checks(sorted(changed), select=select, ignore=ignore, jobs=jobs, config=cfg)
        if fmt == "json":
            _print_json(diags)
        elif fmt == "sonarqube":
            _print_sonarqube(diags, sonar_root)
        elif fmt == "sarif":
            _print_sarif(diags, sonar_root)
        else:
            _print_text(diags)
            if diags:
                _print_summary(diags, len(changed))
            else:
                _console.print(f"[green]Clean.[/green] ({len(changed)} file(s))")

    watcher = FileWatcher()
    watcher.watch(workspace, _on_change)


def _run_init(target_dir: str) -> None:
    """Write a starter bsl-analyzer.toml to *target_dir*."""
    from rich.console import Console

    _console = Console(stderr=True)
    config_path = os.path.join(target_dir, "bsl-analyzer.toml")

    if os.path.exists(config_path):
        _console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
        return

    content = '''\
# bsl-analyzer.toml — configuration for bsl-analyzer
# See: https://github.com/your-org/bsl-analyzer

# Rules to run (empty = all rules)
# select = ["BSL001", "BSL002"]

# Rules to always skip
ignore = []

# Directories / file patterns to exclude
exclude = [
    "vendor",
    ".git",
    "build",
]

# Per-file rule overrides
# [per-file-ignores]
# "legacy_*.bsl" = ["BSL012", "BSL035"]

# Output format: text | json | sonarqube | sarif  (default: text)
# format = "text"

# Parallel workers (0 = auto, 1 = serial)
# jobs = 0

# Never fail CI exit code
# exit-zero = false

# Baseline file for gradual adoption
# baseline = "bsl-baseline.json"

# ---- Threshold overrides ----
# max-line-length = 120
# max-proc-lines  = 200
# max-cognitive-complexity = 15
# max-mccabe-complexity    = 10
# max-nesting-depth        = 4
# max-params               = 7
# max-returns              = 3
# max-bool-ops             = 3
# min-duplicate-uses       = 3
'''
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    _console.print(f"[green]Created:[/green] {config_path}")
    _console.print("Edit the file to customize rules and thresholds.")


def _run_index(workspace: str, force: bool) -> None:
    from bsl_analyzer.indexer.incremental import IncrementalIndexer
    db_path = os.environ.get("INDEX_DB_PATH", "bsl_index.sqlite")
    indexer = IncrementalIndexer(db_path=db_path)
    indexer.index_workspace(workspace, force=force)


def _parse_codes(raw: str | None) -> set[str] | None:
    """Parse a comma-separated list of rule codes, or return None."""
    if not raw:
        return None
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bsl-analyzer",
        description="BSL (1C Enterprise) analyzer — MCP server, LSP server, and CLI linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bsl-analyzer --check .                              Check current directory
  bsl-analyzer --check src/ --select BSL001,BSL002
  bsl-analyzer --check . --ignore BSL014 --format json > issues.json
  bsl-analyzer --check . --format sonarqube --sonar-root /project > sonar.json
  bsl-analyzer --check . --format sarif > results.sarif
  bsl-analyzer --check . --jobs 8                     Use 8 parallel workers
  bsl-analyzer --check . --exit-zero                  Never fail CI
  bsl-analyzer --check . --update-baseline baseline.json  Save known issues
  bsl-analyzer --check . --baseline baseline.json     Only report new issues
  bsl-analyzer --list-rules                           Show all available rules
  bsl-analyzer --mcp --port 8051                     Start MCP server for Claude
        """,
    )
    parser.add_argument("--version", action="version", version=f"bsl-analyzer {__version__}")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "warning"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: warning)",
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--lsp", action="store_true", help="Start LSP server on stdio")
    mode_group.add_argument("--mcp", action="store_true", help="Start MCP HTTP server")
    mode_group.add_argument(
        "--watch",
        metavar="PATH",
        nargs="*",
        help="Watch PATH(s) for BSL file changes and re-run linter on each save",
    )
    mode_group.add_argument(
        "--check",
        metavar="PATH",
        nargs="*",
        help="Run linter on PATH(s) (current dir if omitted)",
    )
    mode_group.add_argument(
        "--index",
        metavar="PATH",
        nargs="?",
        const=os.getcwd(),
        help="Index/reindex workspace (current dir if omitted)",
    )
    mode_group.add_argument(
        "--list-rules",
        action="store_true",
        help="Show all available diagnostic rules with descriptions",
    )
    mode_group.add_argument(
        "--init",
        action="store_true",
        help="Generate a starter bsl-analyzer.toml in the current directory",
    )

    # MCP options
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8051")),
        help="Port for MCP HTTP server (default: 8051)",
    )

    # Check options
    parser.add_argument(
        "--format",
        choices=["text", "compact", "json", "sonarqube", "sarif"],
        default="text",
        help="Output format for --check (default: text)",
    )
    parser.add_argument(
        "--select",
        metavar="CODES",
        default=None,
        help=(
            "Comma-separated rule codes to enable exclusively "
            "(e.g. BSL001,BSL002). When set, only listed rules run."
        ),
    )
    parser.add_argument(
        "--ignore",
        metavar="CODES",
        default=None,
        help=(
            "Comma-separated rule codes to skip (e.g. BSL002,BSL014). "
            "Inline suppression: add  // noqa: BSL002  or  // bsl-disable: BSL002  "
            "at the end of any source line."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help="Number of parallel worker threads (0 = auto, 1 = serial; default: 0)",
    )
    parser.add_argument(
        "--sonar-root",
        metavar="PATH",
        default=None,
        help="Project root directory for SonarQube/SARIF relative path calculation",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        default=False,
        help="Always exit 0 even if issues are found (useful for CI metric collection)",
    )
    parser.add_argument(
        "--baseline",
        metavar="FILE",
        default=None,
        help="Path to baseline JSON — issues present in baseline are suppressed",
    )
    parser.add_argument(
        "--update-baseline",
        metavar="FILE",
        default=None,
        help="Save all found issues as a new baseline, then exit 0",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        default=False,
        help="Print a machine-readable JSON stats summary to stdout after checking",
    )
    parser.add_argument(
        "--show-fix",
        action="store_true",
        default=False,
        help="Show actionable fix hints below each issue in text output",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help=(
            "Only check BSL files changed since HEAD (or --since REF). "
            "Requires git. Useful in pre-commit hooks and PR pipelines."
        ),
    )
    parser.add_argument(
        "--since",
        metavar="REF",
        default=None,
        help=(
            "Git ref to diff against when using --diff "
            "(e.g. HEAD~1, main, origin/main). Default: HEAD."
        ),
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help=(
            "Auto-fix supported issues in-place. "
            "Supported rules: BSL009, BSL010, BSL055, BSL060. "
            "Remaining unfixable issues are still reported."
        ),
    )

    # Index options
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full reindex even if incremental is possible (--index mode)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    if args.list_rules:
        from bsl_analyzer.cli.check import list_rules
        list_rules()
        return

    if args.init:
        _run_init(os.getcwd())
        return

    if args.lsp:
        _run_lsp()

    elif args.mcp:
        _run_mcp(args.port)

    elif args.check is not None:
        paths = args.check if args.check else [os.getcwd()]
        sys.exit(
            _run_check(
                paths,
                fmt=args.format,
                select=_parse_codes(args.select),
                ignore=_parse_codes(args.ignore),
                jobs=args.jobs,
                sonar_root=args.sonar_root,
                exit_zero=args.exit_zero,
                baseline=args.baseline,
                update_baseline=args.update_baseline,
                stats=args.stats,
                show_fix=args.show_fix,
                diff=args.diff,
                since=args.since,
                fix=args.fix,
            )
        )

    elif args.watch is not None:
        watch_paths = args.watch if args.watch else [os.getcwd()]
        _run_watch(
            watch_paths,
            fmt=args.format,
            select=_parse_codes(args.select),
            ignore=_parse_codes(args.ignore),
            jobs=args.jobs,
            sonar_root=args.sonar_root,
            exit_zero=args.exit_zero,
        )

    elif args.index is not None:
        _run_index(args.index, force=args.force)


if __name__ == "__main__":
    main()
