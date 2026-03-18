"""
Entry point for bsl-analyzer CLI.

Usage:
    bsl-analyzer --lsp                              Start LSP server on stdio
    bsl-analyzer --mcp [--port 8051]               Start MCP HTTP server
    bsl-analyzer --check [PATH ...]                 Run linter (ruff-style output)
    bsl-analyzer --index [PATH]                     Force full reindex of workspace
    bsl-analyzer --list-rules                       Show all available rules

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
) -> int:
    from bsl_analyzer.cli.check import check
    from bsl_analyzer.cli.config import load_config

    # Load config from the first checked path (or cwd)
    search_from = paths[0] if paths else os.getcwd()
    cfg = load_config(search_from)

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
    )


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
        choices=["text", "json", "sonarqube", "sarif"],
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
            )
        )

    elif args.index is not None:
        _run_index(args.index, force=args.force)


if __name__ == "__main__":
    main()
