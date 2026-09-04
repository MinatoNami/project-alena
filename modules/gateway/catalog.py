"""The tool catalog: contracts plus the policy that governs them.

Two providers feed it.

* **MCP discovery** is canonical, per the interoperability standard, and is
  what every new tool uses.
* **The static provider** wraps the hand-maintained tool_definitions.py so the
  assistant keeps working while discovery is proven against the existing
  servers. It is a migration shim. Nothing new should be added to it; it goes
  away once discovery covers codex and google-calendar, and the catalog is
  then fed by discovery alone.

An entry is only callable if policy declares it. Discovery finding a tool is
not permission to use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .contracts import SideEffect, ToolContract
from .policy import Policy, ToolPolicy


@dataclass(frozen=True)
class CatalogEntry:
    contract: ToolContract
    policy: Optional[ToolPolicy]

    @property
    def name(self) -> str:
        return self.contract.name

    @property
    def declared(self) -> bool:
        return self.policy is not None

    @property
    def side_effect(self) -> Optional[SideEffect]:
        return self.policy.side_effect if self.policy else None


def static_contracts() -> List[ToolContract]:
    """Contracts from the legacy hand-written definitions.

    Migration shim -- see the module docstring.
    """
    from modules.core.controller.tool_definitions import TOOL_DEFINITIONS

    contracts: List[ToolContract] = []
    for definition in TOOL_DEFINITIONS:
        rendered = definition.to_openai_tool()["function"]
        contracts.append(
            ToolContract(
                name=definition.name,
                description=definition.description,
                input_schema=rendered["parameters"],
                mcp_server=definition.mcp_server,
                source="static",
            )
        )
    return contracts


class ToolCatalog:
    def __init__(self, policy: Policy):
        self._policy = policy
        self._contracts: Dict[str, ToolContract] = {}
        # True once MCP discovery has actually reached a server. The assistant
        # checks it to decide whether to spend a subprocess on discovery again,
        # so a failed attempt must leave it False -- one unlucky start should
        # not silently cost the planner half its tools for the process's life.
        self.discovered = False

    @property
    def policy(self) -> Policy:
        return self._policy

    def register(self, contracts: Iterable[ToolContract]) -> None:
        """Add contracts. A discovered contract replaces a static one.

        Discovery is canonical, so when both providers describe the same tool
        the MCP definition wins regardless of registration order.
        """
        for contract in contracts:
            existing = self._contracts.get(contract.name)
            if existing is not None and existing.source == "mcp" and contract.source != "mcp":
                continue
            self._contracts[contract.name] = contract

    def get(self, name: str) -> Optional[CatalogEntry]:
        contract = self._contracts.get(name)
        if contract is None:
            return None
        return CatalogEntry(contract=contract, policy=self._policy.tool(name))

    def names(self) -> List[str]:
        return sorted(self._contracts)

    def undeclared(self) -> List[str]:
        """Discovered tools with no policy entry -- these cannot be called."""
        return sorted(
            name for name in self._contracts if self._policy.tool(name) is None
        )

    def unimplemented(self) -> List[str]:
        """Policy entries with no contract behind them -- stale policy."""
        return sorted(
            name for name in self._policy.tools if name not in self._contracts
        )

    def disagreements(self) -> List[tuple[str, SideEffect, SideEffect]]:
        """Tools whose server claims a worse side effect than policy declares.

        A server that starts reporting `destructiveHint` on a tool the policy
        has classified as read-only has changed under us. The hint never wins
        -- policy decides -- but silently ignoring the disagreement is how a
        classification goes stale.
        """
        found = []
        for name, contract in self._contracts.items():
            hint = contract.side_effect_hint
            declared = self._policy.tool(name)
            if hint is None or declared is None:
                continue
            if hint.rank > declared.side_effect.rank:
                found.append((name, declared.side_effect, hint))
        return sorted(found)

    def openai_tools(self, agent: str) -> List[Dict[str, Any]]:
        """The `tools` array for LM Studio, filtered to what `agent` may call.

        A planner should not be shown tools it will be refused for calling.
        """
        return [
            self._contracts[name].to_openai_tool() for name in self.callable_by(agent)
        ]

    def callable_by(self, agent: str) -> List[str]:
        """The tools `agent` is permitted to call, in catalog order."""
        return [
            name
            for name in self.names()
            if (policy := self._policy.tool(name)) is not None
            and policy.permits_agent(agent)
        ]

    def system_prompt_section(self, agent: str) -> str:
        """The prompt's tool list, matching what `openai_tools` will offer.

        Native tool calling makes this redundant in principle, but local models
        lean on the prompt heavily, and a prompt that lists a different set from
        the `tools` array teaches the model to ask for tools it will be refused.
        """
        lines = ["Available tools:"]
        for name in self.callable_by(agent):
            contract = self._contracts[name]
            properties = (contract.input_schema or {}).get("properties", {}) or {}
            required = set(contract.required_arguments())
            args = [
                f"{arg}{'' if arg in required else '?'}: "
                f"{schema.get('type', 'any') if isinstance(schema, dict) else 'any'}"
                for arg, schema in properties.items()
            ]
            lines.append(f"- {name}({', '.join(args)})")
        return "\n".join(lines)


# The MCP servers ALENA can discover tools from, as (key, folder) pairs. The
# legacy servers are still described by tool_definitions.py; alena-core is
# discovered, which is the direction everything moves in.
DISCOVERABLE_SERVERS = (("alena-core", "alena-core"),)


def server_parameters(folder: str):
    """Stdio parameters for one of ALENA's own MCP servers."""
    import os
    import sys

    from mcp import StdioServerParameters

    root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "mcp", folder)
    )
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.main"], cwd=root, env={**os.environ}
    )


async def discover_into(catalog: "ToolCatalog", pool=None) -> List[str]:
    """Register every discoverable server's tools, MCP-first.

    Discovery is the canonical source for these; the static provider covers
    only the legacy servers. A server that fails to start is logged and
    skipped, because one broken server should not take the catalog with it.
    """
    from modules.core.controller.logger import logger

    from .discovery import discover

    found: List[str] = []
    for key, folder in DISCOVERABLE_SERVERS:
        try:
            contracts = await discover(server_parameters(folder), key, pool)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not discover tools from {key}: {exc!r}")
            continue
        catalog.register(contracts)
        found.extend(c.name for c in contracts)
    if found:
        catalog.discovered = True
    return found
