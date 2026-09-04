"""The Tool Gateway.

Agents do not invoke tools. They ask the gateway, which answers the questions
the architecture addendum lists -- is the tool registered, is the agent
allowed, is the repository allowed, are the permissions granted, does a human
have to agree -- logs the attempt, and only then calls the tool.

This is the one security boundary in the system, so it has to be *on* the call
path. The previous safety layer (safety.check_repo_path, validate_tool_call)
was written, tested, and then never called from the agent loop; the way that
does not happen again is for the executor itself to go through here.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from modules.core.controller.logger import logger

from .audit import AuditLog, hash_arguments
from .catalog import CatalogEntry, ToolCatalog
from .contracts import SideEffect
from .grants import ActionGrant, GrantBook
from .errors import (
    ApprovalRequired,
    GatewayDenied,
    InvalidArguments,
    RepositoryPathDenied,
    ToolNotDeclared,
    ToolNotRegistered,
)
from .pool import MCPSessionPool, get_pool

# Argument names that carry a filesystem path, in the order they are checked.
_PATH_ARGUMENTS = ("repo_path", "workspace", "cwd", "path")


@dataclass(frozen=True)
class Approval:
    """A human's agreement to one specific call.

    Bound to the exact arguments, so approving "edit repo X to do Y" does not
    also approve "edit repo X to do Z".
    """

    tool: str
    arguments_hash: str
    approved_by: str
    repository_id: Optional[str] = None
    expires_at: Optional[datetime] = None

    def valid_now(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now(timezone.utc) < self.expires_at

    def matches(
        self, tool: str, arguments_hash: str, repository_id: Optional[str]
    ) -> bool:
        return (
            self.tool == tool
            and self.arguments_hash == arguments_hash
            and self.repository_id == repository_id
            and self.valid_now()
        )


def allowed_repo_roots() -> List[str]:
    """Roots that path arguments must stay inside, from the environment.

    Empty means unconfigured, and the path check is skipped. Phase 1 replaces
    this with the repository registry, whose `workspace.path` per repository is
    the real answer; the environment variable is the interim.
    """
    raw = os.getenv("ALENA_ALLOWED_REPO_ROOTS", "").strip()
    if not raw:
        return []
    separator = ":" if ":" in raw and "," not in raw else ","
    return [
        os.path.abspath(os.path.expanduser(part.strip()))
        for part in raw.split(separator)
        if part.strip()
    ]


class ToolGateway:
    def __init__(
        self,
        catalog: ToolCatalog,
        *,
        audit: Optional[AuditLog] = None,
        pool: Optional[MCPSessionPool] = None,
        repo_root_provider: Optional[Callable[[], List[str]]] = None,
        grants: Optional[GrantBook] = None,
    ):
        self._catalog = catalog
        self._audit = audit if audit is not None else AuditLog()
        self._pool = pool
        self._repo_roots = repo_root_provider or allowed_repo_roots
        self._grants = grants if grants is not None else GrantBook()

    @property
    def catalog(self) -> ToolCatalog:
        return self._catalog

    @property
    def audit(self) -> AuditLog:
        """The audit log, for a caller that refuses before reaching `call`."""
        return self._audit

    @property
    def grants(self) -> GrantBook:
        """Write grants currently in force. Empty is the normal state."""
        return self._grants

    @property
    def pool(self) -> MCPSessionPool:
        if self._pool is None:
            self._pool = get_pool()
        return self._pool

    # -- checks ------------------------------------------------------------

    def _resolve(self, tool: str) -> CatalogEntry:
        entry = self._catalog.get(tool)
        if entry is None:
            raise ToolNotRegistered(
                f"{tool} is not in the tool catalog. Known tools: "
                f"{', '.join(self._catalog.names()) or '(none)'}"
            )
        if not entry.declared:
            raise ToolNotDeclared(
                f"{tool} exists but is not declared in the tool policy, so it "
                "cannot be called. Declare it with a side_effect first."
            )
        return entry

    def _check_paths(self, tool: str, arguments: Dict[str, Any]) -> None:
        roots = self._repo_roots()
        if not roots:
            return
        for key in _PATH_ARGUMENTS:
            value = arguments.get(key)
            if not isinstance(value, str) or not value:
                continue
            resolved = os.path.abspath(os.path.expanduser(value))
            if not any(
                resolved == root or resolved.startswith(root + os.sep)
                for root in roots
            ):
                raise RepositoryPathDenied(
                    f"{tool} was given {key}={value!r}, which resolves outside "
                    f"the allowed roots: {', '.join(roots)}"
                )

    # -- the call path -----------------------------------------------------

    async def call(
        self,
        server: Any,
        tool: str,
        arguments: Dict[str, Any],
        *,
        agent: str = "assistant",
        repository_id: Optional[str] = None,
        approval: Optional[Approval] = None,
    ) -> Any:
        arguments = arguments if isinstance(arguments, dict) else {}
        args_hash = hash_arguments(arguments)
        side_effect: Optional[SideEffect] = None
        mcp_server: Optional[str] = None
        version: Optional[str] = None

        def deny(exc: GatewayDenied) -> GatewayDenied:
            self._audit.record(
                tool=tool,
                agent=agent,
                outcome="denied",
                arguments=arguments,
                tool_version=version,
                mcp_server=mcp_server,
                repository_id=repository_id,
                side_effect=side_effect.value if side_effect else None,
                denial_reason=exc.reason_code,
                error=str(exc),
            )
            logger.warning(f"GATEWAY_DENIED: {tool} ({exc.reason_code}) - {exc}")
            return exc

        try:
            entry = self._resolve(tool)
        except GatewayDenied as exc:
            raise deny(exc) from None

        side_effect = entry.side_effect
        mcp_server = entry.contract.mcp_server
        version = entry.contract.version

        try:
            entry.contract.validate_arguments(arguments)
        except ValueError as exc:
            raise deny(InvalidArguments(str(exc))) from None

        decision = self._catalog.policy.evaluate(tool, agent, repository_id)
        if not decision.allowed:
            raise deny(
                GatewayDenied(decision.detail or "refused", decision.reason_code)
            ) from None

        try:
            self._check_paths(tool, arguments)
        except GatewayDenied as exc:
            raise deny(exc) from None

        granted: Optional[ActionGrant] = None
        if decision.requires_approval:
            approved = approval is not None and approval.matches(
                tool, args_hash, repository_id
            )
            if not approved:
                granted = self._grants.find(agent, repository_id, side_effect)
            if not approved and granted is None:
                raise deny(
                    ApprovalRequired(
                        f"{tool} requires approval from {agent} "
                        f"(side effect: "
                        f"{side_effect.value if side_effect else 'unknown'}). "
                        "Accept the recommendation it implements, or supply an "
                        "explicit approval."
                    )
                ) from None
            if granted is not None:
                logger.info(f"GATEWAY_GRANT: {tool} under {granted.describe()}")

        started = time.perf_counter()
        try:
            result = await self.pool.call_tool(server, tool, arguments)
        except Exception as exc:
            self._audit.record(
                tool=tool,
                agent=agent,
                outcome="error",
                arguments=arguments,
                tool_version=version,
                mcp_server=mcp_server,
                repository_id=repository_id,
                side_effect=side_effect.value if side_effect else None,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        self._audit.record(
            tool=tool,
            agent=agent,
            outcome="success",
            arguments=arguments,
            tool_version=version,
            mcp_server=mcp_server,
            repository_id=repository_id,
            side_effect=side_effect.value if side_effect else None,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return result


_gateway: Optional[ToolGateway] = None


def get_gateway() -> ToolGateway:
    """The process-wide gateway, built on first use."""
    global _gateway
    if _gateway is None:
        from .catalog import ToolCatalog, static_contracts
        from .policy import load_policy

        catalog = ToolCatalog(load_policy())
        catalog.register(static_contracts())
        _gateway = ToolGateway(catalog)
    return _gateway


def set_gateway(gateway: Optional[ToolGateway]) -> None:
    """Replace the process-wide gateway. For tests and for the orchestrator."""
    global _gateway
    _gateway = gateway


async def ensure_discovered(gateway: Optional[ToolGateway] = None) -> List[str]:
    """Fill the catalog from MCP discovery, once per catalog.

    `get_gateway()` can only build a catalog synchronously, so it registers the
    static contracts and stops there. Discovery needs a running loop and a
    subprocess, which makes it the caller's job -- and the caller is whoever is
    about to plan a turn.

    Returns the names discovered, or an empty list when the catalog already has
    them. A server that will not start is logged by `discover_into` and leaves
    the catalog unmarked, so the next turn tries again.
    """
    from .catalog import discover_into

    gateway = gateway or get_gateway()
    if gateway.catalog.discovered:
        return []
    return await discover_into(gateway.catalog)
