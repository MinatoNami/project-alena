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
import threading
from pathlib import Path
from typing import List, Optional

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


# One connection per thread, not one per process.
#
# sqlite3 refuses a connection used from a thread other than the one that
# created it, and a web server is multi-threaded -- Starlette runs endpoints on
# a portal thread, and not necessarily the same one each time. A single shared
# connection works perfectly until the API is added, then fails on the second
# request from a new thread.
#
# Thread-local rather than check_same_thread=False, because that flag only
# silences the check; it does not make concurrent use safe. WAL mode, set in
# connect(), is what lets these read alongside a writer.
_local = threading.local()
# Every connection handed out, so reset_connection() can close the ones this
# thread did not create. Tests repoint ALENA_DB_PATH between cases and a
# connection left open on a server thread would keep serving the old file.
_opened: List[sqlite3.Connection] = []
_opened_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """This thread's connection, opened on first use."""
    existing = getattr(_local, "conn", None)
    if existing is not None:
        return existing

    conn = connect()
    _local.conn = conn
    with _opened_lock:
        _opened.append(conn)
    return conn


def reset_connection() -> None:
    """Close every connection this process has opened.

    For tests that repoint ALENA_DB_PATH, and for anything that needs the next
    caller to reopen against a different file.
    """
    with _opened_lock:
        connections, _opened[:] = list(_opened), []
    for conn in connections:
        try:
            conn.close()
        except sqlite3.Error:
            # Closing from a different thread than it was created on raises,
            # and there is nothing useful to do about it -- the connection is
            # being discarded either way.
            pass
    _local.conn = None
