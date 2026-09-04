"""The repository registry: where repositories live and what may be done to them."""

from .loader import (
    RepositoryRegistry,
    load_registry,
    parse_registry,
    parse_repository,
    resolve_registry_path,
    workspace_root,
)
from .schema import (
    ALL_CAPABILITIES,
    AgentRoles,
    Capabilities,
    RegistryError,
    Repository,
    Schedules,
    Source,
)

__all__ = [
    "ALL_CAPABILITIES",
    "AgentRoles",
    "Capabilities",
    "RegistryError",
    "Repository",
    "RepositoryRegistry",
    "Schedules",
    "Source",
    "load_registry",
    "parse_registry",
    "parse_repository",
    "resolve_registry_path",
    "workspace_root",
]
