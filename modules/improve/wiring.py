"""Wire the repository registry into the Tool Gateway.

This is the registry finally answering the question `safety.py` tried to
answer with a hardcoded list: the roots a tool's path argument may point at
are the declared workspaces, and nothing else.
"""

from __future__ import annotations

from typing import Optional

from modules.gateway import ToolGateway, set_gateway
from modules.gateway.catalog import ToolCatalog, static_contracts
from modules.gateway.policy import load_policy

from .registry import RepositoryRegistry


def build_gateway(
    registry: RepositoryRegistry, policy_path: Optional[str] = None
) -> ToolGateway:
    catalog = ToolCatalog(load_policy(policy_path))
    catalog.register(static_contracts())
    return ToolGateway(catalog, repo_root_provider=registry.workspaces)


def install_gateway(
    registry: RepositoryRegistry, policy_path: Optional[str] = None
) -> ToolGateway:
    """Make the registry-bound gateway the process-wide one."""
    gateway = build_gateway(registry, policy_path)
    set_gateway(gateway)
    return gateway
