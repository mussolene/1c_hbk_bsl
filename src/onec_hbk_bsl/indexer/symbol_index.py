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
from pathlib import Path
from typing import Any

from onec_hbk_bsl.indexer.db_path import (
    cleanup_index_storage,
    index_storage_lock,
    resolve_index_db_path,
)

# Increment when workspace discovery semantics change. Existing databases keep
# their previous value so the next run performs one full scope reconciliation.
INDEX_POLICY_VERSION = 2

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
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_file          TEXT NOT NULL,
    caller_line          INTEGER NOT NULL,
    caller_character     INTEGER NOT NULL DEFAULT 0,
    caller_name          TEXT,               -- name of the containing procedure/function
    callee_name          TEXT NOT NULL,
    callee_name_lower    TEXT NOT NULL DEFAULT '',  -- casefold(callee_name)
    callee_args_count    INTEGER DEFAULT 0,
    receiver_expression  TEXT                -- raw qualifier text (`Модуль` in `Модуль.Функция(...)`),
                                              -- NULL for bare/unqualified calls
);

CREATE INDEX IF NOT EXISTS idx_calls_caller      ON calls(caller_file, caller_line);
CREATE INDEX IF NOT EXISTS idx_calls_caller_name ON calls(caller_name);
CREATE INDEX IF NOT EXISTS idx_calls_callee_order ON calls(callee_name_lower, caller_file, caller_line);
CREATE INDEX IF NOT EXISTS idx_calls_caller_name_line ON calls(caller_file, caller_name, caller_line);

CREATE TABLE IF NOT EXISTS git_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    commit_hash    TEXT,
    indexed_at     REAL,
    workspace_root TEXT,
    index_mode     TEXT NOT NULL DEFAULT 'full',
    index_policy_version INTEGER NOT NULL DEFAULT 2
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

CREATE TABLE IF NOT EXISTS metadata_state (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    config_root  TEXT NOT NULL DEFAULT '',
    fingerprint  TEXT NOT NULL DEFAULT '',
    object_count INTEGER NOT NULL DEFAULT 0,
    member_count INTEGER NOT NULL DEFAULT 0,
    indexed_at   REAL NOT NULL
);
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

CORRUPT_DB_ERROR_FRAGMENTS = (
    "file is not a database",
    "database disk image is malformed",
)


class SymbolIndex:
    """
    Persistent SQLite-backed index of BSL symbols and call-graph edges.

    Args:
        db_path: Path to the SQLite database file. ``None`` uses
            :func:`~onec_hbk_bsl.indexer.db_path.resolve_index_db_path` with
            ``os.getcwd()`` (typically ``.git/onec-hbk-bsl_index.sqlite`` or
            ``~/.cache/onec-hbk-bsl/…``). Use ``":memory:"`` for in-memory (tests).
    """

    def __init__(
        self,
        db_path: str | None = None,
        mode: str | None = None,
        max_size_bytes: int | None = None,
    ) -> None:
        self.db_path = db_path if db_path is not None else resolve_index_db_path(os.getcwd())
        self._sqlite_profile = self._resolve_sqlite_profile(mode)
        self.max_size_bytes = (
            max_size_bytes
            if max_size_bytes is not None
            else self._read_env_int("BSL_INDEX_MAX_BYTES", 0, minimum=0)
        )
        # Connections belong to this SymbolIndex instance.  The previous module-global
        # thread-local map let independent LSP/MCP instances accidentally share a
        # connection and made it impossible for close() to release worker connections.
        self._conn_tls = threading.local()
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.RLock()
        # Per-thread flag: True only in the thread that opened bulk_write().
        # Using threading.local() avoids cross-thread reads of a shared bool that
        # caused upsert_file() to skip its transaction wrapper when called from the
        # LSP/MCP thread while the indexer thread held BEGIN IMMEDIATE.
        self._bulk_write_tls = threading.local()
        # In-memory DBs are connection-scoped; keep per-instance connection to
        # avoid test isolation issues with the thread-local pool.
        self._mem_conn: sqlite3.Connection | None = None
        try:
            self._initialize_or_open_existing()
        except sqlite3.DatabaseError as exc:
            if self.db_path != ":memory:" and self._is_corrupt_db_error(exc):
                if self._recover_corrupt_database():
                    self._initialize_schema()
                else:
                    self._fallback_to_memory()
            elif self.db_path != ":memory:" and isinstance(exc, sqlite3.OperationalError):
                self._fallback_to_memory()
            else:
                raise
        # Heavy data migrations (index build / data population) run in background
        # so they don't block LSP startup.
        self._migration_thread = threading.Thread(
            target=self._migrate_background, daemon=True, name="bsl-db-migrate"
        )
        self._migration_thread.start()

    def wait_for_background_migration(self, timeout: float | None = None) -> bool:
        """Wait for the per-instance migration writer before another write operation."""
        thread = self._migration_thread
        if thread is threading.current_thread():
            return True
        join = getattr(thread, "join", None)
        is_alive = getattr(thread, "is_alive", None)
        if join is None or is_alive is None:
            return True
        join(timeout=timeout)
        return not bool(is_alive())

    def _initialize_or_open_existing(self) -> None:
        """Create/migrate under the writer lock, or open an already-active index read-only-ish."""
        if self.db_path == ":memory:":
            self._initialize_schema()
            return
        with index_storage_lock(self.db_path) as acquired:
            if acquired:
                self._initialize_schema()
                return
            # Another process is indexing.  Avoid schema writes and verify that the
            # existing cache is usable; callers can still serve read queries.
            self._conn().execute("SELECT 1 FROM symbols LIMIT 1").fetchone()

    @staticmethod
    def _read_env_int(name: str, default: int, *, minimum: int | None = None) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            parsed = int(raw)
        except ValueError:
            return default
        if minimum is not None and parsed < minimum:
            return default
        return parsed

    @classmethod
    def _resolve_sqlite_profile(cls, mode: str | None) -> dict[str, int | str]:
        selected = (
            (mode or "").strip().lower()
            or os.environ.get("BSL_SYMBOL_INDEX_MODE", "").strip().lower()
            or "interactive"
        )
        if selected not in {"interactive", "batch"}:
            selected = "interactive"

        # Lower memory pressure for long-lived interactive processes, higher throughput for batch.
        defaults: dict[str, dict[str, int | str]] = {
            "interactive": {
                "cache_size": -32768,  # 32 MB page cache per connection
                "mmap_size": 268435456,  # 256 MB mmap window
                "busy_timeout_ms": 10000,
                "temp_store": "MEMORY",
            },
            "batch": {
                "cache_size": -131072,  # 128 MB page cache per connection
                "mmap_size": 1073741824,  # 1 GB mmap window
                "busy_timeout_ms": 10000,
                "temp_store": "MEMORY",
            },
        }
        base = defaults[selected].copy()
        base["mode"] = selected

        base["cache_size"] = cls._read_env_int("BSL_SQLITE_CACHE_SIZE", int(base["cache_size"]))
        base["mmap_size"] = cls._read_env_int(
            "BSL_SQLITE_MMAP_SIZE", int(base["mmap_size"]), minimum=0
        )
        base["busy_timeout_ms"] = cls._read_env_int(
            "BSL_SQLITE_BUSY_TIMEOUT_MS", int(base["busy_timeout_ms"]), minimum=1
        )

        temp_store_raw = os.environ.get("BSL_SQLITE_TEMP_STORE", "").strip().upper()
        if temp_store_raw in {"DEFAULT", "FILE", "MEMORY"}:
            base["temp_store"] = temp_store_raw
        return base

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
        if "receiver_expression" not in existing_calls:
            conn.execute("ALTER TABLE calls ADD COLUMN receiver_expression TEXT")

        existing_git_state = {row[1] for row in conn.execute("PRAGMA table_info(git_state)")}
        if "index_mode" not in existing_git_state:
            conn.execute("ALTER TABLE git_state ADD COLUMN index_mode TEXT NOT NULL DEFAULT 'full'")
        if "index_policy_version" not in existing_git_state:
            # Version 1 represents the former filesystem-wide discovery policy.
            # Do not use the current schema default here: existing indexes must
            # receive a one-time full pass that prunes newly ignored paths.
            conn.execute(
                "ALTER TABLE git_state ADD COLUMN index_policy_version INTEGER NOT NULL DEFAULT 1"
            )

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
            CREATE TABLE IF NOT EXISTS metadata_state (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                config_root  TEXT NOT NULL DEFAULT '',
                fingerprint  TEXT NOT NULL DEFAULT '',
                object_count INTEGER NOT NULL DEFAULT 0,
                member_count INTEGER NOT NULL DEFAULT 0,
                indexed_at   REAL NOT NULL
            );
        """)

    def _migrate_background(self) -> None:
        """Heavy migrations: index creation and data population, run in background thread."""
        if self.db_path == ":memory:":
            return
        with index_storage_lock(self.db_path) as acquired:
            if not acquired:
                return
            self._migrate_background_locked()

    def _migrate_background_locked(self) -> None:
        try:
            conn = self._conn()
            # Symbols: name_lower index (fast — index already built or instant for empty table)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name_lower ON symbols(name_lower)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_name_file ON symbols(name_lower, file_path)"
            )
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_calls_callee_order ON calls(callee_name_lower, caller_file, caller_line)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_calls_caller_name_line ON calls(caller_file, caller_name, caller_line)"
            )
            conn.execute(
                "UPDATE calls SET callee_name_lower = LOWER(callee_name) WHERE callee_name_lower = ''"
            )

            # Help query planner
            conn.execute("ANALYZE symbols")
            conn.execute("ANALYZE calls")
        except Exception:
            pass  # Non-fatal; will retry next startup

    def _initialize_schema(self) -> None:
        conn = self._conn()
        conn.executescript(SCHEMA_SQL)
        self._migrate_sync(conn)
        conn.commit()

    def _fallback_to_memory(self) -> None:
        self.close()
        self.db_path = ":memory:"
        self._mem_conn = None
        self._initialize_schema()

    @staticmethod
    def _is_corrupt_db_error(exc: sqlite3.DatabaseError) -> bool:
        message = str(exc).casefold()
        return any(fragment in message for fragment in CORRUPT_DB_ERROR_FRAGMENTS)

    def _recover_corrupt_database(self) -> bool:
        """Delete an unusable disposable cache DB under the cross-process lock."""
        self.close()
        with index_storage_lock(self.db_path) as acquired:
            if not acquired:
                return False
            cleanup_index_storage(self.db_path, include_corrupt=True)
            return True

    def _handle_read_database_error(self, exc: sqlite3.DatabaseError) -> bool:
        if not self._is_corrupt_db_error(exc):
            return False
        if self.db_path != ":memory:":
            if not self._recover_corrupt_database():
                self._fallback_to_memory()
                return True
            try:
                self._initialize_schema()
            except sqlite3.DatabaseError:
                self._fallback_to_memory()
        return True

    def _read_list(self, query) -> list[dict[str, Any]]:
        try:
            rows = query(self._conn())
        except sqlite3.DatabaseError as exc:
            if not self._handle_read_database_error(exc):
                raise
            return []
        return [dict(row) for row in rows]

    def _read_optional_row(self, query) -> sqlite3.Row | None:
        try:
            return query(self._conn())
        except sqlite3.DatabaseError as exc:
            if not self._handle_read_database_error(exc):
                raise
            return None

    def _read_int(self, query) -> int:
        try:
            row = query(self._conn())
        except sqlite3.DatabaseError as exc:
            if not self._handle_read_database_error(exc):
                raise
            return 0
        return int(row[0]) if row else 0

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

        def _safe_pragma(sql: str) -> sqlite3.Row | None:
            try:
                return conn.execute(sql).fetchone()
            except sqlite3.OperationalError:
                # Keep connection usable even when a particular pragma is unsupported.
                return None

        # Some filesystems/sandboxes do not support WAL; fallback to DELETE journal.
        journal_row = _safe_pragma("PRAGMA journal_mode=WAL")
        if journal_row is None or str(journal_row[0]).casefold() != "wal":
            _safe_pragma("PRAGMA journal_mode=DELETE")
        _safe_pragma("PRAGMA synchronous=NORMAL")
        _safe_pragma(
            f"PRAGMA wal_autocheckpoint={self._read_env_int('BSL_SQLITE_WAL_AUTOCHECKPOINT', 1000, minimum=1)}"
        )
        # Wait up to 10 s before raising "database is locked" — prevents spurious
        # failures when the LSP/MCP thread tries to write while the indexer thread
        # holds BEGIN IMMEDIATE (e.g. full workspace reindex on initialize).
        _safe_pragma(f"PRAGMA busy_timeout={int(self._sqlite_profile['busy_timeout_ms'])}")
        _safe_pragma(f"PRAGMA cache_size={int(self._sqlite_profile['cache_size'])}")
        _safe_pragma(f"PRAGMA mmap_size={int(self._sqlite_profile['mmap_size'])}")
        _safe_pragma(f"PRAGMA temp_store={str(self._sqlite_profile['temp_store'])}")
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

        existing: sqlite3.Connection | None = getattr(self._conn_tls, "conn", None)
        if existing is None or self._is_closed(existing):
            existing = self._make_conn()
            self._conn_tls.conn = existing
            with self._connections_lock:
                self._connections.add(existing)
        return existing

    @staticmethod
    def _is_closed(conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT 1")
            return False
        except sqlite3.ProgrammingError:
            return True

    @staticmethod
    def _path_size_bytes(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _index_size_stats(self) -> dict[str, int]:
        """Return file sizes for the main DB and sidecar WAL/SHM files."""
        if self.db_path == ":memory:":
            return {
                "db_size_bytes": 0,
                "wal_size_bytes": 0,
                "shm_size_bytes": 0,
                "index_size_bytes": 0,
            }

        db_path = Path(self.db_path)
        db_size = self._path_size_bytes(db_path)
        wal_size = self._path_size_bytes(Path(f"{self.db_path}-wal"))
        shm_size = self._path_size_bytes(Path(f"{self.db_path}-shm"))
        return {
            "db_size_bytes": db_size,
            "wal_size_bytes": wal_size,
            "shm_size_bytes": shm_size,
            "index_size_bytes": db_size + wal_size + shm_size,
        }

    def close(self) -> None:
        """Close every connection owned by this index, including worker threads."""
        migration = getattr(self, "_migration_thread", None)
        if migration is not None and migration is not threading.current_thread():
            join = getattr(migration, "join", None)
            if join is not None:
                join(timeout=10.0)
        if self.db_path == ":memory:":
            if self._mem_conn and not self._is_closed(self._mem_conn):
                self._mem_conn.close()
            self._mem_conn = None
        else:
            with self._connections_lock:
                connections = list(self._connections)
                self._connections.clear()
            for conn in connections:
                try:
                    if not self._is_closed(conn):
                        conn.close()
                except sqlite3.Error:
                    pass
            self._conn_tls = threading.local()

    def checkpoint(self, *, truncate: bool = False) -> dict[str, int]:
        """Checkpoint WAL pages; truncate the sidecar after an exclusive full pass."""
        if self.db_path == ":memory:":
            return {"busy": 0, "log_pages": 0, "checkpointed_pages": 0}
        mode = "TRUNCATE" if truncate else "PASSIVE"
        row = self._conn().execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        values = tuple(row or (0, 0, 0))
        return {
            "busy": int(values[0]),
            "log_pages": int(values[1]),
            "checkpointed_pages": int(values[2]),
        }

    def compact(self) -> dict[str, int]:
        """Rebuild the disposable DB to reclaim free pages, then truncate its WAL."""
        before = self._index_size_stats()["index_size_bytes"]
        self.checkpoint(truncate=True)
        self._conn().execute("VACUUM")
        self.checkpoint(truncate=True)
        after = self._index_size_stats()["index_size_bytes"]
        return {"before_bytes": before, "after_bytes": after, "reclaimed_bytes": before - after}

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
                callee_name, callee_name_lower, callee_args_count, receiver_expression
            )
            VALUES (
                :caller_file, :caller_line, :caller_character, :caller_name,
                :callee_name, :callee_name_lower, :callee_args_count, :receiver_expression
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
                    "receiver_expression": c.get("receiver_expression"),
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

    def save_commit(
        self,
        commit_hash: str,
        workspace_root: str = "",
        index_mode: str = "full",
        index_policy_version: int = INDEX_POLICY_VERSION,
    ) -> None:
        """Persist the last successfully indexed commit hash."""
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO git_state
                    (id, commit_hash, indexed_at, workspace_root, index_mode, index_policy_version)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    commit_hash = excluded.commit_hash,
                    indexed_at = excluded.indexed_at,
                    workspace_root = excluded.workspace_root,
                    index_mode = excluded.index_mode,
                    index_policy_version = excluded.index_policy_version
                """,
                (
                    commit_hash,
                    time.time(),
                    workspace_root,
                    index_mode,
                    index_policy_version,
                ),
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
            return self._read_list(lambda conn: conn.execute(sql, params).fetchall())
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
            params = {
                "name_lower": name.casefold(),
                "file_filter": file_filter,
                "file_like": f"%{file_filter}%" if file_filter else None,
                "limit": limit,
            }
            return self._read_list(lambda conn: conn.execute(sql, params).fetchall())

    def find_symbol_candidates(
        self,
        name: str,
        file_filter: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Return a stable page of exact symbol matches and the total match count.

        This is intentionally separate from ``find_symbol``: interactive
        hover/definition lookups retain their index-order fast path, while
        ambiguity responses get deterministic ordering and an explicit
        truncation contract.
        """
        sql = """
            SELECT s.*, COUNT(*) OVER () AS candidate_count
            FROM symbols s
            WHERE s.name_lower = :name_lower
              AND (:file_filter IS NULL OR s.file_path LIKE :file_like)
            ORDER BY
                s.file_path COLLATE NOCASE,
                s.file_path,
                s.line,
                s.character,
                s.kind,
                s.id
            LIMIT :limit
        """
        params = {
            "name_lower": name.casefold(),
            "file_filter": file_filter,
            "file_like": f"%{file_filter}%" if file_filter else None,
            "limit": limit,
        }
        rows = self._read_list(lambda conn: conn.execute(sql, params).fetchall())
        if not rows:
            return [], 0
        candidate_count = int(rows[0].pop("candidate_count"))
        for row in rows[1:]:
            row.pop("candidate_count", None)
        return rows, candidate_count

    def find_callers_count(self, callee_name: str) -> int:
        """Return the total number of call sites for *callee_name* (fast COUNT query)."""
        return self._read_int(
            lambda conn: conn.execute(
                "SELECT COUNT(*) FROM calls WHERE callee_name_lower = ?",
                (callee_name.casefold(),),
            ).fetchone()
        )

    def find_callers_count_non_recursive(self, callee_name: str) -> int:
        """Count call sites for *callee_name*, excluding recursive self-calls."""
        name_lo = callee_name.casefold()
        return self._read_int(
            lambda conn: conn.execute(
                """
                SELECT COUNT(*) FROM calls
                WHERE callee_name_lower = ?
                  AND (caller_name IS NULL OR LOWER(caller_name) != ?)
                """,
                (name_lo, name_lo),
            ).fetchone()
        )

    def find_unused_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """Return non-export procedures/functions in *file_path* with zero non-recursive callers."""
        return self._read_list(
            lambda conn: conn.execute(
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
        )

    def find_callers(
        self,
        callee_name: str,
        limit: int | None = 50,
        scope_file: str | None = None,
        receiver_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find all call sites that call *callee_name*.

        Args:
            callee_name: Bare name of the called procedure/function.
            limit:       Max rows to return (``None`` for unlimited).
            scope_file:  When given, restrict results to call sites in this
                         file. Bare-name calls to a non-exported (module-local)
                         symbol can only resolve within its own module, so
                         callers should be scoped to the defining file to
                         avoid attributing an unrelated same-named local
                         procedure's callers to it.
            receiver_name: When given, restrict *qualified* call sites
                         (``Модуль.Функция(...)``) to ones whose qualifier
                         names this exact module/object — the last dotted
                         segment of ``receiver_expression`` is compared
                         case-insensitively (covers both
                         ``ОбщийМодуль.Функция`` and
                         ``Справочники.Объект.Функция`` shapes). Bare/
                         unqualified calls (``receiver_expression IS NULL``)
                         are never excluded by this filter — a same-named
                         exported symbol elsewhere still can't be ruled out
                         for those (see
                         ``tmp/fixed/onec-hbk-bsl-issue-calls-drop-qualifier.md``).
                         Use for symbols with multiple same-named
                         definitions, where an unfiltered lookup would
                         attribute every qualified caller in the workspace
                         to whichever definition happened to be resolved.

        Returns dicts with: caller_file, caller_line, caller_name, callee_name.
        """
        sql = """
                SELECT c.caller_file, c.caller_line, c.caller_character, c.caller_name, c.callee_name,
                       c.receiver_expression,
                       s.signature as caller_signature
                FROM calls c
                LEFT JOIN symbols s ON s.name_lower = c.callee_name_lower AND s.file_path = c.caller_file
                WHERE c.callee_name_lower = ?
                """
        params: list[Any] = [callee_name.casefold()]
        if scope_file is not None:
            sql += " AND c.caller_file = ?"
            params.append(scope_file)
        if receiver_name is not None:
            sql += """ AND (
                c.receiver_expression IS NULL
                OR LOWER(c.receiver_expression) = LOWER(?)
                OR LOWER(c.receiver_expression) LIKE '%.' || LOWER(?)
            )"""
            params.append(receiver_name)
            params.append(receiver_name)
        sql += " ORDER BY c.caller_file, c.caller_line"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return self._read_list(
            lambda conn: conn.execute(
                sql,
                tuple(params),
            ).fetchall()
        )

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
        if caller_name is not None:
            return self._read_list(
                lambda conn: conn.execute(
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
            )
        elif caller_line is not None:
            return self._read_list(
                lambda conn: conn.execute(
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
            )
        return self._read_list(
            lambda conn: conn.execute(
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
        )

    def get_file_symbols(self, file_path: str) -> list[dict[str, Any]]:
        """Return all symbols defined in a file, ordered by line."""
        return self._read_list(
            lambda conn: conn.execute(
                "SELECT * FROM symbols WHERE file_path = ? ORDER BY line",
                (file_path,),
            ).fetchall()
        )

    def get_indexed_files(self) -> set[str]:
        """Return file paths currently represented by symbol or call rows."""
        rows = self._read_list(
            lambda conn: conn.execute(
                "SELECT file_path AS path FROM symbols UNION SELECT caller_file AS path FROM calls"
            ).fetchall()
        )
        return {str(row["path"]) for row in rows}

    def get_last_commit(self) -> str | None:
        """Return the last indexed commit hash, or None if not yet indexed."""
        row = self._read_optional_row(
            lambda conn: conn.execute("SELECT commit_hash FROM git_state WHERE id = 1").fetchone()
        )
        return row["commit_hash"] if row else None

    def get_last_index_mode(self) -> str | None:
        """Return the mode used for the last complete workspace pass."""
        row = self._read_optional_row(
            lambda conn: conn.execute("SELECT index_mode FROM git_state WHERE id = 1").fetchone()
        )
        return str(row["index_mode"]) if row else None

    def get_last_index_policy_version(self) -> int | None:
        """Return the discovery policy used for the last complete workspace pass."""
        row = self._read_optional_row(
            lambda conn: conn.execute(
                "SELECT index_policy_version FROM git_state WHERE id = 1"
            ).fetchone()
        )
        return int(row["index_policy_version"]) if row else None

    def get_module_exports(self, module_name: str) -> list[dict]:
        """Return exported symbols from the file whose stem matches *module_name* (case-insensitive)."""
        name_lo = module_name.casefold()
        return self._read_list(
            lambda conn: conn.execute(
                "SELECT * FROM symbols WHERE is_export=1 "
                "AND (LOWER(REPLACE(REPLACE(file_path,'\\\\','/'),'.bsl','')) LIKE ? "
                " OR  LOWER(REPLACE(REPLACE(file_path,'\\\\','/'),'.os',''))  LIKE ?) "
                "ORDER BY name_lower LIMIT 100",
                (f"%/{name_lo}", f"%/{name_lo}"),
            ).fetchall()
        )

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

    def get_metadata_state(self, config_root: str) -> dict[str, Any] | None:
        """Return cached metadata crawl state for *config_root*, if present."""
        row = self._read_optional_row(
            lambda conn: conn.execute(
                """
                SELECT config_root, fingerprint, object_count, member_count, indexed_at
                FROM metadata_state
                WHERE id = 1 AND config_root = ?
                """,
                (config_root,),
            ).fetchone()
        )
        return dict(row) if row else None

    def save_metadata_state(
        self,
        *,
        config_root: str,
        fingerprint: str,
        object_count: int,
        member_count: int,
    ) -> None:
        """Persist metadata crawl fingerprint and counts."""
        conn = self._conn()
        with conn:
            conn.execute(
                """
                INSERT INTO metadata_state
                    (id, config_root, fingerprint, object_count, member_count, indexed_at)
                VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    config_root = excluded.config_root,
                    fingerprint = excluded.fingerprint,
                    object_count = excluded.object_count,
                    member_count = excluded.member_count,
                    indexed_at = excluded.indexed_at
                """,
                (config_root, fingerprint, object_count, member_count, time.time()),
            )

    # ------------------------------------------------------------------
    # Metadata read operations
    # ------------------------------------------------------------------

    def get_meta_members(
        self,
        object_name: str,
        member_prefix: str = "",
        *,
        object_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return metadata members for the given object name (case-insensitive).

        Args:
            object_name: Technical name of the 1C object (e.g. 'Контрагенты').
            member_prefix: If provided, filter members whose name starts with this prefix.
            object_kind: If provided, require the exact metadata kind. This avoids
                choosing an arbitrary same-named object from another collection.

        Returns:
            List of member dicts with keys: name, kind, type_info, synonym_ru, object_name, object_kind.
        """
        name_lo = object_name.casefold()
        if object_kind is None:
            obj_row = self._read_optional_row(
                lambda conn: conn.execute(
                    "SELECT id, name, kind, synonym_ru FROM meta_objects "
                    "WHERE name_lower = ? ORDER BY kind LIMIT 1",
                    (name_lo,),
                ).fetchone()
            )
        else:
            obj_row = self._read_optional_row(
                lambda conn: conn.execute(
                    "SELECT id, name, kind, synonym_ru FROM meta_objects "
                    "WHERE name_lower = ? AND kind = ? LIMIT 1",
                    (name_lo, object_kind),
                ).fetchone()
            )
        if obj_row is None:
            return []

        obj_id = obj_row["id"]
        obj_name = obj_row["name"]
        obj_kind = obj_row["kind"]

        if member_prefix:
            prefix_lo = member_prefix.casefold()
            rows = self._read_list(
                lambda conn: conn.execute(
                    "SELECT name, kind, type_info, synonym_ru FROM meta_members "
                    "WHERE object_id = ? AND name_lower LIKE ? ORDER BY name_lower",
                    (obj_id, f"{prefix_lo}%"),
                ).fetchall()
            )
        else:
            rows = self._read_list(
                lambda conn: conn.execute(
                    "SELECT name, kind, type_info, synonym_ru FROM meta_members "
                    "WHERE object_id = ? ORDER BY name_lower",
                    (obj_id,),
                ).fetchall()
            )

        return [
            {
                "name": member["name"],
                "kind": member["kind"],
                "type_info": member["type_info"],
                "synonym_ru": member["synonym_ru"],
                "object_name": obj_name,
                "object_kind": obj_kind,
            }
            for member in rows
        ]

    def find_meta_object_candidates(
        self,
        object_name: str,
        *,
        object_kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return deterministic exact-name candidates without guessing across kinds."""
        if object_kind is None:
            return self._read_list(
                lambda conn: conn.execute(
                    "SELECT name, kind, synonym_ru, collection FROM meta_objects "
                    "WHERE name_lower = ? ORDER BY kind, name",
                    (object_name.casefold(),),
                ).fetchall()
            )
        return self._read_list(
            lambda conn: conn.execute(
                "SELECT name, kind, synonym_ru, collection FROM meta_objects "
                "WHERE name_lower = ? AND kind = ? ORDER BY name",
                (object_name.casefold(), object_kind),
            ).fetchall()
        )

    def find_meta_object(self, object_name: str) -> dict[str, Any] | None:
        """Return the first deterministic metadata object candidate for compatibility."""
        candidates = self.find_meta_object_candidates(object_name)
        return candidates[0] if candidates else None

    def find_meta_objects_by_collection(
        self, collection: str, prefix: str = ""
    ) -> list[dict[str, Any]]:
        """
        Return all objects in a 1C global collection (e.g. 'Справочники').

        Args:
            collection: Russian collection name (e.g. 'Справочники', 'Документы').
            prefix: If provided, filter by name prefix.
        """
        if prefix:
            prefix_lo = prefix.casefold()
            return self._read_list(
                lambda conn: conn.execute(
                    "SELECT name, kind, synonym_ru FROM meta_objects "
                    "WHERE collection = ? AND name_lower LIKE ? ORDER BY name_lower LIMIT 100",
                    (collection, f"{prefix_lo}%"),
                ).fetchall()
            )
        else:
            return self._read_list(
                lambda conn: conn.execute(
                    "SELECT name, kind, synonym_ru FROM meta_objects "
                    "WHERE collection = ? ORDER BY name_lower LIMIT 100",
                    (collection,),
                ).fetchall()
            )

    def has_metadata(self) -> bool:
        """Return True if any metadata objects are indexed."""
        return (
            self._read_int(
                lambda conn: conn.execute("SELECT COUNT(*) FROM meta_objects").fetchone()
            )
            > 0
        )

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""

        def _read_stats(conn: sqlite3.Connection) -> dict[str, Any]:
            symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            file_count = conn.execute("SELECT COUNT(DISTINCT file_path) FROM symbols").fetchone()[0]
            call_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            meta_count = conn.execute("SELECT COUNT(*) FROM meta_objects").fetchone()[0]
            last_commit_row = conn.execute(
                "SELECT commit_hash FROM git_state WHERE id = 1"
            ).fetchone()
            row = conn.execute(
                "SELECT indexed_at, workspace_root FROM git_state WHERE id = 1"
            ).fetchone()
            return {
                "symbol_count": symbol_count,
                "file_count": file_count,
                "call_count": call_count,
                "meta_object_count": meta_count,
                "last_commit": last_commit_row["commit_hash"] if last_commit_row else None,
                "indexed_at": row["indexed_at"] if row else None,
                "workspace_root": row["workspace_root"] if row else None,
            }

        try:
            stats = _read_stats(self._conn())
        except sqlite3.DatabaseError as exc:
            if not self._handle_read_database_error(exc):
                raise
            stats = {
                "symbol_count": 0,
                "file_count": 0,
                "call_count": 0,
                "meta_object_count": 0,
                "last_commit": None,
                "indexed_at": None,
                "workspace_root": None,
            }
        stats.update(self._index_size_stats())
        stats["max_size_bytes"] = self.max_size_bytes
        stats["over_size_limit"] = bool(
            self.max_size_bytes and stats["index_size_bytes"] > self.max_size_bytes
        )
        return stats
