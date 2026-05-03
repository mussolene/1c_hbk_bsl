"""Thin MCP entrypoint: avoid pulling CLI-specific runtime at startup."""

from __future__ import annotations

import argparse
import os

from onec_hbk_bsl.__main__ import _run_mcp, _setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="onec-hbk-bsl-mcp",
        description="Start onec-hbk-bsl MCP server",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "warning"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: warning)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8051")),
        help="Port for MCP HTTP server (default: 8051)",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run MCP server over stdio instead of HTTP",
    )
    parser.add_argument(
        "--workspace",
        metavar="PATH",
        default=os.environ.get("WORKSPACE_ROOT", os.getcwd()),
        help="Workspace root to index and serve (default: $WORKSPACE_ROOT or cwd)",
    )
    args = parser.parse_args()
    _setup_logging(args.log_level, use_rich=False)
    _run_mcp(args.port, stdio=args.stdio, workspace=os.path.abspath(args.workspace))


if __name__ == "__main__":
    main()
