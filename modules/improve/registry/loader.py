"""Load and validate config/repositories.yaml.

Two things this file is strict about.

Secrets: the registry names GitHub repositories, so it is exactly the file
someone will paste a token into. Anything token-shaped is rejected at load
time rather than committed and discovered later.

Workspace containment: every workspace must be absolute, and when
`ALENA_WORKSPACE_ROOT` is set, must sit inside it. The registry is what feeds
the gateway's allowed roots, so a workspace pointing at `/` would quietly
unlock the path guard for every tool.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from .schema import (
    AgentRoles,
    Capabilities,
    Repository,
    RegistryError,
    Schedules,
    Source,
    ID_PATTERN,
)

DEFAULT_REGISTRY_PATH = "config/repositories.yaml"
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Credential shapes that must never appear in a checked-in registry.
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
)
_SECRET_KEYS = {"token", "password", "secret", "api_key", "apikey", "credentials"}


def _scan_for_secrets(node: Any, path: str = "repositories") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in _SECRET_KEYS:
                raise RegistryError(
                    f"{path}.{key} looks like a credential. Keep secrets in the "
                    "environment; the registry is checked in."
                )
            _scan_for_secrets(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _scan_for_secrets(value, f"{path}[{index}]")
    elif isinstance(node, str):
        for pattern in _SECRET_PATTERNS:
            if pattern.search(node):
                raise RegistryError(
                    f"{path} contains what looks like an access token. Keep "
                    "secrets in the environment; the registry is checked in."
                )


def workspace_root() -> Optional[Path]:
    raw = os.getenv("ALENA_WORKSPACE_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _parse_workspace(raw: Any, repo_id: str) -> Path:
    if isinstance(raw, dict):
        raw = raw.get("path")
    if not isinstance(raw, str) or not raw.strip():
        raise RegistryError(f"{repo_id} has no workspace.path")

    resolved = Path(raw).expanduser()
    if not resolved.is_absolute():
        raise RegistryError(
            f"{repo_id}.workspace.path must be absolute; got {raw!r}. A relative "
            "path would resolve differently for the CLI, the controller and the "
            "nightly job."
        )
    resolved = Path(os.path.normpath(str(resolved)))

    root = workspace_root()
    if root is not None and not (
        resolved == root or str(resolved).startswith(str(root) + os.sep)
    ):
        raise RegistryError(
            f"{repo_id}.workspace.path ({resolved}) is outside ALENA_WORKSPACE_ROOT "
            f"({root})"
        )
    return resolved


def _parse_source(raw: Any, repo_id: str) -> Source:
    if raw is None:
        return Source()
    if not isinstance(raw, dict):
        raise RegistryError(f"{repo_id}.source must be a mapping")
    return Source(
        provider=str(raw.get("provider", "local")),
        url=raw.get("url"),
        default_branch=str(raw.get("default_branch", "main")),
    )


def _parse_agents(raw: Any, repo_id: str) -> AgentRoles:
    if raw is None:
        return AgentRoles()
    if not isinstance(raw, dict):
        raise RegistryError(f"{repo_id}.agents must be a mapping")
    unknown = set(raw) - {"research", "engineering", "implementation"}
    if unknown:
        raise RegistryError(
            f"{repo_id}.agents has unknown role(s): {', '.join(sorted(unknown))}"
        )

    def names(key: str) -> List[str]:
        value = raw.get(key) or []
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            raise RegistryError(f"{repo_id}.agents.{key} must be a list")
        return [str(item) for item in value]

    return AgentRoles(
        research=names("research"),
        engineering=names("engineering"),
        implementation=names("implementation"),
    )


def _parse_schedule(raw: Any, repo_id: str) -> Schedules:
    if raw is None:
        return Schedules()
    if not isinstance(raw, dict):
        raise RegistryError(f"{repo_id}.schedule must be a mapping")
    defaults = Schedules()
    return Schedules(
        repository_scan=str(raw.get("repository_scan", defaults.repository_scan)),
        research=str(raw.get("research", defaults.research)),
        architecture_review=str(
            raw.get("architecture_review", defaults.architecture_review)
        ),
    )


def parse_repository(raw: Any) -> Repository:
    if not isinstance(raw, dict):
        raise RegistryError("Each repository entry must be a mapping")

    repo_id = str(raw.get("id", "")).strip()
    if not repo_id:
        raise RegistryError("A repository entry has no id")
    if not ID_PATTERN.match(repo_id):
        raise RegistryError(
            f"Repository id {repo_id!r} must be lowercase and may contain only "
            "letters, digits, dot, dash and underscore -- it is used in file "
            "paths and URIs."
        )

    return Repository(
        id=repo_id,
        name=str(raw.get("name") or repo_id),
        workspace=_parse_workspace(raw.get("workspace"), repo_id),
        source=_parse_source(raw.get("source"), repo_id),
        capabilities=Capabilities.parse(raw.get("capabilities"), repo_id),
        agents=_parse_agents(raw.get("agents"), repo_id),
        schedule=_parse_schedule(raw.get("schedule"), repo_id),
        enabled=bool(raw.get("enabled", True)),
        tags=[str(tag) for tag in (raw.get("tags") or [])],
    )


class RepositoryRegistry:
    """Every run starts by resolving a declared target through here."""

    def __init__(self, repositories: Iterable[Repository]):
        self._repositories: Dict[str, Repository] = {}
        for repository in repositories:
            if repository.id in self._repositories:
                raise RegistryError(f"Duplicate repository id: {repository.id}")
            self._repositories[repository.id] = repository

    def __len__(self) -> int:
        return len(self._repositories)

    def __contains__(self, repository_id: object) -> bool:
        return repository_id in self._repositories

    def ids(self) -> List[str]:
        return sorted(self._repositories)

    def all(self, *, include_disabled: bool = False) -> List[Repository]:
        return [
            repository
            for _, repository in sorted(self._repositories.items())
            if include_disabled or repository.enabled
        ]

    def resolve(self, repository_id: str, capability: Optional[str] = None) -> Repository:
        """Resolve a target, refusing unknown, disabled or unpermitted work."""
        repository = self._repositories.get(repository_id)
        if repository is None:
            known = ", ".join(self.ids()) or "(none)"
            raise RegistryError(
                f"Unknown repository {repository_id!r}. Declared: {known}"
            )
        if not repository.enabled:
            raise RegistryError(f"{repository_id} is disabled in the registry")
        if capability is not None:
            repository.require(capability)
        return repository

    def workspaces(self) -> List[str]:
        """Allowed roots for the gateway's path guard.

        This is the registry's real answer to the question safety.py tried to
        answer with a hardcoded list.
        """
        return [str(repo.workspace) for repo in self.all()]


def resolve_registry_path(path: Optional[str] = None) -> Path:
    explicit = path or os.getenv("ALENA_REPOSITORIES")
    if explicit:
        candidate = Path(explicit)
        return candidate if candidate.is_absolute() else Path.cwd() / candidate
    for candidate in (
        Path.cwd() / DEFAULT_REGISTRY_PATH,
        _REPO_ROOT / DEFAULT_REGISTRY_PATH,
    ):
        if candidate.exists():
            return candidate
    return _REPO_ROOT / DEFAULT_REGISTRY_PATH


def parse_registry(data: Any) -> RepositoryRegistry:
    if data is None:
        return RepositoryRegistry([])
    if not isinstance(data, dict):
        raise RegistryError("The repository registry must be a mapping")

    raw_repositories = data.get("repositories")
    if raw_repositories is None:
        return RepositoryRegistry([])
    if not isinstance(raw_repositories, list):
        raise RegistryError("`repositories` must be a list")

    _scan_for_secrets(raw_repositories)
    return RepositoryRegistry(parse_repository(raw) for raw in raw_repositories)


def load_registry(path: Optional[str] = None) -> RepositoryRegistry:
    resolved = resolve_registry_path(path)
    if not resolved.exists():
        raise RegistryError(
            f"Repository registry not found at {resolved}. Copy "
            "config/repositories.example.yaml and declare your repositories."
        )
    return parse_registry(yaml.safe_load(resolved.read_text()))
