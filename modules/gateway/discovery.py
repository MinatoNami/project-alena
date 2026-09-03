"""Derive tool contracts from MCP `tools/list`.

The Tool Interoperability Standard makes the MCP definition the canonical
contract: the server that implements a tool is the thing that knows its real
schema. Anything ALENA maintains by hand alongside it is a second source of
truth that will drift.

What MCP does *not* carry is a side-effect classification. The annotations a
server may attach (`readOnlyHint`, `destructiveHint`) are hints from the tool
author, so they are used only to guess, and only ever upward -- see
side_effect_hint.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .contracts import SideEffect, ToolContract
from .pool import MCPSessionPool, get_pool


def side_effect_hint(annotations: Any) -> Optional[SideEffect]:
    """Best guess at a tool's impact from its MCP annotations.

    Only ever a hint. A server declaring itself read-only is the tool author's
    claim about their own tool, which is exactly the sort of thing a policy
    boundary exists not to take on faith -- so the guess is never used to
    *lower* a classification the policy file has made, only to fill a gap and
    to flag disagreement.
    """
    if annotations is None:
        return None
    if getattr(annotations, "destructiveHint", None) is True:
        return SideEffect.DESTRUCTIVE
    if getattr(annotations, "readOnlyHint", None) is True:
        return SideEffect.READ_ONLY
    return None


def contract_from_mcp_tool(tool: Any, mcp_server: Optional[str] = None) -> ToolContract:
    """Map one `mcp.types.Tool` onto a ToolContract."""
    return ToolContract(
        name=tool.name,
        description=(getattr(tool, "description", None) or "").strip(),
        input_schema=dict(getattr(tool, "inputSchema", None) or {}),
        output_schema=(
            dict(tool.outputSchema) if getattr(tool, "outputSchema", None) else None
        ),
        mcp_server=mcp_server,
        source="mcp",
        side_effect_hint=side_effect_hint(getattr(tool, "annotations", None)),
    )


async def discover(
    server: Any,
    mcp_server: Optional[str] = None,
    pool: Optional[MCPSessionPool] = None,
) -> List[ToolContract]:
    """List one MCP server's tools as contracts."""
    pool = pool or get_pool()
    result = await pool.list_tools(server)
    tools = getattr(result, "tools", None) or []
    return [contract_from_mcp_tool(tool, mcp_server) for tool in tools]
