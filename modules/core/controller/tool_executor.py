"""Tool execution for the assistant, routed through the Tool Gateway.

This used to open a `stdio_client` per call, which spawned a process and redid
the MCP handshake every time, and which no policy check stood in front of. It
now goes through the gateway: the tool is looked up in the catalog, the policy
decides, the attempt is logged, and a pooled session runs it.

`ALENA_GATEWAY_ENABLED=0` restores the direct path. It exists so a gateway
misconfiguration cannot leave the assistant unusable, and it should go away
once the gateway has run for a release.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from modules.core.controller.logger import logger


def gateway_enabled() -> bool:
    return os.getenv("ALENA_GATEWAY_ENABLED", "1") != "0"


async def _execute_direct(server, tool: str, arguments: dict):
    """The original path: one subprocess and one handshake per call."""
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool, arguments)


async def execute_tool(
    server,
    tool: str,
    arguments: Dict[str, Any],
    *,
    agent: str = "assistant",
    repository_id: Optional[str] = None,
    approval: Optional[Any] = None,
):
    """Run one tool call on behalf of `agent`.

    The signature the agent loop and its tests already use is unchanged; the
    keyword arguments are what the orchestrator passes when it calls the same
    tools as a different agent against a declared repository.
    """
    if not gateway_enabled():
        logger.warning("ALENA_GATEWAY_ENABLED=0: tool call bypassing the gateway")
        return await _execute_direct(server, tool, arguments)

    from modules.gateway import get_gateway

    return await get_gateway().call(
        server,
        tool,
        arguments,
        agent=agent,
        repository_id=repository_id,
        approval=approval,
    )
