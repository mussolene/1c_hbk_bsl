"""
Entry point for onec-hbk-bsl CLI.

Usage:
    onec-hbk-bsl --lsp                              Start LSP server on stdio
    onec-hbk-bsl --mcp [--port 8051]               Start MCP HTTP server
    onec-hbk-bsl --mcp --stdio                     Start MCP server over stdio (Claude Desktop)
    onec-hbk-bsl --mcp --workspace /path/to/proj   Serve specific workspace (auto-indexes if empty)
    onec-hbk-bsl --check [PATH ...]                 Run linter (ruff-style output)
    onec-hbk-bsl --check [PATH] --diff              Check only git-changed BSL files
    onec-hbk-bsl --index [PATH]                     Force full reindex of workspace
    onec-hbk-bsl --list-rules                       Show all available rules
    onec-hbk-bsl --watch [PATH ...]                 Watch for changes and re-lint
    onec-hbk-bsl --init                             Generate starter onec-hbk-bsl.toml

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
    onec-hbk-bsl.toml (or [tool."onec-hbk-bsl"] in pyproject.toml) is
    automatically loaded from the checked directory (or cwd).
    CLI flags override config file values.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from rich.logging import RichHandler

from onec_hbk_bsl import __version__


def _setup_logging(level: str) -> None:
    from rich.console import Console
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        # Explicitly route to stderr — stdout is reserved for LSP JSON-RPC in stdio mode
        handlers=[RichHandler(console=Console(stderr=True), rich_tracebacks=True)],
    )


def _run_lsp() -> None:
    # In LSP stdio mode stdout is the exclusive JSON-RPC pipe.
    # Reconfigure logging with force=True so that any previously installed
    # handlers (e.g. from _setup_logging) are replaced with a plain stderr
    # handler.  Rich colours are suppressed because stderr is not a TTY when
    # the process is spawned by VSCode.
    import sys
    logging.basicConfig(
        level=logging.WARNING,   # silence noisy pygls INFO startup messages
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
            s["symbol_count"], s["file_count"],
        )

    threading.Thread(target=_index, daemon=True, name="bsl-autoindex").start()


def _run_mcp(port: int, stdio: bool, workspace: str) -> None:
    from onec_hbk_bsl.indexer.db_path import resolve_index_db_path

    db_path = resolve_index_db_path(workspace)
    # Set env vars BEFORE importing mcp/server so module-level globals pick them up
    os.environ.setdefault("INDEX_DB_PATH", db_path)
    os.environ.setdefault("WORKSPACE_ROOT", workspace)

    from onec_hbk_bsl.mcp.server import create_mcp_app

    _autoindex_if_empty(workspace, db_path)

    app = create_mcp_app()
    if stdio:
        logging.getLogger(__name__).info("Starting BSL MCP server on stdio")
        app.run(transport="stdio")
    else:
        logging.getLogger(__name__).info("Starting BSL MCP server on port %d", port)
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
    from onec_hbk_bsl.cli.check import check
    from onec_hbk_bsl.cli.config import load_config

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

    from onec_hbk_bsl.cli.check import (
        _print_json,
        _print_sarif,
        _print_sonarqube,
        _print_summary,
        _print_text,
        _run_checks,
    )
    from onec_hbk_bsl.cli.config import load_config
    from onec_hbk_bsl.indexer.watcher import FileWatcher

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
    """Write a starter onec-hbk-bsl.toml to *target_dir*."""
    from rich.console import Console

    _console = Console(stderr=True)
    config_path = os.path.join(target_dir, "onec-hbk-bsl.toml")

    if os.path.exists(config_path):
        _console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
        return

    content = '''\
# onec-hbk-bsl.toml — configuration for onec-hbk-bsl
# See: https://github.com/mussolene/1c_hbk_bsl

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
# max-line-length          = 120    # BSL014
# max-proc-lines           = 200    # BSL002
# max-cognitive-complexity = 15     # BSL011
# max-mccabe-complexity    = 10     # BSL019
# max-nesting-depth        = 4      # BSL020
# max-params               = 7      # BSL031
# max-returns              = 3      # BSL008
# max-bool-ops             = 3      # BSL036
# min-duplicate-uses       = 3      # BSL035
# max-module-lines         = 1000   # BSL063
'''
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


def _run_bench(workspace: str) -> int:
    """
    Run lightweight cold/warm indexing + diagnostics benchmark.

    Output is JSON to stdout so it can be captured in CI and compared across commits.
    """
    import json
    import time

    from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
    from onec_hbk_bsl.indexer.db_path import resolve_index_db_path
    from onec_hbk_bsl.indexer.incremental import IncrementalIndexer

    workspace = os.path.abspath(workspace)
    db_path = resolve_index_db_path(workspace)

    # Pick a representative file for diagnostics timing.
    files = IncrementalIndexer._find_all_bsl_files(workspace)
    sample_file = files[0] if files else None

    # Cold index (force full reindex).
    if db_path != ":memory:":
        try:
            if os.path.exists(db_path) and os.path.isfile(db_path):
                os.remove(db_path)
        except OSError:
            # Non-fatal: benchmark still continues with existing db state.
            pass

    indexer = IncrementalIndexer(db_path=db_path)
    t0 = time.perf_counter()
    cold_result = indexer.index_workspace(workspace, force=True)
    cold_wall_s = time.perf_counter() - t0

    # Warm index (incremental check; should be near-instant if HEAD unchanged).
    t1 = time.perf_counter()
    warm_result = indexer.index_workspace(workspace, force=False)
    warm_wall_s = time.perf_counter() - t1

    # Diagnostics on sample file.
    diag_payload: dict[str, object] = {"sample_file": sample_file}
    if sample_file:
        engine = DiagnosticEngine()
        t2 = time.perf_counter()
        _ = engine.check_file(sample_file)
        diag_wall_s = time.perf_counter() - t2
        diag_payload.update(
            {
                "diag_wall_s": diag_wall_s,
                "diagnostics_metrics": engine.last_metrics,
            }
        )

    payload = {
        "workspace": workspace,
        "db_path": db_path,
        "cold_index": {"wall_s": cold_wall_s, **cold_result},
        "warm_index": {"wall_s": warm_wall_s, **warm_result},
        "diagnostics_bench": diag_payload,
        "timestamp": time.time(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _parse_codes(raw: str | None) -> set[str] | None:
    """Parse a comma-separated list of rule codes, or return None."""
    if not raw:
        return None
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="onec-hbk-bsl",
        description="BSL (1C Enterprise) analyzer — MCP server, LSP server, and CLI linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  onec-hbk-bsl --check .                              Check current directory
  onec-hbk-bsl --check src/ --select BSL001,BSL002
  onec-hbk-bsl --check . --ignore BSL014 --format json > issues.json
  onec-hbk-bsl --check . --format sonarqube --sonar-root /project > sonar.json
  onec-hbk-bsl --check . --format sarif > results.sarif
  onec-hbk-bsl --check . --jobs 8                     Use 8 parallel workers
  onec-hbk-bsl --check . --exit-zero                  Never fail CI
  onec-hbk-bsl --check . --update-baseline baseline.json  Save known issues
  onec-hbk-bsl --check . --baseline baseline.json     Only report new issues
  onec-hbk-bsl --list-rules                           Show all available rules
  onec-hbk-bsl --mcp --port 8051                     Start MCP server for Claude
        """,
    )
    parser.add_argument("--version", action="version", version=f"onec-hbk-bsl {__version__}")
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
        "--bench",
        metavar="PATH",
        nargs="?",
        const=os.getcwd(),
        help="Run indexing+diagnostics benchmarks and print JSON",
    )
    mode_group.add_argument(
        "--list-rules",
        action="store_true",
        help="Show all available diagnostic rules with descriptions",
    )
    mode_group.add_argument(
        "--init",
        action="store_true",
        help="Generate a starter onec-hbk-bsl.toml in the current directory",
    )

    # MCP options
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8051")),
        help="Port for MCP HTTP server (default: 8051)",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Run MCP server over stdio instead of HTTP (for Claude Desktop / local agents)",
    )
    parser.add_argument(
        "--workspace",
        metavar="PATH",
        default=os.environ.get("WORKSPACE_ROOT", os.getcwd()),
        help="Workspace root to index and serve (default: $WORKSPACE_ROOT or cwd)",
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

    # List-rules filter
    parser.add_argument(
        "--tag",
        metavar="TAG",
        default=None,
        help="Filter --list-rules output to rules with this tag (e.g. security, performance)",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    if args.list_rules:
        from onec_hbk_bsl.cli.check import list_rules
        list_rules(tag=args.tag)
        return

    if args.init:
        _run_init(os.getcwd())
        return

    if args.lsp:
        _run_lsp()

    elif args.mcp:
        _run_mcp(args.port, stdio=args.stdio, workspace=os.path.abspath(args.workspace))

    elif getattr(args, "bench", None) is not None:
        sys.exit(_run_bench(args.bench))

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
