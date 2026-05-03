"""Thin LSP entrypoint: avoid pulling CLI/MCP runtime at startup."""

from __future__ import annotations

import argparse
import os

from onec_hbk_bsl.__main__ import _run_lsp


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="onec-hbk-bsl-lsp",
        description="Start onec-hbk-bsl LSP server on stdio",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "warning"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: warning)",
    )
    args = parser.parse_args()
    _run_lsp(args.log_level)


if __name__ == "__main__":
    main()
