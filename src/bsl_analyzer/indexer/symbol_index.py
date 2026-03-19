"""
SQLite-backed symbol index for BSL workspaces.

Schema
------
symbols     — procedures, functions, variables with location and metadata
calls       — call-graph edges (caller → callee)
git_state   — last indexed commit hash per workspace root

Full-text search is provided by FTS5 on the symbol name.
Thread-safety is achieved via threading.local() connection pool.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

# Each thread gets its own connection to avoid SQLite thread-safety issues.
_local = threading.local()

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    line        INTEGER NOT NULL,
    character   INTEGER NOT NULL DEFAULT 0,
    end_line    INTEGER NOT NULL DEFAULT 0,
    end_character INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL,          -- 'procedure' | 'function' | 'variable'
    is_export   INTEGER NOT NULL DEFAULT 0,
    container   TEXT,                  -- parent procedure name for nested symbols
    signature   TEXT,                  -- full signature string  e.g. Func(A, B)
    doc_comment TEXT,                  -- leading comment block
    indexed_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_name      ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file      ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name_file ON symbols(name, file_path);

-- FTS5 virtual table for fast substring/prefix search
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    file_path UNINDEXED,
    signature UNINDEXED,
    content='symbols',
    content_rowid='id'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, file_path, signature)
    VALUES (new.id, new.name, new.file_path, new.signature);
END;
CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, file_path, signature)
    VALUES ('delete', old.id, old.name, old.file_path, old.signature);
END;
CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, file_path, signature)
    VALUES ('delete', old.id, old.name, old.file_path, old.signature);
    INSERT INTO symbols_fts(rowid, name, file_path, signature)
    VALUES (new.id, new.name, new.file_path, new.signature);
END;

CREATE TABLE IF NOT EXISTS calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_file  TEXT NOT NULL,
    caller_line  INTEGER NOT NULL,
    caller_name  TEXT,               -- name of the containing procedure/function
    callee_name  TEXT NOT NULL,
    callee_args_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee_name);
CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller_file, caller_line);
CREATE INDEX IF NOT EXISTS idx_calls_caller_name ON calls(caller_name);

CREATE TABLE IF NOT EXISTS git_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    commit_hash    TEXT,
    indexed_at     REAL,
    workspace_root TEXT
);
"""


class SymbolIndex:
    """
    Persistent SQLite-backed index of BSL symbols and call-graph edges.

    Args:
        db_path: Path to the SQLite database file.
                 Use ``":memory:"`` for in-memory (tests).
    """

    def __init__(self, db_path: str = "bsl_index.sqlite") -> None:
        self.db_path = db_path
        # In-memory DBs are connection-scoped; keep per-instance connection to
        # avoid test isolation issues with the thread-local pool.
        self._mem_conn: sqlite3.Connection | None = None
        conn = self._conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _make_conn(self) -> sqlite3.Connection:
        """Create a new SQLite connection with all required settings."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions manually
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # Override SQLite LOWER with Python's Unicode-aware casefold so that
        # Cyrillic (and other non-ASCII) characters are handled correctly.
        conn.create_function("LOWER", 1, lambda x: x.casefold() if isinstance(x, str) else x)
        return conn

    def _conn(self) -> sqlite3.Connection:
        """Return an SQLite connection, creating it if needed."""
        if self.db_path == ":memory:":
            # Each SymbolIndex instance gets its own in-memory DB.
            if self._mem_conn is None or self._is_closed(self._mem_conn):
                self._mem_conn = self._make_conn()
            return self._mem_conn

        conn: sqlite3.Connection | None = getattr(_local, "conn", None)
        if conn is None or self._is_closed(conn):
            conn = self._make_conn()
            _local.conn = conn
        return conn

    @staticmethod
    def _is_closed(conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT 1")
            return False
        except sqlite3.ProgrammingError:
            return True

    def close(self) -> None:
        """Close the connection for the current thread (or instance for :memory:)."""
        if self.db_path == ":memory:":
            if self._mem_conn and not self._is_closed(self._mem_conn):
                self._mem_conn.close()
            self._mem_conn = None
        else:
            conn: sqlite3.Connection | None = getattr(_local, "conn", None)
            if conn and not self._is_closed(conn):
                conn.close()
                _local.conn = None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_file(
        self,
        file_path: str,
        symbols: list[dict],
        calls: list[dict],
    ) -> None:
        """
        Replace all index data for *file_path* with the provided symbols and calls.

        Args:
            file_path: Absolute path of the indexed file.
            symbols: List of symbol dicts (see ``symbols`` table columns).
            calls:   List of call dicts (see ``calls`` table columns).
        """
        conn = self._conn()
        now = time.time()

        with conn:
            # Delete old data for this file
            conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
            conn.execute("DELETE FROM calls WHERE caller_file = ?", (file_path,))

            # Insert new symbols
            conn.executemany(
                """
                INSERT INTO symbols
                    (name, file_path, line, character, end_line, end_character,
                     kind, is_export, container, signature, doc_comment, indexed_at)
                VALUES
                    (:name, :file_path, :line, :character, :end_line, :end_character,
                     :kind, :is_export, :container, :signature, :doc_comment, :indexed_at)
                """,
                [
                    {
                        "name": s.get("name", ""),
                        "file_path": file_path,
                        "line": s.get("line", 0),
                        "character": s.get("character", 0),
                        "end_line": s.get("end_line", 0),
                        "end_character": s.get("end_character", 0),
                        "kind": s.get("kind", "unknown"),
                        "is_export": int(bool(s.get("is_export", False))),
                        "container": s.get("container"),
                        "signature": s.get("signature"),
                        "doc_comment": s.get("doc_comment"),
                        "indexed_at": now,
                    }
                    for s in symbols
                ],
            )

            # Insert new calls
            conn.executemany(
                """
                INSERT INTO calls (caller_file, caller_line, caller_name, callee_name, callee_args_count)
                VALUES (:caller_file, :caller_line, :caller_name, :callee_name, :callee_args_count)
                """,
                [
                    {
                        "caller_file": file_path,
                        "caller_line": c.get("caller_line", 0),
                        "caller_name": c.get("caller_name"),
                        "callee_name": c.get("callee_name", ""),
                        "callee_args_count": c.get("callee_args_count", 0),
                    }
                    for c in calls
                ],
            )

    def remove_file(self, file_path: str) -> None:
        """Remove all index data for a file (called when file is deleted)."""
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
            conn.execute("DELETE FROM calls WHERE caller_file = ?", (file_path,))

    def save_commit(self, commit_hash: str, workspace_root: str = "") -> None:
        """Persist the last successfully indexed commit hash."""
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO git_state (id, commit_hash, indexed_at, workspace_root)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    commit_hash = excluded.commit_hash,
                    indexed_at = excluded.indexed_at,
                    workspace_root = excluded.workspace_root
                """,
                (commit_hash, time.time(), workspace_root),
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def find_symbol(
        self,
        name: str,
        file_filter: str | None = None,
        limit: int = 20,
        fuzzy: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Find symbols by name.

        Args:
            name:        Exact name (case-insensitive) or FTS prefix when fuzzy=True.
            file_filter: If provided, restrict results to files matching this substring.
            limit:       Maximum number of results.
            fuzzy:       Use FTS5 prefix search instead of exact match.

        Returns:
            List of symbol dicts with all columns from the ``symbols`` table.
        """
        conn = self._conn()

        if fuzzy:
            fts_query = name.strip() + "*"
            sql = """
                SELECT s.*
                FROM symbols s
                JOIN symbols_fts f ON s.id = f.rowid
                WHERE symbols_fts MATCH :fts_query
                  AND (:file_filter IS NULL OR s.file_path LIKE :file_like)
                ORDER BY rank
                LIMIT :limit
            """
            params: dict = {
                "fts_query": fts_query,
                "file_filter": file_filter,
                "file_like": f"%{file_filter}%" if file_filter else None,
                "limit": limit,
            }
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = """
                SELECT * FROM symbols
                WHERE LOWER(name) = LOWER(:name)
                  AND (:file_filter IS NULL OR file_path LIKE :file_like)
                ORDER BY file_path, line
                LIMIT :limit
            """
            rows = conn.execute(
                sql,
                {
                    "name": name,
                    "file_filter": file_filter,
                    "file_like": f"%{file_filter}%" if file_filter else None,
                    "limit": limit,
                },
            ).fetchall()

        return [dict(row) for row in rows]

    def find_callers(self, callee_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Find all call sites that call *callee_name*.

        Returns dicts with: caller_file, caller_line, caller_name, callee_name.
        """
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT c.caller_file, c.caller_line, c.caller_name, c.callee_name,
                   s.signature as caller_signature
            FROM calls c
            LEFT JOIN symbols s ON s.name = c.caller_name AND s.file_path = c.caller_file
            WHERE LOWER(c.callee_name) = LOWER(?)
            ORDER BY c.caller_file, c.caller_line
            LIMIT ?
            """,
            (callee_name, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def find_callees(
        self,
        caller_file: str,
        caller_name: str | None = None,
        caller_line: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find all symbols called from *caller_file*.

        When *caller_name* is given, filters to calls made by that function
        (by matching the ``caller_name`` column in the calls table).
        When *caller_line* is given instead, uses a ±15-line window.

        Returns dicts with: caller_file, caller_line, callee_name + resolved definition.
        """
        conn = self._conn()
        if caller_name is not None:
            rows = conn.execute(
                """
                SELECT c.callee_name, c.caller_line, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON LOWER(s.name) = LOWER(c.callee_name)
                WHERE c.caller_file = ?
                  AND LOWER(c.caller_name) = LOWER(?)
                ORDER BY c.caller_line
                """,
                (caller_file, caller_name),
            ).fetchall()
        elif caller_line is not None:
            rows = conn.execute(
                """
                SELECT c.callee_name, c.caller_line, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON LOWER(s.name) = LOWER(c.callee_name)
                WHERE c.caller_file = ?
                  AND c.caller_line BETWEEN ? AND ?
                ORDER BY c.caller_line
                """,
                (caller_file, caller_line - 15, caller_line + 15),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT c.callee_name, c.caller_line, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON LOWER(s.name) = LOWER(c.callee_name)
                WHERE c.caller_file = ?
                ORDER BY c.caller_line
                """,
                (caller_file,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_file_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """Return all symbols defined in a file, ordered by line."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY line",
            (file_path,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_last_commit(self) -> str | None:
        """Return the last indexed commit hash, or None if not yet indexed."""
        conn = self._conn()
        row = conn.execute("SELECT commit_hash FROM git_state WHERE id = 1").fetchone()
        return row["commit_hash"] if row else None

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""
        conn = self._conn()
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(DISTINCT file_path) FROM symbols").fetchone()[0]
        call_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        last_commit = self.get_last_commit()
        row = conn.execute("SELECT indexed_at, workspace_root FROM git_state WHERE id = 1").fetchone()
        return {
            "symbol_count": symbol_count,
            "file_count": file_count,
            "call_count": call_count,
            "last_commit": last_commit,
            "indexed_at": row["indexed_at"] if row else None,
            "workspace_root": row["workspace_root"] if row else None,
        }
