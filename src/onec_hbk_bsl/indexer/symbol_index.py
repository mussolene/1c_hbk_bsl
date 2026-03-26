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

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from onec_hbk_bsl.indexer.db_path import resolve_index_db_path

# Each thread gets its own connection to avoid SQLite thread-safety issues.
_local = threading.local()

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS symbols (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    name_lower  TEXT NOT NULL DEFAULT '',  -- casefold(name) for fast case-insensitive lookup
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

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);

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
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_file       TEXT NOT NULL,
    caller_line       INTEGER NOT NULL,
    caller_character  INTEGER NOT NULL DEFAULT 0,
    caller_name       TEXT,               -- name of the containing procedure/function
    callee_name       TEXT NOT NULL,
    callee_name_lower TEXT NOT NULL DEFAULT '',  -- casefold(callee_name)
    callee_args_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_calls_caller      ON calls(caller_file, caller_line);
CREATE INDEX IF NOT EXISTS idx_calls_caller_name ON calls(caller_name);

CREATE TABLE IF NOT EXISTS git_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    commit_hash    TEXT,
    indexed_at     REAL,
    workspace_root TEXT
);

-- 1C Configuration metadata tables
CREATE TABLE IF NOT EXISTS meta_objects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    name_lower  TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- 'Catalog' | 'Document' | 'DataProcessor' | ...
    synonym_ru  TEXT NOT NULL DEFAULT '',
    file_path   TEXT NOT NULL DEFAULT '',
    collection  TEXT NOT NULL DEFAULT '',  -- e.g. 'Справочники', 'Документы'
    indexed_at  REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_objects_name_kind ON meta_objects(name_lower, kind);
CREATE INDEX IF NOT EXISTS idx_meta_objects_collection ON meta_objects(collection);

CREATE TABLE IF NOT EXISTS meta_members (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id    INTEGER NOT NULL REFERENCES meta_objects(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    name_lower   TEXT NOT NULL,
    kind         TEXT NOT NULL,   -- 'attribute' | 'tabular_section' | 'ts_attribute' | 'form_attribute' | 'form_command'
    type_info    TEXT NOT NULL DEFAULT '',
    synonym_ru   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_meta_members_object ON meta_members(object_id);
CREATE INDEX IF NOT EXISTS idx_meta_members_name ON meta_members(name_lower);
"""

# Recreated after bulk index (must match SCHEMA_SQL trigger bodies).
FTS5_TRIGGER_SQL = """
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
"""


class SymbolIndex:
    """
    Persistent SQLite-backed index of BSL symbols and call-graph edges.

    Args:
        db_path: Path to the SQLite database file. ``None`` uses
            :func:`~onec_hbk_bsl.indexer.db_path.resolve_index_db_path` with
            ``os.getcwd()`` (typically ``.git/onec-hbk-bsl_index.sqlite`` or
            ``~/.cache/onec-hbk-bsl/…``). Use ``":memory:"`` for in-memory (tests).
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path if db_path is not None else resolve_index_db_path(os.getcwd())
        # Per-thread flag: True only in the thread that opened bulk_write().
        # Using threading.local() avoids cross-thread reads of a shared bool that
        # caused upsert_file() to skip its transaction wrapper when called from the
        # LSP/MCP thread while the indexer thread held BEGIN IMMEDIATE.
        self._bulk_write_tls = threading.local()
        # In-memory DBs are connection-scoped; keep per-instance connection to
        # avoid test isolation issues with the thread-local pool.
        self._mem_conn: sqlite3.Connection | None = None
        try:
            conn = self._conn()
            conn.executescript(SCHEMA_SQL)
            self._migrate_sync(conn)
            conn.commit()
        except sqlite3.OperationalError:
            # Fallback for restricted/unstable filesystems where on-disk DB is not writable.
            if self.db_path != ":memory:":
                self.db_path = ":memory:"
                self._mem_conn = None
                conn = self._conn()
                conn.executescript(SCHEMA_SQL)
                self._migrate_sync(conn)
                conn.commit()
            else:
                raise
        # Heavy data migrations (index build / data population) run in background
        # so they don't block LSP startup.
        threading.Thread(target=self._migrate_background, daemon=True,
                         name="bsl-db-migrate").start()

    def _migrate_sync(self, conn: sqlite3.Connection) -> None:
        """Fast, structural-only migrations that must complete before the server starts."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(symbols)")}
        if "name_lower" not in existing:
            conn.execute("ALTER TABLE symbols ADD COLUMN name_lower TEXT NOT NULL DEFAULT ''")

        existing_calls = {row[1] for row in conn.execute("PRAGMA table_info(calls)")}
        if "caller_character" not in existing_calls:
            conn.execute("ALTER TABLE calls ADD COLUMN caller_character INTEGER NOT NULL DEFAULT 0")
        if "callee_name_lower" not in existing_calls:
            conn.execute("ALTER TABLE calls ADD COLUMN callee_name_lower TEXT NOT NULL DEFAULT ''")

        # Ensure metadata tables exist for databases created before metadata support
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta_objects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                name_lower  TEXT NOT NULL,
                kind        TEXT NOT NULL,
                synonym_ru  TEXT NOT NULL DEFAULT '',
                file_path   TEXT NOT NULL DEFAULT '',
                collection  TEXT NOT NULL DEFAULT '',
                indexed_at  REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_objects_name_kind ON meta_objects(name_lower, kind);
            CREATE INDEX IF NOT EXISTS idx_meta_objects_collection ON meta_objects(collection);
            CREATE TABLE IF NOT EXISTS meta_members (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                object_id    INTEGER NOT NULL REFERENCES meta_objects(id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                name_lower   TEXT NOT NULL,
                kind         TEXT NOT NULL,
                type_info    TEXT NOT NULL DEFAULT '',
                synonym_ru   TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_meta_members_object ON meta_members(object_id);
            CREATE INDEX IF NOT EXISTS idx_meta_members_name ON meta_members(name_lower);
        """)

    def _migrate_background(self) -> None:
        """Heavy migrations: index creation and data population, run in background thread."""
        if self.db_path == ":memory:":
            return
        try:
            conn = self._conn()
            # Symbols: name_lower index (fast — index already built or instant for empty table)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name_lower ON symbols(name_lower)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name_file ON symbols(name_lower, file_path)")
            # Populate name_lower for existing rows that have empty value
            conn.execute("UPDATE symbols SET name_lower = LOWER(name) WHERE name_lower = ''")

            # Calls: drop old index on callee_name (useless after migration to callee_name_lower)
            old_idx = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_calls_callee'"
            ).fetchone()
            if old_idx and old_idx[0] and "callee_name_lower" not in old_idx[0]:
                conn.execute("DROP INDEX idx_calls_callee")
            # Create correct index on callee_name_lower
            conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee_name_lower)")
            conn.execute("UPDATE calls SET callee_name_lower = LOWER(callee_name) WHERE callee_name_lower = ''")

            # Help query planner
            conn.execute("ANALYZE symbols")
            conn.execute("ANALYZE calls")
        except Exception:
            pass  # Non-fatal; will retry next startup

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
        def _safe_pragma(sql: str) -> None:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                # Keep connection usable even when a particular pragma is unsupported.
                pass

        # Some filesystems/sandboxes do not support WAL; fallback to DELETE journal.
        _safe_pragma("PRAGMA journal_mode=WAL")
        _safe_pragma("PRAGMA journal_mode=DELETE")
        _safe_pragma("PRAGMA synchronous=NORMAL")
        # Wait up to 10 s before raising "database is locked" — prevents spurious
        # failures when the LSP/MCP thread tries to write while the indexer thread
        # holds BEGIN IMMEDIATE (e.g. full workspace reindex on initialize).
        _safe_pragma("PRAGMA busy_timeout=10000")
        _safe_pragma("PRAGMA cache_size=-131072")   # 128 MB page cache per connection
        _safe_pragma("PRAGMA mmap_size=1073741824")  # 1 GB memory-mapped I/O
        _safe_pragma("PRAGMA temp_store=MEMORY")
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

        conn_map: dict[str, sqlite3.Connection] = getattr(_local, "conn_map", {})
        existing = conn_map.get(self.db_path)
        if existing is None or self._is_closed(existing):
            existing = self._make_conn()
            conn_map[self.db_path] = existing
            _local.conn_map = conn_map
        return existing

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
            conn_map: dict[str, sqlite3.Connection] = getattr(_local, "conn_map", {})
            conn = conn_map.get(self.db_path)
            if conn and not self._is_closed(conn):
                conn.close()
            conn_map.pop(self.db_path, None)
            _local.conn_map = conn_map

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    @property
    def _bulk_write_active(self) -> bool:
        """True only in the thread that currently holds the bulk_write transaction."""
        return bool(getattr(self._bulk_write_tls, "active", False))

    @contextmanager
    def bulk_write(self):
        """
        Bulk indexing: drop FTS sync triggers, one transaction, fast PRAGMA, then FTS rebuild.

        Use around many ``upsert_file`` / ``remove_file`` calls (e.g. full workspace index).
        Skips per-row FTS5 trigger work during inserts; rebuilds ``symbols_fts`` once at the end.
        Thread-safe: the flag is tracked per-thread so concurrent LSP/MCP writes in other
        threads still wrap their own transaction instead of piggy-backing on this one.
        """
        conn = self._conn()
        if self._bulk_write_active:
            raise RuntimeError("nested bulk_write is not supported")
        self._bulk_write_tls.active = True
        conn.execute("DROP TRIGGER IF EXISTS symbols_ai")
        conn.execute("DROP TRIGGER IF EXISTS symbols_ad")
        conn.execute("DROP TRIGGER IF EXISTS symbols_au")
        try:
            conn.execute("PRAGMA synchronous=OFF")
        except sqlite3.OperationalError:
            pass
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            conn.execute("COMMIT")
            conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
            conn.executescript(FTS5_TRIGGER_SQL)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:
                pass
            conn.executescript(FTS5_TRIGGER_SQL)
            raise
        finally:
            try:
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.OperationalError:
                pass
            self._bulk_write_tls.active = False

    def _upsert_file_impl(
        self,
        conn: sqlite3.Connection,
        file_path: str,
        symbols: list[dict],
        calls: list[dict],
        now: float,
    ) -> None:
        conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
        conn.execute("DELETE FROM calls WHERE caller_file = ?", (file_path,))

        conn.executemany(
            """
            INSERT INTO symbols
                (name, name_lower, file_path, line, character, end_line, end_character,
                 kind, is_export, container, signature, doc_comment, indexed_at)
            VALUES
                (:name, :name_lower, :file_path, :line, :character, :end_line, :end_character,
                 :kind, :is_export, :container, :signature, :doc_comment, :indexed_at)
            """,
            [
                {
                    "name": s.get("name", ""),
                    "name_lower": s.get("name", "").casefold(),
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

        conn.executemany(
            """
            INSERT INTO calls (
                caller_file, caller_line, caller_character, caller_name,
                callee_name, callee_name_lower, callee_args_count
            )
            VALUES (
                :caller_file, :caller_line, :caller_character, :caller_name,
                :callee_name, :callee_name_lower, :callee_args_count
            )
            """,
            [
                {
                    "caller_file": file_path,
                    "caller_line": c.get("caller_line", 0),
                    "caller_character": c.get("caller_character", 0),
                    "caller_name": c.get("caller_name"),
                    "callee_name": c.get("callee_name", ""),
                    "callee_name_lower": c.get("callee_name", "").casefold(),
                    "callee_args_count": c.get("callee_args_count", 0),
                }
                for c in calls
            ],
        )

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
        if self._bulk_write_active:
            self._upsert_file_impl(conn, file_path, symbols, calls, now)
        else:
            with conn:
                self._upsert_file_impl(conn, file_path, symbols, calls, now)

    def remove_file(self, file_path: str) -> None:
        """Remove all index data for a file (called when file is deleted)."""
        conn = self._conn()
        if self._bulk_write_active:
            conn.execute("DELETE FROM symbols WHERE file_path = ?", (file_path,))
            conn.execute("DELETE FROM calls WHERE caller_file = ?", (file_path,))
        else:
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
            # Use pre-computed name_lower for index-assisted case-insensitive lookup.
            # No ORDER BY — avoids temp B-tree sort on large result sets (e.g. Записать: 3000+ rows).
            # The index scan order is already deterministic enough for IDE hover/definition use.
            sql = """
                SELECT * FROM symbols
                WHERE name_lower = :name_lower
                  AND (:file_filter IS NULL OR file_path LIKE :file_like)
                LIMIT :limit
            """
            rows = conn.execute(
                sql,
                {
                    "name_lower": name.casefold(),
                    "file_filter": file_filter,
                    "file_like": f"%{file_filter}%" if file_filter else None,
                    "limit": limit,
                },
            ).fetchall()

        return [dict(row) for row in rows]

    def find_callers_count(self, callee_name: str) -> int:
        """Return the total number of call sites for *callee_name* (fast COUNT query)."""
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM calls WHERE callee_name_lower = ?",
            (callee_name.casefold(),),
        ).fetchone()
        return int(row[0]) if row else 0

    def find_callers_count_non_recursive(self, callee_name: str) -> int:
        """Count call sites for *callee_name*, excluding recursive self-calls."""
        conn = self._conn()
        name_lo = callee_name.casefold()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM calls
            WHERE callee_name_lower = ?
              AND (caller_name IS NULL OR LOWER(caller_name) != ?)
            """,
            (name_lo, name_lo),
        ).fetchone()
        return int(row[0]) if row else 0

    def find_unused_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """Return non-export procedures/functions in *file_path* with zero non-recursive callers."""
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT s.* FROM symbols s
            WHERE s.file_path = ?
              AND s.kind IN ('procedure', 'function')
              AND s.is_export = 0
              AND NOT EXISTS (
                  SELECT 1 FROM calls c
                  WHERE c.callee_name_lower = s.name_lower
                    AND (c.caller_name IS NULL OR LOWER(c.caller_name) != s.name_lower)
              )
            ORDER BY s.line
            """,
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_callers(self, callee_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        Find all call sites that call *callee_name*.

        Returns dicts with: caller_file, caller_line, caller_name, callee_name.
        """
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT c.caller_file, c.caller_line, c.caller_character, c.caller_name, c.callee_name,
                   s.signature as caller_signature
            FROM calls c
            LEFT JOIN symbols s ON s.name_lower = c.callee_name_lower AND s.file_path = c.caller_file
            WHERE c.callee_name_lower = ?
            ORDER BY c.caller_file, c.caller_line
            LIMIT ?
            """,
            (callee_name.casefold(), limit),
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
                SELECT c.callee_name, c.caller_line, c.caller_character, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON s.name_lower = c.callee_name_lower
                WHERE c.caller_file = ?
                  AND c.caller_name = ?
                ORDER BY c.caller_line
                """,
                (caller_file, caller_name),
            ).fetchall()
        elif caller_line is not None:
            rows = conn.execute(
                """
                SELECT c.callee_name, c.caller_line, c.caller_character, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON s.name_lower = c.callee_name_lower
                WHERE c.caller_file = ?
                  AND c.caller_line BETWEEN ? AND ?
                ORDER BY c.caller_line
                """,
                (caller_file, caller_line - 15, caller_line + 15),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT c.callee_name, c.caller_line, c.caller_character, c.callee_args_count,
                       s.file_path as callee_file, s.line as callee_line, s.signature as callee_sig
                FROM calls c
                LEFT JOIN symbols s ON s.name_lower = c.callee_name_lower
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

    def get_module_exports(self, module_name: str) -> list[dict]:
        """Return exported symbols from the file whose stem matches *module_name* (case-insensitive)."""
        conn = self._conn()
        name_lo = module_name.casefold()
        rows = conn.execute(
            "SELECT * FROM symbols WHERE is_export=1 "
            "AND (LOWER(REPLACE(REPLACE(file_path,'\\\\','/'),'.bsl','')) LIKE ? "
            " OR  LOWER(REPLACE(REPLACE(file_path,'\\\\','/'),'.os',''))  LIKE ?) "
            "ORDER BY name_lower LIMIT 100",
            (f"%/{name_lo}", f"%/{name_lo}"),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Metadata write operations
    # ------------------------------------------------------------------

    def upsert_metadata(self, meta_objects: list) -> int:
        """
        Replace all metadata objects with the provided list.

        Args:
            meta_objects: List of MetaObject dataclass instances.

        Returns:
            Total number of members upserted.
        """
        from onec_hbk_bsl.indexer.metadata_registry import KIND_TO_COLLECTION  # noqa: PLC0415

        conn = self._conn()
        now = time.time()
        total_members = 0

        with conn:
            conn.execute("DELETE FROM meta_members")
            conn.execute("DELETE FROM meta_objects")

            for obj in meta_objects:
                collection = KIND_TO_COLLECTION.get(obj.kind, "")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO meta_objects
                        (name, name_lower, kind, synonym_ru, file_path, collection, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obj.name,
                        obj.name.casefold(),
                        obj.kind,
                        obj.synonym_ru,
                        obj.file_path,
                        collection,
                        now,
                    ),
                )
                obj_row = conn.execute(
                    "SELECT id FROM meta_objects WHERE name_lower=? AND kind=?",
                    (obj.name.casefold(), obj.kind),
                ).fetchone()
                if obj_row is None:
                    continue
                obj_id = obj_row[0]

                if obj.members:
                    conn.executemany(
                        """
                        INSERT INTO meta_members (object_id, name, name_lower, kind, type_info, synonym_ru)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (obj_id, m.name, m.name.casefold(), m.kind, m.type_info, m.synonym_ru)
                            for m in obj.members
                        ],
                    )
                    total_members += len(obj.members)

        return total_members

    # ------------------------------------------------------------------
    # Metadata read operations
    # ------------------------------------------------------------------

    def get_meta_members(self, object_name: str, member_prefix: str = "") -> list[dict[str, Any]]:
        """
        Return metadata members for the given object name (case-insensitive).

        Args:
            object_name: Technical name of the 1C object (e.g. 'Контрагенты').
            member_prefix: If provided, filter members whose name starts with this prefix.

        Returns:
            List of member dicts with keys: name, kind, type_info, synonym_ru, object_name, object_kind.
        """
        conn = self._conn()
        name_lo = object_name.casefold()

        obj_row = conn.execute(
            "SELECT id, name, kind, synonym_ru FROM meta_objects WHERE name_lower = ? LIMIT 1",
            (name_lo,),
        ).fetchone()
        if obj_row is None:
            return []

        obj_id = obj_row["id"]
        obj_name = obj_row["name"]
        obj_kind = obj_row["kind"]

        if member_prefix:
            prefix_lo = member_prefix.casefold()
            rows = conn.execute(
                "SELECT name, kind, type_info, synonym_ru FROM meta_members "
                "WHERE object_id = ? AND name_lower LIKE ? ORDER BY name_lower LIMIT 200",
                (obj_id, f"{prefix_lo}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, kind, type_info, synonym_ru FROM meta_members "
                "WHERE object_id = ? ORDER BY name_lower LIMIT 200",
                (obj_id,),
            ).fetchall()

        return [
            {
                "name": row["name"],
                "kind": row["kind"],
                "type_info": row["type_info"],
                "synonym_ru": row["synonym_ru"],
                "object_name": obj_name,
                "object_kind": obj_kind,
            }
            for row in rows
        ]

    def find_meta_object(self, object_name: str) -> dict[str, Any] | None:
        """Return metadata object info by name, or None if not found."""
        conn = self._conn()
        row = conn.execute(
            "SELECT name, kind, synonym_ru, collection FROM meta_objects WHERE name_lower = ? LIMIT 1",
            (object_name.casefold(),),
        ).fetchone()
        return dict(row) if row else None

    def find_meta_objects_by_collection(self, collection: str, prefix: str = "") -> list[dict[str, Any]]:
        """
        Return all objects in a 1C global collection (e.g. 'Справочники').

        Args:
            collection: Russian collection name (e.g. 'Справочники', 'Документы').
            prefix: If provided, filter by name prefix.
        """
        conn = self._conn()
        if prefix:
            prefix_lo = prefix.casefold()
            rows = conn.execute(
                "SELECT name, kind, synonym_ru FROM meta_objects "
                "WHERE collection = ? AND name_lower LIKE ? ORDER BY name_lower LIMIT 100",
                (collection, f"{prefix_lo}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, kind, synonym_ru FROM meta_objects "
                "WHERE collection = ? ORDER BY name_lower LIMIT 100",
                (collection,),
            ).fetchall()
        return [dict(r) for r in rows]

    def has_metadata(self) -> bool:
        """Return True if any metadata objects are indexed."""
        conn = self._conn()
        row = conn.execute("SELECT COUNT(*) FROM meta_objects").fetchone()
        return bool(row and row[0] > 0)

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""
        conn = self._conn()
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(DISTINCT file_path) FROM symbols").fetchone()[0]
        call_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        meta_count = conn.execute("SELECT COUNT(*) FROM meta_objects").fetchone()[0]
        last_commit = self.get_last_commit()
        row = conn.execute("SELECT indexed_at, workspace_root FROM git_state WHERE id = 1").fetchone()
        return {
            "symbol_count": symbol_count,
            "file_count": file_count,
            "call_count": call_count,
            "meta_object_count": meta_count,
            "last_commit": last_commit,
            "indexed_at": row["indexed_at"] if row else None,
            "workspace_root": row["workspace_root"] if row else None,
        }
