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
# A line of context is cheap; a screenful per hit fills the model's window with
# one search. Three either side is enough to tell a comment from a string.
MAX_CONTEXT_LINES = 10
# A read has to be bounded or one generated file becomes the whole prompt.
MAX_READ_LINES = 400
MAX_LINE_LENGTH = 500


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
    context: int = 0,
    exclude: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search a repository's tracked files.

    Tracked-only, via `git grep`, so build output and vendored dependencies are
    skipped without needing to know what they are called. The workspace comes
    from the registry; the caller supplies a pattern, never a path.

    `context` asks for surrounding lines, and it exists because of a specific
    failure. A bare matching line cannot distinguish a `# FIXME` comment from
    the word FIXME inside a markdown table, a spec bullet or a string literal.
    ALENA's own research agent searched for FIXME, got three hits that were all
    prose or fixtures, and proposed work that did not need doing. Context is
    what makes that judgeable.

    `exclude` drops paths matching a glob -- `Documents/*` when you want code
    rather than the plans that describe it.
    """
    repository = _registry(registry).resolve(repository_id, "analyze")
    if not pattern.strip():
        return []

    git = GitRepository(repository.workspace)
    context = max(0, min(int(context or 0), MAX_CONTEXT_LINES))
    hits = []
    for line in git.grep(
        [pattern],
        max_results=min(max_results, MAX_SEARCH_RESULTS),
        exclude=exclude,
    ):
        path, _, rest = line.partition(":")
        number, _, text = rest.partition(":")
        hit = {
            "path": path,
            "line": int(number) if number.isdigit() else 0,
            "text": text.strip()[:300],
        }
        if context and hit["line"]:
            hit["context"] = _context_lines(
                repository.workspace, path, hit["line"], context
            )
        hits.append(hit)
    return hits


def _context_lines(workspace, path: str, line: int, radius: int) -> List[Dict[str, Any]]:
    """The lines around a hit, numbered, so a caller can see what it sits in."""
    from pathlib import Path

    target = Path(workspace) / path
    try:
        lines = target.read_text(errors="replace").splitlines()
    except OSError:
        return []
    start = max(0, line - 1 - radius)
    end = min(len(lines), line + radius)
    return [
        {"line": index + 1, "text": lines[index][:MAX_LINE_LENGTH]}
        for index in range(start, end)
    ]


def read_repository_file(
    repository_id: str,
    path: str,
    start: int = 1,
    limit: int = 200,
    registry: Optional[RepositoryRegistry] = None,
) -> Dict[str, Any]:
    """Read one tracked file, or a slice of it.

    The gap this closes: an agent could find where something was *mentioned*
    and never open it, so it could not tell a capability that already exists
    from one that does not. Two of the first three findings ALENA's research
    agent produced were rejected as "already implemented", and the reviewer
    established that by reading the file the agent could only grep.

    **Tracked files only, and the registry resolves the workspace.** `git
    ls-files` is the allowlist: it excludes anything ignored -- `.env`, keys,
    build output -- without needing a denylist of secrets to keep current. A
    path that escapes the workspace, or that git does not know about, is
    refused rather than read. That matters more here than elsewhere, because a
    client reaching alena-core talks to it directly with no gateway in between.
    """
    from pathlib import Path

    repository = _registry(registry).resolve(repository_id, "analyze")
    workspace = Path(repository.workspace).resolve()

    requested = (path or "").strip()
    if not requested:
        raise RegistryError("A path is required")

    target = (workspace / requested).resolve()
    try:
        relative = target.relative_to(workspace)
    except ValueError:
        raise RegistryError(
            f"{requested} is outside {repository_id}'s workspace"
        ) from None

    git = GitRepository(workspace)
    if str(relative) not in set(git.tracked_files()):
        raise RegistryError(
            f"{relative} is not a tracked file in {repository_id}. Only files "
            "git knows about can be read, which is what keeps ignored files "
            "-- .env, keys, build output -- out of reach."
        )

    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        raise RegistryError(f"Could not read {relative}: {exc}") from None

    lines = content.splitlines()
    start = max(1, int(start or 1))
    limit = max(1, min(int(limit or 200), MAX_READ_LINES))
    window = lines[start - 1 : start - 1 + limit]

    return {
        "path": str(relative),
        "start": start,
        "lines": len(lines),
        "returned": len(window),
        "truncated": start - 1 + len(window) < len(lines),
        "text": "\n".join(line[:MAX_LINE_LENGTH] for line in window),
    }


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
