"""The gateway is the security boundary, so these tests are about refusals.

Every test that expects a denial also asserts the attempt was logged: a
refusal nobody can see afterwards is not much of a boundary.
"""

import pytest

from modules.gateway.audit import hash_arguments
from modules.gateway.catalog import ToolCatalog
from modules.gateway.contracts import ToolContract
from modules.gateway.errors import (
    ApprovalRequired,
    InvalidArguments,
    RepositoryPathDenied,
    ToolNotDeclared,
    ToolNotRegistered,
)
from modules.gateway.gateway import Approval, ToolGateway


class FakePool:
    """Records calls instead of spawning anything."""

    def __init__(self, result="ok", error=None):
        self.calls = []
        self._result = result
        self._error = error

    async def call_tool(self, server, tool, arguments):
        self.calls.append((tool, arguments))
        if self._error:
            raise self._error
        return self._result


ECHO = ToolContract(
    name="fake_echo",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    mcp_server="fake",
)
WRITE = ToolContract(
    name="fake_write",
    input_schema={
        "type": "object",
        "properties": {"repo_path": {"type": "string"}},
        "required": ["repo_path"],
    },
    mcp_server="fake",
)
READ = ToolContract(
    name="fake_read",
    input_schema={
        "type": "object",
        "properties": {"repo_path": {"type": "string"}},
        "required": ["repo_path"],
    },
    mcp_server="fake",
)
UNDECLARED = ToolContract(name="fake_undeclared", mcp_server="fake")


@pytest.fixture
def catalog(fake_policy):
    catalog = ToolCatalog(fake_policy)
    catalog.register([ECHO, WRITE, READ, UNDECLARED])
    return catalog


@pytest.fixture
def pool():
    return FakePool()


@pytest.fixture
def gateway(catalog, memory_audit, pool):
    return ToolGateway(catalog, audit=memory_audit, pool=pool)


@pytest.mark.asyncio
async def test_permitted_call_runs_and_is_logged(gateway, pool, memory_audit):
    result = await gateway.call(None, "fake_echo", {"text": "hi"}, agent="assistant")

    assert result == "ok"
    assert pool.calls == [("fake_echo", {"text": "hi"})]

    row = memory_audit.recent(1)[0]
    assert row["outcome"] == "success"
    assert row["tool"] == "fake_echo"
    assert row["agent"] == "assistant"
    assert row["side_effect"] == "read_only"
    assert row["duration_ms"] is not None


@pytest.mark.asyncio
async def test_unknown_tool_is_refused(gateway, pool, memory_audit):
    with pytest.raises(ToolNotRegistered):
        await gateway.call(None, "rm_rf", {}, agent="assistant")

    assert pool.calls == []
    assert memory_audit.recent(1)[0]["denial_reason"] == "tool_not_registered"


@pytest.mark.asyncio
async def test_tool_in_catalog_but_not_in_policy_is_refused(
    gateway, pool, memory_audit
):
    """Discovery finding a tool is not permission to call it."""
    with pytest.raises(ToolNotDeclared):
        await gateway.call(None, "fake_undeclared", {}, agent="assistant")

    assert pool.calls == []
    assert memory_audit.recent(1)[0]["denial_reason"] == "tool_not_declared"


@pytest.mark.asyncio
async def test_agent_without_permission_is_refused(gateway, pool, memory_audit):
    with pytest.raises(Exception) as excinfo:
        await gateway.call(None, "fake_echo", {"text": "hi"}, agent="action-agent")

    assert excinfo.value.reason_code == "agent_not_permitted"
    assert pool.calls == []


@pytest.mark.asyncio
async def test_missing_required_argument_is_caught_before_the_tool_runs(
    gateway, pool, memory_audit
):
    with pytest.raises(InvalidArguments, match="text"):
        await gateway.call(None, "fake_echo", {}, agent="assistant")

    assert pool.calls == []
    assert memory_audit.recent(1)[0]["denial_reason"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_approval_required_tool_is_refused_without_one(gateway, pool):
    with pytest.raises(ApprovalRequired):
        await gateway.call(
            None, "fake_write", {"repo_path": "/tmp/x"}, agent="action-agent"
        )

    assert pool.calls == []


@pytest.mark.asyncio
async def test_matching_approval_lets_the_call_through(gateway, pool):
    arguments = {"repo_path": "/tmp/x"}
    approval = Approval(
        tool="fake_write",
        arguments_hash=hash_arguments(arguments),
        approved_by="lionel",
    )

    await gateway.call(
        None, "fake_write", arguments, agent="action-agent", approval=approval
    )

    assert pool.calls == [("fake_write", arguments)]


@pytest.mark.asyncio
async def test_approval_does_not_carry_to_different_arguments(gateway, pool):
    """Approving one edit must not approve the next one."""
    approval = Approval(
        tool="fake_write",
        arguments_hash=hash_arguments({"repo_path": "/tmp/approved"}),
        approved_by="lionel",
    )

    with pytest.raises(ApprovalRequired):
        await gateway.call(
            None,
            "fake_write",
            {"repo_path": "/tmp/something-else"},
            agent="action-agent",
            approval=approval,
        )

    assert pool.calls == []


@pytest.mark.asyncio
async def test_expired_approval_is_refused(gateway, pool):
    from datetime import datetime, timedelta, timezone

    arguments = {"repo_path": "/tmp/x"}
    approval = Approval(
        tool="fake_write",
        arguments_hash=hash_arguments(arguments),
        approved_by="lionel",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    with pytest.raises(ApprovalRequired):
        await gateway.call(
            None, "fake_write", arguments, agent="action-agent", approval=approval
        )


@pytest.mark.asyncio
async def test_path_outside_the_allowed_roots_is_refused(
    catalog, memory_audit, pool, tmp_path
):
    root = tmp_path / "repos"
    root.mkdir()
    gateway = ToolGateway(
        catalog, audit=memory_audit, pool=pool, repo_root_provider=lambda: [str(root)]
    )

    with pytest.raises(RepositoryPathDenied, match="outside"):
        await gateway.call(
            None, "fake_read", {"repo_path": "/etc"}, agent="assistant"
        )

    assert pool.calls == []
    assert memory_audit.recent(1)[0]["denial_reason"] == "repository_path_denied"


@pytest.mark.asyncio
async def test_path_inside_the_allowed_roots_is_permitted(
    catalog, memory_audit, pool, tmp_path
):
    root = tmp_path / "repos"
    (root / "luma").mkdir(parents=True)
    gateway = ToolGateway(
        catalog, audit=memory_audit, pool=pool, repo_root_provider=lambda: [str(root)]
    )

    await gateway.call(
        None, "fake_read", {"repo_path": str(root / "luma")}, agent="assistant"
    )

    assert pool.calls


@pytest.mark.asyncio
async def test_path_traversal_out_of_an_allowed_root_is_refused(
    catalog, memory_audit, pool, tmp_path
):
    root = tmp_path / "repos"
    root.mkdir()
    gateway = ToolGateway(
        catalog, audit=memory_audit, pool=pool, repo_root_provider=lambda: [str(root)]
    )

    with pytest.raises(RepositoryPathDenied):
        await gateway.call(
            None,
            "fake_read",
            {"repo_path": f"{root}/../../etc"},
            agent="assistant",
        )


@pytest.mark.asyncio
async def test_a_sibling_directory_sharing_a_prefix_is_not_inside_the_root(
    catalog, memory_audit, pool, tmp_path
):
    """/srv/alena-evil must not pass a /srv/alena root check."""
    root = tmp_path / "alena"
    root.mkdir()
    (tmp_path / "alena-evil").mkdir()
    gateway = ToolGateway(
        catalog, audit=memory_audit, pool=pool, repo_root_provider=lambda: [str(root)]
    )

    with pytest.raises(RepositoryPathDenied):
        await gateway.call(
            None,
            "fake_read",
            {"repo_path": str(tmp_path / "alena-evil")},
            agent="assistant",
        )


@pytest.mark.asyncio
async def test_paths_are_unchecked_when_no_roots_are_configured(gateway, pool):
    """Phase 0 ships with no roots set, so behaviour is unchanged."""
    await gateway.call(None, "fake_read", {"repo_path": "/etc"}, agent="assistant")
    assert pool.calls


@pytest.mark.asyncio
async def test_a_failing_tool_is_logged_as_an_error_and_reraised(
    catalog, memory_audit
):
    pool = FakePool(error=RuntimeError("boom"))
    gateway = ToolGateway(catalog, audit=memory_audit, pool=pool)

    with pytest.raises(RuntimeError, match="boom"):
        await gateway.call(None, "fake_echo", {"text": "hi"}, agent="assistant")

    row = memory_audit.recent(1)[0]
    assert row["outcome"] == "error"
    assert "boom" in row["error"]


@pytest.mark.asyncio
async def test_every_attempt_is_logged_once(gateway, memory_audit):
    await gateway.call(None, "fake_echo", {"text": "a"}, agent="assistant")
    with pytest.raises(ToolNotRegistered):
        await gateway.call(None, "nope", {}, agent="assistant")

    assert memory_audit.count() == 2
    assert memory_audit.count("success") == 1
    assert memory_audit.count("denied") == 1
