"""The executor must go through the gateway.

The previous safety layer was written, tested, and never called. These tests
exist so that cannot quietly happen again: they assert the call path, not just
that the gateway works when invoked directly.
"""

import pytest

from modules.core.controller import tool_executor
from modules.gateway.catalog import ToolCatalog
from modules.gateway.contracts import ToolContract
from modules.gateway.errors import ToolNotDeclared
from modules.gateway.gateway import ToolGateway
from modules.gateway.policy import parse_policy
from modules.gateway import set_gateway


class RecordingPool:
    def __init__(self):
        self.calls = []

    async def call_tool(self, server, tool, arguments):
        self.calls.append((tool, arguments))
        return "result"


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setenv("ALENA_DB_PATH", str(tmp_path / "test.db"))
    from modules.store import db

    db.reset_connection()

    catalog = ToolCatalog(
        parse_policy(
            {
                "version": 1,
                "tools": {
                    "codex_analyze": {
                        "side_effect": "read_only",
                        "allowed_agents": ["assistant"],
                    }
                },
            }
        )
    )
    catalog.register(
        [
            ToolContract(
                name="codex_analyze",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo_path": {"type": "string"},
                        "question": {"type": "string"},
                    },
                    "required": ["repo_path", "question"],
                },
            ),
            ToolContract(name="codex_edit"),
        ]
    )
    pool = RecordingPool()
    set_gateway(ToolGateway(catalog, pool=pool))
    yield pool
    set_gateway(None)
    db.reset_connection()


@pytest.mark.asyncio
async def test_execute_tool_goes_through_the_gateway(wired):
    result = await tool_executor.execute_tool(
        None, "codex_analyze", {"repo_path": "/tmp", "question": "what"}
    )

    assert result == "result"
    assert wired.calls == [("codex_analyze", {"repo_path": "/tmp", "question": "what"})]


@pytest.mark.asyncio
async def test_a_policy_refusal_stops_the_executor(wired):
    """A tool the policy has not declared never reaches the MCP server."""
    with pytest.raises(ToolNotDeclared):
        await tool_executor.execute_tool(None, "codex_edit", {})

    assert wired.calls == []


@pytest.mark.asyncio
async def test_the_orchestrator_can_call_as_another_agent(wired):
    from modules.gateway.errors import GatewayDenied

    with pytest.raises(GatewayDenied) as excinfo:
        await tool_executor.execute_tool(
            None,
            "codex_analyze",
            {"repo_path": "/tmp", "question": "what"},
            agent="action-agent",
        )

    assert excinfo.value.reason_code == "agent_not_permitted"


def test_the_gateway_is_on_by_default(monkeypatch):
    monkeypatch.delenv("ALENA_GATEWAY_ENABLED", raising=False)
    assert tool_executor.gateway_enabled()


def test_the_escape_hatch_bypasses_it(monkeypatch):
    monkeypatch.setenv("ALENA_GATEWAY_ENABLED", "0")
    assert not tool_executor.gateway_enabled()


@pytest.mark.asyncio
async def test_a_refusal_reaches_the_user_as_text(wired, monkeypatch):
    """A denied tool must not surface as a traceback in the CLI or the API."""
    import json

    from modules.core.controller.agent import run_agent
    from modules.core.controller.memory import ConversationMemory

    # The planner asks for a tool the policy has not declared.
    monkeypatch.setattr(
        "modules.core.controller.agent.ask_llm",
        lambda _: json.dumps({"tool": "codex_edit", "arguments": {}}),
    )

    outputs = []
    answer = await run_agent(
        "edit the repo",
        memory=ConversationMemory(),
        output_sink=outputs.append,
        return_output=True,
    )

    assert answer is not None
    assert "cannot complete this request" in answer
    assert wired.calls == [], "a refused tool still reached the MCP server"
