"""Dedicated formatter entrypoint."""

from __future__ import annotations

import argparse
import os
import sys

from onec_hbk_bsl.__main__ import _run_format, _setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="onec-hbk-bsl-format",
        description="Format BSL files using the BSLLS-aligned formatter",
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to format")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether files are already formatted",
    )
    parser.add_argument(
        "--indent-size",
        type=int,
        default=4,
        metavar="N",
        help="Indent width when spaces are requested (default: 4)",
    )
    parser.add_argument(
        "--insert-spaces",
        action="store_true",
        default=None,
        help="Indent with spaces instead of BSLLS-default tabs",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "warning"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: warning)",
    )
    args = parser.parse_args()
    _setup_logging(args.log_level, use_rich=True)
    sys.exit(
        _run_format(
            args.paths or [os.getcwd()],
            check=args.check,
            indent_size=args.indent_size,
            insert_spaces=args.insert_spaces,
        )
    )


if __name__ == "__main__":
    main()
