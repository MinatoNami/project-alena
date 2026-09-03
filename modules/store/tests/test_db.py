import sqlite3

import pytest

from modules.store import connect, migrate, resolve_db_path
from modules.store import db as db_module


def test_migrations_create_the_audit_table(tmp_path):
    conn = connect(str(tmp_path / "a.db"))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "tool_invocations" in tables
    assert "schema_migrations" in tables


def test_migrating_twice_is_a_no_op(tmp_path):
    conn = connect(str(tmp_path / "a.db"))
    first = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

    migrate(conn)

    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == first


def test_reopening_keeps_the_data(tmp_path):
    path = str(tmp_path / "a.db")
    conn = connect(path)
    conn.execute(
        "INSERT INTO tool_invocations (created_at, tool, agent, arguments_hash, outcome)"
        " VALUES ('now', 't', 'a', 'h', 'success')"
    )
    conn.commit()
    conn.close()

    reopened = connect(path)
    assert reopened.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()[0] == 1


def test_outcome_is_constrained(tmp_path):
    conn = connect(str(tmp_path / "a.db"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tool_invocations (created_at, tool, agent, arguments_hash,"
            " outcome) VALUES ('now', 't', 'a', 'h', 'probably_fine')"
        )


def test_the_database_lives_outside_the_repo_by_default(monkeypatch):
    """It is generated state; it must not land in the working tree."""
    monkeypatch.delenv("ALENA_DB_PATH", raising=False)
    assert ".alena" in str(resolve_db_path())


def test_env_overrides_the_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "x.db"))
    assert resolve_db_path() == tmp_path / "x.db"


def test_migration_filenames_must_be_ordered():
    """A migration without a numeric prefix has no defined position."""
    for _, path in db_module._discover_migrations():
        assert path.name[:3].isdigit()
