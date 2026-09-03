"""The repository registry model.

The registry is the authoritative answer to where a repository lives, which
branch is authoritative, and what agents may do to it. Agents are never handed
a filesystem path they chose themselves; they are handed a resolved workspace
from here.

Capabilities default asymmetrically on purpose. The read-shaped ones default
to true because a repository listed in the registry is one you want looked at.
The write-shaped ones default to false, and `merge` has no way to become true
by omission, because the cost of guessing wrong runs one way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

READ_CAPABILITIES = ("research", "analyze", "plan")
WRITE_CAPABILITIES = ("modify", "create_branch", "create_pr", "merge")
ALL_CAPABILITIES = READ_CAPABILITIES + WRITE_CAPABILITIES


class RegistryError(ValueError):
    """The registry file is malformed, or names something that cannot be used."""


@dataclass(frozen=True)
class Capabilities:
    research: bool = True
    analyze: bool = True
    plan: bool = True
    modify: bool = False
    create_branch: bool = False
    create_pr: bool = False
    merge: bool = False

    def allows(self, capability: str) -> bool:
        if capability not in ALL_CAPABILITIES:
            raise RegistryError(
                f"Unknown capability {capability!r}. Expected one of: "
                f"{', '.join(ALL_CAPABILITIES)}"
            )
        return bool(getattr(self, capability))

    @classmethod
    def parse(cls, raw: Any, repo_id: str) -> "Capabilities":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise RegistryError(f"{repo_id}.capabilities must be a mapping")
        unknown = set(raw) - set(ALL_CAPABILITIES)
        if unknown:
            raise RegistryError(
                f"{repo_id}.capabilities has unknown key(s): "
                f"{', '.join(sorted(unknown))}"
            )
        defaults = cls()
        return cls(
            **{
                name: bool(raw.get(name, getattr(defaults, name)))
                for name in ALL_CAPABILITIES
            }
        )


@dataclass(frozen=True)
class Source:
    provider: str = "local"
    url: Optional[str] = None
    default_branch: str = "main"


@dataclass(frozen=True)
class AgentRoles:
    research: List[str] = field(default_factory=list)
    engineering: List[str] = field(default_factory=list)
    implementation: List[str] = field(default_factory=list)

    def permits(self, role: str, agent: str) -> bool:
        """An empty list means the role is unrestricted, not that it is closed.

        Unlike capabilities, this is routing rather than permission -- the
        gateway's tool policy is what actually stops an agent. Defaulting to
        closed here would mean every registry entry had to enumerate agents
        before anything ran.
        """
        configured = getattr(self, role, None)
        if configured is None:
            raise RegistryError(f"Unknown agent role: {role!r}")
        return not configured or agent in configured


@dataclass(frozen=True)
class Schedules:
    repository_scan: str = "nightly"
    research: str = "weekly"
    architecture_review: str = "weekly"


@dataclass(frozen=True)
class Repository:
    id: str
    name: str
    workspace: Path
    source: Source = field(default_factory=Source)
    capabilities: Capabilities = field(default_factory=Capabilities)
    agents: AgentRoles = field(default_factory=AgentRoles)
    schedule: Schedules = field(default_factory=Schedules)
    enabled: bool = True
    tags: List[str] = field(default_factory=list)

    @property
    def default_branch(self) -> str:
        return self.source.default_branch

    def require(self, capability: str) -> None:
        """Raise unless this repository permits `capability`."""
        if not self.capabilities.allows(capability):
            raise RegistryError(
                f"{self.id} does not permit {capability!r}. Enable it in the "
                "repository registry if that is intended."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "workspace": str(self.workspace),
            "default_branch": self.default_branch,
            "enabled": self.enabled,
            "tags": list(self.tags),
            "capabilities": {
                name: self.capabilities.allows(name) for name in ALL_CAPABILITIES
            },
        }
