import sys
from pathlib import Path

import pytest

from mcp import StdioServerParameters

from modules.gateway.catalog import ToolCatalog
from modules.gateway.policy import parse_policy
from modules.gateway.audit import AuditLog
from modules.store import connect

FAKE_SERVER = str(Path(__file__).parent / "fake_mcp_server.py")

FAKE_POLICY = {
    "version": 1,
    "defaults": {"requires_approval": False, "repositories": ["*"]},
    "tools": {
        "fake_echo": {"side_effect": "read_only", "allowed_agents": ["assistant"]},
        "fake_pid": {"side_effect": "read_only", "allowed_agents": ["assistant"]},
        "fake_boom": {"side_effect": "read_only", "allowed_agents": ["assistant"]},
        "fake_read": {"side_effect": "read_only", "allowed_agents": ["assistant"]},
        "fake_write": {
            "side_effect": "repository_write",
            "allowed_agents": ["action-agent"],
            "requires_approval": True,
        },
    },
}


@pytest.fixture
def fake_server():
    """Server parameters for the fake MCP server subprocess."""
    return StdioServerParameters(command=sys.executable, args=[FAKE_SERVER])


@pytest.fixture
def memory_audit(tmp_path):
    """An audit log backed by a throwaway database."""
    conn = connect(str(tmp_path / "audit.db"))
    yield AuditLog(conn)
    conn.close()


@pytest.fixture
def fake_policy():
    return parse_policy(FAKE_POLICY)


@pytest.fixture
def fake_catalog(fake_policy):
    return ToolCatalog(fake_policy)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Never let a test touch the real ~/.alena database."""
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("ALENA_ALLOWED_REPO_ROOTS", raising=False)
    monkeypatch.delenv("ALENA_AUDIT_ARGUMENTS", raising=False)
    from modules.store import db

    db.reset_connection()
    yield
    db.reset_connection()
