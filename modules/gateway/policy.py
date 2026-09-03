"""Tool policy: who may call a tool, where, and whether a human must agree.

The Tool Interoperability Standard keeps this separate from the tool contract.
MCP says what a tool is and how to call it; this file says whether a given
agent may call it against a given repository. Neither can answer the other's
question.

The policy fails closed. A tool that is not declared here cannot be called,
even if an MCP server happily advertises it -- which is what makes "every
permanent tool MUST declare its side effect" an enforced rule rather than a
convention.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .contracts import SideEffect

DEFAULT_POLICY_PATH = "config/tool_policy.yaml"

# Reason codes are stable strings: they land in the audit log and get counted,
# so they should not be prose that someone later rewords.
REASON_TOOL_NOT_DECLARED = "tool_not_declared"
REASON_AGENT_NOT_PERMITTED = "agent_not_permitted"
REASON_REPOSITORY_NOT_PERMITTED = "repository_not_permitted"
REASON_DENIED_FOR_REPOSITORY = "tool_denied_for_repository"
REASON_NOT_ALLOWLISTED_FOR_REPOSITORY = "tool_not_allowlisted_for_repository"
REASON_REPOSITORY_REQUIRED = "repository_required"


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool = False
    reason_code: Optional[str] = None
    detail: Optional[str] = None

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class ToolPolicy:
    """Policy for one tool."""

    name: str
    side_effect: SideEffect
    allowed_agents: List[str] = field(default_factory=list)
    repositories: List[str] = field(default_factory=lambda: ["*"])
    requires_approval: bool = False

    def permits_agent(self, agent: str) -> bool:
        return any(
            pattern == "*" or pattern == agent for pattern in self.allowed_agents
        )

    def permits_repository(self, repository_id: Optional[str]) -> bool:
        if any(pattern == "*" for pattern in self.repositories):
            return True
        if repository_id is None:
            return False
        return repository_id in self.repositories


@dataclass(frozen=True)
class RepositoryToolPolicy:
    """A repository's own opinion about which tools may touch it.

    Per the architecture addendum: a sandbox may allow everything, a production
    control plane allows reads and denies pushes. Deny always beats allow.
    """

    repository_id: str
    allow: List[str] = field(default_factory=lambda: ["*"])
    deny: List[str] = field(default_factory=list)

    def evaluate(self, tool_name: str) -> PolicyDecision:
        for pattern in self.deny:
            if fnmatch.fnmatchcase(tool_name, pattern):
                return PolicyDecision(
                    allowed=False,
                    reason_code=REASON_DENIED_FOR_REPOSITORY,
                    detail=(
                        f"{self.repository_id} denies {tool_name} "
                        f"(matched deny pattern {pattern!r})"
                    ),
                )
        for pattern in self.allow:
            if fnmatch.fnmatchcase(tool_name, pattern):
                return PolicyDecision(allowed=True)
        return PolicyDecision(
            allowed=False,
            reason_code=REASON_NOT_ALLOWLISTED_FOR_REPOSITORY,
            detail=f"{self.repository_id} does not allow {tool_name}",
        )


class PolicyError(ValueError):
    """The policy file is malformed."""


@dataclass
class Policy:
    tools: Dict[str, ToolPolicy] = field(default_factory=dict)
    repositories: Dict[str, RepositoryToolPolicy] = field(default_factory=dict)

    def tool(self, name: str) -> Optional[ToolPolicy]:
        return self.tools.get(name)

    def evaluate(
        self,
        tool_name: str,
        agent: str,
        repository_id: Optional[str] = None,
    ) -> PolicyDecision:
        """Decide whether `agent` may call `tool_name` against a repository."""
        tool_policy = self.tools.get(tool_name)
        if tool_policy is None:
            return PolicyDecision(
                allowed=False,
                reason_code=REASON_TOOL_NOT_DECLARED,
                detail=(
                    f"{tool_name} is not declared in the tool policy. Tools must "
                    "be declared before they can be called."
                ),
            )

        if not tool_policy.permits_agent(agent):
            return PolicyDecision(
                allowed=False,
                reason_code=REASON_AGENT_NOT_PERMITTED,
                detail=f"Agent {agent!r} may not call {tool_name}",
            )

        if not tool_policy.permits_repository(repository_id):
            # A tool scoped to named repositories called with no repository at
            # all is a missing argument, not a policy violation; say so.
            reason = (
                REASON_REPOSITORY_REQUIRED
                if repository_id is None
                else REASON_REPOSITORY_NOT_PERMITTED
            )
            return PolicyDecision(
                allowed=False,
                reason_code=reason,
                detail=(
                    f"{tool_name} is restricted to "
                    f"{', '.join(tool_policy.repositories)}; got {repository_id!r}"
                ),
            )

        if repository_id is not None:
            repo_policy = self.repositories.get(repository_id)
            if repo_policy is not None:
                decision = repo_policy.evaluate(tool_name)
                if not decision.allowed:
                    return decision

        return PolicyDecision(
            allowed=True, requires_approval=tool_policy.requires_approval
        )


def _as_list(value: Any, field_name: str, tool: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise PolicyError(f"{tool}.{field_name} must be a string or list of strings")


def parse_policy(data: Any) -> Policy:
    """Build a Policy from already-loaded YAML data."""
    if data is None:
        return Policy()
    if not isinstance(data, dict):
        raise PolicyError("Tool policy must be a mapping at the top level")

    version = data.get("version", 1)
    if version != 1:
        raise PolicyError(f"Unsupported tool policy version: {version}")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise PolicyError("`defaults` must be a mapping")

    default_agents = _as_list(defaults.get("allowed_agents"), "allowed_agents", "defaults")
    default_repos = _as_list(defaults.get("repositories"), "repositories", "defaults") or ["*"]
    default_approval = bool(defaults.get("requires_approval", False))

    tools: Dict[str, ToolPolicy] = {}
    raw_tools = data.get("tools") or {}
    if not isinstance(raw_tools, dict):
        raise PolicyError("`tools` must be a mapping of tool name to policy")

    for name, raw in raw_tools.items():
        raw = raw or {}
        if not isinstance(raw, dict):
            raise PolicyError(f"Policy for {name} must be a mapping")
        if "side_effect" not in raw:
            raise PolicyError(
                f"{name} does not declare a side_effect. Every tool must declare "
                "its impact before it can be called."
            )
        tools[name] = ToolPolicy(
            name=name,
            side_effect=SideEffect.parse(str(raw["side_effect"])),
            allowed_agents=_as_list(raw.get("allowed_agents"), "allowed_agents", name)
            or default_agents,
            repositories=_as_list(raw.get("repositories"), "repositories", name)
            or default_repos,
            requires_approval=bool(raw.get("requires_approval", default_approval)),
        )

    repositories: Dict[str, RepositoryToolPolicy] = {}
    raw_repos = data.get("repositories") or {}
    if not isinstance(raw_repos, dict):
        raise PolicyError("`repositories` must be a mapping of repository id to policy")

    for repo_id, raw in raw_repos.items():
        raw = raw or {}
        if not isinstance(raw, dict):
            raise PolicyError(f"Repository policy for {repo_id} must be a mapping")
        repositories[repo_id] = RepositoryToolPolicy(
            repository_id=repo_id,
            allow=_as_list(raw.get("allow"), "allow", repo_id) or ["*"],
            deny=_as_list(raw.get("deny"), "deny", repo_id),
        )

    return Policy(tools=tools, repositories=repositories)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_policy_path(path: Optional[str] = None) -> Path:
    """Locate the policy file.

    Falls back to the repo-root copy rather than only looking under the
    current directory: the controller, the CLI and the MCP servers are all
    started from different working directories.
    """
    explicit = path or os.getenv("ALENA_TOOL_POLICY")
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_absolute() else Path.cwd() / candidate

    for candidate in (Path.cwd() / DEFAULT_POLICY_PATH, _REPO_ROOT / DEFAULT_POLICY_PATH):
        if candidate.exists():
            return candidate
    return _REPO_ROOT / DEFAULT_POLICY_PATH


def load_policy(path: Optional[str] = None) -> Policy:
    """Read the policy file. A missing file is an error, not an empty policy.

    Silently falling back to an empty policy would deny every tool and look
    like a bug in the gateway; saying the file is missing is more useful.
    """
    resolved = resolve_policy_path(path)
    if not resolved.exists():
        raise PolicyError(f"Tool policy not found at {resolved}")
    return parse_policy(yaml.safe_load(resolved.read_text()))
