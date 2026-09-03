"""A grant is how a human decision becomes write permission for one run.

Most of this is about what a grant cannot do.
"""

from datetime import datetime, timedelta, timezone

import pytest

from modules.gateway.catalog import ToolCatalog
from modules.gateway.contracts import SideEffect, ToolContract
from modules.gateway.errors import ApprovalRequired
from modules.gateway.gateway import ToolGateway
from modules.gateway.grants import (
    MAX_GRANTED_SIDE_EFFECT,
    ActionGrant,
    GrantBook,
)
from modules.gateway.policy import parse_policy


def grant(**overrides) -> ActionGrant:
    base = dict(repository_id="luma-index", agent="action-agent", authority="recommendation:3")
    base.update(overrides)
    return ActionGrant(**base)


# -- the ceiling -----------------------------------------------------------


def test_a_grant_cannot_authorise_more_than_a_repository_write():
    """Pushing and pull requests leave the machine; they need their own act."""
    with pytest.raises(ValueError, match="remote_write"):
        grant(max_side_effect=SideEffect.REMOTE_WRITE)


def test_a_grant_cannot_authorise_something_destructive():
    with pytest.raises(ValueError, match="destructive"):
        grant(max_side_effect=SideEffect.DESTRUCTIVE)


def test_the_ceiling_is_repository_write():
    assert MAX_GRANTED_SIDE_EFFECT is SideEffect.REPOSITORY_WRITE


def test_a_grant_does_not_cover_a_side_effect_above_its_cap():
    assert not grant().covers("action-agent", "luma-index", SideEffect.REMOTE_WRITE)


def test_a_grant_covers_a_repository_write():
    assert grant().covers("action-agent", "luma-index", SideEffect.REPOSITORY_WRITE)


def test_a_grant_does_not_cover_an_unclassified_tool():
    """A standing grant should not wave through something nobody classified."""
    assert not grant().covers("action-agent", "luma-index", None)


# -- scope -----------------------------------------------------------------


def test_a_grant_is_scoped_to_one_repository():
    assert not grant().covers("action-agent", "athena", SideEffect.REPOSITORY_WRITE)


def test_a_grant_is_scoped_to_one_agent():
    assert not grant().covers("assistant", "luma-index", SideEffect.REPOSITORY_WRITE)


def test_a_grant_expires():
    expired = grant(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert not expired.active()
    assert not expired.covers("action-agent", "luma-index", SideEffect.REPOSITORY_WRITE)


def test_a_grant_for_a_recommendation_records_its_authority():
    issued = ActionGrant.for_recommendation("luma-index", "action-agent", 7)
    assert issued.authority == "recommendation:7"
    assert issued.active()


# -- the book --------------------------------------------------------------


def test_a_grant_is_dropped_when_the_run_ends():
    book = GrantBook()
    with book.granted(grant()):
        assert book.find("action-agent", "luma-index", SideEffect.REPOSITORY_WRITE)
    assert book.grants == []


def test_a_grant_is_dropped_even_when_the_run_raises():
    """A grant that outlives its run is a standing write permission."""
    book = GrantBook()
    with pytest.raises(RuntimeError):
        with book.granted(grant()):
            raise RuntimeError("the implementation failed")
    assert book.grants == []


def test_an_empty_book_grants_nothing():
    assert GrantBook().find("action-agent", "luma-index", SideEffect.REPOSITORY_WRITE) is None


# -- through the gateway ---------------------------------------------------


WRITE = ToolContract(
    name="codex_edit",
    input_schema={"type": "object", "properties": {}, "required": []},
    mcp_server="codex",
)

POLICY = {
    "version": 1,
    "tools": {
        "codex_edit": {
            "side_effect": "repository_write",
            "allowed_agents": ["assistant", "action-agent"],
            "requires_approval": ["action-agent"],
        }
    },
}


class Pool:
    def __init__(self):
        self.calls = []

    async def call_tool(self, server, tool, arguments):
        self.calls.append(tool)
        return "ok"


def build(book):
    catalog = ToolCatalog(parse_policy(POLICY))
    catalog.register([WRITE])
    pool = Pool()
    return ToolGateway(catalog, pool=pool, grants=book), pool


@pytest.mark.asyncio
async def test_the_action_agent_is_refused_without_a_grant():
    gateway, pool = build(GrantBook())

    with pytest.raises(ApprovalRequired):
        await gateway.call(None, "codex_edit", {}, agent="action-agent", repository_id="luma-index")

    assert pool.calls == []


@pytest.mark.asyncio
async def test_a_grant_satisfies_the_approval_requirement():
    book = GrantBook()
    gateway, pool = build(book)

    with book.granted(grant()):
        await gateway.call(
            None, "codex_edit", {}, agent="action-agent", repository_id="luma-index"
        )

    assert pool.calls == ["codex_edit"]


@pytest.mark.asyncio
async def test_a_grant_for_another_repository_does_not_help():
    book = GrantBook()
    gateway, pool = build(book)

    with book.granted(grant(repository_id="athena")):
        with pytest.raises(ApprovalRequired):
            await gateway.call(
                None, "codex_edit", {}, agent="action-agent", repository_id="luma-index"
            )

    assert pool.calls == []


@pytest.mark.asyncio
async def test_a_grant_does_not_let_an_unpermitted_agent_in():
    """A grant satisfies approval; it never adds a tool policy would refuse."""
    book = GrantBook()
    catalog = ToolCatalog(parse_policy(POLICY))
    catalog.register([WRITE])
    pool = Pool()
    gateway = ToolGateway(catalog, pool=pool, grants=book)

    with book.granted(grant(agent="codex")):
        with pytest.raises(Exception) as excinfo:
            await gateway.call(
                None, "codex_edit", {}, agent="codex", repository_id="luma-index"
            )

    assert excinfo.value.reason_code == "agent_not_permitted"
    assert pool.calls == []


@pytest.mark.asyncio
async def test_the_assistant_is_unaffected_by_the_action_agents_approval():
    """A user asking the assistant to edit a file is the approval."""
    gateway, pool = build(GrantBook())

    await gateway.call(None, "codex_edit", {}, agent="assistant", repository_id="luma-index")

    assert pool.calls == ["codex_edit"]
