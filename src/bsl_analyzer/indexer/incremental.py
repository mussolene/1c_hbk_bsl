"""
Incremental BSL workspace indexer.

Uses ``git diff`` to detect changed files since the last indexed commit,
so only modified .bsl/.os files are re-parsed on each run.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable

from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from bsl_analyzer.analysis.symbols import extract_symbols
from bsl_analyzer.analysis.call_graph import extract_calls
from bsl_analyzer.indexer.symbol_index import SymbolIndex
from bsl_analyzer.parser.bsl_parser import BslParser

logger = logging.getLogger(__name__)

BSL_EXTENSIONS = {".bsl", ".os"}


class IncrementalIndexer:
    """
    Indexes a BSL workspace into a :class:`SymbolIndex`.

    Args:
        db_path:    Path to the SQLite index database.
        index:      Existing SymbolIndex instance (overrides db_path).
        on_progress: Optional callback ``fn(current, total, file_path)`` for progress.
    """

    def __init__(
        self,
        db_path: str = "bsl_index.sqlite",
        index: SymbolIndex | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self.index = index or SymbolIndex(db_path=db_path)
        self._parser = BslParser()
        self._on_progress = on_progress

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_workspace(self, workspace: str, force: bool = False) -> dict:
        """
        Index (or incrementally update) a BSL workspace.

        Args:
            workspace: Absolute path to the workspace root.
            force:     If True, always perform a full reindex.

        Returns:
            Dict with ``indexed``, ``skipped``, ``errors`` counts.
        """
        workspace = str(Path(workspace).resolve())
        last_commit = None if force else self.index.get_last_commit()
        current_commit = self._get_current_commit(workspace)

        if not force and last_commit and last_commit == current_commit:
            logger.info("Index is up-to-date at %s. Nothing to do.", current_commit[:8])
            return {"indexed": 0, "skipped": 0, "errors": 0}

        if not force and last_commit:
            files = self.get_changed_files(since_commit=last_commit, workspace=workspace)
            logger.info(
                "Incremental index: %d changed files since %s",
                len(files),
                last_commit[:8],
            )
        else:
            files = self._find_all_bsl_files(workspace)
            logger.info("Full index: %d BSL files in %s", len(files), workspace)

        result = self._index_files(files, workspace)

        if current_commit:
            self.index.save_commit(current_commit, workspace_root=workspace)

        return result

    def get_changed_files(self, since_commit: str, workspace: str) -> list[str]:
        """
        Return absolute paths of .bsl/.os files changed since *since_commit*.

        Uses ``git diff --name-only`` against the current HEAD.
        Falls back to full scan if git is unavailable.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_commit, "HEAD"],
                capture_output=True,
                text=True,
                cwd=workspace,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(
                    "git diff failed (rc=%d): %s. Falling back to full scan.",
                    result.returncode,
                    result.stderr.strip(),
                )
                return self._find_all_bsl_files(workspace)

            changed: list[str] = []
            for rel_path in result.stdout.splitlines():
                rel_path = rel_path.strip()
                if not rel_path:
                    continue
                if Path(rel_path).suffix.lower() in BSL_EXTENSIONS:
                    abs_path = str(Path(workspace) / rel_path)
                    changed.append(abs_path)
            return changed

        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("git not available (%s). Falling back to full scan.", exc)
            return self._find_all_bsl_files(workspace)

    def index_file(self, path: str) -> dict:
        """
        Parse a single BSL file and upsert it into the index.

        Returns:
            Dict with ``symbols`` and ``calls`` counts, plus ``error`` if failed.
        """
        try:
            tree = self._parser.parse_file(path)
            symbols = extract_symbols(tree, file_path=path)
            calls = extract_calls(tree, file_path=path)

            sym_dicts = [_symbol_to_dict(s) for s in symbols]
            call_dicts = [_call_to_dict(c) for c in calls]

            self.index.upsert_file(path, sym_dicts, call_dicts)
            return {"symbols": len(sym_dicts), "calls": len(call_dicts)}

        except Exception as exc:
            logger.error("Failed to index %s: %s", path, exc)
            return {"symbols": 0, "calls": 0, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _index_files(self, files: list[str], workspace: str) -> dict:
        indexed = 0
        skipped = 0
        errors = 0

        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Indexing BSL files", total=len(files))

            for path in files:
                progress.update(task, description=f"[bold blue]{Path(path).name}")

                if not Path(path).exists():
                    # File was deleted — remove from index
                    self.index.remove_file(path)
                    skipped += 1
                    progress.advance(task)
                    continue

                result = self.index_file(path)
                if "error" in result:
                    errors += 1
                else:
                    indexed += 1

                if self._on_progress:
                    self._on_progress(indexed + skipped + errors, len(files), path)

                progress.advance(task)

        logger.info(
            "Indexing complete: %d indexed, %d skipped, %d errors",
            indexed,
            skipped,
            errors,
        )
        return {"indexed": indexed, "skipped": skipped, "errors": errors}

    @staticmethod
    def _find_all_bsl_files(workspace: str) -> list[str]:
        """Walk the workspace and return all .bsl/.os files."""
        result: list[str] = []
        workspace_path = Path(workspace)
        for ext in BSL_EXTENSIONS:
            result.extend(str(p) for p in workspace_path.rglob(f"*{ext}"))
        return sorted(result)

    @staticmethod
    def _get_current_commit(workspace: str) -> str | None:
        """Return current HEAD commit hash, or None if not a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=workspace,
                timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None


# ---------------------------------------------------------------------------
# Helper converters
# ---------------------------------------------------------------------------

def _symbol_to_dict(symbol: Any) -> dict:  # noqa: ANN401
    """Convert a Symbol dataclass to a plain dict for the index."""
    return {
        "name": symbol.name,
        "line": symbol.line,
        "character": symbol.character,
        "end_line": symbol.end_line,
        "end_character": symbol.end_character,
        "kind": symbol.kind,
        "is_export": symbol.is_export,
        "container": symbol.container,
        "signature": symbol.signature,
        "doc_comment": symbol.doc_comment,
    }


def _call_to_dict(call: Any) -> dict:  # noqa: ANN401
    """Convert a Call dataclass to a plain dict for the index."""
    return {
        "caller_line": call.caller_line,
        "caller_name": call.caller_name,
        "callee_name": call.callee_name,
        "callee_args_count": call.callee_args_count,
    }


# Type hint only — avoid circular import
from typing import Any  # noqa: E402
