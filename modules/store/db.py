"""SQLite storage for Project ALENA.

Deliberately stdlib `sqlite3` and hand-written SQL migrations rather than an
ORM: the schema is small, the repo's dependency list is short on purpose, and
migrations that are plain files are easy to review.

The database lives outside the repository by default. It is generated state
that grows on every run, so committing it -- or letting it sit in the working
tree where a stray `git add -A` would -- is not wanted.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_FILENAME = re.compile(r"^(\d{3})_.+\.sql$")

DEFAULT_DB_PATH = "~/.alena/alena.db"


def resolve_db_path(path: Optional[str] = None) -> Path:
    """Where the database lives. `:memory:` is passed through for tests."""
    raw = path or os.getenv("ALENA_DB_PATH") or DEFAULT_DB_PATH
    if raw == ":memory:":
        return Path(raw)
    return Path(raw).expanduser().resolve()


def _discover_migrations() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for entry in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_FILENAME.match(entry.name)
        if not match:
            raise ValueError(
                f"Migration {entry.name} does not match NNN_name.sql; "
                "the numeric prefix is what orders them."
            )
        found.append((int(match.group(1)), entry))
    return found


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration the connection has not seen. Returns the version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    applied = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    }

    version = max(applied, default=0)
    for number, path in _discover_migrations():
        if number in applied:
            continue
        # executescript() commits any open transaction, so the bookkeeping row
        # is written in the same script to keep the two from drifting apart.
        conn.executescript(path.read_text())
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (number,)
        )
        conn.commit()
        version = max(version, number)

    return version


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """Open the database, creating and migrating it if needed."""
    resolved = resolve_db_path(path)
    if str(resolved) != ":memory:":
        resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    # Concurrent readers alongside the nightly writer; without WAL a scan would
    # block anything else touching the database.
    if str(resolved) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


_shared: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """The process-wide connection, opened on first use."""
    global _shared
    if _shared is None:
        _shared = connect()
    return _shared


def reset_connection() -> None:
    """Drop the shared connection. For tests that repoint ALENA_DB_PATH."""
    global _shared
    if _shared is not None:
        _shared.close()
    _shared = None
