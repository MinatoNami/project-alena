"""The ALENA Tool Gateway.

Agents ask the gateway for a tool; the gateway decides whether they may have
it, records the attempt, and runs it. MCP describes what a tool is, the policy
file describes who may call it, and the two stay separate on purpose.
"""

from .contracts import SideEffect, ToolContract
from .catalog import CatalogEntry, ToolCatalog, static_contracts
from .errors import (
    ApprovalRequired,
    GatewayDenied,
    GatewayError,
    InvalidArguments,
    RepositoryPathDenied,
    ToolNotDeclared,
    ToolNotRegistered,
)
from .gateway import Approval, ToolGateway, get_gateway, set_gateway
from .grants import MAX_GRANTED_SIDE_EFFECT, ActionGrant, GrantBook
from .policy import Policy, PolicyError, load_policy, parse_policy
from .pool import MCPSessionPool, close_pool, get_pool

__all__ = [
    "ActionGrant",
    "Approval",
    "ApprovalRequired",
    "CatalogEntry",
    "GatewayDenied",
    "GatewayError",
    "GrantBook",
    "MAX_GRANTED_SIDE_EFFECT",
    "InvalidArguments",
    "MCPSessionPool",
    "Policy",
    "PolicyError",
    "RepositoryPathDenied",
    "SideEffect",
    "ToolCatalog",
    "ToolContract",
    "ToolGateway",
    "ToolNotDeclared",
    "ToolNotRegistered",
    "close_pool",
    "get_gateway",
    "get_pool",
    "load_policy",
    "parse_policy",
    "set_gateway",
    "static_contracts",
]
