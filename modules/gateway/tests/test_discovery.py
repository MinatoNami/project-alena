import pytest

from mcp.types import Tool, ToolAnnotations

from modules.gateway.contracts import SideEffect
from modules.gateway.discovery import (
    contract_from_mcp_tool,
    discover,
    side_effect_hint,
)
from modules.gateway.pool import MCPSessionPool


def test_contract_carries_the_mcp_schema():
    tool = Tool(
        name="dependency.outdated",
        description="  Find outdated dependencies.  ",
        inputSchema={
            "type": "object",
            "properties": {"repository_id": {"type": "string"}},
            "required": ["repository_id"],
        },
        outputSchema={"type": "object", "properties": {"dependencies": {}}},
    )

    contract = contract_from_mcp_tool(tool, mcp_server="alena-dev")

    assert contract.name == "dependency.outdated"
    assert contract.description == "Find outdated dependencies."
    assert contract.required_arguments() == ["repository_id"]
    assert contract.output_schema is not None
    assert contract.mcp_server == "alena-dev"
    assert contract.source == "mcp"


def test_annotations_only_ever_hint():
    assert side_effect_hint(None) is None
    assert side_effect_hint(ToolAnnotations()) is None
    assert side_effect_hint(ToolAnnotations(readOnlyHint=True)) is SideEffect.READ_ONLY
    assert (
        side_effect_hint(ToolAnnotations(destructiveHint=True))
        is SideEffect.DESTRUCTIVE
    )


def test_destructive_wins_over_read_only():
    """A tool claiming both gets the more cautious reading."""
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=True)
    assert side_effect_hint(annotations) is SideEffect.DESTRUCTIVE


@pytest.mark.asyncio
async def test_discovery_lists_a_real_servers_tools(fake_server):
    pool = MCPSessionPool()
    try:
        contracts = await discover(fake_server, mcp_server="fake", pool=pool)
    finally:
        await pool.aclose()

    by_name = {c.name: c for c in contracts}
    assert {"fake_echo", "fake_pid", "fake_boom", "fake_read"} <= set(by_name)
    assert by_name["fake_echo"].required_arguments() == ["text"]
    assert by_name["fake_echo"].source == "mcp"
