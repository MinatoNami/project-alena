"""What the local model is offered, and where its call is then sent.

The planner used to be handed a hand-maintained list that discovery could not
reach. A tool could be implemented, discovered, declared in the policy and
callable through the gateway, and still be invisible to the model that was
supposed to use it -- which is how alena-core shipped eight tools that ALENA's
own planner could not see.
"""

import pytest

from modules.core.controller import agent, llm_client
from modules.gateway import set_gateway
from modules.gateway.catalog import ToolCatalog, static_contracts
from modules.gateway.contracts import ToolContract
from modules.gateway.gateway import ToolGateway
from modules.gateway.policy import parse_policy

POLICY = {
    "version": 1,
    "tools": {
        "codex_edit": {
            "side_effect": "repository_write",
            "allowed_agents": ["assistant", "action-agent"],
        },
        "repo.search": {"side_effect": "read_only", "allowed_agents": ["*"]},
        "google_list_events": {
            "side_effect": "read_only",
            "allowed_agents": ["assistant"],
        },
    },
}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A gateway holding one discovered tool alongside the static ones."""
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "test.db"))
    from modules.store import db

    db.reset_connection()

    catalog = ToolCatalog(parse_policy(POLICY))
    catalog.register(static_contracts())
    catalog.register(
        [
            ToolContract(
                name="repo.search",
                description="Search a repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repository_id": {"type": "string"},
                        "pattern": {"type": "string"},
                    },
                    "required": ["repository_id", "pattern"],
                },
                mcp_server="alena-core",
                source="mcp",
            )
        ]
    )
    set_gateway(ToolGateway(catalog))
    yield catalog
    set_gateway(None)
    db.reset_connection()


def names(agent_name):
    return [t["function"]["name"] for t in llm_client.planner_tools(agent_name)[0]]


def test_a_discovered_tool_is_offered_to_the_planner(wired):
    assert "repo.search" in names("assistant")
    assert "- repo.search(repository_id: string, pattern: string)" in (
        llm_client.planner_tools("assistant")[1]
    )


def test_the_planner_is_not_offered_what_its_agent_may_not_call(wired):
    """The array and the policy have to be filtered by the same identity.

    Showing the action agent a calendar tool it will be refused for calling
    costs a turn and reads to the model as a failure worth retrying.
    """
    assert names("action-agent") == ["codex_edit", "repo.search"]
    assert "google_list_events" in names("assistant")


def test_a_broken_catalog_falls_back_to_the_static_tools(monkeypatch):
    """A policy file that will not load should cost tools, not the assistant."""

    def boom():
        raise RuntimeError("policy is malformed")

    monkeypatch.setattr(llm_client, "get_gateway", boom)

    from modules.core.controller.tool_definitions import get_all_tool_names

    assert names("assistant") == get_all_tool_names()


def test_a_discovered_tool_is_routed_to_its_own_server(wired):
    """Not to codex, which is where the static fallback sends anything unknown."""
    assert agent._get_server_for_tool("repo.search").cwd.endswith("mcp/alena-core")
    assert agent._get_server_for_tool("codex_edit").cwd.endswith("mcp/codex-server")


def test_a_discovered_tool_survives_the_capability_gate(wired):
    """MCP carries no capability vocabulary, so a missing entry proves nothing.

    Judging a discovered tool by a table that describes only the static ones
    refuses every alena-core tool before the gateway ever sees it.
    """
    assert agent._tool_can_handle("repo.search", {"edit_files"})
    assert not agent._tool_can_handle("google_list_events", {"edit_files"})
    assert not agent._tool_can_handle("not_a_tool", {"edit_files"})


def test_a_capability_refusal_is_recorded_like_any_other_denial(wired):
    """The heuristic used to be the one refusal nothing counted.

    Every gateway denial lands in the audit log with a reason code, which is
    what `alena-improve tools` reads. This one sits in front of the gateway
    and refused silently, so whether it has ever prevented a real mistake was
    unanswerable.
    """
    from modules.gateway import get_gateway

    assert not agent._tool_can_handle(
        "google_list_events", {"edit_files"}, {"calendar_id": "primary"}
    )

    row = get_gateway().audit.recent(limit=1)[0]
    assert row["tool"] == "google_list_events"
    assert row["outcome"] == "denied"
    assert row["denial_reason"] == "capability_heuristic:edit_files"


def test_an_allowed_tool_records_nothing(wired):
    from modules.gateway import get_gateway

    assert agent._tool_can_handle("repo.search", {"edit_files"})

    assert get_gateway().audit.recent(limit=1) == []
