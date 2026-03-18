"""
Entry point for bsl-analyzer CLI.

Usage:
    bsl-analyzer --lsp                    Start LSP server on stdio (for VSCode/Cursor)
    bsl-analyzer --mcp [--port 8051]      Start MCP HTTP server
    bsl-analyzer --check [path]           Run linter (ruff-style output)
    bsl-analyzer --index [path]           Force full reindex of workspace
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
    """Start LSP server on stdio."""
    from bsl_analyzer.lsp.server import start_lsp_server

    logging.getLogger(__name__).info("Starting BSL LSP server on stdio")
    start_lsp_server()


def _run_mcp(port: int) -> None:
    """Start MCP HTTP server."""
    from bsl_analyzer.mcp.server import create_mcp_app

    logging.getLogger(__name__).info("Starting BSL MCP server on port %d", port)
    app = create_mcp_app()
    app.run(transport="streamable-http", host="0.0.0.0", port=port)


def _run_check(paths: list[str], fmt: str) -> int:
    """Run CLI linter. Returns exit code (0 = clean, 1 = issues)."""
    from bsl_analyzer.cli.check import check

    return check(paths, format=fmt)


def _run_index(workspace: str, force: bool) -> None:
    """Index (or reindex) BSL workspace."""
    from bsl_analyzer.indexer.incremental import IncrementalIndexer

    db_path = os.environ.get("INDEX_DB_PATH", "bsl_index.sqlite")
    indexer = IncrementalIndexer(db_path=db_path)
    indexer.index_workspace(workspace, force=force)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bsl-analyzer",
        description="BSL (1C Enterprise) analyzer — MCP server, LSP server, and CLI linter",
    )
    parser.add_argument("--version", action="version", version=f"bsl-analyzer {__version__}")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "info"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: info)",
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

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8051")),
        help="Port for MCP HTTP server (default: 8051)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format for --check (default: text)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full reindex even if incremental is possible (--index mode)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    if args.lsp:
        _run_lsp()

    elif args.mcp:
        _run_mcp(args.port)

    elif args.check is not None:
        paths = args.check if args.check else [os.getcwd()]
        sys.exit(_run_check(paths, args.format))

    elif args.index is not None:
        workspace = args.index
        _run_index(workspace, force=args.force)


if __name__ == "__main__":
    main()
