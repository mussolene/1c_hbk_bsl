"""
Entry point for onec-hbk-bsl CLI.

Usage:
    onec-hbk-bsl lsp                                Start LSP server on stdio
    onec-hbk-bsl mcp [--port 8051]                 Start MCP HTTP server
    onec-hbk-bsl mcp --stdio                       Start MCP server over stdio
    onec-hbk-bsl mcp --workspace /path/to/proj     Serve specific workspace
    onec-hbk-bsl check [PATH ...]                  Run linter
    onec-hbk-bsl format [PATH ...]                  Format BSL files in-place
    onec-hbk-bsl check [PATH] --diff               Check only git-changed BSL files
    onec-hbk-bsl index [PATH]                      Reindex workspace
    onec-hbk-bsl rules                              Show all available rules
    onec-hbk-bsl init                               Generate starter onec-hbk-bsl.toml

Check mode flags:
    --select BSL001,BSL002         Run only these rules
    --ignore BSL002                Skip these rules
    --format text|json|sarif       Output format (default: text)
    --jobs N                       Parallel workers (0 = auto, 1 = serial)
    --exit-zero                    Always exit 0 (don't fail CI on issues)
    --baseline FILE                Suppress issues listed in baseline
    --update-baseline FILE         Save current issues as new baseline, exit 0

Config file:
    onec-hbk-bsl.toml (or [tool."onec-hbk-bsl"] in pyproject.toml) is
    automatically loaded from the checked directory (or cwd).
    CLI flags override config file values.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
from pathlib import Path

from onec_hbk_bsl import __version__


def _setup_logging(level: str, use_rich: bool = True) -> None:
    if use_rich:
        from rich.console import Console
        from rich.logging import RichHandler

        logging.basicConfig(
            level=level.upper(),
            format="%(message)s",
            datefmt="[%X]",
            # Explicitly route to stderr — stdout is reserved for LSP JSON-RPC in stdio mode
            handlers=[RichHandler(console=Console(stderr=True), rich_tracebacks=True)],
            force=True,
        )
        return

    logging.basicConfig(
        level=level.upper(),
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def _run_lsp(log_level: str = "warning") -> None:
    # In LSP stdio mode stdout is the exclusive JSON-RPC pipe.
    # Reconfigure logging with force=True so that any previously installed
    # handlers (e.g. from _setup_logging) are replaced with a plain stderr
    # handler.  Rich colours are suppressed because stderr is not a TTY when
    # the process is spawned by VSCode.
    import sys

    # Signal all subsystems (especially IncrementalIndexer) that we are running
    # in LSP stdio mode.  Any Rich progress bars or other stdout output would
    # corrupt the JSON-RPC framing and crash the connection.
    os.environ["BSL_LSP_MODE"] = "1"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="[bsl-lsp] %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    # "Cancel notification for unknown message id" — normal race condition when
    # VSCode cancels a request that the server already answered.  These are not
    # errors; suppress them so the output channel stays clean.
    logging.getLogger("pygls.protocol.json_rpc").setLevel(logging.ERROR)
    logging.getLogger("pygls.protocol").setLevel(logging.ERROR)
    from onec_hbk_bsl.lsp.server import start_lsp_server

    start_lsp_server()


def _autoindex_if_empty(workspace: str, db_path: str) -> None:
    """Spawn background indexing if the index has no symbols yet."""
    import threading

    from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

    idx = SymbolIndex(db_path=db_path)
    stats = idx.get_stats()
    if stats["symbol_count"] > 0:
        logging.getLogger(__name__).info(
            "Index ready: %d symbols in %d files", stats["symbol_count"], stats["file_count"]
        )
        return

    logging.getLogger(__name__).info(
        "Index is empty — starting background indexing of %s", workspace
    )

    def _index() -> None:
        from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

        IncrementalIndexer(db_path=db_path).index_workspace(workspace)
        s = SymbolIndex(db_path=db_path).get_stats()
        logging.getLogger(__name__).info(
            "Background indexing complete: %d symbols in %d files",
            s["symbol_count"],
            s["file_count"],
        )

    threading.Thread(target=_index, daemon=True, name="bsl-autoindex").start()


def _run_mcp(port: int, stdio: bool, workspace: str) -> None:
    from onec_hbk_bsl.indexer.db_path import resolve_index_db_path

    db_path = resolve_index_db_path(workspace)
    # Set env vars BEFORE importing mcp_bridge/server so module-level globals pick them up
    os.environ.setdefault("INDEX_DB_PATH", db_path)
    os.environ.setdefault("WORKSPACE_ROOT", workspace)

    from onec_hbk_bsl.mcp_bridge.server import create_mcp_app

    _autoindex_if_empty(workspace, db_path)

    if stdio:
        app = create_mcp_app()
        logging.getLogger(__name__).info("Starting BSL MCP server on stdio")
        app.run(transport="stdio")
    else:
        app = create_mcp_app(host="0.0.0.0", port=port)
        logging.getLogger(__name__).info("Starting BSL MCP server on port %d", port)
        app.run(transport="streamable-http")


def _run_check(
    paths: list[str],
    fmt: str,
    select: set[str] | None,
    ignore: set[str] | None,
    jobs: int,
    exit_zero: bool,
    baseline: str | None,
    update_baseline: str | None,
    diff: bool,
    since: str | None,
    fix: bool,
    paths_from: str | None,
) -> int:
    from onec_hbk_bsl.cli.check import check, read_paths_from_file
    from onec_hbk_bsl.cli.config import load_config

    if paths_from:
        paths.extend(read_paths_from_file(paths_from))

    # Load config from the first checked path (or cwd)
    search_from = paths[0] if paths else os.getcwd()
    cfg = load_config(search_from)

    # --diff: resolve paths to git-changed BSL files
    if diff:
        from onec_hbk_bsl.cli.git_utils import git_changed_files

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
        exit_zero=exit_zero,
        baseline=baseline,
        update_baseline=update_baseline,
        config=cfg,
        fix=fix,
    )


def _iter_bsl_source_files(paths: list[str]) -> list[Path]:
    suffixes = {".bsl", ".os"}
    out: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() in suffixes or path.name == "Module.bsl":
                out.append(path)
            continue
        if path.is_dir():
            out.extend(
                p
                for p in path.rglob("*")
                if p.is_file() and (p.suffix.lower() in suffixes or p.name == "Module.bsl")
            )
    return sorted(set(out))


def _run_format(
    paths: list[str],
    *,
    check: bool,
    indent_size: int,
    insert_spaces: bool | None,
) -> int:
    """Format BSL files in-place, or only check whether formatting would change them."""
    from onec_hbk_bsl.analysis.formatter import default_formatter

    files = _iter_bsl_source_files(paths)
    changed: list[Path] = []
    failed: list[tuple[Path, str]] = []

    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
            formatted = default_formatter.format(
                original,
                indent_size=indent_size,
                insert_spaces=insert_spaces,
            )
        except Exception as exc:  # noqa: BLE001
            failed.append((path, str(exc)))
            continue
        if formatted == original:
            continue
        changed.append(path)
        if not check:
            path.write_text(formatted, encoding="utf-8")

    for path in changed:
        action = "would format" if check else "formatted"
        print(f"{action}: {path}")
    for path, reason in failed:
        print(f"format failed: {path}: {reason}", file=sys.stderr)

    if failed:
        return 2
    if check and changed:
        return 1
    return 0


def _run_init(target_dir: str) -> None:
    """Write a starter onec-hbk-bsl.toml to *target_dir*."""
    from rich.console import Console

    _console = Console(stderr=True)
    config_path = os.path.join(target_dir, "onec-hbk-bsl.toml")

    if os.path.exists(config_path):
        _console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
        return

    content = """\
# onec-hbk-bsl.toml — configuration for onec-hbk-bsl
# See: https://github.com/mussolene/1c_hbk_bsl

# Rules to add to the product default set
# select = ["BSL001", "BSL002"]

# Diagnostics use the product default rule set.

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

# Output format: text | json | sarif  (default: text)
# format = "text"

# Parallel workers (0 = auto, 1 = serial)
# jobs = 0

# Never fail CI exit code
# exit-zero = false

# Baseline file for gradual adoption
# baseline = "bsl-baseline.json"

# ---- Threshold overrides ----
# max-line-length          = 120    # BSL014
# max-proc-lines           = 200    # BSL002
# max-cognitive-complexity = 15     # BSL011
# max-mccabe-complexity    = 10     # BSL019
# max-nesting-depth        = 4      # BSL020
# max-params               = 7      # BSL031
# max-returns              = 3      # BSL008
# max-bool-ops             = 3      # BSL036
# min-duplicate-uses       = 3      # BSL035
"""
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    _console.print(f"[green]Created:[/green] {config_path}")
    _console.print("Edit the file to customize rules and thresholds.")


def _run_index(workspace: str, force: bool) -> None:
    from onec_hbk_bsl.indexer.db_path import resolve_index_db_path
    from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

    db_path = resolve_index_db_path(workspace)
    indexer = IncrementalIndexer(db_path=db_path)
    indexer.index_workspace(workspace, force=force)


def _parse_codes(raw: str | None) -> set[str] | None:
    """Parse comma-separated rule tokens (``BSL###`` or BSLLS names), or return None."""
    if not raw:
        return None
    from onec_hbk_bsl.analysis.diagnostics import normalize_rule_code_set_strict

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return normalize_rule_code_set_strict(parts, source="CLI rule filter")


_COMMAND_ALIASES = {
    "--check": "check",
    "--lsp": "lsp",
    "--mcp": "mcp",
    "--index": "index",
    "--list-rules": "rules",
    "--init": "init",
}
_COMMANDS = {"check", "format", "lsp", "mcp", "index", "rules", "init"}


def _normalize_argv(argv: list[str]) -> list[str]:
    """Accept legacy mode flags as aliases for the product subcommands."""
    if not argv:
        return argv
    leading_global_options: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--log-level" and index + 1 < len(argv):
            leading_global_options.extend(argv[index : index + 2])
            index += 2
            continue
        if arg.startswith("--log-level="):
            leading_global_options.append(arg)
            index += 1
            continue
        alias = _COMMAND_ALIASES.get(arg)
        if alias is not None:
            return [alias, *leading_global_options, *argv[index + 1 :]]
        if arg in _COMMANDS and leading_global_options:
            return [arg, *leading_global_options, *argv[index + 1 :]]
        return argv
    return argv


def main() -> None:
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(
        prog="onec-hbk-bsl",
        description="BSL (1C Enterprise) analyzer, formatter, LSP server, and MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  onec-hbk-bsl check .                                Check current directory
  onec-hbk-bsl check . --format sarif > results.sarif
  onec-hbk-bsl format .                               Format BSL files in-place
  onec-hbk-bsl format . --check                       Check formatting without writing
  onec-hbk-bsl rules                                  Show all available rules
  onec-hbk-bsl mcp --stdio --workspace /project       Start MCP server for agents
        """,
    )
    parser.add_argument("--version", action="version", version=f"onec-hbk-bsl {__version__}")

    log_parent = argparse.ArgumentParser(add_help=False)
    log_parent.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "warning"),
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity (default: warning)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    check_parser = subparsers.add_parser(
        "check",
        parents=[log_parent],
        help="Run diagnostics",
        description="Run diagnostics on BSL files",
    )
    check_parser.add_argument("paths", metavar="PATH", nargs="*", help="Files or directories to check")
    check_parser.add_argument(
        "--format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format (default: text)",
    )
    check_parser.add_argument(
        "--select",
        metavar="CODES",
        default=None,
        help="Comma-separated rule codes to enable exclusively",
    )
    check_parser.add_argument(
        "--ignore",
        metavar="CODES",
        default=None,
        help="Comma-separated rule codes to skip",
    )
    check_parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help="Number of parallel worker threads (0 = auto, 1 = serial; default: 0)",
    )
    check_parser.add_argument(
        "--exit-zero",
        action="store_true",
        default=False,
        help="Always exit 0 even if issues are found",
    )
    check_parser.add_argument(
        "--baseline",
        metavar="FILE",
        default=None,
        help="Suppress issues listed in baseline",
    )
    check_parser.add_argument(
        "--update-baseline",
        metavar="FILE",
        default=None,
        help="Save all found issues as a new baseline, then exit 0",
    )
    check_parser.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Only check BSL files changed since HEAD or --since REF",
    )
    check_parser.add_argument(
        "--since",
        metavar="REF",
        default=None,
        help="Git ref to diff against when using --diff (default: HEAD)",
    )
    check_parser.add_argument(
        "--paths-from",
        metavar="FILE",
        default=None,
        help="Read additional newline-delimited paths from FILE ('-' reads stdin)",
    )
    check_parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Auto-fix supported issues in-place",
    )

    format_parser = subparsers.add_parser(
        "format",
        parents=[log_parent],
        help="Format BSL files",
        description="Format BSL files using the built-in formatter",
    )
    format_parser.add_argument("paths", metavar="PATH", nargs="*", help="Files or directories to format")
    format_parser.add_argument(
        "--check",
        action="store_true",
        help="Only check whether files are already formatted",
    )
    format_parser.add_argument(
        "--indent-size",
        type=int,
        default=4,
        metavar="N",
        help="Indent width when spaces are requested (default: 4)",
    )
    format_parser.add_argument(
        "--insert-spaces",
        action="store_true",
        default=None,
        help="Indent with spaces instead of tabs",
    )

    subparsers.add_parser(
        "lsp",
        parents=[log_parent],
        help="Start LSP server on stdio",
    )

    mcp_parser = subparsers.add_parser(
        "mcp",
        parents=[log_parent],
        help="Start MCP server",
    )
    mcp_parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8051")),
        help="Port for MCP HTTP server (default: 8051)",
    )
    mcp_parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run MCP server over stdio instead of HTTP",
    )
    mcp_parser.add_argument(
        "--workspace",
        metavar="PATH",
        default=os.environ.get("WORKSPACE_ROOT", os.getcwd()),
        help="Workspace root to index and serve (default: $WORKSPACE_ROOT or cwd)",
    )

    index_parser = subparsers.add_parser(
        "index",
        parents=[log_parent],
        help="Index or reindex workspace",
    )
    index_parser.add_argument(
        "path",
        metavar="PATH",
        nargs="?",
        default=os.getcwd(),
        help="Workspace to index (default: current directory)",
    )
    index_parser.add_argument(
        "--force",
        action="store_true",
        help="Force full reindex even if incremental is possible",
    )

    rules_parser = subparsers.add_parser(
        "rules",
        parents=[log_parent],
        help="Show available diagnostic rules",
    )
    rules_parser.add_argument(
        "--tag",
        metavar="TAG",
        default=None,
        help="Filter output to rules with this tag (e.g. security, performance)",
    )

    subparsers.add_parser("init", parents=[log_parent], help="Generate a starter onec-hbk-bsl.toml")

    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    if args.command == "rules":
        _setup_logging(args.log_level, use_rich=True)
        from onec_hbk_bsl.cli.check import list_rules

        list_rules(tag=args.tag)
        return

    if args.command == "init":
        _setup_logging(args.log_level, use_rich=True)
        _run_init(os.getcwd())
        return

    if args.command == "lsp":
        _run_lsp(args.log_level)
        return

    if args.command == "mcp":
        _setup_logging(args.log_level, use_rich=False)
        _run_mcp(args.port, stdio=args.stdio, workspace=os.path.abspath(args.workspace))
        return

    if args.command == "check":
        _setup_logging(args.log_level, use_rich=True)
        paths = args.paths if args.paths or args.paths_from else [os.getcwd()]
        try:
            select = _parse_codes(args.select)
            ignore = _parse_codes(args.ignore)
            code = _run_check(
                paths,
                fmt=args.format,
                select=select,
                ignore=ignore,
                jobs=args.jobs,
                exit_zero=args.exit_zero,
                baseline=args.baseline,
                update_baseline=args.update_baseline,
                diff=args.diff,
                since=args.since,
                fix=args.fix,
                paths_from=args.paths_from,
            )
        except ValueError as exc:
            parser.error(str(exc))
        sys.exit(code)

    if args.command == "format":
        _setup_logging(args.log_level, use_rich=True)
        sys.exit(
            _run_format(
                args.paths or [os.getcwd()],
                check=args.check,
                indent_size=args.indent_size,
                insert_spaces=args.insert_spaces,
            )
        )

    if args.command == "index":
        _setup_logging(args.log_level, use_rich=True)
        _run_index(args.path, force=args.force)


if __name__ == "__main__":
    main()
