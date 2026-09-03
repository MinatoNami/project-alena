"""Read-only queries over what ALENA knows.

These are the capabilities the MCP server exposes, written as plain functions
with typed inputs and outputs and no MCP imports. That is the discipline that
keeps the server a thin adapter: logic that lives inside an `@mcp.tool()` body
cannot be called from the CLI, a worker, or a unit test, and the "build once,
many consumers" rule in the interoperability standard is broken the moment it
does.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .persistence import (
    latest_scan,
    observations_for,
    recommendations_for,
    scan_history,
)
from .portfolio import analyse, build_graph
from .registry import RegistryError, RepositoryRegistry, load_registry
from .scan import GitRepository
from .text import jaccard

MAX_SEARCH_RESULTS = 200


def _registry(registry: Optional[RepositoryRegistry] = None) -> RepositoryRegistry:
    return registry or load_registry()


def list_repositories(registry: Optional[RepositoryRegistry] = None) -> List[Dict[str, Any]]:
    registry = _registry(registry)
    rows = []
    for repository in registry.all():
        scan = latest_scan(repository.id)
        rows.append(
            {
                **repository.to_dict(),
                "scanned_at": (scan or {}).get("scanned_at"),
                "file_count": (scan or {}).get("file_count"),
                "languages": list((scan or {}).get("languages") or {}),
            }
        )
    return rows


def repository_profile(
    repository_id: str, registry: Optional[RepositoryRegistry] = None
) -> Dict[str, Any]:
    repository = _registry(registry).resolve(repository_id)
    scan = latest_scan(repository_id)
    if scan is None:
        raise RegistryError(
            f"{repository_id} has not been scanned yet. Run: alena-improve scan "
            f"{repository_id}"
        )
    return {**repository.to_dict(), **scan}


def search_repository(
    repository_id: str,
    pattern: str,
    max_results: int = 100,
    registry: Optional[RepositoryRegistry] = None,
) -> List[Dict[str, Any]]:
    """Search a repository's tracked files.

    Tracked-only, via `git grep`, so build output and vendored dependencies are
    skipped without needing to know what they are called. The workspace comes
    from the registry; the caller supplies a pattern, never a path.
    """
    repository = _registry(registry).resolve(repository_id, "analyze")
    if not pattern.strip():
        return []

    git = GitRepository(repository.workspace)
    hits = []
    for line in git.grep([pattern], max_results=min(max_results, MAX_SEARCH_RESULTS)):
        path, _, rest = line.partition(":")
        number, _, text = rest.partition(":")
        hits.append(
            {
                "path": path,
                "line": int(number) if number.isdigit() else 0,
                "text": text.strip()[:300],
            }
        )
    return hits


def repository_todos(repository_id: str) -> List[Dict[str, Any]]:
    return (latest_scan(repository_id) or {}).get("todos") or []


def repository_dependencies(repository_id: str) -> List[Dict[str, Any]]:
    return (latest_scan(repository_id) or {}).get("dependencies") or []


def repository_history(repository_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    return [
        {
            "scanned_at": scan["scanned_at"],
            "head_sha": scan["head_sha"],
            "branch": scan["branch"],
            "file_count": scan["file_count"],
        }
        for scan in scan_history(repository_id, limit)
    ]


def _rank(rows: List[Dict[str, Any]], query: str, fields: tuple) -> List[Dict[str, Any]]:
    """Score rows by word overlap with the query, best first.

    Word overlap rather than embeddings: this has to answer the same way
    whether or not an embedding model happens to be loaded.
    """
    scored = []
    for row in rows:
        haystack = " ".join(str(row.get(field) or "") for field in fields)
        score = jaccard(query, haystack)
        if score > 0:
            scored.append({**row, "relevance": round(score, 4)})
    return sorted(scored, key=lambda r: -r["relevance"])


def search_recommendations(
    query: str,
    repository_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    registry: Optional[RepositoryRegistry] = None,
) -> List[Dict[str, Any]]:
    registry = _registry(registry)
    targets = (
        [registry.resolve(repository_id)] if repository_id else registry.all()
    )

    rows: List[Dict[str, Any]] = []
    for repository in targets:
        for row in recommendations_for(repository.id, status):
            rows.append(
                {
                    "id": row["id"],
                    "repository_id": row["repository_id"],
                    "title": row["title"],
                    "status": row["status"],
                    "score": row["score"],
                    "reason": row["reason"],
                    "estimated_effort": row["estimated_effort"],
                }
            )

    if not query.strip():
        return rows[:limit]
    return _rank(rows, query, ("title", "reason"))[:limit]


def search_memory(
    query: str,
    repository_id: Optional[str] = None,
    limit: int = 20,
    registry: Optional[RepositoryRegistry] = None,
) -> Dict[str, Any]:
    """Search what has been proposed before, decided and undecided.

    The rejected ones are the point: an agent about to propose something can
    find out it was already turned down, and why.
    """
    registry = _registry(registry)
    targets = (
        [registry.resolve(repository_id)] if repository_id else registry.all()
    )

    observations: List[Dict[str, Any]] = []
    for repository in targets:
        for row in observations_for(repository.id, include_duplicates=True):
            observations.append(
                {
                    "id": row["id"],
                    "repository_id": row["repository_id"],
                    "title": row["title"],
                    "duplicate_reason": row["duplicate_reason"],
                }
            )

    return {
        "recommendations": search_recommendations(
            query, repository_id, limit=limit, registry=registry
        ),
        "observations": _rank(observations, query, ("title",))[:limit]
        if query.strip()
        else observations[:limit],
    }


def portfolio_snapshot(
    registry: Optional[RepositoryRegistry] = None,
) -> Dict[str, Any]:
    registry = _registry(registry)
    repositories = registry.all()
    scans = {r.id: latest_scan(r.id) for r in repositories}
    decided = {r.id: recommendations_for(r.id) for r in repositories}

    result = analyse(repositories, scans, decided)
    return {
        "repositories": result["graph"].to_dict()["repositories"],
        "shared": result["shared"],
        "divergence": [item.to_dict() for item in result["divergence"]],
        "findings": [finding.to_dict() for finding in result["findings"]],
    }


def search_capability(
    term: str, registry: Optional[RepositoryRegistry] = None
) -> Dict[str, List[str]]:
    """Which repositories use a technology.

    The question behind the spec's portfolio example: before adding a
    capability, find out whether the portfolio already has one.
    """
    registry = _registry(registry)
    repositories = registry.all()
    graph = build_graph(repositories, {r.id: latest_scan(r.id) for r in repositories})
    return graph.search(term)
